"""Deterministic orchestration for a fail-closed research decision packet."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ..contracts import AvailabilityStatus, WorkspaceSnapshot, as_utc
from ..data.quality import (
    QualityPolicy,
    QualityState,
    assess_snapshot_quality,
    provider_layer,
)
from ..evidence import EvidenceLedger, canonical_hash
from ..models.registry import baseline_registry_from_snapshot
from ..risk.scenarios import (
    ScenarioState,
    evaluate_scenarios,
    institutional_research_scenarios,
)
from .contracts import (
    DecisionState,
    GateResult,
    GateStatus,
    GovernanceAssessment,
    InstitutionalPolicy,
    ResearchBoundary,
    ResearchDecisionPacket,
    ResearchPosture,
    ValidationRun,
)


def _input_ledger(snapshot: WorkspaceSnapshot, evaluated_at: Any) -> tuple[EvidenceLedger, dict[str, tuple[str, ...]]]:
    evaluation_time = as_utc(evaluated_at)
    if evaluation_time < snapshot.as_of:
        raise ValueError("evaluated_at cannot precede the workspace snapshot")
    ledger = EvidenceLedger()
    provider_evidence: dict[str, list[str]] = {}
    ledger.append(
        evidence_id=f"workspace:{snapshot.symbol}:{snapshot.as_of.isoformat()}",
        kind="workspace_snapshot_header",
        source="market_intelligence",
        observed_at=snapshot.as_of,
        known_at=snapshot.as_of,
        recorded_at=evaluation_time,
        payload={
            "symbol": snapshot.symbol,
            "as_of": snapshot.as_of,
            "overall_status": snapshot.overall_status,
            "market_status": snapshot.market_status,
            "catalyst_status": snapshot.catalyst_status,
            "microstructure_level": snapshot.microstructure_level,
        },
    )
    for index, provider in enumerate(sorted(snapshot.provider_health, key=lambda item: item.provider)):
        layer = provider_layer(provider.provider)
        evidence_id = f"provider:{layer}:{index}"
        provider_evidence.setdefault(layer, []).append(evidence_id)
        ledger.append(
            evidence_id=evidence_id,
            kind="provider_health",
            source=provider.provider,
            observed_at=provider.as_of,
            known_at=provider.as_of,
            recorded_at=max(evaluation_time, provider.as_of),
            payload=provider,
            flags=(provider.status.value.upper(),),
        )
    for event in sorted(snapshot.events, key=lambda item: (item.event_id, item.revision_id)):
        ledger.append(
            evidence_id=f"event:{event.event_id}:{event.revision_id}",
            kind="structured_event",
            source=event.source,
            observed_at=event.publication_time,
            known_at=event.tradable_at,
            recorded_at=evaluation_time,
            payload=event,
            flags=event.validation_flags,
        )
    micro_evidence = ledger.append(
        evidence_id=f"microstructure:{snapshot.microstructure.symbol}:{snapshot.microstructure.as_of.isoformat()}",
        kind="microstructure_snapshot",
        source="workspace_microstructure_layer",
        observed_at=snapshot.microstructure.as_of,
        known_at=snapshot.microstructure.as_of,
        recorded_at=evaluation_time,
        payload=snapshot.microstructure,
        flags=snapshot.microstructure.uncertainty_flags,
    )
    forecast_ids: list[str] = []
    for forecast in sorted(snapshot.forecasts, key=lambda item: (item.model_id, item.model_version, item.horizon)):
        evidence_id = f"forecast:{forecast.model_id}:{forecast.model_version}:{forecast.horizon}"
        forecast_ids.append(evidence_id)
        ledger.append(
            evidence_id=evidence_id,
            kind="forecast_distribution",
            source=forecast.model_id,
            observed_at=forecast.data_cutoff,
            known_at=forecast.as_of,
            recorded_at=evaluation_time,
            payload=forecast,
            flags=forecast.uncertainty_flags,
        )
    ledger.append(
        evidence_id=f"interaction:{snapshot.symbol}:{snapshot.as_of.isoformat()}",
        kind="interaction_assessment",
        source="catalyst_microstructure_baseline",
        observed_at=snapshot.as_of,
        known_at=snapshot.as_of,
        recorded_at=evaluation_time,
        payload=snapshot.interaction,
        flags=snapshot.interaction.validation_flags,
    )
    references = {key: tuple(value) for key, value in provider_evidence.items()}
    references["microstructure"] = (micro_evidence.evidence_id,)
    references["forecasts"] = tuple(forecast_ids)
    return ledger, references


def _gate(
    gate_id: str,
    label: str,
    status: GateStatus,
    reason: str,
    *,
    evidence_ids: tuple[str, ...] = (),
    blocking: bool = True,
) -> GateResult:
    return GateResult(gate_id, label, status, blocking, reason, evidence_ids)


def assess_workspace(
    snapshot: WorkspaceSnapshot,
    *,
    evaluated_at: Any | None = None,
    policy: InstitutionalPolicy | None = None,
    quality_policy: QualityPolicy | None = None,
) -> GovernanceAssessment:
    active_policy = policy or InstitutionalPolicy()
    evaluation_time = snapshot.as_of if evaluated_at is None else as_utc(evaluated_at)
    ledger, evidence = _input_ledger(snapshot, evaluation_time)
    quality = assess_snapshot_quality(
        snapshot,
        evaluated_at=evaluation_time,
        policy=quality_policy,
        evidence_ids={
            layer: identifiers
            for layer, identifiers in evidence.items()
            if layer not in {"microstructure", "forecasts"}
        },
    )
    for assessment in sorted(quality, key=lambda item: item.layer):
        ledger.append(
            evidence_id=f"quality:{assessment.layer}",
            kind="data_quality_assessment",
            source="mi-quality-2.0.0",
            observed_at=evaluation_time,
            known_at=evaluation_time,
            recorded_at=evaluation_time,
            payload=assessment,
            flags=assessment.flags,
        )

    forecast_evidence_by_model: dict[tuple[str, str], list[str]] = {}
    for forecast in snapshot.forecasts:
        forecast_evidence_by_model.setdefault((forecast.model_id, forecast.model_version), []).append(
            f"forecast:{forecast.model_id}:{forecast.model_version}:{forecast.horizon}"
        )
    registry = baseline_registry_from_snapshot(
        snapshot,
        evidence_ids_by_model=forecast_evidence_by_model,
    )
    for record in registry.records:
        ledger.append(
            evidence_id=f"model:{record.model_id}:{record.version}",
            kind="model_registry_record",
            source="mi-model-registry-2.0.0",
            observed_at=record.data_cutoff,
            known_at=record.data_cutoff,
            recorded_at=evaluation_time,
            payload=record,
            flags=record.flags,
        )
    risk_envelope = evaluate_scenarios(
        snapshot.forecasts,
        institutional_research_scenarios(),
        evidence_ids=evidence["forecasts"],
    )
    for assessment in risk_envelope.assessments:
        ledger.append(
            evidence_id=f"scenario:{assessment.scenario_id}:{assessment.horizon}",
            kind="scenario_assessment",
            source=assessment.method,
            observed_at=assessment.as_of,
            known_at=assessment.as_of,
            recorded_at=evaluation_time,
            payload=assessment,
            flags=assessment.flags,
        )
    ledger.verify()

    gates: list[GateResult] = []
    pit_safe = all(
        event.first_seen_time <= event.ingested_at <= event.tradable_at <= event.feature_computed_at <= snapshot.as_of
        and event.publication_time <= event.tradable_at
        for event in snapshot.events
    ) and all(forecast.data_cutoff <= forecast.as_of <= snapshot.as_of for forecast in snapshot.forecasts)
    gates.append(
        _gate(
            "PIT_CHAIN",
            "Point-in-time chain",
            GateStatus.PASS if pit_safe else GateStatus.FAIL,
            "All event and forecast timestamps are prediction-time safe" if pit_safe else "Future or misordered timestamps detected",
            evidence_ids=tuple(record.evidence_id for record in ledger.records if record.kind in {"structured_event", "forecast_distribution"}),
        )
    )
    invalid_quality = [item for item in quality if item.state in {QualityState.INVALID, QualityState.STALE} and item.required]
    waiting_quality = [item for item in quality if item.blocking and item not in invalid_quality]
    if invalid_quality:
        quality_status = GateStatus.FAIL
        quality_reason = "Invalid/stale required layers: " + ", ".join(item.layer for item in invalid_quality)
    elif waiting_quality:
        quality_status = GateStatus.WAITING_EVIDENCE
        quality_reason = "Required layers are simulated, unavailable, or research-only: " + ", ".join(item.layer for item in waiting_quality)
    else:
        quality_status = GateStatus.PASS
        quality_reason = "All required provider layers satisfy the active freshness policy"
    gates.append(
        _gate(
            "DATA_QUALITY",
            "Data quality and freshness",
            quality_status,
            quality_reason,
            evidence_ids=tuple(identifier for item in quality for identifier in item.evidence_ids),
            blocking=active_policy.require_current_data,
        )
    )
    interaction_valid = snapshot.interaction.confidence != "INVALID"
    gates.append(
        _gate(
            "INTERACTION_INPUTS",
            "Catalyst × microstructure inputs",
            GateStatus.PASS if interaction_valid else GateStatus.FAIL,
            "Required interaction inputs are present" if interaction_valid else "Interaction assessment is INVALID",
        )
    )
    calibrated = bool(snapshot.forecasts) and all(
        "UNCALIBRATED" not in forecast.uncertainty_flags
        and "NOT CALIBRATED" not in forecast.calibration_status.upper()
        for forecast in snapshot.forecasts
    )
    gates.append(
        _gate(
            "CALIBRATION",
            "Probability calibration",
            GateStatus.PASS if calibrated else GateStatus.WAITING_EVIDENCE,
            "Calibrated outcome evidence is registered" if calibrated else "No realized prediction/outcome calibration ledger",
            evidence_ids=evidence["forecasts"],
            blocking=active_policy.require_calibration,
        )
    )
    gates.append(
        _gate(
            "CHRONOLOGICAL_OOS",
            "Chronological out-of-sample validation",
            GateStatus.WAITING_EVIDENCE,
            "No registered purged walk-forward OOS evidence",
            blocking=active_policy.require_chronological_oos,
        )
    )
    gates.append(
        _gate(
            "SCENARIO_RISK",
            "Scenario and risk evidence",
            GateStatus.WAITING_EVIDENCE
            if any(item.state != ScenarioState.EVALUATED for item in risk_envelope.assessments)
            else GateStatus.PASS,
            "Scenario transforms are assumption-only and require empirical sensitivities",
            evidence_ids=tuple(item for assessment in risk_envelope.assessments for item in assessment.evidence_ids),
        )
    )
    gates.append(
        _gate(
            "SHADOW_HISTORY",
            "Append-only shadow history",
            GateStatus.WAITING_EVIDENCE,
            "No realized shadow prediction history is registered",
            blocking=active_policy.require_shadow_history,
        )
    )
    gates.append(
        _gate(
            "HUMAN_REVIEW",
            "Human promotion decision",
            GateStatus.WAITING_EVIDENCE,
            "Human review is required after evidence eligibility; execution remains disabled",
            blocking=False,
        )
    )
    gates.append(
        _gate(
            "EVIDENCE_INTEGRITY",
            "Evidence-chain integrity",
            GateStatus.PASS,
            f"Verified {len(ledger.records)} deterministic hash-chained records",
            evidence_ids=tuple(record.evidence_id for record in ledger.records),
        )
    )

    evidence_root = ledger.root_hash
    run_id = "MI-VAL-" + canonical_hash(
        {"policy": active_policy.version, "as_of": evaluation_time, "evidence_root": evidence_root}
    )[:20]
    validation = ValidationRun(
        run_id=run_id,
        policy_version=active_policy.version,
        started_at=evaluation_time,
        completed_at=evaluation_time,
        gates=tuple(gates),
        evidence_root=evidence_root,
    )
    blocking_results = validation.blocking_results
    if any(result.status == GateStatus.FAIL for result in blocking_results):
        state = DecisionState.REJECTED
    elif blocking_results:
        state = DecisionState.WAITING_EVIDENCE
    else:
        state = DecisionState.ELIGIBLE_FOR_HUMAN_REVIEW
    blockers = tuple(f"{result.gate_id}: {result.reason}" for result in blocking_results)
    flags = {
        flag
        for forecast in snapshot.forecasts
        for flag in forecast.uncertainty_flags
    }
    flags.update(snapshot.interaction.validation_flags)
    flags.update(flag for item in quality for flag in item.flags)
    flags.update(flag for item in risk_envelope.assessments for flag in item.flags)
    risk_states = {item.state for item in risk_envelope.assessments}
    if ScenarioState.UNPRICED in risk_states:
        risk_state = ScenarioState.UNPRICED.value
    elif ScenarioState.WAITING_EVIDENCE in risk_states:
        risk_state = ScenarioState.WAITING_EVIDENCE.value
    else:
        risk_state = ScenarioState.EVALUATED.value
    packet_material = {
        "symbol": snapshot.symbol,
        "as_of": snapshot.as_of,
        "boundary": ResearchBoundary.RESEARCH_ONLY,
        "state": state,
        "evidence_root": evidence_root,
        "policy": active_policy.version,
    }
    decision = ResearchDecisionPacket(
        packet_id="MI-DEC-" + canonical_hash(packet_material)[:20],
        symbol=snapshot.symbol,
        as_of=snapshot.as_of,
        boundary=ResearchBoundary.RESEARCH_ONLY,
        state=state,
        posture=ResearchPosture.OBSERVE_ONLY,
        execution_allowed=False,
        human_review_required=True,
        quality=quality,
        validation=validation,
        evidence_root=evidence_root,
        interaction_state=snapshot.interaction.state,
        model_keys=tuple(f"{record.model_id}:{record.version}" for record in registry.records),
        risk_state=risk_state,
        blockers=blockers,
        uncertainty_flags=tuple(sorted(flags)),
    )
    return GovernanceAssessment(decision, ledger, registry, risk_envelope)


def build_research_decision_packet(
    snapshot: WorkspaceSnapshot,
    *,
    evaluated_at: Any | None = None,
    policy: InstitutionalPolicy | None = None,
    quality_policy: QualityPolicy | None = None,
) -> ResearchDecisionPacket:
    return assess_workspace(
        snapshot,
        evaluated_at=evaluated_at,
        policy=policy,
        quality_policy=quality_policy,
    ).decision
