from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

CALIBRATION_DATASET_VERSION = "OPTIONS-CALIBRATION-DATASET-2.5.5"
EVENT_POLICIES = (
    "Keep observed event premium",
    "Exclude event-window maturity",
    "Strip estimated discrete event variance",
)
HOLDOUT_POLICIES = (
    "Stratified quote holdout",
    "Maturity holdout",
    "Last maturity holdout",
)
WEIGHTING_METHODS = (
    "Vega × liquidity × quality",
    "Vega only",
    "Liquidity × quality",
    "Equal by maturity",
)


@dataclass(frozen=True)
class CalibrationDatasetSettings:
    event_policy: str = "Strip estimated discrete event variance"
    holdout_policy: str = "Stratified quote holdout"
    weighting_method: str = "Vega × liquidity × quality"
    max_abs_log_moneyness: float = 0.30
    holdout_fraction: float = 0.20
    min_maturities: int = 4
    min_training_points: int = 40
    min_points_per_maturity: int = 6
    min_effective_sample_size: float = 25.0
    max_quote_weight: float = 0.05
    event_baseline_method: str = "Median non-event forward variance"


def _signature(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(payload), sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16].upper()


def _normal_pdf(value: np.ndarray | float) -> np.ndarray | float:
    return np.exp(-0.5 * np.asarray(value, dtype=float) ** 2) / math.sqrt(2.0 * math.pi)


def _black_scholes_vega(
    spot: np.ndarray,
    strike: np.ndarray,
    time_to_expiry: np.ndarray,
    risk_free_rate: float,
    dividend_yield: np.ndarray,
    volatility: np.ndarray,
) -> np.ndarray:
    s = np.asarray(spot, dtype=float)
    k = np.asarray(strike, dtype=float)
    t = np.maximum(np.asarray(time_to_expiry, dtype=float), 1e-8)
    q = np.asarray(dividend_yield, dtype=float)
    sigma = np.maximum(np.asarray(volatility, dtype=float), 1e-6)
    d1 = (np.log(np.maximum(s, 1e-12) / np.maximum(k, 1e-12)) + (float(risk_free_rate) - q + 0.5 * sigma**2) * t) / (sigma * np.sqrt(t))
    return s * np.exp(-q * t) * _normal_pdf(d1) * np.sqrt(t)


def _robust_scale(values: Sequence[float], floor: float = 0.05, cap: float = 1.0) -> np.ndarray:
    x = np.asarray(values, dtype=float)
    finite = np.isfinite(x) & (x >= 0.0)
    output = np.full_like(x, floor, dtype=float)
    if not finite.any():
        return output
    valid = x[finite]
    p10, p90 = np.quantile(valid, [0.10, 0.90]) if valid.size >= 3 else (float(np.min(valid)), float(np.max(valid)))
    if p90 <= p10 + 1e-12:
        output[finite] = cap
    else:
        output[finite] = floor + (cap - floor) * np.clip((valid - p10) / (p90 - p10), 0.0, 1.0)
    return output


def _cap_and_normalize(weights: np.ndarray, cap: float) -> np.ndarray:
    w = np.maximum(np.asarray(weights, dtype=float), 0.0)
    if not np.isfinite(w).all() or float(np.sum(w)) <= 0.0:
        w = np.ones_like(w, dtype=float)
    w = w / float(np.sum(w))
    cap = float(np.clip(cap, 1.0 / max(len(w), 1), 1.0))
    free = np.ones(len(w), dtype=bool)
    result = np.zeros_like(w)
    remaining = 1.0
    source = w.copy()
    for _ in range(len(w) + 2):
        if not free.any():
            break
        scaled = source[free] / max(float(np.sum(source[free])), 1e-12) * remaining
        over = scaled > cap + 1e-12
        indices = np.flatnonzero(free)
        if not np.any(over):
            result[indices] = scaled
            remaining = 0.0
            break
        capped_indices = indices[over]
        result[capped_indices] = cap
        free[capped_indices] = False
        remaining = max(0.0, 1.0 - float(np.sum(result)))
    if remaining > 1e-10 and free.any():
        result[free] += remaining / int(np.sum(free))
    return result / max(float(np.sum(result)), 1e-12)


