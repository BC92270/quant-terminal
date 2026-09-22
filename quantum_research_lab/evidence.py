from __future__ import annotations

import hashlib
import inspect
import json
from typing import Any

import numpy as np
import pandas as pd

from . import engine as _engine_module
from .engine import rolling_density_decomposition, rolling_quantum_information, rolling_tensor_stability


FROZEN_ENGINE_ROWS = [
    {
        "Engine": "REGIME / DENSITY",
        "Frozen Version": "V2.2.1",
        "Research State": "FROZEN",
        "Highest Evidence": "L2 · CLASSICAL MODEL EDGE OBSERVED",
        "Strongest Control": "Purged expanding-window + dependency-aware block bootstrap",
        "Current Claim": "Quantum-like layer can improve the matched classical probability encoder, but dependency-robust OOS superiority is not established.",
        "Economic / Compute Value": "NOT ESTABLISHED",
        "Hardware Claim": "NOT APPLICABLE",
        "Next Permissible Test": "New market / genuinely new OOS extension; no parameter retuning on the frozen sample.",
    },
    {
        "Engine": "QMC / RISK",
        "Frozen Version": "V2.3.2",
        "Research State": "FROZEN",
        "Highest Evidence": "ENGINEERING CONTROLLED",
        "Strongest Control": "Canonical MC/RQMC references + total-error feasibility frontier",
        "Current Claim": "QAE retains favorable asymptotic query complexity, but current state-preparation, error-floor and latency assumptions do not produce a modeled crossover.",
        "Economic / Compute Value": "NO MODELLED CROSSOVER",
        "Hardware Claim": "NOT ELIGIBLE",
        "Next Permissible Test": "Measured compiled-circuit / QPU resource workflow against optimized classical implementations.",
    },
    {
        "Engine": "QUBO / ISING",
        "Frozen Version": "V2.4.1",
        "Research State": "FROZEN",
        "Highest Evidence": "SIMULATOR ALGORITHMIC RESULT",
        "Strongest Control": "Exact + MILP + SA/local controls; X-mixer vs Dicke+XY matched statevector test",
        "Current Claim": "Constraint-preserving Dicke+XY improves feasible mass and can improve optimum concentration in the classical statevector emulator.",
        "Economic / Compute Value": "CLASSICAL HARDNESS NOT ELIGIBLE",
        "Hardware Claim": "NOT ELIGIBLE",
        "Next Permissible Test": "Pre-registered harder instance suite; hardware only after credible classical hardness emerges.",
    },
    {
        "Engine": "QUANTUM INFORMATION / TT",
        "Frozen Version": "V2.5.1",
        "Research State": "FROZEN",
        "Highest Evidence": "L3 · SURVIVES TEMPORAL NULL",
        "Strongest Control": "Budgeted SVD + Tucker/HOSVD + temporal-null distribution + rank/block stress",
        "Current Claim": "The validated TT configuration contains temporal compression structure beyond shuffled nulls, with partial robustness across representation budgets.",
        "Economic / Compute Value": "DOWNSTREAM OOS VALUE NOT ESTABLISHED",
        "Hardware Claim": "NOT APPLICABLE",
        "Next Permissible Test": "Pre-register a downstream OOS structural task before any Level-5 promotion.",
    },
]


_ENGINE_SOURCE_SYMBOLS: dict[str, tuple[str, ...]] = {
    "REGIME / DENSITY": (
        "run_regime_benchmark",
        "multi_horizon_regime_stack",
        "target_integrity_grid",
        "quantum_density_probabilities",
        "apply_regime_hysteresis",
    ),
    "QMC / RISK": (
        "monte_carlo_option_price",
        "monte_carlo_method_benchmark",
        "randomized_sobol_study",
        "option_market_risk",
        "exposure_cva_profile",
        "qae_total_error_feasibility",
        "product_advantage_frontier",
    ),
    "QUBO / ISING": (
        "build_portfolio_qubo_components",
        "presolve_portfolio_qubo",
        "qubo_penalty_frontier",
        "constraint_preserving_qaoa_study",
        "classical_hardness_benchmark",
    ),
    "QUANTUM INFORMATION / TT": (
        "density_state_variants",
        "rolling_density_decomposition",
        "tensor_network_market_analysis_v251",
        "tensor_null_distribution",
        "tensor_rank_frontier",
        "tensor_block_frontier",
        "rolling_tensor_stability",
    ),
}

