"""Unit and scientific-evidence tests for Quantum Lab V4.1."""

from __future__ import annotations

import ast
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import phase3_v41_certified_bridge_compiler as compiler_module
from .phase3_v41_certified_bridge_compiler import (
    BUDGET_CNOT,
    SEEDS,
    _read_json_strict,
    authenticate_parent_chain,
    canonical_json_sha256,
    compile_bridge_engine,
    default_v41_artifact_path,
    load_v41_spec,
    raw_file_sha256,
    validate_v41_artifact,
)
from .phase3_v41_validation import (
    exhaustive_round_half_even_control,
    exhaustive_strict_margin_theorem_control,
    selected_model_formula_control,
)
from .verify_phase3_v41 import EXPECTED_VALIDATION_EVIDENCE_SHA


ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "quantum_research_lab/PHASE_III_V4_1_CERTIFIED_BRIDGE_COMPILER_SPEC_V1.json"
ENGINE_PATH = ROOT / "quantum_research_lab/phase3_v41_bridge_engine.cpp"
SOURCE_PATH = ROOT / "quantum_research_lab/phase3_v41_certified_bridge_compiler.py"
VALIDATION_PATH = ROOT / "quantum_research_lab/phase3_v41_validation.py"
ARTIFACT_PATH = default_v41_artifact_path(root=ROOT)

EXPECTED_SPEC_RAW = "0bbe903e7520213f8effcd592051420ac54502934a1840b6052e3b4865950c35"
EXPECTED_SPEC_SHA = "a5977ce4dda24d2fe6e8308e299b8a6b9097cf4fdf7e2835ca8e2fdc6aa99c89"
EXPECTED_ENGINE_RAW = "6b065ac1fb834e9ff226954984fe466901314c9b556c2c253a0ace873f2bf26e"
EXPECTED_SOURCE_RAW = "5565ce436034183228d27e37b249afc56f19121a5a8c2638533d4480762c62d1"
EXPECTED_ARTIFACT_RAW = "42a5d7caf4e9fab18e771b2bd55fc38c9a77f7fac42f2599feb4fe789cf88c07"
EXPECTED_ARTIFACT_SHA = "7260336e3a3c6bd2adbd6397d9bed569b91c2da2a7942a17b8090fdcac739e4e"


def _rehash_artifact(payload: dict) -> None:
    payload["artifact_sha256"] = canonical_json_sha256(
        {key: value for key, value in payload.items() if key != "artifact_sha256"}
    )


def _literal_check_names(path: Path, function_name: str) -> tuple[str, ...]:
    """Read the literal validator contract without executing a domain rebuild."""

    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name != function_name:
            continue
        for child in ast.walk(node):
            value = None
            targets: list[ast.expr] = []
            if isinstance(child, ast.Assign):
                value = child.value
                targets = child.targets
            elif isinstance(child, ast.AnnAssign):
                value = child.value
                targets = [child.target]
            if not any(
                isinstance(target, ast.Name) and target.id == "checks"
                for target in targets
            ) or not isinstance(value, ast.Dict):
                continue
            names = tuple(
                key.value
                for key in value.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            )
            if len(names) == len(value.keys):
                return names
    raise AssertionError(f"Literal {function_name} checks contract not found.")


