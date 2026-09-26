from __future__ import annotations

from datetime import datetime, timezone

import pytest

from market_intelligence.data import assert_cutoff, latest_known_at, relationship_valid_at, tradable_time


UTC = timezone.utc


def test_latest_consensus_never_selects_future_revision() -> None:
    records = [
        {"value": 100, "available_at": "2026-01-01T12:00:00Z", "revision_id": "r1"},
        {"value": 102, "available_at": "2026-01-01T13:00:00Z", "revision_id": "r2"},
    ]
    selected = latest_known_at(records, "2026-01-01T12:30:00Z")
    assert selected is not None
    assert selected["value"] == 100


def test_same_time_revision_selection_is_numeric_safe_and_input_order_independent() -> None:
    records = [
        {"value": "second", "available_at": "2026-01-01T12:00:00Z", "revision_id": "r2"},
        {"value": "tenth", "available_at": "2026-01-01T12:00:00Z", "revision_id": "r10"},
    ]
    assert latest_known_at(records, "2026-01-01T12:00:00Z")["value"] == "tenth"
    assert latest_known_at(reversed(records), "2026-01-01T12:00:00Z")["value"] == "tenth"


def test_cutoff_rejects_future_feature() -> None:
    with pytest.raises(ValueError, match="not point-in-time safe"):
        assert_cutoff("2026-01-01T12:01:00Z", "2026-01-01T12:00:00Z", label="consensus")


def test_tradable_time_uses_later_publication_or_first_seen() -> None:
    result = tradable_time("2026-01-01T12:00:00Z", "2026-01-01T12:00:03Z")
    assert result == datetime(2026, 1, 1, 12, 0, 3, tzinfo=UTC)


def test_relationship_interval_is_left_closed_right_open() -> None:
    edge = {"valid_from": "2026-01-01T00:00:00Z", "valid_to": "2026-02-01T00:00:00Z"}
    assert relationship_valid_at(edge, "2026-01-01T00:00:00Z")
    assert not relationship_valid_at(edge, "2026-02-01T00:00:00Z")
