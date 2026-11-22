from __future__ import annotations

import hashlib
import io
import json
import math
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel


REQUIRED_SHEETS = {"04_CONTRACTS"}
DATA_QUALITY_SHEETS = [
    "02_OPC_PROFILE",
    "03_CUSTOMERS",
    "04_CONTRACTS",
    "05_PRODUCTS",
    "06_ORDERS",
    "07_INVOICES",
    "08_BANK_TXN",
    "09_CASHFLOW",
    "10_CREDIT_PROFILE",
    "11_BANK_PRODUCTS",
    "12_API_CATALOG",
    "13_RISK_RULES",
    "14_ALERTS",
    "20_DATA_CLASS",
]

SEVERITY_ORDER = {"Low": 1, "Medium": 2, "High": 3, "Critical": 4}
DECISION_STRENGTH = {
    "NEED MORE DATA": 0,
    "REJECT": 1,
    "NEED REVIEW": 2,
    "CONDITIONAL ACCEPT": 3,
    "ACCEPT": 4,
}
ROOT = Path(__file__).resolve().parent
DEFAULT_RULES = {
    "transaction_anomaly_threshold": 85,
    "bank_confidence_threshold": 0.65,
    "founder_approval_threshold_vnd": 300_000_000,
    "working_capital_tenor_years": 0.5,
    "missing_data_policy": "STOP_AND_REQUEST_EXACT_FIELD",
}


def make_audit_id(prefix: str, timestamp: datetime | None = None) -> str:
    """Return a sortable audit identifier with a collision-resistant UUID.

    The timestamp keeps IDs easy to inspect during a live demo, while the full
    128-bit UUID prevents runs created within the same second from overwriting
    one another.  The complete value is retained in API payloads and audit logs.
    """
    created_at = timestamp or datetime.now().astimezone()
    safe_prefix = re.sub(r"[^A-Z0-9]", "", str(prefix).upper())
    if not safe_prefix:
        raise ValueError("Audit ID prefix must contain at least one letter or number.")
    return f"{safe_prefix}-{created_at.strftime('%Y%m%d-%H%M%S')}-{uuid4().hex.upper()}"


class TeamPackError(ValueError):
    pass


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _sheet_rows(worksheet) -> list[dict[str, Any]]:
    values = list(worksheet.iter_rows(values_only=True))
    if not values:
        return []
    headers = [str(value).strip() if value is not None else "" for value in values[0]]
    rows: list[dict[str, Any]] = []
    for raw in values[1:]:
        if not any(value is not None for value in raw):
            continue
        rows.append({header: _json_value(value) for header, value in zip(headers, raw) if header})
    return rows


@dataclass
class TeamPack:
    sheets: dict[str, list[dict[str, Any]]]
    source_name: str
    source_hash: str
    sheet_names: list[str]

    @classmethod
    def from_path(cls, path: Path) -> "TeamPack":
        return cls.from_bytes(path.read_bytes(), path.name)

    @classmethod
    def from_bytes(cls, content: bytes, source_name: str) -> "TeamPack":
        if len(content) > 5 * 1024 * 1024:
            raise TeamPackError("TeamPack vượt quá giới hạn 5 MB của bản demo.")
        try:
            workbook = load_workbook(io.BytesIO(content), data_only=True, read_only=True)
        except Exception as exc:  # pragma: no cover - library-specific errors
            raise TeamPackError(f"Không đọc được workbook: {exc}") from exc
        missing = sorted(REQUIRED_SHEETS - set(workbook.sheetnames))
        if missing:
            raise TeamPackError("Thiếu sheet bắt buộc: " + ", ".join(missing))
        sheets = {name: _sheet_rows(workbook[name]) for name in workbook.sheetnames}
        return cls(
            sheets=sheets,
            source_name=source_name,
            source_hash=hashlib.sha256(content).hexdigest()[:12],
            sheet_names=list(workbook.sheetnames),
        )

    def rows(self, sheet_name: str) -> list[dict[str, Any]]:
        return self.sheets.get(sheet_name, [])

    def profile(self) -> dict[str, Any]:
        return {str(row.get("field")): row.get("value") for row in self.rows("02_OPC_PROFILE")}

    def contracts(self) -> list[dict[str, Any]]:
        return self.rows("04_CONTRACTS")


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _month(value: Any) -> str | None:
    if isinstance(value, str):
        if re.fullmatch(r"\d{4}-\d{2}", value):
            return value
        try:
            return datetime.fromisoformat(value).strftime("%Y-%m")
        except ValueError:
            return None
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m")
    if isinstance(value, (int, float)) and 1 <= value <= 100_000:
        try:
            return from_excel(value).strftime("%Y-%m")
        except (TypeError, ValueError, OverflowError):
            return None
    return None


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and 1 <= value <= 100_000:
        try:
            return from_excel(value).date()
        except (TypeError, ValueError, OverflowError):
            return None
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            return None
    return None


def load_rules(path: Path | None = None) -> dict[str, Any]:
    rules = dict(DEFAULT_RULES)
    rule_path = path or ROOT / "config" / "decision_rules.json"
    if rule_path.exists():
        try:
            loaded = json.loads(rule_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TeamPackError(f"Không đọc được decision rules: {exc}") from exc
        if not isinstance(loaded, dict):
            raise TeamPackError("decision_rules.json phải là một JSON object.")
        rules.update(loaded)
    return rules


def _shift_month(month: str, delta: int) -> str:
    year, number = (int(part) for part in month.split("-"))
    serial = year * 12 + number - 1 + delta
    return f"{serial // 12:04d}-{serial % 12 + 1:02d}"


def _safe_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _trace_event(
    trace_id: str,
    agent: str,
    event_type: str,
    input_source: str,
    status: str,
    note: str,
    tool_or_api_id: str | None = None,
    openai_service: str | None = None,
    duration_ms: float | None = None,
) -> dict[str, Any]:
    return {
        # Microsecond precision preserves the real order of fast handoffs that
        # happen inside one wall-clock second.
        "timestamp": datetime.now().astimezone().isoformat(timespec="microseconds"),
        "trace_id": trace_id,
        "agent_or_component": agent,
        "event_type": event_type,
        "input_source": input_source,
        "tool_or_api_id": tool_or_api_id,
        "masked_fields": ["customer_id", "account_id"],
        "openai_service_used": openai_service,
        "response_status": status,
        "validation_note": note,
        "secret_logging_rule": "Không ghi API key/access token/password",
        "duration_ms": round(duration_ms, 2) if duration_ms is not None else None,
    }


def _find_by(rows: Iterable[dict[str, Any]], field: str, value: Any) -> dict[str, Any] | None:
    for row in rows:
        if row.get(field) == value:
            return row
    return None


def _format_billion(value: float) -> str:
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f} tỷ VND"
    return f"{value / 1_000_000:.1f} triệu VND"


def _masked_contract_ref(value: Any) -> str:
    contract_id = _safe_text(value)
    if not contract_id:
        return "CON-***"
    prefix = contract_id.split("-", 1)[0] or "CON"
    suffix = re.sub(r"[^A-Za-z0-9]", "", contract_id)[-3:] or "UNK"
    return f"{prefix}-***{suffix}"


def _customer_token(value: Any) -> str:
    customer_id = _safe_text(value)
    if customer_id == "CUS-005":
        return "TOK-CUS-A91F"
    digest = hashlib.sha256(customer_id.encode("utf-8")).hexdigest()[:8].upper() if customer_id else "UNKNOWN"
    return f"TOK-CUS-{digest}"


def _margin_comparison(actual: float, target: float) -> dict[str, Any]:
    """Return one consistent, data-driven margin comparison for every contract."""
    gap_pp = (actual - target) * 100
    if abs(gap_pp) < 0.05:
        relation = "EQUAL"
        text = f"Biên gộp {actual:.1%} bằng mục tiêu {target:.1%}."
    elif gap_pp > 0:
        relation = "ABOVE"
        text = (
            f"Biên gộp {actual:.1%} cao hơn mục tiêu {target:.1%} "
            f"{gap_pp:.1f} điểm %."
        )
    else:
        relation = "BELOW"
        text = (
            f"Biên gộp {actual:.1%} thấp hơn mục tiêu {target:.1%} "
            f"{abs(gap_pp):.1f} điểm %."
        )
    return {"relation": relation, "gap_pp": gap_pp, "text": text}


