# ============================================================
# Production Dockerfile — multi-stage (tiêu chí 1)
#
#   Stage builder : cài dependencies vào /install
#   Stage runtime : python:3.11-slim sạch, chỉ copy package đã cài + code
#                   → không có pip cache / file build, chạy bằng user non-root
#
# Build : docker build -t agent .
# Run   : docker run -p 8000:8000 -e AGENT_API_KEY=... -e REDIS_URL=... agent
# ============================================================

# ── Stage 1: builder ─────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

# Copy requirements TRƯỚC code → layer pip install được cache khi chỉ sửa code.
# Mọi package trong requirements.txt đều có wheel dựng sẵn nên không cần gcc.
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt


# ── Stage 2: runtime ─────────────────────────────────────────
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

# User non-root: lỡ app bị khai thác thì kẻ tấn công không có quyền root trong container
RUN groupadd --system app && useradd --system --gid app --home-dir /app --no-create-home app

WORKDIR /app
COPY --from=builder /install /usr/local
COPY --chown=app:app app/ ./app/
COPY --chown=app:app utils/ ./utils/

USER app
EXPOSE 8000

# Docker tự gọi /health; fail 3 lần liên tiếp → container bị đánh dấu unhealthy
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '8000') + '/health', timeout=3)" || exit 1

# `exec` → uvicorn thay thế sh và là PID 1, nên nhận trực tiếp SIGTERM khi `docker stop`.
# Port lấy từ biến PORT do platform cấp (Railway / Render), mặc định 8000.
# --timeout-graceful-shutdown 8: chờ tối đa 8s cho request đang chạy, < 10s của docker stop.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2 --timeout-graceful-shutdown 8"]
