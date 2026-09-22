"""Regression tests for the V3.5 zero-job backend admission core."""

from __future__ import annotations

import copy
import unittest

from .phase3_backend_admission import (
    BLOCKED,
    NOT_RUN,
    PASS,
    REJECTED,
    admit_backend,
    attach_snapshot_digest,
    canonical_json_sha256,
    load_v35_spec,
    validate_admission_artifact,
    verify_v34_parent,
)
from .phase3_v35_validation import (
    FIXED_AS_OF,
    build_sealed_negative_result,
    run_backend_admission_validation,
    synthetic_candidate,
    synthetic_snapshot,
)


class BackendAdmissionV35Tests(unittest.TestCase):
    def evaluate(self, snapshot=None, candidate=None, expected=None):
        snapshot = snapshot if snapshot is not None else synthetic_snapshot()
        candidate = candidate if candidate is not None else synthetic_candidate()
        expected = expected if expected is not None else snapshot["snapshot_sha256"]
        return admit_backend(
            snapshot,
            candidate,
            expected_snapshot_sha256=expected,
            as_of_utc=FIXED_AS_OF,
        )

    def test_spec_self_hash_and_prohibitions(self) -> None:
        spec = load_v35_spec()
        core = {
            key: value
            for key, value in spec.items()
            if key not in {"v35_spec_sha", "v35_spec_sha256"}
        }
        self.assertEqual(spec["v35_spec_sha256"], canonical_json_sha256(core))
        self.assertEqual(spec["research_classification"], "RESEARCH_ONLY")
        self.assertEqual(spec["admission_scope"]["credential_access"], "PROHIBITED")
        self.assertEqual(spec["admission_scope"]["hardware_execution"], "PROHIBITED")

    def test_v34_parent_is_byte_and_semantic_exact(self) -> None:
        report = verify_v34_parent(load_v35_spec())
        self.assertEqual(report["state"], PASS, report)

    def test_nominal_offline_evidence_passes_metrics_but_parent_limit_rejects(self) -> None:
        artifact = self.evaluate()
        provider = artifact["gates"]["parent_provider_2q_gate_model_screen"]
        self.assertEqual(provider["state"], REJECTED)
        self.assertEqual(provider["stage"], "PRETRANSPILATION_MODEL_SCREEN")
        self.assertAlmostEqual(provider["observed"]["multiple_of_limit"], 29_881.106542)
        metric_names = {
            "snapshot_authentication",
            "backend_identity_and_provenance",
            "calibration_freshness",
            "transpilation_metadata",
            "logical_width",
            "connected_capacity",
            "routed_width",
            "routed_depth",
            "routed_two_qubit_count",
            "calibration_two_qubit_error",
            "rotation_synthesis",
            "noise_aware_survival_proxy",
        }
        self.assertTrue(all(artifact["gates"][name]["state"] == PASS for name in metric_names))
        self.assertTrue(artifact["decisions"]["offline_backend_admission"].startswith("REJECTED"))

    def test_snapshot_requires_independent_digest_and_detects_tamper(self) -> None:
        snapshot = synthetic_snapshot()
        missing = self.evaluate(snapshot, expected="")
        self.assertEqual(missing["gates"]["snapshot_authentication"]["state"], BLOCKED)
        digest = snapshot["snapshot_sha256"]
        snapshot["backend"]["num_qubits"] += 1
        tampered = self.evaluate(snapshot, expected=digest)
        self.assertEqual(tampered["gates"]["snapshot_authentication"]["state"], BLOCKED)

    def test_staleness_and_future_timestamp_fail_closed(self) -> None:
        stale = synthetic_snapshot()
        stale["calibration"]["captured_at_utc"] = "2026-09-01T10:00:00+00:00"
        stale["calibration"]["properties_last_update_utc"] = "2026-09-01T09:59:00+00:00"
        for row in stale["calibration"]["two_qubit_gate_errors"]:
            row["measured_at_utc"] = "2026-09-01T09:59:00+00:00"
        stale["provenance"]["exported_at_utc"] = "2026-09-01T10:01:00+00:00"
        stale = attach_snapshot_digest(stale)
        self.assertEqual(self.evaluate(stale)["gates"]["calibration_freshness"]["state"], REJECTED)
        future = synthetic_snapshot()
        future["calibration"]["captured_at_utc"] = "2026-09-06T11:00:00+00:00"
        future = attach_snapshot_digest(future)
        self.assertEqual(self.evaluate(future)["gates"]["calibration_freshness"]["state"], BLOCKED)

    def test_width_depth_and_two_qubit_count_budgets(self) -> None:
        narrow = synthetic_snapshot()
        narrow["backend"]["num_qubits"] = 117
        narrow = attach_snapshot_digest(narrow)
        self.assertEqual(self.evaluate(narrow)["gates"]["logical_width"]["state"], REJECTED)
        deep = synthetic_candidate()
        deep["transpilation"]["routed_depth"] = 1_000_001
        self.assertEqual(self.evaluate(candidate=deep)["gates"]["routed_depth"]["state"], REJECTED)
        large = synthetic_candidate()
        large["transpilation"]["routed_two_qubit_gates"] = 2_000_001
        self.assertEqual(self.evaluate(candidate=large)["gates"]["routed_two_qubit_count"]["state"], REJECTED)

    def test_route_specific_error_coverage_and_basis(self) -> None:
        noisy = synthetic_snapshot()
        noisy["calibration"]["two_qubit_gate_errors"][0]["error"] = 0.031
        noisy = attach_snapshot_digest(noisy)
        self.assertEqual(self.evaluate(noisy)["gates"]["calibration_two_qubit_error"]["state"], REJECTED)
        incomplete = synthetic_snapshot()
        incomplete["calibration"]["two_qubit_gate_errors"] = incomplete["calibration"]["two_qubit_gate_errors"][:1]
        incomplete = attach_snapshot_digest(incomplete)
        self.assertEqual(self.evaluate(incomplete)["gates"]["calibration_two_qubit_error"]["state"], REJECTED)
        bad_basis = synthetic_candidate()
        bad_basis["transpilation"]["target_basis_gates"].append("cx")
        self.assertEqual(self.evaluate(candidate=bad_basis)["gates"]["transpilation_metadata"]["state"], REJECTED)

    def test_provider_status_connected_capacity_and_seed_contract(self) -> None:
        wrong_provider = synthetic_snapshot()
        wrong_provider["backend"]["provider_id"] = "UNREGISTERED_PROVIDER"
        wrong_provider = attach_snapshot_digest(wrong_provider)
        self.assertEqual(
            self.evaluate(wrong_provider)["gates"]["backend_identity_and_provenance"]["state"],
            REJECTED,
        )
        inactive = synthetic_snapshot()
        inactive["backend"]["status_msg"] = "internal"
        inactive = attach_snapshot_digest(inactive)
        self.assertEqual(
            self.evaluate(inactive)["gates"]["backend_identity_and_provenance"]["state"],
            REJECTED,
        )
        disconnected = synthetic_snapshot()
        disconnected["backend"]["coupling_map"] = [
            [index, index + 1] for index in range(116)
        ] + [[index, index + 1] for index in range(117, 126)]
        disconnected = attach_snapshot_digest(disconnected)
        self.assertEqual(
            self.evaluate(disconnected)["gates"]["connected_capacity"]["state"],
            REJECTED,
        )
        unregistered_seed = synthetic_candidate()
        unregistered_seed["transpilation"]["routing_seed"] = 12
        self.assertEqual(
            self.evaluate(candidate=unregistered_seed)["gates"]["transpilation_metadata"]["state"],
            REJECTED,
        )

    def test_snapshot_timestamp_and_calibration_identity_contract(self) -> None:
        no_calibration_id = synthetic_snapshot()
        del no_calibration_id["calibration"]["calibration_id"]
        no_calibration_id = attach_snapshot_digest(no_calibration_id)
        self.assertEqual(
            self.evaluate(no_calibration_id)["gates"]["calibration_freshness"]["state"],
            BLOCKED,
        )
        delayed_export = synthetic_snapshot()
        delayed_export["provenance"]["exported_at_utc"] = "2026-09-05T11:00:00+00:00"
        delayed_export = attach_snapshot_digest(delayed_export)
        self.assertEqual(
            self.evaluate(delayed_export)["gates"]["calibration_freshness"]["state"],
            BLOCKED,
        )
        missing_metric_time = synthetic_snapshot()
        del missing_metric_time["calibration"]["two_qubit_gate_errors"][0]["measured_at_utc"]
        missing_metric_time = attach_snapshot_digest(missing_metric_time)
        self.assertEqual(
            self.evaluate(missing_metric_time)["gates"]["calibration_freshness"]["state"],
            BLOCKED,
        )

    def test_rotation_inventory_and_error_budget(self) -> None:
        absent = synthetic_candidate()
        absent["rotations"]["status"] = "NOT_RUN"
        self.assertEqual(self.evaluate(candidate=absent)["gates"]["rotation_synthesis"]["state"], NOT_RUN)
        incomplete = synthetic_candidate()
        incomplete["rotations"]["synthesized_rotation_count"] = 1559
        self.assertEqual(self.evaluate(candidate=incomplete)["gates"]["rotation_synthesis"]["state"], BLOCKED)
        inaccurate = synthetic_candidate()
        inaccurate["rotations"]["max_approximation_error"] = 7e-7
        self.assertEqual(self.evaluate(candidate=inaccurate)["gates"]["rotation_synthesis"]["state"], REJECTED)
        wrong_lane = synthetic_candidate()
        wrong_lane["rotations"]["evidence_lane"] = "IBM_NATIVE_T_COUNT"
        self.assertEqual(
            self.evaluate(candidate=wrong_lane)["gates"]["rotation_synthesis"]["state"],
            BLOCKED,
        )
        inconsistent_sum = synthetic_candidate()
        inconsistent_sum["rotations"]["aggregate_approximation_error"] = 0.0001
        self.assertEqual(
            self.evaluate(candidate=inconsistent_sum)["gates"]["rotation_synthesis"]["state"],
            BLOCKED,
        )

    def test_absent_bundle_preserves_independent_negative_and_zero_jobs(self) -> None:
        artifact = admit_backend(
            None,
            None,
            expected_snapshot_sha256=None,
            as_of_utc=FIXED_AS_OF,
        )
        self.assertEqual(artifact["gates"]["snapshot_authentication"]["state"], BLOCKED)
        self.assertEqual(artifact["gates"]["transpilation_metadata"]["state"], NOT_RUN)
        self.assertEqual(artifact["gates"]["parent_provider_2q_gate_model_screen"]["state"], REJECTED)
        self.assertEqual(artifact["decisions"]["qpu_jobs_submitted"], 0)
        self.assertFalse(artifact["claim_boundary"]["credentials_read"])
        self.assertEqual(artifact["claim_boundary"]["network_calls"], 0)

    def test_artifact_integrity_and_tamper_detection(self) -> None:
        artifact = self.evaluate()
        self.assertTrue(validate_admission_artifact(artifact)["valid"])
        tampered = copy.deepcopy(artifact)
        tampered["decisions"]["quantum_advantage"] = "CLAIMED"
        report = validate_admission_artifact(tampered)
        self.assertFalse(report["valid"])
        self.assertTrue(report["errors"])

    def test_canonical_negative_result_contains_no_synthetic_backend(self) -> None:
        artifact = build_sealed_negative_result()
        self.assertTrue(validate_admission_artifact(artifact)["valid"])
        self.assertEqual(artifact["evidence"]["mode"], "NONE")
        self.assertIsNone(artifact["backend"]["backend_name"])
        self.assertFalse(artifact["release_evidence"]["synthetic_fixture_in_scientific_artifact"])
        self.assertEqual(
            artifact["decisions"]["pretranspilation_model_screen"],
            "REJECTED_MODEL_SCREEN",
        )
        self.assertTrue(
            artifact["decisions"]["offline_backend_admission"].startswith(
                "REJECTED_MODEL_SCREEN"
            )
        )

    def test_full_validation_ladder(self) -> None:
        report = run_backend_admission_validation()
        self.assertTrue(report["overall_pass"], report)
        self.assertEqual(len(report["checks"]), 16)
        self.assertTrue(all(report["checks"].values()))


if __name__ == "__main__":
    unittest.main()
