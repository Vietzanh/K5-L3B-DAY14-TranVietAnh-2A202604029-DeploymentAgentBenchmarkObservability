"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

  • Đọc REDIS_URL từ config.
  • redis.from_url() chỉ tạo connection pool, KHÔNG kết nối ngay → app vẫn khởi động
    được khi Redis chưa sẵn sàng (container chạy một mình, Redis khởi động chậm...).
  • Timeout ngắn để /ready và /ask không bị treo khi Redis mất kết nối.
  • redis_healthy() dùng cho GET /ready.
"""
import redis

from app.config import settings

r = redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
    health_check_interval=30,
)


def redis_healthy() -> bool:
    try:
        return bool(r.ping())
    except redis.RedisError:
        return False
