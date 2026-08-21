from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict
from typing import Any, Dict, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy import stats

from .config import DEFAULT_HORIZONS, MAX_HORIZON, BarrierLevels, ScenarioParameters
from .models.dispatcher import simulate_paths_max_horizon
from .risk_metrics import _summarize_paths

TAIL_EVENT_VERSION = "TAIL-EVENT-STRESS-2.3.1"
TAIL_EVENT_STRESS_TYPES = (
    "EVT tail injection",
    "Merton jump-diffusion",
    "Historical crisis replay",
    "Earnings / overnight gap proxy",
    "Custom deterministic shock",
)


def _finite(values: Sequence[float] | np.ndarray) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    return array[np.isfinite(array)]


def _evt_var_es(
    threshold: float,
    shape: float,
    scale: float,
    exceedance_probability: float,
    confidence: float,
) -> tuple[float, float]:
    tail_probability = max(1.0 - float(confidence), 1e-12)
    ratio = max(float(exceedance_probability) / tail_probability, 1.0)
    xi = float(shape)
    beta = max(float(scale), 1e-12)
    if abs(xi) < 1e-8:
        var_loss = float(threshold + beta * math.log(ratio))
    else:
        var_loss = float(threshold + beta / xi * (ratio**xi - 1.0))
    if xi >= 1.0:
        es_loss = float("inf")
    else:
        es_loss = float((var_loss + beta - xi * float(threshold)) / (1.0 - xi))
    return var_loss, es_loss


def fit_evt_tail(
    log_returns: Sequence[float] | np.ndarray,
    threshold_quantile: float = 0.95,
    bootstrap_repetitions: int = 100,
    seed: int = 42,
) -> Dict[str, Any]:
    values = _finite(log_returns)
    if values.size < 120:
        return {
            "ok": False,
            "status": "INELIGIBLE",
            "reason": "At least 120 returns are required for EVT diagnostics.",
            "observations": int(values.size),
        }

    q = float(np.clip(threshold_quantile, 0.85, 0.995))
    losses = -values
    threshold = float(np.quantile(losses, q))
    exceedances = losses[losses > threshold] - threshold
    exceedances = exceedances[np.isfinite(exceedances) & (exceedances >= 0.0)]
    count = int(exceedances.size)
    exceedance_probability = float(count / values.size)
    if count < 20 or not np.isfinite(threshold):
        return {
            "ok": False,
            "status": "INELIGIBLE",
            "reason": f"Only {count} threshold exceedances are available; at least 20 are required.",
            "observations": int(values.size),
            "threshold_quantile": q,
            "threshold_loss": threshold,
            "exceedances": count,
        }

    try:
        shape, _, scale = stats.genpareto.fit(exceedances, floc=0.0)
        shape = float(shape)
        scale = float(scale)
    except Exception as exc:
        return {
            "ok": False,
            "status": "INELIGIBLE",
            "reason": f"GPD fit failed: {exc}",
            "observations": int(values.size),
            "threshold_quantile": q,
            "threshold_loss": threshold,
            "exceedances": count,
        }

    if not np.isfinite(shape) or not np.isfinite(scale) or scale <= 0.0:
        return {
            "ok": False,
            "status": "INELIGIBLE",
            "reason": "GPD fit produced non-finite parameters.",
            "observations": int(values.size),
            "threshold_quantile": q,
            "threshold_loss": threshold,
            "exceedances": count,
        }

    ks_stat, ks_p = stats.kstest(exceedances, "genpareto", args=(shape, 0.0, scale))
    metrics: Dict[str, float] = {}
    for confidence in (0.99, 0.995, 0.999):
        var_loss, es_loss = _evt_var_es(
            threshold, shape, scale, exceedance_probability, confidence
        )
        label = str(confidence).replace("0.", "")
        metrics[f"var_{label}_loss"] = var_loss
        metrics[f"es_{label}_loss"] = es_loss

    reasons: list[str] = []
    if count < 50:
        reasons.append(f"only {count} exceedances; 50+ preferred")
    if shape >= 1.0:
        reasons.append("shape >= 1 implies infinite tail mean")
    elif shape >= 0.5:
        reasons.append("shape >= 0.5 implies infinite GPD variance")
    if float(ks_p) < 0.05:
        reasons.append("GPD KS goodness-of-fit p-value < 0.05")

    if shape >= 1.0 or count < 25:
        status = "INELIGIBLE"
    elif reasons:
        status = "WARNING"
    else:
        status = "ELIGIBLE"

    rng = np.random.default_rng(int(seed))
    bootstrap_rows: list[dict[str, float]] = []
    repetitions = max(0, min(int(bootstrap_repetitions), 1_000))
    if repetitions > 0 and count >= 20:
        for _ in range(repetitions):
            sample = rng.choice(exceedances, size=count, replace=True)
            try:
                b_shape, _, b_scale = stats.genpareto.fit(sample, floc=0.0)
                b_var, b_es = _evt_var_es(
                    threshold,
                    float(b_shape),
                    float(b_scale),
                    exceedance_probability,
                    0.99,
                )
                if np.isfinite(b_shape) and np.isfinite(b_scale) and np.isfinite(b_var):
                    bootstrap_rows.append(
                        {
                            "shape": float(b_shape),
                            "scale": float(b_scale),
                            "var_99_loss": float(b_var),
                            "es_99_loss": float(b_es),
                        }
                    )
            except Exception:
                continue

    bootstrap = pd.DataFrame(bootstrap_rows)
    intervals: Dict[str, tuple[float, float]] = {}
    for column in ("shape", "scale", "var_99_loss", "es_99_loss"):
        if column in bootstrap and not bootstrap.empty:
            finite = bootstrap[column].replace([np.inf, -np.inf], np.nan).dropna()
            if not finite.empty:
                intervals[column] = (
                    float(finite.quantile(0.025)),
                    float(finite.quantile(0.975)),
                )

    return {
        "ok": True,
        "status": status,
        "reasons": reasons,
        "observations": int(values.size),
        "threshold_quantile": q,
        "threshold_loss": threshold,
        "threshold_return": -threshold,
        "exceedances": count,
        "exceedance_probability": exceedance_probability,
        "shape": shape,
        "scale": scale,
        "ks_statistic": float(ks_stat),
        "ks_p_value": float(ks_p),
        "finite_mean": bool(shape < 1.0),
        "finite_variance": bool(shape < 0.5),
        "metrics": metrics,
        "bootstrap_intervals": intervals,
        "bootstrap_successes": int(len(bootstrap)),
        "excesses": exceedances,
    }


