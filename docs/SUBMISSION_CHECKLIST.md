# Submission checklist — 2.7.2

- [x] Prototype chạy local, không phụ thuộc CDN.
- [x] Chỉ một canonical TeamPack; không có Complete/Incomplete workbook.
- [x] Selector hợp đồng đọc động từ 04_CONTRACTS.
- [x] Data Quality Gate báo riêng từng field/record/sheet và Data Quality là tab mặc định.
- [x] Contract Cashflow dùng order/invoice của đúng hợp đồng.
- [x] Hard gate thanh khoản độc lập với margin.
- [x] Trace ID dùng timestamp + full UUID; UI chỉ rút gọn.
- [x] Approval ID dùng timestamp + full UUID và lưu exact trace_id.
- [x] Reconciliation deterministic theo 08→07→06→04.
- [x] L1 explicit invoice reference và L2 unique exact facts; không fuzzy guess.
- [x] UI không hard-code mã TXN; status/scope lấy từ backend.
- [x] Anomaly có exact lineage giữ CASE + ENTERPRISE; anomaly không lineage là enterprise-only.
- [x] Unmatched/ambiguous/excluded records hiển thị rõ.
- [x] Reverse warning cho Paid invoice thiếu Credit match.
- [x] Raw counterparty không xuất hiện trong DOM/Decision export.
- [x] Enterprise anomaly chưa xác minh khóa Approve.
- [x] OpenAI Structured Evidence Extraction chạy trước engine.
- [x] Fingerprint gắn Trace ID; source/quote/confidence/phủ định/semantic validation chạy deterministic.
- [x] Bounded Decision Challenger chạy sau engine và exact-match recommendation.
- [x] Offline/invalid OpenAI cap outcome approvable ở NEED REVIEW; REJECT/NMD giữ nguyên.
- [x] Founder approval chỉ APPROVED_FOR_PRECHECK; external submission=false.
- [x] Dashboard không có Stress/Crisis UI.
- [x] Kịch bản thuyết trình đúng 3 người và khung 1+6+3 phút.
- [x] Không chứa API key thật, .env thật hoặc runtime log.

## Kiểm tra ngay trước khi đóng ZIP

- [ ] Chạy python -m unittest discover -s tests -v trên chính thư mục sắp đóng gói.
- [ ] Chạy Python compilation và Node syntax check.
- [ ] Xác nhận package có đúng một file .xlsx.
- [ ] Xác nhận không có DEMO_SCRIPT_15_MIN hoặc tài liệu Main/Missing/Crisis cũ.
- [ ] Nếu có API key và mạng, chạy một live extraction + challenger; nếu không thì ghi rõ chưa kiểm thử live.
- [ ] Mở dashboard tại đúng cổng 8766 và không để lộ secret.

## Mang theo khi thi

- Laptop chính và sạc.
- ZIP đã kiểm tra trên USB/drive dự phòng.
- API key mới trong password manager.
- Chỉ dùng docs/DEMO_SCRIPT_10_MIN_3_NGUOI.md; nếu đội tự làm slide, phải đồng bộ lại với bản 2.7.2 trước khi trình chiếu.
