from __future__ import annotations

import hashlib
import json
import re
from typing import Any


CORE_EVIDENCE_FIELDS = (
    "performance_bond_required",
    "deployment_scope_provinces",
    "collection_timing_signal",
)

COLLECTION_SIGNALS = {
    "MONTHLY",
    "MILESTONE",
    "AFTER_UAT",
    "AFTER_ACCEPTANCE",
    "OPEN_INVOICE",
    "OTHER_EXPLICIT",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalise(value: Any) -> str:
    return re.sub(r"\s+", " ", _text(value)).strip().lower()


def _contract_token(contract_id: Any) -> str:
    digest = hashlib.sha256(_text(contract_id).encode("utf-8")).hexdigest()[:12].upper()
    return f"CTR-{digest}"


def build_extraction_packet(
    contract: dict[str, Any],
    orders: list[dict[str, Any]],
    run_token: str,
) -> dict[str, Any]:
    """Build the only free-text packet allowed to reach the evidence extractor.

    Customer IDs, account IDs, values and financial calculations are deliberately
    absent.  Source aliases let the model cite evidence while the server retains
    the exact TeamPack lineage.
    """

    contract_id = _text(contract.get("contract_id"))
    current_run_token = _text(run_token)
    if not current_run_token:
        raise ValueError("run_token is required to bind extraction evidence to one run")
    source_rows: list[tuple[str, str, str, str]] = [
        (
            "04_CONTRACTS",
            contract_id,
            "description",
            _text(contract.get("description")),
        ),
        (
            "04_CONTRACTS",
            contract_id,
            "payment_terms",
            _text(contract.get("payment_terms")),
        ),
    ]
    for order in orders:
        source_rows.append(
            (
                "06_ORDERS",
                _text(order.get("order_id")),
                "delivery_note",
                _text(order.get("delivery_note")),
            )
        )

    sources: list[dict[str, Any]] = []
    source_map: dict[str, dict[str, str]] = {}
    for index, (sheet, record_id, field, value) in enumerate(source_rows, start=1):
        source_id = f"SRC-{index:03d}"
        sources.append({"source_id": source_id, "field": field, "text": value})
        source_map[source_id] = {
            "sheet": sheet,
            "record_id": record_id,
            "field": field,
            "source": f"{sheet}[{record_id}].{field}",
        }

    public_payload = {
        "contract_ref": _contract_token(contract_id),
        "sources": sources,
    }
    # The trace-derived nonce is deliberately kept server-side.  It makes the
    # fingerprint unique to this run, so a valid response from an earlier run
    # cannot be replayed even when the source text is identical.
    fingerprint_payload = {
        **public_payload,
        "run_token": current_run_token,
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        **public_payload,
        "contract_fingerprint": fingerprint,
        "run_binding_hash": hashlib.sha256(current_run_token.encode("utf-8")).hexdigest(),
        "source_map": source_map,
        "policy": {
            "allowed_fields": list(CORE_EVIDENCE_FIELDS),
            "minimum_supported_confidence": 0.80,
            "no_financial_calculation": True,
            "no_unquoted_inference": True,
        },
    }


_BOND_NEGATION_PATTERNS = (
    r"\bno\s+(?:performance\s+)?bond\b",
    r"\bwithout\s+(?:a\s+)?(?:performance\s+)?bond\b",
    r"\b(?:performance\s+)?bond\s+(?:is\s+)?not\s+(?:required|needed|mandatory)\b",
    r"\bnot\s+(?:require|required|requiring)\s+(?:a\s+)?(?:performance\s+)?bond\b",
    r"\bkhông\s+(?:cần|yêu\s+cầu|bắt\s+buộc|phải\s+có)\s+(?:bảo\s+lãnh|bảo\s+lãnh\s+thực\s+hiện)\b",
    r"\bkhông\s+có\s+yêu\s+cầu\s+(?:về\s+)?bảo\s+lãnh\b",
    r"\bmiễn\s+(?:yêu\s+cầu\s+)?bảo\s+lãnh\b",
)

_COLLECTION_NEGATION_PATTERNS = (
    r"\bno\s+(?:payment|collection)\b",
    r"\b(?:payment|collection)\s+(?:is\s+)?not\b",
    r"\bnot\s+(?:paid|payable|collected)\b",
    r"\bwithout\s+(?:payment|collection)\b",
    r"\bkhông\s+(?:thanh\s+toán|thu\s+tiền|thu\s+hồi)\b",
    r"\bchưa\s+(?:thanh\s+toán|thu\s+tiền|thu\s+hồi)\b",
)


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _bond_semantic_match(value: bool, joined_quotes: str) -> bool:
    positive = bool(re.search(r"\bperformance\s+bond\b|\bbảo\s+lãnh(?:\s+thực\s+hiện)?\b", joined_quotes))
    explicitly_negated = _matches_any(joined_quotes, _BOND_NEGATION_PATTERNS)
    if value:
        return positive and not explicitly_negated
    # False is evidence too: it is accepted only when the text explicitly says
    # the bond is not required, never merely because a positive phrase is absent.
    return explicitly_negated


def _collection_semantic_match(signal: str, joined_quotes: str) -> bool:
    if _matches_any(joined_quotes, _COLLECTION_NEGATION_PATTERNS):
        return False

    action = r"(?:payment|payable|paid|collection|collect(?:ion|ed)?|invoice\s+due|thanh\s+toán|thu\s+tiền|thu\s+hồi)"
    signal_patterns: dict[str, tuple[str, ...]] = {
        "MONTHLY": (
            rf"{action}.{{0,40}}\bmonthly\b",
            rf"\bmonthly\b.{{0,40}}{action}",
            r"thanh\s+toán\s+(?:định\s+kỳ\s+)?hàng\s+tháng",
        ),
        "MILESTONE": (
            rf"{action}.{{0,50}}\b(?:by|per|at|on)\s+(?:each\s+)?milestone\b",
            r"thanh\s+toán.{0,30}(?:theo\s+mốc|theo\s+tiến\s+độ|theo\s+giai\s+đoạn)",
        ),
        "AFTER_UAT": (
            rf"{action}.{{0,50}}\bafter\s+(?:successful\s+)?uat\b",
            r"thanh\s+toán.{0,30}sau\s+(?:khi\s+)?uat",
        ),
        "AFTER_ACCEPTANCE": (
            rf"{action}.{{0,50}}\bafter\s+(?:final\s+)?acceptance\b",
            r"thanh\s+toán.{0,30}sau\s+(?:khi\s+)?nghiệm\s+thu",
        ),
        "OPEN_INVOICE": (
            rf"{action}.{{0,50}}\b(?:upon|after|on)\s+(?:an?\s+)?(?:open\s+)?invoice\b",
            r"thanh\s+toán.{0,40}(?:sau|khi).{0,20}(?:mở|phát\s+hành)\s+hóa\s+đơn",
        ),
    }
    if signal in signal_patterns:
        return _matches_any(joined_quotes, signal_patterns[signal])
    if signal != "OTHER_EXPLICIT":
        return False

    # OTHER_EXPLICIT is intentionally strict: both a money-collection action
    # and an explicit timing/due-date expression must be present.
    has_action = bool(re.search(action, joined_quotes, flags=re.IGNORECASE))
    timing_patterns = (
        r"\b(?:within|in|after)\s+\d{1,3}\s+(?:calendar\s+|business\s+)?days?\b",
        r"\bnet\s*\d{1,3}\b",
        r"\b(?:due|payable)\s+(?:on|by|before|upon)\b",
        r"\b(?:on|before|by)\s+\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b",
        r"\b(?:trong|sau)\s+\d{1,3}\s+ngày\b",
        r"\b(?:đến\s+hạn|trước\s+ngày|vào\s+ngày|khi\s+bàn\s+giao)\b",
    )
    return has_action and _matches_any(joined_quotes, timing_patterns)


def extraction_api_input(packet: dict[str, Any]) -> dict[str, Any]:
    """Remove server-only lineage before sending the packet to OpenAI."""

    return {
        "contract_ref": packet.get("contract_ref"),
        "contract_fingerprint": packet.get("contract_fingerprint"),
        "sources": packet.get("sources") or [],
        "policy": packet.get("policy") or {},
    }


def _field_check(
    field_name: str,
    item: Any,
    packet: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    checks: list[dict[str, Any]] = []
    sources = {row["source_id"]: row for row in packet.get("sources") or []}
    source_map = packet.get("source_map") or {}
    minimum_confidence = float((packet.get("policy") or {}).get("minimum_supported_confidence", 0.80))

    if not isinstance(item, dict):
        return ([{"check": f"{field_name}.object", "passed": False, "note": "Evidence field phải là object."}], None)

    status = _text(item.get("status")).upper()
    value = item.get("value")
    confidence = item.get("confidence")
    evidence = item.get("evidence")
    checks.append(
        {
            "check": f"{field_name}.status",
            "passed": status in {"SUPPORTED", "NOT_STATED", "AMBIGUOUS"},
            "note": "Status chỉ có SUPPORTED, NOT_STATED hoặc AMBIGUOUS.",
        }
    )
    confidence_ok = isinstance(confidence, (int, float)) and not isinstance(confidence, bool) and 0 <= float(confidence) <= 1
    checks.append(
        {
            "check": f"{field_name}.confidence_range",
            "passed": confidence_ok,
            "note": "Confidence phải nằm trong khoảng 0..1.",
        }
    )
    if not isinstance(evidence, list):
        evidence = []
        checks.append(
            {
                "check": f"{field_name}.evidence_array",
                "passed": False,
                "note": "Evidence phải là một mảng.",
            }
        )

    cited: list[dict[str, Any]] = []
    citations_ok = True
    for citation in evidence:
        if not isinstance(citation, dict):
            citations_ok = False
            continue
        source_id = _text(citation.get("source_id"))
        quote = _text(citation.get("quote"))
        source = sources.get(source_id)
        exact_quote = bool(source and quote and _normalise(quote) in _normalise(source.get("text")))
        if not exact_quote:
            citations_ok = False
            continue
        cited.append(
            {
                "source_id": source_id,
                "quote": quote,
                **(source_map.get(source_id) or {}),
            }
        )
    checks.append(
        {
            "check": f"{field_name}.evidence_grounded",
            "passed": citations_ok,
            "note": "Mỗi quote phải là đoạn văn có thật trong đúng source_id.",
        }
    )

    consistency_ok = True
    if status == "SUPPORTED":
        consistency_ok = value is not None and bool(cited) and confidence_ok and float(confidence) >= minimum_confidence
    elif status in {"NOT_STATED", "AMBIGUOUS"}:
        consistency_ok = value is None and (status != "NOT_STATED" or len(evidence) == 0)
    checks.append(
        {
            "check": f"{field_name}.status_value_consistency",
            "passed": consistency_ok,
            "note": "SUPPORTED cần value, quote và confidence ≥ 0.80; NOT_STATED không được tạo value/evidence.",
        }
    )

    semantic_ok = True
    semantic_note = (
        "Value phải khớp với toàn bộ source chứa quote; không được cắt quote để loại bỏ phủ định/ngữ cảnh."
    )
    joined_quotes = " ".join(_normalise(row.get("quote")) for row in cited)
    # A quote is only a pointer into the cited source, not an isolated truth.
    # Evaluate semantics against the full cited source so a cropped phrase such
    # as "performance bond" cannot hide the leading "No" from
    # "No performance bond is required".  The same guard closes cropped
    # payment/collection negations in both English and Vietnamese.
    joined_source_context = " ".join(
        _normalise((sources.get(row.get("source_id")) or {}).get("text"))
        for row in cited
    )
    semantic_context = joined_source_context or joined_quotes
    if status == "SUPPORTED":
        if field_name == "performance_bond_required":
            semantic_ok = isinstance(value, bool) and _bond_semantic_match(value, semantic_context)
        elif field_name == "deployment_scope_provinces":
            semantic_ok = isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 63
            if semantic_ok:
                province_numbers = {
                    int(match)
                    for match in re.findall(r"\b(\d{1,2})\s*[- ]?\s*(?:province|provinces|tỉnh|thành phố)\b", semantic_context)
                }
                semantic_ok = value in province_numbers
        elif field_name == "collection_timing_signal":
            signal = _text(value).upper()
            semantic_ok = signal in COLLECTION_SIGNALS and _collection_semantic_match(signal, semantic_context)
    checks.append(
        {
            "check": f"{field_name}.semantic_match",
            "passed": semantic_ok,
            "note": semantic_note,
        }
    )

    if not all(check["passed"] for check in checks):
        return checks, None
    return (
        checks,
        {
            "status": status,
            "value": value,
            "confidence": float(confidence),
            "evidence": cited,
            "validated": True,
        },
    )


def validate_extraction_output(
    output: Any,
    packet: dict[str, Any],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    if not isinstance(output, dict):
        return {
            "status": "BLOCKED_BY_VALIDATION",
            "checks": [{"check": "output_object", "passed": False, "note": "OpenAI output phải là JSON object."}],
            "validated_evidence": {},
        }

    fingerprint_ok = _text(output.get("contract_fingerprint")) == _text(packet.get("contract_fingerprint"))
    checks.append(
        {
            "check": "contract_fingerprint_match",
            "passed": fingerprint_ok,
            "note": "Extraction phải thuộc đúng source packet của lượt chạy hiện tại.",
        }
    )
    fields = output.get("fields")
    fields_ok = isinstance(fields, dict) and set(fields) == set(CORE_EVIDENCE_FIELDS)
    checks.append(
        {
            "check": "exact_core_fields",
            "passed": fields_ok,
            "note": "Output phải có đúng ba evidence field đã được phép.",
        }
    )

    validated_evidence: dict[str, Any] = {}
    if isinstance(fields, dict):
        for field_name in CORE_EVIDENCE_FIELDS:
            field_checks, validated = _field_check(field_name, fields.get(field_name), packet)
            checks.extend(field_checks)
            if validated is not None:
                validated_evidence[field_name] = validated

    passed = all(check["passed"] for check in checks) and len(validated_evidence) == len(CORE_EVIDENCE_FIELDS)
    return {
        "status": "VALIDATED" if passed else "BLOCKED_BY_VALIDATION",
        "checks": checks,
        "validated_evidence": validated_evidence if passed else {},
    }
