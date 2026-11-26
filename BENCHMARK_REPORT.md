# Benchmark & Observability Report — Day 14

> Mọi con số lấy từ report JSON (`06-lab-complete/benchmark-observability/develop/reports/`, bản sao ở `reports/`), CSV Locust (`benchmark-results/`) và screenshot thật.

**Họ tên:** TranVietAnh — 2A202604029
**Ngày chạy:** 2026-11-26
**Môi trường:** Laptop Windows 11, Intel Core i7-12650H (10 nhân / 16 luồng), RAM 15.7 GB; Docker Desktop 29.6.1 (WSL2, 16 CPU / 7.6 GB cấp cho Docker). Phần develop chạy trực tiếp trên Windows (Python 3.13, uvicorn 1 process / agent); phần production chạy bằng Docker Compose (agent giới hạn 0.5 CPU / 256 MB mỗi container).

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Mock LLM mất ~120–180 ms + ~20 ms retrieval, nên p95 bình thường ~250 ms (đo được 245–255 ms ở concurrency 1–20). 500 ms để dư gấp đôi cho jitter và tải cao, nhưng vẫn bắt được khi request chậm chiếm > 5% (MOCK_SLOW_RATE 0.1 → p95 1696 ms, vi phạm ngay). Đặt theo p95 chứ không theo average vì average che tail latency (mục 2.2). Alert dùng ngưỡng lỏng hơn (p95 > 1 s trong 2 phút) để tránh báo động vì spike ngắn. |
| Error rate `/ask` | < 2 % | Mock LLM lỗi upstream ~1% (`MOCK_ERROR_RATE=0.01`), đo được 0.33–1.67% khi bình thường. 2% chừa error budget cho mức lỗi nền đó; vượt 2% nghĩa là có sự cố thật (MOCK_SLOW_RATE 0.1 → 3.33%). Alert ở > 5% trong 1 phút. |
| Accuracy trên golden dataset | ≥ 80 % (gate CI), mục tiêu 100 % | 80% là ngưỡng mặc định của quality gate, đủ chặn bản v1 (4.3%). Với dataset nhỏ (23 câu) mỗi câu là 4.3 điểm %, nên ngoài ngưỡng accuracy còn chặn **mọi regression** so với baseline; sau khi sửa KB, v2 đạt 100% và được dùng làm ngưỡng cho lần eval cuối (`--min-accuracy 1.0`). |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

300 request mỗi mức, `MOCK_SLOW_RATE=0.03` (mặc định). File: `reports/load_v2_c{1,10,50,100}.json`.

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.14 | 206.9 | 244.9 | 1701.9 | 1.00% | ✅ PASS |
| 10 | 34.26 | 208.3 | 255.9 | 1721.6 | 1.33% | ✅ PASS |
| 50 | 88.06 | 241.0 | 464.4 | 1811.8 | 1.67% | ✅ PASS |
| 100 | 43.15 | 733.5 | 5308.3 | 5548.8 | 1.00% | ❌ FAIL (p95) |

**Nhận xét:** RPS **không** tăng tuyến tính.

- Từ 1 → 10, RPS tăng 8.3× (gần tuyến tính) vì agent gần như chỉ chờ mock LLM (`asyncio.sleep`), không tốn CPU: 10 request chờ song song mà latency gần như không đổi (p50 207 → 208 ms). Theo định luật Little, RPS ≈ concurrency / latency ≈ 10 / 0.27 s ≈ 37, khớp với 34.
- Từ 10 → 50, RPS chỉ tăng 2.6× (lẽ ra 5×) và p95 tăng từ 256 lên 464 ms: process uvicorn duy nhất bắt đầu bão hoà (1 event loop, 1 nhân CPU cho parse JSON, tính metrics, ghi log) nên request phải xếp hàng.
- Ở 100, RPS **giảm** còn 43 và p95 lên 5.3 s: quá điểm bão hoà, request chủ yếu xếp hàng (hàng đợi kết nối của server, client cũng chạy trên cùng máy) nên latency tăng vọt mà throughput không tăng, thậm chí giảm vì overhead tranh chấp. Đây là điểm cần scale ngang (thêm process / instance) chứ không thể tăng concurrency thêm.
- Error rate gần như không đổi (1.0–1.67%) vì lỗi đến từ mock upstream, không phải do tải.

