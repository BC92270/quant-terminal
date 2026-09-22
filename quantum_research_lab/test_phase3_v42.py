"""Unit, evidence-boundary and tamper tests for Quantum Lab V4.2."""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import phase3_v42_coined_walk_compiler as compiler_module
from .phase3_v42_coined_walk_compiler import (
    BUDGET_CNOT,
    SEEDS,
    _read_json_strict,
    authenticate_v41_parent,
    build_v42_artifact,
    canonical_json_sha256,
    default_v42_artifact_path,
    load_v42_spec,
    raw_file_sha256,
    run_selector_control,
    validate_v42_artifact,
)
from .phase3_v42_validation import (
    EXPECTED_SELECTOR_COUNTS,
    exhaustive_python_selector_control,
    selected_model_formula_control,
)


ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "quantum_research_lab/PHASE_III_V4_2_COINED_WALK_COMPILER_SPEC_V1.json"
ENGINE_PATH = ROOT / "quantum_research_lab/phase3_v42_selector_engine.cpp"
SOURCE_PATH = ROOT / "quantum_research_lab/phase3_v42_coined_walk_compiler.py"
ARTIFACT_PATH = default_v42_artifact_path(root=ROOT)

EXPECTED_SPEC_RAW = "11b9d7a86fc1617f7c313c2cda58c4b8874d33cb9e4fe11460a65b8920e40674"
EXPECTED_SPEC_SHA = "acf640c11d3dc575ebcc1358919095cf68673583a8c628c7131e664f7859801e"
EXPECTED_ENGINE_RAW = "3d73cddfc7c06cf6e0e5bc22a3ad29c3ea79ac22d7c1e5a8b1ca1044789c65ab"
EXPECTED_SOURCE_RAW = "fc4b9ce991cc866aa7a9b809172df41227e9dcd133a41d210068663ee7bd77e9"
EXPECTED_ARTIFACT_RAW = "0952111064db57f6c1122e9a7b4d45ee997667e0d57137ea173be0009ba4feec"
EXPECTED_ARTIFACT_SHA = "f2f294f8f0a21804d7dd6a23d7695b161723fcc1efea48b2f9d1ce7bcbb3f5be"


def _rehash(payload: dict) -> None:
    payload["artifact_sha256"] = canonical_json_sha256(
        {key: value for key, value in payload.items() if key != "artifact_sha256"}
    )


def _literal_check_names(path: Path, function_name: str) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name != function_name:
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.AnnAssign):
                continue
            if not isinstance(child.target, ast.Name) or child.target.id != "checks":
                continue
            if not isinstance(child.value, ast.Dict):
                continue
            return tuple(
                key.value for key in child.value.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            )
    raise AssertionError(f"Literal check dictionary not found in {function_name}.")


