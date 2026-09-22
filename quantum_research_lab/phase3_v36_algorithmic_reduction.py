"""Provider-free structural decomposition and rewrite admission for V3.6.

V3.6 attacks the frozen selected-model numerator before any backend work.  It
authenticates the V3.4/V3.5 evidence chain, reconstructs every canonical CNOT
total by mechanism, validates the exact swap-delta arithmetic that could power
an incremental feasibility guard, and classifies every rewrite lane by its
semantic boundary.  It imports no provider SDK and contains no execution path.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence


V36_VERSION = "PHASE III · V3.6 PROVIDER-FREE ALGORITHMIC REDUCTION · V1"
ARTIFACT_VERSION = "PHASE III · V3.6 STRUCTURAL COST + REWRITE ADMISSION ARTIFACT · V1"
SPEC_FILENAME = "PHASE_III_V3_6_ALGORITHMIC_REDUCTION_SPEC_V1.json"
DEFAULT_ARTIFACT_NAME = "SEALED_V3_6_ALGORITHMIC_REDUCTION_ARTIFACT.json"
CANONICAL_LEDGER_KEY = "DUAL_GUARD_CACHED::COMPLETE_SWAP_SCAN"
EXPECTED_SEEDS = (1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807)

SEMANTICS_FULL = "PRESERVED_EXACT_FULL_OPERATOR"
SEMANTICS_FEASIBLE = "PRESERVED_ON_FROZEN_FEASIBLE_SUPPORT_ONLY"
SEMANTICS_CHANGED = "CHANGED_SEMANTICS"
SEMANTICS_UNPROVEN = (
    "PRESERVATION_TARGET_EXACT_BUT_REVERSIBLE_IMPLEMENTATION_UNPROVEN"
)


def canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_json_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def raw_file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_sha256() -> str:
    return raw_file_sha256(Path(__file__))


def _read_object(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def load_v36_spec(path: str | Path | None = None) -> dict[str, Any]:
    spec_path = Path(path) if path is not None else Path(__file__).with_name(SPEC_FILENAME)
    payload = _read_object(spec_path)
    core = {
        key: value
        for key, value in payload.items()
        if key not in {"v36_spec_sha", "v36_spec_sha256"}
    }
    digest = canonical_json_sha256(core)
    if payload.get("v36_spec_sha256") != digest:
        raise ValueError("V3.6 specification SHA-256 mismatch.")
    if payload.get("v36_spec_sha") != digest[:20].upper():
        raise ValueError("V3.6 specification short SHA mismatch.")
    boundary = payload.get("claim_boundary") or {}
    acceptance = payload.get("acceptance_contract") or {}
    if boundary.get("research_classification") != "RESEARCH_ONLY":
        raise ValueError("V3.6 must remain RESEARCH_ONLY.")
    if boundary.get("hardware_executable") is not False:
        raise ValueError("V3.6 hardware boundary is not false.")
    if boundary.get("qpu_submission_enabled") is not False:
        raise ValueError("V3.6 QPU boundary is not false.")
    if boundary.get("provider_calls") != 0:
        raise ValueError("V3.6 provider-call boundary is non-zero.")
    if acceptance.get("provider_credentials") != "PROHIBITED":
        raise ValueError("V3.6 permits provider credentials.")
    if acceptance.get("qpu_jobs_submitted") != 0:
        raise ValueError("V3.6 reports QPU jobs.")
    return payload


def _default_paths() -> dict[str, Path]:
    root = Path(__file__).resolve().parents[1]
    return {
        "root": root,
        "v31": root / "SEALED_EXACT_DYADIC_BANDS_ORACLE.json",
        "v34": root
        / "outputs"
        / "quantum_phase3"
        / "optimized_native"
        / "SEALED_OPTIMIZED_NATIVE_MIXER_ARTIFACT.json",
        "v34_spec": root
        / "quantum_research_lab"
        / "PHASE_III_OPTIMIZED_NATIVE_SPEC_V1.json",
        "v35": root
        / "outputs"
        / "quantum_phase3"
        / "backend_admission"
        / "SEALED_BACKEND_ADMISSION_NEGATIVE_RESULT.json",
        "v35_freeze": root / "FREEZE_CONTRACT_V3_5.json",
    }


def _parent_payloads(
    *,
    v31_path: str | Path | None = None,
    v34_path: str | Path | None = None,
    v34_spec_path: str | Path | None = None,
    v35_path: str | Path | None = None,
    v35_freeze_path: str | Path | None = None,
) -> tuple[dict[str, Path], dict[str, dict[str, Any]]]:
    defaults = _default_paths()
    paths = {
        "v31": Path(v31_path) if v31_path is not None else defaults["v31"],
        "v34": Path(v34_path) if v34_path is not None else defaults["v34"],
        "v34_spec": (
            Path(v34_spec_path) if v34_spec_path is not None else defaults["v34_spec"]
        ),
        "v35": Path(v35_path) if v35_path is not None else defaults["v35"],
        "v35_freeze": (
            Path(v35_freeze_path)
            if v35_freeze_path is not None
            else defaults["v35_freeze"]
        ),
    }
    payloads = {name: _read_object(path) for name, path in paths.items()}
    return paths, payloads


def authenticate_parent_chain(
    spec: Mapping[str, Any] | None = None,
    **path_overrides: Any,
) -> dict[str, Any]:
    contract = dict(spec) if spec is not None else load_v36_spec()
    expected = contract.get("parent_contract") or {}
    errors: list[str] = []
    try:
        paths, payloads = _parent_payloads(**path_overrides)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"checks": {}, "errors": [str(exc)], "valid": False}

    v34 = payloads["v34"]
    v34_core = {
        key: value
        for key, value in v34.items()
        if key not in {"artifact_sha256", "created_utc"}
    }
    v34_spec = payloads["v34_spec"]
    v34_spec_core = {
        key: value
        for key, value in v34_spec.items()
        if key not in {"v34_spec_sha", "v34_spec_sha256"}
    }
    v35 = payloads["v35"]
    v35_core = {key: value for key, value in v35.items() if key != "artifact_sha256"}
    v35_freeze = payloads["v35_freeze"]
    v35_freeze_core = {
        key: value
        for key, value in v35_freeze.items()
        if key != "freeze_contract_sha256"
    }
    comparisons = {
        "v31_raw": (
            raw_file_sha256(paths["v31"]),
            expected.get("expected_parent_v31_raw_file_sha256"),
        ),
        "v34_raw": (
            raw_file_sha256(paths["v34"]),
            expected.get("expected_parent_v34_artifact_raw_file_sha256"),
        ),
        "v34_semantic_stored": (
            v34.get("artifact_sha256"),
            expected.get("expected_parent_v34_artifact_sha256"),
        ),
        "v34_semantic_recomputed": (
            canonical_json_sha256(v34_core),
            expected.get("expected_parent_v34_artifact_sha256"),
        ),
        "v34_resource_manifest": (
            (v34.get("resource_envelopes") or {}).get("resource_manifest_sha256"),
            expected.get("expected_parent_v34_resource_manifest_sha256"),
        ),
        "v34_spec_raw": (
            raw_file_sha256(paths["v34_spec"]),
            expected.get("expected_parent_v34_spec_raw_file_sha256"),
        ),
        "v34_spec_semantic_stored": (
            v34_spec.get("v34_spec_sha256"),
            expected.get("expected_parent_v34_spec_sha256"),
        ),
        "v34_spec_semantic_recomputed": (
            canonical_json_sha256(v34_spec_core),
            expected.get("expected_parent_v34_spec_sha256"),
        ),
        "v35_raw": (
            raw_file_sha256(paths["v35"]),
            expected.get("expected_parent_v35_artifact_raw_file_sha256"),
        ),
        "v35_semantic_stored": (
            v35.get("artifact_sha256"),
            expected.get("expected_parent_v35_artifact_sha256"),
        ),
        "v35_semantic_recomputed": (
            canonical_json_sha256(v35_core),
            expected.get("expected_parent_v35_artifact_sha256"),
        ),
        "v35_spec": (
            v35.get("spec_sha256"),
            expected.get("expected_parent_v35_spec_sha256"),
        ),
        "v35_freeze_raw": (
            raw_file_sha256(paths["v35_freeze"]),
            expected.get("expected_parent_v35_freeze_raw_file_sha256"),
        ),
        "v35_freeze_semantic_stored": (
            v35_freeze.get("freeze_contract_sha256"),
            expected.get("expected_parent_v35_freeze_sha256"),
        ),
        "v35_freeze_semantic_recomputed": (
            canonical_json_sha256(v35_freeze_core),
            expected.get("expected_parent_v35_freeze_sha256"),
        ),
    }
    for label, (actual, wanted) in comparisons.items():
        if actual != wanted:
            errors.append(f"{label} mismatch")
    v34_boundary = v34.get("claim_boundary") or {}
    v35_boundary = v35.get("claim_boundary") or {}
    v35_decisions = v35.get("decisions") or {}
    checks = {
        "all_hashes_exact": not errors,
        "v34_zero_job_boundary": bool(
            v34_boundary.get("hardware_executable") is False
            and v34_boundary.get("qpu_submission_enabled") is False
            and v34_boundary.get("qpu_jobs_submitted") == 0
        ),
        "v35_negative_result_retained": bool(
            v35_decisions.get("pretranspilation_model_screen")
            == "REJECTED_MODEL_SCREEN"
            and v35_decisions.get("qpu_jobs_submitted") == 0
            and v35_decisions.get("quantum_advantage") == "NOT_CLAIMED"
        ),
        "v35_zero_job_boundary": bool(
            v35_boundary.get("hardware_executable") is False
            and v35_boundary.get("qpu_submission_enabled") is False
            and v35_boundary.get("qpu_jobs_submitted") == 0
            and v35_boundary.get("provider_session_opened") is False
            and v35_boundary.get("credentials_read") is False
            and v35_boundary.get("network_calls") == 0
        ),
    }
    failed = [name for name, value in checks.items() if not value]
    errors.extend(f"failed check: {name}" for name in failed)
    return {
        "checks": checks,
        "comparisons": {
            label: {"actual": actual, "expected": wanted, "valid": actual == wanted}
            for label, (actual, wanted) in comparisons.items()
        },
        "errors": errors,
        "valid": not errors and all(checks.values()),
    }


def structural_cost_attribution(
    v34_artifact: Mapping[str, Any],
    spec: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Reconstruct every V3.4 canonical CNOT total by exact integer division."""

    contract = dict(spec) if spec is not None else load_v36_spec()
    structural = contract["structural_cost_contract"]
    budget = int(contract["acceptance_contract"]["canonical_selected_model_budget_cnot"])
    ledgers = (v34_artifact.get("resource_envelopes") or {}).get("ledgers") or {}
    ledger = ledgers.get(CANONICAL_LEDGER_KEY)
    if not isinstance(ledger, Mapping):
        raise ValueError("V3.4 canonical resource ledger is absent.")
    edge_count = int(ledger.get("edge_count", -1))
    oracle_calls = int(ledger.get("oracle_calls", -1))
    per_edge_cnot = int(
        ((ledger.get("per_edge") or {}).get("ccx_7t_cost_model") or {}).get(
            "CX", -1
        )
    )
    if edge_count != int(structural["canonical_edge_count"]):
        raise ValueError("Canonical edge count mismatch.")
    if oracle_calls != int(structural["canonical_oracle_calls"]):
        raise ValueError("Canonical oracle-call count mismatch.")
    if per_edge_cnot != int(structural["per_edge_selected_model_cnot"]):
        raise ValueError("Per-edge selected-model CNOT count mismatch.")
    rows: list[dict[str, Any]] = []
    for source in sorted(ledger.get("per_seed") or [], key=lambda row: int(row["seed"])):
        seed = int(source["seed"])
        total = int(source["cnot_after_selected_ccx_model"])
        edge_subtotal = edge_count * per_edge_cnot
        oracle_subtotal = total - edge_subtotal
        quotient, remainder = divmod(oracle_subtotal, oracle_calls)
        row = {
            "seed": seed,
            "instance_id": source.get("instance_id"),
            "total_cnot": total,
            "oracle_calls": oracle_calls,
            "per_oracle_cnot": quotient,
            "oracle_cnot_subtotal": oracle_subtotal,
            "edge_count": edge_count,
            "per_edge_cnot": per_edge_cnot,
            "edge_cnot_subtotal": edge_subtotal,
            "division_remainder": remainder,
            "reconstructed_total_cnot": oracle_calls * quotient + edge_subtotal,
            "reconstruction_exact": bool(
                remainder == 0 and oracle_calls * quotient + edge_subtotal == total
            ),
            "oracle_share_of_total": oracle_subtotal / total,
        }
        row["row_sha256"] = canonical_json_sha256(row)
        rows.append(row)
    seeds = tuple(row["seed"] for row in rows)
    if seeds != EXPECTED_SEEDS:
        raise ValueError(f"Canonical seed inventory mismatch: {seeds}")
    oracle_values = [row["per_oracle_cnot"] for row in rows]
    minimum_oracle = min(oracle_values)
    maximum_oracle = max(oracle_values)
    required_calls = int(structural["required_nontrivial_oracle_calls"])
    pair_floor = required_calls * minimum_oracle
    if minimum_oracle != int(structural["v34_per_oracle_cnot_expected_min"]):
        raise ValueError("Minimum per-oracle CNOT identity mismatch.")
    if maximum_oracle != int(structural["v34_per_oracle_cnot_expected_max"]):
        raise ValueError("Maximum per-oracle CNOT identity mismatch.")
    core = {
        "canonical_ledger_key": CANONICAL_LEDGER_KEY,
        "equation": structural["equation"],
        "edge_count": edge_count,
        "oracle_calls": oracle_calls,
        "per_edge_selected_model_cnot": per_edge_cnot,
        "rows": rows,
        "summary": {
            "all_eight_equations_exact": len(rows) == 8
            and all(row["reconstruction_exact"] for row in rows),
            "canonical_total_cnot_max": max(row["total_cnot"] for row in rows),
            "canonical_total_cnot_min": min(row["total_cnot"] for row in rows),
            "per_oracle_cnot_max": maximum_oracle,
            "per_oracle_cnot_min": minimum_oracle,
            "required_nontrivial_oracle_calls": required_calls,
            "required_compute_uncompute_pair_cnot_floor": pair_floor,
            "selected_model_budget_cnot": budget,
            "pair_floor_multiple_of_budget": pair_floor / budget,
            "pair_floor_exceeds_budget": pair_floor > budget,
            "attribution_scope": (
                "Frozen V3.4 selected 7T-CCX accounting only; not a backend-native "
                "count and not a global lower bound over alternative algorithms."
            ),
        },
    }
    return {**core, "structural_manifest_sha256": canonical_json_sha256(core)}


