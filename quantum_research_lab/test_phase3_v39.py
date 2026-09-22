"""Unit and evidence-contract tests for Quantum Lab V3.9."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from .phase3_v39_scalable_reversible_ir import (
    BUDGET_CNOT,
    EDGE_COUNT,
    SEEDS,
    authenticate_parent_chain,
    build_v39_artifact,
    load_v39_artifact,
    load_v39_spec,
    seal_v39_artifact,
    validate_v39_artifact,
)
from .phase3_v39_validation import run_v39_validation


class QuantumLabV39Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = load_v39_spec()
        cls.artifact = build_v39_artifact()
        cls.validation = run_v39_validation()

    def test_specification_is_preregistered_and_provider_free(self) -> None:
        self.assertEqual(self.spec["candidate_family"]["frozen_seeds"], list(SEEDS))
        self.assertEqual(self.spec["acceptance_contract"]["budget_cnot"], BUDGET_CNOT)
        self.assertFalse(self.spec["claim_boundary"]["hardware_executable"])
        self.assertEqual(self.spec["claim_boundary"]["provider_calls"], 0)

    def test_parent_chain_authenticates_v38_through_v31(self) -> None:
        report = authenticate_parent_chain()
        self.assertTrue(report["valid"], report["errors"])
        self.assertTrue(all(row["valid"] for row in report["raw_checks"].values()))

    def test_scientific_validation_passes_all_checks(self) -> None:
        self.assertTrue(self.validation["passed"])
        self.assertEqual(self.validation["counts"]["checks_passed"], self.validation["counts"]["checks_total"])
        self.assertGreaterEqual(self.validation["counts"]["checks_total"], 18)

    def test_complete_ordered_inventory_and_dead_live_split(self) -> None:
        aggregate = self.artifact["aggregate_evidence"]
        self.assertEqual(aggregate["edge_seed_positions"], 6_240)
        self.assertEqual(aggregate["constraint_row_cases"], 43_680)
        self.assertEqual(aggregate["live_edge_positions"], 4_220)
        self.assertEqual(aggregate["certified_identity_positions"], 2_020)
        for row in self.artifact["seed_rows"]:
            self.assertEqual(row["edge_count"], EDGE_COUNT)
            self.assertEqual(len(row["edge_ir_sha256"]), EDGE_COUNT)

    def test_exact_seed_counts_and_maximum_resource_decision(self) -> None:
        expected = {
            1103: (273, 507, 725_326_700),
            2207: (229, 551, 781_332_180),
            3301: (266, 514, 722_838_840),
            4409: (270, 510, 722_438_876),
            5501: (245, 535, 774_993_824),
            6607: (254, 526, 767_893_060),
            7703: (234, 546, 775_257_268),
            8807: (249, 531, 760_588_844),
        }
        self.assertEqual([row["seed"] for row in self.artifact["seed_rows"]], list(SEEDS))
        for row in self.artifact["seed_rows"]:
            self.assertEqual(
                (row["certified_identity_count"], row["live_edge_count"], row["resources"]["selected_model_cnot"]),
                expected[row["seed"]],
            )
        screen = self.artifact["resource_screen"]
        self.assertEqual(screen["maximum_selected_model_cnot"], 781_332_180)
        self.assertEqual(screen["minimum_budget_margin_cnot"], -778_832_180)
        self.assertEqual(screen["decision"], "REJECTED_SELECTED_MODEL_CNOT_BUDGET")

    def test_bounded_decision_does_not_promote_connectivity_or_hardware(self) -> None:
        decisions = self.artifact["decisions"]
        boundary = self.artifact["claim_boundary"]
        self.assertEqual(decisions["overall"], "N40_REVERSIBLE_IR_PASSED_RESOURCE_SCREEN_REJECTED")
        self.assertEqual(decisions["reversible_ir_decision"], "N40_REVERSIBLE_IR_PASSED")
        self.assertEqual(decisions["complete_global_connectivity"], "INDETERMINATE")
        self.assertEqual(decisions["production_admission"], "BLOCKED_GLOBAL_CONNECTIVITY_AND_BACKEND")
        self.assertFalse(boundary["hardware_executable"])
        self.assertEqual(boundary["qpu_jobs_submitted"], 0)
        self.assertEqual(boundary["quantum_advantage"], "NOT_CLAIMED")

    def test_self_hash_tamper_is_rejected(self) -> None:
        tampered = copy.deepcopy(self.artifact)
        tampered["resource_screen"]["maximum_selected_model_cnot"] -= 1
        self.assertFalse(validate_v39_artifact(tampered)["valid"])

    def test_nested_rehash_tamper_is_rejected(self) -> None:
        from .phase3_v39_scalable_reversible_ir import canonical_json_sha256

        tampered = copy.deepcopy(self.artifact)
        tampered["seed_rows"][0]["edge_ir_sha256"][0] = "0" * 64
        seed = tampered["seed_rows"][0]
        seed_core = {key: value for key, value in seed.items() if key != "seed_ir_sha256"}
        seed["seed_ir_sha256"] = canonical_json_sha256(seed_core)
        core = {key: value for key, value in tampered.items() if key != "artifact_sha256"}
        tampered["artifact_sha256"] = canonical_json_sha256(core)
        self.assertFalse(validate_v39_artifact(tampered)["valid"])

    def test_missing_duplicate_and_reordered_seeds_are_rejected(self) -> None:
        for mutate in (
            lambda rows: rows.pop(),
            lambda rows: rows.__setitem__(1, copy.deepcopy(rows[0])),
            lambda rows: rows.reverse(),
        ):
            tampered = copy.deepcopy(self.artifact)
            mutate(tampered["seed_rows"])
            self.assertFalse(validate_v39_artifact(tampered)["valid"])

    def test_sealed_artifact_matches_complete_recomputation(self) -> None:
        sealed, report = load_v39_artifact()
        self.assertTrue(report["valid"], report["errors"])
        self.assertEqual(sealed, self.artifact)

    def test_seal_is_idempotent_and_refuses_nonidentical_existing_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v39-seal-") as temporary:
            target = Path(temporary) / "artifact.json"
            first = seal_v39_artifact(target)
            second = seal_v39_artifact(target)
            self.assertTrue(first["created"])
            self.assertFalse(second["created"])
            payload = json.loads(target.read_text(encoding="utf-8"))
            payload["artifact_sha256"] = "0" * 64
            target.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(FileExistsError):
                seal_v39_artifact(target)


if __name__ == "__main__":
    unittest.main()
