"""Exact elementary lowering of the V3.3 doubly-guarded XY primitive.

The lowering is deliberately provider neutral.  For data qubits ``i, j`` and
oracle guard bits ``a=f(x), b=f(S_ij x)``, it implements

    CX(i, j) ; C3-RX(i, 2 beta | a,b,j) ; CX(i, j)

with two clean scratch qubits.  The three-controlled RX is reduced to a clean
AND ladder, an exact CRX decomposition, and the reverse AND ladder.  The two
scratch qubits are borrowed from the already-clean oracle work register, so
the lowering adds no logical qubits to the V3.4 sequential-reuse envelope.

No named SDK, coupling map, backend target, pulse schedule, calibration, noise
model or QPU is used here.  The arbitrary RY rotations remain continuous and
their fault-tolerant approximation cost is explicitly NOT_ESTIMATED.
"""

from __future__ import annotations

import hashlib
import cmath
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from .phase3_algorithmic_contract import (
    PROFILE_DUAL_GUARD,
    SUPPORTED_TOPOLOGIES,
    edge_schedule,
)
from .phase3_gate_compiler import canonical_json_sha256
from .phase3_optimized_oracle import OptimizedCircuitIR, analyze_optimized_circuit


NATIVE_LOWERING_VERSION = "PHASE III · CLEAN-SCRATCH C2-XY LOWERING · V1"
SCHEDULE_QUBITS = ("a", "b", "i", "j", "and_ab", "guard")
VALIDATION_BETAS = (0.0, 0.137, math.pi / 7.0, 0.731, math.pi / 2.0, -0.4)


def native_mixer_source_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def elementary_c2xy_schedule() -> tuple[dict[str, Any], ...]:
    """Return the canonical exact lowering, in chronological gate order."""

    return (
        {"gate": "CX", "controls": ["i"], "target": "j", "stage": "PARITY_MAP"},
        {
            "gate": "CCX",
            "controls": ["a", "b"],
            "target": "and_ab",
            "stage": "GUARD_COMPUTE",
        },
        {
            "gate": "CCX",
            "controls": ["and_ab", "j"],
            "target": "guard",
            "stage": "GUARD_COMPUTE",
        },
        {
            "gate": "RZ",
            "target": "i",
            "angle": {"pi_multiple": 0.5},
            "stage": "CRX",
        },
        {"gate": "CX", "controls": ["guard"], "target": "i", "stage": "CRX"},
        {
            "gate": "RY",
            "target": "i",
            "angle": {"beta_coefficient": -1.0},
            "stage": "CRX",
        },
        {"gate": "CX", "controls": ["guard"], "target": "i", "stage": "CRX"},
        {
            "gate": "RY",
            "target": "i",
            "angle": {"beta_coefficient": 1.0},
            "stage": "CRX",
        },
        {
            "gate": "RZ",
            "target": "i",
            "angle": {"pi_multiple": -0.5},
            "stage": "CRX",
        },
        {
            "gate": "CCX",
            "controls": ["and_ab", "j"],
            "target": "guard",
            "stage": "GUARD_UNCOMPUTE",
        },
        {
            "gate": "CCX",
            "controls": ["a", "b"],
            "target": "and_ab",
            "stage": "GUARD_UNCOMPUTE",
        },
        {"gate": "CX", "controls": ["i"], "target": "j", "stage": "PARITY_UNMAP"},
    )


def elementary_schedule_sha256() -> str:
    return canonical_json_sha256(
        {
            "lowering_version": NATIVE_LOWERING_VERSION,
            "qubit_order": list(SCHEDULE_QUBITS),
            "schedule": list(elementary_c2xy_schedule()),
        }
    )


