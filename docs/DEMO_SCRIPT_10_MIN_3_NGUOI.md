# Kịch bản thuyết trình 10 phút — 3 thành viên

Kịch bản này dành cho phần đội chủ động trình bày: **1 phút mở cảnh, 6 phút live demo và 3 phút Decision Reveal**. Phần hỏi đáp 5 phút chuẩn bị riêng ở `JUDGE_QA_PLAYBOOK.md`.

## Phân vai

- **Thành viên 1 — Business & Data:** mở bài, upload TeamPack và chứng minh single source of truth.
- **Thành viên 2 — Agent & AI:** trình diễn handoff, đối soát giao dịch và OpenAI Structured Evidence Extraction.
- **Thành viên 3 — Decision & Governance:** công bố quyết định, hard gate, phương án đối tác và Founder Approval Gate.

Không đọc nguyên văn toàn bộ nội dung trên màn hình. Mỗi người nói theo thông điệp chính, đồng thời một người phụ trách chuột để tránh ngắt quãng.

## 0:00–1:00 — Mở cảnh · Thành viên 1

**Lời nói đề xuất**

> Một Founder của OPC phải đồng thời đọc hợp đồng, kiểm soát dòng tiền, kiểm tra giao dịch và làm việc với đối tác tài chính. Khi dữ liệu nằm rải rác trong TeamPack, quyết định nhận hợp đồng dễ chậm hoặc thiếu bằng chứng. OPC Agentic AI biến một TeamPack thật thành Financial Snapshot, Risk Report và Decision Card qua ba Agent; AI hỗ trợ trích xuất và đối biện, còn Founder giữ quyền quyết định cuối cùng.

**Thông điệp phải chốt:** Đây là Agentic MIS chạy dữ liệu thật, không phải chatbot và không tự phê duyệt tín dụng.

## 1:00–3:20 — Live demo: nguồn dữ liệu thật · Thành viên 1

1. Mở dashboard và chỉ trạng thái backend, OpenAI, model và đồng hồ hệ thống.
2. Upload duy nhất `data/MISTalent2026_OPC_AgenticAI_TeamPack_v3.xlsx`.
3. Chỉ tên file, hash nguồn, số sheet và danh sách hợp đồng được đọc động từ `04_CONTRACTS`.
4. Chọn `CON-004 – Liên hiệp HTX Xanh`, mở **Xác nhận hồ sơ**. Sau khi kiểm tra, tự tích **Hợp đồng/phạm vi**, **Bảng tuổi nợ** và **Kế hoạch triển khai**; giữ **Giao dịch đã xác minh** ở trạng thái chưa tích.
5. Bật OpenAI online và chạy workflow.
6. Trong Input Data, chỉ giá trị hợp đồng 4,2 tỷ, biên 24%, order coverage và dòng tiền hợp đồng được tính từ `06_ORDERS + 07_INVOICES`.

**Lời chuyển**

> Hệ thống không có workbook Complete/Incomplete và không chèn correction trong giao diện. Nếu dữ liệu thật thiếu trường, Founder phải sửa chính bản sao TeamPack rồi upload lại. Mỗi lượt chạy tạo một Trace ID đầy đủ, không bị ghi đè dù chạy liên tiếp trong cùng một giây.

## 3:20–7:00 — Live demo: Agent, reconciliation và OpenAI · Thành viên 2

### 3:20–4:20 — Ba Agent và handoff

- Data & Finance Agent đọc hợp đồng, order, invoice và tính số tiền bằng deterministic code.
- Risk & Compliance Agent áp rule và đối soát `08_BANK_TXN → 07_INVOICES → 06_ORDERS → 04_CONTRACTS`.
- Decision & Partner Agent chỉ dùng output đã kiểm soát để tạo đúng ba lý do và một điều kiện bảo vệ.

### 4:20–5:20 — Kết quả đối soát trên dashboard

1. Chỉ phần **Risk & Controls** và lý do đối soát đang hiện trực tiếp trên dashboard; không mở cửa sổ chi tiết riêng.
2. Giải thích `TXN-004 → INV-001 → ORD-001 → CON-001` là chuỗi liên kết đầy đủ do backend tạo.
3. `TXN-002` trong TeamPack hiện tại là incoming chưa có invoice đối ứng nên không được tính vào decision-grade contract cash; giao diện không hard-code mã này.
4. `TXN-006/TXN-007` là bất thường phạm vi doanh nghiệp, cần Founder xác minh; hệ thống không tự gán chúng cho CON-004.

**Thông điệp phải chốt:** Matching là deterministic, chỉ nhận exact evidence; trường hợp không chắc chắn được ghi `UNMATCHED/AMBIGUOUS`, tuyệt đối không để AI đoán chứng từ.

### 5:20–7:00 — OpenAI Core Function

1. Mở **Chi tiết** tại Data & OpenAI Control; tab mặc định vẫn là **Data Quality**.
2. Chuyển sang **OpenAI Extraction**: chỉ ba evidence được trích từ văn bản hợp đồng — yêu cầu bảo lãnh, phạm vi số tỉnh và tín hiệu thời điểm thu tiền — kèm source, confidence và trạng thái validation.
3. Chuyển sang **OpenAI Guardrails**: chỉ fingerprint, output có cấu trúc và các kiểm tra trước khi câu chữ AI được dùng.

