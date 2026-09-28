"""Regime, tail, multivariate and reverse-stress scenario engines."""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil, sqrt
from typing import Any

import numpy as np
import pandas as pd

try:  # scipy is part of the product requirements; fail closed if a thin runtime omits it.
    from scipy.stats import genpareto, kstest
except ImportError:  # pragma: no cover - exercised only by unsupported runtimes.
    genpareto = None
    kstest = None


INSTITUTIONAL_MIN_PATHS = 250
INSTITUTIONAL_MIN_HORIZON_DAYS = 20
INSTITUTIONAL_MIN_CONFIDENCE = 0.95


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
    historical_block_length: int = 10
    evt_threshold_quantile: float = 0.90
    evt_min_tail_observations: int = 15
    policy: str = "institutional"


def _validate_config(config: ScenarioConfig) -> None:
    if str(config.policy).lower() not in {"institutional", "exploratory"}:
        raise ValueError("Scenario policy must be 'institutional' or 'exploratory'")
    for name, value in (("horizon_days", config.horizon_days), ("paths", config.paths), ("seed", config.seed)):
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
            raise ValueError(f"Scenario {name} must be an integer")
    if config.horizon_days < 1 or config.paths < 1:
        raise ValueError("Scenario horizon and path count must be positive")
    if not np.isfinite(config.confidence) or not 0.50 < config.confidence < 1.0:
        raise ValueError("Scenario confidence must be between 0.50 and 1.0")
    if not np.isfinite(config.student_df) or config.student_df <= 2.0:
        raise ValueError("Student-t degrees of freedom must exceed two")
    if not np.isfinite(config.high_vol_multiplier) or config.high_vol_multiplier <= 0.0:
        raise ValueError("High-volatility multiplier must be strictly positive")
    if not np.isfinite(config.liquidity_cost_bps) or config.liquidity_cost_bps < 0.0:
        raise ValueError("Liquidity cost must be non-negative")
    if not np.isfinite(config.crisis_correlation) or not 0.0 <= config.crisis_correlation < 1.0:
        raise ValueError("Crisis correlation must be in [0, 1)")
    if not np.isfinite(config.target_drawdown) or not -1.0 < config.target_drawdown < 0.0:
        raise ValueError("Target drawdown must be in (-1, 0)")
    if (
        isinstance(config.historical_block_length, (bool, np.bool_))
        or not isinstance(config.historical_block_length, (int, np.integer))
        or config.historical_block_length < 1
    ):
        raise ValueError("Historical block length must be positive")
    if not 0.50 < config.evt_threshold_quantile < 0.99:
        raise ValueError("EVT threshold quantile must be between 0.50 and 0.99")
    if (
        isinstance(config.evt_min_tail_observations, (bool, np.bool_))
        or not isinstance(config.evt_min_tail_observations, (int, np.integer))
        or config.evt_min_tail_observations < 8
    ):
        raise ValueError("EVT requires at least eight tail observations")


def _institutional_policy_assessment(config: ScenarioConfig) -> dict[str, Any]:
    """Return a gateable policy result while still allowing exploratory output.

    Small/zero-cost runs are useful for deterministic development, but they
    must never be represented as institutionally calibrated.  The scenario
    suite therefore keeps generating explicitly exploratory diagnostics while
    exposing an UNAVAILABLE policy state consumed by the institutional gate.
    """
    _validate_config(config)
    reasons: list[str] = []
    if str(config.policy).lower() != "institutional":
        reasons.append("configuration explicitly requests exploratory policy")
    if int(config.paths) < INSTITUTIONAL_MIN_PATHS:
        reasons.append(f"paths {int(config.paths)} < {INSTITUTIONAL_MIN_PATHS}")
    if int(config.horizon_days) < INSTITUTIONAL_MIN_HORIZON_DAYS:
        reasons.append(
            f"horizon {int(config.horizon_days)} < {INSTITUTIONAL_MIN_HORIZON_DAYS} periods"
        )
    if float(config.confidence) < INSTITUTIONAL_MIN_CONFIDENCE:
        reasons.append(
            f"confidence {float(config.confidence):.1%} < {INSTITUTIONAL_MIN_CONFIDENCE:.1%}"
        )
    if float(config.high_vol_multiplier) < 1.0:
        reasons.append("high-volatility multiplier must be at least 1.0")
    if float(config.liquidity_cost_bps) <= 0.0:
        reasons.append("institutional liquidity cost must be strictly positive")
    return {
        "state": "UNAVAILABLE" if reasons else "AVAILABLE",
        "reason": (
            "Institutional scenario minima not met: " + "; ".join(reasons)
            if reasons
            else "Institutional scenario minima satisfied"
        ),
        "policy": str(config.policy).lower(),
        "minimum_paths": INSTITUTIONAL_MIN_PATHS,
        "minimum_horizon_days": INSTITUTIONAL_MIN_HORIZON_DAYS,
        "minimum_confidence": INSTITUTIONAL_MIN_CONFIDENCE,
        "requires_positive_liquidity_cost": True,
    }