def elementary_resource_per_edge() -> dict[str, Any]:
    """Exact gate inventory plus an explicit, non-native FT cost model."""

    return {
        "abstract_elementary": {
            "CCX": 4,
            "CX": 4,
            "RY_CONTINUOUS": 2,
            "RZ_PI_OVER_2_CLIFFORD": 2,
            "gate_count": 12,
            "serial_schedule_depth": 12,
        },
        "clean_scratch": {
            "count": 2,
            "initial_state": "|00>",
            "returned_state": "|00>",
            "reuse_source": "OPTIMIZED_ORACLE_WORK_REGISTER_AFTER_UNCOMPUTE",
            "additional_logical_qubits": 0,
        },
        "ccx_7t_cost_model": {
            "basis": "FOUR_CCX_AT_7T_6CX_2H_EACH_PLUS_EXPLICIT_CRX_AND_PARITY_GATES",
            "CX": 28,
            "H": 8,
            "T_OR_T_DAGGER": 28,
            "RY_CONTINUOUS": 2,
            "RZ_PI_OVER_2_CLIFFORD": 2,
            "discrete_fault_tolerant_rotation_synthesis": "NOT_ESTIMATED",
        },
        "claim_boundary": {
            "backend_native": False,
            "named_backend_transpilation": "NOT_RUN",
            "routing": "NOT_RUN",
            "continuous_rotation_identity": "EXACT",
            "fault_tolerant_rotation_approximation": "NOT_ESTIMATED",
        },
    }


def _qubit_index(label: str) -> int:
    try:
        return SCHEDULE_QUBITS.index(label)
    except ValueError as exc:
        raise ValueError(f"Unknown schedule qubit: {label}") from exc


def _apply_x_like(
    state: Sequence[complex], target: int, controls: Sequence[int]
) -> list[complex]:
    result = list(state)
    target_mask = 1 << int(target)
    controls_mask = sum(1 << int(control) for control in controls)
    for basis in range(len(state)):
        if basis & target_mask or (basis & controls_mask) != controls_mask:
            continue
        peer = basis | target_mask
        result[basis] = state[peer]
        result[peer] = state[basis]
    return result


def _apply_rotation(
    state: Sequence[complex],
    target: int,
    matrix: tuple[tuple[complex, complex], tuple[complex, complex]],
) -> list[complex]:
    result = list(state)
    mask = 1 << int(target)
    for basis in range(len(state)):
        if basis & mask:
            continue
        peer = basis | mask
        low, high = state[basis], state[peer]
        result[basis] = matrix[0][0] * low + matrix[0][1] * high
        result[peer] = matrix[1][0] * low + matrix[1][1] * high
    return result


def _rotation_matrix(
    kind: str, angle: float
) -> tuple[tuple[complex, complex], tuple[complex, complex]]:
    half = float(angle) / 2.0
    if kind == "RY":
        return (
            (complex(math.cos(half)), complex(-math.sin(half))),
            (complex(math.sin(half)), complex(math.cos(half))),
        )
    if kind == "RZ":
        return (
            (cmath.exp(-0.5j * angle), 0j),
            (0j, cmath.exp(0.5j * angle)),
        )
    raise ValueError(f"Unsupported rotation: {kind}")


def _resolve_angle(payload: Mapping[str, Any], beta: float) -> float:
    angle = payload.get("angle") or {}
    if "beta_coefficient" in angle:
        return float(angle["beta_coefficient"]) * float(beta)
    if "pi_multiple" in angle:
        return float(angle["pi_multiple"]) * math.pi
    raise ValueError("Rotation gate is missing a symbolic angle.")


def simulate_elementary_schedule(
    initial_state: Sequence[complex], beta: float
) -> list[complex]:
    """Apply the canonical six-qubit lowering to a statevector."""

    state = [complex(value) for value in initial_state]
    expected_size = 1 << len(SCHEDULE_QUBITS)
    if len(state) != expected_size:
        raise ValueError(f"Expected a {expected_size}-amplitude statevector.")
    for gate in elementary_c2xy_schedule():
        kind = str(gate["gate"])
        target = _qubit_index(str(gate["target"]))
        controls = tuple(_qubit_index(str(item)) for item in gate.get("controls", []))
        if kind in {"CX", "CCX"}:
            state = _apply_x_like(state, target, controls)
        elif kind in {"RY", "RZ"}:
            state = _apply_rotation(state, target, _rotation_matrix(kind, _resolve_angle(gate, beta)))
        else:
            raise ValueError(f"Unsupported elementary gate: {kind}")
    return state


