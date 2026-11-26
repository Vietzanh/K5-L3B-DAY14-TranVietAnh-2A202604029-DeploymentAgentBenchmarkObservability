# Day 14 Lab - Mission Answers

<!--
Hướng dẫn điền (các comment này không hiển thị khi xem Markdown, có thể xoá khi nộp):
- Tiêu chí từng Part: CHECKPOINTS.md (mục "Sản phẩm") và RUBRIC.md.
- Mọi con số (MB, % chênh lệch, mã HTTP...) phải lấy từ lệnh bạn tự chạy (RULES.md mục 1).
- Che token/API key thật khi dán output (RULES.md mục 5).
- Không ghi email, số điện thoại.
-->

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found

File: `01-localhost-vs-production/develop/app.py`

1. **Hardcode secret trong code** (dòng 17–18): `OPENAI_API_KEY = "sk-hardcoded-..."`, `DATABASE_URL = "postgresql://admin:password123@..."`. Push lên GitHub là lộ key và mật khẩu DB; xoá file sau đó cũng không đủ vì secret còn trong lịch sử git.
2. **Log ra secret** (dòng 34): `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")`. Ai đọc được log (dashboard cloud, log aggregator) đều thấy key. Khi chạy thử, log server in ra đúng `[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this`.
3. **Không có config management** (dòng 21–22): `DEBUG = True`, `MAX_TOKENS = 500` ghi cứng. Muốn đổi giữa dev/production phải sửa code và deploy lại, dễ quên tắt `DEBUG` khi lên production.
4. **Dùng `print()` thay vì logging** (dòng 33, 34, 38): không có level (INFO/ERROR), không có timestamp, không có cấu trúc, nên không lọc hay tìm kiếm được trong log aggregator.
5. **Không có health check endpoint** (dòng 42–43): gọi `GET /health` trả **404**. Platform không biết agent còn sống hay đã treo để restart, cũng không biết bản mới đã sẵn sàng nhận traffic chưa.
6. **Port cố định** (dòng 52): `port=8000`. Railway/Render cấp port qua biến môi trường `PORT` (khi deploy Railway, app được cấp port 8080), nên app nghe 8000 sẽ không nhận được request.
7. **Bind vào `localhost`** (dòng 51): `host="localhost"` chỉ nhận kết nối từ trong cùng máy/container. Chạy trong Docker hoặc trên cloud thì request từ bên ngoài không vào được; cần `0.0.0.0`.
8. **`reload=True` cứng** (dòng 53): chế độ auto-reload chỉ dành cho lúc code, chạy ở production tốn tài nguyên và không cần thiết.
9. **Không xử lý shutdown**: không có `lifespan` hay handler cho `SIGTERM`, nên khi platform tắt container (deploy bản mới, scale down) request đang xử lý có thể bị cắt ngang.

### Exercise 1.2: Run basic version

Bản develop nhận `question` qua **query string** (`def ask_agent(question: str)`), không phải JSON body.

> Ghi chú: lúc chạy, cổng 8000 đang bị bản production chiếm nên bản develop được chạy bằng `python -m uvicorn app:app --port 8001` trong `develop/`. Code `app.py` giữ nguyên.

```text
> curl.exe -i -X POST "http://localhost:8001/ask?question=Hello"
HTTP/1.1 200 OK
server: uvicorn
content-type: application/json

{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}

> curl.exe -i http://localhost:8001/health
HTTP/1.1 404 Not Found

{"detail":"Not Found"}

> curl.exe -i -X POST http://localhost:8001/ask -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 422 Unprocessable Content

{"detail":[{"type":"missing","loc":["query","question"],"msg":"Field required","input":null}]}
```

Log phía server (thấy rõ anti-pattern 2 và 4: `print` và lộ key):

```text
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
[DEBUG] Response: Đây là câu trả lời từ AI agent (mock). ...
INFO:     127.0.0.1:53744 - "POST /ask?question=Hello HTTP/1.1" 200 OK
INFO:     127.0.0.1:53746 - "GET /health HTTP/1.1" 404 Not Found
```

**Quan sát:** app chạy và trả lời được, nhưng chưa production-ready: không có health check, in secret ra log, chỉ nghe `127.0.0.1` trên port cứng.

Bản production (`01-localhost-vs-production/production`, chạy `python app.py`, port 8000):

```text
> curl.exe -i http://localhost:8000/health
HTTP/1.1 200 OK

{"status":"ok","uptime_seconds":1021.8,"version":"1.0.0","environment":"development","timestamp":"2026-11-26T08:45:08.818062+00:00"}

> curl.exe -i http://localhost:8000/ready
HTTP/1.1 200 OK

{"ready":true}

> curl.exe -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 200 OK

{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","model":"gpt-4o-mini"}
```

### Exercise 1.3: Comparison table

| Feature      | Develop                                                                              | Production                                                                                                                                                                     | Why Important?                                                                                                                  |
| ------------ | ------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------- |
| Config       | Ghi cứng trong code: `DEBUG = True`, `MAX_TOKENS = 500` (dòng 21–22)                 | Gom vào `config.py`, mọi giá trị đọc từ env var có default: `os.getenv("DEBUG", "false")`, `os.getenv("MAX_TOKENS", "500")`                                                    | Cùng một code chạy được ở dev/staging/production; đổi cấu hình không cần sửa code, build và deploy lại (12-Factor: Config)      |
| Secrets      | `OPENAI_API_KEY`, `DATABASE_URL` hardcode (dòng 17–18) và còn bị in ra log (dòng 34) | Đọc từ env var (`config.py:27, 32`); log chỉ ghi `question_length`, `client_ip`, không ghi secret; `validate()` báo lỗi nếu thiếu `AGENT_API_KEY` khi `ENVIRONMENT=production` | Secret trong code hoặc trong log sẽ bị lộ qua git và log aggregator; fail fast giúp phát hiện thiếu cấu hình ngay lúc khởi động |
| Health check | Không có, `GET /health` → 404                                                        | `GET /health` (liveness, trả uptime), `GET /ready` (readiness, 503 khi chưa sẵn sàng), `GET /metrics`                                                                          | Platform dùng `/health` để tự restart khi agent treo; load balancer dùng `/ready` để chỉ gửi traffic vào instance đã sẵn sàng   |
| Logging      | `print(f"[DEBUG] ...")`                                                              | `logging` với format JSON (`{"time":...,"level":...,"msg":...}`), level theo `DEBUG`                                                                                           | Log có cấu trúc thì parse, lọc và tìm kiếm được trong Datadog/Loki; có level để tắt log debug ở production                      |
| Shutdown     | Đột ngột, không có handler                                                           | Graceful: `lifespan` đặt `is_ready = False` và chờ request đang xử lý khi tắt; `signal.signal(SIGTERM, handle_sigterm)`                                                        | Platform gửi SIGTERM mỗi lần deploy hoặc scale down; tắt an toàn để không cắt ngang request của người dùng                      |
| Host / Port  | `host="localhost"`, `port=8000` cứng                                                 | `HOST` mặc định `0.0.0.0`, `PORT` đọc từ env var                                                                                                                               | Container và cloud cần nhận kết nối từ bên ngoài; Railway/Render chỉ định port qua `PORT`                                       |
| Reload       | `reload=True` luôn bật                                                               | `reload=settings.debug`, chỉ bật khi `DEBUG=true`                                                                                                                              | Auto-reload là tính năng cho lúc code, ở production chỉ tốn tài nguyên                                                          |

**Tự kiểm tra (CP1):** develop dùng `port=8000` cứng ở `develop/app.py:52`; production đã sửa bằng `port: int = ... int(os.getenv("PORT", "8000"))` ở `production/config.py:18` và truyền vào `uvicorn.run(port=settings.port)` ở `production/app.py:197`.

## Part 2: Docker

### Exercise 2.1: Dockerfile questions

<!-- 02-docker/develop/Dockerfile -->

1. **Base image:** `python:3.11` (dòng 8), bản Python đầy đủ dựa trên Debian, có sẵn compiler, header và nhiều công cụ hệ thống, nên rất nặng (đo được ở 2.2: 1.67 GB khi giải nén).
2. **Working directory:** `/app` (`WORKDIR /app`, dòng 11). Mọi lệnh `COPY`, `RUN`, `CMD` sau đó chạy trong `/app`; thư mục được tạo tự động nếu chưa có.
3. **Tại sao COPY requirements.txt trước:** để tận dụng **Docker layer cache**. Mỗi lệnh trong Dockerfile tạo một layer, và Docker chỉ build lại một layer khi input của nó đổi (kéo theo mọi layer sau nó). Copy `requirements.txt` rồi `pip install` trước, copy code sau: khi chỉ sửa code thì layer `pip install` vẫn dùng cache, không phải tải và cài lại dependency. Nếu `COPY . .` đứng trước, mỗi lần sửa một dòng code đều phải cài lại toàn bộ package. Thấy rõ khi build lại: các bước `[3/7] COPY requirements.txt` và `[4/7] RUN pip install` đều báo `CACHED`.
4. **CMD vs ENTRYPOINT:**
   - `CMD` là lệnh **mặc định**, dễ bị ghi đè: `docker run my-agent:develop python -c "print(1)"` sẽ chạy lệnh mới thay cho `CMD ["python", "app.py"]`.
   - `ENTRYPOINT` là chương trình **cố định** của container: tham số truyền vào `docker run` được **nối thêm** vào sau, không thay thế nó (muốn đổi phải dùng `--entrypoint`).
   - Dùng chung: `ENTRYPOINT` là chương trình, `CMD` là tham số mặc định. Ví dụ `ENTRYPOINT ["uvicorn"]` + `CMD ["app:app", "--port", "8000"]`.
   - Dockerfile này chỉ dùng `CMD ["python", "app.py"]` (dạng exec, dòng 30), để dễ ghi đè khi debug.

