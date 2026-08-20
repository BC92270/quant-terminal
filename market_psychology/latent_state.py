from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import numpy as np
import pandas as pd


LATENT_KEYS: tuple[str, ...] = (
    "attention",
    "fear",
    "herding",
    "extrapolation",
    "reflexivity",
)


@dataclass(frozen=True)
class LatentSpec:
    key: str
    label: str
    process_ratio: float
    min_measurement_var: float
    history_window: int = 126
    percentile_window: int = 252
    normalization_window: int = 252
    normalization_min_periods: int = 40
    shock_mode: str = "positive"  # positive | absolute


LATENT_SPECS: dict[str, LatentSpec] = {
    "attention": LatentSpec("attention", "Attention", 0.055, 30.0, shock_mode="absolute"),
    "fear": LatentSpec("fear", "Fear", 0.040, 22.0, shock_mode="positive"),
    "herding": LatentSpec("herding", "Herding", 0.028, 16.0, shock_mode="positive"),
    "extrapolation": LatentSpec("extrapolation", "Extrapolation", 0.035, 20.0, shock_mode="positive"),
    "reflexivity": LatentSpec("reflexivity", "Reflexivity", 0.032, 18.0, shock_mode="positive"),
}


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        out = float(value)
        return out if np.isfinite(out) else default
    except Exception:
        return default


def _clip_score(value: Any, default: float = 50.0) -> float:
    x = _safe_float(value, default)
    if x is None:
        x = default
    return float(np.clip(x, 0.0, 100.0))


def _robust_scale(values: pd.Series, floor: float = 4.0) -> float:
    s = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if len(s) < 8:
        return float(floor)
    med = float(s.median())
    mad = float((s - med).abs().median())
    scale = 1.4826 * mad
    if not np.isfinite(scale) or scale < floor:
        sd = float(s.std(ddof=1)) if len(s) > 1 else floor
        scale = sd if np.isfinite(sd) and sd >= floor else floor
    return float(scale)


def _z_to_score(z: Any) -> float:
    """
    Robust z -> bounded 0..100 state coordinate.

    The tanh mapping is deliberately softer than a Gaussian CDF so a one-sigma
    move does not immediately become an extreme state. 50 represents the causal
    historical centre of the mechanism for the instrument.
    """
    zf = _safe_float(z, 0.0) or 0.0
    zf = float(np.clip(zf, -6.0, 6.0))
    return float(np.clip(50.0 + 50.0 * np.tanh(zf / 2.2), 0.0, 100.0))


def causal_robust_normalize(
    observed: pd.Series,
    *,
    window: int = 252,
    min_periods: int = 40,
    scale_floor: float = 2.5,
) -> pd.DataFrame:
    """
    Point-in-time robust normalization of a raw 0..100 proxy.

    Each observation is standardized only against *previous* observations. This
    prevents the structural level of a proxy (for example persistently high raw
    cross-asset correlation) from being mistaken for an acute behavioral extreme.
    """
    s = pd.to_numeric(observed, errors="coerce").astype(float)
    score = pd.Series(np.nan, index=s.index, dtype=float)
    z_out = pd.Series(np.nan, index=s.index, dtype=float)
    center = pd.Series(np.nan, index=s.index, dtype=float)
    scale_out = pd.Series(np.nan, index=s.index, dtype=float)

    values = s.to_numpy(dtype=float)
    for i, current in enumerate(values):
        if not np.isfinite(current):
            continue
        start = max(0, i - int(window))
        hist = values[start:i]
        hist = hist[np.isfinite(hist)]
        if len(hist) < int(min_periods):
            continue
        hist_s = pd.Series(hist, dtype=float)
        med = float(hist_s.median())
        scale = _robust_scale(hist_s, floor=scale_floor)
        z = (float(current) - med) / max(scale, 1e-8)
        score.iloc[i] = _z_to_score(z)
        z_out.iloc[i] = z
        center.iloc[i] = med
        scale_out.iloc[i] = scale

    return pd.DataFrame({
        "normalized": score,
        "normalization_z": z_out,
        "normalization_center": center,
        "normalization_scale": scale_out,
    })


