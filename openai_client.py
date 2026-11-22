from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from engine import TeamPackError, extract_response_text, validate_openai_output


OPENAI_URL = "https://api.openai.com/v1/responses"


OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "scenario_fingerprint": {"type": "string"},
        "scenario_echo": {
            "type": "object",
            "properties": {
                "cost_increase_pct": {"type": "number"},
                "payment_delay_days": {"type": "number"},
                "deadline_change_days": {"type": "number"},
                "scope_change_pct": {"type": "number"},
                "collateral_change_pp": {"type": "number"},
            },
            "required": [
                "cost_increase_pct",
                "payment_delay_days",
                "deadline_change_days",
                "scope_change_pct",
                "collateral_change_pp",
            ],
            "additionalProperties": False,
        },
        "evidence_echo": {
            "type": "object",
            "properties": {
                "gross_margin": {"type": "number"},
                "peak_funding_gap_vnd": {"type": "number"},
                "case_risk_level": {"type": "string", "enum": ["Low", "Medium", "High", "Critical"]},
                "enterprise_risk_level": {"type": "string", "enum": ["Low", "Medium", "High", "Critical"]},
            },
            "required": [
                "gross_margin",
                "peak_funding_gap_vnd",
                "case_risk_level",
                "enterprise_risk_level",
            ],
            "additionalProperties": False,
        },
        "recommendation": {
            "type": "string",
            "enum": ["ACCEPT", "CONDITIONAL ACCEPT", "NEED REVIEW", "REJECT", "NEED MORE DATA"],
        },
        "three_reasons": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 3},
        "human_confirmation_point": {"type": "string"},
        "risk_explanation": {"type": "string"},
        "data_quality_comment": {"type": "string"},
    },
    "required": [
        "scenario_fingerprint",
        "scenario_echo",
        "evidence_echo",
        "recommendation",
        "three_reasons",
        "human_confirmation_point",
        "risk_explanation",
        "data_quality_comment",
    ],
    "additionalProperties": False,
}


def _evidence_field_schema(value_schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["SUPPORTED", "NOT_STATED", "AMBIGUOUS"],
            },
            "value": {"anyOf": [value_schema, {"type": "null"}]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "evidence": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "source_id": {"type": "string"},
                        "quote": {"type": "string"},
                    },
                    "required": ["source_id", "quote"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["status", "value", "confidence", "evidence"],
        "additionalProperties": False,
    }


EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "contract_fingerprint": {"type": "string"},
        "fields": {
            "type": "object",
            "properties": {
                "performance_bond_required": _evidence_field_schema({"type": "boolean"}),
                "deployment_scope_provinces": _evidence_field_schema(
                    {"type": "integer", "minimum": 1, "maximum": 63}
                ),
                "collection_timing_signal": _evidence_field_schema(
                    {
                        "type": "string",
                        "enum": [
                            "MONTHLY",
                            "MILESTONE",
                            "AFTER_UAT",
                            "AFTER_ACCEPTANCE",
                            "OPEN_INVOICE",
                            "OTHER_EXPLICIT",
                        ],
                    }
                ),
            },
            "required": [
                "performance_bond_required",
                "deployment_scope_provinces",
                "collection_timing_signal",
            ],
            "additionalProperties": False,
        },
    },
    "required": ["contract_fingerprint", "fields"],
    "additionalProperties": False,
}


def is_configured() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY", "").strip())


def model_name() -> str:
    return os.environ.get("OPENAI_MODEL", "gpt-5.6-luna").strip() or "gpt-5.6-luna"


