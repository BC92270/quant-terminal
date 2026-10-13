from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from backtest_universal import (
    AssetClass,
    EventKind,
    FXMatrix,
    Instrument,
    MarginContext,
    MarginEngineRegistry,
    MarginMethod,
    MarginParameterSet,
    OccTimsReferenceMarginEngine,
    OptionCalendarContract,
    OptionExerciseStyle,
    OptionLifecycleAction,
    OptionLifecycleDataRequired,
    OptionLifecycleProcessor,
    OptionLifecycleRequestKind,
    OptionRight,
    OptionSettlementReference,
    PortfolioLedger,
    PortfolioMarginReferenceEngine,
    Position,
    SecurityMaster,
    SettlementType,
    SimmReferenceMarginEngine,
    SpanReferenceMarginEngine,
    UniversalBacktestEngine,
    UniversalEngineConfig,
    VersionedMarginParameterStore,
)
from backtest_universal.adapters import (
    parse_long_dataset,
    parse_margin_parameter_set,
)


EXPIRY = datetime(2025, 1, 17, 21, tzinfo=timezone.utc)
CUTOFF = datetime(2025, 1, 17, 22, tzinfo=timezone.utc)
SETTLEMENT = datetime(2025, 1, 21, 14, 30, tzinfo=timezone.utc)


def _underlying() -> Instrument:
    return Instrument("SPY", AssetClass.ETF, "USD", instrument_id="ARCX:SPY")


def _option(
    *,
    right: OptionRight = OptionRight.CALL,
    settlement: SettlementType = SettlementType.PHYSICAL,
    style: OptionExerciseStyle = OptionExerciseStyle.AMERICAN,
    strike: float = 100.0,
) -> Instrument:
    return Instrument(
        f"SPY-{right.value}-100",
        AssetClass.OPTION,
        "USD",
        instrument_id=f"OPRA:SPY-{right.value}-100",
        underlying_symbol="ARCX:SPY",
        multiplier=100.0,
        strike=strike,
        option_right=right,
        expiry=EXPIRY,
        settlement_type=settlement,
        option_exercise_style=style,
        option_calendar_id="OPRA-2025-01-17",
        automatic_exercise_threshold=0.01,
    )


def _calendar(
    style: OptionExerciseStyle = OptionExerciseStyle.AMERICAN,
) -> OptionCalendarContract:
    return OptionCalendarContract(
        calendar_id="OPRA-2025-01-17",
        timezone_name="America/New_York",
        expiration_at=EXPIRY,
        exercise_cutoff_at=CUTOFF,
        settlement_at=SETTLEMENT,
        exercise_style=style,
        source="test-calendar",
        source_version="2025-01-01",
        available_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )


def _reference(price: float, *, at: datetime = CUTOFF) -> OptionSettlementReference:
    return OptionSettlementReference(
        observed_at=at,
        available_at=at,
        source="test-close",
        source_version="v1",
        underlying_price=price,
    )


def test_physical_long_call_resolves_and_applies_multiplier_delivery_atomically() -> None:
    option = _option()
    underlying = _underlying()
    processor = OptionLifecycleProcessor()
    instruction = processor.resolve(
        instrument=option,
        position_quantity=2.0,
        at=CUTOFF,
        calendar=_calendar(),
        reference=_reference(110.0),
        underlying=underlying,
    )

    assert instruction.available
    assert instruction.action == OptionLifecycleAction.PHYSICAL_EXERCISE
    assert instruction.underlying_quantity_delta == pytest.approx(200.0)
    assert instruction.cash_delta_quote == pytest.approx(-20_000.0)
    assert instruction.intrinsic_value == pytest.approx(10.0)

    ledger = PortfolioLedger("USD", 100_000.0)
    ledger.position(option.key).trade(2.0, 5.0)
    processor.apply(
        ledger=ledger,
        instruction=instruction,
        option=option,
        underlying=underlying,
        at=SETTLEMENT,
    )
    assert ledger.position(option.key).quantity == 0.0
    assert ledger.position(underlying.key).quantity == pytest.approx(200.0)
    assert ledger.position(underlying.key).last_price == pytest.approx(110.0)
    assert ledger.cash.balance("USD") == pytest.approx(80_000.0)
    with pytest.raises(ValueError, match="already applied"):
        processor.apply(
            ledger=ledger,
            instruction=instruction,
            option=option,
            underlying=underlying,
            at=SETTLEMENT,
        )


