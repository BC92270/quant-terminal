from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .phase2_qhardness import build_hard_instance, is_feasible

DYADIC_ORACLE_VERSION = "PHASE III · EXACT DYADIC BANDS ORACLE · V1"
DYADIC_SPEC_VERSION = "IEEE-754 BINARY64 → EXACT DYADIC INTEGER ORACLE SPEC · V1"
PHASE2_PROTOCOL_SHA = "8E5EF191FAE97A75"
PHASE2_EXECUTION_SPEC_SHA = "40D3225B0AFC86BC01DD"
PHASE3_PREPARATION_SPEC_SHA = "CDC693C22A3838B0B3C1"
SOURCE_FIXED_POINT_ORACLE_SPEC_SHA = "62854F1D7076BA742775"
SEALED_SEEDS = (1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807)
PHASE2_FEASIBILITY_TOL = 1e-8

DYADIC_SPEC: dict[str, Any] = {
    "dyadic_oracle_version": DYADIC_ORACLE_VERSION,
    "dyadic_spec_version": DYADIC_SPEC_VERSION,
    "phase2_protocol_sha": PHASE2_PROTOCOL_SHA,
    "phase2_execution_spec_sha": PHASE2_EXECUTION_SPEC_SHA,
    "phase3_preparation_spec_sha": PHASE3_PREPARATION_SPEC_SHA,
    "source_fixed_point_oracle_spec_sha": SOURCE_FIXED_POINT_ORACLE_SPEC_SHA,
    "candidate_family": {"N": 40, "Regime": "BANDS", "seeds": list(SEALED_SEEDS)},
    "source_semantics": {
        "coefficients": "The exact IEEE-754 binary64 values emitted by the sealed Phase-II deterministic generator.",
        "hard_band_bounds": "The exact IEEE-754 binary64 lower/upper BANDS bounds used by the authoritative Phase-II MILP model.",
        "phase2_feasibility_validator_tolerance": PHASE2_FEASIBILITY_TOL,
        "tolerance_role": "The 1e-8 tolerance is retained as a numerical validator/post-processing convention; it is not widened into the canonical hard-band oracle.",
    },
    "exact_mapping": (
        "For each factor, every binary64 coefficient and bound is converted with float.as_integer_ratio(). "
        "All denominators are powers of two. A per-factor common denominator 2^E is selected and all coefficients/bounds "
        "are lifted to signed integers exactly, with no coefficient or bound rounding."
    ),
    "proof_contract": {
        "parameter_identity": "Every original coefficient/bound must reconstruct bit-for-bit to the same Python float after integer/dyadic conversion.",
        "algebraic_equivalence": "For every x in {0,1}^N, sum(beta_i*x_i) in exact rational semantics equals sum(B_i*x_i)/2^E; therefore hard-band inequalities are exactly equivalent to integer comparisons.",
        "family_rule": "All 8 sealed N=40 BANDS seeds must receive exact parameter-identity certificates before the logical oracle may be sealed.",
        "v3_0_falsification_dependency": "The V3.0 8/12/16 approximate fixed-point ladder must remain preserved as a falsification record; V3.1 does not overwrite or reinterpret those failed audits.",
    },
    "reversible_oracle_contract": {
        "cardinality": "Preserved by the number-preserving XY mixer.",
        "group_counts": "Exact reversible integer counts and comparisons.",
        "factor_exposures": "Exact controlled signed-integer additions using the dyadic coefficient integers, exact integer lower/upper comparisons, then uncompute.",
        "clean_ancilla": True,
        "phase2_economic_qubo_unchanged": True,
        "arbitrary_penalty_substitution": False,
        "gate_level_compiler_required_after_logical_seal": True,
    },
}


