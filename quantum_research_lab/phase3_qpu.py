from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import platform
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .phase2_qhardness import (
    build_hard_instance,
    default_results_root as phase2_results_root,
    load_run_status as load_phase2_run_status,
)

PHASE3_VERSION = "PHASE III · EQUAL-OBJECTIVE QPU PREPARATION · V1"
PHASE3_PREP_SPEC_VERSION = "QPU COMPILATION READINESS SPEC · V1"
PHASE2_PROTOCOL_SHA = "8E5EF191FAE97A75"
PHASE2_EXECUTION_SPEC_SHA = "40D3225B0AFC86BC01DD"

# This is an engineering/readiness contract, not a confirmatory QPU protocol.
# It can be used before the classical Phase-II run finishes, but it cannot seal
# a hardware benchmark until the immutable 120/120 artifact exists and passes.
PREPARATION_SPEC: dict[str, Any] = {
    "phase3_version": PHASE3_VERSION,
    "preparation_spec_version": PHASE3_PREP_SPEC_VERSION,
    "phase2_parent_protocol_sha": PHASE2_PROTOCOL_SHA,
    "phase2_parent_execution_spec_sha": PHASE2_EXECUTION_SPEC_SHA,
    "candidate_selection_rule": (
        "Among Phase-II families with Family gate = TRUE and Complete family = TRUE, choose the smallest N; "
        "tie-break by hardware encoding complexity BASE < PAIRWISE < BANDS. All 8 preregistered seeds remain in scope."
    ),
    "encoding_policy": {
        "BASE": "Exact-K warm-start basis state + number-preserving XY ring mixer + economic QUBO cost Hamiltonian.",
        "PAIRWISE": "Exact-K warm-start basis state + XY ring mixer + economic QUBO plus witness-safe pairwise-exclusion penalties.",
        "BANDS": (
            "No executable hardware circuit is claimed until group-count and factor-exposure bands have a sealed reversible "
            "feasibility oracle or an auditable slack/fixed-point penalty encoding. Abstract resource envelopes are diagnostic only."
        ),
    },
    "hardware_submission_policy": "V2.9 does not submit jobs. Hardware execution requires a later sealed Phase-III benchmark protocol.",
    "provider_policy": {
        "ibm_quantum_compute": "First-class readiness path via qiskit-ibm-runtime when installed and authenticated.",
        "aws_braket": "SDK presence is inventoried only in V2.9; no task submission is implemented.",
    },
    "sealing_requirements": [
        "Phase-II QUBO run finalized 120/120 with integrity OK",
        "Phase-II HARDNESS GATE PASSED",
        "Selected family is one of the completed gate-passing families",
        "All 8 sealed seeds included",
        "Named hardware backend and calibration snapshot recorded",
        "Equal-objective circuit/encoding blueprint marked executable for the selected regime",
        "Resource/capacity check passes for the selected backend",
    ],
}