_ENGINE_PREFIX = {
    "REGIME / DENSITY": "QREG",
    "QMC / RISK": "QQMC",
    "QUBO / ISING": "QQUBO",
    "QUANTUM INFORMATION / TT": "QTT",
}


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return str(pd.Timestamp(value))
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (set, tuple)):
        return list(value)
    return str(value)


def _stable_hash(payload: Any, length: int = 12) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_json_default).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[: int(length)]


def _engine_code_hash(engine_name: str, length: int = 12) -> str:
    chunks: list[str] = []
    for symbol in _ENGINE_SOURCE_SYMBOLS.get(engine_name, ()):
        obj = getattr(_engine_module, symbol, None)
        if obj is None:
            chunks.append(f"MISSING:{symbol}")
            continue
        try:
            chunks.append(inspect.getsource(obj))
        except (OSError, TypeError):
            chunks.append(repr(obj))
    return hashlib.sha256("\n\n".join(chunks).encode("utf-8")).hexdigest()[: int(length)]


def _date_bounds(frame: pd.DataFrame | None) -> tuple[str, str]:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return "N/A", "N/A"
    try:
        idx = pd.DatetimeIndex(frame.index)
        idx = idx[~idx.isna()]
        if len(idx) == 0:
            return "N/A", "N/A"
        if idx.tz is not None:
            idx = idx.tz_convert(None)
        return idx.min().strftime("%Y-%m-%d"), idx.max().strftime("%Y-%m-%d")
    except Exception:
        return "N/A", "N/A"


def build_evidence_provenance(
    regime_result: dict[str, Any] | None,
    returns: pd.DataFrame | None,
    config_payloads: dict[str, dict[str, Any]] | None = None,
) -> pd.DataFrame:
    """Create deterministic evidence identifiers without mutating frozen engines.

    Code SHA is a hash of the frozen engine's relevant source functions. Config SHA
    hashes the active/frozen configuration payload supplied by the governance UI.
    Data cutoffs describe the data visible to that engine in this lab session.
    """
    config_payloads = config_payloads or {}
    reg_frame = regime_result.get("feature_frame") if isinstance(regime_result, dict) else None
    reg_start, reg_end = _date_bounds(reg_frame if isinstance(reg_frame, pd.DataFrame) else None)
    ret_start, ret_end = _date_bounds(returns)
    ret_universe = ", ".join(map(str, returns.columns)) if isinstance(returns, pd.DataFrame) and not returns.empty else "N/A"

    data_scope = {
        "REGIME / DENSITY": {
            "Data Start": reg_start,
            "Data Through": reg_end,
            "Universe / Scope": "PRIMARY · SPY · TLT · GLD · HYG · VIX + derived features",
            "OOS / Scope": "Purged expanding-window OOS",
        },
        "QMC / RISK": {
            "Data Start": "N/A",
            "Data Through": "N/A",
            "Universe / Scope": "Scenario / product inputs",
            "OOS / Scope": "Engineering benchmark · not a market OOS sample",
        },
        "QUBO / ISING": {
            "Data Start": ret_start,
            "Data Through": ret_end,
            "Universe / Scope": ret_universe,
            "OOS / Scope": "Current aligned return moments · optimization study",
        },
        "QUANTUM INFORMATION / TT": {
            "Data Start": ret_start,
            "Data Through": ret_end,
            "Universe / Scope": ret_universe,
            "OOS / Scope": "Structural validation / rolling monitor",
        },
    }

    frozen_map = {row["Engine"]: row for row in FROZEN_ENGINE_ROWS}
    rows: list[dict[str, Any]] = []
    for engine_name in frozen_map:
        version = frozen_map[engine_name]["Frozen Version"]
        code_sha = _engine_code_hash(engine_name)
        cfg_payload = config_payloads.get(engine_name, {"frozen_version": version})
        config_sha = _stable_hash(cfg_payload)
        scope = data_scope[engine_name]
        cutoff = str(scope["Data Through"])
        cutoff_token = cutoff.replace("-", "") if cutoff not in {"N/A", ""} else "SCENARIO"
        evidence_digest = _stable_hash(
            {
                "engine": engine_name,
                "version": version,
                "code": code_sha,
                "config": config_sha,
                "cutoff": cutoff,
                "scope": scope["OOS / Scope"],
            },
            length=10,
        ).upper()
        evidence_id = f"{_ENGINE_PREFIX[engine_name]}-{cutoff_token}-{evidence_digest}"
        rows.append(
            {
                "Engine": engine_name,
                "Frozen Version": version,
                "Code SHA": code_sha,
                "Config SHA": config_sha,
                "Data Start": scope["Data Start"],
                "Data Through": scope["Data Through"],
                "Universe / Scope": scope["Universe / Scope"],
                "OOS / Scope": scope["OOS / Scope"],
                "Evidence Snapshot ID": evidence_id,
            }
        )
    return pd.DataFrame(rows)


