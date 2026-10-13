from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from backtest_sdk import Bar, TargetSignal

from backtest_universal import (
    AssetClass,
    Event,
    EventKind,
    EventQueue,
    FXMatrix,
    Instrument,
    OptionRight,
    SecurityMaster,
    SettlementType,
    UniversalBacktestEngine,
    UniversalEngineConfig,
)
from backtest_universal.adapters import (
    build_sma_targets,
    parse_long_dataset,
    single_asset_dataset,
    universal_csv_template,
)
from backtest_universal.strategy import (
    DEFAULT_STRATEGY_TEMPLATE,
    SandboxAttestation,
    SandboxRequiredError,
    build_strategy_job,
    validate_strategy_source,
)


def _bars(
    index: pd.DatetimeIndex,
    open_prices: list[float],
    close_prices: list[float] | None = None,
    **extra: object,
) -> pd.DataFrame:
    opens = np.asarray(open_prices, dtype=float)
    closes = np.asarray(close_prices if close_prices is not None else open_prices, dtype=float)
    frame = pd.DataFrame(
        {
            "open": opens,
            "high": np.maximum(opens, closes) * 1.01,
            "low": np.minimum(opens, closes) * 0.99,
            "close": closes,
            "volume": 1_000_000.0,
        },
        index=index,
    )
    for name, value in extra.items():
        frame[name] = value
    return frame


def _config(**overrides: object) -> UniversalEngineConfig:
    values: dict[str, object] = {
        "initial_cash": 100_000.0,
        "commission_bps": 0.0,
        "spread_bps": 0.0,
        "slippage_bps": 0.0,
        "impact_bps_at_full_participation": 0.0,
        "fx_conversion_bps": 0.0,
    }
    values.update(overrides)
    return UniversalEngineConfig(**values)


def test_event_queue_is_stable_and_separates_knowledge_from_effective_time() -> None:
    known = datetime(2025, 1, 2, tzinfo=timezone.utc)
    effective = datetime(2025, 1, 10, tzinfo=timezone.utc)
    market = Event(
        EventKind.MARKET_DATA,
        known,
        known,
        "SPY",
        source="prices",
        source_sequence=2,
    )
    dividend = Event(
        EventKind.CORPORATE_ACTION,
        effective,
        known,
        "SPY",
        {"dividend": 1.0},
        source="actions",
        source_sequence=1,
    )
    queue = EventQueue()
    queue.push(dividend)
    queue.push(market)
    assert queue.pop() == market
    assert queue.pop() == dividend
    assert dividend.process_at == effective

    duplicate = EventQueue()
    duplicate.push(market)
    with pytest.raises(ValueError, match="duplicate event_id"):
        duplicate.push(market)


def test_public_strategy_sdk_enforces_causal_timezone_contracts() -> None:
    event_time = datetime(2025, 1, 2, tzinfo=timezone.utc)
    bar = Bar("spy", event_time, event_time, 100, 101, 99, 100.5, 1_000_000)
    signal = TargetSignal("spy", event_time, event_time, 0.5, "trend")
    assert bar.symbol == "SPY"
    assert signal.target_exposure == 0.5
    with pytest.raises(ValueError, match="timezone-aware"):
        Bar("SPY", datetime(2025, 1, 2), event_time, 100, 101, 99, 100)


def test_fx_matrix_triangulates_and_rejects_retroactive_updates() -> None:
    fx = FXMatrix("USD")
    t1 = datetime(2025, 1, 2, tzinfo=timezone.utc)
    t2 = datetime(2025, 1, 3, tzinfo=timezone.utc)
    fx.set_rate("EUR", "USD", 1.10, as_of=t1)
    fx.set_rate("GBP", "EUR", 1.20, as_of=t1)
    assert fx.convert(100, "GBP", "USD") == pytest.approx(132.0)
    fx.set_rate("EUR", "USD", 1.11, as_of=t2)
    with pytest.raises(ValueError, match="retroactive"):
        fx.set_rate("EUR", "USD", 1.09, as_of=t1)
    fx.set_valuation_clock(
        datetime(2025, 1, 5, tzinfo=timezone.utc), max_age_seconds=24 * 60 * 60
    )
    with pytest.raises(LookupError, match="staleness"):
        fx.rate("EUR", "USD")


