"""Fail-closed bridge between session pattern research and strategic governance."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from ..contracts import WorkspaceSnapshot
from ..evidence import canonical_hash
from .contracts import (
    ADMISSIBLE_PRICE_ADJUSTMENT_POLICIES,
    ADMISSIBLE_REVISION_POLICIES,
    GateState,
    PATTERN_ENGINE_VERSION,
    PATTERN_POLICY_VERSION,
    PATTERN_SCHEMA_VERSION,
    PatternBridgeState,
    PatternCandidateState,
    PatternDiscoveryReport,
    PatternRunState,
    PatternStrategyBridge,
    STRATEGIC_ADMISSION_GATE_IDS,
)


def build_pattern_strategy_bridge(
    snapshot: WorkspaceSnapshot,
    report: PatternDiscoveryReport | None,
    *,
    current_dataset_id: str | None,
    memo_id: str | None,
) -> PatternStrategyBridge:
    integrity = dict(snapshot.audit.get("context_integrity") or {})
    requested = str(integrity.get("requested_symbol") or "UNKNOWN").strip().upper()
    fixture = str(integrity.get("fixture_symbol") or "UNKNOWN").strip().upper()
    context_state = str(integrity.get("state") or "UNKNOWN").strip().upper()
    fusion_allowed = integrity.get("fusion_allowed") is True
    governed_subject = snapshot.symbol.strip().upper()
    try:
        report_hash_valid = report.verify_hash() if report is not None else False
    except Exception:
        report_hash_valid = False

    if report is None:
        state = PatternBridgeState.NOT_RUN
        status = "NOT RUN"
        action = "Run governed Pattern Discovery on a sufficiently deep chronological dataset."
        reason = "No session-bound ML pattern report exists."
        eligible = False
        report_id = None
    elif not report_hash_valid:
        state = PatternBridgeState.WAITING_VALIDATION
        status = "REPORT INTEGRITY BLOCK"
        action = "Discard the altered artifact and re-run governed pattern discovery."
        reason = "The pattern report content no longer matches its immutable content hash."
        eligible = False
        report_id = report.report_id
    elif (
        report.schema_version != PATTERN_SCHEMA_VERSION
        or report.engine_version != PATTERN_ENGINE_VERSION
        or report.policy_version != PATTERN_POLICY_VERSION
    ):
        state = PatternBridgeState.WAITING_VALIDATION
        status = "VERSION / POLICY QUARANTINE"
        action = "Re-run discovery with the active governed schema, engine and policy versions."
        reason = (
            f"Received schema/engine/policy {report.schema_version} / {report.engine_version} / "
            f"{report.policy_version}; required {PATTERN_SCHEMA_VERSION} / {PATTERN_ENGINE_VERSION} / "
            f"{PATTERN_POLICY_VERSION}."
        )
        eligible = False
        report_id = report.report_id
    elif (
        report.autonomous_trading
        or report.execution_allowed
        or report.order_payload is not None
        or not report.human_review_required
        or any(candidate.execution_allowed for candidate in report.candidates)
    ):
        state = PatternBridgeState.WAITING_VALIDATION
        status = "AUTHORITY QUARANTINE"
        action = "Discard the authority-bearing artifact and re-run under the research-only contract."
        reason = (
            "The bridge independently detected autonomous, execution, order or human-review authority "
            "in a pattern artifact; those capabilities are prohibited even when its hash is valid."
        )
        eligible = False
        report_id = report.report_id
    elif any(
        candidate.state == PatternCandidateState.OOS_SUPPORTED_HYPOTHESIS
        for candidate in report.candidates
    ):
        state = PatternBridgeState.WAITING_VALIDATION
        status = "POLICY CLAIM QUARANTINE"
        action = "Re-run under a future policy that explicitly defines and validates a support claim."
        reason = (
            "The active pattern policy permits run-local screened hypotheses only; an "
            "OOS_SUPPORTED_HYPOTHESIS claim is inadmissible under this version."
        )
        eligible = False
        report_id = report.report_id
    elif report.state != PatternRunState.COMPLETED_RESEARCH_ONLY:
        state = PatternBridgeState.WAITING_VALIDATION
        status = report.state.value
        action = "Satisfy data and model controls before strategic review."
        reason = report.reason
        eligible = False
        report_id = report.report_id
    elif context_state != "MATCHED" or not fusion_allowed:
        state = PatternBridgeState.BLOCKED_SUBJECT
        status = "CONTEXT QUARANTINE"
        action = "Restore a MATCHED, fusion-authorized governed context before interpretation."
        reason = (
            f"Context integrity is {context_state}; fusion authorization is "
            f"{'YES' if fusion_allowed else 'NO'}."
        )
        eligible = False
        report_id = report.report_id
    elif (
        report.symbol != governed_subject
        or report.input_audit.symbol != governed_subject
        or report.input_audit.source_symbol != governed_subject
        or not report.input_audit.subject_match
        or requested != governed_subject
        or fixture != governed_subject
    ):
        state = PatternBridgeState.BLOCKED_SUBJECT
        status = "SUBJECT BLOCKED"
        action = "Resolve requested, dataset and governed subject identity before interpretation."
        reason = (
            f"Report/audit/source/requested/fixture/governed subjects are {report.symbol} / "
            f"{report.input_audit.symbol} / {report.input_audit.source_symbol} / {requested} / "
            f"{fixture} / {governed_subject}; source subject match is "
            f"{'YES' if report.input_audit.subject_match else 'NO'}."
        )
        eligible = False
        report_id = report.report_id
    elif current_dataset_id is None or report.input_audit.dataset_id != current_dataset_id:
        state = PatternBridgeState.STALE_DATASET
        status = "STALE / DETACHED"
        action = "Re-run discovery on the currently inherited terminal dataset."
        reason = "The session report is not bound to the current dataset identity."
        eligible = False
        report_id = report.report_id
    elif (
        report.input_audit.blocking_reasons
        or report.input_audit.normalized_rows <= 0
        or not report.input_audit.chronological
        or not report.input_audit.unique_timestamps
        or not report.input_audit.open_price_observed
        or not report.input_audit.corporate_action_safe
        or report.input_audit.price_adjustment_policy
        not in ADMISSIBLE_PRICE_ADJUSTMENT_POLICIES
        or (
            not report.input_audit.adjusted_close_observed
            and report.input_audit.price_adjustment_policy
            != "NATIVE_NON_CORPORATE_ACTION_SERIES"
        )
    ):
        state = PatternBridgeState.WAITING_LINEAGE
        status = "PRICE / INPUT CONTRACT QUARANTINE"
        action = "Restore complete observed price provenance and a clean chronological input contract, then re-run."
        reason = (
            "The bridge independently rejected the report input audit: observed next-open pricing, "
            "corporate-action-safe adjustment provenance, chronological uniqueness and zero blocking reasons "
            "are mandatory."
        )
        eligible = False
        report_id = report.report_id
    elif not (
        report.input_audit.pit_lineage_complete
        and report.input_audit.source_identified
        and report.input_audit.subject_match
        and report.input_audit.point_in_time_declared
        and report.input_audit.row_lineage_complete
        and report.input_audit.source_known_at is not None
        and report.input_audit.latest_row_known_at is not None
        and report.input_audit.data_cutoff is not None
        and report.input_audit.source_known_at >= report.input_audit.data_cutoff
        and report.input_audit.source_known_at >= report.input_audit.latest_row_known_at
        and report.input_audit.revision_policy in ADMISSIBLE_REVISION_POLICIES
    ):
        state = PatternBridgeState.WAITING_LINEAGE
        status = "LINEAGE QUARANTINE"
        action = "Acquire point-in-time known-at and revision lineage, then re-run the evidence chain."
        reason = (
            "The input audit itself does not attest complete provider, row, revision and availability lineage; "
            "a report gate cannot override that source contract."
        )
        eligible = False
        report_id = report.report_id
    elif any(
        clock is None
        for clock in (
            report.input_audit.data_cutoff,
            report.input_audit.source_known_at,
            report.input_audit.latest_row_known_at,
            report.evaluated_at,
        )
    ):
        state = PatternBridgeState.CLOCK_MISMATCH
        status = "CLOCK QUARANTINE"
        action = "Re-run with complete cutoff, known-at, row-lineage and evaluation clocks."
        reason = "Pattern evidence is missing at least one mandatory availability clock."
        eligible = False
        report_id = report.report_id
    elif any(
        clock > datetime.now(timezone.utc) + timedelta(minutes=5)
        for clock in (
            report.input_audit.data_cutoff,
            report.input_audit.source_known_at,
            report.input_audit.latest_row_known_at,
            report.evaluated_at,
        )
        if clock is not None
    ):
        state = PatternBridgeState.CLOCK_MISMATCH
        status = "FUTURE CLOCK QUARANTINE"
        action = "Correct future-dated evidence clocks and re-run from the observed wall-clock state."
        reason = "At least one pattern evidence clock is more than five minutes in the future."
        eligible = False
        report_id = report.report_id
    elif any(
        clock > snapshot.as_of
        for clock in (
            report.input_audit.data_cutoff,
            report.input_audit.source_known_at,
            report.input_audit.latest_row_known_at,
            report.evaluated_at,
        )
        if clock is not None
    ):
        state = PatternBridgeState.CLOCK_MISMATCH
        status = "CLOCK QUARANTINE"
        action = "Rebuild a governed snapshot at or after every pattern evidence clock."
        reason = (
            "At least one dataset cutoff, provider known-at, latest-row known-at or evaluation clock is "
            "newer than the immutable strategic snapshot and cannot be backfilled into its memo."
        )
        eligible = False
        report_id = report.report_id
    else:
        gates_by_id = {gate.gate_id: gate for gate in report.gates}
        duplicate_gate_ids = len(gates_by_id) != len(report.gates)
        unknown_gate_ids = gates_by_id.keys() - STRATEGIC_ADMISSION_GATE_IDS
        missing_gate_ids = STRATEGIC_ADMISSION_GATE_IDS - gates_by_id.keys()
        nonpassing_gate_ids = {
            gate_id
            for gate_id in STRATEGIC_ADMISSION_GATE_IDS
            if gate_id in gates_by_id and gates_by_id[gate_id].state != GateState.PASS
        }
        lineage = gates_by_id.get("PIT_PROVIDER_LINEAGE")
        if lineage is None or lineage.state != GateState.PASS:
            state = PatternBridgeState.WAITING_LINEAGE
            status = "LINEAGE QUARANTINE"
            action = "Acquire point-in-time known-at and revision lineage, then re-run the evidence chain."
            reason = lineage.reason if lineage is not None else "No point-in-time lineage gate exists."
            eligible = False
        elif duplicate_gate_ids or unknown_gate_ids or missing_gate_ids or nonpassing_gate_ids:
            state = PatternBridgeState.WAITING_VALIDATION
            status = "VALIDATION QUARANTINE"
            action = "Close every mandatory strategic admission gate under the active bridge policy."
            details = ["duplicate gate identifiers"] if duplicate_gate_ids else []
            details.extend(f"unknown {gate_id}" for gate_id in sorted(unknown_gate_ids))
            details.extend(f"missing {gate_id}" for gate_id in sorted(missing_gate_ids))
            details.extend(
                f"{gate_id}: {gates_by_id[gate_id].state.value} — {gates_by_id[gate_id].reason}"
                for gate_id in sorted(nonpassing_gate_ids)
            )
            reason = "; ".join(details)
            eligible = False
        else:
            state = PatternBridgeState.ELIGIBLE_FOR_GOVERNED_REBUILD
            status = "REBUILD ELIGIBLE"
            action = "Rebuild governance and strategic memo from the enlarged immutable evidence packet."
            reason = "All pattern admission gates pass; the current memo still remains immutable."
            eligible = True
        report_id = report.report_id

    material: dict[str, Any] = {
        "state": state,
        "report_id": report_id,
        "memo_id": memo_id,
        "status_label": status,
        "strategic_action": action,
        "reason": reason,
        "admissible_for_governed_rebuild": eligible,
        "admitted_to_current_memo": False,
        "capital_authority": False,
        "execution_allowed": False,
    }
    return PatternStrategyBridge(
        bridge_id="MI-PBR-" + canonical_hash(material)[:20].upper(),
        **material,
    )
