import sys
import unittest
from copy import deepcopy
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import DecisionEngine, TeamPack  # noqa: E402


CANONICAL_TEAM_PACK = ROOT / "data" / "MISTalent2026_OPC_AgenticAI_TeamPack_v3.xlsx"
DEFAULT_EVIDENCE = {
    "contract_signed": True,
    "receivable_aging": True,
    "capacity_plan": True,
    "suspicious_txn_reviewed": False,
}


class TransactionReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = TeamPack.from_path(CANONICAL_TEAM_PACK)

    def analyze(
        self,
        contract_id="CON-001",
        *,
        pack=None,
        suspicious_txn_reviewed=False,
    ):
        evidence = dict(DEFAULT_EVIDENCE)
        evidence["suspicious_txn_reviewed"] = suspicious_txn_reviewed
        return DecisionEngine(pack or self.pack).analyze(
            {"contract_id": contract_id, "scenario": {}, "evidence": evidence}
        )

    def mutated_pack(self):
        sheets = deepcopy(self.pack.sheets)
        return sheets, TeamPack(
            sheets,
            "reconciliation-probe.xlsx",
            "reconciliationprobe",
            list(self.pack.sheet_names),
        )

    def test_canonical_txn004_has_complete_explicit_lineage(self):
        reconciliation = self.analyze()["risk"]["transaction_reconciliation"]

        self.assertEqual(
            reconciliation["route"],
            ["08_BANK_TXN", "07_INVOICES", "06_ORDERS", "04_CONTRACTS"],
        )
        txn004 = next(row for row in reconciliation["records"] if row["txn_id"] == "TXN-004")
        self.assertEqual(txn004["match_level"], "L1_EXPLICIT_INVOICE_ID")
        self.assertEqual(txn004["match_status"], "MATCHED_SELECTED_CONTRACT")
        self.assertTrue(txn004["included_in_selected_contract"])
        self.assertEqual(txn004["invoice_id"], "INV-001")
        self.assertEqual(txn004["order_id"], "ORD-001")
        self.assertEqual(txn004["contract_id"], "CON-001")
        self.assertEqual(
            [step["sheet"] for step in txn004["lineage"]],
            ["08_BANK_TXN", "07_INVOICES", "06_ORDERS", "04_CONTRACTS"],
        )
        self.assertEqual(reconciliation["kpis"]["selected_contract_matched_amount"], 45_000_000)

    def test_txn002_is_unmatched_and_never_allocated_to_selected_contract(self):
        for contract_id in ("CON-001", "CON-002", "CON-004"):
            reconciliation = self.analyze(contract_id)["risk"]["transaction_reconciliation"]
            txn002 = next(row for row in reconciliation["records"] if row["txn_id"] == "TXN-002")
            self.assertEqual(txn002["match_status"], "UNMATCHED_INCOMING")
            self.assertEqual(txn002["match_level"], "NONE")
            self.assertIsNone(txn002["contract_id"])
            self.assertFalse(txn002["included_in_selected_contract"])

    def test_l2_uses_only_one_exact_amount_customer_paid_date_match(self):
        sheets, pack = self.mutated_pack()
        txn004 = next(row for row in sheets["08_BANK_TXN"] if row.get("txn_id") == "TXN-004")
        txn004["description"] = "Customer remittance without invoice reference"

        reconciliation = self.analyze(pack=pack)["risk"]["transaction_reconciliation"]
        matched = next(row for row in reconciliation["records"] if row["txn_id"] == "TXN-004")
        self.assertEqual(matched["match_level"], "L2_EXACT_UNIQUE_FACTS")
        self.assertEqual(matched["match_rule"], "UNIQUE_EXACT_AMOUNT_COUNTERPARTY_PAID_DATE")
        self.assertEqual(matched["contract_id"], "CON-001")
        self.assertTrue(all(matched["fact_checks"].values()))

    def test_l2_refuses_ambiguous_exact_facts(self):
        sheets, pack = self.mutated_pack()
        txn004 = next(row for row in sheets["08_BANK_TXN"] if row.get("txn_id") == "TXN-004")
        txn004["description"] = "Customer remittance without invoice reference"
        inv001 = next(row for row in sheets["07_INVOICES"] if row.get("invoice_id") == "INV-001")
        duplicate = dict(inv001)
        duplicate["invoice_id"] = "INV-901"
        sheets["07_INVOICES"].append(duplicate)

        reconciliation = self.analyze(pack=pack)["risk"]["transaction_reconciliation"]
        ambiguous = next(row for row in reconciliation["records"] if row["txn_id"] == "TXN-004")
        self.assertEqual(ambiguous["match_status"], "UNMATCHED_INCOMING")
        self.assertEqual(ambiguous["match_level"], "NONE")
        self.assertEqual(ambiguous["match_rule"], "AMBIGUOUS_EXACT_FACTS")
        self.assertFalse(ambiguous["included_in_selected_contract"])

    def test_paid_invoice_without_credit_match_triggers_reverse_warning(self):
        sheets, pack = self.mutated_pack()
        txn004 = next(row for row in sheets["08_BANK_TXN"] if row.get("txn_id") == "TXN-004")
        txn004["description"] = "Unreferenced remittance"
        txn004["amount"] = 44_000_000

        result = self.analyze(pack=pack)
        reconciliation = result["risk"]["transaction_reconciliation"]
        self.assertEqual(reconciliation["selected_contract_status"], "REVIEW_REQUIRED")
        self.assertEqual(reconciliation["kpis"]["reverse_paid_warning_count"], 1)
        warning = reconciliation["reverse_paid_warnings"][0]
        self.assertEqual(warning["rule_id"], "RR-REC-001")
        self.assertEqual(warning["invoice_id"], "INV-001")
        self.assertEqual(warning["contract_id"], "CON-001")
        self.assertTrue(any(alert["rule_id"] == "RR-REC-001" for alert in result["risk"]["alerts"]))

    def test_suspicious_debits_stay_enterprise_scoped_and_follow_evidence(self):
        pending = self.analyze()["risk"]
        pending_reconciliation = pending["transaction_reconciliation"]
        self.assertEqual(
            {row["txn_id"] for row in pending_reconciliation["enterprise_anomalies"]},
            {"TXN-006", "TXN-007"},
        )
        self.assertTrue(
            all(
                row["scope"] == "ENTERPRISE"
                and not row["included_in_selected_contract"]
                and row["review_status"] == "PENDING_FOUNDER_REVIEW"
                for row in pending_reconciliation["enterprise_anomalies"]
            )
        )
        self.assertTrue(any(alert["rule_id"] == "RR-001" for alert in pending["alerts"]))

        reviewed = self.analyze(suspicious_txn_reviewed=True)["risk"]
        reviewed_reconciliation = reviewed["transaction_reconciliation"]
        self.assertEqual(reviewed_reconciliation["enterprise_anomaly_status"], "REVIEWED_BY_EVIDENCE")
        self.assertTrue(
            all(
                row["review_status"] == "REVIEWED_BY_EVIDENCE"
                for row in reviewed_reconciliation["enterprise_anomalies"]
            )
        )
        self.assertFalse(any(alert["rule_id"] == "RR-001" for alert in reviewed["alerts"]))

    def test_high_risk_incoming_with_exact_lineage_keeps_case_and_enterprise_scopes(self):
        sheets, pack = self.mutated_pack()
        txn004 = next(row for row in sheets["08_BANK_TXN"] if row.get("txn_id") == "TXN-004")
        txn004["transaction_risk_score"] = 99
        txn004["txn_status"] = "Suspicious"

        reconciliation = self.analyze("CON-001", pack=pack)["risk"]["transaction_reconciliation"]
        record = next(row for row in reconciliation["records"] if row["txn_id"] == "TXN-004")
        anomaly = next(row for row in reconciliation["enterprise_anomalies"] if row["txn_id"] == "TXN-004")

        self.assertEqual(record["match_status"], "MATCHED_SELECTED_CONTRACT")
        self.assertTrue(record["included_in_selected_contract"])
        self.assertEqual(record["scope"], "BOTH")
        self.assertEqual(record["scopes"], ["CASE", "ENTERPRISE", "REVIEW"])
        self.assertEqual(anomaly["contract_id"], "CON-001")
        self.assertTrue(anomaly["in_selected_contract"])
        self.assertTrue(anomaly["included_in_selected_contract"])
        self.assertEqual(anomaly["scope"], "BOTH")
        self.assertEqual(anomaly["scopes"], ["CASE", "ENTERPRISE", "REVIEW"])
        # The anomaly control is an additional review layer, not another cash
        # allocation.  Decision-grade matched cash remains exactly one txn.
        self.assertEqual(reconciliation["kpis"]["selected_contract_matched_txn_count"], 1)
        self.assertEqual(reconciliation["kpis"]["selected_contract_matched_amount"], 45_000_000)

    def test_high_risk_unmatched_incoming_remains_enterprise_only(self):
        sheets, pack = self.mutated_pack()
        txn002 = next(row for row in sheets["08_BANK_TXN"] if row.get("txn_id") == "TXN-002")
        txn002["transaction_risk_score"] = 99
        txn002["txn_status"] = "Suspicious"

        reconciliation = self.analyze("CON-001", pack=pack)["risk"]["transaction_reconciliation"]
        record = next(row for row in reconciliation["records"] if row["txn_id"] == "TXN-002")
        anomaly = next(row for row in reconciliation["enterprise_anomalies"] if row["txn_id"] == "TXN-002")

        self.assertEqual(record["match_status"], "UNMATCHED_INCOMING")
        self.assertFalse(record["included_in_selected_contract"])
        self.assertNotIn("CASE", record["scopes"])
        self.assertEqual(record["scopes"], ["ENTERPRISE", "REVIEW"])
        self.assertIsNone(anomaly["contract_id"])
        self.assertFalse(anomaly["in_selected_contract"])
        self.assertEqual(anomaly["scope"], "ENTERPRISE")
        self.assertEqual(anomaly["scopes"], ["ENTERPRISE", "REVIEW"])
        self.assertEqual(reconciliation["kpis"]["selected_contract_matched_amount"], 45_000_000)

    def test_enterprise_anomaly_review_is_a_hard_founder_approval_gate(self):
        pending = self.analyze("CON-005", suspicious_txn_reviewed=False)
        self.assertEqual(pending["decision"]["decision_type"], "CONDITIONAL ACCEPT")
        self.assertFalse(pending["decision"]["approval_allowed"])
        self.assertEqual(pending["decision"]["approval_status"], "PENDING_REVIEW")

        reviewed = self.analyze("CON-005", suspicious_txn_reviewed=True)
        self.assertEqual(reviewed["decision"]["decision_type"], "CONDITIONAL ACCEPT")
        self.assertTrue(reviewed["decision"]["approval_allowed"])
        self.assertEqual(reviewed["decision"]["approval_status"], "PENDING")

    def test_decision_card_uses_runtime_anomaly_ids_instead_of_canonical_ids(self):
        sheets, pack = self.mutated_pack()
        replacements = {
            "TXN-006": "BANK-RISK-A9",
            "TXN-007": "BANK-RISK-B4",
        }
        for row in sheets["08_BANK_TXN"]:
            txn_id = row.get("txn_id")
            if txn_id in replacements:
                row["txn_id"] = replacements[txn_id]

        result = self.analyze("CON-005", pack=pack)
        decision_text = json.dumps(result["decision"], ensure_ascii=False)

        self.assertIn("BANK-RISK-A9", decision_text)
        self.assertIn("BANK-RISK-B4", decision_text)
        self.assertNotIn("TXN-006", decision_text)
        self.assertNotIn("TXN-007", decision_text)

    def test_selected_contract_scope_excludes_a_match_owned_by_another_contract(self):
        reconciliation = self.analyze("CON-002")["risk"]["transaction_reconciliation"]
        txn004 = next(row for row in reconciliation["records"] if row["txn_id"] == "TXN-004")
        self.assertEqual(reconciliation["scope"]["contract_id"], "CON-002")
        self.assertEqual(txn004["match_status"], "MATCHED_OTHER_CONTRACT")
        self.assertEqual(txn004["contract_id"], "CON-001")
        self.assertFalse(txn004["included_in_selected_contract"])
        self.assertEqual(reconciliation["kpis"]["selected_contract_matched_txn_count"], 0)
        self.assertEqual(reconciliation["kpis"]["selected_contract_matched_amount"], 0)

    def test_reconciliation_output_masks_counterparty_and_account_identifiers(self):
        reconciliation_json = json.dumps(
            self.analyze("CON-001")["risk"]["transaction_reconciliation"],
            ensure_ascii=False,
        )
        raw_values = {
            str(row.get(field) or "").strip()
            for row in self.pack.rows("08_BANK_TXN")
            for field in ("counterparty_id", "account_id")
            if str(row.get(field) or "").strip()
        }
        # Generic words may legitimately occur in status labels; all actual
        # identifier-shaped values must remain server-side.
        raw_values.discard("FOUNDER")
        self.assertTrue(all(value not in reconciliation_json for value in raw_values))
        self.assertTrue(
            all("counterparty_token" in row for row in json.loads(reconciliation_json)["records"])
        )


if __name__ == "__main__":
    unittest.main()