def extract_structured_evidence(masked_packet: dict[str, Any], timeout: int = 45) -> dict[str, Any]:
    """Extract three allowed business signals from free text.

    This call never receives amounts, account IDs or customer IDs.  Its output is
    still untrusted: the orchestrator must run deterministic source/quote,
    fingerprint and semantic validation before passing any field to the engine.
    """

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise TeamPackError("OPENAI_API_KEY chưa được cấu hình trên máy chạy demo.")

    instructions = (
        "Bạn là Structured Evidence Extractor của OPC Agentic AI. Chỉ trích xuất ba trường được yêu cầu "
        "từ sources đã cung cấp; không tính tiền, không suy đoán tín dụng và không đưa ra quyết định. "
        "Mọi SUPPORTED field phải có quote nguyên văn thuộc đúng source_id và confidence chỉ phản ánh độ rõ của văn bản. "
        "Nếu văn bản không nêu thì trả NOT_STATED với value=null và evidence rỗng; nếu mâu thuẫn hoặc không chắc thì "
        "trả AMBIGUOUS với value=null. Sao chép contract_fingerprint chính xác. "
        "performance_bond_required chỉ true khi văn bản khẳng định rõ performance bond/bảo lãnh và không có phủ định; "
        "chỉ false khi quote nói rõ không/no/not required/without bond; "
        "deployment_scope_provinces chỉ dùng số tỉnh/thành được nêu trực tiếp; "
        "collection_timing_signal chỉ dùng tín hiệu thời điểm thu tiền/thanh toán được nêu trực tiếp, "
        "không gán enum từ câu phủ định; OTHER_EXPLICIT phải có cả hành động thu tiền và mốc thời gian rõ."
    )
    body = {
        "model": model_name(),
        "reasoning": {"effort": "low"},
        "instructions": instructions,
        "input": json.dumps(masked_packet, ensure_ascii=False, separators=(",", ":")),
        "max_output_tokens": 900,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "opc_structured_evidence",
                "strict": True,
                "schema": EXTRACTION_SCHEMA,
            }
        },
    }
    request = urllib.request.Request(
        OPENAI_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise TeamPackError(f"OpenAI extraction HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise TeamPackError(f"Không kết nối được OpenAI Evidence Extractor: {exc}") from exc

    text = extract_response_text(raw)
    try:
        output = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TeamPackError("OpenAI extraction output không phải JSON hợp lệ.") from exc
    return {
        "called": True,
        "status": "returned_unvalidated",
        "model": model_name(),
        "response_id": raw.get("id"),
        "output": output,
        "usage": raw.get("usage"),
    }


def review_decision(masked_input: dict[str, Any], deterministic_decision: str, timeout: int = 45) -> dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise TeamPackError("OPENAI_API_KEY chưa được cấu hình trên máy chạy demo.")

    instructions = (
        "Bạn là Decision Challenger trong hệ thống OPC Agentic AI. Chỉ dùng dữ liệu đã cung cấp, "
        "không suy đoán phê duyệt ngân hàng. Kiểm tra logic tài chính, rủi ro và dữ liệu thiếu; trả lời tiếng Việt. "
        "Recommendation phải KHỚP CHÍNH XÁC deterministic_decision; không được tự gửi hồ sơ hay tự phê duyệt. "
        "Sao chép nguyên vẹn scenario_fingerprint, toàn bộ scenario vào scenario_echo, và bốn trường yêu cầu vào evidence_echo. "
        "Không được thêm số liệu, phần trăm, số ngày hoặc giả định ngoài masked input. Nếu scenario_label=BASELINE thì tuyệt đối không mô tả tăng chi phí hay chậm thanh toán. "
        "Phải giữ đúng ba lý do, nêu một điểm Founder cần xác nhận và không tái tạo định danh bị mask."
    )
    body = {
        "model": model_name(),
        "reasoning": {"effort": "low"},
        "instructions": instructions,
        "input": json.dumps(masked_input, ensure_ascii=False, separators=(",", ":")),
        "max_output_tokens": 900,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "opc_decision_challenge",
                "strict": True,
                "schema": OUTPUT_SCHEMA,
            }
        },
    }
    request = urllib.request.Request(
        OPENAI_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise TeamPackError(f"OpenAI HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise TeamPackError(f"Không kết nối được OpenAI: {exc}") from exc

    text = extract_response_text(raw)
    try:
        output = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TeamPackError("OpenAI output không phải JSON hợp lệ.") from exc
    checks = validate_openai_output(output, deterministic_decision, masked_input)
    return {
        "called": True,
        "status": "validated" if all(check["passed"] for check in checks) else "blocked_by_validation",
        "model": model_name(),
        "response_id": raw.get("id"),
        "output": output,
        "validation": checks,
        "usage": raw.get("usage"),
    }
