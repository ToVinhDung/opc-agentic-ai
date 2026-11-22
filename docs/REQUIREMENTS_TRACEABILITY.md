# Requirements Traceability Matrix — 2.7.2

| Yêu cầu/chứng minh | Triển khai | Bằng chứng trong gói |
|---|---|---|
| Một nguồn dữ liệu thật | Một canonical TeamPack; không Complete/Incomplete | data/, release regression |
| Đọc hợp đồng động | Selector từ 04_CONTRACTS; mapping customer/order/invoice/credit theo contract | engine.py, multi-contract tests |
| Thiếu dữ liệu đa sheet | Một issue cho từng record/field; Blocking/Warning/Optional | engine.py, Data Quality tab, tests |
| Ba vai trò Agent | Data & Finance; Risk & Compliance; Funding & Partnership | workflow UI, trace events |
| OpenAI core trước engine | Structured Evidence Extraction ba field từ source text đã mask | evidence_extraction.py, openai_client.py, OpenAI Extraction tab |
| Evidence không bị AI bịa/replay | Fingerprint gắn Trace ID, source whitelist, exact quote, confidence, phủ định và semantic checks | evidence_extraction.py, test_evidence_extraction.py |
| OpenAI bounded sau engine | Challenger exact-match recommendation và evidence echo | openai_client.py, OpenAI Guardrails tab, tests |
| Fail-safe khi mất OpenAI | Approvable → NEED REVIEW; REJECT/NMD giữ nguyên | app.py, test_openai_pipeline.py |
| Reconciliation đầy đủ | 08_BANK_TXN → 07_INVOICES → 06_ORDERS → 04_CONTRACTS; lớp chi tiết UI được ẩn nhưng pipeline vẫn hoạt động | engine.py, Risk/Decision output, Decision JSON, test_reconciliation.py |
| Không hard-code giao dịch | UI lấy status/scope từ backend; anomaly có lineage giữ CASE + ENTERPRISE | engine.py, static/app.js, test_reconciliation.py |
| Không fuzzy guess | L1 explicit ref; L2 unique exact amount+counterparty+paid_date; còn lại unmatched/ambiguous | engine.py, ambiguity tests |
| Reverse reconciliation | Paid invoice không có Credit match tạo warning | RR-REC-001, reconciliation tests |
| Tách scope | Contract match của case khác bị exclude; anomalies không lineage giữ enterprise scope | Risk output, reconciliation tests |
| Bảo vệ counterparty | Raw identifier chỉ dùng server-side; UI/export nhận token mask | engine.py, static/app.js |
| Enterprise anomaly HITL | Chưa xác minh thì approval_allowed=false cho outcome approvable; ô xác nhận không được tích sẵn | Xác nhận hồ sơ, tests |
| Hard gate thanh khoản | <80% REJECT; 80–<100% NEED REVIEW; ≥100% mới đánh giá tiếp | engine.py, config, regression tests |
| Trace ID không trùng | Timestamp + full UUID4; 100 IDs cùng giây vẫn unique | engine.py, test_engine.py |
| Approval ID và exact linkage | Timestamp + full UUID4; approval lưu exact trace_id | app.py, test_app_guardrails.py |
| UI compact nhưng audit đầy đủ | UI rút gọn ID; API/JSON/audit giữ full ID | static/app.js, API output |
| Không hành động thật | APPROVED_FOR_PRECHECK; external_submission_executed=false | Founder Gate, approval API tests |
| Demo đúng thể lệ | 3 người; 1 phút mở + 6 phút demo + 3 phút reveal | docs/DEMO_SCRIPT_10_MIN_3_NGUOI.md |

Báo cáo kiểm thử thực tế nằm trong docs/TEST_REPORT.md. Không dùng script 15 phút hoặc tài liệu cũ có Stress/Crisis flow.
