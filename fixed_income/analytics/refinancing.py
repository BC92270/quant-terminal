"""Refinancing-wall analytics with explicit unit conventions."""

from __future__ import annotations

from math import isfinite
from typing import Any

import numpy as np
import pandas as pd


REQUIRED_COLUMNS = (
    "year",
    "debt_due",
    "coupon_pct",
    "benchmark_pct",
    "current_spread_bp",
    "refi_spread_bp",
    "secured_pct",
)


def analyze_refinancing_schedule(
    schedule: pd.DataFrame,
    cash: float = 0.0,
    revolver: float = 0.0,
    annual_fcf: float = 0.0,
    as_of_year: int | None = None,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Return normalized debt-wall rows and liquidity/refinancing metrics.

    Rate fields ending in _pct are percentage points. Spread fields ending in
    _bp are basis points. Monetary inputs and outputs use one common currency.
    """
    work = pd.DataFrame(schedule).copy()
    for column in REQUIRED_COLUMNS:
        if column not in work.columns:
            work[column] = 0.0
        work[column] = pd.to_numeric(work[column], errors="coerce").fillna(0.0)

    if (work["debt_due"] < 0.0).any():
        raise ValueError("debt_due cannot be negative")
    for column in ("coupon_pct", "benchmark_pct", "current_spread_bp", "refi_spread_bp", "secured_pct"):
        values = work[column].to_numpy(float)
        if not np.isfinite(values).all():
            raise ValueError(f"{column} must contain finite values")
    if not work["secured_pct"].between(0.0, 100.0).all():
        raise ValueError("secured_pct must be between 0 and 100")

    work = work.sort_values("year").reset_index(drop=True)
    work["refi_rate_pct"] = work["benchmark_pct"] + work["refi_spread_bp"] / 100.0
    work["current_interest"] = work["debt_due"] * work["coupon_pct"] / 100.0
    work["refi_interest"] = work["debt_due"] * work["refi_rate_pct"] / 100.0
    work["incremental_interest"] = work["refi_interest"] - work["current_interest"]
    work["cumulative_debt_due"] = work["debt_due"].cumsum()

    current_year = int(as_of_year or pd.Timestamp.today().year)
    next_24m = float(work.loc[work["year"] <= current_year + 2, "debt_due"].sum())
    sources = max(_finite(cash), 0.0) + max(_finite(revolver), 0.0) + 2.0 * max(_finite(annual_fcf), 0.0)
    total = float(work["debt_due"].sum())
    weighted_maturity = (
        float(np.average(work["year"] - current_year, weights=work["debt_due"]))
        if total > 0.0
        else np.nan
    )
    metrics = {
        "total_debt_due": total,
        "next_24m_debt": next_24m,
        "liquidity_sources": sources,
        "liquidity_coverage_24m": sources / next_24m if next_24m > 0.0 else np.nan,
        "incremental_interest": float(work["incremental_interest"].sum()),
        "weighted_maturity_years": weighted_maturity,
    }
    return work, metrics


def refinancing_cost_surface(
    debt_due: float,
    rate_shocks_bp: list[float],
    spread_shocks_bp: list[float],
) -> pd.DataFrame:
    """Return annual interest-cost deltas for a rate by spread shock grid."""
    debt = max(_finite(debt_due), 0.0)
    rates = np.asarray(rate_shocks_bp, dtype=float)
    spreads = np.asarray(spread_shocks_bp, dtype=float)
    if not np.isfinite(rates).all() or not np.isfinite(spreads).all():
        raise ValueError("shock grids must be finite")
    values = debt * (spreads[:, None] + rates[None, :]) / 10_000.0
    return pd.DataFrame(values, index=spreads, columns=rates)


def _finite(value: Any) -> float:
    number = float(value)
    if not isfinite(number):
        raise ValueError("monetary inputs must be finite")
    return number
