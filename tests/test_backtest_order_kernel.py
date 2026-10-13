from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from backtest_universal import (
    InvalidOrderTransition,
    MarketSnapshot,
    OrderEventKind,
    OrderKernel,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)


UTC = timezone.utc
T0 = datetime(2025, 1, 2, 14, 30, tzinfo=UTC)


def _request(**overrides: object) -> OrderRequest:
    values: dict[str, object] = {
        "symbol": "spy",
        "side": OrderSide.BUY,
        "order_type": OrderType.LIMIT,
        "quantity": 10,
        "submitted_at": T0,
        "time_in_force": TimeInForce.GTC,
        "limit_price": 100,
    }
    values.update(overrides)
    return OrderRequest(**values)  # type: ignore[arg-type]


def _quote(
    at: datetime,
    *,
    bid: object = 99,
    ask: object = 100,
    bid_size: object | None = 100,
    ask_size: object | None = 100,
    sequence: int = 1,
) -> MarketSnapshot:
    return MarketSnapshot(
        "SPY",
        at,
        bid=bid,
        ask=ask,
        bid_size=bid_size,
        ask_size=ask_size,
        source_sequence=sequence,
    )


def test_order_request_validates_prices_timestamps_and_day_expiry() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _request(submitted_at=datetime(2025, 1, 2), limit_price=100)
    with pytest.raises(ValueError, match="LIMIT orders require only"):
        _request(limit_price=None)
    with pytest.raises(ValueError, match="MARKET orders cannot"):
        _request(order_type="MARKET", limit_price=100)
    with pytest.raises(ValueError, match="DAY orders require"):
        _request(time_in_force="DAY")
    with pytest.raises(ValueError, match="STOP orders do not support"):
        _request(
            order_type="STOP",
            limit_price=None,
            stop_price=101,
            time_in_force="IOC",
        )
    valid = _request(
        time_in_force="DAY",
        expires_at=T0 + timedelta(hours=6),
        quantity="10.250",
    )
    assert valid.symbol == "SPY"
    assert valid.quantity == Decimal("10.250")


def test_submission_and_event_ids_are_deterministic() -> None:
    def run() -> tuple[object, ...]:
        kernel = OrderKernel()
        order = kernel.submit(_request())
        kernel.process_snapshot(_quote(T0 + timedelta(seconds=1)))
        return order.order_id, kernel.events, kernel.fills

    first = run()
    second = run()
    assert first == second
    assert first[0] == "O000000000001"
    assert [event.kind for event in first[1]] == [
        OrderEventKind.SUBMITTED,
        OrderEventKind.ACCEPTED,
        OrderEventKind.FILLED,
    ]
    assert first[2][0].fill_id == "F000000000001"


def test_market_order_partial_fills_and_weighted_average_are_exact() -> None:
    kernel = OrderKernel()
    order = kernel.submit(
        _request(order_type="MARKET", limit_price=None, quantity=10)
    )
    first = kernel.process_snapshot(
        _quote(T0 + timedelta(seconds=1), ask="100.10", ask_size=4)
    )
    assert first[0].quantity == Decimal("4")
    assert kernel.get(order.order_id).status is OrderStatus.PARTIALLY_FILLED
    second = kernel.process_snapshot(
        _quote(
            T0 + timedelta(seconds=2),
            ask="100.30",
            ask_size=6,
            sequence=2,
        )
    )
    assert second[0].quantity == Decimal("6")
    final = kernel.get(order.order_id)
    assert final.status is OrderStatus.FILLED
    assert final.average_fill_price == Decimal("100.22")
    assert final.remaining_quantity == 0


def test_limit_orders_use_price_time_priority_and_consume_visible_size() -> None:
    kernel = OrderKernel()
    first = kernel.submit(_request(order_id="FIRST", quantity=4, limit_price=101))
    second = kernel.submit(_request(order_id="SECOND", quantity=4, limit_price=101))
    fills = kernel.process_snapshot(
        _quote(T0 + timedelta(seconds=1), ask=100, ask_size=6)
    )
    assert [(fill.order_id, fill.quantity, fill.price) for fill in fills] == [
        ("FIRST", Decimal("4"), Decimal("100")),
        ("SECOND", Decimal("2"), Decimal("100")),
    ]
    assert kernel.get(first.order_id).status is OrderStatus.FILLED
    assert kernel.get(second.order_id).status is OrderStatus.PARTIALLY_FILLED


