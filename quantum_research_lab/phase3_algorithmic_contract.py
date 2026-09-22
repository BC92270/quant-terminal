"""Exact feasible-subspace mixer contract layered on the frozen V3.2 oracle.

The module deliberately stops at an algorithmic, provider-neutral IR.  It
constructs and simulates guarded XY transitions, authenticates the immutable
V3.1/V3.2 parents, and accounts for every frozen-oracle invocation.  It does
not synthesize the controlled rotation into a native basis or submit hardware
jobs.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .phase3_circuit_validation import load_compiler_artifact
from .phase3_gate_compiler import (
    DOMAIN_EXACT_K,
    canonical_json_sha256,
)
from .verify_phase3_v32 import verify_release_chain


ALGORITHM_VERSION = "PHASE III · EXACT FEASIBLE-SUBSPACE MIXER · V1"
SPEC_FILENAME = "PHASE_III_ALGORITHMIC_CONTRACT_SPEC_V1.json"

PROFILE_DUAL_GUARD = "DUAL_GUARD_CACHED"
PROFILE_FEASIBLE_ONLY = "FEASIBLE_SUPPORT_OPTIMIZED"
SUPPORTED_PROFILES = (PROFILE_DUAL_GUARD, PROFILE_FEASIBLE_ONLY)

TOPOLOGY_RING = "RING_SWAP_SCAN"
TOPOLOGY_COMPLETE = "COMPLETE_SWAP_SCAN"
SUPPORTED_TOPOLOGIES = (TOPOLOGY_RING, TOPOLOGY_COMPLETE)

EXPECTED_V31_RAW_SHA256 = (
    "7b39a20ec9200b16996ec25edd660ba7bf26bfb2b454ed44dd1a333513afd50e"
)
EXPECTED_V32_RAW_SHA256 = (
    "616cc12808465916dfcfcde6c8e2c9feed1be4b294ad034f29cb7cb36704031b"
)
EXPECTED_V32_ARTIFACT_SHA256 = (
    "5e6cc7e53f15921f7cbd22ef66f04878b37d54372e04b5bf49f5bb4854050fcd"
)
EXPECTED_V32_VALIDATION_SHA256 = (
    "bde0dc2e90a355821c8678d2df8ac743820c0a4d2e83701aeeeaab3e1d8e9b91"
)

Basis = tuple[int, ...]
Predicate = Callable[[Sequence[int]], bool]


def _without(payload: Mapping[str, Any], fields: Sequence[str]) -> dict[str, Any]:
    excluded = set(fields)
    return {key: value for key, value in payload.items() if key not in excluded}


def raw_file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_algorithm_spec(path: str | Path | None = None) -> dict[str, Any]:
    """Load the preregistered contract and enforce its self-hash boundary."""

    spec_path = Path(path) if path is not None else Path(__file__).with_name(SPEC_FILENAME)
    payload = json.loads(spec_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Algorithmic contract specification must be a JSON object.")
    content = _without(
        payload,
        ("algorithm_contract_spec_sha", "algorithm_contract_spec_sha256"),
    )
    full_hash = canonical_json_sha256(content)
    if payload.get("algorithm_contract_spec_sha256") != full_hash:
        raise ValueError("Algorithmic contract specification SHA-256 mismatch.")
    if payload.get("algorithm_contract_spec_sha") != full_hash[:20].upper():
        raise ValueError("Algorithmic contract specification short SHA mismatch.")
    boundary = payload.get("claim_boundary") or {}
    if boundary.get("hardware_executable") is not False:
        raise ValueError("Algorithmic specification violates the hardware boundary.")
    if boundary.get("qpu_submission_enabled") is not False:
        raise ValueError("Algorithmic specification enables QPU submission.")
    return payload


def algorithm_source_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def load_verified_parent_chain(
    v31_path: str | Path,
    v32_path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Authenticate both immutable parents and return their payloads/report."""

    spec = load_algorithm_spec()
    parent = spec["parent_contract"]
    report = verify_release_chain(v31_path, v32_path)
    errors: list[str] = []
    v31_raw = raw_file_sha256(v31_path)
    v32_raw = raw_file_sha256(v32_path)
    if v31_raw != parent["expected_parent_v31_raw_file_sha256"]:
        errors.append("V3.1 raw SHA-256 mismatch.")
    if v32_raw != parent["expected_parent_v32_raw_file_sha256"]:
        errors.append("V3.2 raw SHA-256 mismatch.")
    v32, integrity = load_compiler_artifact(v32_path)
    if not integrity.get("valid"):
        errors.extend(str(item) for item in integrity.get("errors", []))
    if v32.get("artifact_sha256") != parent["expected_parent_v32_artifact_sha256"]:
        errors.append("V3.2 semantic artifact SHA-256 mismatch.")
    if (
        v32.get("validation", {}).get("validation_manifest_sha256")
        != parent["expected_parent_v32_validation_manifest_sha256"]
    ):
        errors.append("V3.2 validation manifest SHA-256 mismatch.")
    if report.get("valid") is not True:
        errors.extend(str(item) for item in report.get("errors", []))
        errors.extend(f"V3.2 check failed: {item}" for item in report.get("failed_checks", []))
    if errors:
        raise ValueError("Frozen parent chain failed: " + "; ".join(dict.fromkeys(errors)))
    v31 = json.loads(Path(v31_path).read_text(encoding="utf-8"))
    return v31, v32, {
        "v31_raw_file_sha256": v31_raw,
        "v32_raw_file_sha256": v32_raw,
        "v32_release_verifier": report,
    }


