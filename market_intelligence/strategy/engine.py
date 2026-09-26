"""Deterministic strategic synthesis over one governed workspace snapshot."""

from __future__ import annotations

from datetime import timedelta
import math
from typing import Iterable

from ..contracts import WorkspaceSnapshot
from ..evidence import canonical_hash
from ..governance import DecisionState, GateStatus, GovernanceAssessment
from .contracts import (
    ClaimKind,
    DecisionContext,
    DecisionPurpose,
    ImpactAssessment,
    ImpactState,
    MonitoringRule,
    OptionClass,
    OptionStatus,
    StrategicClaim,
    StrategicDecisionMemo,
    StrategicDisposition,
    StrategicOption,
)


SCHEMA_VERSION = "mi-strategy-1.0.0"
ENGINE_VERSION = "mi-strategy-engine-1.0.0"
POLICY_VERSION = "mi-strategy-policy-1.0.0"


def _horizon_delta(label: str) -> timedelta:
    normalized = str(label).strip().lower()
    if normalized.endswith("m"):
        return timedelta(minutes=int(normalized[:-1]))
    if normalized.endswith("h"):
        return timedelta(hours=int(normalized[:-1]))
    if normalized.endswith("d"):
        return timedelta(days=int(normalized[:-1]))
    raise ValueError(f"Unsupported decision horizon: {label}")


def _question(purpose: DecisionPurpose, horizon: str) -> str:
    if purpose == DecisionPurpose.RESEARCH_PRIORITIZATION:
        return "Which evidence programme should be prioritized before the thesis can advance?"
    if purpose == DecisionPurpose.MARKET_MONITORING:
        return f"What must be monitored or invalidate the current thesis over {horizon}?"
    return f"Can the evidence support escalation to a human risk-posture review over {horizon}?"


def build_decision_context(
    snapshot: WorkspaceSnapshot,
    *,
    horizon: str,
    purpose: DecisionPurpose = DecisionPurpose.RESEARCH_PRIORITIZATION,
) -> DecisionContext:
    if not isinstance(purpose, DecisionPurpose):
        raise TypeError("purpose must be a DecisionPurpose")
    horizons = {forecast.horizon for forecast in snapshot.forecasts}
    if horizon not in horizons:
        raise ValueError(f"Horizon {horizon!r} is absent from the governed snapshot")
    integrity = dict(snapshot.audit.get("context_integrity") or {})
    requested_symbol = str(integrity.get("requested_symbol") or "UNKNOWN").strip().upper()
    fixture_symbol = str(integrity.get("fixture_symbol") or "UNKNOWN").strip().upper()
    context_integrity = str(integrity.get("state") or "UNKNOWN").strip().upper()
    fusion_allowed = integrity.get("fusion_allowed") is True
    context_admissible = (
        context_integrity == "MATCHED"
        and fusion_allowed
        and requested_symbol == snapshot.symbol.upper()
        and fixture_symbol == snapshot.symbol.upper()
    )
    material = {
        "requested_symbol": requested_symbol,
        "subject_symbol": snapshot.symbol.upper(),
        "as_of": snapshot.as_of,
        "horizon": horizon,
        "purpose": purpose,
        "question": _question(purpose, horizon),
        "mandate_status": "NOT_PROVIDED",
        "exposure_status": "NOT_PROVIDED",
        "owner_role": "MARKET_INTELLIGENCE_DECISION_OWNER",
        "owner_status": "UNASSIGNED",
        "fixture_symbol": fixture_symbol,
        "context_integrity": context_integrity,
        "context_reason": str(integrity.get("reason") or "Context integrity was not declared"),
        "fusion_allowed": fusion_allowed,
        "context_admissible": context_admissible,
        "constraints": (
            "RESEARCH_ONLY",
            "OBSERVE_ONLY",
            "NO_CAPITAL_AUTHORITY",
            "NO_EXECUTION_PATH",
            "HUMAN_DECISION_REQUIRED",
        ),
    }
    return DecisionContext(
        context_id="MI-SCTX-" + canonical_hash(material)[:20].upper(),
        **material,
    )