def _basis_index(bits: Sequence[int]) -> int:
    if len(bits) != len(SCHEDULE_QUBITS) or any(int(bit) not in (0, 1) for bit in bits):
        raise ValueError("Basis state must provide six binary values.")
    return sum(int(bit) << index for index, bit in enumerate(bits))


def ideal_guarded_xy_state(
    a: int, b: int, i: int, j: int, beta: float
) -> list[complex]:
    """Return the ideal C2-XY action with clean scratch qubits."""

    bits = [int(a), int(b), int(i), int(j), 0, 0]
    state = [0j] * (1 << len(SCHEDULE_QUBITS))
    source = _basis_index(bits)
    if int(a) and int(b) and int(i) != int(j):
        swapped = bits.copy()
        swapped[2], swapped[3] = swapped[3], swapped[2]
        state[source] = math.cos(float(beta))
        state[_basis_index(swapped)] = -1j * math.sin(float(beta))
    else:
        state[source] = 1.0
    return state


def validate_c2xy_lowering() -> dict[str, Any]:
    """Exhaustively validate all 16 clean logical basis inputs at six angles."""

    rows: list[dict[str, Any]] = []
    maximum_error = 0.0
    maximum_scratch_probability = 0.0
    for beta in VALIDATION_BETAS:
        beta_error = 0.0
        beta_scratch = 0.0
        for a in (0, 1):
            for b in (0, 1):
                for i in (0, 1):
                    for j in (0, 1):
                        initial = [0j] * (1 << len(SCHEDULE_QUBITS))
                        initial[_basis_index((a, b, i, j, 0, 0))] = 1.0
                        actual = simulate_elementary_schedule(initial, beta)
                        ideal = ideal_guarded_xy_state(a, b, i, j, beta)
                        error = max(abs(left - right) for left, right in zip(actual, ideal))
                        dirty_probability = float(
                            sum(
                                abs(amplitude) ** 2
                                for index, amplitude in enumerate(actual)
                                if ((index >> 4) & 1) or ((index >> 5) & 1)
                            )
                        )
                        beta_error = max(beta_error, error)
                        beta_scratch = max(beta_scratch, dirty_probability)
        maximum_error = max(maximum_error, beta_error)
        maximum_scratch_probability = max(maximum_scratch_probability, beta_scratch)
        rows.append(
            {
                "beta": float(beta),
                "basis_cases": 16,
                "maximum_amplitude_error": beta_error,
                "maximum_dirty_scratch_probability": beta_scratch,
            }
        )
    checks = {
        "all_16_clean_basis_inputs_per_angle": all(row["basis_cases"] == 16 for row in rows),
        "ideal_c2xy_matrix_match": maximum_error <= 1e-12,
        "scratch_returned_to_zero": maximum_scratch_probability <= 1e-24,
        "schedule_hash_reproducible": elementary_schedule_sha256() == elementary_schedule_sha256(),
    }
    return {
        "angles": rows,
        "checks": checks,
        "maximum_amplitude_error": maximum_error,
        "maximum_dirty_scratch_probability": maximum_scratch_probability,
        "passed": all(checks.values()),
        "schedule_sha256": elementary_schedule_sha256(),
        "total_basis_angle_cases": 16 * len(rows),
    }