def estimate_event_variance_adjustments(surface_result: Mapping[str, Any]) -> pd.DataFrame:
    term = surface_result.get("term_structure")
    events = surface_result.get("event_diagnostics")
    if not isinstance(term, pd.DataFrame) or term.empty or not isinstance(events, pd.DataFrame) or events.empty:
        return pd.DataFrame(columns=[
            "window_start", "window_end", "start_dte", "end_dte", "actual_incremental_variance",
            "baseline_annualized_variance", "baseline_forward_variance", "estimated_event_variance", "estimated_event_vol_equivalent",
            "potential_event_window",
        ])
    term = term.sort_values("time_to_expiry").reset_index(drop=True)
    event_rows = events.copy()
    non_event = event_rows.loc[~event_rows["potential_event_window"].astype(bool), "incremental_forward_variance"]
    baseline = float(np.nanmedian(non_event.to_numpy(dtype=float))) if len(non_event) else float(np.nanmedian(event_rows["incremental_forward_variance"].to_numpy(dtype=float)))
    if not np.isfinite(baseline) or baseline < 0.0:
        baseline = 0.0
    output: list[dict[str, Any]] = []
    for row in event_rows.itertuples(index=False):
        start_t = float(term.loc[term["expiration"].astype(str) == str(row.window_start), "time_to_expiry"].iloc[0])
        end_t = float(term.loc[term["expiration"].astype(str) == str(row.window_end), "time_to_expiry"].iloc[0])
        dt = max(end_t - start_t, 1e-12)
        actual_increment = float(row.incremental_forward_variance) * dt
        expected_increment = baseline * dt
        event_variance = max(actual_increment - expected_increment, 0.0) if bool(row.potential_event_window) else 0.0
        output.append({
            "window_start": str(row.window_start),
            "window_end": str(row.window_end),
            "start_dte": int(row.start_dte),
            "end_dte": int(row.end_dte),
            "actual_incremental_variance": actual_increment,
            "baseline_annualized_variance": baseline,
            "baseline_forward_variance": baseline,  # backward-compatible alias
            "expected_continuous_increment": expected_increment,
            "estimated_event_variance": event_variance,
            "estimated_event_vol_equivalent": math.sqrt(max(event_variance, 0.0)),
            "potential_event_window": bool(row.potential_event_window),
            "diagnostic": str(row.diagnostic),
        })
    return pd.DataFrame(output)


def _assign_quote_holdout(frame: pd.DataFrame, fraction: float) -> pd.Series:
    holdout = pd.Series(False, index=frame.index)
    fraction = float(np.clip(fraction, 0.05, 0.40))
    for _, group in frame.groupby("expiration", sort=True):
        ordered = group.sort_values("log_moneyness")
        n = len(ordered)
        if n < 8:
            continue
        hold_count = max(1, int(round(n * fraction)))
        positions = np.unique(np.round(np.linspace(1, n - 2, hold_count)).astype(int))
        holdout.loc[ordered.index[positions]] = True
    return holdout


def _assign_maturity_holdout(frame: pd.DataFrame, fraction: float, last_only: bool = False) -> pd.Series:
    expiries = frame[["expiration", "time_to_expiry"]].drop_duplicates().sort_values("time_to_expiry")
    holdout = pd.Series(False, index=frame.index)
    if expiries.empty:
        return holdout
    if last_only:
        selected = [str(expiries.iloc[-1]["expiration"])]
    else:
        count = max(1, int(round(len(expiries) * float(np.clip(fraction, 0.10, 0.40)))))
        candidates = expiries.iloc[1:] if len(expiries) > 1 else expiries
        positions = np.unique(np.round(np.linspace(0, len(candidates) - 1, count)).astype(int))
        selected = candidates.iloc[positions]["expiration"].astype(str).tolist()
    holdout.loc[frame["expiration"].astype(str).isin(selected)] = True
    return holdout