def _ids(assessment: GovernanceAssessment, kind: str) -> tuple[str, ...]:
    return tuple(record.evidence_id for record in assessment.ledger.records if record.kind == kind)


def _focus_ids(assessment: GovernanceAssessment, kind: str, horizon: str) -> tuple[str, ...]:
    return tuple(
        record.evidence_id
        for record in assessment.ledger.records
        if record.kind == kind and record.evidence_id.endswith(f":{horizon}")
    )


def _claim(
    claim_id: str,
    kind: ClaimKind,
    statement: str,
    source_view: str,
    evidence_ids: Iterable[str] = (),
) -> StrategicClaim:
    return StrategicClaim(claim_id, kind, statement, source_view, tuple(evidence_ids))


def _assert_assessment_binds_snapshot(
    snapshot: WorkspaceSnapshot,
    assessment: GovernanceAssessment,
) -> None:
    """Reject any attempt to synthesize strategy over a different source snapshot."""

    decision = assessment.decision
    if decision.symbol != snapshot.symbol or decision.as_of != snapshot.as_of:
        raise ValueError("Governance assessment subject/as-of does not match the strategic snapshot")
    records = {record.evidence_id: record for record in assessment.ledger.records}

    def require_exact(kind: str, expected: Iterable[tuple[str, str]]) -> None:
        recorded = sorted(
            (record.evidence_id, record.payload_hash)
            for record in assessment.ledger.records
            if record.kind == kind
        )
        if recorded != sorted(expected):
            raise ValueError(f"Governance {kind} evidence does not exactly bind the strategic snapshot")

    def require(evidence_id: str, payload: object) -> None:
        record = records.get(evidence_id)
        if record is None or record.payload_hash != canonical_hash(payload):
            raise ValueError(f"Governance evidence {evidence_id!r} does not bind the strategic snapshot")

    require(
        f"workspace:{snapshot.symbol}:{snapshot.as_of.isoformat()}",
        {
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
        },
    )
    integrity = dict(snapshot.audit.get("context_integrity") or {})
    requested_symbol = str(integrity.get("requested_symbol") or "").strip().upper()
    fixture_symbol = str(integrity.get("fixture_symbol") or "").strip().upper()
    context_state = str(integrity.get("state", "UNKNOWN")).strip().upper()
    context_id = f"context:{requested_symbol}:{snapshot.symbol}:{snapshot.as_of.isoformat()}"
    context_payload = {
        "requested_symbol": requested_symbol,
        "fixture_symbol": fixture_symbol,
        "state": context_state,
        "fusion_allowed": integrity.get("fusion_allowed") is True,
        "reason": integrity.get("reason", "Context integrity was not declared"),
    }
    require(
        context_id,
        context_payload,
    )
    require(
        f"information-gap:{snapshot.symbol}:{snapshot.as_of.isoformat()}",
        dict(snapshot.audit.get("information_gap") or {}),
    )
    require(
        f"microstructure:{snapshot.microstructure.symbol}:{snapshot.microstructure.as_of.isoformat()}",
        snapshot.microstructure,
    )
    require(
        f"interaction:{snapshot.symbol}:{snapshot.as_of.isoformat()}",
        snapshot.interaction,
    )
    for event in snapshot.events:
        require(f"event:{event.event_id}:{event.revision_id}", event)
    for forecast in snapshot.forecasts:
        require(
            f"forecast:{forecast.model_id}:{forecast.model_version}:{forecast.horizon}",
            forecast,
        )
    require_exact(
        "workspace_snapshot_header",
        ((f"workspace:{snapshot.symbol}:{snapshot.as_of.isoformat()}", canonical_hash({
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
        })),),
    )
    require_exact("context_integrity", ((context_id, canonical_hash(context_payload)),))
    require_exact(
        "information_gap",
        ((
            f"information-gap:{snapshot.symbol}:{snapshot.as_of.isoformat()}",
            canonical_hash(dict(snapshot.audit.get("information_gap") or {})),
        ),),
    )
    require_exact(
        "microstructure_snapshot",
        ((
            f"microstructure:{snapshot.microstructure.symbol}:{snapshot.microstructure.as_of.isoformat()}",
            canonical_hash(snapshot.microstructure),
        ),),
    )
    require_exact(
        "interaction_assessment",
        ((
            f"interaction:{snapshot.symbol}:{snapshot.as_of.isoformat()}",
            canonical_hash(snapshot.interaction),
        ),),
    )
    require_exact(
        "structured_event",
        (
            (f"event:{event.event_id}:{event.revision_id}", canonical_hash(event))
            for event in snapshot.events
        ),
    )
    require_exact(
        "forecast_distribution",
        (
            (
                f"forecast:{forecast.model_id}:{forecast.model_version}:{forecast.horizon}",
                canonical_hash(forecast),
            )
            for forecast in snapshot.forecasts
        ),
    )
    recorded_provider_hashes = sorted(
        record.payload_hash for record in assessment.ledger.records if record.kind == "provider_health"
    )
    expected_provider_hashes = sorted(canonical_hash(provider) for provider in snapshot.provider_health)
    if recorded_provider_hashes != expected_provider_hashes:
        raise ValueError("Governance provider evidence does not bind the strategic snapshot")


