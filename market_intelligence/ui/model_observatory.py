"""Institutional model inventory, evidence, calibration, drift, and rollback observatory."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ..contracts import WorkspaceSnapshot
from .common import AMBER, CYAN, GREEN, RED, bounded_table, card, provenance, section_header, style_figure, tone_for_status
from .institutional_control import (
    gate_frame,
    governance_assessment,
    model_registry_frame,
    quality_frame,
)


def render_model_observatory(snapshot: WorkspaceSnapshot) -> None:
    assessment = governance_assessment(snapshot)
    decision = assessment.decision
    records = assessment.model_registry.records
    blocking = len(decision.validation.blocking_results)

    section_header(
        "GOVERN DESK / 12",
        "Model Observatory",
        "TYPED INVENTORY · HASHED LINEAGE · DRIFT · HUMAN PROMOTION · ROLLBACK",
    )
    top = st.columns(6)
    with top[0]:
        card("Production champion", "NONE", "Promotion path is closed", tone="amber")
    with top[1]:
        card("Registered models", str(len(records)), "Typed versioned research records", tone="cyan")
    with top[2]:
        lifecycle = records[0].lifecycle.value.upper() if len(records) == 1 else "MIXED"
        card("Lifecycle", lifecycle, "No implicit state transition", tone="cyan")
    with top[3]:
        card("Promotion", decision.state.value, f"{blocking} blocking controls", tone=tone_for_status(decision.state.value))
    with top[4]:
        card("Rollback", "NOT APPLICABLE", "No production model exists")
    with top[5]:
        card("Execution", "DISABLED", "Enforced by decision contract", tone="red")

    section_header("MODEL CONTROL", "Registered baseline inventory", "ARTIFACT · CONFIG · TRAINING-DATA HASHES")
    registry = model_registry_frame(assessment)
    left, right = st.columns([1.75, 1.0], gap="medium")
    with left:
        bounded_table(registry, height=305)
        provenance(
            f"Registry schema {assessment.model_registry.schema_version}. Every record is bounded to RESEARCH_ONLY; "
            "SHADOW requires explicit human approval and a non-blocking validation run."
        )
    with right:
        states = registry["Promotion"].value_counts() if not registry.empty else pd.Series(dtype=int)
        colors = [AMBER if "WAIT" in status else GREEN if "ELIGIBLE" in status else RED for status in states.index]
        fig = go.Figure(
            go.Bar(
                x=states.index,
                y=states.values,
                marker_color=colors or [CYAN],
                text=states.values,
                textposition="outside",
            )
        )
        st.plotly_chart(
            style_figure(fig, title="Promotion-state distribution", height=305, hovermode="closest"),
            width="stretch",
            config={"displaylogo": False},
        )

    quality_tab, gates_tab, candidates_tab = st.tabs(
        ["DATA QUALITY & FRESHNESS", "MODEL-READINESS CONTROLS", "RESEARCH CANDIDATE BLUEPRINT"]
    )
    with quality_tab:
        bounded_table(quality_frame(assessment), height=345)
        provenance(
            "Freshness and completeness are evaluated from point-in-time provider contracts. Missing completeness "
            "evidence is not converted into a favorable state."
        )
    with gates_tab:
        gates = gate_frame(assessment)
        model_gates = gates.loc[
            gates["Gate"].isin(
                [
                    "PIT_CHAIN",
                    "DATA_QUALITY",
                    "CALIBRATION",
                    "CHRONOLOGICAL_OOS",
                    "SHADOW_HISTORY",
                    "HUMAN_REVIEW",
                    "EVIDENCE_INTEGRITY",
                ]
            )
        ]
        bounded_table(model_gates, height=390)
    with candidates_tab:
        bounded_table(snapshot.model_registry.copy(), height=355)
        provenance(
            "This table is the candidate architecture backlog supplied by the deterministic fixture. It is not the "
            "typed active registry above and creates no trained artifact, champion, or production entitlement."
        )

    section_header("OUTCOME CONTROLS", "Calibration, drift, and rollback evidence", "ABSENCE REMAINS EXPLICIT")
    calibration = pd.DataFrame(
        [
            {"Metric": "Brier score", "Value": None, "State": "WAITING_EVIDENCE", "Required evidence": "Realized probability outcomes"},
            {"Metric": "Log loss", "Value": None, "State": "WAITING_EVIDENCE", "Required evidence": "Append-only prediction ledger"},
            {"Metric": "Expected calibration error", "Value": None, "State": "WAITING_EVIDENCE", "Required evidence": "Sufficient OOS bins"},
            {"Metric": "Q05-Q95 interval coverage", "Value": None, "State": "WAITING_EVIDENCE", "Required evidence": "Chronological realized returns"},
            {"Metric": "Feature / prediction drift", "Value": None, "State": "NOT_MEASURABLE", "Required evidence": "Live feature stream + reference window"},
            {"Metric": "Rollback readiness", "Value": None, "State": "NOT_APPLICABLE", "Required evidence": "Human-promoted shadow or production model"},
        ]
    )
    bounded_table(calibration, height=300)
    provenance(
        "Controlled path: outcome logging → independent validation → drift review → challenger comparison → "
        "human shadow approval → rollback-ready registry. This release stops before shadow promotion."
    )
