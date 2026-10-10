from __future__ import annotations

from typing import Any
import numpy as np
import pandas as pd


def apply_alignment_lags(changes: pd.DataFrame, lag_map: dict[str, int] | None = None) -> pd.DataFrame:
    """Apply explicit session-alignment lags after return transformation.

    Positive lag shifts the series forward by that many rows so that information intervals line up with
    the reference market. No price forward-fill is introduced.
    """
    if changes is None or changes.empty or not lag_map:
        return changes.copy() if isinstance(changes, pd.DataFrame) else pd.DataFrame()
    out = changes.copy()
    for k, v in lag_map.items():
        key = str(k).upper().strip()
        if key in out.columns:
            try:
                lag = int(v)
            except Exception:
                continue
            if lag:
                out[key] = out[key].shift(lag)
    return out


def synchronization_audit(levels: pd.DataFrame, changes: pd.DataFrame, metadata: dict[str, Any] | None = None,
                          lag_map: dict[str, int] | None = None) -> pd.DataFrame:
    metadata = metadata or {}; lag_map = lag_map or {}
    rows = []
    for c in levels.columns if isinstance(levels, pd.DataFrame) else []:
        m = metadata.get(c, {}) if isinstance(metadata.get(c, {}), dict) else {}
        s = changes[c] if c in changes else pd.Series(dtype=float)
        rows.append({
            "Ticker": c,
            "Timezone": m.get("timezone", "Unknown"),
            "Session close": m.get("session_close", "Unknown"),
            "Calendar": m.get("calendar", "Unknown"),
            "Base currency": m.get("currency", "Unknown"),
            "Return space": m.get("space", "Return"),
            "Alignment lag": int(lag_map.get(c, 0) or 0),
            "Return obs": int(s.notna().sum()),
            "First return": s.dropna().index.min() if s.notna().any() else None,
            "Last return": s.dropna().index.max() if s.notna().any() else None,
        })
    return pd.DataFrame(rows)


def hayashi_yoshida_covariance(a: pd.Series, b: pd.Series) -> float | None:
    """Hayashi-Yoshida covariance for asynchronous *interval returns*.

    Series indices are interval end timestamps; the previous timestamp defines each interval start.
    This function is provided for intraday adapters and is not applied to daily closes automatically.
    """
    a = pd.to_numeric(a, errors="coerce").dropna().sort_index()
    b = pd.to_numeric(b, errors="coerce").dropna().sort_index()
    if len(a) < 2 or len(b) < 2:
        return None
    # For each A interval, locate the contiguous block of B intervals that
    # overlaps it. Prefix sums replace the Python two-pointer accumulation and
    # make the max-stat bootstrap practical on intraday panels without changing
    # the Hayashi-Yoshida estimator or its number of resamples.
    ai = pd.DatetimeIndex(a.index).asi8
    bi = pd.DatetimeIndex(b.index).asi8
    av = a.to_numpy(dtype=float)
    bv = b.to_numpy(dtype=float)
    a_starts, a_ends, a_values = ai[:-1], ai[1:], av[1:]
    b_starts, b_ends, b_values = bi[:-1], bi[1:], bv[1:]
    valid_a = a_ends > a_starts
    valid_b = b_ends > b_starts
    a_starts, a_ends, a_values = a_starts[valid_a], a_ends[valid_a], a_values[valid_a]
    b_starts, b_ends, b_values = b_starts[valid_b], b_ends[valid_b], b_values[valid_b]
    if not len(a_values) or not len(b_values):
        return None
    left = np.searchsorted(b_ends, a_starts, side="right")
    right = np.searchsorted(b_starts, a_ends, side="left")
    prefix = np.concatenate(([0.0], np.cumsum(b_values, dtype=float)))
    overlap_sums = prefix[right] - prefix[left]
    total = float(np.dot(a_values, overlap_sums))
    return total if np.isfinite(total) else None


def hayashi_yoshida_correlation(a: pd.Series, b: pd.Series) -> float | None:
    """Hayashi-Yoshida correlation with pair-specific asynchronous timestamps."""

    covariance = hayashi_yoshida_covariance(a, b)
    variance_a = hayashi_yoshida_covariance(a, a)
    variance_b = hayashi_yoshida_covariance(b, b)
    if covariance is None or variance_a is None or variance_b is None:
        return None
    denominator = float(np.sqrt(max(variance_a, 0.0) * max(variance_b, 0.0)))
    if not np.isfinite(denominator) or denominator <= 1e-18:
        return None
    return float(np.clip(covariance / denominator, -1.0, 1.0))