def swap_bits(bits: Sequence[int], i: int, j: int) -> Basis:
    values = tuple(int(value) for value in bits)
    if any(value not in (0, 1) for value in values):
        raise ValueError("Swap input must be binary.")
    if i == j or not (0 <= i < len(values) and 0 <= j < len(values)):
        raise ValueError("Swap edge must contain two distinct in-range indices.")
    result = list(values)
    result[i], result[j] = result[j], result[i]
    return tuple(result)


def edge_schedule(n: int, topology: str) -> tuple[tuple[int, int], ...]:
    """Return a canonical ordered sequence of unordered swap edges."""

    n = int(n)
    if n < 2:
        raise ValueError("A mixer topology requires at least two data qubits.")
    if topology == TOPOLOGY_COMPLETE:
        return tuple((i, j) for i in range(n) for j in range(i + 1, n))
    if topology == TOPOLOGY_RING:
        if n == 2:
            return ((0, 1),)
        return tuple([(i, i + 1) for i in range(n - 1)] + [(0, n - 1)])
    raise ValueError(f"Unsupported mixer topology: {topology}")


def guard_truth_case(
    current_feasible: bool,
    swapped_feasible: bool,
    *,
    different_bits: bool,
    profile: str,
) -> dict[str, Any]:
    """Symbolically audit activation and cleanup for one predicate truth case."""

    if profile not in SUPPORTED_PROFILES:
        raise ValueError(f"Unsupported guard profile: {profile}")
    fx = bool(current_feasible)
    fy = bool(swapped_feasible)
    different = bool(different_bits)
    if profile == PROFILE_DUAL_GUARD:
        active = bool(fx and fy and different)
        precondition_met = True
    else:
        active = bool(fy and different)
        precondition_met = fx

    branch_labels = ("x", "Sx") if active else ("x",)
    branches: list[dict[str, Any]] = []
    for label in branch_labels:
        current_f = fx if label == "x" else fy
        swapped_current_f = fy if label == "x" else fx
        transient_b_after = int(fy) ^ int(swapped_current_f)
        retained_a_consistent = (
            int(fx) == int(current_f)
            if profile == PROFILE_DUAL_GUARD
            else True
        )
        branches.append(
            {
                "branch": label,
                "current_predicate": current_f,
                "retained_a_consistent": retained_a_consistent,
                "transient_b_after_uncompute": transient_b_after,
                "transient_b_clean": transient_b_after == 0,
            }
        )
    cleanup_pass = all(
        row["transient_b_clean"] and row["retained_a_consistent"]
        for row in branches
    )
    return {
        "active": active,
        "branches": branches,
        "current_feasible": fx,
        "different_bits": different,
        "precondition_met": precondition_met,
        "profile": profile,
        "swapped_feasible": fy,
        "within_contract_cleanup": bool(cleanup_pass and precondition_met),
    }