def test_universal_engine_multi_asset_multi_currency_is_causal() -> None:
    index = pd.date_range("2025-01-01", periods=5, freq="D", tz="UTC")
    us = Instrument(
        "US_EQ", AssetClass.EQUITY, "USD", instrument_id="US_EQ", lot_size=1e-8
    )
    eu = Instrument(
        "EU_EQ", AssetClass.EQUITY, "EUR", instrument_id="EU_EQ", lot_size=1e-8
    )
    targets = pd.DataFrame(
        {
            "US_EQ": [0.0, 0.5, 0.5, 0.0, 0.0],
            "EU_EQ": [0.0, 0.5, 0.5, 0.0, 0.0],
        },
        index=index,
    )
    result = UniversalBacktestEngine(
        security_master=SecurityMaster([us, eu]), config=_config()
    ).run(
        market_data={
            "US_EQ": _bars(index, [100] * 5, [100.5] * 5),
            "EU_EQ": _bars(index, [50] * 5, [50.25] * 5),
        },
        target_weights=targets,
        fx_rates={"EUR/USD": pd.Series([1.1, 1.1, 1.2, 1.2, 1.2], index=index)},
    )
    assert result.status == "AVAILABLE"
    first_fills = result.fills[result.fills["timestamp"] == index[2]]
    assert set(first_fills["instrument_id"]) == {"US_EQ", "EU_EQ"}
    assert result.fills["timestamp"].min() > index[1]
    assert result.diagnostics["multi_currency_cashbook"] is True
    assert result.diagnostics["fx_conversions"]
    assert result.daily.loc[index[2], "nav"] == pytest.approx(100_500.0)


def test_split_replay_preserves_nav_and_quantity() -> None:
    index = pd.date_range("2025-02-01", periods=4, freq="D", tz="UTC")
    split = [0.0, 0.0, 2.0, 0.0]
    bars = _bars(index, [100, 100, 50, 50], split=split)
    instrument = Instrument(
        "SPLT", AssetClass.EQUITY, "USD", instrument_id="SPLT", lot_size=1e-8
    )
    targets = pd.DataFrame({"SPLT": [1.0, np.nan, np.nan, np.nan]}, index=index)
    result = UniversalBacktestEngine(
        security_master=SecurityMaster([instrument]), config=_config()
    ).run(market_data={"SPLT": bars}, target_weights=targets)
    assert result.status == "AVAILABLE"
    assert result.daily.loc[index[1], "nav"] == pytest.approx(100_000.0)
    assert result.daily.loc[index[2], "nav"] == pytest.approx(100_000.0)
    assert result.positions.loc[0, "quantity"] == pytest.approx(2_000.0)
    assert "split" in set(result.events["kind"])


def test_future_variation_margin_and_crypto_funding_hit_cashbook() -> None:
    index = pd.date_range("2025-03-01", periods=4, freq="D", tz="UTC")
    future = Instrument(
        "ESM5",
        AssetClass.FUTURE,
        "USD",
        instrument_id="ESM5",
        multiplier=50.0,
        lot_size=1.0,
        initial_margin_rate=0.10,
        maintenance_margin_rate=0.075,
    )
    targets = pd.DataFrame({"ESM5": [0.10, np.nan, np.nan, np.nan]}, index=index)
    result = UniversalBacktestEngine(
        security_master=SecurityMaster([future]), config=_config()
    ).run(
        market_data={"ESM5": _bars(index, [100, 100, 103, 104], [100, 102, 104, 105])},
        target_weights=targets,
    )
    assert result.status == "AVAILABLE"
    assert result.fills.iloc[0]["signed_quantity"] == pytest.approx(2.0)
    assert result.daily.iloc[-1]["nav"] == pytest.approx(100_500.0)
    assert "variation_margin" in {item["kind"] for item in result.records()["events"]} or any(
        item.get("kind") == "variation_margin" for item in result.diagnostics.get("accounting_events", [])
    )

    perp = Instrument(
        "BTC-PERP",
        AssetClass.CRYPTO_PERPETUAL,
        "USD",
        instrument_id="BTC-PERP",
        lot_size=1e-8,
    )
    perp_bars = _bars(index, [10_000] * 4, funding_rate=[0.0, 0.0, 0.001, 0.0])
    perp_result = UniversalBacktestEngine(
        security_master=SecurityMaster([perp]), config=_config()
    ).run(
        market_data={"BTC-PERP": perp_bars},
        target_weights=pd.DataFrame(
            {"BTC-PERP": [0.5, np.nan, np.nan, np.nan]}, index=index
        ),
    )
    assert perp_result.daily.iloc[-1]["nav"] == pytest.approx(99_950.0)
    assert "funding" in set(perp_result.events["kind"])


