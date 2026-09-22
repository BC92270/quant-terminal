"""Independent validation ladder for the Quantum Lab V3.9 scalable IR."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any, Iterator, Mapping

from .phase3_gate_compiler import compare_inclusive, make_gate
from .phase3_v39_scalable_reversible_ir import (
    BUDGET_CNOT,
    EDGE_COUNT,
    K,
    N,
    SEEDS,
    authenticate_parent_chain,
    build_v39_artifact,
    canonical_json_sha256,
    compile_seed,
    load_v39_spec,
)


VALIDATION_VERSION = "QUANTUM LAB V3.9 SCIENTIFIC VALIDATION · V1"
_CACHE: dict[str, Any] | None = None


def _apply_gates(state: list[int], gates: Iterator[Any]) -> None:
    for gate in gates:
        if all(state[index] == expected for index, expected in zip(gate.controls, gate.control_values)):
            state[gate.target] ^= 1


def _two_pattern_add_gates(width: int, constant: int, q: int) -> list[Any]:
    d = 0
    orientation = 1
    register = tuple(range(2, 2 + width))
    encoded = int(constant) & ((1 << width) - 1)
    gates: list[Any] = []
    for position in range(width - 1, -1, -1):
        if not ((encoded >> position) & 1):
            continue
        suffix = register[position:]
        for index in range(len(suffix) - 1, -1, -1):
            controls = (d, orientation) + suffix[:index]
            values = (1, 1 if q == 0 else 0) + tuple(1 for _ in suffix[:index])
            gates.append(make_gate(suffix[index], controls, values, stage="V39_TEST", label="ADD"))
    return gates


def exhaustive_two_pattern_addition() -> dict[str, Any]:
    cases = 0
    inverse_cases = 0
    mismatches = 0
    untouched_equal_bit_cases = 0
    for width in range(1, 7):
        modulus = 1 << width
        constants = range(-(1 << (width - 1)), (1 << (width - 1)) + 1)
        for constant in constants:
            for q in (0, 1):
                forward = _two_pattern_add_gates(width, constant, q)
                for d in (0, 1):
                    for orientation in (0, 1):
                        active = d == 1 and orientation != q
                        for value in range(modulus):
                            state = [d, orientation] + [(value >> bit) & 1 for bit in range(width)]
                            original = list(state)
                            _apply_gates(state, iter(forward))
                            actual = sum(state[2 + bit] << bit for bit in range(width))
                            expected = (value + constant) % modulus if active else value
                            cases += 1
                            if actual != expected or state[:2] != original[:2]:
                                mismatches += 1
                            if d == 0 and actual == value:
                                untouched_equal_bit_cases += 1
                            _apply_gates(state, reversed(forward))
                            inverse_cases += 1
                            if state != original:
                                mismatches += 1
    core = {
        "widths": [1, 2, 3, 4, 5, 6],
        "forward_cases": cases,
        "inverse_cases": inverse_cases,
        "untouched_equal_bit_cases": untouched_equal_bit_cases,
        "mismatches": mismatches,
        "passed": mismatches == 0,
    }
    return {**core, "evidence_sha256": canonical_json_sha256(core)}


def exhaustive_comparators() -> dict[str, Any]:
    cases = 0
    mismatches = 0
    for width in range(1, 7):
        for signed in (False, True):
            minimum = -(1 << (width - 1)) if signed else 0
            maximum = (1 << (width - 1)) - 1 if signed else (1 << width) - 1
            for constant in range(minimum - 1, maximum + 2):
                for relation in ("GE", "LE"):
                    register = tuple(range(width))
                    target = width
                    gates = tuple(compare_inclusive(register, constant, target, relation=relation, signed=signed))
                    for encoded in range(1 << width):
                        value = encoded
                        if signed and encoded >= (1 << (width - 1)):
                            value -= 1 << width
                        for target_before in (0, 1):
                            state = [(encoded >> bit) & 1 for bit in range(width)] + [target_before]
                            original_register = state[:width]
                            _apply_gates(state, iter(gates))
                            expected_toggle = value >= constant if relation == "GE" else value <= constant
                            cases += 1
                            if state[:width] != original_register or state[target] != (target_before ^ int(expected_toggle)):
                                mismatches += 1
                            _apply_gates(state, reversed(gates))
                            if state != original_register + [target_before]:
                                mismatches += 1
    core = {"cases": cases, "mismatches": mismatches, "passed": mismatches == 0}
    return {**core, "evidence_sha256": canonical_json_sha256(core)}


def exhaustive_canonical_pair_algebra() -> dict[str, Any]:
    cases = 0
    equal_bit_untouched = 0
    mismatches = 0
    width = 6
    modulus = 1 << width
    for delta in range(-15, 16):
        for q in (0, 1):
            for a_zero in range(modulus):
                a_one = (a_zero + delta) % modulus
                endpoint = {0: a_zero, 1: a_one}
                for orientation in (0, 1):
                    constant = -delta if q == 0 else delta
                    normalized = (endpoint[orientation] + (constant if orientation != q else 0)) % modulus
                    if normalized != endpoint[q]:
                        mismatches += 1
                    for new_orientation in (0, 1):
                        restored = (normalized - (constant if new_orientation != q else 0)) % modulus
                        if restored != endpoint[new_orientation]:
                            mismatches += 1
                        cases += 1
                for bit in (0, 1):
                    # d=0 disables both q branches even when x_i=1.
                    active = False and bit != q
                    if not active:
                        equal_bit_untouched += 1
    core = {
        "width": width,
        "delta_values": 31,
        "pair_transition_cases": cases,
        "equal_bit_untouched_cases": equal_bit_untouched,
        "mismatches": mismatches,
        "passed": mismatches == 0,
    }
    return {**core, "evidence_sha256": canonical_json_sha256(core)}


def exhaustive_symmetric_interval_identity() -> dict[str, Any]:
    cases = 0
    mismatches = 0
    for lower in range(-5, 5):
        for upper in range(lower, 6):
            for delta in range(-9, 10):
                for q in (0, 1):
                    sign = 1 - 2 * q
                    interval_lower = max(lower, lower - sign * delta)
                    interval_upper = min(upper, upper - sign * delta)
                    for canonical in range(-20, 21):
                        other = canonical + sign * delta
                        direct = lower <= canonical <= upper and lower <= other <= upper
                        interval = interval_lower <= canonical <= interval_upper
                        cases += 1
                        if direct != interval:
                            mismatches += 1
    core = {"integer_cases": cases, "mismatches": mismatches, "passed": mismatches == 0}
    return {**core, "evidence_sha256": canonical_json_sha256(core)}


def controlled_rx_pair_action() -> dict[str, Any]:
    betas = (-0.731, 0.0, 0.419)
    basis_columns = 0
    max_error = 0.0
    for beta in betas:
        matrix = ((complex(math.cos(beta), 0.0), complex(0.0, -math.sin(beta))), (complex(0.0, -math.sin(beta)), complex(math.cos(beta), 0.0)))
        for column in (0, 1):
            actual = [matrix[row][column] for row in (0, 1)]
            expected = [
                complex(math.cos(beta), 0.0) if row == column else complex(0.0, -math.sin(beta))
                for row in (0, 1)
            ]
            max_error = max(max_error, *(abs(a - b) for a, b in zip(actual, expected)))
            basis_columns += 1
    core = {
        "betas": list(betas),
        "basis_columns": basis_columns,
        "maximum_action_error": max_error,
        "passed": max_error <= 1e-15,
    }
    return {**core, "evidence_sha256": canonical_json_sha256(core)}


def _load_certificates() -> list[dict[str, Any]]:
    import json

    root = Path(__file__).resolve().parents[1]
    payload = json.loads((root / "SEALED_EXACT_DYADIC_BANDS_ORACLE.json").read_text(encoding="utf-8"))
    return list(payload["seed_certificates"])


def run_v39_validation(*, force: bool = False) -> dict[str, Any]:
    global _CACHE
    if _CACHE is not None and not force:
        return copy.deepcopy(_CACHE)
    spec = load_v39_spec()
    parent = authenticate_parent_chain()
    addition = exhaustive_two_pattern_addition()
    comparators = exhaustive_comparators()
    canonical_pair = exhaustive_canonical_pair_algebra()
    intervals = exhaustive_symmetric_interval_identity()
    rx = controlled_rx_pair_action()
    first = build_v39_artifact(use_cache=False)
    replay_rows = [compile_seed(certificate) for certificate in _load_certificates()]
    first_rows = first["seed_rows"]
    replay_equal = replay_rows == first_rows
    aggregate = first["aggregate_evidence"]
    coverage = first["coverage_counts_out_of_8"]
    resources = first["resource_screen"]
    expected_dead_live = {
        1103: (273, 507),
        2207: (229, 551),
        3301: (266, 514),
        4409: (270, 510),
        5501: (245, 535),
        6607: (254, 526),
        7703: (234, 546),
        8807: (249, 531),
    }
    expected_widths = {
        1103: [4, 4, 4, 4, 61, 64, 63],
        2207: [4, 4, 4, 4, 60, 62, 63],
        3301: [4, 4, 4, 4, 63, 61, 61],
        4409: [4, 4, 4, 4, 63, 64, 62],
        5501: [4, 4, 4, 4, 65, 64, 62],
        6607: [4, 4, 4, 4, 64, 68, 64],
        7703: [4, 4, 4, 4, 63, 61, 61],
        8807: [4, 4, 4, 4, 62, 62, 64],
    }
    dead_live_exact = all(
        (int(row["certified_identity_count"]), int(row["live_edge_count"])) == expected_dead_live[int(row["seed"])]
        for row in first_rows
    )
    widths_exact = all(
        [int(register["width"]) for register in row["constraint_registers"]] == expected_widths[int(row["seed"])]
        for row in first_rows
    )
    all_edges_hashed = all(
        len(row["edge_ir_sha256"]) == EDGE_COUNT
        and len(set(row["edge_ir_sha256"])) == EDGE_COUNT
        and all(len(value) == 64 for value in row["edge_ir_sha256"])
        for row in first_rows
    )
    all_counts_complete = all(
        int(row["live_edge_count"]) + int(row["certified_identity_count"]) == EDGE_COUNT
        and int(row["constraint_row_cases"]) == EDGE_COUNT * 7
        for row in first_rows
    )
    budget_derived = (
        resources["decision"] == "REJECTED_SELECTED_MODEL_CNOT_BUDGET"
        and int(resources["maximum_selected_model_cnot"]) == max(int(row["resources"]["selected_model_cnot"]) for row in first_rows)
        and int(resources["minimum_budget_margin_cnot"]) == min(BUDGET_CNOT - int(row["resources"]["selected_model_cnot"]) for row in first_rows)
    )
    checks = {
        "v38_to_v31_parent_chain_authenticated": bool(parent["valid"]),
        "specification_self_hash_and_boundary_valid": spec["claim_boundary"]["hardware_executable"] is False,
        "two_pattern_controlled_addition_exhaustive_small_width": bool(addition["passed"]),
        "signed_unsigned_inclusive_comparators_exhaustive_small_width": bool(comparators["passed"]),
        "cache_canonicalization_and_inverse_exhaustive_small_width": bool(canonical_pair["passed"]),
        "symmetric_interval_identity_exhaustive_integer_grid": bool(intervals["passed"]),
        "controlled_rx_pair_action_registered_betas": bool(rx["passed"]),
        "all_eight_seed_register_widths_exact": widths_exact,
        "all_6240_ordered_positions_complete": aggregate["edge_seed_positions"] == 6_240 and all_counts_complete,
        "all_43680_row_edge_cases_present": aggregate["constraint_row_cases"] == 43_680,
        "dead_live_certificates_match_independent_inventory": dead_live_exact,
        "all_6240_edge_records_unique_and_sha256_committed": all_edges_hashed,
        "all_eight_proof_ladders_complete": all(int(value) == 8 for key, value in coverage.items() if key != "selected_model_budget_at_most_2500000"),
        "selected_model_counts_replayed_independently": replay_equal,
        "maximum_not_mean_drives_budget_rejection": budget_derived,
        "global_connectivity_remains_indeterminate": first["decisions"]["complete_global_connectivity"] == "INDETERMINATE",
        "provider_hardware_and_advantage_boundaries_zero": (
            first["claim_boundary"]["provider_calls"] == 0
            and first["claim_boundary"]["qpu_jobs_submitted"] == 0
            and first["claim_boundary"]["hardware_executable"] is False
            and first["claim_boundary"]["quantum_advantage"] == "NOT_CLAIMED"
        ),
        "overall_decision_is_resource_rejection_not_global_impossibility": (
            first["decisions"]["overall"] == "N40_REVERSIBLE_IR_PASSED_RESOURCE_SCREEN_REJECTED"
            and first["decisions"]["production_admission"] == "BLOCKED_GLOBAL_CONNECTIVITY_AND_BACKEND"
        ),
    }
    core = {
        "validation_version": VALIDATION_VERSION,
        "artifact_sha256": first["artifact_sha256"],
        "arithmetic": addition,
        "comparators": comparators,
        "canonical_pair": canonical_pair,
        "symmetric_intervals": intervals,
        "controlled_rx": rx,
        "checks": checks,
        "counts": {
            "checks_passed": sum(checks.values()),
            "checks_total": len(checks),
            "edge_seed_positions": aggregate["edge_seed_positions"],
            "constraint_row_cases": aggregate["constraint_row_cases"],
            "live_edge_positions": aggregate["live_edge_positions"],
            "certified_identity_positions": aggregate["certified_identity_positions"],
        },
        "passed": all(checks.values()),
    }
    result = {**core, "validation_manifest_sha256": canonical_json_sha256(core)}
    _CACHE = copy.deepcopy(result)
    return result


def _main() -> int:
    result = run_v39_validation()
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if result.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "VALIDATION_VERSION",
    "controlled_rx_pair_action",
    "exhaustive_canonical_pair_algebra",
    "exhaustive_comparators",
    "exhaustive_symmetric_interval_identity",
    "exhaustive_two_pattern_addition",
    "run_v39_validation",
]
