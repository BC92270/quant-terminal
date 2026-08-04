from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict
from typing import Any, Mapping, Tuple

import numpy as np
import pandas as pd

try:
    from scipy.stats import chi2 as _scipy_chi2
    from scipy.stats import norm as _scipy_norm
    from scipy.stats import t as _scipy_t
except Exception:  # pragma: no cover
    _scipy_chi2 = None
    _scipy_norm = None
    _scipy_t = None

from .config import DEFAULT_CONFIDENCE, EPS, MODEL_ALIASES, MODEL_SEED_OFFSETS

def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or pd.isna(value):
            return default
        out = float(value)
        return out if np.isfinite(out) else default
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        out = int(value)
        return out
    except Exception:
        return default


def _pct(value: float | None, digits: int = 2, signed: bool = False) -> str:
    value = _safe_float(value)
    if value is None:
        return "N/A"
    sign = "+" if signed and value > 0 else ""
    return f"{sign}{value * 100:.{digits}f}%"


def _pp(value: float | None, digits: int = 2, signed: bool = False) -> str:
    value = _safe_float(value)
    if value is None:
        return "N/A"
    sign = "+" if signed and value > 0 else ""
    return f"{sign}{value:.{digits}f} pp"


def _price(value: float | None, digits: int = 2) -> str:
    value = _safe_float(value)
    if value is None:
        return "N/A"
    return f"{value:,.{digits}f}"


def _number(value: float | None, digits: int = 2) -> str:
    value = _safe_float(value)
    if value is None:
        return "N/A"
    return f"{value:,.{digits}f}"


def _clamp(value: float, low: float, high: float) -> float:
    return float(max(low, min(high, value)))


def _normal_ppf(probability: float) -> float:
    probability = _clamp(probability, 1e-8, 1.0 - 1e-8)
    if _scipy_norm is not None:
        return float(_scipy_norm.ppf(probability))

    # Peter J. Acklam rational approximation.
    a = (
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    )
    b = (
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    )
    c = (
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    )
    d = (
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    )
    plow = 0.02425
    phigh = 1.0 - plow
    if probability < plow:
        q = math.sqrt(-2.0 * math.log(probability))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    if probability > phigh:
        q = math.sqrt(-2.0 * math.log(1.0 - probability))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    q = probability - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (
        (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    )


def _chi2_survival_1df(statistic: float) -> float:
    statistic = max(float(statistic), 0.0)
    if _scipy_chi2 is not None:
        return float(_scipy_chi2.sf(statistic, 1))
    # For 1 degree of freedom: survival = erfc(sqrt(x / 2)).
    return float(math.erfc(math.sqrt(statistic / 2.0)))


def _wilson_interval(successes: int, trials: int, confidence: float = DEFAULT_CONFIDENCE) -> Tuple[float, float]:
    if trials <= 0:
        return float("nan"), float("nan")
    z = _normal_ppf(0.5 + confidence / 2.0)
    p = successes / trials
    denominator = 1.0 + z * z / trials
    center = (p + z * z / (2.0 * trials)) / denominator
    half = z * math.sqrt((p * (1.0 - p) / trials) + (z * z / (4.0 * trials * trials))) / denominator
    return max(0.0, center - half), min(1.0, center + half)


def _moment_skew(values: np.ndarray) -> float:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if values.size < 3:
        return float("nan")
    centered = values - values.mean()
    m2 = np.mean(centered**2)
    if m2 <= EPS:
        return 0.0
    return float(np.mean(centered**3) / (m2 ** 1.5))


def _moment_excess_kurtosis(values: np.ndarray) -> float:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if values.size < 4:
        return float("nan")
    centered = values - values.mean()
    m2 = np.mean(centered**2)
    if m2 <= EPS:
        return 0.0
    return float(np.mean(centered**4) / (m2 * m2) - 3.0)


def _stable_model_seed(seed: int, model: str, extra: int = 0) -> int:
    canonical = MODEL_ALIASES.get(model, model)
    return int(seed + MODEL_SEED_OFFSETS.get(canonical, 90_001) + extra)


def _jsonable(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value
