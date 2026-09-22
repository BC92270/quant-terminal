from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import shutil
import socket
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .engine import qubo_energy
from .experiments import QUBO_SUITE


PROTOCOL_KEY = "QUBO_HARD_INSTANCE_SUITE"
PROTOCOL_SHA = "8E5EF191FAE97A75"
SOURCE_EVIDENCE_ID = "QQUBO-20260821-861D4D08E8"
PHASE2_MANIFEST_SHA = "AA06BE666EBFE379C82B"
EXECUTION_SPEC_VERSION = "QUBO PHASE-II EXECUTION SPEC · V1"

# This execution contract is deliberately separate from the V2.7.1 preregistration
# manifest. The latter already sealed sizes, regimes, seeds and promotion gates;
# this object seals deterministic instance-generation and solver-budget details
# before any canonical 120-instance run is executed.
EXECUTION_SPEC: dict[str, Any] = {
    "execution_spec_version": EXECUTION_SPEC_VERSION,
    "protocol_key": PROTOCOL_KEY,
    "protocol_sha": PROTOCOL_SHA,
    "source_evidence_id": SOURCE_EVIDENCE_ID,
    "phase2_manifest_sha": PHASE2_MANIFEST_SHA,
    "canonical_order": "N ascending -> regime BASE/PAIRWISE/BANDS -> preregistered seed order",
    "objective": {
        "portfolio_type": "equal-weight binary selection",
        "cardinality_fraction": float(QUBO_SUITE["cardinality_fraction"]),
        "risk_aversion": 5.0,
        "expected_return_mean": 0.10,
        "expected_return_sd": 0.06,
        "expected_return_clip": [-0.05, 0.30],
        "volatility_range": [0.12, 0.35],
        "factor_rank": 5,
        "factor_corr_weight": 0.65,
        "idiosyncratic_corr_weight": 0.35,
    },
    "constraints": {
        "BASE": "exact cardinality only",
        "PAIRWISE": {
            "description": "exact cardinality + witness-safe random pairwise exclusions",
            "target_conflict_density": 0.06,
        },
        "BANDS": {
            "description": "exact cardinality + 4 group-count bands + 3 factor-exposure bands",
            "groups": 4,
            "group_count_half_width": 1,
            "factor_bands": 3,
            "factor_band_tolerance_scale": 0.35,
        },
    },
    "solver_budgets": {
        "milp_time_limit_seconds": 75.0,
        "milp_relative_gap_target": 1e-9,
        "sa_restarts": 8,
        "sa_sweeps": 64,
        "local_restarts": 16,
        "local_max_passes": 64,
        "local_candidate_swaps_per_pass": 128,
        "initial_randomization_swaps": 128,
    },
    "gap_definition": (
        "best fixed-budget heuristic relative gap = (min(E_SA,E_Local)-E_reference) / max(abs(E_reference),1e-12); "
        "E_reference is the best feasible incumbent among MILP, SA and Local Search. MILP optimality certification is reported separately."
    ),
    "family_definition": "one family = fixed (N, constraint regime) across all 8 preregistered seeds",
    "success_gate": {
        "milp_median_gate_seconds": float(QUBO_SUITE["milp_median_gate_seconds"]),
        "milp_p95_gate_seconds": float(QUBO_SUITE["milp_p95_gate_seconds"]),
        "heuristic_gap_gate": float(QUBO_SUITE["heuristic_gap_gate"]),
        "heuristic_hard_fraction_gate": float(QUBO_SUITE["heuristic_hard_fraction_gate"]),
        "required_instances_per_family": len(QUBO_SUITE["seeds"]),
        "technical_failure_policy": "any canonical instance without a valid recorded result makes the global confirmatory outcome INDETERMINATE",
    },
    "operational_rules": {
        "no_instance_skipping": True,
        "no_seed_replacement": True,
        "no_rerun_of_completed_instance": True,
        "resume_requires_identical_environment_fingerprint": True,
        "checkpoint_after_each_instance": True,
        "final_gate_only_after_all_instances": True,
    },
}


