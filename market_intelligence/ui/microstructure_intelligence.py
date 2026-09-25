"""Order-book state and absorption-sensor view."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ..contracts import WorkspaceSnapshot
from ..microstructure import microprice, order_flow_imbalance, queue_imbalance
from .common import AMBER, CYAN, GREEN, RED, bounded_table, card, fmt_number, fmt_pct, provenance, section_header, style_figure


def _depth_chart(snapshot: WorkspaceSnapshot) -> go.Figure:
    depth = snapshot.audit["depth_ladder"].sort_values("level", ascending=False)
    fig = go.Figure()
    fig.add_trace(go.Bar(y=depth["bid_price"].map(lambda value: f"{value:.2f}"), x=-depth["bid_size"], orientation="h", name="Bid depth", marker_color=GREEN, customdata=depth["bid_size"], hovertemplate="Bid %{y}<br>Size %{customdata:,.0f}<extra></extra>"))
    fig.add_trace(go.Bar(y=depth["ask_price"].map(lambda value: f"{value:.2f}"), x=depth["ask_size"], orientation="h", name="Ask depth", marker_color=RED, customdata=depth["ask_size"], hovertemplate="Ask %{y}<br>Size %{customdata:,.0f}<extra></extra>"))
    fig.update_layout(barmode="overlay", xaxis_title="Mirrored displayed size")
    return style_figure(fig, title="Depth ladder / pressure profile · simulated sequenced L2", height=400, hovermode="closest")


def _quote_history(snapshot: WorkspaceSnapshot) -> pd.DataFrame:
    quotes = snapshot.audit["quote_events"].copy()
    quotes["timestamp"] = pd.to_datetime(quotes["timestamp"], utc=True)
    quotes["queue_imbalance"] = [queue_imbalance(row.bid_size, row.ask_size) for row in quotes.itertuples()]
    quotes["microprice"] = [microprice(row.best_bid, row.best_ask, row.bid_size, row.ask_size) for row in quotes.itertuples()]
    quotes["mid"] = (quotes["best_bid"] + quotes["best_ask"]) / 2.0
    cumulative = [0.0]
    for end in range(2, len(quotes) + 1):
        value = order_flow_imbalance(quotes.iloc[:end].to_dict("records"))
        cumulative.append(float(value or 0.0))
    quotes["cumulative_ofi"] = cumulative
    return quotes


def render_microstructure_intelligence(snapshot: WorkspaceSnapshot) -> None:
    section_header("STATE DESK / 07", "Microstructure Intelligence", "ABSORPTION SENSOR · NOT AN HFT EXECUTION ENGINE")
    m = snapshot.microstructure
    metrics = st.columns(7)
    values = (
        ("Spread", fmt_number(m.spread, 4), "best ask − best bid", ""),
        ("Queue imbalance", fmt_number(m.queue_imbalance, 3), "best queues", "cyan"),
        ("OFI", fmt_number(m.ofi, 0), "best-quote events", "cyan"),
        ("Trade imbalance", fmt_number(m.trade_imbalance, 3), "aggressive volume", "red"),
        ("Bid replenishment", fmt_number(m.bid_replenishment, 2), "sequenced L2", "green"),
        ("Impact proxy", fmt_number(m.price_impact_proxy, 2), "sell impact declining", "green"),
        ("Anomaly", fmt_pct(m.anomaly_percentile, 0), "fixture percentile", "amber"),
    )
    for column, (label, value, note, tone) in zip(metrics, values):
        with column:
            card(label, value, note, tone=tone)
    left, right = st.columns([1.0, 1.35], gap="medium")
    with left:
        st.plotly_chart(_depth_chart(snapshot), width="stretch", config={"displaylogo": False})
    with right:
        quotes = _quote_history(snapshot)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=quotes["timestamp"], y=quotes["cumulative_ofi"], name="Cumulative OFI", line=dict(color=CYAN, width=2.3)))
        fig.add_trace(go.Scatter(x=quotes["timestamp"], y=quotes["queue_imbalance"], name="Queue imbalance", yaxis="y2", line=dict(color=AMBER, width=1.7)))
        fig.update_layout(yaxis=dict(title="OFI"), yaxis2=dict(title="Queue imbalance", overlaying="y", side="right", range=[-1, 1], showgrid=False))
        st.plotly_chart(style_figure(fig, title="OFI and queue-imbalance state · 30-second fixture messages", height=400), width="stretch", config={"displaylogo": False})
    quotes = _quote_history(snapshot)
    bounded_table(quotes, height=260)
    with st.expander("FEATURE DEFINITIONS AND DATA-LEVEL GUARDS", expanded=False):
        st.markdown(
            "- **Queue imbalance**: `(bid_size - ask_size) / (bid_size + ask_size)` at the best quote.\n"
            "- **Microprice**: size-weighted best quotes, constrained inside bid/ask.\n"
            "- **OFI**: Cont–Kukanov–Stoikov best-quote event imbalance.\n"
            "- **Replenishment / cancel intensity**: only valid with sequenced L2/MBO messages; never inferred from isolated L1 snapshots.\n"
            "- **Scope**: seconds-to-minutes state sensing, not millisecond execution."
        )
    provenance("Schema L2 is simulated. The workspace does not assert venue entitlement, raw-message retention, clock synchronization or live book coverage.")