def test_sell_limit_and_last_trade_matching_have_signed_fills() -> None:
    kernel = OrderKernel()
    order = kernel.submit(
        _request(side="SELL", quantity=3, limit_price=101)
    )
    no_fill = kernel.process_snapshot(
        _quote(T0 + timedelta(seconds=1), bid=100, ask=101, sequence=1)
    )
    assert not no_fill
    fills = kernel.process_snapshot(
        MarketSnapshot(
            "SPY",
            T0 + timedelta(seconds=2),
            last=Decimal("101.25"),
            last_size=3,
            source_sequence=2,
        )
    )
    assert fills[0].signed_quantity == Decimal("-3")
    assert fills[0].price == Decimal("101.25")
    assert kernel.get(order.order_id).status is OrderStatus.FILLED


def test_stop_and_stop_limit_trigger_once_then_follow_effective_order_type() -> None:
    kernel = OrderKernel()
    stop = kernel.submit(
        _request(
            order_id="STOP",
            order_type="STOP",
            limit_price=None,
            stop_price=102,
            quantity=2,
        )
    )
    stop_limit = kernel.submit(
        _request(
            order_id="STOP_LIMIT",
            order_type="STOP_LIMIT",
            stop_price=102,
            limit_price="102.25",
            quantity=2,
        )
    )
    assert not kernel.process_snapshot(
        _quote(T0 + timedelta(seconds=1), bid=100, ask=101, sequence=1)
    )
    fills = kernel.process_snapshot(
        MarketSnapshot(
            "SPY",
            T0 + timedelta(seconds=2),
            bid=Decimal("102.00"),
            ask=Decimal("102.20"),
            last=Decimal("102.10"),
            bid_size=10,
            ask_size=3,
            last_size=10,
            source_sequence=2,
        )
    )
    assert [(fill.order_id, fill.quantity) for fill in fills] == [
        (stop.order_id, Decimal("2")),
        (stop_limit.order_id, Decimal("1")),
    ]
    triggered = [event.order_id for event in kernel.events if event.kind is OrderEventKind.TRIGGERED]
    assert triggered == ["STOP", "STOP_LIMIT"]
    assert kernel.get("STOP_LIMIT").status is OrderStatus.PARTIALLY_FILLED


def test_ioc_fills_available_quantity_then_cancels_remainder() -> None:
    kernel = OrderKernel()
    order = kernel.submit(_request(quantity=10, time_in_force="IOC"))
    fills = kernel.process_snapshot(
        _quote(T0 + timedelta(seconds=1), ask=100, ask_size=3)
    )
    assert fills[0].quantity == Decimal("3")
    final = kernel.get(order.order_id)
    assert final.status is OrderStatus.CANCELED
    assert final.filled_quantity == Decimal("3")
    assert kernel.events[-1].reason == "IOC_REMAINDER_CANCELED"


def test_fok_is_all_or_none_and_does_not_consume_liquidity_on_failure() -> None:
    kernel = OrderKernel()
    failed = kernel.submit(
        _request(order_id="FOK-FAIL", quantity=6, time_in_force="FOK")
    )
    succeeds = kernel.submit(
        _request(order_id="FOK-OK", quantity=5, time_in_force="FOK")
    )
    fills = kernel.process_snapshot(
        _quote(T0 + timedelta(seconds=1), ask=100, ask_size=5)
    )
    assert kernel.get(failed.order_id).status is OrderStatus.CANCELED
    assert [(fill.order_id, fill.quantity) for fill in fills] == [
        (succeeds.order_id, Decimal("5"))
    ]