def _stable_json(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _sha(payload: Any, length: int = 20) -> str:
    return hashlib.sha256(_stable_json(payload)).hexdigest()[: int(length)].upper()


PREPARATION_SPEC_SHA = _sha(PREPARATION_SPEC, 20)


def preparation_spec_payload() -> dict[str, Any]:
    return {**PREPARATION_SPEC, "preparation_spec_sha": PREPARATION_SPEC_SHA}


def sdk_inventory() -> pd.DataFrame:
    rows = []
    for key, module, role in [
        ("Qiskit", "qiskit", "Circuit construction / transpilation"),
        ("IBM Quantum Compute", "qiskit_ibm_runtime", "Authenticated IBM hardware access"),
        ("Qiskit Aer", "qiskit_aer", "Local/noisy simulator control only"),
        ("Amazon Braket", "braket", "Provider inventory only in V2.9"),
    ]:
        available = bool(importlib.util.find_spec(module))
        version = "N/A"
        if available:
            try:
                mod = __import__(module)
                version = str(getattr(mod, "__version__", "installed"))
            except Exception:
                version = "installed"
        rows.append({"SDK": key, "Module": module, "Available": available, "Version": version, "Role": role})
    return pd.DataFrame(rows)


def phase2_hardness_gate(root: str | Path | None = None) -> dict[str, Any]:
    status = load_phase2_run_status(root=root or phase2_results_root())
    if not status.get("exists"):
        return {
            "state": "WAITING · PHASE-II RUN",
            "ready": False,
            "reason": "No active Phase-II QUBO run artifact was found.",
            "status": status,
            "eligible_families": pd.DataFrame(),
            "recommended_family": None,
        }
    summary = status.get("summary") or {}
    finalized = status.get("finalized") or {}
    fam = summary.get("family_summary")
    if not isinstance(fam, pd.DataFrame):
        fam = pd.DataFrame()
    provisional = fam.copy()
    if not provisional.empty:
        provisional = provisional[(provisional.get("Family gate", False).astype(bool)) & (provisional.get("Complete family", False).astype(bool))].copy()
    final_complete = bool(finalized) and int(finalized.get("completed_instances", 0)) == 120 and int(finalized.get("technical_failures", 0)) == 0
    integrity_ok = bool(status.get("integrity_ok", False))
    gate_pass = bool(final_complete and integrity_ok and finalized.get("hardware_eligibility_open", False) and str(finalized.get("outcome")) == "HARDNESS GATE · PASSED")
    if not bool(finalized):
        state = "WAITING · 120/120 FINALIZATION"
        reason = f"Phase-II run is not finalized ({int(summary.get('completed', 0))}/120 recorded). Provisional family gates cannot unlock QPU work."
    elif not integrity_ok:
        state = "BLOCKED · PHASE-II INTEGRITY"
        reason = str(status.get("integrity_reason", "Phase-II artifact integrity check failed."))
    elif not gate_pass:
        state = "BLOCKED · HARDNESS GATE NOT PASSED"
        reason = f"Final Phase-II outcome is {finalized.get('outcome', summary.get('outcome', 'UNKNOWN'))}."
    else:
        state = "UNLOCKED · CLASSICAL HARDNESS ESTABLISHED"
        reason = "The immutable 120/120 Phase-II artifact passed the preregistered classical-hardness gate."
    eligible = provisional.copy() if gate_pass else pd.DataFrame(columns=provisional.columns)
    recommended = select_candidate_family(eligible) if not eligible.empty else None
    return {
        "state": state,
        "ready": gate_pass,
        "reason": reason,
        "status": status,
        "eligible_families": eligible.reset_index(drop=True),
        "provisional_families": provisional.reset_index(drop=True),
        "recommended_family": recommended,
    }


def select_candidate_family(eligible_families: pd.DataFrame) -> dict[str, Any] | None:
    if not isinstance(eligible_families, pd.DataFrame) or eligible_families.empty:
        return None
    rank = {"BASE": 0, "PAIRWISE": 1, "BANDS": 2}
    df = eligible_families.copy()
    df["_regime_rank"] = df["Regime"].astype(str).str.upper().map(rank).fillna(99)
    df = df.sort_values(["N", "_regime_rank", "Regime"], kind="stable")
    row = df.iloc[0].drop(labels=["_regime_rank"]).to_dict()
    row["Selection rule"] = "smallest N, then BASE < PAIRWISE < BANDS"
    return row


def _objective_structure(inst: Any, tol: float = 1e-12) -> dict[str, Any]:
    q = np.asarray(inst.Q, dtype=float)
    n = int(inst.n)
    upper = np.triu(np.abs(q) > float(tol), 1)
    offdiag = int(np.sum(upper))
    diag = int(np.sum(np.abs(np.diag(q)) > float(tol)))
    dense_pairs = int(n * (n - 1) // 2)
    return {
        "N": n,
        "K": int(inst.k),
        "economic_linear_terms": diag,
        "economic_quadratic_terms": offdiag,
        "economic_pair_density": float(offdiag / max(dense_pairs, 1)),
        "economic_abs_coeff_sum": float(np.sum(np.abs(q))),
        "economic_max_abs_coeff": float(np.max(np.abs(q))) if q.size else 0.0,
    }


def _bands_envelopes(inst: Any) -> list[dict[str, Any]]:
    # Diagnostic resource envelopes only. They are intentionally not treated as compiled circuits.
    rows = []
    n = int(inst.n)
    group_sizes = [len(x.get("indices", [])) for x in getattr(inst, "group_bands", [])]
    group_counter_bits = int(sum(max(1, math.ceil(math.log2(max(s, 1) + 1))) for s in group_sizes))
    for fp in (8, 12, 16):
        factor_regs = int(len(getattr(inst, "factor_bands", [])) * fp)
        comparator_anc = int(len(group_sizes) * 2 + len(getattr(inst, "factor_bands", [])) * max(2, math.ceil(fp / 4)))
        arithmetic_scratch = int(max(group_counter_bits, fp + 2))
        logical = int(n + group_counter_bits + factor_regs + comparator_anc + arithmetic_scratch)
        # Coarse reversible arithmetic envelope, used only as an order-of-magnitude diagnostic.
        twoq_low = int(max(1, n) * max(1, len(group_sizes) + len(getattr(inst, "factor_bands", []))) * fp * 4)
        twoq_high = int(twoq_low * 4)
        rows.append({
            "Fixed-point bits": fp,
            "Data qubits": n,
            "Count register bits": group_counter_bits,
            "Factor register bits": factor_regs,
            "Comparator ancillas": comparator_anc,
            "Scratch ancillas": arithmetic_scratch,
            "Logical qubits envelope": logical,
            "2Q gates / constraint-oracle layer low": twoq_low,
            "2Q gates / constraint-oracle layer high": twoq_high,
            "Status": "ABSTRACT ENVELOPE · NOT COMPILED",
        })
    return rows


def family_encoding_audit(n: int, regime: str, seed: int) -> dict[str, Any]:
    inst = build_hard_instance(int(n), str(regime), int(seed))
    base = _objective_structure(inst)
    regime = str(regime).upper()
    pair_count = int(len(getattr(inst, "pairwise_exclusions", [])))
    group_count = int(len(getattr(inst, "group_bands", [])))
    factor_count = int(len(getattr(inst, "factor_bands", [])))
    result: dict[str, Any] = {
        **base,
        "regime": regime,
        "seed": int(seed),
        "pairwise_exclusions": pair_count,
        "group_bands": group_count,
        "factor_bands": factor_count,
        "initial_state": "witness-feasible computational basis state",
        "mixer": "number-preserving XY ring",
        "seeds_in_hardware_scope": 8,
    }
    if regime == "BASE":
        result.update({
            "encoding_status": "BLUEPRINT AVAILABLE",
            "encoding_exactness": "Exact cardinality is preserved by the mixer; feasible-state objective equals the Phase-II economic QUBO.",
            "logical_qubits_min": int(inst.n),
            "extra_constraint_qubits": 0,
            "constraint_resource_envelopes": [],
        })
    elif regime == "PAIRWISE":
        # A conservative penalty scale is an engineering diagnostic; it is not sealed for hardware use here.
        safe_penalty_bound = float(2.0 * np.sum(np.abs(inst.Q)) + 1e-9)
        result.update({
            "encoding_status": "BLUEPRINT AVAILABLE · PENALTY AUDIT REQUIRED BEFORE SEAL",
            "encoding_exactness": "Exact cardinality is mixer-preserved; pairwise exclusions require an auditable penalty coefficient before hardware execution.",
            "logical_qubits_min": int(inst.n),
            "extra_constraint_qubits": 0,
            "pairwise_penalty_safe_bound_diagnostic": safe_penalty_bound,
            "constraint_resource_envelopes": [],
        })
    else:
        envs = _bands_envelopes(inst)
        result.update({
            "encoding_status": "BLOCKED · EXACT BANDS ORACLE NOT SEALED",
            "encoding_exactness": (
                "Group-count and real-valued factor-exposure bands are hard constraints in Phase II. V2.9 does not replace them with an arbitrary penalty. "
                "A reversible feasibility oracle or audited fixed-point/slack encoding must be sealed first."
            ),
            "logical_qubits_min": int(inst.n),
            "extra_constraint_qubits": None,
            "constraint_resource_envelopes": envs,
            "hardware_executable": False,
            "compiler_status": "EXACT BANDS LOGICAL ORACLE REQUIRED BEFORE GATE-LEVEL COMPILATION",
        })
    # p=1 blueprint estimate before routing/transpilation.
    qterms = int(base["economic_quadratic_terms"])
    result["logical_cost_2q_terms_p1"] = int(qterms + pair_count)
    result["xy_mixer_2q_blocks_p1"] = int(inst.n)
    result["logical_2q_interactions_p1_pretranspile"] = int(qterms + pair_count + 2 * inst.n)
    return result


def family_seed_audits(n: int, regime: str, seeds: list[int] | tuple[int, ...] | None = None) -> pd.DataFrame:
    seeds = list(seeds or [1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807])
    rows = []
    for seed in seeds:
        a = family_encoding_audit(n, regime, int(seed))
        rows.append({
            "N": a["N"], "Regime": a["regime"], "Seed": int(seed),
            "Encoding status": a["encoding_status"],
            "Economic 2Q terms": a["economic_quadratic_terms"],
            "Pairwise exclusions": a["pairwise_exclusions"],
            "Group bands": a["group_bands"], "Factor bands": a["factor_bands"],
            "Logical qubits min": a["logical_qubits_min"],
            "Pre-transpile 2Q interactions p=1": a["logical_2q_interactions_p1_pretranspile"],
        })
    return pd.DataFrame(rows)


def backend_capacity_assessment(encoding: dict[str, Any], backend: dict[str, Any] | None) -> dict[str, Any]:
    if not backend:
        return {"status": "WAITING · BACKEND", "capacity_ok": False, "reason": "No hardware backend snapshot selected."}
    n_backend = int(backend.get("num_qubits", 0) or 0)
    status = str(encoding.get("encoding_status", ""))
    if status.startswith("BLOCKED"):
        return {
            "status": "BLOCKED · ENCODING",
            "capacity_ok": False,
            "reason": str(encoding.get("encoding_exactness", "Equal-objective encoding is not executable.")),
            "backend_qubits": n_backend,
        }
    required = int(encoding.get("logical_qubits_min", 0) or 0)
    ok = bool(n_backend >= required and backend.get("operational", True))
    return {
        "status": "CAPACITY PASS" if ok else "CAPACITY FAIL",
        "capacity_ok": ok,
        "required_logical_qubits_min": required,
        "backend_qubits": n_backend,
        "reason": "Backend has sufficient raw qubits for the logical blueprint; routing/depth still require transpilation." if ok else "Raw backend qubit capacity or operational status is insufficient.",
    }


def _backend_name(backend: Any) -> str:
    name = getattr(backend, "name", None)
    if callable(name):
        try:
            name = name()
        except Exception:
            name = None
    return str(name or "UNKNOWN")


def _backend_num_qubits(backend: Any) -> int:
    for attr in ("num_qubits", "n_qubits"):
        value = getattr(backend, attr, None)
        if value is not None:
            try:
                return int(value)
            except Exception:
                pass
    cfg = getattr(backend, "configuration", None)
    if callable(cfg):
        try:
            c = cfg()
            return int(getattr(c, "n_qubits", 0) or 0)
        except Exception:
            pass
    return 0


def _backend_snapshot(backend: Any) -> dict[str, Any]:
    status_obj = None
    try:
        status_obj = backend.status()
    except Exception:
        pass
    basis = []
    try:
        basis = sorted(str(x) for x in getattr(backend, "operation_names", []) or [])
    except Exception:
        basis = []
    coupling_edges = 0
    try:
        cm = getattr(backend, "coupling_map", None)
        if cm is not None:
            edges = cm.get_edges() if hasattr(cm, "get_edges") else list(cm)
            coupling_edges = len(list(edges))
    except Exception:
        coupling_edges = 0
    snap = {
        "backend_name": _backend_name(backend),
        "num_qubits": _backend_num_qubits(backend),
        "operational": bool(getattr(status_obj, "operational", True)) if status_obj is not None else True,
        "pending_jobs": int(getattr(status_obj, "pending_jobs", 0) or 0) if status_obj is not None else 0,
        "basis_operations": basis,
        "coupling_edges": int(coupling_edges),
        "captured_utc": datetime.now(timezone.utc).isoformat(),
    }
    snap["snapshot_sha"] = _sha(snap, 16)
    return snap


def discover_ibm_backends(token: str | None = None, instance: str | None = None, saved_account_ok: bool = True) -> dict[str, Any]:
    if not importlib.util.find_spec("qiskit_ibm_runtime"):
        return {"available": False, "reason": "qiskit-ibm-runtime is not installed.", "backends": pd.DataFrame(), "snapshots": {}}
    try:
        from qiskit_ibm_runtime import QiskitRuntimeService
    except Exception as exc:
        return {"available": False, "reason": f"IBM runtime import failed: {exc}", "backends": pd.DataFrame(), "snapshots": {}}
    kwargs: dict[str, Any] = {}
    if token:
        kwargs["token"] = str(token).strip()
    if instance:
        kwargs["instance"] = str(instance).strip()
    # IBM's current service uses the ibm_quantum_platform channel. Fall back to
    # account defaults for compatibility with existing saved credentials.
    service = None
    errors: list[str] = []
    for channel in ("ibm_quantum_platform", None):
        try:
            call_kwargs = dict(kwargs)
            if channel is not None:
                call_kwargs["channel"] = channel
            if not token and not saved_account_ok:
                raise RuntimeError("No session token supplied and saved-account lookup disabled.")
            service = QiskitRuntimeService(**call_kwargs)
            break
        except Exception as exc:
            errors.append(f"{channel or 'default'}: {type(exc).__name__}: {exc}")
    if service is None:
        return {"available": False, "reason": " | ".join(errors), "backends": pd.DataFrame(), "snapshots": {}}
    try:
        backends = list(service.backends())
    except Exception as exc:
        return {"available": False, "reason": f"Backend discovery failed: {exc}", "backends": pd.DataFrame(), "snapshots": {}, "service": service}
    snaps = {_backend_name(b): _backend_snapshot(b) for b in backends}
    table = pd.DataFrame(list(snaps.values()))
    if not table.empty:
        table = table.sort_values(["operational", "num_qubits", "pending_jobs"], ascending=[False, False, True], kind="stable")
    return {"available": True, "reason": "OK", "backends": table.reset_index(drop=True), "snapshots": snaps, "service": service, "backend_objects": {_backend_name(b): b for b in backends}}


def build_qiskit_topology_probe(n: int, regime: str, seed: int, *, p: int = 1, gamma: float = 0.5, beta: float = 0.35):
    """Build a topology/depth probe for BASE/PAIRWISE only.

    This is NOT a performance circuit and NOT a sealed QPU protocol. The numeric
    angles are arbitrary engineering probes used solely to estimate routed depth.
    """
    if not importlib.util.find_spec("qiskit"):
        raise RuntimeError("qiskit is not installed")
    from qiskit import QuantumCircuit
    try:
        from qiskit.circuit.library import RXXGate, RYYGate
    except Exception:
        RXXGate = RYYGate = None
    inst = build_hard_instance(int(n), str(regime), int(seed))
    regime = str(regime).upper()
    if regime == "BANDS":
        raise RuntimeError("BANDS exact-objective circuit is intentionally blocked until a sealed band-constraint oracle/encoding exists.")
    q = np.asarray(inst.Q, dtype=float).copy()
    if regime == "PAIRWISE":
        # Diagnostic only. We use a conservative bound so infeasible pair states
        # cannot be lower than the entire economic coefficient envelope. This
        # coefficient must be independently audited before a real protocol seal.
        M = float(2.0 * np.sum(np.abs(q)) + 1e-9)
        for i, j in inst.pairwise_exclusions:
            q[i, j] += M / 2.0
            q[j, i] += M / 2.0
    n = int(inst.n)
    qc = QuantumCircuit(n, n)
    for idx in np.where(inst.witness > 0)[0]:
        qc.x(int(idx))

    # Map x'Qx to Ising coefficients under x=(1-Z)/2.
    # For symmetric Q: x'Qx = const + sum h_i Z_i + sum_{i<j} J_ij Z_iZ_j.
    diag = np.diag(q)
    row_off = np.sum(q, axis=1) - diag
    h = -0.5 * diag - 0.5 * row_off
    for _layer in range(max(int(p), 1)):
        for i in range(n):
            if abs(float(h[i])) > 1e-14:
                qc.rz(2.0 * float(gamma) * float(h[i]), i)
        for i in range(n):
            for j in range(i + 1, n):
                Jij = 0.5 * float(q[i, j])
                if abs(Jij) > 1e-14:
                    qc.rzz(2.0 * float(gamma) * Jij, i, j)
        # Number-preserving XY ring. RXX and RYY implement the two commuting
        # components on each edge; overlapping edges are intentionally serialized.
        for i in range(n):
            j = (i + 1) % n
            if RXXGate is not None and RYYGate is not None:
                qc.append(RXXGate(float(beta)), [i, j])
                qc.append(RYYGate(float(beta)), [i, j])
            else:
                qc.rxx(float(beta), i, j)
                qc.ryy(float(beta), i, j)
    qc.measure(range(n), range(n))
    return qc


def transpile_probe(backend_obj: Any, n: int, regime: str, seed: int, *, p: int = 1, optimization_level: int = 3) -> dict[str, Any]:
    if not importlib.util.find_spec("qiskit"):
        return {"available": False, "reason": "qiskit is not installed."}
    try:
        from qiskit import transpile
        qc = build_qiskit_topology_probe(n, regime, seed, p=int(p))
        tqc = transpile(qc, backend=backend_obj, optimization_level=int(optimization_level), seed_transpiler=1701)
        ops = {str(k): int(v) for k, v in tqc.count_ops().items()}
        twoq_names = {"cx", "cz", "ecr", "rzz", "rxx", "ryy", "iswap", "swap"}
        twoq = int(sum(v for k, v in ops.items() if k.lower() in twoq_names))
        return {
            "available": True,
            "backend": _backend_name(backend_obj),
            "N": int(n), "regime": str(regime).upper(), "seed": int(seed), "p": int(p),
            "num_qubits": int(tqc.num_qubits), "depth": int(tqc.depth() or 0), "size": int(tqc.size() or 0),
            "two_qubit_gate_count_proxy": twoq,
            "count_ops": ops,
            "optimization_level": int(optimization_level),
            "probe_only": True,
            "note": "Topology/depth probe only; arbitrary fixed angles, no hardware execution and no performance inference.",
        }
    except Exception as exc:
        return {"available": False, "reason": f"Transpilation probe failed: {type(exc).__name__}: {exc}"}


def phase3_protocol_draft(
    phase2_gate: dict[str, Any],
    family: dict[str, Any] | None,
    backend_snapshot: dict[str, Any] | None,
    encoding_audit: dict[str, Any] | None,
    *,
    depth_schedule: tuple[int, ...] = (1, 2, 3),
    shots_per_circuit: int = 4096,
    hardware_repeats: int = 30,
) -> dict[str, Any]:
    fam = dict(family or {})
    snap = dict(backend_snapshot or {})
    audit = dict(encoding_audit or {})
    status = phase2_gate.get("status") or {}
    finalized = status.get("finalized") or {}
    parent_run = str(status.get("run_id", "N/A"))
    parent_final_sha = "N/A"
    run_dir = status.get("run_dir")
    if run_dir:
        p = Path(run_dir) / "FINALIZED.json"
        if p.exists():
            parent_final_sha = hashlib.sha256(p.read_bytes()).hexdigest()[:20].upper()
    payload = {
        "phase3_version": PHASE3_VERSION,
        "preparation_spec_sha": PREPARATION_SPEC_SHA,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "parent_phase2": {
            "run_id": parent_run,
            "finalized_sha": parent_final_sha,
            "protocol_sha": PHASE2_PROTOCOL_SHA,
            "execution_spec_sha": PHASE2_EXECUTION_SPEC_SHA,
            "outcome": finalized.get("outcome"),
        },
        "selected_family": {
            "N": int(fam.get("N", 0) or 0),
            "Regime": str(fam.get("Regime", "")),
            "all_seeds": [1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807],
            "selection_note": str(fam.get("Selection rule", "user-selected from eligible Phase-II families")),
        },
        "encoding": {
            "status": audit.get("encoding_status"),
            "initial_state": audit.get("initial_state"),
            "mixer": audit.get("mixer"),
            "exactness": audit.get("encoding_exactness"),
            "hardware_executable": audit.get("hardware_executable", True),
            "bands_oracle_sha": audit.get("bands_oracle_sha"),
            "bands_oracle_bits": audit.get("bands_oracle_bits"),
            "bands_oracle_mode": audit.get("bands_oracle_mode"),
            "max_factor_accumulator_bits": audit.get("max_factor_accumulator_bits"),
            "max_dyadic_denominator_exponent": audit.get("max_dyadic_denominator_exponent"),
            "logical_qubits_min": audit.get("logical_qubits_min"),
            "compiler_status": audit.get("compiler_status"),
        },
        "backend_snapshot": snap,
        "proposed_measurement_contract": {
            "depth_schedule": [int(x) for x in depth_schedule],
            "shots_per_circuit": int(shots_per_circuit),
            "minimum_independent_hardware_repeats": int(hardware_repeats),
            "status": "DRAFT ONLY · MUST BE SEALED BEFORE FIRST QPU JOB",
        },
        "claim_boundary": (
            "A sealed hardware test may measure equal-objective solution quality/time-to-solution. No quantum advantage claim is permitted "
            "unless a later preregistered hardware protocol beats the matched optimized classical workflow end-to-end."
        ),
    }
    payload["draft_sha"] = _sha(payload, 20)
    return payload


def seal_phase3_protocol(
    output_root: str | Path,
    phase2_gate: dict[str, Any],
    family: dict[str, Any],
    backend_snapshot: dict[str, Any],
    encoding_audit: dict[str, Any],
    *,
    depth_schedule: tuple[int, ...] = (1, 2, 3),
    shots_per_circuit: int = 4096,
    hardware_repeats: int = 30,
) -> dict[str, Any]:
    if not phase2_gate.get("ready", False):
        return {"sealed": False, "reason": "Phase-II HARDNESS GATE is not finalized and passed."}
    if not backend_snapshot or not backend_snapshot.get("backend_name"):
        return {"sealed": False, "reason": "A named hardware backend calibration snapshot is required."}
    if str(encoding_audit.get("encoding_status", "")).startswith("BLOCKED"):
        return {"sealed": False, "reason": "Equal-objective encoding is not executable for this family."}
    if encoding_audit.get("hardware_executable") is False:
        return {"sealed": False, "reason": "Equal-objective logical oracle is audited, but no sealed hardware circuit compiler exists for this family yet."}
    if int(backend_snapshot.get("num_qubits", 0) or 0) < int(encoding_audit.get("logical_qubits_min", 10**9) or 10**9):
        return {"sealed": False, "reason": "Selected backend does not have enough raw qubits for the blueprint."}
    eligible = phase2_gate.get("eligible_families")
    if not isinstance(eligible, pd.DataFrame) or eligible.empty:
        return {"sealed": False, "reason": "No eligible Phase-II family is available."}
    n = int(family.get("N", 0)); regime = str(family.get("Regime", "")).upper()
    mask = (eligible["N"].astype(int) == n) & (eligible["Regime"].astype(str).str.upper() == regime)
    if not bool(mask.any()):
        return {"sealed": False, "reason": "Selected family did not pass the immutable Phase-II family gate."}
    draft = phase3_protocol_draft(
        phase2_gate, family, backend_snapshot, encoding_audit,
        depth_schedule=depth_schedule, shots_per_circuit=shots_per_circuit, hardware_repeats=hardware_repeats,
    )
    draft["proposed_measurement_contract"]["status"] = "SEALED · NO HARDWARE JOBS YET"
    draft["sealed_utc"] = datetime.now(timezone.utc).isoformat()
    draft["protocol_sha"] = _sha({k: v for k, v in draft.items() if k not in {"draft_sha", "protocol_sha"}}, 20)
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    existing = sorted(root.glob("PHASE_III_QPU_PROTOCOL_*.json"))
    if existing:
        return {"sealed": False, "reason": f"A Phase-III QPU protocol already exists: {existing[0].name}"}
    path = root / f"PHASE_III_QPU_PROTOCOL_{draft['protocol_sha']}.json"
    path.write_text(json.dumps(draft, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return {"sealed": True, "path": str(path), "protocol": draft}


def phase3_output_root() -> Path:
    return Path.cwd() / "outputs" / "quantum_phase3" / "qpu"


def runtime_fingerprint() -> dict[str, Any]:
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "qiskit_installed": bool(importlib.util.find_spec("qiskit")),
        "ibm_runtime_installed": bool(importlib.util.find_spec("qiskit_ibm_runtime")),
        "braket_installed": bool(importlib.util.find_spec("braket")),
        "environment_variables_present": {
            "IBM_QUANTUM_TOKEN": bool(os.environ.get("IBM_QUANTUM_TOKEN")),
            "QISKIT_IBM_TOKEN": bool(os.environ.get("QISKIT_IBM_TOKEN")),
            "QISKIT_IBM_INSTANCE": bool(os.environ.get("QISKIT_IBM_INSTANCE")),
        },
    }
