"""Independent scientific controls for Quantum Lab V4.3.

The replay authenticates the immutable V4.2 parent, recomputes every aggregate
from the sealed V4.3 manifests, executes the separately implemented C++17
simulator, and verifies the elementary CCX, XX+YY and Gray-path two-level
templates without a provider SDK.  It deliberately preserves the negative
off-promise cleanup witness instead of generalizing the promise theorem.
"""

from __future__ import annotations

import ast
import cmath
import copy
from itertools import combinations
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from .phase3_v43_reversible_circuit_ir import (
    BUDGET_CNOT,
    ELEMENTARY_BASIS,
    SEEDS,
    _compile_simulator,
    authenticate_v42_parent,
    canonical_json_sha256,
    load_v43_artifact,
    load_v43_spec,
    mandatory_off_promise_witness,
    raw_file_sha256,
)


VALIDATION_VERSION = "QUANTUM LAB V4.3 INDEPENDENT CIRCUIT VALIDATION · V1"


def _root(root: str | Path | None = None) -> Path:
    return Path(root).resolve() if root is not None else Path(__file__).resolve().parents[1]


def _without(payload: Mapping[str, Any], key: str) -> dict[str, Any]:
    return {name: copy.deepcopy(value) for name, value in payload.items() if name != key}


def _provider_free_imports(path: Path) -> bool:
    forbidden = {"qiskit", "cirq", "braket", "pennylane", "qbraid"}
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        if any(name.split(".")[0] in forbidden for name in names):
            return False
    return True


def _apply_one_qubit(state: list[complex], n: int, q: int, matrix: Sequence[Sequence[complex]]) -> None:
    stride = 1 << q
    for base in range(0, 1 << n, stride << 1):
        for offset in range(stride):
            i0 = base + offset
            i1 = i0 + stride
            a, b = state[i0], state[i1]
            state[i0] = matrix[0][0] * a + matrix[0][1] * b
            state[i1] = matrix[1][0] * a + matrix[1][1] * b


def _apply_cx(state: list[complex], n: int, control: int, target: int) -> None:
    for index in range(1 << n):
        if ((index >> control) & 1) and not ((index >> target) & 1):
            partner = index | (1 << target)
            state[index], state[partner] = state[partner], state[index]


def _apply_pattern_x(state: list[complex], n: int, controls: Sequence[int], values: Sequence[int], target: int) -> None:
    for index in range(1 << n):
        if (index >> target) & 1:
            continue
        if all(((index >> q) & 1) == int(value) for q, value in zip(controls, values)):
            partner = index | (1 << target)
            state[index], state[partner] = state[partner], state[index]


def _ry(angle: float) -> tuple[tuple[complex, complex], tuple[complex, complex]]:
    return ((math.cos(angle / 2), -math.sin(angle / 2)), (math.sin(angle / 2), math.cos(angle / 2)))


def _rz(angle: float) -> tuple[tuple[complex, complex], tuple[complex, complex]]:
    return ((cmath.exp(-0.5j * angle), 0j), (0j, cmath.exp(0.5j * angle)))


H = ((1 / math.sqrt(2), 1 / math.sqrt(2)), (1 / math.sqrt(2), -1 / math.sqrt(2)))
T = ((1 + 0j, 0j), (0j, cmath.exp(0.25j * math.pi)))
TDG = ((1 + 0j, 0j), (0j, cmath.exp(-0.25j * math.pi)))


def _columns(n: int, apply: Any) -> list[list[complex]]:
    columns: list[list[complex]] = []
    for basis in range(1 << n):
        state = [0j] * (1 << n)
        state[basis] = 1 + 0j
        apply(state)
        columns.append(state)
    return columns


def _max_error_up_to_global(actual: Sequence[Sequence[complex]], expected: Sequence[Sequence[complex]]) -> float:
    overlap = sum(expected[col][row].conjugate() * actual[col][row] for col in range(len(actual)) for row in range(len(actual[col])))
    phase = overlap / abs(overlap) if abs(overlap) else 1 + 0j
    return max(abs(actual[col][row] - phase * expected[col][row]) for col in range(len(actual)) for row in range(len(actual[col])))


