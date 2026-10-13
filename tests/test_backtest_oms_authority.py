from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from backtest_sdk import PortfolioSnapshot, Slice
from backtest_universal.engine import UniversalBacktestEngine, UniversalEngineConfig
from backtest_universal.fx import FXMatrix
from backtest_universal.orders import OrderKernel, OrderRequest
from backtest_universal.portfolio import PortfolioLedger
from backtest_universal.security import SecurityMaster
from backtest_universal.types import AssetClass, Instrument


UTC = timezone.utc
T0 = datetime(2025, 1, 2, tzinfo=UTC)


def _instrument() -> Instrument:
    return Instrument(
        "AAA",
        AssetClass.EQUITY,
        "USD",
        instrument_id="AAA",
        lot_size=1.0,
        tick_size=0.01,
    )


def _bars(prices: list[float]) -> pd.DataFrame:
    index = pd.date_range(T0, periods=len(prices), freq="D")
    values = np.asarray(prices, dtype=float)
    return pd.DataFrame(
        {
            "open": values,
            "high": values + 1.0,
            "low": values - 1.0,
            "close": values,
            "volume": 1_000_000.0,
        },
        index=index,
    )


def _config() -> UniversalEngineConfig:
    return UniversalEngineConfig(
        initial_cash=100_000.0,
        commission_bps=0.0,
        spread_bps=0.0,
        slippage_bps=0.0,
        impact_bps_at_full_participation=0.0,
        fx_conversion_bps=0.0,
    )


def test_engine_books_only_authoritative_oms_fills_and_reconciles_ids() -> None:
    instrument = _instrument()
    bars = _bars([100.0, 100.0, 101.0])
    targets = pd.DataFrame(
        {instrument.key: [1.0, np.nan, np.nan]}, index=bars.index
    )

    result = UniversalBacktestEngine(
        security_master=SecurityMaster([instrument]), config=_config()
    ).run(market_data={instrument.key: bars}, target_weights=targets)

    assert result.diagnostics["oms_authoritative"] is True
    assert result.diagnostics["ledger_fill_authority"] == "OrderKernel.authoritative_fills"
    assert result.diagnostics["oms_ledger_reconciled"] is True
    assert result.diagnostics["oms_active_orders"] == 0
    assert set(result.fills["authority"]) == {"OMS"}
    assert set(result.fills["source"]) == {"UNIVERSAL_BAR_EXECUTION"}
    accounting_fill_ids = {
        item["fill_id"]
        for item in result.diagnostics["accounting_events"]
        if item.get("kind") == "fill"
    }
    assert accounting_fill_ids == set(result.fills["fill_id"])
    assert {item["kind"] for item in result.diagnostics["oms_events"]} >= {
        "SUBMITTED",
        "ACCEPTED",
        "FILLED",
    }
    assert result.portfolio_snapshot is not None
    assert result.portfolio_snapshot.source == "OMS_EXECUTION_LEDGER"
    assert result.portfolio_snapshot.ledger_sha256

    replay = UniversalBacktestEngine(
        security_master=SecurityMaster([instrument]), config=_config()
    ).run(market_data={instrument.key: bars}, target_weights=targets)
    pd.testing.assert_frame_equal(result.orders, replay.orders)
    pd.testing.assert_frame_equal(result.fills, replay.fills)
    assert (
        result.diagnostics["oms_fill_ledger_sha256"]
        == replay.diagnostics["oms_fill_ledger_sha256"]
    )
    assert (
        result.portfolio_snapshot.ledger_sha256
        == replay.portfolio_snapshot.ledger_sha256
    )


def test_portfolio_rejects_duplicate_or_cross_instrument_oms_fill() -> None:
    instrument = _instrument()
    other = Instrument("BBB", AssetClass.EQUITY, "USD", instrument_id="BBB")
    kernel = OrderKernel()
    order = kernel.submit(
        OrderRequest(
            symbol=instrument.key,
            side="BUY",
            order_type="MARKET",
            quantity=2,
            submitted_at=T0,
        )
    )
    fill = kernel.apply_fill(order.order_id, at=T0, quantity=2, price=100)
    ledger = PortfolioLedger("USD", 1_000.0)

    with pytest.raises(ValueError, match="instrument mismatch"):
        ledger.apply_oms_fill(other, fill, 0.0, T0)
    ledger.apply_oms_fill(instrument, fill, 0.0, T0)
    with pytest.raises(ValueError, match="duplicate OMS fill"):
        ledger.apply_oms_fill(instrument, fill, 0.0, T0)
    assert ledger.position(instrument.key).quantity == pytest.approx(2.0)


class _CausalRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[PortfolioSnapshot, Slice]] = []
        self.immutable = False

    def on_slice(
        self, *, portfolio: PortfolioSnapshot, market_slice: Slice
    ) -> dict[str, float]:
        self.calls.append((portfolio, market_slice))
        try:
            portfolio.cash["USD"] = -1.0  # type: ignore[index]
        except TypeError:
            self.immutable = True
        if portfolio.sequence == 1:
            return {"AAA": 1.0}
        if portfolio.sequence == 2:
            return {"AAA": 0.0}
        return {}


def test_causal_runtime_receives_post_ledger_snapshot_and_next_bar_execution() -> None:
    instrument = _instrument()
    bars = _bars([100.0, 100.0, 102.0, 103.0])
    runtime = _CausalRuntime()

    result = UniversalBacktestEngine(
        security_master=SecurityMaster([instrument]), config=_config()
    ).run(
        market_data={instrument.key: bars},
        strategy_runtime=runtime,
    )

    assert runtime.immutable is True
    assert len(runtime.calls) == len(bars)
    first_snapshot, first_slice = runtime.calls[0]
    second_snapshot, second_slice = runtime.calls[1]
    assert first_snapshot.positions == {}
    assert first_snapshot.as_of == first_slice.available_at
    assert second_snapshot.as_of == second_slice.available_at
    assert second_snapshot.positions["AAA"]["quantity"] == pytest.approx(1_000.0)
    assert second_snapshot.open_orders == ()
    assert list(result.fills["timestamp"]) == [bars.index[1], bars.index[2]]
    assert list(result.fills["signed_quantity"]) == pytest.approx([1_000.0, -1_000.0])
    target_events = result.events[result.events["kind"] == "strategy_target"]
    assert set(target_events["source"]) == {"causal_strategy_runtime"}
    assert all(
        fill_time > target_time
        for fill_time, target_time in zip(
            result.fills["timestamp"], target_events["timestamp"]
        )
    )
    assert result.diagnostics["portfolio_feedback_slices"] == len(bars)
    assert result.diagnostics["oms_ledger_reconciled"] is True


class _InvalidRuntime:
    def on_slice(
        self, *, portfolio: PortfolioSnapshot, market_slice: Slice
    ) -> dict[str, float]:
        return {"AAA": float("nan")}


def test_causal_runtime_fails_closed_on_invalid_target() -> None:
    instrument = _instrument()
    result = UniversalBacktestEngine(
        security_master=SecurityMaster([instrument]), config=_config()
    ).run(
        market_data={instrument.key: _bars([100.0, 101.0])},
        strategy_runtime=_InvalidRuntime(),
    )

    assert result.status == "UNAVAILABLE"
    assert result.fills.empty
    assert any(
        "must be finite" in reason for reason in result.diagnostics["fatal_reasons"]
    )
