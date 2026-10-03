from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ResearchBudget:
    max_literature_queries: int = 3
    max_hypotheses: int = 6
    max_tasks: int = 12
    max_experiment_proposals: int = 2
    max_cycles: int = 1
    max_compute_units: float = 100.0


@dataclass(frozen=True)
class OpenResearchQuestion:
    question_id: str
    created_at: str
    title: str
    question: str
    origin_type: str
    origin_refs: tuple[str, ...] = ()
    experiment_id: str = ""
    target_variable: str = ""
    status: str = "OPEN"
    priority_score: float = 0.0
    uncertainty_score: float = 0.0
    information_gain_score: float = 0.0
    novelty_score: float = 0.0
    impact_score: float = 0.0
    feasibility_score: float = 0.0
    cost_score: float = 0.0
    rationale: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    literature_queries: tuple[str, ...] = ()
    hypothesis_ids: tuple[str, ...] = ()
    plan_id: str = ""
    selected_observable_id: str = ""
    grounded_evidence_refs: tuple[str, ...] = ()
    lifecycle_history: tuple[dict[str, Any], ...] = ()
    production_status: str = "RESEARCH_ONLY"


@dataclass(frozen=True)
class ResearchHypothesis:
    hypothesis_id: str
    created_at: str
    question_id: str
    label: str
    description: str
    mechanism_family: str
    predictions: tuple[str, ...] = ()
    falsification_conditions: tuple[str, ...] = ()
    required_evidence: tuple[str, ...] = ()
    literature_queries: tuple[str, ...] = ()
    status: str = "CANDIDATE"
    priority_score: float = 0.0
    source_type: str = "DETERMINISTIC_DIRECTOR"
    parent_hypothesis_id: str = ""
    generation: int = 0
    production_status: str = "RESEARCH_ONLY"


@dataclass(frozen=True)
class ResearchTask:
    task_id: str
    created_at: str
    plan_id: str
    question_id: str
    task_type: str
    description: str
    status: str
    expected_information_gain: float
    estimated_cost: float
    query: str = ""
    prerequisites: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    required_tools: tuple[str, ...] = ()
    result_refs: tuple[str, ...] = ()
    production_status: str = "RESEARCH_ONLY"


@dataclass(frozen=True)
class ResearchPlan:
    plan_id: str
    created_at: str
    question_id: str
    selected_hypothesis_id: str
    hypothesis_ids: tuple[str, ...]
    tasks: tuple[ResearchTask, ...]
    budget: ResearchBudget
    stop_rules: tuple[str, ...]
    status: str
    next_action: str
    rationale: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    production_status: str = "RESEARCH_ONLY"


@dataclass(frozen=True)
class ResearchDiaryEntry:
    diary_id: str
    created_at: str
    question_id: str
    cycle_id: str
    entry_type: str
    observation: str
    interpretation: str
    action: str
    rationale: str
    evidence_refs: tuple[str, ...] = ()
    production_status: str = "RESEARCH_ONLY"


@dataclass(frozen=True)
class DirectorCycle:
    cycle_id: str
    created_at: str
    selected_question_id: str
    created_question_ids: tuple[str, ...]
    generated_hypothesis_ids: tuple[str, ...]
    plan_id: str
    status: str
    next_action: str
    budget: ResearchBudget
    decisions: tuple[str, ...] = ()
    external_actions_executed: bool = False
    experiment_execution_allowed: bool = False
    production_status: str = "RESEARCH_ONLY"


@dataclass(frozen=True)
class LiteratureScoutRecord:
    scout_id: str
    created_at: str
    question_id: str
    task_id: str
    query: str
    source: str
    status: str
    result_count: int
    results: tuple[dict[str, Any], ...] = ()
    error: str = ""
    budget_units_used: float = 0.0
    production_status: str = "RESEARCH_ONLY"