def ccx_unitary_control() -> dict[str, Any]:
    operations: tuple[tuple[Any, ...], ...] = (
        ("H", 2), ("CX", 1, 2), ("TDG", 2), ("CX", 0, 2), ("T", 2),
        ("CX", 1, 2), ("TDG", 2), ("CX", 0, 2), ("T", 1), ("T", 2),
        ("H", 2), ("CX", 0, 1), ("T", 0), ("TDG", 1), ("CX", 0, 1),
    )

    def apply_actual(state: list[complex]) -> None:
        for operation in operations:
            if operation[0] == "CX":
                _apply_cx(state, 3, operation[1], operation[2])
            else:
                _apply_one_qubit(state, 3, operation[1], {"H": H, "T": T, "TDG": TDG}[operation[0]])

    def apply_expected(state: list[complex]) -> None:
        _apply_pattern_x(state, 3, (0, 1), (1, 1), 2)

    error = _max_error_up_to_global(_columns(3, apply_actual), _columns(3, apply_expected))
    core = {
        "basis": ["H", "T", "TDG", "CX"],
        "cnot_count": sum(operation[0] == "CX" for operation in operations),
        "max_error_up_to_global_phase": error,
        "one_qubit_count": sum(operation[0] != "CX" for operation in operations),
        "passed": error < 1e-12,
    }
    return {**core, "control_sha256": canonical_json_sha256(core)}


def coin_unitary_control() -> dict[str, Any]:
    theta = math.pi / 2
    operations: tuple[tuple[Any, ...], ...] = (
        ("RZ", 1, -math.pi / 2), ("H", 1), ("RZ", 1, math.pi / 2), ("H", 1),
        ("RZ", 1, math.pi / 2), ("RZ", 0, math.pi / 2), ("CX", 1, 0),
        ("RY", 1, -theta / 2), ("RY", 0, -theta / 2), ("CX", 1, 0),
        ("RZ", 0, -math.pi / 2), ("RZ", 1, -math.pi / 2), ("H", 1),
        ("RZ", 1, -math.pi / 2), ("H", 1), ("RZ", 1, math.pi / 2),
    )

    def apply_actual(state: list[complex]) -> None:
        for operation in operations:
            if operation[0] == "CX":
                _apply_cx(state, 2, operation[1], operation[2])
            elif operation[0] == "H":
                _apply_one_qubit(state, 2, operation[1], H)
            else:
                _apply_one_qubit(state, 2, operation[1], _ry(operation[2]) if operation[0] == "RY" else _rz(operation[2]))

    def apply_expected(state: list[complex]) -> None:
        old = list(state)
        c = math.cos(theta / 2)
        s = -1j * math.sin(theta / 2)
        state[1] = c * old[1] + s * old[2]
        state[2] = s * old[1] + c * old[2]

    error = _max_error_up_to_global(_columns(2, apply_actual), _columns(2, apply_expected))
    core = {
        "cnot_count": sum(operation[0] == "CX" for operation in operations),
        "max_error_up_to_global_phase": error,
        "one_hot_subspace_preserved": error < 1e-12,
        "passed": error < 1e-12,
        "theta_pi": [1, 2],
    }
    return {**core, "control_sha256": canonical_json_sha256(core)}