def guarded_edge_action(
    bits: Sequence[int],
    edge: tuple[int, int],
    predicate: Predicate,
    beta: float,
    *,
    profile: str = PROFILE_DUAL_GUARD,
) -> dict[str, Any]:
    """Apply one abstract guarded XY rotation to a computational basis state."""

    if profile not in SUPPORTED_PROFILES:
        raise ValueError(f"Unsupported guard profile: {profile}")
    x = tuple(int(value) for value in bits)
    i, j = edge
    y = swap_bits(x, i, j)
    fx = bool(predicate(x))
    fy = bool(predicate(y))
    different = x[i] != x[j]
    truth = guard_truth_case(
        fx,
        fy,
        different_bits=different,
        profile=profile,
    )
    if truth["active"]:
        amplitudes = {
            x: complex(math.cos(float(beta)), 0.0),
            y: complex(0.0, -math.sin(float(beta))),
        }
    else:
        amplitudes = {x: complex(1.0, 0.0)}
    amplitudes = {
        state: amplitude
        for state, amplitude in amplitudes.items()
        if abs(amplitude) > 1e-15
    }
    return {
        "amplitudes": amplitudes,
        "current_feasible": fx,
        "different_bits": different,
        "guard": truth,
        "swapped_feasible": fy,
    }


def apply_mixer_layer(
    amplitudes: Mapping[Basis, complex],
    edges: Sequence[tuple[int, int]],
    predicate: Predicate,
    beta: float | Sequence[float],
    *,
    profile: str = PROFILE_DUAL_GUARD,
    enforce_precondition: bool = True,
) -> dict[Basis, complex]:
    """Simulate the ordered partial-mixer product on a sparse statevector."""

    state = {
        tuple(int(value) for value in basis): complex(amplitude)
        for basis, amplitude in amplitudes.items()
        if abs(amplitude) > 1e-15
    }
    if not state:
        raise ValueError("Mixer input state cannot be empty.")
    if profile == PROFILE_FEASIBLE_ONLY and enforce_precondition:
        if any(not predicate(basis) for basis in state):
            raise ValueError("Feasible-support profile received infeasible amplitude.")
    if isinstance(beta, Sequence) and not isinstance(beta, (str, bytes)):
        angles = tuple(float(value) for value in beta)
        if len(angles) != len(edges):
            raise ValueError("One beta is required for every ordered edge.")
    else:
        angles = tuple(float(beta) for _ in edges)

    for edge, angle in zip(edges, angles):
        updated: dict[Basis, complex] = {}
        for basis, source_amplitude in state.items():
            action = guarded_edge_action(
                basis,
                edge,
                predicate,
                angle,
                profile=profile,
            )
            for target, coefficient in action["amplitudes"].items():
                updated[target] = updated.get(target, 0j) + source_amplitude * coefficient
        state = {
            basis: amplitude
            for basis, amplitude in updated.items()
            if abs(amplitude) > 1e-13
        }
    return state


def statevector_norm(amplitudes: Mapping[Basis, complex]) -> float:
    return float(sum(abs(value) ** 2 for value in amplitudes.values()))