def hayashi_yoshida_matrix(
    asynchronous_returns: pd.DataFrame,
    *,
    min_obs: int = 30,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Build an asynchronous HY correlation matrix and pair audit table.

    The input index must contain real event or interval-end timestamps. Missing
    cells are expected and preserve each market's own sampling clock.
    """

    if asynchronous_returns is None or asynchronous_returns.empty:
        return pd.DataFrame(), pd.DataFrame(), {"status": "unavailable", "reason": "empty_input"}
    frame = asynchronous_returns.copy()
    frame.index = pd.to_datetime(frame.index, errors="coerce", utc=True)
    frame = frame[~frame.index.isna()].sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    frame = frame.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    eligible = [str(c) for c in frame.columns if int(frame[c].notna().sum()) >= int(min_obs)]
    if len(eligible) < 2:
        return pd.DataFrame(), pd.DataFrame(), {
            "status": "insufficient_data",
            "eligible_assets": eligible,
            "min_obs": int(min_obs),
        }
    matrix = pd.DataFrame(np.eye(len(eligible)), index=eligible, columns=eligible, dtype=float)
    rows: list[dict[str, Any]] = []
    for left in range(len(eligible)):
        for right in range(left + 1, len(eligible)):
            a_name, b_name = eligible[left], eligible[right]
            a = frame[a_name].dropna()
            b = frame[b_name].dropna()
            value = hayashi_yoshida_correlation(a, b)
            if value is not None:
                matrix.loc[a_name, b_name] = matrix.loc[b_name, a_name] = value
            else:
                matrix.loc[a_name, b_name] = matrix.loc[b_name, a_name] = np.nan
            synchronous = pd.concat([a.rename("a"), b.rename("b")], axis=1, join="inner").dropna()
            rows.append({
                "Asset A": a_name,
                "Asset B": b_name,
                "HY correlation": value,
                "A observations": int(len(a)),
                "B observations": int(len(b)),
                "Synchronous timestamps": int(len(synchronous)),
                "Asynchronous gain": int(max(0, min(len(a), len(b)) - len(synchronous))),
            })
    finite = matrix.to_numpy(dtype=float)
    offdiag = finite[np.triu_indices_from(finite, 1)]
    return matrix, pd.DataFrame(rows), {
        "status": "ok",
        "authority": "RESEARCH_ONLY",
        "estimator": "Hayashi-Yoshida",
        "timestamp_semantics": "interval end; previous observation defines interval start",
        "eligible_assets": eligible,
        "pairs": int(len(rows)),
        "finite_pairs": int(np.isfinite(offdiag).sum()),
        "min_obs": int(min_obs),
        "daily_data_allowed": False,
    }


def hayashi_yoshida_lead_lag(
    a: pd.Series,
    b: pd.Series,
    *,
    lag_seconds: tuple[int, ...] = (-900, -600, -300, -120, -60, 0, 60, 120, 300, 600, 900),
    bootstrap_samples: int = 199,
    seed: int = 42,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """HY lead/lag scan with a circular-shift max-statistic null.

    Positive lag shifts series B later in clock time. The bootstrap preserves B's
    timestamp grid and marginal sequence while breaking its calendar alignment.
    """

    left = pd.to_numeric(a, errors="coerce").dropna().sort_index()
    right = pd.to_numeric(b, errors="coerce").dropna().sort_index()
    if len(left) < 30 or len(right) < 30:
        return pd.DataFrame(), {"status": "insufficient_data", "authority": "RESEARCH_ONLY"}

    left_times = pd.DatetimeIndex(left.index).asi8
    right_times = pd.DatetimeIndex(right.index).asi8
    left_valid = left_times[1:] > left_times[:-1]
    right_valid = right_times[1:] > right_times[:-1]
    left_starts = left_times[:-1][left_valid]
    left_ends = left_times[1:][left_valid]
    left_values = left.to_numpy(dtype=float)[1:][left_valid]
    right_starts = right_times[:-1][right_valid]
    right_ends = right_times[1:][right_valid]
    if not len(left_values) or not int(right_valid.sum()):
        return pd.DataFrame(), {"status": "insufficient_data", "authority": "RESEARCH_ONLY"}

    # Timestamp geometry is invariant across the circular-shift null. Cache the
    # overlap ranges for every lag once, then evaluate all bootstrap curves with
    # vectorised prefix sums. This is mathematically identical to recomputing HY
    # interval overlaps for every surrogate but avoids millions of Python-level
    # interval comparisons in an interactive rerun.
    overlap_ranges: list[tuple[np.ndarray, np.ndarray]] = []
    for lag in lag_seconds:
        shift_ns = int(lag) * 1_000_000_000
        shifted_starts = right_starts + shift_ns
        shifted_ends = right_ends + shift_ns
        first = np.searchsorted(shifted_ends, left_starts, side="right")
        last = np.searchsorted(shifted_starts, left_ends, side="left")
        overlap_ranges.append((first, last))
    left_variance = float(np.dot(left_values, left_values))

    def curve(interval_values: np.ndarray) -> list[float]:
        values = np.asarray(interval_values, dtype=float)
        right_variance = float(np.dot(values, values))
        denominator = float(np.sqrt(max(left_variance, 0.0) * max(right_variance, 0.0)))
        if not np.isfinite(denominator) or denominator <= 1e-18:
            return [np.nan] * len(lag_seconds)
        prefix = np.concatenate(([0.0], np.cumsum(values, dtype=float)))
        out: list[float] = []
        for first, last in overlap_ranges:
            covariance = float(np.dot(left_values, prefix[last] - prefix[first]))
            out.append(float(np.clip(covariance / denominator, -1.0, 1.0)))
        return out

    raw_right_values = right.to_numpy(dtype=float)
    observed_interval_values = raw_right_values[1:][right_valid]
    observed = np.asarray(curve(observed_interval_values), dtype=float)
    if not np.isfinite(observed).any():
        return pd.DataFrame(), {"status": "unavailable", "authority": "RESEARCH_ONLY"}
    selected_position = int(np.nanargmax(np.abs(observed)))
    observed_max = float(abs(observed[selected_position]))
    rng = np.random.default_rng(seed)
    null_maxima: list[float] = []
    if len(raw_right_values) >= 6:
        for _ in range(max(0, int(bootstrap_samples))):
            shift = int(rng.integers(2, len(raw_right_values) - 2))
            surrogate_values = np.roll(raw_right_values, shift)[1:][right_valid]
            null_curve = np.asarray(curve(surrogate_values), dtype=float)
            if np.isfinite(null_curve).any():
                null_maxima.append(float(np.nanmax(np.abs(null_curve))))
    pvalue = (
        float((1 + np.sum(np.asarray(null_maxima) >= observed_max)) / (len(null_maxima) + 1))
        if null_maxima
        else None
    )
    table = pd.DataFrame({"Lag seconds": list(lag_seconds), "HY correlation": observed})
    table["Selected"] = False
    table.loc[selected_position, "Selected"] = True
    return table, {
        "status": "ok",
        "authority": "RESEARCH_ONLY",
        "selected_lag_seconds": int(lag_seconds[selected_position]),
        "selected_correlation": float(observed[selected_position]),
        "max_abs_correlation": observed_max,
        "max_stat_bootstrap_pvalue": pvalue,
        "bootstrap_samples": int(len(null_maxima)),
        "bootstrap_null": "circular shift of B values across the original timestamp grid",
        "interpretation": "positive lag shifts B later; descriptive clock-time lead/lag, not causality",
    }


def epps_effect_curve(
    a: pd.Series,
    b: pd.Series,
    *,
    frequencies: tuple[str, ...] = ("1min", "5min", "15min", "30min", "60min"),
    min_bins: int = 12,
) -> pd.DataFrame:
    """Estimate correlation across aggregation grids to expose the Epps effect."""

    left = pd.to_numeric(a, errors="coerce").dropna().sort_index()
    right = pd.to_numeric(b, errors="coerce").dropna().sort_index()
    rows: list[dict[str, Any]] = []
    for frequency in frequencies:
        try:
            left_bins = left.resample(frequency).sum(min_count=1)
            right_bins = right.resample(frequency).sum(min_count=1)
            aligned = pd.concat([left_bins.rename("a"), right_bins.rename("b")], axis=1).dropna()
            correlation = float(aligned.corr().iloc[0, 1]) if len(aligned) >= int(min_bins) else np.nan
            rows.append({"Aggregation": frequency, "Correlation": correlation, "Common bins": int(len(aligned))})
        except Exception:
            rows.append({"Aggregation": frequency, "Correlation": np.nan, "Common bins": 0})
    return pd.DataFrame(rows)
