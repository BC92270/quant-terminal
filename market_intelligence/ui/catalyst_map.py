"""Typed catalyst and relationship graph."""

from __future__ import annotations

import math

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ..contracts import WorkspaceSnapshot
from .common import AMBER, CYAN, GREEN, RED, bounded_table, provenance, section_header, style_figure


def _graph(snapshot: WorkspaceSnapshot) -> go.Figure:
    symbol = snapshot.symbol
    nodes = {
        "Federal Reserve": (-1.0, 0.65, "catalyst"),
        "US 2Y": (-0.45, 0.35, "market"),
        "Nasdaq 100": (0.05, 0.25, "market"),
        symbol: (0.62, 0.15, "asset"),
        "Earnings": (0.30, -0.55, "catalyst"),
        "Guidance": (0.84, -0.48, "catalyst"),
        "SMH": (1.15, 0.62, "asset"),
        "AI infrastructure": (1.28, -0.12, "hypothesis"),
    }
    edges = [
        ("Federal Reserve", "US 2Y", "observed"),
        ("US 2Y", "Nasdaq 100", "model_association"),
        ("Nasdaq 100", symbol, "economic_link"),
        ("Earnings", symbol, "observed"),
        ("Guidance", symbol, "observed"),
        (symbol, "SMH", "economic_link"),
        (symbol, "AI infrastructure", "hypothesis"),
    ]
    edge_styles = {
        "observed": (GREEN, "solid"),
        "economic_link": (CYAN, "solid"),
        "model_association": (AMBER, "dot"),
        "hypothesis": (RED, "dash"),
    }
    fig = go.Figure()
    for source, target, status in edges:
        x0, y0, _ = nodes[source]
        x1, y1, _ = nodes[target]
        color, dash = edge_styles[status]
        fig.add_trace(
            go.Scatter(
                x=[x0, x1], y=[y0, y1], mode="lines", line=dict(color=color, width=1.8, dash=dash),
                hoverinfo="text", text=[f"{source} → {target}<br>{status}"] * 2, showlegend=False,
            )
        )
    categories = {"catalyst": RED, "market": AMBER, "asset": CYAN, "hypothesis": "#b98cff"}
    for category, color in categories.items():
        selected = [(name, values) for name, values in nodes.items() if values[2] == category]
        fig.add_trace(
            go.Scatter(
                x=[values[0] for _, values in selected],
                y=[values[1] for _, values in selected],
                text=[name for name, _ in selected],
                mode="markers+text",
                textposition="bottom center",
                name=category.replace("_", " ").title(),
                marker=dict(size=[25 if name == symbol else 18 for name, _ in selected], color=color, line=dict(color="#07131e", width=2)),
                hovertemplate="%{text}<br>Node type: " + category + "<extra></extra>",
            )
        )
    fig.update_xaxes(visible=False, range=[-1.25, 1.55])
    fig.update_yaxes(visible=False, range=[-0.82, 0.92])
    return style_figure(fig, title="Typed propagation graph · edge semantics are explicit", height=470, hovermode="closest")


def render_catalyst_map(snapshot: WorkspaceSnapshot) -> None:
    section_header("NOW DESK / 03", "Catalyst Map", "OBSERVED ≠ ECONOMIC LINK ≠ MODEL ASSOCIATION ≠ HYPOTHESIS")
    left, right = st.columns([1.7, 1.0], gap="medium")
    with left:
        st.plotly_chart(_graph(snapshot), width="stretch", config={"displaylogo": False})
        provenance("Network topology is a deterministic fixture. Hypothesis edges are visually distinct and never presented as causal facts.")
    with right:
        counts = snapshot.relationships["Edge status"].value_counts().rename_axis("Edge status").reset_index(name="Count")
        bounded_table(counts, height=205)
        st.markdown(
            '<div class="mi-card"><div class="mi-card-title">Graph contract</div>'
            '<div class="mi-card-note">Every edge requires relation type, source, confidence, valid-from / valid-to, '
            'and a point-in-time safety flag. Empirical lead-lag stays distinct from economic relationships.</div></div>',
            unsafe_allow_html=True,
        )
    section_header("EDGE REGISTRY", "Point-in-time relationship evidence", "BOUNDED TABLE")
    bounded_table(snapshot.relationships, height=310)
