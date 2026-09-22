"""Validation ladder and immutable artifact seal for Quantum Lab V3.4.

V3.4 is additive.  It authenticates the complete V3.3 freeze before testing an
exact interval-flag optimization and an elementary clean-scratch lowering of
the doubly-guarded XY primitive.  The seal remains RESEARCH_ONLY and fails
closed on backend execution, routing, calibration and quantum advantage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .phase3_algorithmic_contract import (
    PROFILE_DUAL_GUARD,
    TOPOLOGY_COMPLETE,
    TOPOLOGY_RING,
    algorithm_source_sha256,
    edge_schedule,
    load_algorithm_spec,
    raw_file_sha256,
    swap_bits,
)
from .phase3_circuit_validation import load_compiler_artifact
from .phase3_gate_compiler import (
    DOMAIN_EXACT_K,
    CircuitIR,
    Gate,
    canonical_json_sha256,
    classical_predicate,
    compile_seed_circuit,
)
from .phase3_native_mixer import (
    NATIVE_LOWERING_VERSION,
    elementary_c2xy_schedule,
    elementary_resource_per_edge,
    elementary_schedule_sha256,
    native_mixer_source_sha256,
    optimized_native_resource_ledger,
    validate_c2xy_lowering,
)
from .phase3_optimized_oracle import (
    OPTIMIZER_VERSION,
    OptimizedCircuitIR,
    analyze_optimized_circuit,
    compile_optimized_seed,
    load_v34_spec,
    optimized_classical_predicate,
    optimized_interval_flag,
    optimizer_source_sha256,
)
from .verify_phase3_v32 import verify_release_chain as verify_v32_release_chain


VALIDATION_VERSION = "PHASE III · V3.4 OPTIMIZED NATIVE VALIDATION LADDER · V1"
ARTIFACT_VERSION = "PHASE III · SEALED OPTIMIZED ORACLE + ELEMENTARY MIXER · V1"
DEFAULT_SEAL_NAME = "SEALED_OPTIMIZED_NATIVE_MIXER_ARTIFACT.json"
ProgressCallback = Callable[[str], None]


def validation_source_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def verifier_source_sha256() -> str:
    path = Path(__file__).with_name("verify_phase3_v34.py")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _notify(callback: ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def _gate_masks(gate: Gate) -> tuple[int, int, int]:
    control_mask = 0
    expected_mask = 0
    for control, value in zip(gate.controls, gate.control_values):
        bit = 1 << int(control)
        control_mask |= bit
        if int(value):
            expected_mask |= bit
    return control_mask, expected_mask, 1 << int(gate.target)


def _simulate_gate_sequence(
    gates: Iterable[Gate], initial_state: int
) -> int:
    state = int(initial_state)
    for gate in gates:
        control_mask, expected_mask, target_mask = _gate_masks(gate)
        if state & control_mask == expected_mask:
            state ^= target_mask
    return state


def run_interval_identity_validation() -> dict[str, Any]:
    """Exhaust every signed/unsigned interval and value through width six."""

    rows: list[dict[str, Any]] = []
    total_cases = 0
    first_failure: dict[str, Any] | None = None
    for signed in (False, True):
        for width in range(1, 7):
            minimum = -(1 << (width - 1)) if signed else 0
            maximum = (1 << (width - 1)) - 1 if signed else (1 << width) - 1
            values = range(minimum, maximum + 1)
            width_cases = 0
            width_pass = True
            for lower in values:
                for upper in range(lower, maximum + 1):
                    gates = tuple(
                        optimized_interval_flag(
                            tuple(range(width)),
                            lower,
                            upper,
                            width,
                            signed=signed,
                        )
                    )
                    for value in values:
                        encoded = int(value) & ((1 << width) - 1)
                        expected_toggle = int(lower <= value <= upper)
                        for target_before in (0, 1):
                            initial = encoded | (target_before << width)
                            final = _simulate_gate_sequence(gates, initial)
                            actual_toggle = ((final >> width) & 1) ^ target_before
                            data_preserved = final & ((1 << width) - 1) == encoded
                            passed = actual_toggle == expected_toggle and data_preserved
                            width_cases += 1
                            total_cases += 1
                            width_pass = width_pass and passed
                            if not passed and first_failure is None:
                                first_failure = {
                                    "actual_toggle": actual_toggle,
                                    "data_preserved": data_preserved,
                                    "expected_toggle": expected_toggle,
                                    "lower": lower,
                                    "signed": signed,
                                    "target_before": target_before,
                                    "upper": upper,
                                    "value": value,
                                    "width": width,
                                }
            rows.append(
                {
                    "case_count": width_cases,
                    "passed": width_pass,
                    "signed": signed,
                    "value_count": maximum - minimum + 1,
                    "width": width,
                }
            )
    checks = {
        "all_signed_and_unsigned_widths_covered": len(rows) == 12,
        "all_interval_truth_tables_exact": all(row["passed"] for row in rows),
        "input_register_always_preserved": first_failure is None,
    }
    return {
        "checks": checks,
        "first_failure": first_failure,
        "passed": all(checks.values()),
        "rows": rows,
        "total_basis_cases": total_cases,
    }


def _interval_value_from_bits(bits: int, width: int, signed: bool) -> int:
    encoded = bits & ((1 << width) - 1)
    if signed and encoded & (1 << (width - 1)):
        return encoded - (1 << width)
    return encoded


def run_actual_constraint_boundary_validation(
    circuits: Sequence[OptimizedCircuitIR],
) -> dict[str, Any]:
    """Exercise every N=40 frozen bound and its immediate neighbours."""

    rows: list[dict[str, Any]] = []
    cases = 0
    for circuit in sorted(circuits, key=lambda item: item.seed):
        for constraint in circuit.constraints:
            width = constraint.width
            minimum = -(1 << (width - 1)) if constraint.signed else 0
            maximum = (
                (1 << (width - 1)) - 1
                if constraint.signed
                else (1 << width) - 1
            )
            candidates = {
                minimum,
                maximum,
                0,
                constraint.lower - 1,
                constraint.lower,
                constraint.lower + 1,
                constraint.upper - 1,
                constraint.upper,
                constraint.upper + 1,
            }
            values = sorted(value for value in candidates if minimum <= value <= maximum)
            gates = tuple(
                optimized_interval_flag(
                    tuple(range(width)),
                    constraint.lower,
                    constraint.upper,
                    width,
                    signed=constraint.signed,
                )
            )
            passed = True
            for value in values:
                encoded = int(value) & ((1 << width) - 1)
                for target_before in (0, 1):
                    initial = encoded | (target_before << width)
                    final = _simulate_gate_sequence(gates, initial)
                    actual_value = _interval_value_from_bits(final, width, constraint.signed)
                    actual_toggle = ((final >> width) & 1) ^ target_before
                    expected_toggle = int(constraint.lower <= value <= constraint.upper)
                    passed = passed and actual_value == value and actual_toggle == expected_toggle
                    cases += 1
            rows.append(
                {
                    "case_count": 2 * len(values),
                    "constraint": constraint.name,
                    "lower": constraint.lower,
                    "passed": passed,
                    "seed": circuit.seed,
                    "signed": constraint.signed,
                    "upper": constraint.upper,
                    "width": width,
                }
            )
    return {
        "constraint_count": len(rows),
        "passed": bool(rows) and all(row["passed"] for row in rows),
        "rows": rows,
        "total_boundary_cases": cases,
    }


def _basis_to_int(bits: Sequence[int], data_start: int = 0) -> int:
    return sum(int(value) << (data_start + index) for index, value in enumerate(bits))


def _legacy_exact_k_entries(v32: Mapping[str, Any]) -> dict[int, Mapping[str, Any]]:
    entries = {
        int(row["seed"]): row
        for row in v32.get("validation", {}).get("compilation_entries", [])
        if row.get("domain_mode") == DOMAIN_EXACT_K
    }
    if len(entries) != 8:
        raise ValueError("Frozen V3.2 artifact must expose eight exact-K entries.")
    return entries


def _constraint_payloads(circuit: CircuitIR | OptimizedCircuitIR) -> list[dict[str, Any]]:
    return [constraint.as_dict() for constraint in circuit.constraints]


def run_n40_optimized_oracle_validation(
    v31: Mapping[str, Any],
    v32: Mapping[str, Any],
    v33: Mapping[str, Any],
    spec: Mapping[str, Any],
    *,
    progress: ProgressCallback | None = None,
) -> tuple[dict[str, Any], list[OptimizedCircuitIR], dict[int, dict[str, Any]]]:
    """Compile all seeds, audit all witness swaps, and simulate selected gates."""

    parent = spec["parent_contract"]
    witness_bits = spec["authenticated_v33_witnesses"]["bits_by_seed"]
    certificates = {
        int(certificate["seed"]): certificate
        for certificate in v31["seed_certificates"]
    }
    legacy_entries = _legacy_exact_k_entries(v32)
    v33_witness_rows = {
        int(row["seed"]): row
        for row in v33["validation"]["n40_witness_graph"]["rows"]
    }
    circuits: list[OptimizedCircuitIR] = []
    analyses: dict[int, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    total_nontrivial_swaps = 0
    total_gate_cases = 0

    for seed in sorted(certificates):
        _notify(progress, f"D · optimized oracle seed {seed} · compile/resources")
        certificate = certificates[seed]
        legacy = compile_seed_circuit(
            certificate,
            DOMAIN_EXACT_K,
            parent_dyadic_oracle_sha=str(v31["dyadic_oracle_sha"]),
            parent_artifact_file_sha256=parent["expected_parent_v31_raw_file_sha256"],
        )
        optimized = compile_optimized_seed(
            certificate,
            DOMAIN_EXACT_K,
            parent_v31_raw_file_sha256=parent["expected_parent_v31_raw_file_sha256"],
            parent_v32_artifact_sha256=parent["expected_parent_v32_artifact_sha256"],
            parent_v33_artifact_sha256=parent["expected_parent_v33_artifact_sha256"],
            parent_v33_freeze_sha256=parent["expected_parent_v33_freeze_sha256"],
            spec=spec,
        )
        witness = tuple(int(value) for value in witness_bits[str(seed)])
        if len(witness) != 40 or sum(witness) != 10:
            raise ValueError(f"Invalid preregistered N=40/K=10 witness for seed {seed}.")
        witness_hash = canonical_json_sha256(list(witness))
        legacy_witness = classical_predicate(witness, legacy)
        optimized_witness = optimized_classical_predicate(witness, optimized)
        feasible_neighbors: list[tuple[int, ...]] = []
        infeasible_neighbors: list[tuple[int, ...]] = []
        swap_parity = True
        nontrivial = 0
        for edge in edge_schedule(40, TOPOLOGY_COMPLETE):
            if witness[edge[0]] == witness[edge[1]]:
                continue
            nontrivial += 1
            candidate = swap_bits(witness, *edge)
            legacy_value = classical_predicate(candidate, legacy)
            optimized_value = optimized_classical_predicate(candidate, optimized)
            swap_parity = swap_parity and legacy_value == optimized_value
            (feasible_neighbors if legacy_value else infeasible_neighbors).append(candidate)
        total_nontrivial_swaps += nontrivial

        selected = [
            ("AUTHENTICATED_WITNESS", witness),
            ("FEASIBLE_SWAP", feasible_neighbors[0] if feasible_neighbors else witness),
            (
                "INFEASIBLE_SWAP",
                infeasible_neighbors[0] if infeasible_neighbors else witness,
            ),
        ]
        cases = [
            {
                "bits": bits,
                "label": label,
                "predicate": classical_predicate(bits, legacy),
                "target_before": target,
            }
            for label, bits in selected
            for target in (0, 1)
        ]
        target_index = optimized.register("target").bits[0]
        data_register = optimized.register("data")
        initial_states = [
            _basis_to_int(case["bits"], data_register.start)
            | (int(case["target_before"]) << target_index)
            for case in cases
        ]
        _notify(progress, f"D · optimized oracle seed {seed} · hash/resources/gate batch")
        analysis = analyze_optimized_circuit(
            optimized, initial_basis_states=initial_states
        )
        final_states = analysis.pop("simulated_basis_states_after")
        data_mask = ((1 << optimized.n) - 1) << data_register.start
        target_mask = 1 << target_index
        ancilla_mask = ((1 << optimized.logical_qubits) - 1) ^ data_mask ^ target_mask
        batch_rows: list[dict[str, Any]] = []
        for case, initial, final in zip(cases, initial_states, final_states):
            expected_target = int(case["target_before"]) ^ int(case["predicate"])
            batch_row = {
                "ancilla_clean": final & ancilla_mask == 0,
                "data_preserved": final & data_mask == initial & data_mask,
                "label": str(case["label"]),
                "predicate": bool(case["predicate"]),
                "target_after": (final >> target_index) & 1,
                "target_before": int(case["target_before"]),
                "target_correct": ((final >> target_index) & 1) == expected_target,
            }
            batch_row["passed"] = bool(
                batch_row["ancilla_clean"]
                and batch_row["data_preserved"]
                and batch_row["target_correct"]
            )
            batch_rows.append(batch_row)
        batch = {
            "case_count": len(batch_rows),
            "gate_count": analysis["levels"]["GATE_LEVEL_ABSTRACT"]["gate_count"],
            "passed": all(row["passed"] for row in batch_rows),
            "rows": batch_rows,
        }
        recompiled = compile_optimized_seed(
            certificate,
            DOMAIN_EXACT_K,
            parent_v31_raw_file_sha256=parent["expected_parent_v31_raw_file_sha256"],
            parent_v32_artifact_sha256=parent["expected_parent_v32_artifact_sha256"],
            parent_v33_artifact_sha256=parent["expected_parent_v33_artifact_sha256"],
            parent_v33_freeze_sha256=parent["expected_parent_v33_freeze_sha256"],
            spec=spec,
        )
        circuits.append(optimized)
        analyses[seed] = analysis
        total_gate_cases += batch["case_count"]
        legacy_resource = legacy_entries[seed]["resource_ledger"]["levels"]
        optimized_resource = analysis["levels"]
        structural_parity = _constraint_payloads(legacy) == _constraint_payloads(optimized)
        legacy_logical = int(legacy_resource["LOGICAL_IR"]["logical_qubits_total"])
        optimized_logical = int(
            optimized_resource["LOGICAL_IR"]["logical_qubits_total"]
        )
        legacy_comparators = int(legacy_resource["LOGICAL_IR"]["comparator_count"])
        optimized_comparators = int(
            optimized_resource["LOGICAL_IR"]["comparator_network_count"]
        )
        row_checks = {
            "constraint_ir_identical": structural_parity,
            "witness_identity_matches_v33": witness_hash
            == v33_witness_rows[seed]["witness_sha256"],
            "witness_predicate_parity": legacy_witness == optimized_witness is True,
            "all_nontrivial_swap_predicates_match": swap_parity,
            "feasible_and_infeasible_swap_cases_present": bool(
                feasible_neighbors and infeasible_neighbors
            ),
            "compilation_ir_reproduced": recompiled == optimized,
            "gate_hash_is_sha256": len(analysis["gate_ir_sha256"]) == 64,
            "gate_level_target_data_cleanup": batch["passed"],
            "two_logical_qubits_removed": legacy_logical - optimized_logical == 2,
            "comparator_networks_halved": legacy_comparators
            == 2 * optimized_comparators,
            "oracle_gate_count_strictly_lower": int(
                optimized_resource["GATE_LEVEL_ABSTRACT"]["gate_count"]
            )
            < int(legacy_resource["GATE_LEVEL_ABSTRACT"]["gate_count"]),
            "oracle_t_subtotal_strictly_lower": int(
                optimized_resource["FAULT_TOLERANT_ESTIMATE"]["t_count"]
            )
            < int(legacy_resource["FAULT_TOLERANT_ESTIMATE"]["t_count"]),
        }
        rows.append(
            {
                "checks": row_checks,
                "feasible_swap_count": len(feasible_neighbors),
                "gate_level_batch": batch,
                "instance_id": optimized.instance_id,
                "legacy_gate_ir_sha256": legacy_entries[seed]["gate_ir_sha256"],
                "nontrivial_swap_count": nontrivial,
                "optimized_gate_ir_sha256": analysis["gate_ir_sha256"],
                "resource_delta": {
                    "abstract_gate_reduction": int(
                        legacy_resource["GATE_LEVEL_ABSTRACT"]["gate_count"]
                    )
                    - int(optimized_resource["GATE_LEVEL_ABSTRACT"]["gate_count"]),
                    "comparator_network_reduction": legacy_comparators
                    - optimized_comparators,
                    "logical_qubit_reduction": legacy_logical - optimized_logical,
                    "t_count_reduction": int(
                        legacy_resource["FAULT_TOLERANT_ESTIMATE"]["t_count"]
                    )
                    - int(optimized_resource["FAULT_TOLERANT_ESTIMATE"]["t_count"]),
                },
                "seed": seed,
                "witness_sha256": witness_hash,
            }
        )

    checks = {
        "eight_authenticated_seed_circuits": len(rows) == 8,
        "all_seed_checks_pass": all(
            all(bool(value) for value in row["checks"].values()) for row in rows
        ),
        "all_2400_nontrivial_witness_swaps_checked": total_nontrivial_swaps == 2400,
        "forty_eight_gate_level_cases_checked": total_gate_cases == 48,
        "all_gate_hashes_unique": len(
            {row["optimized_gate_ir_sha256"] for row in rows}
        )
        == 8,
    }
    return (
        {
            "checks": checks,
            "passed": all(checks.values()),
            "rows": rows,
            "total_gate_level_cases": total_gate_cases,
            "total_nontrivial_witness_swaps": total_nontrivial_swaps,
        },
        circuits,
        analyses,
    )


def build_resource_envelopes(
    circuits: Sequence[OptimizedCircuitIR],
    analyses: Mapping[int, Mapping[str, Any]],
    v33: Mapping[str, Any],
) -> dict[str, Any]:
    ledgers = {
        f"{PROFILE_DUAL_GUARD}::{topology}": optimized_native_resource_ledger(
            circuits,
            topology=topology,
            profile=PROFILE_DUAL_GUARD,
            analyses=analyses,
        )
        for topology in (TOPOLOGY_RING, TOPOLOGY_COMPLETE)
    }
    canonical_key = f"{PROFILE_DUAL_GUARD}::{TOPOLOGY_COMPLETE}"
    current = ledgers[canonical_key]
    parent = v33["resource_envelopes"]["ledgers"][canonical_key]
    current_rows = {int(row["seed"]): row for row in current["per_seed"]}
    parent_rows = {int(row["seed"]): row for row in parent["per_seed"]}
    comparisons: list[dict[str, Any]] = []
    for seed in sorted(current_rows):
        new = current_rows[seed]
        old = parent_rows[seed]
        comparisons.append(
            {
                "logical_qubit_reduction": int(old["logical_qubits_sequential_reuse"])
                - int(new["logical_qubits_sequential_reuse"]),
                "provider_neutral_gate_reduction_after_12_gate_c2xy_lowering": int(
                    old["provider_neutral_gate_count"]
                )
                - int(new["provider_neutral_gate_count"]),
                "seed": seed,
                "t_subtotal_reduction_after_c2xy_ccx_cost": int(
                    old["oracle_path_t_count_upper_subtotal"]
                )
                - int(new["t_count_oracle_and_ccx_subtotal"]),
            }
        )
    core = {
        "canonical_profile": PROFILE_DUAL_GUARD,
        "canonical_topology": TOPOLOGY_COMPLETE,
        "comparison_vs_v33": comparisons,
        "ledgers": ledgers,
    }
    return {**core, "resource_manifest_sha256": canonical_json_sha256(core)}


def _source_file_sha256(filename: str) -> str:
    return hashlib.sha256(Path(__file__).with_name(filename).read_bytes()).hexdigest()


def _validate_v33_artifact_static(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the frozen V3.3 artifact without importing its NumPy ladder."""

    errors: list[str] = []
    core = {
        key: value
        for key, value in payload.items()
        if key not in {"artifact_sha256", "created_utc"}
    }
    computed = canonical_json_sha256(core)
    if payload.get("artifact_sha256") != computed:
        errors.append("V3.3 artifact SHA-256 mismatch.")
    validation = payload.get("validation") or {}
    validation_core = {
        key: value
        for key, value in validation.items()
        if key not in {"validation_manifest_sha256", "overall_pass"}
    }
    if validation.get("overall_pass") is not True:
        errors.append("V3.3 validation ladder is not passing.")
    if validation.get("validation_manifest_sha256") != canonical_json_sha256(
        validation_core
    ):
        errors.append("V3.3 validation manifest SHA-256 mismatch.")
    resources = payload.get("resource_envelopes") or {}
    ledgers = resources.get("ledgers") or {}
    if resources.get("resource_manifest_sha256") != canonical_json_sha256(ledgers):
        errors.append("V3.3 resource manifest SHA-256 mismatch.")
    boundary = payload.get("claim_boundary") or {}
    if boundary.get("hardware_executable") is not False:
        errors.append("V3.3 hardware boundary violated.")
    if boundary.get("qpu_submission_enabled") is not False:
        errors.append("V3.3 QPU boundary violated.")
    return {
        "artifact_sha256_computed": computed,
        "errors": errors,
        "valid": not errors,
    }


