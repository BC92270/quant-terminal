from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd


PHASE_II_VERSION = "PHASE II · PREREGISTERED OOS PROGRAM · V1"
PREREGISTRATION_DATE = "2026-08-24"

SEALED_SOURCE_EVIDENCE = {
    "REGIME / DENSITY": "QREG-20260821-8B14479CA5",
    "QMC / RISK": "QQMC-SCENARIO-41595DB605",
    "QUBO / ISING": "QQUBO-20260821-861D4D08E8",
    "QUANTUM INFORMATION / TT": "QTT-20260821-40FE377848",
}

# The evidence parent is frozen at preregistration. New post-cutoff data is expected in Phase II
# and MUST NOT mutate the parent Evidence Snapshot identity.
SEALED_DATA_CUTOFF = {
    "REGIME / DENSITY": "2026-08-21",
    "QMC / RISK": "N/A",
    "QUBO / ISING": "2026-08-21",
    "QUANTUM INFORMATION / TT": "2026-08-21",
}


def _sealed_evidence_digest(evidence_id: str) -> str:
    """Return the terminal deterministic digest from a sealed Evidence Snapshot ID."""
    token = str(evidence_id).rsplit("-", 1)[-1].strip().upper()
    return token


def validate_sealed_source_evidence() -> dict[str, bool]:
    """Strict preregistration guard: every sealed snapshot must end in 10 hex chars."""
    out: dict[str, bool] = {}
    for engine_name, evidence_id in SEALED_SOURCE_EVIDENCE.items():
        digest = _sealed_evidence_digest(evidence_id)
        out[engine_name] = bool(len(digest) == 10 and all(ch in "0123456789ABCDEF" for ch in digest))
    return out


@dataclass(frozen=True)
class ProtocolSpec:
    key: str
    engine: str
    title: str
    evidence_target: str
    scientific_question: str
    unlock_condition: str
    primary_endpoint: str
    primary_control: str
    inference_rule: str
    success_rule: str
    failure_rule: str
    secondary_endpoints: tuple[str, ...]
    forbidden_changes: tuple[str, ...]
    execution_notes: tuple[str, ...]


def _stable_hash(payload: Any, length: int = 12) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[: int(length)]


