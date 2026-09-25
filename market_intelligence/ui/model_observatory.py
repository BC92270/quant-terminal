"""Champion/challenger, provider, calibration, and drift observatory."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ..contracts import WorkspaceSnapshot
from .common import AMBER, CYAN, GREEN, RED, bounded_table, card, provider_health_frame, provenance, section_header, style_figure


def render_model_observatory(snapshot: WorkspaceSnapshot) -> None:
    section_header("GOVERN DESK / 12", "Model Observatory", "CHAMPION / CHALLENGER · DRIFT · ROLLBACK")
    registry = snapshot.model_registry.copy()
    top = st.columns(5)
    with top[0]:
        card("Production champion", "NONE", "No calibrated model is promoted", tone="green")
    with top[1]:
        card("Reference baseline", "EMPIRICAL DIST.", "Level-0 research benchmark", tone="cyan")
    with top[2]:
        card("Calibration", "UNAVAILABLE", "No shadow outcomes", tone="red")
    with top[3]:
        card("Drift", "NOT MEASURABLE", "No live feature stream", tone="amber")
    with top[4]:
        card("Rollback", "N/A", "Nothing production-promoted")
    left, right = st.columns([1.45, 1.0], gap="medium")
    with left:
        bounded_table(registry, height=315)
    with right:
        status_order = ["RESEARCH_ONLY", "WAITING_DATA", "DISABLED"]
        counts = registry["Status"].value_counts().reindex(status_order, fill_value=0)
        fig = go.Figure(go.Bar(x=counts.index, y=counts.values, marker_color=[CYAN, AMBER, RED], text=counts.values, textposition="outside"))
        st.plotly_chart(style_figure(fig, title="Registry state distribution", height=315, hovermode="closest"), width="stretch", config={"displaylogo": False})
    section_header("PROVIDER HEALTH", "Availability and schema matrix", "NO SILENT FALLBACK")
    bounded_table(provider_health_frame(snapshot), height=280)
    calibration = pd.DataFrame(
        [
            {"Metric": "Brier score", "Value": None, "Status": "WAITING OUTCOMES"},
            {"Metric": "Log loss", "Value": None, "Status": "WAITING OUTCOMES"},
            {"Metric": "Expected calibration error", "Value": None, "Status": "WAITING OUTCOMES"},
            {"Metric": "Q05-Q95 interval coverage", "Value": None, "Status": "WAITING OUTCOMES"},
            {"Metric": "Regime coverage", "Value": None, "Status": "FIXTURE ONLY"},
        ]
    )
    bounded_table(calibration, height=245)
    provenance("Production flow is closed: outcome logging → drift detection → challenger retraining → offline validation → shadow → human promotion → rollback-ready registry.")
