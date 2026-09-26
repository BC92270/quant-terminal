from __future__ import annotations

from datetime import datetime, timedelta, timezone

from market_intelligence.contracts import AvailabilityStatus, ProviderHealth
from market_intelligence.data.quality import (
    FreshnessRule,
    QualityPolicy,
    QualityState,
    assess_provider_quality,
)


UTC = timezone.utc
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
POLICY = QualityPolicy("test", (FreshnessRule("feed", timedelta(seconds=30)),))


def _provider(status: AvailabilityStatus, as_of: datetime = NOW) -> ProviderHealth:
    return ProviderHealth("feed", status, as_of)


def test_simulation_never_becomes_current_even_when_timestamp_is_fresh() -> None:
    result = assess_provider_quality(
        _provider(AvailabilityStatus.SIMULATED),
        evaluated_at=NOW,
        policy=POLICY,
        completeness=1.0,
    )
    assert result.state == QualityState.SIMULATED
    assert result.blocking


def test_freshness_policy_distinguishes_current_stale_and_future() -> None:
    current = assess_provider_quality(
        _provider(AvailabilityStatus.LIVE), evaluated_at=NOW, policy=POLICY, completeness=1.0
    )
    stale = assess_provider_quality(
        _provider(AvailabilityStatus.LIVE, NOW - timedelta(seconds=31)),
        evaluated_at=NOW,
        policy=POLICY,
        completeness=1.0,
    )
    future = assess_provider_quality(
        _provider(AvailabilityStatus.LIVE, NOW + timedelta(seconds=1)),
        evaluated_at=NOW,
        policy=POLICY,
        completeness=1.0,
    )
    assert current.state == QualityState.CURRENT
    assert stale.state == QualityState.STALE
    assert future.state == QualityState.INVALID


def test_required_live_layer_without_completeness_evidence_fails_closed() -> None:
    result = assess_provider_quality(
        _provider(AvailabilityStatus.LIVE), evaluated_at=NOW, policy=POLICY
    )
    assert result.state == QualityState.INVALID
    assert result.blocking
    assert "COMPLETENESS_NOT_ASSERTED" in result.flags
