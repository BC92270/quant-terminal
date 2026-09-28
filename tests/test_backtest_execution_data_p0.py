from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest_institutional.data_catalog import assess_market_data
from backtest_institutional.execution import ExecutionModelConfig, simulate_execution
from backtest_institutional.types import AvailabilityState, ValidationState


def _bars(n: int = 40, *, volume: float = 1_000_000.0) -> pd.DataFrame:
    index = pd.bdate_range("2024-01-02", periods=n)
    close = 100.0 + np.linspace(0.0, 3.0, n)
    open_ = close - 0.10
    return pd.DataFrame(
        {
            "Open": open_,
            "High": np.maximum(open_, close) + 0.50,
            "Low": np.minimum(open_, close) - 0.50,
            "Close": close,
            "Volume": volume,
        },
        index=index,
    )


def _zero_cost_constant(**overrides: object) -> ExecutionModelConfig:
    values: dict[str, object] = {
        "model": "constant",
        "commission_bps": 0.0,
        "spread_bps": 0.0,
        "slippage_bps": 0.0,
    }
    values.update(overrides)
    return ExecutionModelConfig(**values)


def test_open_fill_is_invariant_to_same_bar_close_and_volume() -> None:
    bars = _bars()
    target = pd.Series(0.0, index=bars.index)
    target.iloc[9:] = 0.40
    config = ExecutionModelConfig(
        model="square_root",
        commission_bps=0.0,
        spread_bps=0.0,
        slippage_bps=0.0,
        max_participation=0.10,
        adv_lookback_bars=5,
        volatility_lookback_bars=5,
    )

    baseline = simulate_execution(bars, target, symbol="TEST", config=config)
    fill_time = pd.Timestamp(baseline.fills[0].timestamp)

    perturbed = bars.copy()
    perturbed.loc[fill_time:, "Close"] *= 3.0
    perturbed.loc[fill_time:, "High"] = np.maximum(
        perturbed.loc[fill_time:, "High"], perturbed.loc[fill_time:, "Close"] + 1.0
    )
    perturbed.loc[fill_time:, "Volume"] = 25.0
    replay = simulate_execution(perturbed, target, symbol="TEST", config=config)

    first = baseline.fills[0]
    replay_first = replay.fills[0]
    assert replay_first.timestamp == first.timestamp
    assert replay_first.quantity == pytest.approx(first.quantity)
    assert replay_first.fill_price == pytest.approx(first.fill_price)
    assert replay_first.participation == pytest.approx(first.participation)
    assert replay.daily.loc[fill_time, "adv_forecast"] == pytest.approx(
        baseline.daily.loc[fill_time, "adv_forecast"]
    )
    assert replay.daily.loc[fill_time, "volatility_forecast"] == pytest.approx(
        baseline.daily.loc[fill_time, "volatility_forecast"]
    )
    assert baseline.diagnostics["forecast_is_causal"] is True
    assert baseline.diagnostics["market_observation_lag_bars"] == 1


def test_target_timing_contract_avoids_an_implicit_double_lag() -> None:
    bars = _bars(12)
    target = pd.Series(0.0, index=bars.index)
    target.iloc[5:] = 0.5
    config = _zero_cost_constant(
        target_timing="pre_lagged_target",
        signal_latency_bars=0,
    )
    result = simulate_execution(bars, target, symbol="TEST", config=config)
    assert pd.Timestamp(result.fills[0].timestamp) == bars.index[5]
    assert result.diagnostics["target_timing"] == "pre_lagged_target"

    with pytest.raises(ValueError, match="signal_latency_bars"):
        ExecutionModelConfig(target_timing="raw_signal", signal_latency_bars=0).validate()