**Lời nói đề xuất**

> OpenAI nằm trước Finance/Risk để biến mô tả và điều khoản tự do thành evidence có cấu trúc. Rule engine kiểm tra quote, nguồn, confidence, câu phủ định và fingerprint gắn Trace ID trước khi evidence được phép kích hoạt bond analysis hoặc rollout risk. OpenAI không được tính tiền, sửa recommendation hay thay Founder. Sau đó Decision Challenger chỉ được diễn giải nếu khớp tuyệt đối kết quả deterministic.

## 7:00–10:00 — Decision Reveal · Thành viên 3

### 7:00–8:10 — Công bố CON-004

- Margin 24% thấp hơn mục tiêu 28%.
- Contract funding gap 1,216 tỷ; cộng cash impact bảo lãnh tạo immediate liquidity need khoảng 1,304 tỷ.
- Nguồn vốn tiềm năng 950 triệu chỉ bao phủ khoảng 72,8%.
- Hard gate dưới 80% trả **REJECT**, độc lập với margin và câu chữ OpenAI.

> Quyết định của hệ thống là không nhận ở điều kiện hiện tại. Đây không phải phán quyết của AI: rule engine khóa nút Approve, Founder chỉ có thể từ chối hoặc bổ sung bằng chứng rồi chạy lại.

### 8:10–9:05 — Chứng minh đa hợp đồng và hard approval gate

1. Chuyển sang `CON-005`, nhưng **chưa chạy ngay**.
2. Mở **Xác nhận hồ sơ**; bốn ô phải trở về trạng thái chưa tích vì đây là hợp đồng mới. Kiểm tra rồi tích ba bằng chứng hồ sơ bắt buộc.
3. Nhắc lại bằng chứng trên Risk & Controls: TXN-006/TXN-007 là bất thường phạm vi doanh nghiệp, không được tự gán cho hợp đồng. Chỉ sau khi người trình bày xác nhận đã kiểm tra, tích **Giao dịch đã xác minh**. Đây là input human evidence của lượt chạy mới, không phải nút bỏ qua risk.
4. Nhấn chạy lại Agent Workflow.
5. Chỉ kết quả riêng của CON-005:

- Credit mapping là `CR-003`, không dùng hạn mức của CON-004.
- Margin 29% cao hơn mục tiêu.
- Funding coverage khoảng 114,4%.
- Kết quả **CONDITIONAL ACCEPT**; evidence đã xác minh chỉ gỡ khóa enterprise anomaly cho kết quả vốn được phép phê duyệt, không sửa Finance Math hoặc recommendation.

Nếu bỏ tick rồi chạy lại, Decision Card có thể vẫn nêu kết quả deterministic nhưng **Approve phải bị khóa**. Nếu OpenAI không khả dụng, outcome approvable bị hạ xuống **NEED REVIEW** và cũng không được Approve.

### 9:05–9:40 — Founder Gate và audit

- Tick xác nhận điều kiện bảo vệ, nhập tên Founder và phê duyệt precheck trên kết quả được phép. Không nhầm checkbox này với evidence **TXN đã xác minh** đã cung cấp trước lúc chạy.
- Chỉ Approval ID rút gọn trên UI; JSON và audit log giữ ID đầy đủ và liên kết đúng Trace ID.
- Nhấn mạnh `external_submission_executed=false`.

### 9:40–10:00 — Kết

> OPC Agentic AI không thay Founder ra quyết định. Hệ thống làm ba việc có thể kiểm chứng: đọc một nguồn dữ liệu thật, đối soát và tính toán bằng rule deterministic, rồi dùng OpenAI có guardrail để xử lý bằng chứng phi cấu trúc. Kết quả cuối là Decision Card có thể truy vết, có điều kiện và có người chịu trách nhiệm phê duyệt.

## Các điều không được nói sai

- Không gọi Partner Matrix là hạn mức ngân hàng đã phê duyệt; đây là **tiền kiểm mô phỏng**.
- Không nói OpenAI tính cashflow, margin hoặc funding coverage.
- Không nói TXN bất thường thuộc CON-004 nếu reconciliation không có chuỗi liên kết.
- Không dùng lại số liệu cũ `CONDITIONAL ACCEPT` cho CON-004; bản hiện tại trả `REJECT` vì coverage khoảng 72,8%.
- Không demo Crisis/Stress; chức năng đó dành cho vòng sau.
- Không mở API key, file `.env`, cửa sổ Usage hoặc log chứa thông tin nhạy cảm khi trình chiếu.

## Phương án dự phòng nếu OpenAI không khả dụng

Nói đúng trạng thái hiển thị: Finance Math và reconciliation deterministic vẫn được tạo, nhưng hệ thống chuyển sang **NEED REVIEW / OpenAI evidence unavailable** và khóa Approve. Không giả lập rằng API đã gọi thành công.
