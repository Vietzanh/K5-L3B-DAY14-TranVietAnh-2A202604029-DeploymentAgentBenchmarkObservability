"""
Rate limiting (tiêu chí 7).

  • Mỗi API key tối đa RATE_LIMIT_PER_MINUTE request trong 60 giây (sliding window)
  • Vượt giới hạn → HTTP 429 kèm header Retry-After
  • State lưu trong Redis (sorted set) → mọi worker / instance dùng chung,
    vẫn còn sau khi restart agent

Cách làm: mỗi API key có một sorted set `ratelimit:<hash của key>`, mỗi phần tử là
một request đã được chấp nhận, score = thời điểm (ms). Một Lua script chạy NGUYÊN KHỐI
trong Redis: ZREMRANGEBYSCORE (bỏ request cũ hơn 60s) → ZCARD (đếm) → nếu chưa đủ
giới hạn thì ZADD + PEXPIRE. Chạy nguyên khối nên 2 worker gọi cùng lúc cũng không
cùng lọt qua khi chỉ còn 1 chỗ.
"""
import hashlib
import time
import uuid

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_MS = 60_000

_SLIDING_WINDOW_LUA = """
local key    = KEYS[1]
local now    = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit  = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    return {0, count, oldest[2]}
end
redis.call('ZADD', key, now, ARGV[4])
redis.call('PEXPIRE', key, window)
return {1, count + 1, '0'}
"""
_sliding_window = r.register_script(_SLIDING_WINDOW_LUA)


def _bucket_key(api_key: str) -> str:
    # Không lưu API key gốc trong Redis, chỉ lưu hash.
    return "ratelimit:" + hashlib.sha256(api_key.encode()).hexdigest()[:16]


def check_rate_limit(key: str) -> dict:
    """Ghi nhận 1 request của `key`. Vượt giới hạn → raise HTTPException(429)."""
    limit = settings.rate_limit_per_minute
    now_ms = int(time.time() * 1000)
    allowed, count, oldest = _sliding_window(
        keys=[_bucket_key(key)],
        args=[now_ms, WINDOW_MS, limit, f"{now_ms}-{uuid.uuid4().hex[:8]}"],
    )
    if not int(allowed):
        retry_after = max(1, int((float(oldest) + WINDOW_MS - now_ms) / 1000) + 1)
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Rate limit exceeded",
                "limit": limit,
                "window_seconds": WINDOW_MS // 1000,
                "retry_after_seconds": retry_after,
            },
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
            },
        )
    return {"limit": limit, "remaining": max(0, limit - int(count))}