### Exercise 2.2: Build and run

Build từ thư mục gốc repo (Dockerfile dùng đường dẫn tính từ gốc, ví dụ `COPY 02-docker/develop/app.py .`):

```text
> docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
...
#13 naming to docker.io/library/my-agent:develop done
#13 DONE 0.1s

> docker run -d --name agent-dev -p 8000:8000 my-agent:develop
> docker ps --filter name=agent-dev
IMAGE              STATUS         PORTS
my-agent:develop   Up 4 seconds   0.0.0.0:8000->8000/tcp, [::]:8000->8000/tcp
```

Gọi container (`02-docker/develop/app.py` nhận `question` qua query string):

```text
> curl.exe -i http://localhost:8000/health
HTTP/1.1 200 OK
server: uvicorn
content-type: application/json

{"status":"ok","uptime_seconds":3.4,"container":true}

> curl.exe -i -X POST "http://localhost:8000/ask?question=What%20is%20Docker"
HTTP/1.1 200 OK
server: uvicorn
content-type: application/json

{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

Log của container:

```text
> docker logs agent-dev
INFO:     Started server process [1]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     172.17.0.1:34366 - "GET /health HTTP/1.1" 200 OK
INFO:     172.17.0.1:34380 - "POST /ask?question=What%20is%20Docker HTTP/1.1" 200 OK
```

Kích thước image:

```text
> docker images my-agent:develop
IMAGE              ID             DISK USAGE   CONTENT SIZE
my-agent:develop   67fa4e52979b       1.67GB          426MB
```

- `DISK USAGE` (1.67 GB) là dung lượng khi giải nén trên ổ đĩa; `CONTENT SIZE` (426 MB) là dung lượng nén, tức lượng dữ liệu phải tải khi pull/push. So sánh với bản production ở 2.3 dùng cùng một cột.
- Process trong container là PID 1 và nghe ở `0.0.0.0:8000`; request đi vào từ `172.17.0.1` (gateway của mạng bridge Docker), chứng tỏ app phải bind `0.0.0.0` chứ không phải `localhost`.

### Exercise 2.3: Multi-stage build & image size comparison

File: `02-docker/production/Dockerfile`

- **Stage 1 (`builder`, dòng 16–29):** từ `python:3.11-slim`, cài công cụ build (`gcc`, `libpq-dev`) bằng `apt-get`, rồi `pip install --user -r requirements.txt` để toàn bộ package nằm gọn trong `/root/.local`. Stage này chỉ dùng để build, không được deploy.
- **Stage 2 (`runtime`, dòng 36–72):** bắt đầu lại từ một `python:3.11-slim` sạch, tạo user không phải root `appuser`, chỉ copy sang những thứ cần để **chạy**: thư mục package đã cài (`COPY --from=builder /root/.local /home/appuser/.local`), `main.py` và `utils/mock_llm.py`. Sau đó chuyển sang `USER appuser`, khai báo `HEALTHCHECK` gọi `/health`, và chạy `uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2`.
- **Tại sao image nhỏ hơn:**
  1. Base image là `python:3.11-slim` thay vì `python:3.11` đầy đủ (bỏ compiler, header, nhiều công cụ hệ thống của Debian).
  2. `gcc`, `libpq-dev`, apt cache và các file trung gian của quá trình build chỉ nằm ở stage `builder`; image cuối chỉ chứa các layer của stage `runtime`, nên những thứ đó bị bỏ lại hoàn toàn.
  3. `pip install --no-cache-dir` không giữ cache tải package trong image.
- Ngoài kích thước, bản production còn an toàn hơn: chạy bằng `appuser` thay vì root, và có `HEALTHCHECK` để Docker biết container còn khoẻ không.

Build (từ thư mục gốc repo):

```text
> docker build -f 02-docker/production/Dockerfile -t my-agent:advanced .
#8  [builder 3/5] RUN apt-get update && apt-get install -y gcc libpq-dev ...   DONE 13.6s
#12 [builder 5/5] RUN pip install --no-cache-dir --user -r requirements.txt    DONE 9.4s
#13 [runtime 4/8] COPY --from=builder /root/.local /home/appuser/.local         DONE 0.1s
#17 [runtime 8/8] RUN chown -R appuser:appuser /app                             DONE 0.2s
#18 naming to docker.io/library/my-agent:advanced done
```

```text
> docker images my-agent
IMAGE               ID             DISK USAGE   CONTENT SIZE
my-agent:advanced   1a3a3d9fc71c        240MB         57.4MB
my-agent:develop    67fa4e52979b       1.67GB          426MB
```

| Image                                        | Disk usage (giải nén) | Content size (nén) |
| -------------------------------------------- | --------------------: | -----------------: |
| Develop (`python:3.11`, single-stage)        |               1.67 GB |             426 MB |
| Production (`python:3.11-slim`, multi-stage) |                240 MB |            57.4 MB |
| **Chênh lệch**                               |      **giảm ≈ 85.6%** |   **giảm ≈ 86.5%** |

- Develop: 1.67 GB disk usage / 426 MB content size
- Production: 240 MB disk usage / 57.4 MB content size
- Difference: production nhỏ hơn develop **≈ 85.6%** theo disk usage, `(1670 − 240) / 1670`; **≈ 86.5%** theo content size, `(426.3 − 57.4) / 426.3` (số byte chính xác từ `docker image inspect --format "{{.Size}}"`: 426 320 031 và 57 409 106).

### Exercise 2.4: Docker Compose stack

<!-- Sơ đồ các service, cách chúng giao tiếp, và kết quả test qua Nginx. -->

File: `02-docker/production/docker-compose.yml`, `02-docker/production/nginx/nginx.conf`

```text
                        Máy host (Windows)
                               │
                 HTTP  localhost:80  (khi chạy thử: 8080)
                               │
┌──────────────────────────────┼─────────────────── network "internal" (bridge) ┐
│                              ▼                                                │
│                    ┌───────────────────┐                                      │
│                    │  nginx            │  nginx:alpine                        │
│                    │  reverse proxy    │  - rate limit 10 r/s (burst 20) → 429│
│                    │  cổng 80 / 443    │  - thêm security headers             │
│                    └─────────┬─────────┘                                      │
│                              │ proxy_pass http://agent:8000                   │
│                              ▼                                                │
│                    ┌───────────────────┐                                      │
│                    │  agent            │  build từ 02-docker/production/      │
│                    │  FastAPI, 2 worker│  Dockerfile (target: runtime)        │
│                    │  cổng 8000        │  KHÔNG mở cổng ra host               │
│                    └────┬─────────┬────┘                                      │
│     REDIS_URL           │         │          QDRANT_URL                       │
│  redis://redis:6379/0   │         │   http://qdrant:6333                      │
│                         ▼         ▼                                           │
│              ┌────────────────┐  ┌─────────────────┐                          │
│              │ redis          │  │ qdrant          │                          │
│              │ redis:7-alpine │  │ v1.9.0          │                          │
│              │ cache/session  │  │ vector DB       │                          │
│              │ vol redis_data │  │ vol qdrant_data │                          │
│              └────────────────┘  └─────────────────┘                          │
└───────────────────────────────────────────────────────────────────────────────┘
```

- **Services được start (4):** `redis`, `qdrant`, `agent`, `nginx`. Thứ tự khởi động theo `depends_on`: redis và qdrant phải **healthy** (`redis-cli ping`, kiểm tra TCP 6333) thì agent mới start; nginx start sau agent.
- **Cách các service giao tiếp:**
  - Tất cả nằm chung network bridge `internal`, gọi nhau bằng **tên service** nhờ DNS nội bộ của Docker (`agent:8000`, `redis:6379`, `qdrant:6333`), không cần biết IP.
  - Chỉ **nginx** mở cổng ra host. Agent, redis, qdrant chỉ mở cổng trong network nội bộ, nên từ host gọi thẳng `localhost:8000` không vào được (đo được: `curl` trả `000`, không kết nối được).
  - Client → nginx (cổng 80) → `upstream agent_backend` (`agent:8000`) → agent đọc `REDIS_URL`, `QDRANT_URL` từ biến môi trường.
  - Dữ liệu của redis và qdrant lưu trong named volume (`redis_data`, `qdrant_data`), không mất khi container bị xoá và tạo lại.
  - Ghi chú: `main.py` của bài này hiện chưa thực sự kết nối redis/qdrant, chỉ nhận URL qua env; hai service này có mặt để minh hoạ một stack đầy đủ.

**Cách chạy thử:** trên máy có một web server trong WSL đang chiếm cổng 80 của host, nên khi test, cổng của nginx được map sang **8080** bằng một file override nằm ngoài repo (`ports: !override ["8080:80"]`, chạy bằng `docker compose -f docker-compose.yml -f <override> ...`). `docker-compose.yml` trong repo giữ nguyên. Cũng phải tạo file trống `.env.local` (đã có trong `.gitignore`) vì compose khai báo `env_file: .env.local`.

```text
> docker compose -p k5-day14-docker -f docker-compose.yml -f <override> up -d --build
 Container k5-day14-docker-qdrant-1 Healthy
 Container k5-day14-docker-redis-1 Healthy
 Container k5-day14-docker-agent-1 Started
 Container k5-day14-docker-nginx-1 Started

