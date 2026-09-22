"""Regression tests for V3.6 structural reduction admission."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from .phase3_v36_algorithmic_reduction import (
    SEMANTICS_CHANGED,
    SEMANTICS_FEASIBLE,
    SEMANTICS_UNPROVEN,
    authenticate_parent_chain,
    build_v36_artifact,
    canonical_json_sha256,
    guard_scope_truth_table,
    load_v36_spec,
    seal_v36_artifact,
    validate_v36_artifact,
)
from .phase3_v36_validation import EXPECTED_ORACLE_CNOT, run_v36_validation


class AlgorithmicReductionV36Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = load_v36_spec()
        cls.artifact = build_v36_artifact()

    def test_spec_self_hash_and_zero_job_boundary(self) -> None:
        core = {
            key: value
            for key, value in self.spec.items()
            if key not in {"v36_spec_sha", "v36_spec_sha256"}
        }
        self.assertEqual(self.spec["v36_spec_sha256"], canonical_json_sha256(core))
        self.assertEqual(self.spec["claim_boundary"]["research_classification"], "RESEARCH_ONLY")
        self.assertEqual(self.spec["claim_boundary"]["provider_calls"], 0)
        self.assertFalse(self.spec["claim_boundary"]["qpu_submission_enabled"])

    def test_parent_chain_is_exact(self) -> None:
        report = authenticate_parent_chain(self.spec)
        self.assertTrue(report["valid"], report["errors"])
        self.assertEqual(len(report["comparisons"]), 15)
        self.assertTrue(all(row["valid"] for row in report["comparisons"].values()))

    def test_all_eight_structural_equations_reconstruct(self) -> None:
        attribution = self.artifact["structural_cost_attribution"]
        rows = attribution["rows"]
        self.assertEqual(len(rows), 8)
        self.assertTrue(all(row["reconstruction_exact"] for row in rows))
        self.assertTrue(all(row["division_remainder"] == 0 for row in rows))
        observed = {row["seed"]: row["per_oracle_cnot"] for row in rows}
        self.assertEqual(observed, EXPECTED_ORACLE_CNOT)

    def test_oracle_pair_floor_rejects_topology_only_lane(self) -> None:
        self.assertEqual(
            self.artifact["decisions"]["overall"],
            "ARCHITECTURE_REWRITE_REQUIRED",
        )
        summary = self.artifact["structural_cost_attribution"]["summary"]
        self.assertEqual(summary["per_oracle_cnot_min"], 92_095_707)
        self.assertEqual(summary["per_oracle_cnot_max"], 95_650_135)
        self.assertEqual(summary["required_compute_uncompute_pair_cnot_floor"], 184_191_414)
        self.assertEqual(summary["selected_model_budget_cnot"], 2_500_000)
        self.assertTrue(summary["pair_floor_exceeds_budget"])
        self.assertEqual(summary["pair_floor_multiple_of_budget"], 73.6765656)
        self.assertEqual(
            self.artifact["decisions"]["topology_only"],
            "REJECTED_WITHIN_FROZEN_V34_ARCHITECTURE",
        )

    def test_guard_reduction_has_explicit_semantic_scope(self) -> None:
        proof = guard_scope_truth_table()
        self.assertEqual(proof["total_cases"], 8)
        self.assertTrue(proof["equal_on_all_feasible_support_cases"])
        self.assertTrue(proof["different_outside_feasible_support"])
        self.assertEqual(proof["semantic_classification"], SEMANTICS_FEASIBLE)

    def test_incremental_delta_is_exact_but_not_compiled(self) -> None:
        audit = self.artifact["incremental_exposure_audit"]
        lane = self.artifact["rewrite_admission"]["lanes"]["INCREMENTAL_EXPOSURE_GUARD"]
        self.assertTrue(audit["passed"])
        self.assertEqual(audit["total_swap_cases"], 6_240)
        self.assertEqual(audit["total_constraint_row_cases"], 43_680)
        self.assertEqual(audit["reversible_compiler_status"], "BLOCKED_PENDING_REVERSIBLE_COMPILER")
        self.assertEqual(lane["semantic_classification"], SEMANTICS_UNPROVEN)
        self.assertEqual(lane["selected_model_cnot"], "NOT_ESTIMATED")

    def test_changed_semantics_lanes_cannot_inherit_equivalence(self) -> None:
        lanes = self.artifact["rewrite_admission"]["lanes"]
        self.assertEqual(lanes["TOPOLOGY_ONLY_PRUNED"]["semantic_classification"], SEMANTICS_CHANGED)
        self.assertEqual(lanes["BLOCK_COORDINATE"]["semantic_classification"], SEMANTICS_CHANGED)
        self.assertFalse(lanes["BLOCK_COORDINATE"]["inherit_v34_equivalence"])

    def test_artifact_integrity_tamper_and_create_once(self) -> None:
        self.assertTrue(validate_v36_artifact(self.artifact)["valid"])
        tampered = copy.deepcopy(self.artifact)
        tampered["claim_boundary"]["qpu_jobs_submitted"] = 1
        self.assertFalse(validate_v36_artifact(tampered)["valid"])
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "SEALED_V3_6_TEST_ARTIFACT.json"
            first = seal_v36_artifact(target)
            second = seal_v36_artifact(target)
            self.assertTrue(first["created"])
            self.assertFalse(second["created"])
            self.assertEqual(first["artifact"]["artifact_sha256"], second["artifact"]["artifact_sha256"])

    def test_full_validation_ladder(self) -> None:
        report = run_v36_validation()
        self.assertTrue(report["overall_pass"], report)
        self.assertEqual(len(report["checks"]), 13)
        self.assertTrue(all(report["checks"].values()))


if __name__ == "__main__":
    unittest.main()
