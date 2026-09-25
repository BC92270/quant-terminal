"""Multivariate historical-analogue research view."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ..contracts import WorkspaceSnapshot
from .common import AMBER, CYAN, GREEN, RED, bounded_table, card, provenance, section_header, style_figure


FEATURE_COLUMNS = {
    "Event": "Event sim",
    "Regime": "Regime sim",
    "Microstructure": "Micro sim",
    "Valuation / volatility": "Vol sim",
}


def render_historical_analogues(snapshot: WorkspaceSnapshot) -> None:
    section_header("STATE DESK / 06", "Historical Analogues", "MULTIVARIATE STATE · ABNORMAL-RETURN READY")
    excluded = st.multiselect(
        "EXCLUDE FEATURE GROUPS AND RE-RANK",
        list(FEATURE_COLUMNS),
        default=[],
        key="mi_analogue_exclusions",
        help="Recalculates similarity using only the retained fixture feature groups.",
    )
    retained = [column for label, column in FEATURE_COLUMNS.items() if label not in excluded]
    frame = snapshot.analogues.copy()
    frame["Re-ranked similarity"] = frame[retained].mean(axis=1) if retained else np.nan
    frame = frame.sort_values("Re-ranked similarity", ascending=False, na_position="last").reset_index(drop=True)
    top = frame.iloc[0] if not frame.empty else None
    cards = st.columns(4)
    with cards[0]:
        card("Nearest episode", str(top["Episode"]) if top is not None else "N/A", str(top["Event"]) if top is not None else "No episode")
    with cards[1]:
        card("Composite similarity", f"{top['Re-ranked similarity']:.0%}" if top is not None and pd.notna(top["Re-ranked similarity"]) else "N/A", f"{len(retained)} feature groups retained", tone="cyan")
    with cards[2]:
        card("Fixture sample", str(len(frame)), "Below any institutional inference threshold", tone="amber")
    with cards[3]:
        card("Confidence", "LOW / INVALID", "Synthetic records; no historical population", tone="red")

    left, right = st.columns([1.45, 1.0], gap="medium")
    with left:
        heat = frame.set_index("Episode")[["Event sim", "Regime sim", "Micro sim", "Vol sim"]]
        fig = go.Figure(
            go.Heatmap(
                z=heat.to_numpy(), x=[column.replace(" sim", "") for column in heat.columns], y=heat.index,
                zmin=0, zmax=1, colorscale=[[0, "#0a1d29"], [.5, "#177080"], [1, "#55e8f5"]],
                colorbar=dict(title="Similarity", tickformat=".0%"),
                hovertemplate="%{y}<br>%{x}: %{z:.0%}<extra></extra>",
            )
        )
        st.plotly_chart(style_figure(fig, title="Similarity decomposition · retained and excluded groups stay visible", height=390, hovermode="closest"), width="stretch", config={"displaylogo": False})
    with right:
        outcomes = pd.concat(
            [
                pd.DataFrame({"Horizon": "+1h", "Return": frame["Return +1h"]}),
                pd.DataFrame({"Horizon": "+1d", "Return": frame["Return +1d"]}),
            ]
        )
        fig = go.Figure()
        for horizon, color in (("+1h", CYAN), ("+1d", AMBER)):
            subset = outcomes.loc[outcomes["Horizon"] == horizon]
            fig.add_trace(go.Box(y=subset["Return"], name=horizon, boxpoints="all", marker_color=color, line_color=color))
        fig.update_yaxes(tickformat="+.1%")
        st.plotly_chart(style_figure(fig, title="Subsequent fixture-return distribution", height=390, hovermode="closest"), width="stretch", config={"displaylogo": False})
    display = frame[["Episode", "Event", "Re-ranked similarity", "Event sim", "Regime sim", "Micro sim", "Vol sim", "Return +1h", "Return +1d", "Status"]]
    bounded_table(display, height=285)
    provenance("All analogue episodes are synthetic IDs. Future outcomes are isolated from the similarity vector; a production search must enforce this invariant and use abnormal returns where appropriate.")
