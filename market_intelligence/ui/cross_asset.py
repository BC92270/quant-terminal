"""Point-in-time cross-asset propagation view."""

from __future__ import annotations

import math

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ..contracts import WorkspaceSnapshot
from ..data import relationship_valid_at
from .common import AMBER, CYAN, GREEN, RED, bounded_table, card, provenance, section_header, style_figure


def _propagation_graph(snapshot: WorkspaceSnapshot) -> go.Figure:
    frame = snapshot.relationships.copy()
    names = list(dict.fromkeys(frame["Source"].tolist() + frame["Target"].tolist()))
    angles = {name: 2.0 * math.pi * index / len(names) for index, name in enumerate(names)}
    coordinates = {name: (math.cos(angle), math.sin(angle)) for name, angle in angles.items()}
    coordinates[snapshot.symbol] = (0.0, 0.0)
    status_style = {
        "observed": (GREEN, "solid"),
        "economic_link": (CYAN, "solid"),
        "model_association": (AMBER, "dot"),
        "hypothesis": (RED, "dash"),
    }
    fig = go.Figure()
    for _, row in frame.iterrows():
        source = str(row["Source"])
        target = str(row["Target"])
        x0, y0 = coordinates[source]
        x1, y1 = coordinates[target]
        color, dash = status_style.get(str(row["Edge status"]), ("rgba(190,210,215,.4)", "dot"))
        fig.add_trace(
            go.Scatter(
                x=[x0, x1], y=[y0, y1], mode="lines", showlegend=False,
                line=dict(color=color, width=max(1.0, abs(float(row["Weight"])) * 4.0), dash=dash),
                text=[f"{source} → {target}<br>{row['Relation']}<br>weight {row['Weight']:+.2f}"] * 2,
                hoverinfo="text",
            )
        )
    fig.add_trace(
        go.Scatter(
            x=[coordinates[name][0] for name in names], y=[coordinates[name][1] for name in names],
            text=names, mode="markers+text", textposition="bottom center", name="Entities / assets",
            marker=dict(size=[25 if name == snapshot.symbol else 16 for name in names], color=[CYAN if name == snapshot.symbol else "#557687" for name in names], line=dict(color="#07131e", width=2)),
            hovertemplate="%{text}<extra></extra>",
        )
    )
    fig.update_xaxes(visible=False, range=[-1.25, 1.25])
    fig.update_yaxes(visible=False, range=[-1.25, 1.25])
    return style_figure(fig, title="Propagation candidates · edge width reflects fixture weight", height=440, hovermode="closest")


def render_cross_asset(snapshot: WorkspaceSnapshot) -> None:
    section_header("FUSION DESK / 09", "Cross-Asset Propagation", "ECONOMIC LINKS FIRST · GNN LATER")
    frame = snapshot.relationships.copy()
    frame["Valid at as-of"] = [
        relationship_valid_at(
            {"valid_from": row["Valid from"], "valid_to": row["Valid to"]},
            snapshot.as_of,
        )
        for row in frame.to_dict("records")
    ]
    top = st.columns(4)
    with top[0]:
        card("Valid PIT edges", str(int(frame["Valid at as-of"].sum())), f"of {len(frame)} fixture edges", tone="green")
    with top[1]:
        card("Strongest channel", "Fed → US 2Y", "Observed fixture policy transmission", tone="cyan")
    with top[2]:
        card("Lead candidate", "RATES / NDX", "Lead-lag is descriptive, not causal", tone="amber")
    with top[3]:
        card("Graph model", "LINEAR BASELINE", "GNN remains disabled", tone="green")
    left, right = st.columns([1.4, 1.0], gap="medium")
    with left:
        st.plotly_chart(_propagation_graph(snapshot), width="stretch", config={"displaylogo": False})
    with right:
        link_summary = frame.groupby(["Relation", "Edge status"], as_index=False).agg(Edges=("Target", "size"), Mean_weight=("Weight", "mean"))
        bounded_table(link_summary, height=300)
        st.info("Graph neural networks are not active. A relation-weighted linear propagation baseline and PIT edge registry must be validated first.")
    bounded_table(frame, height=320)
    provenance("Relationship sources and dates are fixture metadata. Production edges require authoritative relationship lineage and historical membership validity.")
