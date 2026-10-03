from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MeasurementHypothesis:
    measurement_hypothesis_id: str
    created_at: str
    measurement_model_id: str
    question_id: str
    target_concept: str
    observable_id: str
    label: str
    mathematical_definition: str
    unit: str
    frequency: str
    measurement_error_risks: tuple[str, ...]
    sensitivity_dimensions: tuple[str, ...]
    invariance_tests: tuple[str, ...]
    evidence_refs: tuple[str, ...] = ()
    status: str = "COMPETING"
    production_status: str = "RESEARCH_ONLY"


@dataclass(frozen=True)
class MeasurementModel:
    measurement_model_id: str
    created_at: str
    question_id: str
    experiment_id: str
    target_concept: str
    observable_ids: tuple[str, ...]
    measurement_hypothesis_ids: tuple[str, ...]
    primary_observable_id: str = ""
    status: str = "MEASUREMENT_UNCERTAINTY_OPEN"
    comparison_principles: tuple[str, ...] = ()
    required_tests: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    production_status: str = "RESEARCH_ONLY"


@dataclass(frozen=True)
class MeasurementDecision:
    decision_id: str
    created_at: str
    measurement_model_id: str
    question_id: str
    selected_observable_id: str
    rationale: str
    evidence_refs: tuple[str, ...]
    actor: str = "HUMAN"
    status: str = "PRIMARY_SELECTED_UNVALIDATED"
    production_status: str = "RESEARCH_ONLY"


@dataclass(frozen=True)
class EvidenceAssessment:
    assessment_id: str
    created_at: str
    question_id: str
    evidence_id: str
    hypothesis_id: str
    relation: str
    strength: float
    rationale: str
    claim_refs: tuple[str, ...]
    assessor: str = "HUMAN"
    status: str = "ASSESSED"
    production_status: str = "RESEARCH_ONLY"


@dataclass(frozen=True)
class EvidenceSynthesis:
    synthesis_id: str
    created_at: str
    question_id: str
    assessment_ids: tuple[str, ...]
    hypothesis_summaries: tuple[dict[str, Any], ...]
    assessed_evidence_count: int
    support_count: int
    challenge_count: int
    context_count: int
    neutral_count: int
    conflict_count: int
    conclusion: str
    required_next_evidence: tuple[str, ...]
    belief_update_authorized: bool = False
    status: str = "SYNTHESIZED_NOT_BELIEF_APPLIED"
    production_status: str = "RESEARCH_ONLY"