def _strategy_state(
    context: DecisionContext,
    assessment: GovernanceAssessment,
    purpose: DecisionPurpose,
) -> tuple[StrategicDisposition, str, str]:
    if not context.context_admissible:
        return (
            StrategicDisposition.BLOCKED_CONTEXT,
            "MI-OPT-RESOLVE-CONTEXT",
            "Resolve instrument identity before interpreting or escalating the canonical fixture.",
        )
    if assessment.decision.state == DecisionState.REJECTED:
        return (
            StrategicDisposition.REMEDIATE_CONTROLS,
            "MI-OPT-REMEDIATE",
            "Remediate hard control failures before any further strategic escalation.",
        )
    if assessment.decision.state == DecisionState.ELIGIBLE_FOR_HUMAN_REVIEW:
        return (
            StrategicDisposition.READY_FOR_HUMAN_REVIEW,
            "MI-OPT-CONVENE-REVIEW",
            "Convene independent human review; no capital or execution authority is implied.",
        )
    if purpose == DecisionPurpose.MARKET_MONITORING:
        return (
            StrategicDisposition.MONITOR,
            "MI-OPT-CONTINUE-OBSERVATION",
            "Continue bounded monitoring while the named evidence gates remain open.",
        )
    return (
        StrategicDisposition.ACQUIRE_EVIDENCE,
        "MI-OPT-ACQUIRE-EVIDENCE",
        "Commission the missing point-in-time, calibration and shadow evidence before portfolio review.",
    )


