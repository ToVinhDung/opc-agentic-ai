# Test Report — OPC Agentic AI Ultimate 2.7.2

## Kết quả đã chạy

Lệnh:

    python -m unittest discover -s tests -v

Kết quả cuối trên worktree đã hợp nhất: **69/69 PASS**.

Các syntax check đã chạy và PASS:

    python -m py_compile app.py engine.py openai_client.py evidence_extraction.py
    node --check static/app.js
    node --check tests/ui_smoke.mjs

HTTP integration cũng PASS:

- health và index trả HTTP 200;
- DOM có đủ ba tab Data Quality / OpenAI Extraction / OpenAI Guardrails;
- bootstrap đọc năm hợp đồng;
- CON-004 trả REJECT;
- CON-005 offline trả NEED REVIEW;
- 10 lượt liên tiếp tạo 10/10 Trace ID, 10/10 extraction fingerprint và 10/10 challenger fingerprint unique.
- bốn ô Xác nhận hồ sơ mặc định trống; khi chưa tích, API trả NEED MORE DATA với đúng ba evidence block;
- khi tích ba evidence hồ sơ bắt buộc, CON-004 trả REJECT và reconciliation vẫn trả bốn bản ghi theo đúng tuyến nguồn.

Root packaging workflow vẫn phải chạy lại các lệnh trên sau thay đổi cuối cùng và chỉ cập nhật con số nếu bộ test thay đổi.

## Coverage mục 4 — Audit IDs

- 100 Trace ID được tạo trong cùng một giây vẫn unique và đều giữ full UUID.
- Nhiều Approval ID cùng giây không trùng.
- Approval record lưu exact full trace_id của đúng run.
- API không cho Approve một REJECT hoặc NEED REVIEW.

## Coverage mục 5 — Transaction Reconciliation

- TXN-004 có lineage đầy đủ TXN-004 → INV-001 → ORD-001 → CON-001.
- L2 chỉ chấp nhận duy nhất một match exact amount + counterparty + paid_date.
- L2 từ chối trường hợp ambiguous.
- UI không hard-code TXN-002 hay bất kỳ mã giao dịch nào; status/scope lấy từ backend.
- Match thuộc hợp đồng khác không được đưa vào selected-contract scope.
- TXN-002 giữ unmatched/excluded.
- Paid invoice không có incoming Credit match tạo reverse warning.
- TXN-006/TXN-007 giữ enterprise scope; evidence thay đổi trạng thái review.
- Synthetic high-risk incoming có exact lineage giữ đồng thời CASE + ENTERPRISE + REVIEW; anomaly unmatched vẫn enterprise-only.
- Enterprise anomaly chưa xác minh khóa Approve cho outcome approvable; sau evidence xác minh mới mở, không override REJECT/NMD.

## Coverage mục 6 — OpenAI Pipeline

- Validated extraction chạy trước deterministic engine.
- Challenger chạy sau engine.
- Evidence CON-004 kích hoạt bond và rollout risk sau validation.
- Quote không nằm trong source bị block.
- Stale fingerprint bị block.
- Hai run có nội dung giống nhau vẫn có extraction/challenger fingerprint khác vì ràng buộc Trace ID; replay run A sang run B bị block.
- Confidence dưới ngưỡng bị block.
- Province value không khớp quote bị block.
- NOT_STATED không được mang value/quote.
- Câu phủ định về bảo lãnh không thể kích hoạt `performance_bond_required=true`; `false` cần phủ định rõ.
- Collection timing cần ngữ cảnh thanh toán và mốc thời gian; OTHER_EXPLICIT không chấp nhận quote chung chung.
- Offline mode cap outcome approvable tại NEED REVIEW.
- Offline mode không làm nhẹ deterministic REJECT.

## Regression coverage được giữ

- Baseline Finance Math và guarantee cash separation.
- Không double count cost/cashflow.
- Multi-contract mapping không dùng global 950M/420M fallback.
- Fixture kiểm thử tạo CON-006 tại runtime: bản có đủ liên kết chạy được, còn contract-only row bị NEED MORE DATA. Workbook phát hành vẫn chỉ chứa năm hợp đồng gốc.
- Multi-sheet missing-data giữ riêng từng issue.
- Liquidity hard gate ba band.
- Margin wording thấp hơn/bằng/cao hơn mục tiêu.
- PartnerX eligibility hard gate.
- Masked OpenAI input và Challenger stale-output guardrails.
- Một canonical workbook duy nhất trong release.

## Artifact QA đã xác nhận bằng syntax/unit tests

- Python modules compile.
- static/app.js và browser smoke script hợp lệ cú pháp.
- UI code có ba control tab và vẫn giữ phần tử đối soát ẩn để renderer/runtime không bị thay đổi.
- Nút Chi tiết đối soát được ẩn đúng yêu cầu nhưng dialog, renderer, export và pipeline backend vẫn còn nguyên.
- Selector không còn dòng đếm từ 04_CONTRACTS; biểu đồ và tooltip đã được Việt hóa.
- Biểu đồ giữ tiêu đề `Dòng tiền hợp đồng`, dòng mô tả động `CON-xxx · Đơn hàng (06) + Hóa đơn (07) · triệu VND`, các mốc tháng và thang số tiền.
- Không có chữ `Số dư tiền cuối tháng`, `Trục X` hoặc `Trục Y`; vùng thiếu hụt chỉ được tô dưới điểm hòa vốn 0 và không đổi nguồn `finance.contract_cashflow`.
- Decision export dùng reconciliation payload đã sanitize.

## Chưa tuyên bố đã kiểm thử trong môi trường này

- OpenAI live call bằng API key thật: chưa chạy vì không sử dụng secret trong quá trình đóng gói.
- Browser smoke execution/render screenshot: đã thử nhưng không hoàn tất vì môi trường không có Chromium hoặc Microsoft Edge binary; script vẫn vượt Node syntax check.
- API ngân hàng: không tồn tại trong prototype và không thuộc phạm vi.

## Known boundaries

- Đây là local decision-support prototype, không phải hệ thống ngân hàng production.
- Partner ranking là precheck mô phỏng từ TeamPack.
- Founder approval không gửi hồ sơ ra ngoài.
- Live API phụ thuộc key, model access, quota và network tại thời điểm demo.