def _constraint_rows(certificate: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    n = int(certificate["N"])
    rows: list[dict[str, Any]] = []
    for group in certificate.get("group_bands") or []:
        members = {int(index) for index in group["indices"]}
        rows.append(
            {
                "kind": "GROUP",
                "name": str(group["name"]),
                "coefficients": tuple(1 if index in members else 0 for index in range(n)),
                "lower": int(group["lower"]),
                "upper": int(group["upper"]),
            }
        )
    for factor in certificate.get("factor_bands") or []:
        coefficients = tuple(int(value) for value in factor["coefficients_int"])
        if len(coefficients) != n:
            raise ValueError("Factor coefficient width mismatch.")
        rows.append(
            {
                "kind": "FACTOR",
                "name": str(factor["name"]),
                "coefficients": coefficients,
                "lower": int(factor["lower_int"]),
                "upper": int(factor["upper_int"]),
            }
        )
    if len(rows) != 7:
        raise ValueError("Expected four group and three factor constraints.")
    return tuple(rows)


def cached_constraint_values(
    bits: Sequence[int], rows: Sequence[Mapping[str, Any]]
) -> tuple[int, ...]:
    values = tuple(int(bit) for bit in bits)
    if any(bit not in (0, 1) for bit in values):
        raise ValueError("Constraint cache input must be binary.")
    return tuple(
        sum(int(coefficient) * bit for coefficient, bit in zip(row["coefficients"], values))
        for row in rows
    )


def prospective_swap_values(
    bits: Sequence[int],
    edge: tuple[int, int],
    rows: Sequence[Mapping[str, Any]],
    cached_values: Sequence[int] | None = None,
) -> tuple[int, ...]:
    """Apply A(S_ij x)=A(x)+(x_j-x_i)(c_i-c_j) exactly."""

    values = tuple(int(bit) for bit in bits)
    i, j = (int(edge[0]), int(edge[1]))
    if i == j or i < 0 or j < 0 or i >= len(values) or j >= len(values):
        raise ValueError("Swap edge is invalid.")
    cached = (
        tuple(int(value) for value in cached_values)
        if cached_values is not None
        else cached_constraint_values(values, rows)
    )
    if len(cached) != len(rows):
        raise ValueError("Cached constraint vector length mismatch.")
    direction = values[j] - values[i]
    return tuple(
        current
        + direction
        * (int(row["coefficients"][i]) - int(row["coefficients"][j]))
        for current, row in zip(cached, rows)
    )


def values_feasible(
    values: Sequence[int], rows: Sequence[Mapping[str, Any]]
) -> bool:
    if len(values) != len(rows):
        raise ValueError("Constraint value vector length mismatch.")
    return all(
        int(row["lower"]) <= int(value) <= int(row["upper"])
        for value, row in zip(values, rows)
    )


def guard_scope_truth_table() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for current_feasible in (False, True):
        for swapped_feasible in (False, True):
            for different in (False, True):
                dual = current_feasible and swapped_feasible and different
                feasible_support = swapped_feasible and different
                rows.append(
                    {
                        "current_feasible": current_feasible,
                        "swapped_feasible": swapped_feasible,
                        "different_bits": different,
                        "dual_guard_active": dual,
                        "single_guard_active": feasible_support,
                        "equal": dual == feasible_support,
                    }
                )
    feasible_rows = [row for row in rows if row["current_feasible"]]
    outside_rows = [row for row in rows if not row["current_feasible"]]
    return {
        "rows": rows,
        "total_cases": len(rows),
        "feasible_support_cases": len(feasible_rows),
        "equal_on_all_feasible_support_cases": all(row["equal"] for row in feasible_rows),
        "different_outside_feasible_support": any(not row["equal"] for row in outside_rows),
        "semantic_classification": SEMANTICS_FEASIBLE,
    }


def incremental_exposure_audit(
    v31_artifact: Mapping[str, Any],
    v34_spec: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate swap-delta arithmetic for 8×780×7 frozen rows."""

    witnesses = (
        v34_spec.get("authenticated_v33_witnesses") or {}
    ).get("bits_by_seed") or {}
    certificates = {
        int(row["seed"]): row for row in v31_artifact.get("seed_certificates") or []
    }
    result_rows: list[dict[str, Any]] = []
    total_constraint_cases = 0
    total_swap_cases = 0
    all_exact = True
    all_predicates_equal = True
    all_exact_k = True
    all_witnesses_feasible = True
    affected_histogram: dict[int, int] = {}
    for seed in EXPECTED_SEEDS:
        certificate = certificates.get(seed)
        bits_raw = witnesses.get(str(seed))
        if not isinstance(certificate, Mapping) or not isinstance(bits_raw, list):
            raise ValueError(f"Missing frozen certificate or witness for seed {seed}.")
        bits = tuple(int(bit) for bit in bits_raw)
        n = int(certificate["N"])
        k = int(certificate["K"])
        if len(bits) != n or any(bit not in (0, 1) for bit in bits):
            raise ValueError(f"Invalid witness bits for seed {seed}.")
        rows = _constraint_rows(certificate)
        cached = cached_constraint_values(bits, rows)
        witness_feasible = sum(bits) == k and values_feasible(cached, rows)
        all_witnesses_feasible = all_witnesses_feasible and witness_feasible
        seed_exact = True
        seed_predicate = True
        seed_exact_k = True
        seed_affected_total = 0
        for i in range(n):
            for j in range(i + 1, n):
                prospective = prospective_swap_values(bits, (i, j), rows, cached)
                swapped = list(bits)
                swapped[i], swapped[j] = swapped[j], swapped[i]
                direct = cached_constraint_values(swapped, rows)
                row_exact = prospective == direct
                predicate_equal = values_feasible(prospective, rows) == values_feasible(
                    direct, rows
                )
                exact_k = sum(swapped) == k
                affected = sum(
                    1 for left, right in zip(cached, prospective) if left != right
                )
                affected_histogram[affected] = affected_histogram.get(affected, 0) + 1
                seed_affected_total += affected
                seed_exact = seed_exact and row_exact
                seed_predicate = seed_predicate and predicate_equal
                seed_exact_k = seed_exact_k and exact_k
                total_swap_cases += 1
                total_constraint_cases += len(rows)
        all_exact = all_exact and seed_exact
        all_predicates_equal = all_predicates_equal and seed_predicate
        all_exact_k = all_exact_k and seed_exact_k
        result_rows.append(
            {
                "seed": seed,
                "swap_cases": n * (n - 1) // 2,
                "constraint_row_cases": (n * (n - 1) // 2) * len(rows),
                "delta_arithmetic_exact": seed_exact,
                "prospective_predicate_exact": seed_predicate,
                "exact_k_preserved": seed_exact_k,
                "witness_feasible": witness_feasible,
                "affected_constraint_row_total": seed_affected_total,
            }
        )
    core = {
        "arithmetic_identity": "A_r(S_ij x) = A_r(x) + (x_j - x_i)(c_ri - c_rj)",
        "rows": result_rows,
        "total_swap_cases": total_swap_cases,
        "total_constraint_row_cases": total_constraint_cases,
        "affected_constraint_count_histogram": {
            str(key): value for key, value in sorted(affected_histogram.items())
        },
        "checks": {
            "all_eight_authenticated_witnesses_feasible": all_witnesses_feasible,
            "all_6240_swap_cases_exact": total_swap_cases == 6_240 and all_exact,
            "all_43680_constraint_rows_exact": total_constraint_cases == 43_680
            and all_exact,
            "prospective_feasibility_equals_full_recompute": all_predicates_equal,
            "exact_k_preserved_by_every_swap": all_exact_k,
        },
        "reversible_compiler_status": "BLOCKED_PENDING_REVERSIBLE_COMPILER",
        "semantic_classification": SEMANTICS_UNPROVEN,
        "claim_boundary": (
            "Classical integer delta equivalence only. No clean-ancilla reversible "
            "gate IR, CNOT count, depth, or coherent cache update is claimed."
        ),
    }
    return {
        **core,
        "passed": all(core["checks"].values()),
        "incremental_audit_sha256": canonical_json_sha256(core),
    }


def rewrite_admission(
    attribution: Mapping[str, Any],
    incremental: Mapping[str, Any],
    guard_scope: Mapping[str, Any],
    spec: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    contract = dict(spec) if spec is not None else load_v36_spec()
    lanes_spec = contract["lane_contracts"]
    summary = attribution["summary"]
    budget = int(summary["selected_model_budget_cnot"])
    canonical_max = int(summary["canonical_total_cnot_max"])
    pair_floor = int(summary["required_compute_uncompute_pair_cnot_floor"])
    lanes = {
        "FROZEN_V34_IDENTITY": {
            **lanes_spec["FROZEN_V34_IDENTITY"],
            "admission_decision": "REJECTED",
            "selected_model_cnot": canonical_max,
            "budget_cnot": budget,
        },
        "TOPOLOGY_ONLY_PRESERVE_OPERATOR": {
            **lanes_spec["TOPOLOGY_ONLY_PRESERVE_OPERATOR"],
            "admission_decision": "REJECTED",
            "selected_model_cnot": canonical_max,
            "budget_cnot": budget,
            "reason": (
                "Preserving the exact ordered V3.4 partial-mixer product permits "
                "no edge deletion; the frozen count is unchanged."
            ),
        },
        "TOPOLOGY_ONLY_PRUNED": {
            **lanes_spec["TOPOLOGY_ONLY_PRUNED"],
            "admission_decision": "REJECTED",
            "conservative_nontrivial_pair_floor_cnot": pair_floor,
            "budget_cnot": budget,
            "reason": (
                "Deleting ordered mixer edges changes semantics, and even the "
                "two-call oracle compute/uncompute floor exceeds the budget."
            ),
        },
        "FEASIBLE_SUPPORT_SINGLE_GUARD": {
            **lanes_spec["FEASIBLE_SUPPORT_SINGLE_GUARD"],
            "admission_decision": "REJECTED",
            "conservative_nontrivial_pair_floor_cnot": pair_floor,
            "budget_cnot": budget,
            "truth_table_pass": bool(
                guard_scope.get("equal_on_all_feasible_support_cases")
                and guard_scope.get("different_outside_feasible_support")
            ),
        },
        "INCREMENTAL_EXPOSURE_GUARD": {
            **lanes_spec["INCREMENTAL_EXPOSURE_GUARD"],
            "admission_decision": "BLOCKED",
            "classical_delta_audit_pass": bool(incremental.get("passed")),
            "selected_model_cnot": "NOT_ESTIMATED",
            "required_next_evidence": [
                "REVERSIBLE_GATE_IR",
                "CLEAN_ANCILLA_PROOF",
                "COHERENT_CACHE_UPDATE_PROOF",
                "FULL_DIFFERENTIAL_MIXER_ACTION",
                "SELECTED_MODEL_RESOURCE_LEDGER",
            ],
        },
        "BLOCK_COORDINATE": {
            **lanes_spec["BLOCK_COORDINATE"],
            "admission_decision": "SEPARATE_PROTOCOL_REQUIRED",
            "selected_model_cnot": "NOT_COMPARABLE",
            "inherit_v34_equivalence": False,
        },
        "BACKEND_NATIVE": {
            **lanes_spec["BACKEND_NATIVE"],
            "admission_decision": "NOT_RUN",
            "provider_calls": 0,
            "qpu_jobs_submitted": 0,
        },
    }
    core = {
        "budget_cnot": budget,
        "lanes": lanes,
        "decisions": {
            "overall": "ARCHITECTURE_REWRITE_REQUIRED",
            "frozen_v34_architecture": "REJECTED_SELECTED_MODEL_BUDGET",
            "topology_only": "REJECTED_WITHIN_FROZEN_V34_ARCHITECTURE",
            "incremental_exposure_guard": "BLOCKED_PENDING_REVERSIBLE_COMPILER",
            "block_coordinate": "CHANGED_SEMANTICS",
            "backend_native": "NOT_RUN_PROVIDER_FREE_PHASE",
            "global_impossibility": "NOT_CLAIMED",
            "next_falsifiable_gate": "CLEAN_REVERSIBLE_INCREMENTAL_EXPOSURE_COMPILER",
        },
    }
    return {**core, "rewrite_manifest_sha256": canonical_json_sha256(core)}


def build_v36_artifact(**path_overrides: Any) -> dict[str, Any]:
    spec = load_v36_spec()
    parents = authenticate_parent_chain(spec, **path_overrides)
    if not parents.get("valid"):
        raise ValueError("V3.6 parent chain failed: " + "; ".join(parents.get("errors") or []))
    _, payloads = _parent_payloads(**path_overrides)
    attribution = structural_cost_attribution(payloads["v34"], spec)
    guard = guard_scope_truth_table()
    incremental = incremental_exposure_audit(payloads["v31"], payloads["v34_spec"])
    rewrites = rewrite_admission(attribution, incremental, guard, spec)
    parent_contract = spec["parent_contract"]
    core = {
        "artifact_version": ARTIFACT_VERSION,
        "v36_version": V36_VERSION,
        "spec_sha256": spec["v36_spec_sha256"],
        "research_classification": "RESEARCH_ONLY",
        "parents": {
            "v31_raw_file_sha256": parent_contract["expected_parent_v31_raw_file_sha256"],
            "v34_artifact_sha256": parent_contract["expected_parent_v34_artifact_sha256"],
            "v34_artifact_raw_file_sha256": parent_contract[
                "expected_parent_v34_artifact_raw_file_sha256"
            ],
            "v35_artifact_sha256": parent_contract["expected_parent_v35_artifact_sha256"],
            "v35_artifact_raw_file_sha256": parent_contract[
                "expected_parent_v35_artifact_raw_file_sha256"
            ],
            "v35_freeze_sha256": parent_contract["expected_parent_v35_freeze_sha256"],
        },
        "parent_authentication": parents,
        "structural_cost_attribution": attribution,
        "guard_scope_proof": guard,
        "incremental_exposure_audit": incremental,
        "rewrite_admission": rewrites,
        "decisions": rewrites["decisions"],
        "claim_boundary": {
            "provider_sdk_imported": False,
            "provider_credentials_read": False,
            "provider_calls": 0,
            "backend_transpilation": "NOT_RUN",
            "hardware_executable": False,
            "qpu_submission_enabled": False,
            "qpu_jobs_submitted": 0,
            "optimization_performance": "NOT_TESTED",
            "global_impossibility": "NOT_CLAIMED",
            "quantum_advantage": "NOT_CLAIMED",
        },
    }
    return {**core, "artifact_sha256": canonical_json_sha256(core)}


def validate_v36_artifact(payload: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(payload, Mapping):
        return {"valid": False, "errors": ["Artifact must be an object."]}
    core = {key: value for key, value in payload.items() if key != "artifact_sha256"}
    try:
        computed = canonical_json_sha256(core)
    except (TypeError, ValueError, OverflowError) as exc:
        return {"valid": False, "errors": [str(exc)]}
    if payload.get("artifact_sha256") != computed:
        errors.append("Artifact SHA-256 mismatch.")
    if payload.get("artifact_version") != ARTIFACT_VERSION:
        errors.append("Artifact version mismatch.")
    if payload.get("research_classification") != "RESEARCH_ONLY":
        errors.append("Research classification violated.")
    attribution = payload.get("structural_cost_attribution") or {}
    summary = attribution.get("summary") or {}
    rewrites = payload.get("rewrite_admission") or {}
    lanes = rewrites.get("lanes") or {}
    decisions = payload.get("decisions") or {}
    incremental = payload.get("incremental_exposure_audit") or {}
    boundary = payload.get("claim_boundary") or {}
    if summary.get("per_oracle_cnot_min") != 92_095_707:
        errors.append("Minimum oracle CNOT identity mismatch.")
    if summary.get("per_oracle_cnot_max") != 95_650_135:
        errors.append("Maximum oracle CNOT identity mismatch.")
    if summary.get("required_compute_uncompute_pair_cnot_floor") != 184_191_414:
        errors.append("Compute/uncompute pair floor mismatch.")
    if summary.get("pair_floor_exceeds_budget") is not True:
        errors.append("Pair-floor rejection is absent.")
    if incremental.get("passed") is not True:
        errors.append("Incremental delta audit is not passing.")
    if incremental.get("total_constraint_row_cases") != 43_680:
        errors.append("Incremental delta scope mismatch.")
    if (lanes.get("TOPOLOGY_ONLY_PRUNED") or {}).get("semantic_classification") != SEMANTICS_CHANGED:
        errors.append("Pruned topology semantic boundary missing.")
    if (lanes.get("BLOCK_COORDINATE") or {}).get("semantic_classification") != SEMANTICS_CHANGED:
        errors.append("Block-coordinate semantic boundary missing.")
    if decisions.get("topology_only") != "REJECTED_WITHIN_FROZEN_V34_ARCHITECTURE":
        errors.append("Topology-only negative decision missing.")
    if decisions.get("overall") != "ARCHITECTURE_REWRITE_REQUIRED":
        errors.append("Overall architecture-rewrite decision missing.")
    if decisions.get("global_impossibility") != "NOT_CLAIMED":
        errors.append("Global-impossibility claim boundary violated.")
    if boundary.get("provider_sdk_imported") is not False:
        errors.append("Provider SDK boundary violated.")
    if boundary.get("provider_credentials_read") is not False:
        errors.append("Credential boundary violated.")
    if boundary.get("provider_calls") != 0:
        errors.append("Provider-call boundary violated.")
    if boundary.get("qpu_submission_enabled") is not False:
        errors.append("Submission boundary violated.")
    if boundary.get("qpu_jobs_submitted") != 0:
        errors.append("QPU job boundary violated.")
    if boundary.get("quantum_advantage") != "NOT_CLAIMED":
        errors.append("Advantage boundary violated.")
    return {
        "artifact_sha256_computed": computed,
        "artifact_sha256_stored": payload.get("artifact_sha256"),
        "errors": errors,
        "valid": not errors,
    }


def default_v36_artifact_path() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "outputs"
        / "quantum_phase3"
        / "v36_reduction"
        / DEFAULT_ARTIFACT_NAME
    )


def load_v36_artifact(
    path: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load the sealed artifact and return its fail-closed integrity report."""

    target = Path(path) if path is not None else default_v36_artifact_path()
    payload = _read_object(target)
    return payload, validate_v36_artifact(payload)


def seal_v36_artifact(
    path: str | Path | None = None,
    **path_overrides: Any,
) -> dict[str, Any]:
    """Create the deterministic artifact once, or accept byte-identical content."""

    target = Path(path) if path is not None else default_v36_artifact_path()
    artifact = build_v36_artifact(**path_overrides)
    report = validate_v36_artifact(artifact)
    if not report["valid"]:
        raise ValueError("Refusing to seal invalid V3.6 artifact: " + "; ".join(report["errors"]))
    encoded = json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != encoded:
            raise FileExistsError(f"Existing V3.6 seal differs: {target}")
        return {"artifact": artifact, "created": False, "path": str(target)}
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            target.unlink()
        except OSError:
            pass
        raise
    return {"artifact": artifact, "created": True, "path": str(target)}


__all__ = [
    "ARTIFACT_VERSION",
    "CANONICAL_LEDGER_KEY",
    "DEFAULT_ARTIFACT_NAME",
    "EXPECTED_SEEDS",
    "SEMANTICS_CHANGED",
    "SEMANTICS_FEASIBLE",
    "SEMANTICS_FULL",
    "SEMANTICS_UNPROVEN",
    "V36_VERSION",
    "authenticate_parent_chain",
    "build_v36_artifact",
    "cached_constraint_values",
    "canonical_json_bytes",
    "canonical_json_sha256",
    "default_v36_artifact_path",
    "guard_scope_truth_table",
    "incremental_exposure_audit",
    "load_v36_artifact",
    "load_v36_spec",
    "prospective_swap_values",
    "raw_file_sha256",
    "rewrite_admission",
    "seal_v36_artifact",
    "source_sha256",
    "structural_cost_attribution",
    "validate_v36_artifact",
    "values_feasible",
]