class QuantumLabV41Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = load_v41_spec(root=ROOT)
        cls.artifact = _read_json_strict(ARTIFACT_PATH)

    def test_exact_spec_engine_source_and_artifact_identities(self) -> None:
        self.assertEqual(raw_file_sha256(SPEC_PATH), EXPECTED_SPEC_RAW)
        self.assertEqual(self.spec["v41_spec_sha256"], EXPECTED_SPEC_SHA)
        self.assertEqual(raw_file_sha256(ENGINE_PATH), EXPECTED_ENGINE_RAW)
        self.assertEqual(raw_file_sha256(SOURCE_PATH), EXPECTED_SOURCE_RAW)
        self.assertEqual(raw_file_sha256(ARTIFACT_PATH), EXPECTED_ARTIFACT_RAW)
        self.assertEqual(self.artifact["artifact_sha256"], EXPECTED_ARTIFACT_SHA)
        self.assertEqual(self.artifact["spec_sha256"], EXPECTED_SPEC_SHA)
        self.assertEqual(self.artifact["source_sha256"], EXPECTED_SOURCE_RAW)
        self.assertEqual(
            self.artifact["engine_source_raw_file_sha256"], EXPECTED_ENGINE_RAW
        )

    def test_spec_discloses_exploration_and_locks_protocol(self) -> None:
        chronology = self.spec["chronology"]
        acceptance = self.spec["acceptance_contract"]
        compiler = self.spec["resource_compiler_contract"]
        self.assertTrue(chronology["exploratory_audit_disclosed"])
        self.assertEqual(
            chronology["confirmatory_protocol_state"],
            "SEALED_BEFORE_CONFIRMATORY_REPLAY",
        )
        self.assertEqual(len(chronology["protocol_amendments"]), 2)
        self.assertEqual(
            acceptance["required_bridge_audit_universe_per_isolated_vertex"],
            19_575,
        )
        self.assertEqual(acceptance["budget_cnot"], BUDGET_CNOT)
        self.assertTrue(acceptance["publish_both_registered_candidates"])
        self.assertEqual(
            compiler["architecture_id"],
            "EXACT_COMPRESSED_UNSIGNED_SLACK_LINEAR_ARITHMETIC_WITH_CERTIFIED_BRIDGES_V1",
        )
        self.assertEqual(compiler["post_observation_switching"], "PROHIBITED")

    def test_parent_chain_authenticates_v40_and_143_immutable_paths(self) -> None:
        parent = authenticate_parent_chain(root=ROOT)
        self.assertTrue(parent["valid"], parent["errors"])
        self.assertEqual(parent["immutable_v40_paths_authenticated"], 143)
        self.assertTrue(
            all(
                row["valid"] is True and row["actual"] == row["expected"]
                for row in parent["raw_checks"].values()
            )
        )
        self.assertTrue(all(parent["semantic_checks"].values()))

    def test_sealed_artifact_passes_all_16_reconstruction_checks(self) -> None:
        expected_names = (
            "artifact_self_hash",
            "artifact_version",
            "source_and_engine_identity",
            "spec_identity",
            "research_boundary_exact",
            "bridge_source_order_exact",
            "bridge_row_hashes_exact",
            "bridge_dual_python_replay_exact",
            "bridge_method_attestations_exact",
            "parent_chain_exact",
            "compression_evidence_exact_rebuild",
            "connectivity_evidence_exact_rebuild",
            "resource_evidence_exact_rebuild",
            "decisions_exact_rebuild",
            "v39_rejection_exact",
            "complete_artifact_exact_rebuild",
        )
        self.assertEqual(
            _literal_check_names(SOURCE_PATH, "validate_v41_artifact"), expected_names
        )
        self.assertEqual(self.artifact["artifact_sha256"], EXPECTED_ARTIFACT_SHA)

    def test_complete_three_method_bridge_audit(self) -> None:
        bridge = self.artifact["bridge_audits"]
        rows = bridge["rows"]
        expected_sources = [
            (2207, "08b4208484"),
            (7703, "a8180000ec"),
            (7703, "e2008a4082"),
        ]
        self.assertEqual(
            [(row["seed"], row["source_mask_hex"]) for row in rows],
            expected_sources,
        )
        self.assertEqual(sum(row["candidates_audited"] for row in rows), 58_725)
        self.assertEqual(sum(row["feasible_neighbor_count"] for row in rows), 787)
        self.assertTrue(bridge["all_triple_replays_match"])
        self.assertTrue(all(row["triple_replay_match"] for row in rows))
        self.assertTrue(all(len(row["independent_methods"]) == 3 for row in rows))

    def test_augmented_connectivity_certificate_is_exact_and_bounded(self) -> None:
        connectivity = self.artifact["connectivity_evidence"]
        aggregate = connectivity["aggregate"]
        self.assertEqual([row["seed"] for row in connectivity["seed_rows"]], list(SEEDS))
        self.assertTrue(aggregate["all_eight_seeds_connected_by_certified_subgraph"])
        self.assertEqual(aggregate["authenticated_v40_components_before_bridges"], 11)
        self.assertEqual(aggregate["selected_bridge_count"], 3)
        self.assertEqual(aggregate["final_components_across_seeds"], 8)
        self.assertEqual(aggregate["selected_spanning_subgraph_edges"], 337_710_606)
        self.assertEqual(
            aggregate["complete_augmented_edge_count"],
            "NOT_ENUMERATED_NOT_REQUIRED_FOR_CONNECTIVITY_CERTIFICATE",
        )
        self.assertTrue(
            all(
                bridge["hamming_distance"] == 4
                for row in connectivity["seed_rows"]
                for bridge in row["selected_bridges"]
            )
        )

    def test_all_24_compression_certificates_are_complete_and_exact(self) -> None:
        compression = self.artifact["compression_evidence"]
        rows = compression["seed_rows"]
        factors = [factor for row in rows for factor in row["factor_rows"]]
        self.assertEqual([row["seed"] for row in rows], list(SEEDS))
        self.assertEqual(len(factors), 24)
        self.assertTrue(compression["all_factor_predicates_exact"])
        self.assertTrue(all(row["all_factor_predicates_exact"] for row in rows))
        self.assertTrue(
            all(factor["identity_or_strict_margin_parity_proof"] for factor in factors)
        )
        self.assertTrue(
            all(
                len(factor["predicate_parity_replays"]) == 2
                and all(
                    replay["classification_disagreement_found"] is False
                    for replay in factor["predicate_parity_replays"]
                )
                for factor in factors
            )
        )

    def test_r1_r2_resource_ledgers_and_qubit_bound_are_exact(self) -> None:
        resources = self.artifact["resource_evidence"]
        rows = resources["seed_rows"]
        aggregate = resources["aggregate"]
        self.assertEqual([row["seed"] for row in rows], list(SEEDS))
        self.assertEqual(aggregate["r1_maximum_selected_model_cnot"], 15_256_056)
        self.assertEqual(aggregate["r2_maximum_selected_model_cnot"], 15_663_936)
        self.assertEqual(aggregate["r2_minimum_budget_margin_cnot"], -13_163_936)
        self.assertFalse(aggregate["r1_all_seeds_pass"])
        self.assertFalse(aggregate["r2_all_seeds_pass"])
        self.assertTrue(aggregate["independent_resource_replay_all_seeds"])
        self.assertEqual(
            max(
                row["r2"]["logical_qubits_with_clean_decomposition_ancillas"]
                for row in rows
            ),
            311,
        )
        self.assertTrue(all("r1" in row and "r2" in row for row in rows))
        self.assertTrue(
            all(
                row["r2"]["decision"] == "REJECTED_SELECTED_MODEL_CNOT_BUDGET"
                for row in rows
            )
        )

    def test_decisions_and_execution_boundary_remain_fail_closed(self) -> None:
        decisions = self.artifact["decisions"]
        boundary = self.artifact["claim_boundary"]
        self.assertEqual(
            decisions["augmented_connectivity_decision"],
            "AUGMENTED_1_2_EXCHANGE_GRAPH_CONNECTED_ALL_SEEDS_BY_CERTIFIED_SUBGRAPH",
        )
        self.assertEqual(
            decisions["resource_architecture_decision"],
            "REJECTED_SELECTED_MODEL_CNOT_BUDGET",
        )
        self.assertEqual(
            decisions["production_admission"],
            "REJECTED_RESOURCE_BUDGET_HARDWARE_NOT_AUTHORIZED",
        )
        self.assertEqual(
            decisions["next_falsifiable_gate"],
            "SPARSE_CONNECTED_GENERATOR_COMPILER_OR_STRONGER_EXACT_ARITHMETIC_REDUCTION",
        )
        self.assertEqual(self.artifact["research_classification"], "RESEARCH_ONLY")
        self.assertEqual(boundary["provider_calls"], 0)
        self.assertFalse(boundary["provider_credentials_read"])
        self.assertFalse(boundary["provider_sdk_imported"])
        self.assertEqual(boundary["backend_transpilation"], "NOT_RUN")
        self.assertFalse(boundary["qpu_submission_enabled"])
        self.assertEqual(boundary["qpu_jobs_submitted"], 0)
        self.assertFalse(boundary["hardware_executable"])
        self.assertEqual(boundary["quantum_advantage"], "NOT_CLAIMED")

    def test_v39_resource_rejection_is_preserved(self) -> None:
        rejection = self.artifact["v39_resource_rejection"]
        self.assertTrue(rejection["preserved"])
        self.assertEqual(rejection["budget_cnot"], BUDGET_CNOT)
        self.assertEqual(rejection["maximum_selected_model_cnot"], 781_332_180)
        self.assertEqual(
            rejection["budget_decision"], "REJECTED_SELECTED_MODEL_CNOT_BUDGET"
        )

    def test_bounded_rounding_margin_and_formula_controls(self) -> None:
        self.assertTrue(exhaustive_round_half_even_control()["passed"])
        self.assertTrue(exhaustive_strict_margin_theorem_control()["passed"])
        self.assertTrue(selected_model_formula_control()["passed"])

    def test_scientific_validation_contract_has_exactly_28_checks(self) -> None:
        names = _literal_check_names(VALIDATION_PATH, "run_v41_validation")
        self.assertEqual(len(names), 28)
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(
            EXPECTED_VALIDATION_EVIDENCE_SHA,
            "be7b47a74a6da02af9867f531f47a5c72b473da13c6eb872e7dce1ddede9ff06",
        )

    def test_bridge_engine_compiles_without_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v41-engine-test-") as temporary:
            target = Path(temporary) / "bridge-engine"
            report = compile_bridge_engine(target, root=ROOT)
            self.assertTrue(target.is_file())
            self.assertEqual(report["source_sha256"], EXPECTED_ENGINE_RAW)

    def test_rehashed_nested_tampers_are_rejected_fail_closed(self) -> None:
        mutations = {
            "bridge": lambda payload: payload["bridge_audits"]["rows"][0].__setitem__(
                "feasible_neighbor_count",
                payload["bridge_audits"]["rows"][0]["feasible_neighbor_count"] + 1,
            ),
            "compression": lambda payload: payload["compression_evidence"]["seed_rows"][0]["factor_rows"][0].__setitem__(
                "selected_shift",
                payload["compression_evidence"]["seed_rows"][0]["factor_rows"][0]["selected_shift"] + 1,
            ),
            "connectivity": lambda payload: payload["connectivity_evidence"]["aggregate"].__setitem__(
                "selected_bridge_count", 4
            ),
            "resource": lambda payload: payload["resource_evidence"]["aggregate"].__setitem__(
                "r2_maximum_selected_model_cnot", 1
            ),
            "boundary": lambda payload: payload["claim_boundary"].__setitem__(
                "provider_calls", 1
            ),
            "decision": lambda payload: payload["decisions"].__setitem__(
                "production_admission", "UNAUTHORIZED_PASS"
            ),
            "parent": lambda payload: payload["parent"].__setitem__(
                "v40_artifact_raw_file_sha256", "0" * 64
            ),
        }
        # The release-chain verifier owns the complete independent rebuild.
        # Here the canonical sealed artifact is injected as that deterministic
        # result so each comparison branch is exercised without repeating the
        # multi-minute complete-domain replay in the unit-test process.
        with patch.object(
            compiler_module,
            "build_v41_artifact",
            return_value=copy.deepcopy(self.artifact),
        ):
            for name, mutate in mutations.items():
                with self.subTest(tamper=name):
                    payload = copy.deepcopy(self.artifact)
                    mutate(payload)
                    _rehash_artifact(payload)
                    report = validate_v41_artifact(
                        payload, root=ROOT, authenticate_parent=False
                    )
                    self.assertFalse(report["valid"], report)


if __name__ == "__main__":
    unittest.main()