def _stable_json(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _sha(payload: Any, length: int = 20) -> str:
    return hashlib.sha256(_stable_json(payload)).hexdigest()[: int(length)].upper()


DYADIC_SPEC_SHA = _sha(DYADIC_SPEC, 20)


def dyadic_spec_payload() -> dict[str, Any]:
    return {**DYADIC_SPEC, "dyadic_spec_sha": DYADIC_SPEC_SHA}


def default_dyadic_root() -> Path:
    return Path("outputs/quantum_phase3/dyadic_bands_oracle")


def _pow2_exp(denominator: int) -> int:
    d = int(denominator)
    if d <= 0 or d & (d - 1):
        raise ValueError(f"Denominator is not a power of two: {d}")
    return int(d.bit_length() - 1)


def _trailing_zeros_abs(value: int) -> int:
    x = abs(int(value))
    if x == 0:
        return 10**9
    return int((x & -x).bit_length() - 1)


def _signed_width(lo: int, hi: int) -> int:
    lo = int(lo); hi = int(hi)
    width = 2
    while lo < -(1 << (width - 1)) or hi > (1 << (width - 1)) - 1:
        width += 1
    return int(width)


def exact_binary64(value: float) -> dict[str, Any]:
    v = float(value)
    numerator, denominator = v.as_integer_ratio()
    exponent = _pow2_exp(denominator)
    return {
        "float": v,
        "float_hex": v.hex(),
        "numerator": int(numerator),
        "denominator": int(denominator),
        "denominator_exponent": int(exponent),
    }


def _common_dyadic_integers(values: list[float]) -> dict[str, Any]:
    atoms = [exact_binary64(v) for v in values]
    exponent = max(int(a["denominator_exponent"]) for a in atoms) if atoms else 0
    integers: list[int] = []
    for atom in atoms:
        shift = exponent - int(atom["denominator_exponent"])
        integers.append(int(atom["numerator"]) << int(shift))

    # Canonical reduction: if every lifted integer shares a power of two, divide it out.
    finite_tz = [_trailing_zeros_abs(x) for x in integers if int(x) != 0]
    common_shift = min(finite_tz) if finite_tz else 0
    common_shift = int(min(common_shift, exponent))
    if common_shift > 0:
        integers = [int(x) >> common_shift for x in integers]
        exponent -= common_shift

    reconstructed = [Fraction(int(x), 1 << int(exponent)) for x in integers]
    identities = []
    for atom, frac in zip(atoms, reconstructed):
        original = Fraction(int(atom["numerator"]), int(atom["denominator"]))
        identities.append(bool(frac == original and float(frac) == float(atom["float"])))
    return {
        "common_denominator_exponent": int(exponent),
        "common_denominator": str(1 << int(exponent)),
        "integers": integers,
        "source_atoms": atoms,
        "identity_flags": identities,
        "all_exact": bool(all(identities)),
        "common_power_of_two_reduction": int(common_shift),
    }


def factor_dyadic_spec(coefficients: np.ndarray | list[float], lower: float, upper: float, k: int, name: str) -> dict[str, Any]:
    coeff = [float(x) for x in np.asarray(coefficients, dtype=float).reshape(-1).tolist()]
    vals = coeff + [float(lower), float(upper)]
    mapped = _common_dyadic_integers(vals)
    ints = [int(x) for x in mapped["integers"]]
    qcoeff = ints[: len(coeff)]
    qlo, qhi = ints[-2], ints[-1]
    sorted_q = sorted(qcoeff)
    min_sum = int(sum(sorted_q[: int(k)]))
    max_sum = int(sum(sorted_q[-int(k):]))
    exact_count = int(sum(bool(x) for x in mapped["identity_flags"]))
    total_count = int(len(mapped["identity_flags"]))
    return {
        "name": str(name),
        "common_denominator_exponent": int(mapped["common_denominator_exponent"]),
        "common_denominator": mapped["common_denominator"],
        "coefficients_int": qcoeff,
        "lower_int": int(qlo),
        "upper_int": int(qhi),
        "accumulator_min": min_sum,
        "accumulator_max": max_sum,
        "accumulator_signed_bits": _signed_width(min_sum, max_sum),
        "max_coefficient_integer_bits": int(max(abs(x).bit_length() for x in qcoeff) if qcoeff else 1),
        "parameter_identity_pass": bool(mapped["all_exact"]),
        "parameter_identity_count": exact_count,
        "parameter_identity_total": total_count,
        "common_power_of_two_reduction": int(mapped["common_power_of_two_reduction"]),
        "source_float_hex": [a["float_hex"] for a in mapped["source_atoms"]],
        "source_parameter_sha": _sha([a["float_hex"] for a in mapped["source_atoms"]], 16),
        "integer_parameter_sha": _sha({"E": mapped["common_denominator_exponent"], "ints": ints}, 16),
    }


def dyadic_oracle_feasible(x: np.ndarray, inst: Any) -> bool:
    xx = (np.asarray(x, dtype=float).reshape(-1) > 0.5).astype(np.int64)
    if len(xx) != int(inst.n) or int(np.sum(xx)) != int(inst.k):
        return False
    for band in inst.group_bands:
        val = int(np.sum(xx[np.asarray(band["indices"], dtype=int)]))
        if val < int(band["lower"]) or val > int(band["upper"]):
            return False
    for band in inst.factor_bands:
        fs = factor_dyadic_spec(np.asarray(band["coefficients"], dtype=float), float(band["lower"]), float(band["upper"]), int(inst.k), str(band["name"]))
        val = sum(int(c) * int(bit) for c, bit in zip(fs["coefficients_int"], xx.tolist()))
        if val < int(fs["lower_int"]) or val > int(fs["upper_int"]):
            return False
    return True


def strict_float_band_feasible(x: np.ndarray, inst: Any) -> bool:
    """Strict hard-band semantics corresponding to the authoritative Phase-II MILP bounds.

    This intentionally does not use the 1e-8 heuristic/post-processing tolerance from is_feasible().
    """
    xx = (np.asarray(x, dtype=float).reshape(-1) > 0.5).astype(float)
    if len(xx) != int(inst.n) or int(np.sum(xx)) != int(inst.k):
        return False
    for band in inst.group_bands:
        val = float(np.sum(xx[np.asarray(band["indices"], dtype=int)]))
        if val < float(band["lower"]) or val > float(band["upper"]):
            return False
    for band in inst.factor_bands:
        val = float(np.asarray(band["coefficients"], dtype=float) @ xx)
        if val < float(band["lower"]) or val > float(band["upper"]):
            return False
    return True


def _dot_roundoff_bound(coefficients: np.ndarray, n_terms: int) -> float:
    # Conservative textbook gamma_n envelope for floating dot accumulation.
    u = 2.0 ** -53
    n = max(int(n_terms), 1)
    gamma = (n * u) / max(1.0 - n * u, 1e-30)
    return float(gamma * np.sum(np.abs(np.asarray(coefficients, dtype=float))))


def seed_dyadic_certificate(n: int, seed: int) -> dict[str, Any]:
    inst = build_hard_instance(int(n), "BANDS", int(seed))
    factor_specs = []
    for band in inst.factor_bands:
        factor_specs.append(
            factor_dyadic_spec(
                np.asarray(band["coefficients"], dtype=float),
                float(band["lower"]),
                float(band["upper"]),
                int(inst.k),
                str(band["name"]),
            )
        )
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
    identity_total = int(sum(int(f["parameter_identity_total"]) for f in factor_specs))
    identity_pass = int(sum(int(f["parameter_identity_count"]) for f in factor_specs))
    witness = inst.witness.astype(float)
    witness_strict = bool(strict_float_band_feasible(witness, inst))
    witness_dyadic = bool(dyadic_oracle_feasible(witness, inst))
    witness_tolerant = bool(is_feasible(witness, inst))
    roundoff = []
    for band in inst.factor_bands:
        roundoff.append({
            "name": str(band["name"]),
            "conservative_abs_dot_roundoff_bound": _dot_roundoff_bound(np.asarray(band["coefficients"], dtype=float), int(inst.n)),
            "phase2_validator_tolerance": PHASE2_FEASIBILITY_TOL,
        })
    passed = bool(identity_pass == identity_total and witness_strict and witness_dyadic)
    payload = {
        "dyadic_spec_sha": DYADIC_SPEC_SHA,
        "instance_id": str(inst.instance_id),
        "N": int(inst.n),
        "K": int(inst.k),
        "seed": int(seed),
        "status": "EXACT DYADIC PARAMETERIZATION PASS" if passed else "DYADIC CERTIFICATE FAIL",
        "parameter_identity_pass": bool(identity_pass == identity_total),
        "parameter_identity_count": identity_pass,
        "parameter_identity_total": identity_total,
        "universal_algebraic_equivalence": bool(identity_pass == identity_total),
        "witness_strict_float_feasible": witness_strict,
        "witness_dyadic_feasible": witness_dyadic,
        "witness_phase2_tolerant_feasible": witness_tolerant,
        "group_bands": group_specs,
        "factor_bands": factor_specs,
        "roundoff_diagnostics": roundoff,
        "semantic_note": (
            "The dyadic oracle is exactly equivalent to the strict hard-band mathematical problem defined by the frozen binary64 coefficients/bounds. "
            "The Phase-II 1e-8 feasibility tolerance remains a separate numerical validation convention, not part of the hard-band oracle."
        ),
        "created_utc": datetime.now(timezone.utc).isoformat(),
    }
    payload["certificate_sha"] = _sha({k: v for k, v in payload.items() if k not in {"created_utc", "certificate_sha"}}, 20)
    return payload


def _resource_blueprint(certificate: dict[str, Any]) -> dict[str, Any]:
    n = int(certificate["N"])
    count_widths = [int(x["counter_bits"]) for x in certificate["group_bands"]]
    acc_widths = [int(x["accumulator_signed_bits"]) for x in certificate["factor_bands"]]
    exponent_bits = [int(x["common_denominator_exponent"]) for x in certificate["factor_bands"]]
    flags = len(count_widths) + len(acc_widths)
    max_work = max(count_widths + acc_widths + [1])
    comparator_work = max(3, int(math.ceil(max_work / 2)))
    sequential = int(n + max_work + comparator_work + flags + 2)
    parallel = int(n + sum(count_widths) + sum(acc_widths) + 2 * flags + max_work + 2)
    controlled_adds = int(n * len(acc_widths) + sum(len(x["indices"]) for x in certificate["group_bands"]))
    comparisons = int(2 * flags)
    return {
        "seed": int(certificate["seed"]),
        "data_qubits": n,
        "group_counter_widths": count_widths,
        "factor_accumulator_widths": acc_widths,
        "factor_common_denominator_exponents": exponent_bits,
        "max_factor_common_denominator_exponent": max(exponent_bits) if exponent_bits else 0,
        "band_flags": int(flags),
        "controlled_add_operations": controlled_adds,
        "integer_comparisons": comparisons,
        "sequential_reuse_logical_qubits": sequential,
        "parallel_register_logical_qubits": parallel,
        "clean_uncompute_required": True,
    }


def family_dyadic_summary(n: int = 40, seeds: tuple[int, ...] = SEALED_SEEDS) -> dict[str, Any]:
    certificates = [seed_dyadic_certificate(int(n), int(seed)) for seed in seeds]
    rows = []
    resources = []
    for cert in certificates:
        res = _resource_blueprint(cert)
        resources.append(res)
        exps = [int(f["common_denominator_exponent"]) for f in cert["factor_bands"]]
        accs = [int(f["accumulator_signed_bits"]) for f in cert["factor_bands"]]
        rows.append({
            "Seed": int(cert["seed"]),
            "Status": str(cert["status"]),
            "Exact identities": f"{int(cert['parameter_identity_count'])}/{int(cert['parameter_identity_total'])}",
            "Factor dyadic exponents": " / ".join(str(x) for x in exps),
            "Accumulator bits": " / ".join(str(x) for x in accs),
            "Witness parity": bool(cert["witness_strict_float_feasible"] == cert["witness_dyadic_feasible"]),
            "Logical qubits · reuse": int(res["sequential_reuse_logical_qubits"]),
        })
    all_pass = bool(all(c["status"] == "EXACT DYADIC PARAMETERIZATION PASS" for c in certificates))
    return {
        "N": int(n),
        "status": "EXACT DYADIC FAMILY PASS · BY CONSTRUCTION" if all_pass else "DYADIC FAMILY FAIL",
        "exact": all_pass,
        "completed": len(certificates),
        "expected": len(seeds),
        "table": pd.DataFrame(rows),
        "certificates": certificates,
        "resources": resources,
        "resource_summary": {
            "logical_qubits_sequential_reuse_max": int(max(r["sequential_reuse_logical_qubits"] for r in resources)),
            "logical_qubits_parallel_envelope_max": int(max(r["parallel_register_logical_qubits"] for r in resources)),
            "max_factor_accumulator_bits": int(max(max(r["factor_accumulator_widths"]) for r in resources)),
            "max_dyadic_denominator_exponent": int(max(r["max_factor_common_denominator_exponent"] for r in resources)),
            "controlled_add_operations_max": int(max(r["controlled_add_operations"] for r in resources)),
            "integer_comparisons": int(max(r["integer_comparisons"] for r in resources)),
        },
    }


def build_dyadic_oracle_blueprint(n: int = 40, *, v3_fixed_point_falsified: bool) -> dict[str, Any]:
    if not bool(v3_fixed_point_falsified):
        raise RuntimeError("V3.1 dyadic oracle sealing is blocked until the V3.0 8/12/16 ladder is preserved as a complete falsification record.")
    summary = family_dyadic_summary(int(n))
    if not summary["exact"]:
        raise RuntimeError("Exact dyadic parameterization did not pass all eight seeds.")
    payload = {
        "dyadic_oracle_version": DYADIC_ORACLE_VERSION,
        "dyadic_spec_sha": DYADIC_SPEC_SHA,
        "phase2_protocol_sha": PHASE2_PROTOCOL_SHA,
        "phase2_execution_spec_sha": PHASE2_EXECUTION_SPEC_SHA,
        "phase3_preparation_spec_sha": PHASE3_PREPARATION_SPEC_SHA,
        "source_fixed_point_oracle_spec_sha": SOURCE_FIXED_POINT_ORACLE_SPEC_SHA,
        "v3_fixed_point_ladder_status": "8/12/16 APPROXIMATE FIXED-POINT LADDER FALSIFIED",
        "family": {"N": int(n), "Regime": "BANDS", "seeds": list(SEALED_SEEDS)},
        "semantic_contract": "Exact dyadic normalization of the authoritative Phase-II MILP hard-band coefficients/bounds; no quantization or arbitrary penalties.",
        "fidelity_status": "EXACT DYADIC FAMILY PASS · BY CONSTRUCTION",
        "seed_certificates": summary["certificates"],
        "resource_blueprints": summary["resources"],
        "resource_summary": summary["resource_summary"],
        "reversible_schedule": [
            "prepare witness-feasible exact-K computational basis state",
            "for each group: controlled add selection bits -> exact count register -> compare [L,U] -> group flag -> uncompute counter",
            "for each factor: controlled signed add exact dyadic integer coefficients -> signed accumulator -> compare exact integer [L_int,U_int] -> factor flag -> uncompute accumulator",
            "AND four group flags and three factor flags into one feasibility flag",
            "use the feasibility flag only through the future sealed gate-level constraint oracle construction",
            "uncompute all temporary comparison and arithmetic ancillas to |0> before continuing",
        ],
        "compiler_status": "LOGICAL DYADIC IR ONLY · GATE-LEVEL COMPILER NOT YET SEALED",
        "hardware_executable": False,
    }
    payload["dyadic_oracle_sha"] = _sha(payload, 20)
    payload["created_utc"] = datetime.now(timezone.utc).isoformat()
    return payload


def sealed_dyadic_oracle_path(root: str | Path, n: int = 40) -> Path:
    return Path(root) / f"N{int(n)}_BANDS" / "SEALED_EXACT_DYADIC_BANDS_ORACLE.json"


def seal_dyadic_oracle(root: str | Path, n: int = 40, *, v3_fixed_point_falsified: bool) -> dict[str, Any]:
    root = Path(root)
    path = sealed_dyadic_oracle_path(root, int(n))
    path.parent.mkdir(parents=True, exist_ok=True)
    blueprint = build_dyadic_oracle_blueprint(int(n), v3_fixed_point_falsified=bool(v3_fixed_point_falsified))
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except Exception:
            return {"sealed": False, "reason": "Existing dyadic oracle seal is unreadable; overwrite is forbidden.", "path": str(path)}
        same = existing.get("dyadic_oracle_sha") == blueprint.get("dyadic_oracle_sha")
        return {
            "sealed": bool(same),
            "reason": "Existing identical dyadic oracle seal preserved." if same else "A different dyadic oracle seal already exists; overwrite is forbidden.",
            "path": str(path),
            "oracle": existing,
        }
    path.write_text(json.dumps(blueprint, indent=2, sort_keys=True))
    return {"sealed": True, "reason": "Exact dyadic BANDS logical oracle sealed. No QPU job submitted.", "path": str(path), "oracle": blueprint}


def load_sealed_dyadic_oracle(root: str | Path, n: int = 40) -> dict[str, Any] | None:
    path = sealed_dyadic_oracle_path(root, int(n))
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return None
    if payload.get("dyadic_spec_sha") != DYADIC_SPEC_SHA:
        return None
    if payload.get("fidelity_status") != "EXACT DYADIC FAMILY PASS · BY CONSTRUCTION":
        return None
    return payload


def promote_dyadic_encoding(base_encoding: dict[str, Any], sealed_oracle: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(base_encoding or {})
    if not sealed_oracle:
        out["hardware_executable"] = False
        return out
    rs = sealed_oracle.get("resource_summary") or {}
    out.update({
        "encoding_status": "LOGICAL ORACLE SEALED · EXACT DYADIC BANDS",
        "encoding_exactness": (
            "The frozen Phase-II binary64 hard-band coefficients and bounds are represented exactly as dyadic integers with per-factor power-of-two denominators. "
            "No 8/12/16 approximation and no arbitrary penalty is used."
        ),
        "logical_qubits_min": int(rs.get("logical_qubits_sequential_reuse_max", out.get("logical_qubits_min", 0)) or 0),
        "logical_qubits_parallel_envelope": int(rs.get("logical_qubits_parallel_envelope_max", 0) or 0),
        "bands_oracle_sha": str(sealed_oracle.get("dyadic_oracle_sha", "")),
        "bands_oracle_mode": "EXACT_DYADIC_BINARY64",
        "bands_oracle_bits": None,
        "max_factor_accumulator_bits": int(rs.get("max_factor_accumulator_bits", 0) or 0),
        "max_dyadic_denominator_exponent": int(rs.get("max_dyadic_denominator_exponent", 0) or 0),
        "oracle_sealed": True,
        "hardware_executable": False,
        "compiler_status": "LOGICAL DYADIC ORACLE SEALED · GATE-LEVEL COMPILER NOT YET SEALED",
        "constraint_resource_envelopes": [],
    })
    return out
