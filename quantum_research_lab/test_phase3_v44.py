"""Scientific and boundary tests for Quantum Lab V4.4."""

from __future__ import annotations

import copy
import unittest

from .phase3_v44_named_backend_routing import (
    EXPECTED_SEEDS,
    EXPECTED_WIDTHS,
    TARGET_QUBITS,
    authenticate_v43_parent,
    canonical_json_sha256,
    capacity_precheck,
    load_v44_snapshot,
    load_v44_spec,
    load_v44_toolchain,
    read_json_strict,
)
from .phase3_v44_validation import (
    EXPECTED_ARTIFACT_SHA256,
    EXPECTED_CANARY_BUNDLE_SHA256,
    EXPECTED_CANARY_ROOT_SHA256,
    EXPECTED_CAPACITY_PRECHECK_SHA256,
    EXPECTED_CHECK_COUNT,
    _paths,
    run_v44_validation,
    validate_v44_artifact,
)


class QuantumLabV44ScientificTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.paths = _paths()
        cls.artifact = read_json_strict(cls.paths["artifact"])

    def test_01_spec_is_preregistered_and_bounded(self) -> None:
        spec = load_v44_spec()
        self.assertEqual(spec["chronology"]["result_state_at_seal"], "NOT_EVALUATED")
        self.assertEqual(spec["claim_boundary"]["research_classification"], "RESEARCH_ONLY")

    def test_02_snapshot_is_exact_offline_target(self) -> None:
        snapshot = load_v44_snapshot()
        self.assertEqual(snapshot["target"]["num_qubits"], 156)
        self.assertFalse(snapshot["evidence_boundary"]["snapshot_is_current_hardware_evidence"])

    def test_03_toolchain_is_pinned_and_zero_job(self) -> None:
        manifest = load_v44_toolchain()
        self.assertEqual(manifest["environment"]["qiskit"], "2.5.2")
        self.assertEqual(manifest["provider_boundary"]["qpu_jobs_submitted"], 0)

    def test_04_exact_v43_parent_authenticates(self) -> None:
        parent = authenticate_v43_parent()
        self.assertTrue(parent["valid"], parent)
        self.assertEqual(parent["immutable_file_count"], 191)

    def test_05_capacity_seed_order_and_widths_are_exact(self) -> None:
        capacity = capacity_precheck()
        rows = capacity["capacity_rows"]
        self.assertEqual([row["seed"] for row in rows], list(EXPECTED_SEEDS))
        self.assertEqual([row["logical_qubits"] for row in rows], list(EXPECTED_WIDTHS))

    def test_06_capacity_deficits_are_exact(self) -> None:
        rows = capacity_precheck()["capacity_rows"]
        self.assertEqual(
            [row["capacity_deficit_qubits"] for row in rows],
            [-174, -175, -171, -172, -173, -175, -183, -178],
        )

    def test_07_persistent_floor_alone_exceeds_target(self) -> None:
        floor = capacity_precheck()["persistent_register_floor"]
        self.assertEqual(floor["persistent_register_floor_qubits"], 160)
        self.assertEqual(floor["capacity_deficit_qubits"], -4)

    def test_08_all_full_workloads_are_rejected_before_transpilation(self) -> None:
        capacity = capacity_precheck()
        self.assertTrue(capacity["all_eight_full_workloads_rejected_before_transpilation"])
        self.assertEqual(capacity["full_workload_transpilation_attempts"], 0)
        self.assertEqual(capacity["full_workload_routing_attempts"], 0)

    def test_09_rejected_metrics_are_not_synthetic_zeroes(self) -> None:
        for row in capacity_precheck()["capacity_rows"]:
            self.assertEqual(row["full_workload_routed_depth"], "NOT_RUN_CAPACITY_PRECHECK_REJECTED")
            self.assertEqual(row["full_workload_native_gate_counts"], "NOT_RUN_CAPACITY_PRECHECK_REJECTED")

    def test_10_capacity_precheck_has_registered_self_hash(self) -> None:
        capacity = capacity_precheck()
        self.assertEqual(capacity["capacity_precheck_sha256"], EXPECTED_CAPACITY_PRECHECK_SHA256)
        self.assertEqual(
            capacity["capacity_precheck_sha256"],
            canonical_json_sha256({key: value for key, value in capacity.items() if key != "capacity_precheck_sha256"}),
        )

    def test_11_artifact_semantic_hash_is_exact(self) -> None:
        self.assertEqual(self.artifact["artifact_sha256"], EXPECTED_ARTIFACT_SHA256)
        self.assertEqual(
            self.artifact["artifact_sha256"],
            canonical_json_sha256({key: value for key, value in self.artifact.items() if key != "artifact_sha256"}),
        )

    def test_12_artifact_preserves_parent_crosslinks(self) -> None:
        parent = self.artifact["parent"]
        self.assertEqual(parent["immutable_file_count"], 191)
        self.assertTrue(parent["immutable_files_exact"])
        self.assertEqual(parent["maximum_logical_qubits"], 339)

    def test_13_two_clean_process_canary_replays_are_identical(self) -> None:
        evidence = self.artifact["canary_evidence"]
        self.assertEqual(evidence["clean_process_replay_count"], 2)
        self.assertEqual(evidence["clean_process_replay_sha256"], [EXPECTED_CANARY_BUNDLE_SHA256] * 2)
        self.assertTrue(evidence["replay_stable"])

    def test_14_five_canaries_pass_target_isa_and_coupling(self) -> None:
        bundle = self.artifact["canary_evidence"]["canonical_canary_bundle"]
        self.assertEqual(bundle["accepted_canary_count"], 5)
        self.assertTrue(bundle["all_accepted_canaries_isa_and_coupling_valid"])
        self.assertEqual(bundle["canonical_result_root_sha256"], EXPECTED_CANARY_ROOT_SHA256)

    def test_15_157_qubit_negative_canary_is_retained(self) -> None:
        negative = self.artifact["canary_evidence"]["canonical_canary_bundle"]["mandatory_negative_canary"]
        self.assertEqual(negative["input_logical_qubits"], TARGET_QUBITS + 1)
        self.assertEqual(negative["status"], "EXPECTED_REJECTION")
        self.assertEqual(negative["exception_class"], "TranspilerError")

    def test_16_claim_boundary_is_zero_job_and_non_extrapolating(self) -> None:
        boundary = self.artifact["claim_boundary"]
        self.assertEqual(boundary["provider_calls"], 0)
        self.assertEqual(boundary["network_calls"], 0)
        self.assertEqual(boundary["qpu_jobs_submitted"], 0)
        self.assertFalse(boundary["hardware_executable"])
        self.assertEqual(boundary["quantum_advantage"], "NOT_CLAIMED")

    def test_17_independent_validation_passes_all_checks(self) -> None:
        report = run_v44_validation()
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["counts"], {"checks_passed": EXPECTED_CHECK_COUNT, "checks_total": EXPECTED_CHECK_COUNT})

    def test_18_semantically_rehashed_boundary_tamper_fails_closed(self) -> None:
        tampered = copy.deepcopy(self.artifact)
        tampered["claim_boundary"]["hardware_executable"] = True
        tampered["artifact_sha256"] = canonical_json_sha256(
            {key: value for key, value in tampered.items() if key != "artifact_sha256"}
        )
        report = validate_v44_artifact(tampered)
        self.assertFalse(report["passed"])
        self.assertIn("artifact_semantic_identity", report["failed_checks"])
        self.assertIn("research_only_hardware_performance_advantage_boundary", report["failed_checks"])


if __name__ == "__main__":
    unittest.main()
