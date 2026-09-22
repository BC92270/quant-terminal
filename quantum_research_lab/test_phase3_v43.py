"""Scientific regression suite for Quantum Lab V4.3.

The suite authenticates the immutable V4.2 predecessor, the preregistered
V4.3 protocol and the sealed provider-neutral elementary circuit manifests.
It never rebuilds the 21.9 million-instruction streams: the sealing path owns
that expensive operation, while these tests independently replay all nested
hashes, ledgers, unitary templates and the compiled C++17 controls.
"""

from __future__ import annotations

import ast
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import unittest

from .phase3_v43_reversible_circuit_ir import (
    BUDGET_CNOT,
    ELEMENTARY_BASIS,
    EXPECTED_SPEC_RAW_SHA256,
    EXPECTED_SPEC_SHA256,
    SEEDS,
    _compile_simulator,
    _full_adder_ops,
    _high_bit_ops,
    authenticate_v42_parent,
    canonical_json_sha256,
    load_v43_artifact,
    load_v43_spec,
    mandatory_off_promise_witness,
    raw_file_sha256,
    validate_v43_artifact,
)
from .phase3_v43_validation import (
    bridge_unitary_control,
    ccx_unitary_control,
    coin_unitary_control,
    independent_manifest_replay,
    independent_promise_boundary_control,
    run_v43_validation,
)


ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "quantum_research_lab/PHASE_III_V4_3_REVERSIBLE_CIRCUIT_MATERIALIZATION_SPEC_V1.json"
SOURCE_PATH = ROOT / "quantum_research_lab/phase3_v43_reversible_circuit_ir.py"
SIMULATOR_PATH = ROOT / "quantum_research_lab/phase3_v43_reversible_simulator.cpp"
VALIDATION_PATH = ROOT / "quantum_research_lab/phase3_v43_validation.py"
ARTIFACT_PATH = ROOT / "outputs/quantum_phase3/v43_reversible_circuit/SEALED_V4_3_REVERSIBLE_CIRCUIT_ARTIFACT.json"

EXPECTED_ARTIFACT_SHA256 = "36a7a63410da87ce7f98bb10e6d3af3c3d784d9f8e520a6771e42cda9ee593ce"
EXPECTED_ARTIFACT_RAW_SHA256 = "626123fda2ee6561fe74cbb073a03f9987ccbd4e3d01c84b4f2815023e8271e3"
EXPECTED_SOURCE_RAW_SHA256 = "d4dc129721dd7a4429aa473658272fef26f5c90831ecb3d125a730246309838d"
EXPECTED_SIMULATOR_RAW_SHA256 = "420761883ce82825c9a1d01ec55cf116d69f4a80f946dc6c5a8e6c002e61f7e7"
EXPECTED_VALIDATION_RAW_SHA256 = "071d6b8a552d630820bb654a8257ce7669f1aa39a61e3267741dfefb59d52938"
EXPECTED_VALIDATION_EVIDENCE_SHA256 = "90effe2631c36be1461475f7964cd3c32b163f9b88851b664de077841cc502a9"
EXPECTED_STREAM_ROOT_SHA256 = "9405dc3659aa7a86fad4437f3a29bd654d87bae0a221e4d169b4f1f5af43bbeb"
EXPECTED_REGISTER_ROOT_SHA256 = "315e7a7d8742ab5a4456e0ea26be8c94b098050d60bc1ad9dd874900c4b0218e"

