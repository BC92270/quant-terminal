"""Validation ladder and immutable seal for the V3.3 mixer contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from itertools import combinations, product
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .phase2_qhardness import build_hard_instance
from .phase3_algorithmic_contract import (
    ALGORITHM_VERSION,
    EXPECTED_V32_ARTIFACT_SHA256,
    PROFILE_DUAL_GUARD,
    PROFILE_FEASIBLE_ONLY,
    SUPPORTED_PROFILES,
    TOPOLOGY_COMPLETE,
    TOPOLOGY_RING,
    algorithm_source_sha256,
    apply_mixer_layer,
    edge_schedule,
    guard_truth_case,
    guarded_edge_action,
    load_algorithm_spec,
    load_verified_parent_chain,
    raw_file_sha256,
    resource_envelopes,
    statevector_norm,
    swap_bits,
)
from .phase3_artifact_guard import EXPECTED_PARENT_RAW_SHA256, SEALED_SEEDS
from .phase3_gate_compiler import (
    DOMAIN_EXACT_K,
    CircuitIR,
    canonical_json_sha256,
    classical_constraint_value,
    classical_predicate,
    compile_seed_circuit,
)


VALIDATION_VERSION = "PHASE III · ALGORITHMIC CONTRACT VALIDATION LADDER · V1"
ARTIFACT_VERSION = "PHASE III · SEALED EXACT FEASIBLE-SUBSPACE MIXER · V1"
DEFAULT_SEAL_NAME = "SEALED_FEASIBLE_SUBSPACE_MIXER_ARTIFACT.json"
ProgressCallback = Callable[[str], None]


def validation_source_sha256() -> str:
    """Return the exact digest of the code that builds and validates the seal."""

    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def verifier_source_sha256() -> str:
    """Return the exact digest of the independent deployed-chain verifier."""

    verifier_path = Path(__file__).with_name("verify_phase3_v33.py")
    return hashlib.sha256(verifier_path.read_bytes()).hexdigest()


def _notify(callback: ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def run_guard_symbolic_validation() -> dict[str, Any]:
    """Enumerate the Boolean guard contract, including its negative boundary."""

    rows: list[dict[str, Any]] = []
    for profile in SUPPORTED_PROFILES:
        for fx, fy, orientation in product(
            (False, True), (False, True), ("01", "10")
        ):
            row = guard_truth_case(
                fx,
                fy,
                different_bits=True,
                profile=profile,
            )
            rows.append({**row, "orientation": orientation})
        for same_value in (False, True):
            row = guard_truth_case(
                same_value,
                same_value,
                different_bits=False,
                profile=profile,
            )
            rows.append({**row, "orientation": "equal"})

    dual_rows = [row for row in rows if row["profile"] == PROFILE_DUAL_GUARD]
    optimized_rows = [
        row for row in rows if row["profile"] == PROFILE_FEASIBLE_ONLY
    ]
    dual_activation = all(
        row["active"]
        == bool(
            row["current_feasible"]
            and row["swapped_feasible"]
            and row["different_bits"]
        )
        for row in dual_rows
    )
    dual_cleanup = all(row["within_contract_cleanup"] for row in dual_rows)
    optimized_contract_cleanup = all(
        row["within_contract_cleanup"]
        for row in optimized_rows
        if row["precondition_met"]
    )
    optimized_boundary_counterexample = any(
        row["active"]
        and not row["precondition_met"]
        and not all(branch["transient_b_clean"] for branch in row["branches"])
        for row in optimized_rows
    )
    checks = {
        "dual_guard_activation_iff_both_feasible": dual_activation,
        "dual_guard_cleanup_all_exact_k_truth_cases": dual_cleanup,
        "equal_bits_never_rotate": all(
            not row["active"] for row in rows if not row["different_bits"]
        ),
        "optimized_cleanup_under_feasible_support_precondition": optimized_contract_cleanup,
        "optimized_out_of_contract_dirty_counterexample_retained": optimized_boundary_counterexample,
    }
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "rows": rows,
        "truth_case_count": len(rows),
    }


def _synthetic_predicate(bits: Sequence[int]) -> bool:
    values = tuple(int(value) for value in bits)
    if len(values) != 6 or any(value not in (0, 1) for value in values):
        raise ValueError("Synthetic validation expects six binary values.")
    if sum(values) != 3:
        return False
    group_a = values[0] + values[1] + values[2]
    group_b = values[2] + values[3] + values[4]
    factor = sum(
        coefficient * value
        for coefficient, value in zip((-3, -1, 1, 2, 4, 5), values)
    )
    return 1 <= group_a <= 2 and 1 <= group_b <= 2 and 1 <= factor <= 7


def _gram_error(columns: Sequence[Mapping[tuple[int, ...], complex]]) -> float:
    maximum = 0.0
    for i, left in enumerate(columns):
        for j, right in enumerate(columns):
            keys = set(left) | set(right)
            inner = sum(left.get(key, 0j).conjugate() * right.get(key, 0j) for key in keys)
            target = 1.0 if i == j else 0.0
            maximum = max(maximum, abs(inner - target))
    return float(maximum)


def run_small_n_validation() -> dict[str, Any]:
    """Exhaustively validate basis actions and full-layer unitarity at N=6."""

    n = 6
    k = 3
    domain = [
        tuple(int(index in selected) for index in range(n))
        for selected in combinations(range(n), k)
    ]
    feasible = [basis for basis in domain if _synthetic_predicate(basis)]
    edges = edge_schedule(n, TOPOLOGY_COMPLETE)
    angles = (0.0, 0.2718281828, math.pi / 4.0, 1.111)
    profile_rows: list[dict[str, Any]] = []
    total_edge_cases = 0

    for profile in SUPPORTED_PROFILES:
        checked_domain = domain if profile == PROFILE_DUAL_GUARD else feasible
        norm_error = 0.0
        cleanup_pass = True
        invariant_pass = True
        for basis in checked_domain:
            for edge in edges:
                for beta in angles:
                    action = guarded_edge_action(
                        basis,
                        edge,
                        _synthetic_predicate,
                        beta,
                        profile=profile,
                    )
                    total_edge_cases += 1
                    norm = sum(
                        abs(amplitude) ** 2
                        for amplitude in action["amplitudes"].values()
                    )
                    norm_error = max(norm_error, abs(norm - 1.0))
                    cleanup_pass = cleanup_pass and bool(
                        action["guard"]["within_contract_cleanup"]
                    )
                    if _synthetic_predicate(basis):
                        invariant_pass = invariant_pass and all(
                            _synthetic_predicate(target)
                            for target in action["amplitudes"]
                        )

        unitary_domain = domain if profile == PROFILE_DUAL_GUARD else feasible
        columns = [
            apply_mixer_layer(
                {basis: 1.0 + 0j},
                edges,
                _synthetic_predicate,
                tuple(0.071 * (index + 1) for index in range(len(edges))),
                profile=profile,
            )
            for basis in unitary_domain
        ]
        full_layer_norm_error = max(
            abs(statevector_norm(column) - 1.0) for column in columns
        )
        full_layer_invariant = all(
            all(_synthetic_predicate(target) for target in column)
            for basis, column in zip(unitary_domain, columns)
            if _synthetic_predicate(basis)
        )
        gram_error = _gram_error(columns)
        profile_rows.append(
            {
                "basis_domain_size": len(checked_domain),
                "edge_action_cleanup": cleanup_pass,
                "edge_action_feasible_invariance": invariant_pass,
                "edge_action_norm_max_error": norm_error,
                "full_layer_feasible_invariance": full_layer_invariant,
                "full_layer_gram_max_error": gram_error,
                "full_layer_norm_max_error": full_layer_norm_error,
                "profile": profile,
                "unitary_domain_size": len(unitary_domain),
            }
        )

    checks = {
        "nontrivial_feasible_subset": 1 < len(feasible) < len(domain),
        "all_edge_actions_normalized": all(
            row["edge_action_norm_max_error"] <= 1e-12 for row in profile_rows
        ),
        "all_declared_cleanup_conditions_pass": all(
            row["edge_action_cleanup"] for row in profile_rows
        ),
        "feasible_support_invariant": all(
            row["edge_action_feasible_invariance"]
            and row["full_layer_feasible_invariance"]
            for row in profile_rows
        ),
        "full_layer_unitary": all(
            row["full_layer_gram_max_error"] <= 1e-11
            and row["full_layer_norm_max_error"] <= 1e-11
            for row in profile_rows
        ),
    }
    return {
        "checks": checks,
        "complete_edge_count": len(edges),
        "domain_size": len(domain),
        "edge_action_cases": total_edge_cases,
        "feasible_basis_count": len(feasible),
        "passed": all(checks.values()),
        "profiles": profile_rows,
        "synthetic_contract": {
            "N": n,
            "K": k,
            "factor_coefficients": [-3, -1, 1, 2, 4, 5],
            "factor_interval": [1, 7],
            "group_a": {"indices": [0, 1, 2], "interval": [1, 2]},
            "group_b": {"indices": [2, 3, 4], "interval": [1, 2]},
        },
    }


def _constraint_vectors(circuit: CircuitIR) -> tuple[list[list[int]], list[int], list[int]]:
    vectors: list[list[int]] = []
    lower: list[int] = []
    upper: list[int] = []
    for constraint in circuit.constraints:
        coefficients = [0] * circuit.n
        for index, coefficient in zip(
            constraint.data_indices, constraint.coefficients
        ):
            coefficients[index] = int(coefficient)
        vectors.append(coefficients)
        lower.append(int(constraint.lower))
        upper.append(int(constraint.upper))
    return vectors, lower, upper


def _constraint_values(bits: Sequence[int], circuit: CircuitIR) -> list[int]:
    return [classical_constraint_value(bits, constraint) for constraint in circuit.constraints]


def _delta_swap_feasible(
    bits: Sequence[int],
    values: Sequence[int],
    vectors: Sequence[Sequence[int]],
    lower: Sequence[int],
    upper: Sequence[int],
    edge: tuple[int, int],
) -> bool:
    i, j = edge
    delta_bit = int(bits[j]) - int(bits[i])
    return all(
        lo
        <= int(value) + delta_bit * (int(coefficients[i]) - int(coefficients[j]))
        <= hi
        for value, coefficients, lo, hi in zip(values, vectors, lower, upper)
    )


def _two_hop_neighborhood(
    start: tuple[int, ...],
    circuit: CircuitIR,
    edges: Sequence[tuple[int, int]],
) -> tuple[list[int], set[tuple[int, ...]]]:
    vectors, lower, upper = _constraint_vectors(circuit)
    visited = {start}
    frontier = {start}
    shells: list[int] = []
    for _ in range(2):
        next_frontier: set[tuple[int, ...]] = set()
        for bits in sorted(frontier):
            values = _constraint_values(bits, circuit)
            for edge in edges:
                i, j = edge
                if bits[i] == bits[j]:
                    continue
                candidate = swap_bits(bits, i, j)
                if candidate in visited:
                    continue
                if _delta_swap_feasible(
                    bits, values, vectors, lower, upper, edge
                ):
                    next_frontier.add(candidate)
        visited.update(next_frontier)
        frontier = next_frontier
        shells.append(len(next_frontier))
    return shells, visited


def run_n40_witness_graph_validation(
    v31: Mapping[str, Any],
) -> dict[str, Any]:
    """Audit every nontrivial one-swap neighbor and exact two-hop shell."""

    certificates = {
        int(certificate["seed"]): certificate
        for certificate in v31["seed_certificates"]
    }
    complete_edges = edge_schedule(40, TOPOLOGY_COMPLETE)
    ring_edges = edge_schedule(40, TOPOLOGY_RING)
    rows: list[dict[str, Any]] = []

    for seed in SEALED_SEEDS:
        certificate = certificates[int(seed)]
        circuit = compile_seed_circuit(
            certificate,
            DOMAIN_EXACT_K,
            parent_dyadic_oracle_sha=str(v31["dyadic_oracle_sha"]),
            parent_artifact_file_sha256=EXPECTED_PARENT_RAW_SHA256,
        )
        instance = build_hard_instance(40, "BANDS", int(seed))
        witness = tuple(int(value) for value in instance.witness.tolist())
        if str(instance.instance_id) != str(certificate["instance_id"]):
            raise ValueError(f"N=40 instance identity mismatch for seed {seed}.")
        witness_feasible = classical_predicate(witness, circuit)
        vectors, lower, upper = _constraint_vectors(circuit)
        values = _constraint_values(witness, circuit)
        direct_neighbors: set[tuple[int, ...]] = set()
        delta_neighbors: set[tuple[int, ...]] = set()
        nontrivial = 0
        for edge in complete_edges:
            i, j = edge
            if witness[i] == witness[j]:
                continue
            nontrivial += 1
            candidate = swap_bits(witness, i, j)
            if classical_predicate(candidate, circuit):
                direct_neighbors.add(candidate)
            if _delta_swap_feasible(
                witness, values, vectors, lower, upper, edge
            ):
                delta_neighbors.add(candidate)

        ring_neighbors = {
            swap_bits(witness, i, j)
            for i, j in ring_edges
            if witness[i] != witness[j]
            and _delta_swap_feasible(
                witness, values, vectors, lower, upper, (i, j)
            )
        }
        shells_forward, visited_forward = _two_hop_neighborhood(
            witness, circuit, complete_edges
        )
        shells_reverse, visited_reverse = _two_hop_neighborhood(
            witness, circuit, tuple(reversed(complete_edges))
        )
        rows.append(
            {
                "complete_degree": len(direct_neighbors),
                "direct_delta_neighbor_parity": direct_neighbors == delta_neighbors,
                "instance_id": circuit.instance_id,
                "nontrivial_swap_candidates": nontrivial,
                "ring_degree": len(ring_neighbors),
                "seed": int(seed),
                "two_hop_order_independent": visited_forward == visited_reverse,
                "two_hop_reachable_lower_bound": len(visited_forward),
                "two_hop_shells": shells_forward,
                "two_hop_shells_reverse": shells_reverse,
                "two_hop_state_set_sha256": canonical_json_sha256(
                    [list(bits) for bits in sorted(visited_forward)]
                ),
                "witness_feasible": witness_feasible,
                "witness_sha256": canonical_json_sha256(list(witness)),
            }
        )

    isolated_ring_seeds = [row["seed"] for row in rows if row["ring_degree"] == 0]
    checks = {
        "all_eight_authenticated_witnesses": len(rows) == 8,
        "all_witnesses_feasible": all(row["witness_feasible"] for row in rows),
        "all_300_nontrivial_swaps_audited": all(
            row["nontrivial_swap_candidates"] == 300 for row in rows
        ),
        "direct_predicate_matches_integer_delta": all(
            row["direct_delta_neighbor_parity"] for row in rows
        ),
        "complete_topology_positive_local_degree": all(
            row["complete_degree"] > 0 for row in rows
        ),
        "ring_isolation_negative_result_retained": isolated_ring_seeds == [5501],
        "two_hop_order_independent": all(
            row["two_hop_order_independent"] for row in rows
        ),
    }
    return {
        "checks": checks,
        "complete_global_connectivity": "INDETERMINATE",
        "complete_local_decision": "PASS · WITNESS LOCAL REACHABILITY ONLY",
        "isolated_ring_seeds": isolated_ring_seeds,
        "passed": all(checks.values()),
        "ring_decision": "REJECTED · AUTHENTICATED WITNESS ISOLATION",
        "rows": rows,
    }


def run_validation_ladder(
    v31_path: str | Path,
    v32_path: str | Path,
    *,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Execute the complete deterministic V3.3 validation ladder."""

    _notify(progress, "A · authenticate frozen V3.1/V3.2 parent chain")
    v31, v32, parent_report = load_verified_parent_chain(v31_path, v32_path)
    spec = load_algorithm_spec()
    _notify(progress, "B · symbolic guard truth table")
    guard = run_guard_symbolic_validation()
    _notify(progress, "C · exhaustive N=6 statevector contract")
    small_n = run_small_n_validation()
    _notify(progress, "D · all N=40 witness swap neighborhoods")
    n40 = run_n40_witness_graph_validation(v31)
    _notify(progress, "E · deterministic resource accounting, pass 1/2")
    resources_first = resource_envelopes(v32)
    _notify(progress, "E · deterministic resource accounting, pass 2/2")
    resources_second = resource_envelopes(v32)
    resource_reproducible = resources_first == resources_second
    spec_self_hash = spec["algorithm_contract_spec_sha256"] == canonical_json_sha256(
        {
            key: value
            for key, value in spec.items()
            if key
            not in {
                "algorithm_contract_spec_sha",
                "algorithm_contract_spec_sha256",
            }
        }
    )
    checks = {
        "A_PARENT_CHAIN": bool(
            parent_report["v32_release_verifier"].get("valid")
            and v32.get("artifact_sha256") == EXPECTED_V32_ARTIFACT_SHA256
        ),
        "B_SPEC_SELF_HASH": spec_self_hash,
        "C_GUARD_SYMBOLIC": bool(guard["passed"]),
        "D_SMALL_N_EXHAUSTIVE_UNITARY": bool(small_n["passed"]),
        "E_N40_WITNESS_GRAPH": bool(n40["passed"]),
        "F_RESOURCE_REPRODUCIBILITY": resource_reproducible,
        "G_NEGATIVE_RESULTS_RETAINED": bool(
            n40["ring_decision"].startswith("REJECTED")
            and n40["complete_global_connectivity"] == "INDETERMINATE"
        ),
        "H_HARDWARE_FAIL_CLOSED": bool(
            spec["claim_boundary"]["hardware_executable"] is False
            and spec["claim_boundary"]["qpu_submission_enabled"] is False
            and all(
                ledger["backend_transpilation_status"] == "NOT_RUN"
                and ledger["controlled_xy_native_cost"] == "NOT_ESTIMATED"
                for ledger in resources_first["ledgers"].values()
            )
        ),
    }
    validation_core = {
        "algorithm_source_sha256": algorithm_source_sha256(),
        "algorithm_spec_sha256": spec["algorithm_contract_spec_sha256"],
        "checks": checks,
        "guard_symbolic": guard,
        "n40_witness_graph": n40,
        "parent_chain": {
            "v31_raw_file_sha256": parent_report["v31_raw_file_sha256"],
            "v32_artifact_sha256": v32["artifact_sha256"],
            "v32_raw_file_sha256": parent_report["v32_raw_file_sha256"],
            "v32_validation_manifest_sha256": v32["validation"][
                "validation_manifest_sha256"
            ],
            "verified": True,
        },
        "resource_manifest_sha256": resources_first[
            "resource_manifest_sha256"
        ],
        "resource_reproducibility": {
            "first_sha256": canonical_json_sha256(resources_first),
            "passed": resource_reproducible,
            "second_sha256": canonical_json_sha256(resources_second),
        },
        "small_n_exhaustive": small_n,
        "validation_source_sha256": validation_source_sha256(),
        "validation_version": VALIDATION_VERSION,
        "verifier_source_sha256": verifier_source_sha256(),
    }
    return {
        **validation_core,
        "overall_pass": all(checks.values()),
        "validation_manifest_sha256": canonical_json_sha256(validation_core),
    }


