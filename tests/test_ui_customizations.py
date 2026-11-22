import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RequestedUiCustomizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        cls.styles = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")

    def test_contract_selector_has_no_sheet_count_hint(self):
        self.assertNotIn('id="contractCount"', self.index)
        self.assertNotIn('$("#contractCount")', self.script)
        self.assertNotRegex(self.index + self.script, r"\d+\s+từ\s+04_CONTRACTS")

    def test_founder_evidence_starts_unchecked_and_resets_with_context(self):
        self.assertIn("Xác nhận hồ sơ", self.index)
        for element_id in ("contractSigned", "agingEvidence", "capacityPlan", "txnReviewed"):
            tag = re.search(rf'<input\s+id="{element_id}"[^>]*>', self.index)
            self.assertIsNotNone(tag)
            self.assertNotRegex(tag.group(0), r"\schecked(?:\s|>|=)")
            self.assertIn(f'"#{element_id}"', self.script)
        self.assertIn("$(selector).checked = false;", self.script)

    def test_cashflow_chart_uses_vietnamese_labels_and_tooltips(self):
        combined = self.index + self.script
        for label in (
            "Dòng tiền hợp đồng",
            "Dòng tiền tích lũy",
            "Vùng thiếu hụt vốn",
            "Điểm hòa vốn",
            "CẦN BỔ SUNG DỮ LIỆU",
            "tích lũy",
            "triệu · thu",
            "triệu · chi",
        ):
            self.assertIn(label, combined)
        for legacy in ("Contract Cashflow", "Cumulative cash", "Break-even", "· cumulative "):
            self.assertNotIn(legacy, combined)

    def test_cashflow_chart_keeps_dynamic_contract_context_without_axis_titles(self):
        combined = self.index + self.script
        self.assertIn("${result.contract.contract_id} · Đơn hàng (06) + Hóa đơn (07) · triệu VND", self.script)
        self.assertIn("renderChart(finance.contract_cashflow, finance);", self.script)
        for removed_label in ("Số dư tiền cuối tháng", "SỐ DƯ TIỀN CUỐI THÁNG", "Trục X", "Trục Y"):
            self.assertNotIn(removed_label, combined)
        self.assertIn('class="cashflow-deficit-area"', self.script)
        self.assertIn('class="cashflow-break-even-line"', self.script)
        self.assertIn('class="chart-break-even-label"', self.script)
        self.assertIn('class="cashflow-point"', self.script)

    def test_reconciliation_ui_is_hidden_but_logic_is_retained(self):
        button = re.search(r'<button\s+id="openReconciliation"[^>]*>', self.index)
        self.assertIsNotNone(button)
        self.assertRegex(button.group(0), r"\shidden(?:\s|>|=)")
        self.assertIn(".reconciliation-open[hidden] { display: none !important; }", self.styles)
        self.assertIn('id="reconciliationDialog"', self.index)
        self.assertIn("renderReconciliation(result, appState.reconciliationFilter);", self.script)
        self.assertIn('$("#openReconciliation").addEventListener("click"', self.script)
        self.assertIn("transaction_reconciliation", self.script)


if __name__ == "__main__":
    unittest.main()