EXPECTED_CNOT = {
    1103: 1_106_814,
    2207: 1_110_414,
    3301: 1_084_798,
    4409: 1_084_798,
    5501: 1_084_798,
    6607: 1_106_814,
    7703: 1_158_046,
    8807: 1_128_830,
}
EXPECTED_QUBITS = {
    1103: 330,
    2207: 331,
    3301: 327,
    4409: 328,
    5501: 329,
    6607: 331,
    7703: 339,
    8807: 334,
}
EXPECTED_WIDTHS = {
    1103: [5, 5, 5, 5, 34, 34, 33],
    2207: [5, 5, 5, 5, 35, 33, 33],
    3301: [5, 5, 5, 5, 33, 33, 33],
    4409: [5, 5, 5, 5, 34, 34, 31],
    5501: [5, 5, 5, 5, 35, 32, 32],
    6607: [5, 5, 5, 5, 33, 35, 33],
    7703: [5, 5, 5, 5, 33, 39, 33],
    8807: [5, 5, 5, 5, 36, 36, 31],
}
EXPECTED_INSTRUCTIONS = {
    1103: 2_737_326,
    2207: 2_746_616,
    3301: 2_682_810,
    4409: 2_682_822,
    5501: 2_682_878,
    6607: 2_737_190,
    7703: 2_864_786,
    8807: 2_791_474,
}


def _without(payload: dict[str, object], key: str) -> dict[str, object]:
    return {name: copy.deepcopy(value) for name, value in payload.items() if name != key}


def _provider_imports(path: Path) -> set[str]:
    forbidden = {"qiskit", "cirq", "braket", "pennylane", "qbraid"}
    imported: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    return imported & forbidden


def _apply_boolean_ops(bits: list[int], operations: object) -> None:
    for name, qubits in operations:  # type: ignore[misc]
        if name == "X":
            bits[qubits[0]] ^= 1
        elif name == "CX":
            bits[qubits[1]] ^= bits[qubits[0]]
        elif name == "CCX":
            bits[qubits[2]] ^= bits[qubits[0]] & bits[qubits[1]]
        else:  # pragma: no cover - the frozen arithmetic IR is Boolean only
            raise AssertionError(name)