> docker compose -p k5-day14-docker ps
SERVICE   IMAGE                   STATUS                    PORTS
agent     k5-day14-docker-agent   Up 20 seconds (healthy)   8000/tcp
nginx     nginx:alpine            Up 20 seconds             0.0.0.0:8080->80/tcp, [::]:8080->80/tcp
qdrant    qdrant/qdrant:v1.9.0    Up 30 seconds (healthy)   6333-6334/tcp
redis     redis:7-alpine          Up 30 seconds (healthy)   6379/tcp

> docker network inspect k5-day14-docker_internal
k5-day14-docker-qdrant-1 172.18.0.2/16
k5-day14-docker-redis-1  172.18.0.3/16
k5-day14-docker-agent-1  172.18.0.4/16
k5-day14-docker-nginx-1  172.18.0.5/16
```

Test qua Nginx (header `Server: nginx` và các security header chứng tỏ request đi qua nginx):

```text
> curl.exe -i http://localhost:8080/health
HTTP/1.1 200 OK
Server: nginx
Content-Type: application/json
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"status":"ok","uptime_seconds":19.1,"version":"2.0.0","timestamp":"2026-11-26T09:40:57.920838"}

> curl.exe -i http://localhost:8080/ready
HTTP/1.1 200 OK
Server: nginx

{"ready":true}

> curl.exe -i -X POST http://localhost:8080/ask -H "Content-Type: application/json" -d '{"question": "Explain microservices"}'
HTTP/1.1 200 OK
Server: nginx
Content-Type: application/json
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}

> curl.exe -s -o NUL -w "%{http_code}" http://localhost:8000/health    # gọi thẳng agent, bỏ qua nginx
000
```

Log của agent: request đến từ `172.18.0.5` (IP của nginx), không phải từ host; 2 worker (process 8 và 9) cùng khởi động; log ở dạng JSON:

```text
agent-1  | {"time":"2026-11-26 09:40:38,775","level":"INFO","msg":"Starting agent..."}
agent-1  | {"time":"2026-11-26 09:40:38,876","level":"INFO","msg":"Agent ready"}
agent-1  | INFO:     127.0.0.1:58528 - "GET /health HTTP/1.1" 200 OK        ← HEALTHCHECK của Docker, chạy trong container
agent-1  | INFO:     172.18.0.5:42934 - "GET /health HTTP/1.1" 200 OK
agent-1  | INFO:     172.18.0.5:42934 - "GET /ready HTTP/1.1" 200 OK
agent-1  | INFO:     172.18.0.5:42934 - "POST /ask HTTP/1.1" 200 OK
nginx-1  | 172.18.0.1 - - [26/Nov/2026:09:40:57 +0000] "GET /ready HTTP/1.1" 200 14 "-" "curl/8.22.0"
nginx-1  | 172.18.0.1 - - [26/Nov/2026:09:40:58 +0000] "POST /ask HTTP/1.1" 200 95 "-" "curl/8.22.0"
```

(Nginx không ghi log cho `/health` vì cấu hình `access_log off` ở `location /health`.) Xong thì tắt stack bằng `docker compose -p k5-day14-docker down`.

## Part 3: Cloud Deployment

<!-- Deploy thư mục 06-lab-complete/, không deploy app mẫu 03-cloud-deployment/ (CHECKPOINTS.md CP6). -->

### Exercise 3.1 / 3.2: Deployment (Railway hoặc Render)

- Platform: **Railway** (Exercise 3.1), deploy agent Part 6 trong `06-lab-complete/` (không phải app mẫu `03-cloud-deployment/`)
- URL: **https://tranvietanh-lab14-production.up.railway.app**
- Chi tiết deploy, biến môi trường, lệnh test: [DEPLOYMENT.md](DEPLOYMENT.md)
- Screenshot: [dashboard](screenshots/dashboard.png), [running](screenshots/running.png), [deploy logs](screenshots/running-logs.png), [test](screenshots/test.png)

**Các bước đã làm** (Railway CLI 5.75, trong `06-lab-complete/`):

1. `railway link` vào project `TranVietAnh-Lab14`, service `TranVietAnh-Lab14` (thay app mẫu đã deploy thử ở phần 03).
2. `railway add --database redis` → tạo service `Redis` trong cùng project.
3. Đặt biến cho service agent: `AGENT_API_KEY` (chuỗi ngẫu nhiên), `ENVIRONMENT=production`, `REDIS_URL=${{Redis.REDIS_URL}}` (biến tham chiếu, trỏ tới `redis.railway.internal` qua mạng nội bộ). `PORT` do Railway cấp.
4. `railway up` → Railway build bằng `Dockerfile` (theo `railway.toml`: `builder = "DOCKERFILE"`), healthcheck `/health`.

**Output 4 lệnh tự kiểm (CP6):**

```text
GET  /health            -> 200
GET  /ready             -> 200
POST /ask (không key)   -> 401
POST /ask (có key)      -> 200
```

```text
health: {"status":"ok","uptime_seconds":26.9,"environment":"production","timestamp":"2026-11-26T15:10:44.331732+00:00"}
ready : {"ready":true}
ask   : {"question":"What is deployment?","answer":"Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được.","usage":{"cost_usd":1.2e-05,"requests_remaining":8}}
```

Rate limit trên production (`RATE_LIMIT_PER_MINUTE=10`, state trong Redis của Railway):

```text
12 requests: 200 200 200 200 200 200 200 200 429 429 429 429
HTTP/1.1 429 Too Many Requests
retry-after: 52
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":52}}
```

`python check_production_ready.py --public-url https://tranvietanh-lab14-production.up.railway.app` → `✅ Public URL: GET https://tranvietanh-lab14-production.up.railway.app/health → 200`.

**Sự cố gặp khi deploy và cách xử lý:**
- Lần deploy đầu, `/ask` có key trả **500**. Log Railway: `TypeError: comparing strings with non-ASCII characters is not supported` ở `hmac.compare_digest`. Nguyên nhân: khi pipe key vào `railway variable set --stdin` từ PowerShell 5.1, PowerShell chèn ký tự BOM (U+FEFF) vào đầu, nên `AGENT_API_KEY` trên Railway dài 44 ký tự thay vì 43. Sửa: đặt lại biến bằng tham số `AGENT_API_KEY=<key>` (kiểm lại: 43 ký tự, 0 ký tự non-ASCII, khớp chính xác).
- Sự cố này lộ ra một lỗi trong code: header `X-API-Key` chứa ký tự non-ASCII làm app trả 500 thay vì 401. Đã sửa `06-lab-complete/app/auth.py` để so sánh dạng bytes (`hmac.compare_digest(api_key.encode(), expected.encode())`), chạy lại `check_production_ready.py` vẫn `PASS 12/12`, deploy lại; header non-ASCII giờ trả 401.

### Nền tảng còn lại: so sánh `railway.toml` với `render.yaml`

So sánh `03-cloud-deployment/railway/railway.toml` (và `06-lab-complete/railway.toml`) với `03-cloud-deployment/render/render.yaml`:

| Khía cạnh | railway.toml | render.yaml | Vì sao khác |
| --------- | ------------ | ----------- | ----------- |
| Định dạng, phạm vi | TOML, mô tả **một service**: cách build (`[build]`) và cách chạy (`[deploy]`) | YAML Blueprint, mô tả **cả hạ tầng**: danh sách `services:` gồm web service **và** Redis | Railway coi file config là "config-as-code" cho từng service, còn project/database tạo bằng CLI hoặc dashboard. Render Blueprint là Infrastructure as Code: một file dựng toàn bộ stack |
| Cách build | `builder = "NIXPACKS"`/`"RAILPACK"` (tự nhận Python) hoặc `"DOCKERFILE"` (bản Part 6) | `runtime: python` + `buildCommand: pip install -r requirements.txt` (hoặc `runtime: docker`) | Railway mặc định tự đoán cách build; Render yêu cầu khai báo rõ runtime và lệnh build |
| Lệnh chạy, port | `startCommand = "uvicorn app:app --host 0.0.0.0 --port $PORT"`; bản Part 6 bỏ `startCommand`, dùng `CMD` của Dockerfile đọc `${PORT}` | `startCommand: uvicorn app:app --host 0.0.0.0 --port $PORT` | Giống nhau: cả hai platform đều cấp port qua biến `PORT`, app phải đọc biến này |
| Health check | `healthcheckPath = "/health"`, `healthcheckTimeout` | `healthCheckPath: /health` | Cùng mục đích (chỉ chuyển traffic sang bản deploy mới khi `/health` trả 200), khác cách viết hoa tên khoá |
| Restart khi crash | `restartPolicyType = "ON_FAILURE"`, `restartPolicyMaxRetries = 3` | Không khai báo, Render tự restart | Railway cho chỉnh chính sách restart trong file; Render quản lý mặc định |
| Biến môi trường, secret | **Không có** trong file; đặt bằng `railway variables --set ...` hoặc tab Variables | Khai báo ngay trong `envVars:`: giá trị thường (`ENVIRONMENT=production`), `sync: false` (secret nhập tay trên dashboard), `generateValue: true` (Render tự sinh `AGENT_API_KEY` ngẫu nhiên) | Railway tách hẳn secret ra khỏi file; Render liệt kê **tên** biến trong file để Blueprint biết cần biến nào, nhưng giá trị secret vẫn không nằm trong git |
| Redis / database | Không khai báo; tạo bằng `railway add --database redis`, nối bằng biến tham chiếu `REDIS_URL=${{Redis.REDIS_URL}}` | Khai báo service `type: redis` (`agent-cache`, `plan: free`, `maxmemoryPolicy: allkeys-lru`) trong cùng file | Hệ quả của khác biệt "một service" và "cả hạ tầng" ở dòng đầu |
| Region, gói | Không có (chọn trên dashboard) | `region: singapore`, `plan: free` | Render đưa cả lựa chọn hạ tầng vào file |
| Cách deploy | `railway up` từ máy (upload thư mục hiện tại), hoặc nối GitHub | Push lên GitHub → New → Blueprint; `autoDeploy: true` tự deploy mỗi lần push | Railway thiên về CLI, deploy nhanh từ local; Render thiên về GitOps, repo là nguồn sự thật |