### 2.2 Tail latency

Concurrency 20, 300 request, khởi động lại v2 với mỗi giá trị. File: `reports/load_v2_slow_{0,0.03,0.1}.json`.

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 213.9 | 248.7 | 269.5 |
| 0.03 (mặc định) | 253.6 | 254.0 | 1710.9 |
| 0.1 | 316.7 | 1696.2 | 1730.9 |

**Nhận xét:**

- Tăng từ 0 lên 0.03 (3% request chậm thêm ~1.5 s): **p99** tăng 6.3× (270 → 1711 ms) trong khi avg chỉ tăng 19% (214 → 254 ms) và p95 gần như không đổi. Lên 0.1: **p95** nhảy 6.8× (249 → 1696 ms), avg chỉ tăng 48%.
- Percentile cao là chỉ số nhạy nhất: một percentile pX "thấy" request chậm ngay khi tỉ lệ request chậm vượt (100 − X)%. Với 3% chậm, p99 thấy còn p95 chưa thấy; với 10% chậm, cả p95 và p99 đều thấy.
- SLO không nên đặt theo average vì average trộn vài request rất chậm với hàng trăm request nhanh: ở `MOCK_SLOW_RATE=0.1` avg = 317 ms trông "ổn" (vẫn < 500 ms) trong khi cứ 10 người thì 1 người chờ ~1.7 s. Người dùng cảm nhận theo lần chậm nhất họ gặp, nên SLO đặt theo p95/p99 mới phản ánh trải nghiệm thật. Lần chạy 0.1 cũng vi phạm SLO error rate (3.33%) nên `load_test.py` trả exit code 1.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

23 câu trong `golden_dataset.jsonl`, câu đúng khi chứa ≥ 60% keyword mong đợi. File: `reports/eval_v1.json`, `reports/eval_v2.json`, `reports/eval_v2_fixed.json`.

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | 100% (23/23) |
| Avg tokens / câu | 55.8 | 109.0 | 118.7 |
| Tổng cost (USD) | 0.000386 | 0.000759 | 0.000834 |
| Cost / câu đúng (USD) | 0.00038595 | 0.00003616 | 0.00003625 |
| Latency p50 / p95 (ms) | 174.1 / 209.4 | 214.0 / 239.4 | 205.1 / 1544.4 |
| Quality gate | ❌ FAIL (accuracy 4.3% < 80%) | ✅ PASS (≥ 80%, baseline v1, 0 regression) | ✅ PASS (≥ 100%, baseline v2, 0 regression) |

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02` "JWT khác gì API key trong xác thực?" | `token`, `hết hạn`, `chữ ký` (score 0.00) | Retrieval không tìm thấy tài liệu nào (không entry nào có từ khoá "jwt") nên agent trả câu chung chung. Thêm entry vào `KNOWLEDGE_BASE` với trigger `["jwt", "json web token"]`, nội dung nói về token có `exp` (hết hạn), được ký (chữ ký), so với API key cố định phải rotate. |
| `scaling-03` "Kubernetes HPA scale dựa trên những chỉ số nào?" | `cpu`, `memory`, `custom metrics` (score 0.00) | Cùng nguyên nhân. Thêm entry với trigger `["hpa", "horizontal pod autoscaler", "kubernetes", "autoscal"]`, nội dung: HPA scale theo CPU, memory hoặc custom metrics. Trước khi thêm đã kiểm tra các trigger mới không xuất hiện trong câu hỏi nào khác, để không đổi tài liệu được chọn cho câu đang đúng. |

Sau khi sửa: tắt rồi bật lại v2 (app không tự nạp code), chạy `run_eval.py --min-accuracy 1.0 --baseline reports/eval_v2.json` → 23/23, 2 câu được cải thiện, 0 regression, `Quality gate (accuracy ≥ 100%, không regression): ✅ PASS`.

Ghi chú: p95 của lần eval cuối là 1544 ms vì 1–2 trong 23 request rơi vào "slow" (`MOCK_SLOW_RATE=0.03`). Đây đúng là cảnh báo trong README: eval 23 câu không đủ mẫu để kết luận về latency; latency phải đo bằng load test.

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**

- **Chất lượng:** v2 (có retrieval) đúng 21/23 so với 1/23 của v1; v1 trả lời chung chung cho gần như mọi câu.
- **Chi phí mỗi câu:** v2 tốn ~2× token (109 so với 55.8) vì prompt có thêm tài liệu retrieve được, nên tổng cost gấp ~2× (0.000759 so với 0.000386 USD cho 23 câu).
- **Chi phí mỗi câu đúng:** v2 rẻ hơn **~10.7×** (0.0000362 so với 0.000386 USD). Đây là chỉ số nên dùng để so sánh: v1 rẻ mỗi câu nhưng gần như mọi câu đều vô dụng.
- **Latency:** v2 chậm hơn ~30–40 ms (p50 214 so với 174 ms, p95 239 so với 209 ms) do bước retrieval (~20 ms) và prompt dài hơn (latency mock tăng theo số token). Vẫn nằm xa SLO 500 ms.
- **Kết luận:** trả ~2× chi phí và ~15–20% latency để tăng accuracy từ 4% lên 91–100% là đáng. Sửa KB (thêm 2 tài liệu) tăng thêm ~9% token / câu nhưng giữ nguyên cost / câu đúng.

**Quality gate trong CI (Exercise 7.3, bài 4):** chạy eval v1 với baseline v2:

```text
$ python eval/run_eval.py --url http://localhost:8001 --baseline reports/eval_v2.json
  Accuracy      : 4.3%  (1/23)
  ⚠️  Câu bị regression : 20 ['docker-01', 'docker-02', 'probe-01', ...]
  Quality gate (accuracy ≥ 80%, không regression): ❌ FAIL
