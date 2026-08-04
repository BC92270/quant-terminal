from __future__ import annotations

import math
from typing import Any, Dict, Mapping, Tuple

import numpy as np
import pandas as pd

from .config import EPS
from .utils import (
    _clamp, _moment_excess_kurtosis, _moment_skew, _normal_ppf, _safe_float,
)

def _normalize_price_data(price_data: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    quality: Dict[str, Any] = {
        "input_rows": 0,
        "duplicate_dates": 0,
        "nonpositive_close": 0,
        "missing_close": 0,
        "extreme_return_count": 0,
        "warnings": [],
    }

    if not isinstance(price_data, pd.DataFrame) or price_data.empty:
        quality["warnings"].append("Aucune donnée de prix fournie.")
        return pd.DataFrame(), quality

    df = price_data.copy()
    quality["input_rows"] = int(len(df))

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(col[0]) for col in df.columns]

    lower_columns = [str(c).strip().lower() for c in df.columns]
    if "date" not in lower_columns and "datetime" not in lower_columns:
        df = df.reset_index()

    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]

    rename_map: Dict[str, str] = {}
    if "datetime" in df.columns and "date" not in df.columns:
        rename_map["datetime"] = "date"
    if "index" in df.columns and "date" not in df.columns:
        rename_map["index"] = "date"
    if "adj_close" in df.columns and "close" not in df.columns:
        rename_map["adj_close"] = "close"
    if "adjusted_close" in df.columns and "close" not in df.columns:
        rename_map["adjusted_close"] = "close"
    if rename_map:
        df = df.rename(columns=rename_map)

    if "close" not in df.columns:
        quality["warnings"].append("Colonne close introuvable.")
        return pd.DataFrame(), quality

    for col in ("open", "high", "low", "close", "volume"):
        if col not in df.columns:
            df[col] = np.nan if col == "volume" else df["close"]
        df[col] = pd.to_numeric(df[col], errors="coerce")

    quality["missing_close"] = int(df["close"].isna().sum())
    quality["nonpositive_close"] = int((df["close"] <= 0).sum())

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce", utc=False)
        df = df.dropna(subset=["date"])
        quality["duplicate_dates"] = int(df["date"].duplicated(keep="last").sum())
        df = df.drop_duplicates(subset=["date"], keep="last").sort_values("date")
    else:
        df["date"] = pd.RangeIndex(start=0, stop=len(df), step=1)
        quality["warnings"].append("Aucune date exploitable : fréquence annuelle par défaut.")

    df = df.replace([np.inf, -np.inf], np.nan)
    df = df.dropna(subset=["close"])
    df = df[df["close"] > 0].copy()

    # Keep true market jumps. Flag them instead of deleting them silently.
    if len(df) >= 2:
        simple_returns = df["close"].pct_change()
        quality["extreme_return_count"] = int((simple_returns.abs() > 0.50).sum())
        if quality["extreme_return_count"] > 0:
            quality["warnings"].append(
                f"{quality['extreme_return_count']} rendement(s) absolu(s) > 50 % détecté(s) ; vérifier splits/corporate actions."
            )

    if quality["duplicate_dates"] > 0:
        quality["warnings"].append(f"{quality['duplicate_dates']} date(s) dupliquée(s) supprimée(s).")
    if quality["missing_close"] > 0:
        quality["warnings"].append(f"{quality['missing_close']} close manquant(s) supprimé(s).")
    if quality["nonpositive_close"] > 0:
        quality["warnings"].append(f"{quality['nonpositive_close']} prix non positif(s) supprimé(s).")

    return df.reset_index(drop=True), quality


def _infer_periods_per_year(dates: pd.Series) -> Tuple[int, str, float | None]:
    if dates is None or len(dates) < 3 or not pd.api.types.is_datetime64_any_dtype(dates):
        return 252, "Daily default", None

    deltas = dates.sort_values().diff().dropna().dt.total_seconds() / 86_400.0
    deltas = deltas[(deltas > 0) & np.isfinite(deltas)]
    if deltas.empty:
        return 252, "Daily default", None

    median_days = float(deltas.median())
    if median_days <= 2.0:
        return 252, "Daily", median_days
    if median_days <= 10.0:
        return 52, "Weekly", median_days
    if median_days <= 45.0:
        return 12, "Monthly", median_days
    if median_days <= 100.0:
        return 4, "Quarterly", median_days
    return 1, "Annual", median_days