def _exact_k_entries(v32_artifact: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    entries = [
        entry
        for entry in v32_artifact.get("validation", {}).get("compilation_entries", [])
        if entry.get("domain_mode") == DOMAIN_EXACT_K
    ]
    if len(entries) != 8:
        raise ValueError("V3.2 artifact must contain eight exact-K compilation entries.")
    return sorted(entries, key=lambda row: int(row["seed"]))


def resource_ledger(
    v32_artifact: Mapping[str, Any],
    *,
    topology: str,
    profile: str,
) -> dict[str, Any]:
    """Compute exact provider-neutral wrapper resources from frozen V3.2 ledgers."""

    if profile not in SUPPORTED_PROFILES:
        raise ValueError(f"Unsupported guard profile: {profile}")
    edges = edge_schedule(40, topology)
    edge_count = len(edges)
    oracle_calls = 2 * edge_count + (2 if profile == PROFILE_DUAL_GUARD else 0)
    per_seed: list[dict[str, Any]] = []
    for entry in _exact_k_entries(v32_artifact):
        levels = entry["resource_ledger"]["levels"]
        logical = levels["LOGICAL_IR"]
        abstract = levels["GATE_LEVEL_ABSTRACT"]
        fault_tolerant = levels["FAULT_TOLERANT_ESTIMATE"]
        oracle_gates = int(abstract["gate_count"])
        oracle_depth = int(abstract["abstract_depth"])
        oracle_t = int(fault_tolerant["t_count"])
        provider_gate_count = oracle_calls * oracle_gates + edge_count
        provider_depth = oracle_calls * oracle_depth + edge_count
        extra_guard = 1 if profile == PROFILE_DUAL_GUARD else 0
        row = {
            "algorithmic_ir_sha256": canonical_json_sha256(
                {
                    "algorithm_version": ALGORITHM_VERSION,
                    "base_gate_ir_sha256": entry["gate_ir_sha256"],
                    "edge_schedule_sha256": canonical_json_sha256(edges),
                    "oracle_calls": oracle_calls,
                    "profile": profile,
                    "spec_sha256": load_algorithm_spec()["algorithm_contract_spec_sha256"],
                    "topology": topology,
                }
            ),
            "base_oracle_abstract_depth": oracle_depth,
            "base_oracle_abstract_gates": oracle_gates,
            "base_oracle_gate_ir_sha256": entry["gate_ir_sha256"],
            "controlled_xy_primitives": edge_count,
            "instance_id": entry["instance_id"],
            "logical_qubits_sequential_reuse": int(logical["logical_qubits_total"]) + extra_guard,
            "native_controlled_xy_status": "NOT_DECOMPOSED",
            "oracle_calls": oracle_calls,
            "oracle_path_t_count_upper_subtotal": oracle_calls * oracle_t,
            "physical_swap_fallback_cx_addition": 12 * edge_count,
            "physical_swap_fallback_depth_addition": 12 * edge_count,
            "profile": profile,
            "provider_neutral_depth": provider_depth,
            "provider_neutral_gate_count": provider_gate_count,
            "seed": int(entry["seed"]),
            "topology": topology,
            "transpiled_backend_specific": "NOT_RUN",
        }
        per_seed.append(row)

    return {
        "backend_transpilation_status": "NOT_RUN",
        "controlled_xy_native_cost": "NOT_ESTIMATED",
        "edge_count": edge_count,
        "edge_schedule_sha256": canonical_json_sha256(edges),
        "maxima": {
            "logical_qubits_sequential_reuse": max(
                row["logical_qubits_sequential_reuse"] for row in per_seed
            ),
            "oracle_path_t_count_upper_subtotal": max(
                row["oracle_path_t_count_upper_subtotal"] for row in per_seed
            ),
            "provider_neutral_depth": max(
                row["provider_neutral_depth"] for row in per_seed
            ),
            "provider_neutral_gate_count": max(
                row["provider_neutral_gate_count"] for row in per_seed
            ),
            "provider_neutral_gate_count_with_physical_swap_fallback": max(
                row["provider_neutral_gate_count"]
                + row["physical_swap_fallback_cx_addition"]
                for row in per_seed
            ),
        },
        "oracle_calls": oracle_calls,
        "per_seed": per_seed,
        "profile": profile,
        "resource_boundary": (
            "Provider-neutral exact frozen-oracle accounting. C2-XY native synthesis, "
            "routing, calibration and noise costs are excluded and NOT_ESTIMATED."
        ),
        "topology": topology,
    }


def resource_envelopes(v32_artifact: Mapping[str, Any]) -> dict[str, Any]:
    ledgers = {
        f"{profile}::{topology}": resource_ledger(
            v32_artifact,
            topology=topology,
            profile=profile,
        )
        for profile in SUPPORTED_PROFILES
        for topology in SUPPORTED_TOPOLOGIES
    }
    return {
        "canonical_profile": PROFILE_DUAL_GUARD,
        "canonical_topology": TOPOLOGY_COMPLETE,
        "ledgers": ledgers,
        "resource_manifest_sha256": canonical_json_sha256(ledgers),
    }


__all__ = [
    "ALGORITHM_VERSION",
    "EXPECTED_V31_RAW_SHA256",
    "EXPECTED_V32_ARTIFACT_SHA256",
    "EXPECTED_V32_RAW_SHA256",
    "EXPECTED_V32_VALIDATION_SHA256",
    "PROFILE_DUAL_GUARD",
    "PROFILE_FEASIBLE_ONLY",
    "SUPPORTED_PROFILES",
    "SUPPORTED_TOPOLOGIES",
    "TOPOLOGY_COMPLETE",
    "TOPOLOGY_RING",
    "algorithm_source_sha256",
    "apply_mixer_layer",
    "edge_schedule",
    "guard_truth_case",
    "guarded_edge_action",
    "load_algorithm_spec",
    "load_verified_parent_chain",
    "raw_file_sha256",
    "resource_envelopes",
    "resource_ledger",
    "statevector_norm",
    "swap_bits",
]