$ echo $?
1
```

`run_eval.py` trả **exit code 1** khi quality gate fail (accuracy dưới ngưỡng **hoặc** có regression), 0 khi pass. CI coi bước có exit code ≠ 0 là thất bại, nên chỉ cần chạy lệnh eval như một bước của job; đặt job này là *required status check* của nhánh `main` thì PR làm giảm chất lượng không merge được:

```yaml
# .github/workflows/eval.yml
name: quality-gate
on: pull_request
jobs:
  eval:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: 06-lab-complete/benchmark-observability/develop
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -r requirements.txt
      - name: Start agent (bản trong PR)
        run: |
          AGENT_VERSION=v2 PORT=8002 python app.py &
          for i in $(seq 1 30); do curl -sf http://localhost:8002/health && break; sleep 1; done
      - name: Eval + quality gate (exit 1 → job đỏ → chặn merge)
        run: |
          python eval/run_eval.py --url http://localhost:8002 \
            --min-accuracy 0.8 --baseline reports/eval_v2_fixed.json --out eval_pr.json
      - uses: actions/upload-artifact@v4
        if: always()
        with: { name: eval-report, path: 06-lab-complete/benchmark-observability/develop/eval_pr.json }
```

---

## 4. Observability stack (production)

Stack chạy bằng `docker compose -p k5-day14-observability up -d --build` trong `06-lab-complete/benchmark-observability/production/`, 2 instance agent, tải nền Locust headless 30 user (`-u 30 -r 5`) trong suốt phần 4. `promtool test rules alert_rules_test.yml` → `SUCCESS`.

> Sửa 1 lỗi trong `production/Dockerfile` để stack chạy được: user `agent` có home là `/app` (`useradd -d /app`) nên Python tìm package ở `/app/.local`, trong khi package được copy vào `/home/agent/.local` → container crash `ModuleNotFoundError: No module named 'uvicorn'`. Thêm `ENV PYTHONUSERBASE=/home/agent/.local` (giống Dockerfile Part 5).

### 4.0 Exercise 7.4: đọc dashboard khi có tải (30 user, 2 instance, đo lúc 22:59)

Số liệu từ Prometheus (cùng câu PromQL với dashboard) và ảnh [screenshots/grafana-dashboard.png](screenshots/grafana-dashboard.png):

1. **p95 và avg:** p50 = 177 ms, **avg = 233 ms, p95 = 294 ms, p99 = 1830 ms** (panel Golden Signals ghi p95 293 ms). avg và p95 gần nhau, nhưng p99 gấp ~8 lần avg: phần lớn request nhanh, còn ~3% request chậm bất thường (~1.7–1.8 s, do `MOCK_SLOW_RATE=0.03`). Khoảng cách giữa avg và p99 chính là tail latency mà average che mất; trên panel "Latency /ask" đường p99 nằm trên vạch đỏ 1 s trong khi p50/p95/avg sát đáy.
2. **Requests/s theo instance:** `172.18.0.6:8000` = 10.084 req/s, `172.18.0.8:8000` = 10.084 req/s → Nginx chia **đều** (round-robin, `server agent:8000 resolve` thấy cả 2 IP).
3. **Input tokens/s (1483) lớn hơn output tokens/s (786):** input gồm system prompt + tài liệu retrieve được (agent v2) + câu hỏi, còn output chỉ là câu trả lời ngắn. RAG làm prompt dài ra: đổi chất lượng lấy token input.
4. **`curl http://localhost:8080/metrics` → `HTTP/1.1 404 Not Found`:** `nginx.conf` có `location = /metrics { return 404; }`. `/metrics` chỉ dành cho Prometheus scrape trực tiếp từng agent trong mạng nội bộ (`agent:8000`), không public ra ngoài vì lộ thông tin nội bộ (version, model, số request, chi phí) và ai cũng gọi được.

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals): [screenshots/grafana-dashboard.png](screenshots/grafana-dashboard.png): 20.4 req/s, error 0.79%, p95 293 ms, in-flight 5, 2 instance, cost/giờ vượt ngưỡng (màu cam)
- [x] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian): [screenshots/jaeger-slow-trace.png](screenshots/jaeger-slow-trace.png): trace 1.8 s, span `chat mock-llm-small` 1.7 s
- [x] Một trace lỗi trong Jaeger (có event `exception`): [screenshots/jaeger-error-trace.png](screenshots/jaeger-error-trace.png): `POST /ask` 503, event `exception` với `exception.message` và stacktrace
- [x] Trang Alerts của Prometheus với ít nhất 1 alert đang **firing**: [screenshots/prometheus-alert-firing.png](screenshots/prometheus-alert-firing.png): `AgentHighErrorRate` và `AgentHighLatencyP95` cùng firing (A + B)