def test_physical_short_put_assignment_delivers_stock_and_debits_strike_cash() -> None:
    option = _option(right=OptionRight.PUT)
    underlying = _underlying()
    instruction = OptionLifecycleProcessor().resolve(
        instrument=option,
        position_quantity=-1.0,
        at=CUTOFF,
        calendar=_calendar(),
        reference=_reference(90.0),
        underlying=underlying,
    )
    assert instruction.action == OptionLifecycleAction.PHYSICAL_ASSIGNMENT
    assert instruction.underlying_quantity_delta == pytest.approx(100.0)
    assert instruction.cash_delta_quote == pytest.approx(-10_000.0)


def test_cash_settlement_and_automatic_lapse_are_explicit() -> None:
    processor = OptionLifecycleProcessor()
    cash_option = _option(settlement=SettlementType.CASH)
    settled = processor.resolve(
        instrument=cash_option,
        position_quantity=3.0,
        at=CUTOFF,
        calendar=_calendar(),
        reference=_reference(110.0),
    )
    assert settled.action == OptionLifecycleAction.CASH_SETTLEMENT
    assert settled.cash_delta_quote == pytest.approx(3_000.0)

    lapsed = processor.resolve(
        instrument=cash_option,
        position_quantity=3.0,
        at=CUTOFF,
        calendar=_calendar(),
        reference=_reference(99.0),
    )
    assert lapsed.action == OptionLifecycleAction.LAPSE
    assert lapsed.cash_delta_quote == 0.0
    assert lapsed.option_close_quantity == -3.0


def test_early_exercise_is_explicit_and_style_gated() -> None:
    early = datetime(2025, 1, 10, 20, tzinfo=timezone.utc)
    processor = OptionLifecycleProcessor()
    american = processor.resolve(
        instrument=_option(),
        position_quantity=1.0,
        at=early,
        calendar=_calendar(),
        reference=_reference(110.0, at=early),
        underlying=_underlying(),
        request_kind=OptionLifecycleRequestKind.EARLY_EXERCISE,
    )
    assert american.available
    assert not american.automatic

    european = processor.resolve(
        instrument=_option(style=OptionExerciseStyle.EUROPEAN),
        position_quantity=1.0,
        at=early,
        calendar=_calendar(OptionExerciseStyle.EUROPEAN),
        reference=_reference(110.0, at=early),
        underlying=_underlying(),
        request_kind=OptionLifecycleRequestKind.EARLY_EXERCISE,
    )
    assert not european.available
    assert any("does not permit early exercise" in reason for reason in european.reasons)


def test_lifecycle_fails_closed_for_missing_or_future_reference() -> None:
    processor = OptionLifecycleProcessor()
    unavailable = processor.resolve(
        instrument=_option(),
        position_quantity=1.0,
        at=CUTOFF,
        calendar=_calendar(),
        reference=None,
        underlying=_underlying(),
    )
    assert unavailable.action == OptionLifecycleAction.DATA_REQUIRED
    assert any("reference is missing" in reason for reason in unavailable.reasons)
    with pytest.raises(OptionLifecycleDataRequired, match="reference is missing"):
        processor.resolve(
            instrument=_option(),
            position_quantity=1.0,
            at=CUTOFF,
            calendar=_calendar(),
            reference=None,
            underlying=_underlying(),
            strict=True,
        )

    future = _reference(110.0, at=CUTOFF + timedelta(minutes=1))
    future_result = processor.resolve(
        instrument=_option(),
        position_quantity=1.0,
        at=CUTOFF,
        calendar=_calendar(),
        reference=future,
        underlying=_underlying(),
    )
    assert not future_result.available
    assert any("point-in-time" in reason for reason in future_result.reasons)


