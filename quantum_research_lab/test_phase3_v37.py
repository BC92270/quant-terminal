"""Regression tests for the V3.7 reversible incremental-exposure prototype."""

from __future__ import annotations

import copy
import math
import tempfile
import unittest
from pathlib import Path

from .phase3_v37_reversible_compiler import (
    NUMERIC_TOLERANCE,
    apply_gate_sequence,
    authenticate_v36_parent,
    build_v37_artifact,
    canonical_json_sha256,
    compile_edge,
    decode_basis_state,
    differential_audit,
    encode_basis_state,
    exact_k_states,
    exposure_values,
    gray_path,
    load_v37_spec,
    portfolio_feasible,
    prototype_fixture,
    register_contract,
    resource_ledger,
    seal_v37_artifact,
    transition_pairs,
    validate_v37_artifact,
)
from .phase3_v37_validation import run_v37_validation


class ReversibleIncrementalExposureV37Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = prototype_fixture()
        cls.artifact = build_v37_artifact()

    def test_v36_parent_chain_is_exact_and_portable(self) -> None:
        report = authenticate_v36_parent()
        self.assertTrue(report["valid"], report["errors"])
        self.assertTrue(all(row["valid"] for row in report["comparisons"].values()))
        self.assertNotIn("path", self.artifact["parent"]["authentication"])

    def test_spec_self_hash_and_fixture_binding(self) -> None:
        spec = load_v37_spec()
        self.assertEqual(self.artifact["spec_sha256"], spec["v37_spec_sha256"])
        self.assertEqual(
            spec["fixture_contract"],
            {key: value for key, value in self.fixture.items() if key != "fixture_sha256"},
        )
        self.assertFalse(spec["claim_boundary"]["hardware_executable"])
        self.assertEqual(spec["claim_boundary"]["selected_model_cnot"], "NOT_ESTIMATED")

    def test_fixture_register_and_signed_cache_roundtrip(self) -> None:
        register = register_contract(self.fixture)
        self.assertEqual(register["data_qubits"], 10)
        self.assertEqual(register["full_domain_basis_states"], 1024)
        self.assertEqual(register["ancilla_qubits"], 0)
        self.assertEqual(register["scratch_qubits"], 0)
        for bits in exact_k_states(self.fixture):
            index = encode_basis_state(bits, fixture=self.fixture)
            decoded = decode_basis_state(index, self.fixture)
            self.assertEqual(decoded["portfolio_bits"], list(bits))
            self.assertEqual(decoded["cached_exposures"], list(exposure_values(bits, self.fixture)))
            self.assertTrue(decoded["cache_consistent"])

    def test_fixture_feasible_support_and_transition_inventory(self) -> None:
        feasible = [state for state in exact_k_states(self.fixture) if portfolio_feasible(state, self.fixture)]
        self.assertEqual(len(exact_k_states(self.fixture)), 6)
        self.assertEqual(len(feasible), 4)
        counts = {
            tuple(edge): len(transition_pairs(tuple(edge), self.fixture))
            for edge in self.fixture["edges"]
        }
        self.assertEqual(
            counts,
            {(0, 1): 2, (0, 2): 0, (0, 3): 0, (1, 2): 0, (1, 3): 0, (2, 3): 2},
        )

    def test_all_differential_delta_predicate_and_exact_k_cases(self) -> None:
        report = differential_audit(self.fixture)
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["portfolio_edge_cases"], 36)
        self.assertEqual(report["constraint_row_cases"], 72)
        self.assertTrue(all(report["checks"].values()))

    def test_gray_path_and_coherent_cache_update(self) -> None:
        compiled = compile_edge((0, 1), self.fixture)
        pair = compiled["pairs"][0]
        left, right = int(pair["left_basis"]), int(pair["right_basis"])
        path = gray_path(left, right, 10)
        self.assertEqual(path[0], left)
        self.assertEqual(path[-1], right)
        self.assertTrue(all((a ^ b).bit_count() == 1 for a, b in zip(path, path[1:])))

        beta = math.pi / 4.0
        actual = apply_gate_sequence({left: 1.0 + 0.0j}, compiled["gates"], beta)
        self.assertEqual(set(actual), {left, right})
        self.assertAlmostEqual(actual[left].real, math.cos(beta), places=12)
        self.assertAlmostEqual(actual[right].imag, -math.sin(beta), places=12)
        for index in actual:
            decoded = decode_basis_state(index, self.fixture)
            self.assertTrue(decoded["cache_consistent"])
            self.assertTrue(decoded["exact_k"])
            self.assertTrue(decoded["feasible"])

    def test_full_domain_unitarity_gram_and_identity_evidence(self) -> None:
        compiler = self.artifact["compiler_evidence"]
        self.assertTrue(compiler["passed"], compiler)
        self.assertEqual(compiler["basis_columns_checked"], 18_432)
        self.assertEqual(compiler["complete_layer_basis_columns_checked"], 3_072)
        self.assertEqual(compiler["complete_layer_gram_entries_checked"], 3_145_728)
        self.assertLessEqual(compiler["maximum_action_error"], NUMERIC_TOLERANCE)
        self.assertLessEqual(compiler["maximum_roundtrip_error"], NUMERIC_TOLERANCE)
        self.assertLessEqual(compiler["complete_layer_maximum_gram_error"], NUMERIC_TOLERANCE)
        self.assertTrue(compiler["checks"]["all_non_target_basis_states_are_identity"])
        self.assertTrue(compiler["checks"]["logical_ir_replay_is_deterministic"])
        self.assertTrue(all(compiler["checks"].values()))

    def test_logical_ledger_is_exact_and_does_not_invent_cnot(self) -> None:
        ledger = resource_ledger(self.fixture)
        totals = ledger["complete_edge_scan"]
        self.assertEqual(ledger["ir_basis"], ["PATTERN_MCX", "PATTERN_MCRX"])
        self.assertEqual(totals["two_level_pair_count"], 4)
        self.assertEqual(totals["pattern_mcx_count"], 36)
        self.assertEqual(totals["pattern_mcrx_count"], 4)
        self.assertEqual(totals["logical_gate_count"], 40)
        self.assertEqual(totals["maximum_control_count"], 9)
        self.assertEqual(totals["ancilla_qubits"], 0)
        self.assertEqual(totals["scratch_qubits"], 0)
        self.assertEqual(ledger["selected_model_cnot"], "NOT_ESTIMATED")
        self.assertEqual(ledger["n40_projection"], "NOT_RUN")
        self.assertFalse(ledger["hardware_executable"])

    def test_four_proof_carrying_transition_rows_are_sealed(self) -> None:
        transitions = self.artifact["coherent_transition_ledger"]
        self.assertEqual(transitions["transition_count"], 4)
        self.assertEqual(len(transitions["rows"]), 4)
        for row in transitions["rows"]:
            self.assertEqual(row["reference_action_state"], "PASSED_ALL_REGISTERED_BETAS")
            self.assertEqual(
                row["roundtrip_state"], "PASSED_ALL_1024_BASIS_COLUMNS_PER_BETA"
            )
            self.assertEqual(row["off_target_identity_state"], "PASSED")
            self.assertEqual(row["clean_scratch_state"], "PASSED_ZERO_ANCILLA_ZERO_SCRATCH")
            self.assertEqual(len(row["pair_ir_sha256"]), 64)

    def test_artifact_decision_boundary_tamper_and_create_once(self) -> None:
        self.assertTrue(validate_v37_artifact(self.artifact)["valid"])
        self.assertEqual(
            self.artifact["decisions"]["overall"],
            "SMALL_INSTANCE_REVERSIBLE_PROTOTYPE_PASSED",
        )
        self.assertEqual(
            self.artifact["decisions"]["production_n40_compiler"],
            "N40_REWRITE_ADMISSION_BLOCKED",
        )
        self.assertFalse(self.artifact["claim_boundary"]["hardware_executable"])
        tampered = copy.deepcopy(self.artifact)
        tampered["claim_boundary"]["qpu_jobs_submitted"] = 1
        self.assertFalse(validate_v37_artifact(tampered)["valid"])
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "SEALED_V37_TEST.json"
            first = seal_v37_artifact(target)
            second = seal_v37_artifact(target)
            self.assertTrue(first["created"])
            self.assertFalse(second["created"])
            self.assertEqual(first["artifact"]["artifact_sha256"], second["artifact"]["artifact_sha256"])

    def test_rehashed_nested_scientific_tampering_fails_closed(self) -> None:
        def reseal(candidate: dict) -> dict:
            candidate["artifact_sha256"] = canonical_json_sha256(
                {key: value for key, value in candidate.items() if key != "artifact_sha256"}
            )
            return candidate

        candidates: list[dict] = []

        source = copy.deepcopy(self.artifact)
        source["source_sha256"] = "0" * 64
        candidates.append(reseal(source))

        fixture = copy.deepcopy(self.artifact)
        fixture["fixture"]["constraint_rows"][0]["coefficients"][0] += 1
        fixture["fixture"]["fixture_sha256"] = canonical_json_sha256(
            {
                key: value
                for key, value in fixture["fixture"].items()
                if key != "fixture_sha256"
            }
        )
        candidates.append(reseal(fixture))

        compiler = copy.deepcopy(self.artifact)
        compiler["compiler_evidence"]["basis_columns_checked"] = 1
        candidates.append(reseal(compiler))

        transition = copy.deepcopy(self.artifact)
        transition["coherent_transition_ledger"]["rows"][1] = copy.deepcopy(
            transition["coherent_transition_ledger"]["rows"][0]
        )
        transition_core = {
            key: value
            for key, value in transition["coherent_transition_ledger"].items()
            if key != "coherent_transition_ledger_sha256"
        }
        transition["coherent_transition_ledger"][
            "coherent_transition_ledger_sha256"
        ] = canonical_json_sha256(transition_core)
        candidates.append(reseal(transition))

        parent = copy.deepcopy(self.artifact)
        parent["parent"]["v36_artifact_sha256"] = "0" * 64
        candidates.append(reseal(parent))

        ledger = copy.deepcopy(self.artifact)
        ledger["resource_ledger"]["selected_model_cnot"] = 1
        candidates.append(reseal(ledger))

        for candidate in candidates:
            with self.subTest(surface=next(
                key for key in candidate if candidate.get(key) != self.artifact.get(key)
            )):
                report = validate_v37_artifact(candidate)
                self.assertFalse(report["valid"], report)
                self.assertTrue(
                    any("Recomputed V3.7 evidence mismatch" in error for error in report["errors"]),
                    report,
                )

    def test_full_validation_ladder(self) -> None:
        report = run_v37_validation()
        self.assertTrue(report["overall_pass"], report)
        self.assertEqual(len(report["checks"]), 18)
        self.assertTrue(all(report["checks"].values()))


if __name__ == "__main__":
    unittest.main()