def evt_threshold_stability(
    log_returns: Sequence[float] | np.ndarray,
    quantiles: Sequence[float] = (0.90, 0.925, 0.95, 0.975),
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for idx, quantile in enumerate(quantiles):
        fit = fit_evt_tail(log_returns, float(quantile), bootstrap_repetitions=0, seed=100 + idx)
        rows.append(
            {
                "Threshold quantile": float(quantile),
                "Status": fit.get("status"),
                "Threshold loss": fit.get("threshold_loss"),
                "Exceedances": fit.get("exceedances", 0),
                "Shape xi": fit.get("shape"),
                "Scale beta": fit.get("scale"),
                "KS p-value": fit.get("ks_p_value"),
                "VaR 99% loss": fit.get("metrics", {}).get("var_99_loss"),
                "ES 99% loss": fit.get("metrics", {}).get("es_99_loss"),
            }
        )
    return pd.DataFrame(rows)


def assess_evt_threshold_stability(
    stability: pd.DataFrame,
    minimum_valid_thresholds: int = 3,
    shape_range_warning: float = 0.15,
    es99_range_warning: float = 0.03,
) -> Dict[str, Any]:
    """Govern EVT threshold sensitivity without altering the selected fit.

    The selected threshold can fit well while nearby thresholds imply materially
    different tail shapes. This diagnostic keeps fit quality and threshold
    stability separate and auditable.
    """
    if not isinstance(stability, pd.DataFrame) or stability.empty:
        return {
            "status": "INELIGIBLE",
            "reasons": ["EVT threshold-stability table is unavailable"],
            "valid_thresholds": 0,
            "shape_range": None,
            "es99_range": None,
        }

    table = stability.copy()
    table["Shape xi"] = pd.to_numeric(table.get("Shape xi"), errors="coerce")
    table["ES 99% loss"] = pd.to_numeric(table.get("ES 99% loss"), errors="coerce")
    valid = table[table["Status"].isin(["ELIGIBLE", "WARNING"])].dropna(
        subset=["Shape xi", "ES 99% loss"]
    )
    count = int(len(valid))
    if count == 0:
        return {
            "status": "INELIGIBLE",
            "reasons": ["No valid EVT threshold fits are available"],
            "valid_thresholds": 0,
            "shape_range": None,
            "es99_range": None,
        }

    shape_range = float(valid["Shape xi"].max() - valid["Shape xi"].min())
    es99_range = float(valid["ES 99% loss"].max() - valid["ES 99% loss"].min())
    reasons: list[str] = []
    if count < int(minimum_valid_thresholds):
        reasons.append(
            f"only {count} valid thresholds; {int(minimum_valid_thresholds)}+ required"
        )
    if shape_range > float(shape_range_warning):
        reasons.append(
            f"GPD shape range {shape_range:.4f} exceeds {float(shape_range_warning):.4f}"
        )
    if es99_range > float(es99_range_warning):
        reasons.append(
            f"EVT ES 99% range {es99_range:.2%} exceeds {float(es99_range_warning):.2%}"
        )

    status = "ELIGIBLE" if not reasons else "WARNING"
    if count < 2:
        status = "INELIGIBLE"
    return {
        "status": status,
        "reasons": reasons,
        "valid_thresholds": count,
        "shape_range": shape_range,
        "es99_range": es99_range,
        "shape_min": float(valid["Shape xi"].min()),
        "shape_max": float(valid["Shape xi"].max()),
        "es99_min": float(valid["ES 99% loss"].min()),
        "es99_max": float(valid["ES 99% loss"].max()),
    }


def calibrate_merton_jumps(
    log_returns: Sequence[float] | np.ndarray,
    periods_per_year: int = 252,
    z_threshold: float = 3.0,
) -> Dict[str, Any]:
    values = _finite(log_returns)
    if values.size < 120:
        return {
            "ok": False,
            "status": "INELIGIBLE",
            "reason": "At least 120 returns are required for jump calibration.",
        }
    center = float(np.median(values))
    mad = float(np.median(np.abs(values - center)))
    robust_sigma = max(1.4826 * mad, float(np.std(values, ddof=1)) * 0.50, 1e-8)
    z = (values - center) / robust_sigma
    mask = np.abs(z) >= float(max(z_threshold, 2.0))
    jumps = values[mask] - center
    regular = values[~mask]
    count = int(jumps.size)
    if count < 5:
        return {
            "ok": False,
            "status": "INELIGIBLE",
            "reason": f"Only {count} jumps detected.",
            "jump_count": count,
        }

    jump_mu = float(np.mean(jumps))
    jump_sigma = max(float(np.std(jumps, ddof=1)) if count > 1 else robust_sigma, 1e-8)
    intensity_ann = float(count / values.size * int(periods_per_year))
    diffusion_sigma_period = max(
        float(np.std(regular, ddof=1)) if regular.size > 2 else robust_sigma,
        1e-8,
    )
    diffusion_vol_ann = diffusion_sigma_period * math.sqrt(int(periods_per_year))
    compensator = float(math.exp(jump_mu + 0.5 * jump_sigma**2) - 1.0)

    reasons: list[str] = []
    if count < 20:
        reasons.append(f"only {count} detected jumps; 20+ preferred")
    if count / values.size > 0.10:
        reasons.append("jump classification exceeds 10% of observations")
    status = "ELIGIBLE" if not reasons else "WARNING"
    return {
        "ok": True,
        "status": status,
        "reasons": reasons,
        "observations": int(values.size),
        "z_threshold": float(z_threshold),
        "jump_count": count,
        "jump_frequency": float(count / values.size),
        "jump_intensity_ann": intensity_ann,
        "jump_log_mean": jump_mu,
        "jump_log_sigma": jump_sigma,
        "jump_compensator": compensator,
        "diffusion_vol_ann": diffusion_vol_ann,
        "robust_sigma_period": robust_sigma,
    }


def historical_event_library(
    calibration_df: pd.DataFrame,
    window_lengths: Sequence[int] = (1, 5, 10, 20),
    events_per_window: int = 3,
) -> pd.DataFrame:
    if not isinstance(calibration_df, pd.DataFrame) or calibration_df.empty or "close" not in calibration_df:
        return pd.DataFrame()
    frame = calibration_df.copy().reset_index(drop=True)
    frame["log_return"] = np.log(frame["close"].astype(float) / frame["close"].astype(float).shift(1))
    rows: list[dict[str, Any]] = []
    for window in window_lengths:
        window = int(window)
        if window < 1 or len(frame) <= window:
            continue
        rolling = frame["log_return"].rolling(window).sum()
        candidates = rolling.dropna().sort_values().index.tolist()
        selected_ranges: list[tuple[int, int]] = []
        selected = 0
        for end_idx in candidates:
            start_idx = int(end_idx) - window + 1
            if any(not (int(end_idx) < start or start_idx > end) for start, end in selected_ranges):
                continue
            sequence = frame.loc[start_idx:int(end_idx), "log_return"].to_numpy(dtype=float)
            if sequence.size != window or not np.isfinite(sequence).all():
                continue
            cumulative_return = float(math.exp(float(sequence.sum())) - 1.0)
            path = np.exp(np.cumsum(sequence))
            drawdown = path / np.maximum.accumulate(path) - 1.0
            start_date = frame.loc[start_idx, "date"] if "date" in frame else start_idx
            end_date = frame.loc[int(end_idx), "date"] if "date" in frame else int(end_idx)
            rows.append(
                {
                    "Event ID": f"W{window}_{pd.Timestamp(start_date).strftime('%Y%m%d') if not isinstance(start_date, (int, np.integer)) else start_idx}",
                    "Window": window,
                    "Start": start_date,
                    "End": end_date,
                    "Cumulative return": cumulative_return,
                    "Realized volatility": float(np.std(sequence, ddof=1) * math.sqrt(252)) if window > 1 else abs(float(sequence[0])) * math.sqrt(252),
                    "Max drawdown": float(drawdown.min()),
                    "Sequence": sequence,
                }
            )
            selected_ranges.append((start_idx, int(end_idx)))
            selected += 1
            if selected >= int(events_per_window):
                break
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["Cumulative return", "Window"]).reset_index(drop=True)