def bridge_unitary_control() -> dict[str, Any]:
    n = 4
    theta = math.pi / 2
    cases = 0
    maximum_error = 0.0
    for source, target in combinations(range(1 << n), 2):
        differing = [index for index in range(n) if ((source ^ target) >> index) & 1]
        if len(differing) < 2:
            continue
        path = [source]
        current = source
        for index in differing:
            current ^= 1 << index
            path.append(current)

        def edge(state: list[complex], pattern: int, target_bit: int) -> None:
            controls = tuple(index for index in range(n) if index != target_bit)
            values = tuple((pattern >> index) & 1 for index in controls)
            _apply_pattern_x(state, n, controls, values, target_bit)

        def apply_actual(state: list[complex]) -> None:
            for position in range(len(differing) - 1):
                edge(state, path[position], differing[position])
            target_bit = differing[-1]
            controls = tuple(index for index in range(n) if index != target_bit)
            values = tuple((path[-2] >> index) & 1 for index in controls)
            _apply_one_qubit(state, n, target_bit, _ry(theta / 2))
            _apply_pattern_x(state, n, controls, values, target_bit)
            _apply_one_qubit(state, n, target_bit, _ry(-theta / 2))
            _apply_pattern_x(state, n, controls, values, target_bit)
            for position in range(len(differing) - 2, -1, -1):
                edge(state, path[position], differing[position])

        def apply_expected(state: list[complex]) -> None:
            old_source, old_target = state[source], state[target]
            state[source] = math.cos(theta / 2) * old_source - math.sin(theta / 2) * old_target
            state[target] = math.sin(theta / 2) * old_source + math.cos(theta / 2) * old_target

        error = _max_error_up_to_global(_columns(n, apply_actual), _columns(n, apply_expected))
        maximum_error = max(maximum_error, error)
        cases += 1
    core = {
        "endpoint_pairs": cases,
        "maximum_error_up_to_global_phase": maximum_error,
        "passed": cases == 88 and maximum_error < 1e-12,
        "small_domain_qubits": n,
        "theta_pi": [1, 2],
    }
    return {**core, "control_sha256": canonical_json_sha256(core)}


def independent_manifest_replay(artifact: Mapping[str, Any], parent: Mapping[str, Any]) -> dict[str, Any]:
    parent_rows = {
        int(row["seed"]): row
        for row in (parent.get("artifact") or {}).get("resource_evidence", {}).get("seed_rows", [])
    }
    rows = artifact.get("seed_materializations") or []
    row_checks: list[dict[str, Any]] = []
    for row in rows:
        seed = int(row["seed"])
        stream = row.get("stream_manifest") or {}
        counts = stream.get("elementary_counts") or {}
        parent_row = parent_rows.get(seed) or {}
        expected_cnot = int((parent_row.get("selected_model_step_resources") or {}).get("selected_model_cnot", -22_616)) + 22_616
        expected_qubits = int(parent_row.get("logical_qubits_with_recycled_workspace", -8)) + 8
        stage_total = sum(int(stage.get("instruction_count", 0)) for stage in stream.get("stage_manifests") or [])
        chunk_total = sum(int(value) for value in stream.get("chunk_instruction_sizes") or [])
        register_layout = row.get("register_layout") or {}
        registers = register_layout.get("registers") or []
        contiguous = bool(registers and registers[0].get("start") == 0)
        cursor = 0
        for register in registers:
            contiguous = contiguous and int(register.get("start", -1)) == cursor
            cursor += int(register.get("width", 0))
        core = {
            "basis_exact": stream.get("basis") == list(ELEMENTARY_BASIS),
            "budget_margin_exact": int(row.get("budget_margin_cnot", -1)) == BUDGET_CNOT - int(counts.get("CX", -1)),
            "chunk_count_exact": len(stream.get("chunk_sha256") or []) == len(stream.get("chunk_instruction_sizes") or []),
            "chunk_total_exact": chunk_total == int(stream.get("instruction_count", -1)),
            "cnot_exact": int(counts.get("CX", -1)) == expected_cnot,
            "layout_contiguous": contiguous and cursor == int(register_layout.get("total_qubits", -1)),
            "qubits_exact": int(register_layout.get("total_qubits", -1)) == expected_qubits,
            "seed": seed,
            "stage_total_exact": stage_total == int(stream.get("instruction_count", -1)),
            "stream_count_exact": sum(int(counts.get(name, 0)) for name in ELEMENTARY_BASIS) == int(stream.get("instruction_count", -1)),
        }
        row_checks.append({**core, "passed": all(value is True for key, value in core.items() if key != "seed")})
    aggregate = artifact.get("aggregate") or {}
    actual_cnot = [int((row.get("stream_manifest") or {}).get("elementary_counts", {}).get("CX", -1)) for row in rows]
    actual_qubits = [int((row.get("register_layout") or {}).get("total_qubits", -1)) for row in rows]
    core = {
        "aggregate_exact": bool(
            actual_cnot
            and aggregate.get("maximum_materialized_cnot") == max(actual_cnot)
            and aggregate.get("minimum_budget_margin_cnot") == min(BUDGET_CNOT - value for value in actual_cnot)
            and aggregate.get("maximum_logical_qubits_with_recycled_workspace") == max(actual_qubits)
            and aggregate.get("total_elementary_instructions")
            == sum(int((row.get("stream_manifest") or {}).get("instruction_count", -1)) for row in rows)
        ),
        "all_rows_passed": len(row_checks) == 8 and all(row["passed"] for row in row_checks),
        "row_checks": row_checks,
    }
    return {**core, "control_sha256": canonical_json_sha256(core), "passed": core["aggregate_exact"] and core["all_rows_passed"]}


