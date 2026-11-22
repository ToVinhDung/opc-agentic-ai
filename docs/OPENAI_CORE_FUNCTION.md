# OpenAI Core Function — Extraction + Challenger

OpenAI có hai nhiệm vụ có ranh giới rõ ràng. Finance Math, reconciliation, hard gate và approval authority luôn deterministic.

## 1. Structured Evidence Extraction — trước engine

### Mục đích

Biến phần mô tả/điều khoản tự do trong hợp đồng và order thành ba tín hiệu có cấu trúc mà rule engine có thể kiểm tra:

- performance_bond_required;
- deployment_scope_provinces;
- collection_timing_signal.

### Input control

- Chỉ gửi source text cần thiết, đặt dưới alias SRC-xxx.
- Contract/customer identifier được token hóa; source map thật chỉ giữ phía server.
- Packet có fingerprint SHA-256 gắn với Trace ID duy nhất của chính lượt extraction; output từ run cũ không thể dùng lại cho run mới có cùng nội dung.
- Không gửi API key, raw bank counterparty ID, bảng giao dịch hoặc số liệu ngoài nhiệm vụ.

### Structured Output

Mỗi field phải có status, value, confidence, source_id và quote. OpenAI không được bổ sung field tự do.

### Deterministic validation

Validator kiểm tra fingerprint, đúng ba field, enum/type, source whitelist, exact quote, confidence threshold, câu phủ định và semantic consistency. `performance_bond_required=true` không thể pass câu “no performance bond/không yêu cầu bảo lãnh”; tín hiệu collection phải có cả ngữ cảnh thanh toán và mốc thời gian. NOT_STATED không được mang value hoặc quote. Chỉ validated evidence mới vào engine.

Nếu extraction sai hoặc API lỗi, hệ thống ghi trạng thái thật và không dùng output. Một deterministic outcome vốn approvable bị hạ xuống NEED REVIEW; REJECT và NEED MORE DATA giữ nguyên.

## 2. Bounded Decision Challenger — sau engine

### Mục đích

Diễn giải Decision Card từ snapshot đã mask và kiểm tra tính nhất quán của quyết định deterministic.

### Guardrails

1. Đúng ba reasons.
2. Recommendation exact-match rule engine.
3. Không vượt upper bound của rule engine.
4. Fingerprint echo đúng lượt hiện tại.
5. Scenario echo khớp.
6. Financial/risk evidence echo khớp.
7. Không rò restricted data.
8. Có human confirmation.

Sai bất kỳ check nào → BLOCKED_BY_VALIDATION. Challenger không tính lại tiền, không sửa recommendation và không mở quyền Approve.

## Hiển thị

Nút Chi tiết mở ba tab:

- Data Quality — mặc định; chỉ deterministic validator quyết định dữ liệu thiếu.
- OpenAI Extraction — ba evidence, source alias, quote, confidence và trạng thái validation.
- OpenAI Guardrails — trạng thái validation riêng cho Extraction và Challenger.

## Vì sao OpenAI là chức năng lõi nhưng vẫn an toàn

Structured Evidence có thể trực tiếp kích hoạt bond analysis và rollout risk sau khi qua deterministic validation. Nếu bỏ OpenAI, hệ thống không tự giả evidence và không cho hoàn tất một kết quả approvable. Đồng thời OpenAI vẫn không được tính số tài chính, reconcile giao dịch, quyết định hoặc phê duyệt; các giới hạn này bảo toàn auditability.

## Những điều không được tuyên bố

- Không nói OpenAI đọc toàn bộ workbook.
- Không nói OpenAI match bank transaction.
- Không nói OpenAI xác nhận hạn mức ngân hàng.
- Không nói safe_fallback tương đương live API.
- Không nói OpenAI có thể override Founder hoặc hard gate.
