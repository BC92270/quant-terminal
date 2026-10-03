from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ObservableCandidate:
    observable_id: str
    created_at: str
    question_id: str
    experiment_id: str
    target_concept: str
    label: str
    economic_interpretation: str
    mathematical_definition: str
    unit: str
    frequency: str
    required_columns: tuple[str, ...]
    transformation_steps: tuple[str, ...]
    rationale: tuple[str, ...]
    limitations: tuple[str, ...]
    observability_score: float
    economic_interpretability_score: float
    leakage_risk_score: float
    data_feasibility_score: float
    total_score: float
    status: str = "PROPOSED"
    source_type: str = "DETERMINISTIC_OBSERVABLE_LIBRARY"
    evidence_refs: tuple[str, ...] = ()
    production_status: str = "RESEARCH_ONLY"


@dataclass(frozen=True)
class EvidencePromotion:
    promotion_id: str
    created_at: str
    scout_id: str
    task_id: str
    question_id: str
    paper_id: str
    title: str
    doi: str
    access_level: str
    status: str
    review_reason: str
    understanding_id: str = ""
    evidence_id: str = ""
    source_text_origin: str = "SCOUT_RESULT"
    warnings: tuple[str, ...] = ()
    production_status: str = "RESEARCH_ONLY"


@dataclass(frozen=True)
class GroundedEvidenceRecord:
    evidence_id: str
    created_at: str
    question_id: str
    scout_id: str
    task_id: str
    promotion_id: str
    paper_id: str
    understanding_id: str
    title: str
    doi: str
    source_level: str
    claim_ids: tuple[str, ...]
    mechanism_keys: tuple[str, ...]
    semantic_entity_ids: tuple[str, ...]
    relation_to_question: str = "RELEVANT_UNASSESSED"
    status: str = "GROUNDED_REVIEWED"
    notes: tuple[str, ...] = ()
    production_status: str = "RESEARCH_ONLY"


@dataclass(frozen=True)
class BudgetLedger:
    ledger_id: str
    created_at: str
    plan_id: str
    question_id: str
    max_literature_queries: int
    used_literature_queries: int
    max_hypotheses: int
    used_hypotheses: int
    max_tasks: int
    used_tasks: int
    max_experiment_proposals: int
    used_experiment_proposals: int
    max_cycles: int
    used_cycles: int
    max_compute_units: float
    used_compute_units: float
    reconciled_from_persisted_state: bool = False
    production_status: str = "RESEARCH_ONLY"


@dataclass(frozen=True)
class BudgetEvent:
    event_id: str
    created_at: str
    ledger_id: str
    plan_id: str
    category: str
    amount: float
    reason: str
    ref_id: str
    actor: str = "SYSTEM"
    metadata: dict[str, Any] | None = None