def optimized_native_resource_ledger(
    circuits: Sequence[OptimizedCircuitIR],
    *,
    topology: str,
    profile: str = PROFILE_DUAL_GUARD,
    analyses: Mapping[int, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Combine exact optimized-oracle and elementary mixer accounting."""

    if topology not in SUPPORTED_TOPOLOGIES:
        raise ValueError(f"Unsupported topology: {topology}")
    if profile != PROFILE_DUAL_GUARD:
        raise ValueError("V3.4 native lowering is sealed only for DUAL_GUARD_CACHED.")
    if not circuits:
        raise ValueError("At least one optimized circuit is required.")
    edges = edge_schedule(circuits[0].n, topology)
    edge_count = len(edges)
    oracle_calls = 2 * edge_count + 2
    per_edge = elementary_resource_per_edge()
    edge_abstract = per_edge["abstract_elementary"]
    edge_ft = per_edge["ccx_7t_cost_model"]
    per_seed: list[dict[str, Any]] = []
    for circuit in sorted(circuits, key=lambda item: item.seed):
        oracle = (
            dict(analyses[circuit.seed])
            if analyses is not None and circuit.seed in analyses
            else analyze_optimized_circuit(circuit)
        )
        levels = oracle["levels"]
        abstract = levels["GATE_LEVEL_ABSTRACT"]
        fault_tolerant = levels["FAULT_TOLERANT_ESTIMATE"]
        row = {
            "seed": circuit.seed,
            "instance_id": circuit.instance_id,
            "optimized_oracle_gate_ir_sha256": oracle["gate_ir_sha256"],
            "logical_qubits_sequential_reuse": circuit.logical_qubits + 1,
            "oracle_calls": oracle_calls,
            "controlled_xy_edges": edge_count,
            "provider_neutral_gate_count": (
                oracle_calls * int(abstract["gate_count"])
                + edge_count * int(edge_abstract["gate_count"])
            ),
            "serial_depth_upper_bound": (
                oracle_calls * int(abstract["abstract_depth"])
                + edge_count * int(edge_abstract["serial_schedule_depth"])
            ),
            "cnot_after_selected_ccx_model": (
                oracle_calls * int(fault_tolerant["decomposed_cnot"])
                + edge_count * int(edge_ft["CX"])
            ),
            "t_count_oracle_and_ccx_subtotal": (
                oracle_calls * int(fault_tolerant["t_count"])
                + edge_count * int(edge_ft["T_OR_T_DAGGER"])
            ),
            "continuous_ry_rotations": edge_count * int(edge_ft["RY_CONTINUOUS"]),
            "rotation_synthesis_cost": "NOT_ESTIMATED",
            "backend_transpilation": "NOT_RUN",
        }
        row["resource_row_sha256"] = canonical_json_sha256(row)
        per_seed.append(row)
    maxima_fields = (
        "logical_qubits_sequential_reuse",
        "provider_neutral_gate_count",
        "serial_depth_upper_bound",
        "cnot_after_selected_ccx_model",
        "t_count_oracle_and_ccx_subtotal",
        "continuous_ry_rotations",
    )
    return {
        "backend_transpilation_status": "NOT_RUN",
        "edge_count": edge_count,
        "edge_schedule_sha256": canonical_json_sha256(edges),
        "elementary_schedule_sha256": elementary_schedule_sha256(),
        "lowering_version": NATIVE_LOWERING_VERSION,
        "maxima": {
            field: max(int(row[field]) for row in per_seed) for field in maxima_fields
        },
        "oracle_calls": oracle_calls,
        "per_edge": per_edge,
        "per_seed": per_seed,
        "profile": profile,
        "resource_boundary": (
            "Exact provider-neutral lowering and selected 7T-CCX accounting. "
            "Arbitrary-rotation synthesis, topology routing, named-backend "
            "transpilation, calibration, noise and runtime are NOT_ESTIMATED/NOT_RUN."
        ),
        "topology": topology,
    }


__all__ = [
    "NATIVE_LOWERING_VERSION",
    "SCHEDULE_QUBITS",
    "VALIDATION_BETAS",
    "elementary_c2xy_schedule",
    "elementary_resource_per_edge",
    "elementary_schedule_sha256",
    "ideal_guarded_xy_state",
    "native_mixer_source_sha256",
    "optimized_native_resource_ledger",
    "simulate_elementary_schedule",
    "validate_c2xy_lowering",
]
