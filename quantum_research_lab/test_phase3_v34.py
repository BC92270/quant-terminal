"""Regression suite for the Quantum Lab V3.4 optimized/native layer."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from .phase3_gate_compiler import DOMAIN_EXACT_K, compile_seed_circuit
from .phase3_native_mixer import (
    elementary_c2xy_schedule,
    elementary_resource_per_edge,
    validate_c2xy_lowering,
)
from .phase3_optimized_oracle import (
    compile_optimized_seed,
    load_v34_spec,
)
from .phase3_v34_validation import (
    DEFAULT_SEAL_NAME,
    default_optimized_native_root,
    load_optimized_native_artifact,
    run_actual_constraint_boundary_validation,
    run_interval_identity_validation,
    validate_optimized_native_artifact,
)


ROOT = Path(__file__).resolve().parents[1]
V31_PATH = ROOT / "SEALED_EXACT_DYADIC_BANDS_ORACLE.json"
V34_PATH = ROOT / default_optimized_native_root() / DEFAULT_SEAL_NAME


class OptimizedNativeV34Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.v31 = json.loads(V31_PATH.read_text(encoding="utf-8"))
        cls.spec = load_v34_spec()
        cls.parent = cls.spec["parent_contract"]
        certificate = next(
            item for item in cls.v31["seed_certificates"] if int(item["seed"]) == 6607
        )
        cls.legacy = compile_seed_circuit(
            certificate,
            DOMAIN_EXACT_K,
            parent_dyadic_oracle_sha=cls.v31["dyadic_oracle_sha"],
            parent_artifact_file_sha256=cls.parent[
                "expected_parent_v31_raw_file_sha256"
            ],
        )
        cls.optimized = compile_optimized_seed(
            certificate,
            DOMAIN_EXACT_K,
            parent_v31_raw_file_sha256=cls.parent[
                "expected_parent_v31_raw_file_sha256"
            ],
            parent_v32_artifact_sha256=cls.parent[
                "expected_parent_v32_artifact_sha256"
            ],
            parent_v33_artifact_sha256=cls.parent[
                "expected_parent_v33_artifact_sha256"
            ],
            parent_v33_freeze_sha256=cls.parent[
                "expected_parent_v33_freeze_sha256"
            ],
        )

    def test_spec_self_hash_and_fail_closed_boundary(self) -> None:
        self.assertEqual(len(self.spec["v34_spec_sha256"]), 64)
        self.assertFalse(self.spec["claim_boundary"]["hardware_executable"])
        self.assertFalse(self.spec["claim_boundary"]["qpu_submission_enabled"])
        self.assertEqual(self.spec["claim_boundary"]["qpu_jobs_submitted"], 0)

    def test_interval_identity_exhaustive_widths_one_to_six(self) -> None:
        report = run_interval_identity_validation()
        self.assertTrue(report["passed"], report["first_failure"])
        self.assertEqual(report["total_basis_cases"], 610_104)

    def test_actual_seed_6607_boundaries(self) -> None:
        report = run_actual_constraint_boundary_validation([self.optimized])
        self.assertTrue(report["passed"])
        self.assertEqual(report["constraint_count"], 7)

    def test_constraint_ir_is_identical_and_two_qubits_are_removed(self) -> None:
        self.assertEqual(
            [item.as_dict() for item in self.legacy.constraints],
            [item.as_dict() for item in self.optimized.constraints],
        )
        self.assertEqual(self.legacy.logical_qubits, 119)
        self.assertEqual(self.optimized.logical_qubits, 117)
        self.assertNotIn("compare_ge", {item.name for item in self.optimized.registers})
        self.assertNotIn("compare_le", {item.name for item in self.optimized.registers})

    def test_elementary_c2xy_matrix_and_clean_scratch(self) -> None:
        report = validate_c2xy_lowering()
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["total_basis_angle_cases"], 96)
        self.assertLessEqual(report["maximum_amplitude_error"], 1e-12)
        self.assertEqual(report["maximum_dirty_scratch_probability"], 0.0)

    def test_elementary_schedule_and_resource_contract(self) -> None:
        self.assertEqual(len(elementary_c2xy_schedule()), 12)
        resources = elementary_resource_per_edge()
        self.assertEqual(resources["abstract_elementary"]["CCX"], 4)
        self.assertEqual(resources["ccx_7t_cost_model"]["CX"], 28)
        self.assertEqual(resources["clean_scratch"]["additional_logical_qubits"], 0)
        self.assertEqual(
            resources["ccx_7t_cost_model"][
                "discrete_fault_tolerant_rotation_synthesis"
            ],
            "NOT_ESTIMATED",
        )

    def test_sealed_artifact_and_tamper_detection_when_present(self) -> None:
        if not V34_PATH.exists():
            self.skipTest("Canonical V3.4 artifact is not sealed yet.")
        artifact, report = load_optimized_native_artifact(V34_PATH)
        self.assertTrue(report["valid"], report["errors"])
        self.assertTrue(artifact["validation"]["overall_pass"])
        tampered = copy.deepcopy(artifact)
        tampered["decisions"]["quantum_advantage"] = "CLAIMED"
        tamper_report = validate_optimized_native_artifact(tampered)
        self.assertFalse(tamper_report["valid"])
        self.assertTrue(tamper_report["errors"])


if __name__ == "__main__":
    unittest.main()
