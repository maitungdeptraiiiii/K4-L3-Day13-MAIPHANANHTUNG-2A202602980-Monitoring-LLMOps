# Báo cáo cá nhân — K4-L3A Day 13 Monitoring & LLMOps

> Mỗi học viên hoàn thiện một file duy nhất này. Khi dẫn evidence, dùng đường dẫn tương đối, ví dụ `evidence/07-trace-waterfall.png`.

## 1. Thông tin học viên

- **Họ và tên:** MAIPHANANHTUNG
- **MSSV:** 2A202602980
- **Lớp:** K4-L3A
- **Repository URL:** https://github.com/maitungdeptraiiiii/K4-L3-Day13-MAIPHANANHTUNG-2A202602980-Monitoring-LLMOps
- **Commit SHA cuối:** `fa08df5444edebb366258b569cf5bf0053c6bfc1` (commit chứa toàn bộ source và evidence; commit sau đó chỉ ghi SHA này vào report)
- **Challenge ID:** day13-k4-l3a-monitoring-llmops-v1 _(xác nhận lại với file Lab Coach gửi)_

## 2. Evidence index

Điền đúng đường dẫn tới evidence thực tế. Có thể đổi tên hoặc dùng nhiều ảnh nếu cần.

| Evidence | Đường dẫn |
|---|---|
| Pytest cuối | `evidence/01-pytest.txt` |
| Log validator | `evidence/02-log-validator.txt` |
| Dashboard validator | `evidence/03-dashboard-validator.txt` |
| Structured log | `evidence/04-structured-log.txt` |
| PII redaction | `evidence/05-pii-redaction.txt` |
| Trace list | `evidence/06-trace-list.png` |
| Trace waterfall | `evidence/07-trace-waterfall.png` |
| Trace metadata | `evidence/08-trace-metadata.png` |
| Prompt versions | `evidence/09-prompt-versions.png` |
| Prompt rollback | `evidence/10-prompt-rollback.png`, `evidence/10b-prompt-metrics-labels.png` |
| Dashboard runtime | `evidence/11-dashboard-overview.png` |
| Incident metric | `evidence/12-incident-metric.png` |
| Incident log | `evidence/13-incident-log.txt` |
| Incident trace | `evidence/14-incident-trace.png`, `evidence/14-incident-trace.txt` |

## 3. Kết quả kỹ thuật

| Nội dung | Baseline | Kết quả cuối | Nhận xét |
|---|---|---|---|
| `validate_logs.py` | 30/100 (`evidence/00-baseline.txt`) | 100/100 (`evidence/02-log-validator.txt`) | correlation ID, enrichment và PII đều đạt |
| `validate_dashboard.py` | 6/6 | 6/6 | validator chỉ kiểm cấu trúc; dashboard runtime ở `evidence/11-dashboard-overview.png` |
| `pytest` | 22 passed | 29 passed | thêm test PII (CCCD, thẻ, passport) và middleware |
| Số traces hợp lệ | 0 child observation | 71 root trace (Langfuse Tracing, filter Is Root Observation = True; `evidence/06-trace-list.png`) | mỗi trace có AGENT → RETRIEVER + GENERATION |
| Số PII leak | 0 | 0 | validator độc lập không thấy PII trong `data/logs.jsonl` |
| Latency P95 / TTFT P95 | _(chưa đo riêng)_ | ~1541 ms / 50 ms (concurrency 5) | xem dashboard |
| Retrieval success rate | _(chưa đo)_ | 100% ở tải bình thường | panel Errors |

## 4. Logging và PII

- **Cách tạo/nhận và truyền correlation ID:** `CorrelationIdMiddleware` (`app/middleware.py`) xoá contextvars, nhận `x-request-id` hợp lệ hoặc sinh `req-<8hex>`, bind vào structlog và `request.state`, trả lại header `x-request-id` và `x-response-time-ms`. Cùng ID được đưa vào metadata của trace Langfuse.
- **Các metadata được ghi vào structured log:** `ts, level, service, event, correlation_id, user_id_hash, session_id, feature, model, env`, cùng `latency_ms, ttft_ms, tokens_in/out, cost_usd, quality_score, tool_name, tool_success` ở `response_sent` (`app/main.py`).
- **Cách bảo đảm PII được scrub trước khi ghi:** `scrub_event` (`app/logging_config.py`) đứng trước `JsonlFileProcessor`, che `event` và mọi chuỗi trong `payload`; `user_id` chỉ ghi dạng SHA-256 rút gọn. Pattern trong `app/pii.py`: email, điện thoại VN, CCCD, thẻ, passport.
- **Cách kiểm chứng kết quả:** unit test `tests/test_pii.py`, `tests/test_middleware.py`; `validate_logs.py` 100/100; gửi một request chứa email/SĐT/CCCD/thẻ giả (`req-099edd29`) và đọc log (`evidence/05-pii-redaction.txt`).

