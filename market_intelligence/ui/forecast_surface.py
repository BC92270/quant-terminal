"""Probabilistic forecast distribution and uncertainty view."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ..contracts import WorkspaceSnapshot
from ..demo import forecasts_frame
from .common import AMBER, CYAN, GREEN, RED, bounded_table, card, provenance, section_header, style_figure


def _fan(frame: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=frame["Horizon"], y=frame["Q95"], line=dict(color="rgba(85,232,245,.18)"), name="Q95", hovertemplate="%{x}<br>Q95 %{y:+.2%}<extra></extra>"))
    fig.add_trace(go.Scatter(x=frame["Horizon"], y=frame["Q05"], line=dict(color="rgba(85,232,245,.18)"), fill="tonexty", fillcolor="rgba(85,232,245,.08)", name="Q05–Q95", hovertemplate="%{x}<br>Q05 %{y:+.2%}<extra></extra>"))
    fig.add_trace(go.Scatter(x=frame["Horizon"], y=frame["Q75"], line=dict(color="rgba(88,223,172,.35)"), name="Q75", hovertemplate="%{x}<br>Q75 %{y:+.2%}<extra></extra>"))
    fig.add_trace(go.Scatter(x=frame["Horizon"], y=frame["Q25"], line=dict(color="rgba(88,223,172,.35)"), fill="tonexty", fillcolor="rgba(88,223,172,.10)", name="Q25–Q75", hovertemplate="%{x}<br>Q25 %{y:+.2%}<extra></extra>"))
    fig.add_trace(go.Scatter(x=frame["Horizon"], y=frame["Q50"], mode="lines+markers", line=dict(color=CYAN, width=2.6), marker=dict(size=8), name="Median", hovertemplate="%{x}<br>Median %{y:+.2%}<extra></extra>"))
    fig.add_trace(go.Scatter(x=frame["Horizon"], y=frame["Expected return"], mode="lines+markers", line=dict(color=AMBER, width=1.8, dash="dot"), marker=dict(size=7), name="Expected return", hovertemplate="%{x}<br>Mean %{y:+.2%}<extra></extra>"))
    fig.add_hline(y=0.0, line_color="rgba(225,240,244,.20)")
    fig.update_yaxes(tickformat="+.1%")
    return style_figure(fig, title="Empirical return distribution surface · fixture history", height=410)


def render_forecast_surface(snapshot: WorkspaceSnapshot) -> None:
    section_header("FUSION DESK / 10", "Forecast Surface", "DISTRIBUTIONS · CALIBRATION · MODEL DISAGREEMENT")
    frame = forecasts_frame(snapshot)
    short = frame.iloc[0]
    cards = st.columns(5)
    with cards[0]:
        card("10m P(up)", f"{short['P(up)']:.0%}" if pd.notna(short["P(up)"]) else "N/A", "Empirical frequency", tone="cyan")
    with cards[1]:
        card("10m expected return", f"{short['Expected return']:+.2%}" if pd.notna(short["Expected return"]) else "N/A", "Unconditional fixture mean")
    with cards[2]:
        card("10m tail band", f"{short['Q05']:+.2%} / {short['Q95']:+.2%}", "Q05 / Q95")
    with cards[3]:
        card("Calibration", "NOT CALIBRATED", "No realized shadow outcomes", tone="red")
    with cards[4]:
        card("Promotion", "CLOSED", "Baseline is not champion-eligible", tone="amber")
    left, right = st.columns([1.55, 1.0], gap="medium")
    with left:
        st.plotly_chart(_fan(frame), width="stretch", config={"displaylogo": False})
    with right:
        probability = go.Figure(go.Bar(x=frame["Horizon"], y=frame["P(up)"], marker_color=[GREEN if value >= .5 else RED for value in frame["P(up)"]], text=[f"{value:.0%}" for value in frame["P(up)"]], textposition="outside"))
        probability.add_hline(y=.5, line_color=AMBER, line_dash="dot", annotation_text="unconditional 50%")
        probability.update_yaxes(range=[0, 1], tickformat=".0%")
        st.plotly_chart(style_figure(probability, title="P(return > 0) · Level-0 benchmark", height=410, hovermode="closest"), width="stretch", config={"displaylogo": False})
    bounded_table(
        frame,
        height=305,
        formats={
            "P(up)": st.column_config.ProgressColumn(min_value=0.0, max_value=1.0, format="%.0f%%"),
            "Expected return": st.column_config.NumberColumn(format="%+.2f%%"),
            "Q05": st.column_config.NumberColumn(format="%+.2f%%"),
            "Q25": st.column_config.NumberColumn(format="%+.2f%%"),
            "Q50": st.column_config.NumberColumn(format="%+.2f%%"),
            "Q75": st.column_config.NumberColumn(format="%+.2f%%"),
            "Q95": st.column_config.NumberColumn(format="%+.2f%%"),
            "Expected volatility": st.column_config.NumberColumn(format="%.2f%%"),
            "Jump probability": st.column_config.NumberColumn(format="%.0f%%"),
        },
    )
    st.warning("Probabilities and quantiles are calculated from the deterministic fixture history. They are not a live forecast, are not catalyst-conditioned, and have no OOS calibration evidence.")
    provenance("Required production ladder: naive baseline → interpretable statistical → strong tabular → temporal challenger → gated fusion. No higher level may replace a baseline without documented OOS evidence.")
