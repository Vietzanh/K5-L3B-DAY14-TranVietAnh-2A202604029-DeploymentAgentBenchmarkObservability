"""
Production AI Agent — Part 6 Final Project.

Chạy:   uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
Chấm:   python check_production_ready.py

Thứ tự xử lý POST /ask:
  verify_api_key (401) → check_rate_limit (429) → check_budget (402) → LLM → record_cost
"""
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import redis
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, estimate_tokens, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import r, redis_healthy
from utils.mock_llm import ask as llm_ask


# ──────────────────────────────────────────────────────────
# Structured logging (tiêu chí 10): mỗi dòng log là 1 JSON object
# ──────────────────────────────────────────────────────────
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "lvl": record.levelname,
            "logger": record.name,
        }
        if isinstance(record.msg, dict):        # logger.info({"event": ..., ...})
            entry.update(record.msg)
        else:
            entry["msg"] = record.getMessage()
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


_handler = logging.StreamHandler()
_handler.setFormatter(JsonFormatter())
logging.basicConfig(level=settings.log_level, handlers=[_handler], force=True)
logger = logging.getLogger("agent")

START_TIME = time.time()
_state = {"ready": False}


# ──────────────────────────────────────────────────────────
# Lifecycle + graceful shutdown (tiêu chí 11)
# ──────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info({
        "event": "startup",
        "environment": settings.environment,
        "port": settings.port,
        "rate_limit_per_minute": settings.rate_limit_per_minute,
        "daily_budget_usd": settings.daily_budget_usd,
        "monthly_budget_usd": settings.monthly_budget_usd,
        "api_key_configured": bool(settings.agent_api_key),
        "redis_ok": redis_healthy(),
    })
    if not settings.agent_api_key:
        logger.warning({"event": "config_warning", "detail": "AGENT_API_KEY not set — /ask rejects every request"})
    _state["ready"] = True
    yield
    # Khi nhận SIGTERM, uvicorn tự: ngừng nhận kết nối mới → chờ request đang chạy xong
    # → rồi mới chạy phần dưới đây. Không tự đăng ký signal handler để khỏi ghi đè handler
    # của uvicorn (ghi đè sai thì process không bao giờ tắt).
    _state["ready"] = False
    logger.info({"event": "shutdown", "detail": "in-flight requests finished, closing Redis pool"})
    r.close()


app = FastAPI(title="Production AI Agent", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def access_log(request: Request, call_next):
    """Log JSON cho mỗi request + header X-Request-ID để truy vết."""
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    if request.url.path not in ("/health", "/ready"):   # bỏ log probe để đỡ nhiễu
        logger.info({
            "event": "request",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "ms": round((time.perf_counter() - started) * 1000, 1),
        })
    return response


# ──────────────────────────────────────────────────────────
# Xử lý lỗi: mã lỗi rõ ràng, không lộ stack trace cho client
# ──────────────────────────────────────────────────────────
@app.exception_handler(redis.RedisError)
async def redis_unavailable(request: Request, exc: redis.RedisError):
    # Không kiểm được rate limit / budget thì từ chối (fail closed) thay vì cho qua.
    logger.error({"event": "redis_error", "path": request.url.path, "error": type(exc).__name__})
    return JSONResponse(status_code=503, content={"detail": "Service temporarily unavailable"},
                        headers={"Retry-After": "5"})


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    logger.exception({"event": "unhandled_error", "path": request.url.path})
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ──────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────
class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, max_length=128)


@app.get("/")
def root():
    return {"app": "Production AI Agent", "environment": settings.environment,
            "endpoints": ["GET /health", "GET /ready", "POST /ask"]}


@app.get("/health")
def health():
    """Liveness (tiêu chí 4): process còn chạy là 200. KHÔNG phụ thuộc Redis, để Redis
    gặp sự cố thì platform không restart hàng loạt agent một cách vô ích."""
    return {
        "status": "ok",
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "environment": settings.environment,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready")
def ready():
    """Readiness (tiêu chí 5): 200 khi nhận được traffic; 503 khi đang khởi động / đang tắt
    hoặc Redis không kết nối được (không có Redis thì không kiểm được rate limit, budget)."""
    if not _state["ready"]:
        return JSONResponse(status_code=503, content={"ready": False, "reason": "starting or shutting down"})
    if not redis_healthy():
        return JSONResponse(status_code=503, content={"ready": False, "reason": "redis unavailable"})
    return {"ready": True}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    rate = check_rate_limit(api_key)        # 429 khi vượt RATE_LIMIT_PER_MINUTE
    check_budget()                          # 402 khi hết DAILY / MONTHLY budget

    answer = llm_ask(body.question)

    cost = record_cost(estimate_tokens(body.question), estimate_tokens(answer))
    return {
        "question": body.question,
        "answer": answer,
        "usage": {"cost_usd": round(cost, 8), "requests_remaining": rate["remaining"]},
    }