def test_cancel_reject_and_terminal_transition_guards() -> None:
    kernel = OrderKernel()
    canceled = kernel.submit(_request(order_id="CANCEL"))
    rejected = kernel.submit(_request(order_id="REJECT"))
    assert kernel.cancel(canceled.order_id, at=T0, reason="USER").status is OrderStatus.CANCELED
    assert kernel.reject(rejected.order_id, at=T0, reason="RISK_LIMIT").status is OrderStatus.REJECTED
    with pytest.raises(InvalidOrderTransition):
        kernel.cancel(canceled.order_id, at=T0)
    with pytest.raises(ValueError, match="reason is required"):
        kernel.reject(kernel.submit(_request(order_id="EMPTY")).order_id, at=T0, reason="")


def test_replace_preserves_fill_history_and_resets_time_priority() -> None:
    kernel = OrderKernel()
    first = kernel.submit(_request(order_id="FIRST", quantity=10, limit_price=100))
    second = kernel.submit(_request(order_id="SECOND", quantity=10, limit_price=100))
    kernel.apply_fill(first.order_id, at=T0, quantity=2, price=99)
    replaced = kernel.replace(
        first.order_id,
        at=T0 + timedelta(seconds=1),
        quantity=8,
        limit_price=101,
    )
    assert replaced.version == 2
    assert replaced.filled_quantity == Decimal("2")
    assert [order.order_id for order in kernel.active_orders("SPY")] == ["SECOND", "FIRST"]
    with pytest.raises(ValueError, match="exceed cumulative"):
        kernel.replace(first.order_id, at=T0 + timedelta(seconds=1), quantity=2)
    with pytest.raises(ValueError, match="does not change"):
        kernel.replace(second.order_id, at=T0 + timedelta(seconds=1), quantity=10)


def test_day_order_expires_before_a_snapshot_at_the_session_boundary() -> None:
    close = T0 + timedelta(hours=6)
    kernel = OrderKernel()
    day = kernel.submit(
        _request(
            order_id="DAY",
            time_in_force="DAY",
            expires_at=close,
            limit_price=200,
        )
    )
    fills = kernel.process_snapshot(_quote(close, ask=100, ask_size=100))
    assert not fills
    assert kernel.get(day.order_id).status is OrderStatus.EXPIRED
    assert kernel.events[-1].kind is OrderEventKind.EXPIRED


def test_unknown_liquidity_fails_closed_and_ioc_cancels() -> None:
    kernel = OrderKernel()
    resting = kernel.submit(_request(order_id="RESTING", quantity=2))
    immediate = kernel.submit(
        _request(order_id="IOC", quantity=2, time_in_force="IOC")
    )
    assert not kernel.process_snapshot(
        _quote(
            T0 + timedelta(seconds=1),
            ask=99,
            bid_size=None,
            ask_size=None,
        )
    )
    assert kernel.get(resting.order_id).status is OrderStatus.ACCEPTED
    assert kernel.get(immediate.order_id).status is OrderStatus.CANCELED


def test_duplicate_and_retroactive_market_events_are_rejected() -> None:
    kernel = OrderKernel()
    kernel.submit(_request())
    snapshot = _quote(T0 + timedelta(seconds=1), sequence=7)
    kernel.process_snapshot(snapshot)
    with pytest.raises(ValueError, match="duplicate market snapshot"):
        kernel.process_snapshot(snapshot)
    with pytest.raises(ValueError, match="retroactive"):
        kernel.process_snapshot(_quote(T0, sequence=8))


def test_external_fill_rejects_overfill_and_computes_exact_average() -> None:
    kernel = OrderKernel()
    order = kernel.submit(_request(quantity="0.3"))
    kernel.apply_fill(order.order_id, at=T0, quantity="0.1", price="10.01")
    kernel.apply_fill(order.order_id, at=T0, quantity="0.2", price="10.02")
    final = kernel.get(order.order_id)
    assert final.average_fill_price == Decimal("10.01666666666666666666666667")
    assert final.status is OrderStatus.FILLED
    with pytest.raises(InvalidOrderTransition):
        kernel.apply_fill(order.order_id, at=T0, quantity="0.1", price=10)