### 4.2 Thí nghiệm "phá hệ thống"

Mỗi thí nghiệm: ghi `.env` rồi `docker compose -p k5-day14-observability up -d --scale agent=2 agent` (t0 = lúc lệnh xong), poll `GET /api/v1/alerts` mỗi 5 s. Thời gian dưới đây gồm cả `for:` của rule (A: 1m, B/C: 2m, D: 30s) và chu kỳ scrape/evaluate 5 s.

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (error rate 20.9–22.7%, ngưỡng 5%) | pending sau 31 s, **firing sau 91 s** | "Error rate" chuyển đỏ (~21%), "Requests/s theo status code" (đường 503 tăng), "LLM calls theo kết quả" (error) |
| B | `MOCK_SLOW_RATE=0.3` (giữ A) | `AgentHighLatencyP95` (p95 1.89 s, ngưỡng 1 s) | pending sau 25 s, **firing sau 146 s** | "Latency /ask p50/p95/p99": p95 vọt lên 1888 ms, p99 1978 ms, avg chỉ 553 ms, **p50 vẫn 193 ms** |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` ($13.8–14.4/giờ, ngưỡng $2) | pending sau ~20 s, **firing sau ~2 phút 20 s** (activeAt 23:11:32 + `for: 2m`)* | "Cost burn rate (USD/giờ)": $1.94 → $14.42/giờ (~7.4×); "LLM latency p95" tăng, p95 /ask 293 → 691 ms |
| D | `docker pause k5-day14-observability-agent-1` | `AgentInstanceDown` (`up{instance=…}==0`) | pending sau 10 s, **firing sau 40 s** | "Instances up" 2 → 1; Locust thấy lỗi (nginx ghi 273 dòng 5xx trong 90 s) nhưng panel "Error rate" của agent vẫn xanh |
| E | `AGENT_VERSION=v1` | Không có | Không firing (theo dõi 90 s) | "Retrieval hit ratio" 88.6% → **không còn dữ liệu** (v1 không retrieval); "Tokens/s" input 1447 → 719, output 766 → 392; "Cost burn rate" $5.30 → $1.51/giờ; bảng "Phiên bản đang chạy" v2 → v1. Error rate (1.5% → 1.8%) và p95 (292 → 198 ms, còn **nhanh hơn**) vẫn xanh |

\* Ở tải nền 30 user, cost với `mock-llm-small` đã dao động quanh ngưỡng $2/giờ ($1.94–3.81/giờ), nên `LLMCostBurnRateHigh` **đã firing ngay ở trạng thái bình thường** (xem phân tích bên dưới). Thời gian của C tính từ lúc đổi model, khi alert đã về inactive.

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Với v1, mọi chỉ số hạ tầng trông **tốt hơn**: nhanh hơn (p95 198 ms), rẻ hơn ($1.51/giờ), lỗi như cũ. Nhưng accuracy thực tế rơi từ 100% xuống 4.3% (eval ở mục 3). Metric hạ tầng chỉ đo "có trả lời được không, nhanh không", không đo "trả lời có đúng không". Cách phát hiện:

1. **Quality gate trước khi deploy:** chạy `run_eval.py --baseline` trong CI (mục 3). v1 bị chặn với exit code 1 và 20 câu regression, nên lẽ ra không bao giờ lên production.
2. **Eval định kỳ trên production (synthetic monitoring chất lượng):** mỗi giờ chạy golden dataset vào endpoint thật, đẩy accuracy thành metric (vd `agent_eval_accuracy`) và alert khi < 90%.
3. **Metric gián tiếp của chất lượng:** alert khi `agent_retrieval_total{result="hit"}` tụt (ở E rơi từ 88.6% về không có dữ liệu), khi token/request giảm bất thường, hoặc khi `agent_info{version}` đổi ngoài lịch deploy.
4. **Tín hiệu từ người dùng:** tỉ lệ 👍/👎, tỉ lệ hỏi lại / bỏ cuộc trò chuyện, và đọc mẫu câu trả lời (hoặc LLM-as-judge trên một tỉ lệ nhỏ traffic).

**Phân tích thí nghiệm:**

- **A (lỗi):** alert firing sau 91 s = ~30 s để `rate(...[1m])` đủ dữ liệu vượt 5% + `for: 1m`. `for` tránh báo động vì vài lỗi lẻ tẻ, đổi lại chậm hơn 1 phút.
- **B (chậm):** p95 tăng 6.4× nhưng **p50 gần như không đổi** (193 ms) và avg chỉ tăng ~2×: đúng bài học mục 2.2, nếu alert theo p50/avg thì sẽ bỏ lỡ sự cố này. Alert latency có `for: 2m` nên chậm hơn A.
- **C (chi phí):** latency tăng ~2.4× (đúng `latency_factor` 2.5 của model large) nhưng không vượt ngưỡng latency 1 s; chỉ alert chi phí bắt được. Không có alert chi phí thì đổi model "lặng lẽ" có thể đốt tiền mà dashboard hạ tầng vẫn xanh.
- **D (instance chết):** `docker pause` (không phải `stop`) giữ container trong DNS nên Prometheus thấy target `up == 0`. Panel "Error rate" của agent vẫn xanh vì request lỗi chết ở **Nginx** (timeout 504 / kết nối lỗi), agent không bao giờ xử lý xong nên không đếm. Metric chỉ phản ánh những gì chính service đó thấy, nên production cần thêm metric ở load balancer hoặc synthetic check từ bên ngoài.
- **Ngưỡng alert chi phí quá thấp so với tải:** với 30 user (~20 req/s), chi phí "bình thường" đã ~$2–3.8/giờ nên `LLMCostBurnRateHigh` firing liên tục ở baseline. Đây là alert fatigue: alert luôn đỏ thì người trực sẽ bỏ qua cả khi có sự cố thật (C). Nên đặt ngưỡng theo baseline thực tế (vd 2–3× mức bình thường), hoặc theo budget ngày/tháng thay vì cố định $2/giờ.

### 4.3 Debug bằng trace

Trace chậm nhất trong 30 phút (tìm bằng Jaeger API `query.duration_min=1s`, sắp theo thời gian giảm dần), ảnh: [screenshots/jaeger-slow-trace.png](screenshots/jaeger-slow-trace.png):

- `trace_id`: `6bf692c320d1e96a6ccb2bc5fb770c55` (instance `5fe3164835fc`, 2026-11-26 22:55:45 GMT+7)
- Tổng thời gian: **1755.8 ms** (span gốc `POST /ask`)
- Span chiếm nhiều thời gian nhất: **`chat mock-llm-small`** (1678.5 ms, **95.6%**), tức lời gọi LLM. Các span khác: `agent.run` 1703.7 ms (span cha bao cả retrieval và LLM), `agent.retrieve_context` 25.0 ms (1.4%), ~52 ms còn lại là FastAPI xử lý request. Span LLM có `gen_ai.usage.input_tokens=74`, `output_tokens=37`, tức prompt không dài bất thường: request này rơi vào nhóm "slow" của mock (`MOCK_SLOW_RATE`, +1.5 s), không phải lỗi trong code agent.
- Dòng log tương ứng (`docker compose -p k5-day14-observability logs agent | grep 6bf692c320d1e96a6ccb2bc5fb770c55`):

```json
{"ts": "2026-11-26T15:55:47.473959+00:00", "level": "INFO", "service": "observable-agent", "instance": "5fe3164835fc", "event": "llm_call", "trace_id": "6bf692c320d1e96a6ccb2bc5fb770c55", "span_id": "f4b6bc75c3c3c1bb", "request_id": "30167a4a93ac", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 74, "output_tokens": 37, "cost_usd": 3.3e-05, "llm_ms": 1676.9}
{"ts": "2026-11-26T15:55:47.474234+00:00", "level": "INFO", "service": "observable-agent", "instance": "5fe3164835fc", "event": "http_request", "trace_id": "6bf692c320d1e96a6ccb2bc5fb770c55", "span_id": "f4b6bc75c3c3c1bb", "request_id": "30167a4a93ac", "method": "POST", "route": "/ask", "status": 200, "ms": 1755.4}
```

Log khớp trace: cùng `trace_id`, `llm_ms` 1676.9 ≈ span LLM 1678.5 ms, `ms` 1755.4 ≈ span gốc 1755.8 ms.

**Trace lỗi** (ảnh: [screenshots/jaeger-error-trace.png](screenshots/jaeger-error-trace.png)): `trace_id` `809e2ccf6b9034b50fa8ec9f995a72a1`, 862 ms, `POST /ask` trả **503**. Span `chat mock-llm-small` (843 ms) có `error.type = upstream_unavailable` và event `exception`: `utils.mock_llm.LLMError: Upstream LLM error: 503 Service Unavailable (mock)`, kèm stacktrace (`app/main.py` dòng 153 → `utils/mock_llm.py` dòng 199). Log tương ứng có `"event": "llm_error"` cùng `trace_id`, ví dụ:

```json
{"ts": "2026-11-26T15:51:35.627390+00:00", "level": "INFO", "service": "observable-agent", "instance": "5fe3164835fc", "event": "llm_error", "trace_id": "1fcffb78c5a8fed01530b09b336e2c3b", "span_id": "6c0f6959f2744625", "request_id": "3c8032b3ffa9", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

`docker compose -p k5-day14-observability run --rm locust ... --headless -u 100 -r 10 -t 2m --csv /mnt/results/scale_{1,3}`, số liệu dòng `POST /ask` trong `benchmark-results/scale_{1,3}_stats.csv` (RPS tổng gồm cả `/health`: 70.32 và 70.48).

| Số instance | RPS (`/ask`) | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 64.31 | 190 | 230 | 1700 | 73 / 7167 (1.02%) |
| 3 | 64.29 | 190 | 230 | 1700 | 61 / 7178 (0.85%) |

Trước khi chạy lần 3 instance đã kiểm tra: Prometheus thấy 3 target `agent` đều `up` (`172.18.0.6`, `.8`, `.9`), và Nginx chia `/health` đều cho cả 3 IP.

**Giải thích kết quả:** Scale từ 1 lên 3 instance **không cải thiện** gì: RPS, p50, p95, p99 gần như giống hệt; failures giảm nhẹ (1.02% → 0.85%) nằm trong dao động ngẫu nhiên của mock (lỗi 1%).

- **RPS không tăng vì không phải giới hạn của server.** Locust có 100 user, mỗi user nghỉ 0.5–2 s giữa 2 request (`wait_time = between(0.5, 2)`), nên tải sinh ra tối đa ≈ 100 / (1.25 s + 0.24 s) ≈ 67 req/s, khớp với 64–70 req/s đo được. 1 instance đã phục vụ hết lượng tải này mà latency vẫn ổn, nên thêm instance thì RPS vẫn bằng đúng lượng tải mà client tạo ra.
- **p95/p99 không đổi vì nút thắt nằm ở LLM, không phải ở agent.** Mỗi request mất ~190 ms chủ yếu để chờ mock LLM (`asyncio.sleep`, không tốn CPU), và p99 ≈ 1700 ms do 3% request "slow" của LLM. Thêm instance không làm LLM trả lời nhanh hơn. Panel "LLM latency p95" trên Grafana trùng gần như hoàn toàn với p95 của `/ask`, và trace cho thấy span LLM chiếm ~95% thời gian request.
- Scale ngang chỉ có ích khi một instance bão hoà (CPU, event loop, in-flight tăng, latency tăng theo tải), như ở mục 2.1 với concurrency 100. Muốn thấy khác biệt ở đây phải tăng tải vượt sức 1 instance (nhiều user hơn, wait_time ngắn hơn). Lợi ích khác của 3 instance là **khả năng chịu lỗi**: 1 instance chết thì vẫn còn 2 (xem thí nghiệm D).

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. **Average nói dối, percentile thì không.** Ở `MOCK_SLOW_RATE=0.1` avg 317 ms vẫn trong SLO nhưng p95 1696 ms; ở thí nghiệm B p50 không đổi trong khi p95 tăng 6.4×. SLO và alert phải đặt theo p95/p99.
  2. **Scale ngang không chữa được nút thắt nằm ngoài service.** 1 → 3 instance cho RPS và p95 y hệt vì tải chưa vượt sức 1 instance và ~95% thời gian request nằm ở LLM (trace cho thấy rõ). Phải đo (load test + trace) trước khi quyết định scale. Ngược lại, khi 1 process bão hoà (concurrency 100 ở develop) thì latency tăng vọt mà RPS còn giảm.
  3. **Metric hạ tầng chỉ thấy những gì chính service thấy, và không thấy chất lượng.** Instance bị pause làm người dùng nhận lỗi nhưng error rate của agent vẫn xanh (D); đổi sang v1 làm accuracy rơi từ 100% xuống 4% mà không alert nào kêu (E). Cần kết hợp metric + trace + log có `trace_id` + eval chất lượng + giám sát từ phía client.
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?
  - **Chất lượng:** chạy eval golden dataset trong CI (quality gate, exit code chặn merge) và định kỳ trên production (synthetic eval mỗi giờ), alert khi accuracy < 90%; metric `agent_retrieval_total{result}` với alert khi hit ratio giảm đột ngột (bắt được thí nghiệm E); thu feedback 👍/👎 của người dùng thành metric.
  - **Phía người dùng / load balancer:** synthetic check `/ask` từ bên ngoài (blackbox exporter) và metric 5xx/latency của Nginx, để bắt lỗi mà agent không thấy (thí nghiệm D).
  - **SLO burn rate:** alert theo tốc độ tiêu error budget (multi-window, vd 1h và 6h) thay vì ngưỡng tức thời, ít báo động giả hơn.
  - **Chi phí:** ngưỡng cost theo baseline và theo budget ngày/tháng (giống cost guard Part 6), cost theo model / phiên bản; alert khi token/request tăng bất thường (prompt phình to).
  - **Bão hoà:** CPU/RAM container, in-flight theo instance, độ dài hàng đợi; alert khi in-flight cao kéo dài (dấu hiệu cần scale, như concurrency 100 ở mục 2.1).
  - **Phụ thuộc:** latency/lỗi của LLM provider tách riêng theo provider và mã lỗi (429 rate limit vs 503), Redis `up` và latency.