def _clean_returns(returns: pd.Series | pd.DataFrame) -> pd.DataFrame:
    frame = returns.to_frame("strategy") if isinstance(returns, pd.Series) else returns.copy()
    frame = frame.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    frame = frame.dropna(axis=1, how="all").dropna(how="any")
    if frame.empty:
        raise ValueError("DATA REQUIRED: non-empty finite returns")
    if frame.columns.duplicated().any():
        raise ValueError("DATA INVALID: scenario return columns must be unique")
    return frame


def _nearest_psd(correlation: np.ndarray) -> np.ndarray:
    corr = np.asarray(correlation, dtype=float)
    corr = (corr + corr.T) / 2.0
    values, vectors = np.linalg.eigh(corr)
    values = np.maximum(values, 1e-8)
    result = vectors @ np.diag(values) @ vectors.T
    scale = np.sqrt(np.maximum(np.diag(result), 1e-12))
    return result / np.outer(scale, scale)


def _stressed_correlation(correlation: np.ndarray, crisis_correlation: float) -> np.ndarray:
    """Apply an explicit crisis co-movement floor to off-diagonal correlations."""
    corr = _nearest_psd(correlation)
    if corr.shape[0] <= 1:
        return corr
    stressed = corr.copy()
    off_diagonal = ~np.eye(corr.shape[0], dtype=bool)
    stressed[off_diagonal] = np.maximum(stressed[off_diagonal], crisis_correlation)
    np.fill_diagonal(stressed, 1.0)
    return _nearest_psd(stressed)


def _path_metrics(
    paths: np.ndarray,
    confidence: float,
    target_drawdown: float = -0.20,
) -> dict[str, float]:
    values = np.asarray(paths, dtype=float)
    if values.ndim != 2 or values.shape[0] < 1 or values.shape[1] < 1:
        raise ValueError("Scenario paths must be a non-empty two-dimensional matrix")
    if not np.isfinite(values).all():
        raise ValueError("Scenario paths contain non-finite returns")
    # NAV starts at one. Without this prefix, a first-period loss is incorrectly
    # treated as a new high-water mark and disappears from max drawdown.
    gross = 1.0 + np.clip(values, -1.0, None)
    equity = np.concatenate(
        [np.ones((len(values), 1)), np.cumprod(gross, axis=1)],
        axis=1,
    )
    terminal = equity[:, -1] - 1.0
    running = np.maximum.accumulate(equity, axis=1)
    drawdowns = np.divide(equity, running, out=np.ones_like(equity), where=running > 0.0) - 1.0
    max_dd = drawdowns.min(axis=1)
    cutoff = max(1, int(np.ceil((1.0 - confidence) * len(terminal))))
    worst = np.sort(terminal)[:cutoff]
    return {
        "median_terminal_return": float(np.median(terminal)),
        "p05_terminal_return": float(np.quantile(terminal, 0.05)),
        "expected_shortfall": float(worst.mean()),
        "median_max_drawdown": float(np.median(max_dd)),
        "p05_max_drawdown": float(np.quantile(max_dd, 0.05)),
        "breach_probability": float(np.mean(max_dd <= target_drawdown)),
    }


