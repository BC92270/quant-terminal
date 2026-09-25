from __future__ import annotations

import pytest

from market_intelligence.events import novelty_score, standardized_surprise
from market_intelligence.microstructure import microprice, order_flow_imbalance, queue_imbalance, trade_imbalance


def test_queue_imbalance_boundaries_and_empty_depth() -> None:
    assert queue_imbalance(10, 0) == 1.0
    assert queue_imbalance(0, 10) == -1.0
    assert queue_imbalance(10, 10) == 0.0
    assert queue_imbalance(0, 0) is None


def test_microprice_stays_inside_spread() -> None:
    value = microprice(100.0, 101.0, 30.0, 10.0)
    assert value is not None
    assert 100.0 <= value <= 101.0
    assert value == pytest.approx(100.75)


def test_cont_style_ofi_on_hand_built_quote_sequence() -> None:
    quotes = [
        {"best_bid": 100.0, "best_ask": 101.0, "bid_size": 10.0, "ask_size": 12.0},
        {"best_bid": 100.0, "best_ask": 101.0, "bid_size": 15.0, "ask_size": 9.0},
        {"best_bid": 101.0, "best_ask": 102.0, "bid_size": 20.0, "ask_size": 8.0},
    ]
    assert order_flow_imbalance(quotes) == pytest.approx(37.0)


def test_trade_imbalance() -> None:
    assert trade_imbalance(75, 25) == pytest.approx(0.5)
    assert trade_imbalance(0, 0) is None


def test_surprise_is_zero_at_consensus_and_blocks_future_consensus() -> None:
    raw, z_score = standardized_surprise(
        100,
        100,
        5,
        consensus_available_at="2026-01-01T11:59:00Z",
        event_tradable_at="2026-01-01T12:00:00Z",
    )
    assert raw == 0
    assert z_score == 0
    with pytest.raises(ValueError):
        standardized_surprise(
            101,
            100,
            5,
            consensus_available_at="2026-01-01T12:01:00Z",
            event_tradable_at="2026-01-01T12:00:00Z",
        )


def test_novelty_ignores_future_documents() -> None:
    prior = [
        {"known_at": "2026-01-01T11:00:00Z", "entity": "NVDA", "topic": "earnings", "embedding": [1.0, 0.0]},
        {"known_at": "2026-01-01T13:00:00Z", "entity": "NVDA", "topic": "earnings", "embedding": [0.0, 1.0]},
    ]
    assert novelty_score([1.0, 0.0], prior, as_of="2026-01-01T12:00:00Z", entity="NVDA", topic="earnings") == pytest.approx(0.0)
    assert novelty_score([0.0, 1.0], prior, as_of="2026-01-01T12:00:00Z", entity="NVDA", topic="earnings") == pytest.approx(1.0)