def test_lifecycle_instruction_has_stable_event_priority_and_identity() -> None:
    processor = OptionLifecycleProcessor()
    kwargs = dict(
        instrument=_option(settlement=SettlementType.CASH),
        position_quantity=1.0,
        at=CUTOFF,
        calendar=_calendar(),
        reference=_reference(110.0),
    )
    first = processor.resolve(**kwargs)
    second = processor.resolve(**kwargs)
    event = processor.to_event(first)
    assert first.lifecycle_id == second.lifecycle_id
    assert event.kind == EventKind.OPTION_LIFECYCLE
    assert event.event_id == first.lifecycle_id


def _margin_context() -> MarginContext:
    instrument = Instrument(
        "ESM5",
        AssetClass.FUTURE,
        "USD",
        instrument_id="CME:ESM5",
        multiplier=1.0,
    )
    return MarginContext(
        equity_base=10_000.0,
        positions={instrument.key: Position(instrument.key, 10.0, 100.0, 100.0)},
        instruments={instrument.key: instrument},
        fx=FXMatrix("USD"),
        as_of=datetime(2025, 1, 10, tzinfo=timezone.utc),
    )


def _parameter_set(method: MarginMethod, parameters: dict[str, object]) -> MarginParameterSet:
    return MarginParameterSet(
        method=method,
        version="2025.01",
        effective_from=datetime(2025, 1, 1, tzinfo=timezone.utc),
        available_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
        source="reference-fixture",
        official=True,
        parameters=parameters,
    )


def test_versioned_parameter_store_obeys_effective_and_available_times() -> None:
    store = VersionedMarginParameterStore()
    current = _parameter_set(MarginMethod.SPAN, {"contracts": {"CME:ESM5": {}}})
    future = MarginParameterSet(
        method=MarginMethod.SPAN,
        version="2025.02",
        effective_from=datetime(2025, 1, 5, tzinfo=timezone.utc),
        available_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
        source="future-file",
        parameters={"contracts": {"CME:ESM5": {}}},
    )
    store.register(current)
    store.register(future)
    assert store.resolve(MarginMethod.SPAN, _margin_context().as_of).version == "2025.01"
    with pytest.raises(LookupError, match="DATA REQUIRED"):
        store.resolve(
            MarginMethod.SPAN,
            _margin_context().as_of,
            version="2025.02",
        )


@pytest.mark.parametrize(
    ("method", "engine_type", "scenario_field", "scenarios"),
    [
        (MarginMethod.SPAN, SpanReferenceMarginEngine, "scenario_shocks", [-0.10, 0.10]),
        (
            MarginMethod.OCC_TIMS,
            OccTimsReferenceMarginEngine,
            "scenario_pnl_per_contract",
            [-10.0, 10.0],
        ),
        (
            MarginMethod.PORTFOLIO_MARGIN,
            PortfolioMarginReferenceEngine,
            "scenario_shocks",
            [-0.10, 0.10],
        ),
    ],
)
def test_scenario_margin_engines_are_versioned_fail_closed_reference_models(
    method: MarginMethod,
    engine_type: type,
    scenario_field: str,
    scenarios: list[float],
) -> None:
    context = _margin_context()
    store = VersionedMarginParameterStore()
    store.register(
        _parameter_set(
            method,
            {
                "contracts": {
                    "CME:ESM5": {scenario_field: scenarios},
                },
                "maintenance_factor": 0.75,
            },
        )
    )
    snapshot = engine_type(store).calculate(context)
    assert snapshot.available
    assert snapshot.initial_required_base == pytest.approx(100.0)
    assert snapshot.maintenance_required_base == pytest.approx(75.0)
    assert snapshot.parameter_version == "2025.01"
    assert len(snapshot.parameter_sha256 or "") == 64
    assert snapshot.reference_model
    assert not snapshot.certified

    missing = engine_type(VersionedMarginParameterStore()).calculate(context)
    assert not missing.available
    assert any("DATA REQUIRED" in reason for reason in missing.reasons)