def calibrate_overnight_gaps(calibration_df: pd.DataFrame) -> Dict[str, Any]:
    if not isinstance(calibration_df, pd.DataFrame) or calibration_df.empty:
        return {"ok": False, "status": "INELIGIBLE", "reason": "No calibration frame."}
    if "open" not in calibration_df or "close" not in calibration_df:
        return {"ok": False, "status": "INELIGIBLE", "reason": "Open and close are required."}
    previous_close = calibration_df["close"].astype(float).shift(1)
    gaps = np.log(calibration_df["open"].astype(float) / previous_close)
    gaps = gaps.replace([np.inf, -np.inf], np.nan).dropna().to_numpy(dtype=float)
    gaps = gaps[np.isfinite(gaps)]
    if gaps.size < 120:
        return {"ok": False, "status": "INELIGIBLE", "reason": "Insufficient overnight gaps."}
    negative = gaps[gaps < 0.0]
    if negative.size < 20:
        return {"ok": False, "status": "INELIGIBLE", "reason": "Insufficient negative gaps."}
    return {
        "ok": True,
        "status": "ELIGIBLE" if gaps.size >= 500 else "WARNING",
        "observations": int(gaps.size),
        "negative_gaps": int(negative.size),
        "gap_p01": float(np.quantile(gaps, 0.01)),
        "gap_p025": float(np.quantile(gaps, 0.025)),
        "gap_p05": float(np.quantile(gaps, 0.05)),
        "worst_gap": float(np.min(gaps)),
        "median_gap": float(np.median(gaps)),
    }


