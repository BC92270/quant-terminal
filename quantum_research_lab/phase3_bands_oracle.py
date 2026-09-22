from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .phase2_qhardness import build_hard_instance, is_feasible

ORACLE_VERSION = "PHASE III · EXACT REVERSIBLE BANDS ORACLE · V1"
ORACLE_SPEC_VERSION = "BANDS FIXED-POINT FIDELITY + REVERSIBLE ORACLE SPEC · V1"
PHASE2_PROTOCOL_SHA = "8E5EF191FAE97A75"
PHASE2_EXECUTION_SPEC_SHA = "40D3225B0AFC86BC01DD"
PHASE3_PREPARATION_SPEC_SHA = "CDC693C22A3838B0B3C1"
SEALED_SEEDS = (1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807)
FIXED_POINT_LADDER = (8, 12, 16)
REAL_FEASIBILITY_TOL = 1e-8

ORACLE_SPEC: dict[str, Any] = {
    "oracle_version": ORACLE_VERSION,
    "oracle_spec_version": ORACLE_SPEC_VERSION,
    "phase2_protocol_sha": PHASE2_PROTOCOL_SHA,
    "phase2_execution_spec_sha": PHASE2_EXECUTION_SPEC_SHA,
    "phase3_preparation_spec_sha": PHASE3_PREPARATION_SPEC_SHA,
    "eligible_regime": "BANDS",
    "candidate_family": {"N": 40, "seeds": list(SEALED_SEEDS)},
    "fixed_point_ladder_bits": list(FIXED_POINT_LADDER),
    "selection_rule": "Use the lowest fixed-point precision in 8 -> 12 -> 16 that receives an exact family-wide MILP mismatch proof; if none passes, remain blocked.",
    "quantization_rule": "Signed round-half-away-from-zero of coefficient*2^b and band-bound*2^b; integer comparisons are exact after quantization.",
    "fidelity_contract": {
        "classical_reference": "Phase-II BANDS real-valued constraints with feasibility tolerance 1e-8",
        "false_positive": "quantized-oracle feasible AND real-valued Phase-II infeasible",
        "false_negative": "real-valued Phase-II feasible AND quantized-oracle infeasible",
        "proof_method": "MILP extremum search over the full binary exact-K/group-band state space; no random sampling can promote fidelity.",
        "promotion_rule": "Every seed must have zero false-positive and zero false-negative witnesses, witness consistency PASS, and all proof MILPs certified.",
        "proof_milp_time_limit_seconds_per_extremum": 30.0,
    },
    "reversible_oracle_contract": {
        "cardinality": "Preserved by the number-preserving XY mixer; no cardinality penalty is introduced.",
        "group_counts": "Controlled reversible integer additions into exact count registers, lower/upper comparisons, flag aggregation, then uncompute.",
        "factor_exposures": "Controlled reversible signed integer additions of sealed fixed-point coefficients, lower/upper integer comparisons, flag aggregation, then uncompute.",
        "clean_ancilla": True,
        "phase2_objective_unchanged": True,
        "arbitrary_penalty_substitution": False,
    },
}