def normalize_current_observation(
    current: Any,
    history: pd.Series,
    *,
    window: int = 252,
    min_periods: int = 40,
    scale_floor: float = 2.5,
) -> tuple[float, float | None, float | None, float | None]:
    """Normalize the live observation against the trailing historical raw proxy only."""
    current_f = _safe_float(current)
    hist = pd.to_numeric(history, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().tail(int(window))
    if current_f is None:
        return 50.0, None, None, None
    if len(hist) < int(min_periods):
        return _clip_score(current_f), None, None, None
    med = float(hist.median())
    scale = _robust_scale(hist, floor=scale_floor)
    z = (current_f - med) / max(scale, 1e-8)
    return _z_to_score(z), float(z), med, scale


def causal_local_level_filter(
    observed: pd.Series,
    *,
    process_ratio: float = 0.04,
    min_measurement_var: float = 20.0,
    variance_window: int = 60,
) -> pd.DataFrame:
    """
    One-sided local-level Kalman filter for a bounded 0..100 behavioral proxy.

    State equation
        x_t = x_{t-1} + eta_t
    Measurement equation
        y_t = x_t + epsilon_t

    Measurement variance is estimated only from information available before t.
    Initial missing observations stay missing; the filter never initializes from a
    future non-missing value.
    """
    y = pd.to_numeric(observed, errors="coerce").astype(float)
    index = y.index

    latent = pd.Series(np.nan, index=index, dtype=float)
    innovation = pd.Series(np.nan, index=index, dtype=float)
    innovation_z = pd.Series(np.nan, index=index, dtype=float)
    gain = pd.Series(np.nan, index=index, dtype=float)
    state_sd = pd.Series(np.nan, index=index, dtype=float)
    measurement_sd = pd.Series(np.nan, index=index, dtype=float)

    x_prev: float | None = None
    p_prev = 100.0
    past_innovations: list[float] = []

    for idx in index:
        obs = _safe_float(y.loc[idx])
        if obs is None:
            if x_prev is not None:
                latent.loc[idx] = x_prev
                state_sd.loc[idx] = float(np.sqrt(max(p_prev, 0.0)))
            continue

        if x_prev is None:
            # First *available at this timestamp* observation. No look-ahead initialization.
            x_prev = _clip_score(obs)
            p_prev = 100.0
            latent.loc[idx] = x_prev
            innovation.loc[idx] = 0.0
            innovation_z.loc[idx] = 0.0
            gain.loc[idx] = 1.0
            state_sd.loc[idx] = float(np.sqrt(p_prev))
            measurement_sd.loc[idx] = float(np.sqrt(max(min_measurement_var * 2.5, 36.0)))
            continue

        if past_innovations:
            hist = pd.Series(past_innovations[-variance_window:], dtype=float)
            meas_sd = _robust_scale(hist, floor=float(np.sqrt(min_measurement_var)))
            r_t = max(meas_sd ** 2, min_measurement_var)
        else:
            r_t = max(min_measurement_var * 2.5, 36.0)
            meas_sd = float(np.sqrt(r_t))

        q_t = max(r_t * float(process_ratio), 0.35)
        x_pred = x_prev
        p_pred = p_prev + q_t
        k_t = p_pred / (p_pred + r_t)
        innov = obs - x_pred
        x_now = _clip_score(x_pred + k_t * innov)
        p_now = max((1.0 - k_t) * p_pred, 1e-6)

        latent.loc[idx] = x_now
        innovation.loc[idx] = innov
        denom = float(np.sqrt(max(p_pred + r_t, 1e-6)))
        innovation_z.loc[idx] = innov / denom
        gain.loc[idx] = k_t
        state_sd.loc[idx] = float(np.sqrt(p_now))
        measurement_sd.loc[idx] = meas_sd

        past_innovations.append(float(innov))
        x_prev = x_now
        p_prev = p_now

    return pd.DataFrame({
        "latent": latent,
        "innovation": innovation,
        "innovation_z": innovation_z,
        "gain": gain,
        "state_sd": state_sd,
        "measurement_sd": measurement_sd,
    })


def causal_percentile(series: pd.Series, window: int = 252, min_periods: int = 60) -> pd.Series:
    """Percentile rank versus the *previous* rolling window; no future observations are used."""
    s = pd.to_numeric(series, errors="coerce")
    out = pd.Series(np.nan, index=s.index, dtype=float)
    values = s.to_numpy(dtype=float)
    for i in range(len(values)):
        current = values[i]
        if not np.isfinite(current):
            continue
        start = max(0, i - int(window))
        hist = values[start:i]
        hist = hist[np.isfinite(hist)]
        if len(hist) < min_periods:
            continue
        less = np.sum(hist < current)
        equal = np.sum(hist == current)
        out.iloc[i] = 100.0 * (less + 0.5 * equal) / len(hist)
    return out


def _rolling_ar1(series: pd.Series, window: int = 126, min_periods: int = 40) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    return s.rolling(window, min_periods=min_periods).apply(
        lambda x: float(pd.Series(x).autocorr(1)) if pd.Series(x).notna().sum() >= min_periods else np.nan,
        raw=False,
    ).clip(-1.0, 1.0)


def structural_state_label(score: Any) -> tuple[str, int]:
    """Persistent state geometry. This is deliberately separate from an acute event alarm."""
    s = _clip_score(score)
    if s >= 82:
        return "EXTREME", 3
    if s >= 70:
        return "HIGH", 2
    if s >= 58:
        return "ELEVATED", 1
    if s <= 35:
        return "LOW", 0
    return "NORMAL", 0


def shock_semantics(key: str, shock_z: Any) -> str:
    z = _safe_float(shock_z, 0.0) or 0.0
    key = str(key).lower().strip()
    if abs(z) < 0.75:
        return "NEUTRAL"
    if key == "attention":
        return "ATTENTION SURGE" if z > 0 else "ATTENTION COLLAPSE"
    if key == "fear":
        return "FEAR STRESS" if z > 0 else "FEAR RELIEF"
    if key == "herding":
        return "CROWDING ACCELERATION" if z > 0 else "DISPERSION"
    if key == "extrapolation":
        return "EXTRAPOLATION SURGE" if z > 0 else "NORMALIZATION"
    if key == "reflexivity":
        return "FEEDBACK ACCELERATION" if z > 0 else "FEEDBACK DECAY"
    return "POSITIVE SHOCK" if z > 0 else "NEGATIVE SHOCK"


def _directional_components(
    key: str,
    percentile: Any,
    shock_z: Any,
    velocity: Any,
    acceleration: Any,
) -> tuple[float | None, float, float, float]:
    spec = LATENT_SPECS.get(str(key), LatentSpec(str(key), str(key).title(), 0.04, 20.0))
    p = _safe_float(percentile)
    z = _safe_float(shock_z, 0.0) or 0.0
    v = _safe_float(velocity, 0.0) or 0.0
    a = _safe_float(acceleration, 0.0) or 0.0

    if spec.shock_mode == "absolute":
        p_eff = max(p, 100.0 - p) if p is not None else None
        return p_eff, abs(z), abs(v), abs(a)
    # Positive-risk mechanisms: negative innovations are relief/normalization, not stress alarms.
    return p, max(z, 0.0), max(v, 0.0), max(a, 0.0)


def acute_alarm_level(
    key: str,
    score: Any,
    percentile: Any = None,
    shock_z: Any = None,
    velocity: Any = None,
    acceleration: Any = None,
) -> tuple[str, int]:
    """
    Acute event severity. Unlike the structural state label, this asks whether the
    mechanism is *newly unusual or accelerating*.

    Directionality is mechanism-specific: a negative Fear shock is relief, not a
    stress alert; Attention treats unusually large positive or negative shocks as events.
    """
    s = _clip_score(score)
    p_eff, z_eff, v_eff, a_eff = _directional_components(key, percentile, shock_z, velocity, acceleration)

    if z_eff >= 3.0 or (p_eff is not None and p_eff >= 99 and v_eff >= 0.8) or (s >= 85 and p_eff is not None and p_eff >= 97 and v_eff >= 0.5):
        return "CRITICAL", 3
    if z_eff >= 2.3 or (p_eff is not None and p_eff >= 95 and v_eff >= 0.55) or (s >= 78 and p_eff is not None and p_eff >= 90 and v_eff >= 0.35):
        return "HIGH", 2
    if z_eff >= 1.6 or (p_eff is not None and p_eff >= 85 and v_eff >= 0.25) or (s >= 70 and p_eff is not None and p_eff >= 75 and v_eff >= 0.20) or (p_eff is not None and p_eff >= 90 and a_eff >= 0.08):
        return "WATCH", 1
    return "NORMAL", 0


def adaptive_alarm_level(score: Any, percentile: Any = None, shock_z: Any = None) -> tuple[str, int]:
    """Backward-compatible V2.0 generic alarm helper. New code should use acute_alarm_level()."""
    s = _clip_score(score)
    p = _safe_float(percentile)
    z = abs(_safe_float(shock_z, 0.0) or 0.0)
    if (s >= 82 and (p is None or p >= 95)) or (s >= 76 and z >= 3.2):
        return "CRITICAL", 3
    if (s >= 70 and (p is None or p >= 82)) or (p is not None and p >= 93) or (s >= 66 and z >= 2.4):
        return "HIGH", 2
    if s >= 58 or (p is not None and p >= 75) or z >= 1.8:
        return "WATCH", 1
    return "NORMAL", 0


def _acute_severity_series(
    key: str,
    score: pd.Series,
    percentile: pd.Series,
    shock_z: pd.Series,
    velocity: pd.Series,
    acceleration: pd.Series,
) -> pd.Series:
    out = []
    for s, p, z, v, a in zip(score, percentile, shock_z, velocity, acceleration):
        _, sev = acute_alarm_level(key, s, p, z, v, a)
        out.append(sev)
    return pd.Series(out, index=score.index, dtype=int)


def _structural_rank_series(score: pd.Series) -> pd.Series:
    return pd.Series([structural_state_label(x)[1] if pd.notna(x) else np.nan for x in score], index=score.index, dtype=float)


def _structural_label_series(score: pd.Series) -> pd.Series:
    return pd.Series([structural_state_label(x)[0] if pd.notna(x) else None for x in score], index=score.index, dtype=object)


def _consecutive_duration(severity: pd.Series, current_severity: int) -> int:
    if severity is None or severity.empty or current_severity <= 0:
        return 0
    count = 0
    for value in severity.iloc[::-1]:
        if pd.isna(value) or int(value) < current_severity:
            break
        count += 1
    return int(count)


def _consecutive_same_label(labels: pd.Series, current_label: str) -> int:
    if labels is None or labels.empty or not current_label:
        return 0
    count = 0
    for value in labels.iloc[::-1]:
        if value is None or str(value) != str(current_label):
            break
        count += 1
    return int(count)


def _onset_date(dates: pd.Series, severity: pd.Series, current_severity: int):
    duration = _consecutive_duration(severity, current_severity)
    if duration <= 0 or dates is None or len(dates) < duration:
        return pd.NaT
    return pd.to_datetime(dates.iloc[-duration], errors="coerce", utc=True)


def _label_onset_date(dates: pd.Series, labels: pd.Series, current_label: str):
    duration = _consecutive_same_label(labels, current_label)
    if duration <= 0 or dates is None or len(dates) < duration:
        return pd.NaT
    return pd.to_datetime(dates.iloc[-duration], errors="coerce", utc=True)


def build_latent_state_bundle(
    history: pd.DataFrame,
    current_raw_scores: dict[str, float],
    confidence_map: dict[str, float] | None = None,
) -> dict[str, Any]:
    """
    Build point-in-time latent states for the five mechanisms with historical proxy series.

    V2.0.1 calibration order:
        RAW PROXY -> causal robust normalization -> one-sided filter -> structural state
        -> direction-aware acute alarm.

    The output keeps raw, normalized and latent values separately so no UI or research
    layer has to infer psychology directly from an uncalibrated proxy.
    """
    confidence_map = dict(confidence_map or {})
    if history is None or history.empty:
        return {
            "history": pd.DataFrame(),
            "current_table": pd.DataFrame(),
            "operational_scores": dict(current_raw_scores),
            "coverage": 0,
            "stability": np.nan,
        }

    h = history.copy().sort_values("date").reset_index(drop=True)
    h["date"] = pd.to_datetime(h["date"], errors="coerce", utc=True)
    operational = dict(current_raw_scores)
    rows: list[dict[str, Any]] = []
    stability_values: list[float] = []

    for key in LATENT_KEYS:
        if key not in h.columns:
            continue
        spec = LATENT_SPECS[key]
        raw_hist = pd.to_numeric(h[key], errors="coerce").clip(0, 100)

        normalized_pack = causal_robust_normalize(
            raw_hist,
            window=spec.normalization_window,
            min_periods=spec.normalization_min_periods,
        )
        normalized_hist = pd.to_numeric(normalized_pack["normalized"], errors="coerce").clip(0, 100)

        filtered = causal_local_level_filter(
            normalized_hist,
            process_ratio=spec.process_ratio,
            min_measurement_var=spec.min_measurement_var,
            variance_window=60,
        )
        hist_latent = pd.to_numeric(filtered["latent"], errors="coerce").clip(0, 100)
        hist_pct = causal_percentile(hist_latent, window=spec.percentile_window, min_periods=60)
        hist_velocity = hist_latent.diff(5) / 5.0
        hist_accel = hist_velocity.diff(5) / 5.0
        # Persistence is estimated on the causally normalized observation, not on the filtered state.
        hist_persist = _rolling_ar1(normalized_hist, window=spec.history_window, min_periods=40)

        current_raw = _clip_score(current_raw_scores.get(key, raw_hist.dropna().iloc[-1] if not raw_hist.dropna().empty else 50.0))
        current_normalized, current_norm_z, norm_center, norm_scale = normalize_current_observation(
            current_raw,
            raw_hist,
            window=spec.normalization_window,
            min_periods=spec.normalization_min_periods,
        )

        valid_latent = hist_latent.dropna()
        prior_latent = _safe_float(valid_latent.iloc[-1], current_normalized) if not valid_latent.empty else current_normalized
        prior_latent = prior_latent or current_normalized
        prior_sd = _safe_float(filtered["state_sd"].dropna().iloc[-1], 6.0) if not filtered["state_sd"].dropna().empty else 6.0
        prior_sd = prior_sd or 6.0
        recent_meas_sd = _safe_float(filtered["measurement_sd"].dropna().iloc[-1], 8.0) if not filtered["measurement_sd"].dropna().empty else 8.0
        recent_meas_sd = recent_meas_sd or 8.0
        measurement_quality = np.clip((_safe_float(confidence_map.get(key), 50.0) or 50.0) / 100.0, 0.05, 0.95)

        # Current update is conservative: low-identification mechanisms move less.
        r_now = max(recent_meas_sd ** 2 * (1.55 - 0.75 * measurement_quality), spec.min_measurement_var)
        p_pred = prior_sd ** 2 + max(r_now * spec.process_ratio, 0.35)
        k_now = float(np.clip(p_pred / (p_pred + r_now), 0.08, 0.48))
        current_innovation = current_normalized - prior_latent
        current_latent = _clip_score(prior_latent + k_now * current_innovation)
        current_state_sd = float(np.sqrt(max((1.0 - k_now) * p_pred, 1e-6)))
        current_shock_z = current_innovation / float(np.sqrt(max(p_pred + r_now, 1e-6)))

        hist_reference = hist_latent.dropna().tail(spec.percentile_window)
        current_percentile = np.nan
        if len(hist_reference) >= 60:
            less = float((hist_reference < current_latent).sum())
            equal = float((hist_reference == current_latent).sum())
            current_percentile = 100.0 * (less + 0.5 * equal) / len(hist_reference)

        lat_ext = pd.concat([hist_latent.dropna().reset_index(drop=True), pd.Series([current_latent])], ignore_index=True)
        current_velocity = _safe_float((lat_ext.iloc[-1] - lat_ext.iloc[-6]) / 5.0) if len(lat_ext) >= 6 else None
        previous_velocity = _safe_float((lat_ext.iloc[-6] - lat_ext.iloc[-11]) / 5.0) if len(lat_ext) >= 11 else None
        current_accel = ((current_velocity - previous_velocity) / 5.0 if current_velocity is not None and previous_velocity is not None else None)

        persistence = _safe_float(hist_persist.dropna().iloc[-1], 0.0) if not hist_persist.dropna().empty else 0.0
        persistence = float(np.clip(persistence or 0.0, 0.0, 0.999))
        stability_values.append(persistence)

        structural_label, structural_rank = structural_state_label(current_latent)
        acute_label, acute_rank = acute_alarm_level(
            key, current_latent, current_percentile, current_shock_z, current_velocity, current_accel
        )
        shock_direction = shock_semantics(key, current_shock_z)

        h[f"{key}_raw"] = raw_hist
        h[f"{key}_normalized"] = normalized_hist
        h[f"{key}_normalization_z"] = normalized_pack["normalization_z"]
        h[f"{key}_normalization_center"] = normalized_pack["normalization_center"]
        h[f"{key}_normalization_scale"] = normalized_pack["normalization_scale"]
        h[f"{key}_latent"] = hist_latent
        h[f"{key}_shock"] = filtered["innovation"]
        h[f"{key}_shock_z"] = filtered["innovation_z"]
        h[f"{key}_percentile"] = hist_pct
        h[f"{key}_velocity_5d"] = hist_velocity
        h[f"{key}_acceleration_5d"] = hist_accel
        h[f"{key}_persistence"] = hist_persist
        h[f"{key}_state_sd"] = filtered["state_sd"]
        h[f"{key}_gain"] = filtered["gain"]

        structural_labels_hist = _structural_label_series(hist_latent)
        structural_ranks_hist = _structural_rank_series(hist_latent)
        acute_hist = _acute_severity_series(key, hist_latent, hist_pct, filtered["innovation_z"], hist_velocity, hist_accel)
        h[f"{key}_structural_state"] = structural_labels_hist
        h[f"{key}_structural_rank"] = structural_ranks_hist
        h[f"{key}_severity"] = acute_hist  # backwards compatibility: severity now means acute event severity

        structural_duration = _consecutive_same_label(structural_labels_hist, structural_label)
        structural_onset = _label_onset_date(h["date"], structural_labels_hist, structural_label)
        if structural_duration == 0:
            structural_duration = 1
            structural_onset = pd.to_datetime(h["date"].iloc[-1], errors="coerce", utc=True)
        acute_duration = _consecutive_duration(acute_hist, acute_rank)
        acute_onset = _onset_date(h["date"], acute_hist, acute_rank)
        if acute_rank > 0 and acute_duration == 0:
            acute_duration = 1
            acute_onset = pd.to_datetime(h["date"].iloc[-1], errors="coerce", utc=True)

        # Preserve backwards compatibility: canonical historical columns are calibrated latent states.
        h[key] = hist_latent
        operational[key] = current_latent

        rows.append({
            "Key": key,
            "Mechanism": spec.label,
            "Raw observation": round(current_raw, 1),
            "Normalized observation": round(current_normalized, 1),
            "Normalization z": round(float(current_norm_z), 2) if current_norm_z is not None else np.nan,
            "Normalization center": round(float(norm_center), 2) if norm_center is not None else np.nan,
            "Normalization scale": round(float(norm_scale), 2) if norm_scale is not None else np.nan,
            "Latent state": round(current_latent, 1),
            "Shock": round(current_innovation, 1),
            "Shock z": round(float(current_shock_z), 2),
            "Shock direction": shock_direction,
            "5D velocity": round(float(current_velocity), 2) if current_velocity is not None else np.nan,
            "Acceleration": round(float(current_accel), 3) if current_accel is not None else np.nan,
            "Percentile": round(float(current_percentile), 1) if np.isfinite(current_percentile) else np.nan,
            "Persistence": round(100.0 * persistence, 1),
            "State uncertainty": round(current_state_sd, 2),
            "Kalman gain": round(100.0 * k_now, 1),
            "Filter memory": round(100.0 * (1.0 - k_now), 1),
            "Structural state": structural_label,
            "Structural rank": structural_rank,
            "Structural duration": structural_duration,
            "Structural onset": structural_onset,
            "Acute alarm": acute_label,
            "Acute rank": acute_rank,
            "Acute duration": acute_duration,
            "Acute onset": acute_onset,
            # Compatibility aliases used by older UI code.
            "Severity": acute_label,
            "Severity rank": acute_rank,
            "Duration": acute_duration,
            "Onset": acute_onset,
        })

    current_table = pd.DataFrame(rows)
    coverage = int(len(current_table))
    stability = float(np.mean(stability_values)) if stability_values else np.nan

    return {
        "history": h,
        "current_table": current_table,
        "operational_scores": operational,
        "coverage": coverage,
        "stability": stability,
    }