**Tóm lại:** `railway.toml` chỉ nói "service này build và chạy thế nào", phần còn lại (Redis, biến, domain) làm bằng CLI/dashboard. `render.yaml` mô tả cả hệ thống (web + Redis + tên biến cần có) trong một file nằm trong git, nên dựng lại môi trường giống hệt dễ hơn, đổi lại phải viết nhiều hơn và deploy phải qua GitHub. Điểm chung quan trọng: cả hai đều đọc port từ `$PORT`, kiểm `/health`, và không chứa giá trị secret.

### Exercise 3.3: Cloud Run CI/CD pipeline

Đọc `03-cloud-deployment/production-cloud-run/cloudbuild.yaml` và `service.yaml`:

1. **Trigger:** push lên nhánh `main` kích hoạt Google Cloud Build chạy `cloudbuild.yaml` (hoặc chạy tay bằng `gcloud builds submit`). Các bước nối tiếp nhau bằng `waitFor`, bước nào lỗi thì dừng, không deploy.
2. **Test → Build:** bước `test` chạy `pytest tests/` trong image `python:3.11-slim`; qua test mới sang bước `build` dựng Docker image, gắn 2 tag `ai-agent:$COMMIT_SHA` (truy được đúng commit, rollback được) và `ai-agent:latest`, dùng `--cache-from latest` để tái sử dụng layer.
3. **Push:** đẩy cả 2 tag lên Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
4. **Deploy:** `gcloud run deploy ai-agent` với image `:$COMMIT_SHA`, region `asia-southeast1`, public (`--allow-unauthenticated`), 1–10 instance (`min-instances=1` để tránh cold start), 512Mi RAM / 1 CPU, `ENVIRONMENT=production`, còn secret lấy từ **Secret Manager** (`--set-secrets`), không nằm trong code.
5. **`service.yaml`** mô tả cùng service dưới dạng khai báo (Knative, áp dụng bằng `gcloud run services replace`): autoscale 1–10 instance, tối đa 80 request đồng thời mỗi instance, timeout 60s, `livenessProbe` gọi `/health` và `startupProbe` gọi `/ready`; `AGENT_API_KEY` và `OPENAI_API_KEY` lấy từ Secret Manager qua `secretKeyRef`.

Ghi chú: thư mục mẫu không có `tests/` nên bước `test` sẽ lỗi nếu chạy nguyên trạng; và `$COMMIT_SHA` chỉ có giá trị khi build được kích hoạt bởi trigger từ git (chạy `gcloud builds submit` bằng tay thì phải tự truyền tag).

## Part 4: API Security

### Exercise 4.1: API Key authentication

File: `04-api-gateway/develop/app.py`

- **API key được check ở đâu:**
  - Key đúng được đọc từ biến môi trường ở dòng 35: `API_KEY = os.getenv("AGENT_API_KEY", "demo-key-change-in-production")`.
  - `APIKeyHeader(name="X-API-Key", auto_error=False)` (dòng 36) lấy giá trị header `X-API-Key` của request.
  - Hàm `verify_api_key` (dòng 39–54) so sánh header với `API_KEY`. Hàm này được gắn vào endpoint bằng dependency injection: `_key: str = Depends(verify_api_key)` ở `/ask` (dòng 70). Request chỉ vào được thân hàm `ask_agent` khi `verify_api_key` không raise lỗi.
  - `/` và `/health` không gắn dependency nên vẫn public (platform cần gọi `/health` mà không có key).
- **Điều gì xảy ra nếu sai key:**
  - Không gửi header → **401 Unauthorized**, `"Missing API key. Include header: X-API-Key: <your-key>"` (dòng 44–48).
  - Gửi key sai → **403 Forbidden**, `"Invalid API key."` (dòng 49–53).
  - Ý nghĩa: 401 = "chưa xác thực, hãy gửi thông tin đăng nhập"; 403 = "đã gửi nhưng không được phép".
- **Làm sao rotate key:**
  - Vì key nằm trong biến môi trường chứ không trong code, rotate chỉ cần: tạo key mới (ví dụ `python -c "import secrets; print(secrets.token_urlsafe(32))"`), đặt lại `AGENT_API_KEY` trên nền tảng (Railway Variables, `railway variables set ...`), restart/redeploy, rồi gửi key mới cho client. Không phải sửa code hay build lại image.
  - Hạn chế của code hiện tại: chỉ so với **một** key, nên lúc đổi key mọi client cầm key cũ bị 403 ngay. Muốn rotate không gián đoạn thì cho phép nhiều key cùng lúc (ví dụ `AGENT_API_KEYS=new,old`, kiểm `api_key in keys`), đợi client chuyển hết sang key mới rồi mới gỡ key cũ.
  - Lưu ý thêm: dòng 91 `print(f"API Key: {API_KEY}")` in key ra log khi khởi động, chính là anti-pattern "log ra secret" ở Part 1.

Chạy bằng `$env:AGENT_API_KEY = "secret-key-123"; python app.py` trong `04-api-gateway/develop` (README, lưu ý số 6).

```text
> curl.exe -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 401 Unauthorized
server: uvicorn
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}
```

```text
> curl.exe -i -X POST http://localhost:8000/ask -H "X-API-Key: wrong-key" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 403 Forbidden
server: uvicorn
content-type: application/json

{"detail":"Invalid API key."}
```

```text
> curl.exe -i -X POST http://localhost:8000/ask -H "X-API-Key: secret-key-123" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 200 OK
server: uvicorn
content-type: application/json

{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

```text
> curl.exe -i http://localhost:8000/health        # public, không cần key
HTTP/1.1 200 OK

{"status":"ok"}
```

### Exercise 4.2: JWT authentication

File: `04-api-gateway/production/auth.py`, `04-api-gateway/production/app.py`. Endpoint lấy token là `POST /auth/token`, tài khoản `student` / `demo123` (README, lưu ý số 6; `CODE_LAB.md` ghi `/token` và `admin`/`secret` là không đúng với code).

**JWT flow:**

1. Client gửi `username`/`password` tới `POST /auth/token`. `authenticate_user` (auth.py:70–75) so với `DEMO_USERS`; sai → **401** `"Invalid credentials"`.
2. Đúng thì `create_token` (auth.py:35–43) tạo payload `{sub, role, iat, exp}` (hết hạn sau 60 phút) và **ký** bằng `JWT_SECRET` với thuật toán HS256.
3. Client gửi token trong header `Authorization: Bearer <token>` ở mọi request tiếp theo.
4. `verify_token` (auth.py:46–67) được gắn vào `/ask` bằng `Depends`: kiểm chữ ký và hạn dùng, rồi lấy `username`, `role` ngay từ payload, **không cần tra database** (stateless). Thiếu header → **401**; token hết hạn → **401** `"Token expired"`; token sai/giả → **403** `"Invalid token."`.
5. `role` trong token dùng để chọn rate limiter (user 10 req/phút, admin 100 req/phút) ở app.py:141.

Payload của JWT chỉ được **mã hoá base64, không bị mã hoá bí mật**: ai cầm token cũng đọc được nội dung (giải mã thử token vừa lấy: header `{"alg":"HS256","typ":"JWT"}`, payload `{"sub":"student","role":"user","iat":1795688426,"exp":1795692026}`, `exp − iat = 3600` giây). Cái bảo vệ là **chữ ký**: sửa payload (ví dụ đổi `role` thành `admin`) thì chữ ký không còn khớp và server trả 403. Vì vậy không đặt thông tin bí mật vào payload, và `JWT_SECRET` phải được giữ kín.

Lấy token (token đã được che):

```text
> curl.exe -i -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username": "student", "password": "wrong"}'
HTTP/1.1 401 Unauthorized

{"detail":"Invalid credentials"}

> curl.exe -i -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username": "student", "password": "demo123"}'
HTTP/1.1 200 OK
server: uvicorn
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"access_token":"eyJhbGciOi...***","token_type":"bearer","expires_in_minutes":60,"hint":"Include in header: Authorization: Bearer eyJhbGciOi...***..."}
```

Gọi `/ask`:

```text
> curl.exe -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question": "Explain JWT"}'
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer

