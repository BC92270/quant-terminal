from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .contracts import EngineResult
from .regimes import REGIMES


COLORS = {
    "bg": "#07121b",
    "grid": "rgba(120,165,186,.12)",
    "text": "#a9bdc8",
    "cyan": "#24c9e8",
    "blue": "#4a8fff",
    "green": "#2ed6a1",
    "red": "#ff6174",
    "amber": "#f4bf58",
    "purple": "#a88bff",
}

REGIME_COLORS = {
    "BULL_TREND": "rgba(46,214,161,.09)",
    "BEAR_TREND": "rgba(255,97,116,.09)",
    "RANGE": "rgba(98,139,161,.07)",
    "STRESS": "rgba(244,191,88,.11)",
}


def _base_layout(fig: go.Figure, height: int, title: str | None = None) -> go.Figure:
    fig.update_layout(
        height=height,
        title=title,
        paper_bgcolor=COLORS["bg"],
        plot_bgcolor=COLORS["bg"],
        font=dict(color=COLORS["text"], family="Inter, Arial, sans-serif", size=11),
        margin=dict(l=45, r=28, t=48 if title else 24, b=34),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0, font=dict(size=10)),
    )
    fig.update_xaxes(gridcolor=COLORS["grid"], zeroline=False, rangeslider_visible=False)
    fig.update_yaxes(gridcolor=COLORS["grid"], zeroline=False)
    return fig


def _add_regime_shading(fig: go.Figure, regimes: pd.DataFrame, row: int = 1) -> None:
    if regimes.empty:
        return
    run_start = 0
    states = regimes["state"].tolist()
    dates = pd.to_datetime(regimes["date"]).tolist()
    for index in range(1, len(states) + 1):
        if index == len(states) or states[index] != states[run_start]:
            fig.add_vrect(
                x0=dates[run_start],
                x1=dates[min(index, len(dates) - 1)],
                fillcolor=REGIME_COLORS.get(states[run_start], "rgba(255,255,255,.03)"),
                line_width=0,
                layer="below",
                row=row,
                col=1,
            )
            run_start = index


def price_decision_chart(result: EngineResult, lookback: int = 260) -> go.Figure:
    frame = result.frame.tail(lookback).copy()
    regimes = result.regimes[result.regimes["date"].isin(frame["date"])].copy()
    figure = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.035,
        row_heights=[0.62, 0.19, 0.19],
    )
    _add_regime_shading(figure, regimes, row=1)

    has_ohlc = frame[["open", "high", "low"]].notna().all(axis=1).mean() > 0.8
    if has_ohlc:
        figure.add_trace(
            go.Candlestick(
                x=frame["date"],
                open=frame["open"],
                high=frame["high"],
                low=frame["low"],
                close=frame["close"],
                name=result.ticker,
                increasing_line_color=COLORS["green"],
                decreasing_line_color=COLORS["red"],
                increasing_fillcolor="rgba(46,214,161,.45)",
                decreasing_fillcolor="rgba(255,97,116,.45)",
            ),
            row=1,
            col=1,
        )
    else:
        figure.add_trace(go.Scatter(x=frame["date"], y=frame["close"], name="Close", line=dict(color=COLORS["cyan"], width=1.5)), row=1, col=1)
    for column, name, color, width in (
        ("ema_20", "EMA20", COLORS["blue"], 1.3),
        ("ema_50", "EMA50", COLORS["amber"], 1.1),
        ("sma_200", "SMA200", COLORS["purple"], 1.0),
    ):
        if column in frame:
            figure.add_trace(go.Scatter(x=frame["date"], y=frame[column], name=name, line=dict(color=color, width=width)), row=1, col=1)

    ticket = result.decision
    levels = (
        (ticket.entry_low, "Entry low", COLORS["cyan"], "dot"),
        (ticket.entry_high, "Entry high", COLORS["cyan"], "dot"),
        (ticket.stop, "Invalidation", COLORS["red"], "dash"),
        (ticket.target_1, "Target 1", COLORS["green"], "dash"),
    )
    for value, label, color, dash in levels:
        if value is not None:
            figure.add_hline(y=value, line_color=color, line_dash=dash, line_width=1, annotation_text=label, annotation_font_color=color, row=1, col=1)

    future_dates = pd.bdate_range(frame["date"].iloc[-1] + timedelta(days=1), periods=result.ensemble.horizon)
    if len(future_dates):
        start = result.price
        mean_end = start * (1 + result.ensemble.expected_return)
        lower_end = start * (1 + result.ensemble.lower)
        upper_end = start * (1 + result.ensemble.upper)
        figure.add_trace(
            go.Scatter(x=[frame["date"].iloc[-1], future_dates[-1]], y=[start, upper_end], line=dict(width=0), hoverinfo="skip", showlegend=False),
            row=1,
            col=1,
        )
        figure.add_trace(
            go.Scatter(
                x=[frame["date"].iloc[-1], future_dates[-1]],
                y=[start, lower_end],
                fill="tonexty",
                fillcolor="rgba(36,201,232,.10)",
                line=dict(width=0),
                name="80% model band",
                hoverinfo="skip",
            ),
            row=1,
            col=1,
        )
        figure.add_trace(
            go.Scatter(x=[frame["date"].iloc[-1], future_dates[-1]], y=[start, mean_end], name="Ensemble path", line=dict(color=COLORS["cyan"], width=2, dash="dot")),
            row=1,
            col=1,
        )

    momentum = frame["momentum_composite"].fillna(0)
    momentum_colors = np.where(momentum >= 0, COLORS["green"], COLORS["red"])
    figure.add_trace(go.Bar(x=frame["date"], y=momentum, name="Momentum z", marker_color=momentum_colors, opacity=0.7), row=2, col=1)
    figure.add_hline(y=0, line_color="rgba(255,255,255,.3)", line_width=1, row=2, col=1)
    figure.add_trace(go.Scatter(x=frame["date"], y=frame["trend_quality"], name="Trend quality", line=dict(color=COLORS["blue"], width=1.2)), row=2, col=1)

    for regime, color in zip(REGIMES, (COLORS["green"], COLORS["red"], "#718c9b", COLORS["amber"])):
        figure.add_trace(
            go.Scatter(
                x=regimes["date"],
                y=regimes[regime],
                name=regime.replace("_", " ").title(),
                stackgroup="regime",
                line=dict(width=0.7, color=color),
            ),
            row=3,
            col=1,
        )

    figure.update_yaxes(title_text="Price", row=1, col=1)
    figure.update_yaxes(title_text="Signal", range=[-4, 4], row=2, col=1)
    figure.update_yaxes(title_text="Regime p", range=[0, 1], tickformat=".0%", row=3, col=1)
    return _base_layout(figure, 690, f"{result.ticker} · price structure, momentum and filtered regimes")