def verify_v33_parent_chain(
    v31_path: str | Path,
    v32_path: str | Path,
    v33_path: str | Path,
) -> dict[str, Any]:
    """Dependency-light reproduction of the frozen V3.3 13-gate verifier."""

    errors: list[str] = []
    try:
        v31_raw = raw_file_sha256(v31_path)
    except OSError as exc:
        v31_raw = None
        errors.append(str(exc))
    try:
        v32_raw = raw_file_sha256(v32_path)
        v32, v32_integrity = load_compiler_artifact(v32_path)
    except Exception as exc:
        v32_raw = None
        v32 = {}
        v32_integrity = {"valid": False, "errors": [str(exc)]}
    try:
        v33_raw = raw_file_sha256(v33_path)
        v33 = json.loads(Path(v33_path).read_text(encoding="utf-8"))
        v33_integrity = _validate_v33_artifact_static(v33)
    except Exception as exc:
        v33_raw = None
        v33 = {}
        v33_integrity = {"valid": False, "errors": [str(exc)]}
    try:
        v32_report = verify_v32_release_chain(v31_path, v32_path)
    except Exception as exc:
        v32_report = {"valid": False, "errors": [str(exc)]}
    try:
        v33_spec = load_algorithm_spec()
    except Exception as exc:
        v33_spec = {}
        errors.append(str(exc))
    algorithm = v33.get("algorithm") or {}
    validation = v33.get("validation") or {}
    parents = v33.get("parents") or {}
    decisions = v33.get("decisions") or {}
    canonical = (v33.get("resource_envelopes", {}).get("ledgers") or {}).get(
        f"{PROFILE_DUAL_GUARD}::{TOPOLOGY_COMPLETE}", {}
    )
    checks = {
        "artifact_internal_integrity": bool(v33_integrity.get("valid")),
        "algorithm_source_hash_live": algorithm.get("algorithm_source_sha256")
        == algorithm_source_sha256(),
        "algorithm_spec_hash_live": algorithm.get("algorithm_spec_sha256")
        == v33_spec.get("algorithm_contract_spec_sha256"),
        "validation_and_verifier_source_hashes_live": bool(
            validation.get("validation_source_sha256")
            == _source_file_sha256("phase3_algorithmic_validation.py")
            and validation.get("verifier_source_sha256")
            == _source_file_sha256("verify_phase3_v33.py")
        ),
        "v31_parent_raw_hash": v31_raw
        == parents.get("v31_raw_file_sha256")
        == "7b39a20ec9200b16996ec25edd660ba7bf26bfb2b454ed44dd1a333513afd50e",
        "v32_parent_release_chain": bool(v32_report.get("valid")),
        "v32_parent_raw_hash": v32_raw
        == parents.get("v32_raw_file_sha256")
        == "616cc12808465916dfcfcde6c8e2c9feed1be4b294ad034f29cb7cb36704031b",
        "v32_parent_semantic_hash": parents.get("v32_artifact_sha256")
        == v32.get("artifact_sha256")
        == "5e6cc7e53f15921f7cbd22ef66f04878b37d54372e04b5bf49f5bb4854050fcd",
        "validation_ladder_pass": bool(
            validation.get("overall_pass") is True
            and len(validation.get("checks") or {}) == 8
            and all((validation.get("checks") or {}).values())
        ),
        "invariance_and_cleanup_pass": bool(
            str(decisions.get("feasibility_invariance", "")).startswith("PASS")
            and decisions.get("guard_ancilla_cleanup") == "PASS"
        ),
        "connectivity_boundary_retained": bool(
            str(decisions.get("ring_topology", "")).startswith("REJECTED")
            and decisions.get("complete_global_connectivity") == "INDETERMINATE"
        ),
        "resource_boundary_retained": bool(
            canonical.get("edge_count") == 780
            and canonical.get("oracle_calls") == 1562
            and canonical.get("controlled_xy_native_cost") == "NOT_ESTIMATED"
            and canonical.get("backend_transpilation_status") == "NOT_RUN"
        ),
        "hardware_fail_closed": bool(
            v33.get("claim_boundary", {}).get("hardware_executable") is False
            and v33.get("claim_boundary", {}).get("qpu_submission_enabled") is False
            and decisions.get("hardware_execution") == "BLOCKED · ZERO JOBS"
            and decisions.get("quantum_advantage") == "NOT_CLAIMED"
        ),
    }
    errors.extend(str(item) for item in v32_integrity.get("errors", []))
    errors.extend(str(item) for item in v33_integrity.get("errors", []))
    errors.extend(str(item) for item in v32_report.get("errors", []))
    failed = [name for name, value in checks.items() if not value]
    return {
        "artifact_raw_file_sha256": v33_raw,
        "checks": checks,
        "errors": list(dict.fromkeys(errors)),
        "failed_checks": failed,
        "valid": bool(all(checks.values()) and not errors),
    }