{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

> curl.exe -i -X POST http://localhost:8000/ask -H "Authorization: Bearer abc.def.ghi" -H "Content-Type: application/json" -d '{"question": "Explain JWT"}'
HTTP/1.1 403 Forbidden

{"detail":"Invalid token."}

> curl.exe -i -X POST http://localhost:8000/ask -H "Authorization: Bearer eyJhbGciOi...***" -H "Content-Type: application/json" -d '{"question": "Explain JWT"}'
HTTP/1.1 200 OK
server: uvicorn
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"question":"Explain JWT","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","usage":{"requests_remaining":9,"budget_remaining_usd":1.9e-05}}
```

Log server:

```text
INFO:     127.0.0.1:54656 - "POST /auth/token HTTP/1.1" 401 Unauthorized
INFO:     127.0.0.1:54658 - "POST /auth/token HTTP/1.1" 200 OK
INFO:     127.0.0.1:54660 - "POST /ask HTTP/1.1" 401 Unauthorized
INFO:     127.0.0.1:54662 - "POST /ask HTTP/1.1" 403 Forbidden
INFO:     127.0.0.1:54664 - "POST /ask HTTP/1.1" 200 OK
INFO:cost_guard:Usage: user=student req=1 cost=$0.0000/1.0
```

Quan sát:

- Bản production thêm các security header (`x-frame-options: DENY`, `x-content-type-options: nosniff`...) vào mọi response, kể cả response lỗi.
- `requests_remaining: 9` cho thấy request này đã bị rate limiter (10 req/phút) tính vào.
- Trường `budget_remaining_usd` thực ra đang trả về **số tiền đã dùng** (`usage.total_cost_usd` ở app.py), không phải số còn lại: tên trường bị đặt sai trong code mẫu. Số tiền còn lại xem ở `GET /me/usage` (`budget_remaining_usd`).

### Exercise 4.3: Rate limiting

File: `04-api-gateway/production/rate_limiter.py`

- **Algorithm: Sliding window log.** Mỗi user có một `deque` lưu timestamp của các request được chấp nhận (`self._windows[user_id]`). Mỗi lần `check()`: bỏ các timestamp cũ hơn 60 giây ở đầu deque (dòng 39–40), nếu số còn lại `>= max_requests` thì raise **429** kèm `retry_after` = lúc timestamp cũ nhất ra khỏi cửa sổ (dòng 45–62); nếu không thì thêm timestamp hiện tại (dòng 65). Khác với fixed window (đếm theo phút đồng hồ, có thể bị dồn 2× request quanh ranh giới phút), cửa sổ ở đây trượt theo thời gian thực nên luôn đúng "tối đa 10 request trong 60 giây bất kỳ".
- **Limit:** `rate_limiter_user = RateLimiter(max_requests=10, window_seconds=60)` → **10 request/phút** cho role `user`; `rate_limiter_admin = RateLimiter(max_requests=100, window_seconds=60)` → **100 request/phút** cho role `admin` (dòng 86–87).
- **Cách bypass limit cho admin:** không tắt hẳn rate limit mà cho admin một **tier riêng, nới hơn**. Ở `app.py:141`: `limiter = rate_limiter_admin if role == "admin" else rate_limiter_user`; `role` lấy từ JWT đã được server ký, nên client không tự nâng quyền được. Muốn bỏ hẳn giới hạn cho admin thì có thể bỏ qua `limiter.check()` khi `role == "admin"`, nhưng giữ một giới hạn cao vẫn an toàn hơn (phòng token admin bị lộ hoặc script admin chạy lỗi).
- Response có header chuẩn: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`, `Retry-After`, để client biết khi nào được gọi lại.
- Hạn chế: state nằm trong RAM của process, nên chạy nhiều instance thì mỗi instance đếm riêng (3 instance → thực tế 30 req/phút), restart là mất. Production cần lưu trong Redis (Part 6).

Vòng lặp 20 request bằng token `student` (PowerShell; token đã che):

