"""Scientific and security tests for the V5.0 control plane."""

from __future__ import annotations

import ast
import copy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import unittest

from ..engine.checker import (
    EXPECTED_ARTIFACT_RAW_SHA256,
    EXPECTED_CHECK_COUNT,
    validate_artifact,
)
from ..engine.evaluator import (
    ARTIFACT,
    EXPECTED_SEEDS,
    authenticate_parent,
    build_control_plane_artifact,
    default_root,
)
from ..engine.evidence import (
    EXPECTED_TOPOLOGY_SHA256,
    load_evidence_cohort,
    raw_file_sha256,
    read_json_strict,
    semantic_sha256,
)
from ..engine.provider_gate import ProviderGateClosed, authenticated_status, require_provider_access
from ..engine.validation import REPORT, run_validation


ROOT = default_root()
ARTIFACT_PATH = ROOT / ARTIFACT


def _reseal_tampered_artifact(artifact: dict[str, object]) -> str:
    artifact["artifact_sha256"] = semantic_sha256(
        artifact, exclude=("artifact_sha256",)
    )
    encoded = (
        json.dumps(
            artifact,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class QuantumLabV50ScienceTests(unittest.TestCase):
    def test_01_parent_v49_authenticates(self) -> None:
        freeze, artifact, report = authenticate_parent(ROOT)
        self.assertEqual(freeze["freeze_contract_sha256"], "f5168ff42d8a72111a0e740e8675203e1382c0bcb6a23d1d12b9e9c3c9d2f597")
        self.assertEqual(artifact["decisions"]["overall"], "V49_NOT_EVALUABLE_INSUFFICIENT_AUTHENTIC_EPOCHS")
        self.assertTrue(report["valid"])

    def test_02_build_is_deterministic_and_matches_sealed_artifact(self) -> None:
        first = build_control_plane_artifact(ROOT)
        second = build_control_plane_artifact(ROOT)
        self.assertEqual(first, second)
        self.assertEqual(first, read_json_strict(ARTIFACT_PATH))

    def test_03_artifact_self_hash_is_exact(self) -> None:
        artifact = read_json_strict(ARTIFACT_PATH)
        self.assertEqual(
            artifact["artifact_sha256"],
            semantic_sha256(artifact, exclude=("artifact_sha256",)),
        )

    def test_04_independent_checker_passes_all_checks(self) -> None:
        artifact = read_json_strict(ARTIFACT_PATH)
        report = validate_artifact(
            artifact,
            root=ROOT,
            artifact_raw_sha256=raw_file_sha256(ARTIFACT_PATH),
        )
        self.assertTrue(report["valid"], report)
        self.assertEqual(report["check_count"], EXPECTED_CHECK_COUNT)

    def test_05_validation_report_is_positive(self) -> None:
        report = run_validation(ROOT, write=False)
        self.assertTrue(report["valid"], report)
        self.assertTrue(report["deterministic_rebuild"])
        self.assertEqual(report["independent_check_count"], EXPECTED_CHECK_COUNT)

    def test_06_four_distinct_historical_epochs_pass_the_gate(self) -> None:
        artifact = read_json_strict(ARTIFACT_PATH)
        gate = artifact["historical_epoch_gate"]
        rows = artifact["historical_observations"]
        self.assertEqual(gate["observed_distinct_authentic_epochs"], 4)
        self.assertEqual(gate["required_distinct_authentic_epochs"], 3)
        self.assertTrue(gate["pass"])
        self.assertEqual(len({row["properties_raw_sha256"] for row in rows}), 4)
        self.assertEqual(len({row["normalized_properties_sha256"] for row in rows}), 4)
        self.assertEqual(len({row["source_epoch"] for row in rows}), 4)

    def test_07_cohort_is_one_exact_heron_topology(self) -> None:
        _, rows = load_evidence_cohort(ROOT)
        self.assertEqual({row["processor_family"] for row in rows}, {"Heron"})
        self.assertEqual({row["processor_revision"] for row in rows}, {"2"})
        self.assertEqual({row["directed_topology_sha256"] for row in rows}, {EXPECTED_TOPOLOGY_SHA256})
        self.assertEqual({row["num_qubits"] for row in rows}, {156})
        self.assertEqual({row["dt_ns"] for row in rows}, {"4"})

    def test_08_historical_snapshots_are_never_current_hardware_evidence(self) -> None:
        catalog, rows = load_evidence_cohort(ROOT)
        self.assertFalse(catalog["qualification"]["current_hardware_evidence"])
        self.assertTrue(all(not row["current_hardware_evidence"] for row in rows))
        self.assertTrue(all(not row["live_provider_export"] for row in rows))

    def test_09_strict_snapshot_ceilings_are_exact(self) -> None:
        rows = read_json_strict(ARTIFACT_PATH)["historical_observations"]
        self.assertEqual([row["strict_error_ceiling_exclusive"] for row in rows], [1054, 566, 965, 468])
        self.assertEqual([row["strict_duration_ceiling_exclusive"] for row in rows], [517063, 231739, 613393, 281113])
        self.assertEqual([row["required_maximum_direct_cx"] for row in rows], [1053, 565, 964, 467])
        self.assertEqual([row["largest_fault_excluded_component_qubits"] for row in rows], [152, 156, 153, 154])

        for row in rows:
            error = Decimal(row["minimum_cz_reported_error"])
            error_exclusive = int(row["strict_error_ceiling_exclusive"])
            self.assertLess(Decimal(error_exclusive - 1) * error, Decimal(1))
            self.assertGreaterEqual(Decimal(error_exclusive) * error, Decimal(1))

            t2_ticks = Decimal(row["maximum_t2_ticks_exact"])
            duration_ticks = int(row["minimum_cz_duration_ticks"])
            parallel = int(row["idealized_parallel_cz_capacity"])
            duration_exclusive = int(row["strict_duration_ceiling_exclusive"])
            maximum_gates = duration_exclusive - 1
            maximum_layers = (maximum_gates + parallel - 1) // parallel
            rejected_layers = (maximum_gates + 1 + parallel - 1) // parallel
            self.assertLess(Decimal(maximum_layers * duration_ticks), t2_ticks)
            self.assertGreaterEqual(
                Decimal(rejected_layers * duration_ticks), t2_ticks
            )

    def test_10_matrix_order_and_size_are_frozen(self) -> None:
        matrix = read_json_strict(ARTIFACT_PATH)["snapshot_seed_matrix"]
        self.assertEqual(len(matrix), 32)
        for offset in range(0, 32, 8):
            self.assertEqual(tuple(row["seed"] for row in matrix[offset : offset + 8]), EXPECTED_SEEDS)

    def test_11_all_capacity_and_route_cells_pass(self) -> None:
        matrix = read_json_strict(ARTIFACT_PATH)["snapshot_seed_matrix"]
        self.assertTrue(all(row["capacity_pass"] for row in matrix))
        self.assertTrue(all(row["route_replay_pass"] for row in matrix))

    def test_12_all_error_and_duration_cells_fail(self) -> None:
        matrix = read_json_strict(ARTIFACT_PATH)["snapshot_seed_matrix"]
        self.assertTrue(all(not row["error_screen_pass"] for row in matrix))
        self.assertTrue(all(not row["duration_screen_pass"] for row in matrix))
        self.assertTrue(all(not row["cell_admission_pass"] for row in matrix))

    def test_13_cross_snapshot_architecture_gap_is_exact(self) -> None:
        gate = read_json_strict(ARTIFACT_PATH)["architecture_gate"]
        self.assertEqual(gate["cross_snapshot_required_maximum_direct_cx"], 467)
        self.assertEqual(gate["observed_minimum_direct_cx"], 795_990)
        self.assertEqual(gate["observed_maximum_direct_cx"], 838_686)
        self.assertEqual(gate["minimum_additional_cx_reduction_required"], 795_523)
        self.assertFalse(gate["all_cells_pass"])

    def test_14_scientific_decision_is_fail_closed(self) -> None:
        decisions = read_json_strict(ARTIFACT_PATH)["decisions"]
        self.assertEqual(decisions["overall"], "V50_AUTHENTIC_EPOCH_GATE_PASSED_ARCHITECTURE_NO_GO")
        self.assertEqual(decisions["current_provider_discovery"], "DENIED_ARCHITECTURE_NO_GO")
        self.assertEqual(decisions["v5_execution"], "CLOSED")
        self.assertEqual(decisions["qpu_jobs"], "PROHIBITED")

    def test_15_execution_boundary_is_zero_call_zero_job(self) -> None:
        boundary = read_json_strict(ARTIFACT_PATH)["claim_boundary"]
        self.assertEqual(boundary["research_classification"], "RESEARCH_ONLY")
        self.assertFalse(boundary["hardware_executable"])
        self.assertFalse(boundary["current_hardware_evidence"])
        self.assertEqual(
            sum(
                boundary[key]
                for key in (
                    "credential_reads",
                    "provider_calls",
                    "network_calls",
                    "backend_run_calls",
                    "local_simulator_jobs_submitted",
                    "qpu_jobs_submitted",
                )
            ),
            0,
        )

    def test_16_provider_gate_reports_closed_and_refuses(self) -> None:
        status = authenticated_status(ROOT)
        self.assertEqual(status["current_provider_discovery"], "DENIED_ARCHITECTURE_NO_GO")
        self.assertFalse(status["hardware_executable"])
        with self.assertRaises(ProviderGateClosed):
            require_provider_access(ROOT)

    def test_17_engine_has_no_provider_or_network_import(self) -> None:
        forbidden = {
            "qiskit",
            "qiskit_ibm_runtime",
            "qiskit_ibm_provider",
            "requests",
            "socket",
            "urllib",
            "httpx",
        }
        roots: set[str] = set()
        for path in sorted((ROOT / "quantum_research_lab/v50/engine").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    roots.add(node.module.split(".")[0])
        self.assertTrue(roots.isdisjoint(forbidden), roots)

    def test_18_tampered_decision_fails_independent_checker(self) -> None:
        artifact = copy.deepcopy(read_json_strict(ARTIFACT_PATH))
        artifact["decisions"]["current_provider_discovery"] = "AUTHORIZED"
        report = validate_artifact(artifact, root=ROOT, artifact_raw_sha256="0" * 64)
        self.assertFalse(report["valid"])
        self.assertIn("provider_denied", report["failed_checks"])

    def test_19_tampered_epoch_fails_semantic_and_recomputed_checks(self) -> None:
        artifact = copy.deepcopy(read_json_strict(ARTIFACT_PATH))
        artifact["historical_observations"][0]["source_epoch"] = "2099-01-01T00:00:00Z"
        report = validate_artifact(artifact, root=ROOT, artifact_raw_sha256="0" * 64)
        self.assertFalse(report["valid"])
        self.assertIn("observations_recomputed", report["failed_checks"])

    def test_20_validation_report_is_sealed_and_valid(self) -> None:
        report = read_json_strict(ROOT / REPORT)
        self.assertTrue(report["valid"])
        self.assertEqual(report["artifact_raw_sha256"], raw_file_sha256(ARTIFACT_PATH))
        self.assertEqual(
            report["validation_report_sha256"],
            semantic_sha256(report, exclude=("validation_report_sha256",)),
        )

    def test_21_resealed_material_tampering_is_rejected(self) -> None:
        cases = (
            ("parent", "parent_link_recomputed"),
            ("architecture", "architecture_recomputed"),
            ("matrix", "matrix_recomputed"),
            ("version", "release_version"),
            ("identity", "evidence_identities_recomputed"),
            ("epoch", "epoch_gate_recomputed"),
        )
        for case, semantic_check in cases:
            with self.subTest(case=case):
                artifact = copy.deepcopy(read_json_strict(ARTIFACT_PATH))
                if case == "parent":
                    artifact["parent"]["v49_freeze_raw_sha256"] = "0" * 64
                elif case == "architecture":
                    artifact["architecture_gate"]["reference_architecture_id"] = "FORGED"
                elif case == "matrix":
                    artifact["snapshot_seed_matrix"][0]["direct_cx"] = 0
                elif case == "version":
                    artifact["v50_version"] = "5.0.0-forged"
                elif case == "identity":
                    artifact["evidence_identities"]["protocol_path"] = "forged.json"
                else:
                    artifact["historical_epoch_gate"]["distinct_backend_names"] = 99
                tampered_raw = _reseal_tampered_artifact(artifact)
                self.assertNotEqual(tampered_raw, EXPECTED_ARTIFACT_RAW_SHA256)
                report = validate_artifact(
                    artifact,
                    root=ROOT,
                    artifact_raw_sha256=tampered_raw,
                )
                self.assertFalse(report["valid"])
                self.assertIn("artifact_raw_exact", report["failed_checks"])
                self.assertIn(semantic_check, report["failed_checks"])


if __name__ == "__main__":
    unittest.main()
