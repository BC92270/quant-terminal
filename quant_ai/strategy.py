from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import math
from typing import Any

import numpy as np
import pandas as pd


@dataclass(slots=True)
class StrategySpec:
    name: str = "Trend validation"
    rule: str = "Moving-average trend"
    fast_window: int = 20
    slow_window: int = 100
    lookback: int = 63
    entry_z: float = 1.5
    allow_short: bool = False
    cost_bps: float = 5.0
    slippage_bps: float = 3.0
    train_fraction: float = 0.65
    trials_declared: int = 1

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "StrategySpec":
        value = value or {}
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: value[key] for key in allowed if key in value})


@dataclass(slots=True)
class BacktestResult:
    spec: StrategySpec
    status: str
    summary: dict[str, Any]
    in_sample: dict[str, Any]
    out_of_sample: dict[str, Any]
    benchmark: dict[str, Any]
    diagnostics: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    equity: pd.DataFrame = field(default_factory=pd.DataFrame)
    walk_forward: list[dict[str, Any]] = field(default_factory=list)
    robustness: dict[str, Any] = field(default_factory=dict)

    def serializable(self) -> dict[str, Any]:
        return {
            "spec": asdict(self.spec),
            "status": self.status,
            "summary": self.summary,
            "in_sample": self.in_sample,
            "out_of_sample": self.out_of_sample,
            "benchmark": self.benchmark,
            "diagnostics": list(self.diagnostics),
            "warnings": list(self.warnings),
            "walk_forward": list(self.walk_forward),
            "robustness": dict(self.robustness),
        }


def _close_series(frame: pd.DataFrame) -> pd.Series:
    for column in frame.columns:
        if str(column).lower().strip() == "close":
            close = pd.to_numeric(frame[column], errors="coerce")
            close.index = frame.index
            return close.dropna()
    return pd.Series(dtype=float)


