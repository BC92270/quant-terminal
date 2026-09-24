"""Pure admission-envelope calculations for V4.9.

This module does not compile or execute a quantum circuit. It converts sealed
V4.8 resource counts into the preregistered V4.9 necessary-condition ledger.
"""

from __future__ import annotations

from typing import Any, Mapping


def build_seed_admission_row(
    seed_evaluation: Mapping[str, Any],
    *,
    error_ceiling_exclusive: int,
    duration_ceiling_exclusive: int,
    maximum_healthy_qubits: int,
) -> dict[str, Any]:
    """Return one deterministic, fail-closed seed admission row."""

    comparison = seed_evaluation.get("comparison")
    lower_bound = seed_evaluation.get("architecture_lower_bound_v47_comparable")
    routing = seed_evaluation.get("structural_routing")
    if not isinstance(comparison, Mapping) or not isinstance(lower_bound, Mapping):
        raise ValueError("V4.8 seed evaluation lacks comparison or lower-bound evidence")
    if not isinstance(routing, Mapping):
        raise ValueError("V4.8 seed evaluation lacks structural routing evidence")

    seed = int(seed_evaluation["seed"])
    direct_cx = int(comparison["candidate_cx"])
    logical_qubits = int(seed_evaluation["logical_qubits"])
    error_pass = direct_cx < int(error_ceiling_exclusive)
    duration_pass = direct_cx < int(duration_ceiling_exclusive)
    capacity_pass = logical_qubits <= int(maximum_healthy_qubits)
    route_pass = str(routing.get("status", "")).startswith("PASS")
    admitted = error_pass and duration_pass and capacity_pass and route_pass

    return {
        "seed": seed,
        "instance_id": seed_evaluation.get("instance_id"),
        "logical_qubits": logical_qubits,
        "direct_cx": direct_cx,
        "routed_cz": int(comparison["candidate_basic_swap_cz"]),
        "strict_error_ceiling_exclusive": int(error_ceiling_exclusive),
        "strict_duration_ceiling_exclusive": int(duration_ceiling_exclusive),
        "cx_reduction_required_to_admissible_maximum": max(
            0, direct_cx - (int(error_ceiling_exclusive) - 1)
        ),
        "capacity_pass": capacity_pass,
        "route_replay_pass": route_pass,
        "error_screen_pass": error_pass,
        "duration_screen_pass": duration_pass,
        "seed_admission_pass": admitted,
        "status": "PASS" if admitted else "FAIL",
    }


__all__ = ["build_seed_admission_row"]