## 5. Tracing và prompt versioning

- **Cấu trúc root/retrieval/generation observations:** root `lab-agent-run` (AGENT) có hai con: `rag-retrieve` (RETRIEVER, metadata `doc_count`, `query_preview` đã scrub) và `llm-generate` (GENERATION, có `model`, `usage_details`, `cost_details`, prompt link, `ttft_ms`). Không capture raw input/output. Kiểm tra qua Langfuse API v2 observations.
- **Cách nối trace với log:** `correlation_id` có trong metadata mọi observation và trong mọi dòng log của request.
- **Prompt name:** `day13-chat` (`scripts/manage_prompts.py` tạo/promote)
- **Version/label baseline:** v1, labels `baseline`, `production`
- **Version/label candidate:** v2, label `candidate` (thêm câu "Answer concisely in at most three sentences.")
- **Trace ID của mỗi version:** baseline v1 `cf52857d2695d6c9016778766502029b` (req-prompt-v1a); candidate v2 `db999ed2ef592f03e679993b8b22ccd1` (req-prompt-v2a); production→v2 `f90de1f8a8b427e9954b4c2b8d1d98f1` (req-prompt-prod-v2); rollback production→v1 `27f093250db965091aa86a3c6e87343b` (req-prompt-prod-v1b)
- **Cách promote và rollback `production`:** `python scripts/manage_prompts.py promote 2` rồi `promote 1` (đổi label `production`, không sửa code); chạy lại cùng input để xác nhận version trong trace.

## 6. Dashboard, SLO và alerts

- **Dashboard và sáu panel:** `python scripts/dashboard.py` (stdlib + PyYAML) đọc `data/logs.jsonl` và `config/dashboard.yaml`, dựng đúng 6 panel, đơn vị, 60 phút, refresh 30 s, đường threshold. Ảnh: `evidence/11-dashboard-overview.png` (render từ `data/logs.jsonl` bằng `--at 2026-09-29T08:26:00Z` vì cửa sổ 60 phút tính từ thời điểm đó; ảnh `12-incident-metric.png` dùng `--only latency,traffic --mark-ms 2000`, đường cam "Challenge threshold 2000 ms" và dòng ghi chú là chú thích thêm, không thuộc contract).
- **SLO và lý do chọn:** 99.5% request `response_sent` với latency ≤ 2000 ms trong 28 ngày; 2 s ≈ 1.3× baseline P95 (~1.5 s) và bằng `latency_threshold_ms` của challenge — xem `config/slo.yaml`. Bản nháp đầu dùng 3 s nhưng không bắt được sự cố 2.65 s nên đã siết lại. Đường threshold trên dashboard giữ 3000 ms theo contract `config/dashboard.yaml` (không được sửa), vì vậy panel latency vẫn hiện ✓ dù SLO 2 s bị vi phạm.
- **Cách tính error budget:** 100% − 99.5% = 0.5% request (5 request xấu/ngày ở 1.000 request/ngày); request lỗi cũng là bad event.
- **Ba alert và runbook tương ứng:** `high_latency_p95` (P2), `high_error_rate` (P1), `cost_per_request_spike` (P3) trong `config/alert_rules.yaml`; runbook `docs/alerts.md`.

## 7. Điều tra challenge

- **Challenge ID:** day13-k4-l3a-monitoring-llmops-v1
- **Khoảng thời gian điều tra:** 2026-09-29 08:24:12Z – 08:24:25Z (15:24 giờ VN), 5 request `feature=monitoring`, concurrency 5
- **Triệu chứng từ metrics:** panel Latency: `latency_ms` của cả 5 request = 2652 ms (P95 2652, vượt `latency_threshold_ms` 2000 của challenge và SLO 2 s) trong khi TTFT P95 chỉ 50 ms; error rate 0%, retrieval success 100%, cost/token/quality không đổi. Ảnh `evidence/12-incident-metric.png` (điểm ngoài cùng bên phải; điểm nhô lên ở khoảng −35 phút là lần practice của tôi). Cả 5 request chậm đều nhau nên đây là độ trễ cố định, không phải lỗi.
- **Log line và correlation ID liên quan:** `req-aab7bc32` — `response_sent` `latency_ms=2652`, `ttft_ms=50`, `tool_success=true` (`evidence/13-incident-log.txt`).
- **Trace ID và span gây ảnh hưởng:** trace `e66adda30ec4270927e00ef884567fac` (metadata `correlation_id=req-aab7bc32`): `lab-agent-run` 2.653 s = `rag-retrieve` 2.501 s + `llm-generate` 0.152 s (`evidence/14-incident-trace.txt`; thêm ảnh Langfuse nếu chụp được).
- **Root cause:** bước retrieval (`rag-retrieve`, `app/mock_rag.py` khi incident `rag_slow` bật) chiếm 2.5 s ≈ 94% thời gian request; LLM chỉ 0.15 s và TTFT bình thường 50 ms nên LLM không phải thủ phạm.
- **Fix action:** tắt incident (`python scripts/inject_incident.py --disable`); trong thực tế: kiểm tra vector store/dependency, timeout + fallback không retrieval.
- **Preventive measure:** alert `high_latency_p95` (P95 > 2000 ms trong 5 phút) kèm runbook chỉ tới span `rag-retrieve`; timeout ngắn cho retrieval; SLO 2 s (đã siết từ 3 s vì 3 s không bắt được sự cố này); span retrieval riêng để phân tách bottleneck.