def test_simm_reference_engine_requires_pit_sensitivities_and_uses_correlations() -> None:
    base = _margin_context()
    context = MarginContext(
        equity_base=base.equity_base,
        positions=base.positions,
        instruments=base.instruments,
        fx=base.fx,
        as_of=base.as_of,
        sensitivities={"CME:ESM5": {"DELTA": 1_000.0, "VEGA": 500.0}},
    )
    store = VersionedMarginParameterStore()
    store.register(
        _parameter_set(
            MarginMethod.SIMM,
            {
                "risk_weights": {"DELTA": 0.10, "VEGA": 0.20},
                "correlations": {"DELTA|VEGA": 0.50},
            },
        )
    )
    snapshot = SimmReferenceMarginEngine(store).calculate(context)
    assert snapshot.available
    assert snapshot.initial_required_base == pytest.approx(30000.0**0.5)
    assert snapshot.maintenance_required_base == snapshot.initial_required_base
    assert not snapshot.certified

    missing = SimmReferenceMarginEngine(store).calculate(base)
    assert not missing.available
    assert any("sensitivities missing" in reason for reason in missing.reasons)


def test_margin_registry_routes_explicit_method_without_universal_claim() -> None:
    context = _margin_context()
    store = VersionedMarginParameterStore()
    store.register(
        _parameter_set(
            MarginMethod.SPAN,
            {"contracts": {"CME:ESM5": {"scenario_shocks": [-0.1, 0.1]}}},
        )
    )
    registry = MarginEngineRegistry((SpanReferenceMarginEngine(store),))
    result = registry.calculate(MarginMethod.SPAN, context)
    assert result.method == "SPAN"
    with pytest.raises(LookupError, match="not registered"):
        registry.calculate(MarginMethod.SIMM, context)


def test_engine_routes_span_margin_through_pretrade_valuation_and_sdk_snapshot() -> None:
    instrument = Instrument(
        "ESM5",
        AssetClass.FUTURE,
        "USD",
        instrument_id="CME:ESM5",
        multiplier=1.0,
    )
    index = pd.date_range("2025-01-10", periods=3, freq="D", tz="UTC")
    bars = pd.DataFrame(
        {
            "open": [100.0, 100.0, 101.0],
            "high": [101.0, 101.0, 102.0],
            "low": [99.0, 99.0, 100.0],
            "close": [100.0, 100.0, 101.0],
            "volume": [100_000.0, 100_000.0, 100_000.0],
        },
        index=index,
    )
    store = VersionedMarginParameterStore()
    parameter_set = _parameter_set(
        MarginMethod.SPAN,
        {
            "contracts": {
                instrument.key: {"scenario_shocks": [-0.10, 0.10]}
            },
            "maintenance_factor": 0.75,
        },
    )
    store.register(parameter_set)
    result = UniversalBacktestEngine(
        security_master=SecurityMaster([instrument]),
        config=UniversalEngineConfig(
            initial_cash=100_000.0,
            commission_bps=0.0,
            spread_bps=0.0,
            slippage_bps=0.0,
            impact_bps_at_full_participation=0.0,
            fx_conversion_bps=0.0,
        ),
        margin_model=SpanReferenceMarginEngine(store),
    ).run(
        market_data={instrument.key: bars},
        target_weights=pd.DataFrame(
            {instrument.key: [1.0, float("nan"), float("nan")]},
            index=index,
        ),
    )

    assert result.status == "AVAILABLE"
    assert result.diagnostics["margin_method"] == "SPAN"
    assert result.diagnostics["margin_parameter_version"] == "2025.01"
    assert result.diagnostics["margin_parameter_sha256"] == parameter_set.source_sha256
    assert result.diagnostics["margin_reference_model"] is True
    assert result.diagnostics["margin_certified"] is False
    assert result.portfolio_snapshot is not None
    assert result.portfolio_snapshot.margin["available"] is True
    assert result.portfolio_snapshot.margin["initial_required_base"] > 0
    assert result.daily["margin_available"].all()


