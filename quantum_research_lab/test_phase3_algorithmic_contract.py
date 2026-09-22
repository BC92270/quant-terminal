"""Fast regression suite for the sealed V3.3 algorithmic contract."""

from __future__ import annotations

import copy
import unittest
from pathlib import Path

from .phase3_algorithmic_contract import (
    PROFILE_DUAL_GUARD,
    TOPOLOGY_COMPLETE,
    TOPOLOGY_RING,
    edge_schedule,
    load_algorithm_spec,
)
from .phase3_algorithmic_validation import (
    load_algorithmic_artifact,
    run_guard_symbolic_validation,
    run_small_n_validation,
    validate_algorithmic_artifact,
)
from .verify_phase3_v33 import verify_release_chain


ROOT = Path(__file__).resolve().parents[1]
V31_PATH = ROOT / "SEALED_EXACT_DYADIC_BANDS_ORACLE.json"
V32_PATH = (
    ROOT
    / "outputs"
    / "quantum_phase3"
    / "gate_compiler"
    / "SEALED_GATE_COMPILER_ARTIFACT.json"
)
V33_PATH = (
    ROOT
    / "outputs"
    / "quantum_phase3"
    / "algorithmic_contract"
    / "SEALED_FEASIBLE_SUBSPACE_MIXER_ARTIFACT.json"
)


class AlgorithmicContractFastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact, cls.integrity = load_algorithmic_artifact(V33_PATH)

    def test_spec_self_hash_and_boundaries(self) -> None:
        spec = load_algorithm_spec()
        self.assertEqual(len(spec["algorithm_contract_spec_sha"]), 20)
        self.assertFalse(spec["claim_boundary"]["hardware_executable"])
        self.assertFalse(spec["claim_boundary"]["qpu_submission_enabled"])

    def test_canonical_edge_schedules(self) -> None:
        self.assertEqual(len(edge_schedule(40, TOPOLOGY_RING)), 40)
        self.assertEqual(len(edge_schedule(40, TOPOLOGY_COMPLETE)), 780)
        self.assertEqual(len(set(edge_schedule(40, TOPOLOGY_COMPLETE))), 780)

    def test_symbolic_guard_contract(self) -> None:
        report = run_guard_symbolic_validation()
        self.assertTrue(report["passed"])
        self.assertEqual(report["truth_case_count"], 20)
        self.assertTrue(
            report["checks"]["optimized_out_of_contract_dirty_counterexample_retained"]
        )

    def test_small_n_unitary_and_invariance(self) -> None:
        report = run_small_n_validation()
        self.assertTrue(report["passed"])
        self.assertEqual(report["edge_action_cases"], 1800)
        self.assertTrue(report["checks"]["full_layer_unitary"])

    def test_sealed_artifact_integrity_and_negative_results(self) -> None:
        self.assertTrue(self.integrity["valid"])
        decisions = self.artifact["decisions"]
        self.assertTrue(decisions["ring_topology"].startswith("REJECTED"))
        self.assertEqual(decisions["complete_global_connectivity"], "INDETERMINATE")
        self.assertEqual(decisions["hardware_execution"], "BLOCKED · ZERO JOBS")

    def test_canonical_resource_accounting(self) -> None:
        ledger = self.artifact["resource_envelopes"]["ledgers"][
            f"{PROFILE_DUAL_GUARD}::{TOPOLOGY_COMPLETE}"
        ]
        self.assertEqual(ledger["oracle_calls"], 1562)
        self.assertEqual(ledger["maxima"]["logical_qubits_sequential_reuse"], 120)
        self.assertEqual(ledger["maxima"]["provider_neutral_gate_count"], 668963206)
        self.assertEqual(
            ledger["maxima"]["oracle_path_t_count_upper_subtotal"],
            174490676360,
        )

    def test_tamper_is_detected(self) -> None:
        tampered = copy.deepcopy(self.artifact)
        tampered["decisions"]["complete_global_connectivity"] = "PASS"
        report = validate_algorithmic_artifact(tampered)
        self.assertFalse(report["valid"])
        self.assertTrue(report["errors"])

        source_tamper = copy.deepcopy(self.artifact)
        source_tamper["validation"]["validation_source_sha256"] = "0" * 64
        source_report = validate_algorithmic_artifact(source_tamper)
        self.assertFalse(source_report["valid"])
        self.assertTrue(
            any("validation source" in error.lower() for error in source_report["errors"])
        )

    def test_end_to_end_release_verifier(self) -> None:
        report = verify_release_chain(V31_PATH, V32_PATH, V33_PATH)
        self.assertTrue(report["valid"], report)
        self.assertEqual(sum(report["checks"].values()), 13)

    def test_missing_parent_fails_closed_without_crashing(self) -> None:
        report = verify_release_chain(ROOT / "missing-v31.json", V32_PATH, V33_PATH)
        self.assertFalse(report["valid"])
        self.assertFalse(report["checks"]["v31_parent_raw_hash"])
        self.assertTrue(report["errors"])


if __name__ == "__main__":
    unittest.main()
