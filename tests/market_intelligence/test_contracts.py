from __future__ import annotations

from datetime import datetime, timezone

import pytest

from market_intelligence.contracts import (
    AvailabilityStatus,
    ForecastDistribution,
    MicrostructureSnapshot,
    as_utc,
)


UTC = timezone.utc


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        as_utc(datetime(2026, 1, 1))


def test_forecast_requires_monotone_quantiles_and_safe_cutoff() -> None:
    with pytest.raises(ValueError, match="monotone"):
        ForecastDistribution(
            symbol="NVDA",
            as_of=datetime(2026, 1, 1, tzinfo=UTC),
            horizon="1h",
            p_up=0.5,
            expected_return=0.0,
            q05=-0.01,
            q25=0.01,
            q50=0.0,
            q75=0.02,
            q95=0.03,
            expected_volatility=0.01,
            jump_probability=0.1,
            calibration_status="UNCALIBRATED",
            model_id="test",
            model_version="1",
            feature_set_version="1",
            data_cutoff=datetime(2026, 1, 1, tzinfo=UTC),
            provider_status=AvailabilityStatus.SIMULATED,
            regime_state="test",
            uncertainty_flags=("RESEARCH_ONLY",),
        )


def test_l1_contract_rejects_l2_only_metrics() -> None:
    with pytest.raises(ValueError, match="L2/L3"):
        MicrostructureSnapshot(
            symbol="NVDA",
            as_of=datetime(2026, 1, 1, tzinfo=UTC),
            window="1m",
            schema_level="L1",
            provider_status=AvailabilityStatus.RESEARCH_ONLY,
            best_bid=100.0,
            best_ask=100.1,
            bid_size=10.0,
            ask_size=10.0,
            mid=100.05,
            microprice=100.05,
            spread=0.1,
            ofi=0.0,
            queue_imbalance=0.0,
            bid_replenishment=0.5,
        )