def test_long_dataset_adapter_and_sma_targets() -> None:
    dataset = parse_long_dataset(universal_csv_template(), base_currency="USD")
    assert len(dataset.security_master.records()) == 2
    assert set(dataset.market_data) == {"ARCX:SPY", "XETR:EWG"}
    assert "EUR/USD" in dataset.fx_rates
    assert dataset.target_weights is not None
    sma = build_sma_targets(dataset.market_data, fast=1, slow=2)
    assert list(sma.columns) == ["ARCX:SPY", "XETR:EWG"]
    assert sma.abs().sum(axis=1).max() <= 1.0


def test_long_dataset_keys_contracts_by_instrument_id_not_display_symbol() -> None:
    index = pd.date_range("2025-06-01", periods=2, freq="D", tz="UTC")
    rows: list[dict[str, object]] = []
    for contract, expiry, price in (
        ("CME:ESM5", "2025-06-20T00:00:00Z", 5_300.0),
        ("CME:ESU5", "2025-09-19T00:00:00Z", 5_320.0),
    ):
        for timestamp in index:
            rows.append(
                {
                    "timestamp": timestamp,
                    "symbol": "ES",
                    "instrument_id": contract,
                    "asset_class": "FUTURE",
                    "quote_currency": "USD",
                    "exchange": "CME",
                    "root_symbol": "ES",
                    "expiry": expiry,
                    "multiplier": 50.0,
                    "lot_size": 1.0,
                    "tick_size": 0.25,
                    "open": price,
                    "high": price + 5.0,
                    "low": price - 5.0,
                    "close": price + 1.0,
                    "volume": 50_000.0,
                }
            )

    dataset = parse_long_dataset(pd.DataFrame(rows), base_currency="USD")

    assert set(dataset.market_data) == {"CME:ESM5", "CME:ESU5"}
    assert len(dataset.security_master.records()) == 2
    assert all(len(frame) == 2 for frame in dataset.market_data.values())


def test_long_dataset_rejects_inconsistent_metadata_within_instrument() -> None:
    frame = universal_csv_template().iloc[:2].copy()
    frame.loc[frame.index[-1], "quote_currency"] = "EUR"

    with pytest.raises(ValueError, match="inconsistent instrument metadata"):
        parse_long_dataset(frame, base_currency="USD")


def test_single_asset_adapter_accepts_required_derivative_metadata() -> None:
    index = pd.date_range("2025-01-01", periods=2, freq="D", tz="UTC")
    bars = _bars(index, [1.10, 1.11])
    fx_dataset = single_asset_dataset(
        "EURUSD",
        bars,
        currency="USD",
        asset_class=AssetClass.FX,
        base_currency="EUR",
        instrument_id="FX:EURUSD",
        lot_size=1_000.0,
        tick_size=0.00001,
    )
    assert fx_dataset.security_master.get("FX:EURUSD").base_currency == "EUR"

    option_dataset = single_asset_dataset(
        "SPY-C-500",
        _bars(index, [5.0, 5.5]),
        asset_class=AssetClass.OPTION,
        underlying_symbol="SPY",
        strike=500.0,
        option_right=OptionRight.CALL,
        expiry=index[-1].to_pydatetime(),
        multiplier=100.0,
    )
    option = option_dataset.security_master.get("SPY-C-500")
    assert option.asset_class == AssetClass.OPTION
    assert option.lot_size == 1.0


def test_strategy_policy_accepts_sdk_contract_and_blocks_escape_vectors() -> None:
    accepted = validate_strategy_source(DEFAULT_STRATEGY_TEMPLATE)
    assert accepted.passed, accepted.issues
    attacks = [
        "def on_bar(ctx, bar):\n    return ().__class__.__mro__\n",
        "import os\ndef on_bar(ctx, bar):\n    os.system('id')\n",
        "def on_bar(ctx, bar):\n    return open('/etc/passwd').read()\n",
        "def on_bar(ctx, bar):\n    while True:\n        pass\n",
    ]
    for source in attacks:
        report = validate_strategy_source(source)
        assert not report.passed