def build_algorithmic_artifact(
    v31_path: str | Path,
    v32_path: str | Path,
    *,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    v31, v32, parent_report = load_verified_parent_chain(v31_path, v32_path)
    del v31
    spec = load_algorithm_spec()
    validation = run_validation_ladder(
        v31_path,
        v32_path,
        progress=progress,
    )
    if not validation["overall_pass"]:
        raise ValueError("V3.3 validation ladder did not pass; seal is blocked.")
    resources = resource_envelopes(v32)
    n40 = validation["n40_witness_graph"]
    artifact_core = {
        "algorithm": {
            "algorithm_source_sha256": algorithm_source_sha256(),
            "algorithm_spec_sha": spec["algorithm_contract_spec_sha"],
            "algorithm_spec_sha256": spec["algorithm_contract_spec_sha256"],
            "algorithm_version": ALGORITHM_VERSION,
            "canonical_profile": PROFILE_DUAL_GUARD,
            "canonical_topology": TOPOLOGY_COMPLETE,
            "status": "SEALED EXACT FEASIBILITY-INVARIANCE CONTRACT",
        },
        "artifact_version": ARTIFACT_VERSION,
        "claim_boundary": {
            "allowed": spec["claim_boundary"]["allowed"],
            "forbidden": spec["claim_boundary"]["forbidden"],
            "hardware_executable": False,
            "qpu_submission_enabled": False,
        },
        "construction": {
            "cached_dual_guard": True,
            "controlled_rotation": "C2-XY(beta)",
            "oracle_calls_per_layer": "2E+2",
            "ordered_partial_mixers": True,
            "physical_swap_gates_in_logical_ir": 0,
            "profiles": spec["construction"]["profiles"],
            "static_neighbor_oracle_wire_relabel": True,
        },
        "decisions": {
            "backend_native_lowering": "NOT_RUN",
            "complete_global_connectivity": "INDETERMINATE",
            "complete_witness_local_reachability": n40[
                "complete_local_decision"
            ],
            "controlled_xy_native_synthesis": "NOT_RUN",
            "feasibility_invariance": "PASS · RELATIVE TO FROZEN V3.2 PREDICATE",
            "guard_ancilla_cleanup": "PASS",
            "hardware_execution": "BLOCKED · ZERO JOBS",
            "optimization_performance": "NOT_TESTED",
            "quantum_advantage": "NOT_CLAIMED",
            "ring_topology": n40["ring_decision"],
        },
        "family": v32["family"],
        "limitations": [
            "The complete single-swap feasible graph was not exhaustively enumerated at N=40; global connectivity and ergodicity remain indeterminate.",
            "Ring-only exploration is rejected because the authenticated seed-5501 witness has zero feasible ring-swap neighbors.",
            "C2-XY is an algorithmic IR primitive whose native decomposition, synthesis precision and T cost are not estimated.",
            "Static wire relabelling is free only in provider-neutral logical IR; backend routing cost is not run.",
            "No variational optimization, sampling advantage, runtime advantage or QPU execution was performed.",
            "The optimized single-guard profile is clean only under an explicit feasible-support precondition; it is not the institutional default.",
        ],
        "parents": {
            "v31_dyadic_oracle_sha": spec["parent_contract"][
                "expected_parent_v31_dyadic_oracle_sha"
            ],
            "v31_raw_file_sha256": parent_report["v31_raw_file_sha256"],
            "v32_artifact_sha256": v32["artifact_sha256"],
            "v32_compiler_source_sha256": v32["compiler"][
                "compiler_source_sha256"
            ],
            "v32_compiler_spec_sha256": v32["compiler"][
                "compiler_spec_sha256"
            ],
            "v32_raw_file_sha256": parent_report["v32_raw_file_sha256"],
            "v32_validation_manifest_sha256": v32["validation"][
                "validation_manifest_sha256"
            ],
        },
        "resource_envelopes": resources,
        "roadmap_change_control": spec["roadmap_change_control"],
        "validation": validation,
    }
    return {
        **artifact_core,
        "artifact_sha256": canonical_json_sha256(artifact_core),
        "created_utc": datetime.now(timezone.utc).isoformat(),
    }


def validate_algorithmic_artifact(payload: Mapping[str, Any]) -> dict[str, Any]:
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
    validation = payload.get("validation")
    if not isinstance(validation, dict) or validation.get("overall_pass") is not True:
        errors.append("Validation manifest is not passing.")
    elif validation.get("validation_manifest_sha256") != canonical_json_sha256(
        {
            key: value
            for key, value in validation.items()
            if key not in {"validation_manifest_sha256", "overall_pass"}
        }
    ):
        errors.append("Validation manifest SHA-256 mismatch.")
    if isinstance(validation, dict):
        if validation.get("validation_source_sha256") != validation_source_sha256():
            errors.append("Live validation source SHA-256 mismatch.")
        if validation.get("verifier_source_sha256") != verifier_source_sha256():
            errors.append("Live verifier source SHA-256 mismatch.")
    decisions = payload.get("decisions") or {}
    required_decisions = {
        "backend_native_lowering": "NOT_RUN",
        "complete_global_connectivity": "INDETERMINATE",
        "controlled_xy_native_synthesis": "NOT_RUN",
        "guard_ancilla_cleanup": "PASS",
        "hardware_execution": "BLOCKED · ZERO JOBS",
        "optimization_performance": "NOT_TESTED",
        "quantum_advantage": "NOT_CLAIMED",
    }
    for key, expected in required_decisions.items():
        if decisions.get(key) != expected:
            errors.append(f"Decision boundary mismatch: {key}.")
    if not str(decisions.get("feasibility_invariance", "")).startswith("PASS"):
        errors.append("Feasibility-invariance decision is not passing.")
    if not str(decisions.get("ring_topology", "")).startswith("REJECTED"):
        errors.append("Ring-isolation negative decision was not retained.")
    if (
        payload.get("parents", {}).get("v32_artifact_sha256")
        != EXPECTED_V32_ARTIFACT_SHA256
    ):
        errors.append("Frozen V3.2 parent identity mismatch.")
    return {
        "artifact_sha256_computed": computed,
        "artifact_sha256_stored": payload.get("artifact_sha256"),
        "errors": errors,
        "valid": not errors,
    }


def load_algorithmic_artifact(
    path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    report = validate_algorithmic_artifact(payload)
    return payload, report


def seal_algorithmic_artifact(
    payload: Mapping[str, Any], path: str | Path
) -> dict[str, Any]:
    """Write once, accepting only an existing semantically identical seal."""

    report = validate_algorithmic_artifact(payload)
    if not report["valid"]:
        raise ValueError("Refusing to seal an invalid V3.3 artifact.")
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        existing, existing_report = load_algorithmic_artifact(destination)
        if not existing_report["valid"]:
            raise FileExistsError("Existing V3.3 seal is invalid and will not be overwritten.")
        if existing.get("artifact_sha256") != payload.get("artifact_sha256"):
            raise FileExistsError("Existing non-identical V3.3 seal will not be overwritten.")
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
            prefix=".algorithmic-contract-",
            delete=False,
        ) as temporary:
            temporary.write(encoded)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        try:
            os.link(temporary_name, destination)
        except FileExistsError:
            existing, existing_report = load_algorithmic_artifact(destination)
            if (
                not existing_report["valid"]
                or existing.get("artifact_sha256") != payload.get("artifact_sha256")
            ):
                raise FileExistsError(
                    "Concurrent non-identical V3.3 seal will not be overwritten."
                )
            return existing
    finally:
        if temporary_name and Path(temporary_name).exists():
            Path(temporary_name).unlink()
    return dict(payload)


def default_algorithmic_root() -> Path:
    return Path.cwd() / "outputs" / "quantum_phase3" / "algorithmic_contract"


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build/seal the V3.3 mixer contract.")
    parser.add_argument("v31_parent", type=Path)
    parser.add_argument("v32_parent", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=default_algorithmic_root() / DEFAULT_SEAL_NAME,
    )
    args = parser.parse_args(argv)
    payload = build_algorithmic_artifact(
        args.v31_parent,
        args.v32_parent,
        progress=lambda message: print(message, flush=True),
    )
    sealed = seal_algorithmic_artifact(payload, args.output)
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
    "build_algorithmic_artifact",
    "default_algorithmic_root",
    "load_algorithmic_artifact",
    "run_guard_symbolic_validation",
    "run_n40_witness_graph_validation",
    "run_small_n_validation",
    "run_validation_ladder",
    "seal_algorithmic_artifact",
    "validation_source_sha256",
    "validate_algorithmic_artifact",
    "verifier_source_sha256",
]
