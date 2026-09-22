"""Scientific and evidence-boundary tests for Quantum Lab V4.7."""

from __future__ import annotations

import ast
import copy
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from . import phase3_v47_independent_checker as checker
from .phase3_v47_validation import (
    ALLOWED_OVERALL_DECISIONS,
    ARTIFACT_PATH,
    EXPECTED_CHECK_COUNT,
    EXPECTED_INDEPENDENT_CHECK_COUNT,
    EXPECTED_NEXT_GATE,
    EXPECTED_PRODUCTION_ADMISSION,
    EXPECTED_SEEDS,
    EXPECTED_WIDTHS,
    canonical_json_sha256,
    raw_file_sha256,
    read_json_strict,
    run_v47_validation,
    validate_v47_artifact,
)
from .verify_phase3_v47 import EXPECTED_RELEASE_CHECK_COUNT, verify_release_chain


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "quantum_research_lab"


class QuantumLabV47ScientificTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = read_json_strict(
            MODULE / "PHASE_III_V4_7_PINNED_DATED_PROPERTIES_OPTIMIZATION_SPEC_V1.json"
        )
        cls.properties = read_json_strict(
            MODULE / "PHASE_III_V4_7_NORMALIZED_PROPERTIES_ORACLE_V1.json"
        )
        cls.path_oracle = read_json_strict(
            MODULE / "PHASE_III_V4_7_FAULT_EXCLUDED_PATH_ORACLE_V1.json"
        )
        cls.model = read_json_strict(
            MODULE / "PHASE_III_V4_7_DURATION_ERROR_MODEL_CONTRACT_V1.json"
        )
        cls.parent = read_json_strict(
            ROOT
            / "outputs/quantum_phase3/v46_full_stream_routing/"
            "SEALED_V4_6_FULL_STREAM_FAKEMARRAKESH_ROUTING_ARTIFACT.json"
        )
        cls.artifact_path = ROOT / ARTIFACT_PATH
        cls.artifact = read_json_strict(cls.artifact_path) if cls.artifact_path.is_file() else None
        cls.artifact_raw = raw_file_sha256(cls.artifact_path) if cls.artifact_path.is_file() else None
        cls.artifact_semantic = cls.artifact.get("artifact_sha256") if cls.artifact else None

    def require_artifact(self) -> dict:
        if self.artifact is None:
            self.skipTest("The sealed eight-seed V4.7 artifact is still being generated.")
        return self.artifact

    def test_01_protocol_is_result_blind_and_dated_input_is_disclosed(self) -> None:
        chronology = self.spec["chronology"]
        boundary = self.spec["claim_boundary"]
        self.assertEqual(chronology["result_state_at_seal"], "NOT_EVALUATED")
        self.assertTrue(chronology["dated_properties_inspected_before_seal"])
        self.assertEqual(boundary["research_classification"], "RESEARCH_ONLY")
        self.assertFalse(boundary["hardware_executable"])
        self.assertFalse(boundary["snapshot_is_current_hardware_evidence"])

    def test_02_preregistration_input_identities_are_exact(self) -> None:
        identities = self.spec["input_identities"]
        self.assertEqual(identities["normalized_properties_sha256"], checker.EXPECTED_PROPERTIES_SHA256)
        self.assertEqual(identities["path_oracle_sha256"], checker.EXPECTED_PATH_ORACLE_SHA256)
        self.assertEqual(identities["model_contract_sha256"], checker.EXPECTED_MODEL_SHA256)
        self.assertEqual(identities["v46_artifact_sha256"], checker.EXPECTED_V46_ARTIFACT_SHA256)
        self.assertEqual(identities["v46_freeze_sha256"], checker.EXPECTED_V46_FREEZE_SHA256)

    def test_03_raw_and_normalized_property_evidence_is_exact(self) -> None:
        raw = MODULE / "PHASE_III_V4_7_FAKEMARRAKESH_PROPERTIES_2025_02_26_RAW.json"
        normalized = MODULE / "PHASE_III_V4_7_NORMALIZED_PROPERTIES_ORACLE_V1.json"
        self.assertEqual(raw.stat().st_size, checker.EXPECTED_RAW_PROPERTIES_SIZE)
        self.assertEqual(raw_file_sha256(raw), checker.EXPECTED_RAW_PROPERTIES_SHA256)
        self.assertEqual(raw_file_sha256(normalized), checker.EXPECTED_PROPERTIES_RAW_SHA256)
        self.assertEqual(self.properties["properties_snapshot_sha256"], checker.EXPECTED_PROPERTIES_SHA256)
        self.assertEqual(
            self.properties["properties_snapshot_sha256"],
            canonical_json_sha256(
                {key: value for key, value in self.properties.items() if key != "properties_snapshot_sha256"}
            ),
        )

    def test_04_property_coverage_and_fault_screen_are_complete(self) -> None:
        coverage = self.properties["coverage"]
        fault = self.properties["fault_screen"]
        self.assertEqual(coverage["native_gate_tuple_count"], 976)
        self.assertEqual(coverage["required_property_value_count"], 1952)
        self.assertTrue(coverage["all_required_gate_tuples_complete"])
        self.assertEqual(fault["excluded_directed_cz_edge_count"], 26)
        self.assertEqual(fault["excluded_undirected_cz_edge_count"], 13)
        self.assertEqual(fault["fault_excluded_component_sizes"], [153, 1, 1, 1])
        self.assertEqual(fault["isolated_qubits"], [24, 102, 113])
        self.assertEqual(fault["width_margin"], 8)

    def test_05_property_dates_do_not_masquerade_as_current_evidence(self) -> None:
        dates = self.properties["property_time_range"]
        boundary = self.properties["claim_boundary"]
        self.assertTrue(dates["global_date_is_not_asserted_as_strict_cutoff"])
        self.assertGreater(
            datetime.fromisoformat(dates["maximum_embedded_property_date"]),
            datetime.fromisoformat(dates["global_last_update_date"]),
        )
        self.assertFalse(boundary["snapshot_is_current_hardware_evidence"])
        self.assertFalse(boundary["hardware_executable"])

    def test_06_path_oracle_identity_shape_and_order_are_exact(self) -> None:
        oracle = self.path_oracle
        self.assertEqual(raw_file_sha256(MODULE / "PHASE_III_V4_7_FAULT_EXCLUDED_PATH_ORACLE_V1.json"), checker.EXPECTED_PATH_ORACLE_RAW_SHA256)
        self.assertEqual(oracle["path_oracle_sha256"], checker.EXPECTED_PATH_ORACLE_SHA256)
        self.assertEqual(oracle["component_size"], 153)
        self.assertEqual(oracle["ordered_path_count"], 153 * 152)
        self.assertEqual(oracle["maximum_hops"], 43)
        self.assertEqual(
            oracle["cost_contract"]["objective_order"],
            ["minimum_hops", "reported_gate_error_mass", "nominal_duration_ticks", "full_path_tuple"],
        )
        self.assertIn("NO_GLOBAL_OPTIMALITY_CLAIM", oracle["cost_contract"]["scope"])

    def test_07_path_oracle_objective_is_independently_recomputed(self) -> None:
        properties, property_checks = checker._validate_properties(self.properties)
        self.assertTrue(all(property_checks.values()), property_checks)
        path_checks = checker._validate_path_oracle(self.path_oracle, properties)
        self.assertTrue(all(path_checks.values()), path_checks)

    def test_08_duration_and_error_models_are_explicit_and_non_fidelity(self) -> None:
        duration = self.model["duration_model"]
        error = self.model["error_model"]
        self.assertEqual(duration["dt_nanoseconds"], 4)
        self.assertEqual(duration["clock_count"], 156)
        self.assertEqual(duration["unit"], "INTEGER_DT_TICKS")
        self.assertEqual(error["decimal_precision"], 50)
        self.assertEqual(error["normative_name"], "reported_gate_error_mass")
        self.assertEqual(error["missing_invalid_or_nonfinite_property"], "BLOCK_CALCULATION_FAIL_CLOSED")
        self.assertEqual(error["independent_product_acceptance_role"], "NONE")
        self.assertIn("CIRCUIT_FIDELITY", error["not_interpreted_as"])
        self.assertIn("EXPECTED_FAILURE_COUNT", error["not_interpreted_as"])

    def test_09_candidate_scope_has_no_global_optimality_claim(self) -> None:
        optimization = self.model["optimization_model"]
        self.assertEqual(optimization["candidate_name"], checker.CANDIDATE_NAME)
        self.assertEqual(optimization["candidate_optimality_claim"], "NONE_BEYOND_STATIC_ORDERED_PAIR_TIEBREAK")
        self.assertEqual(
            optimization["initial_layout"],
            "LOGICAL_ORDER_TO_ASCENDING_LARGEST_COMPONENT_PREFIX",
        )
        self.assertTrue(optimization["pareto_safe_replacement_requires_every_seed"]["candidate_reported_gate_error_mass_strictly_lt_baseline"])

    def test_10_strict_json_rejects_duplicate_and_nonfinite_values(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v47-json-test.") as temporary:
            duplicate = Path(temporary) / "duplicate.json"
            nonfinite = Path(temporary) / "nonfinite.json"
            duplicate.write_text('{"x":1,"x":2}', encoding="utf-8")
            nonfinite.write_text('{"x":NaN}', encoding="utf-8")
            with self.assertRaises(ValueError):
                read_json_strict(duplicate)
            with self.assertRaises(ValueError):
                read_json_strict(nonfinite)

    def test_11_checker_does_not_import_optimizer_provider_or_network(self) -> None:
        path = MODULE / "phase3_v47_independent_checker.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        forbidden = {"qiskit", "qiskit_ibm_runtime", "qiskit_ibm_provider", "requests", "httpx", "urllib", "socket"}
        self.assertFalse(any(module.endswith("phase3_v47_dated_properties_optimizer") for module in imports))
        self.assertFalse(any(module.split(".")[0] in forbidden for module in imports))

    def test_12_optimizer_has_explicit_network_denial_and_no_provider_client(self) -> None:
        path = MODULE / "phase3_v47_dated_properties_optimizer.py"
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        forbidden = {"qiskit", "qiskit_ibm_runtime", "qiskit_ibm_provider", "requests", "httpx", "urllib"}
        self.assertFalse(any(module.split(".")[0] in forbidden for module in imports))
        self.assertIn('mock.patch.object(socket.socket, "connect", deny_network)', text)
        self.assertIn('"socket.create_connection", side_effect=deny_network', text)

    def test_13_artifact_self_hash_and_source_crosslinks_are_exact(self) -> None:
        artifact = self.require_artifact()
        self.assertEqual(
            artifact["artifact_sha256"],
            canonical_json_sha256({key: value for key, value in artifact.items() if key != "artifact_sha256"}),
        )
        self.assertEqual(artifact["source_raw_file_sha256"], raw_file_sha256(MODULE / "phase3_v47_dated_properties_optimizer.py"))
        self.assertEqual(artifact["independent_checker_raw_file_sha256"], raw_file_sha256(MODULE / "phase3_v47_independent_checker.py"))

    def test_14_seed_order_widths_and_parent_instance_ids_are_exact(self) -> None:
        artifact = self.require_artifact()
        rows = artifact["seed_evaluations"]
        parent_rows = self.parent["seed_routings"]
        self.assertEqual(tuple(row["seed"] for row in rows), EXPECTED_SEEDS)
        self.assertEqual(tuple(row["logical_qubits"] for row in rows), EXPECTED_WIDTHS)
        self.assertEqual(
            [(row["seed"], row["instance_id"]) for row in rows],
            [(row["seed"], row["instance_id"]) for row in parent_rows],
        )

    def test_15_baseline_replay_commitments_are_exact_v46(self) -> None:
        artifact = self.require_artifact()
        parents = {row["seed"]: row for row in self.parent["seed_routings"]}
        for row in artifact["seed_evaluations"]:
            parent = parents[row["seed"]]["routed_compilation"]
            baseline = row["baseline_v46"]["routed_compilation"]
            self.assertTrue(row["baseline_v46_commitments_exact"])
            self.assertEqual(baseline["route_ir"], parent["route_ir"])
            self.assertEqual(baseline["native_ledger"], parent["native_ledger"])
            self.assertEqual(baseline["routing_ledger"], parent["routing_ledger"])
            self.assertEqual(baseline["v46_compatible_layout_commitment"], parent["layout"])
            self.assertEqual(baseline["input_stream_manifest"], parent["input_stream_manifest"])

    def test_16_candidate_uses_fault_excluded_oracle_and_nontrivial_layout(self) -> None:
        artifact = self.require_artifact()
        component = self.path_oracle["component_qubits"]
        for row in artifact["seed_evaluations"]:
            routed = row["candidate"]["routed_compilation"]
            routing = routed["routing_ledger"]
            layout = routed["layout"]
            self.assertEqual(routing["candidate_name"], checker.CANDIDATE_NAME)
            self.assertEqual(routing["path_oracle_sha256"], checker.EXPECTED_PATH_ORACLE_SHA256)
            self.assertIsNone(routing["transpiler_seed"])
            self.assertEqual(layout["initial_layout"], component[: row["logical_qubits"]])
            self.assertEqual(layout["initial_layout_contract"], "LOGICAL_ORDER_TO_ASCENDING_FAULT_EXCLUDED_COMPONENT_PREFIX")

    def test_17_duration_error_and_property_usage_ledgers_are_complete(self) -> None:
        artifact = self.require_artifact()
        for row in artifact["seed_evaluations"]:
            for key in ("baseline_v46", "candidate"):
                routed = row[key]["routed_compilation"]
                timing = routed["timing_ledger"]
                error = routed["error_screen"]
                usage = routed["physical_property_usage"]
                self.assertEqual(len(timing["final_physical_clock_ticks"]), 156)
                self.assertEqual(timing["makespan_ticks"], max(timing["final_physical_clock_ticks"]))
                self.assertEqual(timing["makespan_nanoseconds"], timing["makespan_ticks"] * 4)
                self.assertTrue(timing["not_hardware_job_or_pulse_runtime"])
                self.assertEqual(error["missing_property_occurrences"], 0)
                self.assertEqual(error["calibration_aware_circuit_fidelity"], "NOT_CLAIMED")
                self.assertEqual(error["reported_gate_error_mass_interpretation"], "DESCRIPTIVE_SUM_NOT_FIDELITY_SUCCESS_PROBABILITY_OR_EXPECTED_FAILURE_COUNT")
                self.assertEqual(usage["gate_occurrence_count"], sum(item["occurrence_count"] for item in usage["exact_gate_qargs_occurrences"]))

    def test_18_resource_and_pareto_semantics_are_fail_closed(self) -> None:
        artifact = self.require_artifact()
        for row in artifact["seed_evaluations"]:
            candidate = row["candidate"]
            resource = candidate["resource_gate"]
            comparison = row["comparison"]
            if resource["status"] == "PASS_V47_RESEARCH_FEASIBILITY_GATE":
                error = candidate["routed_compilation"]["error_screen"]
                self.assertEqual(error["unit_error_gate_occurrences"], 0)
                self.assertEqual(error["missing_property_occurrences"], 0)
                self.assertTrue(resource["final_layout_bijective"])
            if comparison["pareto_safe_for_seed"]:
                self.assertEqual(resource["status"], "PASS_V47_RESEARCH_FEASIBILITY_GATE")
                self.assertLess(
                    Decimal(comparison["candidate_minus_baseline_reported_error_mass"]),
                    Decimal(0),
                )
                self.assertLessEqual(comparison["candidate_minus_baseline_makespan_ticks"], 0)
                self.assertLessEqual(comparison["candidate_minus_baseline_native_cz"], 0)

    def test_19_architecture_lower_bound_is_only_a_necessary_condition(self) -> None:
        artifact = self.require_artifact()
        for row in artifact["seed_evaluations"]:
            lower = row["architecture_lower_bound"]
            self.assertEqual(lower["idealized_parallel_cz_capacity"], 78)
            self.assertEqual(lower["scope"], "ZERO_SWAP_ZERO_1Q_IDEALIZED_NECESSARY_CONDITION_NOT_A_SUFFICIENT_HARDWARE_MODEL")
            self.assertIsInstance(lower["passes_duration_screen"], bool)
            self.assertIsInstance(lower["passes_reported_error_mass_screen"], bool)

    def test_20_decisions_and_claim_boundary_are_exact(self) -> None:
        artifact = self.require_artifact()
        decisions = artifact["decisions"]
        boundary = artifact["claim_boundary"]
        self.assertIn(decisions["overall"], ALLOWED_OVERALL_DECISIONS)
        self.assertEqual(decisions["production_admission"], EXPECTED_PRODUCTION_ADMISSION)
        self.assertEqual(decisions["next_falsifiable_gate"], EXPECTED_NEXT_GATE)
        for field in ("credential_reads", "provider_calls", "network_calls", "backend_run_calls", "local_simulator_jobs_submitted", "qpu_jobs_submitted"):
            self.assertEqual(boundary[field], 0, field)
        self.assertFalse(boundary["provider_sdk_imported"])
        self.assertFalse(boundary["provider_credentials_read"])
        self.assertFalse(boundary["hardware_executable"])
        self.assertFalse(boundary["snapshot_is_current_hardware_evidence"])
        self.assertEqual(boundary["quantum_advantage"], "NOT_CLAIMED")

    def test_21_independent_checker_passes_all_51_checks(self) -> None:
        artifact = self.require_artifact()
        result = checker.validate_v47_artifact(
            artifact,
            root=ROOT,
            authenticate_parent=True,
            expected_artifact_sha256=self.artifact_semantic,
            artifact_raw_file_sha256=self.artifact_raw,
            expected_artifact_raw_sha256=self.artifact_raw,
        )
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["check_count"], EXPECTED_INDEPENDENT_CHECK_COUNT)

    def test_22_scientific_validation_passes_all_96_checks(self) -> None:
        self.require_artifact()
        result = run_v47_validation(
            root=ROOT,
            expected_artifact_raw_sha256=self.artifact_raw,
            expected_artifact_sha256=self.artifact_semantic,
        )
        self.assertTrue(result["passed"], result)
        self.assertEqual(
            result["counts"],
            {"checks_passed": EXPECTED_CHECK_COUNT, "checks_total": EXPECTED_CHECK_COUNT},
        )

    def test_23_identity_release_chain_passes_20_checks_with_explicit_pins(self) -> None:
        self.require_artifact()
        result = verify_release_chain(
            ROOT,
            deep=False,
            rebuild=False,
            expected_artifact_raw_sha256=self.artifact_raw,
            expected_artifact_sha256=self.artifact_semantic,
        )
        self.assertTrue(result["passed"], result)
        self.assertEqual(
            result["counts"],
            {"checks_passed": EXPECTED_RELEASE_CHECK_COUNT, "checks_total": EXPECTED_RELEASE_CHECK_COUNT},
        )

    def test_24_rehashed_hardware_claim_tampering_fails_closed(self) -> None:
        artifact = self.require_artifact()
        tampered = copy.deepcopy(artifact)
        tampered["claim_boundary"]["hardware_executable"] = True
        tampered["artifact_sha256"] = canonical_json_sha256(
            {key: value for key, value in tampered.items() if key != "artifact_sha256"}
        )
        result = checker.validate_v47_artifact(
            tampered,
            root=ROOT,
            authenticate_parent=False,
            expected_artifact_sha256=self.artifact_semantic,
            artifact_raw_file_sha256=self.artifact_raw,
            expected_artifact_raw_sha256=self.artifact_raw,
        )
        self.assertFalse(result["valid"])
        self.assertIn("hardware_and_claim_boundary", result["failed_checks"])

    def test_25_rehashed_error_mass_tampering_fails_recomputation(self) -> None:
        artifact = self.require_artifact()
        tampered = copy.deepcopy(artifact)
        routed = tampered["seed_evaluations"][0]["candidate"]["routed_compilation"]
        routed["error_screen"]["reported_gate_error_mass"] = "0"
        routed["error_screen"]["error_screen_sha256"] = canonical_json_sha256(
            {
                key: value
                for key, value in routed["error_screen"].items()
                if key != "error_screen_sha256"
            }
        )
        tampered["artifact_sha256"] = canonical_json_sha256(
            {key: value for key, value in tampered.items() if key != "artifact_sha256"}
        )
        result = checker.validate_v47_artifact(
            tampered,
            root=ROOT,
            authenticate_parent=False,
        )
        self.assertFalse(result["valid"])
        self.assertIn("error_screens_recomputed", result["failed_checks"])

    def test_26_seed_removal_and_rehash_still_fails_eight_seed_contract(self) -> None:
        artifact = self.require_artifact()
        tampered = copy.deepcopy(artifact)
        tampered["seed_evaluations"].pop()
        tampered["artifact_sha256"] = canonical_json_sha256(
            {key: value for key, value in tampered.items() if key != "artifact_sha256"}
        )
        result = validate_v47_artifact(
            tampered,
            root=ROOT,
            expected_artifact_raw_sha256=self.artifact_raw,
            expected_artifact_sha256=self.artifact_semantic,
            authenticate_parent=False,
        )
        self.assertFalse(result["passed"])
        self.assertIn("exact_eight_seed_rows", result["failed_checks"])
        self.assertIn("independent::seed_order", result["failed_checks"])


if __name__ == "__main__":
    unittest.main()