def test_strategy_job_fails_closed_without_attested_oci_sandbox() -> None:
    kwargs = dict(
        source=DEFAULT_STRATEGY_TEMPLATE,
        parameters={"fast": 20, "slow": 100},
        seed=41,
        dataset_sha256="a" * 64,
        security_master_sha256="b" * 64,
        calendar_sha256="c" * 64,
        base_currency="USD",
        symbols=("SPY",),
    )
    with pytest.raises(SandboxRequiredError):
        build_strategy_job(attestation=SandboxAttestation(), **kwargs)
    attested = SandboxAttestation(
        available=True,
        runner_image_digest="sha256:" + "d" * 64,
        network_disabled=True,
        read_only_root=True,
        no_secrets_mounted=True,
        non_root=True,
        signature_verified=True,
        reason="",
    )
    first = build_strategy_job(attestation=attested, **kwargs)
    second = build_strategy_job(attestation=attested, **kwargs)
    assert first.job_id == second.job_id
    changed = build_strategy_job(
        attestation=attested,
        **(kwargs | {"parameters": {"fast": 21, "slow": 100}}),
    )
    assert changed.job_id != first.job_id


def test_cash_asset_exit_nets_commission_from_unsettled_sale_proceeds() -> None:
    index = pd.date_range("2025-04-01", periods=5, freq="D", tz="UTC")
    instrument = Instrument(
        "FULL", AssetClass.EQUITY, "USD", instrument_id="FULL", lot_size=1e-8,
        settlement_days=2,
    )
    targets = pd.DataFrame(
        {"FULL": [1.0, np.nan, 0.0, np.nan, np.nan]}, index=index
    )
    result = UniversalBacktestEngine(
        security_master=SecurityMaster([instrument]),
        config=_config(commission_bps=10.0),
    ).run(market_data={"FULL": _bars(index, [100.0] * len(index))}, target_weights=targets)

    assert len(result.fills) == 2
    assert list(result.fills["signed_quantity"] > 0) == [True, False]
    assert not any(
        "insufficient settled" in str(value)
        for value in result.orders.get("rejection_reason", pd.Series(dtype=str)).dropna()
    )


def test_cash_settled_option_uses_subscribed_underlying_intrinsic_value() -> None:
    index = pd.date_range("2025-06-18", periods=3, freq="D", tz="UTC")
    underlying = Instrument(
        "SPY", AssetClass.ETF, "USD", instrument_id="SPY", lot_size=1e-8
    )
    option = Instrument(
        "SPY-C-105",
        AssetClass.OPTION,
        "USD",
        instrument_id="SPY-C-105",
        multiplier=100.0,
        lot_size=1.0,
        underlying_symbol="SPY",
        expiry=index[-1].to_pydatetime(),
        strike=105.0,
        option_right=OptionRight.CALL,
        settlement_type=SettlementType.CASH,
    )
    targets = pd.DataFrame(
        {option.key: [0.10, np.nan, np.nan]}, index=index
    )
    result = UniversalBacktestEngine(
        security_master=SecurityMaster([underlying, option]), config=_config()
    ).run(
        market_data={
            underlying.key: _bars(index, [100, 110, 120]),
            option.key: _bars(index, [4, 5, 15]),
        },
        target_weights=targets,
    )

    assert result.status == "AVAILABLE"
    assert result.daily.iloc[-1]["nav"] == pytest.approx(120_000.0)
    assert "option_cash_settlement" in set(result.events["kind"])
    assert result.positions.empty


