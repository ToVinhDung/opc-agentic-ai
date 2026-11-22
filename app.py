from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import sys
import threading
import time
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from engine import DATA_QUALITY_SHEETS, DecisionEngine, TeamPack, TeamPackError, _trace_event, make_audit_id
from evidence_extraction import build_extraction_packet, extraction_api_input, validate_extraction_output
from openai_client import extract_structured_evidence, is_configured, model_name, review_decision


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
DEFAULT_DATA = ROOT / "data" / "MISTalent2026_OPC_AgenticAI_TeamPack_v3.xlsx"
RUNTIME_LOG_DIR = ROOT / "runtime_logs"
AUDIT_LOG = RUNTIME_LOG_DIR / "audit.jsonl"
APP_VERSION = "2.7.2-cashflow-clarity"


def append_audit(records: list[dict[str, Any]] | dict[str, Any]) -> None:
    RUNTIME_LOG_DIR.mkdir(parents=True, exist_ok=True)
    items = records if isinstance(records, list) else [records]
    with AUDIT_LOG.open("a", encoding="utf-8") as handle:
        for record in items:
            safe_record = dict(record)
            safe_record.pop("api_key", None)
            safe_record.pop("authorization", None)
            handle.write(json.dumps(safe_record, ensure_ascii=False, separators=(",", ":")) + "\n")


def load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv()


