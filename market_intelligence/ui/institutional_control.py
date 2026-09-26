"""Institutional governance presentation and decision-dossier helpers."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from ..contracts import WorkspaceSnapshot
from ..evidence import canonical_json
from ..governance import GOVERNANCE_ENGINE_VERSION, GovernanceAssessment, assess_workspace
from ..risk.scenarios import institutional_research_scenarios
from ..strategy import StrategicDecisionMemo, build_strategic_decision_memo
from .strategic_decision import monitoring_frame, option_frame
from .common import bounded_table, esc, section_header, status_badge, tone_for_status


def governance_assessment(snapshot: WorkspaceSnapshot) -> GovernanceAssessment:
    """Rebuild the packet from the exact snapshot; never reuse cross-rerun evidence."""

    return assess_workspace(snapshot)


def render_governance_bar(assessment: GovernanceAssessment) -> None:
    """Render the always-visible institutional control spine."""

    decision = assessment.decision
    gates = decision.validation.gates
    passed = sum(gate.status.value == "PASS" for gate in gates)
    waiting = sum(gate.status.value == "WAITING_EVIDENCE" for gate in gates)
    failed = sum(gate.status.value == "FAIL" for gate in gates)
    usable_layers = sum(item.state.value in {"current", "degraded"} for item in decision.quality)
    invalid_layers = sum(item.state.value in {"invalid", "stale"} for item in decision.quality)
    quality_state = "INVALID" if invalid_layers else "WAITING_EVIDENCE" if usable_layers < len(decision.quality) else "PASS"
    gate_state = "FAIL" if failed else "WAITING_EVIDENCE" if waiting else "PASS"
    if decision.state.value == "ELIGIBLE_FOR_HUMAN_REVIEW":
        review_state = "ELIGIBLE"
        review_detail = "Independent human review not started"
    elif decision.state.value == "REJECTED":
        review_state = "BLOCKED"
        review_detail = "Hard control failure"
    else:
        review_state = "NOT ELIGIBLE"
        review_detail = "Pending admissible evidence"
    items = (
        ("RESEARCH READINESS", decision.state.value, decision.posture.value),
        ("DATA QUALITY", quality_state, f"{usable_layers}/{len(decision.quality)} usable · {invalid_layers} invalid/stale"),
        ("CONTROL GATES", gate_state, f"{passed} pass · {waiting} waiting · {failed} fail"),
        ("EVIDENCE CHAIN", "VERIFIED", f"{len(assessment.ledger.records)} records · {decision.evidence_root[:12]}…"),
        ("HUMAN REVIEW", review_state, review_detail),
        ("EXECUTION", "DISABLED", f"Packet {decision.packet_id[-10:]}"),
    )
    rendered = "".join(
        f'<div class="mi-status-badge mi-status-badge-{esc(tone_for_status(status))}">'
        f'<span>{esc(label)}</span><b>{esc(status)}</b><small>{esc(detail)}</small></div>'
        for label, status, detail in items
    )
    st.markdown(f'<div class="mi-governance-grid">{rendered}</div>', unsafe_allow_html=True)


def quality_frame(assessment: GovernanceAssessment) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Layer": item.layer,
                "State": item.state.value.upper(),
                "Required": "YES" if item.required else "NO",
                "Source status": item.source_status.value.upper(),
                "As of": item.as_of.isoformat(),
                "Replay age sec": item.age_seconds,
                "Evaluation clock": "SNAPSHOT_AS_OF",
                "Completeness": item.completeness,
                "Flags": " · ".join(item.flags) or "NONE",
                "Evidence": " · ".join(item.evidence_ids) or "UNLINKED",
            }
            for item in assessment.decision.quality
        ]
    )


def gate_frame(assessment: GovernanceAssessment) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Gate": gate.gate_id,
                "Control": gate.label,
                "State": gate.status.value,
                "Blocking now": "YES" if gate.blocks_progression else "NO",
                "Policy blocking": "YES" if gate.blocking else "NO",
                "Reason": gate.reason,
                "Evidence count": len(gate.evidence_ids),
            }
            for gate in assessment.decision.validation.gates
        ]
    )


def model_registry_frame(assessment: GovernanceAssessment) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Model": record.model_id,
                "Version": record.version,
                "Role": record.role.value.upper(),
                "Lifecycle": record.lifecycle.value.upper(),
                "Promotion": record.promotion_state.value,
                "Feature set": record.feature_set_version,
                "Data cutoff": record.data_cutoff.isoformat(),
                "Artifact hash": record.artifact_hash[:16] + "…",
                "Config hash": record.config_hash[:16] + "…",
                "Training data hash": record.training_data_hash[:16] + "…",
                "Validation run": record.validation_run_id or "NONE",
                "Validation root": (
                    record.validation_evidence_root[:16] + "…"
                    if record.validation_evidence_root
                    else "NONE"
                ),
                "Approval": record.approval_id or "NONE",
                "Rollback": record.rollback_model_id or "NONE",
                "Boundary": record.research_boundary,
            }
            for record in assessment.model_registry.records
        ]
    )


def risk_frame(assessment: GovernanceAssessment) -> pd.DataFrame:
    focus_horizon = str(st.session_state.get("mi_horizon", "30m"))
    return pd.DataFrame(
        [
            {
                "Focus": "● SELECTED" if item.horizon == focus_horizon else "",
                "Scenario": item.scenario_id,
                "Model": f"{item.model_id} · {item.model_version}",
                "Horizon": item.horizon,
                "State": item.state.value.upper(),
                "Base Q05": item.base_q05,
                "Base Q50": item.base_q50,
                "Base Q95": item.base_q95,
                "Stress Q05": item.stressed_q05,
                "Stress Q50": item.stressed_q50,
                "Stress Q95": item.stressed_q95,
                "Method": item.method,
                "Flags": " · ".join(item.flags),
            }
            for item in assessment.risk_envelope.assessments
        ]
    )


def evidence_frame(assessment: GovernanceAssessment) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Evidence ID": record.evidence_id,
                "Kind": record.kind,
                "Source": record.source,
                "Observed at": record.observed_at.isoformat(),
                "Known at": record.known_at.isoformat(),
                "Recorded at": record.recorded_at.isoformat(),
                "Payload hash": record.payload_hash[:16] + "…",
                "Previous hash": record.previous_hash[:16] + "…",
                "Record hash": record.record_hash[:16] + "…",
                "Flags": " · ".join(record.flags) or "NONE",
            }
            for record in assessment.ledger.records
        ]
    )


def decision_dossier_json(
    assessment: GovernanceAssessment,
    snapshot: WorkspaceSnapshot,
    strategic_memo: StrategicDecisionMemo | None = None,
) -> str:
    """Serialize the full reproducible dossier without leaking runtime objects."""

    if strategic_memo is None:
        horizons = tuple(forecast.horizon for forecast in snapshot.forecasts)
        strategic_memo = build_strategic_decision_memo(
            snapshot,
            assessment,
            horizon=horizons[0],
        )
    else:
        expected_memo = build_strategic_decision_memo(
            snapshot,
            assessment,
            horizon=strategic_memo.context.horizon,
            purpose=strategic_memo.context.purpose,
        )
        if strategic_memo != expected_memo:
            raise ValueError("Strategic memo does not bind the supplied snapshot and governance assessment")
    return canonical_json(
        {
            "replay_contract": {
                "engine": "market_intelligence.governance.assess_workspace",
                "engine_version": GOVERNANCE_ENGINE_VERSION,
                "evaluation_clock": "SNAPSHOT_AS_OF",
                "evaluated_at": assessment.decision.validation.completed_at,
                "policy_version": assessment.decision.validation.policy_version,
            },
            "source_contracts": {
                "symbol": snapshot.symbol,
                "instrument_name": snapshot.instrument_name,
                "as_of": snapshot.as_of,
                "price": snapshot.price,
                "price_change": snapshot.price_change,
                "regime": snapshot.regime,
                "regime_probability": snapshot.regime_probability,
                "overall_status": snapshot.overall_status,
                "market_status": snapshot.market_status,
                "catalyst_status": snapshot.catalyst_status,
                "microstructure_level": snapshot.microstructure_level,
                "provider_health": snapshot.provider_health,
                "events": snapshot.events,
                "microstructure": snapshot.microstructure,
                "forecasts": snapshot.forecasts,
                "interaction": snapshot.interaction,
                "context_integrity": dict(snapshot.audit.get("context_integrity") or {}),
                "information_gap": dict(snapshot.audit.get("information_gap") or {}),
            },
            "scenario_definitions": institutional_research_scenarios(),
            "decision_packet": assessment.decision,
            "evidence_ledger": assessment.ledger.records,
            "model_registry": assessment.model_registry,
            "risk_envelope": assessment.risk_envelope,
            "strategic_decision_memo": strategic_memo,
            "authority_contract": {
                "scope": "ADVISORY_ONLY",
                "capital_authority": False,
                "execution_allowed": False,
                "order_payload": None,
                "human_decision_required": True,
            },
        }
    )


def render_dossier_identity(
    assessment: GovernanceAssessment,
    snapshot: WorkspaceSnapshot,
    strategic_memo: StrategicDecisionMemo | None = None,
) -> None:
    decision = assessment.decision
    if strategic_memo is None:
        focus_horizon = str(st.session_state.get("mi_horizon", snapshot.forecasts[0].horizon))
        strategic_memo = build_strategic_decision_memo(
            snapshot,
            assessment,
            horizon=focus_horizon,
        )
    section_header("CONTROL DOSSIER", "Immutable decision identity", "HASH-CHAINED · DETERMINISTIC · EXPORTABLE")
    a, b, c, d = st.columns(4)
    with a:
        status_badge("PACKET", decision.packet_id, detail=decision.boundary.value)
    with b:
        status_badge("VALIDATION RUN", decision.validation.run_id, detail=decision.validation.policy_version)
    with c:
        status_badge("EVIDENCE ROOT", "VERIFIED", detail=decision.evidence_root[:24] + "…")
    with d:
        status_badge("RISK ENVELOPE", decision.risk_state.upper(), detail="Scenario assumptions · no execution")
    st.caption(
        f"Strategic memo {strategic_memo.memo_id} · {strategic_memo.disposition.value} · "
        "portfolio impact UNPRICED · advisory only."
    )
    payload = decision_dossier_json(assessment, snapshot, strategic_memo)
    st.download_button(
        "EXPORT REPRODUCIBLE EVIDENCE DOSSIER · JSON",
        data=payload,
        file_name=f"mi_decision_dossier_{decision.symbol}_{decision.packet_id}.json",
        mime="application/json",
        width="stretch",
        type="secondary",
        key="mi_export_decision_dossier",
    )


def render_control_tables(
    assessment: GovernanceAssessment,
    strategic_memo: StrategicDecisionMemo | None = None,
) -> None:
    """Render quality, gates, risk, and evidence in audit-oriented tabs."""

    labels = ["DATA QUALITY", "VALIDATION GATES", "SCENARIO RISK", "EVIDENCE LEDGER"]
    if strategic_memo is not None:
        labels.extend(["STRATEGIC OPTIONS", "MONITOR / INVALIDATE"])
    tabs = st.tabs(labels)
    quality, gates, risk, evidence = tabs[:4]
    with quality:
        bounded_table(quality_frame(assessment), height=330)
    with gates:
        bounded_table(gate_frame(assessment), height=390)
    with risk:
        bounded_table(risk_frame(assessment), height=390)
    with evidence:
        bounded_table(evidence_frame(assessment), height=430)
    if strategic_memo is not None:
        with tabs[4]:
            bounded_table(option_frame(strategic_memo), height=430)
        with tabs[5]:
            bounded_table(monitoring_frame(strategic_memo), height=390)


def decision_tone(assessment: GovernanceAssessment) -> str:
    return tone_for_status(assessment.decision.state.value)


def safe_enum(value: Any) -> str:
    return str(getattr(value, "value", value))
