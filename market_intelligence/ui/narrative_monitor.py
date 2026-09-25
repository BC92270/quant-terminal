"""Persistent narrative-state monitor."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from ..contracts import WorkspaceSnapshot
from .common import AMBER, CYAN, GREEN, RED, bounded_table, card, provenance, section_header, style_figure


def render_narrative_monitor(snapshot: WorkspaceSnapshot) -> None:
    section_header("NOW DESK / 04", "Narrative Monitor", "INTENSITY · MOMENTUM · NOVELTY SHARE · DECAY")
    frame = snapshot.narratives.copy()
    selected = st.selectbox("ACTIVE NARRATIVE", frame["Narrative"].tolist(), key="mi_selected_narrative")
    row = frame.loc[frame["Narrative"] == selected].iloc[0]
    metrics = st.columns(5)
    with metrics[0]:
        card("Intensity", f"{row['Intensity']:.0%}", "Weighted fixture information units", tone="cyan")
    with metrics[1]:
        card("Momentum", f"{row['Momentum']:+.2f}", "First difference", tone="green" if row["Momentum"] >= 0 else "red")
    with metrics[2]:
        card("Acceleration", f"{row['Acceleration']:+.2f}", "Second difference", tone="amber")
    with metrics[3]:
        card("Novelty share", f"{row['Novelty share']:.0%}", "New information / total activity")
    with metrics[4]:
        card("Decay state", str(row["Decay state"]), "Empirical persistence band only")
    fig = go.Figure()
    colors = [GREEN if value >= 0 else RED for value in frame["Sentiment"]]
    fig.add_trace(
        go.Bar(
            x=frame["Narrative"], y=frame["Intensity"], name="Intensity", marker_color=CYAN,
            hovertemplate="%{x}<br>Intensity %{y:.0%}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=frame["Narrative"], y=frame["Sentiment"], name="Sentiment", mode="markers+lines",
            yaxis="y2", marker=dict(color=colors, size=11), line=dict(color=AMBER, width=1.2),
            hovertemplate="%{x}<br>Sentiment %{y:+.2f}<extra></extra>",
        )
    )
    fig.update_layout(yaxis=dict(title="Intensity", tickformat=".0%", range=[0, 1]), yaxis2=dict(title="Sentiment", overlaying="y", side="right", range=[-1, 1], showgrid=False))
    st.plotly_chart(style_figure(fig, title="Narrative intensity and directional tone · fixture snapshot", height=380), width="stretch", config={"displaylogo": False})
    bounded_table(frame, height=255)
    provenance("Narrative values are deterministic fixture features. Article count is not used as a direct proxy for information intensity.")