def multivariate_student_t_paths(
    returns: pd.DataFrame,
    config: ScenarioConfig,
    *,
    return_metadata: bool = False,
) -> np.ndarray | tuple[np.ndarray, dict[str, Any]]:
    _validate_config(config)
    clean = _clean_returns(returns)
    if clean.shape[1] < 2:
        raise ValueError(
            "DATA REQUIRED: Multivariate Student-t needs at least two aligned factor-return columns"
        )
    if len(clean) < max(10, clean.shape[1] + 3):
        raise ValueError("DATA REQUIRED: insufficient observations for multivariate calibration")
    matrix = clean.to_numpy(dtype=float)
    factor_volatility = matrix.std(axis=0, ddof=1)
    if not np.isfinite(factor_volatility).all() or np.any(factor_volatility <= 0.0):
        invalid = [
            str(column)
            for column, volatility in zip(clean.columns, factor_volatility)
            if not np.isfinite(volatility) or volatility <= 0.0
        ]
        raise ValueError("DATA INVALID: non-positive factor volatility: " + ", ".join(invalid))
    means = matrix.mean(axis=0)
    covariance = np.atleast_2d(np.cov(matrix, rowvar=False, ddof=1))
    volatility = np.sqrt(np.maximum(np.diag(covariance), 1e-12))
    empirical = covariance / np.outer(volatility, volatility)
    empirical = _nearest_psd(empirical)
    correlation = _stressed_correlation(empirical, config.crisis_correlation)
    rng = np.random.default_rng(config.seed)
    normals = rng.multivariate_normal(
        np.zeros(clean.shape[1]), correlation,
        size=(config.paths, config.horizon_days),
    )
    chi = rng.chisquare(config.student_df, size=(config.paths, config.horizon_days, 1))
    t_draws = normals / np.sqrt(chi / config.student_df)
    scaled = t_draws * volatility.reshape(1, 1, -1) * sqrt((config.student_df - 2.0) / config.student_df)
    paths = means.reshape(1, 1, -1) + scaled
    metadata = {
        "method": "multivariate Student-t with crisis-correlation floor",
        "observations": int(len(clean)),
        "columns": [str(column) for column in clean.columns],
        "student_df": float(config.student_df),
        "crisis_correlation_floor": float(config.crisis_correlation),
        "empirical_correlation": empirical.tolist(),
        "scenario_correlation": correlation.tolist(),
    }
    return (paths, metadata) if return_metadata else paths


def marginal_student_t_paths(
    returns: pd.Series,
    config: ScenarioConfig,
    *,
    return_metadata: bool = False,
) -> np.ndarray | tuple[np.ndarray, dict[str, Any]]:
    """Simulate one strategy marginal without claiming multivariate evidence."""
    _validate_config(config)
    clean = pd.to_numeric(returns, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) < 10:
        raise ValueError("DATA REQUIRED: at least ten observations for marginal Student-t")
    volatility = float(clean.std(ddof=1))
    if not np.isfinite(volatility) or volatility <= 0.0:
        raise ValueError("DATA INVALID: positive realized volatility is required")
    rng = np.random.default_rng(config.seed + 9)
    innovation = rng.standard_t(
        config.student_df,
        size=(config.paths, config.horizon_days),
    ) * sqrt((config.student_df - 2.0) / config.student_df)
    paths = np.maximum(float(clean.mean()) + volatility * innovation, -0.999999)
    metadata = {
        "method": "univariate marginal Student-t",
        "multivariate": False,
        "observations": int(len(clean)),
        "student_df": float(config.student_df),
        "volatility": volatility,
    }
    return (paths, metadata) if return_metadata else paths


