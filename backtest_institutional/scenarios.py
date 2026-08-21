"""Regime, tail, multivariate and reverse-stress scenario engines."""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ScenarioConfig:
    horizon_days: int = 252
    paths: int = 500
    seed: int = 41
    confidence: float = 0.975
    student_df: float = 5.0
    high_vol_multiplier: float = 2.25
    crisis_correlation: float = 0.80
    liquidity_cost_bps: float = 35.0
    target_drawdown: float = -0.20


def _clean_returns(returns: pd.Series | pd.DataFrame) -> pd.DataFrame:
    frame = returns.to_frame("strategy") if isinstance(returns, pd.Series) else returns.copy()
    frame = frame.apply(pd.to_numeric, errors="coerce").dropna(how="all").fillna(0.0)
    if frame.empty:
        raise ValueError("DATA REQUIRED: non-empty returns")
    return frame


def _nearest_psd(correlation: np.ndarray) -> np.ndarray:
    corr = np.asarray(correlation, dtype=float)
    corr = (corr + corr.T) / 2.0
    values, vectors = np.linalg.eigh(corr)
    values = np.maximum(values, 1e-8)
    result = vectors @ np.diag(values) @ vectors.T
    scale = np.sqrt(np.diag(result))
    return result / np.outer(scale, scale)


def _path_metrics(paths: np.ndarray, confidence: float) -> dict[str, float]:
    terminal = np.prod(1.0 + paths, axis=1) - 1.0
    equity = np.cumprod(1.0 + paths, axis=1)
    running = np.maximum.accumulate(equity, axis=1)
    drawdowns = equity / running - 1.0
    max_dd = drawdowns.min(axis=1)
    cutoff = max(1, int(np.ceil((1.0 - confidence) * len(terminal))))
    worst = np.sort(terminal)[:cutoff]
    return {
        "median_terminal_return": float(np.median(terminal)),
        "p05_terminal_return": float(np.quantile(terminal, 0.05)),
        "expected_shortfall": float(worst.mean()),
        "median_max_drawdown": float(np.median(max_dd)),
        "p05_max_drawdown": float(np.quantile(max_dd, 0.05)),
        "breach_probability": float(np.mean(max_dd <= -0.20)),
    }


def multivariate_student_t_paths(
    returns: pd.DataFrame,
    config: ScenarioConfig,
) -> np.ndarray:
    clean = _clean_returns(returns)
    matrix = clean.to_numpy(dtype=float)
    means = matrix.mean(axis=0)
    covariance = np.cov(matrix, rowvar=False)
    covariance = np.atleast_2d(covariance)
    volatility = np.sqrt(np.maximum(np.diag(covariance), 1e-12))
    correlation = covariance / np.outer(volatility, volatility)
    correlation = _nearest_psd(correlation)
    rng = np.random.default_rng(config.seed)
    normals = rng.multivariate_normal(
        np.zeros(clean.shape[1]), correlation,
        size=(config.paths, config.horizon_days),
    )
    chi = rng.chisquare(config.student_df, size=(config.paths, config.horizon_days, 1))
    t_draws = normals / np.sqrt(chi / config.student_df)
    scaled = t_draws * volatility.reshape(1, 1, -1) * sqrt((config.student_df - 2.0) / config.student_df)
    return means.reshape(1, 1, -1) + scaled


def markov_regime_paths(
    returns: pd.Series,
    config: ScenarioConfig,
) -> tuple[np.ndarray, np.ndarray]:
    clean = pd.to_numeric(returns, errors="coerce").dropna().to_numpy(dtype=float)
    mu = float(clean.mean())
    sigma = max(float(clean.std(ddof=1)), 1e-6)
    transition = np.asarray([[0.975, 0.023, 0.002], [0.08, 0.88, 0.04], [0.04, 0.16, 0.80]])
    drifts = np.asarray([mu, mu * 0.25, mu - 0.75 * sigma])
    vols = np.asarray([0.75 * sigma, 1.25 * sigma, config.high_vol_multiplier * sigma])
    rng = np.random.default_rng(config.seed + 1)
    states = np.zeros((config.paths, config.horizon_days), dtype=int)
    paths = np.zeros_like(states, dtype=float)
    for p in range(config.paths):
        state = 0
        for t in range(config.horizon_days):
            state = int(rng.choice(3, p=transition[state]))
            states[p, t] = state
            paths[p, t] = drifts[state] + vols[state] * rng.standard_normal()
    return paths, states