class TestPhase3V43ScientificContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = load_v43_spec(root=ROOT)
        cls.parent = authenticate_v42_parent(root=ROOT)
        cls.artifact, cls.artifact_report = load_v43_artifact(root=ROOT, rebuild=False)

    def test_01_registered_file_identities_are_exact(self) -> None:
        self.assertEqual(raw_file_sha256(SPEC_PATH), EXPECTED_SPEC_RAW_SHA256)
        self.assertEqual(EXPECTED_SPEC_RAW_SHA256, "ad8904557e850b8850e11ccc410fa3bb44cc15947cf06d7bdee7047f24563226")
        self.assertEqual(raw_file_sha256(SOURCE_PATH), EXPECTED_SOURCE_RAW_SHA256)
        self.assertEqual(raw_file_sha256(SIMULATOR_PATH), EXPECTED_SIMULATOR_RAW_SHA256)
        self.assertEqual(raw_file_sha256(VALIDATION_PATH), EXPECTED_VALIDATION_RAW_SHA256)
        self.assertEqual(raw_file_sha256(ARTIFACT_PATH), EXPECTED_ARTIFACT_RAW_SHA256)

    def test_02_specification_is_preregistered_and_bounded(self) -> None:
        core = {key: value for key, value in self.spec.items() if key not in {"v43_spec_sha", "v43_spec_sha256"}}
        self.assertEqual(canonical_json_sha256(core), EXPECTED_SPEC_SHA256)
        self.assertEqual(self.spec["chronology"]["result_state_at_seal"], "NOT_EVALUATED")
        self.assertEqual(self.spec["chronology"]["confirmatory_protocol_state"], "SEALED_BEFORE_ACCEPTED_V43_ARTIFACT")
        boundary = self.spec["claim_boundary"]
        self.assertEqual(boundary["research_classification"], "RESEARCH_ONLY")
        self.assertEqual(boundary["provider_calls"], 0)
        self.assertEqual(boundary["qpu_jobs_submitted"], 0)
        self.assertFalse(boundary["hardware_executable"])
        self.assertEqual(boundary["quantum_advantage"], "NOT_CLAIMED")

    def test_03_v42_parent_and_all_175_immutable_paths_authenticate(self) -> None:
        self.assertTrue(self.parent["valid"], self.parent["errors"])
        self.assertEqual(self.parent["immutable_file_count"], 175)
        self.assertTrue(self.parent["immutable_files_exact"])
        self.assertTrue(all(self.parent["semantic_checks"].values()))
        self.assertTrue(all(row["valid"] for row in self.parent["raw_checks"].values()))

    def test_04_artifact_raw_semantic_and_loader_identities_are_exact(self) -> None:
        self.assertTrue(self.artifact_report["valid"], self.artifact_report)
        self.assertEqual(self.artifact["artifact_sha256"], EXPECTED_ARTIFACT_SHA256)
        self.assertEqual(
            canonical_json_sha256(_without(self.artifact, "artifact_sha256")),
            EXPECTED_ARTIFACT_SHA256,
        )
        self.assertEqual(self.artifact["source_raw_file_sha256"], EXPECTED_SOURCE_RAW_SHA256)
        self.assertEqual(self.artifact["simulator_source_raw_file_sha256"], EXPECTED_SIMULATOR_RAW_SHA256)

    def test_05_all_eight_seed_stream_and_register_self_hashes_are_exact(self) -> None:
        rows = self.artifact["seed_materializations"]
        self.assertEqual([row["seed"] for row in rows], list(SEEDS))
        for row in rows:
            stream = row["stream_manifest"]
            layout = row["register_layout"]
            self.assertEqual(
                stream["stream_manifest_sha256"],
                canonical_json_sha256(_without(stream, "stream_manifest_sha256")),
            )
            self.assertEqual(
                layout["register_map_sha256"],
                canonical_json_sha256(_without(layout, "register_map_sha256")),
            )
            self.assertEqual(
                row["seed_materialization_sha256"],
                canonical_json_sha256(_without(row, "seed_materialization_sha256")),
            )

    def test_06_ordered_chunk_stage_and_elementary_counts_close(self) -> None:
        for row in self.artifact["seed_materializations"]:
            stream = row["stream_manifest"]
            counts = stream["elementary_counts"]
            self.assertEqual(stream["basis"], list(ELEMENTARY_BASIS))
            self.assertEqual(set(counts), set(ELEMENTARY_BASIS))
            self.assertEqual(sum(counts.values()), stream["instruction_count"])
            self.assertEqual(sum(stream["chunk_instruction_sizes"]), stream["instruction_count"])
            self.assertEqual(sum(stage["instruction_count"] for stage in stream["stage_manifests"]), stream["instruction_count"])
            self.assertEqual(len(stream["chunk_sha256"]), len(stream["chunk_instruction_sizes"]))
            self.assertTrue(all(0 < size <= 8_192 for size in stream["chunk_instruction_sizes"]))
            self.assertTrue(all(len(value) == 64 for value in stream["chunk_sha256"]))
            self.assertTrue(all(len(stage["stage_sha256"]) == 64 for stage in stream["stage_manifests"]))
            # CONTROL_FLAGS reserves one final clean flag for later backend
            # routing work.  The materialized stream must stay inside the
            # allocation and, in V4.3, deliberately leaves that qubit idle.
            self.assertEqual(stream["max_qubit_id"] + 2, stream["total_qubits"])

    def test_07_per_seed_width_cnot_qubit_and_instruction_ledgers_are_exact(self) -> None:
        for row in self.artifact["seed_materializations"]:
            seed = row["seed"]
            self.assertEqual(row["materialized_widths"], EXPECTED_WIDTHS[seed])
            self.assertEqual(row["stream_manifest"]["elementary_counts"]["CX"], EXPECTED_CNOT[seed])
            self.assertEqual(row["budget_margin_cnot"], BUDGET_CNOT - EXPECTED_CNOT[seed])
            self.assertEqual(row["register_layout"]["total_qubits"], EXPECTED_QUBITS[seed])
            self.assertEqual(row["stream_manifest"]["instruction_count"], EXPECTED_INSTRUCTIONS[seed])
            self.assertTrue(row["preregistered_cnot_replay"]["match"])
            self.assertTrue(row["preregistered_qubit_replay"]["match"])

    def test_08_registers_are_contiguous_and_liveness_is_explicit(self) -> None:
        for row in self.artifact["seed_materializations"]:
            cursor = 0
            for register in row["register_layout"]["registers"]:
                self.assertEqual(register["start"], cursor)
                self.assertEqual(register["qubit_ids"], list(range(cursor, cursor + register["width"])))
                cursor += register["width"]
            self.assertEqual(cursor, row["register_layout"]["total_qubits"])
            liveness = row["liveness"]
            self.assertEqual(liveness["peak_qubits"], cursor)
            self.assertTrue(liveness["bridge_target_reuse_after_selector_clean"])
            self.assertTrue(liveness["c7x_constant_first_five_reuse_after_comparator_constants_clean"])
            self.assertEqual(liveness["liveness_decision"], "PASSED_STATIC_DISJOINT_PHASE_AND_CLEAN_EXIT_CONTRACT")

    def test_09_aggregate_and_ordered_roots_are_exact(self) -> None:
        rows = self.artifact["seed_materializations"]
        aggregate = self.artifact["aggregate"]
        self.assertEqual(aggregate["aggregate_sha256"], canonical_json_sha256(_without(aggregate, "aggregate_sha256")))
        self.assertEqual(aggregate["ordered_stream_manifest_root_sha256"], EXPECTED_STREAM_ROOT_SHA256)
        self.assertEqual(aggregate["register_map_root_sha256"], EXPECTED_REGISTER_ROOT_SHA256)
        self.assertEqual(
            aggregate["ordered_stream_manifest_root_sha256"],
            canonical_json_sha256([row["stream_manifest"]["stream_manifest_sha256"] for row in rows]),
        )
        self.assertEqual(
            aggregate["register_map_root_sha256"],
            canonical_json_sha256([row["register_layout"]["register_map_sha256"] for row in rows]),
        )
        self.assertEqual(aggregate["maximum_materialized_cnot"], 1_158_046)
        self.assertEqual(aggregate["minimum_budget_margin_cnot"], 1_341_954)
        self.assertEqual(aggregate["maximum_logical_qubits_with_recycled_workspace"], 339)
        self.assertEqual(aggregate["total_elementary_instructions"], 21_925_902)

    def test_10_preregistered_width_lift_and_postseal_exact_correction_are_visible(self) -> None:
        expectation = self.spec["preregistered_resource_expectation"]
        self.assertEqual(expectation["maximum_materialized_cnot"], 1_158_214)
        self.assertEqual(expectation["minimum_budget_margin_cnot"], 1_341_786)
        amendments = self.artifact["protocol_amendments"]
        self.assertIn("168_CNOT_REMOVED", amendments["interval_predicate"])
        self.assertIn("22784_CNOT_ADDED", amendments["width_three_to_five"])
        self.assertFalse(amendments["v42_bytes_rewritten"])
        self.assertFalse(amendments["v42_cnot_decision_rewritten"])
        self.assertEqual(
            amendments["v42_elementary_basis_omitted_h"],
            "DISCLOSED_AND_CORRECTED_APPEND_ONLY_IN_V43",
        )
        self.assertTrue(all(row["preregistered_cnot_replay"]["total_delta"] == 22_616 for row in self.artifact["seed_materializations"]))

    def test_11_exact_boolean_adder_and_high_bit_identities(self) -> None:
        for width in (4, 5):
            a = tuple(range(width))
            b = tuple(range(width, 2 * width))
            out, carry = 2 * width, 2 * width + 1
            adder = _full_adder_ops(a, b, out, carry)
            comparator = _high_bit_ops(a, b, out, carry)
            self.assertEqual(Counter(name for name, _ in adder), Counter({"CCX": 2 * width - 1, "CX": 5 * width - 3, "X": 2 * width - 4}))
            self.assertEqual(Counter(name for name, _ in comparator), Counter({"CCX": 2 * width - 1, "CX": 4 * width - 3}))
            for left in range(1 << width):
                for right in range(1 << width):
                    initial = [0] * (2 * width + 2)
                    for bit in range(width):
                        initial[a[bit]] = (left >> bit) & 1
                        initial[b[bit]] = (right >> bit) & 1
                    added = initial.copy()
                    _apply_boolean_ops(added, adder)
                    self.assertEqual(sum(added[q] << bit for bit, q in enumerate(a)), left)
                    self.assertEqual(sum(added[q] << bit for bit, q in enumerate(b)), (left + right) & ((1 << width) - 1))
                    self.assertEqual(added[out], int(left + right >= 1 << width))
                    self.assertEqual(added[carry], 0)
                    compared = initial.copy()
                    _apply_boolean_ops(compared, comparator)
                    self.assertEqual(compared[: 2 * width], initial[: 2 * width])
                    self.assertEqual(compared[out], int(left + right >= 1 << width))
                    self.assertEqual(compared[carry], 0)

    def test_12_independent_cpp_replay_covers_107520_arithmetic_and_64_promise_cases(self) -> None:
        replay = _compile_simulator(root=ROOT)
        self.assertEqual(replay, self.artifact["independent_cpp_simulator"])
        self.assertEqual(replay["status"], "PASS")
        self.assertTrue(replay["valid"])
        self.assertEqual(replay["pass_counts"]["arithmetic_cases"], 107_520)
        self.assertEqual(replay["pass_counts"]["promise_select_cases"], 64)
        self.assertEqual(replay["pass_counts"]["promise_select_roundtrips"], 64)
        self.assertEqual(replay["failure_count"], 0)

    def test_13_mandatory_off_promise_cleanup_generalization_is_rejected(self) -> None:
        witness = mandatory_off_promise_witness()
        self.assertEqual(witness, self.artifact["mandatory_off_promise_control"])
        self.assertEqual(witness["status"], "OFF_PROMISE_CLEANUP_REJECTED_WITH_WITNESS")
        self.assertEqual(witness["start_mask_hex"], "0000000002")
        self.assertEqual(witness["target_mask_hex"], "0000000001")
        self.assertEqual(witness["move"], 1)
        self.assertEqual(witness["retained_feasible_flag_after_reverse"], 1)
        self.assertTrue(witness["witness_detected"])
        negative = self.artifact["independent_cpp_simulator"]["negative_control"]
        self.assertFalse(negative["cleanup_accepted"])
        self.assertEqual(negative["retained_feasibility_flag"], 1)

    def test_14_real_n40_promise_witnesses_move_and_cleanup_for_every_seed(self) -> None:
        for row in self.artifact["seed_materializations"]:
            witness = row["real_n40_promise_select_witness"]
            self.assertEqual(witness["move"], 1)
            self.assertEqual(witness["retained_feasible_flag_after_reverse"], 0)
            self.assertEqual(witness["reverse_target_mask_hex"], witness["start_mask_hex"])
            self.assertTrue(witness["promise_cleanup_passed"])
            self.assertEqual(witness["witness_sha256"], canonical_json_sha256(_without(witness, "witness_sha256")))
        control = independent_promise_boundary_control(self.artifact)
        self.assertTrue(control["passed"])
        self.assertTrue(control["off_promise_cleanup_generalization_rejected"])

    def test_15_ccx_coin_and_bridge_unitary_controls_are_exact(self) -> None:
        ccx = ccx_unitary_control()
        coin = coin_unitary_control()
        bridge = bridge_unitary_control()
        self.assertTrue(ccx["passed"])
        self.assertEqual((ccx["cnot_count"], ccx["one_qubit_count"]), (6, 9))
        self.assertLess(ccx["max_error_up_to_global_phase"], 1e-12)
        self.assertTrue(coin["passed"])
        self.assertEqual(coin["cnot_count"], 2)
        self.assertTrue(coin["one_hot_subspace_preserved"])
        self.assertTrue(bridge["passed"])
        self.assertEqual(bridge["endpoint_pairs"], 88)
        self.assertLess(bridge["maximum_error_up_to_global_phase"], 1e-12)

    def test_16_independent_manifest_replay_and_31_check_validation_pass(self) -> None:
        manifest = independent_manifest_replay(self.artifact, self.parent)
        self.assertTrue(manifest["passed"])
        self.assertTrue(manifest["aggregate_exact"])
        self.assertEqual(len(manifest["row_checks"]), 8)
        validation = run_v43_validation(root=ROOT, rebuild_streams=False)
        self.assertTrue(validation["passed"], validation)
        self.assertEqual(validation["counts"], {"checks_passed": 31, "checks_total": 31})
        self.assertEqual(validation["failed_checks"], [])
        self.assertFalse(validation["deep_stream_rebuild"])
        self.assertEqual(validation["validation_evidence_sha256"], EXPECTED_VALIDATION_EVIDENCE_SHA256)

    def test_17_nested_tampering_is_rejected_after_top_level_rehash(self) -> None:
        mutations = (
            ("chunk", lambda item: item["seed_materializations"][0]["stream_manifest"]["chunk_sha256"].__setitem__(0, "0" * 64)),
            ("cnot", lambda item: item["seed_materializations"][0]["stream_manifest"]["elementary_counts"].__setitem__("CX", 1)),
            ("qubits", lambda item: item["seed_materializations"][0]["register_layout"].__setitem__("total_qubits", 1)),
            ("root", lambda item: item["aggregate"].__setitem__("ordered_stream_manifest_root_sha256", "0" * 64)),
            ("boundary", lambda item: item["claim_boundary"].__setitem__("hardware_executable", True)),
        )
        for name, mutate in mutations:
            with self.subTest(name=name):
                tampered = copy.deepcopy(self.artifact)
                mutate(tampered)
                tampered["artifact_sha256"] = canonical_json_sha256(_without(tampered, "artifact_sha256"))
                report = validate_v43_artifact(tampered, root=ROOT, rebuild=False)
                self.assertFalse(report["valid"], report)
                self.assertTrue(report["failed_checks"])

    def test_18_provider_sdk_imports_and_execution_claims_remain_zero(self) -> None:
        self.assertEqual(_provider_imports(SOURCE_PATH), set())
        self.assertEqual(_provider_imports(VALIDATION_PATH), set())
        boundary = self.artifact["claim_boundary"]
        self.assertEqual(self.artifact["research_classification"], "RESEARCH_ONLY")
        self.assertFalse(boundary["provider_sdk_imported"])
        self.assertFalse(boundary["provider_credentials_read"])
        self.assertEqual(boundary["provider_calls"], 0)
        self.assertEqual(boundary["qpu_jobs_submitted"], 0)
        self.assertFalse(boundary["hardware_executable"])
        self.assertEqual(boundary["backend_transpilation"], "NOT_RUN")
        self.assertEqual(boundary["optimization_performance"], "NOT_TESTED")
        self.assertEqual(boundary["quantum_advantage"], "NOT_CLAIMED")
        decisions = self.artifact["decisions"]
        self.assertEqual(decisions["overall"], "V43_BACKEND_AGNOSTIC_CIRCUIT_MATERIALIZED_PROMISE_SIMULATION_PASSED")
        self.assertEqual(decisions["next_falsifiable_gate"], "NAMED_BACKEND_ZERO_JOB_TRANSPILATION_AND_ROUTING_PROTOCOL")
        self.assertEqual(decisions["production_admission"], "PROVIDER_NEUTRAL_RESEARCH_CIRCUIT_IR_ADMITTED_BACKEND_AND_HARDWARE_NOT_AUTHORIZED")


if __name__ == "__main__":
    unittest.main()


__all__ = [
    "EXPECTED_ARTIFACT_RAW_SHA256",
    "EXPECTED_ARTIFACT_SHA256",
    "EXPECTED_SIMULATOR_RAW_SHA256",
    "EXPECTED_SOURCE_RAW_SHA256",
    "EXPECTED_VALIDATION_EVIDENCE_SHA256",
    "EXPECTED_VALIDATION_RAW_SHA256",
]
