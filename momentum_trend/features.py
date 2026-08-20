from __future__ import annotations

import numpy as np
import pandas as pd

from .utils import EPS, causal_zscore


def _wilder(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = _wilder(delta.clip(lower=0), period)
    loss = _wilder(-delta.clip(upper=0), period)
    relative = gain / loss.replace(0, np.nan)
    result = 100 - 100 / (1 + relative)
    return result.where(loss.ne(0), 100.0).clip(0, 100)


def _atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    previous = frame["close"].shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous).abs(),
            (frame["low"] - previous).abs(),
        ],
        axis=1,
    ).max(axis=1, skipna=True)
    fallback = frame["close"].diff().abs()
    return _wilder(true_range.fillna(fallback), period)


def _adx(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    high_diff = frame["high"].diff()
    low_diff = -frame["low"].diff()
    plus_dm = pd.Series(np.where((high_diff > low_diff) & (high_diff > 0), high_diff, 0.0), index=frame.index)
    minus_dm = pd.Series(np.where((low_diff > high_diff) & (low_diff > 0), low_diff, 0.0), index=frame.index)
    atr = _atr(frame, period).replace(0, np.nan)
    plus_di = 100 * _wilder(plus_dm, period) / atr
    minus_di = 100 * _wilder(minus_dm, period) / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return _wilder(dx, period).clip(0, 100)


def _efficiency_ratio(close: pd.Series, period: int) -> pd.Series:
    direction = close.diff(period).abs()
    path = close.diff().abs().rolling(period, min_periods=period).sum()
    return (direction / path.replace(0, np.nan)).clip(0, 1)


def _rolling_log_slope(close: pd.Series, period: int) -> tuple[pd.Series, pd.Series]:
    x = np.arange(period, dtype=float)
    x_centered = x - x.mean()
    denominator = float(np.square(x_centered).sum())

    def slope(values: np.ndarray) -> float:
        if np.any(~np.isfinite(values)) or np.any(values <= 0):
            return np.nan
        y = np.log(values)
        return float(np.dot(x_centered, y - y.mean()) / denominator)

    def r_squared(values: np.ndarray) -> float:
        if np.any(~np.isfinite(values)) or np.any(values <= 0):
            return np.nan
        y = np.log(values)
        coefficient = np.dot(x_centered, y - y.mean()) / denominator
        fitted = y.mean() + coefficient * x_centered
        total = np.square(y - y.mean()).sum()
        return float(1 - np.square(y - fitted).sum() / total) if total > EPS else 0.0

    raw_slope = close.rolling(period, min_periods=period).apply(slope, raw=True)
    annualized = np.expm1(raw_slope.clip(-0.03, 0.03) * 252)
    r2 = close.rolling(period, min_periods=period).apply(r_squared, raw=True).clip(0, 1)
    return annualized, r2


def build_feature_frame(frame: pd.DataFrame, annualisation: int = 252) -> pd.DataFrame:
    """Create causal features; every row depends only on that row and its past."""

    data = frame.copy()
    close = data["close"]
    data["simple_return"] = close.pct_change()
    data["log_return"] = np.log(close).diff()

    for period in (10, 20, 50):
        data[f"ema_{period}"] = close.ewm(span=period, adjust=False, min_periods=max(3, period // 3)).mean()
    for period in (50, 200):
        data[f"sma_{period}"] = close.rolling(period, min_periods=max(20, period // 2)).mean()

    data["rsi_14"] = _rsi(close)
    ema12 = close.ewm(span=12, adjust=False, min_periods=8).mean()
    ema26 = close.ewm(span=26, adjust=False, min_periods=16).mean()
    data["macd"] = ema12 - ema26
    data["macd_signal"] = data["macd"].ewm(span=9, adjust=False, min_periods=5).mean()
    data["macd_hist"] = data["macd"] - data["macd_signal"]

    data["atr_14"] = _atr(data)
    data["atr_pct"] = data["atr_14"] / close.replace(0, np.nan)
    data["adx_14"] = _adx(data)
    data["vol_20"] = data["log_return"].rolling(20, min_periods=12).std(ddof=0) * np.sqrt(annualisation)
    data["vol_60"] = data["log_return"].rolling(60, min_periods=30).std(ddof=0) * np.sqrt(annualisation)
    negative = data["log_return"].where(data["log_return"] < 0, 0)
    data["downside_vol_20"] = negative.rolling(20, min_periods=12).std(ddof=0) * np.sqrt(annualisation)
    data["vol_z_60"] = causal_zscore(data["vol_20"], 60, 20)

    for period in (20, 60, 120):
        data[f"momentum_{period}"] = close.pct_change(period)
        data[f"efficiency_{period}"] = _efficiency_ratio(close, period)
        slope, r2 = _rolling_log_slope(close, period)
        data[f"slope_{period}"] = slope
        data[f"r2_{period}"] = r2

    data["distance_ema20_atr"] = (close - data["ema_20"]) / data["atr_14"].replace(0, np.nan)
    data["distance_sma50_atr"] = (close - data["sma_50"]) / data["atr_14"].replace(0, np.nan)
    data["macd_hist_atr"] = data["macd_hist"] / data["atr_14"].replace(0, np.nan)

    data["high_20_prior"] = close.rolling(20, min_periods=15).max().shift(1)
    data["low_20_prior"] = close.rolling(20, min_periods=15).min().shift(1)
    data["breakout_20_atr"] = (close - data["high_20_prior"]) / data["atr_14"].replace(0, np.nan)
    data["breakdown_20_atr"] = (close - data["low_20_prior"]) / data["atr_14"].replace(0, np.nan)
    data["rolling_high_252"] = close.rolling(252, min_periods=60).max()
    data["rolling_low_252"] = close.rolling(252, min_periods=60).min()
    data["position_52w"] = (
        (close - data["rolling_low_252"])
        / (data["rolling_high_252"] - data["rolling_low_252"]).replace(0, np.nan)
    ).clip(0, 1)

    data["drawdown"] = close / close.cummax() - 1
    data["return_z_20"] = causal_zscore(data["log_return"], 20, 12)
    if data["volume"].notna().any():
        log_volume = np.log1p(data["volume"].clip(lower=0))
        data["volume_z_60"] = causal_zscore(log_volume, 60, 20)
        data["volume_ratio_20"] = data["volume"] / data["volume"].rolling(20, min_periods=10).mean()
    else:
        data["volume_z_60"] = np.nan
        data["volume_ratio_20"] = np.nan

    benchmark_columns = [column for column in data.columns if column.startswith("benchmark_")]
    relative_components: list[pd.Series] = []
    for benchmark_column in benchmark_columns:
        benchmark = data[benchmark_column]
        slug = benchmark_column.removeprefix("benchmark_")
        ratio = close / benchmark.replace(0, np.nan)
        data[f"rs_{slug}_20"] = close.pct_change(20) - benchmark.pct_change(20)
        data[f"rs_{slug}_60"] = close.pct_change(60) - benchmark.pct_change(60)
        data[f"rs_{slug}_slope"] = np.log(ratio).diff(20) / 20 * annualisation
        relative_components.append(
            0.45 * causal_zscore(data[f"rs_{slug}_20"], 120, 40)
            + 0.35 * causal_zscore(data[f"rs_{slug}_60"], 180, 60)
            + 0.20 * causal_zscore(data[f"rs_{slug}_slope"], 120, 40)
        )
    if relative_components:
        data["relative_strength_z"] = pd.concat(relative_components, axis=1).mean(axis=1)
    else:
        data["relative_strength_z"] = np.nan

    direction = np.sign(data["momentum_60"].fillna(data["momentum_20"]))
    data["trend_quality"] = (
        direction
        * (
            0.35 * (data["adx_14"] / 50).clip(0, 1.5)
            + 0.35 * data["efficiency_60"].clip(0, 1)
            + 0.30 * data["r2_60"].clip(0, 1)
        )
    ).clip(-1, 1)
    data["momentum_composite"] = (
        0.20 * causal_zscore(data["momentum_20"], 120, 40)
        + 0.35 * causal_zscore(data["momentum_60"], 180, 60)
        + 0.20 * causal_zscore(data["slope_60"], 120, 40)
        + 0.15 * causal_zscore(data["macd_hist_atr"], 120, 40)
        + 0.10 * data["relative_strength_z"].fillna(0)
    ).clip(-4, 4)
    data["noise_score"] = (
        0.50 * (1 - data["efficiency_20"].fillna(0.5))
        + 0.30 * (1 - data["r2_20"].fillna(0.3))
        + 0.20 * ((data["vol_z_60"].fillna(0) + 2) / 4).clip(0, 1)
    ).clip(0, 1)
    return data


MODEL_FEATURES = (
    "momentum_20",
    "momentum_60",
    "slope_20",
    "slope_60",
    "r2_20",
    "r2_60",
    "efficiency_20",
    "efficiency_60",
    "rsi_14",
    "macd_hist_atr",
    "distance_ema20_atr",
    "atr_pct",
    "vol_z_60",
    "drawdown",
    "volume_z_60",
    "relative_strength_z",
    "trend_quality",
    "momentum_composite",
    "noise_score",
)

