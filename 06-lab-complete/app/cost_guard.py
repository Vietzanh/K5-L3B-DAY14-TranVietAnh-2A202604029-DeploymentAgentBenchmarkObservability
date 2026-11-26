"""
Cost guard (tiêu chí 8).

  • Cộng dồn chi phí LLM (tính theo token) vào Redis
  • Tổng chi phí đạt DAILY_BUDGET_USD hoặc MONTHLY_BUDGET_USD → HTTP 402

Key Redis:
  cost:day:YYYY-MM-DD   (TTL 2 ngày)  — sang ngày mới thì tên key đổi → tự reset
  cost:month:YYYY-MM    (TTL 32 ngày) — sang tháng mới thì tên key đổi → tự reset
INCRBYFLOAT là lệnh atomic: nhiều worker / instance cộng cùng lúc không mất số.
Ngày / tháng tính theo UTC.
"""
from datetime import datetime, timezone

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

DAY_TTL_SECONDS = 2 * 24 * 3600
MONTH_TTL_SECONDS = 32 * 24 * 3600


def estimate_tokens(text: str) -> int:
    """Ước lượng thô ~4 ký tự / token (mock LLM không trả số token thật)."""
    return max(1, len(text) // 4)


def _keys() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return f"cost:day:{now:%Y-%m-%d}", f"cost:month:{now:%Y-%m}"


def get_spend() -> dict:
    day_key, month_key = _keys()
    day, month = r.mget(day_key, month_key)
    return {"day_usd": float(day or 0), "month_usd": float(month or 0)}


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    spend = get_spend()
    for period, used, budget in (
        ("daily", spend["day_usd"], settings.daily_budget_usd),
        ("monthly", spend["month_usd"], settings.monthly_budget_usd),
    ):
        if used >= budget:
            raise HTTPException(
                status_code=402,
                detail={
                    "error": f"{period.capitalize()} budget exceeded",
                    "used_usd": round(used, 6),
                    "budget_usd": budget,
                    "resets": "00:00 UTC" if period == "daily" else "first day of next month (UTC)",
                },
            )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    cost = input_tokens / 1000 * PRICE_INPUT_PER_1K + output_tokens / 1000 * PRICE_OUTPUT_PER_1K
    day_key, month_key = _keys()
    pipe = r.pipeline()
    pipe.incrbyfloat(day_key, cost)
    pipe.expire(day_key, DAY_TTL_SECONDS)
    pipe.incrbyfloat(month_key, cost)
    pipe.expire(month_key, MONTH_TTL_SECONDS)
    pipe.execute()
    return cost
