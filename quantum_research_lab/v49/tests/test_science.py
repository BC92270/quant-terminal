"""Scientific tests for the V4.9 terminal offline admission dossier."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path
import unittest

from ..engine.checker import EXPECTED_CHECK_COUNT, validate_artifact
from ..engine.evaluator import (
    ARTIFACT_RELATIVE_PATH,
    EXPECTED_SEEDS,
    authenticate_parent,
    build_admission_artifact,
    canonical_json_bytes,
    default_root,
    read_json_strict,
)
from ..engine.validation import REPORT_RELATIVE_PATH, build_validation_report


ROOT = default_root()
ARTIFACT_PATH = ROOT / ARTIFACT_RELATIVE_PATH


class QuantumLabV49ScienceTests(unittest.TestCase):
    def test_01_parent_v48_authenticates(self) -> None:
        freeze, artifact = authenticate_parent(ROOT)
        self.assertEqual(freeze["freeze_contract_version"], "QUANTUM LAB V4.8 FREEZE CONTRACT · V1")
        self.assertEqual(
            artifact["v48_version"],
            "PHASE III · V4.8 CONTROL-LOADED CUCCARO ARCHITECTURE · V1",
        )

    def test_02_build_is_deterministic(self) -> None:
        self.assertEqual(build_admission_artifact(ROOT), build_admission_artifact(ROOT))

    def test_03_artifact_self_hash(self) -> None:
        artifact = read_json_strict(ARTIFACT_PATH)
        body = {key: value for key, value in artifact.items() if key != "artifact_sha256"}
        self.assertEqual(
            artifact["artifact_sha256"],
            hashlib.sha256(canonical_json_bytes(body)).hexdigest(),
        )

    def test_04_independent_checker_passes(self) -> None:
        artifact = read_json_strict(ARTIFACT_PATH)
        report = validate_artifact(
            artifact,
            root=ROOT,
            artifact_raw_sha256=hashlib.sha256(ARTIFACT_PATH.read_bytes()).hexdigest(),
        )
        self.assertTrue(report["valid"], report)
        self.assertEqual(report["check_count"], EXPECTED_CHECK_COUNT)

    def test_05_validation_report_passes(self) -> None:
        report = build_validation_report(ROOT)
        self.assertTrue(report["valid"], report)
        self.assertEqual(report["expected_check_count"], EXPECTED_CHECK_COUNT)

    def test_06_seed_order_is_frozen(self) -> None:
        artifact = read_json_strict(ARTIFACT_PATH)
        self.assertEqual(tuple(row["seed"] for row in artifact["seed_admission"]), EXPECTED_SEEDS)

    def test_07_authentic_epoch_gate_is_one_of_three(self) -> None:
        gate = read_json_strict(ARTIFACT_PATH)["snapshot_gate"]
        self.assertEqual(gate["observed_distinct_authentic_epochs"], 1)
        self.assertEqual(gate["required_distinct_authentic_epochs"], 3)
        self.assertEqual(gate["missing_distinct_authentic_epochs"], 2)
        self.assertFalse(gate["pass"])

    def test_08_synthetic_epochs_are_forbidden(self) -> None:
        artifact = read_json_strict(ARTIFACT_PATH)
        protocol = read_json_strict(ROOT / "quantum_research_lab/v49/PROTOCOL.json")
        self.assertFalse(artifact["snapshot_gate"]["synthetic_substitution_allowed"])
        self.assertFalse(protocol["authentic_snapshot_gate"]["synthetic_jitter_bootstrap_resampling_allowed"])

    def test_09_reference_cx_range_is_exact(self) -> None:
        gate = read_json_strict(ARTIFACT_PATH)["architecture_gate"]
        self.assertEqual(gate["observed_minimum_direct_cx"], 795_990)
        self.assertEqual(gate["observed_maximum_direct_cx"], 838_686)

    def test_10_strict_resource_screens_fail_all_eight(self) -> None:
        rows = read_json_strict(ARTIFACT_PATH)["seed_admission"]
        self.assertEqual(len(rows), 8)
        self.assertTrue(all(not row["error_screen_pass"] for row in rows))
        self.assertTrue(all(not row["duration_screen_pass"] for row in rows))

    def test_11_capacity_and_frozen_route_replay_pass(self) -> None:
        rows = read_json_strict(ARTIFACT_PATH)["seed_admission"]
        self.assertTrue(all(row["capacity_pass"] for row in rows))
        self.assertTrue(all(row["route_replay_pass"] for row in rows))

    def test_12_fail_closed_decision_is_exact(self) -> None:
        decisions = read_json_strict(ARTIFACT_PATH)["decisions"]
        self.assertEqual(decisions["overall"], "V49_NOT_EVALUABLE_INSUFFICIENT_AUTHENTIC_EPOCHS")

    def test_13_provider_and_v5_gates_remain_closed(self) -> None:
        decisions = read_json_strict(ARTIFACT_PATH)["decisions"]
        self.assertEqual(decisions["provider_discovery"], "DENIED")
        self.assertEqual(decisions["v5_hardware_protocol_entry"], "CLOSED")

    def test_14_execution_boundary_is_zero_job(self) -> None:
        boundary = read_json_strict(ARTIFACT_PATH)["claim_boundary"]
        self.assertEqual(boundary["research_classification"], "RESEARCH_ONLY")
        self.assertFalse(boundary["hardware_executable"])
        self.assertEqual(
            sum(boundary[key] for key in ("credential_reads", "provider_calls", "network_calls", "backend_run_calls", "local_simulator_jobs_submitted", "qpu_jobs_submitted")),
            0,
        )

    def test_15_engine_has_no_provider_or_network_import(self) -> None:
        forbidden = {"qiskit", "qiskit_ibm_runtime", "qiskit_ibm_provider", "requests", "socket", "urllib", "httpx"}
        roots: set[str] = set()
        for path in sorted((ROOT / "quantum_research_lab/v49/engine").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    roots.add(node.module.split(".")[0])
        self.assertTrue(roots.isdisjoint(forbidden), roots)

    def test_16_tampered_decision_fails_independent_checker(self) -> None:
        artifact = copy.deepcopy(read_json_strict(ARTIFACT_PATH))
        artifact["decisions"]["provider_discovery"] = "AUTHORIZED"
        report = validate_artifact(artifact, root=ROOT, artifact_raw_sha256="0" * 64)
        self.assertFalse(report["valid"])
        self.assertIn("provider_denied", report["failed_checks"])

    def test_17_catalog_has_two_open_authentic_slots(self) -> None:
        catalog = read_json_strict(ROOT / "quantum_research_lab/v49/snapshots/catalog.json")
        self.assertEqual([row["status"] for row in catalog["open_slots"]], ["MISSING", "MISSING"])

    def test_18_v49_is_terminal_offline_phase(self) -> None:
        protocol = read_json_strict(ROOT / "quantum_research_lab/v49/PROTOCOL.json")
        self.assertTrue(protocol["terminal_scope"]["v49_is_final_offline_v4_phase"])
        self.assertTrue(protocol["terminal_scope"]["pass_only_opens_v5_hardware_protocol"])
        self.assertTrue(protocol["terminal_scope"]["pass_does_not_authorize_qpu_execution"])


if __name__ == "__main__":
    unittest.main()
