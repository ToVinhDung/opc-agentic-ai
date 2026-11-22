# START HERE — checklist trước demo

1. Thu hồi và tạo mới bất kỳ API key nào từng xuất hiện trong ảnh, chat hoặc màn hình chia sẻ.
2. Ultimate dùng http://127.0.0.1:8766; không mở nhầm bản legacy trên cổng 8765.
3. Chạy START_OPENAI_LIVE.bat và dán key tại prompt bảo mật.
4. Upload duy nhất data/MISTalent2026_OPC_AgenticAI_TeamPack_v3.xlsx.
5. Chọn hợp đồng, mở **Xác nhận hồ sơ** và kiểm tra trước khi tích. Cả bốn ô phải để trống khi vừa mở hoặc đổi hợp đồng; với luồng chuẩn, tích ba mục hồ sơ bắt buộc rồi mới chạy.
6. Sau khi chạy, mở Chi tiết tại Data & OpenAI Control. Data Quality phải là tab mặc định; OpenAI Extraction phải có ba trường evidence; OpenAI Guardrails phải hiện trạng thái extraction và challenger của chính lượt chạy.
7. Phần **Chi tiết đối soát** đã được ẩn khỏi dashboard. Dùng Risk & Controls và ba lý do trên Decision Card để trình bày kết quả; không nói giao dịch thuộc một hợp đồng nếu backend không có lineage. Nếu demo kết quả approvable, chỉ tích **Giao dịch đã xác minh** sau khi đã kiểm tra bằng chứng; nếu chưa tích, Approve phải bị khóa.
8. Kiểm tra UI chỉ hiện Trace/Approval ID rút gọn; Decision JSON và audit phải giữ ID đầy đủ, approval phải liên kết exact trace_id.
9. Nếu cần demo NEED MORE DATA, tạo bản sao TeamPack ngoài gói, xóa một trường bắt buộc, upload và xem Data Quality. Sửa bản sao hoặc upload lại file gốc; không lưu workbook lỗi vào package.
10. Nếu OpenAI hoặc mạng lỗi, chạy START_OFFLINE_DEMO.bat. Nói đúng: deterministic analysis vẫn chạy, nhưng kết quả approvable bị hạ xuống NEED REVIEW; REJECT và NEED MORE DATA giữ nguyên.
11. Không demo Stress/Crisis trong vòng Bán kết.
12. Không mở .env, API key, Usage page hoặc raw log chứa thông tin nhạy cảm khi trình chiếu.

Kịch bản sử dụng là docs/DEMO_SCRIPT_10_MIN_3_NGUOI.md: 1 phút mở cảnh + 6 phút live demo + 3 phút Decision Reveal. Không dùng script 15 phút.

Thông điệp chốt: một TeamPack thật được kiểm tra, trích xuất evidence, tính toán, đối soát và ra quyết định có thể truy vết; OpenAI bị giới hạn và Founder giữ quyền phê duyệt cuối.
