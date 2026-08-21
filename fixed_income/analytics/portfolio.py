"""Transparent constrained optimizer for fixed-income portfolios."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Any, Sequence

import numpy as np
import pandas as pd

from fixed_income.contracts import validate_weight_bounds


REQUIRED_COLUMNS = (
    "identifier",
    "issuer",
    "sector",
    "rating",
    "expected_return_pct",
    "volatility_pct",
    "current_weight_pct",
    "min_weight_pct",
    "max_weight_pct",
    "duration",
    "spread_duration",
    "expected_loss_bp",
    "liquidity_score",
)


@dataclass(frozen=True)
class OptimizerConfig:
    objective: str = "Risk-adjusted"
    risk_aversion: float = 6.0
    turnover_cost_bp: float = 15.0
    sector_cap_pct: float = 35.0
    nav: float = 100_000_000.0
    iterations: int = 900

    def __post_init__(self) -> None:
        if self.objective not in {"Risk-adjusted", "Equal risk", "Carry / quality blend"}:
            raise ValueError("unsupported objective")
        if self.risk_aversion <= 0.0:
            raise ValueError("risk_aversion must be positive")
        if self.turnover_cost_bp < 0.0:
            raise ValueError("turnover_cost_bp cannot be negative")
        if not 0.0 < self.sector_cap_pct <= 100.0:
            raise ValueError("sector_cap_pct must be in (0, 100]")
        if self.nav <= 0.0:
            raise ValueError("nav must be positive")
        if self.iterations < 1:
            raise ValueError("iterations must be positive")


def project_bounded_simplex(
    values: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
) -> np.ndarray:
    """Project approximately onto a fully-invested bounded simplex."""
    weights = np.clip(np.asarray(values, dtype=float), lower, upper)
    for _ in range(200):
        residual = 1.0 - float(weights.sum())
        if abs(residual) < 1e-10:
            break
        slack = (upper - weights) if residual > 0 else (weights - lower)
        available = float(np.maximum(slack, 0.0).sum())
        if available <= 1e-12:
            break
        weights = weights + residual * np.maximum(slack, 0.0) / available
        weights = np.clip(weights, lower, upper)
    return weights


def apply_sector_cap(
    weights: np.ndarray,
    sectors: Sequence[str],
    lower: np.ndarray,
    upper: np.ndarray,
    sector_cap: float,
) -> np.ndarray:
    """Enforce a uniform sector cap while preserving individual bounds."""
    weights = project_bounded_simplex(weights, lower, upper)
    sector_array = np.asarray(list(sectors), dtype=object)
    for _ in range(80):
        changed = False
        for sector in pd.unique(sector_array):
            index = np.where(sector_array == sector)[0]
            total = float(weights[index].sum())
            if total > sector_cap + 1e-10:
                excess = total - sector_cap
                adjustable = np.maximum(weights[index] - lower[index], 0.0)
                if adjustable.sum() > 0.0:
                    weights[index] -= excess * adjustable / adjustable.sum()
                outside = np.where(sector_array != sector)[0]
                slack = np.maximum(upper[outside] - weights[outside], 0.0)
                if slack.sum() > 0.0:
                    weights[outside] += excess * slack / slack.sum()
                changed = True
        weights = project_bounded_simplex(weights, lower, upper)
        if not changed:
            break
    return weights


def build_correlation(universe: pd.DataFrame) -> pd.DataFrame:
    """Build the documented market, sector and duration-kernel correlation."""
    sectors = universe["sector"].fillna("Unclassified").astype(str).to_numpy()
    duration = pd.to_numeric(universe["duration"], errors="coerce").fillna(0.0).to_numpy(float)
    same_sector = (sectors[:, None] == sectors[None, :]).astype(float)
    duration_kernel = np.exp(-np.abs(duration[:, None] - duration[None, :]) / 4.0)
    correlation = 0.15 + 0.25 * same_sector + 0.20 * duration_kernel
    np.fill_diagonal(correlation, 1.0)
    return pd.DataFrame(correlation, index=universe["identifier"], columns=universe["identifier"])


def optimize_portfolio(
    universe: pd.DataFrame,
    objective: str = "Risk-adjusted",
    risk_aversion: float = 6.0,
    turnover_cost_bp: float = 15.0,
    sector_cap_pct: float = 35.0,
    nav: float = 100_000_000.0,
) -> dict[str, Any]:
    """Optimize a long-only credit portfolio with auditable constraints."""
    config = OptimizerConfig(
        objective=objective,
        risk_aversion=float(risk_aversion),
        turnover_cost_bp=float(turnover_cost_bp),
        sector_cap_pct=float(sector_cap_pct),
        nav=float(nav),
    )
    work = pd.DataFrame(universe).copy()
    missing = [column for column in REQUIRED_COLUMNS if column not in work.columns]
    if missing:
        return {"errors": ["Missing columns: " + ", ".join(missing)]}

    for column in REQUIRED_COLUMNS[4:]:
        work[column] = pd.to_numeric(work[column], errors="coerce")
    work = work.dropna(subset=["identifier", "expected_return_pct", "volatility_pct"]).reset_index(drop=True)
    if work.empty:
        return {"errors": ["No valid assets after numeric validation."]}

    lower = work["min_weight_pct"].fillna(0.0).to_numpy(float) / 100.0
    upper = work["max_weight_pct"].fillna(100.0).to_numpy(float) / 100.0
    bounds_report = validate_weight_bounds(lower, upper)
    if not bounds_report.ok:
        return {"errors": [issue.message for issue in bounds_report.issues if issue.severity == "ERROR"]}

    sector_cap = config.sector_cap_pct / 100.0
    work["sector"] = work["sector"].fillna("Unclassified").astype(str)
    sector_lower = work.assign(_lower=lower).groupby("sector")["_lower"].sum()
    if (sector_lower > sector_cap + 1e-9).any():
        return {"errors": ["Infeasible sector cap relative to minimum weights."]}

    mu = work["expected_return_pct"].to_numpy(float) / 100.0
    vol = np.maximum(work["volatility_pct"].to_numpy(float) / 100.0, 0.0001)
    if not np.isfinite(mu).all() or not np.isfinite(vol).all():
        return {"errors": ["Expected returns and volatility must be finite."]}

    sectors = work["sector"].to_numpy()
    correlation_frame = build_correlation(work)
    correlation = correlation_frame.to_numpy(float)
    covariance = np.outer(vol, vol) * correlation
    eigenvalues = np.linalg.eigvalsh(covariance)
    if float(eigenvalues.min()) < -1e-10:
        return {"errors": ["Covariance matrix is not positive semidefinite."]}

    current = work["current_weight_pct"].fillna(0.0).to_numpy(float) / 100.0
    current = apply_sector_cap(current, sectors, lower, upper, sector_cap)

    if config.objective == "Equal risk":
        candidate = 1.0 / vol
        candidate = candidate / candidate.sum()
    elif config.objective == "Carry / quality blend":
        liquidity = work["liquidity_score"].fillna(50.0).to_numpy(float)
        expected_loss = work["expected_loss_bp"].fillna(0.0).to_numpy(float) / 10_000.0
        score = 2.0 * mu - expected_loss + 0.002 * (liquidity - 50.0) - 0.25 * vol
        score = score - np.nanmax(score)
        candidate = np.exp(np.clip(score * 30.0, -40.0, 40.0))
        candidate = candidate / candidate.sum()
    else:
        candidate = current.copy()
        cost = config.turnover_cost_bp / 10_000.0
        for iteration in range(config.iterations):
            gradient = (
                mu
                - config.risk_aversion * (covariance @ candidate)
                - cost * np.sign(candidate - current)
            )
            step = 0.45 / np.sqrt(iteration + 8.0)
            candidate = candidate + step * gradient
            candidate = apply_sector_cap(candidate, sectors, lower, upper, sector_cap)

    weights = apply_sector_cap(candidate, sectors, lower, upper, sector_cap)
    if abs(float(weights.sum()) - 1.0) > 1e-7:
        return {"errors": ["Fully-invested constraint could not be satisfied."]}
    if any(float(weights[sectors == sector].sum()) > sector_cap + 1e-6 for sector in pd.unique(sectors)):
        return {"errors": ["Sector constraints could not be satisfied with the supplied bounds."]}

    portfolio_return = float(weights @ mu)
    variance = float(weights @ covariance @ weights)
    portfolio_vol = sqrt(max(variance, 0.0))
    marginal = covariance @ weights
    component_risk = weights * marginal
    risk_contribution = component_risk / variance if variance > 0.0 else np.zeros_like(weights)
    turnover = 0.5 * float(np.abs(weights - current).sum())
    expected_loss = float(
        weights @ (work["expected_loss_bp"].fillna(0.0).to_numpy(float) / 10_000.0)
    )

    table = work.copy()
    table["optimized_weight_pct"] = weights * 100.0
    table["trade_weight_pct"] = (weights - current) * 100.0
    table["trade_amount"] = (weights - current) * config.nav
    table["risk_contribution_pct"] = risk_contribution * 100.0
    table["active_return_contribution_bp"] = (weights - current) * mu * 10_000.0

    sector_table = table.groupby("sector", as_index=False).agg(
        current_weight_pct=("current_weight_pct", "sum"),
        optimized_weight_pct=("optimized_weight_pct", "sum"),
        expected_return_pct=("expected_return_pct", "mean"),
        expected_loss_bp=("expected_loss_bp", "mean"),
    )
    sector_table["cap_pct"] = config.sector_cap_pct
    sector_table["headroom_pct"] = sector_table["cap_pct"] - sector_table["optimized_weight_pct"]

    metrics = {
        "expected_return_pct": portfolio_return * 100.0,
        "volatility_pct": portfolio_vol * 100.0,
        "return_to_risk": portfolio_return / portfolio_vol if portfolio_vol > 0.0 else np.nan,
        "duration": float(weights @ work["duration"].fillna(0.0).to_numpy(float)),
        "spread_duration": float(weights @ work["spread_duration"].fillna(0.0).to_numpy(float)),
        "expected_loss_bp": expected_loss * 10_000.0,
        "turnover_pct": turnover * 100.0,
        "hhi": float(np.sum(weights ** 2)),
        "estimated_cost": turnover * config.nav * config.turnover_cost_bp / 10_000.0,
        "covariance_min_eigenvalue": float(eigenvalues.min()),
    }
    return {
        "errors": [],
        "assets": table,
        "sectors": sector_table,
        "metrics": metrics,
        "correlation": correlation_frame,
        "covariance": covariance,
        "config": config,
    }
