# TEAM TSD — OPC Agentic AI Ultimate

Phiên bản 2.7.2 phát triển từ v8 theo ba phương án đã chốt và nhóm tinh chỉnh giao diện tiếng Việt:

1. Mỗi lượt chạy và mỗi hành động Founder có ID kiểm toán riêng bằng timestamp + UUID đầy đủ.
2. Risk Agent đối soát giao dịch theo chuỗi 08_BANK_TXN → 07_INVOICES → 06_ORDERS → 04_CONTRACTS bằng luật exact-match, không đoán gần đúng.
3. OpenAI thực hiện Structured Evidence Extraction trước engine và Decision Challenger có giới hạn sau engine.

Prototype vẫn giữ một TeamPack gốc, phân tích động theo hợp đồng, Data Quality Gate đa sheet, Contract Cashflow deterministic và Founder Approval Gate. OpenAI không được tạo số tiền, sửa số liệu nguồn hoặc tự phê duyệt.

## Chạy nhanh

### OpenAI online — luồng demo chính

1. Nhấp đúp START_OPENAI_LIVE.bat.
2. Dán API key tại prompt bảo mật. Key chỉ tồn tại trong tiến trình server.
3. Mở http://127.0.0.1:8766.
4. Upload data/MISTalent2026_OPC_AgenticAI_TeamPack_v3.xlsx và chọn hợp đồng.
5. Mở **Xác nhận hồ sơ**, kiểm tra rồi tự tích các bằng chứng phù hợp; hệ thống không tích sẵn và sẽ xóa trạng thái khi đổi hợp đồng hoặc TeamPack.
6. Chạy Agent Workflow, sau đó mở Chi tiết để xem ba tab: Data Quality, OpenAI Extraction và OpenAI Guardrails.

Không lưu API key trong source, ảnh, log, slide hoặc gói nộp. Trạng thái OpenAI chỉ được xem là thành công sau khi chính lượt chạy có extraction và challenger vượt validation.

### Không có API key — fail-safe trung thực

Nhấp đúp START_OFFLINE_DEMO.bat. Data Quality, Finance Math, Contract Cashflow, reconciliation, Risk và Partner precheck vẫn chạy deterministic. Tuy nhiên, nếu kết quả deterministic vốn có thể phê duyệt thì hệ thống hạ xuống NEED REVIEW và khóa Approve vì thiếu Structured Evidence đã xác thực. REJECT và NEED MORE DATA được giữ nguyên; hệ thống không dựng output OpenAI giả.

## Một nguồn dữ liệu thật

Gói chỉ chứa data/MISTalent2026_OPC_AgenticAI_TeamPack_v3.xlsx. Không có workbook Complete, Incomplete hoặc bản đã xóa dữ liệu.

- Selector đọc động hợp đồng từ 04_CONTRACTS.
- Customer, order, invoice, credit profile và cashflow được map theo hợp đồng đang chọn.
- Khi thêm hợp đồng mới, selector tự cập nhật nếu hàng hợp đồng hợp lệ.
- Nếu thiếu dữ liệu hoặc liên kết bắt buộc, engine trả NEED MORE DATA và nêu sheet, bản ghi, trường cần bổ sung.
- Prototype không cho nhập correction trực tiếp. Founder sửa workbook bên ngoài rồi upload lại.

## Luồng xử lý 2.7.2

Masked contract/order text → OpenAI Structured Evidence Extraction → deterministic evidence validation → deterministic engine (Data Quality first, rồi Data & Finance → Reconciliation + Risk → Partner + Decision) → bounded OpenAI Challenger → Founder Gate

### OpenAI Structured Evidence Extraction

Trước Finance/Risk, OpenAI chỉ đọc phần văn bản đã mask của hợp đồng và order để trích ba tín hiệu:

- performance_bond_required;
- deployment_scope_provinces;
- collection_timing_signal.

Mỗi tín hiệu phải có trạng thái, giá trị có cấu trúc, source ID, quote và confidence. Fingerprint được gắn với Trace ID duy nhất của lượt chạy để chặn replay. Validator deterministic kiểm tra source whitelist, quote có thật trong nguồn, confidence, câu phủ định và tính hợp lệ ngữ nghĩa. Chỉ evidence đã qua toàn bộ kiểm tra mới được kích hoạt bond analysis hoặc rollout risk.

Data Quality luôn là tab mặc định. Hai tab OpenAI chỉ giải thích extraction và guardrail; chúng không thay thế danh sách dữ liệu thiếu do rule engine tạo.

### Bounded Decision Challenger

Sau khi engine hoàn tất, OpenAI nhận snapshot đã mask để diễn giải đúng ba lý do. Recommendation, scenario fingerprint và financial/risk echo phải khớp chính xác kết quả deterministic. Output sai bị BLOCKED_BY_VALIDATION; OpenAI không được nâng hoặc hạ quyết định.

## Đối soát giao dịch deterministic