def _options(
    disposition: StrategicDisposition,
    recommended_id: str,
    blockers: tuple[str, ...],
) -> tuple[StrategicOption, ...]:
    first_blocker = blockers[0] if blockers else "No blocking research gate"

    def status(option_id: str, *, eligible: bool = True) -> OptionStatus:
        if option_id == recommended_id:
            return OptionStatus.RECOMMENDED
        return OptionStatus.AVAILABLE if eligible else OptionStatus.BLOCKED

    context_blocked = disposition == StrategicDisposition.BLOCKED_CONTEXT
    control_blocked = disposition == StrategicDisposition.REMEDIATE_CONTROLS
    review_ready = disposition == StrategicDisposition.READY_FOR_HUMAN_REVIEW
    return (
        StrategicOption(
            "MI-OPT-RESOLVE-CONTEXT",
            "Resolve instrument context",
            OptionClass.PROCESS,
            status("MI-OPT-RESOLVE-CONTEXT", eligible=context_blocked),
            "Rebuild the dossier only after the requested and governed instrument identities match.",
            "Prevents cross-instrument evidence leakage.",
            "Delays analysis until a valid source contract exists.",
            "HIGH",
            "DIRECT" if context_blocked else "NOT_APPLICABLE",
            first_blocker if context_blocked else "Context already matched",
            "Requested symbol equals the governed subject symbol.",
            "Any later identity mismatch or mixed-instrument lineage.",
            "research",
        ),
        StrategicOption(
            "MI-OPT-REMEDIATE",
            "Remediate failed controls",
            OptionClass.PROCESS,
            status("MI-OPT-REMEDIATE", eligible=disposition == StrategicDisposition.REMEDIATE_CONTROLS),
            "Repair hard integrity or validation failures before resuming research progression.",
            "Restores a trustworthy research basis.",
            "Consumes control-owner capacity without advancing the thesis.",
            "HIGH",
            "DIRECT" if disposition == StrategicDisposition.REMEDIATE_CONTROLS else "CONDITIONAL",
            first_blocker,
            "At least one hard gate is REJECTED.",
            "Evidence root, PIT chain, or context integrity remains invalid.",
            "research",
        ),
        StrategicOption(
            "MI-OPT-ACQUIRE-EVIDENCE",
            "Escalate targeted evidence acquisition",
            OptionClass.PROCESS,
            status("MI-OPT-ACQUIRE-EVIDENCE", eligible=not context_blocked and not control_blocked),
            "Prioritize licensed PIT events, entitled L2, realized outcomes and independent validation.",
            "Converts named unknowns into testable institutional evidence.",
            "Research cost and latency may not improve the thesis.",
            "HIGH",
            "BOUND" if blockers else "DIRECT",
            first_blocker,
            "One or more progression gates are WAITING_EVIDENCE.",
            "Evidence cannot be sourced with admissible lineage or chronology.",
            "research",
        ),
        StrategicOption(
            "MI-OPT-CONTINUE-OBSERVATION",
            "Continue bounded observation",
            OptionClass.PROCESS,
            status("MI-OPT-CONTINUE-OBSERVATION", eligible=not context_blocked and not control_blocked),
            "Preserve optionality while monitoring explicit catalyst, microstructure and residual triggers.",
            "Avoids premature escalation while institutional evidence remains incomplete.",
            "May miss a time-sensitive opportunity while evidence remains incomplete.",
            "HIGH",
            "LIMITED",
            first_blocker,
            "No hard integrity failure and monitoring inputs remain interpretable.",
            "Interaction inputs become INVALID or the evidence chain fails.",
            "live",
        ),
        StrategicOption(
            "MI-OPT-CONVENE-REVIEW",
            "Convene independent human evidence review",
            OptionClass.PROCESS,
            status("MI-OPT-CONVENE-REVIEW", eligible=review_ready),
            "Present the bounded dossier to an independent human reviewer.",
            "Creates accountable challenge without selecting a capital posture.",
            "Portfolio impact remains unpriced without mandate and exposure context.",
            "MEDIUM" if review_ready else "INSUFFICIENT",
            "RESEARCH_ELIGIBILITY",
            first_blocker if not review_ready else "Human decision not recorded",
            "All blocking research gates pass.",
            "Evidence, mandate or exposure context changes materially.",
            "research",
        ),
        StrategicOption(
            "MI-OPT-ADVANCE-PORTFOLIO-REVIEW",
            "Advance a portfolio-posture proposal",
            OptionClass.PORTFOLIO_REVIEW,
            OptionStatus.BLOCKED,
            "Frame a capital posture only after research eligibility, mandate and exposure context are complete.",
            "Would connect validated research to a separately authorized portfolio process.",
            "Premature framing could imply false precision or authority.",
            "INSUFFICIENT",
            "MANDATE_EXPOSURE_AND_CAPITAL_AUTHORITY",
            "Mandate, holdings, limits and exposure sensitivities are not registered.",
            "Research eligibility plus complete mandate, exposure and decision-owner context.",
            "Any evidence-root, mandate, exposure or limit change.",
            "research",
        ),
        StrategicOption(
            "MI-OPT-AUTHORIZE-EXECUTION",
            "Authorize execution",
            OptionClass.EXECUTION,
            OptionStatus.PROHIBITED,
            "Execution is outside the Market Intelligence research mandate.",
            "NONE — prohibited by contract.",
            "Would bypass human authority, portfolio controls and OMS safeguards.",
            "NONE",
            "RESEARCH_ONLY_BOUNDARY",
            "Execution is unconditionally disabled.",
            "No trigger exists inside this workspace.",
            "Any attempt to create an order payload invalidates the memo.",
            "research",
        ),
    )