def test_first_bar_return_and_drawdown_are_anchored_to_initial_capital() -> None:
    index = pd.bdate_range("2024-03-01", periods=3)
    bars = pd.DataFrame(
        {
            "Open": [100.0, 90.0, 90.0],
            "High": [101.0, 91.0, 91.0],
            "Low": [89.0, 89.0, 89.0],
            "Close": [90.0, 90.0, 90.0],
        },
        index=index,
    )
    target = pd.Series(1.0, index=index)
    result = simulate_execution(
        bars,
        target,
        symbol="TEST",
        config=_zero_cost_constant(
            target_timing="pre_lagged_target",
            signal_latency_bars=0,
        ),
    )
    assert result.daily.iloc[0]["nav"] == pytest.approx(900_000.0)
    assert result.daily.iloc[0]["return"] == pytest.approx(-0.10)
    assert result.daily.iloc[0]["drawdown"] == pytest.approx(-0.10)


def test_raw_split_and_dividend_are_applied_without_false_drawdown() -> None:
    bars = _bars(8).drop(columns=["Volume"])
    bars.loc[:, ["Open", "High", "Low", "Close"]] = [100.0, 100.5, 99.5, 100.0]
    split_day = bars.index[4]
    dividend_day = bars.index[5]
    bars.loc[split_day:, ["Open", "High", "Low", "Close"]] = [50.0, 50.5, 49.5, 50.0]
    bars["Dividend"] = 0.0
    bars["Split"] = 0.0
    bars.loc[split_day, "Split"] = 2.0
    bars.loc[dividend_day, "Dividend"] = 1.0
    target = pd.Series(1.0, index=bars.index)

    result = simulate_execution(
        bars,
        target,
        symbol="TEST",
        config=_zero_cost_constant(corporate_action_policy="require", price_basis="raw"),
    )

    assert result.status == AvailabilityState.AVAILABLE
    assert result.daily.loc[split_day, "nav"] == pytest.approx(1_000_000.0)
    assert result.daily.loc[split_day, "turnover_notional"] == pytest.approx(0.0)
    assert result.diagnostics["split_events_applied"] == 1
    assert result.diagnostics["dividend_events_applied"] == 1
    assert result.diagnostics["corporate_action_cash"] == pytest.approx(20_000.0)

    missing_actions = simulate_execution(
        bars.drop(columns=["Dividend", "Split"]),
        target,
        symbol="TEST",
        config=_zero_cost_constant(corporate_action_policy="require", price_basis="raw"),
    )
    assert missing_actions.status == AvailabilityState.UNAVAILABLE
    assert missing_actions.diagnostics["fail_closed"] is True


def test_adjusted_prices_do_not_double_count_embedded_corporate_actions() -> None:
    bars = _bars(8).drop(columns=["Volume"])
    bars["Dividend"] = 0.0
    bars["Split"] = 0.0
    bars.loc[bars.index[4], "Dividend"] = 5.0
    bars.loc[bars.index[5], "Split"] = 2.0
    bars.attrs["price_basis"] = "adjusted_total_return"
    target = pd.Series(1.0, index=bars.index)

    adjusted = simulate_execution(
        bars,
        target,
        symbol="TEST",
        config=_zero_cost_constant(price_basis="adjusted_total_return"),
    )
    assert adjusted.status == AvailabilityState.AVAILABLE
    assert adjusted.diagnostics["corporate_action_cash"] == 0.0
    assert adjusted.diagnostics["split_events_applied"] == 0

    mismatched = simulate_execution(
        bars,
        target,
        symbol="TEST",
        config=_zero_cost_constant(price_basis="raw"),
    )
    assert mismatched.status == AvailabilityState.UNAVAILABLE
    assert "price_basis conflicts" in mismatched.reason


def test_short_gate_requires_prior_shortable_locate_and_borrow() -> None:
    bars = _bars(12).drop(columns=["Volume"])
    bars["Shortable"] = False
    bars["Locate"] = False
    bars["Borrow Rate"] = 100.0
    target = pd.Series(-0.50, index=bars.index)
    config = _zero_cost_constant(short_sale_policy="require", require_locate=True)

    blocked = simulate_execution(bars, target, symbol="TEST", config=config)
    assert blocked.status == AvailabilityState.UNAVAILABLE
    assert blocked.diagnostics["short_gate_failures"] > 0
    assert not bool((blocked.daily["position"] < 0).any())
    assert any(order.status == "REJECTED" for order in blocked.orders)

    eligible = bars.copy()
    eligible["Shortable"] = True
    eligible["Locate"] = True
    allowed = simulate_execution(eligible, target, symbol="TEST", config=config)
    assert allowed.status == AvailabilityState.AVAILABLE
    assert bool((allowed.daily["position"] < 0).any())
    assert float(allowed.daily["borrow_cost"].sum()) > 0.0