def verify_v33_freeze_snapshot(
    release_root: str | Path,
    freeze_path: str | Path,
    parent_report: Mapping[str, Any] | None = None,
    *,
    superseded_files: Sequence[str] = (),
) -> dict[str, Any]:
    """Rehash every frozen V3.3 byte and its five release invariants."""

    root = Path(release_root).resolve()
    try:
        payload = json.loads(Path(freeze_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"checks": {"freeze_readable": False}, "errors": [str(exc)], "valid": False}
    core = {key: value for key, value in payload.items() if key != "freeze_contract_sha256"}
    files: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    superseded = {str(item) for item in superseded_files}
    frozen_names = set((payload.get("frozen_files") or {}).keys())
    unexpected_exemptions = sorted(superseded - frozen_names)
    if unexpected_exemptions:
        errors.append(
            "Unknown V3.3 supersession exemptions: " + ", ".join(unexpected_exemptions)
        )
    for relative, expected in sorted((payload.get("frozen_files") or {}).items()):
        try:
            actual = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        except OSError as exc:
            actual = None
            errors.append(f"{relative}: {exc}")
        files[relative] = {
            "actual_sha256": actual,
            "declared_successor": relative in superseded,
            "expected_sha256": expected,
            "valid": actual == expected or relative in superseded,
        }
    release = dict(parent_report or {})
    if not release:
        release = verify_v33_parent_chain(
            root / "SEALED_EXACT_DYADIC_BANDS_ORACLE.json",
            root / "outputs/quantum_phase3/gate_compiler/SEALED_GATE_COMPILER_ARTIFACT.json",
            root
            / "outputs/quantum_phase3/algorithmic_contract/SEALED_FEASIBLE_SUBSPACE_MIXER_ARTIFACT.json",
        )
    boundary = payload.get("claim_boundary") or {}
    checks = {
        "freeze_self_hash": payload.get("freeze_contract_sha256")
        == canonical_json_sha256(core),
        "parent_core_exact_or_declared_successor": bool(files)
        and not unexpected_exemptions
        and all(row["valid"] for row in files.values()),
        "release_chain_13_of_13": bool(
            release.get("valid")
            and len(release.get("checks") or {}) == 13
            and all((release.get("checks") or {}).values())
        ),
        "hardware_boundary_false": bool(
            boundary.get("hardware_executable") is False
            and boundary.get("qpu_submission_enabled") is False
            and boundary.get("qpu_jobs_submitted") == 0
        ),
        "negative_results_retained": bool(
            payload.get("scientific_decisions", {}).get("complete_global_connectivity")
            == "INDETERMINATE"
            and str(payload.get("scientific_decisions", {}).get("ring_topology", ""))
            .startswith("REJECTED")
        ),
    }
    failed = [name for name, value in checks.items() if not value]
    return {
        "checks": checks,
        "errors": errors,
        "failed_checks": failed,
        "file_count": len(files),
        "file_results": files,
        "freeze_contract_sha256_computed": canonical_json_sha256(core),
        "freeze_contract_sha256_stored": payload.get("freeze_contract_sha256"),
        "valid": bool(all(checks.values()) and not errors),
    }


def _load_verified_parents(
    v31_path: str | Path,
    v32_path: str | Path,
    v33_path: str | Path,
    freeze_path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    spec = load_v34_spec()
    parent = spec["parent_contract"]
    release_root = Path(v31_path).resolve().parent
    v33_report = verify_v33_parent_chain(v31_path, v32_path, v33_path)
    freeze_report = verify_v33_freeze_snapshot(
        release_root, freeze_path, parent_report=v33_report
    )
    v31 = json.loads(Path(v31_path).read_text(encoding="utf-8"))
    v32, v32_integrity = load_compiler_artifact(v32_path)
    v33 = json.loads(Path(v33_path).read_text(encoding="utf-8"))
    v33_integrity = _validate_v33_artifact_static(v33)
    errors: list[str] = []
    raw_expectations = (
        (v31_path, parent["expected_parent_v31_raw_file_sha256"], "V3.1"),
        (v32_path, parent["expected_parent_v32_raw_file_sha256"], "V3.2"),
        (v33_path, parent["expected_parent_v33_artifact_raw_file_sha256"], "V3.3"),
    )
    for path, expected, label in raw_expectations:
        if raw_file_sha256(path) != expected:
            errors.append(f"{label} raw file SHA-256 mismatch.")
    if v32.get("artifact_sha256") != parent["expected_parent_v32_artifact_sha256"]:
        errors.append("V3.2 semantic artifact SHA-256 mismatch.")
    if v33.get("artifact_sha256") != parent["expected_parent_v33_artifact_sha256"]:
        errors.append("V3.3 semantic artifact SHA-256 mismatch.")
    if (
        v33.get("validation", {}).get("validation_manifest_sha256")
        != parent["expected_parent_v33_validation_manifest_sha256"]
    ):
        errors.append("V3.3 validation manifest SHA-256 mismatch.")
    if (
        v33.get("resource_envelopes", {}).get("resource_manifest_sha256")
        != parent["expected_parent_v33_resource_manifest_sha256"]
    ):
        errors.append("V3.3 resource manifest SHA-256 mismatch.")
    if freeze_report.get("freeze_contract_sha256_stored") != parent[
        "expected_parent_v33_freeze_sha256"
    ]:
        errors.append("V3.3 freeze semantic SHA-256 mismatch.")
    if not v32_integrity.get("valid"):
        errors.extend(str(item) for item in v32_integrity.get("errors", []))
    if not v33_integrity.get("valid"):
        errors.extend(str(item) for item in v33_integrity.get("errors", []))
    if not freeze_report.get("valid"):
        errors.extend(str(item) for item in freeze_report.get("errors", []))
        errors.extend(
            f"V3.3 freeze check failed: {item}"
            for item in freeze_report.get("failed_checks", [])
        )
    if not v33_report.get("valid"):
        errors.extend(str(item) for item in v33_report.get("errors", []))
        errors.extend(
            f"V3.3 release check failed: {item}"
            for item in v33_report.get("failed_checks", [])
        )
    if errors:
        raise ValueError("Frozen V3.3 parent chain failed: " + "; ".join(dict.fromkeys(errors)))
    return v31, v32, v33, {
        "freeze_report": freeze_report,
        "v31_raw_file_sha256": raw_file_sha256(v31_path),
        "v32_raw_file_sha256": raw_file_sha256(v32_path),
        "v33_raw_file_sha256": raw_file_sha256(v33_path),
        "v33_release_report": v33_report,
    }


def run_validation_ladder(
    v31_path: str | Path,
    v32_path: str | Path,
    v33_path: str | Path,
    freeze_path: str | Path,
    *,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Execute the complete deterministic V3.4 validation ladder."""

    _notify(progress, "A · authenticate complete V3.3 freeze and release chain")
    v31, v32, v33, parent_report = _load_verified_parents(
        v31_path, v32_path, v33_path, freeze_path
    )
    spec = load_v34_spec()
    _notify(progress, "B · exhaustive interval identity widths 1..6")
    interval = run_interval_identity_validation()
    _notify(progress, "C · elementary C2-XY matrix and scratch validation")
    native = validate_c2xy_lowering()
    _notify(progress, "D · N=40 optimized oracle differential validation")
    n40, circuits, analyses = run_n40_optimized_oracle_validation(
        v31, v32, v33, spec, progress=progress
    )
    _notify(progress, "E · actual frozen constraint boundary validation")
    boundaries = run_actual_constraint_boundary_validation(circuits)
    _notify(progress, "F · optimized + elementary resource accounting pass 1/2")
    resources_first = build_resource_envelopes(circuits, analyses, v33)
    _notify(progress, "F · optimized + elementary resource accounting pass 2/2")
    resources_second = build_resource_envelopes(circuits, analyses, v33)
    resource_reproducible = resources_first == resources_second
    comparisons = resources_first["comparison_vs_v33"]
    spec_core = {
        key: value
        for key, value in spec.items()
        if key not in {"v34_spec_sha", "v34_spec_sha256"}
    }
    checks = {
        "A_V33_FREEZE_AND_RELEASE_CHAIN": bool(
            parent_report["freeze_report"].get("valid")
            and parent_report["v33_release_report"].get("valid")
        ),
        "B_SPEC_SELF_HASH": spec["v34_spec_sha256"]
        == canonical_json_sha256(spec_core),
        "C_INTERVAL_IDENTITY_EXHAUSTIVE": interval["passed"],
        "D_N40_OPTIMIZED_ORACLE_EQUIVALENCE": n40["passed"],
        "E_ACTUAL_CONSTRAINT_BOUNDARIES": boundaries["passed"],
        "F_C2XY_ELEMENTARY_MATRIX_AND_CLEANUP": native["passed"],
        "G_RESOURCE_REDUCTION_AND_REPRODUCIBILITY": bool(
            resource_reproducible
            and all(row["logical_qubit_reduction"] == 2 for row in comparisons)
            and all(
                row["provider_neutral_gate_reduction_after_12_gate_c2xy_lowering"]
                > 0
                and row["t_subtotal_reduction_after_c2xy_ccx_cost"] > 0
                for row in comparisons
            )
        ),
        "H_NEGATIVE_CONNECTIVITY_RESULT_RETAINED": bool(
            str(v33["decisions"]["ring_topology"]).startswith("REJECTED")
            and v33["decisions"]["complete_global_connectivity"] == "INDETERMINATE"
        ),
        "I_HARDWARE_AND_ADVANTAGE_FAIL_CLOSED": bool(
            spec["claim_boundary"]["hardware_executable"] is False
            and spec["claim_boundary"]["qpu_submission_enabled"] is False
            and spec["claim_boundary"]["qpu_jobs_submitted"] == 0
            and spec["claim_boundary"]["quantum_advantage"] == "NOT_CLAIMED"
            and all(
                ledger["backend_transpilation_status"] == "NOT_RUN"
                and ledger["per_edge"]["claim_boundary"][
                    "fault_tolerant_rotation_approximation"
                ]
                == "NOT_ESTIMATED"
                for ledger in resources_first["ledgers"].values()
            )
        ),
    }
    validation_core = {
        "actual_constraint_boundaries": boundaries,
        "checks": checks,
        "interval_identity": interval,
        "n40_optimized_oracle": n40,
        "native_c2xy": native,
        "native_mixer_source_sha256": native_mixer_source_sha256(),
        "optimizer_source_sha256": optimizer_source_sha256(),
        "parent_chain": {
            "v31_raw_file_sha256": parent_report["v31_raw_file_sha256"],
            "v32_artifact_sha256": v32["artifact_sha256"],
            "v32_raw_file_sha256": parent_report["v32_raw_file_sha256"],
            "v33_artifact_sha256": v33["artifact_sha256"],
            "v33_freeze_sha256": parent_report["freeze_report"][
                "freeze_contract_sha256_stored"
            ],
            "v33_raw_file_sha256": parent_report["v33_raw_file_sha256"],
            "verified": True,
        },
        "resource_manifest_sha256": resources_first["resource_manifest_sha256"],
        "resource_reproducibility": {
            "first_sha256": canonical_json_sha256(resources_first),
            "passed": resource_reproducible,
            "second_sha256": canonical_json_sha256(resources_second),
        },
        "spec_sha256": spec["v34_spec_sha256"],
        "validation_source_sha256": validation_source_sha256(),
        "validation_version": VALIDATION_VERSION,
        "verifier_source_sha256": verifier_source_sha256(),
    }
    return {
        **validation_core,
        "overall_pass": all(checks.values()),
        "resources": resources_first,
        "validation_manifest_sha256": canonical_json_sha256(validation_core),
    }


def build_optimized_native_artifact(
    v31_path: str | Path,
    v32_path: str | Path,
    v33_path: str | Path,
    freeze_path: str | Path,
    *,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    v31, v32, v33, parent_report = _load_verified_parents(
        v31_path, v32_path, v33_path, freeze_path
    )
    del v31
    spec = load_v34_spec()
    validation = run_validation_ladder(
        v31_path,
        v32_path,
        v33_path,
        freeze_path,
        progress=progress,
    )
    if not validation["overall_pass"]:
        raise ValueError("V3.4 validation ladder did not pass; seal is blocked.")
    resources = validation.pop("resources")
    artifact_core = {
        "artifact_version": ARTIFACT_VERSION,
        "claim_boundary": dict(spec["claim_boundary"]),
        "construction": {
            "cached_dual_guard": True,
            "controlled_xy_elementary_schedule": list(elementary_c2xy_schedule()),
            "controlled_xy_schedule_sha256": elementary_schedule_sha256(),
            "interval_flag_identity": spec["interval_optimization"]["identity"],
            "oracle_calls_per_layer": "2E+2",
            "scratch_reuse": "OPTIMIZED_ORACLE_WORK_REGISTER_AFTER_UNCOMPUTE",
        },
        "decisions": {
            "backend_native_lowering": "NOT_RUN",
            "complete_global_connectivity": "INDETERMINATE",
            "controlled_xy_elementary_synthesis": "PASS · EXACT CONTINUOUS-ROTATION MATRIX",
            "fault_tolerant_rotation_synthesis": "NOT_ESTIMATED",
            "hardware_execution": "BLOCKED · ZERO JOBS",
            "optimization_performance": "NOT_TESTED",
            "optimized_oracle_equivalence": "PASS · RELATIVE TO FROZEN V3.2 PREDICATE",
            "optimized_oracle_resource_reduction": "PASS · ALL EIGHT SEEDS",
            "quantum_advantage": "NOT_CLAIMED",
            "ring_topology": v33["decisions"]["ring_topology"],
        },
        "family": dict(spec["family"]),
        "limitations": [
            "The complete N=40 feasible graph is still not exhaustively enumerated; global connectivity and ergodicity remain indeterminate.",
            "The authenticated ring-topology isolation result is retained and ring-only exploration remains rejected.",
            "The C2-XY schedule is an exact provider-neutral elementary identity, not a named-backend native instruction.",
            "Continuous RY angles are exact symbolically; discrete fault-tolerant approximation error and T cost are not estimated.",
            "No coupling-map routing, calibration snapshot, noise experiment, variational optimization, sampling advantage, runtime advantage or QPU job is present.",
        ],
        "native_lowering": {
            "lowering_version": NATIVE_LOWERING_VERSION,
            "resource_per_edge": elementary_resource_per_edge(),
            "schedule_sha256": elementary_schedule_sha256(),
            "source_sha256": native_mixer_source_sha256(),
            "status": "SEALED PROVIDER-NEUTRAL ELEMENTARY LOWERING",
        },
        "optimizer": {
            "optimizer_version": OPTIMIZER_VERSION,
            "source_sha256": optimizer_source_sha256(),
            "spec_sha": spec["v34_spec_sha"],
            "spec_sha256": spec["v34_spec_sha256"],
            "status": "SEALED EXACT DISJOINT-VIOLATION ORACLE",
        },
        "parents": {
            "v31_raw_file_sha256": parent_report["v31_raw_file_sha256"],
            "v32_artifact_sha256": v32["artifact_sha256"],
            "v32_raw_file_sha256": parent_report["v32_raw_file_sha256"],
            "v33_artifact_sha256": v33["artifact_sha256"],
            "v33_freeze_sha256": parent_report["freeze_report"][
                "freeze_contract_sha256_stored"
            ],
            "v33_raw_file_sha256": parent_report["v33_raw_file_sha256"],
            "v33_resource_manifest_sha256": v33["resource_envelopes"][
                "resource_manifest_sha256"
            ],
            "v33_validation_manifest_sha256": v33["validation"][
                "validation_manifest_sha256"
            ],
        },
        "resource_envelopes": resources,
        "validation": validation,
    }
    return {
        **artifact_core,
        "artifact_sha256": canonical_json_sha256(artifact_core),
        "created_utc": datetime.now(timezone.utc).isoformat(),
    }


def validate_optimized_native_artifact(payload: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["Artifact must be a JSON object."]}
    try:
        core = {
            key: value
            for key, value in payload.items()
            if key not in {"artifact_sha256", "created_utc"}
        }
        computed = canonical_json_sha256(core)
    except (TypeError, ValueError, OverflowError) as exc:
        return {"valid": False, "errors": [str(exc)]}
    if payload.get("artifact_sha256") != computed:
        errors.append("Artifact SHA-256 mismatch.")
    if payload.get("artifact_version") != ARTIFACT_VERSION:
        errors.append("Artifact version mismatch.")
    boundary = payload.get("claim_boundary") or {}
    if boundary.get("hardware_executable") is not False:
        errors.append("Hardware execution boundary violated.")
    if boundary.get("qpu_submission_enabled") is not False:
        errors.append("QPU submission boundary violated.")
    if boundary.get("qpu_jobs_submitted") != 0:
        errors.append("QPU job-count boundary violated.")
    validation = payload.get("validation") or {}
    if validation.get("overall_pass") is not True:
        errors.append("Validation manifest is not passing.")
    else:
        validation_core = {
            key: value
            for key, value in validation.items()
            if key not in {"validation_manifest_sha256", "overall_pass"}
        }
        if validation.get("validation_manifest_sha256") != canonical_json_sha256(
            validation_core
        ):
            errors.append("Validation manifest SHA-256 mismatch.")
    live_hashes = {
        "native_mixer_source_sha256": native_mixer_source_sha256(),
        "optimizer_source_sha256": optimizer_source_sha256(),
        "validation_source_sha256": validation_source_sha256(),
        "verifier_source_sha256": verifier_source_sha256(),
    }
    for key, expected in live_hashes.items():
        if validation.get(key) != expected:
            errors.append(f"Live source SHA-256 mismatch: {key}.")
    resources = payload.get("resource_envelopes") or {}
    resource_core = {
        key: value for key, value in resources.items() if key != "resource_manifest_sha256"
    }
    if resources.get("resource_manifest_sha256") != canonical_json_sha256(resource_core):
        errors.append("Resource manifest SHA-256 mismatch.")
    spec = load_v34_spec()
    parent = spec["parent_contract"]
    parents = payload.get("parents") or {}
    expected_parent_fields = {
        "v31_raw_file_sha256": parent["expected_parent_v31_raw_file_sha256"],
        "v32_artifact_sha256": parent["expected_parent_v32_artifact_sha256"],
        "v32_raw_file_sha256": parent["expected_parent_v32_raw_file_sha256"],
        "v33_artifact_sha256": parent["expected_parent_v33_artifact_sha256"],
        "v33_freeze_sha256": parent["expected_parent_v33_freeze_sha256"],
        "v33_raw_file_sha256": parent[
            "expected_parent_v33_artifact_raw_file_sha256"
        ],
    }
    for key, expected in expected_parent_fields.items():
        if parents.get(key) != expected:
            errors.append(f"Frozen parent identity mismatch: {key}.")
    decisions = payload.get("decisions") or {}
    if not str(decisions.get("optimized_oracle_equivalence", "")).startswith("PASS"):
        errors.append("Optimized-oracle equivalence decision is not passing.")
    if not str(decisions.get("controlled_xy_elementary_synthesis", "")).startswith(
        "PASS"
    ):
        errors.append("C2-XY elementary synthesis decision is not passing.")
    if decisions.get("backend_native_lowering") != "NOT_RUN":
        errors.append("Backend-native boundary changed.")
    if decisions.get("quantum_advantage") != "NOT_CLAIMED":
        errors.append("Quantum-advantage boundary changed.")
    return {
        "artifact_sha256_computed": computed,
        "artifact_sha256_stored": payload.get("artifact_sha256"),
        "errors": errors,
        "valid": not errors,
    }


def load_optimized_native_artifact(
    path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload, validate_optimized_native_artifact(payload)


def seal_optimized_native_artifact(
    payload: Mapping[str, Any], path: str | Path
) -> dict[str, Any]:
    """Create once; an existing seal is accepted only when semantically identical."""

    report = validate_optimized_native_artifact(payload)
    if not report["valid"]:
        raise ValueError("Refusing to seal an invalid V3.4 artifact: " + "; ".join(report["errors"]))
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        existing, existing_report = load_optimized_native_artifact(destination)
        if not existing_report["valid"]:
            raise FileExistsError("Existing V3.4 seal is invalid and will not be overwritten.")
        if existing.get("artifact_sha256") != payload.get("artifact_sha256"):
            raise FileExistsError("Existing non-identical V3.4 seal will not be overwritten.")
        return existing
    encoded = json.dumps(
        dict(payload),
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8") + b"\n"
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=".optimized-native-",
            delete=False,
        ) as temporary:
            temporary.write(encoded)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        try:
            os.link(temporary_name, destination)
        except FileExistsError:
            existing, existing_report = load_optimized_native_artifact(destination)
            if (
                not existing_report["valid"]
                or existing.get("artifact_sha256") != payload.get("artifact_sha256")
            ):
                raise FileExistsError(
                    "Concurrent non-identical V3.4 seal will not be overwritten."
                )
            return existing
    finally:
        if temporary_name and Path(temporary_name).exists():
            Path(temporary_name).unlink()
    return dict(payload)


def default_optimized_native_root() -> Path:
    return Path.cwd() / "outputs" / "quantum_phase3" / "optimized_native"


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build/seal the Quantum Lab V3.4 artifact.")
    parser.add_argument("v31_parent", type=Path)
    parser.add_argument("v32_parent", type=Path)
    parser.add_argument("v33_parent", type=Path)
    parser.add_argument("v33_freeze", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=default_optimized_native_root() / DEFAULT_SEAL_NAME,
    )
    args = parser.parse_args(argv)
    payload = build_optimized_native_artifact(
        args.v31_parent,
        args.v32_parent,
        args.v33_parent,
        args.v33_freeze,
        progress=lambda message: print(message, flush=True),
    )
    sealed = seal_optimized_native_artifact(payload, args.output)
    print(
        json.dumps(
            {
                "artifact_sha256": sealed["artifact_sha256"],
                "decisions": sealed["decisions"],
                "output": str(args.output),
                "resource_manifest_sha256": sealed["resource_envelopes"][
                    "resource_manifest_sha256"
                ],
                "validation_manifest_sha256": sealed["validation"][
                    "validation_manifest_sha256"
                ],
            },
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "ARTIFACT_VERSION",
    "DEFAULT_SEAL_NAME",
    "VALIDATION_VERSION",
    "build_optimized_native_artifact",
    "build_resource_envelopes",
    "default_optimized_native_root",
    "load_optimized_native_artifact",
    "run_actual_constraint_boundary_validation",
    "run_interval_identity_validation",
    "run_n40_optimized_oracle_validation",
    "run_validation_ladder",
    "seal_optimized_native_artifact",
    "validate_optimized_native_artifact",
    "validation_source_sha256",
    "verifier_source_sha256",
    "verify_v33_freeze_snapshot",
    "verify_v33_parent_chain",
]