def _resample_rows(paths: np.ndarray, simulations: int, seed: int) -> np.ndarray:
    array = np.asarray(paths, dtype=float)
    simulations = int(simulations)
    if array.shape[0] == simulations:
        return array.copy()
    rng = np.random.default_rng(int(seed))
    indices = rng.integers(0, array.shape[0], size=simulations)
    return array[indices].copy()


def _paths_to_log_steps(paths: np.ndarray) -> np.ndarray:
    return np.log(np.maximum(paths[:, 1:], 1e-12) / np.maximum(paths[:, :-1], 1e-12))


def _log_steps_to_paths(start_price: float, log_steps: np.ndarray) -> np.ndarray:
    simulations = int(log_steps.shape[0])
    paths = np.empty((simulations, log_steps.shape[1] + 1), dtype=float)
    paths[:, 0] = float(start_price)
    paths[:, 1:] = float(start_price) * np.exp(np.cumsum(log_steps, axis=1))
    return np.maximum(paths, float(start_price) * 1e-4)


def simulate_merton_paths(
    start_price: float,
    drift_ann: float,
    diffusion_vol_ann: float,
    jump_fit: Mapping[str, Any],
    simulations: int,
    horizon: int,
    periods_per_year: int,
    seed: int,
    intensity_multiplier: float = 1.0,
    severity_multiplier: float = 1.0,
) -> tuple[np.ndarray, Dict[str, Any]]:
    if not jump_fit.get("ok"):
        raise ValueError(jump_fit.get("reason", "Jump calibration unavailable."))
    rng = np.random.default_rng(int(seed))
    ppy = max(int(periods_per_year), 1)
    lam_ann = max(float(jump_fit["jump_intensity_ann"]) * float(intensity_multiplier), 0.0)
    mu_j = float(jump_fit["jump_log_mean"]) * float(severity_multiplier)
    sigma_j = max(float(jump_fit["jump_log_sigma"]) * abs(float(severity_multiplier)), 1e-10)
    kappa = math.exp(mu_j + 0.5 * sigma_j**2) - 1.0
    diffusion_vol_ann = max(float(diffusion_vol_ann), 1e-10)
    drift_step = (float(drift_ann) - lam_ann * kappa - 0.5 * diffusion_vol_ann**2) / ppy
    diffusion_step = diffusion_vol_ann / math.sqrt(ppy)
    counts = rng.poisson(lam=lam_ann / ppy, size=(int(simulations), int(horizon)))
    jump_component = counts * mu_j + np.sqrt(counts) * sigma_j * rng.normal(size=counts.shape)
    log_steps = drift_step + diffusion_step * rng.normal(size=counts.shape) + jump_component
    paths = _log_steps_to_paths(float(start_price), log_steps)
    metadata = {
        "model": "Merton jump-diffusion",
        "jump_intensity_ann": lam_ann,
        "jump_log_mean": mu_j,
        "jump_log_sigma": sigma_j,
        "jump_compensator": kappa,
        "simulated_jump_count": int(counts.sum()),
        "supports_bridge": False,
        "step_log_variance": float((diffusion_vol_ann / math.sqrt(ppy)) ** 2),
    }
    return paths, metadata


