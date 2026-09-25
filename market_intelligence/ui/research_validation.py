"""Explicit, bounded research and validation workbench."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..contracts import WorkspaceSnapshot
from ..monitoring import run_fixture_integrity_audit
from .common import bounded_table, card, provenance, section_header


def render_research_validation(snapshot: WorkspaceSnapshot) -> None:
    section_header("GOVERN DESK / 13", "Research & Validation", "CHRONOLOGICAL · PURGED · REPRODUCIBLE · FAIL CLOSED")
    with st.form("mi_research_configuration"):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.selectbox("UNIVERSE", (f"{snapshot.symbol} · fixture",), disabled=True)
        with c2:
            st.selectbox("STUDY", ("Canonical integration audit", "Event study · unavailable", "Walk-forward · unavailable"), key="mi_research_study")
        with c3:
            st.selectbox("SPLIT POLICY", ("Chronological + purge + embargo",), disabled=True)
        with c4:
            st.selectbox("BENCHMARK", ("Level-0 empirical distribution",), disabled=True)
        c5, c6, c7 = st.columns(3)
        with c5:
            st.number_input("PURGE WINDOW (observations)", min_value=0, max_value=100, value=5, key="mi_purge_window")
        with c6:
            st.number_input("EMBARGO (observations)", min_value=0, max_value=100, value=5, key="mi_embargo")
        with c7:
            st.selectbox("COST POLICY", ("Not applicable to fixture audit",), disabled=True)
        run = st.form_submit_button("RUN BOUNDED FIXTURE AUDIT", type="secondary", width="stretch")
    if run:
        result = run_fixture_integrity_audit(snapshot)
        st.session_state["mi_research_run"] = result.to_dict("records")
    records = st.session_state.get("mi_research_run")
    result = pd.DataFrame(records) if records else run_fixture_integrity_audit(snapshot)
    passed = int((result["Result"] == "PASS").sum())
    failed = int((result["Result"] == "FAIL").sum())
    blocking_failed = int(((result["Result"] == "FAIL") & result["Blocking"]).sum())
    cards = st.columns(5)
    with cards[0]:
        card("Integrity gates", str(len(result)), "Deterministic checks")
    with cards[1]:
        card("Pass", str(passed), "Current fixture result", tone="green")
    with cards[2]:
        card("Fail", str(failed), "Requires investigation", tone="red" if failed else "green")
    with cards[3]:
        card("Blocking fails", str(blocking_failed), "Would block promotion", tone="red" if blocking_failed else "green")
    with cards[4]:
        card("Promotion decision", "CLOSED", "Live evidence absent", tone="amber")
    bounded_table(result, height=350)
    section_header("PROMOTION GATES", "Evidence still required", "UI PASS ≠ SCIENTIFIC VALIDATION")
    promotion = pd.DataFrame(
        [
            {"Gate": "Point-in-time provider audit", "State": "WAITING_EVIDENCE", "Owner evidence": "Licensed event / consensus / L2 lineage"},
            {"Gate": "Deterministic reproducibility", "State": "FOUNDATION PASS", "Owner evidence": "Fixture + unit tests"},
            {"Gate": "Chronological walk-forward OOS", "State": "WAITING_EVIDENCE", "Owner evidence": "Historical PIT corpus"},
            {"Gate": "Benchmark superiority / complementarity", "State": "WAITING_EVIDENCE", "Owner evidence": "Registered experiments"},
            {"Gate": "Probability calibration", "State": "WAITING_EVIDENCE", "Owner evidence": "Realized prediction ledger"},
            {"Gate": "Multiple-testing correction", "State": "WAITING_EVIDENCE", "Owner evidence": "Search universe + trials"},
            {"Gate": "Costs and slippage", "State": "NOT CLAIMED", "Owner evidence": "Only required for trading interpretation"},
            {"Gate": "Shadow-live observation", "State": "NOT STARTED", "Owner evidence": "Append-only shadow ledger"},
            {"Gate": "Human promotion / rollback", "State": "CLOSED", "Owner evidence": "Governance decision"},
        ]
    )
    bounded_table(promotion, height=390)
    provenance("Heavy studies never run on initial render. This button executes only bounded deterministic fixture checks; event studies and walk-forward jobs remain unavailable until a PIT corpus exists.")
