import json
import re
import shutil
import sys
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import DecisionEngine, TeamPack, make_audit_id, validate_openai_output  # noqa: E402
from tests.workbook_fixtures import create_external_copy_with_blanks  # noqa: E402


CANONICAL_TEAM_PACK = ROOT / "data" / "MISTalent2026_OPC_AgenticAI_TeamPack_v3.xlsx"


class DecisionEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = TeamPack.from_path(CANONICAL_TEAM_PACK)
        cls.engine = DecisionEngine(cls.pack)

    def analyze(self, **overrides):
        payload = {
            "contract_id": "CON-004",
            "evidence": {
                "contract_signed": True,
                "receivable_aging": True,
                "capacity_plan": True,
                "suspicious_txn_reviewed": False,
            },
            "scenario": {},
        }
        payload.update(overrides)
        return self.engine.analyze(payload)

    def test_trace_ids_are_unique_within_the_same_second_and_keep_full_uuid(self):
        fixed_second = datetime(2026, 7, 20, 18, 37, 37, tzinfo=timezone.utc)
        trace_ids = {make_audit_id("TRACE", fixed_second) for _ in range(100)}

        self.assertEqual(len(trace_ids), 100)
        for trace_id in trace_ids:
            self.assertRegex(
                trace_id,
                re.compile(r"^TRACE-20260720-183737-[0-9A-F]{32}$"),
            )

    def test_main_flow_has_grounded_decision_with_three_reasons(self):
        result = self.analyze()
        self.assertIn(
            result["decision"]["decision_type"],
            {"ACCEPT", "CONDITIONAL ACCEPT", "NEED REVIEW", "REJECT"},
        )
        self.assertEqual(len(result["decision"]["three_reasons"]), 3)
        self.assertEqual(
            result["finance"]["peak_funding_gap"],
            max(row["funding_gap"] for row in result["finance"]["contract_cashflow"]),
        )
        self.assertTrue(result["decision"]["approval_required"])

    def test_missing_data_stops_decision(self):
        result = self.analyze(
            evidence={
                "contract_signed": True,
                "receivable_aging": False,
                "capacity_plan": False,
                "suspicious_txn_reviewed": False,
            }
        )
        self.assertEqual(result["decision"]["decision_type"], "NEED MORE DATA")
        self.assertEqual(result["decision"]["approval_status"], "BLOCKED_BY_DATA")
        self.assertGreaterEqual(len(result["finance"]["missing_data"]), 2)

    def test_cost_crisis_reduces_margin_and_increases_gap(self):
        baseline = self.analyze()
        crisis = self.analyze(scenario={"cost_increase_pct": 15})
        self.assertLess(crisis["finance"]["gross_margin"], baseline["finance"]["gross_margin"])
        self.assertGreater(crisis["finance"]["peak_funding_gap"], baseline["finance"]["peak_funding_gap"])

    def test_payment_delay_changes_before_after_cashflow(self):
        result = self.analyze(scenario={"payment_delay_days": 30})
        changed = [
            row for row in result["finance"]["cashflow"]
            if row["baseline_closing_cash"] != row["scenario_closing_cash"]
        ]
        self.assertGreaterEqual(len(changed), 1)

    def test_liquidity_hard_gate_uses_three_coverage_bands_independent_of_margin(self):
        """The same high-margin contract is evaluated at all funding bands."""

        def at_coverage(coverage: float):
            sheets = deepcopy(self.pack.sheets)
            for order in sheets["06_ORDERS"]:
                if order.get("contract_id") == "CON-004":
                    order["estimated_cost"] = float(order["order_revenue"]) * 0.60
            probe_pack = TeamPack(sheets, "coverage-probe.xlsx", "coverageprobe", list(self.pack.sheet_names))
            probe = DecisionEngine(probe_pack).analyze(
                {
                    "contract_id": "CON-004",
                    "scenario": {},
                    "evidence": {
                        "contract_signed": True,
                        "receivable_aging": True,
                        "capacity_plan": True,
                        "suspicious_txn_reviewed": False,
                    },
                }
            )
            need = probe["finance"]["immediate_liquidity_need"]
            working_capital = next(
                row for row in sheets["10_CREDIT_PROFILE"]
                if row.get("credit_case_id") == "CR-001"
            )
            working_capital["requested_amount"] = need * coverage
            pack = TeamPack(sheets, f"coverage-{coverage}.xlsx", f"coverage{coverage}", list(self.pack.sheet_names))
            return DecisionEngine(pack).analyze(
                {
                    "contract_id": "CON-004",
                    "scenario": {},
                    "evidence": {
                        "contract_signed": True,
                        "receivable_aging": True,
                        "capacity_plan": True,
                        "suspicious_txn_reviewed": False,
                    },
                }
            )

        below_80 = at_coverage(0.79)
        between_80_and_100 = at_coverage(0.90)
        at_least_100 = at_coverage(1.05)

        self.assertLess(below_80["finance"]["funding_coverage_ratio"], 0.80)
        self.assertEqual(below_80["decision"]["decision_type"], "REJECT")
        self.assertGreater(below_80["finance"]["gross_margin"], below_80["finance"]["target_gross_margin"])

        self.assertGreaterEqual(between_80_and_100["finance"]["funding_coverage_ratio"], 0.80)
        self.assertLess(between_80_and_100["finance"]["funding_coverage_ratio"], 1.0)
        self.assertEqual(between_80_and_100["decision"]["decision_type"], "NEED REVIEW")

        self.assertGreaterEqual(at_least_100["finance"]["funding_coverage_ratio"], 1.0)
        self.assertIn(at_least_100["decision"]["decision_type"], {"ACCEPT", "CONDITIONAL ACCEPT"})

    def test_openai_input_is_masked(self):
        result = self.analyze()
        serialized = json.dumps(result["openai"]["input_masked"], ensure_ascii=False)
        self.assertNotIn("CUS-005", serialized)
        self.assertNotIn("OPC_MAIN", serialized)
        self.assertIn("TOK-CUS-A91F", serialized)

    def test_openai_guardrail_blocks_stronger_recommendation(self):
        output = {
            "recommendation": "ACCEPT",
            "three_reasons": ["a", "b", "c"],
            "human_confirmation_point": "Founder phải xác nhận nghĩa vụ tài chính trước khi gửi.",
            "risk_explanation": "risk",
            "data_quality_comment": "data",
        }
        checks = validate_openai_output(output, "CONDITIONAL ACCEPT")
        self.assertFalse(next(item for item in checks if item["check"] == "rule_engine_upper_bound")["passed"])

    def test_finance_separates_gap_guarantee_and_headroom(self):
        result = self.analyze()
        finance = result["finance"]
        self.assertAlmostEqual(finance["order_coverage_ratio"], 3.1 / 4.2, places=6)
        self.assertEqual(finance["guarantee_collateral_encumbrance"], 84_000_000)
        self.assertAlmostEqual(finance["guarantee_fee_estimate"], 4_183_890.41, places=2)
        self.assertAlmostEqual(
            finance["immediate_liquidity_need"],
            finance["peak_funding_gap"] + finance["guarantee_cash_impact"],
            places=2,
        )
        self.assertAlmostEqual(
            finance["liquidity_headroom"],
            finance["potential_funding_capacity"] - finance["immediate_liquidity_need"],
            places=2,
        )
        self.assertAlmostEqual(
            finance["funding_coverage_ratio"],
            finance["potential_funding_capacity"] / finance["immediate_liquidity_need"],
            places=6,
        )

    def test_cashflow_is_not_double_counted_in_baseline(self):
        result = self.analyze()
        for row in result["finance"]["cashflow"]:
            self.assertEqual(row["baseline_closing_cash"], row["scenario_closing_cash"])

    def test_crisis_flow_rejects_when_margin_and_liquidity_fail(self):
        result = self.analyze(scenario={"cost_increase_pct": 15, "payment_delay_days": 30})
        self.assertEqual(result["decision"]["decision_type"], "REJECT")
        self.assertAlmostEqual(result["finance"]["gross_margin"], 0.126, places=6)
        self.assertEqual(
            result["finance"]["peak_funding_gap"],
            max(row["funding_gap"] for row in result["finance"]["contract_cashflow"]),
        )
        self.assertLess(result["finance"]["liquidity_headroom"], 0)

    def test_case_and_enterprise_risk_are_not_conflated(self):
        result = self.analyze()
        self.assertIn(result["risk"]["case_risk_level"], {"Low", "Medium", "High", "Critical"})
        self.assertEqual(result["risk"]["enterprise_risk_level"], "Critical")
        self.assertTrue(any(item["scope"] == "ENTERPRISE" for item in result["risk"]["alerts"]))

    def test_partnerx_is_ineligible_without_issued_invoice(self):
        result = self.analyze()
        partnerx = next(item for item in result["partner"]["options"] if item["option_id"] == "PARTNERX-FACTOR")
        self.assertEqual(partnerx["status"], "INELIGIBLE")
        self.assertEqual(partnerx["liquidity_amount"], 0)
        self.assertEqual(partnerx["provider"], "PartnerX")
        self.assertEqual(partnerx["presentation_label"], "ĐỐI TÁC GIẢ LẬP")

    def test_release_contains_exactly_one_canonical_workbook(self):
        workbooks = sorted(path.relative_to(ROOT).as_posix() for path in ROOT.rglob("*.xlsx"))
        self.assertEqual(workbooks, ["data/MISTalent2026_OPC_AgenticAI_TeamPack_v3.xlsx"])

    def test_external_incomplete_then_corrected_upload_transition(self):
        payload = {
            "contract_id": "CON-004",
            "scenario": {},
            "evidence": {
                "contract_signed": True,
                "receivable_aging": True,
                "capacity_plan": True,
                "suspicious_txn_reviewed": False,
            },
        }
        with tempfile.TemporaryDirectory(prefix="opc-founder-upload-") as temp_dir:
            external_missing = Path(temp_dir) / "Founder_CON004_missing.xlsx"
            external_corrected = Path(temp_dir) / "Founder_CON004_corrected.xlsx"
            create_external_copy_with_blanks(
                CANONICAL_TEAM_PACK,
                external_missing,
                [("06_ORDERS", "order_id", "ORD-006", "estimated_cost")],
            )
            shutil.copy2(CANONICAL_TEAM_PACK, external_corrected)

            incomplete = DecisionEngine(TeamPack.from_path(external_missing)).analyze(payload)
            blocking_sources = {item["source"] for item in incomplete["data_quality"]["blocking"]}
            self.assertEqual(incomplete["source"]["file_name"], external_missing.name)
            self.assertEqual(incomplete["decision"]["decision_type"], "NEED MORE DATA")
            self.assertEqual(incomplete["finance"]["cashflow_status"], "BLOCKED_BY_DATA")
            self.assertIn("06_ORDERS[ORD-006].estimated_cost", blocking_sources)
            self.assertTrue(
                any(
                    "06_ORDERS[ORD-006].estimated_cost" in item
                    for item in incomplete["finance"]["missing_data"]
                )
            )

            corrected = DecisionEngine(TeamPack.from_path(external_corrected)).analyze(payload)
            corrected_sources = {item["source"] for item in corrected["data_quality"]["blocking"]}
            self.assertEqual(corrected["source"]["file_name"], external_corrected.name)
            self.assertNotIn("06_ORDERS[ORD-006].estimated_cost", corrected_sources)
            self.assertEqual(corrected["finance"]["missing_data"], [])
            self.assertEqual(corrected["finance"]["cashflow_status"], "READY")
            self.assertNotEqual(corrected["decision"]["decision_type"], "NEED MORE DATA")

    def test_missing_contract_value_stays_blocked_until_teampack_is_reuploaded(self):
        payload = {
            "contract_id": "CON-004",
            "scenario": {},
            "evidence": {
                "contract_signed": True,
                "receivable_aging": True,
                "capacity_plan": True,
                "suspicious_txn_reviewed": False,
            },
        }
        with tempfile.TemporaryDirectory(prefix="opc-founder-upload-") as temp_dir:
            external_missing = Path(temp_dir) / "Founder_CON004_missing_value.xlsx"
            create_external_copy_with_blanks(
                CANONICAL_TEAM_PACK,
                external_missing,
                [("04_CONTRACTS", "contract_id", "CON-004", "contract_value")],
            )
            engine = DecisionEngine(TeamPack.from_path(external_missing))
            blocked = engine.analyze(payload)
            self.assertEqual(blocked["decision"]["decision_type"], "NEED MORE DATA")
            self.assertTrue(
                any(
                    item["source"] == "04_CONTRACTS[CON-004].contract_value"
                    for item in blocked["finance"]["missing_fields"]
                )
            )
            spoofed = engine.analyze({**payload, "corrections": {"contract_value": 4_200_000_000}})
            self.assertEqual(spoofed["decision"]["decision_type"], "NEED MORE DATA")
            self.assertEqual(spoofed["finance"]["contract_value"], 0)
            self.assertNotIn("corrections_applied", spoofed)

    def test_contract_cashflow_is_unique_and_grounded_for_each_contract(self):
        signatures = set()
        for contract in self.pack.contracts():
            result = self.analyze(contract_id=contract["contract_id"])
            profile = result["finance"]["contract_cashflow"]
            self.assertTrue(profile)
            self.assertTrue(all(row["contract_id"] == contract["contract_id"] for row in profile))
            self.assertTrue(all(row["sources"] or (row["cash_in"] == 0 and row["cash_out"] == 0) for row in profile))
            signatures.add(tuple((row["month"], row["cash_in"], row["cash_out"], row["cumulative_cashflow"]) for row in profile))
        self.assertEqual(len(signatures), len(self.pack.contracts()))

    def test_multi_invoice_cashflow_keeps_all_milestones_and_one_unbilled_residual(self):
        sheets = deepcopy(self.pack.sheets)
        first = next(
            row for row in sheets["07_INVOICES"] if row.get("invoice_id") == "INV-006"
        )
        first.update(
            {
                "status": "Open",
                "invoice_amount": 300_000_000,
                "due_date": "2026-10-15",
                "paid_date": None,
            }
        )
        sheets["07_INVOICES"].append(
            {
                "invoice_id": "INV-006B",
                "order_id": "ORD-007",
                "customer_id": "CUS-008",
                "issue_date": "2026-10-20",
                "due_date": "2026-11-15",
                "status": "Open",
                "invoice_amount": 200_000_000,
                "paid_date": None,
            }
        )
        # A large invoice from another contract must not leak into CON-005.
        sheets["07_INVOICES"].append(
            {
                "invoice_id": "INV-CROSS-CONTRACT",
                "order_id": "ORD-005",
                "customer_id": "CUS-005",
                "issue_date": "2026-09-01",
                "due_date": "2026-09-30",
                "status": "Open",
                "invoice_amount": 9_999_000_000,
                "paid_date": None,
            }
        )
        pack = TeamPack(sheets, "multi-invoice.xlsx", "multiinvoice", list(self.pack.sheet_names))
        result = DecisionEngine(pack).analyze(
            {
                "contract_id": "CON-005",
                "scenario": {"payment_delay_days": 30},
                "evidence": {
                    "contract_signed": True,
                    "receivable_aging": True,
                    "capacity_plan": True,
                    "suspicious_txn_reviewed": False,
                },
            }
        )
        finance = result["finance"]
        profile = finance["contract_cashflow"]
        by_month = {row["month"]: row for row in profile}
        sources = {source for row in profile for source in row["sources"]}
        bases = {basis for row in profile for basis in row["collection_basis"]}

        self.assertEqual(finance["linked_invoice_count"], 2)
        self.assertEqual(sum(row["baseline_cash_in"] for row in profile), 800_000_000)
        self.assertEqual(by_month["2026-09"]["baseline_cash_in"], 300_000_000)
        self.assertEqual(by_month["2026-10"]["baseline_cash_in"], 300_000_000)
        self.assertEqual(by_month["2026-11"]["baseline_cash_in"], 200_000_000)
        self.assertEqual(by_month["2026-09"]["cash_in"], 300_000_000)
        self.assertEqual(by_month["2026-10"]["cash_in"], 0)
        self.assertEqual(by_month["2026-11"]["cash_in"], 500_000_000)
        self.assertIn("07_INVOICES[INV-006].invoice_amount", sources)
        self.assertIn("07_INVOICES[INV-006B].invoice_amount", sources)
        self.assertIn("06_ORDERS[ORD-007].order_revenue", sources)
        self.assertNotIn("07_INVOICES[INV-CROSS-CONTRACT].invoice_amount", sources)
        self.assertTrue(
            any("UNBILLED_RESIDUAL_AFTER_INVOICES[500000000]" in basis for basis in bases)
        )
        self.assertTrue(
            any("INV-006:INVOICE_DUE_FORECAST:DELAYED_1_MONTH" in basis for basis in bases)
        )

    def test_multi_invoice_cashflow_uses_actual_overage_without_order_residual(self):
        sheets = deepcopy(self.pack.sheets)
        sheets["07_INVOICES"].append(
            {
                "invoice_id": "INV-006B",
                "order_id": "ORD-007",
                "customer_id": "CUS-008",
                "issue_date": "2026-10-20",
                "due_date": "2026-11-15",
                "status": "Open",
                "invoice_amount": 200_000_000,
                "paid_date": None,
            }
        )
        pack = TeamPack(sheets, "over-invoiced.xlsx", "overinvoice", list(self.pack.sheet_names))
        result = DecisionEngine(pack).analyze(
            {
                "contract_id": "CON-005",
                "scenario": {},
                "evidence": {
                    "contract_signed": True,
                    "receivable_aging": True,
                    "capacity_plan": True,
                    "suspicious_txn_reviewed": False,
                },
            }
        )
        profile = result["finance"]["contract_cashflow"]
        sources = {source for row in profile for source in row["sources"]}

        self.assertEqual(result["finance"]["linked_invoice_count"], 2)
        self.assertEqual(sum(row["baseline_cash_in"] for row in profile), 1_000_000_000)
        self.assertIn("07_INVOICES[INV-006].invoice_amount", sources)
        self.assertIn("07_INVOICES[INV-006B].invoice_amount", sources)
        self.assertNotIn("06_ORDERS[ORD-007].order_revenue", sources)

    def test_all_existing_contracts_use_contract_specific_credit_mapping_without_global_fallback(self):
        contracts = self.pack.contracts()
        self.assertEqual([row["contract_id"] for row in contracts], [
            "CON-001", "CON-002", "CON-003", "CON-004", "CON-005"
        ])
        funding_signatures = set()

        for contract in contracts:
            contract_id = contract["contract_id"]
            result = self.analyze(contract_id=contract_id)
            finance = result["finance"]
            case_ids = set(finance["credit_case_ids"])
            mappings = finance["credit_mapping"]
            mapping_ids = {item["credit_case_id"] for item in mappings}

            self.assertEqual(case_ids, mapping_ids)
            self.assertTrue(all(item["mapping_source"] for item in mappings))
            self.assertTrue(
                all(row["contract_id"] == contract_id for row in finance["contract_cashflow"])
            )

            if not case_ids:
                self.assertEqual(
                    finance["potential_funding_capacity"],
                    finance["factoring_capacity"],
                    "An unmapped contract may use its own eligible invoices, not another contract's credit case",
                )
                self.assertEqual(result["decision"]["decision_type"], "NEED MORE DATA")
                self.assertTrue(
                    any(
                        item["source"] == f"10_CREDIT_PROFILE[contract_id={contract_id}]"
                        for item in result["data_quality"]["blocking"]
                    )
                )

            if contract_id != "CON-004":
                self.assertFalse(
                    finance["working_capital_request"] == 950_000_000
                    and finance["performance_bond_request"] == 420_000_000,
                    f"{contract_id} inherited CON-004's credit and bond cases",
                )

            funding_signatures.add(
                (
                    tuple(sorted(case_ids)),
                    finance["working_capital_request"],
                    finance["performance_bond_request"],
                    finance["potential_funding_capacity"],
                )
            )

        self.assertGreater(
            len(funding_signatures),
            1,
            "All contracts still share one global credit/bond fallback",
        )

    def test_scenario_fingerprint_changes_with_scenario(self):
        baseline = self.analyze()
        crisis = self.analyze(scenario={"cost_increase_pct": 15, "payment_delay_days": 30})
        self.assertNotEqual(
            baseline["openai"]["input_masked"]["scenario_fingerprint"],
            crisis["openai"]["input_masked"]["scenario_fingerprint"],
        )

    def test_challenger_fingerprint_is_bound_to_each_unique_trace(self):
        payload = {
            "contract_id": "CON-004",
            "scenario": {},
            "evidence": {
                "contract_signed": True,
                "receivable_aging": True,
                "capacity_plan": True,
                "suspicious_txn_reviewed": False,
            },
        }
        run_a = DecisionEngine(
            self.pack,
            trace_id="TRACE-20260720-190000-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        ).analyze(payload)
        run_b = DecisionEngine(
            self.pack,
            trace_id="TRACE-20260720-190000-BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
        ).analyze(payload)
        input_a = run_a["openai"]["input_masked"]
        input_b = run_b["openai"]["input_masked"]

        self.assertNotEqual(input_a["run_token"], input_b["run_token"])
        self.assertNotEqual(input_a["scenario_fingerprint"], input_b["scenario_fingerprint"])

        stale_output = {
            "scenario_fingerprint": input_a["scenario_fingerprint"],
            "scenario_echo": deepcopy(input_a["scenario"]),
            "evidence_echo": {
                "gross_margin": input_a["financial_snapshot"]["gross_margin"],
                "peak_funding_gap_vnd": input_a["financial_snapshot"]["peak_funding_gap_vnd"],
                "case_risk_level": input_a["risk_report"]["case_risk_level"],
                "enterprise_risk_level": input_a["risk_report"]["enterprise_risk_level"],
            },
            "recommendation": run_a["decision"]["decision_type"],
            "three_reasons": ["a", "b", "c"],
            "human_confirmation_point": "Founder xác nhận đầy đủ điều kiện trước precheck.",
            "risk_explanation": "Chỉ dùng dữ kiện trong masked input.",
            "data_quality_comment": "Không có trường bắt buộc bị thiếu.",
        }
        checks = validate_openai_output(
            stale_output,
            run_b["decision"]["decision_type"],
            input_b,
        )
        self.assertFalse(
            next(item for item in checks if item["check"] == "scenario_fingerprint_match")["passed"]
        )

    def test_contract_only_row_is_listed_but_blocked_with_exact_missing_data(self):
        sheets = deepcopy(self.pack.sheets)
        sheets["04_CONTRACTS"].append(
            {
                "contract_id": "CON-006",
                "customer_id": "CUS-099",
                "start_date": "2026-08-01",
                "end_date": "2027-02-01",
                "status": "Draft",
                "description": "New regional rollout",
                "contract_value": 2_000_000_000,
                "gross_margin": 0.25,
                "payment_terms": "Milestone payment",
            }
        )
        pack = TeamPack(sheets, "contract-only.xlsx", "contractonly", list(self.pack.sheet_names))
        from app import AppState

        catalog = AppState._contract_catalog(pack)
        result = DecisionEngine(pack).analyze(
            {
                "contract_id": "CON-006",
                "scenario": {},
                "evidence": {
                    "contract_signed": True,
                    "receivable_aging": True,
                    "capacity_plan": True,
                    "suspicious_txn_reviewed": False,
                },
            }
        )
        self.assertIn("CON-006", [row["contract_id"] for row in pack.contracts()])
        self.assertIn("CON-006", [row["contract_id"] for row in catalog])
        self.assertEqual(next(row for row in catalog if row["contract_id"] == "CON-006")["display_name"], "CON-006- CUS-099")
        self.assertEqual(result["decision"]["decision_type"], "NEED MORE DATA")
        self.assertEqual(result["finance"]["cashflow_status"], "BLOCKED_BY_DATA")
        self.assertTrue(any("03_CUSTOMERS[CUS-099]" in item for item in result["finance"]["missing_data"]))
        self.assertTrue(any("06_ORDERS[contract_id=CON-006]" in item for item in result["finance"]["missing_data"]))
        self.assertTrue(any("10_CREDIT_PROFILE[contract_id=CON-006]" in item for item in result["finance"]["missing_data"]))
        self.assertEqual(result["finance"]["credit_case_ids"], [])
        self.assertEqual(result["finance"]["potential_funding_capacity"], 0)
        self.assertEqual(result["openai"]["input_masked"]["business_opportunity"]["contract_ref"], "CON-***006")
        self.assertNotEqual(result["openai"]["input_masked"]["business_opportunity"]["customer_token"], "TOK-CUS-A91F")

    def test_new_contract_runs_when_linked_customer_order_and_invoice_exist(self):
        sheets = deepcopy(self.pack.sheets)
        sheets["03_CUSTOMERS"].append(
            {
                "customer_id": "CUS-006",
                "customer_name": "Khách hàng thử nghiệm",
                "customer_type": "SME",
                "province": "Hà Nội",
                "industry": "Technology",
                "strategic_value": "Medium",
                "revenue_model": "Project",
                "payment_reliability": 0.72,
            }
        )
        sheets["04_CONTRACTS"].append(
            {
                "contract_id": "CON-006",
                "customer_id": "CUS-006",
                "start_date": "2026-08-01",
                "end_date": "2027-02-01",
                "status": "Draft",
                "description": "New regional rollout",
                "contract_value": 2_000_000_000,
                "gross_margin": 0.25,
                "payment_terms": "Milestone payment",
            }
        )
        sheets["06_ORDERS"].append(
            {
                "order_id": "ORD-006X",
                "contract_id": "CON-006",
                "customer_id": "CUS-006",
                "order_date": "2026-08-02",
                "due_date": "2026-08-20",
                "status": "Planned",
                "service_id": "SVC-004",
                "order_revenue": 1_500_000_000,
                "estimated_cost": 1_050_000_000,
            }
        )
        sheets["07_INVOICES"].append(
            {
                "invoice_id": "INV-006X",
                "order_id": "ORD-006X",
                "customer_id": "CUS-006",
                "issue_date": "2026-08-20",
                "due_date": "2026-09-15",
                "status": "Open",
                "invoice_amount": 600_000_000,
            }
        )
        sheets["10_CREDIT_PROFILE"].append(
            {
                "credit_case_id": "CR-006-WC",
                "company_id": "OPC-001",
                "contract_id": "CON-006",
                "request_type": "Working capital line",
                "requested_amount": 1_200_000_000,
                "tenor": "6 months",
                "collateral_or_basis": "CON-006 receivables",
                "eligibility_score": 0.75,
                "precheck_note": "Synthetic linked-contract regression case",
                "approval_status": "Human approval required",
                "bank_product_id": "BANKPROD-004",
            }
        )
        pack = TeamPack(sheets, "linked-contract.xlsx", "linkedcontract", list(self.pack.sheet_names))
        result = DecisionEngine(pack).analyze(
            {
                "contract_id": "CON-006",
                "scenario": {},
                "evidence": {
                    "contract_signed": True,
                    "receivable_aging": True,
                    "capacity_plan": True,
                    "suspicious_txn_reviewed": False,
                },
            }
        )
        self.assertEqual(result["finance"]["missing_data"], [])
        self.assertEqual(result["finance"]["cashflow_status"], "READY")
        self.assertNotEqual(result["decision"]["decision_type"], "NEED MORE DATA")
        self.assertEqual(result["contract"]["contract_ref_masked"], "CON-***006")
        self.assertEqual(result["finance"]["credit_case_ids"], ["CR-006-WC"])
        self.assertEqual(result["finance"]["working_capital_request"], 1_200_000_000)
        self.assertEqual(result["finance"]["performance_bond_request"], 0)
        self.assertEqual(
            result["finance"]["credit_mapping"][0]["mapping_source"],
            "10_CREDIT_PROFILE[CR-006-WC].contract_id",
        )

    def test_con003_reports_every_missing_order_cell_separately(self):
        sheets = deepcopy(self.pack.sheets)
        target = next(row for row in sheets["06_ORDERS"] if row.get("order_id") == "ORD-008")
        target["order_revenue"] = None
        target["estimated_cost"] = None
        pack = TeamPack(sheets, "con003-two-fields.xlsx", "con003missing", list(self.pack.sheet_names))
        result = DecisionEngine(pack).analyze(
            {
                "contract_id": "CON-003",
                "scenario": {},
                "evidence": {
                    "contract_signed": True,
                    "receivable_aging": True,
                    "capacity_plan": True,
                    "suspicious_txn_reviewed": False,
                },
            }
        )
        sources = {item["source"] for item in result["data_quality"]["blocking"]}
        self.assertIn("06_ORDERS[ORD-008].order_revenue", sources)
        self.assertIn("06_ORDERS[ORD-008].estimated_cost", sources)
        self.assertEqual(sum(source.startswith("06_ORDERS[ORD-008]") for source in sources), 2)
        self.assertEqual(result["decision"]["decision_type"], "NEED MORE DATA")

    def test_margin_reason_wording_distinguishes_below_equal_and_above_target(self):
        expected_by_margin = {
            0.24: "thấp hơn mục tiêu",
            0.28: "bằng mục tiêu",
            0.40: "cao hơn mục tiêu",
        }
        for requested_margin, expected_phrase in expected_by_margin.items():
            with self.subTest(requested_margin=requested_margin):
                sheets = deepcopy(self.pack.sheets)
                orders = [
                    row for row in sheets["06_ORDERS"] if row.get("contract_id") == "CON-004"
                ]
                for row in orders:
                    row["estimated_cost"] = float(row["order_revenue"]) * (1 - requested_margin)
                pack = TeamPack(
                    sheets,
                    f"margin-{requested_margin:.2f}.xlsx",
                    f"margin{requested_margin:.2f}",
                    list(self.pack.sheet_names),
                )
                result = DecisionEngine(pack).analyze(
                    {
                        "contract_id": "CON-004",
                        "scenario": {},
                        "evidence": {
                            "contract_signed": True,
                            "receivable_aging": True,
                            "capacity_plan": True,
                            "suspicious_txn_reviewed": False,
                        },
                    }
                )
                reason_text = " ".join(result["decision"]["three_reasons"]).lower()
                self.assertAlmostEqual(result["finance"]["gross_margin"], requested_margin, places=6)
                self.assertIn(expected_phrase, reason_text)
                for wrong_phrase in set(expected_by_margin.values()) - {expected_phrase}:
                    self.assertNotIn(wrong_phrase, reason_text)

    def test_data_quality_collects_issues_across_multiple_sheets(self):
        sheets = deepcopy(self.pack.sheets)
        next(row for row in sheets["03_CUSTOMERS"] if row.get("customer_id") == "CUS-004")["province"] = None
        sheets["09_CASHFLOW"][0]["projected_closing_cash"] = None
        sheets["13_RISK_RULES"][0]["required_action"] = None
        pack = TeamPack(sheets, "multi-sheet-missing.xlsx", "multisheet", list(self.pack.sheet_names))
        result = DecisionEngine(pack).analyze(
            {
                "contract_id": "CON-003",
                "scenario": {},
                "evidence": {
                    "contract_signed": True,
                    "receivable_aging": True,
                    "capacity_plan": True,
                    "suspicious_txn_reviewed": False,
                },
            }
        )
        issues = result["data_quality"]["issues"]
        self.assertTrue(any(item["sheet"] == "03_CUSTOMERS" and item["level"] == "WARNING" for item in issues))
        self.assertTrue(any(item["sheet"] == "09_CASHFLOW" and item["level"] == "BLOCKING" for item in issues))
        self.assertTrue(any(item["sheet"] == "13_RISK_RULES" and item["level"] == "BLOCKING" for item in issues))
        self.assertGreaterEqual(result["data_quality"]["affected_sheet_count"], 3)
        self.assertEqual(result["decision"]["decision_type"], "NEED MORE DATA")

    def test_openai_echo_guardrails_accept_exact_current_run(self):
        result = self.analyze()
        expected = result["openai"]["input_masked"]
        output = {
            "scenario_fingerprint": expected["scenario_fingerprint"],
            "scenario_echo": deepcopy(expected["scenario"]),
            "evidence_echo": {
                "gross_margin": expected["financial_snapshot"]["gross_margin"],
                "peak_funding_gap_vnd": expected["financial_snapshot"]["peak_funding_gap_vnd"],
                "case_risk_level": expected["risk_report"]["case_risk_level"],
                "enterprise_risk_level": expected["risk_report"]["enterprise_risk_level"],
            },
            "recommendation": result["decision"]["decision_type"],
            "three_reasons": ["a", "b", "c"],
            "human_confirmation_point": "Founder xác nhận đầy đủ các điều kiện kiểm soát trước precheck.",
            "risk_explanation": "Chỉ sử dụng dữ kiện trong masked input.",
            "data_quality_comment": "Không có trường bắt buộc bị thiếu.",
        }
        checks = validate_openai_output(output, result["decision"]["decision_type"], expected)
        self.assertTrue(all(item["passed"] for item in checks))

    def test_openai_echo_guardrails_block_stale_scenario(self):
        result = self.analyze()
        expected = result["openai"]["input_masked"]
        output = {
            "scenario_fingerprint": "stale-run",
            "scenario_echo": {**expected["scenario"], "cost_increase_pct": 15},
            "evidence_echo": {
                "gross_margin": 0.126,
                "peak_funding_gap_vnd": 1_800_000_000,
                "case_risk_level": "High",
                "enterprise_risk_level": "Critical",
            },
            "recommendation": result["decision"]["decision_type"],
            "three_reasons": ["a", "b", "c"],
            "human_confirmation_point": "Founder xác nhận đầy đủ các điều kiện kiểm soát trước precheck.",
            "risk_explanation": "Nội dung của lượt chạy cũ.",
            "data_quality_comment": "stale",
        }
        checks = validate_openai_output(output, result["decision"]["decision_type"], expected)
        self.assertFalse(next(item for item in checks if item["check"] == "scenario_fingerprint_match")["passed"])
        self.assertFalse(next(item for item in checks if item["check"] == "scenario_values_match")["passed"])
        self.assertFalse(next(item for item in checks if item["check"] == "financial_risk_echo_match")["passed"])

    def test_decision_card_always_has_exactly_three_reasons(self):
        for result in (
            self.analyze(),
            self.analyze(scenario={"cost_increase_pct": 15, "payment_delay_days": 30}),
            self.analyze(evidence={"contract_signed": False, "receivable_aging": False, "capacity_plan": False}),
        ):
            self.assertEqual(len(result["decision"]["three_reasons"]), 3)


if __name__ == "__main__":
    unittest.main()
