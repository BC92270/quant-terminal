"""Unit and evidence-contract tests for Quantum Lab V3.8."""

from __future__ import annotations

import copy
import unittest

from .phase3_v36_algorithmic_reduction import canonical_json_sha256
from .phase3_v38_elementary_admission import (
    N40_SEEDS,
    SELECTED_MODEL,
    apply_elementary_sequence,
    build_v38_artifact,
    ccx_template,
    compile_elementary_layer,
    crx_template,
    load_v38_artifact,
    load_v38_spec,
    lower_pattern_gate,
    validate_v38_artifact,
)
from .phase3_v38_validation import run_v38_validation


class ElementaryAdmissionV38Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact = build_v38_artifact()
        cls.validation = run_v38_validation()

    def test_preregistered_spec_is_authenticated(self) -> None:
        spec = load_v38_spec()
        self.assertEqual(spec["counting_contract"]["selected_decomposition_model"], SELECTED_MODEL)
        self.assertEqual(spec["n40_admission_contract"]["budget_cnot"], 2_500_000)

    def test_ccx_template_is_exact(self) -> None:
        gates = ccx_template(0, 1, 2)
        self.assertEqual(sum(gate["kind"] == "CX" for gate in gates), 6)
        for basis in range(8):
            expected = basis ^ 4 if basis & 1 and basis & 2 else basis
            self.assertLessEqual(
                max(
                    abs(value - ({expected: 1.0 + 0.0j}).get(index, 0.0j))
                    for index, value in apply_elementary_sequence({basis: 1.0 + 0.0j}, gates, 0.0).items()
                ),
                1.0e-12,
            )

    def test_controlled_rx_template_is_two_cnot(self) -> None:
        gates = crx_template(0, 1, 2.0)
        self.assertEqual(sum(gate["kind"] == "CX" for gate in gates), 2)
        self.assertEqual(sum(gate["kind"] != "CX" for gate in gates), 4)

    def test_pattern_lowering_uses_clean_ancilla_ladder(self) -> None:
        logical = {
            "kind": "PATTERN_MCRX",
            "target": 9,
            "controls": [{"qubit": index, "value": index % 2} for index in range(9)],
            "angle_multiplier": 2,
        }
        lowered = lower_pattern_gate(logical)
        self.assertEqual(lowered["clean_ancilla_qubits"], 8)
        self.assertEqual(lowered["cnot_count"], 98)

    def test_elementary_resource_ledger_is_exact(self) -> None:
        ledger = compile_elementary_layer()
        self.assertEqual(ledger["logical_occurrence_count"], 40)
        self.assertEqual(ledger["cnot_count"], 3_632)
        self.assertEqual(ledger["one_qubit_gate_count"], 5_920)
        self.assertEqual(ledger["maximum_total_qubits"], 18)

    def test_exhaustive_elementary_validation_passes(self) -> None:
        evidence = self.artifact["elementary_validation"]
        self.assertTrue(evidence["passed"])
        self.assertEqual(evidence["primitive_basis_beta_cases_checked"], 49_152)
        self.assertEqual(evidence["clean_ancilla_failures"], 0)

    def test_n40_seed_contract_is_complete_but_compiler_is_absent(self) -> None:
        admission = self.artifact["n40_admission"]
        self.assertEqual(tuple(row["seed"] for row in admission["rows"]), N40_SEEDS)
        self.assertEqual(admission["coverage_counts_out_of_8"]["seven_constraint_parent_evidence"], 8)
        self.assertEqual(admission["coverage_counts_out_of_8"]["scalable_reversible_ir"], 0)

    def test_n40_cost_is_not_imputed(self) -> None:
        admission = self.artifact["n40_admission"]
        self.assertEqual(admission["maximum_selected_model_cnot"], "NOT_ESTIMATED")
        self.assertEqual(admission["budget_gate"], "NOT_EVALUATED")
        self.assertEqual(admission["admission_decision"], "BLOCKED_INCOMPLETE_REVERSIBLE_IR")

    def test_historical_negative_result_is_preserved(self) -> None:
        for row in self.artifact["n40_admission"]["rows"]:
            self.assertGreater(row["historical_v34_selected_model_cnot"], 2_500_000)
            self.assertIn("NONCOMPARABLE_PARENT", row["historical_v34_status"])

    def test_artifact_nested_tamper_is_rejected_even_when_rehashed(self) -> None:
        tampered = copy.deepcopy(self.artifact)
        tampered["n40_admission"]["rows"][0]["selected_model_cnot"] = 1
        tampered["artifact_sha256"] = canonical_json_sha256(
            {key: value for key, value in tampered.items() if key != "artifact_sha256"}
        )
        self.assertFalse(validate_v38_artifact(tampered)["valid"])

    def test_sealed_artifact_is_exact(self) -> None:
        sealed, report = load_v38_artifact()
        self.assertTrue(report["valid"])
        self.assertEqual(sealed, self.artifact)

    def test_independent_validation_ladder_passes(self) -> None:
        self.assertTrue(self.validation["overall_pass"])
        self.assertEqual(len(self.validation["checks"]), 15)


if __name__ == "__main__":
    unittest.main()