def _stress_signature(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16].upper()


def build_tail_event_stress(
    lab: Mapping[str, Any],
    stress_type: str = "EVT tail injection",
    simulations: int = 5_000,
    threshold_quantile: float = 0.95,
    evt_intensity_multiplier: float = 1.5,
    severity_multiplier: float = 1.0,
    volatility_multiplier: float = 1.0,
    event_day: int = 1,
    historical_event_id: str | None = None,
    gap_quantile: float = 0.01,
    custom_shock: float = -0.15,
    bootstrap_repetitions: int = 100,
    seed: int = 42,
) -> Dict[str, Any]:
    if not lab.get("ok"):
        return {"ok": False, "status": "BLOCKED", "reason": "Base Monte Carlo lab is unavailable."}
    if stress_type not in TAIL_EVENT_STRESS_TYPES:
        stress_type = "EVT tail injection"

    simulations = max(250, min(int(simulations), 100_000))
    event_day = max(1, min(int(event_day), MAX_HORIZON))
    base = lab["base"]
    levels_obj = lab.get("levels_object")
    if levels_obj is None:
        levels_obj = BarrierLevels(**lab["levels"])

    selected_model = str(lab["settings"]["model"])
    selected_scenario = str(lab["settings"]["scenario"])
    baseline_paths, params, baseline_metadata = simulate_paths_max_horizon(
        base=base,
        scenario=selected_scenario,
        model=selected_model,
        simulations=simulations,
        seed=int(seed),
        max_horizon=MAX_HORIZON,
        mean_block_length=int(lab["settings"].get("mean_block_length", 10)),
        ewma_lambda=float(lab["settings"].get("ewma_lambda", 0.94)),
    )
    baseline_steps = _paths_to_log_steps(baseline_paths)
    stressed_steps = baseline_steps.copy()

    evt_fit = fit_evt_tail(
        base["log_return_values"],
        threshold_quantile=float(threshold_quantile),
        bootstrap_repetitions=int(bootstrap_repetitions),
        seed=int(seed) + 17,
    )
    evt_stability = evt_threshold_stability(base["log_return_values"])
    evt_stability_diagnostic = assess_evt_threshold_stability(evt_stability)
    jump_fit = calibrate_merton_jumps(
        base["log_return_values"],
        periods_per_year=int(base["periods_per_year"]),
    )
    event_library = historical_event_library(base["calibration_df"])
    gap_fit = calibrate_overnight_gaps(base["calibration_df"])

    stress_status = "STRESS_ONLY"
    stress_reasons: list[str] = []
    stress_metadata: Dict[str, Any] = {
        "stress_type": stress_type,
        "event_day": event_day,
        "severity_multiplier": float(severity_multiplier),
        "volatility_multiplier": float(volatility_multiplier),
        "monitoring": "Clôture de chaque pas",
    }

    if stress_type == "EVT tail injection":
        if not evt_fit.get("ok"):
            return {"ok": False, "status": "BLOCKED", "reason": evt_fit.get("reason"), "evt_fit": evt_fit}
        rng = np.random.default_rng(int(seed) + 1_003)
        event_probability = min(
            float(evt_fit["exceedance_probability"]) * max(float(evt_intensity_multiplier), 0.0),
            0.50,
        )
        event_mask = rng.random(size=stressed_steps.shape) < event_probability
        event_mask[:, : max(event_day - 1, 0)] = False
        count = int(event_mask.sum())
        if count > 0:
            excesses = stats.genpareto.rvs(
                c=float(evt_fit["shape"]),
                loc=0.0,
                scale=float(evt_fit["scale"]),
                size=count,
                random_state=rng,
            )
            tail_losses = (float(evt_fit["threshold_loss"]) + np.asarray(excesses)) * float(severity_multiplier)
            existing_losses = np.maximum(-stressed_steps[event_mask], 0.0)
            stressed_steps[event_mask] -= np.maximum(tail_losses - existing_losses, 0.0)
        expected_events_by_horizon = {
            int(h): float(event_probability * max(int(h) - max(event_day - 1, 0), 0))
            for h in DEFAULT_HORIZONS
        }
        evt_governance_status = str(evt_fit.get("status", "INELIGIBLE"))
        if evt_governance_status == "ELIGIBLE" and evt_stability_diagnostic.get("status") != "ELIGIBLE":
            evt_governance_status = str(evt_stability_diagnostic.get("status"))
        stress_metadata.update(
            {
                "evt_status": evt_fit.get("status"),
                "evt_stability_status": evt_stability_diagnostic.get("status"),
                "evt_governance_status": evt_governance_status,
                "tail_event_probability_per_step": event_probability,
                "expected_tail_events_by_horizon": expected_events_by_horizon,
                "injected_tail_events": count,
                "threshold_quantile": float(threshold_quantile),
            }
        )
        if evt_fit.get("status") != "ELIGIBLE":
            stress_reasons.extend(evt_fit.get("reasons", []))
        if evt_stability_diagnostic.get("status") != "ELIGIBLE":
            stress_reasons.extend(evt_stability_diagnostic.get("reasons", []))
        if expected_events_by_horizon.get(30, 0.0) > 1.0:
            stress_reasons.append(
                f"severe EVT frequency: {expected_events_by_horizon[30]:.2f} expected injected events per 30D path"
            )

    elif stress_type == "Merton jump-diffusion":
        if not jump_fit.get("ok"):
            return {"ok": False, "status": "BLOCKED", "reason": jump_fit.get("reason"), "jump_fit": jump_fit}
        stressed_paths, merton_metadata = simulate_merton_paths(
            start_price=float(base["current_price"]),
            drift_ann=float(params.drift_ann),
            diffusion_vol_ann=float(jump_fit["diffusion_vol_ann"]) * float(volatility_multiplier),
            jump_fit=jump_fit,
            simulations=simulations,
            horizon=MAX_HORIZON,
            periods_per_year=int(base["periods_per_year"]),
            seed=int(seed) + 2_003,
            intensity_multiplier=float(evt_intensity_multiplier),
            severity_multiplier=float(severity_multiplier),
        )
        stressed_steps = _paths_to_log_steps(stressed_paths)
        stress_metadata.update(merton_metadata)
        if jump_fit.get("status") != "ELIGIBLE":
            stress_reasons.extend(jump_fit.get("reasons", []))

    elif stress_type == "Historical crisis replay":
        if event_library.empty:
            return {"ok": False, "status": "BLOCKED", "reason": "No historical stress windows are available."}
        if historical_event_id is None or historical_event_id not in set(event_library["Event ID"]):
            selected_event = event_library.iloc[0]
        else:
            selected_event = event_library[event_library["Event ID"] == historical_event_id].iloc[0]
        sequence = np.asarray(selected_event["Sequence"], dtype=float) * float(severity_multiplier)
        start = event_day - 1
        end = min(start + sequence.size, MAX_HORIZON)
        sequence = sequence[: end - start]
        if sequence.size:
            stressed_steps[:, start:end] = sequence[None, :]
        stress_metadata.update(
            {
                "historical_event_id": str(selected_event["Event ID"]),
                "historical_event_start": str(selected_event["Start"]),
                "historical_event_end": str(selected_event["End"]),
                "historical_event_return": float(selected_event["Cumulative return"]),
                "replay_length": int(sequence.size),
            }
        )

    elif stress_type == "Earnings / overnight gap proxy":
        if not gap_fit.get("ok"):
            return {"ok": False, "status": "BLOCKED", "reason": gap_fit.get("reason"), "gap_fit": gap_fit}
        quantile_map = {
            0.01: "gap_p01",
            0.025: "gap_p025",
            0.05: "gap_p05",
        }
        closest = min(quantile_map, key=lambda q: abs(q - float(gap_quantile)))
        shock = float(gap_fit[quantile_map[closest]]) * float(severity_multiplier)
        stressed_steps[:, event_day - 1] += shock
        stress_metadata.update(
            {
                "gap_status": gap_fit.get("status"),
                "gap_quantile": closest,
                "gap_log_shock": shock,
                "gap_simple_shock": math.exp(shock) - 1.0,
                "proxy_warning": "Overnight-gap proxy; actual earnings dates are not used.",
            }
        )

    elif stress_type == "Custom deterministic shock":
        shock = float(np.clip(custom_shock, -0.95, 3.0))
        stressed_steps[:, event_day - 1] += math.log1p(shock)
        stress_metadata.update({"custom_simple_shock": shock, "custom_log_shock": math.log1p(shock)})

    if float(volatility_multiplier) != 1.0 and stress_type != "Merton jump-diffusion":
        start = max(event_day - 1, 0)
        end = min(start + 10, MAX_HORIZON)
        drift_step = float(params.drift_ann) / int(base["periods_per_year"])
        stressed_steps[:, start:end] = drift_step + (
            stressed_steps[:, start:end] - drift_step
        ) * float(volatility_multiplier)
        stress_metadata["volatility_cluster_window"] = (start + 1, end)

    stressed_paths = _log_steps_to_paths(float(base["current_price"]), stressed_steps)
    baseline_model_metadata = dict(baseline_metadata)
    baseline_model_metadata.update(
        {
            "eligibility_status": "RESEARCH_CONTROL",
            "eligible_for_aggregation": False,
            "research_only": True,
            "barrier_monitoring_requested": "Clôture de chaque pas",
            "barrier_monitoring_effective": "Clôture de chaque pas",
            "barrier_monitoring_forced": True,
        }
    )
    stressed_model_metadata = {
        "model": stress_type,
        "supports_bridge": False,
        "step_log_variance": float(np.var(stressed_steps[:, 0])) if stressed_steps.size else 0.0,
        "calibration_status": stress_status,
        "calibration_converged": True,
        "calibration_warning": "; ".join(stress_reasons),
        "fallback_used": False,
        "eligibility_status": stress_status,
        "eligibility_reasons": stress_reasons,
        "eligible_for_aggregation": False,
        "research_only": True,
        "barrier_monitoring_requested": "Clôture de chaque pas",
        "barrier_monitoring_effective": "Clôture de chaque pas",
        "barrier_monitoring_forced": True,
    }
    stress_params = ScenarioParameters(
        drift_ann=float(params.drift_ann),
        vol_ann=float(params.vol_ann) * float(volatility_multiplier),
        drift_multiplier=float(params.drift_multiplier),
        volatility_multiplier=float(params.volatility_multiplier) * float(volatility_multiplier),
        note=f"Tail/Event stress: {stress_type}",
    )

    baseline_summaries: Dict[int, Dict[str, Any]] = {}
    stressed_summaries: Dict[int, Dict[str, Any]] = {}
    paths_by_horizon: Dict[int, np.ndarray] = {}
    baseline_paths_by_horizon: Dict[int, np.ndarray] = {}
    for horizon in DEFAULT_HORIZONS:
        baseline_paths_by_horizon[horizon] = baseline_paths[:, : horizon + 1]
        paths_by_horizon[horizon] = stressed_paths[:, : horizon + 1]
        baseline_summaries[horizon] = _summarize_paths(
            baseline_paths,
            levels_obj,
            params,
            baseline_model_metadata,
            horizon,
            selected_scenario,
            selected_model,
            "Clôture de chaque pas",
            int(seed),
            confidence=float(lab["settings"].get("confidence_level", 0.95)),
            ruin_threshold=float(lab["settings"].get("ruin_threshold", -0.30)),
            include_diagnostics=True,
        )
        stressed_summaries[horizon] = _summarize_paths(
            stressed_paths,
            levels_obj,
            stress_params,
            stressed_model_metadata,
            horizon,
            stress_type,
            stress_type,
            "Clôture de chaque pas",
            int(seed) + 10_000,
            confidence=float(lab["settings"].get("confidence_level", 0.95)),
            ruin_threshold=float(lab["settings"].get("ruin_threshold", -0.30)),
            include_diagnostics=True,
        )

    delta_rows: list[dict[str, Any]] = []
    metrics = (
        ("Expected return", "expected_return"),
        ("VaR 5%", "var_5"),
        ("ES 5%", "es_5"),
        ("VaR 1%", "var_1"),
        ("ES 1%", "es_1"),
        ("Expected max drawdown", "expected_max_drawdown"),
        ("Ruin probability", "prob_ruin"),
        ("Target before stop", "prob_target_before_stop"),
        ("Stop before target", "prob_stop_before_target"),
    )
    for horizon in DEFAULT_HORIZONS:
        base_summary = baseline_summaries[horizon]
        stress_summary = stressed_summaries[horizon]
        for label, key in metrics:
            delta_rows.append(
                {
                    "Horizon": horizon,
                    "Metric": label,
                    "Baseline": float(base_summary[key]),
                    "Stressed": float(stress_summary[key]),
                    "Delta": float(stress_summary[key] - base_summary[key]),
                }
            )
    delta_table = pd.DataFrame(delta_rows)

    signature_payload = {
        "base_signature": lab.get("configuration_signature"),
        "stress_type": stress_type,
        "simulations": simulations,
        "threshold_quantile": threshold_quantile,
        "intensity_multiplier": evt_intensity_multiplier,
        "severity_multiplier": severity_multiplier,
        "volatility_multiplier": volatility_multiplier,
        "event_day": event_day,
        "historical_event_id": historical_event_id,
        "gap_quantile": gap_quantile,
        "custom_shock": custom_shock,
        "seed": seed,
    }
    signature = _stress_signature(signature_payload)

    return {
        "ok": True,
        "status": stress_status,
        "tail_event_version": TAIL_EVENT_VERSION,
        "configuration_signature": signature,
        "ticker": lab.get("ticker"),
        "stress_type": stress_type,
        "base": base,
        "levels": dict(lab["levels"]),
        "levels_object": levels_obj,
        "paths_by_horizon": paths_by_horizon,
        "baseline_paths_by_horizon": baseline_paths_by_horizon,
        "summaries_by_horizon": stressed_summaries,
        "baseline_summaries_by_horizon": baseline_summaries,
        "delta_table": delta_table,
        "evt_fit": evt_fit,
        "evt_threshold_stability": evt_stability,
        "evt_stability_diagnostic": evt_stability_diagnostic,
        "jump_fit": jump_fit,
        "gap_fit": gap_fit,
        "event_library": event_library,
        "stress_metadata": stress_metadata,
        "assumptions": {
            "measure": "Physical P / deterministic stress",
            "aggregation": "Stress results never enter validated model aggregation automatically.",
            "barrier_monitoring": "Discrete close monitoring for baseline and stressed paths to preserve comparability.",
            "evt_method": "Peaks-over-threshold GPD fitted to log-loss exceedances.",
            "historical_replay": "Observed adjusted-price return sequence replayed without assigning a probability.",
            "gap_proxy": "Overnight open/previous-close gaps; actual earnings dates are not inferred.",
            "configuration": signature_payload,
        },
    }