PROTOCOLS: tuple[ProtocolSpec, ...] = (
    ProtocolSpec(
        key="REGIME_OOS_EXTENSION",
        engine="REGIME / DENSITY",
        title="Frozen-Spec Regime OOS Extension",
        evidence_target="L3 · DEPENDENCY-ROBUST OOS EDGE",
        scientific_question=(
            "Does the frozen Quantum Density layer continue to improve probabilistic regime forecasts versus the "
            "matched Classical Centroid on observations unavailable at the V2.2.1 evidence cutoff?"
        ),
        unlock_condition=(
            "Confirmatory evaluation unlocks after at least 126 new PRIMARY trading observations strictly after the frozen data cutoff."
        ),
        primary_endpoint=(
            "Paired new-sample Log-Loss edge ΔLL = LL(Classical Centroid) − LL(Quantum Density), using only post-cutoff predictions."
        ),
        primary_control="Matched Classical Centroid with the identical frozen feature encoder and frozen walk-forward specification.",
        inference_rule=(
            "Circular block bootstrap at 5/10/20/40 trading-day blocks; conservative p = max(p_b), conservative CI low = min(CI_low,b); "
            "report effective sample size."
        ),
        success_rule=(
            "Promote to L3 only if ΔLL > 0, every preregistered block-bootstrap CI excludes 0 on the positive side, conservative p < 0.05, "
            "and N_eff ≥ 50."
        ),
        failure_rule=(
            "No L3 promotion if ΔLL ≤ 0, any preregistered block CI includes 0, conservative p ≥ 0.05, or N_eff < 50. Result is recorded even if unfavorable."
        ),
        secondary_endpoints=(
            "Brier-score edge versus Classical Centroid",
            "Balanced accuracy / Macro-F1 / Risk-Off recall",
            "Economic CEQ / turnover after the already-frozen allocation policy and costs",
        ),
        forbidden_changes=(
            "No change to frozen Config SHA or Code SHA before confirmatory evaluation",
            "No target relabeling, horizon selection, feature additions, scaler changes or penalty retuning after seeing new outcomes",
            "No replacement of the matched Classical Centroid control",
        ),
        execution_notes=(
            "Scheduled refits defined by the frozen walk-forward specification are allowed; hyperparameter retuning is not.",
            "An interim descriptive checkpoint may be viewed after 63 new observations, but it cannot promote evidence.",
        ),
    ),
    ProtocolSpec(
        key="TT_OOS_STRUCTURAL_TRANSFER",
        engine="QUANTUM INFORMATION / TT",
        title="Tensor-Network OOS Structural Transfer",
        evidence_target="L5 · OUT-OF-SAMPLE STRUCTURAL VALUE",
        scientific_question=(
            "Does the frozen TT/MPS representation transfer to genuinely new cross-asset blocks better than parameter-matched SVD and Tucker controls?"
        ),
        unlock_condition=(
            "Descriptive interim unlocks after 126 new aligned 6-asset observations; confirmatory evaluation unlocks after 252 new aligned observations after the frozen cutoff."
        ),
        primary_endpoint=(
            "Mean one-block-ahead structural transfer edge on the frozen 20-day / max-rank-8 representation: "
            "min(Error_SVD, Error_Tucker) − Error_TT across post-cutoff blocks."
        ),
        primary_control="Parameter-budgeted Matrix SVD and Tucker/HOSVD fitted under the same chronology and data tensor contract.",
        inference_rule=(
            "Paired block bootstrap over post-cutoff 20-day blocks; report mean edge, 95% CI, win-rate by block and a predeclared temporal-null diagnostic."
        ),
        success_rule=(
            "L5 promotion requires positive mean TT edge, 95% paired-block CI entirely above 0, TT beating both controls on ≥60% of confirmatory blocks, "
            "and no violation of the frozen 20-day/rank-8/configuration contract."
        ),
        failure_rule=(
            "No L5 promotion if either classical tensor/matrix control is superior on average, CI includes 0, win-rate <60%, or confirmatory sample is incomplete."
        ),
        secondary_endpoints=(
            "Bond-spectrum drift stability",
            "Previous-template transfer error",
            "Channel-level transfer error for return / |z| / z²",
            "Asset-level transfer error map",
        ),
        forbidden_changes=(
            "No rank/block-size search on the confirmatory post-cutoff sample",
            "No new channels or assets added after viewing confirmatory outcomes",
            "No replacement of SVD/Tucker controls",
        ),
        execution_notes=(
            "The task is structural generalization, not return prediction.",
            "The 126-observation interim is descriptive only; the 252-observation checkpoint is confirmatory.",
        ),
    ),
    ProtocolSpec(
        key="QUBO_HARD_INSTANCE_SUITE",
        engine="QUBO / ISING",
        title="Pre-Registered Classical-Hardness Instance Suite",
        evidence_target="HARDNESS ELIGIBILITY FOR EQUAL-OBJECTIVE QPU TESTING",
        scientific_question=(
            "Can a deterministic family of constrained portfolio-selection instances become materially hard for strong classical controls before any QPU comparison is attempted?"
        ),
        unlock_condition="Immediately executable: synthetic family, seeds, size grid and hardness thresholds are sealed in this preregistration.",
        primary_endpoint=(
            "Classical hardness under fixed budgets: MILP median/p95 wall-clock plus feasibility/objective gaps for fixed-budget SA and local-search controls."
        ),
        primary_control="MILP is authoritative when optimality is certified; SA and local search use fixed predeclared compute budgets.",
        inference_rule=(
            "Evaluate the full deterministic seed grid without dropping hard instances. Summaries are reported by size and constraint regime; no seed replacement is permitted."
        ),
        success_rule=(
            "Hardware-eligibility gate opens only if MILP median runtime ≥10 s OR p95 ≥60 s in at least one preregistered family, and ≥25% of that family has fixed-budget heuristic gap >0.5%."
        ),
        failure_rule=(
            "Remain NOT ELIGIBLE if classical controls stay fast/effectively exact. A large combinatorial state count alone never satisfies the gate."
        ),
        secondary_endpoints=(
            "MILP node count / final MIP gap when available",
            "Constraint density and Ising coupling density",
            "QUBO coefficient dynamic range",
            "Heuristic success-rate dispersion across seeds",
        ),
        forbidden_changes=(
            "No deletion or replacement of preregistered seeds after runtimes are observed",
            "No post-hoc threshold changes to manufacture classical hardness",
            "No QAOA/QPU advantage claim before the classical-hardness gate opens",
        ),
        execution_notes=(
            "Preregistered sizes N = 24, 32, 40, 48, 64.",
            "Constraint regimes = BASE, PAIRWISE, BANDS; deterministic seeds = 1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807.",
            "The suite is a compute-hardness experiment, not an investment backtest.",
        ),
    ),
    ProtocolSpec(
        key="QMC_QPU_READINESS",
        engine="QMC / RISK",
        title="Compiled QPU Time-to-Solution Benchmark",
        evidence_target="MEASURED HARDWARE COMPUTE EVIDENCE",
        scientific_question=(
            "Can a compiled, repeatable QAE workflow reach a matched financial pricing error faster end-to-end than the strongest optimized classical control?"
        ),
        unlock_condition=(
            "Requires a supported quantum SDK, authenticated hardware backend, recorded calibration snapshot and executable compiled circuit."
        ),
        primary_endpoint=(
            "Matched-error time-to-solution for a fixed canonical European-call benchmark, comparing compiled QPU execution with optimized classical RQMC/control-variate pricing."
        ),
        primary_control="Best validated classical method at the same absolute price-error target and confidence requirement.",
        inference_rule=(
            "At least 30 repeated hardware runs; report compilation time, execution time, queue time separately, physical resources, achieved pricing error and 95% uncertainty."
        ),
        success_rule=(
            "Hardware evidence advances only if achieved total pricing error meets the preregistered target on ≥95% of runs and median end-to-end compute time excluding provider queue is below the matched classical control; queue-inclusive time is reported separately."
        ),
        failure_rule=(
            "No advantage claim if target error is infeasible, hardware error budget is violated, fewer than 30 valid repeats complete, or matched classical time is not beaten."
        ),
        secondary_endpoints=(
            "Logical / physical qubits and two-qubit gate count",
            "Circuit depth after transpilation",
            "State-preparation share of execution cost",
            "Mitigation overhead and run-to-run variance",
        ),
        forbidden_changes=(
            "No change of classical comparator after hardware results are observed",
            "No reporting query-complexity ratio as wall-clock speedup",
            "No exclusion of failed hardware runs except predeclared provider/system failures",
        ),
        execution_notes=(
            "Canonical scenario and target-error contract are sealed before connecting a backend.",
            "Provider queue latency is reported but not mixed with device-compute time in the primary endpoint.",
        ),
    ),
)