## 8. Giải thích và tự đánh giá

- **Một quyết định kỹ thuật quan trọng và lý do:** bọc retrieval và generation bằng hai hàm riêng có `@observe` (`_retrieve`, `_generate` trong `app/agent.py`) thay vì mở span thủ công. Nhờ vậy span cha–con đúng, có thể bật/tắt capture input/output (tắt để không đưa PII lên Langfuse) và vẫn chạy được với các test double không có đủ method của Langfuse client (hàm `_update_observation` là best effort, telemetry không bao giờ làm hỏng request).
- **Một lỗi/blocker đã gặp:** (1) API `GET /api/public/traces` của Langfuse trả 410 vì project mới, phải đọc trace qua `/api/public/v2/observations`; (2) khi tắt server ngay sau request, span chưa kịp flush nên trace bị mất; (3) SLO 3 s của tôi không bắt được sự cố 2.65 s; (4) chạy uvicorn bằng Python hệ thống thay vì `.venv` gây `ModuleNotFoundError: structlog`.
- **Cách tìm nguyên nhân và xử lý:** (1) đọc thông báo lỗi và chuyển sang endpoint được gợi ý; (2) chờ ~10 s sau mỗi request trước khi dừng server; (3) so kết quả challenge (2652 ms) với ngưỡng 2000 ms trong file challenge rồi siết SLO/alert xuống 2 s và ghi lại trong `config/slo.yaml`; (4) dùng `.\.venv\Scripts\Activate.ps1` hoặc gọi `.venv\Scripts\python.exe`.
- **Cách hiểu luồng Metrics → Logs → Traces:** metrics cho biết có vấn đề và từ lúc nào (P95 2652 ms, TTFT vẫn 50 ms nên không phải LLM); logs cho biết request nào và cho `correlation_id` (`req-aab7bc32`); traces cùng ID cho biết bước nào chậm (`rag-retrieve` 2.5 s trên tổng 2.65 s). Mỗi lớp thu hẹp phạm vi cho lớp sau; `correlation_id` là khóa nối.
- **Vai trò của prompt version, token/cost, SLO hoặc rollback trong vận hành LLM:** prompt version trong trace cho biết chính xác request dùng prompt nào; đổi label `production` (promote/rollback) không cần deploy code nên rollback nhanh; token/cost theo generation cho thấy request nào tốn kém; SLO và error budget biến "chậm" thành con số để quyết định khi nào dừng thay đổi.
- **Điều quan trọng nhất đã học:** HTTP 200 chưa chắc là khỏe; ngưỡng SLO phải được kiểm chứng bằng chính sự cố thật (bản 3 s của tôi đã bỏ sót), và mọi telemetry phải scrub PII trước khi ghi.
- **Hạn chế hoặc phần chưa hoàn thành, nếu có:** dashboard là script HTML tự viết (không phải Grafana/Streamlit), đường threshold latency giữ 3000 ms theo contract nên panel vẫn hiện ✓ khi incident 2.65 s; alert mới ở dạng cấu hình + runbook, chưa gắn hệ thống gửi Slack thật; chưa đo riêng retrieval success và P95 baseline trước khi sửa code; các trace prompt v1/v2 nằm chung project với trace practice (71 root trace).

## 9. Checklist trước khi nộp

- [ ] Kết quả và evidence thuộc commit SHA cuối.
- [ ] Tất cả ảnh/output mở được bằng đường dẫn tương đối.
- [ ] Incident evidence nối đúng metric → log → trace.
- [ ] Repository chạy lại được theo README.
- [ ] Không có secret, API key, PII thô hoặc evidence của người khác/lớp khác.
- [ ] URL repo và commit SHA cuối đã được nộp trên LMS/Codelabs.
