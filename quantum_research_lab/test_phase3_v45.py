"""Scientific, liveness and claim-boundary tests for Quantum Lab V4.5."""

from __future__ import annotations

import copy
import unittest

from .phase3_v45_validation import (
    EXPECTED_ARTIFACT_SHA256,
    EXPECTED_CERTIFICATE_SHA256,
    EXPECTED_CHECK_COUNT,
    EXPECTED_SEEDS,
    EXPECTED_WIDTHS,
    _paths,
    _static_contract,
    run_v45_validation,
    validate_v45_artifact,
)
from .phase3_v45_width_proof_checker import (
    K as CHECKER_CARDINALITY,
    canonical_json_sha256,
    read_json_strict,
    validate_v45_artifact as run_independent_checker,
)


class QuantumLabV45ScientificTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.paths = _paths()
        cls.artifact = read_json_strict(cls.paths["artifact"])
        cls.certificate = read_json_strict(cls.paths["certificate"])

    def test_01_spec_is_result_blind_and_research_only(self) -> None:
        spec = read_json_strict(self.paths["spec"])
        self.assertEqual(spec["chronology"]["result_state_at_seal"], "NOT_EVALUATED")
        self.assertEqual(spec["acceptance_contract"]["result_state_at_protocol_seal"], "NOT_EVALUATED")
        self.assertEqual(spec["claim_boundary"]["research_classification"], "RESEARCH_ONLY")
        self.assertEqual(CHECKER_CARDINALITY, 10)

    def test_02_exact_v44_parent_closure_is_recorded(self) -> None:
        parent = self.artifact["parent"]
        self.assertEqual(parent["immutable_file_count"], 209)
        self.assertTrue(parent["immutable_files_exact"])
        self.assertEqual(parent["overall_decision"], "V44_FAKE_MARRAKESH_CAPACITY_REJECTED_CANARY_PIPELINE_VALIDATED_ZERO_JOB")

    def test_03_certificate_has_exact_identity(self) -> None:
        self.assertEqual(self.certificate["certificate_sha256"], EXPECTED_CERTIFICATE_SHA256)
        self.assertEqual(
            self.certificate["certificate_sha256"],
            canonical_json_sha256({key: value for key, value in self.certificate.items() if key != "certificate_sha256"}),
        )

    def test_04_seed_order_and_widths_are_exact(self) -> None:
        rows = self.artifact["seed_materializations"]
        self.assertEqual([row["seed"] for row in rows], list(EXPECTED_SEEDS))
        self.assertEqual([row["register_layout"]["total_qubits"] for row in rows], list(EXPECTED_WIDTHS))

    def test_05_maximum_width_and_margin_are_exact(self) -> None:
        aggregate = self.artifact["aggregate"]
        self.assertEqual(aggregate["maximum_logical_qubits"], 145)
        self.assertEqual(aggregate["minimum_capacity_margin_qubits"], 11)
        self.assertTrue(aggregate["all_eight_widths_fit_156"])

    def test_06_all_register_allocations_are_contiguous_and_nonoverlapping(self) -> None:
        for row in self.artifact["seed_materializations"]:
            layout = row["register_layout"]
            ids = [qubit for register in layout["registers"] for qubit in register["qubit_ids"]]
            self.assertEqual(ids, list(range(layout["total_qubits"])))
            self.assertEqual(len(ids), len(set(ids)))
            self.assertEqual(layout["total_qubits"], 67 + 2 * layout["arithmetic_width"])

    def test_07_all_materialized_streams_are_self_hashed(self) -> None:
        for row in self.artifact["seed_materializations"]:
            stream = row["stream_manifest"]
            self.assertEqual(
                stream["stream_manifest_sha256"],
                canonical_json_sha256({key: value for key, value in stream.items() if key != "stream_manifest_sha256"}),
            )

    def test_08_all_materialized_streams_respect_cnot_budget(self) -> None:
        counts = [row["stream_manifest"]["elementary_counts"]["CX"] for row in self.artifact["seed_materializations"]]
        self.assertTrue(all(0 <= count <= 2_500_000 for count in counts), counts)
        self.assertEqual(self.artifact["aggregate"]["cnot_budget_pass_count"], 8)

    def test_09_two_binary_coin_rings_have_40_edges_each(self) -> None:
        for row in self.artifact["seed_materializations"]:
            self.assertEqual(row["stream_manifest"]["macro_counts"]["BINARY_TWO_LEVEL_RX"], 80)
            self.assertEqual(row["semantic_trace_certificate"]["binary_domain"]["valid"], [0, 39])
            self.assertEqual(row["semantic_trace_certificate"]["binary_domain"]["invalid_encodings"], list(range(40, 64)))

    def test_10_relative_phase_forward_and_adjoint_counts_match(self) -> None:
        for row in self.artifact["seed_materializations"]:
            macros = row["stream_manifest"]["macro_counts"]
            self.assertGreater(macros["RELATIVE_PHASE_C7X"], 0)
            self.assertEqual(macros["RELATIVE_PHASE_C7X"], macros["RELATIVE_PHASE_C7X_DAGGER"])

    def test_11_liveness_ledger_requires_exact_adjoint_and_clean_exit(self) -> None:
        for row in self.artifact["seed_materializations"]:
            liveness = row["liveness"]
            self.assertEqual(liveness["reset_instruction_count"], 0)
            self.assertEqual(
                liveness["relative_phase_compute_use_uncompute"]["uncompute"],
                "EXPLICIT_EXACT_ADJOINT_IN_REVERSE_ORDER",
            )
            self.assertIn("B_DAGGER_U_B", liveness["relative_phase_compute_use_uncompute"]["exactness_argument"])

    def test_12_source_ast_has_explicit_adjoint_bennett_and_selector_structure(self) -> None:
        static = _static_contract(self.paths["source"], self.paths["checker"], self.paths["root"] / "quantum_research_lab/phase3_v45_validation.py")
        self.assertTrue(static["exact_adjoint_structure"], static)
        self.assertTrue(static["bennett_reverse_structure"], static)
        self.assertTrue(static["selector_structure"], static)
        self.assertTrue(static["two_coin_40_edge_structure"], static)

    def test_13_every_semantic_sample_exhausts_1600_address_pairs(self) -> None:
        for row in self.artifact["seed_materializations"]:
            certificate = row["semantic_trace_certificate"]
            self.assertGreaterEqual(certificate["sample_count"], 1)
            for sample in certificate["samples"]:
                self.assertEqual(sample["address_pair_count"], 1600)
                self.assertTrue(sample["all_valid_binary_address_pairs_exhausted"])

    def test_14_off_promise_negative_witness_is_retained(self) -> None:
        witness = self.artifact["mandatory_off_promise_control"]
        self.assertEqual(witness["status"], "OFF_PROMISE_CLEANUP_REJECTED_WITH_WITNESS")
        self.assertTrue(witness["witness_detected"])
        self.assertEqual(witness["retained_feasible_flag_after_reverse"], 1)

    def test_15_standard_library_checker_accepts(self) -> None:
        result = run_independent_checker(self.artifact, root=self.paths["root"])
        self.assertTrue(result["valid"], result)
        self.assertGreaterEqual(result["check_count"], 250)

    def test_16_full_independent_validation_passes_51_checks(self) -> None:
        result = run_v45_validation()
        self.assertTrue(result["passed"], result)
        self.assertEqual(
            result["counts"],
            {"checks_passed": EXPECTED_CHECK_COUNT, "checks_total": EXPECTED_CHECK_COUNT},
        )
        self.assertEqual(result["artifact_sha256"], EXPECTED_ARTIFACT_SHA256)

    def test_17_boundary_is_zero_job_and_non_extrapolating(self) -> None:
        boundary = self.artifact["claim_boundary"]
        self.assertFalse(boundary["provider_sdk_imported"])
        self.assertFalse(boundary["provider_credentials_read"])
        self.assertEqual(boundary["credential_reads"], 0)
        self.assertEqual(boundary["provider_calls"], 0)
        self.assertEqual(boundary["network_calls"], 0)
        self.assertEqual(boundary["qpu_jobs_submitted"], 0)
        self.assertFalse(boundary["hardware_executable"])
        self.assertEqual(boundary["quantum_advantage"], "NOT_CLAIMED")

    def test_18_routing_and_transpilation_are_explicitly_not_run(self) -> None:
        boundary = self.artifact["claim_boundary"]
        self.assertEqual(boundary["full_workload_routing"], "NOT_RUN_IN_V4_5")
        self.assertEqual(boundary["full_workload_transpilation"], "NOT_RUN_IN_V4_5")
        self.assertEqual(boundary["calibration_aware_fidelity"], "NOT_TESTED")
        self.assertEqual(boundary["optimization_performance"], "NOT_TESTED")

    def test_19_semantically_rehashed_hardware_claim_tamper_fails_closed(self) -> None:
        tampered = copy.deepcopy(self.artifact)
        tampered["claim_boundary"]["hardware_executable"] = True
        tampered["artifact_sha256"] = canonical_json_sha256(
            {key: value for key, value in tampered.items() if key != "artifact_sha256"}
        )
        result = validate_v45_artifact(tampered)
        self.assertFalse(result["passed"])
        self.assertIn("artifact_semantic_identity", result["failed_checks"])
        self.assertIn("no_hardware_performance_or_advantage_claim", result["failed_checks"])

    def test_20_semantically_rehashed_width_tamper_fails_closed(self) -> None:
        tampered = copy.deepcopy(self.artifact)
        row = tampered["seed_materializations"][0]
        row["register_layout"]["total_qubits"] = 136
        row["register_layout"]["register_map_sha256"] = canonical_json_sha256(
            {key: value for key, value in row["register_layout"].items() if key != "register_map_sha256"}
        )
        row["seed_materialization_sha256"] = canonical_json_sha256(
            {key: value for key, value in row.items() if key != "seed_materialization_sha256"}
        )
        tampered["artifact_sha256"] = canonical_json_sha256(
            {key: value for key, value in tampered.items() if key != "artifact_sha256"}
        )
        result = validate_v45_artifact(tampered)
        self.assertFalse(result["passed"])
        self.assertIn("artifact_semantic_identity", result["failed_checks"])
        self.assertIn("all_eight_widths_exact", result["failed_checks"])
        self.assertIn("allocation_formula_all_seeds", result["failed_checks"])


if __name__ == "__main__":
    unittest.main()