QUBO_SUITE = {
    "sizes": [24, 32, 40, 48, 64],
    "constraint_regimes": ["BASE", "PAIRWISE", "BANDS"],
    "seeds": [1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807],
    "cardinality_fraction": 0.25,
    "milp_median_gate_seconds": 10.0,
    "milp_p95_gate_seconds": 60.0,
    "heuristic_gap_gate": 0.005,
    "heuristic_hard_fraction_gate": 0.25,
}

QMC_CANONICAL = {
    "product": "European call",
    "model": "GBM / Black-Scholes",
    "spot": 100.0,
    "strike": 100.0,
    "maturity_years": 1.0,
    "risk_free_rate": 0.03,
    "dividend_yield": 0.0,
    "volatility": 0.20,
    "absolute_price_error_target": 0.50,
    "confidence_requirement": 0.95,
    "minimum_hardware_repeats": 30,
}


def protocol_payload(spec: ProtocolSpec, source_evidence_id: str) -> dict[str, Any]:
    payload = asdict(spec)
    payload["source_evidence_id"] = str(source_evidence_id)
    payload["preregistration_date"] = PREREGISTRATION_DATE
    payload["phase_ii_version"] = PHASE_II_VERSION
    if spec.key == "QUBO_HARD_INSTANCE_SUITE":
        payload["sealed_suite"] = QUBO_SUITE
    if spec.key == "QMC_QPU_READINESS":
        payload["canonical_scenario"] = QMC_CANONICAL
    return payload


