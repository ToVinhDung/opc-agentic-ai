# Package contents

- START_HERE.md: checklist trước demo bản 2.7.2.
- START_OPENAI_LIVE.bat/.ps1: launcher nhập API key bảo mật.
- START_OFFLINE_DEMO.bat: fail-safe không có OpenAI.
- STOP_ULTIMATE_SERVER.bat: dừng đúng server Ultimate trên cổng 8766.
- app.py: orchestration extraction → engine → challenger và Founder Approval API.
- engine.py: parser, Data Quality, Finance Math, reconciliation, Risk, Partner, deterministic decision và audit IDs.
- evidence_extraction.py: tạo masked extraction packet và deterministic validation cho Structured Evidence.
- openai_client.py: OpenAI Structured Evidence Extraction và bounded Decision Challenger qua Structured Output.
- static/: dashboard local, ba tab control, biểu đồ Dòng tiền hợp đồng có vùng thiếu hụt vốn và không có tên trục X/Y, xác nhận hồ sơ mặc định trống và logic đối soát được giữ sau lớp giao diện đã ẩn.
- data/MISTalent2026_OPC_AgenticAI_TeamPack_v3.xlsx: TeamPack gốc duy nhất; không có bản Complete/Incomplete.
- tests/: regression cho UUID audit, exact approval linkage, reconciliation, OpenAI pipeline, multi-contract, missing-data, liquidity hard gate và các tinh chỉnh UI.
- docs/DEMO_SCRIPT_10_MIN_3_NGUOI.md: kịch bản đúng 3 người trong 10 phút đội chủ động.
- docs/: architecture, OpenAI core, Q&A, traceability, test report và checklist.

Không đóng gói script 15 phút, Crisis/Stress UI, slide/screenshot cũ, API key, .env thật hoặc runtime log.
