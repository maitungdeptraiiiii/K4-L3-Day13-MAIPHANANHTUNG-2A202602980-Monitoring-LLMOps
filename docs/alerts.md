# Alert và Runbook

Ba alert đều dựa trên triệu chứng người dùng hoặc SLO (chậm, lỗi, tốn kém), không dựa vào tên hàm nội bộ. Cấu hình máy đọc được nằm ở [`config/alert_rules.yaml`](../config/alert_rules.yaml); SLO và error budget nằm ở [`config/slo.yaml`](../config/slo.yaml).

## SLO và error budget

- SLO: **99.5% request là `response_sent` với `latency_ms ≤ 2000`**, cửa sổ 28 ngày.
- Baseline đo được bằng `scripts/load_test.py` (concurrency 5): P95 ≈ 1.5 s, P99 ≈ 1.6 s, TTFT P95 ≈ 50 ms. Ngưỡng 2 s (bằng `latency_threshold_ms` của challenge) cao hơn baseline khoảng 30% nên tải bình thường không đốt budget, còn `rag_slow` (+2.5 s ở retrieval, request ≈ 2.65 s) thì có. Bản nháp đầu dùng 3 s và không bắt được sự cố 2.65 s nên đã siết lại.
- Error budget = 100% − 99.5% = **0.5%** số request. Với 1.000 request/ngày là 5 request xấu/ngày (140 request/28 ngày). Request lỗi (`request_failed`) không có `response_sent` nên cũng tính là xấu.
- Nếu budget bị đốt nhanh gấp 2 lần kế hoạch (> 1% request xấu trong 1 giờ) thì dừng đổi prompt/model và điều tra theo Metrics → Logs → Traces.

## Alert 1

- Tên: `high_latency_p95`
- Severity: P2
- Duration: 5 phút liên tục
- Kênh thông báo: Slack `#day13-alerts`
- SLI/SLO liên quan: SLO `fast_successful_requests` (latency ≤ 2000 ms); alert dùng cùng ngưỡng 2000 ms
- Điều kiện và thời gian duy trì: P95 của `latency_ms` trên event `response_sent` > 2000 ms, duy trì 5 phút
- Ảnh hưởng tới người dùng: Người dùng nhận câu trả lời chậm hơn vượt ngưỡng 2 s (baseline P95 ~1.5 s) dù HTTP vẫn 200; đốt error budget.
- Ba bước kiểm tra đầu tiên:
  1. Dashboard panel *Latency*: P95/P99 tăng từ lúc nào, TTFT có tăng theo không (TTFT bình thường ~50 ms; nếu TTFT ổn thì LLM không phải thủ phạm).
  2. Lọc `data/logs.jsonl` theo `latency_ms > 2000`, lấy `correlation_id` của một request chậm.
  3. Mở trace Langfuse cùng `correlation_id`, so sánh duration span `rag-retrieve` và `llm-generate`; span dài nhất là bottleneck.
- Mitigation tạm thời: Nếu `rag-retrieve` chậm: tắt incident/dependency lỗi (`python scripts/inject_incident.py --scenario rag_slow --disable`) hoặc chuyển sang fallback không retrieval; nếu `llm-generate` chậm: rollback prompt `production` về version trước bằng `python scripts/manage_prompts.py promote <version>`.
- Owner: maiphananhtung-oncall (học viên MAIPHANANHTUNG, MSSV 2A202602980)

## Alert 2

- Tên: `high_error_rate`
- Severity: P1
- Duration: 5 phút liên tục
- Kênh thông báo: Slack `#day13-alerts`
- SLI/SLO liên quan: SLO `fast_successful_requests` (request thất bại là bad event); guardrail error rate ≤ 2%
- Điều kiện và thời gian duy trì: `request_failed` / `request_received` > 2%, duy trì 5 phút
- Ảnh hưởng tới người dùng: Người dùng nhận HTTP 500, không có câu trả lời; đốt error budget nhanh nhất.
- Ba bước kiểm tra đầu tiên:
  1. Panel *Error rate and retrieval success*: xem breakdown theo `error_type` và tỷ lệ `tool_success`.
  2. Lọc log `event == "request_failed"`, đọc `error_type`, `tool_name`, lấy `correlation_id`.
  3. Mở trace cùng `correlation_id`: span nào có level ERROR (thường là `rag-retrieve` khi vector store timeout).
- Mitigation tạm thời: Tắt incident `tool_fail` nếu đang bật; bật fallback trả lời không có context; nếu do deploy/prompt mới thì rollback label `production`.
- Owner: maiphananhtung-oncall (học viên MAIPHANANHTUNG, MSSV 2A202602980)

## Alert 3

- Tên: `cost_per_request_spike`
- Severity: P3
- Duration: 10 phút liên tục
- Kênh thông báo: Slack `#day13-alerts`
- SLI/SLO liên quan: Guardrail `daily_cost_usd_max` = 2.5 USD và chi phí trung bình/request
- Điều kiện và thời gian duy trì: `sum(cost_usd) / count(response_sent)` > 0.004 USD, duy trì 10 phút (baseline ~0.002 USD/request)
- Ảnh hưởng tới người dùng: Chi phí vận hành tăng gấp đôi trên mỗi câu trả lời; không ảnh hưởng trực tiếp tới người dùng nhưng đe dọa ngân sách hằng ngày.
- Ba bước kiểm tra đầu tiên:
  1. Panel *Cost over time* và *Input and output tokens*: token nào tăng (thường `tokens_out`).
  2. Lọc log `response_sent` có `tokens_out` cao, lấy `correlation_id` và `feature`.
  3. Mở generation observation của trace đó: xem `usage_details`, `cost_details`, prompt version/label.
- Mitigation tạm thời: Tắt incident `cost_spike`; rollback prompt về version ngắn hơn; đặt giới hạn `max_tokens`.
- Owner: maiphananhtung-oncall (học viên MAIPHANANHTUNG, MSSV 2A202602980)