def _markov_calibration(returns: np.ndarray, config: ScenarioConfig) -> dict[str, Any]:
    if len(returns) < 30:
        raise ValueError("DATA REQUIRED: at least 30 observations for Markov calibration")
    series = pd.Series(returns, dtype=float)
    window = min(21, max(5, len(series) // 10))
    rolling = series.rolling(window, min_periods=2).std(ddof=1)
    expanding = series.expanding(min_periods=2).std(ddof=1)
    global_sigma = max(float(series.std(ddof=1)), 1e-8)
    volatility = rolling.fillna(expanding).fillna(global_sigma)
    loss_cutoff = float(series.quantile(0.10))
    quiet_cutoff = float(volatility.quantile(0.50))
    crisis_vol_cutoff = float(volatility.quantile(0.90))

    observed_states = np.ones(len(series), dtype=int)
    observed_states[(volatility.to_numpy() <= quiet_cutoff) & (returns > loss_cutoff)] = 0
    observed_states[(returns <= loss_cutoff) | (volatility.to_numpy() >= crisis_vol_cutoff)] = 2

    # A sticky Dirichlet prior avoids zero-probability transitions without hiding
    # that this is an observable-state proxy rather than a fitted latent HMM.
    counts = np.full((3, 3), 0.5, dtype=float)
    counts += np.eye(3) * 2.0
    for previous, current in zip(observed_states[:-1], observed_states[1:]):
        counts[previous, current] += 1.0
    transition = counts / counts.sum(axis=1, keepdims=True)
    state_counts = np.bincount(observed_states, minlength=3)
    initial = (state_counts + 1.0) / (state_counts.sum() + 3.0)

    global_mean = float(series.mean())
    drifts = np.zeros(3, dtype=float)
    vols = np.zeros(3, dtype=float)
    for state in range(3):
        sample = returns[observed_states == state]
        weight = len(sample) / (len(sample) + 20.0)
        local_mean = float(sample.mean()) if len(sample) else global_mean
        local_sigma = float(sample.std(ddof=1)) if len(sample) > 1 else global_sigma
        drifts[state] = weight * local_mean + (1.0 - weight) * global_mean
        vols[state] = max(weight * local_sigma + (1.0 - weight) * global_sigma, 1e-8)
    vols[1] = max(vols[1], 1.15 * vols[0])
    vols[2] = max(vols[2], config.high_vol_multiplier * vols[0])
    drifts[2] = min(drifts[2], global_mean - 0.25 * global_sigma)
    return {
        "transition": transition,
        "initial": initial,
        "drifts": drifts,
        "volatilities": vols,
        "observed_states": observed_states,
        "state_counts": state_counts,
        "rolling_window": window,
        "loss_cutoff": loss_cutoff,
        "crisis_vol_cutoff": crisis_vol_cutoff,
    }


def markov_regime_paths(
    returns: pd.Series,
    config: ScenarioConfig,
    *,
    return_metadata: bool = False,
) -> tuple[np.ndarray, np.ndarray] | tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    _validate_config(config)
    clean = pd.to_numeric(returns, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().to_numpy(dtype=float)
    calibration = _markov_calibration(clean, config)
    transition = calibration["transition"]
    drifts = calibration["drifts"]
    vols = calibration["volatilities"]
    rng = np.random.default_rng(config.seed + 1)
    states = np.zeros((config.paths, config.horizon_days), dtype=int)
    paths = np.zeros_like(states, dtype=float)
    innovation_scale = sqrt((config.student_df - 2.0) / config.student_df)
    for p in range(config.paths):
        state = int(rng.choice(3, p=calibration["initial"]))
        for t in range(config.horizon_days):
            states[p, t] = state
            innovation = rng.standard_t(config.student_df) * innovation_scale
            paths[p, t] = max(drifts[state] + vols[state] * innovation, -0.999999)
            state = int(rng.choice(3, p=transition[state]))
    metadata = {
        "method": "empirically calibrated observable-state Markov proxy",
        "is_latent_hmm": False,
        "observations": int(len(clean)),
        "rolling_window": int(calibration["rolling_window"]),
        "state_counts": calibration["state_counts"].astype(int).tolist(),
        "transition_matrix": transition.tolist(),
        "initial_probabilities": calibration["initial"].tolist(),
        "drifts": drifts.tolist(),
        "volatilities": vols.tolist(),
        "loss_cutoff": float(calibration["loss_cutoff"]),
        "crisis_vol_cutoff": float(calibration["crisis_vol_cutoff"]),
    }
    return (paths, states, metadata) if return_metadata else (paths, states)


def empirical_evt_tail_paths(
    returns: pd.Series,
    config: ScenarioConfig,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Generate loss-tail paths using a peaks-over-threshold GPD calibration."""
    _validate_config(config)
    if genpareto is None or kstest is None:
        raise RuntimeError("DEPENDENCY REQUIRED: scipy is needed for EVT calibration")
    clean = pd.to_numeric(returns, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().to_numpy(dtype=float)
    required = max(
        30,
        int(ceil(config.evt_min_tail_observations / (1.0 - config.evt_threshold_quantile))),
    )
    if len(clean) < required:
        raise ValueError(
            f"DATA REQUIRED: {required} observations needed for EVT; {len(clean)} supplied"
        )
    losses = -clean
    threshold_loss = float(np.quantile(losses, config.evt_threshold_quantile))
    tail_mask = losses > threshold_loss
    excess = losses[tail_mask] - threshold_loss
    if len(excess) < config.evt_min_tail_observations or len(np.unique(excess)) < 5:
        raise ValueError(
            "DATA REQUIRED: insufficient distinct peaks-over-threshold observations for EVT"
        )
    shape, location, scale = genpareto.fit(excess, floc=0.0)
    if (
        not np.isfinite([shape, location, scale]).all()
        or abs(location) > 1e-12
        or scale <= 0.0
        or shape <= -1.0
        or shape >= 1.0
    ):
        raise ValueError("EVT CALIBRATION FAILED: implausible generalized-Pareto parameters")
    body = clean[~tail_mask]
    if len(body) < 5:
        raise ValueError("DATA REQUIRED: insufficient body observations for EVT mixture")

    rng = np.random.default_rng(config.seed + 2)
    indicator = rng.random((config.paths, config.horizon_days)) < (len(excess) / len(clean))
    body_draw = rng.choice(body, size=indicator.shape, replace=True)
    excess_draw = genpareto.rvs(
        shape,
        loc=0.0,
        scale=scale,
        size=indicator.shape,
        random_state=rng,
    )
    tail_draw = np.maximum(-(threshold_loss + excess_draw), -0.999999)
    paths = np.where(indicator, tail_draw, body_draw)
    ks = kstest(excess, "genpareto", args=(shape, 0.0, scale))
    return paths, {
        "status": "CALIBRATED",
        "method": "peaks-over-threshold generalized Pareto (MLE, location fixed at zero)",
        "threshold": float(-threshold_loss),
        "loss_threshold": threshold_loss,
        "threshold_quantile": float(config.evt_threshold_quantile),
        "tail_observations": int(len(excess)),
        "tail_probability": float(len(excess) / len(clean)),
        "shape": float(shape),
        "scale": float(scale),
        "mean_excess": float(excess.mean()),
        "ks_statistic": float(ks.statistic),
        "ks_p_value_approximate": float(ks.pvalue),
        "daily_loss_cap": 0.999999,
    }


def _circular_block_bootstrap_paths(
    returns: np.ndarray,
    *,
    paths: int,
    horizon: int,
    block_length: int,
    seed: int,
) -> np.ndarray:
    values = np.asarray(returns, dtype=float)
    if values.ndim != 1 or len(values) < 2 or not np.isfinite(values).all():
        raise ValueError("DATA REQUIRED: finite return history for block bootstrap")
    block = max(1, min(int(block_length), len(values), horizon))
    rng = np.random.default_rng(seed)
    result = np.empty((paths, horizon), dtype=float)
    for path in range(paths):
        cursor = 0
        while cursor < horizon:
            start = int(rng.integers(0, len(values)))
            width = min(block, horizon - cursor)
            indices = (start + np.arange(width)) % len(values)
            result[path, cursor:cursor + width] = values[indices]
            cursor += width
    return result


def liquidity_spiral_paths(
    returns: pd.Series,
    config: ScenarioConfig,
) -> np.ndarray:
    _validate_config(config)
    clean = pd.to_numeric(returns, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().to_numpy(dtype=float)
    realized_volatility = float(np.std(clean, ddof=1)) if len(clean) > 1 else float("nan")
    if not np.isfinite(realized_volatility) or realized_volatility <= 0.0:
        raise ValueError("DATA INVALID: positive realized volatility is required for liquidity stress")
    paths = _circular_block_bootstrap_paths(
        clean,
        paths=config.paths,
        horizon=config.horizon_days,
        block_length=config.historical_block_length,
        seed=config.seed + 3,
    )
    cost = config.liquidity_cost_bps / 10_000.0
    sigma = realized_volatility
    for t in range(1, config.horizon_days):
        prior_loss = np.minimum(paths[:, t - 1], 0.0)
        feedback = 0.35 * prior_loss
        stochastic_cost = cost * (1.0 + np.abs(prior_loss) / sigma)
        paths[:, t] = np.maximum(paths[:, t] + feedback - stochastic_cost, -0.999999)
    return paths


def reverse_stress_multiplier(
    returns: pd.Series,
    *,
    target_drawdown: float = -0.20,
    max_multiplier: float = 20.0,
) -> dict[str, float | bool]:
    clean = pd.to_numeric(returns, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().to_numpy(dtype=float)
    if not -1.0 < target_drawdown < 0.0:
        raise ValueError("Target drawdown must be in (-1, 0)")
    if max_multiplier < 1.0:
        raise ValueError("Maximum stress multiplier must be at least one")
    if clean.size == 0:
        raise ValueError("DATA REQUIRED: non-empty returns for reverse stress")
    losses = np.minimum(clean, 0.0)
    if not np.any(losses < 0):
        return {"multiplier": float("inf"), "target_drawdown": target_drawdown, "breached": False}

    def drawdown(multiplier: float) -> float:
        shocked = np.where(clean < 0, clean * multiplier, clean)
        equity = np.concatenate([
            np.ones(1),
            np.cumprod(1.0 + np.clip(shocked, -0.999999, None)),
        ])
        return float(np.min(equity / np.maximum.accumulate(equity) - 1.0))

    if drawdown(max_multiplier) > target_drawdown:
        return {"multiplier": max_multiplier, "target_drawdown": target_drawdown, "breached": False}
    if drawdown(1.0) <= target_drawdown:
        return {
            "multiplier": 1.0,
            "target_drawdown": float(target_drawdown),
            "breached": True,
            "drawdown_at_multiplier": drawdown(1.0),
        }
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


def _factor_strategy_paths(
    strategy: pd.Series,
    factors: pd.DataFrame,
    factor_paths: np.ndarray,
    config: ScenarioConfig,
) -> tuple[np.ndarray, dict[str, Any]]:
    joined = pd.concat([strategy.rename("__strategy__"), factors], axis=1, join="inner")
    joined = joined.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if joined.columns.duplicated().any():
        raise ValueError("DATA INVALID: duplicate factor names")
    minimum = max(30, factors.shape[1] + 5)
    if len(joined) < minimum:
        raise ValueError(
            f"DATA REQUIRED: {minimum} aligned strategy/factor observations; {len(joined)} supplied"
        )
    x = joined.iloc[:, 1:].to_numpy(dtype=float)
    y = joined.iloc[:, 0].to_numpy(dtype=float)
    variation = np.std(x, axis=0, ddof=1) > 1e-12
    if not np.all(variation):
        dropped = [str(column) for column, keep in zip(joined.columns[1:], variation) if not keep]
        raise ValueError("DATA INVALID: constant factor columns: " + ", ".join(dropped))
    design = np.column_stack([np.ones(len(x)), x])
    coefficients, _, rank, _ = np.linalg.lstsq(design, y, rcond=None)
    if rank < design.shape[1]:
        raise ValueError("DATA INVALID: collinear factor design")
    fitted = design @ coefficients
    residual = y - fitted
    residual_sigma = max(float(np.std(residual, ddof=design.shape[1])), 0.0)
    rng = np.random.default_rng(config.seed + 11)
    residual_draws = rng.standard_t(
        config.student_df,
        size=(config.paths, config.horizon_days),
    ) * sqrt((config.student_df - 2.0) / config.student_df) * residual_sigma
    aggregated = coefficients[0] + np.einsum("ptf,f->pt", factor_paths, coefficients[1:]) + residual_draws
    denominator = float(np.sum((y - y.mean()) ** 2))
    r_squared = 1.0 - float(np.sum(residual ** 2)) / denominator if denominator > 0.0 else 0.0
    return np.maximum(aggregated, -0.999999), {
        "method": "historical OLS factor exposure plus Student-t residual",
        "observations": int(len(joined)),
        "intercept": float(coefficients[0]),
        "exposures": {
            str(column): float(beta)
            for column, beta in zip(joined.columns[1:], coefficients[1:])
        },
        "residual_volatility": residual_sigma,
        "r_squared": float(r_squared),
    }


def run_institutional_scenario_suite(
    returns: pd.Series,
    *,
    factor_returns: pd.DataFrame | None = None,
    config: ScenarioConfig | None = None,
) -> dict[str, object]:
    config = config or ScenarioConfig()
    _validate_config(config)
    policy_assessment = _institutional_policy_assessment(config)
    strategy = pd.to_numeric(returns, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if len(strategy) < 30:
        raise ValueError("DATA REQUIRED: at least 30 observations for scenario generation")
    realized_volatility = float(strategy.std(ddof=1))
    if not np.isfinite(realized_volatility) or realized_volatility <= 0.0:
        raise ValueError("DATA INVALID: positive realized strategy volatility is required")

    availability: dict[str, dict[str, Any]] = {}

    def available(name: str, *, detail: str = "Calibrated from authoritative executed returns") -> None:
        availability[name] = {"state": "AVAILABLE", "reason": detail}

    def unavailable(name: str, exc: Exception) -> None:
        availability[name] = {"state": "UNAVAILABLE", "reason": str(exc)}

    availability["Institutional scenario policy"] = {
        "state": policy_assessment["state"],
        "reason": policy_assessment["reason"],
    }

    marginal: np.ndarray | None = None
    try:
        marginal, marginal_meta = marginal_student_t_paths(
            strategy,
            config,
            return_metadata=True,
        )
        available(
            "Marginal Student-t",
            detail="Univariate strategy marginal only; does not satisfy multivariate factor coverage",
        )
    except Exception as exc:
        unavailable("Marginal Student-t", exc)
        marginal_meta = {
            "status": "UNAVAILABLE",
            "reason": str(exc),
            "method": "univariate marginal Student-t",
        }

    factor_model: dict[str, Any]
    multi: np.ndarray | None = None
    try:
        if factor_returns is None or factor_returns.empty:
            raise ValueError(
                "DATA REQUIRED: Multivariate Student-t requires at least two aligned factor-return columns"
            )
        factor_frame = factor_returns.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
        if not factor_frame.columns.is_unique:
            raise ValueError("DATA INVALID: factor-return columns must be unique")
        if factor_frame.shape[1] < 2:
            raise ValueError(
                "DATA REQUIRED: Multivariate Student-t requires at least two aligned factor-return columns"
            )
        aligned = pd.concat([strategy.rename("__strategy__"), factor_frame], axis=1, join="inner").dropna()
        factor_history_coverage = float(len(aligned) / len(strategy)) if len(strategy) else 0.0
        if factor_history_coverage < 0.80:
            raise ValueError(
                f"DATA REQUIRED: aligned factor coverage {factor_history_coverage:.1%} is below 80.0%"
            )
        calibrated_factors = aligned.iloc[:, 1:]
        factor_paths, multivariate_meta = multivariate_student_t_paths(
            calibrated_factors,
            config,
            return_metadata=True,
        )
        multi, factor_model = _factor_strategy_paths(
            aligned.iloc[:, 0],
            calibrated_factors,
            factor_paths,
            config,
        )
        factor_model["history_coverage"] = factor_history_coverage
        available("Multivariate Student-t")
    except Exception as exc:
        unavailable("Multivariate Student-t", exc)
        multivariate_meta = {"status": "UNAVAILABLE", "reason": str(exc)}
        factor_model = {"status": "UNAVAILABLE", "reason": str(exc), "exposures": {}}

    regime: np.ndarray | None = None
    states = np.asarray([], dtype=int)
    try:
        regime, states, markov_meta = markov_regime_paths(strategy, config, return_metadata=True)
        available("Markov regime switching", detail="Observable-state calibrated proxy; not a latent HMM")
    except Exception as exc:
        unavailable("Markov regime switching", exc)
        markov_meta = {"status": "UNAVAILABLE", "reason": str(exc), "is_latent_hmm": False}

    evt: np.ndarray | None = None
    try:
        evt, evt_meta = empirical_evt_tail_paths(strategy, config)
        available("EVT empirical tail")
    except Exception as exc:
        unavailable("EVT empirical tail", exc)
        evt_meta = {"status": "UNAVAILABLE", "reason": str(exc), "method": "GPD peaks over threshold"}

    liquidity: np.ndarray | None = None
    try:
        liquidity = liquidity_spiral_paths(strategy, config)
        available("Liquidity spiral")
    except Exception as exc:
        unavailable("Liquidity spiral", exc)

    historical: np.ndarray | None = None
    try:
        historical = _circular_block_bootstrap_paths(
            strategy.to_numpy(dtype=float),
            paths=config.paths,
            horizon=config.horizon_days,
            block_length=config.historical_block_length,
            seed=config.seed + 4,
        )
        available("Historical bootstrap")
    except Exception as exc:
        unavailable("Historical bootstrap", exc)

    scenarios: dict[str, np.ndarray | None] = {
        "Historical bootstrap": historical,
        "Multivariate Student-t": multi,
        "Markov regime switching": regime,
        "EVT empirical tail": evt,
        "Liquidity spiral": liquidity,
    }
    rows = []
    for name, paths in scenarios.items():
        metrics = (
            _path_metrics(paths, config.confidence, config.target_drawdown)
            if isinstance(paths, np.ndarray) and paths.size
            else {
                "median_terminal_return": np.nan,
                "p05_terminal_return": np.nan,
                "expected_shortfall": np.nan,
                "median_max_drawdown": np.nan,
                "p05_max_drawdown": np.nan,
                "breach_probability": np.nan,
            }
        )
        rows.append({
            "scenario": name,
            **metrics,
        })
    summary = pd.DataFrame(rows).set_index("scenario")
    regime_mix = {
        "calm": float(np.mean(states == 0)) if len(states) else np.nan,
        "volatile": float(np.mean(states == 1)) if len(states) else np.nan,
        "crisis": float(np.mean(states == 2)) if len(states) else np.nan,
    }
    try:
        reverse = reverse_stress_multiplier(strategy, target_drawdown=config.target_drawdown)
    except Exception as exc:
        reverse = {"status": "UNAVAILABLE", "reason": str(exc), "target_drawdown": config.target_drawdown}
    return {
        "summary": summary,
        "paths": scenarios,
        "availability": availability,
        "reverse_stress": reverse,
        "evt": evt_meta,
        "regime_mix": regime_mix,
        "markov": markov_meta,
        "multivariate": multivariate_meta,
        "factor_model": factor_model,
        "marginal_student_t": {
            "metadata": marginal_meta,
            "metrics": (
                _path_metrics(marginal, config.confidence, config.target_drawdown)
                if isinstance(marginal, np.ndarray) and marginal.size
                else None
            ),
        },
        "historical_bootstrap": {
            "method": "circular moving-block bootstrap",
            "block_length": int(min(config.historical_block_length, len(strategy), config.horizon_days)),
            "observations": int(len(strategy)),
        },
        "config": config,
        "policy": policy_assessment,
        "institutional_eligible": all(
            isinstance(item, dict) and item.get("state") == "AVAILABLE"
            for item in availability.values()
        ),
        "seed": config.seed,
    }
