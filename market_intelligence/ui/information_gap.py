"""Known-catalyst coverage versus unexplained-flow residual."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ..contracts import WorkspaceSnapshot
from .common import AMBER, CYAN, GREEN, RED, bounded_table, card, provenance, section_header, style_figure, tone_for_status


def render_information_gap(snapshot: WorkspaceSnapshot) -> None:
    section_header("STATE DESK / 08", "Information Gap", "ABNORMAL ≠ INSIDER INFORMATION · INVESTIGATION QUEUE")
    gap = snapshot.audit["information_gap"]
    component_rows = [
        {"Component": "Known catalyst intensity", "Value": gap["known_catalyst_intensity"], "Availability": "SIMULATED", "Interpretation": "Explained-state coverage"},
        {"Component": "Microstructure anomaly", "Value": gap["microstructure_anomaly"], "Availability": "SIMULATED L2", "Interpretation": "Observed-state anomaly"},
        {"Component": "Options anomaly", "Value": gap["options_anomaly"], "Availability": "UNAVAILABLE", "Interpretation": "Withheld; no options feed"},
        {"Component": "Related-asset anomaly", "Value": gap["related_asset_anomaly"], "Availability": "SIMULATED", "Interpretation": "Cross-asset propagation"},
        {"Component": "Unexplained residual", "Value": gap["unexplained_residual"], "Availability": "DERIVED FIXTURE", "Interpretation": "Investigation score, not mispricing"},
    ]
    components = pd.DataFrame(component_rows)
    top = st.columns(4)
    with top[0]:
        card(
            "Current state",
            gap["status"],
            "Threshold is descriptive and fixture-only",
            tone=tone_for_status(str(gap["status"])),
        )
    with top[1]:
        card("Known coverage", f"{gap['known_catalyst_intensity']:.0%}", "Fed, rates, earnings and guidance", tone="green")
    with top[2]:
        card("Residual", f"{gap['unexplained_residual']:.0%}", "Below investigation threshold", tone="cyan")
    with top[3]:
        card("Options layer", "MISSING", "Explicit null; never imputed", tone="amber")
    chart = components.dropna(subset=["Value"])
    colors = [GREEN, AMBER, "#b98cff", RED]
    fig = go.Figure(go.Bar(x=chart["Value"], y=chart["Component"], orientation="h", marker_color=colors[: len(chart)], text=[f"{value:.0%}" for value in chart["Value"]], textposition="outside"))
    fig.update_xaxes(range=[0, 1], tickformat=".0%")
    left, right = st.columns([1.25, 1.0], gap="medium")
    with left:
        st.plotly_chart(style_figure(fig, title="Explanation coverage and anomaly components", height=370, hovermode="closest"), width="stretch", config={"displaylogo": False})
    with right:
        st.markdown("##### Investigation queue")
        checks = pd.DataFrame(
            [
                {"Check": "Fresh official/company event", "State": "COVERED BY FIXTURE", "Priority": 1},
                {"Check": "Related assets / index lead", "State": "CANDIDATE FOUND", "Priority": 2},
                {"Check": "Rates / FX / commodity shock", "State": "RATES SHOCK KNOWN", "Priority": 3},
                {"Check": "Options IV / skew / volume", "State": "UNAVAILABLE", "Priority": 4},
                {"Check": "Sector / ETF flow proxy", "State": "RESEARCH ONLY", "Priority": 5},
            ]
        )
        bounded_table(checks, height=300)
    bounded_table(components, height=245)
    st.warning("UNEXPLAINED INFORMATION FLOW means measured inputs do not currently explain the market state. It must never be translated into an insider-information allegation.")
    provenance("Residual formula and inputs are fixture-only. A production residual requires PIT factor/event decomposition, options coverage and calibrated reference distributions.")