def frozen_evidence_registry(provenance: pd.DataFrame | None = None) -> pd.DataFrame:
    """Governance snapshot for research engines that have been explicitly frozen."""
    registry = pd.DataFrame(FROZEN_ENGINE_ROWS)
    if isinstance(provenance, pd.DataFrame) and not provenance.empty:
        cols = [c for c in ["Engine", "Code SHA", "Config SHA", "Data Through", "Evidence Snapshot ID"] if c in provenance.columns]
        if "Engine" in cols:
            registry = registry.merge(provenance[cols], on="Engine", how="left")
    return registry


def evidence_ladder() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Task-agnostic evidence ladder. Numeric matrix is for visualization only, not an aggregate score."""
    labels = pd.DataFrame(
        [
            ("REGIME / DENSITY", "VALIDATED", "OBSERVED", "TESTED · NOT ROBUST", "NO", "N/A"),
            ("QMC / RISK", "VALIDATED", "ENGINEERING", "N/A", "NO CROSSOVER", "NOT ELIGIBLE"),
            ("QUBO / ISING", "VALIDATED", "SIMULATOR POSITIVE", "N/A", "CLASSICAL TOO EASY", "NOT ELIGIBLE"),
            ("QUANTUM INFORMATION / TT", "VALIDATED", "ROBUST NULL RESULT", "ROLLING STRUCTURAL ONLY", "NOT TESTED", "N/A"),
        ],
        columns=["Engine", "Controlled Benchmark", "Statistical / Null", "OOS / Generalization", "Economic / Compute", "Hardware"],
    ).set_index("Engine")
    numeric = pd.DataFrame(
        [
            ("REGIME / DENSITY", 3, 2, 1, 0, 0),
            ("QMC / RISK", 3, 1, 0, 0, 0),
            ("QUBO / ISING", 3, 2, 0, 0, 0),
            ("QUANTUM INFORMATION / TT", 3, 3, 1, 0, 0),
        ],
        columns=["Engine", "Controlled Benchmark", "Statistical / Null", "OOS / Generalization", "Economic / Compute", "Hardware"],
    ).set_index("Engine")
    return labels, numeric


def claim_governance() -> pd.DataFrame:
    rows = [
        (
            "REGIME / DENSITY",
            "Observed matched-encoder probabilistic improvement; purged/dependency-aware validation controls are in place.",
            "Robust OOS edge, alpha, or quantum advantage.",
            "New untouched OOS market/time extension.",
        ),
        (
            "QMC / RISK",
            "QAE has favorable asymptotic query scaling; current engineering assumptions show no modeled crossover.",
            "Wall-clock speedup or hardware advantage.",
            "Measured compiled QPU vs optimized classical end-to-end benchmark.",
        ),
        (
            "QUBO / ISING",
            "Dicke+XY preserves feasibility and can improve simulator optimum concentration versus penalty X-mixer.",
            "Optimization speedup or practical quantum advantage.",
            "Hard classical instance family followed by equal-objective QPU testing.",
        ),
        (
            "QUANTUM INFORMATION / TT",
            "TT temporal ordering survives the frozen temporal-null test; representation robustness is partial.",
            "Physical entanglement, return predictability, or universal TT superiority.",
            "Pre-registered downstream OOS structural task.",
        ),
    ]
    return pd.DataFrame(rows, columns=["Engine", "Allowed Wording", "Prohibited Wording", "Promotion Requirement"])


def promotion_rules() -> pd.DataFrame:
    rows = [
        ("Descriptive", "Representation is mathematically well-defined and invariants pass.", "No superiority claim."),
        ("Controlled", "Credible classical / null controls use the same data and objective.", "May claim implementation validity."),
        ("Statistical", "Improvement survives appropriate uncertainty / multiple-testing / dependency controls.", "May claim statistical evidence only."),
        ("OOS / Generalization", "Result survives untouched chronology, market, or pre-registered downstream task.", "May claim out-of-sample evidence."),
        ("Economic / Compute", "Net economic utility or end-to-end compute advantage beats strong controls.", "May claim practical value within scope."),
        ("Hardware", "Measured QPU execution beats comparable optimized classical workflow end-to-end.", "Only then may 'quantum advantage' be considered."),
    ]
    return pd.DataFrame(rows, columns=["Evidence Tier", "Minimum Requirement", "Permitted Interpretation"])


def _percentile_series(s: pd.Series) -> pd.Series:
    s = pd.Series(s, copy=True).astype(float).replace([np.inf, -np.inf], np.nan)
    if s.notna().sum() < 2:
        return pd.Series(np.nan, index=s.index, dtype=float)
    return s.rank(method="average", pct=True) * 100.0


def _nearest_value(series: pd.Series, date: pd.Timestamp, tolerance_days: int) -> float:
    if series is None or series.empty:
        return float("nan")
    idx = pd.DatetimeIndex(series.index)
    if idx.tz is not None:
        idx = idx.tz_convert(None)
    target = pd.Timestamp(date).tz_localize(None) if pd.Timestamp(date).tzinfo is not None else pd.Timestamp(date)
    loc = idx.get_indexer([target], method="nearest", tolerance=pd.Timedelta(days=int(tolerance_days)))
    if len(loc) == 0 or int(loc[0]) < 0:
        return float("nan")
    try:
        return float(series.iloc[int(loc[0])])
    except Exception:
        return float("nan")


def _max_finite(values: list[float]) -> float:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    return float(np.max(arr)) if arr.size else float("nan")


def _dedupe_event_dates(rows: list[dict[str, Any]], min_gap_days: int = 7, limit: int = 12) -> list[dict[str, Any]]:
    chosen: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda r: float(r.get("Composite", -np.inf)), reverse=True):
        date = pd.Timestamp(row["Date"])
        if all(abs((date - pd.Timestamp(x["Date"])).days) >= int(min_gap_days) for x in chosen):
            chosen.append(row)
        if len(chosen) >= int(limit):
            break
    return sorted(chosen, key=lambda r: pd.Timestamp(r["Date"]), reverse=True)


def build_cross_engine_event_monitor(
    regime_result: dict[str, Any] | None,
    returns: pd.DataFrame | None,
    density_window: int = 63,
    density_step: int = 5,
    tt_block_size: int = 20,
    tt_max_rank: int = 8,
    tt_energy: float = 0.995,
) -> dict[str, Any]:
    """Align heterogeneous diagnostics in time without treating missing engines as equivalent evidence."""
    channels: dict[str, pd.Series] = {}

    if isinstance(regime_result, dict) and regime_result.get("available"):
        pred = regime_result.get("predictions")
        if isinstance(pred, pd.DataFrame) and not pred.empty:
            pcols = [c for c in pred.columns if str(c).startswith("Quantum Density · ") and not str(c).endswith("Pred")]
            if len(pcols) >= 2:
                probs = pred[pcols].astype(float)
                shift = 0.5 * probs.diff().abs().sum(axis=1)
                shift.name = "Regime probability shift"
                channels[shift.name] = _percentile_series(shift)
        ff = regime_result.get("feature_frame")
        if isinstance(ff, pd.DataFrame) and "rv_20" in ff.columns:
            rv = ff["rv_20"].astype(float).dropna()
            channels["Realized volatility"] = _percentile_series(rv)

    ret = returns.copy() if isinstance(returns, pd.DataFrame) else pd.DataFrame()
    if not ret.empty:
        qi = rolling_quantum_information(ret, window=int(density_window), step=int(density_step))
        if qi.get("available"):
            tl = qi["timeline"]
            if "trace_distance_prev" in tl:
                channels["Density shift"] = _percentile_series(tl["trace_distance_prev"].astype(float).dropna())
        dd = rolling_density_decomposition(ret, window=int(density_window), step=int(density_step))
        if dd.get("available"):
            tl = dd["timeline"]
            for col, name in [("correlation_shift", "Correlation shift"), ("volatility_shift", "Volatility-structure shift")]:
                if col in tl:
                    channels[name] = _percentile_series(tl[col].astype(float).dropna())
        tt = rolling_tensor_stability(ret, block_size=int(tt_block_size), max_rank=int(tt_max_rank), energy_threshold=float(tt_energy))
        if tt.get("available"):
            tl = tt["timeline"]
            if "Spectrum drift" in tl:
                channels["TT spectrum drift"] = _percentile_series(tl["Spectrum drift"].astype(float).dropna())
            if "Template transfer error" in tl:
                channels["TT transfer error"] = _percentile_series(tl["Template transfer error"].astype(float).dropna())

    if not channels:
        return {"available": False, "reason": "No aligned diagnostics available."}

    candidates: set[pd.Timestamp] = set()
    for s in channels.values():
        clean = s.dropna()
        if clean.empty:
            continue
        for d in clean.nlargest(min(12, len(clean))).index:
            candidates.add(pd.Timestamp(d))

    rows: list[dict[str, Any]] = []
    tolerance = {
        "Regime probability shift": 4,
        "Realized volatility": 4,
        "Density shift": 7,
        "Correlation shift": 7,
        "Volatility-structure shift": 7,
        "TT spectrum drift": 15,
        "TT transfer error": 15,
    }
    broad_names = np.asarray(["REGIME", "DENSITY", "VOL", "TT"], dtype=object)
    for d in candidates:
        vals = {name: _nearest_value(s, d, tolerance.get(name, 7)) for name, s in channels.items()}
        regime_score = _max_finite([vals.get("Regime probability shift", np.nan)])
        density_score = _max_finite([vals.get("Density shift", np.nan), vals.get("Correlation shift", np.nan)])
        vol_score = _max_finite([vals.get("Realized volatility", np.nan), vals.get("Volatility-structure shift", np.nan)])
        tt_score = _max_finite([vals.get("TT spectrum drift", np.nan), vals.get("TT transfer error", np.nan)])
        broad = np.asarray([regime_score, density_score, vol_score, tt_score], dtype=float)
        mask = np.isfinite(broad)
        available_channels = int(np.sum(mask))
        if available_channels < 2:
            continue
        broad_valid = broad[mask]
        composite = float(np.mean(broad_valid))
        confluence = int(np.sum(broad_valid >= 90.0))
        strongest = str(broad_names[mask][int(np.argmax(broad_valid))])
        coverage_pct = float(25.0 * available_channels)
        rows.append(
            {
                "Date": pd.Timestamp(d),
                "Composite": composite,
                "Confluence ≥90p": confluence,
                "Strongest channel": strongest,
                "Available Channels": f"{available_channels}/4",
                "Coverage %": coverage_pct,
                "Coverage Status": "FULL" if available_channels == 4 else "PARTIAL",
                "Regime pctl": regime_score,
                "Density pctl": density_score,
                "Volatility pctl": vol_score,
                "TT pctl": tt_score,
            }
        )

    if not rows:
        return {"available": False, "reason": "No multi-engine candidate dates could be aligned."}

    full_rows = [r for r in rows if r["Coverage Status"] == "FULL"]
    partial_rows = [r for r in rows if r["Coverage Status"] == "PARTIAL"]
    chosen_full = _dedupe_event_dates(full_rows, min_gap_days=7, limit=12) if full_rows else []
    chosen_partial = _dedupe_event_dates(partial_rows, min_gap_days=7, limit=12) if partial_rows else []
    events_full = pd.DataFrame(chosen_full)
    events_partial = pd.DataFrame(chosen_partial)
    if not events_full.empty:
        events_full = events_full.sort_values("Composite", ascending=False).reset_index(drop=True)
    if not events_partial.empty:
        events_partial = events_partial.sort_values("Composite", ascending=False).reset_index(drop=True)
    events = pd.concat([events_full, events_partial], ignore_index=True) if (not events_full.empty or not events_partial.empty) else pd.DataFrame()

    all_dates = sorted(set().union(*[set(pd.DatetimeIndex(s.dropna().index)) for s in channels.values() if not s.dropna().empty]))
    timeline = pd.DataFrame(index=pd.DatetimeIndex(all_dates))
    for name, s in channels.items():
        timeline[name] = s.reindex(timeline.index)
    timeline = timeline.sort_index()
    return {
        "available": True,
        "events": events,
        "events_full": events_full,
        "events_partial": events_partial,
        "timeline": timeline,
        "channels": list(channels),
        "interpretation": "Percentile synchronization monitor only. Composite rankings are comparable only within the same coverage class; no causal, predictive, or trading claim is implied.",
    }


def _matched_delta_from_metrics(regime_result: dict[str, Any]) -> float:
    metrics = regime_result.get("metrics")
    if not isinstance(metrics, pd.DataFrame) or metrics.empty or "Model" not in metrics.columns or "OOS Log Loss" not in metrics.columns:
        return float("nan")
    try:
        idx = metrics.set_index("Model")["OOS Log Loss"].astype(float)
        if "Quantum Density" in idx.index and "Classical Centroid" in idx.index:
            return float(idx.loc["Classical Centroid"] - idx.loc["Quantum Density"])
    except Exception:
        pass
    return float("nan")


def live_regime_evidence(regime_result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(regime_result, dict) or not regime_result.get("available"):
        return {"available": False}
    val = regime_result.get("validation_level", {}) or {}
    boot = regime_result.get("bootstrap_matched", {}) or {}
    econ = regime_result.get("economic_gate", {}) or {}
    eff = regime_result.get("effective_sample_size", np.nan)
    if isinstance(eff, dict):
        eff_n = float(eff.get("effective_n", np.nan))
        nom_n = int(round(float(eff.get("nominal_n", regime_result.get("oos_observations", 0) or 0))))
    else:
        eff_n = float(eff) if np.isscalar(eff) else float("nan")
        nom_n = int(regime_result.get("oos_observations", 0) or 0)

    delta = boot.get("delta", boot.get("mean_delta", np.nan))
    try:
        delta = float(delta)
    except Exception:
        delta = float("nan")
    if not np.isfinite(delta):
        delta = _matched_delta_from_metrics(regime_result)

    return {
        "available": True,
        "validation": str(val.get("label", "UNAVAILABLE")),
        "level": int(val.get("level", 0) or 0),
        "matched_delta_logloss": delta,
        "matched_p": float(boot.get("p_value", np.nan)),
        "matched_ci_low": float(boot.get("ci_low", np.nan)),
        "matched_ci_high": float(boot.get("ci_high", np.nan)),
        "effective_n": eff_n,
        "nominal_n": nom_n,
        "purge_pass": bool(regime_result.get("purge_pass", False)),
        "economic_gate": str(econ.get("label", "NOT TESTED")),
        "dominant": str(regime_result.get("current_dominant", "—")),
        "dominant_probability": float(regime_result.get("current_probability", np.nan)),
    }
