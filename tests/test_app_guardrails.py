import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import AppState  # noqa: E402
from engine import DecisionEngine, TeamPack, TeamPackError  # noqa: E402


TEAM_PACK = ROOT / "data" / "MISTalent2026_OPC_AgenticAI_TeamPack_v3.xlsx"


class AppGuardrailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = TeamPack.from_path(TEAM_PACK)

    def test_rule_reject_cannot_be_approved_through_api_state(self):
        state = AppState()
        state.pack = self.pack
        state.runs["TRACE-REJECT"] = {
            "decision": {
                "decision_type": "REJECT",
                "approval_required": True,
                "approval_allowed": False,
            }
        }
        payload = {
            "trace_id": "TRACE-REJECT",
            "founder_name": "Founder Test",
            "action": "APPROVE",
            "confirmed": True,
        }
        with self.assertRaisesRegex(TeamPackError, "không cho phép phê duyệt"):
            state.approve(payload)

        with patch("app.append_audit"):
            rejected = state.approve({**payload, "action": "REJECT"})
        self.assertEqual(rejected["status"], "REJECTED_BY_FOUNDER")
        self.assertFalse(rejected["external_submission_executed"])

    def test_engine_requires_explicit_contract_id(self):
        with self.assertRaisesRegex(TeamPackError, "Thiếu contract_id"):
            DecisionEngine(self.pack).analyze({"scenario": {}, "evidence": {}})

    def test_approval_ids_are_unique_in_same_second_and_link_exact_trace(self):
        # AppState converts the local wall clock to an aware timestamp.  Keep
        # this fixture naive so that conversion attaches, rather than shifts,
        # the same 18:37:37 wall-clock second on every host timezone.
        fixed_second = datetime(2026, 7, 20, 18, 37, 37)

        class FrozenDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed_second if tz is None else fixed_second.astimezone(tz)

        state = AppState()
        trace_ids = [f"TRACE-TEST-{index:02d}" for index in range(20)]
        for trace_id in trace_ids:
            state.runs[trace_id] = {
                "decision": {
                    "decision_type": "CONDITIONAL ACCEPT",
                    "approval_required": True,
                    "approval_allowed": True,
                }
            }

        records = []
        with patch("app.datetime", FrozenDateTime), patch("app.append_audit"):
            for trace_id in trace_ids:
                records.append(
                    state.approve(
                        {
                            "trace_id": trace_id,
                            "founder_name": "Founder Test",
                            "action": "APPROVE",
                            "confirmed": True,
                        }
                    )
                )

        approval_ids = {record["approval_id"] for record in records}
        self.assertEqual(len(approval_ids), len(trace_ids))
        self.assertEqual(set(state.approvals), approval_ids)
        for expected_trace, record in zip(trace_ids, records):
            self.assertEqual(record["trace_id"], expected_trace)
            self.assertIs(state.approvals[record["approval_id"]], record)
            self.assertRegex(
                record["approval_id"],
                r"^APR-20260720-183737-[0-9A-F]{32}$",
            )


if __name__ == "__main__":
    unittest.main()
