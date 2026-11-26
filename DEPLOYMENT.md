# Deployment Information

## Public URL

https://tranvietanh-lab14-production.up.railway.app

## Platform

Railway: project `TranVietAnh-Lab14`, environment `production`, region `sfo`.

| Service | Vai trò |
| --- | --- |
| `TranVietAnh-Lab14` | Agent Part 6 (`06-lab-complete/`), build từ `Dockerfile` (multi-stage, `python:3.11-slim`), uvicorn 2 worker |
| `Redis` | Redis của Railway: state dùng chung cho rate limit và cost guard, agent kết nối qua mạng nội bộ `redis.railway.internal` |

Cấu hình deploy: [`06-lab-complete/railway.toml`](06-lab-complete/railway.toml) (`builder = "DOCKERFILE"`, `healthcheckPath = "/health"`, restart `ON_FAILURE`).

Deploy bằng Railway CLI từ thư mục `06-lab-complete/`:

```bash
railway link                     # chọn project TranVietAnh-Lab14, service TranVietAnh-Lab14
railway add --database redis
railway variable set AGENT_API_KEY=<key>
railway variable set ENVIRONMENT=production
railway variable set 'REDIS_URL=${{Redis.REDIS_URL}}'
railway up
railway domain
```

## Test Commands

Đặt trước: `BASE=https://tranvietanh-lab14-production.up.railway.app`, `AGENT_API_KEY=<key đã đặt trên Railway>`.

### Health Check

```bash
curl https://tranvietanh-lab14-production.up.railway.app/health
# Expected: 200 {"status":"ok","uptime_seconds":...,"environment":"production","timestamp":"..."}
```

### Readiness (Redis đã kết nối)

```bash
curl https://tranvietanh-lab14-production.up.railway.app/ready
# Expected: 200 {"ready":true}
```

### API Test (with authentication)

```bash
# Không có key → 401
curl -X POST https://tranvietanh-lab14-production.up.railway.app/ask \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'

# Có key → 200
curl -X POST https://tranvietanh-lab14-production.up.railway.app/ask \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'
# Expected: 200 {"question":"Hello","answer":"...","usage":{"cost_usd":...,"requests_remaining":...}}
```

### Tự kiểm (CP6), chỉ in mã HTTP

```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

Kết quả đo ngày 2026-11-26:

```text
GET  /health             -> 200
GET  /ready              -> 200
POST /ask (không key)    -> 401
POST /ask (có key)       -> 200
POST /ask (sai key)      -> 401
12 request liên tiếp có key (RATE_LIMIT_PER_MINUTE=10): 200 ×8, 429 ×4   (2 request trước đó trong cùng cửa sổ 60s)
  HTTP/1.1 429 Too Many Requests
  retry-after: 52
  x-ratelimit-limit: 10
  {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":52}}
```

`python check_production_ready.py --public-url https://tranvietanh-lab14-production.up.railway.app` → `✅ Public URL: GET .../health → 200`.

## Environment Variables Set

Đặt trên service `TranVietAnh-Lab14` (tab Variables / `railway variable set`), không có giá trị nào nằm trong code hay git:

| Biến | Giá trị / nguồn |
| --- | --- |
| `AGENT_API_KEY` | Chuỗi ngẫu nhiên 43 ký tự (`secrets.token_urlsafe(32)`), secret |
| `ENVIRONMENT` | `production` (app dừng khi khởi động nếu thiếu `AGENT_API_KEY` ở môi trường này) |
| `REDIS_URL` | Biến tham chiếu `${{Redis.REDIS_URL}}` → `redis://...@redis.railway.internal:6379` |
| `PORT` | Railway tự cấp; `CMD` trong Dockerfile đọc `${PORT:-8000}` |

Dùng giá trị mặc định trong code (không đặt): `RATE_LIMIT_PER_MINUTE=10`, `DAILY_BUDGET_USD=1.0`, `MONTHLY_BUDGET_USD=10.0`, `LOG_LEVEL=INFO`.

## Screenshots

- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png): bản deploy ACTIVE, "Deployment successful", Redis và agent cùng Online
- [Deploy logs](screenshots/running-logs.png): log JSON `event: startup` với `environment: production`, `redis_ok: true`; `/health` 200, `/ready` 200, `/ask` không key 401
- [Test results](screenshots/test.png): 4 lệnh tự kiểm → 200 / 200 / 401 / 200