class AppState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.pack = TeamPack.from_path(DEFAULT_DATA)
        self.approvals: dict[str, dict[str, Any]] = {}
        self.runs: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _contract_catalog(pack: TeamPack) -> list[dict[str, Any]]:
        """Build the selector catalog from the currently loaded workbook only."""
        customers_by_id = {
            row.get("customer_id"): row
            for row in pack.rows("03_CUSTOMERS")
            if row.get("customer_id")
        }
        contracts: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for row in pack.contracts():
            contract_id = str(row.get("contract_id") or "").strip()
            if not contract_id:
                raise TeamPackError("04_CONTRACTS có bản ghi nhưng thiếu contract_id; không thể tạo danh sách hợp đồng.")
            if contract_id in seen_ids:
                raise TeamPackError(f"04_CONTRACTS có contract_id trùng lặp: {contract_id}.")
            seen_ids.add(contract_id)
            customer_id = row.get("customer_id")
            customer_name = (customers_by_id.get(customer_id) or {}).get("customer_name")
            display_name = customer_name or customer_id or row.get("description") or "Chưa có tên khách hàng"
            contracts.append(
                {
                    "contract_id": contract_id,
                    "customer_id": customer_id,
                    "customer_name": customer_name,
                    "display_name": f"{contract_id}- {display_name}",
                    "description": row.get("description"),
                    "status": row.get("status"),
                    "contract_value": row.get("contract_value"),
                }
            )
        if not contracts:
            raise TeamPackError("04_CONTRACTS không có hợp đồng nào để phân tích.")
        return contracts

    def bootstrap(self) -> dict[str, Any]:
        with self.lock:
            contracts = self._contract_catalog(self.pack)
            return {
                "app": "OPC Agentic AI Decision Cockpit",
                "version": APP_VERSION,
                "data": {
                    "file_name": self.pack.source_name,
                    "sha256_short": self.pack.source_hash,
                    "sheet_count": len(self.pack.sheet_names),
                    "required_sheets_ok": not (set(DATA_QUALITY_SHEETS) - set(self.pack.sheet_names)),
                    "missing_required_sheets": sorted(set(DATA_QUALITY_SHEETS) - set(self.pack.sheet_names)),
                    "missing_contract_values": [
                        row["contract_id"]
                        for row in contracts
                        if not row.get("contract_value")
                    ],
                    "contract_count": len(contracts),
                },
                "contracts": contracts,
                "openai": {
                    "configured": is_configured(),
                    "model": model_name(),
                    "role": "Structured Evidence Extractor + bounded Decision Challenger",
                },
            }

    def upload(self, filename: str, content: bytes) -> dict[str, Any]:
        pack = TeamPack.from_bytes(content, filename)
        # Validate the selector catalog before replacing the active source.
        # A failed upload therefore leaves the last valid TeamPack untouched.
        self._contract_catalog(pack)
        with self.lock:
            self.pack = pack
        return self.bootstrap()

    def analyze(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_started = time.perf_counter()
        contract_id = str(payload.get("contract_id") or "").strip()
        if not contract_id:
            raise TeamPackError("Hãy chọn một hợp đồng từ TeamPack đang được tải.")

        with self.lock:
            pack = self.pack
            available_contracts = {item["contract_id"] for item in self._contract_catalog(pack)}
            if contract_id not in available_contracts:
                raise TeamPackError(
                    f"Hợp đồng {contract_id} không còn trong TeamPack đang được tải; hãy chọn lại hợp đồng."
                )
            contract = next(
                dict(row)
                for row in pack.contracts()
                if str(row.get("contract_id") or "").strip() == contract_id
            )
            orders = [
                dict(row)
                for row in pack.rows("06_ORDERS")
                if str(row.get("contract_id") or "").strip() == contract_id
            ]

        use_openai = bool(payload.get("use_openai"))
        trace_created_at = datetime.now().astimezone()
        trace_id = make_audit_id("TRACE", trace_created_at)
        extraction_packet = build_extraction_packet(contract, orders, trace_id)
        masked_extraction_input = extraction_api_input(extraction_packet)
        extraction_started_at = datetime.now().astimezone()
        extraction_started = time.perf_counter()
        extraction: dict[str, Any] = {
            "called": False,
            "status": "disabled_for_run",
            "model": model_name(),
            "response_id": None,
            "input_masked": masked_extraction_input,
            "output": None,
            "validated_evidence": {},
            "validation": [],
        }
        structured_evidence: dict[str, Any] = {}

        if use_openai:
            try:
                returned = extract_structured_evidence(masked_extraction_input)
                validated = validate_extraction_output(returned.get("output"), extraction_packet)
                extraction.update(returned)
                extraction.update(
                    {
                        "status": (
                            "validated"
                            if validated["status"] == "VALIDATED"
                            else "blocked_by_validation"
                        ),
                        "input_masked": masked_extraction_input,
                        "validated_evidence": validated["validated_evidence"],
                        "validation": validated["checks"],
                    }
                )
                if extraction["status"] == "validated":
                    structured_evidence = extraction["validated_evidence"]
            except TeamPackError as exc:
                extraction.update(
                    {
                        "called": False,
                        "status": "safe_fallback",
                        "error": str(exc),
                        "validation": [
                            {
                                "check": "extractor_fail_safe",
                                "passed": True,
                                "note": (
                                    "Không giả lập evidence; Finance Math vẫn chạy deterministic "
                                    "nhưng kết quả approvable bị hạ xuống NEED REVIEW."
                                ),
                            }
                        ],
                    }
                )
        else:
            extraction["validation"] = [
                {
                    "check": "offline_mode_disclosed",
                    "passed": True,
                    "note": (
                        "OpenAI Evidence Extractor bị tắt; Finance Math vẫn chạy deterministic "
                        "nhưng không thể hoàn tất một quyết định approvable."
                    ),
                }
            ]

        extraction_ms = (time.perf_counter() - extraction_started) * 1000
        result = DecisionEngine(
            pack,
            structured_evidence=structured_evidence,
            trace_id=trace_id,
        ).analyze(payload)
        extraction_event = _trace_event(
            result["trace_id"],
            "OpenAI Evidence Extractor",
            "extract",
            "04_CONTRACTS.description/payment_terms + 06_ORDERS.delivery_note",
            extraction["status"],
            (
                "Ba trường evidence đã được kiểm tra fingerprint theo run, quote, source, confidence và semantic."
                if extraction["status"] == "validated"
                else "Không có structured evidence hợp lệ; không bịa dữ liệu và kích hoạt fail-safe."
            ),
            openai_service=f"Responses API / {model_name()}",
            duration_ms=extraction_ms,
        )
        extraction_event["timestamp"] = extraction_started_at.isoformat(timespec="microseconds")
        result["workflow"].insert(0, extraction_event)

        extraction_ready = extraction["status"] == "validated"
        rule_engine_decision = result["decision"]["decision_type"]
        result["decision"]["rule_engine_decision"] = rule_engine_decision
        result["decision"]["final_gated_decision"] = rule_engine_decision
        decision_was_capped = False
        if not extraction_ready and result["decision"]["decision_type"] in {"ACCEPT", "CONDITIONAL ACCEPT"}:
            decision_was_capped = True
            result["decision"].update(
                {
                    "decision_type": "NEED REVIEW",
                    "final_gated_decision": "NEED REVIEW",
                    "headline": "CẦN FOUNDER RÀ SOÁT BẰNG CHỨNG OPENAI",
                    "three_reasons": [
                        result["decision"]["three_reasons"][0],
                        result["decision"]["three_reasons"][1],
                        (
                            f"Rule engine sơ bộ trả {rule_engine_decision}, nhưng Structured Evidence "
                            "chưa được OpenAI trích xuất và kiểm định thành công."
                        ),
                    ],
                    "human_confirmation_point": (
                        "Founder kiểm tra trạng thái OpenAI Extraction; chỉ chạy lại và xem xét phê duyệt "
                        "khi evidence có source, quote, confidence và fingerprint hợp lệ."
                    ),
                    "approval_allowed": False,
                    "approval_status": "PENDING_REVIEW",
                    "openai_evidence_gate": "BLOCKED",
                }
            )

        challenger: dict[str, Any] = {
            "called": False,
            "status": "not_requested",
            "model": model_name(),
            "response_id": None,
            "output": None,
            "validation": [],
        }
        challenger_ms = 0.0
        if (
            use_openai
            and extraction_ready
            and not decision_was_capped
            and rule_engine_decision != "NEED MORE DATA"
        ):
            challenger_started = time.perf_counter()
            try:
                challenger = review_decision(
                    result["openai"]["input_masked"],
                    rule_engine_decision,
                )
                if challenger["status"] == "validated":
                    result["decision"]["three_reasons"] = challenger["output"]["three_reasons"]
                    result["decision"]["human_confirmation_point"] = challenger["output"]["human_confirmation_point"]
                    result["decision"]["openai_enhanced"] = True
            except TeamPackError as exc:
                challenger = {
                    "called": False,
                    "status": "safe_fallback",
                    "model": model_name(),
                    "response_id": None,
                    "output": None,
                    "error": str(exc),
                    "validation": [
                        {
                            "check": "challenger_fail_safe",
                            "passed": True,
                            "note": "Giữ Decision Card deterministic; không giả lập Challenger thành công.",
                        }
                    ],
                }
            challenger_ms = (time.perf_counter() - challenger_started) * 1000
            result["workflow"].append(
                _trace_event(
                    result["trace_id"],
                    "OpenAI Decision Challenger",
                    "reason",
                    "Masked Financial Snapshot + Risk Report + validated evidence summary",
                    challenger["status"],
                    "Structured Output chỉ được dùng khi toàn bộ Decision Challenger guardrail đạt.",
                    openai_service=f"Responses API / {model_name()}",
                    duration_ms=challenger_ms,
                )
            )
        elif use_openai and extraction_ready and rule_engine_decision == "NEED MORE DATA":
            challenger.update(
                {
                    "status": "blocked_by_data",
                    "validation": [
                        {
                            "check": "data_gate_before_challenger",
                            "passed": True,
                            "note": "Extraction đã chạy; Data Quality Gate dừng Decision Challenger.",
                        }
                    ],
                }
            )
            result["workflow"].append(
                _trace_event(
                    result["trace_id"],
                    "OpenAI Decision Challenger",
                    "guardrail",
                    "Data Quality Report",
                    "blocked_by_data",
                    "Không tạo câu chữ Decision Card khi workbook còn blocking issue.",
                    openai_service=f"Responses API / {model_name()}",
                    duration_ms=0,
                )
            )
        elif use_openai:
            challenger.update(
                {
                    "status": "blocked_by_extraction",
                    "validation": [
                        {
                            "check": "validated_extraction_before_challenger",
                            "passed": True,
                            "note": "Decision Challenger không chạy khi evidence extraction chưa hợp lệ.",
                        }
                    ],
                }
            )
        else:
            challenger.update(
                {
                    "status": "disabled_for_run",
                    "validation": [
                        {
                            "check": "offline_mode_disclosed",
                            "passed": True,
                            "note": "Decision Challenger bị tắt cho lượt chạy này.",
                        }
                    ],
                }
            )

        overall_openai_status = (
            "validated"
            if extraction["status"] == "validated" and challenger["status"] == "validated"
            else "extraction_validated_data_blocked"
            if extraction["status"] == "validated" and challenger["status"] == "blocked_by_data"
            else "extraction_validated_challenger_fallback"
            if extraction["status"] == "validated"
            else extraction["status"]
        )
        result["openai"] = {
            "status": overall_openai_status,
            "model": model_name(),
            "called": bool(extraction.get("called") or challenger.get("called")),
            "input_masked": result["openai"]["input_masked"],
            "output": challenger.get("output"),
            "validation": challenger.get("validation") or [],
            "extraction": extraction,
            "challenger": challenger,
        }

        result["performance"]["request_total_ms"] = round((time.perf_counter() - request_started) * 1000, 2)
        result["performance"]["openai_extraction_ms"] = round(extraction_ms, 2)
        result["performance"]["openai_challenger_ms"] = round(challenger_ms, 2)
        result["performance"]["openai_ms"] = round(extraction_ms + challenger_ms, 2)
        with self.lock:
            self.runs[result["trace_id"]] = {
                "decision": result["decision"],
                "scenario": result["scenario"],
                "source": result["source"],
            }
        append_audit(result["workflow"])
        append_audit(
            {
                "timestamp": result["generated_at"],
                "trace_id": result["trace_id"],
                "agent_or_component": "Orchestrator",
                "event_type": "run_summary",
                "response_status": result["decision"]["decision_type"],
                "rule_engine_decision": result["decision"]["rule_engine_decision"],
                "final_gated_decision": result["decision"]["final_gated_decision"],
                "scenario_fingerprint": result["openai"]["input_masked"].get("scenario_fingerprint"),
                "openai_status": result["openai"]["status"],
                "openai_extraction_status": extraction["status"],
                "openai_challenger_status": challenger["status"],
                "performance": result["performance"],
                "secret_logging_rule": "No API key/access token/password",
            }
        )
        return result

    def approve(self, payload: dict[str, Any]) -> dict[str, Any]:
        trace_id = str(payload.get("trace_id") or "").strip()
        founder_name = str(payload.get("founder_name") or "").strip()
        action = str(payload.get("action") or "").strip().upper()
        confirmed = bool(payload.get("confirmed"))
        if not trace_id or not founder_name:
            raise TeamPackError("Thiếu trace_id hoặc tên Founder.")
        if action not in {"APPROVE", "REJECT"}:
            raise TeamPackError("Action chỉ có thể là APPROVE hoặc REJECT.")
        if not confirmed:
            raise TeamPackError("Founder chưa xác nhận đã đọc điều kiện bảo vệ.")
        with self.lock:
            run = self.runs.get(trace_id)
        if not run:
            raise TeamPackError("Không tìm thấy trace_id hợp lệ trong phiên demo này.")
        if not run["decision"].get("approval_required"):
            raise TeamPackError("Luồng đang bị khóa bởi dữ liệu; không thể phê duyệt.")
        if action == "APPROVE" and not run["decision"].get("approval_allowed", True):
            raise TeamPackError(
                "Rule engine không cho phép phê duyệt kết quả REJECT/NEED REVIEW; "
                "Founder chỉ có thể từ chối hoặc bổ sung TeamPack rồi chạy lại."
            )
        approval_time = datetime.now().astimezone()
        record = {
            "approval_id": make_audit_id("APR", approval_time),
            "trace_id": trace_id,
            "founder_name": founder_name,
            "action": action,
            "status": "APPROVED_FOR_PRECHECK" if action == "APPROVE" else "REJECTED_BY_FOUNDER",
            "timestamp": approval_time.isoformat(timespec="seconds"),
            "external_submission_executed": False,
            "note": "Phê duyệt chỉ mở trạng thái precheck trong bản demo; không gửi API/không giải ngân thật.",
        }
        with self.lock:
            # Key by the unique approval ID so separate human actions can never
            # overwrite one another.  Each record still carries its exact trace.
            self.approvals[record["approval_id"]] = record
        append_audit(
            {
                **record,
                "agent_or_component": "Founder Approval Gate",
                "event_type": "human_confirmation",
                "secret_logging_rule": "No API key/access token/password",
            }
        )
        return record


STATE = AppState()


class Handler(BaseHTTPRequestHandler):
    server_version = "OPCDecisionCockpit/2.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")

    def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 8 * 1024 * 1024:
            raise TeamPackError("Payload rỗng hoặc vượt quá giới hạn 8 MB.")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TeamPackError("JSON request không hợp lệ.") from exc
        if not isinstance(payload, dict):
            raise TeamPackError("JSON request phải là object.")
        return payload

    def do_GET(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        if route in {"/api/health", "/api/status"}:
            self._send_json(
                {
                    "status": "ok",
                    "app": "OPC Agentic AI Decision Cockpit",
                    "app_id": "team-tsd-opc-agentic-ai-ultimate",
                    "version": APP_VERSION,
                    "server_port": self.server.server_address[1],
                    "openai_configured": is_configured(),
                    "openai_model": model_name(),
                    "audit_log": str(AUDIT_LOG.name),
                }
            )
            return
        if route == "/api/bootstrap":
            self._send_json(STATE.bootstrap())
            return
        if route == "/":
            self._serve_static("index.html")
            return
        if route.startswith("/static/"):
            self._serve_static(route.removeprefix("/static/"))
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        try:
            payload = self._read_json()
            if route == "/api/shutdown":
                caller = self.client_address[0]
                app_id = self.headers.get("X-OPC-App-ID", "")
                if caller not in {"127.0.0.1", "::1"} or app_id != "team-tsd-opc-agentic-ai-ultimate":
                    self._send_json({"error": "Shutdown request bị từ chối."}, HTTPStatus.FORBIDDEN)
                    return
                self._send_json(
                    {
                        "status": "stopping",
                        "app_id": "team-tsd-opc-agentic-ai-ultimate",
                        "external_action": False,
                    }
                )
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if route == "/api/upload":
                filename = str(payload.get("filename") or "uploaded.xlsx")
                if not filename.lower().endswith(".xlsx"):
                    raise TeamPackError("Chỉ chấp nhận file .xlsx.")
                try:
                    content = base64.b64decode(payload.get("data_base64") or "", validate=True)
                except Exception as exc:
                    raise TeamPackError("Nội dung base64 không hợp lệ.") from exc
                self._send_json(STATE.upload(Path(filename).name, content))
                return
            if route == "/api/analyze":
                self._send_json(STATE.analyze(payload))
                return
            if route == "/api/approve":
                self._send_json(STATE.approve(payload))
                return
            self.send_error(HTTPStatus.NOT_FOUND)
        except TeamPackError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:  # pragma: no cover - last-resort demo safety
            self._send_json(
                {"error": "Lỗi hệ thống đã được chặn an toàn.", "detail": str(exc)[:300]},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _serve_static(self, relative: str) -> None:
        requested = (STATIC_DIR / relative).resolve()
        if STATIC_DIR.resolve() not in requested.parents and requested != STATIC_DIR.resolve():
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not requested.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content = requested.read_bytes()
        mime, _ = mimetypes.guess_type(requested.name)
        self.send_response(HTTPStatus.OK)
        self._security_headers()
        self.send_header("Content-Type", (mime or "application/octet-stream") + ("; charset=utf-8" if mime and mime.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def main() -> None:
    parser = argparse.ArgumentParser(description="OPC Agentic AI Decision Cockpit")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8766, type=int)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"OPC Agentic AI đang chạy tại http://{args.host}:{args.port}")
    print(f"OpenAI: {'configured' if is_configured() else 'not configured - safe fallback'} | model={model_name()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nĐã dừng server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
