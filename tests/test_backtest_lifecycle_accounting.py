from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from backtest_universal import (
    AssetClass,
    Instrument,
    PortfolioLedger,
    SecurityMaster,
    UniversalBacktestEngine,
    UniversalEngineConfig,
)


NOW = datetime(2025, 1, 2, tzinfo=timezone.utc)


def _equity(symbol: str) -> Instrument:
    return Instrument(
        symbol,
        AssetClass.EQUITY,
        "USD",
        instrument_id=f"XNYS:{symbol}",
    )


def _bars(index: pd.DatetimeIndex, prices: list[float], **fields: object) -> pd.DataFrame:
    values = np.asarray(prices, dtype=float)
    frame = pd.DataFrame(
        {
            "open": values,
            "high": values * 1.01,
            "low": values * 0.99,
            "close": values,
            "volume": 1_000_000.0,
        },
        index=index,
    )
    for name, value in fields.items():
        frame[name] = value
    return frame


def _config() -> UniversalEngineConfig:
    return UniversalEngineConfig(
        initial_cash=100_000.0,
        commission_bps=0.0,
        spread_bps=0.0,
        slippage_bps=0.0,
        impact_bps_at_full_participation=0.0,
        fx_conversion_bps=0.0,
        require_volume=True,
    )


def test_spinoff_distribution_preserves_parent_and_credits_child() -> None:
    parent = _equity("PARENT")
    child = _equity("CHILD")
    ledger = PortfolioLedger("USD", 0.0)
    ledger.position(parent.key).trade(100.0, 50.0)

    credited = ledger.apply_distribution(
        parent,
        child,
        0.25,
        NOW,
        kind="spinoff",
        cost_allocation=0.20,
    )

    assert credited == pytest.approx(25.0)
    assert ledger.position(parent.key).quantity == pytest.approx(100.0)
    assert ledger.position(parent.key).average_price == pytest.approx(40.0)
    assert ledger.position(child.key).average_price == pytest.approx(40.0)
    assert ledger.realized_events[-1]["kind"] == "spinoff"


def test_symbol_change_transfers_quantity_and_economic_cost() -> None:
    source = _equity("OLD")
    destination = _equity("NEW")
    ledger = PortfolioLedger("USD", 0.0)
    ledger.position(source.key).trade(80.0, 25.0)
    ledger.position(source.key).last_price = 30.0

    moved = ledger.apply_symbol_change(source, destination, NOW, ratio=0.5)

    assert moved == pytest.approx(40.0)
    assert ledger.position(source.key).quantity == 0.0
    assert ledger.position(destination.key).quantity == pytest.approx(40.0)
    assert ledger.position(destination.key).average_price == pytest.approx(50.0)
    assert ledger.position(destination.key).last_price == pytest.approx(60.0)


def test_cash_merger_closes_position_and_credits_consideration() -> None:
    target = _equity("TARGET")
    ledger = PortfolioLedger("USD", 0.0)
    ledger.position(target.key).trade(10.0, 80.0)

    amount = ledger.apply_cash_merger(target, 95.0, NOW)

    assert amount == pytest.approx(950.0)
    assert ledger.cash.balance("USD") == pytest.approx(950.0)
    assert ledger.position(target.key).quantity == 0.0
    assert ledger.realized_events[-1]["realized_pnl"] == pytest.approx(150.0)


def test_engine_applies_explicit_spinoff_contract_without_lifecycle_gap() -> None:
    index = pd.date_range("2025-03-01", periods=4, freq="D", tz="UTC")
    parent = _equity("PARENT")
    child = _equity("CHILD")
    parent_bars = _bars(index, [100.0, 100.0, 50.0, 50.0])
    parent_bars["spinoff_ratio"] = [0.0, 0.0, 0.5, 0.0]
    parent_bars["spinoff_instrument_id"] = ["", "", child.key, ""]
    result = UniversalBacktestEngine(
        security_master=SecurityMaster([parent, child]), config=_config()
    ).run(
        market_data={
            parent.key: parent_bars,
            child.key: _bars(index, [100.0, 100.0, 100.0, 100.0]),
        },
        target_weights=pd.DataFrame(
            {parent.key: [1.0, np.nan, np.nan, np.nan]}, index=index
        ),
    )

    positions = result.positions.set_index("instrument_id")["quantity"]
    assert result.status == "AVAILABLE"
    assert positions[parent.key] == pytest.approx(1_000.0)
    assert positions[child.key] == pytest.approx(500.0)
    assert result.daily.iloc[-1]["nav"] == pytest.approx(100_000.0)
    assert result.diagnostics["lifecycle_gaps"] == []
    assert "spinoff" in set(result.events["kind"])


def test_engine_moves_position_through_explicit_symbol_change() -> None:
    index = pd.date_range("2025-04-01", periods=4, freq="D", tz="UTC")
    old = _equity("OLD")
    new = _equity("NEW")
    old_bars = _bars(index, [100.0] * 4)
    old_bars["symbol_change_to"] = ["", "", new.key, ""]
    result = UniversalBacktestEngine(
        security_master=SecurityMaster([old, new]), config=_config()
    ).run(
        market_data={old.key: old_bars, new.key: _bars(index, [100.0] * 4)},
        target_weights=pd.DataFrame(
            {old.key: [1.0, np.nan, np.nan, np.nan]}, index=index
        ),
    )

    assert result.status == "AVAILABLE"
    assert set(result.positions["instrument_id"]) == {new.key}
    assert result.positions.iloc[0]["quantity"] == pytest.approx(1_000.0)
    assert "symbol_change" in set(result.events["kind"])


def test_engine_cash_merger_closes_position_at_explicit_consideration() -> None:
    index = pd.date_range("2025-05-01", periods=4, freq="D", tz="UTC")
    target = _equity("TARGET")
    bars = _bars(index, [100.0, 100.0, 120.0, 120.0])
    bars["merger_cash"] = [0.0, 0.0, 120.0, 0.0]
    result = UniversalBacktestEngine(
        security_master=SecurityMaster([target]), config=_config()
    ).run(
        market_data={target.key: bars},
        target_weights=pd.DataFrame(
            {target.key: [1.0, np.nan, np.nan, np.nan]}, index=index
        ),
    )

    assert result.status == "AVAILABLE"
    assert result.positions.empty
    assert result.daily.iloc[-1]["nav"] == pytest.approx(120_000.0)
    assert "cash_merger" in set(result.events["kind"])