def independent_promise_boundary_control(artifact: Mapping[str, Any]) -> dict[str, Any]:
    promise_rows = []
    for row in artifact.get("seed_materializations") or []:
        witness = row.get("real_n40_promise_select_witness") or {}
        promise_rows.append({
            "cleanup": witness.get("retained_feasible_flag_after_reverse") == 0,
            "move": witness.get("move") == 1,
            "seed": row.get("seed"),
            "source_restored_as_reverse_target": witness.get("start_mask_hex") == witness.get("reverse_target_mask_hex"),
        })
    negative = mandatory_off_promise_witness()
    core = {
        "off_promise_cleanup_generalization_rejected": negative.get("retained_feasible_flag_after_reverse") == 1,
        "off_promise_status": negative.get("status"),
        "promise_rows": promise_rows,
        "promise_rows_passed": len(promise_rows) == 8 and all(all(value is True for key, value in row.items() if key != "seed") for row in promise_rows),
    }
    return {**core, "control_sha256": canonical_json_sha256(core), "passed": core["promise_rows_passed"] and core["off_promise_cleanup_generalization_rejected"]}


def run_v43_validation(
    *,
    root: str | Path | None = None,
    progress: Any | None = None,
    rebuild_streams: bool = False,
) -> dict[str, Any]:
    base = _root(root)
    spec = load_v43_spec(root=base)
    parent = authenticate_v42_parent(root=base)
    artifact, artifact_report = load_v43_artifact(root=base, rebuild=rebuild_streams)
    if progress is not None:
        progress("V4.3 validation · independent elementary-template unitary controls")
    ccx = ccx_unitary_control()
    coin = coin_unitary_control()
    bridge = bridge_unitary_control()
    if progress is not None:
        progress("V4.3 validation · independent C++17 arithmetic and SELECT simulator")
    cpp = _compile_simulator(root=base)
    manifest = independent_manifest_replay(artifact, parent)
    boundary_control = independent_promise_boundary_control(artifact)
    boundary = artifact.get("claim_boundary") or {}
    decisions = artifact.get("decisions") or {}
    aggregate = artifact.get("aggregate") or {}
    source_paths = [
        base / "quantum_research_lab/phase3_v43_reversible_circuit_ir.py",
        base / "quantum_research_lab/phase3_v43_validation.py",
    ]
    checks: dict[str, bool] = {
        "spec_sealed_before_result": spec.get("chronology", {}).get("result_state_at_seal") == "NOT_EVALUATED",
        "parent_v42_exact": parent.get("valid") is True and parent.get("immutable_file_count") == 175,
        "artifact_validator": artifact_report.get("valid") is True,
        "artifact_self_hash": artifact.get("artifact_sha256") == canonical_json_sha256(_without(artifact, "artifact_sha256")),
        "source_identity": artifact.get("source_raw_file_sha256") == raw_file_sha256(source_paths[0]),
        "simulator_identity": artifact.get("simulator_source_raw_file_sha256") == raw_file_sha256(base / "quantum_research_lab/phase3_v43_reversible_simulator.cpp"),
        "provider_free_python_imports": all(_provider_free_imports(path) for path in source_paths),
        "ccx_unitary_exact": ccx.get("passed") is True and ccx.get("cnot_count") == 6 and ccx.get("one_qubit_count") == 9,
        "coin_unitary_exact": coin.get("passed") is True and coin.get("cnot_count") == 2,
        "bridge_unitary_exact": bridge.get("passed") is True,
        "cpp_status_pass": cpp.get("status") == "PASS" and cpp.get("valid") is True,
        "cpp_arithmetic_exhaustive": cpp.get("pass_counts", {}).get("arithmetic_cases") == 107_520,
        "cpp_promise_select": cpp.get("pass_counts", {}).get("promise_select_cases") == 64 and cpp.get("pass_counts", {}).get("promise_select_roundtrips") == 64,
        "cpp_off_promise_rejected": cpp.get("negative_control", {}).get("status") == "OFF_PROMISE_CLEANUP_REJECTED_WITH_WITNESS" and cpp.get("negative_control", {}).get("retained_feasibility_flag") == 1,
        "cpp_replay_stable": cpp == artifact.get("independent_cpp_simulator"),
        "manifest_replay": manifest.get("passed") is True,
        "promise_boundary_control": boundary_control.get("passed") is True,
        "all_seeds_materialized": aggregate.get("seed_count") == 8 and [row.get("seed") for row in artifact.get("seed_materializations") or []] == list(SEEDS),
        "resource_gate_exact": aggregate.get("maximum_materialized_cnot") == 1_158_046 and aggregate.get("minimum_budget_margin_cnot") == 1_341_954,
        "qubit_gate_exact": aggregate.get("maximum_logical_qubits_with_recycled_workspace") == 339,
        "stream_roots_present": len(str(aggregate.get("ordered_stream_manifest_root_sha256", ""))) == 64 and len(str(aggregate.get("register_map_root_sha256", ""))) == 64,
        "protocol_amendments_visible": (artifact.get("protocol_amendments") or {}).get("v42_bytes_rewritten") is False and (artifact.get("protocol_amendments") or {}).get("v42_elementary_basis_omitted_h") == "DISCLOSED_AND_CORRECTED_APPEND_ONLY_IN_V43",
        "decision_exact": decisions.get("overall") == "V43_BACKEND_AGNOSTIC_CIRCUIT_MATERIALIZED_PROMISE_SIMULATION_PASSED" and decisions.get("next_falsifiable_gate") == "NAMED_BACKEND_ZERO_JOB_TRANSPILATION_AND_ROUTING_PROTOCOL",
        "production_still_blocked": decisions.get("production_admission") == "PROVIDER_NEUTRAL_RESEARCH_CIRCUIT_IR_ADMITTED_BACKEND_AND_HARDWARE_NOT_AUTHORIZED",
        "research_only": artifact.get("research_classification") == "RESEARCH_ONLY" and boundary.get("research_classification") == "RESEARCH_ONLY",
        "provider_calls_zero": boundary.get("provider_calls") == 0 and boundary.get("provider_sdk_imported") is False and boundary.get("provider_credentials_read") is False,
        "qpu_jobs_zero": boundary.get("qpu_jobs_submitted") == 0 and boundary.get("qpu_submission_enabled") is False,
        "backend_not_run": boundary.get("backend_transpilation") == "NOT_RUN" and boundary.get("named_backend_selected") is False,
        "hardware_false": boundary.get("hardware_executable") is False,
        "performance_not_tested": boundary.get("optimization_performance") == "NOT_TESTED",
        "advantage_not_claimed": boundary.get("quantum_advantage") == "NOT_CLAIMED",
    }
    failed = [name for name, passed in checks.items() if passed is not True]
    core = {
        "artifact_sha256": artifact.get("artifact_sha256"),
        "checks": checks,
        "counts": {"checks_passed": len(checks) - len(failed), "checks_total": len(checks)},
        "deep_stream_rebuild": bool(rebuild_streams),
        "errors": [],
        "failed_checks": failed,
        "independent_controls": {
            "bridge_unitary": bridge,
            "ccx_unitary": ccx,
            "coin_unitary": coin,
            "cpp_simulator": cpp,
            "manifest_replay": manifest,
            "promise_boundary": boundary_control,
        },
        "passed": not failed,
        "validation_version": VALIDATION_VERSION,
    }
    return {**core, "validation_evidence_sha256": canonical_json_sha256(core)}


__all__ = [
    "VALIDATION_VERSION",
    "bridge_unitary_control",
    "ccx_unitary_control",
    "coin_unitary_control",
    "independent_manifest_replay",
    "independent_promise_boundary_control",
    "run_v43_validation",
]
