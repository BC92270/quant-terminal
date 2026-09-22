"""Unit and scientific-evidence tests for Quantum Lab V4.0."""

from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

from .phase3_v40_global_connectivity import (
    SEEDS,
    authenticate_parent_chain,
    canonical_json_sha256,
    compile_connectivity_engine,
    load_v40_artifact,
    load_v40_spec,
    validate_v40_artifact,
)
from .phase3_v40_validation import (
    exhaustive_core_adjacency_identity,
    exhaustive_small_graph_equivalence,
    run_v40_validation,
)


def _rehash_artifact(payload: dict) -> None:
    payload["artifact_sha256"] = canonical_json_sha256({key: value for key, value in payload.items() if key != "artifact_sha256"})


def _rehash_seed(row: dict) -> None:
    row["seed_evidence_sha256"] = canonical_json_sha256({key: value for key, value in row.items() if key != "seed_evidence_sha256"})


class QuantumLabV40Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = load_v40_spec()
        cls.artifact, cls.report = load_v40_artifact()
        cls.validation = run_v40_validation()

    def test_spec_discloses_exploration_and_locks_confirmatory_replay(self) -> None:
        chronology = self.spec["chronology"]
        protocol = self.spec["connectivity_protocol"]
        self.assertTrue(chronology["exploratory_audit_disclosed"])
        self.assertEqual(chronology["confirmatory_protocol_state"], "SEALED_BEFORE_CONFIRMATORY_REPLAY")
        self.assertEqual(protocol["primary_replay"]["group_split"], [[0, 1], [2, 3]])
        self.assertEqual(protocol["structural_replay"]["group_split"], [[0, 2], [1, 3]])

    def test_parent_chain_authenticates_v39_through_v31(self) -> None:
        parent = authenticate_parent_chain()
        self.assertTrue(parent["valid"], parent["errors"])
        self.assertTrue(all(item["valid"] for item in parent["raw_checks"].values()))
        self.assertEqual(parent["immutable_v39_files_checked"], 127)

    def test_sealed_artifact_is_valid_and_provider_free(self) -> None:
        self.assertTrue(self.report["valid"], self.report)
        boundary = self.artifact["claim_boundary"]
        self.assertFalse(boundary["hardware_executable"])
        self.assertEqual(boundary["provider_calls"], 0)
        self.assertEqual(boundary["qpu_jobs_submitted"], 0)
        self.assertEqual(boundary["quantum_advantage"], "NOT_CLAIMED")

    def test_complete_eight_seed_exact_graph_ledger(self) -> None:
        rows = self.artifact["connectivity_evidence"]["seed_rows"]
        self.assertEqual([row["seed"] for row in rows], list(SEEDS))
        self.assertEqual(sum(row["feasible_vertex_count"] for row in rows), 21_655_776)
        self.assertEqual(sum(row["exact_state_graph_edge_count"] for row in rows), 337_710_603)
        self.assertEqual(sum(row["observed_nine_core_incidences"] for row in rows), 216_557_760)
        for row in rows:
            self.assertTrue(row["coverage_complete"])
            self.assertTrue(row["replay"]["all_stable_fields_match"])
            self.assertEqual(row["observed_nine_core_incidences"], 10 * row["feasible_vertex_count"])
            self.assertEqual(row["successful_unions"] + row["component_count"], row["feasible_vertex_count"])

    def test_counterexample_is_exact_and_compact(self) -> None:
        rows = {row["seed"]: row for row in self.artifact["connectivity_evidence"]["seed_rows"]}
        self.assertEqual(rows[2207]["component_count"], 2)
        self.assertEqual(rows[7703]["component_count"], 3)
        isolated = rows[2207]["isolated_counterexamples"] + rows[7703]["isolated_counterexamples"]
        self.assertEqual(len(isolated), 3)
        self.assertEqual(sum(item["neighbors_audited"] for item in isolated), 900)
        self.assertTrue(all(item["vertex_exactly_feasible"] for item in isolated))
        self.assertTrue(all(item["all_neighbors_rejected"] for item in isolated))
        self.assertTrue(all(item["feasible_neighbor_count"] == 0 for item in isolated))

    def test_decision_rejects_one_swap_mixer_without_overclaiming(self) -> None:
        decisions = self.artifact["decisions"]
        self.assertEqual(decisions["global_connectivity_decision"], "GLOBAL_FEASIBLE_GRAPH_DISCONNECTED_COUNTEREXAMPLE")
        self.assertEqual(decisions["production_admission"], "REJECTED_CONNECTIVITY_AND_V39_RESOURCE_ARCHITECTURE")
        self.assertEqual(decisions["next_falsifiable_gate"], "AUGMENTED_1_2_EXCHANGE_GRAPH_CONNECTIVITY_OR_COUNTEREXAMPLE")

    def test_v39_rejection_is_preserved_and_redesign_not_evaluated(self) -> None:
        self.assertEqual(self.artifact["v39_resource_rejection"]["maximum_selected_model_cnot"], 781_332_180)
        self.assertEqual(self.artifact["v39_resource_rejection"]["budget_decision"], "REJECTED_SELECTED_MODEL_CNOT_BUDGET")
        redesign = self.artifact["resource_redesign"]
        self.assertEqual(redesign["status"], "RESOURCE_ARCHITECTURE_PREREGISTERED_NOT_EVALUATED")
        self.assertEqual(redesign["result_fields"]["cnot"], "NOT_EVALUATED")
        self.assertEqual(redesign["result_fields"]["budget_margin"], "NOT_COMPUTED")

    def test_small_graph_and_core_theorem_exhaustive_controls(self) -> None:
        self.assertTrue(exhaustive_small_graph_equivalence()["passed"])
        self.assertTrue(exhaustive_core_adjacency_identity()["passed"])

    def test_scientific_validation_passes_all_checks(self) -> None:
        self.assertTrue(self.validation["passed"], self.validation)
        self.assertEqual(self.validation["counts"]["checks_passed"], self.validation["counts"]["checks_total"])
        self.assertGreaterEqual(self.validation["counts"]["checks_total"], 21)

    def test_engine_compiles_without_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v40-engine-test-") as temporary:
            report = compile_connectivity_engine(Path(temporary) / "engine")
            self.assertEqual(len(report["binary_sha256"]), 64)

    def test_raw_and_nested_tamper_are_rejected(self) -> None:
        raw = copy.deepcopy(self.artifact)
        raw["aggregate_evidence"]["total_feasible_vertices"] -= 1
        self.assertFalse(validate_v40_artifact(raw, authenticate_parent=False)["valid"])

        nested = copy.deepcopy(self.artifact)
        row = nested["connectivity_evidence"]["seed_rows"][1]
        row["isolated_counterexamples"][0]["feasible_neighbor_count"] = 1
        _rehash_seed(row)
        _rehash_artifact(nested)
        self.assertFalse(validate_v40_artifact(nested, authenticate_parent=False)["valid"])

    def test_missing_duplicate_and_reordered_seeds_are_rejected(self) -> None:
        mutations = (
            lambda rows: rows.pop(),
            lambda rows: rows.__setitem__(1, copy.deepcopy(rows[0])),
            lambda rows: rows.reverse(),
        )
        for mutation in mutations:
            payload = copy.deepcopy(self.artifact)
            mutation(payload["connectivity_evidence"]["seed_rows"])
            _rehash_artifact(payload)
            self.assertFalse(validate_v40_artifact(payload, authenticate_parent=False)["valid"])

    def test_relabel_and_post_observation_resource_number_are_rejected(self) -> None:
        relabeled = copy.deepcopy(self.artifact)
        relabeled["decisions"]["global_connectivity_decision"] = "GLOBAL_FEASIBLE_GRAPH_CONNECTED_ALL_SEEDS"
        _rehash_artifact(relabeled)
        self.assertFalse(validate_v40_artifact(relabeled, authenticate_parent=False)["valid"])

        numbered = copy.deepcopy(self.artifact)
        numbered["resource_redesign"]["result_fields"]["cnot"] = 1
        _rehash_artifact(numbered)
        self.assertFalse(validate_v40_artifact(numbered, authenticate_parent=False)["valid"])


if __name__ == "__main__":
    unittest.main()