class DecisionEngine:
    def __init__(
        self,
        pack: TeamPack,
        rules: dict[str, Any] | None = None,
        structured_evidence: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ):
        self.pack = pack
        self.rules = rules or load_rules()
        self.structured_evidence = structured_evidence or {}
        self.trace_id = _safe_text(trace_id) or None

    def analyze(self, request: dict[str, Any]) -> dict[str, Any]:
        total_started = time.perf_counter()
        contract_id = _safe_text(request.get("contract_id"))
        if not contract_id:
            raise TeamPackError("Thiếu contract_id; hãy chọn hợp đồng từ TeamPack trước khi phân tích.")
        found_contract = _find_by(self.pack.contracts(), "contract_id", contract_id)
        contract = dict(found_contract) if found_contract else None
        if not contract:
            raise TeamPackError(f"Không tìm thấy hợp đồng {contract_id}.")

        now = datetime.now().astimezone()
        trace_id = self.trace_id or make_audit_id("TRACE", now)
        scenario = self._normalise_scenario(request.get("scenario") or {})
        evidence = self._normalise_evidence(request.get("evidence") or {})
        workflow: list[dict[str, Any]] = []

        finance_started = time.perf_counter()
        finance = self._finance_agent(contract, scenario, evidence, trace_id, workflow)
        finance_ms = (time.perf_counter() - finance_started) * 1000
        if workflow:
            workflow[-1]["duration_ms"] = round(finance_ms, 2)

        risk_started = time.perf_counter()
        risk = self._risk_agent(contract, finance, scenario, evidence, trace_id, workflow)
        risk_ms = (time.perf_counter() - risk_started) * 1000
        if workflow:
            workflow[-1]["duration_ms"] = round(risk_ms, 2)

        partner_started = time.perf_counter()
        partner = self._partner_agent(contract, finance, risk, scenario, evidence, trace_id, workflow)
        partner_ms = (time.perf_counter() - partner_started) * 1000
        if workflow:
            workflow[-1]["duration_ms"] = round(partner_ms, 2)
        decision = self._decision_card(contract, finance, risk, partner, evidence)

        masked_input = self._openai_input(
            contract,
            finance,
            risk,
            partner,
            decision,
            evidence,
            scenario,
            trace_id,
        )
        workflow.append(
            _trace_event(
                trace_id,
                "Decision & Partner Agent",
                "decision",
                "Financial Snapshot + Risk Report + 10_CREDIT_PROFILE + 11_BANK_PRODUCTS",
                "needs_data" if decision["decision_type"] == "NEED MORE DATA" else "needs_approval",
                "Decision Card có đúng 3 lý do và một điểm xác nhận của Founder.",
            )
        )

        result = {
            "trace_id": trace_id,
            "generated_at": now.isoformat(timespec="seconds"),
            "source": {
                "file_name": self.pack.source_name,
                "sha256_short": self.pack.source_hash,
                "sheet_count": len(self.pack.sheet_names),
                "sheets_used": [
                    "02_OPC_PROFILE",
                    "03_CUSTOMERS",
                    "04_CONTRACTS",
                    "05_PRODUCTS",
                    "06_ORDERS",
                    "07_INVOICES",
                    "08_BANK_TXN",
                    "09_CASHFLOW",
                    "10_CREDIT_PROFILE",
                    "11_BANK_PRODUCTS",
                    "13_RISK_RULES",
                    "14_ALERTS",
                    "20_DATA_CLASS",
                ],
            },
            "contract": self._contract_view(contract),
            "scenario": scenario,
            "evidence": evidence,
            "finance": finance,
            "data_quality": finance["data_quality"],
            "risk": risk,
            "partner": partner,
            "decision": decision,
            "openai": {
                "input_masked": masked_input,
                "status": "not_requested",
                "called": False,
                "validation": [],
                "output": None,
            },
            "workflow": workflow,
        }
        result["performance"] = {
            "finance_ms": round(finance_ms, 2),
            "risk_ms": round(risk_ms, 2),
            "partner_ms": round(partner_ms, 2),
            "deterministic_total_ms": round((time.perf_counter() - total_started) * 1000, 2),
        }
        return result

    @staticmethod
    def _normalise_scenario(raw: dict[str, Any]) -> dict[str, float]:
        def clamp(name: str, minimum: float, maximum: float) -> float:
            return max(minimum, min(maximum, _number(raw.get(name), 0.0)))

        return {
            "cost_increase_pct": clamp("cost_increase_pct", -20.0, 100.0),
            "payment_delay_days": clamp("payment_delay_days", 0.0, 120.0),
            "deadline_change_days": clamp("deadline_change_days", -30.0, 90.0),
            "scope_change_pct": clamp("scope_change_pct", -30.0, 100.0),
            "collateral_change_pp": clamp("collateral_change_pp", -10.0, 30.0),
        }

    @staticmethod
    def _normalise_evidence(raw: dict[str, Any]) -> dict[str, bool]:
        defaults = {
            "contract_signed": True,
            "receivable_aging": True,
            "capacity_plan": True,
            "suspicious_txn_reviewed": False,
        }
        return {key: bool(raw.get(key, default)) for key, default in defaults.items()}

    @staticmethod
    def _credit_category(request_type: Any) -> str:
        text = _safe_text(request_type).lower()
        if "performance bond" in text or "bảo lãnh" in text:
            return "PERFORMANCE_BOND"
        if "trade finance" in text or re.search(r"\blc\b", text):
            return "TRADE_FINANCE"
        if "micro" in text and "working capital" in text:
            return "MICRO_WORKING_CAPITAL"
        if "working capital" in text or "vốn lưu động" in text:
            return "WORKING_CAPITAL"
        return "OTHER"

    @staticmethod
    def _product_category(product: dict[str, Any]) -> str:
        text = " ".join(
            _safe_text(product.get(field)).lower()
            for field in ("product_name", "description")
        )
        if "performance bond" in text or "bảo lãnh" in text:
            return "PERFORMANCE_BOND"
        if "trade finance" in text or re.search(r"\blc\b", text):
            return "TRADE_FINANCE"
        if "invoice factoring" in text or "bao thanh toán" in text:
            return "FACTORING"
        if "micro" in text and "working capital" in text:
            return "MICRO_WORKING_CAPITAL"
        if "working capital" in text or "vốn lưu động" in text:
            return "WORKING_CAPITAL"
        return "OTHER"

    def _contract_linked_rows(self, contract: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        contract_id = _safe_text(contract.get("contract_id"))
        orders = [
            row for row in self.pack.rows("06_ORDERS")
            if _safe_text(row.get("contract_id")) == contract_id
        ]
        order_ids = {
            _safe_text(row.get("order_id"))
            for row in orders
            if _safe_text(row.get("order_id"))
        }
        invoices = [
            row for row in self.pack.rows("07_INVOICES")
            if _safe_text(row.get("order_id")) in order_ids
        ]
        return orders, invoices

    def _contract_signals(self, contract: dict[str, Any]) -> dict[str, Any]:
        orders, invoices = self._contract_linked_rows(contract)
        customer = _find_by(
            self.pack.rows("03_CUSTOMERS"),
            "customer_id",
            contract.get("customer_id"),
        ) or {}
        text = " ".join(
            [
                _safe_text(contract.get("description")),
                _safe_text(contract.get("payment_terms")),
                *[_safe_text(row.get("delivery_note")) for row in orders],
            ]
        ).lower()
        customer_type = _safe_text(customer.get("customer_type")).lower()
        eligible_invoice_statuses = {"open", "issued", "approved"}
        eligible_invoices = [
            row for row in invoices
            if _safe_text(row.get("status")).lower() in eligible_invoice_statuses
            and _number(row.get("invoice_amount")) > 0
        ]
        structured = self.structured_evidence
        use_structured = bool(structured) and all(
            isinstance(structured.get(name), dict)
            and structured[name].get("validated") is True
            for name in (
                "performance_bond_required",
                "deployment_scope_provinces",
                "collection_timing_signal",
            )
        )

        if use_structured:
            bond_field = structured["performance_bond_required"]
            province_field = structured["deployment_scope_provinces"]
            collection_field = structured["collection_timing_signal"]
            bond_required = (
                bool(bond_field.get("value"))
                if bond_field.get("status") == "SUPPORTED"
                else False
            )
            deployment_scope_provinces = (
                int(province_field["value"])
                if province_field.get("status") == "SUPPORTED"
                and isinstance(province_field.get("value"), int)
                and not isinstance(province_field.get("value"), bool)
                else None
            )
            collection_timing_signal = (
                _safe_text(collection_field.get("value")).upper()
                if collection_field.get("status") == "SUPPORTED"
                else None
            )
            evidence_mode = "OPENAI_STRUCTURED_EVIDENCE_VALIDATED"
        else:
            # Safe offline/degraded fallback.  AppState discloses this mode and
            # caps any otherwise approvable result at NEED REVIEW.  It exists so
            # deterministic finance and data-quality inspection remain usable
            # when the external service is unavailable.
            bond_required = "performance bond" in text or "bảo lãnh" in text
            province_match = re.search(
                r"\b(\d{1,2})\s*[- ]?\s*(?:province|provinces|tỉnh|thành phố)\b",
                text,
            )
            deployment_scope_provinces = int(province_match.group(1)) if province_match else None
            if any(token in text for token in ("after uat", "sau uat", "payment after uat")):
                collection_timing_signal = "AFTER_UAT"
            elif "monthly" in text or "hàng tháng" in text:
                collection_timing_signal = "MONTHLY"
            elif "milestone" in text or "theo mốc" in text:
                collection_timing_signal = "MILESTONE"
            elif any(token in text for token in ("after acceptance", "acceptance", "nghiệm thu")):
                collection_timing_signal = "AFTER_ACCEPTANCE"
            else:
                collection_timing_signal = None
            evidence_mode = "DETERMINISTIC_TEXT_FALLBACK"
        return {
            "orders": orders,
            "invoices": invoices,
            "customer": customer,
            "bond_required": bond_required,
            "deployment_scope_provinces": deployment_scope_provinces,
            "collection_timing_signal": collection_timing_signal,
            "core_evidence_mode": evidence_mode,
            "structured_evidence": structured if use_structured else {},
            "trade_required": "trade finance" in text or bool(re.search(r"\blc\b", text)),
            "working_capital_required": "working capital" in text or "vốn lưu động" in text,
            "micro_fit": customer_type in {"cooperative", "household"}
            and any(token in text for token in ("local", "pilot", "rollout", "cooperative", "địa phương")),
            "eligible_invoices": eligible_invoices,
        }

    @staticmethod
    def _row_contract_refs(row: dict[str, Any]) -> set[str]:
        explicit = {
            _safe_text(row.get(field)).upper()
            for field in ("contract_id", "related_contract_id")
            if _safe_text(row.get(field))
        }
        haystack = " ".join(
            _safe_text(row.get(field))
            for field in ("collateral_or_basis", "precheck_note", "description", "fit_note")
        )
        explicit.update(match.upper() for match in re.findall(r"\bCON[-_]\d+\b", haystack, flags=re.IGNORECASE))
        return {value.replace("_", "-") for value in explicit}

    def _matching_bank_products(self, credit_case: dict[str, Any]) -> list[dict[str, Any]]:
        direct_product_id = _safe_text(credit_case.get("bank_product_id"))
        products = self.pack.rows("11_BANK_PRODUCTS")
        if direct_product_id:
            return [
                row for row in products
                if _safe_text(row.get("bank_product_id")) == direct_product_id
            ]
        category = self._credit_category(credit_case.get("request_type"))
        return [row for row in products if self._product_category(row) == category]

    def _credit_case_mappings(self, contract: dict[str, Any]) -> list[dict[str, Any]]:
        """Resolve credit cases without ever borrowing a case tied to another contract.

        New TeamPacks should use 10_CREDIT_PROFILE.contract_id. The original TeamPack
        predates that column, so exact CON-xxx references in the basis/note are also
        accepted. A genuinely company-wide facility may be shown only when the
        selected contract explicitly signals that purpose, and is labelled
        ENTERPRISE_SHARED instead of being presented as contract-owned.
        """
        contract_id = _safe_text(contract.get("contract_id")).upper().replace("_", "-")
        signals = self._contract_signals(contract)
        mappings: list[dict[str, Any]] = []
        for row in self.pack.rows("10_CREDIT_PROFILE"):
            refs = self._row_contract_refs(row)
            category = self._credit_category(row.get("request_type"))
            mapping_scope: str | None = None
            mapping_source: str | None = None

            if refs:
                if contract_id not in refs:
                    continue
                mapping_scope = "EXACT_CONTRACT"
                mapping_source = (
                    f"10_CREDIT_PROFILE[{_safe_text(row.get('credit_case_id'))}].contract_id"
                    if _safe_text(row.get("contract_id"))
                    else f"10_CREDIT_PROFILE[{_safe_text(row.get('credit_case_id'))}].collateral_or_basis"
                )
            elif category == "WORKING_CAPITAL" and signals["working_capital_required"]:
                mapping_scope = "ENTERPRISE_SHARED"
                mapping_source = (
                    f"10_CREDIT_PROFILE[{_safe_text(row.get('credit_case_id'))}] "
                    "+ 06_ORDERS.delivery_note"
                )
            elif category == "MICRO_WORKING_CAPITAL" and signals["micro_fit"]:
                mapping_scope = "PURPOSE_SEGMENT_MATCH"
                mapping_source = (
                    f"10_CREDIT_PROFILE[{_safe_text(row.get('credit_case_id'))}] "
                    "+ 03_CUSTOMERS.customer_type + 04_CONTRACTS.description"
                )
            else:
                continue

            products = self._matching_bank_products(row)
            mappings.append(
                {
                    "credit_case_id": _safe_text(row.get("credit_case_id")),
                    "request_type": _safe_text(row.get("request_type")),
                    "category": category,
                    "requested_amount": _number(row.get("requested_amount")),
                    "eligibility_score": _number(row.get("eligibility_score")),
                    "approval_status": _safe_text(row.get("approval_status")),
                    "mapping_scope": mapping_scope,
                    "mapping_source": mapping_source,
                    "bank_product_ids": [
                        _safe_text(product.get("bank_product_id")) for product in products
                    ],
                    "row": row,
                    "products": products,
                }
            )
        return mappings

    def _contract_view(self, contract: dict[str, Any]) -> dict[str, Any]:
        customer = _find_by(self.pack.rows("03_CUSTOMERS"), "customer_id", contract.get("customer_id")) or {}
        return {
            "contract_id": contract.get("contract_id"),
            "contract_ref_masked": _masked_contract_ref(contract.get("contract_id")),
            "customer_token": _customer_token(contract.get("customer_id")),
            "customer_name_masked": "Khách hàng ***",
            "description": contract.get("description"),
            "status": contract.get("status"),
            "contract_value": _number(contract.get("contract_value")),
            "gross_margin": _number(contract.get("gross_margin")),
            "payment_terms": contract.get("payment_terms"),
            "strategic_value": customer.get("strategic_value"),
            "payment_reliability": _number(customer.get("payment_reliability")),
        }

    def _validate_data_quality(
        self,
        contract: dict[str, Any],
        evidence: dict[str, bool],
    ) -> dict[str, Any]:
        contract_id = _safe_text(contract.get("contract_id"))
        customer_id = _safe_text(contract.get("customer_id"))
        issues: list[dict[str, Any]] = []
        sheet_order = {name: index for index, name in enumerate(DATA_QUALITY_SHEETS)}

        def add_issue(
            level: str,
            sheet: str,
            record_id: str,
            field: str,
            label: str,
            source: str,
            request: str,
            expected_type: str,
            impact: str,
            issue_type: str = "FIELD_MISSING",
            required_fields: list[str] | None = None,
        ) -> None:
            issues.append(
                {
                    "level": level,
                    "sheet": sheet,
                    "record_id": record_id,
                    "field": field,
                    "label": label,
                    "source": source,
                    "request": request,
                    "expected_type": expected_type,
                    "impact": impact,
                    "issue_type": issue_type,
                    "required_fields": required_fields or [],
                }
            )

        def check_field(
            row: dict[str, Any],
            field: str,
            *,
            level: str,
            sheet: str,
            record_id: str,
            label: str,
            expected_type: str,
            impact: str,
            positive: bool = False,
            nonzero: bool = False,
            numeric: bool = False,
        ) -> None:
            value = row.get(field)
            invalid = _is_blank(value)
            if not invalid and (positive or nonzero or numeric):
                try:
                    number = float(value)
                    invalid = (positive and number <= 0) or (nonzero and abs(number) <= 1e-12)
                except (TypeError, ValueError):
                    invalid = True
            if invalid:
                add_issue(
                    level,
                    sheet,
                    record_id,
                    field,
                    label,
                    f"{sheet}[{record_id}].{field}",
                    f"Bổ sung {label.lower()} cho {record_id}.",
                    expected_type,
                    impact,
                    "FIELD_MISSING" if _is_blank(value) else "VALUE_INVALID",
                )

        present_sheets = set(self.pack.sheet_names)
        blocking_sheets = {
            "02_OPC_PROFILE",
            "03_CUSTOMERS",
            "04_CONTRACTS",
            "05_PRODUCTS",
            "06_ORDERS",
            "07_INVOICES",
            "08_BANK_TXN",
            "09_CASHFLOW",
            "10_CREDIT_PROFILE",
            "11_BANK_PRODUCTS",
            "13_RISK_RULES",
            "20_DATA_CLASS",
        }
        sheet_requirements = {
            "02_OPC_PROFILE": ["field", "value"],
            "03_CUSTOMERS": ["customer_id", "customer_type", "strategic_value", "payment_reliability"],
            "04_CONTRACTS": ["contract_id", "customer_id", "start_date", "end_date", "contract_value"],
            "05_PRODUCTS": ["service_id", "service_name", "pricing_model", "list_price", "target_margin"],
            "06_ORDERS": ["order_id", "contract_id", "customer_id", "order_date", "due_date", "status", "service_id", "order_revenue", "estimated_cost"],
            "07_INVOICES": ["invoice_id", "order_id", "customer_id", "status", "invoice_amount"],
            "08_BANK_TXN": ["txn_id", "txn_date", "direction", "amount", "txn_status", "transaction_risk_score"],
            "09_CASHFLOW": ["month", "expected_cash_in", "expected_cash_out", "cash_reserve_minimum", "projected_closing_cash"],
            "10_CREDIT_PROFILE": ["credit_case_id", "request_type", "requested_amount", "eligibility_score"],
            "11_BANK_PRODUCTS": ["bank_product_id", "bank", "product_name", "annual_rate_or_fee", "collateral_ratio"],
            "12_API_CATALOG": ["api_id", "provider", "purpose"],
            "13_RISK_RULES": ["rule_id", "trigger_condition", "severity", "required_action"],
            "14_ALERTS": ["alert_id", "related_record", "severity", "risk_score"],
            "20_DATA_CLASS": ["data_pattern", "classification", "external_api_rule", "masking_or_tokenization", "logging_rule"],
        }
        for sheet in DATA_QUALITY_SHEETS:
            if sheet in present_sheets:
                continue
            level = "BLOCKING" if sheet in blocking_sheets else "WARNING"
            add_issue(
                level,
                sheet,
                "SHEET",
                "sheet",
                f"Sheet {sheet}",
                sheet,
                f"Bổ sung sheet {sheet} theo cấu trúc TeamPack.",
                "Sheet hợp lệ",
                "Không thể hoàn tất bước phân tích phụ thuộc vào sheet này." if level == "BLOCKING" else "Giảm khả năng truy vết và quản trị dữ liệu.",
                "SHEET_MISSING",
                sheet_requirements.get(sheet, []),
            )

        if "02_OPC_PROFILE" in present_sheets:
            profile = self.pack.profile()
            profile_specs = [
                ("company_id", "Mã doanh nghiệp", "Mã OPC", "Không thể liên kết hồ sơ tín dụng."),
                ("cash_reserve_minimum", "Mức dự trữ tiền tối thiểu", "VND dương", "Không thể xác định reserve breach."),
                ("target_gross_margin", "Biên gộp mục tiêu", "Tỷ lệ dương", "Không thể đánh giá biên lợi nhuận."),
                ("governance_rule", "Quy tắc phê duyệt", "Văn bản", "Không xác định được Founder Approval Gate."),
            ]
            for field, label, expected, impact in profile_specs:
                value = profile.get(field)
                invalid = _is_blank(value)
                if field in {"cash_reserve_minimum", "target_gross_margin"} and not invalid:
                    invalid = _number(value) <= 0
                if invalid:
                    add_issue(
                        "BLOCKING",
                        "02_OPC_PROFILE",
                        field,
                        "value",
                        label,
                        f"02_OPC_PROFILE[field={field}].value",
                        f"Bổ sung giá trị cho {field}.",
                        expected,
                        impact,
                        "FIELD_MISSING" if _is_blank(value) else "VALUE_INVALID",
                    )

        customer = None
        if "03_CUSTOMERS" in present_sheets and customer_id:
            customer = _find_by(self.pack.rows("03_CUSTOMERS"), "customer_id", customer_id)
            if not customer:
                add_issue(
                    "BLOCKING",
                    "03_CUSTOMERS",
                    customer_id,
                    "record",
                    "Hồ sơ khách hàng liên kết",
                    f"03_CUSTOMERS[{customer_id}]",
                    f"Bổ sung một dòng khách hàng có customer_id={customer_id}.",
                    "Bản ghi khách hàng hợp lệ",
                    "Không thể đánh giá khách hàng và liên kết hợp đồng.",
                    "RECORD_MISSING",
                    ["customer_id", "customer_type", "province", "industry", "strategic_value", "payment_reliability"],
                )
            else:
                for field, label, expected in [
                    ("customer_id", "Mã khách hàng", "CUS-xxx"),
                    ("customer_type", "Loại khách hàng", "Phân loại khách hàng"),
                    ("strategic_value", "Giá trị chiến lược", "Low/Medium/High"),
                    ("payment_reliability", "Độ tin cậy thanh toán", "Tỷ lệ 0-1"),
                ]:
                    check_field(
                        customer,
                        field,
                        level="BLOCKING",
                        sheet="03_CUSTOMERS",
                        record_id=customer_id,
                        label=label,
                        expected_type=expected,
                        impact="Không thể hoàn tất đánh giá khách hàng.",
                        numeric=field == "payment_reliability",
                    )
                for field, label in [("province", "Tỉnh/thành"), ("industry", "Ngành"), ("revenue_model", "Mô hình doanh thu")]:
                    check_field(
                        customer,
                        field,
                        level="WARNING",
                        sheet="03_CUSTOMERS",
                        record_id=customer_id,
                        label=label,
                        expected_type="Văn bản",
                        impact="Giảm mức độ đầy đủ của phân tích bối cảnh khách hàng.",
                    )

        for field, label, expected, level, positive in [
            ("contract_id", "Mã hợp đồng", "CON-xxx", "BLOCKING", False),
            ("customer_id", "Mã khách hàng liên kết", "CUS-xxx", "BLOCKING", False),
            ("start_date", "Ngày bắt đầu", "Ngày hợp lệ", "BLOCKING", False),
            ("end_date", "Ngày kết thúc", "Ngày hợp lệ", "BLOCKING", False),
            ("status", "Trạng thái hợp đồng", "Văn bản", "BLOCKING", False),
            ("contract_value", "Giá trị hợp đồng", "VND dương", "BLOCKING", True),
            ("gross_margin", "Biên gộp tham chiếu", "Tỷ lệ dương", "WARNING", True),
            ("description", "Mô tả hợp đồng", "Văn bản", "WARNING", False),
            ("payment_terms", "Điều khoản thanh toán", "Văn bản", "WARNING", False),
        ]:
            check_field(
                contract,
                field,
                level=level,
                sheet="04_CONTRACTS",
                record_id=contract_id or "SELECTED",
                label=label,
                expected_type=expected,
                impact="Không thể tính toán hoặc truy vết đầy đủ hợp đồng." if level == "BLOCKING" else "Giảm khả năng giải thích điều kiện thương mại.",
                positive=positive,
            )

        products = self.pack.rows("05_PRODUCTS") if "05_PRODUCTS" in present_sheets else []
        products_by_id = {row.get("service_id"): row for row in products if row.get("service_id")}
        orders = [row for row in self.pack.rows("06_ORDERS") if row.get("contract_id") == contract_id] if "06_ORDERS" in present_sheets else []
        if "06_ORDERS" in present_sheets and not orders:
            add_issue(
                "BLOCKING",
                "06_ORDERS",
                f"contract_id={contract_id}",
                "record",
                "Đơn hàng liên kết hợp đồng",
                f"06_ORDERS[contract_id={contract_id}]",
                f"Bổ sung ít nhất một order có contract_id={contract_id}.",
                "Ít nhất 1 bản ghi order",
                "Không thể tính doanh thu, chi phí và biên gộp.",
                "RECORD_MISSING",
                sheet_requirements["06_ORDERS"],
            )
        for index, order in enumerate(orders, start=2):
            order_id = _safe_text(order.get("order_id")) or f"row={index}"
            for field, label, expected, positive in [
                ("order_id", "Mã đơn hàng", "ORD-xxx", False),
                ("contract_id", "Mã hợp đồng", "CON-xxx", False),
                ("customer_id", "Mã khách hàng", "CUS-xxx", False),
                ("order_date", "Ngày đặt hàng", "Ngày hợp lệ", False),
                ("due_date", "Ngày đến hạn", "Ngày hợp lệ", False),
                ("status", "Trạng thái đơn hàng", "Văn bản", False),
                ("service_id", "Mã dịch vụ", "SVC-xxx", False),
                ("order_revenue", "Doanh thu đơn hàng", "VND dương", True),
                ("estimated_cost", "Chi phí ước tính", "VND dương", True),
            ]:
                check_field(
                    order,
                    field,
                    level="BLOCKING",
                    sheet="06_ORDERS",
                    record_id=order_id,
                    label=label,
                    expected_type=expected,
                    impact="Không thể tính và truy vết Financial Snapshot chính xác.",
                    positive=positive,
                )
            if not _is_blank(order.get("customer_id")) and order.get("customer_id") != customer_id:
                add_issue(
                    "BLOCKING",
                    "06_ORDERS",
                    order_id,
                    "customer_id",
                    "Liên kết khách hàng không khớp",
                    f"06_ORDERS[{order_id}].customer_id",
                    f"Đồng bộ customer_id với hợp đồng {contract_id}.",
                    customer_id,
                    "Order đang liên kết sai khách hàng của hợp đồng.",
                    "REFERENCE_BROKEN",
                )
            service_id = _safe_text(order.get("service_id"))
            if service_id and "05_PRODUCTS" in present_sheets and service_id not in products_by_id:
                add_issue(
                    "BLOCKING",
                    "05_PRODUCTS",
                    service_id,
                    "record",
                    "Sản phẩm/dịch vụ được order tham chiếu",
                    f"05_PRODUCTS[{service_id}]",
                    f"Bổ sung sản phẩm {service_id} được {order_id} tham chiếu.",
                    "Bản ghi sản phẩm hợp lệ",
                    "Không thể đối chiếu giá và biên mục tiêu của dịch vụ.",
                    "RECORD_MISSING",
                    sheet_requirements["05_PRODUCTS"],
                )
            if _is_blank(order.get("delivery_note")):
                add_issue(
                    "OPTIONAL",
                    "06_ORDERS",
                    order_id,
                    "delivery_note",
                    "Ghi chú giao hàng",
                    f"06_ORDERS[{order_id}].delivery_note",
                    "Chỉ bổ sung khi có ghi chú vận hành.",
                    "Văn bản tùy chọn",
                    "Không ảnh hưởng quyết định ở trạng thái hiện tại.",
                    "OPTIONAL_BLANK",
                )

        order_ids = {_safe_text(row.get("order_id")) for row in orders if _safe_text(row.get("order_id"))}
        invoices = [row for row in self.pack.rows("07_INVOICES") if _safe_text(row.get("order_id")) in order_ids] if "07_INVOICES" in present_sheets else []
        if "07_INVOICES" in present_sheets:
            invoice_order_ids = {_safe_text(row.get("order_id")) for row in invoices}
            for order in orders:
                order_id = _safe_text(order.get("order_id"))
                if order_id and order_id not in invoice_order_ids:
                    add_issue(
                        "WARNING",
                        "07_INVOICES",
                        f"order_id={order_id}",
                        "record",
                        "Hóa đơn liên kết đơn hàng",
                        f"07_INVOICES[order_id={order_id}]",
                        f"Bổ sung invoice khi {order_id} đủ điều kiện phát hành.",
                        "Bản ghi invoice",
                        "Partner factoring có thể chưa đánh giá được order này.",
                        "RECORD_MISSING",
                        sheet_requirements["07_INVOICES"],
                    )
            for index, invoice in enumerate(invoices, start=2):
                invoice_id = _safe_text(invoice.get("invoice_id")) or f"row={index}"
                status = _safe_text(invoice.get("status")).lower()
                for field, label, expected, positive in [
                    ("invoice_id", "Mã hóa đơn", "INV-xxx", False),
                    ("order_id", "Mã đơn hàng", "ORD-xxx", False),
                    ("customer_id", "Mã khách hàng", "CUS-xxx", False),
                    ("due_date", "Ngày đến hạn", "Ngày hợp lệ", False),
                    ("status", "Trạng thái hóa đơn", "Văn bản", False),
                    ("invoice_amount", "Giá trị hóa đơn", "VND dương", True),
                ]:
                    check_field(
                        invoice,
                        field,
                        level="BLOCKING",
                        sheet="07_INVOICES",
                        record_id=invoice_id,
                        label=label,
                        expected_type=expected,
                        impact="Không thể đối soát khoản phải thu và điều kiện factoring.",
                        positive=positive,
                    )
                if status in {"open", "paid", "issued", "approved"}:
                    check_field(
                        invoice,
                        "issue_date",
                        level="BLOCKING",
                        sheet="07_INVOICES",
                        record_id=invoice_id,
                        label="Ngày phát hành",
                        expected_type="Ngày hợp lệ",
                        impact="Không thể xác minh vòng đời hóa đơn.",
                    )
                elif _is_blank(invoice.get("issue_date")):
                    add_issue(
                        "OPTIONAL",
                        "07_INVOICES",
                        invoice_id,
                        "issue_date",
                        "Ngày phát hành",
                        f"07_INVOICES[{invoice_id}].issue_date",
                        "Bổ sung khi hóa đơn được phát hành.",
                        "Ngày tùy theo trạng thái",
                        "Không ảnh hưởng khi hóa đơn chưa phát hành.",
                        "OPTIONAL_BLANK",
                    )
                if status == "paid":
                    check_field(
                        invoice,
                        "paid_date",
                        level="BLOCKING",
                        sheet="07_INVOICES",
                        record_id=invoice_id,
                        label="Ngày thanh toán",
                        expected_type="Ngày hợp lệ",
                        impact="Không thể xác nhận hóa đơn đã được thanh toán.",
                    )
                elif _is_blank(invoice.get("paid_date")):
                    add_issue(
                        "OPTIONAL",
                        "07_INVOICES",
                        invoice_id,
                        "paid_date",
                        "Ngày thanh toán",
                        f"07_INVOICES[{invoice_id}].paid_date",
                        "Chỉ bổ sung khi trạng thái chuyển thành Paid.",
                        "Ngày tùy theo trạng thái",
                        "Không ảnh hưởng khi hóa đơn chưa được thanh toán.",
                        "OPTIONAL_BLANK",
                    )

        if "08_BANK_TXN" in present_sheets:
            bank_rows = self.pack.rows("08_BANK_TXN")
            if not bank_rows:
                add_issue(
                    "BLOCKING", "08_BANK_TXN", "SHEET", "record", "Dữ liệu giao dịch ngân hàng", "08_BANK_TXN",
                    "Bổ sung giao dịch nền để kiểm tra dòng tiền và bất thường.", "Ít nhất 1 giao dịch", "Không thể đánh giá rủi ro giao dịch.", "RECORD_MISSING",
                )
            for index, row in enumerate(bank_rows, start=2):
                record_id = _safe_text(row.get("txn_id")) or f"row={index}"
                for field, label, expected, nonzero in [
                    ("txn_id", "Mã giao dịch", "TXN-xxx", False),
                    ("txn_date", "Ngày giao dịch", "Ngày hợp lệ", False),
                    ("direction", "Chiều giao dịch", "Credit/Debit", False),
                    ("amount", "Số tiền giao dịch", "VND khác 0", True),
                    ("txn_status", "Trạng thái giao dịch", "Văn bản", False),
                    ("transaction_risk_score", "Điểm rủi ro giao dịch", "Số 0-100", False),
                ]:
                    check_field(
                        row, field, level="BLOCKING", sheet="08_BANK_TXN", record_id=record_id, label=label,
                        expected_type=expected, impact="Không thể đánh giá đầy đủ dòng tiền và rủi ro giao dịch.",
                        nonzero=nonzero, numeric=field == "transaction_risk_score",
                    )
                for field, label in [("bank", "Ngân hàng"), ("account_id", "Tài khoản"), ("description", "Mô tả"), ("counterparty_id", "Đối tác giao dịch")]:
                    check_field(
                        row, field, level="WARNING", sheet="08_BANK_TXN", record_id=record_id, label=label,
                        expected_type="Văn bản", impact="Giảm khả năng truy vết giao dịch.",
                    )

        if "09_CASHFLOW" in present_sheets:
            cashflow_rows = self.pack.rows("09_CASHFLOW")
            if not cashflow_rows:
                add_issue(
                    "BLOCKING", "09_CASHFLOW", "SHEET", "record", "Dự báo dòng tiền", "09_CASHFLOW",
                    "Bổ sung ít nhất một tháng dự báo dòng tiền.", "Ít nhất 1 dòng theo tháng", "Không thể tính funding gap.", "RECORD_MISSING",
                )
            for index, row in enumerate(cashflow_rows, start=2):
                record_id = _safe_text(row.get("month")) or f"row={index}"
                for field, label, expected, positive in [
                    ("month", "Tháng", "YYYY-MM", False),
                    ("expected_cash_in", "Dòng tiền vào dự kiến", "Số VND", False),
                    ("expected_cash_out", "Dòng tiền ra dự kiến", "Số VND", False),
                    ("direct_cost", "Chi phí trực tiếp", "Số VND", False),
                    ("opex", "Chi phí vận hành", "Số VND", False),
                    ("cash_reserve_minimum", "Dự trữ tối thiểu", "VND dương", True),
                    ("projected_closing_cash", "Tiền cuối tháng dự kiến", "Số VND", False),
                ]:
                    check_field(
                        row, field, level="BLOCKING", sheet="09_CASHFLOW", record_id=record_id, label=label,
                        expected_type=expected, impact="Không thể xác nhận Cashflow Before/After.", positive=positive,
                        numeric=field not in {"month", "cash_reserve_minimum"},
                    )

        credit_mappings = self._credit_case_mappings(contract) if "10_CREDIT_PROFILE" in present_sheets else []
        signals = self._contract_signals(contract)
        liquidity_mappings = [
            item for item in credit_mappings
            if item["category"] != "PERFORMANCE_BOND" and item["requested_amount"] > 0
        ]
        bond_mappings = [item for item in credit_mappings if item["category"] == "PERFORMANCE_BOND"]
        trade_mappings = [item for item in credit_mappings if item["category"] == "TRADE_FINANCE"]
        factoring_products = [
            row for row in self.pack.rows("11_BANK_PRODUCTS")
            if self._product_category(row) == "FACTORING"
        ] if "11_BANK_PRODUCTS" in present_sheets else []
        factoring_available = bool(signals["eligible_invoices"] and factoring_products)

        if "10_CREDIT_PROFILE" in present_sheets:
            if not liquidity_mappings:
                add_issue(
                    "BLOCKING",
                    "10_CREDIT_PROFILE",
                    f"contract_id={contract_id}",
                    "contract_id",
                    "Hồ sơ tài trợ liên kết hợp đồng",
                    f"10_CREDIT_PROFILE[contract_id={contract_id}]",
                    (
                        f"Bổ sung credit case có contract_id={contract_id}, request_type và requested_amount. "
                        "Hóa đơn chỉ mở thêm phương án factoring, không thay thế hồ sơ tín dụng liên kết."
                    ),
                    "Credit case liên kết đúng contract_id",
                    "Không thể xác nhận năng lực tài trợ riêng cho hợp đồng; hệ thống không dùng hồ sơ của hợp đồng khác.",
                    "RECORD_MISSING",
                    ["credit_case_id", "contract_id", "request_type", "requested_amount", "eligibility_score"],
                )
            if signals["bond_required"] and not bond_mappings:
                add_issue(
                    "BLOCKING", "10_CREDIT_PROFILE", f"contract_id={contract_id}", "contract_id",
                    "Hồ sơ bảo lãnh thực hiện liên kết hợp đồng",
                    f"10_CREDIT_PROFILE[contract_id={contract_id};request_type=Performance bond]",
                    f"Bổ sung hồ sơ Performance bond tham chiếu chính xác {contract_id}.",
                    "Credit case Performance bond liên kết đúng contract_id",
                    "Không thể tính tiền ký quỹ, phí bảo lãnh và partner precheck cho hợp đồng này.",
                    "RECORD_MISSING",
                    ["credit_case_id", "contract_id", "request_type", "requested_amount", "eligibility_score"],
                )
            if signals["trade_required"] and not trade_mappings:
                add_issue(
                    "BLOCKING", "10_CREDIT_PROFILE", f"contract_id={contract_id}", "contract_id",
                    "Hồ sơ trade finance/LC liên kết hợp đồng",
                    f"10_CREDIT_PROFILE[contract_id={contract_id};request_type=Trade finance/LC support]",
                    f"Bổ sung hồ sơ Trade finance/LC support tham chiếu chính xác {contract_id}.",
                    "Credit case Trade finance/LC liên kết đúng contract_id",
                    "Không thể đánh giá phương án tài trợ thương mại cho hợp đồng.",
                    "RECORD_MISSING",
                    ["credit_case_id", "contract_id", "request_type", "requested_amount", "eligibility_score"],
                )

            for mapping in credit_mappings:
                row = mapping["row"]
                record_id = mapping["credit_case_id"] or mapping["request_type"]
                for field, label, expected, positive in [
                    ("credit_case_id", "Mã hồ sơ tín dụng", "CR-xxx", False),
                    ("company_id", "Mã doanh nghiệp", "OPC-xxx", False),
                    ("request_type", "Loại yêu cầu", "Văn bản", False),
                    ("requested_amount", "Số tiền đề nghị", "VND dương", True),
                    ("eligibility_score", "Điểm đủ điều kiện", "Tỷ lệ 0-1", False),
                ]:
                    check_field(
                        row, field, level="BLOCKING", sheet="10_CREDIT_PROFILE", record_id=record_id, label=label,
                        expected_type=expected, impact="Không thể đánh giá đúng khả năng tài trợ.", positive=positive,
                        numeric=field == "eligibility_score",
                    )
                for field, label in [("tenor", "Kỳ hạn"), ("collateral_or_basis", "Cơ sở bảo đảm"), ("approval_status", "Trạng thái phê duyệt")]:
                    check_field(
                        row, field, level="WARNING", sheet="10_CREDIT_PROFILE", record_id=record_id, label=label,
                        expected_type="Văn bản", impact="Giảm độ đầy đủ của partner precheck.",
                    )
                if mapping["mapping_scope"] == "ENTERPRISE_SHARED":
                    add_issue(
                        "WARNING", "10_CREDIT_PROFILE", record_id, "contract_id",
                        "Hạn mức dùng chung cấp doanh nghiệp",
                        mapping["mapping_source"],
                        f"Founder xác nhận phần hạn mức còn khả dụng cho {contract_id}; nên bổ sung contract_id khi dành riêng hạn mức.",
                        "Xác nhận availability cho lượt chạy hiện tại",
                        "Hạn mức này không thuộc riêng hợp đồng và không được coi là phê duyệt ngân hàng.",
                        "SHARED_CAPACITY_REVIEW",
                    )

        linked_products: dict[str, dict[str, Any]] = {}
        for mapping in credit_mappings:
            if not mapping["products"]:
                add_issue(
                    "BLOCKING", "11_BANK_PRODUCTS", mapping["request_type"], "record",
                    "Sản phẩm ngân hàng phù hợp credit case",
                    f"11_BANK_PRODUCTS[request_type={mapping['request_type']}]",
                    f"Bổ sung bank_product_id hoặc sản phẩm khớp request_type {mapping['request_type']}.",
                    "Bank product liên kết theo bank_product_id/request_type",
                    "Không thể tạo Partner Option Matrix có nguồn dữ liệu.",
                    "RECORD_MISSING", sheet_requirements["11_BANK_PRODUCTS"],
                )
            for product in mapping["products"]:
                linked_products[_safe_text(product.get("bank_product_id"))] = product
        if signals["eligible_invoices"]:
            if not factoring_products:
                add_issue(
                    "WARNING", "11_BANK_PRODUCTS", "FACTORING", "record", "Sản phẩm bao thanh toán",
                    "11_BANK_PRODUCTS[category=FACTORING]", "Bổ sung sản phẩm Invoice factoring nếu muốn đánh giá hóa đơn mở.",
                    "Bank product factoring", "Không thể đưa factoring vào Partner Matrix.", "RECORD_MISSING",
                    sheet_requirements["11_BANK_PRODUCTS"],
                )
            for product in factoring_products:
                linked_products[_safe_text(product.get("bank_product_id"))] = product

        if "11_BANK_PRODUCTS" in present_sheets:
            for product_id, row in linked_products.items():
                for field, label, expected, numeric in [
                    ("bank_product_id", "Mã sản phẩm", "BANKPROD-xxx", False),
                    ("bank", "Nhà cung cấp", "Văn bản", False),
                    ("product_name", "Tên sản phẩm", "Văn bản", False),
                    ("annual_rate_or_fee", "Lãi suất/phí", "Tỷ lệ số", True),
                    ("processing_fee_rate", "Phí xử lý", "Tỷ lệ số", True),
                    ("collateral_ratio", "Tỷ lệ tài sản bảo đảm", "Tỷ lệ số", True),
                    ("minimum_amount", "Số tiền tối thiểu", "Số VND", True),
                ]:
                    check_field(
                        row, field, level="BLOCKING", sheet="11_BANK_PRODUCTS", record_id=product_id, label=label,
                        expected_type=expected, impact="Không thể tính đầy đủ chi phí và mức phù hợp của phương án.", numeric=numeric,
                    )

        if "12_API_CATALOG" in present_sheets and not self.pack.rows("12_API_CATALOG"):
            add_issue(
                "WARNING", "12_API_CATALOG", "SHEET", "record", "Danh mục API mô phỏng", "12_API_CATALOG",
                "Bổ sung API catalog để tăng khả năng truy vết.", "Ít nhất 1 API", "Giảm bằng chứng kiến trúc và audit.", "RECORD_MISSING",
            )

        if "13_RISK_RULES" in present_sheets:
            risk_rows = self.pack.rows("13_RISK_RULES")
            if not risk_rows:
                add_issue(
                    "BLOCKING", "13_RISK_RULES", "SHEET", "record", "Quy tắc rủi ro", "13_RISK_RULES",
                    "Bổ sung risk rules để kiểm soát quyết định.", "Ít nhất 1 rule", "Không thể xác nhận Risk Report.", "RECORD_MISSING",
                )
            for index, row in enumerate(risk_rows, start=2):
                record_id = _safe_text(row.get("rule_id")) or f"row={index}"
                for field, label in [("rule_id", "Mã quy tắc"), ("risk_type", "Loại rủi ro"), ("trigger_condition", "Điều kiện kích hoạt"), ("severity", "Mức độ"), ("required_action", "Hành động bắt buộc"), ("owner_agent", "Agent phụ trách")]:
                    check_field(
                        row, field, level="BLOCKING", sheet="13_RISK_RULES", record_id=record_id, label=label,
                        expected_type="Văn bản", impact="Không thể kiểm soát và giải thích Risk Report.",
                    )

        if "14_ALERTS" in present_sheets:
            for index, row in enumerate(self.pack.rows("14_ALERTS"), start=2):
                record_id = _safe_text(row.get("alert_id")) or f"row={index}"
                for field, label, level, numeric in [
                    ("alert_id", "Mã cảnh báo", "BLOCKING", False),
                    ("alert_type", "Loại cảnh báo", "BLOCKING", False),
                    ("related_record", "Bản ghi liên quan", "BLOCKING", False),
                    ("severity", "Mức độ", "BLOCKING", False),
                    ("risk_score", "Điểm rủi ro", "BLOCKING", True),
                    ("description", "Mô tả cảnh báo", "WARNING", False),
                    ("recommended_action", "Hành động đề xuất", "WARNING", False),
                ]:
                    check_field(
                        row, field, level=level, sheet="14_ALERTS", record_id=record_id, label=label,
                        expected_type="Số 0-100" if numeric else "Văn bản", impact="Giảm độ đầy đủ và khả năng hành động của Risk Report.", numeric=numeric,
                    )

        if "20_DATA_CLASS" in present_sheets:
            class_rows = self.pack.rows("20_DATA_CLASS")
            if not class_rows:
                add_issue(
                    "BLOCKING", "20_DATA_CLASS", "SHEET", "record", "Quy tắc phân loại dữ liệu", "20_DATA_CLASS",
                    "Bổ sung data classification trước khi gọi OpenAI.", "Ít nhất 1 quy tắc", "Không thể xác định masking và logging an toàn.", "RECORD_MISSING",
                )
            for index, row in enumerate(class_rows, start=2):
                record_id = _safe_text(row.get("data_pattern")) or f"row={index}"
                for field, label in [("data_pattern", "Mẫu dữ liệu"), ("classification", "Phân loại"), ("external_api_rule", "Quy tắc API ngoài"), ("masking_or_tokenization", "Quy tắc masking"), ("logging_rule", "Quy tắc log")]:
                    check_field(
                        row, field, level="BLOCKING", sheet="20_DATA_CLASS", record_id=record_id, label=label,
                        expected_type="Văn bản", impact="Không thể bảo đảm dữ liệu được xử lý an toàn trước khi gọi API.",
                    )

        evidence_specs = [
            ("contract_signed", "Hợp đồng đã ký/biên bản phạm vi", "Bổ sung bằng chứng hợp đồng đã ký."),
            ("receivable_aging", "Bảng tuổi nợ phải thu", "Bổ sung bảng tuổi nợ hỗ trợ hạn mức vốn lưu động."),
            ("capacity_plan", "Kế hoạch năng lực triển khai", "Bổ sung capacity plan theo giai đoạn/địa bàn."),
        ]
        for field, label, request in evidence_specs:
            if not evidence.get(field):
                add_issue(
                    "BLOCKING", "FOUNDER_EVIDENCE", contract_id, field, label, f"FOUNDER_EVIDENCE[{contract_id}].{field}",
                    request, "Bằng chứng được Founder xác nhận", "Workflow không được đưa ra quyết định cuối khi thiếu bằng chứng này.", "EVIDENCE_MISSING",
                )

        level_order = {"BLOCKING": 0, "WARNING": 1, "OPTIONAL": 2}
        issues.sort(
            key=lambda item: (
                level_order.get(item["level"], 9),
                sheet_order.get(item["sheet"], len(sheet_order)),
                item["record_id"],
                item["field"],
            )
        )
        for index, issue in enumerate(issues, start=1):
            issue["issue_id"] = f"DQ-{index:03d}"

        blocking = [item for item in issues if item["level"] == "BLOCKING"]
        warnings = [item for item in issues if item["level"] == "WARNING"]
        optional = [item for item in issues if item["level"] == "OPTIONAL"]
        affected_sheets = sorted(
            {item["sheet"] for item in issues},
            key=lambda name: sheet_order.get(name, len(sheet_order)),
        )
        return {
            "status": "BLOCKED" if blocking else "READY_WITH_WARNINGS" if warnings else "READY",
            "blocking_count": len(blocking),
            "warning_count": len(warnings),
            "optional_count": len(optional),
            "total_issue_count": len(issues),
            "affected_sheet_count": len(affected_sheets),
            "affected_sheets": affected_sheets,
            "checked_sheets": DATA_QUALITY_SHEETS,
            "checked_sheet_count": sum(name in present_sheets for name in DATA_QUALITY_SHEETS),
            "issues": issues,
            "blocking": blocking,
            "warnings": warnings,
            "optional": optional,
            "truth_source": "Deterministic TeamPack validator; OpenAI may explain but cannot add, remove, or reclassify issues.",
        }

    def _contract_cashflow_profile(
        self,
        contract_id: str,
        orders: list[dict[str, Any]],
        invoices: list[dict[str, Any]],
        scenario: dict[str, float],
    ) -> list[dict[str, Any]]:
        """Build baseline/scenario cashflow only from rows linked to contract_id."""
        selected_order_ids = {
            _safe_text(row.get("order_id"))
            for row in orders
            if _safe_text(row.get("order_id"))
        }
        order_due_months = {
            _safe_text(row.get("order_id")): _month(row.get("due_date"))
            for row in orders
            if _safe_text(row.get("order_id"))
        }
        invoices_by_order: dict[str, list[dict[str, Any]]] = {}
        for row in invoices:
            order_id = _safe_text(row.get("order_id"))
            # Keep this boundary defensive even though _finance_agent already
            # supplies contract-linked invoices. It prevents an unrelated row
            # from entering the selected contract's chart when this helper is
            # called directly or reused later.
            if not order_id or order_id not in selected_order_ids:
                continue
            invoices_by_order.setdefault(order_id, []).append(row)
        for linked_rows in invoices_by_order.values():
            linked_rows.sort(
                key=lambda row: (
                    _month(row.get("paid_date")) or _month(row.get("due_date")) or "9999-99",
                    _safe_text(row.get("invoice_id")),
                )
            )

        selected_delayed_invoice_id: str | None = None
        if scenario["payment_delay_days"] > 0 and invoices:
            eligible_invoices: list[tuple[float, str, str]] = []
            for order_id, linked_rows in invoices_by_order.items():
                for row in linked_rows:
                    status = _safe_text(row.get("status")).lower()
                    paid_month = _month(row.get("paid_date"))
                    collection_month = (
                        paid_month
                        if status == "paid" and paid_month
                        else _month(row.get("due_date")) or order_due_months.get(order_id)
                    )
                    amount = _number(row.get("invoice_amount"))
                    invoice_id = _safe_text(row.get("invoice_id"))
                    # Actual paid receipts must remain on their paid date. The
                    # stress delay applies to the largest forecast receipt only.
                    if (
                        amount > 0
                        and invoice_id
                        and collection_month
                        and not (status == "paid" and paid_month)
                    ):
                        eligible_invoices.append((amount, collection_month, invoice_id))
            if eligible_invoices:
                # Largest amount first; month and ID make ties deterministic.
                selected_delayed_invoice_id = min(
                    eligible_invoices,
                    key=lambda item: (-item[0], item[1], item[2]),
                )[2]
        scope_factor = 1 + scenario["scope_change_pct"] / 100
        cost_factor = scope_factor * (1 + scenario["cost_increase_pct"] / 100)
        delay_months = max(1, math.ceil(scenario["payment_delay_days"] / 30)) if scenario["payment_delay_days"] > 0 else 0
        events: dict[str, dict[str, Any]] = {}

        def event(month: str) -> dict[str, Any]:
            return events.setdefault(
                month,
                {
                    "baseline_cash_in": 0.0,
                    "baseline_cash_out": 0.0,
                    "scenario_cash_in": 0.0,
                    "scenario_cash_out": 0.0,
                    "sources": [],
                    "collection_basis": [],
                },
            )

        def append_lineage(target: dict[str, Any], source: str, basis: str) -> None:
            if source not in target["sources"]:
                target["sources"].append(source)
            if basis not in target["collection_basis"]:
                target["collection_basis"].append(basis)

        def add_collection(
            order_id: str,
            collection_month: str | None,
            amount: float,
            source: str,
            basis: str,
            invoice_id: str | None = None,
        ) -> None:
            if not collection_month or amount <= 0:
                return
            baseline_target = event(collection_month)
            baseline_target["baseline_cash_in"] += amount
            baseline_lineage = f"{order_id}:{basis}"
            append_lineage(baseline_target, source, baseline_lineage)

            scenario_month = (
                _shift_month(collection_month, delay_months)
                if invoice_id and invoice_id == selected_delayed_invoice_id and delay_months
                else collection_month
            )
            scenario_target = event(scenario_month)
            scenario_target["scenario_cash_in"] += amount * scope_factor
            scenario_lineage = baseline_lineage + (
                f":DELAYED_{delay_months}_MONTH" if scenario_month != collection_month else ""
            )
            append_lineage(scenario_target, source, scenario_lineage)

        for order in sorted(orders, key=lambda row: _safe_text(row.get("order_id"))):
            order_id = _safe_text(order.get("order_id")) or "UNKNOWN_ORDER"
            cost_month = _month(order.get("order_date")) or _month(order.get("due_date"))
            cost = _number(order.get("estimated_cost"))
            if cost_month and cost > 0:
                target = event(cost_month)
                target["baseline_cash_out"] += cost
                target["scenario_cash_out"] += cost * cost_factor
                target["sources"].append(f"06_ORDERS[{order_id}].estimated_cost")

            linked_invoices = invoices_by_order.get(order_id, [])
            invoiced_total = 0.0
            for invoice in linked_invoices:
                amount = _number(invoice.get("invoice_amount"))
                if amount <= 0:
                    continue
                invoiced_total += amount
                status = _safe_text(invoice.get("status")).lower()
                if status == "paid" and _month(invoice.get("paid_date")):
                    collection_month = _month(invoice.get("paid_date"))
                    basis = "PAID_DATE_ACTUAL"
                else:
                    collection_month = _month(invoice.get("due_date")) or _month(order.get("due_date"))
                    basis = "INVOICE_DUE_FORECAST" if status not in {"not issued", "draft"} else "UNISSUED_INVOICE_FORECAST"
                invoice_id = _safe_text(invoice.get("invoice_id")) or order_id
                source = f"07_INVOICES[{invoice_id}].invoice_amount"
                add_collection(
                    order_id,
                    collection_month,
                    amount,
                    source,
                    f"{invoice_id}:{basis}",
                    invoice_id,
                )

            # Invoice milestones may cover only part of the order. Forecast the
            # unbilled remainder once (never once per invoice) at the order due
            # date. When invoices exceed order revenue, keep their actual values
            # and add no artificial negative/offsetting residual.
            order_revenue = _number(order.get("order_revenue"))
            unbilled_residual = max(0.0, order_revenue - invoiced_total)
            if unbilled_residual > 0:
                add_collection(
                    order_id,
                    _month(order.get("due_date")),
                    unbilled_residual,
                    f"06_ORDERS[{order_id}].order_revenue",
                    f"UNBILLED_RESIDUAL_AFTER_INVOICES[{invoiced_total:.0f}]",
                )

        if not events:
            return []

        first_month = min(events)
        last_month = max(events)
        months: list[str] = []
        month = first_month
        while month <= last_month:
            months.append(month)
            month = _shift_month(month, 1)

        cumulative_baseline = 0.0
        cumulative_scenario = 0.0
        profile: list[dict[str, Any]] = []
        for month in months:
            values = events.get(
                month,
                {
                    "baseline_cash_in": 0.0,
                    "baseline_cash_out": 0.0,
                    "scenario_cash_in": 0.0,
                    "scenario_cash_out": 0.0,
                    "sources": [],
                    "collection_basis": [],
                },
            )
            baseline_net = values["baseline_cash_in"] - values["baseline_cash_out"]
            scenario_net = values["scenario_cash_in"] - values["scenario_cash_out"]
            cumulative_baseline += baseline_net
            cumulative_scenario += scenario_net
            profile.append(
                {
                    "month": month,
                    "cash_in": values["scenario_cash_in"],
                    "cash_out": values["scenario_cash_out"],
                    "net_cashflow": scenario_net,
                    "cumulative_cashflow": cumulative_scenario,
                    "baseline_cash_in": values["baseline_cash_in"],
                    "baseline_cash_out": values["baseline_cash_out"],
                    "baseline_net_cashflow": baseline_net,
                    "baseline_cumulative_cashflow": cumulative_baseline,
                    "funding_gap": max(0.0, -cumulative_scenario),
                    "break_even": 0.0,
                    "sources": values["sources"],
                    "collection_basis": values["collection_basis"],
                    "contract_id": contract_id,
                }
            )
        return profile

    def _finance_agent(
        self,
        contract: dict[str, Any],
        scenario: dict[str, float],
        evidence: dict[str, bool],
        trace_id: str,
        workflow: list[dict[str, Any]],
    ) -> dict[str, Any]:
        contract_id = _safe_text(contract.get("contract_id"))
        customer_id = _safe_text(contract.get("customer_id"))
        customer = _find_by(self.pack.rows("03_CUSTOMERS"), "customer_id", customer_id)
        orders = [row for row in self.pack.rows("06_ORDERS") if row.get("contract_id") == contract_id]
        order_ids = {row.get("order_id") for row in orders if row.get("order_id")}
        contract_invoices = [
            row for row in self.pack.rows("07_INVOICES") if row.get("order_id") in order_ids
        ]
        contract_cashflow = self._contract_cashflow_profile(contract_id, orders, contract_invoices, scenario)
        contract_value = _number(contract.get("contract_value"))
        revenue = sum(_number(row.get("order_revenue")) for row in orders)
        base_cost = sum(_number(row.get("estimated_cost")) for row in orders)
        order_coverage_ratio = revenue / contract_value if contract_value else 0.0
        scope_factor = 1 + scenario["scope_change_pct"] / 100
        scenario_revenue = revenue * scope_factor
        scenario_cost = base_cost * scope_factor * (1 + scenario["cost_increase_pct"] / 100)
        gross_margin = (scenario_revenue - scenario_cost) / scenario_revenue if scenario_revenue else 0.0

        profile = self.pack.profile()
        reserve_default = _number(profile.get("cash_reserve_minimum"), 550_000_000)
        target_margin = _number(profile.get("target_gross_margin"), 0.28)
        margin_comparison = _margin_comparison(gross_margin, target_margin)
        cashflow_rows = self.pack.rows("09_CASHFLOW")
        cashflow: list[dict[str, Any]] = []

        monthly_cost_delta: dict[str, float] = {}
        for order in orders:
            due_month = _month(order.get("due_date"))
            if due_month:
                incremental = _number(order.get("estimated_cost")) * (
                    scope_factor * (1 + scenario["cost_increase_pct"] / 100) - 1
                )
                monthly_cost_delta[due_month] = monthly_cost_delta.get(due_month, 0.0) + incremental

        payment_shift_amount = 0.0
        payment_source_month: str | None = None
        payment_target_month: str | None = None
        if scenario["payment_delay_days"] > 0:
            if contract_invoices:
                selected = max(contract_invoices, key=lambda row: _number(row.get("invoice_amount")))
                payment_shift_amount = _number(selected.get("invoice_amount"))
                payment_source_month = _month(selected.get("due_date"))
                if payment_source_month:
                    payment_target_month = _shift_month(
                        payment_source_month,
                        max(1, math.ceil(scenario["payment_delay_days"] / 30)),
                    )

        for row in cashflow_rows:
            month = _safe_text(row.get("month"))
            baseline = _number(row.get("projected_closing_cash"))
            reserve = _number(row.get("cash_reserve_minimum"), reserve_default)
            scenario_cash = baseline - monthly_cost_delta.get(month, 0.0)
            if payment_source_month == month:
                scenario_cash -= payment_shift_amount
            if payment_target_month == month:
                scenario_cash += payment_shift_amount
            cashflow.append(
                {
                    "month": month,
                    "baseline_closing_cash": baseline,
                    "scenario_closing_cash": scenario_cash,
                    "reserve_minimum": reserve,
                    "funding_gap": max(0.0, reserve - scenario_cash),
                    "source": f"09_CASHFLOW[{month}]",
                }
            )

        # The enterprise forecast in 09_CASHFLOW remains context only. Contract
        # liquidity must come from the selected contract's own orders/invoices.
        peak_gap_row = max(contract_cashflow, key=lambda item: item["funding_gap"]) if contract_cashflow else {}
        peak_funding_gap = _number(peak_gap_row.get("funding_gap"))
        credit_mappings = self._credit_case_mappings(contract)
        liquidity_mappings = [
            item for item in credit_mappings
            if item["category"] != "PERFORMANCE_BOND" and item["requested_amount"] > 0
        ]
        bond_mappings = [item for item in credit_mappings if item["category"] == "PERFORMANCE_BOND"]
        working_capital_request = max(
            (
                item["requested_amount"]
                for item in liquidity_mappings
                if item["category"] in {"WORKING_CAPITAL", "MICRO_WORKING_CAPITAL"}
            ),
            default=0.0,
        )
        performance_bond_mapping = bond_mappings[0] if bond_mappings else None
        performance_bond_request = (
            performance_bond_mapping["requested_amount"] if performance_bond_mapping else 0.0
        )
        bond_product = (
            performance_bond_mapping["products"][0]
            if performance_bond_mapping and performance_bond_mapping["products"]
            else {}
        )
        base_collateral_ratio = _number(bond_product.get("collateral_ratio"))
        guarantee_collateral_ratio = min(
            1.0,
            max(0.0, base_collateral_ratio + scenario["collateral_change_pp"] / 100),
        )
        contract_start = _as_date(contract.get("start_date"))
        contract_end = _as_date(contract.get("end_date"))
        guarantee_duration_days = max(1, (contract_end - contract_start).days) if contract_start and contract_end else 365
        guarantee_fee_rate = _number(bond_product.get("annual_rate_or_fee"))
        guarantee_collateral = performance_bond_request * guarantee_collateral_ratio
        guarantee_fee = performance_bond_request * guarantee_fee_rate * guarantee_duration_days / 365
        guarantee_cash_impact = guarantee_collateral + guarantee_fee
        immediate_liquidity_need = peak_funding_gap + guarantee_cash_impact
        signals = self._contract_signals(contract)
        factoring_capacity = sum(
            _number(row.get("invoice_amount")) for row in signals["eligible_invoices"]
        )
        mapped_case_capacity = max(
            (item["requested_amount"] for item in liquidity_mappings),
            default=0.0,
        )
        # Partner products are alternatives, therefore capacities are not added
        # together. The best grounded option is used for the hard-gate coverage.
        potential_funding_capacity = max(mapped_case_capacity, factoring_capacity)
        liquidity_headroom = potential_funding_capacity - immediate_liquidity_need
        funding_coverage_ratio = (
            potential_funding_capacity / immediate_liquidity_need
            if immediate_liquidity_need > 0
            else 1.0
        )
        policy = self.rules.get("decision_policy") if isinstance(self.rules.get("decision_policy"), dict) else {}
        reject_below = _number(policy.get("liquidity_coverage_reject_below"), 0.80)
        review_below = _number(policy.get("liquidity_coverage_review_below"), 1.00)

        data_quality = self._validate_data_quality(contract, evidence)
        missing_fields = data_quality["blocking"]
        missing = [f"{item['label']} tại {item['source']}" for item in missing_fields]

        cashflow_status = "BLOCKED_BY_DATA" if missing else "READY"
        cashflow_block_reason = (
            f"Không đủ dữ liệu liên kết để xác nhận dòng tiền cho {contract_id}."
            if missing
            else "Dòng tiền hợp đồng từ order/invoice và forecast doanh nghiệp tham chiếu đã sẵn sàng."
        )
        credit_mapping = [
            {
                "credit_case_id": item["credit_case_id"],
                "request_type": item["request_type"],
                "category": item["category"],
                "requested_amount": item["requested_amount"],
                "eligibility_score": item["eligibility_score"],
                "approval_status": item["approval_status"],
                "mapping_scope": item["mapping_scope"],
                "mapping_source": item["mapping_source"],
                "bank_product_ids": item["bank_product_ids"],
            }
            for item in credit_mappings
        ]

        workflow.append(
            _trace_event(
                trace_id,
                "Data & Finance Agent",
                "observe",
                "04_CONTRACTS + 06_ORDERS + 07_INVOICES + 08_BANK_TXN + 09_CASHFLOW",
                "missing_data" if missing else "ok",
                f"Đối soát {len(orders)} đơn hàng; funding gap đỉnh {_format_billion(peak_funding_gap)}.",
                "API-007",
            )
        )

        return {
            "contract_value": contract_value,
            "order_revenue": revenue,
            "order_coverage_ratio": order_coverage_ratio,
            "estimated_cost": base_cost,
            "linked_order_count": len(orders),
            "linked_invoice_count": len(contract_invoices),
            "core_evidence_mode": signals["core_evidence_mode"],
            "structured_evidence_used": signals["structured_evidence"],
            "performance_bond_required_signal": signals["bond_required"],
            "deployment_scope_provinces": signals["deployment_scope_provinces"],
            "collection_timing_signal": signals["collection_timing_signal"],
            "scenario_revenue": scenario_revenue,
            "scenario_cost": scenario_cost,
            "gross_profit": scenario_revenue - scenario_cost,
            "gross_margin": gross_margin,
            "target_gross_margin": target_margin,
            "margin_gap_pp": margin_comparison["gap_pp"],
            "margin_relation": margin_comparison["relation"],
            "margin_comparison_text": margin_comparison["text"],
            "peak_funding_gap": peak_funding_gap,
            "peak_gap_month": peak_gap_row.get("month"),
            "working_capital_request": working_capital_request,
            "potential_funding_capacity": potential_funding_capacity,
            "funding_coverage_ratio": funding_coverage_ratio,
            "liquidity_coverage_reject_below": reject_below,
            "liquidity_coverage_review_below": review_below,
            "credit_case_ids": [item["credit_case_id"] for item in credit_mapping],
            "credit_mapping": credit_mapping,
            "factoring_capacity": factoring_capacity,
            "performance_bond_request": performance_bond_request,
            "performance_bond_credit_case_id": (
                performance_bond_mapping["credit_case_id"] if performance_bond_mapping else None
            ),
            "performance_bond_eligibility": (
                performance_bond_mapping["eligibility_score"] if performance_bond_mapping else 0.0
            ),
            "performance_bond_mapping_source": (
                performance_bond_mapping["mapping_source"] if performance_bond_mapping else None
            ),
            "guarantee_collateral_ratio": guarantee_collateral_ratio,
            "guarantee_collateral_encumbrance": guarantee_collateral,
            "guarantee_fee_rate": guarantee_fee_rate,
            "guarantee_duration_days": guarantee_duration_days,
            "guarantee_fee_estimate": guarantee_fee,
            "guarantee_cash_impact": guarantee_cash_impact,
            "immediate_liquidity_need": immediate_liquidity_need,
            "liquidity_headroom": liquidity_headroom,
            "financial_status": (
                "NEED_MORE_DATA"
                if missing
                else "LIQUIDITY_REJECT"
                if funding_coverage_ratio < reject_below
                else "LIQUIDITY_NEED_REVIEW"
                if funding_coverage_ratio < review_below
                else "VIABLE_WITH_CONTROLS"
                if gross_margin >= target_margin
                else "CONDITIONAL_MARGIN_REMEDIATION"
            ),
            "cashflow": cashflow,
            "cashflow_scope": "ENTERPRISE_CONTEXT",
            "contract_cashflow": contract_cashflow,
            "contract_cashflow_method": "Selected contract only: 06_ORDERS estimated_cost at order month; all linked 07_INVOICES milestones at paid/due month; any unbilled order remainder is forecast once at order due month; scenario delay applies to the largest eligible forecast invoice.",
            "cashflow_status": cashflow_status,
            "cashflow_block_reason": cashflow_block_reason,
            "missing_data": missing,
            "missing_fields": missing_fields,
            "data_quality": data_quality,
            "calculation_notes": [
                "Biên gộp = (tổng doanh thu đơn hàng - chi phí ước tính) / tổng doanh thu đơn hàng.",
                "Funding gap hợp đồng = max(0, âm dòng tiền tích lũy) từ order/invoice liên kết đúng contract_id.",
                "09_CASHFLOW được giữ làm bối cảnh doanh nghiệp; không sao chép thành nhu cầu vốn riêng cho mọi hợp đồng.",
                f"Contract Cashflow của {contract_id} chỉ dùng order/invoice liên kết; không dùng order/invoice của hợp đồng khác.",
                "Nhu cầu thanh khoản tức thời = funding gap đỉnh + tiền ký quỹ bảo lãnh + phí bảo lãnh ước tính.",
                "Funding coverage dùng phương án có capacity lớn nhất; không cộng dồn các phương án đối tác thay thế nhau.",
                f"Kịch bản chi phí phân bổ theo tháng đến hạn của {len(orders)} order thuộc {contract_id}; thanh toán chậm dùng invoice liên kết lớn nhất.",
            ],
            "limitations": [
                f"Order coverage hiện tại là {order_coverage_ratio:.1%}; phần hợp đồng chưa map vào order chưa có cost schedule cấp đơn hàng.",
                "Tiền ký quỹ bảo lãnh được xem như cash encumbrance theo góc nhìn stress thận trọng; ngân hàng có thể chấp nhận tài sản bảo đảm khác.",
                "Partner precheck là dữ liệu mô phỏng trong TeamPack, không phải phê duyệt tín dụng.",
            ],
            "sources": ["03_CUSTOMERS", "04_CONTRACTS", "06_ORDERS", "07_INVOICES", "09_CASHFLOW", "10_CREDIT_PROFILE", "11_BANK_PRODUCTS"],
        }

    def _transaction_reconciliation(
        self,
        contract: dict[str, Any],
        evidence: dict[str, bool],
    ) -> dict[str, Any]:
        """Reconcile incoming bank transactions without inferring ownership.

        A transaction reaches the selected contract only through the complete
        08_BANK_TXN -> 07_INVOICES -> 06_ORDERS -> 04_CONTRACTS lineage.  The
        matching rules are deliberately narrow and deterministic:

        * L1 accepts one exact invoice identifier in the bank reference text.
        * L2 accepts one unique invoice with the same amount, customer and paid
          date when no invoice identifier was supplied.

        Anything else remains visible as an excluded/unmatched transaction.  In
        particular, a positive amount alone is never treated as contract cash.
        """
        selected_contract_id = _safe_text(contract.get("contract_id"))
        route_layers = ["08_BANK_TXN", "07_INVOICES", "06_ORDERS", "04_CONTRACTS"]
        orders_by_id = {
            _safe_text(row.get("order_id")): row
            for row in self.pack.rows("06_ORDERS")
            if _safe_text(row.get("order_id"))
        }
        contracts_by_id = {
            _safe_text(row.get("contract_id")): row
            for row in self.pack.rows("04_CONTRACTS")
            if _safe_text(row.get("contract_id"))
        }
        invoices_by_id = {
            _safe_text(row.get("invoice_id")): row
            for row in self.pack.rows("07_INVOICES")
            if _safe_text(row.get("invoice_id"))
        }

        def lineage_for(invoice: dict[str, Any]) -> tuple[str | None, str | None]:
            order_id = _safe_text(invoice.get("order_id"))
            order = orders_by_id.get(order_id)
            if not order:
                return order_id or None, None
            contract_id = _safe_text(order.get("contract_id"))
            if contract_id not in contracts_by_id:
                return order_id or None, None
            return order_id or None, contract_id or None

        def date_text(value: Any) -> str | None:
            parsed = _as_date(value)
            return parsed.isoformat() if parsed else (_safe_text(value) or None)

        def incoming(row: dict[str, Any]) -> bool:
            return _safe_text(row.get("direction")).lower() == "credit" and _number(row.get("amount")) > 0

        def explicit_invoice_refs(row: dict[str, Any]) -> list[str]:
            fields = ("invoice_id", "invoice_ref", "payment_reference", "reference", "description")
            references: set[str] = set()
            for field in fields:
                text = _safe_text(row.get(field)).upper()
                if not text:
                    continue
                references.update(
                    match.replace("_", "-")
                    for match in re.findall(r"(?<![A-Z0-9])INV[-_][A-Z0-9]+(?![A-Z0-9])", text)
                )
            return sorted(references)

        invoice_index = {key.upper().replace("_", "-"): value for key, value in invoices_by_id.items()}
        incoming_rows = sorted(
            (row for row in self.pack.rows("08_BANK_TXN") if incoming(row)),
            key=lambda row: (date_text(row.get("txn_date")) or "", _safe_text(row.get("txn_id"))),
        )
        records: list[dict[str, Any]] = []

        for txn in incoming_rows:
            txn_id = _safe_text(txn.get("txn_id"))
            txn_amount = _number(txn.get("amount"))
            txn_customer = _safe_text(txn.get("counterparty_id"))
            txn_date = _as_date(txn.get("txn_date"))
            explicit_refs = explicit_invoice_refs(txn)
            matched_invoice: dict[str, Any] | None = None
            match_level = "NONE"
            match_rule = "NO_DETERMINISTIC_MATCH"
            reason = (
                "Không có invoice_id rõ ràng và không có bộ amount + counterparty_id + paid_date "
                "khớp chính xác, duy nhất; giao dịch bị loại khỏi hợp đồng đang chọn."
            )

            if len(explicit_refs) == 1 and explicit_refs[0] in invoice_index:
                matched_invoice = invoice_index[explicit_refs[0]]
                match_level = "L1_EXPLICIT_INVOICE_ID"
                match_rule = "EXACT_INVOICE_ID_IN_BANK_REFERENCE"
                reason = "Invoice ID xuất hiện chính xác trong nội dung giao dịch ngân hàng."
            elif explicit_refs:
                match_rule = "INVALID_OR_AMBIGUOUS_EXPLICIT_REFERENCE"
                reason = (
                    "Tham chiếu invoice trong giao dịch không tồn tại hoặc không duy nhất; "
                    "hệ thống không chuyển sang suy đoán bằng dữ kiện khác."
                )
            else:
                exact_candidates: list[dict[str, Any]] = []
                for invoice in invoices_by_id.values():
                    order_id, lineage_contract_id = lineage_for(invoice)
                    invoice_paid_date = _as_date(invoice.get("paid_date"))
                    amount_matches = math.isclose(
                        txn_amount,
                        _number(invoice.get("invoice_amount")),
                        rel_tol=0.0,
                        abs_tol=0.01,
                    )
                    customer_matches = bool(txn_customer) and txn_customer == _safe_text(invoice.get("customer_id"))
                    paid_date_matches = bool(txn_date and invoice_paid_date and txn_date == invoice_paid_date)
                    if order_id and lineage_contract_id and amount_matches and customer_matches and paid_date_matches:
                        exact_candidates.append(invoice)
                if len(exact_candidates) == 1:
                    matched_invoice = exact_candidates[0]
                    match_level = "L2_EXACT_UNIQUE_FACTS"
                    match_rule = "UNIQUE_EXACT_AMOUNT_COUNTERPARTY_PAID_DATE"
                    reason = "Amount, counterparty_id và paid_date khớp chính xác với đúng một hóa đơn."
                elif len(exact_candidates) > 1:
                    match_rule = "AMBIGUOUS_EXACT_FACTS"
                    reason = (
                        "Có nhiều hóa đơn cùng khớp chính xác amount + counterparty_id + paid_date; "
                        "hệ thống giữ giao dịch ở trạng thái chưa đối soát."
                    )

            invoice_id: str | None = None
            order_id: str | None = None
            lineage_contract_id: str | None = None
            amount_matches: bool | None = None
            counterparty_matches: bool | None = None
            paid_date_matches: bool | None = None
            lineage: list[dict[str, Any]] = [
                {"layer": 1, "sheet": "08_BANK_TXN", "record_id": txn_id}
            ]
            route = f"08_BANK_TXN[{txn_id}]"
            if matched_invoice is not None:
                invoice_id = _safe_text(matched_invoice.get("invoice_id")) or None
                order_id, lineage_contract_id = lineage_for(matched_invoice)
                amount_matches = math.isclose(
                    txn_amount,
                    _number(matched_invoice.get("invoice_amount")),
                    rel_tol=0.0,
                    abs_tol=0.01,
                )
                counterparty_matches = bool(txn_customer) and txn_customer == _safe_text(matched_invoice.get("customer_id"))
                invoice_paid_date = _as_date(matched_invoice.get("paid_date"))
                paid_date_matches = bool(txn_date and invoice_paid_date and txn_date == invoice_paid_date)
                lineage.append({"layer": 2, "sheet": "07_INVOICES", "record_id": invoice_id})
                route += f" -> 07_INVOICES[{invoice_id}]"
                if order_id:
                    lineage.append({"layer": 3, "sheet": "06_ORDERS", "record_id": order_id})
                    route += f" -> 06_ORDERS[{order_id}]"
                if lineage_contract_id:
                    lineage.append({"layer": 4, "sheet": "04_CONTRACTS", "record_id": lineage_contract_id})
                    route += f" -> 04_CONTRACTS[{lineage_contract_id}]"

            complete_lineage = bool(invoice_id and order_id and lineage_contract_id)
            in_selected_contract = complete_lineage and lineage_contract_id == selected_contract_id
            if matched_invoice is None:
                match_status = "UNMATCHED_INCOMING"
            elif not complete_lineage:
                match_status = "BROKEN_LINEAGE"
                reason = "Có invoice match nhưng chuỗi invoice -> order -> contract không đầy đủ; không được phân bổ."
            elif in_selected_contract:
                match_status = "MATCHED_SELECTED_CONTRACT"
            else:
                match_status = "MATCHED_OTHER_CONTRACT"
                reason = f"Giao dịch được đối soát với {lineage_contract_id}, không phải {selected_contract_id}."

            records.append(
                {
                    "txn_id": txn_id,
                    "txn_date": date_text(txn.get("txn_date")),
                    "direction": _safe_text(txn.get("direction")),
                    "amount": txn_amount,
                    "counterparty_token": (
                        f"CP-{hashlib.sha256(txn_customer.encode('utf-8')).hexdigest()[:8].upper()}"
                        if txn_customer
                        else None
                    ),
                    "match_status": match_status,
                    "match_level": match_level,
                    "match_rule": match_rule,
                    "invoice_id": invoice_id,
                    "order_id": order_id,
                    "contract_id": lineage_contract_id,
                    "in_selected_contract": in_selected_contract,
                    "included_in_selected_contract": in_selected_contract,
                    "reason": reason,
                    "fact_checks": {
                        "amount_matches_invoice": amount_matches,
                        "counterparty_matches_customer": counterparty_matches,
                        "txn_date_matches_paid_date": paid_date_matches,
                    },
                    "route": route,
                    "lineage": lineage,
                }
            )

        # Multiple incoming transactions claiming the same invoice are not
        # silently double-counted. They are retained for human reconciliation.
        records_by_invoice: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            if record["invoice_id"] and record["match_status"].startswith("MATCHED_"):
                records_by_invoice.setdefault(record["invoice_id"], []).append(record)
        for invoice_id, invoice_records in records_by_invoice.items():
            if len(invoice_records) <= 1:
                continue
            for record in invoice_records:
                record["match_status"] = "AMBIGUOUS_MULTIPLE_TXNS"
                record["in_selected_contract"] = False
                record["included_in_selected_contract"] = False
                record["reason"] = (
                    f"Nhiều giao dịch cùng tham chiếu {invoice_id}; không giao dịch nào được tự động cộng vào hợp đồng."
                )

        # Scope is an explicit backend fact.  The browser must not infer a
        # transaction's ownership from its ID or presentation order.
        for record in records:
            if record["included_in_selected_contract"]:
                record["scope"] = "CASE"
                record["scopes"] = ["CASE"]
            elif record["match_status"] in {
                "UNMATCHED_INCOMING",
                "BROKEN_LINEAGE",
                "AMBIGUOUS_MULTIPLE_TXNS",
            }:
                record["scope"] = "ENTERPRISE"
                record["scopes"] = ["ENTERPRISE", "REVIEW"]
            else:
                # A deterministic match owned by another contract is visible
                # as enterprise context, but it is not a data-quality warning
                # for the selected contract.
                record["scope"] = "ENTERPRISE"
                record["scopes"] = ["ENTERPRISE"]

        selected_orders = {
            order_id
            for order_id, row in orders_by_id.items()
            if _safe_text(row.get("contract_id")) == selected_contract_id
        }
        selected_invoices = [
            row
            for row in invoices_by_id.values()
            if _safe_text(row.get("order_id")) in selected_orders
        ]
        selected_paid_invoices = [
            row for row in selected_invoices if _safe_text(row.get("status")).lower() == "paid"
        ]
        reconciled_selected_invoice_ids = {
            record["invoice_id"]
            for record in records
            if record["included_in_selected_contract"] and record["invoice_id"]
        }
        reverse_paid_warnings: list[dict[str, Any]] = []
        for invoice in selected_paid_invoices:
            invoice_id = _safe_text(invoice.get("invoice_id"))
            if invoice_id in reconciled_selected_invoice_ids:
                continue
            order_id = _safe_text(invoice.get("order_id"))
            reverse_paid_warnings.append(
                {
                    "scope": "CASE",
                    "rule_id": "RR-REC-001",
                    "severity": "Medium",
                    "title": "Hóa đơn Paid chưa có giao dịch Credit đối soát",
                    "detail": (
                        f"{invoice_id} đang ở trạng thái Paid nhưng không có giao dịch Credit nào đi qua đầy đủ "
                        f"08_BANK_TXN -> 07_INVOICES -> 06_ORDERS -> 04_CONTRACTS tới {selected_contract_id}."
                    ),
                    "required_action": "Kiểm tra sao kê/tham chiếu thanh toán; không tự suy đoán giao dịch thay thế.",
                    "source": (
                        f"07_INVOICES[{invoice_id}] -> 06_ORDERS[{order_id}] -> "
                        f"04_CONTRACTS[{selected_contract_id}] + 08_BANK_TXN"
                    ),
                    "invoice_id": invoice_id,
                    "order_id": order_id,
                    "contract_id": selected_contract_id,
                }
            )

        anomaly_threshold = _number(self.rules.get("transaction_anomaly_threshold"), 85)
        anomaly_reviewed = bool(evidence.get("suspicious_txn_reviewed"))
        records_by_txn_id = {record["txn_id"]: record for record in records if record["txn_id"]}
        enterprise_anomalies: list[dict[str, Any]] = []
        for row in self.pack.rows("08_BANK_TXN"):
            if _number(row.get("transaction_risk_score")) < anomaly_threshold:
                continue

            txn_id = _safe_text(row.get("txn_id"))
            reconciled = records_by_txn_id.get(txn_id)
            in_selected_contract = bool(
                reconciled and reconciled.get("included_in_selected_contract")
            )
            anomaly_scopes = (
                ["CASE", "ENTERPRISE", "REVIEW"]
                if in_selected_contract
                else ["ENTERPRISE", "REVIEW"]
            )

            if reconciled is not None:
                # Preserve deterministic CASE lineage while layering the
                # enterprise risk control on the same transaction.  Neither
                # the inclusion flag nor selected-contract cash is changed.
                reconciled["scope"] = "BOTH" if in_selected_contract else "ENTERPRISE"
                reconciled["scopes"] = anomaly_scopes
                reconciled["is_enterprise_anomaly"] = True
                reconciled["requires_review"] = True
                reconciled["review_status"] = (
                    "REVIEWED_BY_EVIDENCE" if anomaly_reviewed else "PENDING_FOUNDER_REVIEW"
                )

            enterprise_anomalies.append(
                {
                    "txn_id": txn_id,
                    "txn_date": date_text(row.get("txn_date")),
                    "direction": _safe_text(row.get("direction")),
                    "amount": _number(row.get("amount")),
                    "txn_status": _safe_text(row.get("txn_status")),
                    "transaction_risk_score": _number(row.get("transaction_risk_score")),
                    "scope": "BOTH" if in_selected_contract else "ENTERPRISE",
                    "scopes": anomaly_scopes,
                    "match_status": (
                        reconciled.get("match_status")
                        if reconciled is not None
                        else "ENTERPRISE_ANOMALY_UNMATCHED"
                    ),
                    "match_level": (
                        reconciled.get("match_level") if reconciled is not None else "NONE"
                    ),
                    "invoice_id": reconciled.get("invoice_id") if reconciled is not None else None,
                    "order_id": reconciled.get("order_id") if reconciled is not None else None,
                    "contract_id": reconciled.get("contract_id") if reconciled is not None else None,
                    "in_selected_contract": in_selected_contract,
                    "included_in_selected_contract": in_selected_contract,
                    "review_status": "REVIEWED_BY_EVIDENCE" if anomaly_reviewed else "PENDING_FOUNDER_REVIEW",
                    "reason": (
                        "Giao dịch có lineage chính xác tới hợp đồng đang chọn; hệ thống giữ liên kết CASE "
                        "và đồng thời mở kiểm soát rủi ro ENTERPRISE."
                        if in_selected_contract
                        else "Điểm rủi ro đạt ngưỡng cấp doanh nghiệp; không gán cho hợp đồng nếu thiếu lineage hóa đơn."
                    ),
                    "source": f"08_BANK_TXN[{txn_id}] + 13_RISK_RULES[RR-001]",
                }
            )

        selected_records = [record for record in records if record["included_in_selected_contract"]]
        unmatched_records = [record for record in records if record["match_status"] == "UNMATCHED_INCOMING"]
        excluded_records = [record for record in records if not record["included_in_selected_contract"]]
        matched_records = [record for record in records if record["match_status"].startswith("MATCHED_")]
        reconciled_paid_count = sum(
            _safe_text(invoice.get("invoice_id")) in reconciled_selected_invoice_ids
            for invoice in selected_paid_invoices
        )
        if reverse_paid_warnings:
            selected_contract_status = "REVIEW_REQUIRED"
        elif selected_paid_invoices:
            selected_contract_status = "RECONCILED"
        else:
            selected_contract_status = "NO_PAID_INVOICES"
        enterprise_anomaly_status = (
            "CLEAR"
            if not enterprise_anomalies
            else "REVIEWED_BY_EVIDENCE"
            if anomaly_reviewed
            else "PENDING_FOUNDER_REVIEW"
        )
        overall_status = (
            "REVIEW_REQUIRED"
            if reverse_paid_warnings or enterprise_anomaly_status == "PENDING_FOUNDER_REVIEW"
            else selected_contract_status
        )

        return {
            "status": overall_status,
            "selected_contract_status": selected_contract_status,
            "enterprise_anomaly_status": enterprise_anomaly_status,
            "scope": {
                "type": "SELECTED_CONTRACT",
                "contract_id": selected_contract_id,
                "included_rule": "Chỉ giao dịch Credit có lineage đầy đủ tới hợp đồng đang chọn.",
                "excluded_rule": "Giao dịch unmatched hoặc thuộc hợp đồng khác không được cộng vào case; nhãn anomaly không tự tạo quyền sở hữu hay cộng tiền lần hai.",
            },
            "route": route_layers,
            "policy": {
                "matching_order": ["L1_EXPLICIT_INVOICE_ID", "L2_EXACT_UNIQUE_FACTS"],
                "l1": "Một invoice_id chính xác trong bank reference.",
                "l2": "Amount + counterparty_id + paid_date khớp chính xác với duy nhất một invoice.",
                "no_guessing": True,
                "incoming_only": True,
            },
            "kpis": {
                "incoming_txn_count": len(records),
                "matched_incoming_count": len(matched_records),
                "unmatched_incoming_count": len(unmatched_records),
                "unmatched_incoming_amount": sum(record["amount"] for record in unmatched_records),
                "selected_contract_invoice_count": len(selected_invoices),
                "selected_contract_paid_invoice_count": len(selected_paid_invoices),
                "selected_contract_reconciled_paid_invoice_count": reconciled_paid_count,
                "selected_contract_matched_txn_count": len(selected_records),
                "selected_contract_matched_amount": sum(record["amount"] for record in selected_records),
                "excluded_incoming_count": len(excluded_records),
                "excluded_incoming_amount": sum(record["amount"] for record in excluded_records),
                "reverse_paid_warning_count": len(reverse_paid_warnings),
                "enterprise_anomaly_count": len(enterprise_anomalies),
                "enterprise_anomaly_amount": abs(sum(item["amount"] for item in enterprise_anomalies)),
            },
            "records": records,
            "reverse_paid_warnings": reverse_paid_warnings,
            "enterprise_anomalies": enterprise_anomalies,
            "evidence": {"suspicious_txn_reviewed": anomaly_reviewed},
            "sources": route_layers + ["13_RISK_RULES", "14_ALERTS"],
        }

    def _risk_agent(
        self,
        contract: dict[str, Any],
        finance: dict[str, Any],
        scenario: dict[str, float],
        evidence: dict[str, bool],
        trace_id: str,
        workflow: list[dict[str, Any]],
    ) -> dict[str, Any]:
        alerts: list[dict[str, Any]] = []

        transaction_reconciliation = self._transaction_reconciliation(contract, evidence)
        alerts.extend(transaction_reconciliation["reverse_paid_warnings"])
        suspicious = transaction_reconciliation["enterprise_anomalies"]
        if suspicious and not evidence["suspicious_txn_reviewed"]:
            alerts.append(
                {
                    "scope": "ENTERPRISE",
                    "rule_id": "RR-001",
                    "severity": "Critical",
                    "title": "Giao dịch bất thường chưa được xác nhận",
                    "detail": f"{len(suspicious)} giao dịch, tổng giá trị {abs(sum(_number(row.get('amount')) for row in suspicious)):,.0f} VND.",
                    "required_action": "Tạm giữ/xác minh theo API-006; Founder phê duyệt hành động không thể đảo ngược.",
                    "source": "08_BANK_TXN + 14_ALERTS",
                }
            )
        if finance["peak_funding_gap"] > 0:
            alerts.append(
                {
                    "scope": "CASE",
                    "rule_id": "RR-002",
                    "severity": "High",
                    "title": "Vi phạm ngưỡng dự trữ tiền mặt",
                    "detail": f"Funding gap đỉnh {_format_billion(finance['peak_funding_gap'])} vào {finance['peak_gap_month']}.",
                    "required_action": "Bảo đảm hạn mức vốn trước khi kích hoạt triển khai.",
                    "source": "06_ORDERS + 07_INVOICES",
                }
            )
        if not finance["missing_data"] and finance["funding_coverage_ratio"] < 1.0:
            coverage = finance["funding_coverage_ratio"]
            reject_below = finance["liquidity_coverage_reject_below"]
            alerts.append(
                {
                    "scope": "CASE",
                    "rule_id": "RR-LIQ-001",
                    "severity": "Critical" if coverage < reject_below else "High",
                    "title": "Funding coverage chưa đạt ngưỡng",
                    "detail": (
                        f"Nguồn vốn tiềm năng {_format_billion(finance['potential_funding_capacity'])} "
                        f"chỉ bao phủ {coverage:.1%} nhu cầu tức thời "
                        f"{_format_billion(finance['immediate_liquidity_need'])}."
                    ),
                    "required_action": (
                        "REJECT dưới 80%; NEED REVIEW từ 80% đến dưới 100%; "
                        "chỉ tiếp tục đánh giá khi coverage đạt ít nhất 100%."
                    ),
                    "source": "06_ORDERS + 07_INVOICES + 10_CREDIT_PROFILE + 11_BANK_PRODUCTS",
                }
            )
        if finance["gross_margin"] < finance["target_gross_margin"]:
            alerts.append(
                {
                    "scope": "CASE",
                    "rule_id": "RR-003",
                    "severity": "Medium",
                    "title": "Biên gộp thấp hơn mục tiêu",
                    "detail": f"Biên sau kịch bản {finance['gross_margin']:.1%}, mục tiêu {finance['target_gross_margin']:.1%}.",
                    "required_action": "Khóa phạm vi, giá và cơ chế chuyển phần tăng chi phí.",
                    "source": "04_CONTRACTS + 06_ORDERS",
                }
            )
        scope_provinces = finance.get("deployment_scope_provinces")
        if isinstance(scope_provinces, int) and not isinstance(scope_provinces, bool) and scope_provinces >= 20:
            alerts.append(
                {
                    "scope": "CASE",
                    "rule_id": "AL-003",
                    "severity": "High",
                    "title": "Rủi ro năng lực triển khai đa địa bàn",
                    "detail": f"Phạm vi rollout {scope_provinces} tỉnh có thể vượt năng lực nhà thầu hiện tại.",
                    "required_action": "Chia rollout theo cổng nghiệm thu và xác nhận capacity plan theo giai đoạn.",
                    "source": (
                        "OpenAI Structured Evidence đã kiểm định + 14_ALERTS[AL-003]"
                        if finance.get("core_evidence_mode") == "OPENAI_STRUCTURED_EVIDENCE_VALIDATED"
                        else "04_CONTRACTS + 14_ALERTS[AL-003] (deterministic fallback)"
                    ),
                }
            )
        bank_confidence = _number(finance.get("performance_bond_eligibility"))
        bank_threshold = _number(self.rules.get("bank_confidence_threshold"), 0.65)
        if bank_confidence and bank_confidence < bank_threshold:
            alerts.append(
                {
                    "scope": "CASE",
                    "rule_id": "RR-006",
                    "severity": "Medium",
                    "title": "Độ tin cậy precheck bảo lãnh dưới ngưỡng",
                    "detail": f"eligibility_score={bank_confidence:.2f}, thấp hơn ngưỡng {bank_threshold:.2f}.",
                    "required_action": "Bổ sung hợp đồng đã ký và bằng chứng cash buffer sau tài trợ.",
                    "source": (
                        f"{finance.get('performance_bond_mapping_source') or '10_CREDIT_PROFILE'} "
                        "+ 13_RISK_RULES[RR-006]"
                    ),
                }
            )
        founder_threshold = _number(self.rules.get("founder_approval_threshold_vnd"), 300_000_000)
        if finance["working_capital_request"] > founder_threshold or finance["performance_bond_request"] > founder_threshold:
            alerts.append(
                {
                    "scope": "CASE",
                    "rule_id": "RR-005",
                    "severity": "High",
                    "title": "Quyết định tài chính vượt 300 triệu VND",
                    "detail": "Hạn mức vốn và bảo lãnh đều vượt ngưỡng quản trị của OPC.",
                    "required_action": "Bắt buộc Founder Approval Gate trước khi gửi hồ sơ đối tác.",
                    "source": "02_OPC_PROFILE + 10_CREDIT_PROFILE",
                }
            )
        if scenario["deadline_change_days"] > 7:
            penalty_rate = _number(self.pack.profile().get("late_delivery_penalty_rate"), 0.015)
            penalty = _number(contract.get("contract_value")) * penalty_rate
            alerts.append(
                {
                    "scope": "CASE",
                    "rule_id": "RR-007",
                    "severity": "High",
                    "title": "Nguy cơ phạt chậm tiến độ",
                    "detail": f"Deadline tăng trễ {scenario['deadline_change_days']:.0f} ngày; exposure minh họa {penalty:,.0f} VND.",
                    "required_action": "Tái lập kế hoạch năng lực và đàm phán mốc nghiệm thu.",
                    "source": "13_RISK_RULES + 02_OPC_PROFILE",
                }
            )
        for item in finance["missing_data"]:
            alerts.append(
                {
                    "scope": "CASE",
                    "rule_id": "API-H-001",
                    "severity": "High",
                    "title": "Thiếu dữ liệu bắt buộc",
                    "detail": item,
                    "required_action": "Dừng khuyến nghị cuối và yêu cầu bổ sung đúng trường dữ liệu.",
                    "source": "22_API_HANDLING_RULES",
                }
            )

        case_risk_level = max(
            (item["severity"] for item in alerts if item.get("scope") == "CASE"),
            key=lambda severity: SEVERITY_ORDER[severity],
            default="Low",
        )
        enterprise_risk_level = max(
            (item["severity"] for item in alerts if item.get("scope") == "ENTERPRISE"),
            key=lambda severity: SEVERITY_ORDER[severity],
            default="Low",
        )
        overall_risk_level = max(
            (case_risk_level, enterprise_risk_level),
            key=lambda severity: SEVERITY_ORDER[severity],
        )
        workflow.append(
            _trace_event(
                trace_id,
                "Risk & Compliance Agent",
                "reason",
                "08_BANK_TXN + 13_RISK_RULES + 14_ALERTS + 20_DATA_CLASS",
                "needs_approval" if overall_risk_level in {"Critical", "High"} else "ok",
                (
                    f"Đối soát {transaction_reconciliation['kpis']['incoming_txn_count']} giao dịch Credit qua "
                    f"08->07->06->04; kích hoạt {len(alerts)} cảnh báo; "
                    f"case={case_risk_level}, enterprise={enterprise_risk_level}."
                ),
                "API-006" if suspicious else None,
            )
        )
        return {
            "risk_level": case_risk_level,
            "case_risk_level": case_risk_level,
            "enterprise_risk_level": enterprise_risk_level,
            "overall_risk_level": overall_risk_level,
            "risk_score": max((90 if a["severity"] == "Critical" else 76 if a["severity"] == "High" else 55 for a in alerts), default=0),
            "alerts": alerts,
            "critical_count": sum(item["severity"] == "Critical" for item in alerts),
            "high_count": sum(item["severity"] == "High" for item in alerts),
            "case_alert_count": sum(item.get("scope") == "CASE" for item in alerts),
            "enterprise_alert_count": sum(item.get("scope") == "ENTERPRISE" for item in alerts),
            "human_review_required": any(item["severity"] in {"Critical", "High"} for item in alerts),
            "transaction_reconciliation": transaction_reconciliation,
            "sources": ["04_CONTRACTS", "06_ORDERS", "07_INVOICES", "08_BANK_TXN", "13_RISK_RULES", "14_ALERTS", "20_DATA_CLASS", "22_API_HANDLING_RULES"],
        }

    def _partner_agent(
        self,
        contract: dict[str, Any],
        finance: dict[str, Any],
        risk: dict[str, Any],
        scenario: dict[str, float],
        evidence: dict[str, bool],
        trace_id: str,
        workflow: list[dict[str, Any]],
    ) -> dict[str, Any]:
        mappings = self._credit_case_mappings(contract)
        liquidity_mappings = [
            item for item in mappings
            if item["category"] != "PERFORMANCE_BOND" and item["requested_amount"] > 0
        ]
        bond_mappings = [item for item in mappings if item["category"] == "PERFORMANCE_BOND"]
        need = max(_number(finance.get("immediate_liquidity_need")), 1.0)
        tenor_years = _number(self.rules.get("working_capital_tenor_years"), 0.5)
        bank_threshold = _number(self.rules.get("bank_confidence_threshold"), 0.65)
        options: list[dict[str, Any]] = []

        def logo_key(provider: str) -> str:
            value = provider.lower().replace("-", "")
            if "vietin" in value:
                return "vietinbank"
            if "coop" in value:
                return "coopbank"
            return "partnerx"

        for mapping in liquidity_mappings:
            for product in mapping["products"]:
                amount = mapping["requested_amount"]
                provider = _safe_text(product.get("bank")) or "Partner"
                rate = _number(product.get("annual_rate_or_fee"))
                fee_rate = _number(product.get("processing_fee_rate"))
                estimated_cost = amount * rate * tenor_years + amount * fee_rate
                coverage = amount / need
                eligibility = mapping["eligibility_score"]
                minimum_amount = _number(product.get("minimum_amount"))
                status = (
                    "INELIGIBLE"
                    if amount < minimum_amount
                    else "CONDITIONAL"
                    if eligibility < bank_threshold or mapping["mapping_scope"] != "EXACT_CONTRACT"
                    else "ELIGIBLE"
                )
                provider_bond = next(
                    (
                        bond
                        for bond in bond_mappings
                        if any(_safe_text(item.get("bank")) == provider for item in bond["products"])
                    ),
                    None,
                )
                guarantee_amount = provider_bond["requested_amount"] if provider_bond else 0.0
                if provider_bond:
                    estimated_cost += finance["guarantee_fee_estimate"]
                    eligibility = min(eligibility, provider_bond["eligibility_score"])
                    if eligibility < bank_threshold:
                        status = "CONDITIONAL"
                product_id = _safe_text(product.get("bank_product_id"))
                fit_score = round(
                    35 * min(1.0, coverage)
                    + 25 * min(1.0, eligibility)
                    + 20 * (1 - min(1.0, estimated_cost / max(amount, 1.0)))
                    + 20 * (1.0 if status == "ELIGIBLE" else 0.75 if status == "CONDITIONAL" else 0.0),
                    1,
                )
                options.append(
                    {
                        "option_id": f"{mapping['credit_case_id']}-{product_id}",
                        "provider": provider,
                        "logo_key": logo_key(provider),
                        "presentation_label": "PHƯƠNG ÁN MÔ PHỎNG",
                        "product": _safe_text(product.get("product_name")) or mapping["request_type"],
                        "liquidity_amount": amount,
                        "guarantee_amount": guarantee_amount,
                        "coverage_ratio": coverage,
                        "eligibility_score": eligibility,
                        "estimated_cost": estimated_cost,
                        "cash_collateral": (
                            amount * _number(product.get("collateral_ratio"))
                            + (finance["guarantee_collateral_encumbrance"] if provider_bond else 0.0)
                        ),
                        "fit_score": fit_score,
                        "status": status,
                        "mapping_scope": mapping["mapping_scope"],
                        "hard_gate_notes": [
                            "Founder phê duyệt trước mọi partner submission.",
                            (
                                "Hạn mức cấp doanh nghiệp; Founder phải xác nhận phần còn khả dụng cho hợp đồng này."
                                if mapping["mapping_scope"] == "ENTERPRISE_SHARED"
                                else f"Credit case liên kết trực tiếp/purpose-match với {contract.get('contract_id')}."
                            ),
                        ],
                        "source": (
                            f"{mapping['mapping_source']} + "
                            f"11_BANK_PRODUCTS[{product_id}]"
                        ),
                    }
                )

        factoring_products = [
            row for row in self.pack.rows("11_BANK_PRODUCTS")
            if self._product_category(row) == "FACTORING"
        ]
        signals = self._contract_signals(contract)
        approved_invoice_amount = sum(
            _number(row.get("invoice_amount")) for row in signals["eligible_invoices"]
        )
        for factoring in factoring_products:
            product_id = _safe_text(factoring.get("bank_product_id"))
            factoring_amount = approved_invoice_amount
            factoring_coverage = factoring_amount / need if factoring_amount else 0.0
            factoring_cost = factoring_amount * (
                _number(factoring.get("annual_rate_or_fee")) * 0.25
                + _number(factoring.get("processing_fee_rate"))
            )
            factoring_status = (
                "CONDITIONAL"
                if factoring_amount >= _number(factoring.get("minimum_amount")) and factoring_amount > 0
                else "INELIGIBLE"
            )
            options.append(
                {
                    "option_id": "PARTNERX-FACTOR" if _safe_text(factoring.get("bank")) == "PartnerX" else f"FACTOR-{product_id}",
                    "provider": _safe_text(factoring.get("bank")) or "Partner",
                    "logo_key": logo_key(_safe_text(factoring.get("bank"))),
                    "presentation_label": "ĐỐI TÁC GIẢ LẬP" if _safe_text(factoring.get("bank")) == "PartnerX" else "PHƯƠNG ÁN MÔ PHỎNG",
                    "product": _safe_text(factoring.get("product_name")) or "Invoice factoring",
                    "liquidity_amount": factoring_amount,
                    "guarantee_amount": 0.0,
                    "coverage_ratio": factoring_coverage,
                    "eligibility_score": None,
                    "estimated_cost": factoring_cost,
                    "cash_collateral": factoring_amount * _number(factoring.get("collateral_ratio")),
                    "fit_score": round(35 * min(1.0, factoring_coverage) + (20 if factoring_status == "CONDITIONAL" else 0), 1),
                    "status": factoring_status,
                    "mapping_scope": "CONTRACT_INVOICES",
                    "hard_gate_notes": (
                        [f"Không có hóa đơn mở/đã phát hành cho {contract.get('contract_id')}; chưa đủ điều kiện factoring."]
                        if not approved_invoice_amount
                        else ["Chỉ dùng invoice liên kết qua order_id của hợp đồng đang chọn."]
                    ),
                    "source": f"06_ORDERS[contract_id={contract.get('contract_id')}] + 07_INVOICES + 11_BANK_PRODUCTS[{product_id}]",
                }
            )

        options.sort(key=lambda option: option["fit_score"], reverse=True)
        for rank, option in enumerate(options, start=1):
            option["rank"] = rank

        if finance["missing_data"]:
            recommended = None
            partner_status = "NEED MORE DATA"
        else:
            recommended = next((option for option in options if option["status"] != "INELIGIBLE"), None)
            partner_status = "PRECHECK ONLY"

        workflow.append(
            _trace_event(
                trace_id,
                "Decision & Partner Agent",
                "tool_call",
                "10_CREDIT_PROFILE + 11_BANK_PRODUCTS + 12_API_CATALOG",
                "missing_data" if finance["missing_data"] else "needs_approval",
                f"So sánh {len(options)} phương án được map cho {contract.get('contract_id')}; không thể hiện ngân hàng đã phê duyệt.",
                "API-002",
            )
        )
        return {
            "status": partner_status,
            "options": options,
            "recommended": recommended,
            "api_call": {
                "api_id": "API-002",
                "provider": recommended["provider"] if recommended else None,
                "endpoint": "/openapi/v1/guarantee/precheck",
                "payload_masked": {
                    "contract_ref": _masked_contract_ref(contract.get("contract_id")),
                    "amount_band": f"{_number(finance.get('performance_bond_request')) / 1_000_000:.0f}M VND",
                    "company_profile": "TOK-ORG-001",
                },
                "execution": "NOT EXECUTED - chờ Founder Approval Gate; demo không gửi ra ngoài",
            },
            "disclaimer": "Tất cả sản phẩm/chi phí là dữ liệu mô phỏng trong TeamPack, không phải chấp thuận tín dụng thực tế.",
            "mapping_policy": "Exact contract_id/reference first; purpose/segment match or enterprise-shared scope must be disclosed; never borrow a case tied to another contract.",
        }

    def _decision_card(
        self,
        contract: dict[str, Any],
        finance: dict[str, Any],
        risk: dict[str, Any],
        partner: dict[str, Any],
        evidence: dict[str, bool],
    ) -> dict[str, Any]:
        contract_value = _number(finance.get("contract_value"))
        liquidity_shortfall = max(0.0, -finance["liquidity_headroom"])
        reconciliation = risk.get("transaction_reconciliation") or {}
        enterprise_anomalies = reconciliation.get("enterprise_anomalies") or []
        enterprise_anomaly_ids = list(
            dict.fromkeys(
                txn_id
                for item in enterprise_anomalies
                if (txn_id := _safe_text(item.get("txn_id")))
            )
        )
        enterprise_anomaly_label = "/".join(enterprise_anomaly_ids)
        margin_text = finance["margin_comparison_text"]
        funding_coverage = finance["funding_coverage_ratio"]
        reject_below = finance["liquidity_coverage_reject_below"]
        review_below = finance["liquidity_coverage_review_below"]
        if finance["missing_data"]:
            decision_type = "NEED MORE DATA"
            reasons = [
                f"Thiếu {len(finance['missing_data'])} bằng chứng bắt buộc; hệ thống không được suy đoán hồ sơ đã đầy đủ.",
                f"Funding gap đỉnh tạm tính {_format_billion(finance['peak_funding_gap'])}, nhưng chưa đủ căn cứ xác nhận khả năng tài trợ.",
                "Theo API-H-001/API-H-002, phải dừng precheck và yêu cầu đúng dữ liệu còn thiếu.",
            ]
            condition = "Founder giao người phụ trách bổ sung hồ sơ; chạy lại luồng trước mọi khuyến nghị đối tác."
        elif funding_coverage < reject_below:
            decision_type = "REJECT"
            reasons = [
                margin_text,
                (
                    f"Nguồn vốn tiềm năng {_format_billion(finance['potential_funding_capacity'])} chỉ bao phủ "
                    f"{funding_coverage:.1%} nhu cầu {_format_billion(finance['immediate_liquidity_need'])}, "
                    f"dưới hard gate {reject_below:.0%}; thiếu {_format_billion(liquidity_shortfall)}."
                ),
                f"Case risk {risk['case_risk_level']} và enterprise risk {risk['enterprise_risk_level']}; các control bắt buộc chưa được đóng.",
            ]
            condition = "Chỉ xem xét lại khi funding coverage đạt tối thiểu 80%; margin không được dùng để bỏ qua thiếu hụt thanh khoản."
        elif funding_coverage < review_below:
            decision_type = "NEED REVIEW"
            reasons = [
                margin_text,
                (
                    f"Nguồn vốn tiềm năng {_format_billion(finance['potential_funding_capacity'])} bao phủ "
                    f"{funding_coverage:.1%} nhu cầu {_format_billion(finance['immediate_liquidity_need'])}; "
                    f"còn thiếu {_format_billion(liquidity_shortfall)} trước ngưỡng {review_below:.0%}."
                ),
                f"Case risk {risk['case_risk_level']}; Founder phải xác minh availability của từng credit case trước quyết định.",
            ]
            condition = "Founder yêu cầu xác nhận/bổ sung nguồn vốn; chưa được phê duyệt partner submission khi coverage dưới 100%."
        elif finance["gross_margin"] < 0:
            decision_type = "REJECT"
            reasons = [
                margin_text,
                "Biên gộp âm làm hợp đồng không khả thi ngay cả khi funding coverage đã đạt ngưỡng.",
                f"Case risk {risk['case_risk_level']} và enterprise risk {risk['enterprise_risk_level']} vẫn cần xử lý độc lập.",
            ]
            condition = "Chỉ xem xét lại sau khi tái đàm phán giá/scope để biên gộp không còn âm."
        else:
            decision_type = "CONDITIONAL ACCEPT"
            reasons = [
                f"Cơ hội {_format_billion(contract_value)}; order coverage {finance['order_coverage_ratio']:.1%}. {margin_text}",
                (
                    f"Funding coverage {funding_coverage:.1%}: nguồn vốn tiềm năng "
                    f"{_format_billion(finance['potential_funding_capacity'])} so với nhu cầu "
                    f"{_format_billion(finance['immediate_liquidity_need'])}."
                ),
                f"Case risk {risk['case_risk_level']}; enterprise risk {risk['enterprise_risk_level']} được tách riêng và phải xử lý trước hành động không thể đảo ngược.",
            ]
            condition = (
                "Founder xác nhận đồng thời: khóa scope/giá, rollout theo giai đoạn, hạn mức và bảo lãnh trên 300M."
            )
            if enterprise_anomaly_label:
                condition = (
                    f"{condition} Tách luồng xác minh {enterprise_anomaly_label} "
                    "trước mọi partner submission."
                )

        anomaly_review_pending = (
            reconciliation.get("enterprise_anomaly_status")
            == "PENDING_FOUNDER_REVIEW"
        )
        approval_allowed = (
            decision_type in {"CONDITIONAL ACCEPT", "ACCEPT"}
            and not anomaly_review_pending
        )
        if anomaly_review_pending and decision_type in {"CONDITIONAL ACCEPT", "ACCEPT"}:
            condition = (
                f"{condition} Founder phải xác minh riêng các giao dịch bất thường cấp doanh nghiệp "
                "và chạy lại workflow trước khi nút Phê duyệt được mở."
            )

        return {
            "decision_type": decision_type,
            "headline": {
                "NEED MORE DATA": "TẠM DỪNG - BỔ SUNG DỮ LIỆU",
                "REJECT": "KHÔNG NHẬN Ở ĐIỀU KIỆN HIỆN TẠI",
                "NEED REVIEW": "CẦN FOUNDER RÀ SOÁT NGUỒN VỐN",
                "CONDITIONAL ACCEPT": "NHẬN HỢP ĐỒNG CÓ ĐIỀU KIỆN",
                "ACCEPT": "NHẬN HỢP ĐỒNG",
            }[decision_type],
            "three_reasons": reasons,
            "human_confirmation_point": condition,
            "recommended_actions": [
                "Khóa scope/giá và chia rollout thành các cổng nghiệm thu.",
                "Hoàn thiện aging evidence và bộ hồ sơ bảo lãnh thực hiện.",
                (
                    f"Xử lý {enterprise_anomaly_label} qua Founder Approval Gate trước hành động không thể đảo ngược."
                    if enterprise_anomaly_label
                    else "Lưu vết kết quả đối soát giao dịch trước hành động không thể đảo ngược."
                ),
            ],
            "approval_required": decision_type != "NEED MORE DATA",
            "approval_allowed": approval_allowed,
            "approval_status": (
                "BLOCKED_BY_DATA"
                if decision_type == "NEED MORE DATA"
                else "BLOCKED_BY_RULE"
                if decision_type == "REJECT"
                else "PENDING_REVIEW"
                if decision_type == "NEED REVIEW"
                else "PENDING_REVIEW"
                if anomaly_review_pending
                else "PENDING"
            ),
            "confidence": 0.86 if decision_type == "CONDITIONAL ACCEPT" else 0.74,
            "guardrail": "OpenAI chỉ được diễn giải/đối biện khi recommendation và scenario fingerprint khớp rule engine; không được tự gửi hồ sơ.",
        }

    def _openai_input(
        self,
        contract: dict[str, Any],
        finance: dict[str, Any],
        risk: dict[str, Any],
        partner: dict[str, Any],
        decision: dict[str, Any],
        evidence: dict[str, bool],
        scenario: dict[str, float],
        trace_id: str,
    ) -> dict[str, Any]:
        active_scenario_fields = [key for key, value in scenario.items() if abs(_number(value)) > 1e-9]
        if not active_scenario_fields:
            scenario_label = "BASELINE"
        elif scenario["cost_increase_pct"] and scenario["payment_delay_days"]:
            scenario_label = "COMBINED_STRESS"
        elif scenario["cost_increase_pct"]:
            scenario_label = "COST_STRESS"
        elif scenario["payment_delay_days"]:
            scenario_label = "PAYMENT_DELAY"
        else:
            scenario_label = "CUSTOM"

        # A content-only digest can be replayed when two runs have identical
        # inputs. Bind every Challenger packet to the unique audit trace while
        # exposing only a one-way run token in the masked payload.
        run_token = hashlib.sha256(_safe_text(trace_id).encode("utf-8")).hexdigest()[:16].upper()
        fingerprint_payload = {
            "run_token": run_token,
            "contract_ref": _masked_contract_ref(contract.get("contract_id")),
            "scenario": scenario,
            "gross_margin": round(finance["gross_margin"], 6),
            "peak_funding_gap_vnd": round(finance["peak_funding_gap"]),
            "case_risk_level": risk["case_risk_level"],
            "enterprise_risk_level": risk["enterprise_risk_level"],
            "deterministic_decision": decision["decision_type"],
        }
        scenario_fingerprint = hashlib.sha256(
            json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:16]

        return {
            "scenario_fingerprint": scenario_fingerprint,
            "run_token": run_token,
            "scenario_label": scenario_label,
            "scenario": scenario,
            "business_opportunity": {
                "contract_ref": _masked_contract_ref(contract.get("contract_id")),
                "customer_token": _customer_token(contract.get("customer_id")),
                "contract_value_band": f"{_number(contract.get('contract_value')) / 1_000_000_000:.1f}B VND",
                "deployment_scope_provinces": finance.get("deployment_scope_provinces"),
                "collection_timing_signal": finance.get("collection_timing_signal"),
                "performance_bond_required": bool(finance.get("performance_bond_required_signal")),
                "evidence_mode": finance.get("core_evidence_mode"),
            },
            "financial_snapshot": {
                "gross_margin": round(finance["gross_margin"], 4),
                "target_margin": round(finance["target_gross_margin"], 4),
                "order_coverage_ratio": round(finance["order_coverage_ratio"], 4),
                "peak_funding_gap_vnd": round(finance["peak_funding_gap"]),
                "guarantee_cash_impact_vnd": round(finance["guarantee_cash_impact"]),
                "immediate_liquidity_need_vnd": round(finance["immediate_liquidity_need"]),
                "liquidity_headroom_vnd": round(finance["liquidity_headroom"]),
                "working_capital_precheck_vnd": round(finance["working_capital_request"]),
                "performance_bond_vnd": round(finance["performance_bond_request"]),
            },
            "risk_report": {
                "case_risk_level": risk["case_risk_level"],
                "enterprise_risk_level": risk["enterprise_risk_level"],
                "triggered_rules": [alert["rule_id"] for alert in risk["alerts"]],
                "missing_data_count": len(finance["missing_data"]),
                "missing_data_labels": finance["missing_data"],
                "transaction_reconciliation": {
                    "status": (risk.get("transaction_reconciliation") or {}).get("status"),
                    "selected_contract_status": (
                        risk.get("transaction_reconciliation") or {}
                    ).get("selected_contract_status"),
                    "unmatched_incoming_count": (
                        (risk.get("transaction_reconciliation") or {}).get("kpis") or {}
                    ).get("unmatched_incoming_count", 0),
                    "enterprise_anomaly_count": (
                        (risk.get("transaction_reconciliation") or {}).get("kpis") or {}
                    ).get("enterprise_anomaly_count", 0),
                    "enterprise_anomaly_status": (
                        risk.get("transaction_reconciliation") or {}
                    ).get("enterprise_anomaly_status"),
                },
            },
            "partner_precheck": {
                "recommended_option": partner["recommended"]["option_id"] if partner["recommended"] else None,
                "status": partner["status"],
            },
            "deterministic_decision": decision["decision_type"],
            "control_policy": {
                "human_approval_over_vnd": round(_number(self.rules.get("founder_approval_threshold_vnd"), 300_000_000)),
                "restricted_identifiers_masked": True,
                "external_submission_allowed": False,
                "openai_must_echo_fingerprint": True,
                "openai_must_match_rule_engine": True,
            },
        }


def validate_openai_output(
    output: dict[str, Any],
    deterministic_decision: str,
    expected_input: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    reasons = output.get("three_reasons")
    checks.append(
        {
            "check": "exactly_three_reasons",
            "passed": isinstance(reasons, list) and len(reasons) == 3 and all(isinstance(item, str) and item.strip() for item in reasons),
            "note": "Decision Card phải có đúng ba lý do.",
        }
    )
    recommendation = _safe_text(output.get("recommendation")).upper()
    allowed = set(DECISION_STRENGTH)
    strength_ok = recommendation in allowed and DECISION_STRENGTH[recommendation] <= DECISION_STRENGTH[deterministic_decision]
    checks.append(
        {
            "check": "rule_engine_upper_bound",
            "passed": strength_ok,
            "note": f"OpenAI={recommendation or 'MISSING'}, rule engine={deterministic_decision}.",
        }
    )
    checks.append(
        {
            "check": "recommendation_exact_match",
            "passed": recommendation == deterministic_decision,
            "note": "Chỉ dùng câu chữ OpenAI khi recommendation khớp tuyệt đối rule engine để tránh Decision Card tự mâu thuẫn.",
        }
    )

    if expected_input is not None:
        expected_fingerprint = _safe_text(expected_input.get("scenario_fingerprint"))
        checks.append(
            {
                "check": "scenario_fingerprint_match",
                "passed": _safe_text(output.get("scenario_fingerprint")) == expected_fingerprint,
                "note": f"Expected fingerprint={expected_fingerprint}.",
            }
        )
        expected_scenario = expected_input.get("scenario") or {}
        echoed_scenario = output.get("scenario_echo") or {}
        scenario_match = all(
            abs(_number(echoed_scenario.get(key), float("inf")) - _number(value)) < 1e-9
            for key, value in expected_scenario.items()
        )
        checks.append(
            {
                "check": "scenario_values_match",
                "passed": isinstance(echoed_scenario, dict) and scenario_match,
                "note": "Cost/delay/deadline/scope/collateral phải đúng lượt chạy hiện tại.",
            }
        )
        expected_finance = expected_input.get("financial_snapshot") or {}
        expected_risk = expected_input.get("risk_report") or {}
        echo = output.get("evidence_echo") or {}
        evidence_match = (
            abs(_number(echo.get("gross_margin"), float("inf")) - _number(expected_finance.get("gross_margin"))) <= 0.0001
            and abs(_number(echo.get("peak_funding_gap_vnd"), float("inf")) - _number(expected_finance.get("peak_funding_gap_vnd"))) <= 1
            and _safe_text(echo.get("case_risk_level")) == _safe_text(expected_risk.get("case_risk_level"))
            and _safe_text(echo.get("enterprise_risk_level")) == _safe_text(expected_risk.get("enterprise_risk_level"))
        )
        checks.append(
            {
                "check": "financial_risk_echo_match",
                "passed": isinstance(echo, dict) and evidence_match,
                "note": "Biên, funding gap và hai lớp risk phải khớp dữ liệu đã mask.",
            }
        )
    serialized = json.dumps(output, ensure_ascii=False)
    leaked = bool(re.search(r"\bCUS-\d{3}\b|\bOPC_MAIN\b|\beyJ[A-Za-z0-9_-]+|\bsk-[A-Za-z0-9_-]+", serialized))
    checks.append(
        {
            "check": "restricted_data_not_leaked",
            "passed": not leaked,
            "note": "Không cho phép customer_id/account_id/token thô trong đầu ra.",
        }
    )
    human_point = _safe_text(output.get("human_confirmation_point"))
    checks.append(
        {
            "check": "human_confirmation_present",
            "passed": len(human_point) >= 20,
            "note": "Phải nêu rõ hành động Founder cần xác nhận.",
        }
    )
    return checks


def extract_response_text(response: dict[str, Any]) -> str:
    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                return str(content["text"])
    raise TeamPackError("OpenAI response không chứa output_text.")