def empirical_evt_tail_paths(
    returns: pd.Series,
    config: ScenarioConfig,
) -> tuple[np.ndarray, dict[str, float]]:
    clean = pd.to_numeric(returns, errors="coerce").dropna().to_numpy(dtype=float)
    threshold = float(np.quantile(clean, 0.10))
    tail = clean[clean <= threshold]
    body = clean[clean > threshold]
    rng = np.random.default_rng(config.seed + 2)
    indicator = rng.random((config.paths, config.horizon_days)) < max(len(tail) / len(clean), 0.10)
    body_draw = rng.choice(body if len(body) else clean, size=indicator.shape, replace=True)
    tail_draw = rng.choice(tail if len(tail) else clean, size=indicator.shape, replace=True)
    # Preserve empirical extremes and thicken the loss tail with a calibrated exponential excess.
    excess_scale = max(float(np.mean(threshold - tail)) if len(tail) else 0.0, 1e-8)
    extra = rng.exponential(excess_scale, size=indicator.shape)
    tail_draw = np.minimum(tail_draw, threshold - extra)
    paths = np.where(indicator, tail_draw, body_draw)
    return paths, {
        "threshold": threshold,
        "tail_observations": int(len(tail)),
        "tail_probability": float(len(tail) / len(clean)),
        "mean_excess": excess_scale,
    }


def liquidity_spiral_paths(
    returns: pd.Series,
    config: ScenarioConfig,
) -> np.ndarray:
    clean = pd.to_numeric(returns, errors="coerce").dropna().to_numpy(dtype=float)
    rng = np.random.default_rng(config.seed + 3)
    paths = rng.choice(clean, size=(config.paths, config.horizon_days), replace=True)
    cost = config.liquidity_cost_bps / 10_000.0
    for t in range(1, config.horizon_days):
        prior_loss = np.minimum(paths[:, t - 1], 0.0)
        feedback = 0.35 * prior_loss
        stochastic_cost = cost * (1.0 + np.abs(prior_loss) / max(np.std(clean), 1e-6))
        paths[:, t] += feedback - stochastic_cost
    return paths


def reverse_stress_multiplier(
    returns: pd.Series,
    *,
    target_drawdown: float = -0.20,
    max_multiplier: float = 20.0,
) -> dict[str, float | bool]:
    clean = pd.to_numeric(returns, errors="coerce").dropna().to_numpy(dtype=float)
    losses = np.minimum(clean, 0.0)
    if not np.any(losses < 0):
        return {"multiplier": float("inf"), "target_drawdown": target_drawdown, "breached": False}
    def drawdown(multiplier: float) -> float:
        shocked = np.where(clean < 0, clean * multiplier, clean)
        equity = np.cumprod(1.0 + np.clip(shocked, -0.99, None))
        return float(np.min(equity / np.maximum.accumulate(equity) - 1.0))
    if drawdown(max_multiplier) > target_drawdown:
        return {"multiplier": max_multiplier, "target_drawdown": target_drawdown, "breached": False}
    lo, hi = 1.0, max_multiplier
    for _ in range(48):
        mid = (lo + hi) / 2.0
        if drawdown(mid) <= target_drawdown:
            hi = mid
        else:
            lo = mid
    return {
        "multiplier": float(hi),
        "target_drawdown": float(target_drawdown),
        "breached": True,
        "drawdown_at_multiplier": drawdown(hi),
    }


def run_institutional_scenario_suite(
    returns: pd.Series,
    *,
    factor_returns: pd.DataFrame | None = None,
    config: ScenarioConfig | None = None,
) -> dict[str, object]:
    config = config or ScenarioConfig()
    strategy = pd.to_numeric(returns, errors="coerce").dropna()
    if len(strategy) < 30:
        raise ValueError("DATA REQUIRED: at least 30 observations for scenario generation")
    factors = _clean_returns(factor_returns) if factor_returns is not None and not factor_returns.empty else strategy.to_frame("strategy")
    multi = multivariate_student_t_paths(factors, config)[:, :, 0]
    regime, states = markov_regime_paths(strategy, config)
    evt, evt_meta = empirical_evt_tail_paths(strategy, config)
    liquidity = liquidity_spiral_paths(strategy, config)
    historical = np.random.default_rng(config.seed + 4).choice(
        strategy.to_numpy(dtype=float),
        size=(config.paths, config.horizon_days),
        replace=True,
    )
    scenarios = {
        "Historical bootstrap": historical,
        "Multivariate Student-t": multi,
        "Markov regime switching": regime,
        "EVT empirical tail": evt,
        "Liquidity spiral": liquidity,
    }
    rows = []
    for name, paths in scenarios.items():
        rows.append({"scenario": name, **_path_metrics(paths, config.confidence)})
    summary = pd.DataFrame(rows).set_index("scenario")
    regime_mix = {
        "calm": float(np.mean(states == 0)),
        "volatile": float(np.mean(states == 1)),
        "crisis": float(np.mean(states == 2)),
    }
    return {
        "summary": summary,
        "paths": scenarios,
        "reverse_stress": reverse_stress_multiplier(strategy, target_drawdown=config.target_drawdown),
        "evt": evt_meta,
        "regime_mix": regime_mix,
        "config": config,
        "seed": config.seed,
    }