def test_engine_fails_closed_when_span_parameters_are_not_point_in_time() -> None:
    instrument = Instrument(
        "ESM5",
        AssetClass.FUTURE,
        "USD",
        instrument_id="CME:ESM5",
        multiplier=1.0,
    )
    index = pd.date_range("2025-01-10", periods=2, freq="D", tz="UTC")
    bars = pd.DataFrame(
        {
            "open": [100.0, 100.0],
            "high": [101.0, 101.0],
            "low": [99.0, 99.0],
            "close": [100.0, 100.0],
            "volume": [100_000.0, 100_000.0],
        },
        index=index,
    )
    result = UniversalBacktestEngine(
        security_master=SecurityMaster([instrument]),
        config=UniversalEngineConfig(initial_cash=100_000.0),
        margin_model=SpanReferenceMarginEngine(VersionedMarginParameterStore()),
    ).run(
        market_data={instrument.key: bars},
        target_weights=pd.DataFrame(
            {instrument.key: [1.0, float("nan")]}, index=index
        ),
    )

    assert result.status == "PARTIAL"
    assert result.fills.empty
    assert set(result.orders["status"]) == {"REJECTED"}
    assert result.diagnostics["margin_method"] == "SPAN"
    assert result.diagnostics["margin_parameter_version"] is None
    assert result.diagnostics["margin_certified"] is False
    assert any(
        "DATA REQUIRED" in reason
        for reason in result.diagnostics["lifecycle_gaps"]
    )


def test_engine_rejects_unresolved_post_settlement_insolvency() -> None:
    underlying = Instrument(
        "SPY", AssetClass.ETF, "USD", instrument_id="ARCX:SPY"
    )
    expiry = datetime(2025, 1, 3, 21, tzinfo=timezone.utc)
    option = Instrument(
        "SPY-C-100",
        AssetClass.OPTION,
        "USD",
        instrument_id="OPRA:SPY-C-100",
        underlying_symbol=underlying.key,
        multiplier=100.0,
        strike=100.0,
        option_right=OptionRight.CALL,
        expiry=expiry,
        settlement_type=SettlementType.CASH,
        initial_margin_rate=0.01,
        maintenance_margin_rate=0.01,
    )
    index = pd.DatetimeIndex(
        [
            datetime(2025, 1, 1, 21, tzinfo=timezone.utc),
            datetime(2025, 1, 2, 21, tzinfo=timezone.utc),
            expiry,
        ]
    )

    def bars(values: list[float]) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "open": values,
                "high": values,
                "low": values,
                "close": values,
                "volume": [1_000_000.0] * len(values),
            },
            index=index,
        )

    result = UniversalBacktestEngine(
        security_master=SecurityMaster([underlying, option]),
        config=UniversalEngineConfig(
            initial_cash=100_000.0,
            allow_short=True,
            commission_bps=0.0,
            spread_bps=0.0,
            slippage_bps=0.0,
            impact_bps_at_full_participation=0.0,
            fx_conversion_bps=0.0,
        ),
    ).run(
        market_data={
            underlying.key: bars([100.0, 100.0, 200.0]),
            option.key: bars([1.0, 1.0, 100.0]),
        },
        target_weights=pd.DataFrame(
            {option.key: [-3.0, float("nan"), float("nan")]},
            index=index,
        ),
    )

    assert result.status == "UNAVAILABLE"
    assert result.reason.startswith("RISK REJECTED")
    assert result.daily.iloc[-1]["nav"] < 0
    assert result.diagnostics["margin_calls"] >= 1
    assert result.diagnostics["portfolio_insolvent"] is True
    assert result.diagnostics["unresolved_margin_deficit"] is True


