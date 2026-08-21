from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .config import OrganizationConfig
from .schemas import AgentReport, CommitteeRun, NodeStatus


@dataclass(slots=True)
class QualityDimension:
    name: str
    score: int
    weight: float
    detail: str


@dataclass(slots=True)
class CommitteeQuality:
    score: int
    grade: str
    dimensions: list[QualityDimension]
    strengths: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _bounded(value: float) -> int:
    return int(round(max(0.0, min(100.0, value))))


def score_agent_report(report: AgentReport) -> int:
    score = 10.0
    score += min(20.0, len(report.evidence_used) * 5.0)
    score += min(15.0, len(report.rationale) * 3.0)
    score += min(12.0, len(report.risks) * 3.0)
    score += min(12.0, len(report.invalidation) * 4.0)
    score += min(10.0, len(report.scenarios) * 3.5)
    score += min(8.0, len(report.assumptions) * 2.5)
    score += min(8.0, len(report.monitoring) * 2.0)
    score += 5.0 if report.dissent else 0.0
    if not report.evidence_used and report.confidence > 0.5:
        score -= 25.0
    if report.stance == "ABSTAIN" and not report.risks:
        score -= 10.0
    return _bounded(score)


def evaluate_committee(run: CommitteeRun, organization: OrganizationConfig) -> CommitteeQuality:
    tool_count = max(1, len(run.tools))
    evidence_units = sum(
        1.0 if result.status == NodeStatus.COMPLETE else 0.55 if result.status == NodeStatus.PARTIAL else 0.0
        for result in run.tools.values()
    )
    evidence_score = _bounded(100.0 * evidence_units / tool_count)

    expected_desks = len([agent for agent in organization.agents if agent.enabled])
    independence_score = _bounded(100.0 * len(run.reports) / max(1, expected_desks))
    if len({report.agent_id for report in run.reports}) != len(run.reports):
        independence_score = max(0, independence_score - 25)

    report_scores = [score_agent_report(report) for report in run.reports]
    report_contract_score = _bounded(sum(report_scores) / max(1, len(report_scores)))

    consultations = [event for event in run.interactions if event.kind in {"consult", "challenge", "support"}]
    challenges = [event for event in run.interactions if event.kind == "challenge"]
    challenge_score = _bounded(35 + min(40, len(consultations) * 2.5) + min(25, len(challenges) * 4.0))
    if not consultations:
        challenge_score = 20

    risk_events = [event for event in run.interactions if event.kind in {"veto", "sign_off"}]
    risk_score = 100 if risk_events else 35 if not organization.require_risk_signoff else 0

    explicit_fields = [
        bool(run.brief.thesis),
        bool(run.brief.risks),
        bool(run.brief.invalidation),
        bool(run.brief.implementation),
        bool(run.brief.sizing),
        bool(run.brief.time_horizon),
        run.brief.approval_required,
    ]
    decision_score = _bounded(100.0 * sum(explicit_fields) / len(explicit_fields))
    if run.brief.confidence > 0.75 and evidence_score < 60:
        decision_score = max(0, decision_score - 25)

    dimensions = [
        QualityDimension("Evidence coverage", evidence_score, 0.24, f"{evidence_units:.1f}/{tool_count} weighted evidence engines available."),
        QualityDimension("Desk independence", independence_score, 0.14, f"{len(run.reports)}/{expected_desks} enabled desks returned a frozen first-pass report."),
        QualityDimension("Report contract", report_contract_score, 0.18, "Evidence, assumptions, scenarios, risks, invalidation and monitoring completeness."),
        QualityDimension("Adversarial review", challenge_score, 0.16, f"{len(consultations)} peer interactions including {len(challenges)} explicit challenges."),
        QualityDimension("Risk governance", risk_score, 0.14, "Chief Risk veto or sign-off is recorded in the interaction ledger."),
        QualityDimension("Decision contract", decision_score, 0.14, "Implementation, sizing, horizon, invalidation and human approval are explicit."),
    ]
    total = _bounded(sum(item.score * item.weight for item in dimensions))
    grade = "INSTITUTIONAL" if total >= 85 else "ROBUST" if total >= 72 else "RESEARCH" if total >= 55 else "INSUFFICIENT"

    strengths: list[str] = []
    blockers: list[str] = []
    next_actions: list[str] = []
    for item in dimensions:
        if item.score >= 82:
            strengths.append(f"{item.name}: {item.score}/100.")
        elif item.score < 60:
            blockers.append(f"{item.name}: {item.score}/100 — {item.detail}")
    missing = [name for name, result in run.tools.items() if result.status in {NodeStatus.NOT_AVAILABLE, NodeStatus.ERROR}]
    if missing:
        blockers.append("Unavailable decision inputs: " + ", ".join(missing[:8]) + ".")
        next_actions.append("Connect or refresh the missing evidence engines before increasing confidence or capital.")
    if any(event.kind == "veto" for event in risk_events):
        next_actions.append("Resolve the Chief Risk veto explicitly; do not route around it through sizing language.")
    if report_contract_score < 75:
        next_actions.append("Require incomplete desks to supply falsification tests, scenarios and monitoring variables.")
    if evidence_score >= 80 and not blockers:
        next_actions.append("Archive the decision packet and schedule the next evidence-triggered review.")
    return CommitteeQuality(total, grade, dimensions, strengths[:6], blockers[:8], next_actions[:6])
