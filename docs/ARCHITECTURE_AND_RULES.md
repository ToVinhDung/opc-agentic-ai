# Architecture & Decision Rules — 2.7.2

## End-to-end flow

TeamPack contract/order text đã mask
→ OpenAI Structured Evidence Extraction
→ deterministic evidence validation
→ deterministic engine: Data Quality Gate
→ Data & Finance Agent
→ deterministic Transaction Reconciliation
→ Risk & Compliance Agent
→ Funding & Partnership Agent
→ Deterministic Decision
→ bounded OpenAI Decision Challenger
→ Founder Gate

Extraction nằm trước engine để tạo evidence cấu trúc. Khi engine phát hiện blocking data, Finance/Risk/Partner/Decision bị dừng và Challenger không chạy; extraction đã thực hiện vẫn chỉ là evidence phụ, không thể vượt Data Quality Gate. Extraction không hợp lệ không được đưa vào engine; Challenger không được thay recommendation.

## Data authority

- 04_CONTRACTS là nguồn hợp đồng và selector.
- 06_ORDERS + 07_INVOICES là nguồn authoritative cho timing, revenue, cost và Contract Cashflow của hợp đồng.
- 08_BANK_TXN chỉ được liên kết vào case khi reconciliation có bằng chứng exact.
- 09_CASHFLOW là bối cảnh doanh nghiệp vì không có contract_id.
- 10_CREDIT_PROFILE chỉ được dùng khi mapping sang đúng hợp đồng được chứng minh.
- Founder phải sửa workbook rồi upload lại; prototype không ghi correction vào dữ liệu nguồn.

## Data Quality Gate

- Validator tạo một issue riêng cho từng sheet, record và field.
- BLOCKING: thiếu dữ liệu cần để tính hoặc truy vết; trả NEED MORE DATA và khóa downstream.
- WARNING: workflow chạy nhưng nêu giới hạn bằng chứng.
- OPTIONAL: không ảnh hưởng quyết định hiện tại.
- Data Quality là tab mặc định trong hộp Chi tiết; danh sách nhóm theo sheet và scroll nội bộ.
- OpenAI không quyết định field nào thiếu.

## Structured Evidence trước engine

OpenAI chỉ trích ba tín hiệu từ văn bản đã mask:

1. performance_bond_required;
2. deployment_scope_provinces;
3. collection_timing_signal.

Output phải theo schema và gắn source ID, quote, confidence, fingerprint. Validator deterministic xác nhận:

- fingerprint được ràng buộc với Trace ID duy nhất và thuộc đúng lượt chạy;
- đủ đúng ba field;
- source ID nằm trong whitelist của packet;
- quote là substring chính xác của source;
- confidence đạt ngưỡng khi trạng thái SUPPORTED;
- value phù hợp ngữ nghĩa và không được gắn cho NOT_STATED.

Chỉ evidence đã validated mới được kích hoạt bond analysis hoặc rollout risk. Nếu extraction unavailable/invalid, deterministic numbers vẫn được tính từ dữ liệu bảng, nhưng một kết quả approvable bị cap ở NEED REVIEW. REJECT và NEED MORE DATA không bị làm nhẹ đi.

## Contract Cashflow và liquidity gate

- Cost ước tính được ghi tại tháng order.
- Receipt dùng paid_date của invoice đã trả, due_date của invoice còn lại hoặc order due date nếu chưa có invoice.
- Mỗi order/invoice chỉ được tính một lần.
- Funding gap là đáy lũy kế của Contract Cashflow.
- Immediate liquidity need cộng cash impact bảo lãnh khi validated evidence cho thấy hợp đồng yêu cầu.
- Funding coverage dưới 80% → REJECT.
- Funding coverage từ 80% đến dưới 100% → NEED REVIEW.
- Funding coverage từ 100% trở lên → tiếp tục đánh giá margin, risk và partner.

OpenAI không tính hoặc sửa bất kỳ số tiền nào.

## Transaction Reconciliation

### Route

08_BANK_TXN → 07_INVOICES → 06_ORDERS → 04_CONTRACTS

### Matching policy

- L1 explicit reference: giao dịch chứa đúng invoice_id tồn tại.
- L2 exact facts: chỉ dùng khi không có explicit reference và có duy nhất một invoice khớp chính xác amount + counterparty + paid_date.
- Nhiều ứng viên → AMBIGUOUS.
- Không đủ bằng chứng → UNMATCHED.
- Không fuzzy text match, không similarity score và không để OpenAI đoán.
- Reverse check: invoice Paid không có incoming Credit đối ứng tạo cảnh báo RR-REC-001.

Một match thuộc hợp đồng khác không được đưa vào case đang chọn. Incoming chưa map được đánh dấu excluded khỏi decision-grade contract cash. Enterprise anomaly TXN-006/TXN-007 được giữ ở enterprise scope nếu không có lineage.

Raw counterparty ID chỉ dùng nội bộ cho exact matching. Browser/Decision JSON chỉ nhận counterparty token đã mask. UI không có nhánh riêng cho bất kỳ mã TXN nào; nó hiển thị `match_status`, `included_in_selected_contract` và `scope/scopes` do backend tạo.

Anomaly rủi ro cao có exact lineage tới hợp đồng vẫn giữ CASE linkage, đồng thời mang ENTERPRISE + REVIEW. Chỉ anomaly không có lineage mới là enterprise-only.

## Risk và Founder evidence gate

Case risk và enterprise risk là hai phạm vi riêng. Nếu enterprise anomaly chưa được Founder xác minh, decision có thể vẫn hiển thị kết quả deterministic nhưng approval_allowed=false. Chỉ evidence TXN đã xác minh mới mở Approve cho một kết quả vốn approvable; evidence này không thể override REJECT hoặc NEED REVIEW.

## Deterministic Decision và Challenger

Decision priority:

1. Blocking data issue → NEED MORE DATA.
2. Funding coverage dưới 80% → REJECT.
3. Funding coverage 80%–dưới 100% → NEED REVIEW.
4. Từ 100% trở lên → đánh giá margin, risk và partner.

Decision Challenger chạy sau engine, trên snapshot đã mask. Recommendation phải exact-match deterministic decision; fingerprint, scenario và financial/risk evidence echo phải khớp. Sai guardrail → BLOCKED_BY_VALIDATION.

## Audit identity

- Trace ID: TRACE-YYYYMMDD-HHMMSS-UUID4HEX.
- Approval ID: APR-YYYYMMDD-HHMMSS-UUID4HEX.
- UUID đầy đủ nằm trong backend, API JSON và audit log.
- UI chỉ dùng compact label để tránh chiếm không gian.
- Approval record lưu exact full trace_id của run nguồn.

## Phạm vi và ranh giới

- Live TeamPack only; không Stress/Crisis UI ở Bán kết.
- Partner Matrix là mô phỏng tiền kiểm; không gọi API ngân hàng.
- Founder approval chỉ là APPROVED_FOR_PRECHECK.
- external_submission_executed=false.