```text
> 1..20 | ForEach-Object { curl.exe -s -w "|%{http_code}" -X POST http://localhost:8000/ask -H "Authorization: Bearer eyJhbGciOi...***" -H "Content-Type: application/json" -d "{`"question`": `"Test $_`"}" }
Request  1 -> 200  remaining=9
Request  2 -> 200  remaining=8
Request  3 -> 200  remaining=7
Request  4 -> 200  remaining=6
Request  5 -> 200  remaining=5
Request  6 -> 200  remaining=4
Request  7 -> 200  remaining=3
Request  8 -> 200  remaining=2
Request  9 -> 200  remaining=1
Request 10 -> 200  remaining=0
Request 11 -> 429  {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":58}}
Request 12 -> 429  {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":58}}
Request 13 -> 429  ...
...
Request 20 -> 429  {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":58}}
```

Một response 429 đầy đủ:

```text
> curl.exe -i -X POST http://localhost:8000/ask -H "Authorization: Bearer eyJhbGciOi...***" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 429 Too Many Requests
server: uvicorn
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795689496
retry-after: 58
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":58}}
```

Admin tier: lấy token `teacher` / `teach456` (role `admin`), gửi 15 request liên tiếp, không request nào bị chặn:

```text
teacher (admin): 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200
```

Usage sau vòng lặp (`GET /me/usage` của `student`): chỉ 10 request được tính tiền, 10 request bị 429 không gọi LLM nên không tốn chi phí, vì rate limit được kiểm **trước** cost guard trong `app.py`:

```text
{"user_id":"student","date":"2026-11-26","requests":10,"input_tokens":40,"output_tokens":292,"cost_usd":0.000181,"budget_usd":1.0,"budget_remaining_usd":0.999819,"budget_used_pct":0.0}
```

`GET /admin/stats` với token `student` → `403 {"detail":"Admin only"}`; với token `teacher` → `{"total_users":"N/A (in-memory demo)","global_cost_usd":0.00046...,"global_budget_usd":10.0}`.

### Exercise 4.4: Cost guard implementation

**Vì sao cần cost guard khi đã có rate limit:** rate limit chỉ giới hạn **tốc độ** (10 req/phút). Một user vẫn có thể gọi đều 10 req/phút suốt cả tháng, hoặc gửi prompt rất dài khiến mỗi request tốn nhiều token. Cost guard giới hạn **tiền**, thứ rate limit không bảo vệ được. Hai lớp chặn hai rủi ro khác nhau nên cần cả hai.

**Cách bản mẫu `04-api-gateway/production/cost_guard.py` hoạt động:**

1. **Tính chi phí theo token** với giá GPT-4o-mini: `$0.00015 / 1K input tokens`, `$0.0006 / 1K output tokens` (dòng 20–21). Bản mock ước lượng token bằng `số từ × 2` (app.py).
2. **Hai mức ngân sách** (dòng 128): `$1/ngày` mỗi user và `$10/ngày` toàn hệ thống.
3. **`check_budget()` chạy trước khi gọi LLM** (dòng 60–91):
   - Tổng chi phí toàn hệ thống `>= $10` → **503** (dịch vụ tạm ngừng, bảo vệ hoá đơn của cả công ty).
   - Chi phí của user hôm nay `>= $1` → **402 Payment Required**, kèm `used_usd`, `budget_usd`, `resets_at`.
   - Dùng `>= 80%` ngân sách → ghi log `WARNING` để cảnh báo sớm.
4. **`record_usage()` chạy sau khi gọi LLM** (dòng 93–110): cộng token thực tế vào bản ghi của user và vào tổng toàn hệ thống.
5. **Reset theo ngày:** mỗi `UsageRecord` gắn với ngày `%Y-%m-%d`; sang ngày mới thì `_get_record()` tạo bản ghi mới.

Không thể chạm ngân sách $1 bằng vài request (10 request chỉ tốn $0.000181), nên logic được kiểm bằng cách gọi trực tiếp class `CostGuard` của repo với ngân sách rất nhỏ (`daily_budget_usd=0.0005`, `global_daily_budget_usd=0.001`), mỗi request 200 input + 200 output token ≈ $0.00015 (code trong repo giữ nguyên):

```text
student req 1: OK   used=$0.000150 / $0.0005
student req 2: OK   used=$0.000300 / $0.0005
student req 3: OK   used=$0.000450 / $0.0005
WARNING:cost_guard:User student at 90% budget
student req 4: OK   used=$0.000600 / $0.0005
student req 5: 402 {'error': 'Daily budget exceeded', 'used_usd': 0.0006, 'budget_usd': 0.0005, 'resets_at': 'midnight UTC'}
user1: OK   global=$0.000750 / $0.001
user2: OK   global=$0.000900 / $0.001
user3: OK   global=$0.001050 / $0.001
CRITICAL:cost_guard:GLOBAL BUDGET EXCEEDED: $0.0010
user4: 503 Service temporarily unavailable due to budget limits. Try again tomorrow.
user5: 503 Service temporarily unavailable due to budget limits. Try again tomorrow.
```

**Hạn chế của bản mẫu:**

- `check_budget()` chỉ so **chi phí đã dùng** với ngân sách, không cộng chi phí của request sắp gọi, nên request cuối vẫn lọt và vượt ngân sách (ở trên: request 4 đưa student lên $0.0006 > $0.0005, user3 đưa toàn hệ thống lên $0.00105 > $0.001).
- State nằm trong RAM: restart là mất, chạy nhiều instance thì mỗi instance đếm một ngân sách riêng (3 instance → user tiêu được gấp 3).

**Cách làm theo đề ($10/tháng mỗi user, lưu trong Redis):**

```python
import os
from datetime import datetime, timezone
import redis

MONTHLY_BUDGET_USD = 10.0
r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)

def check_budget(user_id: str, estimated_cost: float) -> bool:
    month_key = datetime.now(timezone.utc).strftime("%Y-%m")
    key = f"budget:{user_id}:{month_key}"          # vd: budget:student:2026-11
    current = float(r.get(key) or 0)
    if current + estimated_cost > MONTHLY_BUDGET_USD:
        return False                                 # caller trả 402
    r.incrbyfloat(key, estimated_cost)
    r.expire(key, 32 * 24 * 3600)                    # 32 ngày
    return True
```

- **Key theo tháng** `budget:{user_id}:{YYYY-MM}`: sang tháng mới tên key đổi (`2026-11` → `2026-12`) nên chi phí **tự reset về 0** mà không cần cron job.
- **Kiểm trước khi cộng** `current + estimated_cost > 10`: chặn ngay request sẽ làm vượt ngân sách, khắc phục hạn chế đầu tiên của bản mẫu.
- **`INCRBYFLOAT`** là lệnh atomic trong Redis: nhiều instance cùng cộng vào một key không bị mất số.
- **`EXPIRE` 32 ngày**: key của tháng cũ tự xoá, Redis không phình mãi.
- **State nằm trong Redis** dùng chung cho mọi instance và không mất khi restart agent, khắc phục hạn chế thứ hai.

Chạy thử hàm trên với một container Redis tạm (`docker run -d --rm -p 6390:6379 redis:7-alpine`), ngân sách $10:

```text
call 1: estimated=$4.0  -> ALLOW   stored=$4.00
call 2: estimated=$4.0  -> ALLOW   stored=$8.00
call 3: estimated=$1.5  -> ALLOW   stored=$9.50
call 4: estimated=$0.6  -> BLOCK (402)   stored=$9.50
call 5: estimated=$0.5  -> ALLOW   stored=$10.00
redis key: budget:student:2026-11 | TTL (s): 2764800
other user: ALLOW
```

- Call 4 bị chặn vì $9.50 + $0.60 > $10, và **không** bị cộng vào; call 5 ($0.50) vẫn vừa đủ, chạm đúng $10.
- TTL 2 764 800 giây = 32 ngày. User khác (`teacher`) có key riêng nên không bị ảnh hưởng.
- Còn một điểm chưa hoàn hảo: `GET` rồi mới `INCRBYFLOAT` là **hai lệnh riêng**, nên hai request đồng thời có thể cùng đọc $9.50 và cùng được cho qua. Muốn chặt chẽ tuyệt đối thì gộp "kiểm + cộng" vào một Lua script (`EVAL`) để Redis chạy nguyên khối, hoặc `INCRBYFLOAT` trước rồi trừ lại nếu vượt.

## Part 5: Scaling & Reliability

### Exercise 5.1: Health checks

File: `05-scaling-reliability/develop/app.py`. Hai endpoint đã có sẵn trong code mẫu; phần này đọc, chạy và giải thích.

```python
@app.get("/health")                      # dòng 104
def health():
    # trả uptime, version, environment, timestamp
    # + checks["memory"] (psutil): "degraded" nếu RAM >= 90%
    return {"status": overall_status, "uptime_seconds": ..., "checks": checks}

@app.get("/ready")                       # dòng 147
def ready():
    if not _is_ready:                    # False khi đang khởi động hoặc đang tắt
        raise HTTPException(503, "Agent not ready. Check back in a few seconds.")
    return {"ready": True, "in_flight_requests": _in_flight_requests}
```

| | `/health` (liveness) | `/ready` (readiness) |
|---|---|---|
| Câu hỏi | "Process còn sống không?" | "Có nên gửi traffic vào instance này lúc này không?" |
| Ai gọi | Platform / orchestrator (Docker `HEALTHCHECK`, Railway `healthcheckPath`, K8s liveness probe) | Load balancer / K8s readiness probe |
| Khi fail | Platform **restart** container | Instance **tạm bị loại khỏi load balancer**, không restart |
| Khi nào fail | Process treo, deadlock, hết RAM | Đang khởi động (chưa load xong model/kết nối DB), đang shutdown, dependency (Redis, DB) chưa sẵn sàng |
| Nên kiểm gì | Nhẹ, chỉ chính process. **Không** kiểm dependency bên ngoài: Redis chết mà `/health` fail thì platform restart hàng loạt agent, nhưng restart không sửa được Redis | Các dependency cần để phục vụ request |

Nếu gộp hai cái làm một: lúc agent đang khởi động hoặc Redis tạm mất kết nối, platform sẽ restart liên tục (restart loop) thay vì chỉ chờ.

Chạy `python app.py` trong `05-scaling-reliability/develop`:

```text
INFO     Agent starting up...
INFO     Loading model and checking dependencies...
INFO     ✅ Agent is ready!
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000

> curl.exe -i http://localhost:8000/health
HTTP/1.1 200 OK

{"status":"ok","uptime_seconds":3.0,"version":"1.0.0","environment":"development","timestamp":"2026-11-26T13:22:29.160159+00:00","checks":{"memory":{"status":"ok","used_percent":87.2}}}

> curl.exe -i http://localhost:8000/ready
HTTP/1.1 200 OK

{"ready":true,"in_flight_requests":1}
```

- `in_flight_requests` là `1` vì middleware `track_requests` đếm cả chính request `/ready` đang chạy.
- `/ready` chỉ trả 200 sau khi `lifespan` đặt `_is_ready = True` (sau bước "Loading model..."); trong lúc shutdown, `_is_ready` về `False` nên `/ready` trả 503 và `/ask` cũng trả 503.

### Exercise 5.2: Graceful shutdown

File: `05-scaling-reliability/develop/app.py`. Logic đã có sẵn trong code mẫu:

```python
# lifespan, phần sau yield (dòng 54–66)
_is_ready = False                          # 1. /ready → 503, LB ngừng gửi request mới
while _in_flight_requests > 0 and elapsed < 30:
    time.sleep(1)                          # 2. chờ request đang xử lý (tối đa 30s)
logger.info("✅ Shutdown complete")         # 3. đóng kết nối, thoát

signal.signal(signal.SIGTERM, handle_sigterm)          # dòng 186: log khi nhận SIGTERM
uvicorn.run(app, ..., timeout_graceful_shutdown=30)    # dòng 198
```

Khi nhận **SIGTERM**, uvicorn: (1) ngừng nhận kết nối mới, (2) chờ các request đang chạy xong (tối đa `timeout_graceful_shutdown` = 30 giây), (3) chạy phần shutdown của `lifespan`, (4) thoát. **SIGKILL** thì không bắt được: process chết ngay, request đang chạy bị cắt.

**Cách test:** lệnh `kill -TERM $PID` trong `CODE_LAB.md` không dùng được trên Windows (Windows không có SIGTERM, `taskkill /F` giết ngay). Vì vậy app được chạy trong container Linux và dùng `docker stop` (gửi SIGTERM) / `docker kill` (gửi SIGKILL). `/ask` của mock chỉ mất 0.1 giây, quá nhanh để kịp tắt giữa chừng, nên thêm một endpoint `/slow` mất 5 giây bằng một file wrapper nằm ngoài repo; file này `from app import app` (dùng nguyên `lifespan`, middleware, signal handler của `develop/app.py`, mount read-only vào container) rồi chạy `uvicorn.run(app, ..., timeout_graceful_shutdown=30)` giống `app.py`. Kịch bản: gửi `POST /slow`, 1 giây sau tắt container.

**A. SIGTERM, cho đủ thời gian (`docker stop -t 30`):** request hoàn thành.

```text
> docker stop -t 30 p52        (mất 4.5s)
client nhận: {"result":"done after 5s"}  HTTP=200  TIME=4.98s
exit code container: 0

13:24:27,386 INFO slow request started (5s)
INFO:     Shutting down
INFO:     Waiting for connections to close. (CTRL+C to force quit)
13:24:32,278 INFO slow request finished
INFO:     172.17.0.1:38800 - "POST /slow HTTP/1.1" 200 OK
INFO:     Waiting for application shutdown.
13:24:32,351 INFO 🔄 Graceful shutdown initiated...
13:24:32,351 INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
INFO:     Finished server process [1]
```

**B. SIGTERM nhưng hết thời gian chờ (`docker stop`, mặc định trên máy này = 1 giây):** request bị cắt.

```text
> docker stop p52              (mất 1.5s)
client nhận: HTTP=000 (mất kết nối)
exit code container: 137

13:24:37,726 INFO slow request started (5s)
INFO:     Shutting down
INFO:     Waiting for connections to close. (CTRL+C to force quit)
(container bị SIGKILL sau 1 giây, không có dòng "slow request finished")
```

**C. SIGKILL ngay (`docker kill`):** request bị cắt, không có dòng log shutdown nào.

```text
> docker kill p52              (mất 0.4s)
client nhận: HTTP=000 (mất kết nối)
exit code container: 137

13:24:45,095 INFO slow request started (5s)
(hết log)
```

**Quan sát:**
- **Request có hoàn thành không?** Có, khi process nhận SIGTERM và được cho đủ thời gian (A): uvicorn ngừng nhận request mới, chờ request 5 giây chạy xong, trả 200, rồi mới chạy shutdown và thoát với exit 0. Không, khi bị SIGKILL (C) hoặc khi platform không chờ đủ lâu (B): client mất kết nối, exit 137 (= 128 + 9, tức bị SIGKILL).
- Graceful shutdown cần **cả hai phía**: app phải xử lý SIGTERM, và platform phải cho đủ thời gian trước khi gửi SIGKILL. Trên máy này container được tạo với `StopTimeout = 1` giây (`docker inspect --format "{{.Config.StopTimeout}}"`), nên `docker stop` mặc định chỉ chờ 1 giây; thực tế cần đặt thời gian chờ ≥ request dài nhất, ví dụ `docker stop -t 30`, `stop_grace_period: 30s` trong docker-compose, `terminationGracePeriodSeconds` trên Kubernetes.
- Ở A, dòng `Waiting for N in-flight requests...` của `lifespan` không xuất hiện: uvicorn đã tự chờ request xong ở bước "Waiting for connections to close" **trước** khi gọi phần shutdown của `lifespan`, nên lúc đó `_in_flight_requests` đã về 0.

### Exercise 5.3: Stateless design

File: `05-scaling-reliability/production/app.py`

**Anti-pattern (stateful):** lưu state trong biến Python, ví dụ `conversation_history = {}`. Biến này nằm trong RAM của **một process**. Khi chạy 3 instance sau load balancer:
- Mỗi instance có RAM riêng, không thấy dữ liệu của instance khác. Lượt 1 vào instance A (lưu ở A), lượt 2 vào B (B không biết lượt 1).
- Instance restart/crash/redeploy hoặc bị scale down là mất dữ liệu.
- Muốn chạy đúng thì phải ép user luôn vào cùng một instance (sticky session), mất tác dụng cân bằng tải và vẫn mất dữ liệu khi instance đó chết.

**Cách làm đúng (stateless):** agent không giữ state; mọi state nằm ở một kho chung bên ngoài là **Redis**:
- `save_session()` / `load_session()` (dòng 59–73): lưu session dưới key `session:{session_id}` bằng `SETEX` với TTL 1 giờ.
- `append_to_history()` (dòng 76–90): đọc session từ Redis, thêm message, giữ tối đa 20 message, ghi lại vào Redis.
- `POST /chat` nhận `session_id` từ client; client chỉ cần gửi lại `session_id`, bất kỳ instance nào cũng load được lịch sử.
- Response có `served_by: INSTANCE_ID` để thấy instance nào xử lý; `storage` cho biết đang dùng `redis` hay `in-memory`.
- Không có Redis thì app tự rơi về `_memory_store` (dict trong RAM) và in cảnh báo `⚠️ Redis not available — using in-memory store (not scalable!)`.

**Chứng minh state trong RAM hỏng khi có 3 instance:** dừng Redis (`docker compose -p k5-day14-scaling stop redis`), restart 3 agent để chúng chuyển sang in-memory, rồi gửi 6 lượt cùng một `session_id` qua nginx:

```text
agent-1  | ⚠️  Redis not available — using in-memory store (not scalable!)
agent-2  | ⚠️  Redis not available — using in-memory store (not scalable!)
agent-3  | ⚠️  Redis not available — using in-memory store (not scalable!)

turn 1 -> served_by=instance-e66020  storage=in-memory
turn 2 -> served_by=instance-b678e1  storage=in-memory
turn 3 -> served_by=instance-6ad39e  storage=in-memory
turn 4 -> served_by=instance-e66020  storage=in-memory
turn 5 -> served_by=instance-b678e1  storage=in-memory
turn 6 -> served_by=instance-6ad39e  storage=in-memory

GET /chat/{session_id}/history, gọi 3 lần (đúng ra: 6 lượt × 2 = 12 tin nhắn)
history: count=4  user turns có trong instance này: Turn 1, Turn 4
history: count=4  user turns có trong instance này: Turn 2, Turn 5
history: count=4  user turns có trong instance này: Turn 3, Turn 6
```

Mỗi instance chỉ giữ 1/3 cuộc hội thoại, và kết quả `GET history` thay đổi tuỳ request rơi vào instance nào. So với Exercise 5.5 (có Redis) history luôn đủ. Sau thí nghiệm, Redis được bật lại và cả 3 agent báo `Storage: Redis ✅`.

### Exercise 5.4: Load balancing

File: `05-scaling-reliability/production/docker-compose.yml`, `nginx.conf`. Theo README (lưu ý số 7): cổng **8080**, endpoint **`POST /chat`**; phải tạo file trống `.env.local` (trong `.gitignore`) vì compose khai báo `env_file: .env.local`.

```text
> docker compose -p k5-day14-scaling up -d --build --scale agent=3
 Container k5-day14-scaling-redis-1 Healthy
 Container k5-day14-scaling-agent-1 Started
 Container k5-day14-scaling-agent-3 Started
 Container k5-day14-scaling-agent-2 Started
 Container k5-day14-scaling-nginx-1 Started

> docker compose -p k5-day14-scaling ps
NAME                       STATUS                    PORTS
k5-day14-scaling-agent-1   Up 9 seconds (healthy)    8000/tcp
k5-day14-scaling-agent-2   Up 8 seconds (healthy)    8000/tcp
k5-day14-scaling-agent-3   Up 8 seconds (healthy)    8000/tcp
k5-day14-scaling-nginx-1   Up 8 seconds              0.0.0.0:8080->80/tcp
k5-day14-scaling-redis-1   Up 19 seconds (healthy)   6379/tcp
```

3 instance, mỗi cái có IP và `INSTANCE_ID` riêng:

```text
k5-day14-scaling-agent-1  ip=172.18.0.3  instance-3f043b
k5-day14-scaling-agent-2  ip=172.18.0.5  instance-300b25
k5-day14-scaling-agent-3  ip=172.18.0.4  instance-5c2fc1
```

10 request qua nginx (`served_by` lấy từ body, `upstream` lấy từ header `X-Served-By` mà nginx thêm vào):

```text
Request  1 -> served_by=instance-300b25  upstream=172.18.0.5:8000  storage=redis
Request  2 -> served_by=instance-3f043b  upstream=172.18.0.3:8000  storage=redis
Request  3 -> served_by=instance-5c2fc1  upstream=172.18.0.4:8000  storage=redis
Request  4 -> served_by=instance-300b25  upstream=172.18.0.5:8000  storage=redis
Request  5 -> served_by=instance-3f043b  upstream=172.18.0.3:8000  storage=redis
Request  6 -> served_by=instance-5c2fc1  upstream=172.18.0.4:8000  storage=redis
Request  7 -> served_by=instance-300b25  upstream=172.18.0.5:8000  storage=redis
Request  8 -> served_by=instance-3f043b  upstream=172.18.0.3:8000  storage=redis
Request  9 -> served_by=instance-5c2fc1  upstream=172.18.0.4:8000  storage=redis
Request 10 -> served_by=instance-300b25  upstream=172.18.0.5:8000  storage=redis
```

`docker compose -p k5-day14-scaling logs agent` (sau 10 request trên và 5 request của `test_stateless.py`): mỗi instance nhận đúng 5 request.

```text
agent-1  | INFO:app:Starting instance instance-3f043b
agent-1  | INFO:app:Storage: Redis ✅
agent-1  | INFO:     172.18.0.6:47978 - "POST /chat HTTP/1.1" 200 OK      (× 5)
agent-2  | INFO:app:Starting instance instance-300b25
agent-2  | INFO:app:Storage: Redis ✅
agent-2  | INFO:     172.18.0.6:53638 - "POST /chat HTTP/1.1" 200 OK      (× 5)
agent-3  | INFO:app:Starting instance instance-5c2fc1
agent-3  | INFO:app:Storage: Redis ✅
agent-3  | INFO:     172.18.0.6:48002 - "POST /chat HTTP/1.1" 200 OK      (× 5)
```

**Cách hoạt động:**
- `--scale agent=3` tạo 3 container cùng tên service `agent`. DNS nội bộ của Docker trả về cả 3 IP cho tên `agent`, nên `upstream agent_cluster { server agent:8000; }` trong nginx có 3 backend.
- Nginx dùng **round-robin** mặc định: request lần lượt vào .5 → .3 → .4 → .5 → ..., đúng như bảng trên. Mọi request tới agent đều đi từ IP của nginx (`172.18.0.6`).
- Chỉ nginx mở cổng ra host (`8080:80`); các agent chỉ mở `8000` trong network `agent_net`.

**Một instance chết thì sao:** giữa một cuộc hội thoại, `docker kill k5-day14-scaling-agent-2` rồi gửi tiếp cùng `session_id`:

```text
turn 1 -> instance-3f043b
turn 2 -> instance-5c2fc1
killed agent-2 (instance-300b25)
turn 3 -> instance-3f043b  http=200
turn 4 -> instance-5c2fc1  http=200
turn 5 -> instance-3f043b  http=200
turn 6 -> instance-5c2fc1  http=200
turn 7 -> instance-3f043b  http=200
turn 8 -> instance-5c2fc1  http=200
history count: 16  (8 lượt × 2 = 16, đủ)

nginx-1 | [error] upstream timed out (110: Operation timed out) while connecting to upstream,
          request: "POST /chat HTTP/1.1", upstream: "http://172.18.0.5:8000/chat"
```

Traffic tự chuyển sang 2 instance còn lại, không request nào lỗi, và history vẫn đủ vì nằm trong Redis. Nhờ `proxy_next_upstream error timeout http_503; proxy_next_upstream_tries 3;` trong `nginx.conf`, khi một backend lỗi nginx thử backend khác thay vì trả lỗi cho client.

Đo thời gian từng request sau khi kill:

```text
req 1 -> HTTP=200 TIME=0.17s   upstream tried: 172.18.0.4:8000
req 2 -> HTTP=200 TIME=0.14s   upstream tried: 172.18.0.3:8000
req 3 -> HTTP=200 TIME=0.12s   upstream tried: 172.18.0.4:8000
req 4 -> HTTP=200 TIME=14.56s  upstream tried: 172.18.0.5:8000, 172.18.0.3:8000
req 5 -> HTTP=200 TIME=0.14s   upstream tried: 172.18.0.4:8000
req 6 -> HTTP=200 TIME=0.11s   upstream tried: 172.18.0.3:8000
```

Request rơi vào instance đã chết (req 4) vẫn thành công nhưng mất **14.6 giây**: nginx phải chờ kết nối tới `172.18.0.5` hết thời gian rồi mới thử `172.18.0.3`. Sau đó nginx đánh dấu backend này lỗi (mặc định `max_fails=1`, `fail_timeout=10s`) nên các request tiếp theo không thử lại nó. Muốn giảm độ trễ này nên đặt `proxy_connect_timeout` ngắn (ví dụ 2s) và dựa vào health check để loại instance chết sớm hơn.

Thêm một quan sát: nginx (bản open-source) chỉ resolve tên `agent` **một lần lúc khởi động**. Sau khi restart các agent (chúng có thể nhận IP mới), nginx vẫn gửi tới IP cũ và trả **502 Bad Gateway** cho tới khi restart nginx (`docker compose -p k5-day14-scaling restart nginx`).

### Exercise 5.5: Test stateless

`test_stateless.py` gửi 5 câu hỏi trong **cùng một session** qua nginx (`http://localhost:8080/chat`), ghi lại instance nào trả lời, rồi đọc lại history. Script không tự tắt instance nào (README, lưu ý số 7); phần "instance chết" đã thử bằng tay ở Exercise 5.4.

```text
> python test_stateless.py
============================================================
Stateless Scaling Demo
============================================================

Session ID: 5a06734c-72ae-4c24-af1f-6e84093987bb

Request 1: [instance-3f043b]
  Q: What is Docker?
  A: Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!...

Request 2: [instance-5c2fc1]
  Q: Why do we need containers?
  A: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé....

Request 3: [instance-300b25]
  Q: What is Kubernetes?
  A: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé....

Request 4: [instance-3f043b]
  Q: How does load balancing work?
  A: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận....

Request 5: [instance-5c2fc1]
  Q: What is Redis used for?
  A: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận....

------------------------------------------------------------
Total requests: 5
Instances used: {'instance-3f043b', 'instance-300b25', 'instance-5c2fc1'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?...
  [assistant]: Container là cách đóng gói app để chạy ở mọi nơi. Build once...
  [user]: Why do we need containers?...
  [assistant]: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đ...
  [user]: What is Kubernetes?...
  [assistant]: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đ...
  [user]: How does load balancing work?...
  [assistant]: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã đư...
  [user]: What is Redis used for?...
  [assistant]: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã đư...

✅ Session history preserved across all instances via Redis!
```

**Giải thích kết quả:**
- 5 request của cùng một session được **cả 3 instance** phục vụ (3f043b → 5c2fc1 → 300b25 → 3f043b → 5c2fc1), đúng thứ tự round-robin của nginx.
- History vẫn đủ **10 tin nhắn** (5 user + 5 assistant) đúng thứ tự, dù mỗi lượt do một instance khác ghi. Lý do: không instance nào giữ history trong RAM; tất cả đọc và ghi cùng key `session:{session_id}` trong Redis.
- Đối chiếu với thí nghiệm không có Redis ở Exercise 5.3 (mỗi instance chỉ thấy 4/12 tin nhắn), đây là bằng chứng agent đã **stateless**: có thể thêm, bớt, restart instance bất kỳ mà không mất dữ liệu của người dùng.

Xong thì tắt stack: `docker compose -p k5-day14-scaling down`.

## Part 6: check_production_ready.py

Chạy đầy đủ (có Docker, không `--static-only` / `--skip-docker`) trong `06-lab-complete/`. Chạy trong WSL Ubuntu 22.04 (Python 3.10, Docker Desktop 29.6.1 qua WSL integration), vì trên Windows script không gửi được SIGTERM nên mục graceful shutdown luôn ở trạng thái ⚠️.

```text
$ python check_production_ready.py
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 41/41 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

Một số chi tiết trong output: image **56 MB**, build 19s; rate limit trả 429 sau 5 request (`RATE_LIMIT_PER_MINUTE=5`) và vẫn 429 sau khi restart agent; cost guard trả 402 ở request đầu tiên khi budget 0.000001 USD; SIGTERM lúc đang có request → request vẫn 200, exit code 0; `docker stop` xong trong 0.8s với exit code 0.

## AI log

<!-- RULES.md mục 1: mỗi lần dùng AI cho code Part 6 hoặc cho câu trả lời. -->

| #   | Hỏi gì                                  | Nhận gì                                                                                                                                                                                                                                                              | Tự sửa và tự kiểm tra thế nào |
| --- | --------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------- |
| 1   | Nhờ Claude Code điền mục Part 1 (CP1)   | Danh sách 9 anti-pattern kèm dòng code, output chạy thật của bản develop và production, bảng so sánh 7 tiêu chí                                                                                                                                                      |                               |
| 2   | Nhờ Claude Code làm Exercise 2.1 và 2.2 | 4 câu trả lời về Dockerfile develop; build, chạy container trên port 8000, output `/health`, `/ask`, `docker logs` và kích thước image đo bằng `docker images`                                                                                                       |                               |
| 3   | Nhờ Claude Code làm Exercise 2.3 và 2.4 | Giải thích 2 stage của Dockerfile production; build `my-agent:advanced` và đo kích thước (240 MB / 57.4 MB, giảm ≈ 86%); chạy compose stack (nginx map sang cổng 8080 vì cổng 80 bị chiếm), sơ đồ 4 service, output test qua nginx                                   |                               |
| 4   | Nhờ Claude Code làm Exercise 4.1 và 4.2 | Trả lời 3 câu về API key (vị trí check, 401/403, cách rotate); chạy bản develop với `secret-key-123` (401/403/200) và bản production (lấy JWT bằng `student`/`demo123`, `/ask` 401/403/200), giải thích JWT flow, token đã che                                       |                               |
| 5   | Nhờ Claude Code làm Exercise 4.3 và 4.4 | Giải thích sliding window và admin tier; vòng lặp 20 request (10 × 200, 10 × 429) và 15 request admin; giải thích cost guard trong repo, kiểm 402/503 bằng cách gọi class `CostGuard` với budget nhỏ; viết và chạy thử bản Redis ($10/tháng) với container Redis tạm |                               |
| 6   | Nhờ Claude Code làm Exercise 5.1 đến 5.5 | Chạy và giải thích `/health` vs `/ready`; test graceful shutdown trong container (SIGTERM đủ thời gian → 200, timeout 1s và SIGKILL → mất kết nối); stack 3 instance: round-robin, kill 1 instance (failover, có request mất 14.6s), tắt Redis để thấy state trong RAM hỏng, output `test_stateless.py` | |
| 7   | Nhờ Claude Code viết code Part 6 (`06-lab-complete/`) | Code cho `app/config.py`, `auth.py`, `redis_client.py`, `rate_limiter.py` (sliding window bằng Lua script trên sorted set Redis), `cost_guard.py` (budget ngày + tháng, `INCRBYFLOAT`), `main.py` (log JSON, `/health`, `/ready`, lifespan shutdown, xử lý lỗi), `Dockerfile` multi-stage, `docker-compose.yml`, `.dockerignore`, `.env.example`, `railway.toml`; chạy `check_production_ready.py` trong WSL → `PASS 12/12`, và test `docker compose up` (401/422/200/429, key trong Redis, `stop` exit 0) | |
| 8   | Nhờ Claude Code làm CP6 (deploy Railway) và phần viết của Part 3 | So sánh `railway.toml` với `render.yaml`, mô tả pipeline Cloud Run; link service Railway có sẵn, tạo Redis, đặt `AGENT_API_KEY` / `ENVIRONMENT` / `REDIS_URL`, `railway up`; phát hiện key bị dính BOM và lỗi 500 với header non-ASCII, sửa `auth.py`, chấm lại `PASS 12/12`, deploy lại; 4 lệnh tự kiểm 200/200/401/200; viết `DEPLOYMENT.md` | |
| 9   | Nhờ Claude Code làm Part 7 (CP7, CP8) và điền `BENCHMARK_REPORT.md` | Load test v2 ở 4 mức concurrency và 3 mức `MOCK_SLOW_RATE`; eval v1/v2; thêm 2 entry `KNOWLEDGE_BASE` (JWT, Kubernetes HPA) → 23/23, quality gate PASS; sửa `production/Dockerfile` (thiếu `PYTHONUSERBASE`, agent crash); Locust scale 1 vs 3; tìm trace chậm/lỗi trong Jaeger và log khớp `trace_id`; thí nghiệm A–E với thời gian tới lúc firing; 4 ảnh Part 7 chụp bằng Chrome headless (Playwright); copy `reports/`, `benchmark-results/` | |