def _stable_json(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _sha(payload: Any, length: int = 20) -> str:
    return hashlib.sha256(_stable_json(payload)).hexdigest()[: int(length)].upper()


ORACLE_SPEC_SHA = _sha(ORACLE_SPEC, 20)


def oracle_spec_payload() -> dict[str, Any]:
    return {**ORACLE_SPEC, "oracle_spec_sha": ORACLE_SPEC_SHA}


def default_oracle_root() -> Path:
    return Path("outputs/quantum_phase3/bands_oracle")


def _round_half_away_array(values: np.ndarray | list[float] | float, scale: int) -> np.ndarray:
    arr = np.asarray(values, dtype=float) * int(scale)
    return np.where(arr >= 0.0, np.floor(arr + 0.5), np.ceil(arr - 0.5)).astype(np.int64)


def _signed_width(lo: int, hi: int) -> int:
    lo = int(lo); hi = int(hi)
    width = 2
    while lo < -(1 << (width - 1)) or hi > (1 << (width - 1)) - 1:
        width += 1
    return int(width)


def _fixed_point_factor_spec(coefficients: np.ndarray, lower: float, upper: float, k: int, bits: int) -> dict[str, Any]:
    scale = 1 << int(bits)
    a = np.asarray(coefficients, dtype=float)
    qa = _round_half_away_array(a, scale)
    qlo = int(_round_half_away_array([float(lower)], scale)[0])
    qhi = int(_round_half_away_array([float(upper)], scale)[0])
    # Safe exact-K accumulator envelope; group bands can only narrow it.
    sorted_q = np.sort(qa)
    min_sum = int(np.sum(sorted_q[: int(k)]))
    max_sum = int(np.sum(sorted_q[-int(k):]))
    return {
        "bits": int(bits),
        "scale": int(scale),
        "coefficients_int": [int(x) for x in qa.tolist()],
        "lower_int": qlo,
        "upper_int": qhi,
        "accumulator_min": min_sum,
        "accumulator_max": max_sum,
        "accumulator_signed_bits": _signed_width(min_sum, max_sum),
        "max_coefficient_abs_error": float(np.max(np.abs(a - qa.astype(float) / scale))) if len(a) else 0.0,
        "lower_abs_error": float(abs(float(lower) - qlo / scale)),
        "upper_abs_error": float(abs(float(upper) - qhi / scale)),
    }


def seed_fixed_point_spec(n: int, seed: int, bits: int) -> dict[str, Any]:
    inst = build_hard_instance(int(n), "BANDS", int(seed))
    factor_specs = []
    for band in inst.factor_bands:
        fs = _fixed_point_factor_spec(np.asarray(band["coefficients"], dtype=float), float(band["lower"]), float(band["upper"]), inst.k, int(bits))
        fs["name"] = str(band["name"])
        factor_specs.append(fs)
    group_specs = []
    for band in inst.group_bands:
        size = len(band["indices"])
        group_specs.append({
            "name": str(band["name"]),
            "indices": [int(x) for x in band["indices"]],
            "lower": int(band["lower"]),
            "upper": int(band["upper"]),
            "counter_bits": int(max(1, math.ceil(math.log2(size + 1)))),
        })
    return {
        "instance_id": inst.instance_id,
        "N": int(inst.n),
        "K": int(inst.k),
        "seed": int(seed),
        "bits": int(bits),
        "quantization_rule": ORACLE_SPEC["quantization_rule"],
        "group_bands": group_specs,
        "factor_bands": factor_specs,
    }


def quantized_oracle_feasible(x: np.ndarray, inst: Any, bits: int) -> bool:
    xx = (np.asarray(x, dtype=float).reshape(-1) > 0.5).astype(np.int64)
    if len(xx) != int(inst.n) or int(np.sum(xx)) != int(inst.k):
        return False
    for band in inst.group_bands:
        val = int(np.sum(xx[np.asarray(band["indices"], dtype=int)]))
        if val < int(band["lower"]) or val > int(band["upper"]):
            return False
    scale = 1 << int(bits)
    for band in inst.factor_bands:
        qa = _round_half_away_array(np.asarray(band["coefficients"], dtype=float), scale)
        qlo = int(_round_half_away_array([float(band["lower"])], scale)[0])
        qhi = int(_round_half_away_array([float(band["upper"])], scale)[0])
        val = int(qa @ xx)
        if val < qlo or val > qhi:
            return False
    return True


def _proof_extreme(inst: Any, bits: int, domain: str, factor_idx: int, direction: str, time_limit_s: float) -> dict[str, Any]:
    try:
        from scipy.optimize import Bounds, LinearConstraint, milp
    except Exception as exc:
        return {"certified": False, "status": "SOLVER UNAVAILABLE", "reason": str(exc)}

    n = int(inst.n)
    scale = 1 << int(bits)
    rows: list[np.ndarray] = []
    lbs: list[float] = []
    ubs: list[float] = []
    rows.append(np.ones(n)); lbs.append(float(inst.k)); ubs.append(float(inst.k))
    for band in inst.group_bands:
        row = np.zeros(n, dtype=float); row[np.asarray(band["indices"], dtype=int)] = 1.0
        rows.append(row); lbs.append(float(band["lower"])); ubs.append(float(band["upper"]))

    quantized = []
    for band in inst.factor_bands:
        a = np.asarray(band["coefficients"], dtype=float)
        qa = _round_half_away_array(a, scale)
        qlo = int(_round_half_away_array([float(band["lower"])], scale)[0])
        qhi = int(_round_half_away_array([float(band["upper"])], scale)[0])
        quantized.append((a, qa, float(band["lower"]), float(band["upper"]), qlo, qhi))

    if str(domain).upper() == "QUANTIZED":
        for _a, qa, _lo, _hi, qlo, qhi in quantized:
            rows.append(qa.astype(float)); lbs.append(float(qlo)); ubs.append(float(qhi))
        objective = quantized[int(factor_idx)][0].astype(float)
    elif str(domain).upper() == "REAL":
        for a, _qa, lo, hi, _qlo, _qhi in quantized:
            rows.append(a.astype(float)); lbs.append(float(lo) - REAL_FEASIBILITY_TOL); ubs.append(float(hi) + REAL_FEASIBILITY_TOL)
        objective = quantized[int(factor_idx)][1].astype(float)
    else:
        raise ValueError("domain must be REAL or QUANTIZED")

    sign = 1.0 if str(direction).upper() == "MIN" else -1.0
    c = sign * np.asarray(objective, dtype=float)
    constraint = LinearConstraint(np.vstack(rows), np.asarray(lbs, dtype=float), np.asarray(ubs, dtype=float))
    try:
        res = milp(
            c=c,
            integrality=np.ones(n, dtype=int),
            bounds=Bounds(np.zeros(n), np.ones(n)),
            constraints=constraint,
            options={"time_limit": max(float(time_limit_s), 0.1), "mip_rel_gap": 0.0, "presolve": True},
        )
    except Exception as exc:
        return {"certified": False, "status": "SOLVER ERROR", "reason": f"{type(exc).__name__}: {exc}"}
    status_code = int(getattr(res, "status", -999))
    if status_code == 2:  # proven infeasible domain
        return {"certified": True, "status": "DOMAIN INFEASIBLE", "value": None, "x": None, "solver_status": status_code}
    if getattr(res, "x", None) is None:
        return {"certified": False, "status": "NO CERTIFIED SOLUTION", "reason": str(getattr(res, "message", "unknown")), "solver_status": status_code}
    x = (np.asarray(res.x, dtype=float) > 0.5).astype(int)
    value = float(np.asarray(objective, dtype=float) @ x)
    certified = bool(status_code == 0 and bool(getattr(res, "success", False)))
    return {
        "certified": certified,
        "status": "OPTIMAL" if certified else "UNCERTIFIED INCUMBENT",
        "value": value,
        "x": [int(v) for v in x.tolist()],
        "solver_status": status_code,
        "solver_message": str(getattr(res, "message", "")),
    }


def seed_fidelity_audit(n: int, seed: int, bits: int, *, time_limit_s: float = 8.0) -> dict[str, Any]:
    inst = build_hard_instance(int(n), "BANDS", int(seed))
    fixed = seed_fixed_point_spec(int(n), int(seed), int(bits))
    witness_real = bool(is_feasible(inst.witness.astype(float), inst))
    witness_quant = bool(quantized_oracle_feasible(inst.witness.astype(float), inst, int(bits)))
    proof_rows: list[dict[str, Any]] = []
    mismatch_witnesses: list[dict[str, Any]] = []
    any_uncertified = False

    if not witness_real or not witness_quant:
        return {
            "oracle_spec_sha": ORACLE_SPEC_SHA, "instance_id": inst.instance_id,
            "N": int(inst.n), "K": int(inst.k), "seed": int(seed), "bits": int(bits),
            "status": "FAIL · WITNESS CLASSIFICATION MISMATCH",
            "witness_real_feasible": witness_real, "witness_quantized_feasible": witness_quant,
            "false_positive_found": bool(witness_quant and not witness_real),
            "false_negative_found": bool(witness_real and not witness_quant),
            "proof_milps_certified": True, "proof_rows": [],
            "mismatch_witnesses": [{"type": "WITNESS CLASSIFICATION MISMATCH", "x": [int(v) for v in inst.witness.tolist()]}],
            "fixed_point_spec": fixed, "audited_utc": datetime.now(timezone.utc).isoformat(),
        }

    def _return_mismatch(kind: str, band: dict[str, Any], solve: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
        mismatch_witnesses.append({"factor": str(band["name"]), "type": kind, "x": solve.get("x")})
        return {
            "oracle_spec_sha": ORACLE_SPEC_SHA, "instance_id": inst.instance_id,
            "N": int(inst.n), "K": int(inst.k), "seed": int(seed), "bits": int(bits),
            "status": "FAIL · FEASIBILITY MISMATCH FOUND",
            "witness_real_feasible": witness_real, "witness_quantized_feasible": witness_quant,
            "false_positive_found": kind.startswith("FALSE POSITIVE"),
            "false_negative_found": kind.startswith("FALSE NEGATIVE"),
            "proof_milps_certified": True, "proof_rows": rows,
            "mismatch_witnesses": mismatch_witnesses,
            "fixed_point_spec": fixed, "audited_utc": datetime.now(timezone.utc).isoformat(),
        }

    for fidx, band in enumerate(inst.factor_bands):
        lo = float(band["lower"]); hi = float(band["upper"])
        qband = fixed["factor_bands"][fidx]
        qlo = int(qband["lower_int"]); qhi = int(qband["upper_int"])
        row: dict[str, Any] = {"Factor": str(band["name"]), "Real lower": lo, "Real upper": hi, "Quant lower": qlo, "Quant upper": qhi}

        qmin_real = _proof_extreme(inst, bits, "QUANTIZED", fidx, "MIN", time_limit_s)
        row["Quant-feasible min real"] = qmin_real.get("value"); row["QMIN certified"] = bool(qmin_real.get("certified"))
        if qmin_real.get("certified") and qmin_real.get("value") is not None and float(qmin_real["value"]) < lo - REAL_FEASIBILITY_TOL:
            row["FP lower"] = True; proof_rows.append(row); return _return_mismatch("FALSE POSITIVE · LOWER", band, qmin_real, proof_rows)
        any_uncertified = any_uncertified or not bool(qmin_real.get("certified"))

        qmax_real = _proof_extreme(inst, bits, "QUANTIZED", fidx, "MAX", time_limit_s)
        row["Quant-feasible max real"] = qmax_real.get("value"); row["QMAX certified"] = bool(qmax_real.get("certified"))
        if qmax_real.get("certified") and qmax_real.get("value") is not None and float(qmax_real["value"]) > hi + REAL_FEASIBILITY_TOL:
            row["FP upper"] = True; proof_rows.append(row); return _return_mismatch("FALSE POSITIVE · UPPER", band, qmax_real, proof_rows)
        any_uncertified = any_uncertified or not bool(qmax_real.get("certified"))

        rmin_quant = _proof_extreme(inst, bits, "REAL", fidx, "MIN", time_limit_s)
        row["Real-feasible min quant"] = rmin_quant.get("value"); row["RMIN certified"] = bool(rmin_quant.get("certified"))
        if rmin_quant.get("certified") and rmin_quant.get("value") is not None and float(rmin_quant["value"]) < qlo:
            row["FN lower"] = True; proof_rows.append(row); return _return_mismatch("FALSE NEGATIVE · LOWER", band, rmin_quant, proof_rows)
        any_uncertified = any_uncertified or not bool(rmin_quant.get("certified"))

        rmax_quant = _proof_extreme(inst, bits, "REAL", fidx, "MAX", time_limit_s)
        row["Real-feasible max quant"] = rmax_quant.get("value"); row["RMAX certified"] = bool(rmax_quant.get("certified"))
        if rmax_quant.get("certified") and rmax_quant.get("value") is not None and float(rmax_quant["value"]) > qhi:
            row["FN upper"] = True; proof_rows.append(row); return _return_mismatch("FALSE NEGATIVE · UPPER", band, rmax_quant, proof_rows)
        any_uncertified = any_uncertified or not bool(rmax_quant.get("certified"))
        row.setdefault("FP lower", False); row.setdefault("FP upper", False); row.setdefault("FN lower", False); row.setdefault("FN upper", False)
        row["Proof certified"] = bool(row.get("QMIN certified") and row.get("QMAX certified") and row.get("RMIN certified") and row.get("RMAX certified"))
        proof_rows.append(row)

    status = "INDETERMINATE · PROOF MILP NOT CERTIFIED" if any_uncertified else "EXACT FIDELITY PASS"
    return {
        "oracle_spec_sha": ORACLE_SPEC_SHA, "instance_id": inst.instance_id,
        "N": int(inst.n), "K": int(inst.k), "seed": int(seed), "bits": int(bits),
        "status": status,
        "witness_real_feasible": witness_real, "witness_quantized_feasible": witness_quant,
        "false_positive_found": False, "false_negative_found": False,
        "proof_milps_certified": bool(not any_uncertified), "proof_rows": proof_rows,
        "mismatch_witnesses": mismatch_witnesses,
        "fixed_point_spec": fixed, "audited_utc": datetime.now(timezone.utc).isoformat(),
    }

def _audit_file(root: Path, n: int, bits: int, seed: int) -> Path:
    return root / f"N{int(n)}_BANDS" / f"bits_{int(bits)}" / f"seed_{int(seed)}.json"


def load_seed_audit(root: str | Path, n: int, bits: int, seed: int) -> dict[str, Any] | None:
    path = _audit_file(Path(root), n, bits, seed)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return None
    if payload.get("oracle_spec_sha") != ORACLE_SPEC_SHA:
        return None
    return payload


def run_seed_audit_checkpointed(root: str | Path, n: int, bits: int, seed: int, *, time_limit_s: float = 8.0) -> dict[str, Any]:
    root = Path(root)
    existing = load_seed_audit(root, n, bits, seed)
    if existing is not None:
        return existing
    payload = seed_fidelity_audit(n, seed, bits, time_limit_s=time_limit_s)
    path = _audit_file(root, n, bits, seed); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return payload


def family_audit_summary(root: str | Path, n: int, bits: int, seeds: tuple[int, ...] = SEALED_SEEDS) -> dict[str, Any]:
    root = Path(root); audits = [load_seed_audit(root, n, bits, int(seed)) for seed in seeds]
    completed = [a for a in audits if a is not None]
    rows = []
    for seed, audit in zip(seeds, audits):
        rows.append({
            "Seed": int(seed),
            "Status": str(audit.get("status")) if audit else "PENDING",
            "False positive": bool(audit.get("false_positive_found")) if audit else None,
            "False negative": bool(audit.get("false_negative_found")) if audit else None,
            "Proof certified": bool(audit.get("proof_milps_certified")) if audit else None,
            "Witness match": bool(audit.get("witness_real_feasible") and audit.get("witness_quantized_feasible")) if audit else None,
        })
    all_complete = len(completed) == len(seeds)
    any_fail = bool(any(str(a.get("status", "")).startswith("FAIL") for a in completed))
    exact = bool(all_complete and all(a.get("status") == "EXACT FIDELITY PASS" for a in completed))
    indeterminate = bool(any(str(a.get("status", "")).startswith("INDETERMINATE") for a in completed))
    if exact:
        status = "EXACT FAMILY FIDELITY PASS"
    elif any_fail:
        status = "FAMILY FIDELITY FAIL · CERTIFIED COUNTEREXAMPLE"
    elif indeterminate:
        status = "INDETERMINATE · PROOF INCOMPLETE"
    elif not all_complete:
        status = f"AUDIT IN PROGRESS · {len(completed)}/{len(seeds)}"
    else:
        status = "FAMILY FIDELITY FAIL"
    return {"N": int(n), "bits": int(bits), "status": status, "exact": exact, "completed": len(completed), "expected": len(seeds), "table": pd.DataFrame(rows), "audits": completed}


def run_family_ladder(root: str | Path, n: int = 40, *, time_limit_s: float = 30.0, stop_on_exact: bool = True) -> dict[str, Any]:
    root = Path(root); ladder = []
    selected_bits = None
    terminal_status = "NO EXACT PRECISION IN SEALED LADDER"
    for bits in FIXED_POINT_LADDER:
        early_fail = False
        for seed in SEALED_SEEDS:
            audit = run_seed_audit_checkpointed(root, int(n), int(bits), int(seed), time_limit_s=time_limit_s)
            if str(audit.get("status", "")).startswith("FAIL"):
                early_fail = True
                break
            if str(audit.get("status", "")).startswith("INDETERMINATE"):
                summary = family_audit_summary(root, int(n), int(bits)); ladder.append(summary)
                terminal_status = f"INDETERMINATE AT {int(bits)} BITS · PROOF MUST COMPLETE BEFORE HIGHER PRECISION CAN BE CONSIDERED"
                return {"oracle_spec_sha": ORACLE_SPEC_SHA, "N": int(n), "selected_bits": None, "status": terminal_status, "ladder": ladder}
        summary = family_audit_summary(root, int(n), int(bits)); ladder.append(summary)
        if summary["exact"] and selected_bits is None:
            selected_bits = int(bits); terminal_status = "EXACT PRECISION FOUND"
            if stop_on_exact:
                break
        if early_fail:
            continue
    return {"oracle_spec_sha": ORACLE_SPEC_SHA, "N": int(n), "selected_bits": selected_bits, "status": terminal_status, "ladder": ladder}

def _resource_blueprint_for_seed(n: int, seed: int, bits: int) -> dict[str, Any]:
    fixed = seed_fixed_point_spec(n, seed, bits)
    count_widths = [int(x["counter_bits"]) for x in fixed["group_bands"]]
    acc_widths = [int(x["accumulator_signed_bits"]) for x in fixed["factor_bands"]]
    band_flags = len(count_widths) + len(acc_widths)
    max_work = max(count_widths + acc_widths + [1])
    sum_regs = sum(count_widths) + sum(acc_widths)
    comparator_work = max(3, int(math.ceil(max_work / 2)))
    # Sequential reuse is the intended executable architecture; parallel is a conservative envelope.
    sequential = int(n + max_work + comparator_work + band_flags + 2)
    parallel = int(n + sum_regs + 2 * band_flags + max_work + 2)
    controlled_adds = int(n * len(acc_widths) + sum(len(x["indices"]) for x in fixed["group_bands"]))
    comparisons = int(2 * band_flags)
    return {
        "seed": int(seed), "bits": int(bits), "data_qubits": int(n),
        "group_counter_widths": count_widths, "factor_accumulator_widths": acc_widths,
        "band_flags": int(band_flags), "controlled_add_operations": controlled_adds,
        "integer_comparisons": comparisons,
        "sequential_reuse_logical_qubits": sequential,
        "parallel_register_logical_qubits": parallel,
        "clean_uncompute_required": True,
    }


def build_family_oracle_blueprint(root: str | Path, n: int, bits: int) -> dict[str, Any]:
    summary = family_audit_summary(root, n, bits)
    if not summary["exact"]:
        raise RuntimeError("Cannot build a sealable BANDS oracle blueprint before exact family fidelity passes.")
    seed_specs = []
    resources = []
    for seed in SEALED_SEEDS:
        audit = load_seed_audit(root, n, bits, seed)
        if audit is None or audit.get("status") != "EXACT FIDELITY PASS":
            raise RuntimeError(f"Missing exact fidelity proof for seed {seed}.")
        seed_specs.append(audit["fixed_point_spec"])
        resources.append(_resource_blueprint_for_seed(n, seed, bits))
    payload = {
        "oracle_version": ORACLE_VERSION,
        "oracle_spec_sha": ORACLE_SPEC_SHA,
        "phase2_protocol_sha": PHASE2_PROTOCOL_SHA,
        "phase2_execution_spec_sha": PHASE2_EXECUTION_SPEC_SHA,
        "phase3_preparation_spec_sha": PHASE3_PREPARATION_SPEC_SHA,
        "family": {"N": int(n), "Regime": "BANDS", "seeds": list(SEALED_SEEDS)},
        "fixed_point_bits": int(bits),
        "fidelity_status": "EXACT FAMILY FIDELITY PASS",
        "quantization_rule": ORACLE_SPEC["quantization_rule"],
        "reversible_schedule": [
            "prepare witness-feasible exact-K basis state",
            "for each group: controlled add selected bits -> exact count register -> compare [L,U] -> flag -> uncompute counter",
            "for each factor: controlled signed add sealed integer coefficients -> accumulator -> compare [L_int,U_int] -> flag -> uncompute accumulator",
            "AND all seven constraint flags into one feasibility flag",
            "use feasibility flag in the sealed constraint-preserving phase/oracle construction",
            "uncompute temporary flags/ancillas to |0> before mixer/cost continuation",
        ],
        "seed_fixed_point_specs": seed_specs,
        "resource_blueprints": resources,
        "resource_summary": {
            "logical_qubits_sequential_reuse_max": int(max(r["sequential_reuse_logical_qubits"] for r in resources)),
            "logical_qubits_parallel_envelope_max": int(max(r["parallel_register_logical_qubits"] for r in resources)),
            "controlled_add_operations_max": int(max(r["controlled_add_operations"] for r in resources)),
            "integer_comparisons": int(max(r["integer_comparisons"] for r in resources)),
        },
    }
    payload["oracle_blueprint_sha"] = _sha(payload, 20)
    payload["created_utc"] = datetime.now(timezone.utc).isoformat()
    return payload


def sealed_oracle_path(root: str | Path, n: int = 40) -> Path:
    return Path(root) / f"N{int(n)}_BANDS" / "SEALED_BANDS_ORACLE.json"


def seal_family_oracle(root: str | Path, n: int, bits: int) -> dict[str, Any]:
    path = sealed_oracle_path(root, n); path.parent.mkdir(parents=True, exist_ok=True)
    blueprint = build_family_oracle_blueprint(root, n, bits)
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except Exception:
            return {"sealed": False, "reason": "Existing oracle seal is unreadable; do not overwrite it.", "path": str(path)}
        same = existing.get("oracle_blueprint_sha") == blueprint.get("oracle_blueprint_sha")
        return {"sealed": bool(same), "reason": "Existing identical seal preserved." if same else "A different oracle seal already exists; overwrite is forbidden.", "path": str(path), "oracle": existing}
    path.write_text(json.dumps(blueprint, indent=2, sort_keys=True))
    return {"sealed": True, "reason": "BANDS oracle blueprint sealed. No QPU job submitted.", "path": str(path), "oracle": blueprint}


def load_sealed_oracle(root: str | Path, n: int = 40) -> dict[str, Any] | None:
    path = sealed_oracle_path(root, n)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return None
    if payload.get("oracle_spec_sha") != ORACLE_SPEC_SHA or payload.get("fidelity_status") != "EXACT FAMILY FIDELITY PASS":
        return None
    return payload


def promote_bands_encoding(base_encoding: dict[str, Any], sealed_oracle: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(base_encoding or {})
    if not sealed_oracle:
        return out
    summary = sealed_oracle.get("resource_summary") or {}
    out.update({
        "encoding_status": "BLUEPRINT AVAILABLE · SEALED EXACT BANDS ORACLE",
        "encoding_exactness": "All eight Phase-II N=40 BANDS seeds passed the sealed fixed-point MILP mismatch proof; the integer reversible constraint blueprint preserves the audited feasible set at the selected precision.",
        "logical_qubits_min": int(summary.get("logical_qubits_sequential_reuse_max", out.get("logical_qubits_min", 0)) or 0),
        "logical_qubits_parallel_envelope": int(summary.get("logical_qubits_parallel_envelope_max", 0) or 0),
        "bands_oracle_bits": int(sealed_oracle.get("fixed_point_bits", 0) or 0),
        "bands_oracle_sha": str(sealed_oracle.get("oracle_blueprint_sha", "")),
        "constraint_resource_envelopes": [],
        "oracle_sealed": True,
        "hardware_executable": False,
        "compiler_status": "LOGICAL REVERSIBLE ORACLE SEALED · GATE-LEVEL COMPILER NOT YET SEALED",
    })
    return out


def _worker_status_path(root: str | Path, n: int = 40) -> Path:
    return Path(root) / f"N{int(n)}_BANDS" / "oracle_worker_status.json"


def _write_worker_status(root: str | Path, n: int, **payload: Any) -> dict[str, Any]:
    path = _worker_status_path(root, n); path.parent.mkdir(parents=True, exist_ok=True)
    current = {}
    if path.exists():
        try: current = json.loads(path.read_text())
        except Exception: current = {}
    current.update(payload); current["oracle_spec_sha"] = ORACLE_SPEC_SHA; current["updated_utc"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(current, indent=2, sort_keys=True))
    return current


def oracle_worker_status(root: str | Path | None = None, n: int = 40) -> dict[str, Any]:
    root = Path(root or default_oracle_root()); path = _worker_status_path(root, n)
    status = {}
    if path.exists():
        try: status = json.loads(path.read_text())
        except Exception: status = {}
    status.setdefault("status", "IDLE")
    status["root"] = str(root); status["N"] = int(n); status["oracle_spec_sha"] = ORACLE_SPEC_SHA
    status["ladder"] = [{"bits": b, **{k:v for k,v in family_audit_summary(root,n,b).items() if k in {"status","exact","completed","expected"}}} for b in FIXED_POINT_LADDER]
    sealed = load_sealed_oracle(root,n); status["sealed"] = bool(sealed); status["sealed_oracle_sha"] = sealed.get("oracle_blueprint_sha") if sealed else None
    return status


def run_oracle_worker(root: str | Path | None = None, n: int = 40) -> dict[str, Any]:
    import os
    root = Path(root or default_oracle_root()); n = int(n)
    _write_worker_status(root,n,status="RUNNING",pid=os.getpid(),started_utc=datetime.now(timezone.utc).isoformat())
    time_limit = float(ORACLE_SPEC["fidelity_contract"]["proof_milp_time_limit_seconds_per_extremum"])
    try:
        for bits in FIXED_POINT_LADDER:
            summary = family_audit_summary(root,n,bits)
            if summary.get("exact"):
                _write_worker_status(root,n,status="EXACT PRECISION FOUND",selected_bits=int(bits),pid=os.getpid())
                return oracle_worker_status(root,n)
            if str(summary.get("status","")).startswith("FAMILY FIDELITY FAIL"):
                continue
            for seed in SEALED_SEEDS:
                existing = load_seed_audit(root,n,bits,seed)
                if existing is not None:
                    if str(existing.get("status","")).startswith("FAIL"):
                        break
                    if str(existing.get("status","")).startswith("INDETERMINATE"):
                        _write_worker_status(root,n,status="INDETERMINATE",bits=int(bits),seed=int(seed),reason=str(existing.get("status")),pid=os.getpid())
                        return oracle_worker_status(root,n)
                    continue
                _write_worker_status(root,n,status="RUNNING",bits=int(bits),seed=int(seed),pid=os.getpid())
                audit = run_seed_audit_checkpointed(root,n,bits,seed,time_limit_s=time_limit)
                if str(audit.get("status","")).startswith("FAIL"):
                    break
                if str(audit.get("status","")).startswith("INDETERMINATE"):
                    _write_worker_status(root,n,status="INDETERMINATE",bits=int(bits),seed=int(seed),reason=str(audit.get("status")),pid=os.getpid())
                    return oracle_worker_status(root,n)
            summary = family_audit_summary(root,n,bits)
            if summary.get("exact"):
                _write_worker_status(root,n,status="EXACT PRECISION FOUND",selected_bits=int(bits),pid=os.getpid())
                return oracle_worker_status(root,n)
        _write_worker_status(root,n,status="NO EXACT PRECISION IN SEALED LADDER",pid=os.getpid())
    except Exception as exc:
        _write_worker_status(root,n,status="WORKER ERROR",reason=f"{type(exc).__name__}: {exc}",pid=os.getpid())
    return oracle_worker_status(root,n)


def launch_oracle_worker(root: str | Path | None = None, n: int = 40) -> dict[str, Any]:
    import os, subprocess, sys
    root = Path(root or default_oracle_root()); n=int(n)
    state = oracle_worker_status(root,n)
    if state.get("sealed"):
        return {"launched":False,"reason":"oracle already sealed"}
    pid=int(state.get("pid",0) or 0)
    if pid>0 and state.get("status")=="RUNNING":
        try:
            os.kill(pid,0); return {"launched":False,"reason":f"worker already running (PID {pid})","pid":pid}
        except OSError: pass
    package_root=Path(__file__).resolve().parents[1]
    log_path=root/f"N{n}_BANDS"/"oracle_worker.log"; log_path.parent.mkdir(parents=True,exist_ok=True)
    log=log_path.open("ab")
    proc=subprocess.Popen([sys.executable,"-m","quantum_research_lab.phase3_bands_oracle","--worker-root",str(root),"--n",str(n)],cwd=str(package_root),stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    log.close(); _write_worker_status(root,n,status="RUNNING",pid=int(proc.pid),launched_utc=datetime.now(timezone.utc).isoformat())
    return {"launched":True,"pid":int(proc.pid),"log":str(log_path)}


def _main() -> int:
    import argparse
    parser=argparse.ArgumentParser(description="Exact BANDS fixed-point fidelity audit worker")
    parser.add_argument("--worker-root",type=str,default="")
    parser.add_argument("--n",type=int,default=40)
    parser.add_argument("--spec",action="store_true")
    args=parser.parse_args()
    if args.spec:
        print(json.dumps(oracle_spec_payload(),indent=2,sort_keys=True)); return 0
    if args.worker_root:
        print(json.dumps(run_oracle_worker(args.worker_root,args.n),indent=2,default=str)); return 0
    parser.print_help(); return 0


if __name__ == "__main__":
    raise SystemExit(_main())