def _positions(close: pd.Series, spec: StrategySpec) -> pd.Series:
    long_value = 1.0
    short_value = -1.0 if spec.allow_short else 0.0
    if spec.rule == "Buy & hold benchmark":
        raw = pd.Series(long_value, index=close.index)
    elif spec.rule == "Time-series momentum":
        momentum = close.pct_change(max(2, int(spec.lookback)))
        raw = pd.Series(np.where(momentum > 0, long_value, short_value), index=close.index)
    elif spec.rule == "Mean reversion z-score":
        window = max(10, int(spec.lookback))
        mean = close.rolling(window).mean()
        std = close.rolling(window).std(ddof=1).replace(0, np.nan)
        zscore = (close - mean) / std
        raw = pd.Series(np.where(zscore < -abs(spec.entry_z), long_value, np.where(zscore > abs(spec.entry_z), short_value, 0.0)), index=close.index)
    elif spec.rule == "Breakout":
        window = max(10, int(spec.lookback))
        prior_high = close.rolling(window).max().shift(1)
        trailing_mean = close.rolling(max(5, window // 2)).mean()
        raw = pd.Series(np.where(close > prior_high, long_value, np.where(close < trailing_mean, short_value, 0.0)), index=close.index)
    else:
        fast = close.rolling(max(2, int(spec.fast_window))).mean()
        slow = close.rolling(max(int(spec.fast_window) + 1, int(spec.slow_window))).mean()
        raw = pd.Series(np.where(fast > slow, long_value, short_value), index=close.index)
    # The decision observed at t is applied to return t+1. This shift is the no-look-ahead contract.
    return raw.shift(1).fillna(0.0).astype(float)


def _metrics(returns: pd.Series, positions: pd.Series | None = None) -> dict[str, Any]:
    clean = returns.replace([np.inf, -np.inf], np.nan).dropna()
    if clean.empty:
        return {}
    equity = (1.0 + clean).cumprod()
    years = max(len(clean) / 252.0, 1 / 252.0)
    total = float(equity.iloc[-1] - 1.0)
    cagr = float(equity.iloc[-1] ** (1.0 / years) - 1.0) if equity.iloc[-1] > 0 else -1.0
    vol = float(clean.std(ddof=1) * math.sqrt(252)) if len(clean) > 1 else 0.0
    sharpe = float(clean.mean() / clean.std(ddof=1) * math.sqrt(252)) if len(clean) > 1 and clean.std(ddof=1) > 0 else 0.0
    downside = clean[clean < 0]
    sortino = float(clean.mean() / downside.std(ddof=1) * math.sqrt(252)) if len(downside) > 1 and downside.std(ddof=1) > 0 else 0.0
    drawdown = equity / equity.cummax() - 1.0
    max_drawdown = float(drawdown.min())
    turnover = float(positions.diff().abs().sum()) if positions is not None and len(positions) else 0.0
    trades = int((positions.diff().abs() > 0).sum()) if positions is not None and len(positions) else 0
    exposure = float(positions.abs().mean()) if positions is not None and len(positions) else 1.0
    return {
        "observations": int(len(clean)),
        "total_return": round(total, 6),
        "cagr": round(cagr, 6),
        "annualized_volatility": round(vol, 6),
        "sharpe": round(sharpe, 4),
        "sortino": round(sortino, 4),
        "max_drawdown": round(max_drawdown, 6),
        "calmar": round(cagr / abs(max_drawdown), 4) if max_drawdown < 0 else None,
        "hit_rate": round(float((clean > 0).mean()), 6),
        "worst_day": round(float(clean.min()), 6),
        "turnover_units": round(turnover, 4),
        "trades": trades,
        "average_exposure": round(exposure, 6),
    }


def _walk_forward_windows(returns: pd.Series, positions: pd.Series, start: int, folds: int = 4) -> list[dict[str, Any]]:
    indices = np.array_split(np.arange(start, len(returns)), max(2, folds))
    windows: list[dict[str, Any]] = []
    for number, index_values in enumerate(indices, start=1):
        if len(index_values) < 10:
            continue
        metrics = _metrics(returns.iloc[index_values], positions.iloc[index_values])
        metrics["fold"] = number
        metrics["start"] = str(returns.index[index_values[0]])
        metrics["end"] = str(returns.index[index_values[-1]])
        windows.append(metrics)
    return windows


def _robustness_grid(
    close: pd.Series,
    asset_returns: pd.Series,
    spec: StrategySpec,
    split: int,
    one_way_cost: float,
) -> dict[str, Any]:
    variants: list[StrategySpec] = []
    if spec.rule == "Moving-average trend":
        for fast_factor, slow_factor in ((0.75, 0.8), (0.8, 1.2), (1.0, 0.8), (1.0, 1.2), (1.25, 1.2)):
            fast = max(2, int(spec.fast_window * fast_factor))
            slow = max(fast + 2, int(spec.slow_window * slow_factor))
            variants.append(replace(spec, fast_window=fast, slow_window=slow))
    elif spec.rule == "Mean reversion z-score":
        for factor, z_delta in ((0.75, -0.25), (0.75, 0.25), (1.0, -0.25), (1.0, 0.25), (1.25, 0.0)):
            variants.append(replace(spec, lookback=max(10, int(spec.lookback * factor)), entry_z=max(0.25, spec.entry_z + z_delta)))
    elif spec.rule in {"Time-series momentum", "Breakout"}:
        variants = [replace(spec, lookback=max(5, int(spec.lookback * factor))) for factor in (0.6, 0.8, 1.2, 1.5, 2.0)]
    else:
        variants = [spec]
    rows: list[dict[str, Any]] = []
    for variant in variants:
        variant_positions = _positions(close, variant)
        variant_turnover = variant_positions.diff().abs().fillna(variant_positions.abs())
        variant_returns = variant_positions * asset_returns - variant_turnover * one_way_cost
        metrics = _metrics(variant_returns.iloc[split:], variant_positions.iloc[split:])
        rows.append(
            {
                "fast_window": variant.fast_window,
                "slow_window": variant.slow_window,
                "lookback": variant.lookback,
                "entry_z": variant.entry_z,
                "oos_sharpe": metrics.get("sharpe", 0.0),
                "oos_total_return": metrics.get("total_return", 0.0),
                "trades": metrics.get("trades", 0),
            }
        )
    sharpes = np.array([float(item["oos_sharpe"] or 0.0) for item in rows], dtype=float)
    returns = np.array([float(item["oos_total_return"] or 0.0) for item in rows], dtype=float)
    return {
        "variants": rows,
        "positive_oos_fraction": round(float((returns > 0).mean()), 4) if len(returns) else 0.0,
        "median_oos_sharpe": round(float(np.median(sharpes)), 4) if len(sharpes) else 0.0,
        "worst_oos_sharpe": round(float(sharpes.min()), 4) if len(sharpes) else 0.0,
        "best_oos_sharpe": round(float(sharpes.max()), 4) if len(sharpes) else 0.0,
        "median_oos_return": round(float(np.median(returns)), 6) if len(returns) else 0.0,
    }


def _bootstrap_oos(returns: pd.Series, paths: int = 600) -> dict[str, Any]:
    clean = returns.replace([np.inf, -np.inf], np.nan).dropna().to_numpy(dtype=float)
    if len(clean) < 20:
        return {}
    rng = np.random.default_rng(20260812)
    sampled = rng.choice(clean, size=(paths, len(clean)), replace=True)
    totals = np.prod(1.0 + sampled, axis=1) - 1.0
    return {
        "paths": paths,
        "probability_positive": round(float((totals > 0).mean()), 4),
        "p05_total_return": round(float(np.quantile(totals, 0.05)), 6),
        "median_total_return": round(float(np.median(totals)), 6),
        "p95_total_return": round(float(np.quantile(totals, 0.95)), 6),
        "expected_shortfall_05": round(float(totals[totals <= np.quantile(totals, 0.05)].mean()), 6),
    }


def run_strategy_backtest(price_data: pd.DataFrame, spec: StrategySpec | dict[str, Any] | None = None) -> BacktestResult:
    spec = spec if isinstance(spec, StrategySpec) else StrategySpec.from_dict(spec)
    close = _close_series(price_data)
    warmup = max(spec.slow_window, spec.lookback, 20)
    if len(close) < warmup + 40:
        return BacktestResult(
            spec,
            "not_available",
            {},
            {},
            {},
            {},
            warnings=[f"At least {warmup + 40} close observations are required for this specification."],
        )

    asset_returns = close.pct_change().fillna(0.0)
    positions = _positions(close, spec)
    turnover = positions.diff().abs().fillna(positions.abs())
    one_way_cost = max(0.0, float(spec.cost_bps + spec.slippage_bps)) / 10_000.0
    strategy_returns = positions * asset_returns - turnover * one_way_cost
    benchmark_returns = asset_returns.copy()
    split = min(len(close) - 20, max(warmup + 10, int(len(close) * min(max(spec.train_fraction, 0.4), 0.85))))

    summary = _metrics(strategy_returns.iloc[warmup:], positions.iloc[warmup:])
    in_sample = _metrics(strategy_returns.iloc[warmup:split], positions.iloc[warmup:split])
    out_of_sample = _metrics(strategy_returns.iloc[split:], positions.iloc[split:])
    benchmark = _metrics(benchmark_returns.iloc[warmup:], pd.Series(1.0, index=benchmark_returns.iloc[warmup:].index))

    doubled_cost_returns = positions * asset_returns - turnover * one_way_cost * 2.0
    doubled_cost = _metrics(doubled_cost_returns.iloc[split:], positions.iloc[split:])
    is_sharpe = float(in_sample.get("sharpe") or 0.0)
    oos_sharpe = float(out_of_sample.get("sharpe") or 0.0)
    degradation = oos_sharpe - is_sharpe
    walk_forward = _walk_forward_windows(strategy_returns, positions, warmup, folds=4)
    robustness = _robustness_grid(close, asset_returns, spec, split, one_way_cost)
    robustness["bootstrap_oos"] = _bootstrap_oos(strategy_returns.iloc[split:])
    positive_variants = float(robustness.get("positive_oos_fraction") or 0.0)
    positive_folds = float(sum(float(item.get("total_return") or 0.0) > 0 for item in walk_forward) / max(1, len(walk_forward)))
    full_sharpe = float(summary.get("sharpe") or 0.0)
    full_cagr = float(summary.get("cagr") or 0.0)
    oos_return = float(out_of_sample.get("total_return") or 0.0)
    doubled_cost_return = float(doubled_cost.get("total_return") or 0.0)

    methodology_score = 10  # shifted-signal implementation
    methodology_score += 5 if int(out_of_sample.get("observations") or 0) >= 60 else 0
    methodology_score += 5 if int(spec.trials_declared) <= 5 else 0
    methodology_score += 5 if int(summary.get("trades") or 0) >= 5 else 0

    oos_score = 15 if oos_sharpe >= 1.0 else 12 if oos_sharpe >= 0.5 else 6 if oos_sharpe > 0 else 0
    oos_score += 10 if oos_return > 0 else 0
    oos_score += 5 if doubled_cost_return > 0 else 0

    economic_score = 8 if full_sharpe >= 1.0 else 6 if full_sharpe >= 0.5 else 3 if full_sharpe >= 0.25 else 0
    economic_score += 7 if full_cagr > 0 else 0

    robustness_score = 10 if degradation >= -0.75 else 5 if degradation >= -1.0 else 0
    robustness_score += 10 if positive_variants >= 0.6 else 5 if positive_variants >= 0.5 else 0
    robustness_score += 10 if positive_folds >= 0.75 else 6 if positive_folds >= 0.5 else 0
    score = min(100, methodology_score + oos_score + economic_score + robustness_score)

    # Methodological cleanliness cannot turn a weak or economically losing strategy into a validated candidate.
    if oos_sharpe <= 0 or oos_return <= 0:
        score = min(score, 59)
    if full_cagr <= 0 or full_sharpe < 0.25:
        score = min(score, 69)
    if positive_variants < 0.5 or positive_folds < 0.5:
        score = min(score, 69)

    diagnostics = [
        "Signal is shifted one bar before realized returns (look-ahead guard).",
        f"Train/test split: {split - warmup} / {len(close) - split} usable observations.",
        f"Out-of-sample Sharpe change versus in-sample: {degradation:+.2f}.",
        f"Out-of-sample return with doubled costs: {float(doubled_cost.get('total_return') or 0.0):+.1%}.",
        f"Declared parameter/configuration trials: {max(1, int(spec.trials_declared))}.",
        f"Positive walk-forward folds: {positive_folds:.0%}; positive parameter neighbors: {positive_variants:.0%}.",
        f"Gate composition — methodology {methodology_score}/25, OOS evidence {oos_score}/30, "
        f"full-sample economics {economic_score}/15, robustness {robustness_score}/30.",
        f"Validation score: {score}/100 — research gate, not a capital approval.",
    ]
    warnings: list[str] = []
    if int(spec.trials_declared) > 20:
        warnings.append("High declared trial count increases selection and backtest-overfitting risk.")
    if int(out_of_sample.get("observations") or 0) < 60:
        warnings.append("The out-of-sample window is short; confidence must remain low.")
    if oos_sharpe <= 0:
        warnings.append("The strategy has no positive out-of-sample risk-adjusted evidence.")
    if full_cagr <= 0:
        warnings.append("Full-sample CAGR is not positive; methodological validity does not establish economic alpha.")
    if full_sharpe < 0.25:
        warnings.append("Full-sample Sharpe is below the minimum economic-quality floor of 0.25.")
    if degradation < -1.0:
        warnings.append("Severe out-of-sample degradation suggests instability or overfitting.")
    if int(summary.get("trades") or 0) < 5:
        warnings.append("Too few trades for a reliable strategy inference.")
    if positive_variants < 0.5:
        warnings.append("Most nearby parameter configurations fail out-of-sample; the result is not structurally stable.")
    if positive_folds < 0.5:
        warnings.append("Fewer than half of the chronological walk-forward folds are profitable.")

    equity = pd.DataFrame(
        {
            "Strategy": (1.0 + strategy_returns.iloc[warmup:]).cumprod(),
            "Benchmark": (1.0 + benchmark_returns.iloc[warmup:]).cumprod(),
        }
    )
    summary.update(
        {
            "validation_score": score,
            "out_of_sample_degradation": round(degradation, 4),
            "double_cost_oos_return": doubled_cost.get("total_return"),
            "split_index": split,
            "positive_walk_forward_fraction": round(positive_folds, 4),
            "positive_parameter_fraction": round(positive_variants, 4),
            "methodology_score": methodology_score,
            "out_of_sample_score": oos_score,
            "economic_score": economic_score,
            "robustness_score": robustness_score,
        }
    )
    status = "validated_candidate" if score >= 75 and not warnings else "research_only"
    return BacktestResult(spec, status, summary, in_sample, out_of_sample, benchmark, diagnostics, warnings, equity, walk_forward, robustness)