def test_future_roll_transfers_notional_to_explicit_next_contract() -> None:
    index = pd.date_range("2025-06-16", periods=4, freq="D", tz="UTC")
    front = Instrument(
        "ESM5",
        AssetClass.FUTURE,
        "USD",
        instrument_id="ESM5",
        root_symbol="ES",
        expiry=index[2].to_pydatetime(),
        multiplier=50.0,
        lot_size=1.0,
    )
    next_contract = Instrument(
        "ESU5",
        AssetClass.FUTURE,
        "USD",
        instrument_id="ESU5",
        root_symbol="ES",
        expiry=(index[-1] + pd.Timedelta(days=90)).to_pydatetime(),
        multiplier=50.0,
        lot_size=1.0,
    )
    front_bars = _bars(index[:3], [100, 100, 100])
    front_bars["roll_to"] = ["", "", next_contract.key]
    next_bars = _bars(index, [101, 101, 100, 102])
    targets = pd.DataFrame({front.key: [0.10, np.nan, np.nan, np.nan]}, index=index)
    result = UniversalBacktestEngine(
        security_master=SecurityMaster([front, next_contract]), config=_config()
    ).run(
        market_data={front.key: front_bars, next_contract.key: next_bars},
        target_weights=targets,
    )

    assert result.status == "AVAILABLE"
    assert "future_roll" in set(result.events["kind"])
    assert set(result.positions["instrument_id"]) == {next_contract.key}
    assert result.positions.iloc[0]["quantity"] == pytest.approx(2.0)


def test_historical_cash_carry_is_accrued_between_events() -> None:
    index = pd.date_range("2025-07-01", periods=3, freq="D", tz="UTC")
    instrument = Instrument(
        "CASH-PROXY", AssetClass.ETF, "USD", instrument_id="CASH-PROXY"
    )
    result = UniversalBacktestEngine(
        security_master=SecurityMaster([instrument]), config=_config()
    ).run(
        market_data={instrument.key: _bars(index, [100.0] * 3)},
        target_weights=pd.DataFrame({instrument.key: [0.0, 0.0, 0.0]}, index=index),
        cash_rates={"USD": pd.Series([0.365, 0.365, 0.365], index=index)},
    )

    assert result.status == "AVAILABLE"
    assert result.daily.iloc[-1]["nav"] == pytest.approx(100_200.10)
    assert result.diagnostics["cash_carry_available"] is True
    assert "cash_carry" in set(result.events["kind"])


def test_dividend_entitlement_remains_unsettled_until_payable_date() -> None:
    index = pd.date_range("2025-08-01", periods=4, freq="D", tz="UTC")
    payable = index[-1] + pd.Timedelta(days=2)
    bars = _bars(index, [100.0] * 4)
    bars["dividend"] = [0.0, 0.0, 2.0, 0.0]
    bars["dividend_payable_at"] = [None, None, payable.isoformat(), None]
    instrument = Instrument(
        "DIV", AssetClass.EQUITY, "USD", instrument_id="DIV", lot_size=1e-8
    )
    result = UniversalBacktestEngine(
        security_master=SecurityMaster([instrument]), config=_config()
    ).run(
        market_data={instrument.key: bars},
        target_weights=pd.DataFrame(
            {instrument.key: [0.5, np.nan, np.nan, np.nan]}, index=index
        ),
    )

    entitlement = result.events[result.events["kind"] == "dividend_entitlement"]
    settlement = result.events[
        (result.events["kind"] == "settlement")
        & (result.events.get("reference") == "dividend:DIV")
    ]
    assert result.status == "AVAILABLE"
    assert entitlement.iloc[0]["timestamp"] == index[2]
    assert settlement.iloc[0]["timestamp"] == payable
    assert result.cash.iloc[0]["unsettled"] == pytest.approx(0.0)


def test_material_terminal_target_change_is_fail_closed() -> None:
    index = pd.date_range("2025-09-01", periods=3, freq="D", tz="UTC")
    instrument = Instrument(
        "LATE", AssetClass.ETF, "USD", instrument_id="LATE", lot_size=1e-8
    )
    result = UniversalBacktestEngine(
        security_master=SecurityMaster([instrument]), config=_config()
    ).run(
        market_data={instrument.key: _bars(index, [100.0] * 3)},
        target_weights=pd.DataFrame(
            {instrument.key: [0.5, 0.5, 0.0]}, index=index
        ),
    )

    assert result.status == "PARTIAL"
    assert result.diagnostics["terminal_target_changes_without_execution"] == [
        instrument.key
    ]


