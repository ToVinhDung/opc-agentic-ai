# Judge Q&A Playbook — 2.7.2

**OpenAI là chức năng lõi nào?**  OpenAI trích ba evidence phi cấu trúc trước engine: yêu cầu bảo lãnh, số tỉnh triển khai và tín hiệu thời điểm thu tiền. Chỉ evidence qua deterministic validation mới kích hoạt bond/rollout rules. Sau engine, Challenger chỉ diễn giải và kiểm tra consistency.

**Nếu bỏ OpenAI thì hệ thống còn chạy không?**  Data Quality, Finance Math, reconciliation và deterministic risk vẫn chạy để Founder thấy bằng chứng. Nhưng một kết quả vốn approvable bị cap tại NEED REVIEW và khóa Approve vì thiếu validated structured evidence. REJECT và NEED MORE DATA giữ nguyên.

**Vì sao không để LLM tính tiền hoặc quyết định?**  Công thức tài chính, matching chứng từ và risk appetite phải tái lập, kiểm toán được. OpenAI chỉ xử lý text có schema; deterministic code và Founder giữ authority.

**Làm sao chứng minh OpenAI không bịa hoặc dùng lại output cũ?**  Server giữ source map, kiểm tra source_id nằm trong whitelist và quote là substring exact của source. Fingerprint được gắn với Trace ID duy nhất; confidence, câu phủ định và semantic rule cũng phải pass. Sai một mục hoặc replay output từ run trước thì evidence bị loại.

**Risk Agent đối soát invoice thế nào?**  Lớp 1 tìm exact invoice_id trong bank reference. Nếu không có explicit reference, lớp 2 chỉ match khi amount, counterparty và paid_date khớp chính xác với duy nhất một invoice. Không có fuzzy guess; nhiều ứng viên là AMBIGUOUS.

**TXN-002 được xử lý ra sao?**  Trong TeamPack hiện tại, đây là incoming chưa có invoice đối ứng đủ căn cứ, nên backend trả UNMATCHED/EXCLUDED và không cộng vào decision-grade contract cash. UI không hard-code TXN-002; nếu TeamPack mới cung cấp exact lineage hợp lệ thì trạng thái sẽ thay đổi theo backend.

**TXN-006/TXN-007 có thuộc CON-004 không?**  Không thể khẳng định khi thiếu lineage 08→07→06→04. Chúng được giữ ở enterprise anomaly scope. Founder phải kiểm tra bằng chứng rồi mới tick TXN đã xác minh.

**Nếu một giao dịch bất thường có exact lineage thì sao?**  Nó vẫn giữ CASE linkage tới hợp đồng, đồng thời mang ENTERPRISE + REVIEW. Hệ thống không xóa quan hệ case và cũng không cộng tiền hai lần.

**Nếu Founder tick xác minh thì có override REJECT không?**  Không. Evidence này chỉ gỡ khóa anomaly cho outcome vốn approvable; không đổi Finance Math, hard gate, REJECT hoặc NEED REVIEW.

**Counterparty có bị lộ trên dashboard/export không?**  Raw identifier chỉ được dùng server-side cho exact matching. Browser và Decision JSON chỉ nhận counterparty token đã mask.

**Vì sao Trace ID không trùng khi chạy cùng giây?**  Mỗi ID dùng timestamp + UUID4 đầy đủ. UI rút gọn cho dễ đọc, còn API và audit giữ toàn bộ UUID.

**Approval có thể gắn nhầm run không?**  Không. Mỗi approval có UUID riêng và record lưu exact full trace_id của run nguồn.

**Tại sao hợp đồng báo thiếu hồ sơ tín dụng dù sheet có dòng credit?**  Có credit row không đồng nghĩa row đó thuộc hợp đồng đang chọn. Thiếu ở đây là thiếu record/linkage contract-specific, không nhất thiết là thiếu một cột. Engine không mượn 950M/420M của hợp đồng khác.

**Funding gap khác immediate liquidity need thế nào?**  Funding gap là đáy lũy kế Contract Cashflow. Immediate liquidity need cộng thêm cash impact bảo lãnh khi validated evidence cho thấy hợp đồng yêu cầu.

**Hard gate hoạt động thế nào?**  Funding coverage dưới 80% → REJECT; 80%–dưới 100% → NEED REVIEW; từ 100% mới tiếp tục. Margin không được dùng để che một thiếu hụt thanh khoản.

**Có đếm trùng order cost không?**  Không. Cost từ 06_ORDERS được ghi một lần; receipts từ invoice liên kết. 09_CASHFLOW chỉ là enterprise context.

**Partner Matrix có phải ngân hàng đã duyệt?**  Không. Đây là precheck mô phỏng từ TeamPack; prototype không gọi API ngân hàng và không gửi hồ sơ.

**Vì sao không có Stress/Crisis?**  Phạm vi Bán kết khóa vào Live TeamPack thật. Crisis Card để dành cho vòng sau, tránh trộn giả định với hồ sơ hiện hành.

**Nếu mất mạng trong demo?**  Hiển thị đúng safe_fallback; không giả lập OpenAI. Trình bày deterministic artifacts và nói rõ outcome approvable đang bị cap NEED REVIEW.

**Điểm khác biệt chính?**  Một nguồn dữ liệu thật được kiểm tra đa sheet, trích evidence có validation, tính toán deterministic, reconcile không đoán, tạo audit ID không trùng và giữ Founder trong vòng phê duyệt.