Đối soát vẫn chạy deterministic theo tuyến 08 → 07 → 06 → 04 ở mọi lượt phân tích. Điểm truy cập **Chi tiết đối soát** được ẩn để dashboard gọn hơn; kết quả cần hành động tiếp tục xuất hiện trong Risk & Controls, Decision Card và bản JSON đã che dữ liệu nhạy cảm.

- Lớp 1: nhận mã invoice có thật trong reference của giao dịch.
- Lớp 2: chỉ khi không có explicit reference, cho phép match duy nhất nếu amount + counterparty + paid_date khớp chính xác.
- Nếu có nhiều ứng viên hoặc thiếu bằng chứng, giữ UNMATCHED hoặc AMBIGUOUS; không fuzzy guess và không để OpenAI gán chứng từ.
- Paid invoice không có incoming credit đối ứng tạo cảnh báo reverse reconciliation.
- Giao dịch enterprise bất thường không có lineage được tách khỏi phạm vi contract. Nếu có exact lineage, hệ thống giữ đồng thời scope CASE và ENTERPRISE để không làm mất bằng chứng hợp đồng.
- Giao diện không hard-code mã giao dịch; trạng thái luôn lấy từ kết quả reconciliation backend của TeamPack đang chạy.

Raw counterparty ID không được đưa vào DOM hoặc Decision JSON tải xuống; giao diện chỉ nhận token đã mask. Với enterprise anomaly chưa được Founder xác minh, một kết quả vốn approvable vẫn bị khóa Approve. Founder chỉ tick TXN đã xác minh sau khi đã kiểm tra bằng chứng.

## Audit ID không trùng

- Full Trace ID và Approval ID dùng timestamp đến giây + UUID4 32 ký tự.
- UI chỉ rút gọn để dễ đọc; backend, API JSON và audit log giữ nguyên ID đầy đủ.
- Mỗi approval lưu exact full trace_id của đúng lượt chạy, nên các run cùng một giây không ghi đè hoặc trộn audit.

Approval chỉ tạo trạng thái APPROVED_FOR_PRECHECK; external_submission_executed luôn false. Prototype không gửi hồ sơ thật đến ngân hàng.

## Logic tài chính và quyết định

- Contract Cashflow dùng 06_ORDERS và 07_INVOICES của đúng hợp đồng; 09_CASHFLOW chỉ là bối cảnh doanh nghiệp vì không có contract_id.
- Biểu đồ giữ tên **Dòng tiền hợp đồng** và dòng nguồn động theo hợp đồng; vùng đỏ nhạt chỉ thể hiện phần dòng tiền tích lũy dưới điểm hòa vốn 0. Không dùng nhãn “Số dư tiền cuối tháng”, không ghi tên trục X/Y và không đưa ngưỡng dự trữ doanh nghiệp 550 triệu vào chart hợp đồng.
- OpenAI không tính contract value, margin, cashflow, funding gap hoặc funding coverage.
- Funding coverage dưới 80% → REJECT.
- Funding coverage từ 80% đến dưới 100% → NEED REVIEW.
- Funding coverage từ 100% trở lên mới tiếp tục đánh giá margin, risk và partner.
- Partner Matrix chỉ là phương án tiền kiểm mô phỏng, không phải phê duyệt ngân hàng.

Giao diện Bán kết không có Stress test hoặc Crisis Card; hai chức năng này để dành cho phạm vi vòng sau.

## Kiểm thử

Chạy:

    python -m unittest discover -s tests -v

Lượt chạy cuối đạt 69/69 PASS. Python compilation, static/app.js và tests/ui_smoke.mjs đều vượt syntax check. HTTP integration xác nhận năm hợp đồng, ô xác nhận trống trả NEED MORE DATA đúng thiết kế, khi Founder tích ba bằng chứng bắt buộc thì CON-004 trả REJECT, và đối soát vẫn có đủ bản ghi/tuyến dữ liệu dù nút chi tiết đã ẩn. Browser smoke chưa hoàn tất vì môi trường không có Chromium/Microsoft Edge binary; OpenAI live không được tuyên bố đã chạy. Xem docs/TEST_REPORT.md.

## Tài liệu

- START_HERE.md: checklist trước demo.
- docs/DEMO_SCRIPT_10_MIN_3_NGUOI.md: đúng 3 người, 1 phút mở + 6 phút live demo + 3 phút Decision Reveal.
- docs/ARCHITECTURE_AND_RULES.md: data authority, reconciliation, OpenAI evidence và hard gate.
- docs/OPENAI_CORE_FUNCTION.md: hai điểm can thiệp OpenAI và fail-safe.
- docs/JUDGE_QA_PLAYBOOK.md: câu hỏi phản biện.
- docs/TEST_REPORT.md: bằng chứng test và giới hạn chưa kiểm thử.

Không dùng lại kịch bản 15 phút hoặc screenshot/slide cũ có luồng Main/Missing/Crisis.