def _moneyness_bucket(values: pd.Series) -> pd.Categorical:
    bins = [-np.inf, -0.20, -0.08, 0.08, 0.20, np.inf]
    labels = ["Left wing", "Put shoulder", "ATM", "Call shoulder", "Right wing"]
    return pd.cut(values.astype(float), bins=bins, labels=labels, include_lowest=True)


def build_calibration_dataset(
    surface_result: Mapping[str, Any],
    event_policy: str = "Strip estimated discrete event variance",
    holdout_policy: str = "Stratified quote holdout",
    weighting_method: str = "Vega × liquidity × quality",
    max_abs_log_moneyness: float = 0.30,
    holdout_fraction: float = 0.20,
    min_maturities: int = 4,
    min_training_points: int = 40,
    min_points_per_maturity: int = 6,
    min_effective_sample_size: float = 25.0,
    max_quote_weight: float = 0.05,
) -> dict[str, Any]:
    if not isinstance(surface_result, Mapping) or not surface_result.get("ok"):
        return {"ok": False, "status": "BLOCKED", "reason": "A completed governed volatility surface is required."}
    points = surface_result.get("smile_points")
    summary = surface_result.get("expiry_summary")
    if not isinstance(points, pd.DataFrame) or points.empty or not isinstance(summary, pd.DataFrame) or summary.empty:
        return {"ok": False, "status": "BLOCKED", "reason": "The surface does not contain quote-level smile points and expiry diagnostics."}
    if event_policy not in EVENT_POLICIES:
        return {"ok": False, "status": "BLOCKED", "reason": f"Unsupported event policy: {event_policy}"}
    if holdout_policy not in HOLDOUT_POLICIES:
        return {"ok": False, "status": "BLOCKED", "reason": f"Unsupported holdout policy: {holdout_policy}"}
    if weighting_method not in WEIGHTING_METHODS:
        return {"ok": False, "status": "BLOCKED", "reason": f"Unsupported weighting method: {weighting_method}"}

    settings = CalibrationDatasetSettings(
        event_policy=str(event_policy),
        holdout_policy=str(holdout_policy),
        weighting_method=str(weighting_method),
        max_abs_log_moneyness=float(max_abs_log_moneyness),
        holdout_fraction=float(holdout_fraction),
        min_maturities=int(min_maturities),
        min_training_points=int(min_training_points),
        min_points_per_maturity=int(min_points_per_maturity),
        min_effective_sample_size=float(min_effective_sample_size),
        max_quote_weight=float(max_quote_weight),
    )
    frame = points.copy().reset_index(drop=True)
    frame["expiration"] = frame["expiration"].astype(str)
    quality_cols = [
        "expiration", "svi_status", "svi_rmse_iv", "butterfly_g_min", "reliable_quotes",
        "single_expiry_status", "effective_q", "carry_curve_source",
    ]
    available_quality = [column for column in quality_cols if column in summary.columns]
    frame = frame.merge(summary[available_quality].drop_duplicates("expiration"), on="expiration", how="left")
    spot = float(surface_result.get("spot", float("nan")))
    risk_free_rate = float(surface_result.get("settings", {}).get("risk_free_rate", 0.0))

    event_table = estimate_event_variance_adjustments(surface_result)
    flagged_events = event_table[event_table["potential_event_window"].astype(bool)] if not event_table.empty else event_table
    frame["event_variance_removed"] = 0.0
    frame["event_policy_action"] = "NONE"
    excluded_event_expiries: set[str] = set()
    if event_policy == "Exclude event-window maturity" and isinstance(flagged_events, pd.DataFrame):
        excluded_event_expiries = set(flagged_events["window_end"].astype(str))
        frame.loc[frame["expiration"].isin(excluded_event_expiries), "event_policy_action"] = "EXCLUDE_EVENT_MATURITY"
    elif event_policy == "Strip estimated discrete event variance" and isinstance(flagged_events, pd.DataFrame):
        cumulative = np.zeros(len(frame), dtype=float)
        for event in flagged_events.itertuples(index=False):
            mask = frame["dte"].astype(int).to_numpy() >= int(event.end_dte)
            cumulative[mask] += float(event.estimated_event_variance)
        frame["event_variance_removed"] = cumulative
        frame.loc[cumulative > 0.0, "event_policy_action"] = "STRIP_EVENT_VARIANCE"
    elif event_policy == "Keep observed event premium" and len(flagged_events):
        frame.loc[frame["dte"].astype(int) >= int(flagged_events["end_dte"].min()), "event_policy_action"] = "KEEP_EVENT_PREMIUM"

    frame["raw_total_variance"] = frame["total_variance"].astype(float)
    frame["target_total_variance"] = np.maximum(frame["raw_total_variance"] - frame["event_variance_removed"], 1e-8)
    frame["target_iv"] = np.sqrt(frame["target_total_variance"] / np.maximum(frame["time_to_expiry"].astype(float), 1e-12))
    frame["in_moneyness_band"] = frame["log_moneyness"].astype(float).abs() <= float(max_abs_log_moneyness) + 1e-12
    frame["event_expiry_excluded"] = frame["expiration"].isin(excluded_event_expiries)
    frame["included"] = frame["in_moneyness_band"] & ~frame["event_expiry_excluded"] & np.isfinite(frame["target_iv"]) & (frame["target_iv"] > 0.0)
    frame["exclusion_reason"] = ""
    frame.loc[~frame["in_moneyness_band"], "exclusion_reason"] = "OUTSIDE_MONEYNESS_BAND"
    frame.loc[frame["event_expiry_excluded"], "exclusion_reason"] = "EVENT_MATURITY_EXCLUDED"
    frame.loc[~np.isfinite(frame["target_iv"]) | (frame["target_iv"] <= 0.0), "exclusion_reason"] = "INVALID_ADJUSTED_VARIANCE"

    eligible = frame[frame["included"]].copy()
    if eligible.empty:
        return {"ok": False, "status": "BLOCKED", "reason": "No quote survived the calibration-dataset gates.", "dataset": frame, "event_adjustments": event_table}

    if holdout_policy == "Stratified quote holdout":
        holdout_mask = _assign_quote_holdout(eligible, holdout_fraction)
    elif holdout_policy == "Maturity holdout":
        holdout_mask = _assign_maturity_holdout(eligible, holdout_fraction, last_only=False)
    else:
        holdout_mask = _assign_maturity_holdout(eligible, holdout_fraction, last_only=True)
    eligible["sample_role"] = np.where(holdout_mask.reindex(eligible.index, fill_value=False).to_numpy(), "HOLDOUT", "TRAIN")

    eligible["vega_raw"] = _black_scholes_vega(
        np.full(len(eligible), spot),
        eligible["strike"].to_numpy(dtype=float),
        eligible["time_to_expiry"].to_numpy(dtype=float),
        risk_free_rate,
        eligible.get("effective_q", pd.Series(np.zeros(len(eligible)), index=eligible.index)).to_numpy(dtype=float),
        eligible["target_iv"].to_numpy(dtype=float),
    )
    eligible["vega_score"] = _robust_scale(eligible["vega_raw"].to_numpy())
    quote_weight = pd.to_numeric(eligible.get("quote_weight", 1.0), errors="coerce").fillna(0.0).to_numpy(dtype=float)
    eligible["liquidity_score"] = _robust_scale(np.log1p(np.maximum(quote_weight, 0.0)))
    rmse = pd.to_numeric(eligible.get("svi_rmse_iv", 0.0), errors="coerce").fillna(0.02).to_numpy(dtype=float)
    quality = np.exp(-np.square(rmse / 0.015))
    if "butterfly_g_min" in eligible:
        quality *= np.where(pd.to_numeric(eligible["butterfly_g_min"], errors="coerce").fillna(-1.0).to_numpy(dtype=float) >= -1e-5, 1.0, 0.25)
    if "svi_status" in eligible:
        quality *= np.where(eligible["svi_status"].astype(str).to_numpy() == "PASS", 1.0, 0.50)
    eligible["quality_score"] = np.clip(quality, 0.05, 1.0)

    if weighting_method == "Vega × liquidity × quality":
        raw_weight = eligible["vega_score"] * eligible["liquidity_score"] * eligible["quality_score"]
    elif weighting_method == "Vega only":
        raw_weight = eligible["vega_score"]
    elif weighting_method == "Liquidity × quality":
        raw_weight = eligible["liquidity_score"] * eligible["quality_score"]
    else:
        raw_weight = pd.Series(np.ones(len(eligible)), index=eligible.index)
    eligible["raw_calibration_weight"] = np.asarray(raw_weight, dtype=float)
    eligible["calibration_weight"] = 0.0

    train = eligible[eligible["sample_role"] == "TRAIN"].copy()
    if not train.empty:
        maturity_count = max(train["expiration"].nunique(), 1)
        staged = np.zeros(len(train), dtype=float)
        for _, group in train.groupby("expiration", sort=True):
            local = np.maximum(group["raw_calibration_weight"].to_numpy(dtype=float), 0.0)
            if float(np.sum(local)) <= 0.0:
                local = np.ones(len(group), dtype=float)
            local = local / float(np.sum(local)) / maturity_count
            positions = train.index.get_indexer(group.index)
            staged[positions] = local
        capped = _cap_and_normalize(staged, float(max_quote_weight))
        eligible.loc[train.index, "calibration_weight"] = capped

    frame = frame.merge(
        eligible[[
            "expiration", "strike", "option_type", "sample_role", "vega_raw", "vega_score", "liquidity_score",
            "quality_score", "raw_calibration_weight", "calibration_weight",
        ]],
        on=["expiration", "strike", "option_type"],
        how="left",
    )
    frame["sample_role"] = frame["sample_role"].fillna("EXCLUDED")
    for column in ("vega_raw", "vega_score", "liquidity_score", "quality_score", "raw_calibration_weight", "calibration_weight"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    frame["moneyness_bucket"] = _moneyness_bucket(frame["log_moneyness"])

    train_frame = frame[frame["sample_role"] == "TRAIN"].copy()
    holdout_frame = frame[frame["sample_role"] == "HOLDOUT"].copy()
    weights = train_frame["calibration_weight"].to_numpy(dtype=float)
    effective_sample_size = float((np.sum(weights) ** 2) / max(float(np.sum(weights**2)), 1e-12)) if len(weights) else 0.0

    coverage_rows: list[dict[str, Any]] = []
    for expiration, group in frame[frame["sample_role"].isin(["TRAIN", "HOLDOUT"])].groupby("expiration", sort=True):
        train_group = group[group["sample_role"] == "TRAIN"]
        holdout_group = group[group["sample_role"] == "HOLDOUT"]
        coverage_rows.append({
            "expiration": str(expiration),
            "dte": int(group["dte"].iloc[0]),
            "training_points": int(len(train_group)),
            "holdout_points": int(len(holdout_group)),
            "min_log_moneyness": float(group["log_moneyness"].min()),
            "max_log_moneyness": float(group["log_moneyness"].max()),
            "left_wing_points": int((group["log_moneyness"] < -0.08).sum()),
            "atm_points": int((group["log_moneyness"].abs() <= 0.08).sum()),
            "right_wing_points": int((group["log_moneyness"] > 0.08).sum()),
            "call_points": int((group["option_type"].astype(str).str.lower() == "call").sum()),
            "put_points": int((group["option_type"].astype(str).str.lower() == "put").sum()),
            "training_weight": float(train_group["calibration_weight"].sum()),
            "event_policy_action": str(group["event_policy_action"].iloc[0]),
        })
    coverage = pd.DataFrame(coverage_rows).sort_values("dte").reset_index(drop=True)

    weight_matrix = train_frame.pivot_table(index="expiration", columns="moneyness_bucket", values="calibration_weight", aggfunc="sum", fill_value=0.0, observed=False)
    if not weight_matrix.empty:
        weight_matrix = weight_matrix.reset_index()

    warnings: list[str] = []
    blockers: list[str] = []
    training_maturities = int(train_frame["expiration"].nunique())
    if training_maturities < int(min_maturities):
        blockers.append(f"Only {training_maturities} training maturities survived; minimum is {int(min_maturities)}.")
    if len(train_frame) < int(min_training_points):
        blockers.append(f"Only {len(train_frame)} training quotes survived; minimum is {int(min_training_points)}.")
    if not coverage.empty and (coverage["training_points"] < int(min_points_per_maturity)).any():
        bad = coverage.loc[coverage["training_points"] < int(min_points_per_maturity), "expiration"].astype(str).tolist()
        blockers.append(f"Insufficient training quotes in maturities: {', '.join(bad)}.")
    if effective_sample_size < float(min_effective_sample_size):
        blockers.append(f"Effective sample size {effective_sample_size:.1f} is below the minimum {float(min_effective_sample_size):.1f}.")
    wing_failures = coverage[(coverage["left_wing_points"] == 0) | (coverage["right_wing_points"] == 0) | (coverage["atm_points"] == 0)] if not coverage.empty else coverage
    if not wing_failures.empty:
        warnings.append("At least one maturity lacks left-wing, ATM or right-wing coverage inside the selected calibration band.")
    if len(holdout_frame) < 8:
        warnings.append("The holdout contains fewer than eight quotes; holdout error will have low power.")
    if event_policy == "Keep observed event premium" and len(flagged_events):
        warnings.append("Observed event premium is retained; a continuous stochastic-volatility model may absorb discrete event variance into structural parameters.")
    if event_policy == "Strip estimated discrete event variance" and not len(flagged_events):
        warnings.append("No event window was flagged; the strip policy made no adjustment.")
    if float(train_frame["calibration_weight"].max()) > float(max_quote_weight) + 1e-8:
        warnings.append("The maximum quote-weight constraint could not be enforced exactly.")

    status = "BLOCKED" if blockers else ("WARNING" if warnings else "PASS")
    signature = _signature({
        "version": CALIBRATION_DATASET_VERSION,
        "surface_signature": surface_result.get("configuration_signature"),
        "spot": float(spot),
        "risk_free_rate": float(risk_free_rate),
        "surface_settings": dict(surface_result.get("settings", {})),
        "settings": asdict(settings),
        "training_expiries": sorted(train_frame["expiration"].astype(str).unique().tolist()),
        "training_points": int(len(train_frame)),
        "holdout_points": int(len(holdout_frame)),
    })
    return {
        "ok": not bool(blockers),
        "status": status,
        "version": CALIBRATION_DATASET_VERSION,
        "configuration_signature": signature,
        "surface_signature": surface_result.get("configuration_signature"),
        "spot": float(spot),
        "risk_free_rate": float(risk_free_rate),
        "surface_settings": dict(surface_result.get("settings", {})),
        "settings": asdict(settings),
        "dataset": frame,
        "training_dataset": train_frame,
        "holdout_dataset": holdout_frame,
        "coverage_table": coverage,
        "weight_matrix": weight_matrix,
        "event_adjustments": event_table,
        "training_points": int(len(train_frame)),
        "holdout_points": int(len(holdout_frame)),
        "training_maturities": training_maturities,
        "effective_sample_size": effective_sample_size,
        "maximum_quote_weight": float(train_frame["calibration_weight"].max()) if len(train_frame) else 0.0,
        "event_variance_removed_total": float(frame["event_variance_removed"].max()) if len(frame) else 0.0,
        "warnings": warnings,
        "blockers": blockers,
        "governance": {
            "objective": "Create the exact weighted training and holdout dataset used by future Heston/Bates calibration.",
            "event_policy": str(event_policy),
            "weighting": "Quote weights are constructed from vega, quote liquidity and SVI quality, then normalized by maturity and capped.",
            "holdout": "Holdout assignments are deterministic and excluded from calibration weights.",
            "measure": "Targets are Q-measure total variances/IVs derived from the governed surface.",
            "prohibition": "A PASS dataset does not imply that Heston or Bates will be identifiable or superior out of sample.",
        },
    }
