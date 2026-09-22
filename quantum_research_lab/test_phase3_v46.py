"""Scientific, routing and evidence-boundary tests for Quantum Lab V4.6."""

from __future__ import annotations

import ast
import copy
from pathlib import Path
import unittest

from .phase3_v46_independent_checker import validate_v46_artifact as independent_check
from .phase3_v46_validation import (
    ARTIFACT_PATH,
    EXPECTED_AGGREGATE,
    EXPECTED_ARTIFACT_SHA256,
    EXPECTED_CHECK_COUNT,
    EXPECTED_NEXT_GATE,
    EXPECTED_OVERALL,
    EXPECTED_PRODUCTION_ADMISSION,
    EXPECTED_ROW_METRICS,
    EXPECTED_SEEDS,
    EXPECTED_WIDTHS,
    canonical_json_sha256,
    read_json_strict,
    run_v46_validation,
    validate_v46_artifact,
)


ROOT = Path(__file__).resolve().parents[1]


class QuantumLabV46ScientificTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact = read_json_strict(ROOT / ARTIFACT_PATH)
        cls.spec = read_json_strict(
            ROOT / "quantum_research_lab/PHASE_III_V4_6_FULL_STREAM_FAKEMARRAKESH_ROUTING_SPEC_V1.json"
        )

    def test_01_protocol_is_result_blind_and_pilot_is_disclosed(self) -> None:
        chronology = self.spec["chronology"]
        self.assertEqual(chronology["result_state_at_seal"], "NOT_EVALUATED")
        self.assertEqual(chronology["confirmatory_eight_seed_result_state_at_seal"], "NOT_EVALUATED")
        self.assertIn("NOT_CONFIRMATORY_EVIDENCE", chronology["nonconfirmatory_pilot_disclosure"])

    def test_02_exact_v45_parent_closure_is_bound(self) -> None:
        parent = self.artifact["parent"]
        self.assertEqual(parent["immutable_file_count"], 227)
        self.assertTrue(parent["immutable_files_exact"])
        self.assertEqual(parent["overall_decision"], "V45_PROOF_CARRYING_WIDTH_REDUCTION_PASSED_EXACT_PROMISE_PARITY")

    def test_03_reference_contracts_are_exactly_bound(self) -> None:
        refs = self.artifact["reference_contracts"]
        self.assertEqual(refs["path_oracle_sha256"], "0956cfa11e6a507cf8e4197e8c054b0bd90f4ca2a37ac895b61265e95d91ecf7")
        self.assertEqual(refs["translation_contract_sha256"], "e0ab1b7612f7dac1ee9946ff296ee82ab603ed069a228d0dbffd537621f266a7")

    def test_04_artifact_self_hash_is_exact(self) -> None:
        self.assertEqual(self.artifact["artifact_sha256"], EXPECTED_ARTIFACT_SHA256)
        self.assertEqual(
            self.artifact["artifact_sha256"],
            canonical_json_sha256({key: value for key, value in self.artifact.items() if key != "artifact_sha256"}),
        )

    def test_05_seed_order_and_widths_are_exact(self) -> None:
        rows = self.artifact["seed_routings"]
        self.assertEqual(tuple(row["seed"] for row in rows), EXPECTED_SEEDS)
        self.assertEqual(tuple(row["logical_qubits"] for row in rows), EXPECTED_WIDTHS)

    def test_06_all_v45_input_manifests_are_exact(self) -> None:
        for row in self.artifact["seed_routings"]:
            routed = row["routed_compilation"]
            self.assertTrue(routed["input_manifest_exact_parent"])
            self.assertEqual(routed["route_ir"]["input_instruction_count"], routed["input_stream_manifest"]["instruction_count"])

    def test_07_all_structural_routes_pass_without_violations(self) -> None:
        for row in self.artifact["seed_routings"]:
            native = row["routed_compilation"]["native_ledger"]
            self.assertEqual(row["status"], "PASS_FULL_STREAM_STRUCTURAL_AND_RESOURCE_ROUTING")
            self.assertEqual(native["isa_violations"], 0)
            self.assertEqual(native["coupling_violations"], 0)

    def test_08_final_layouts_are_complete_bijections(self) -> None:
        for row in self.artifact["seed_routings"]:
            layout = row["routed_compilation"]["layout"]
            logical = layout["final_logical_to_physical"]
            physical = layout["final_physical_to_logical"]
            self.assertEqual(len(logical), row["logical_qubits"])
            self.assertEqual(len(set(logical)), len(logical))
            for logical_qubit, physical_qubit in enumerate(logical):
                self.assertEqual(physical[physical_qubit], logical_qubit)

    def test_09_exact_route_profiles_are_pinned(self) -> None:
        observed = []
        for row in self.artifact["seed_routings"]:
            routed = row["routed_compilation"]
            manifest, native = routed["input_stream_manifest"], routed["native_ledger"]
            routing, route_ir, resource = routed["routing_ledger"], routed["route_ir"], row["resource_gate"]
            observed.append((
                row["seed"], row["logical_qubits"], manifest["instruction_count"], manifest["elementary_counts"]["CX"],
                native["native_instruction_count"], native["native_operation_counts"]["cz"], native["swap_count"],
                native["asap_structural_depth"], routing["maximum_distance_before_routing"], len(route_ir["chunk_sha256"]),
                len(route_ir["stage_manifests"]), resource["routed_cz_margin"], resource["depth_margin"],
            ))
        self.assertEqual(tuple(observed), EXPECTED_ROW_METRICS)

    def test_10_every_inherited_resource_gate_passes(self) -> None:
        for row in self.artifact["seed_routings"]:
            resource = row["resource_gate"]
            self.assertEqual(resource["status"], "PASS_PREREGISTERED_V45_ROUTING_RESOURCE_GATE")
            self.assertGreaterEqual(resource["routed_cz_margin"], 0)
            self.assertGreaterEqual(resource["depth_margin"], 0)

    def test_11_aggregate_metrics_are_exact(self) -> None:
        aggregate = self.artifact["aggregate"]
        for key, expected in EXPECTED_AGGREGATE.items():
            self.assertEqual(aggregate[key], expected, key)
        self.assertTrue(aggregate["all_eight_structural_routes_pass"])

    def test_12_decision_and_next_gate_are_exact(self) -> None:
        decisions = self.artifact["decisions"]
        self.assertEqual(decisions["overall"], EXPECTED_OVERALL)
        self.assertEqual(decisions["production_admission"], EXPECTED_PRODUCTION_ADMISSION)
        self.assertEqual(decisions["next_falsifiable_gate"], EXPECTED_NEXT_GATE)

    def test_13_standard_library_checker_passes_36_checks(self) -> None:
        result = independent_check(self.artifact, root=ROOT)
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["check_count"], 36)

    def test_14_independent_validation_passes_57_checks(self) -> None:
        result = run_v46_validation(root=ROOT)
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["counts"], {"checks_passed": EXPECTED_CHECK_COUNT, "checks_total": EXPECTED_CHECK_COUNT})

    def test_15_boundary_is_zero_provider_zero_job_and_hardware_false(self) -> None:
        boundary = self.artifact["claim_boundary"]
        for field in ("credential_reads", "provider_calls", "network_calls", "backend_run_calls", "local_simulator_jobs_submitted", "qpu_jobs_submitted"):
            self.assertEqual(boundary[field], 0, field)
        self.assertFalse(boundary["provider_sdk_imported"])
        self.assertFalse(boundary["provider_credentials_read"])
        self.assertFalse(boundary["hardware_executable"])
        self.assertEqual(boundary["quantum_advantage"], "NOT_CLAIMED")

    def test_16_depth_is_structural_not_calibrated_performance(self) -> None:
        boundary = self.artifact["claim_boundary"]
        self.assertTrue(boundary["structural_asap_depth_uses_gate_layers_not_calibrated_durations"])
        self.assertEqual(boundary["hardware_timing_schedule"], "NOT_RUN")
        self.assertEqual(boundary["calibration_aware_fidelity"], "NOT_TESTED")
        self.assertEqual(boundary["optimization_performance"], "NOT_TESTED")

    def test_17_compiler_has_no_qiskit_or_provider_import(self) -> None:
        tree = ast.parse((ROOT / "quantum_research_lab/phase3_v46_full_stream_routing.py").read_text(encoding="utf-8"))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
        self.assertTrue({"qiskit", "qiskit_ibm_runtime", "requests", "httpx"}.isdisjoint(imports))

    def test_18_rehashed_claim_and_metric_tampering_fail_closed(self) -> None:
        tampered = copy.deepcopy(self.artifact)
        tampered["claim_boundary"]["hardware_executable"] = True
        tampered["seed_routings"][0]["routed_compilation"]["native_ledger"]["swap_count"] += 1
        tampered["artifact_sha256"] = canonical_json_sha256({key: value for key, value in tampered.items() if key != "artifact_sha256"})
        result = validate_v46_artifact(tampered, root=ROOT)
        self.assertFalse(result["passed"])
        self.assertIn("hardware_executable_false", result["failed_checks"])
        self.assertIn("exact_eight_route_profiles", result["failed_checks"])


if __name__ == "__main__":
    unittest.main()
