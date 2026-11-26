"""
Config — 12-Factor: mọi cấu hình đọc từ biến môi trường (tiêu chí 9).

  • Mỗi giá trị đọc từ env, có giá trị mặc định hợp lý khi chạy local.
  • Không hard-code secret: AGENT_API_KEY không có giá trị mặc định.
  • Danh sách đầy đủ các biến nằm trong .env.example.
"""
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

# Chạy local: nạp file .env nếu có. Không ghi đè biến đã được đặt sẵn
# (biến của platform / docker / shell luôn được ưu tiên).
load_dotenv(override=False)


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _env_float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


@dataclass(frozen=True)
class Settings:
    # Server
    port: int = field(default_factory=lambda: _env_int("PORT", 8000))
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())

    # Security — không có default: thiếu key thì /ask từ chối mọi request
    agent_api_key: str = field(default_factory=lambda: os.getenv("AGENT_API_KEY", ""))

    # State dùng chung (rate limit, cost guard)
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0"))

    # Giới hạn
    rate_limit_per_minute: int = field(default_factory=lambda: _env_int("RATE_LIMIT_PER_MINUTE", 10))
    daily_budget_usd: float = field(default_factory=lambda: _env_float("DAILY_BUDGET_USD", 1.0))
    monthly_budget_usd: float = field(default_factory=lambda: _env_float("MONTHLY_BUDGET_USD", 10.0))

    def validate(self) -> "Settings":
        """Fail fast: production mà thiếu API key thì không cho khởi động."""
        if self.environment == "production" and not self.agent_api_key:
            raise RuntimeError("AGENT_API_KEY must be set when ENVIRONMENT=production")
        if self.rate_limit_per_minute <= 0:
            raise RuntimeError("RATE_LIMIT_PER_MINUTE must be > 0")
        return self


settings = Settings().validate()
