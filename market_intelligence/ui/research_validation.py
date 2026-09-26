"""Executable, evidence-linked research validation and governance workbench."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..contracts import WorkspaceSnapshot
from ..monitoring import run_fixture_integrity_audit
from .common import bounded_table, card, evidence_block, provenance, section_header, tone_for_status
from .institutional_control import (
    governance_assessment,
    render_control_tables,
    render_dossier_identity,
)


def render_research_validation(snapshot: WorkspaceSnapshot) -> None:
    assessment = governance_assessment(snapshot)
    decision = assessment.decision
    validation = decision.validation

    section_header(
        "GOVERN DESK / 13",
        "Research & Validation",
        "EXECUTABLE GATES · HASH-CHAINED EVIDENCE · CHRONOLOGICAL · FAIL CLOSED",
    )
    render_dossier_identity(assessment, snapshot)

    controls = st.columns(6)
    passed_gates = sum(gate.status.value == "PASS" for gate in validation.gates)
    waiting_gates = sum(gate.status.value == "WAITING_EVIDENCE" for gate in validation.gates)
    failed_gates = sum(gate.status.value == "FAIL" for gate in validation.gates)
    with controls[0]:
        card("Decision", decision.state.value, decision.posture.value, tone=tone_for_status(decision.state.value))
    with controls[1]:
        card("Control gates", str(len(validation.gates)), f"Policy {validation.policy_version}", tone="cyan")
    with controls[2]:
        card("Passing", str(passed_gates), "Evidence currently sufficient", tone="green")
    with controls[3]:
        card("Waiting", str(waiting_gates), "More admissible evidence required", tone="amber")
    with controls[4]:
        card("Failing", str(failed_gates), "Hard control failures", tone="red" if failed_gates else "green")
    with controls[5]:
        card("Execution", "DISABLED", "Unconditional research boundary", tone="red")

    blocker_items = decision.blockers or ("No blocking controls in the current policy evaluation.",)
    evidence_block("Controls preventing progression", blocker_items, tone="amber" if decision.blockers else "green")
    st.caption(
        "Human review is a required downstream action, never an automated pass. A UI test or deterministic fixture "
        "check cannot establish live readiness, scientific validity, or authorization to execute."
    )

    section_header("CONTROL EVIDENCE", "Institutional validation matrix", "QUALITY · GATES · SCENARIOS · LEDGER")
    render_control_tables(assessment)

    section_header("BOUNDED REPLAY", "Deterministic fixture integrity audit", "LOCAL STRUCTURAL CHECKS ONLY")
    with st.form("mi_research_configuration"):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.selectbox("UNIVERSE", (f"{snapshot.symbol} · canonical fixture",), disabled=True)
        with c2:
            st.selectbox(
                "STUDY",
                ("Canonical integration audit",),
                key="mi_research_study",
                disabled=True,
            )
        with c3:
            st.selectbox("SPLIT POLICY", ("Not applied · no PIT corpus",), disabled=True)
        with c4:
            st.selectbox("BENCHMARK", ("Level-0 empirical distribution",), disabled=True)
        c5, c6, c7 = st.columns(3)
        with c5:
            st.number_input(
                "PURGE WINDOW · RESERVED",
                min_value=0,
                max_value=100,
                value=0,
                key="mi_fixture_purge_reserved",
                disabled=True,
                help="Becomes active only when a chronological point-in-time corpus is registered.",
            )
        with c6:
            st.number_input(
                "EMBARGO · RESERVED",
                min_value=0,
                max_value=100,
                value=0,
                key="mi_fixture_embargo_reserved",
                disabled=True,
                help="Becomes active only when a chronological point-in-time corpus is registered.",
            )
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
        card("Fixture checks", str(len(result)), "Deterministic structural controls")
    with cards[1]:
        card("Pass", str(passed), "Current fixture result", tone="green")
    with cards[2]:
        card("Fail", str(failed), "Requires investigation", tone="red" if failed else "green")
    with cards[3]:
        card("Blocking fails", str(blocking_failed), "Would block progression", tone="red" if blocking_failed else "green")
    with cards[4]:
        card("Promotion", "CLOSED", "Live and shadow evidence absent", tone="amber")
    bounded_table(result, height=350)

    manifest = pd.DataFrame(
        [
            {"Manifest field": "Decision packet", "Value": decision.packet_id},
            {"Manifest field": "Validation run", "Value": validation.run_id},
            {"Manifest field": "Policy version", "Value": validation.policy_version},
            {"Manifest field": "Evidence root SHA-256", "Value": decision.evidence_root},
            {"Manifest field": "Snapshot as-of", "Value": decision.as_of.isoformat()},
            {"Manifest field": "Research boundary", "Value": decision.boundary.value},
            {"Manifest field": "Execution allowed", "Value": str(decision.execution_allowed).upper()},
            {"Manifest field": "Model keys", "Value": " · ".join(decision.model_keys) or "NONE"},
        ]
    )
    with st.expander("REPRODUCIBILITY MANIFEST", expanded=False):
        bounded_table(manifest, height=315)
    provenance(
        "Heavy studies never run on initial render. The local audit checks deterministic integration only; "
        "event studies, purged walk-forward validation, multiple-testing correction, realized calibration, "
        "shadow history and independent human review remain required before any progression."
    )