def _extract_nested_price(payload: Any, max_depth: int = 4) -> Tuple[float | None, str | None]:
    if max_depth < 0 or payload is None:
        return None, None

    priority_keys = (
        "live_price",
        "current_price",
        "latest_price",
        "last_price",
        "price",
        "regularMarketPrice",
        "c",
        "close",
    )
    priority_children = (
        "momentum_v2",
        "latest",
        "quote",
        "finnhub_quote",
        "live_quote",
        "market",
        "meta",
        "data",
    )

    if isinstance(payload, Mapping):
        for key in priority_keys:
            if key in payload:
                value = _safe_float(payload.get(key))
                if value is not None and value > 0:
                    return value, key

        for key in priority_children:
            if key in payload:
                value, source = _extract_nested_price(payload.get(key), max_depth=max_depth - 1)
                if value is not None and value > 0:
                    return value, f"{key}.{source}" if source else key

        for key, child in payload.items():
            if isinstance(child, Mapping):
                value, source = _extract_nested_price(child, max_depth=max_depth - 1)
                if value is not None and value > 0:
                    return value, f"{key}.{source}" if source else str(key)

    return None, None


def _analysis_live_price(analysis: Mapping[str, Any], fallback: float) -> Tuple[float, str]:
    if not isinstance(analysis, Mapping):
        return fallback, "historique/close"

    priority_paths = (
        ("momentum_v2", "latest", "price"),
        ("momentum_v2", "quote", "price"),
        ("momentum_v2", "quote", "c"),
        ("quote", "price"),
        ("quote", "c"),
        ("finnhub_quote", "c"),
        ("live_price",),
        ("current_price",),
        ("last_price",),
        ("price",),
        ("latest_price",),
    )

    for path in priority_paths:
        current: Any = analysis
        for key in path:
            if not isinstance(current, Mapping):
                current = None
                break
            current = current.get(key)
        value = _safe_float(current)
        if value is not None and value > 0:
            return value, "analysis/" + ".".join(path)

    value, source = _extract_nested_price(analysis, max_depth=4)
    if value is not None and value > 0:
        return value, f"analysis/{source or 'live quote'}"
    return fallback, "historique/close"


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(period, min_periods=max(3, period // 2)).mean()


def _ewma_variance(log_returns: np.ndarray, decay: float = 0.94) -> np.ndarray:
    values = np.asarray(log_returns, dtype=float)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return np.array([], dtype=float)

    decay = _clamp(decay, 0.50, 0.999)
    centered = values - values.mean()
    initial_window = centered[: min(30, centered.size)]
    initial_var = float(np.var(initial_window, ddof=1)) if initial_window.size > 1 else float(centered[0] ** 2)
    initial_var = max(initial_var, 1e-10)

    variances = np.empty(values.size, dtype=float)
    variances[0] = initial_var
    for idx in range(1, values.size):
        variances[idx] = decay * variances[idx - 1] + (1.0 - decay) * centered[idx - 1] ** 2
    return np.maximum(variances, 1e-12)


def _estimate_student_df(excess_kurtosis: float) -> float:
    # Student-t excess kurtosis = 6 / (nu - 4), nu > 4.
    if not np.isfinite(excess_kurtosis) or excess_kurtosis <= 0.10:
        return 30.0
    nu = 6.0 / excess_kurtosis + 4.0
    return _clamp(nu, 4.25, 30.0)


def _prepare_base(
    price_data: pd.DataFrame,
    analysis: Mapping[str, Any] | None = None,
    ewma_lambda: float = 0.94,
) -> Dict[str, Any]:
    df, quality = _normalize_price_data(price_data)
    if df.empty or len(df) < 40:
        return {
            "ok": False,
            "df": df,
            "quality": quality,
            "reason": "Historique prix insuffisant : au moins 40 observations sont requises.",
        }

    close = df["close"].astype(float)
    simple_returns = close.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    log_returns = np.log(close / close.shift(1)).replace([np.inf, -np.inf], np.nan).dropna()

    aligned = pd.concat(
        [simple_returns.rename("simple"), log_returns.rename("log")],
        axis=1,
    ).dropna()
    simple_returns = aligned["simple"]
    log_returns = aligned["log"]

    if len(log_returns) < 30:
        return {
            "ok": False,
            "df": df,
            "quality": quality,
            "reason": "Rendements exploitables insuffisants après normalisation.",
        }

    periods_per_year, frequency_label, median_spacing_days = _infer_periods_per_year(df["date"])
    close_last = float(close.iloc[-1])
    live_price, price_source = _analysis_live_price(analysis or {}, close_last)

    atr_series = _atr(df)
    atr_14 = _safe_float(atr_series.iloc[-1], close_last * 0.03)
    if atr_14 is None or atr_14 <= 0:
        atr_14 = close_last * 0.03

    log_values = log_returns.to_numpy(dtype=float)
    mean_log_period = float(np.mean(log_values))
    sigma_period = float(np.std(log_values, ddof=1))
    sigma_period = max(sigma_period, 1e-8)
    vol_ann = sigma_period * math.sqrt(periods_per_year)

    # Under dS/S = mu dt + sigma dW, E[log(S_t/S_0)] = (mu - 0.5 sigma²)t.
    drift_ann = mean_log_period * periods_per_year + 0.5 * vol_ann**2
    expected_return_ann = math.exp(drift_ann) - 1.0

    # Sampling uncertainty of the annualized diffusion drift.
    n_returns = len(log_values)
    mean_log_se = sigma_period / math.sqrt(n_returns)
    drift_se_ann = mean_log_se * periods_per_year
    z95 = _normal_ppf(0.975)
    drift_ci_low = drift_ann - z95 * drift_se_ann
    drift_ci_high = drift_ann + z95 * drift_se_ann

    ewma_vars = _ewma_variance(log_values, decay=ewma_lambda)
    ewma_vol_ann = math.sqrt(float(ewma_vars[-1]) * periods_per_year) if ewma_vars.size else vol_ann

    standardized_residuals = np.array([], dtype=float)
    if ewma_vars.size == log_values.size:
        conditional_sigma = np.sqrt(np.maximum(ewma_vars, 1e-12))
        standardized_residuals = (log_values - mean_log_period) / conditional_sigma
        standardized_residuals = standardized_residuals[np.isfinite(standardized_residuals)]
        if standardized_residuals.size:
            standardized_residuals = standardized_residuals - standardized_residuals.mean()
            residual_std = standardized_residuals.std(ddof=1)
            if residual_std > EPS:
                standardized_residuals = standardized_residuals / residual_std

    excess_kurtosis = _moment_excess_kurtosis(log_values)
    skewness = _moment_skew(log_values)
    student_df = _estimate_student_df(excess_kurtosis)

    historical_peak = close.cummax()
    max_drawdown = float((close / historical_peak - 1.0).min())

    quality["output_rows"] = int(len(df))
    quality["returns_count"] = int(n_returns)
    quality["sample_start"] = df["date"].iloc[0]
    quality["sample_end"] = df["date"].iloc[-1]
    quality["frequency_label"] = frequency_label
    quality["periods_per_year"] = periods_per_year
    quality["median_spacing_days"] = median_spacing_days

    if n_returns < 120:
        quality["warnings"].append("Moins de 120 rendements : drift et queues très incertains.")
    elif n_returns < 252 and periods_per_year == 252:
        quality["warnings"].append("Moins d'une année de rendements quotidiens.")
    if drift_ci_low < 0 < drift_ci_high:
        quality["warnings"].append("L'intervalle du drift inclut zéro : direction moyenne non identifiée.")
    if abs(skewness) > 1.0:
        quality["warnings"].append("Asymétrie historique élevée détectée.")
    if excess_kurtosis > 3.0:
        quality["warnings"].append("Excès de kurtosis élevé : queues épaisses significatives.")

    return {
        "ok": True,
        "df": df,
        "simple_returns": simple_returns,
        "log_returns": log_returns,
        "log_return_values": log_values,
        "standardized_residuals": standardized_residuals,
        "ewma_variances": ewma_vars,
        "current_price": float(live_price),
        "close_last": close_last,
        "price_source": price_source,
        "atr_14": float(atr_14),
        "atr_pct": float(atr_14 / live_price),
        "periods_per_year": int(periods_per_year),
        "frequency_label": frequency_label,
        "median_spacing_days": median_spacing_days,
        "mean_log_period": mean_log_period,
        "sigma_period": sigma_period,
        "drift_ann": float(drift_ann),
        "expected_return_ann": float(expected_return_ann),
        "drift_se_ann": float(drift_se_ann),
        "drift_ci_95": (float(drift_ci_low), float(drift_ci_high)),
        "vol_ann": float(vol_ann),
        "ewma_vol_ann": float(ewma_vol_ann),
        "skewness": float(skewness),
        "excess_kurtosis": float(excess_kurtosis),
        "student_df": float(student_df),
        "max_drawdown": float(max_drawdown),
        "quality": quality,
    }
