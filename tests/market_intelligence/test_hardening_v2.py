from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import numpy as np
import pytest

from market_intelligence.contracts import AvailabilityStatus, MicrostructureSnapshot
from market_intelligence.demo import build_workspace_snapshot
from market_intelligence.models import empirical_distribution_forecasts


UTC = timezone.utc


@pytest.mark.parametrize(
    "updates, message",
    [
        ({"bid_size": -1.0}, "bid_size cannot be negative"),
        ({"spread": 99.0}, "spread must equal"),
        ({"mid": 99.0}, "mid must equal"),
    ],
)
def test_microstructure_contract_rejects_incoherent_quotes(updates: dict[str, float], message: str) -> None:
    valid = MicrostructureSnapshot(
        symbol="NVDA",
        as_of=datetime(2026, 1, 1, tzinfo=UTC),
        window="1m",
        schema_level="L1",
        provider_status=AvailabilityStatus.RESEARCH_ONLY,
        best_bid=100.0,
        best_ask=101.0,
        bid_size=10.0,
        ask_size=12.0,
        mid=100.5,
        microprice=100.45,
        spread=1.0,
        ofi=0.0,
        queue_imbalance=0.0,
    )
    with pytest.raises(ValueError, match=message):
        replace(valid, **updates)


def test_forecast_contract_rejects_negative_volatility() -> None:
    forecast = build_workspace_snapshot("NVDA").forecasts[0]
    with pytest.raises(ValueError, match="expected_volatility cannot be negative"):
        replace(forecast, expected_volatility=-0.01)


@pytest.mark.parametrize("prices", [[100.0, np.nan, 101.0], [100.0, np.inf, 101.0], [100.0, 0.0, 101.0]])
def test_empirical_baseline_rejects_invalid_price_history(prices: list[float]) -> None:
    with pytest.raises(ValueError):
        empirical_distribution_forecasts(
            "NVDA",
            prices,
            as_of="2026-01-01T12:00:00Z",
            horizons=(("1m", 1),),
            provider_status=AvailabilityStatus.RESEARCH_ONLY,
        )


def test_empirical_baseline_preserves_explicit_data_cutoff() -> None:
    result = empirical_distribution_forecasts(
        "NVDA",
        [100.0, 101.0, 102.0],
        as_of="2026-01-01T12:00:00Z",
        data_cutoff="2026-01-01T11:59:00Z",
        horizons=(("1m", 1),),
        provider_status=AvailabilityStatus.RESEARCH_ONLY,
    )
    assert result[0].data_cutoff.isoformat() == "2026-01-01T11:59:00+00:00"
    assert "CUTOFF_ASSUMED_AS_OF" not in result[0].uncertainty_flags
