from __future__ import annotations

import numpy as np
import pandas as pd

from backtest_lab import BacktestConfig, _build_signal, _rsi, _run_backtest


def _bars(close: np.ndarray) -> pd.DataFrame:
    index = pd.bdate_range("2024-01-02", periods=len(close))
    close = np.asarray(close, dtype=float)
    frame = pd.DataFrame(
        {
            "open": close,
            "high": close * 1.002,
            "low": close * 0.998,
            "close": close,
            "volume": 2_000_000.0,
        },
        index=index,
    )
    frame.attrs.update(
        price_basis="adjusted_total_return",
        periods_per_year=252,
        interval_label="1d",
    )
    return frame


def _cfg(strategy: str, **overrides: object) -> BacktestConfig:
    values: dict[str, object] = {
        "strategy": strategy,
        "capital": 100_000.0,
        "position_pct": 100.0,
        "fee_bps": 0.0,
        "slippage_bps": 0.0,
        "fast_ma": 3,
        "slow_ma": 7,
        "breakout_window": 5,
        "rsi_window": 5,
        "rsi_entry": 30.0,
        "rsi_exit": 55.0,
        "vol_window": 5,
        "vol_threshold": 5.0,
        "allow_short": False,
        "benchmark_mode": "Ticker Buy & Hold",
        "asset_ticker": "SYNTH",
        "periods_per_year": 252,
        "interval_label": "1d",
    }
    values.update(overrides)
    return BacktestConfig(**values)


def _manual_wilder_rsi(close: pd.Series, window: int) -> pd.Series:
    delta = close.diff()
    gains = delta.clip(lower=0.0)
    losses = -delta.clip(upper=0.0)
    alpha = 1.0 / window
    avg_gain = np.full(len(close), np.nan)
    avg_loss = np.full(len(close), np.nan)
    for i in range(1, len(close)):
        gain = float(gains.iloc[i])
        loss = float(losses.iloc[i])
        if i == 1:
            avg_gain[i] = gain
            avg_loss[i] = loss
        else:
            avg_gain[i] = alpha * gain + (1.0 - alpha) * avg_gain[i - 1]
            avg_loss[i] = alpha * loss + (1.0 - alpha) * avg_loss[i - 1]
    output = np.full(len(close), 50.0)
    for i in range(1, len(close)):
        if avg_loss[i] == 0.0 and avg_gain[i] > 0.0:
            output[i] = 100.0
        elif avg_loss[i] == 0.0 and avg_gain[i] == 0.0:
            output[i] = 50.0
        else:
            rs = avg_gain[i] / avg_loss[i]
            output[i] = 100.0 - 100.0 / (1.0 + rs)
    return pd.Series(output, index=close.index)


def test_sma_backtest_matches_a_hand_calculated_net_return_ledger() -> None:
    close = np.r_[
        np.full(12, 100.0),
        np.linspace(100.0, 135.0, 28),
        np.linspace(135.0, 82.0, 40),
    ]
    bars = _bars(close)
    cfg = _cfg(
        "SMA Trend",
        capital=250_000.0,
        position_pct=65.0,
        fee_bps=2.5,
        slippage_bps=4.5,
        fast_ma=3,
        slow_ma=7,
    )

    result = _run_backtest(bars, cfg)
    assert "error" not in result
    actual = result["data"]

    fast = bars["close"].rolling(3).mean()
    slow = bars["close"].rolling(7).mean()
    manual_signal = (fast > slow).astype(float).shift(1).fillna(0.0)
    manual_exposure = manual_signal * 0.65
    manual_returns = bars["close"].pct_change().fillna(0.0)
    manual_gross = manual_exposure * manual_returns
    manual_turnover = manual_exposure.diff().abs().fillna(manual_exposure.abs())
    manual_costs = manual_turnover * 7.0 / 10_000.0
    manual_net = manual_gross - manual_costs
    manual_equity = 250_000.0 * (1.0 + manual_net).cumprod()

    np.testing.assert_allclose(actual["signal"], manual_signal, atol=1e-14)
    np.testing.assert_allclose(actual["exposure"], manual_exposure, atol=1e-14)
    np.testing.assert_allclose(actual["gross_return"], manual_gross, atol=1e-14)
    np.testing.assert_allclose(actual["costs"], manual_costs, atol=1e-14)
    np.testing.assert_allclose(actual["strategy_return"], manual_net, atol=1e-14)
    np.testing.assert_allclose(actual["equity"], manual_equity, rtol=1e-13)
    np.testing.assert_allclose(
        [result["metrics"]["Total Return"]],
        [manual_equity.iloc[-1] / 250_000.0 - 1.0],
        rtol=1e-13,
    )


def test_breakout_uses_only_the_prior_window_and_executes_one_bar_later() -> None:
    close = np.r_[
        np.full(10, 100.0),
        np.linspace(101.0, 128.0, 25),
        np.linspace(127.0, 78.0, 45),
    ]
    bars = _bars(close)
    cfg = _cfg("Breakout", breakout_window=5, allow_short=True)

    signal = _build_signal(bars, cfg)
    prior_high = bars["close"].shift(1).rolling(5).max()
    prior_low = bars["close"].shift(1).rolling(5).min()
    events = pd.Series(0.0, index=bars.index)
    events[bars["close"] > prior_high] = 1.0
    events[bars["close"] < prior_low] = -1.0
    manual = events.replace(0.0, np.nan).ffill().fillna(0.0).shift(1).fillna(0.0)

    pd.testing.assert_series_equal(signal, manual)
    first_breakout = events.ne(0.0).idxmax()
    first_location = bars.index.get_loc(first_breakout)
    assert signal.iloc[first_location] == 0.0
    assert signal.iloc[first_location + 1] == events.iloc[first_location]


def test_rsi_mean_reversion_matches_an_independent_wilder_oracle() -> None:
    close = np.r_[
        np.full(5, 100.0),
        np.linspace(99.0, 72.0, 32),
        np.linspace(73.0, 125.0, 43),
    ]
    bars = _bars(close)
    cfg = _cfg("RSI Mean Reversion", rsi_window=5, rsi_entry=30.0, rsi_exit=55.0)

    manual_rsi = _manual_wilder_rsi(bars["close"], 5)
    np.testing.assert_allclose(_rsi(bars["close"], 5), manual_rsi, atol=1e-12)

    raw = pd.Series(np.nan, index=bars.index)
    raw[manual_rsi < 30.0] = 1.0
    raw[manual_rsi > 55.0] = 0.0
    manual_signal = raw.ffill().fillna(0.0).shift(1).fillna(0.0)
    actual = _build_signal(bars, cfg)
    pd.testing.assert_series_equal(actual, manual_signal)

    manual_state = raw.ffill().fillna(0.0)
    raw_exit = manual_state.diff().lt(0.0)
    exit_time = raw_exit[raw_exit].index[0]
    exit_location = bars.index.get_loc(exit_time)
    assert actual.iloc[exit_location] == 1.0
    assert actual.iloc[exit_location + 1] == 0.0


def test_rsi_boundary_is_standard_for_monotonic_and_flat_prices() -> None:
    index = pd.bdate_range("2024-01-02", periods=12)
    rising = pd.Series(np.arange(100.0, 112.0), index=index)
    flat = pd.Series(100.0, index=index)
    assert (_rsi(rising, 5).iloc[1:] == 100.0).all()
    assert (_rsi(flat, 5) == 50.0).all()
