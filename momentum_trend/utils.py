from __future__ import annotations

import math

import numpy as np
import pandas as pd


EPS = 1e-12


def clip(value: float | int | None, low: float = 0.0, high: float = 1.0) -> float:
    if value is None or not np.isfinite(value):
        return low
    return float(np.clip(value, low, high))


def safe_float(value, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def sigmoid(value: float) -> float:
    bounded = float(np.clip(value, -35.0, 35.0))
    return 1.0 / (1.0 + math.exp(-bounded))


def softmax(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    values = values - np.nanmax(values)
    exponent = np.exp(np.clip(values, -50, 50))
    total = exponent.sum()
    if not np.isfinite(total) or total <= 0:
        return np.full(len(values), 1.0 / len(values))
    return exponent / total


def causal_zscore(series: pd.Series, window: int, min_periods: int | None = None) -> pd.Series:
    minimum = min_periods or max(10, window // 3)
    mean = series.rolling(window, min_periods=minimum).mean()
    std = series.rolling(window, min_periods=minimum).std(ddof=0).replace(0, np.nan)
    return ((series - mean) / std).clip(-6, 6)


def annualized_return_from_log(log_return: float, horizon: int, annualisation: int = 252) -> float:
    if not np.isfinite(log_return) or horizon <= 0:
        return 0.0
    return float(np.expm1(log_return * annualisation / horizon))


def max_drawdown(returns: pd.Series) -> float:
    curve = (1.0 + returns.fillna(0.0)).cumprod()
    drawdown = curve / curve.cummax() - 1.0
    return float(drawdown.min()) if not drawdown.empty else 0.0