def test_lost_locate_never_blocks_a_risk_reducing_short_cover() -> None:
    bars = _bars(12).drop(columns=["Volume"])
    bars["Shortable"] = True
    bars["Locate"] = True
    bars["Borrow Rate"] = 100.0
    # The locate disappears before a partial cover and then a full close.
    bars.loc[bars.index[4]:, "Shortable"] = False
    bars.loc[bars.index[4]:, "Locate"] = False
    target = pd.Series(0.0, index=bars.index)
    target.iloc[2:5] = -1.0
    target.iloc[5] = -0.5
    config = _zero_cost_constant(short_sale_policy="require", require_locate=True)

    result = simulate_execution(bars, target, symbol="TEST", config=config)

    cover_day = bars.index[5]
    cover_orders = [
        order for order in result.orders
        if pd.Timestamp(order.timestamp) == cover_day and order.side == "BUY"
    ]
    assert cover_orders and cover_orders[0].status == "FILLED"
    assert abs(result.daily.loc[cover_day, "position"]) < abs(
        result.daily.loc[bars.index[4], "position"]
    )
    assert result.diagnostics["short_gate_failures"] == 0
    assert result.status == AvailabilityState.AVAILABLE


def test_catalog_propagates_source_quality_and_adjusted_price_basis() -> None:
    adjusted = _bars(20)
    adjusted.attrs["price_basis"] = "adjusted_total_return"
    adjusted.attrs["data_quality_issues"] = ["volume provenance inferred"]
    assessment = assess_market_data(
        adjusted,
        symbol="TEST",
        source="unit",
        required_capabilities=("corporate_actions",),
    )
    assert assessment.price_basis == "adjusted_total_return"
    assert assessment.capabilities["corporate_actions"].state == AvailabilityState.ESTIMATED
    assert assessment.verdict == ValidationState.WARN
    assert any("source quality" in issue for issue in assessment.issues)

    raw = _bars(20)
    raw.attrs["price_basis"] = "raw"
    missing = assess_market_data(
        raw,
        symbol="TEST",
        source="unit",
        required_capabilities=("corporate_actions", "short_financing"),
    )
    assert missing.capabilities["corporate_actions"].state == AvailabilityState.UNAVAILABLE
    assert missing.capabilities["short_financing"].state == AvailabilityState.UNAVAILABLE
    assert missing.verdict == ValidationState.UNAVAILABLE
    assert assessment.fingerprint != missing.fingerprint

    incomplete_core = _bars(20)
    incomplete_core.loc[incomplete_core.index[4], "Close"] = np.nan
    invalid = assess_market_data(incomplete_core, symbol="TEST", source="unit")
    assert invalid.verdict == ValidationState.FAIL
    invalid_execution = simulate_execution(
        incomplete_core,
        pd.Series(0.5, index=incomplete_core.index),
        symbol="TEST",
        config=_zero_cost_constant(),
    )
    assert invalid_execution.status == AvailabilityState.UNAVAILABLE


def test_frequency_calendar_and_settlement_limit_are_explicit() -> None:
    bars = _bars(8).drop(columns=["Volume"])
    target = pd.Series(0.5, index=bars.index)
    result = simulate_execution(
        bars,
        target,
        symbol="TEST",
        config=_zero_cost_constant(
            bar_frequency="1wk",
            periods_per_year=52.0,
            trading_calendar="CALENDAR_DAY",
            settlement_days=2,
        ),
    )
    assert result.diagnostics["bar_frequency"] == "1wk"
    assert result.diagnostics["periods_per_year"] == 52.0
    assert result.diagnostics["trading_calendar"] == "CALENDAR_DAY"
    assert result.diagnostics["cash_settlement_enforced"] is False
    assert "trade-date cash accounting proxy" in result.diagnostics["settlement_assumption"]
