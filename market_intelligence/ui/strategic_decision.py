"""Strategic decision room and persistent decision ribbon."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from ..contracts import WorkspaceSnapshot
from ..evidence import canonical_json
from ..governance import GovernanceAssessment
from ..patterns.contracts import PatternStrategyBridge
from ..state import set_active_view
from ..strategy import (
    HumanDisposition,
    StrategicDecisionJournal,
    StrategicDecisionMemo,
    StrategicDisposition,
)
from .common import bounded_table, esc, evidence_block, section_header, tone_for_status


def option_frame(memo: StrategicDecisionMemo) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Status": option.status.value,
                "Option": option.label,
                "Class": option.option_class.value,
                "Thesis": option.thesis,
                "Strategic benefit": option.strategic_benefit,
                "Downside / tail": option.downside,
                "Reversibility": option.reversibility,
                "Evidence": option.evidence_strength,
                "Principal blocker": option.principal_blocker,
                "Trigger": option.trigger,
                "Invalidation": option.invalidation,
                "Source view": option.destination_view,
            }
            for option in memo.options
        ]
    )


def impact_frame(memo: StrategicDecisionMemo) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Dimension": impact.dimension,
                "State": impact.state.value,
                "Assessment": impact.assessment,
                "Limit": impact.limitation,
                "Evidence count": len(impact.evidence_ids),
            }
            for impact in memo.impacts
        ]
    )


def monitoring_frame(memo: StrategicDecisionMemo) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Metric": rule.metric,
                "Current observation": rule.current_observation,
                "Warning trigger": rule.warning_trigger,
                "Invalidation": rule.invalidation_condition,
                "Owner": rule.owner_role,
                "Source view": rule.source_view,
                "Evidence count": len(rule.evidence_ids),
            }
            for rule in memo.monitoring_rules
        ]
    )


def _journal() -> StrategicDecisionJournal:
    return StrategicDecisionJournal(st.session_state.get("mi_strategy_journal") or ())


def render_strategy_unavailable() -> None:
    st.markdown(
        '<div class="mi-strategy-ribbon mi-strategy-ribbon-red">'
        '<div><span>STRATEGIC RESPONSE</span><b>DEFER · DECISION UNAVAILABLE</b></div>'
        '<div><span>RESEARCH BASIS</span><b>CONTROL-PLANE INCIDENT</b></div>'
        '<div><span>CAPITAL AUTHORITY</span><b>ABSENT</b></div>'
        '<div><span>EXECUTION</span><b>DISABLED</b></div>'
        '</div>',
        unsafe_allow_html=True,
    )


def render_strategy_ribbon(
    memo: StrategicDecisionMemo,
    assessment: GovernanceAssessment,
    *,
    pattern_bridge: PatternStrategyBridge | None = None,
) -> None:
    selected = next(
        option for option in memo.options if option.option_id == memo.recommended_process_option_id
    )
    review_count = sum(
        getattr(record, "memo_id", None) == memo.memo_id
        for record in (st.session_state.get("mi_strategy_journal") or ())
    )
    memo_validity = "EXPIRED" if datetime.now(timezone.utc) > memo.expires_at else "ACTIVE"
    record_state = "NOT RECORDED" if review_count == 0 else esc(str(review_count) + " SESSION RECORD(S)")
    pattern_status = pattern_bridge.status_label if pattern_bridge is not None else "NOT RUN"
    st.markdown(
        f'''<div class="mi-strategy-ribbon">
          <div><span>STRATEGIC RESPONSE</span><b>{esc(memo.disposition.value)}</b></div>
          <div><span>PROCESS DECISION</span><b>{esc(selected.label)}</b></div>
          <div><span>RESEARCH READINESS</span><b>{esc(assessment.decision.state.value)}</b></div>
          <div><span>FOCUS HORIZON</span><b>{esc(memo.context.horizon.upper())}</b></div>
          <div><span>MEMO / HUMAN RECORD</span><b>{esc(memo_validity)} · {record_state}</b></div>
          <div><span>ML PATTERN ADDENDUM</span><b>{esc(pattern_status)} · NOT ADMITTED</b></div>
          <div><span>CAPITAL / EXECUTION</span><b>UNPRICED · DISABLED</b></div>
        </div>''',
        unsafe_allow_html=True,
    )


def _render_decision_record(memo: StrategicDecisionMemo) -> None:
    flash = st.session_state.pop("mi_strategy_record_flash", None)
    if flash:
        st.success(str(flash))
    section_header(
        "HUMAN DISPOSITION",
        "Non-authorizing strategic decision record",
        "SESSION ONLY · HASH CHAINED · NO APPROVAL OR EXECUTION",
    )
    selectable = [option for option in memo.options if option.selectable_for_session_record]
    option_by_id = {option.option_id: option for option in selectable}
    decision_clock = datetime.now(timezone.utc)
    memo_is_expired = decision_clock > memo.expires_at
    if memo_is_expired:
        allowed_dispositions = (
            HumanDisposition.RETURN_FOR_EVIDENCE,
            HumanDisposition.REJECT_MEMO,
        )
        st.warning(
            f"Memo expired {memo.expires_at:%Y-%m-%d %H:%M UTC}. Any record is retrospective and "
            "EXPIRED; DEFER and advancement are disabled. Rebuild from a current governed snapshot."
        )
    else:
        allowed_dispositions = (
            HumanDisposition.RETURN_FOR_EVIDENCE,
            HumanDisposition.DEFER,
            HumanDisposition.REJECT_MEMO,
            *(
                (HumanDisposition.ADVANCE_TO_INDEPENDENT_REVIEW,)
                if memo.disposition == StrategicDisposition.READY_FOR_HUMAN_REVIEW
                else ()
            ),
        )
    with st.form("mi_strategic_disposition_form"):
        a, b, c = st.columns([1.3, 1.0, 1.0])
        with a:
            option_id = st.selectbox(
                "PROCESS OPTION",
                tuple(option_by_id),
                format_func=lambda value: option_by_id[value].label,
                key="mi_strategy_option_choice",
            )
        with b:
            disposition = st.selectbox(
                "HUMAN DISPOSITION",
                allowed_dispositions,
                format_func=lambda value: value.value.replace("_", " "),
                key="mi_strategy_human_disposition",
            )
        with c:
            actor_role = st.selectbox(
                "ACTOR ROLE",
                (
                    "RESEARCH_STRATEGY_LEAD",
                    "INDEPENDENT_RISK_REVIEWER",
                    "INVESTMENT_COMMITTEE_SECRETARY",
                ),
                key="mi_strategy_actor_role",
            )
        actor_id = st.text_input(
            "ACTOR / COMMITTEE ID · SELF-ASSERTED / UNVERIFIED",
            key="mi_strategy_actor_id",
            placeholder="Required for attributable session record",
        )
        rationale = st.text_area(
            "RATIONALE",
            key="mi_strategy_rationale",
            placeholder="State why this process decision is appropriate, what remains unknown, and what would change it.",
        )
        acknowledged = st.checkbox(
            "I understand this is a session-only research disposition, not capital approval or execution authority.",
            key="mi_strategy_acknowledgement",
        )
        submitted = st.form_submit_button(
            "RECORD NON-AUTHORIZING STRATEGIC DISPOSITION",
            type="secondary",
            width="stretch",
        )
    if submitted:
        if not acknowledged:
            st.error("Explicit acknowledgement is required; no record was created.")
        else:
            try:
                journal = _journal()
                record = journal.append(
                    memo,
                    disposition=disposition,
                    selected_process_option_id=option_id,
                    actor_id=actor_id,
                    actor_role=actor_role,
                    rationale=rationale,
                    recorded_at=datetime.now(timezone.utc),
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.session_state["mi_strategy_journal"] = list(journal.records)
                st.session_state["mi_strategy_record_flash"] = (
                    f"Session disposition recorded · {record.record_id} · {record.memo_validity.value} memo · "
                    "execution remains disabled."
                )
                st.rerun()

    journal = _journal()
    current_records = tuple(item for item in journal.records if item.memo_id == memo.memo_id)
    other_record_count = len(journal.records) - len(current_records)
    if current_records:
        records = pd.DataFrame(
            [
                {
                    "Record": item.record_id,
                    "Memo": item.memo_id,
                    "Context": item.context_id,
                    "Subject": item.subject_symbol,
                    "Horizon / purpose": f"{item.decision_horizon} · {item.decision_purpose.value}",
                    "Basis packet": item.basis_packet_id,
                    "Validation run": item.basis_validation_run_id,
                    "Disposition": item.disposition.value,
                    "Process option": item.selected_process_option_id,
                    "Actor": item.actor_id,
                    "Role": item.actor_role,
                    "Identity": item.identity_assurance,
                    "Memo validity": item.memo_validity.value,
                    "Recorded at": item.recorded_at.isoformat(),
                    "Memo expires": item.memo_expires_at.isoformat(),
                    "Scope": item.scope,
                    "Record hash": item.record_hash,
                }
                for item in current_records
            ]
        )
        bounded_table(records, height=220)
    if other_record_count:
        st.caption(
            f"{other_record_count} record(s) from other memo contexts remain in the full session chain and are "
            "intentionally excluded from this memo view."
        )
    if journal.records:
        st.download_button(
            "EXPORT SESSION DECISION JOURNAL · JSON",
            data=canonical_json(
                {
                    "schema_version": "mi-strategy-session-journal-1.0.0",
                    "current_context": {
                        "memo_id": memo.memo_id,
                        "context_id": memo.context.context_id,
                        "basis_evidence_root": memo.basis_evidence_root,
                    },
                    "journal_root": journal.root_hash,
                    "records": journal.records,
                    "scope": "SESSION_ONLY_NON_AUTHORIZING",
                    "record_count": len(journal.records),
                    "contains_multiple_memos": len({item.memo_id for item in journal.records}) > 1,
                }
            ),
            file_name=f"mi_strategy_journal_{memo.context.subject_symbol}_{memo.memo_id}.json",
            mime="application/json",
            width="stretch",
            type="secondary",
            key="mi_export_strategy_journal",
        )


def render_strategic_decision_room(
    snapshot: WorkspaceSnapshot,
    assessment: GovernanceAssessment,
    memo: StrategicDecisionMemo,
    *,
    pattern_bridge: PatternStrategyBridge | None = None,
) -> None:
    selected = next(
        option for option in memo.options if option.option_id == memo.recommended_process_option_id
    )
    memo_validity = "EXPIRED" if datetime.now(timezone.utc) > memo.expires_at else "ACTIVE"
    section_header(
        "STRATEGY ROOM / DECISION FRAME",
        "Strategic Decision Office",
        "RESEARCH → OPTIONS → IMPACT → INVALIDATION → HUMAN DISPOSITION",
    )
    st.markdown(
        f'''<div class="mi-decision-hero">
          <div class="mi-decision-question"><span>DECISION QUESTION</span><h3>{esc(memo.context.question)}</h3>
            <p>Requested {esc(memo.context.requested_symbol)} · governed subject {esc(memo.context.subject_symbol)} · horizon {esc(memo.context.horizon.upper())}</p></div>
          <div class="mi-decision-answer"><span>SNAPSHOT-CLOCK STRATEGIC RESPONSE</span><h3>{esc(memo.disposition.value.replace("_", " "))}</h3>
            <p>{esc(memo.process_summary)} · Memo {esc(memo_validity)}; expires {esc(memo.expires_at.strftime('%Y-%m-%d %H:%M UTC'))}.</p></div>
        </div>''',
        unsafe_allow_html=True,
    )
    summary_items = (
        ("Process decision", selected.label, f"{memo.decision_strength} advisory action", "cyan"),
        ("Portfolio decision", "DEFERRED", "No preferred capital option", "amber"),
        ("Portfolio impact", "UNPRICED", "Mandate and exposure absent", "amber"),
        ("Research readiness", memo.research_state, f"{len(memo.blockers)} blocker(s)", tone_for_status(memo.research_state)),
        ("Memo validity", memo_validity, f"Expires {memo.expires_at:%Y-%m-%d %H:%M UTC}", tone_for_status(memo_validity)),
        (
            "ML pattern addendum",
            pattern_bridge.status_label if pattern_bridge is not None else "NOT RUN",
            "Separate session evidence · memo unchanged",
            tone_for_status(pattern_bridge.state.value if pattern_bridge is not None else "NOT_RUN"),
        ),
        ("Execution", "DISABLED", memo.authority, "red"),
    )
    summary_html = "".join(
        f'<div class="mi-card"><div class="mi-card-title">{esc(label)}</div>'
        f'<div class="mi-card-value mi-value-{esc(tone)}">{esc(value)}</div>'
        f'<div class="mi-card-note">{esc(note)}</div></div>'
        for label, value, note, tone in summary_items
    )
    st.markdown(f'<div class="mi-decision-summary">{summary_html}</div>', unsafe_allow_html=True)

    supporting = [claim.statement for claim in memo.claims if claim.kind.value in {"OBSERVED", "DERIVED"}]
    challenging = [claim.statement for claim in memo.claims if claim.kind.value in {"COUNTEREVIDENCE", "UNKNOWN", "ASSUMPTION"}]
    brief_tab, options_tab, monitoring_tab, pattern_tab, evidence_tab, journal_tab = st.tabs(
        (
            "DECISION BRIEF",
            "OPTIONS",
            "MONITOR / INVALIDATE",
            "ML PATTERN ADDENDUM",
            "EVIDENCE & LINEAGE",
            "HUMAN JOURNAL",
        )
    )
    with brief_tab:
        a, b = st.columns(2, gap="medium")
        with a:
            evidence_block("Evidence supporting the process decision", supporting, tone="green")
        with b:
            evidence_block("Contradictions, unknowns and assumptions", challenging, tone="amber")
        section_header("IMPACT", "Decision impact and uncertainty", "NO SYNTHETIC SCORE · NO INVENTED PROBABILITY")
        bounded_table(impact_frame(memo), height=290)

    with options_tab:
        section_header("ALTERNATIVES", "Strategic options matrix", "PROCESS · PORTFOLIO REVIEW · PROHIBITED EXECUTION")
        bounded_table(option_frame(memo), height=430)
        st.caption(
            "A preferred process option is not a preferred portfolio action. Portfolio review remains blocked or "
            "unpriced until the governed evidence, mandate, exposure and human authority are complete."
        )

    with monitoring_tab:
        section_header("MONITOR / INVALIDATE", "Strategic monitoring plan", "TRIGGERS · OWNERS · SOURCE VIEWS")
        bounded_table(monitoring_frame(memo), height=330)

    with pattern_tab:
        section_header(
            "SESSION ADDENDUM",
            "ML pattern evidence bridge",
            "SEPARATE ARTIFACT · CURRENT MEMO IMMUTABLE · NO CAPITAL AUTHORITY",
        )
        if pattern_bridge is None:
            st.info(
                "No governed pattern discovery report is attached to this session. Run the ML Pattern Discovery "
                "workspace to create a dataset-bound research addendum."
            )
        else:
            bridge_tone = tone_for_status(pattern_bridge.state.value)
            st.markdown(
                f'''<div class="mi-decision-hero"><div class="mi-decision-question"><span>BRIDGE STATE</span>
                <h3>{esc(pattern_bridge.status_label)}</h3><p>{esc(pattern_bridge.reason)}</p></div>
                <div class="mi-decision-answer mi-decision-answer-{esc(bridge_tone)}"><span>BOUNDED STRATEGIC ACTION</span>
                <h3>{esc(pattern_bridge.state.value.replace("_", " "))}</h3>
                <p>{esc(pattern_bridge.strategic_action)}</p></div></div>''',
                unsafe_allow_html=True,
            )
            bridge_frame = pd.DataFrame(
                [
                    {"Control": "Pattern report", "State": pattern_bridge.report_id or "NOT RUN"},
                    {"Control": "Current strategic memo", "State": pattern_bridge.memo_id or memo.memo_id},
                    {"Control": "Admitted to current memo", "State": "NO — evidence root immutable"},
                    {
                        "Control": "Eligible for governed rebuild",
                        "State": "YES" if pattern_bridge.admissible_for_governed_rebuild else "NO",
                    },
                    {"Control": "Capital authority", "State": "NONE"},
                    {"Control": "Execution", "State": "DISABLED"},
                ]
            )
            bounded_table(bridge_frame, height=250)
        if st.button(
            "OPEN ML PATTERN DISCOVERY",
            key="mi_strategy_open_patterns_addendum",
            width="stretch",
            type="secondary",
        ):
            set_active_view(st.session_state, "patterns")
            st.rerun()

    with evidence_tab:
        lineage_items = (
            ("MEMO", memo.memo_id, memo.schema_version),
            ("REVIEW CLOCK", memo.review_at.strftime("%Y-%m-%d %H:%M UTC"), "Snapshot-clock horizon"),
            (
                "MEMO VALIDITY",
                memo_validity,
                "Expires " + memo.expires_at.strftime("%Y-%m-%d %H:%M UTC"),
            ),
            ("OWNER", memo.context.owner_status, memo.context.owner_role),
            ("EVIDENCE ROOT", "VERIFIED", memo.basis_evidence_root[:16] + "…"),
            ("AUTHORITY", memo.authority, "No order payload"),
        )
        lineage_html = "".join(
            f'<div class="mi-status-badge mi-status-badge-{esc(tone_for_status(status))}">'
            f'<span>{esc(label)}</span><b>{esc(status)}</b><small>{esc(detail)}</small></div>'
            for label, status, detail in lineage_items
        )
        st.markdown(f'<div class="mi-lineage-grid">{lineage_html}</div>', unsafe_allow_html=True)
        st.download_button(
            "EXPORT STRATEGIC DECISION MEMO · JSON",
            data=canonical_json(memo),
            file_name=f"mi_strategic_memo_{snapshot.symbol}_{memo.memo_id}.json",
            mime="application/json",
            width="stretch",
            type="secondary",
            key="mi_export_strategic_memo",
        )
        links = st.columns(5)
        for column, view, label in zip(
            links,
            ("research", "information-gap", "forecast", "patterns", "models"),
            (
                "OPEN VALIDATION GATES",
                "OPEN INFORMATION GAPS",
                "OPEN FORECAST EVIDENCE",
                "OPEN PATTERN ML",
                "OPEN MODEL RISK",
            ),
        ):
            with column:
                if st.button(label, key=f"mi_strategy_open_{view}", width="stretch", type="secondary"):
                    set_active_view(st.session_state, view)
                    st.rerun()

    with journal_tab:
        _render_decision_record(memo)
    st.caption(
        f"Memo {memo.memo_id} · research packet {memo.basis_packet_id} · validation {memo.basis_validation_run_id} · "
        "human disposition records remain session-scoped until durable audited storage is connected."
    )
