"""Opposing catalyst mass and interaction-residual view."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ..contracts import WorkspaceSnapshot
from .common import AMBER, GREEN, RED, bounded_table, card, provenance, section_header, style_figure


def render_catalyst_collision(snapshot: WorkspaceSnapshot) -> None:
    section_header("STATE DESK / 05", "Catalyst Collision", "OPPOSING INFORMATION · UNCERTAINTY FIRST")
    frame = snapshot.catalyst_contributions.copy()
    metrics = snapshot.audit["collision"]
    top = st.columns(5)
    with top[0]:
        card("Positive mass", f"{metrics['positive_mass']:.2f}", "Sum of positive fixture contributions", tone="green")
    with top[1]:
        card("Negative mass", f"{metrics['negative_mass']:.2f}", "Absolute negative fixture contributions", tone="red")
    with top[2]:
        card("Collision", f"{metrics['collision_score']:.0%}", "2 × min(pos, neg) / total", tone="amber")
    with top[3]:
        card("Net pressure", f"{metrics['net_pressure']:+.2f}", "Weak direction under high conflict")
    with top[4]:
        card("Volatility implication", "ELEVATED", "Descriptive fixture state; no vol forecast", tone="amber")

    left, right = st.columns([1.55, 1.0], gap="medium")
    with left:
        ordered = frame.sort_values("contribution")
        colors = [GREEN if value >= 0 else RED for value in ordered["contribution"]]
        fig = go.Figure(
            go.Bar(
                x=ordered["contribution"], y=ordered["catalyst"], orientation="h", marker_color=colors,
                text=[f"{value:+.2f}" for value in ordered["contribution"]], textposition="outside",
                customdata=ordered[["family", "kind", "confidence"]].to_numpy(),
                hovertemplate="%{y}<br>%{x:+.2f}<br>%{customdata[0]} · %{customdata[2]}<extra></extra>",
            )
        )
        fig.add_vline(x=0, line_color="rgba(230,245,248,.25)")
        st.plotly_chart(style_figure(fig, title="Opposing catalyst contributions · fixture attribution units", height=410, hovermode="closest"), width="stretch", config={"displaylogo": False})
    with right:
        state = snapshot.interaction
        st.markdown(
            f'<div class="mi-state"><div class="mi-card-title">Cross-layer assessment</div>'
            f'<div class="mi-state-code">{state.state.replace("_", " ")}</div>'
            f'<div class="mi-state-copy">{state.explanation}</div>'
            f'<div class="mi-chip-row"><span class="mi-chip">{state.confidence}</span>'
            f'<span class="mi-chip">RESEARCH ONLY</span></div></div>',
            unsafe_allow_html=True,
        )
        st.markdown("##### Evidence chain")
        for item in state.evidence:
            st.markdown(f"- {item}")
        st.markdown("##### Persistence policy")
        st.info("Half-life is withheld: no validated decay model exists. The workspace shows an empirical persistence band only after historical provider data is available.")

    attribution = frame.rename(
        columns={"catalyst": "Catalyst", "family": "Family", "contribution": "Contribution", "kind": "Attribution contract", "confidence": "Confidence"}
    )
    attribution["Interaction residual"] = 0.0
    bounded_table(attribution, height=250, formats={"Contribution": st.column_config.NumberColumn(format="%+.2f"), "Interaction residual": st.column_config.NumberColumn(format="%+.2f")})
    provenance(
        "Group leave-one-out effects are not assumed additive when features interact. Production attribution must use grouped additive attribution (for example Shapley/Owen) or expose an explicit interaction residual. The fixture residual is zero by construction."
    )