class QuantumLabV42Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = load_v42_spec(root=ROOT)
        cls.artifact = _read_json_strict(ARTIFACT_PATH)
        cls.parent = authenticate_v41_parent(root=ROOT, deep=False)

    def test_exact_spec_engine_source_and_artifact_identities(self) -> None:
        self.assertEqual(raw_file_sha256(SPEC_PATH), EXPECTED_SPEC_RAW)
        self.assertEqual(self.spec["v42_spec_sha256"], EXPECTED_SPEC_SHA)
        self.assertEqual(raw_file_sha256(ENGINE_PATH), EXPECTED_ENGINE_RAW)
        self.assertEqual(raw_file_sha256(SOURCE_PATH), EXPECTED_SOURCE_RAW)
        self.assertEqual(raw_file_sha256(ARTIFACT_PATH), EXPECTED_ARTIFACT_RAW)
        self.assertEqual(self.artifact["artifact_sha256"], EXPECTED_ARTIFACT_SHA)
        self.assertEqual(self.artifact["source_sha256"], EXPECTED_SOURCE_RAW)

    def test_protocol_was_sealed_before_accepted_artifact(self) -> None:
        chronology = self.spec["chronology"]
        self.assertEqual(
            chronology["confirmatory_protocol_state"],
            "SEALED_BEFORE_ACCEPTED_CONFIRMATORY_ARTIFACT",
        )
        self.assertTrue(chronology["exploratory_audit_disclosed"])
        self.assertEqual(chronology["resource_ledger_state_at_seal"], "NOT_EVALUATED")
        self.assertEqual(
            chronology["exploratory_observation"]["resource_estimate_use"],
            "Engineering feasibility signal only; it is not an accepted result and cannot satisfy any V4.2 gate",
        )

    def test_v41_parent_and_all_159_immutable_paths_authenticate(self) -> None:
        self.assertTrue(self.parent["valid"], self.parent["errors"])
        self.assertEqual(self.parent["immutable_v41_file_count"], 159)
        self.assertTrue(self.parent["immutable_v41_files_exact"])
        self.assertTrue(all(row["valid"] for row in self.parent["raw_checks"].values()))
        self.assertTrue(all(self.parent["semantic_checks"].values()))

    def test_artifact_validator_contract_has_all_16_checks(self) -> None:
        names = _literal_check_names(SOURCE_PATH, "validate_v42_artifact")
        self.assertEqual(len(names), 16)
        self.assertEqual(
            names,
            (
                "artifact_self_hash",
                "artifact_version",
                "spec_source_engine_identity",
                "claim_boundary_exact",
                "parent_exact",
                "selector_control_exact",
                "support_evidence_exact",
                "resource_evidence_exact",
                "decisions_exact",
                "all_pair_positions_preserved",
                "joint_support_connected_all_seeds",
                "promise_selector_exhaustive_controls_pass",
                "independent_resource_replay_all_seeds",
                "maximum_budget_gate_exact",
                "provider_hardware_advantage_zero",
                "complete_artifact_exact_rebuild",
            ),
        )

    def test_sealed_selector_control_is_portable_and_exact(self) -> None:
        selector = self.artifact["selector_control"]
        self.assertTrue(selector["stable_replay_match"])
        self.assertNotIn("binary_sha256", selector["build_contract"])
        self.assertNotIn("compiler", selector["build_contract"])
        self.assertTrue(selector["build_contract"]["diagnostics_clean"])
        self.assertEqual(
            {key: selector["forward"][key] for key in EXPECTED_SELECTOR_COUNTS},
            EXPECTED_SELECTOR_COUNTS,
        )

    def test_independent_python_selector_exhaustion_matches_cpp(self) -> None:
        replay = exhaustive_python_selector_control()
        self.assertTrue(replay["passed"])
        self.assertEqual(
            {key: replay[key] for key in EXPECTED_SELECTOR_COUNTS},
            EXPECTED_SELECTOR_COUNTS,
        )
        self.assertEqual(replay["selector_cases"], 264_328)
        self.assertEqual(replay["bridge_cases"], 8_826)

    def test_cpp_dual_traversal_replay_is_stable(self) -> None:
        replay = run_selector_control(root=ROOT)
        self.assertEqual(replay, self.artifact["selector_control"])
        self.assertTrue(replay["stable_replay_match"])

    def test_joint_support_preserves_every_position_and_is_connected(self) -> None:
        support = self.artifact["support_evidence"]
        aggregate = support["aggregate"]
        self.assertEqual([row["seed"] for row in support["seed_rows"]], list(SEEDS))
        self.assertTrue(aggregate["all_pair_positions_preserved"])
        self.assertTrue(aggregate["all_seeds_connected"])
        self.assertEqual(aggregate["coin_basis_states_per_data_vertex"], 1_600)
        self.assertEqual(aggregate["parent_selected_bridge_count"], 3)
        self.assertEqual(aggregate["joint_promise_vertices"], 34_649_241_600)
        self.assertEqual(aggregate["joint_support_edges"], 69_973_909_206)
        self.assertTrue(all(row["addressed_pair_positions_preserved"] == 780 for row in support["seed_rows"]))
        self.assertTrue(all(row["joint_component_count"] == 1 for row in support["seed_rows"]))

    def test_all_eight_selected_model_resource_rows_pass(self) -> None:
        resources = self.artifact["resource_evidence"]
        rows = resources["seed_rows"]
        expected = {
            1103: 1_084_198,
            2207: 1_087_798,
            3301: 1_062_182,
            4409: 1_062_182,
            5501: 1_062_182,
            6607: 1_084_198,
            7703: 1_135_430,
            8807: 1_106_214,
        }
        self.assertEqual(
            {row["seed"]: row["selected_model_step_resources"]["selected_model_cnot"] for row in rows},
            expected,
        )
        self.assertTrue(all(row["decision"] == "PASSED" for row in rows))
        self.assertTrue(all(row["independent_cnot_formula_replay"]["match"] for row in rows))

    def test_maximum_budget_gate_and_qubit_bound_are_exact(self) -> None:
        aggregate = self.artifact["resource_evidence"]["aggregate"]
        self.assertTrue(aggregate["all_eight_seeds_pass"])
        self.assertEqual(aggregate["budget_cnot"], BUDGET_CNOT)
        self.assertEqual(aggregate["maximum_selected_model_cnot"], 1_135_430)
        self.assertEqual(aggregate["minimum_budget_margin_cnot"], 1_364_570)
        self.assertEqual(aggregate["maximum_logical_qubits_with_recycled_workspace"], 331)
        self.assertEqual(aggregate["v41_to_v42_maximum_reduction_basis_points"], 9_275)

    def test_scaffold_and_bridge_closed_forms_are_exact(self) -> None:
        rows = self.artifact["resource_evidence"]["seed_rows"]
        self.assertTrue(selected_model_formula_control()["passed"])
        self.assertTrue(all(row["select_scaffold"]["resources"]["selected_model_cnot"] == 3_698 for row in rows))
        bridges = [bridge for row in rows for bridge in row["bridge_ir"]]
        self.assertEqual(len(bridges), 3)
        self.assertTrue(all(bridge["data_hamming_distance"] == 4 for bridge in bridges))
        self.assertTrue(all(bridge["resources"]["selected_model_cnot"] == 3_600 for bridge in bridges))

    def test_decision_advances_only_to_the_registered_next_gate(self) -> None:
        decisions = self.artifact["decisions"]
        self.assertEqual(
            decisions["overall"],
            "V42_INDEXED_COINED_WALK_CONNECTED_RESOURCE_SCREEN_PASSED",
        )
        self.assertEqual(
            decisions["production_admission"],
            "PROVIDER_NEUTRAL_RESEARCH_GENERATOR_ADMITTED_HARDWARE_NOT_AUTHORIZED",
        )
        self.assertEqual(
            decisions["next_falsifiable_gate"],
            "INDEPENDENT_REVERSIBLE_SIMULATION_AND_BACKEND_AGNOSTIC_CIRCUIT_MATERIALIZATION",
        )

    def test_execution_and_advantage_boundary_remains_zero(self) -> None:
        boundary = self.artifact["claim_boundary"]
        self.assertEqual(self.artifact["research_classification"], "RESEARCH_ONLY")
        self.assertFalse(boundary["provider_sdk_imported"])
        self.assertFalse(boundary["provider_credentials_read"])
        self.assertEqual(boundary["provider_calls"], 0)
        self.assertEqual(boundary["qpu_jobs_submitted"], 0)
        self.assertFalse(boundary["hardware_executable"])
        self.assertEqual(boundary["backend_transpilation"], "NOT_RUN")
        self.assertEqual(boundary["circuit_materialization"], "NOT_RUN_NEXT_GATE")
        self.assertEqual(boundary["quantum_advantage"], "NOT_CLAIMED")

    def test_compiler_source_has_no_provider_sdk_import(self) -> None:
        tree = ast.parse(SOURCE_PATH.read_text(encoding="utf-8"))
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module.split(".")[0])
        self.assertTrue({"qiskit", "cirq", "braket", "pennylane", "qbraid"}.isdisjoint(imports))

    def test_complete_artifact_rebuild_is_byte_semantically_deterministic(self) -> None:
        rebuilt = build_v42_artifact(root=ROOT, deep_parent=False)
        self.assertEqual(rebuilt, self.artifact)
        self.assertEqual(rebuilt["artifact_sha256"], EXPECTED_ARTIFACT_SHA)

    def test_nested_tampering_is_rejected_even_after_top_level_rehash(self) -> None:
        mutations = (
            ("resource", lambda item: item["resource_evidence"]["seed_rows"][0].__setitem__("budget_margin_cnot", 0)),
            ("support", lambda item: item["support_evidence"]["seed_rows"][0].__setitem__("joint_component_count", 2)),
            ("selector", lambda item: item["selector_control"]["forward"].__setitem__("selector_failures", 1)),
            ("boundary", lambda item: item["claim_boundary"].__setitem__("hardware_executable", True)),
        )
        parent = self.parent
        with patch.object(compiler_module, "authenticate_v41_parent", return_value=parent), patch.object(
            compiler_module, "run_selector_control", return_value=self.artifact["selector_control"]
        ), patch.object(
            compiler_module, "build_support_evidence", return_value=self.artifact["support_evidence"]
        ), patch.object(
            compiler_module, "build_resource_evidence", return_value=self.artifact["resource_evidence"]
        ), patch.object(
            compiler_module, "build_v42_artifact", return_value=self.artifact
        ):
            for name, mutate in mutations:
                with self.subTest(name=name):
                    tampered = copy.deepcopy(self.artifact)
                    mutate(tampered)
                    _rehash(tampered)
                    report = validate_v42_artifact(tampered, root=ROOT, authenticate_parent=False)
                    self.assertFalse(report["valid"])

    def test_strict_json_reader_rejects_duplicate_and_nonfinite_values(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v42-json-") as temporary:
            duplicate = Path(temporary) / "duplicate.json"
            duplicate.write_text('{"a":1,"a":2}', encoding="utf-8")
            with self.assertRaises(ValueError):
                _read_json_strict(duplicate)
            nonfinite = Path(temporary) / "nonfinite.json"
            nonfinite.write_text('{"a":NaN}', encoding="utf-8")
            with self.assertRaises(ValueError):
                _read_json_strict(nonfinite)

    def test_existing_nonidentical_artifact_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v42-seal-") as temporary:
            target = Path(temporary) / "artifact.json"
            target.write_text("sentinel\n", encoding="utf-8")
            with patch.object(compiler_module, "build_v42_artifact", return_value=self.artifact), patch.object(
                compiler_module, "validate_v42_artifact", return_value={"valid": True}
            ):
                with self.assertRaises(FileExistsError):
                    compiler_module.seal_v42_artifact(target, root=ROOT)
            self.assertEqual(target.read_text(encoding="utf-8"), "sentinel\n")


if __name__ == "__main__":
    unittest.main()