def _stable_json(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _sha(payload: Any, length: int = 20) -> str:
    return hashlib.sha256(_stable_json(payload)).hexdigest()[: int(length)].upper()


EXECUTION_SPEC_SHA = _sha(EXECUTION_SPEC, 20)


def execution_spec_payload() -> dict[str, Any]:
    return {**EXECUTION_SPEC, "execution_spec_sha": EXECUTION_SPEC_SHA}


def execution_environment() -> dict[str, Any]:
    try:
        import scipy
        scipy_version = scipy.__version__
    except Exception:
        scipy_version = "UNAVAILABLE"
    return {
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scipy": scipy_version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "UNKNOWN",
        "hostname": socket.gethostname(),
        "omp_num_threads": os.environ.get("OMP_NUM_THREADS", "UNSET"),
        "mkl_num_threads": os.environ.get("MKL_NUM_THREADS", "UNSET"),
        "openblas_num_threads": os.environ.get("OPENBLAS_NUM_THREADS", "UNSET"),
    }


def environment_sha(env: dict[str, Any] | None = None) -> str:
    return _sha(env or execution_environment(), 16)


def executor_code_sha() -> str:
    try:
        data = Path(__file__).read_bytes()
        return hashlib.sha256(data).hexdigest()[:16].upper()
    except Exception:
        return "UNAVAILABLE"


def planned_instances() -> pd.DataFrame:
    rows = []
    order = 0
    for n in [int(x) for x in QUBO_SUITE["sizes"]]:
        for regime in [str(x) for x in QUBO_SUITE["constraint_regimes"]]:
            for seed in [int(x) for x in QUBO_SUITE["seeds"]]:
                order += 1
                rows.append({
                    "Order": order,
                    "N": n,
                    "K": max(1, min(n - 1, int(round(float(QUBO_SUITE["cardinality_fraction"]) * n)))),
                    "Regime": regime,
                    "Seed": seed,
                    "Instance ID": f"QH-N{n:03d}-{regime}-S{seed}",
                })
    frame = pd.DataFrame(rows)
    if len(frame) != 120 or frame["Instance ID"].nunique() != 120:
        raise RuntimeError("Canonical QUBO Phase-II plan must contain exactly 120 unique instances.")
    return frame


@dataclass
class HardInstance:
    instance_id: str
    n: int
    k: int
    regime: str
    seed: int
    mu: np.ndarray
    cov: np.ndarray
    Q: np.ndarray
    witness: np.ndarray
    pairwise_exclusions: list[tuple[int, int]]
    group_bands: list[dict[str, Any]]
    factor_bands: list[dict[str, Any]]
    metadata: dict[str, Any]


def _base_moments(n: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    spec = EXECUTION_SPEC["objective"]
    rng = np.random.default_rng(int(seed) * 1009 + int(n) * 9173 + 41)
    mu = rng.normal(float(spec["expected_return_mean"]), float(spec["expected_return_sd"]), size=int(n))
    lo, hi = [float(x) for x in spec["expected_return_clip"]]
    mu = np.clip(mu, lo, hi)
    rank = int(min(int(spec["factor_rank"]), n))
    factors = rng.normal(size=(int(n), rank))
    gram = factors @ factors.T / max(rank, 1)
    d = np.sqrt(np.clip(np.diag(gram), 1e-12, None))
    corr_factor = gram / np.outer(d, d)
    corr = float(spec["factor_corr_weight"]) * corr_factor + float(spec["idiosyncratic_corr_weight"]) * np.eye(int(n))
    vals, vecs = np.linalg.eigh((corr + corr.T) / 2.0)
    corr = vecs @ np.diag(np.clip(vals, 1e-8, None)) @ vecs.T
    dd = np.sqrt(np.clip(np.diag(corr), 1e-12, None))
    corr = corr / np.outer(dd, dd)
    v_lo, v_hi = [float(x) for x in spec["volatility_range"]]
    vols = rng.uniform(v_lo, v_hi, size=int(n))
    cov = corr * np.outer(vols, vols)
    cov = (cov + cov.T) / 2.0
    return mu.astype(float), cov.astype(float)


def _economic_qubo(mu: np.ndarray, cov: np.ndarray, k: int) -> np.ndarray:
    lam = float(EXECUTION_SPEC["objective"]["risk_aversion"])
    q = (lam / float(k * k)) * np.asarray(cov, dtype=float)
    q = (q + q.T) / 2.0
    q[np.diag_indices(len(mu))] += -np.asarray(mu, dtype=float) / float(k)
    return q


def build_hard_instance(n: int, regime: str, seed: int) -> HardInstance:
    n = int(n); regime = str(regime).upper(); seed = int(seed)
    if n not in [int(x) for x in QUBO_SUITE["sizes"]] and n < 4:
        raise ValueError("n must be >=4")
    if regime not in {"BASE", "PAIRWISE", "BANDS"}:
        raise ValueError(f"Unknown constraint regime: {regime}")
    k = max(1, min(n - 1, int(round(float(QUBO_SUITE["cardinality_fraction"]) * n))))
    mu, cov = _base_moments(n, seed)
    Q = _economic_qubo(mu, cov, k)

    witness_rng = np.random.default_rng(seed * 811 + n * 131 + 7)
    witness_idx = np.sort(witness_rng.choice(n, size=k, replace=False))
    witness = np.zeros(n, dtype=int); witness[witness_idx] = 1

    pairwise: list[tuple[int, int]] = []
    group_bands: list[dict[str, Any]] = []
    factor_bands: list[dict[str, Any]] = []

    if regime == "PAIRWISE":
        target_density = float(EXECUTION_SPEC["constraints"]["PAIRWISE"]["target_conflict_density"])
        candidates = [(i, j) for i in range(n) for j in range(i + 1, n) if not (witness[i] and witness[j])]
        rng = np.random.default_rng(seed * 1237 + n * 3511 + 19)
        m = int(round(target_density * (n * (n - 1) / 2.0)))
        m = max(1, min(m, len(candidates)))
        choice = rng.choice(len(candidates), size=m, replace=False)
        pairwise = sorted(candidates[int(x)] for x in np.atleast_1d(choice))

    elif regime == "BANDS":
        cfg = EXECUTION_SPEC["constraints"]["BANDS"]
        groups = int(cfg["groups"])
        rng = np.random.default_rng(seed * 1597 + n * 2137 + 23)
        perm = rng.permutation(n)
        split = np.array_split(perm, groups)
        half = int(cfg["group_count_half_width"])
        for g, idx in enumerate(split):
            idx = np.asarray(idx, dtype=int)
            c = int(np.sum(witness[idx]))
            group_bands.append({
                "name": f"GROUP_{g+1}",
                "indices": idx.tolist(),
                "lower": max(0, c - half),
                "upper": min(len(idx), c + half),
            })
        factor_count = int(cfg["factor_bands"])
        loadings = rng.normal(size=(factor_count, n))
        tol_scale = float(cfg["factor_band_tolerance_scale"])
        for f in range(factor_count):
            a = loadings[f].astype(float)
            center = float(a @ witness)
            tol = float(tol_scale * max(math.sqrt(k), 1.0) * max(np.std(a), 1e-8))
            factor_bands.append({
                "name": f"FACTOR_{f+1}",
                "coefficients": a.tolist(),
                "lower": center - tol,
                "upper": center + tol,
            })

    nonzero = np.abs(Q[np.abs(Q) > 1e-15])
    dyn = float(np.max(nonzero) / max(np.min(nonzero), 1e-15)) if nonzero.size else float("nan")
    metadata = {
        "pairwise_conflict_count": len(pairwise),
        "pairwise_conflict_density": len(pairwise) / max(n * (n - 1) / 2.0, 1.0),
        "group_band_count": len(group_bands),
        "factor_band_count": len(factor_bands),
        "qubo_dynamic_range": dyn,
        "ising_coupling_density": float(np.count_nonzero(np.triu(np.abs(Q), 1) > 1e-15) / max(n * (n - 1) / 2.0, 1.0)),
    }
    iid = f"QH-N{n:03d}-{regime}-S{seed}"
    inst = HardInstance(iid, n, k, regime, seed, mu, cov, Q, witness, pairwise, group_bands, factor_bands, metadata)
    if not is_feasible(witness.astype(float), inst):
        raise RuntimeError(f"Internal witness infeasible for {iid}")
    return inst


def is_feasible(x: np.ndarray, inst: HardInstance, tol: float = 1e-8) -> bool:
    xx = (np.asarray(x, dtype=float).reshape(-1) > 0.5).astype(float)
    if len(xx) != inst.n or int(np.sum(xx)) != int(inst.k):
        return False
    for i, j in inst.pairwise_exclusions:
        if xx[int(i)] + xx[int(j)] > 1.0 + tol:
            return False
    for band in inst.group_bands:
        val = float(np.sum(xx[np.asarray(band["indices"], dtype=int)]))
        if val < float(band["lower"]) - tol or val > float(band["upper"]) + tol:
            return False
    for band in inst.factor_bands:
        a = np.asarray(band["coefficients"], dtype=float)
        val = float(a @ xx)
        if val < float(band["lower"]) - tol or val > float(band["upper"]) + tol:
            return False
    return True


def _milp_solve(inst: HardInstance, *, time_limit_s: float | None = None) -> dict[str, Any]:
    try:
        from scipy.optimize import Bounds, LinearConstraint, milp
        from scipy.sparse import lil_matrix
    except Exception as exc:
        return {"available": False, "reason": f"scipy.milp unavailable: {exc}"}

    q = np.asarray(inst.Q, dtype=float); n = inst.n
    pairs = [(i, j) for i in range(n) for j in range(i + 1, n) if abs(q[i, j]) > 1e-15]
    m = n + len(pairs)
    c = np.zeros(m, dtype=float); c[:n] = np.diag(q)
    for pos, (i, j) in enumerate(pairs):
        c[n + pos] = 2.0 * q[i, j]

    extra_rows = 1 + len(inst.pairwise_exclusions) + len(inst.group_bands) + len(inst.factor_bands)
    A = lil_matrix((3 * len(pairs) + extra_rows, m), dtype=float)
    lbs: list[float] = []; ubs: list[float] = []; row = 0
    for pos, (i, j) in enumerate(pairs):
        y = n + pos
        A[row, y] = 1; A[row, i] = -1; lbs.append(-np.inf); ubs.append(0.0); row += 1
        A[row, y] = 1; A[row, j] = -1; lbs.append(-np.inf); ubs.append(0.0); row += 1
        A[row, y] = -1; A[row, i] = 1; A[row, j] = 1; lbs.append(-np.inf); ubs.append(1.0); row += 1
    A[row, :n] = 1.0; lbs.append(float(inst.k)); ubs.append(float(inst.k)); row += 1
    for i, j in inst.pairwise_exclusions:
        A[row, int(i)] = 1.0; A[row, int(j)] = 1.0; lbs.append(-np.inf); ubs.append(1.0); row += 1
    for band in inst.group_bands:
        A[row, np.asarray(band["indices"], dtype=int)] = 1.0
        lbs.append(float(band["lower"])); ubs.append(float(band["upper"])); row += 1
    for band in inst.factor_bands:
        A[row, :n] = np.asarray(band["coefficients"], dtype=float)
        lbs.append(float(band["lower"])); ubs.append(float(band["upper"])); row += 1

    constraints = LinearConstraint(A.tocsr(), np.asarray(lbs, dtype=float), np.asarray(ubs, dtype=float))
    limit = float(time_limit_s if time_limit_s is not None else EXECUTION_SPEC["solver_budgets"]["milp_time_limit_seconds"])
    start_wall = time.perf_counter(); start_cpu = time.process_time()
    try:
        res = milp(
            c=c,
            integrality=np.ones(m, dtype=int),
            bounds=Bounds(np.zeros(m), np.ones(m)),
            constraints=constraints,
            options={
                "time_limit": max(limit, 0.1),
                "mip_rel_gap": float(EXECUTION_SPEC["solver_budgets"]["milp_relative_gap_target"]),
                "presolve": True,
            },
        )
    except Exception as exc:
        return {
            "available": False,
            "reason": f"MILP failed: {exc}",
            "runtime_s": time.perf_counter() - start_wall,
            "cpu_s": time.process_time() - start_cpu,
        }
    runtime = time.perf_counter() - start_wall; cpu = time.process_time() - start_cpu
    out: dict[str, Any] = {
        "available": bool(getattr(res, "x", None) is not None),
        "runtime_s": float(runtime),
        "cpu_s": float(cpu),
        "status": int(getattr(res, "status", -999)),
        "message": str(getattr(res, "message", "")),
        "optimality_certified": bool(getattr(res, "success", False) and int(getattr(res, "status", -1)) == 0),
        "mip_gap": float(getattr(res, "mip_gap", np.nan)),
        "mip_node_count": float(getattr(res, "mip_node_count", np.nan)),
        "mip_dual_bound": float(getattr(res, "mip_dual_bound", np.nan)),
    }
    if getattr(res, "x", None) is not None:
        x = np.rint(np.asarray(res.x[:n], dtype=float)).astype(float)
        out.update({"x": x, "feasible": bool(is_feasible(x, inst)), "energy": float(qubo_energy(x, q, 0.0))})
    else:
        out.update({"feasible": False, "energy": float("nan")})
    return out


def _swap_delta(q: np.ndarray, x: np.ndarray, qx: np.ndarray, i: int, j: int) -> float:
    # d_i=-1, d_j=+1 for a 1->0 / 0->1 swap.
    return float(2.0 * (-qx[i] + qx[j]) + q[i, i] + q[j, j] - 2.0 * q[i, j])


def _apply_swap(x: np.ndarray, qx: np.ndarray, q: np.ndarray, i: int, j: int) -> None:
    x[i] = 0.0; x[j] = 1.0
    qx += -q[:, i] + q[:, j]


def _randomized_feasible_start(inst: HardInstance, rng: np.random.Generator, steps: int) -> np.ndarray:
    x = inst.witness.astype(float).copy()
    q_dummy = np.zeros((inst.n, inst.n), dtype=float); qx = np.zeros(inst.n, dtype=float)
    for _ in range(max(int(steps), 0)):
        ones = np.where(x > 0.5)[0]; zeros = np.where(x < 0.5)[0]
        if len(ones) == 0 or len(zeros) == 0:
            break
        i = int(rng.choice(ones)); j = int(rng.choice(zeros))
        cand = x.copy(); cand[i] = 0.0; cand[j] = 1.0
        if is_feasible(cand, inst):
            _apply_swap(x, qx, q_dummy, i, j)
    return x


def _sa_solve(inst: HardInstance) -> dict[str, Any]:
    cfg = EXECUTION_SPEC["solver_budgets"]
    rng = np.random.default_rng(inst.seed * 4001 + inst.n * 97 + 101)
    q = inst.Q; n = inst.n
    start_wall = time.perf_counter(); start_cpu = time.process_time()
    best_x: np.ndarray | None = None; best_e = float("inf"); proposals = 0; accepted = 0
    scale = max(float(np.std(q)) * max(n, 1), 1e-5)
    for _ in range(int(cfg["sa_restarts"])):
        x = _randomized_feasible_start(inst, rng, int(cfg["initial_randomization_swaps"]))
        qx = q @ x; e = float(x @ qx)
        if e < best_e: best_e = e; best_x = x.copy()
        sweeps = int(cfg["sa_sweeps"])
        for sweep in range(sweeps):
            temp = scale * (0.02 ** (sweep / max(sweeps - 1, 1)))
            for _ in range(n):
                ones = np.where(x > 0.5)[0]; zeros = np.where(x < 0.5)[0]
                i = int(rng.choice(ones)); j = int(rng.choice(zeros))
                cand = x.copy(); cand[i] = 0.0; cand[j] = 1.0; proposals += 1
                if not is_feasible(cand, inst):
                    continue
                de = _swap_delta(q, x, qx, i, j)
                if de <= 0.0 or rng.random() < math.exp(-de / max(temp, 1e-12)):
                    _apply_swap(x, qx, q, i, j); e += de; accepted += 1
                    if e < best_e:
                        best_e = float(e); best_x = x.copy()
    return {
        "available": best_x is not None,
        "x": best_x,
        "energy": float(best_e),
        "feasible": bool(best_x is not None and is_feasible(best_x, inst)),
        "runtime_s": float(time.perf_counter() - start_wall),
        "cpu_s": float(time.process_time() - start_cpu),
        "iterations": int(proposals),
        "acceptance_rate": float(accepted / max(proposals, 1)),
    }


def _local_solve(inst: HardInstance) -> dict[str, Any]:
    cfg = EXECUTION_SPEC["solver_budgets"]
    rng = np.random.default_rng(inst.seed * 5003 + inst.n * 101 + 211)
    q = inst.Q; n = inst.n
    start_wall = time.perf_counter(); start_cpu = time.process_time()
    best_x: np.ndarray | None = None; best_e = float("inf"); tested = 0
    for _ in range(int(cfg["local_restarts"])):
        x = _randomized_feasible_start(inst, rng, int(cfg["initial_randomization_swaps"]))
        qx = q @ x; e = float(x @ qx)
        for _pass in range(int(cfg["local_max_passes"])):
            ones = np.where(x > 0.5)[0]; zeros = np.where(x < 0.5)[0]
            total = len(ones) * len(zeros)
            budget = min(int(cfg["local_candidate_swaps_per_pass"]), total)
            if total == 0:
                break
            # deterministic random subset of candidate swaps under the fixed seed stream
            pairs = [(int(i), int(j)) for i in ones for j in zeros]
            if len(pairs) > budget:
                ids = rng.choice(len(pairs), size=budget, replace=False)
                candidates = [pairs[int(h)] for h in ids]
            else:
                candidates = pairs
            best_move = None; best_delta = -1e-12
            for i, j in candidates:
                tested += 1
                cand = x.copy(); cand[i] = 0.0; cand[j] = 1.0
                if not is_feasible(cand, inst):
                    continue
                de = _swap_delta(q, x, qx, i, j)
                if de < best_delta:
                    best_delta = de; best_move = (i, j)
            if best_move is None:
                break
            _apply_swap(x, qx, q, best_move[0], best_move[1]); e += best_delta
        if e < best_e:
            best_e = float(e); best_x = x.copy()
    return {
        "available": best_x is not None,
        "x": best_x,
        "energy": float(best_e),
        "feasible": bool(best_x is not None and is_feasible(best_x, inst)),
        "runtime_s": float(time.perf_counter() - start_wall),
        "cpu_s": float(time.process_time() - start_cpu),
        "iterations": int(tested),
    }


def execute_instance(n: int, regime: str, seed: int, *, milp_time_limit_s: float | None = None) -> dict[str, Any]:
    inst = build_hard_instance(n, regime, seed)
    started = datetime.now(timezone.utc).isoformat()
    milp = _milp_solve(inst, time_limit_s=milp_time_limit_s)
    sa = _sa_solve(inst)
    local = _local_solve(inst)
    candidates = []
    for name, res in (("MILP", milp), ("SA", sa), ("LOCAL", local)):
        if res.get("available") and res.get("feasible") and np.isfinite(float(res.get("energy", np.nan))):
            candidates.append((name, float(res["energy"])))
    if candidates:
        reference_name, reference_e = min(candidates, key=lambda t: t[1])
    else:
        reference_name, reference_e = "NONE", float("nan")
    heuristic_best = min(float(sa.get("energy", np.inf)), float(local.get("energy", np.inf)))
    if np.isfinite(reference_e) and np.isfinite(heuristic_best):
        heuristic_gap = max(heuristic_best - reference_e, 0.0) / max(abs(reference_e), 1e-12)
    else:
        heuristic_gap = float("nan")

    technical_failure = not (
        bool(milp.get("available"))
        and bool(milp.get("feasible", False))
        and np.isfinite(float(milp.get("runtime_s", np.nan)))
        and bool(sa.get("available"))
        and bool(local.get("available"))
        and np.isfinite(reference_e)
    )
    row = {
        "instance_id": inst.instance_id,
        "N": inst.n,
        "K": inst.k,
        "regime": inst.regime,
        "seed": inst.seed,
        "started_utc": started,
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "execution_status": "TECHNICAL_FAILURE" if technical_failure else "VALID",
        "reference_solver": reference_name,
        "reference_energy": reference_e,
        "milp_available": bool(milp.get("available")),
        "milp_feasible": bool(milp.get("feasible", False)),
        "milp_optimality_certified": bool(milp.get("optimality_certified", False)),
        "milp_status": int(milp.get("status", -999)),
        "milp_message": str(milp.get("message", milp.get("reason", ""))),
        "milp_energy": float(milp.get("energy", np.nan)),
        "milp_runtime_s": float(milp.get("runtime_s", np.nan)),
        "milp_cpu_s": float(milp.get("cpu_s", np.nan)),
        "milp_mip_gap": float(milp.get("mip_gap", np.nan)),
        "milp_node_count": float(milp.get("mip_node_count", np.nan)),
        "milp_dual_bound": float(milp.get("mip_dual_bound", np.nan)),
        "sa_energy": float(sa.get("energy", np.nan)),
        "sa_runtime_s": float(sa.get("runtime_s", np.nan)),
        "sa_cpu_s": float(sa.get("cpu_s", np.nan)),
        "sa_feasible": bool(sa.get("feasible", False)),
        "sa_iterations": int(sa.get("iterations", 0)),
        "local_energy": float(local.get("energy", np.nan)),
        "local_runtime_s": float(local.get("runtime_s", np.nan)),
        "local_cpu_s": float(local.get("cpu_s", np.nan)),
        "local_feasible": bool(local.get("feasible", False)),
        "local_iterations": int(local.get("iterations", 0)),
        "best_heuristic_gap_rel": float(heuristic_gap),
        "best_heuristic_gap_pct": float(100.0 * heuristic_gap) if np.isfinite(heuristic_gap) else float("nan"),
        **inst.metadata,
    }
    return row


def summarize_results(results: pd.DataFrame) -> dict[str, Any]:
    expected = planned_instances()
    if not isinstance(results, pd.DataFrame) or results.empty:
        return {"complete": False, "completed": 0, "expected": len(expected), "outcome": "INDETERMINATE"}
    df = results.copy()
    completed_ids = set(df["instance_id"].astype(str)) if "instance_id" in df else set()
    missing = [x for x in expected["Instance ID"].astype(str) if x not in completed_ids]
    duplicate_ids = int(df["instance_id"].duplicated().sum()) if "instance_id" in df else 0
    technical_failures = int((df.get("execution_status", pd.Series(dtype=str)) != "VALID").sum()) if "execution_status" in df else len(df)

    fam_rows: list[dict[str, Any]] = []
    for (n, regime), g in df.groupby(["N", "regime"], dropna=False):
        runtimes = pd.to_numeric(g["milp_runtime_s"], errors="coerce").dropna().to_numpy(dtype=float)
        gaps = pd.to_numeric(g["best_heuristic_gap_rel"], errors="coerce").dropna().to_numpy(dtype=float)
        median_rt = float(np.median(runtimes)) if runtimes.size else float("nan")
        p95_rt = float(np.quantile(runtimes, 0.95)) if runtimes.size else float("nan")
        hard_frac = float(np.mean(gaps > float(QUBO_SUITE["heuristic_gap_gate"]))) if gaps.size else float("nan")
        valid_count = int(np.sum(g.get("execution_status", pd.Series(index=g.index, dtype=str)).astype(str) == "VALID"))
        runtime_hard = bool((np.isfinite(median_rt) and median_rt >= float(QUBO_SUITE["milp_median_gate_seconds"])) or (np.isfinite(p95_rt) and p95_rt >= float(QUBO_SUITE["milp_p95_gate_seconds"])))
        heuristic_hard = bool(np.isfinite(hard_frac) and hard_frac >= float(QUBO_SUITE["heuristic_hard_fraction_gate"]))
        complete_family = bool(len(g) == len(QUBO_SUITE["seeds"]) and valid_count == len(QUBO_SUITE["seeds"]))
        fam_rows.append({
            "N": int(n), "Regime": str(regime), "Instances": int(len(g)), "Valid": valid_count,
            "MILP median s": median_rt, "MILP p95 s": p95_rt,
            "Heuristic hard fraction": hard_frac,
            "Runtime gate": runtime_hard, "Heuristic gate": heuristic_hard,
            "Family gate": bool(complete_family and runtime_hard and heuristic_hard),
            "Complete family": complete_family,
            "Optimality certified fraction": float(np.mean(g["milp_optimality_certified"].astype(bool))) if "milp_optimality_certified" in g else float("nan"),
        })
    family = pd.DataFrame(fam_rows)
    complete = bool(len(missing) == 0 and duplicate_ids == 0 and len(df) == len(expected))
    if not complete:
        outcome = "IN PROGRESS"
    elif technical_failures > 0 or not bool(family["Complete family"].all()):
        outcome = "INDETERMINATE"
    elif bool(family["Family gate"].any()):
        outcome = "HARDNESS GATE · PASSED"
    else:
        outcome = "HARDNESS GATE · FAILED"
    return {
        "complete": complete,
        "completed": int(len(completed_ids)),
        "expected": int(len(expected)),
        "missing_instance_ids": missing,
        "duplicate_instance_rows": duplicate_ids,
        "technical_failures": technical_failures,
        "outcome": outcome,
        "hardware_eligibility_open": bool(outcome == "HARDNESS GATE · PASSED"),
        "family_summary": family,
    }


def default_results_root() -> Path:
    return Path.cwd() / "outputs" / "quantum_phase2" / "qhardness"


def _active_pointer(root: Path) -> Path:
    return root / "ACTIVE_RUN.json"


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def initialize_run(root: str | Path | None = None) -> dict[str, Any]:
    root = Path(root or default_results_root()); root.mkdir(parents=True, exist_ok=True)
    pointer = _active_pointer(root)
    if pointer.exists():
        existing = _read_json(pointer, {}) or {}
        run_dir = root / str(existing.get("run_id", ""))
        if run_dir.exists():
            # Confirmatory reruns of the same sealed 120-instance suite are forbidden.
            # An incomplete run may be resumed; a finalized run remains the active immutable record.
            return load_run_status(run_dir)
    now = datetime.now(timezone.utc)
    run_id = f"QUBO_PHASEII_{now.strftime('%Y%m%dT%H%M%SZ')}_{PROTOCOL_SHA[:8]}_{EXECUTION_SPEC_SHA[:8]}"
    run_dir = root / run_id; run_dir.mkdir(parents=True, exist_ok=False)
    env = execution_environment()
    plan = planned_instances()
    manifest = {
        "run_id": run_id,
        "status": "INITIALIZED",
        "created_utc": now.isoformat(),
        "protocol_key": PROTOCOL_KEY,
        "protocol_sha": PROTOCOL_SHA,
        "source_evidence_id": SOURCE_EVIDENCE_ID,
        "phase2_manifest_sha": PHASE2_MANIFEST_SHA,
        "execution_spec_sha": EXECUTION_SPEC_SHA,
        "executor_code_sha": executor_code_sha(),
        "environment": env,
        "environment_sha": environment_sha(env),
        "plan_sha": _sha(plan.to_dict(orient="records"), 20),
        "planned_instances": int(len(plan)),
        "completed_instances": 0,
    }
    (run_dir / "execution_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    (run_dir / "execution_spec.json").write_text(json.dumps(execution_spec_payload(), indent=2, sort_keys=True), encoding="utf-8")
    plan.to_csv(run_dir / "planned_instances.csv", index=False)
    pointer.write_text(json.dumps({"run_id": run_id}, indent=2), encoding="utf-8")
    return load_run_status(run_dir)


def _results_frame(run_dir: Path) -> pd.DataFrame:
    path = run_dir / "results.jsonl"
    if not path.exists():
        return pd.DataFrame()
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    return pd.DataFrame(rows)


def _validate_run_integrity(run_dir: Path) -> tuple[bool, str]:
    manifest = _read_json(run_dir / "execution_manifest.json", {}) or {}
    if str(manifest.get("protocol_sha")) != PROTOCOL_SHA:
        return False, "Protocol SHA mismatch"
    if str(manifest.get("execution_spec_sha")) != EXECUTION_SPEC_SHA:
        return False, "Execution specification SHA mismatch"
    if str(manifest.get("executor_code_sha")) != executor_code_sha():
        return False, "Executor code SHA mismatch"
    if str(manifest.get("environment_sha")) != environment_sha():
        return False, "Environment fingerprint changed; confirmatory resume is locked"
    plan = planned_instances()
    if str(manifest.get("plan_sha")) != _sha(plan.to_dict(orient="records"), 20):
        return False, "Canonical plan SHA mismatch"
    return True, "OK"


def load_run_status(run_dir: str | Path | None = None, root: str | Path | None = None) -> dict[str, Any]:
    if run_dir is None:
        rootp = Path(root or default_results_root())
        pointer = _read_json(_active_pointer(rootp), {}) or {}
        rid = str(pointer.get("run_id", ""))
        if not rid:
            return {"exists": False, "status": "NOT INITIALIZED"}
        run_dir = rootp / rid
    run_dir = Path(run_dir)
    if not run_dir.exists():
        return {"exists": False, "status": "NOT INITIALIZED"}
    manifest = _read_json(run_dir / "execution_manifest.json", {}) or {}
    results = _results_frame(run_dir)
    summary = summarize_results(results)
    worker = _read_json(run_dir / "worker_status.json", {}) or {}
    if str(worker.get("status")) == "RUNNING":
        pid = int(worker.get("pid", 0) or 0)
        alive = False
        if pid > 0:
            try:
                os.kill(pid, 0); alive = True
            except OSError:
                alive = False
        if not alive:
            worker = {**worker, "status": "INTERRUPTED", "reason": "worker PID is no longer alive; sealed run may be resumed"}
    finalized = _read_json(run_dir / "FINALIZED.json", None)
    ok, reason = _validate_run_integrity(run_dir)
    return {
        "exists": True,
        "run_dir": str(run_dir),
        "run_id": str(manifest.get("run_id", run_dir.name)),
        "manifest": manifest,
        "results": results,
        "summary": summary,
        "worker": worker,
        "finalized": finalized,
        "integrity_ok": ok,
        "integrity_reason": reason,
        "status": str((finalized or {}).get("outcome") or worker.get("status") or manifest.get("status", "INITIALIZED")),
    }


def _append_result(run_dir: Path, row: dict[str, Any]) -> None:
    path = run_dir / "results.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True, default=str) + "\n")
        f.flush(); os.fsync(f.fileno())


def _write_worker_status(run_dir: Path, **kwargs: Any) -> None:
    payload = {"updated_utc": datetime.now(timezone.utc).isoformat(), **kwargs}
    (run_dir / "worker_status.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _warmup_milp() -> None:
    try:
        from scipy.optimize import Bounds, LinearConstraint, milp
        c = np.array([1.0, 2.0]); A = np.array([[1.0, 1.0]])
        milp(c, integrality=np.ones(2), bounds=Bounds([0,0],[1,1]), constraints=LinearConstraint(A,[1],[1]), options={"time_limit":0.5})
    except Exception:
        pass


def run_worker(run_dir: str | Path) -> dict[str, Any]:
    run_dir = Path(run_dir)
    ok, reason = _validate_run_integrity(run_dir)
    if not ok:
        _write_worker_status(run_dir, status="PROTOCOL VIOLATION", reason=reason)
        return load_run_status(run_dir)
    if (run_dir / "FINALIZED.json").exists():
        return load_run_status(run_dir)
    _write_worker_status(run_dir, status="RUNNING", pid=os.getpid(), current_instance=None)
    _warmup_milp()
    plan = planned_instances()
    existing = _results_frame(run_dir)
    done = set(existing["instance_id"].astype(str)) if not existing.empty and "instance_id" in existing else set()
    for _, rec in plan.iterrows():
        iid = str(rec["Instance ID"])
        if iid in done:
            continue
        ok, reason = _validate_run_integrity(run_dir)
        if not ok:
            _write_worker_status(run_dir, status="PROTOCOL VIOLATION", reason=reason, current_instance=iid)
            return load_run_status(run_dir)
        _write_worker_status(run_dir, status="RUNNING", pid=os.getpid(), current_instance=iid, completed=len(done), total=len(plan))
        try:
            row = execute_instance(int(rec["N"]), str(rec["Regime"]), int(rec["Seed"]))
        except Exception as exc:
            row = {
                "instance_id": iid,
                "N": int(rec["N"]), "K": int(rec["K"]), "regime": str(rec["Regime"]), "seed": int(rec["Seed"]),
                "started_utc": datetime.now(timezone.utc).isoformat(), "finished_utc": datetime.now(timezone.utc).isoformat(),
                "execution_status": "TECHNICAL_FAILURE", "error": f"{type(exc).__name__}: {exc}",
            }
        row["protocol_sha"] = PROTOCOL_SHA
        row["execution_spec_sha"] = EXECUTION_SPEC_SHA
        row["environment_sha"] = environment_sha()
        _append_result(run_dir, row); done.add(iid)
        manifest = _read_json(run_dir / "execution_manifest.json", {}) or {}
        manifest["status"] = "RUNNING"; manifest["completed_instances"] = len(done); manifest["updated_utc"] = datetime.now(timezone.utc).isoformat()
        (run_dir / "execution_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return finalize_run(run_dir)


def _checksums(run_dir: Path, files: Iterable[Path]) -> str:
    lines = []
    for p in files:
        if p.exists() and p.is_file():
            h = hashlib.sha256(p.read_bytes()).hexdigest()
            lines.append(f"{h}  {p.name}")
    text = "\n".join(lines) + ("\n" if lines else "")
    (run_dir / "SHA256.txt").write_text(text, encoding="utf-8")
    return text


def finalize_run(run_dir: str | Path) -> dict[str, Any]:
    run_dir = Path(run_dir)
    results = _results_frame(run_dir)
    summary = summarize_results(results)
    results.to_csv(run_dir / "results.csv", index=False)
    fam = summary.get("family_summary")
    if isinstance(fam, pd.DataFrame):
        fam.to_csv(run_dir / "family_summary.csv", index=False)
        family_json = fam.to_dict(orient="records")
    else:
        family_json = []
    summary_json = {k:v for k,v in summary.items() if k != "family_summary"}
    summary_json["family_summary"] = family_json
    summary_json.update({
        "protocol_sha": PROTOCOL_SHA,
        "execution_spec_sha": EXECUTION_SPEC_SHA,
        "finalized_utc": datetime.now(timezone.utc).isoformat(),
    })
    (run_dir / "summary.json").write_text(json.dumps(summary_json, indent=2, sort_keys=True, default=str), encoding="utf-8")
    finalized = {
        "outcome": str(summary["outcome"]),
        "hardware_eligibility_open": bool(summary.get("hardware_eligibility_open", False)),
        "completed_instances": int(summary.get("completed", 0)),
        "expected_instances": int(summary.get("expected", 120)),
        "technical_failures": int(summary.get("technical_failures", 0)),
        "protocol_sha": PROTOCOL_SHA,
        "execution_spec_sha": EXECUTION_SPEC_SHA,
        "finalized_utc": datetime.now(timezone.utc).isoformat(),
    }
    (run_dir / "FINALIZED.json").write_text(json.dumps(finalized, indent=2, sort_keys=True), encoding="utf-8")
    manifest = _read_json(run_dir / "execution_manifest.json", {}) or {}
    manifest["status"] = "FINALIZED"; manifest["completed_instances"] = int(summary.get("completed", 0)); manifest["finalized_utc"] = finalized["finalized_utc"]
    (run_dir / "execution_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    _write_worker_status(run_dir, status="FINALIZED", outcome=finalized["outcome"], completed=finalized["completed_instances"], total=finalized["expected_instances"])
    files = [run_dir / x for x in ["execution_manifest.json","execution_spec.json","planned_instances.csv","results.jsonl","results.csv","family_summary.csv","summary.json","FINALIZED.json","worker_status.json"]]
    _checksums(run_dir, files)
    archive = shutil.make_archive(str(run_dir), "zip", root_dir=run_dir)
    finalized["archive"] = archive
    return load_run_status(run_dir)


def launch_background_worker(run_dir: str | Path) -> dict[str, Any]:
    import subprocess
    run_dir = Path(run_dir)
    status = load_run_status(run_dir)
    if not status.get("integrity_ok", False):
        return {"launched": False, "reason": status.get("integrity_reason", "integrity lock")}
    if status.get("finalized"):
        return {"launched": False, "reason": "run already finalized"}
    worker = status.get("worker") or {}
    pid = int(worker.get("pid", 0) or 0)
    if pid > 0 and str(worker.get("status")) == "RUNNING":
        try:
            os.kill(pid, 0)
            return {"launched": False, "reason": f"worker already running (PID {pid})", "pid": pid}
        except OSError:
            pass
    package_root = Path(__file__).resolve().parents[1]
    log_path = run_dir / "worker.log"
    log = log_path.open("ab")
    proc = subprocess.Popen(
        [sys.executable, "-m", "quantum_research_lab.phase2_qhardness", "--worker", str(run_dir)],
        cwd=str(package_root), stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
    )
    log.close()
    _write_worker_status(run_dir, status="RUNNING", pid=int(proc.pid), current_instance=None, launched_utc=datetime.now(timezone.utc).isoformat())
    return {"launched": True, "pid": int(proc.pid), "log": str(log_path)}


def artifact_zip_bytes(run_dir: str | Path) -> bytes | None:
    run_dir = Path(run_dir)
    zip_path = Path(str(run_dir) + ".zip")
    if not zip_path.exists() and (run_dir / "FINALIZED.json").exists():
        shutil.make_archive(str(run_dir), "zip", root_dir=run_dir)
    try:
        return zip_path.read_bytes()
    except Exception:
        return None


def _main() -> int:
    parser = argparse.ArgumentParser(description="QUBO Phase-II hardness confirmatory worker")
    parser.add_argument("--worker", type=str, default="", help="Run/resume canonical worker in the supplied run directory")
    parser.add_argument("--spec", action="store_true", help="Print sealed execution specification")
    args = parser.parse_args()
    if args.spec:
        print(json.dumps(execution_spec_payload(), indent=2, sort_keys=True)); return 0
    if args.worker:
        status = run_worker(args.worker)
        print(json.dumps({"status": status.get("status"), "summary": {k:v for k,v in (status.get("summary") or {}).items() if k != "family_summary"}}, indent=2, default=str))
        return 0
    parser.print_help(); return 0


if __name__ == "__main__":
    raise SystemExit(_main())
