"""Machine-discovered pattern governance view."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..contracts import WorkspaceSnapshot
from .common import bounded_table, card, provenance, section_header


def render_discovered_patterns(snapshot: WorkspaceSnapshot) -> None:
    section_header("GOVERN DESK / 11", "Machine-Discovered Patterns", "DISCOVERY ≠ VALIDATION ≠ PROMOTION")
    frame = snapshot.patterns.copy()
    top = st.columns(5)
    with top[0]:
        card("Registered", str(len(frame)), "Stable fixture pattern IDs")
    with top[1]:
        card("OOS eligible", "0", "No chronological evidence", tone="red")
    with top[2]:
        card("After-cost evidence", "0", "Costs not evaluated", tone="red")
    with top[3]:
        card("Multiple-testing pass", "0", "Reality Check / SPA not run", tone="amber")
    with top[4]:
        card("Production promoted", "0", "Fail-closed registry", tone="green")
    selection = st.dataframe(
        frame,
        width="stretch",
        hide_index=True,
        height=280,
        key="mi_patterns_grid",
        on_select="rerun",
        selection_mode="single-row",
    )
    try:
        selected = frame.iloc[selection.selection.rows[0]]
    except (AttributeError, IndexError, TypeError):
        selected = frame.iloc[0]
    left, right = st.columns([1.3, 1.0], gap="medium")
    with left:
        st.markdown(
            f"""
            <div class="mi-state">
              <div class="mi-card-title">Selected pattern · {selected['Pattern ID']}</div>
              <div class="mi-state-code">{selected['Status']}</div>
              <div class="mi-state-copy">{selected['Signature']}</div>
              <div class="mi-chip-row"><span class="mi-chip">{selected['Discovery']}</span><span class="mi-chip">{selected['Stability']}</span></div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with right:
        gates = pd.DataFrame(
            [
                {"Gate": "Chronological OOS", "Status": "WAITING_EVIDENCE"},
                {"Gate": "Multiple-testing correction", "Status": str(selected["Multiple-testing"])},
                {"Gate": "Cost / slippage sensitivity", "Status": "NOT RUN"},
                {"Gate": "Subperiod / regime stability", "Status": str(selected["Stability"])},
                {"Gate": "Shadow observation", "Status": "NOT STARTED"},
            ]
        )
        bounded_table(gates, height=250)
    st.info("Autonomous pattern search can create hypotheses only. It cannot auto-label alpha, auto-promote a model, or rewrite the production champion.")
    provenance("Pattern registry is a control surface. White Reality Check, Hansen SPA, Deflated Sharpe and PBO remain unavailable until genuine experiment histories exist.")