def test_persistent_portfolio_positions_cannot_bypass_gross_exposure_limit() -> None:
    index = pd.date_range("2025-10-01", periods=5, freq="D", tz="UTC")
    first = Instrument(
        "FUT-A",
        AssetClass.FUTURE,
        "USD",
        instrument_id="FUT-A",
        lot_size=1.0,
        initial_margin_rate=0.10,
        maintenance_margin_rate=0.075,
    )
    second = Instrument(
        "FUT-B",
        AssetClass.FUTURE,
        "USD",
        instrument_id="FUT-B",
        lot_size=1.0,
        initial_margin_rate=0.10,
        maintenance_margin_rate=0.075,
    )
    targets = pd.DataFrame(
        {
            first.key: [3.0, np.nan, np.nan, np.nan, np.nan],
            second.key: [np.nan, 3.0, np.nan, np.nan, np.nan],
        },
        index=index,
    )
    result = UniversalBacktestEngine(
        security_master=SecurityMaster([first, second]),
        config=_config(max_gross_exposure=4.0),
    ).run(
        market_data={
            first.key: _bars(index, [100.0] * len(index)),
            second.key: _bars(index, [100.0] * len(index)),
        },
        target_weights=targets,
    )

    quantities = result.positions.set_index("instrument_id")["quantity"]
    assert quantities[first.key] == pytest.approx(3_000.0)
    assert quantities[second.key] == pytest.approx(1_000.0)
    assert result.daily["gross_exposure"].max() <= 4.0 + 1e-12
    assert result.diagnostics["gross_limit_clips"] >= 1
    assert "pretrade_gross_clip" in set(result.events["kind"])
    assert result.status == "PARTIAL"


def test_partial_fill_remainder_is_retried_on_later_bars() -> None:
    index = pd.date_range("2025-11-01", periods=4, freq="D", tz="UTC")
    instrument = Instrument(
        "RETRY",
        AssetClass.FUTURE,
        "USD",
        instrument_id="RETRY",
        lot_size=1.0,
        initial_margin_rate=0.10,
        maintenance_margin_rate=0.075,
    )
    targets = pd.DataFrame(
        {instrument.key: [0.02, np.nan, np.nan, np.nan]}, index=index
    )
    result = UniversalBacktestEngine(
        security_master=SecurityMaster([instrument]),
        config=_config(max_participation=0.10),
    ).run(
        market_data={
            instrument.key: _bars(index, [100.0] * len(index), volume=[100.0] * len(index))
        },
        target_weights=targets,
    )

    assert list(result.orders["status"]) == ["PARTIAL", "FILLED"]
    assert list(result.fills["signed_quantity"]) == pytest.approx([10.0, 10.0])
    assert result.positions.iloc[0]["quantity"] == pytest.approx(20.0)
    assert result.diagnostics["terminal_target_changes_without_execution"] == []
    assert "target_remainder" in set(result.events["kind"])


def test_contract_lots_and_adverse_tick_rounding_are_enforced_by_default() -> None:
    index = pd.date_range("2025-12-01", periods=4, freq="D", tz="UTC")
    future = Instrument(
        "LOT-FUT",
        AssetClass.FUTURE,
        "USD",
        instrument_id="LOT-FUT",
        lot_size=0.25,
        tick_size=0.25,
        initial_margin_rate=0.10,
        maintenance_margin_rate=0.075,
    )
    option = Instrument(
        "LOT-OPT",
        AssetClass.OPTION,
        "USD",
        instrument_id="LOT-OPT",
        lot_size=0.25,
        tick_size=0.25,
        underlying_symbol="UNDERLYING",
        strike=100.0,
        option_right=OptionRight.CALL,
    )
    targets = pd.DataFrame(
        {
            future.key: [0.0015, np.nan, 0.0, np.nan],
            option.key: [0.0015, np.nan, 0.0, np.nan],
        },
        index=index,
    )
    result = UniversalBacktestEngine(
        security_master=SecurityMaster([future, option]),
        config=_config(allow_fractional=True),
    ).run(
        market_data={
            future.key: _bars(index, [100.03] * len(index)),
            option.key: _bars(index, [100.03] * len(index)),
        },
        target_weights=targets,
    )

    assert set(result.fills["signed_quantity"]) == {-1.0, 1.0}
    buys = result.fills[result.fills["signed_quantity"] > 0]
    sells = result.fills[result.fills["signed_quantity"] < 0]
    assert np.allclose(buys["fill_price"], 100.25)
    assert np.allclose(sells["fill_price"], 100.0)
    assert all(
        float(price) / 0.25 == pytest.approx(round(float(price) / 0.25))
        for price in result.fills["fill_price"]
    )