def _frozen_parent_runtime_evidence_id(engine_name: str, source: dict[str, Any]) -> str:
    """Rebuild the sealed parent identity from current code/config but the preregistered cutoff.

    Phase-II is supposed to accumulate NEW data after the parent cutoff. Therefore the live
    ``Data Through`` field must never participate in the parent-match lock. The lock protects
    code/config/scope identity; the cutoff remains the sealed V2.6.1 cutoff.
    """
    if not source:
        return "UNRESOLVED"
    sealed = SEALED_SOURCE_EVIDENCE[engine_name]
    prefix = sealed.split("-", 1)[0]
    cutoff = SEALED_DATA_CUTOFF[engine_name]
    cutoff_token = cutoff.replace("-", "") if cutoff not in {"N/A", ""} else "SCENARIO"
    version = str(source.get("Frozen Version", ""))
    code_sha = str(source.get("Code SHA", ""))
    config_sha = str(source.get("Config SHA", ""))
    scope = str(source.get("OOS / Scope", ""))
    if not all([version, code_sha, config_sha, scope]):
        return "UNRESOLVED"
    digest = _stable_hash(
        {
            "engine": engine_name,
            "version": version,
            "code": code_sha,
            "config": config_sha,
            "cutoff": cutoff,
            "scope": scope,
        },
        length=10,
    ).upper()
    return f"{prefix}-{cutoff_token}-{digest}"


def build_phase2_registry(provenance: pd.DataFrame) -> pd.DataFrame:
    sealed_validity = validate_sealed_source_evidence()
    invalid = [name for name, ok in sealed_validity.items() if not ok]
    if invalid:
        raise ValueError(f"Malformed sealed Evidence Snapshot ID(s): {', '.join(invalid)}")
    prov_map: dict[str, dict[str, Any]] = {}
    if isinstance(provenance, pd.DataFrame) and not provenance.empty:
        prov_map = {str(r["Engine"]): dict(r) for _, r in provenance.iterrows() if "Engine" in r}
    rows: list[dict[str, Any]] = []
    for spec in PROTOCOLS:
        source = prov_map.get(spec.engine, {})
        runtime_evidence_id = _frozen_parent_runtime_evidence_id(spec.engine, source)
        evidence_id = SEALED_SOURCE_EVIDENCE[spec.engine]
        payload = protocol_payload(spec, evidence_id)
        p_hash = _stable_hash(payload, length=16).upper()
        rows.append({
            "Protocol": spec.key,
            "Engine": spec.engine,
            "Title": spec.title,
            "Target Tier": spec.evidence_target,
            "Source Evidence": evidence_id,
            "Runtime Evidence": runtime_evidence_id,
            "Source Match": bool(runtime_evidence_id == evidence_id),
            "Protocol SHA": p_hash,
            "Preregistered": PREREGISTRATION_DATE,
            "Data Cutoff": "N/A" if spec.engine == "QMC / RISK" else "2026-08-21",
        })
    return pd.DataFrame(rows)


def phase2_manifest(provenance: pd.DataFrame) -> dict[str, Any]:
    registry = build_phase2_registry(provenance)
    protocols = []
    for spec in PROTOCOLS:
        row = registry.loc[registry["Protocol"] == spec.key].iloc[0]
        protocols.append({
            **protocol_payload(spec, str(row["Source Evidence"])),
            "protocol_sha": str(row["Protocol SHA"]),
        })
    core = {
        "phase_ii_version": PHASE_II_VERSION,
        "preregistration_date": PREREGISTRATION_DATE,
        "protocols": protocols,
        "global_rules": {
            "no_retuning_of_frozen_engines": True,
            "unfavorable_results_are_recorded": True,
            "promotion_requires_predeclared_gate": True,
            "hardware_advantage_requires_measured_qpu_end_to_end_win": True,
            "exploratory_interims_cannot_promote_confirmatory_evidence": True,
        },
    }
    core["manifest_sha"] = _stable_hash(core, length=20).upper()
    return core


def _new_observation_count(frame: pd.DataFrame | None, cutoff: str) -> int:
    if not isinstance(frame, pd.DataFrame) or frame.empty or str(cutoff) in {"N/A", "", "None"}:
        return 0
    try:
        idx = pd.DatetimeIndex(frame.index)
        if idx.tz is not None:
            idx = idx.tz_convert(None)
        c = pd.Timestamp(cutoff)
        return int(np.sum(idx > c))
    except Exception:
        return 0