def build_strategic_decision_memo(
    snapshot: WorkspaceSnapshot,
    assessment: GovernanceAssessment,
    *,
    horizon: str,
    purpose: DecisionPurpose = DecisionPurpose.RESEARCH_PRIORITIZATION,
) -> StrategicDecisionMemo:
    if assessment.decision.packet_id == "" or assessment.decision.evidence_root != assessment.ledger.root_hash:
        raise ValueError("Strategic synthesis requires an intact governance assessment")
    _assert_assessment_binds_snapshot(snapshot, assessment)
    context = build_decision_context(snapshot, horizon=horizon, purpose=purpose)
    context_gates = tuple(
        gate for gate in assessment.decision.validation.gates if gate.gate_id == "CONTEXT_INTEGRITY"
    )
    if len(context_gates) != 1:
        raise ValueError("Governance assessment must contain exactly one CONTEXT_INTEGRITY gate")
    gate_admissible = context_gates[0].status == GateStatus.PASS and not context_gates[0].blocks_progression
    if gate_admissible != context.context_admissible:
        raise ValueError("Strategic context admissibility does not match the governance gate")
    disposition, recommended_id, process_summary = _strategy_state(context, assessment, purpose)
    interaction_ids = _ids(assessment, "interaction_assessment")
    micro_ids = _ids(assessment, "microstructure_snapshot")
    event_ids = _ids(assessment, "structured_event")
    forecast_ids = _focus_ids(assessment, "forecast_distribution", horizon)
    scenario_ids = _focus_ids(assessment, "scenario_assessment", horizon)
    quality_ids = _ids(assessment, "data_quality_assessment")
    context_ids = _ids(assessment, "context_integrity")
    information_gap_ids = _ids(assessment, "information_gap")
    known_ids = {record.evidence_id for record in assessment.ledger.records}
    focus_forecasts = tuple(item for item in snapshot.forecasts if item.horizon == horizon)
    calibration_gate = next(
        (gate for gate in assessment.decision.validation.gates if gate.gate_id == "CALIBRATION"),
        None,
    )
    calibration_pass = calibration_gate is not None and calibration_gate.status == GateStatus.PASS
    failed_gates = tuple(
        gate for gate in assessment.decision.validation.gates if gate.status == GateStatus.FAIL
    )
    control_blocked = context.context_admissible and bool(failed_gates)
    control_evidence_ids = tuple(
        dict.fromkeys(
            evidence_id
            for gate in failed_gates
            for evidence_id in gate.evidence_ids
        )
    ) or _ids(assessment, "workspace_snapshot_header")

    if not context.context_admissible:
        claims = (
            _claim(
                "MI-SCLM-CONTEXT",
                ClaimKind.COUNTEREVIDENCE,
                (
                    f"Context is inadmissible: requested {context.requested_symbol}, fixture "
                    f"{context.fixture_symbol}, governed subject {context.subject_symbol}, state "
                    f"{context.context_integrity}, fusion {'YES' if context.fusion_allowed else 'NO'}. "
                    f"{context.context_reason}"
                ),
                "research",
                context_ids or _ids(assessment, "workspace_snapshot_header"),
            ),
            _claim(
                "MI-SCLM-NO-CROSS-SYMBOL",
                ClaimKind.UNKNOWN,
                "No strategic market inference is admissible for the requested instrument.",
                "research",
            ),
        )
    elif control_blocked:
        claims = (
            _claim(
                "MI-SCLM-CONTROL-FAILURE",
                ClaimKind.COUNTEREVIDENCE,
                "Hard governance control failure(s) block strategic market inference: "
                + ", ".join(gate.gate_id for gate in failed_gates)
                + ".",
                "research",
                control_evidence_ids,
            ),
            _claim(
                "MI-SCLM-NO-INFERENCE",
                ClaimKind.UNKNOWN,
                "No market, scenario, liquidity or portfolio conclusion is admissible until failed controls are remediated.",
                "research",
            ),
        )
    else:
        micro = snapshot.microstructure
        if micro.bid_replenishment is None or micro.price_impact_proxy is None:
            micro_claim = _claim(
                "MI-SCLM-MICRO",
                ClaimKind.UNKNOWN,
                "Bid replenishment or price-impact evidence is unavailable; no absorption inference is admissible.",
                "microstructure",
            )
        else:
            if micro.trade_imbalance is None:
                flow = "unclassified trade flow"
            elif micro.trade_imbalance < 0:
                flow = f"negative trade imbalance {micro.trade_imbalance:+.2f}"
            else:
                flow = f"non-negative trade imbalance {micro.trade_imbalance:+.2f}"
            micro_claim = _claim(
                "MI-SCLM-MICRO",
                ClaimKind.OBSERVED,
                (
                    f"The {micro.provider_status.value.upper()} {micro.schema_level} snapshot reports bid "
                    f"replenishment {micro.bid_replenishment:.2f}, price impact {micro.price_impact_proxy:.2f} "
                    f"and {flow}."
                ),
                "microstructure",
                micro_ids,
            )
        calibration_labels = ", ".join(
            sorted({forecast.calibration_status for forecast in focus_forecasts})
        )
        forecast_claim = _claim(
            "MI-SCLM-FORECAST",
            ClaimKind.OBSERVED if calibration_pass else ClaimKind.COUNTEREVIDENCE,
            (
                f"The {horizon} distribution calibration contract is {calibration_labels}."
                if calibration_pass
                else f"The {horizon} distribution remains an uncalibrated level-0 benchmark."
            ),
            "forecast",
            forecast_ids,
        )
        claims = (
            _claim(
                "MI-SCLM-INTERACTION",
                ClaimKind.DERIVED,
                f"Current descriptive interaction state is {snapshot.interaction.state.replace('_', ' ')}.",
                "live",
                interaction_ids,
            ),
            _claim(
                "MI-SCLM-COLLISION",
                ClaimKind.COUNTEREVIDENCE,
                f"Catalyst collision is {snapshot.interaction.collision_score:.0%}, weakening one-sided interpretation.",
                "collision",
                (*event_ids, *interaction_ids),
            ),
            micro_claim,
            forecast_claim,
            _claim(
                "MI-SCLM-PORTFOLIO-UNKNOWN",
                ClaimKind.UNKNOWN,
                "Mandate, exposure, constraints and portfolio sensitivities were not provided.",
                "research",
            ),
        )

    for claim in claims:
        if not set(claim.evidence_ids).issubset(known_ids):
            raise ValueError(f"Claim {claim.claim_id} references unknown evidence")

    blockers = tuple(assessment.decision.blockers)
    options = _options(disposition, recommended_id, blockers)
    micro = snapshot.microstructure
    gap = dict(snapshot.audit.get("information_gap") or {})
    if not context.context_admissible:
        impacts = (
            ImpactAssessment(
                "CONTEXT INTEGRITY",
                ImpactState.UNPRICED,
                "BLOCKED — the instrument context is not admissible for strategic inference.",
                "Requested, fixture and subject identity plus fusion permission must all pass.",
                context_ids,
            ),
            ImpactAssessment(
                "PORTFOLIO",
                ImpactState.UNPRICED,
                "UNPRICED — no admissible subject-specific decision basis exists.",
                "No zero, neutral or directional impact may be inferred.",
            ),
        )
        monitoring = (
            MonitoringRule(
                "MI-MON-CONTEXT",
                "Requested / governed instrument identity",
                f"{context.requested_symbol} / {context.subject_symbol} · {context.context_integrity} · admissible NO",
                "Rebuild only when a subject-specific governed snapshot is registered.",
                "Any mixed-symbol evidence or relabelled fixture invalidates the dossier.",
                "DATA_GOVERNANCE_OWNER",
                "research",
                context_ids,
            ),
        )
    elif control_blocked:
        impacts = (
            ImpactAssessment(
                "CONTROL INTEGRITY",
                ImpactState.UNPRICED,
                "BLOCKED — one or more hard governance controls failed.",
                "Remediate and rebuild the complete governed packet before interpreting the market evidence.",
                control_evidence_ids,
            ),
            ImpactAssessment(
                "PORTFOLIO",
                ImpactState.UNPRICED,
                "UNPRICED — the failed control basis cannot support a capital posture.",
                "No neutral, zero or directional impact may be inferred.",
            ),
        )
        monitoring = (
            MonitoringRule(
                "MI-MON-CONTROLS",
                "Failed governance controls",
                ", ".join(gate.gate_id for gate in failed_gates),
                "Rebuild only after every hard-fail gate is remediated and independently re-evaluated.",
                "Any persistent or new FAIL state invalidates strategic synthesis.",
                "INDEPENDENT_VALIDATION_OWNER",
                "research",
                control_evidence_ids,
            ),
        )
    else:
        residual_raw = gap.get("unexplained_residual")
        try:
            residual_value = float(residual_raw)
        except (TypeError, ValueError):
            residual_value = None
        if residual_value is not None and not math.isfinite(residual_value):
            residual_value = None
        impacts = (
            ImpactAssessment(
                "RESEARCH PRIORITY",
                ImpactState.ASSESSED,
                "HIGH — current blockers map directly to a bounded evidence programme.",
                "Priority is process-oriented, not a claim of market edge.",
                quality_ids or interaction_ids,
            ),
            ImpactAssessment(
                "TAIL / SCENARIO",
                ImpactState.WAITING_EVIDENCE,
                "Scenario transforms are available for review but remain assumption-only.",
                "No empirical sensitivity or scenario probability is registered.",
                scenario_ids,
            ),
            ImpactAssessment(
                "LIQUIDITY / IMPLEMENTATION",
                ImpactState.WAITING_EVIDENCE,
                "Fixture L2 supports mechanism inspection only.",
                "No venue entitlement, packet-gap audit or executable liquidity estimate.",
                micro_ids,
            ),
            ImpactAssessment(
                "PORTFOLIO",
                ImpactState.UNPRICED,
                "UNPRICED — no mandate, holdings, limits or exposure sensitivities were supplied.",
                "A zero or neutral portfolio impact must not be inferred from missing context.",
            ),
            ImpactAssessment(
                "MODEL RISK",
                ImpactState.WAITING_EVIDENCE,
                (
                    "Focus forecasts satisfy the declared calibration gate; chronological OOS and shadow evidence remain open."
                    if calibration_pass
                    else "Focus forecasts are uncalibrated and lack chronological OOS and shadow outcomes."
                ),
                "Calibration alone does not establish promotion, stability or live predictive validity.",
                forecast_ids,
            ),
        )
        monitoring = (
            MonitoringRule(
                "MI-MON-COLLISION",
                "Catalyst collision",
                f"{snapshot.interaction.collision_score:.0%}",
                "Escalate challenge if opposing catalyst mass remains elevated.",
                "Invalidate any one-sided thesis while collision remains high.",
                "CATALYST_RESEARCH_OWNER",
                "collision",
                (*event_ids, *interaction_ids),
            ),
            MonitoringRule(
                "MI-MON-ABSORPTION",
                "Bid replenishment / price impact",
                (
                    f"Replenishment {micro.bid_replenishment:.2f}; impact {micro.price_impact_proxy:.2f}"
                    if micro.bid_replenishment is not None and micro.price_impact_proxy is not None
                    else "UNAVAILABLE — absorption metrics incomplete"
                ),
                "Investigate if replenishment weakens while sell impact rises.",
                "Invalidate absorption when replenishment fails under continued negative flow.",
                "MICROSTRUCTURE_RESEARCH_OWNER",
                "microstructure",
                micro_ids,
            ),
            MonitoringRule(
                "MI-MON-RESIDUAL",
                "Unexplained residual",
                f"{residual_value:.0%}" if residual_value is not None else "UNAVAILABLE — residual not registered",
                "Escalate residual investigation at 70%.",
                "Invalidate the known-catalyst explanation above the controlled threshold.",
                "INFORMATION_RISK_OWNER",
                "information-gap",
                information_gap_ids,
            ),
            MonitoringRule(
                "MI-MON-VALIDATION",
                "Research gate progression",
                assessment.decision.state.value,
                "Rebuild the memo when any blocking gate changes state.",
                "Invalidate this memo if evidence root or policy version changes.",
                "INDEPENDENT_VALIDATION_OWNER",
                "research",
                quality_ids,
            ),
        )
    for rule in monitoring:
        if not set(rule.evidence_ids).issubset(known_ids):
            raise ValueError(f"Monitoring rule {rule.rule_id} references unknown evidence")

    portfolio_summary = (
        "No portfolio action is preferred: impact is UNPRICED until mandate, exposure and authority context exists."
    )
    next_evidence = (
        (
            f"A governed {context.requested_symbol} snapshot with matching subject identity",
            "Subject-specific provider lineage and context-integrity evidence",
        )
        if not context.context_admissible
        else (
            tuple(
                f"Remediate {gate.gate_id}: {gate.reason}"
                for gate in failed_gates
            )
            if control_blocked
            else tuple(
                item
                for item in (
                    "Licensed point-in-time event and revision lineage",
                    "Venue-authorized sequenced L2 with integrity controls",
                    None if calibration_pass else "Realized forecast outcomes and calibration ledger",
                    "Purged chronological OOS validation",
                    "Append-only shadow decision history",
                    "Mandate, exposure and limit context for any portfolio review",
                )
                if item is not None
            )
        )
    )
    review_at = snapshot.as_of + _horizon_delta(horizon)
    expires_at = review_at + _horizon_delta(horizon)
    material = {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "policy_version": POLICY_VERSION,
        "context": context,
        "basis_packet_id": assessment.decision.packet_id,
        "basis_validation_run_id": assessment.decision.validation.run_id,
        "basis_evidence_root": assessment.decision.evidence_root,
        "research_state": assessment.decision.state.value,
        "disposition": disposition,
        "recommended_process_option_id": recommended_id,
        "preferred_portfolio_option_id": None,
        "process_summary": process_summary,
        "portfolio_summary": portfolio_summary,
        "decision_strength": "PROVISIONAL",
        "options": options,
        "claims": claims,
        "impacts": impacts,
        "monitoring_rules": monitoring,
        "blockers": blockers,
        "next_evidence": next_evidence,
        "review_at": review_at,
        "expires_at": expires_at,
        "authority": "ADVISORY_ONLY",
        "human_review_required": True,
        "execution_allowed": False,
        "order_payload": None,
    }
    content_hash = canonical_hash(material)
    memo = StrategicDecisionMemo(
        memo_id="MI-SDM-" + content_hash[:20].upper(),
        content_hash=content_hash,
        **material,
    )
    if memo.context.subject_symbol != snapshot.symbol.upper():
        raise ValueError("Strategic context subject must match the workspace snapshot")
    return memo