def model_consensus_chart(result: EngineResult) -> go.Figure:
    ready = [forecast for forecast in result.forecasts if forecast.status == "READY" and forecast.expected_return is not None]
    figure = go.Figure()
    if not ready:
        return _base_layout(figure, 340, "Model forecasts unavailable")
    means = [forecast.expected_return for forecast in ready]
    lower = [forecast.lower for forecast in ready]
    upper = [forecast.upper for forecast in ready]
    colors = [COLORS["green"] if value >= 0 else COLORS["red"] for value in means]
    figure.add_trace(
        go.Bar(
            y=[forecast.name for forecast in ready],
            x=means,
            orientation="h",
            marker_color=colors,
            text=[f"{value:+.2%}" for value in means],
            textposition="auto",
            error_x=dict(
                type="data",
                symmetric=False,
                array=[max((hi or mean) - mean, 0) for hi, mean in zip(upper, means)],
                arrayminus=[max(mean - (lo or mean), 0) for lo, mean in zip(lower, means)],
                color="#a9bdc8",
                thickness=1,
            ),
        )
    )
    figure.add_vline(x=0, line_color="rgba(255,255,255,.45)", line_width=1)
    figure.update_xaxes(tickformat=".1%", title=f"Expected {result.ensemble.horizon}D return · 80% interval")
    return _base_layout(figure, 360, "Heterogeneous model consensus")


def regime_probability_chart(result: EngineResult, lookback: int = 220) -> go.Figure:
    data = result.regimes.tail(lookback)
    figure = go.Figure()
    for regime, color in zip(REGIMES, (COLORS["green"], COLORS["red"], "#718c9b", COLORS["amber"])):
        figure.add_trace(
            go.Scatter(x=data["date"], y=data[regime], name=regime.replace("_", " ").title(), stackgroup="one", line=dict(width=0.8, color=color))
        )
    figure.update_yaxes(range=[0, 1], tickformat=".0%", title="Filtered probability")
    return _base_layout(figure, 420, "Causal sticky-regime probabilities")


def equity_curve_chart(result: EngineResult) -> go.Figure:
    data = result.equity_curve
    figure = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.72, 0.28], vertical_spacing=0.05)
    if not data.empty:
        figure.add_trace(go.Scatter(x=data["date"], y=data["strategy"], name="Causal diagnostic", line=dict(color=COLORS["cyan"], width=2)), row=1, col=1)
        figure.add_trace(go.Scatter(x=data["date"], y=data["buy_hold"], name="Buy & hold", line=dict(color="#718c9b", width=1.2)), row=1, col=1)
        figure.add_trace(go.Scatter(x=data["date"], y=data["drawdown"], name="Strategy drawdown", fill="tozeroy", line=dict(color=COLORS["red"], width=1)), row=2, col=1)
    figure.update_yaxes(title="Growth", row=1, col=1)
    figure.update_yaxes(title="DD", tickformat=".0%", row=2, col=1)
    return _base_layout(figure, 490, "Walk-forward causal diagnostic · costs included")

