from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AuditorFinding:
    auditor: str
    status: str
    score: float
    rationale: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    requirements: tuple[str, ...] = ()


@dataclass(frozen=True)
class MultipleTestingAssessment:
    assessment_id: str
    created_at: str
    experiment_id: str
    run_id: str
    observed_tests: int
    robustness_variants: int
    baseline_comparisons: int
    related_runs: int
    selection_risk: str
    pvalue_control_status: str = "NOT_APPLICABLE_NO_PVALUES_STORED"
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ValidationReview:
    review_id: str
    created_at: str
    experiment_id: str
    run_id: str
    stage: str
    run_verdict: str
    transfer_verdict: str
    council_decision: str
    scientific_grade: str
    evidence_tier: str
    auditor_findings: tuple[AuditorFinding, ...] = ()
    multiple_testing: MultipleTestingAssessment | None = None
    evidence_summary: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    requirements: tuple[str, ...] = ()
    review_protocol_version: str = "SRB_COUNCIL_REVIEW_V2"
    review_mode: str = "COMPUTATIONAL_COUNCIL_DOSSIER"
    review_authority: str = "SYSTEM_GENERATED_RESEARCH_REVIEW"
    human_attestation_status: str = "NOT_A_HUMAN_PANEL"
    decision_scope: str = "RESEARCH_WORKFLOW_ONLY"
    disposition: str = ""
    measurement_report_id: str = ""
    measurement_protocol_id: str = ""
    evidence_refs: tuple[str, ...] = ()
    automatic_promotion_authorized: bool = False
    gate_eligibility: str = "PENDING_EVIDENCE"
    production_status: str = "RESEARCH_ONLY"


@dataclass(frozen=True)
class FailureRecord:
    failure_id: str
    created_at: str
    experiment_id: str
    run_id: str
    failure_type: str
    severity: str
    status: str
    signal: str
    evidence: dict[str, Any] = field(default_factory=dict)
    remediation: tuple[str, ...] = ()
    status_updated_at: str = ""
    status_reason: str = ""
    status_evidence_refs: tuple[str, ...] = ()
    lifecycle_history: tuple[dict[str, Any], ...] = ()
    production_status: str = "RESEARCH_ONLY"


@dataclass(frozen=True)
class SurpriseRecord:
    surprise_id: str
    created_at: str
    experiment_id: str
    run_id: str
    surprise_type: str
    status: str
    expected: str
    observed: str
    deviation_score: float
    implication: str
    evidence: dict[str, Any] = field(default_factory=dict)
    status_updated_at: str = ""
    status_reason: str = ""
    status_evidence_refs: tuple[str, ...] = ()
    lifecycle_history: tuple[dict[str, Any], ...] = ()
    production_status: str = "RESEARCH_ONLY"


@dataclass(frozen=True)
class EvidenceEvent:
    event_id: str
    created_at: str
    experiment_id: str
    run_id: str
    event_type: str
    direction: str
    strength: float
    rationale: str


@dataclass(frozen=True)
class TheoryState:
    theory_id: str
    label: str
    description: str
    weight: float
    support_score: float
    challenge_score: float
    evidence_event_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class TheoryPopulation:
    population_id: str
    created_at: str
    experiment_id: str
    target_variable: str
    theories: tuple[TheoryState, ...]
    evidence_events: tuple[EvidenceEvent, ...] = ()
    interpretation: str = (
        "Relative epistemic weights are deterministic research bookkeeping scores, not calibrated probabilities."
    )
    production_status: str = "RESEARCH_ONLY"
