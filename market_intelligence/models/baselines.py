"""Empirical, auditable distribution forecasts used as Level-0 baselines."""

from __future__ import annotations

from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

from ..contracts import AvailabilityStatus, ForecastDistribution, as_utc


def _prices(values: Any) -> pd.Series:
    if isinstance(values, pd.DataFrame):
        candidates = {str(column).casefold(): column for column in values.columns}
        column = candidates.get("close") or candidates.get("price") or candidates.get("last")
        if column is None:
            raise ValueError("Price frame requires Close, price, or Last")
        series = values[column]
    else:
        series = pd.Series(values)
    result = pd.to_numeric(series, errors="coerce").astype(float)
    if result.empty:
        raise ValueError("No prices available")
    if result.isna().any():
        raise ValueError("Price history contains missing or non-numeric observations")
    if not np.isfinite(result.to_numpy(dtype=float)).all():
        raise ValueError("Price history must contain only finite observations")
    if (result <= 0.0).any():
        raise ValueError("Price history must contain only positive observations")
    return result


def empirical_distribution_forecasts(
    symbol: str,
    price_values: Any,
    *,
    as_of: Any,
    horizons: Sequence[tuple[str, int]],
    provider_status: AvailabilityStatus,
    data_cutoff: Any | None = None,
    regime_state: str = "fixture_conflict",
    primary_drivers: Iterable[str] = (),
) -> tuple[ForecastDistribution, ...]:
    """Build unconditional empirical distributions from trailing prices.

    This is explicitly a Level-0 benchmark, not a catalyst-conditioned alpha
    model.  It is marked uncalibrated until walk-forward outcomes exist.
    """

    prices = _prices(price_values)
    prediction_time = as_utc(as_of)
    cutoff = prediction_time if data_cutoff is None else as_utc(data_cutoff)
    if cutoff > prediction_time:
        raise ValueError("data_cutoff cannot be after as_of")
    cutoff_assumed = data_cutoff is None
    outputs: list[ForecastDistribution] = []
    seen_labels: set[str] = set()
    for label, steps in horizons:
        horizon_label = str(label).strip()
        if not horizon_label:
            raise ValueError("Forecast horizon label cannot be empty")
        if horizon_label in seen_labels:
            raise ValueError(f"Duplicate forecast horizon: {horizon_label}")
        seen_labels.add(horizon_label)
        if isinstance(steps, bool) or int(steps) != steps or int(steps) <= 0:
            raise ValueError("Forecast horizon steps must be positive")
        returns = prices.pct_change(int(steps)).replace([np.inf, -np.inf], np.nan).dropna()
        sample_size = int(len(returns))
        flags = ["RESEARCH_ONLY", "UNCALIBRATED", "NOT_CATALYST_CONDITIONED"]
        if cutoff_assumed:
            flags.append("CUTOFF_ASSUMED_AS_OF")
        if provider_status == AvailabilityStatus.SIMULATED:
            flags.append("SIMULATED_INPUT")
        if sample_size < 12:
            flags.append("LOW_SAMPLE")
        if sample_size == 0:
            values = dict(
                p_up=None, expected_return=None, q05=None, q25=None, q50=None,
                q75=None, q95=None, expected_volatility=None, jump_probability=None,
            )
        else:
            quantiles = returns.quantile([0.05, 0.25, 0.50, 0.75, 0.95]).to_numpy(dtype=float)
            volatility = float(returns.std(ddof=1)) if sample_size > 1 else 0.0
            jump_threshold = 2.0 * volatility
            jump_probability = (
                float((returns.abs() > jump_threshold).mean())
                if jump_threshold > 0.0
                else 0.0
            )
            values = dict(
                p_up=float((returns > 0.0).mean()),
                expected_return=float(returns.mean()),
                q05=float(quantiles[0]), q25=float(quantiles[1]), q50=float(quantiles[2]),
                q75=float(quantiles[3]), q95=float(quantiles[4]),
                expected_volatility=volatility,
                jump_probability=jump_probability,
            )
        outputs.append(
            ForecastDistribution(
                symbol=str(symbol).upper(),
                as_of=prediction_time,
                horizon=horizon_label,
                calibration_status="RESEARCH_ONLY · NOT CALIBRATED",
                model_id="EMPIRICAL_DISTRIBUTION_BASELINE",
                model_version="1.0.0",
                feature_set_version="price-returns-1.0.0",
                data_cutoff=cutoff,
                provider_status=provider_status,
                regime_state=regime_state,
                primary_drivers=tuple(primary_drivers),
                uncertainty_flags=tuple(flags),
                sample_size=sample_size,
                **values,
            )
        )
    return tuple(outputs)