def test_adapters_accept_future_margin_packages_and_option_calendar_contracts() -> None:
    parameter_set = parse_margin_parameter_set(
        {
            "method": "SPAN",
            "version": "2025.01",
            "effective_from": "2025-01-01T00:00:00Z",
            "available_at": "2025-01-02T00:00:00Z",
            "source": "vendor-file",
            "parameters": {"contracts": {"CME:ESM5": {"scenario_shocks": [-0.1, 0.1]}}},
        }
    )
    assert parameter_set.method == MarginMethod.SPAN

    frame = pd.DataFrame(
        {
            "timestamp": ["2025-01-17T22:00:00Z"],
            "symbol": ["SPY-C-100"],
            "instrument_id": ["OPRA:SPY-C-100"],
            "asset_class": ["OPTION"],
            "quote_currency": ["USD"],
            "open": [10.0],
            "high": [10.0],
            "low": [10.0],
            "close": [10.0],
            "underlying_symbol": ["ARCX:SPY"],
            "expiry": [EXPIRY.isoformat()],
            "strike": [100.0],
            "option_right": ["CALL"],
            "settlement_type": ["PHYSICAL"],
            "multiplier": [100.0],
            "option_exercise_style": ["AMERICAN"],
            "option_calendar_id": ["OPRA-2025-01-17"],
            "option_calendar_timezone": ["America/New_York"],
            "exercise_cutoff_at": [CUTOFF.isoformat()],
            "settlement_at": [SETTLEMENT.isoformat()],
            "calendar_source": ["exchange-calendar"],
            "calendar_source_version": ["2025.01"],
            "calendar_available_at": ["2025-01-01T00:00:00Z"],
            "automatic_exercise_threshold": [0.01],
            "deliverable_quantity": [100.0],
        }
    )
    dataset = parse_long_dataset(frame, base_currency="USD")
    option = dataset.security_master.get("OPRA:SPY-C-100")
    assert option.option_exercise_style == OptionExerciseStyle.AMERICAN
    assert option.deliverable_quantity == 100.0
    assert dataset.option_calendars["OPRA-2025-01-17"].settlement_at == SETTLEMENT


def test_engine_applies_physical_option_lifecycle_at_contract_settlement() -> None:
    underlying = _underlying()
    option = _option()
    index = pd.DatetimeIndex(
        [
            datetime(2025, 1, 15, 21, tzinfo=timezone.utc),
            datetime(2025, 1, 16, 21, tzinfo=timezone.utc),
            EXPIRY,
        ]
    )

    def bars(values: list[float]) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "open": values,
                "high": values,
                "low": values,
                "close": values,
                "volume": [1_000_000.0] * len(values),
            },
            index=index,
        )

    result = UniversalBacktestEngine(
        security_master=SecurityMaster([underlying, option]),
        config=UniversalEngineConfig(
            initial_cash=100_000.0,
            commission_bps=0.0,
            spread_bps=0.0,
            slippage_bps=0.0,
            impact_bps_at_full_participation=0.0,
            fx_conversion_bps=0.0,
        ),
    ).run(
        market_data={
            underlying.key: bars([100.0, 100.0, 110.0]),
            option.key: bars([5.0, 5.0, 10.0]),
        },
        target_weights=pd.DataFrame(
            {option.key: [0.01, float("nan"), float("nan")]}, index=index
        ),
        option_calendars={_calendar().calendar_id: _calendar()},
    )

    positions = result.positions.set_index("instrument_id")
    assert result.status == "AVAILABLE"
    assert option.key not in positions.index
    assert positions.loc[underlying.key, "quantity"] == pytest.approx(200.0)
    assert result.cash.set_index("currency").loc["USD", "settled"] == pytest.approx(
        79_000.0
    )
    assert "option_physical_exercise" in set(result.events["kind"])
    lifecycle = result.diagnostics["physical_option_lifecycle"]
    assert lifecycle["instructions_resolved"] == 1
    assert lifecycle["instructions_applied"] == 1
    assert lifecycle["physical_actions_applied"] == 1
    assert lifecycle["data_required"] == 0
