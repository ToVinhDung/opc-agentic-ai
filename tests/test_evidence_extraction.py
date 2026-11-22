import unittest
from copy import deepcopy

from evidence_extraction import build_extraction_packet, validate_extraction_output


class StructuredEvidenceValidationTests(unittest.TestCase):
    def setUp(self):
        self.packet = build_extraction_packet(
            {
                "contract_id": "CON-004",
                "description": "20-province cooperative network rollout",
                "payment_terms": "Performance bond required",
            },
            [
                {
                    "order_id": "ORD-005",
                    "delivery_note": "Requires performance bond",
                },
                {
                    "order_id": "ORD-006",
                    "delivery_note": "Requires working capital",
                },
            ],
            "TRACE-TEST-RUN-A",
        )
        self.valid_output = {
            "contract_fingerprint": self.packet["contract_fingerprint"],
            "fields": {
                "performance_bond_required": {
                    "status": "SUPPORTED",
                    "value": True,
                    "confidence": 0.98,
                    "evidence": [
                        {"source_id": "SRC-002", "quote": "Performance bond required"}
                    ],
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
                    "confidence": 0.93,
                    "evidence": [],
                },
            },
        }

    def test_valid_con004_evidence_is_grounded_with_exact_lineage(self):
        result = validate_extraction_output(self.valid_output, self.packet)
        self.assertEqual(result["status"], "VALIDATED")
        evidence = result["validated_evidence"]
        self.assertTrue(evidence["performance_bond_required"]["value"])
        self.assertEqual(evidence["deployment_scope_provinces"]["value"], 20)
        self.assertEqual(
            evidence["performance_bond_required"]["evidence"][0]["source"],
            "04_CONTRACTS[CON-004].payment_terms",
        )

    def test_stale_fingerprint_is_blocked(self):
        output = deepcopy(self.valid_output)
        output["contract_fingerprint"] = "stale"
        result = validate_extraction_output(output, self.packet)
        self.assertEqual(result["status"], "BLOCKED_BY_VALIDATION")
        self.assertFalse(next(item for item in result["checks"] if item["check"] == "contract_fingerprint_match")["passed"])

    def test_identical_source_text_is_bound_to_each_run(self):
        contract = {
            "contract_id": "CON-004",
            "description": "20-province cooperative network rollout",
            "payment_terms": "Performance bond required",
        }
        orders = [{"order_id": "ORD-005", "delivery_note": "Requires performance bond"}]
        run_a = build_extraction_packet(contract, orders, "TRACE-RUN-A")
        run_b = build_extraction_packet(contract, orders, "TRACE-RUN-B")
        self.assertNotEqual(run_a["contract_fingerprint"], run_b["contract_fingerprint"])

        stale_output = deepcopy(self.valid_output)
        stale_output["contract_fingerprint"] = run_a["contract_fingerprint"]
        result = validate_extraction_output(stale_output, run_b)
        self.assertEqual(result["status"], "BLOCKED_BY_VALIDATION")
        fingerprint_check = next(
            item for item in result["checks"] if item["check"] == "contract_fingerprint_match"
        )
        self.assertFalse(fingerprint_check["passed"])

    def test_quote_not_present_in_source_is_blocked(self):
        output = deepcopy(self.valid_output)
        output["fields"]["performance_bond_required"]["evidence"][0]["quote"] = "Invented bond evidence"
        result = validate_extraction_output(output, self.packet)
        self.assertEqual(result["status"], "BLOCKED_BY_VALIDATION")

    def test_province_number_must_match_quote(self):
        output = deepcopy(self.valid_output)
        output["fields"]["deployment_scope_provinces"]["value"] = 21
        result = validate_extraction_output(output, self.packet)
        check = next(
            item for item in result["checks"]
            if item["check"] == "deployment_scope_provinces.semantic_match"
        )
        self.assertFalse(check["passed"])

    def test_supported_confidence_below_threshold_is_blocked(self):
        output = deepcopy(self.valid_output)
        output["fields"]["performance_bond_required"]["confidence"] = 0.79
        result = validate_extraction_output(output, self.packet)
        self.assertEqual(result["status"], "BLOCKED_BY_VALIDATION")

    def test_not_stated_cannot_carry_a_value_or_quote(self):
        output = deepcopy(self.valid_output)
        field = output["fields"]["collection_timing_signal"]
        field["value"] = "MONTHLY"
        field["evidence"] = [{"source_id": "SRC-002", "quote": "Performance bond required"}]
        result = validate_extraction_output(output, self.packet)
        self.assertEqual(result["status"], "BLOCKED_BY_VALIDATION")

    def _packet_and_output_for_text(self, text, field_name, value):
        packet = build_extraction_packet(
            {
                "contract_id": "CON-SEMANTIC",
                "description": text,
                "payment_terms": "",
            },
            [],
            f"TRACE-{field_name}-{text}",
        )
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
        fields[field_name] = {
            "status": "SUPPORTED",
            "value": value,
            "confidence": 0.95,
            "evidence": [{"source_id": "SRC-001", "quote": text}],
        }
        return packet, {
            "contract_fingerprint": packet["contract_fingerprint"],
            "fields": fields,
        }

    def test_bond_true_is_blocked_by_explicit_english_or_vietnamese_negation(self):
        for text in ("No performance bond is required", "Không yêu cầu bảo lãnh thực hiện"):
            with self.subTest(text=text):
                packet, output = self._packet_and_output_for_text(
                    text, "performance_bond_required", True
                )
                result = validate_extraction_output(output, packet)
                self.assertEqual(result["status"], "BLOCKED_BY_VALIDATION")

    def test_bond_true_cannot_crop_negation_from_source(self):
        packet, output = self._packet_and_output_for_text(
            "No performance bond is required", "performance_bond_required", True
        )
        output["fields"]["performance_bond_required"]["evidence"][0]["quote"] = (
            "performance bond"
        )
        self.assertEqual(
            validate_extraction_output(output, packet)["status"],
            "BLOCKED_BY_VALIDATION",
        )

    def test_bond_false_requires_and_accepts_explicit_negation(self):
        packet, output = self._packet_and_output_for_text(
            "No performance bond is required", "performance_bond_required", False
        )
        self.assertEqual(validate_extraction_output(output, packet)["status"], "VALIDATED")

        packet, output = self._packet_and_output_for_text(
            "Performance bond required", "performance_bond_required", False
        )
        self.assertEqual(validate_extraction_output(output, packet)["status"], "BLOCKED_BY_VALIDATION")

    def test_collection_enum_is_blocked_when_quote_negates_payment(self):
        cases = (
            ("Payment is not made monthly", "MONTHLY"),
            ("No payment after UAT", "AFTER_UAT"),
            ("Không thanh toán sau nghiệm thu", "AFTER_ACCEPTANCE"),
        )
        for text, signal in cases:
            with self.subTest(text=text, signal=signal):
                packet, output = self._packet_and_output_for_text(
                    text, "collection_timing_signal", signal
                )
                self.assertEqual(
                    validate_extraction_output(output, packet)["status"],
                    "BLOCKED_BY_VALIDATION",
                )

    def test_collection_signal_cannot_crop_negation_from_source(self):
        cases = (
            ("No payment after UAT", "payment after UAT", "AFTER_UAT"),
            ("Không thanh toán sau nghiệm thu", "thanh toán sau nghiệm thu", "AFTER_ACCEPTANCE"),
        )
        for source_text, cropped_quote, signal in cases:
            with self.subTest(source_text=source_text, signal=signal):
                packet, output = self._packet_and_output_for_text(
                    source_text, "collection_timing_signal", signal
                )
                output["fields"]["collection_timing_signal"]["evidence"][0]["quote"] = (
                    cropped_quote
                )
                self.assertEqual(
                    validate_extraction_output(output, packet)["status"],
                    "BLOCKED_BY_VALIDATION",
                )

    def test_other_explicit_requires_a_real_collection_timing_expression(self):
        packet, output = self._packet_and_output_for_text(
            "Payment terms are flexible", "collection_timing_signal", "OTHER_EXPLICIT"
        )
        self.assertEqual(validate_extraction_output(output, packet)["status"], "BLOCKED_BY_VALIDATION")

        packet, output = self._packet_and_output_for_text(
            "Payment due within 30 days", "collection_timing_signal", "OTHER_EXPLICIT"
        )
        self.assertEqual(validate_extraction_output(output, packet)["status"], "VALIDATED")

    def test_positive_uat_timing_requires_payment_context(self):
        packet, output = self._packet_and_output_for_text(
            "Payment after UAT", "collection_timing_signal", "AFTER_UAT"
        )
        self.assertEqual(validate_extraction_output(output, packet)["status"], "VALIDATED")

        packet, output = self._packet_and_output_for_text(
            "UAT acceptance completed", "collection_timing_signal", "AFTER_UAT"
        )
        self.assertEqual(validate_extraction_output(output, packet)["status"], "BLOCKED_BY_VALIDATION")


if __name__ == "__main__":
    unittest.main()
