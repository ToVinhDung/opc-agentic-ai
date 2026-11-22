import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from app import AppState


ROOT = Path(__file__).resolve().parents[1]


def extraction_result(masked_packet, *, con004=False, invalid_quote=False):
    if con004:
        bond_quote = "Invented bond text" if invalid_quote else "Performance bond required"
        fields = {
            "performance_bond_required": {
                "status": "SUPPORTED",
                "value": True,
                "confidence": 0.98,
                "evidence": [{"source_id": "SRC-002", "quote": bond_quote}],
            },
            "deployment_scope_provinces": {
                "status": "SUPPORTED",
                "value": 20,
                "confidence": 0.96,
                "evidence": [
                    {"source_id": "SRC-001", "quote": "20-province cooperative network rollout"}
                ],
            },
            "collection_timing_signal": {
                "status": "NOT_STATED",
                "value": None,
                "confidence": 0.90,
                "evidence": [],
            },
        }
    else:
        fields = {
            name: {
                "status": "NOT_STATED",
                "value": None,
                "confidence": 0.90,
                "evidence": [],
            }
            for name in (
                "performance_bond_required",
                "deployment_scope_provinces",
                "collection_timing_signal",
            )
        }
    return {
        "called": True,
        "status": "returned_unvalidated",
        "model": "test-model",
        "response_id": "resp_extract_test",
        "usage": {"input_tokens": 1, "output_tokens": 1},
        "output": {
            "contract_fingerprint": masked_packet["contract_fingerprint"],
            "fields": fields,
        },
    }


def challenger_result(masked_input, decision):
    finance = masked_input["financial_snapshot"]
    risk = masked_input["risk_report"]
    return {
        "called": True,
        "status": "validated",
        "model": "test-model",
        "response_id": "resp_challenge_test",
        "usage": {"input_tokens": 1, "output_tokens": 1},
        "output": {
            "scenario_fingerprint": masked_input["scenario_fingerprint"],
            "scenario_echo": masked_input["scenario"],
            "evidence_echo": {
                "gross_margin": finance["gross_margin"],
                "peak_funding_gap_vnd": finance["peak_funding_gap_vnd"],
                "case_risk_level": risk["case_risk_level"],
                "enterprise_risk_level": risk["enterprise_risk_level"],
            },
            "recommendation": decision,
            "three_reasons": ["Lý do được kiểm soát 1", "Lý do được kiểm soát 2", "Lý do được kiểm soát 3"],
            "human_confirmation_point": "Founder xác nhận evidence và điều kiện kiểm soát trước precheck.",
            "risk_explanation": "Chỉ diễn giải risk report đã mask.",
            "data_quality_comment": "Không thay đổi Data Quality của rule engine.",
        },
        "validation": [{"check": "test_guardrail", "passed": True, "note": "fixture"}],
    }


class OpenAICorePipelineTests(unittest.TestCase):
    def setUp(self):
        self.state = AppState()

    def payload(self, contract_id, *, use_openai=True):
        return {
            "contract_id": contract_id,
            "scenario": {},
            "use_openai": use_openai,
            "evidence": {
                "contract_signed": True,
                "receivable_aging": True,
                "capacity_plan": True,
                "suspicious_txn_reviewed": True,
            },
        }

    def test_validated_extraction_runs_before_engine_and_challenger_after(self):
        call_order = []

        def fake_extract(packet):
            call_order.append("extract")
            return extraction_result(packet)

        def fake_challenge(masked_input, decision):
            call_order.append("challenge")
            return challenger_result(masked_input, decision)

        with patch("app.extract_structured_evidence", side_effect=fake_extract), patch(
            "app.review_decision", side_effect=fake_challenge
        ), patch("app.append_audit"):
            result = self.state.analyze(self.payload("CON-005"))

        self.assertEqual(call_order, ["extract", "challenge"])
        self.assertEqual(result["openai"]["status"], "validated")
        self.assertEqual(result["finance"]["core_evidence_mode"], "OPENAI_STRUCTURED_EVIDENCE_VALIDATED")
        self.assertEqual(result["decision"]["decision_type"], "CONDITIONAL ACCEPT")
        self.assertTrue(result["decision"]["approval_allowed"])
        self.assertEqual(result["workflow"][0]["agent_or_component"], "OpenAI Evidence Extractor")
        self.assertEqual(result["workflow"][-1]["agent_or_component"], "OpenAI Decision Challenger")
        self.assertLess(
            datetime.fromisoformat(result["workflow"][0]["timestamp"]),
            datetime.fromisoformat(result["workflow"][1]["timestamp"]),
        )
        self.assertEqual(result["decision"]["rule_engine_decision"], "CONDITIONAL ACCEPT")
        self.assertEqual(result["decision"]["final_gated_decision"], "CONDITIONAL ACCEPT")

    def test_con004_validated_evidence_drives_bond_and_rollout_risk(self):
        with patch(
            "app.extract_structured_evidence",
            side_effect=lambda packet: extraction_result(packet, con004=True),
        ), patch(
            "app.review_decision",
            side_effect=lambda masked, decision: challenger_result(masked, decision),
        ), patch("app.append_audit"):
            result = self.state.analyze(self.payload("CON-004"))

        self.assertEqual(result["finance"]["performance_bond_request"], 420_000_000)
        self.assertEqual(result["finance"]["deployment_scope_provinces"], 20)
        rollout = next(alert for alert in result["risk"]["alerts"] if alert["rule_id"] == "AL-003")
        self.assertIn("Structured Evidence", rollout["source"])
        self.assertEqual(result["decision"]["decision_type"], "REJECT")

    def test_invalid_quote_blocks_extraction_and_challenger(self):
        challenger = Mock()
        with patch(
            "app.extract_structured_evidence",
            side_effect=lambda packet: extraction_result(packet, con004=True, invalid_quote=True),
        ), patch("app.review_decision", challenger), patch("app.append_audit"):
            result = self.state.analyze(self.payload("CON-004"))

        self.assertEqual(result["openai"]["extraction"]["status"], "blocked_by_validation")
        self.assertEqual(result["openai"]["challenger"]["status"], "blocked_by_extraction")
        challenger.assert_not_called()
        self.assertEqual(result["decision"]["decision_type"], "REJECT")

    def test_offline_mode_caps_an_approvable_result_at_need_review(self):
        challenger = Mock()
        with patch("app.review_decision", challenger), patch("app.append_audit"):
            result = self.state.analyze(self.payload("CON-005", use_openai=False))

        self.assertEqual(result["decision"]["decision_type"], "NEED REVIEW")
        self.assertEqual(result["decision"]["rule_engine_decision"], "CONDITIONAL ACCEPT")
        self.assertEqual(result["decision"]["final_gated_decision"], "NEED REVIEW")
        self.assertEqual(
            result["openai"]["input_masked"]["deterministic_decision"],
            "CONDITIONAL ACCEPT",
        )
        self.assertFalse(result["decision"]["approval_allowed"])
        self.assertEqual(result["openai"]["extraction"]["status"], "disabled_for_run")
        self.assertGreater(result["finance"]["peak_funding_gap"], 0)
        challenger.assert_not_called()

    def test_offline_mode_does_not_weaken_deterministic_reject(self):
        with patch("app.append_audit"):
            result = self.state.analyze(self.payload("CON-004", use_openai=False))
        self.assertEqual(result["decision"]["decision_type"], "REJECT")
        self.assertFalse(result["decision"]["approval_allowed"])


if __name__ == "__main__":
    unittest.main()
