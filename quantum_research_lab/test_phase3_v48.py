"""Scientific unit tests for Quantum Lab V4.8."""

from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path
import unittest

from .phase3_v48_independent_checker import (
    EXPECTED_CHECK_COUNT as EXPECTED_INDEPENDENT_CHECK_COUNT,
    canonical_json_sha256,
    raw_file_sha256,
    read_json_strict,
    validate_v48_artifact,
)
from .phase3_v48_multi_snapshot_architecture_optimizer import (
    build_equivalence_evidence,
)
from .phase3_v48_reference_builder import (
    CURRENT_BLOCKED_DECISION,
    validate_reference_bundle,
)
from .phase3_v48_validation import (
    ARTIFACT_PATH,
    EXPECTED_CHECK_COUNT,
    run_v48_validation,
)


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_FILE = ROOT / ARTIFACT_PATH


def _artifact() -> dict:
    return read_json_strict(ARTIFACT_FILE)


class QuantumLabV48ScientificTests(unittest.TestCase):
    def test_01_reference_bundle_is_exact(self) -> None:
        report = validate_reference_bundle(ROOT)
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["counts"]["checks_total"], 11)

    def test_02_catalog_has_one_distinct_epoch(self) -> None:
        payload = read_json_strict(ROOT / "quantum_research_lab/PHASE_III_V4_8_SNAPSHOT_CATALOG_V1.json")
        self.assertEqual(payload["counts"]["distinct_epoch_count"], 1)
        self.assertEqual(payload["counts"]["unique_raw_snapshot_identity_count"], 1)

    def test_03_catalog_admits_no_alias(self) -> None:
        payload = read_json_strict(ROOT / "quantum_research_lab/PHASE_III_V4_8_SNAPSHOT_CATALOG_V1.json")
        self.assertEqual(payload["aliases"], [])
        self.assertEqual(payload["counts"]["admitted_alias_count"], 0)

    def test_04_synthetic_inputs_are_not_snapshots(self) -> None:
        payload = read_json_strict(ROOT / "quantum_research_lab/PHASE_III_V4_8_SNAPSHOT_CATALOG_V1.json")
        self.assertEqual(payload["alias_policy"]["synthetic_jitter_bootstrap_or_resampling"], "NOT_ADMISSIBLE_AS_AN_AUTHENTIC_SNAPSHOT")

    def test_05_architecture_oracle_self_hash(self) -> None:
        payload = read_json_strict(ROOT / "quantum_research_lab/PHASE_III_V4_8_ARCHITECTURE_CANDIDATE_ORACLE_V1.json")
        core = {key: value for key, value in payload.items() if key not in {"v48_spec_sha", "v48_spec_sha256"}}
        self.assertEqual(payload["v48_spec_sha256"], canonical_json_sha256(core))

    def test_06_independent_adder_equivalence(self) -> None:
        evidence = build_equivalence_evidence()
        self.assertTrue(evidence["all_cases_exact"], evidence)
        self.assertEqual(evidence["case_count"], 28_240)

    def test_07_artifact_self_hash(self) -> None:
        artifact = _artifact()
        core = {key: value for key, value in artifact.items() if key != "artifact_sha256"}
        self.assertEqual(artifact["artifact_sha256"], canonical_json_sha256(core))

    def test_08_independent_checker_passes_65(self) -> None:
        artifact = _artifact()
        report = validate_v48_artifact(
            artifact,
            root=ROOT,
            artifact_raw_file_sha256=raw_file_sha256(ARTIFACT_FILE),
            expected_artifact_raw_sha256=raw_file_sha256(ARTIFACT_FILE),
            expected_artifact_sha256=artifact["artifact_sha256"],
        )
        self.assertTrue(report["valid"], report)
        self.assertEqual(report["check_count"], EXPECTED_INDEPENDENT_CHECK_COUNT)

    def test_09_validation_passes_96(self) -> None:
        artifact = _artifact()
        report = run_v48_validation(
            root=ROOT,
            expected_artifact_raw_sha256=raw_file_sha256(ARTIFACT_FILE),
            expected_artifact_sha256=artifact["artifact_sha256"],
        )
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["counts"]["checks_total"], EXPECTED_CHECK_COUNT)

    def test_10_seed_order_is_exact(self) -> None:
        self.assertEqual([row["seed"] for row in _artifact()["seed_evaluations"]], [1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807])

    def test_11_width_order_is_exact(self) -> None:
        self.assertEqual([row["logical_qubits"] for row in _artifact()["seed_evaluations"]], [135, 137, 133, 135, 137, 137, 145, 139])

    def test_12_all_streams_materialized(self) -> None:
        artifact = _artifact()
        self.assertTrue(artifact["aggregate"]["all_eight_candidate_streams_materialized"])
        self.assertTrue(all(row["candidate_stream_materialized"] for row in artifact["seed_evaluations"]))

    def test_13_all_logical_cx_strictly_reduced(self) -> None:
        rows = _artifact()["seed_evaluations"]
        self.assertTrue(all(row["comparison"]["candidate_cx"] < row["comparison"]["parent_v45_cx"] for row in rows))

    def test_14_all_basic_swap_cz_strictly_reduced(self) -> None:
        rows = _artifact()["seed_evaluations"]
        self.assertTrue(all(row["comparison"]["candidate_basic_swap_cz"] < row["comparison"]["parent_v46_basic_swap_cz"] for row in rows))

    def test_15_aggregate_cx_is_exact(self) -> None:
        artifact = _artifact()
        self.assertEqual(artifact["aggregate"]["aggregate_parent_v45_cx"], 19_251_104)
        self.assertEqual(artifact["aggregate"]["aggregate_candidate_cx"], 6_474_096)

    def test_16_aggregate_cz_is_exact(self) -> None:
        artifact = _artifact()
        self.assertEqual(artifact["aggregate"]["aggregate_parent_v46_basic_swap_cz"], 119_029_964)
        self.assertEqual(artifact["aggregate"]["aggregate_candidate_basic_swap_cz"], 59_565_732)

    def test_17_adder_ledgers_explain_entire_cx_delta(self) -> None:
        for row in _artifact()["seed_evaluations"]:
            evidence = row["structural_routing"]["adder_evidence"]
            comparison = row["comparison"]
            self.assertEqual(evidence["adder_cx_reduction"], comparison["cx_reduction"])

    def test_18_native_cz_equals_direct_plus_three_per_swap(self) -> None:
        for row in _artifact()["seed_evaluations"]:
            native = row["structural_routing"]["routed_compilation"]["native_ledger"]
            self.assertEqual(native["native_operation_counts"]["cz"], native["direct_translated_cx_count"] + 3 * native["swap_count"])

    def test_19_no_isa_or_coupling_violation(self) -> None:
        for row in _artifact()["seed_evaluations"]:
            native = row["structural_routing"]["routed_compilation"]["native_ledger"]
            self.assertEqual(native["isa_violations"], 0)
            self.assertEqual(native["coupling_violations"], 0)

    def test_20_final_layouts_are_bijections(self) -> None:
        for row in _artifact()["seed_evaluations"]:
            layout = row["structural_routing"]["routed_compilation"]["layout"]
            self.assertEqual(len(set(layout["final_logical_to_physical"])), row["logical_qubits"])

    def test_21_historical_error_screen_still_fails(self) -> None:
        for row in _artifact()["seed_evaluations"]:
            lower = row["architecture_lower_bound_v47_comparable"]
            self.assertFalse(lower["passes_reported_error_mass_screen"])
            self.assertGreaterEqual(Decimal(lower["optimistic_reported_error_mass_lower_bound"]), Decimal(1))

    def test_22_historical_duration_screen_still_fails(self) -> None:
        for row in _artifact()["seed_evaluations"]:
            lower = row["architecture_lower_bound_v47_comparable"]
            self.assertFalse(lower["passes_duration_screen"])
            self.assertGreater(lower["optimistic_cz_duration_over_maximum_snapshot_t2"], 1)

    def test_23_claim_boundary_is_offline(self) -> None:
        boundary = _artifact()["claim_boundary"]
        self.assertFalse(boundary["hardware_executable"])
        self.assertEqual(boundary["research_classification"], "RESEARCH_ONLY")
        self.assertEqual(sum(boundary[key] for key in ("provider_calls", "network_calls", "backend_run_calls", "local_simulator_jobs_submitted", "qpu_jobs_submitted")), 0)

    def test_24_decisions_preserve_both_positive_and_negative_results(self) -> None:
        decisions = _artifact()["decisions"]
        self.assertEqual(decisions["architecture_candidate"], "PASS_EXACT_CONTROL_LOADED_CUCCARO_REDUCTION_ALL_EIGHT")
        self.assertEqual(decisions["multi_snapshot_robustness"], CURRENT_BLOCKED_DECISION)
        self.assertEqual(decisions["v47_comparable_lower_bound"], "FAIL_BOTH_NECESSARY_SCREENS_ALL_EIGHT")

    def test_25_parent_v47_identity_is_exact(self) -> None:
        parent = _artifact()["parent"]
        self.assertEqual(parent["v47_artifact_sha256"], "fa1b8a2be1471080134f34ada7ba8cff488c87077a4e5f271fd29828f1fffbaf")
        self.assertEqual(parent["v47_freeze_sha256"], "3f870a5ff89368d2000a58533fba395b0d077cc377cdc830fdc4b362f6465858")

    def test_26_optimizer_has_no_provider_or_network_import(self) -> None:
        tree = ast.parse((ROOT / "quantum_research_lab/phase3_v48_multi_snapshot_architecture_optimizer.py").read_text(encoding="utf-8"))
        roots = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        self.assertTrue(roots.isdisjoint({"qiskit", "qiskit_ibm_runtime", "qiskit_ibm_provider", "requests", "socket", "urllib", "httpx"}))


if __name__ == "__main__":
    unittest.main()