def _qpu_runtime_status() -> dict[str, Any]:
    sdk_available = importlib.util.find_spec("qiskit") is not None
    provider_available = importlib.util.find_spec("qiskit_ibm_runtime") is not None
    token_configured = bool(
        os.environ.get("QISKIT_IBM_TOKEN")
        or os.environ.get("IBM_QUANTUM_TOKEN")
        or os.environ.get("QPU_TOKEN")
    )
    backend_named = bool(os.environ.get("QPU_BACKEND") or os.environ.get("IBM_QUANTUM_BACKEND"))
    ready = bool(sdk_available and provider_available and token_configured and backend_named)
    return {
        "sdk_available": sdk_available,
        "provider_available": provider_available,
        "token_configured": token_configured,
        "backend_named": backend_named,
        "ready": ready,
    }


def phase2_readiness(
    provenance: pd.DataFrame,
    regime_frame: pd.DataFrame | None,
    returns: pd.DataFrame | None,
) -> pd.DataFrame:
    # Progress is measured strictly AFTER the sealed evidence cutoffs. It must not reset
    # to zero when live data extends beyond preregistration.
    reg_cutoff = SEALED_DATA_CUTOFF["REGIME / DENSITY"]
    tt_cutoff = SEALED_DATA_CUTOFF["QUANTUM INFORMATION / TT"]
    reg_new = _new_observation_count(regime_frame, reg_cutoff)
    tt_new = _new_observation_count(returns, tt_cutoff)
    qpu = _qpu_runtime_status()

    rows = [
        {
            "Protocol": "REGIME_OOS_EXTENSION",
            "Status": "READY · CONFIRMATORY" if reg_new >= 126 else ("INTERIM ONLY" if reg_new >= 63 else "WAITING · NEW DATA"),
            "Progress": f"{reg_new}/126 new trading observations",
            "Unlock": "126 new PRIMARY observations",
            "Promotion Eligible": bool(reg_new >= 126),
        },
        {
            "Protocol": "TT_OOS_STRUCTURAL_TRANSFER",
            "Status": "READY · CONFIRMATORY" if tt_new >= 252 else ("INTERIM ONLY" if tt_new >= 126 else "WAITING · NEW DATA"),
            "Progress": f"{tt_new}/252 new aligned observations",
            "Unlock": "126 interim · 252 confirmatory",
            "Promotion Eligible": bool(tt_new >= 252),
        },
        {
            "Protocol": "QUBO_HARD_INSTANCE_SUITE",
            "Status": "ARMED · SEALED SUITE",
            "Progress": f"{len(QUBO_SUITE['sizes']) * len(QUBO_SUITE['constraint_regimes']) * len(QUBO_SUITE['seeds'])} preregistered instances",
            "Unlock": "Immediate · explicit execution only",
            "Promotion Eligible": True,
        },
        {
            "Protocol": "QMC_QPU_READINESS",
            "Status": "READY · HARDWARE" if qpu["ready"] else "BLOCKED · QPU ENVIRONMENT",
            "Progress": (
                f"SDK={'YES' if qpu['sdk_available'] else 'NO'} · Provider={'YES' if qpu['provider_available'] else 'NO'} · "
                f"Credential={'YES' if qpu['token_configured'] else 'NO'} · Backend={'YES' if qpu['backend_named'] else 'NO'}"
            ),
            "Unlock": "SDK + authenticated provider + named backend",
            "Promotion Eligible": False,
        },
    ]
    return pd.DataFrame(rows)


def protocol_detail_table(provenance: pd.DataFrame) -> pd.DataFrame:
    registry = build_phase2_registry(provenance).set_index("Protocol")
    rows: list[dict[str, Any]] = []
    for spec in PROTOCOLS:
        reg = registry.loc[spec.key]
        rows.append({
            "Protocol": spec.key,
            "Engine": spec.engine,
            "Question": spec.scientific_question,
            "Primary Endpoint": spec.primary_endpoint,
            "Primary Control": spec.primary_control,
            "Success Rule": spec.success_rule,
            "Failure Rule": spec.failure_rule,
            "Source Evidence": reg["Source Evidence"],
            "Protocol SHA": reg["Protocol SHA"],
        })
    return pd.DataFrame(rows)


def protocol_by_key(key: str) -> ProtocolSpec:
    for spec in PROTOCOLS:
        if spec.key == key:
            return spec
    raise KeyError(key)
