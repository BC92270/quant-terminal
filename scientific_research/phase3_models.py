from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StructuralComparison:
    comparison_id: str
    created_at: str
    source_label: str
    target_label: str
    source_domain: str
    target_domain: str
    source_mechanisms: dict[str, float] = field(default_factory=dict)
    target_mechanisms: dict[str, float] = field(default_factory=dict)
    source_families: dict[str, float] = field(default_factory=dict)
    target_families: dict[str, float] = field(default_factory=dict)
    common_mechanisms: tuple[str, ...] = ()
    common_families: tuple[str, ...] = ()
    source_only: tuple[str, ...] = ()
    target_only: tuple[str, ...] = ()
    mechanism_similarity: float = 0.0
    family_similarity: float = 0.0
    structural_score: float = 0.0
    verdict: str = "NO_STRUCTURAL_EVIDENCE"
    warning: str = ""


@dataclass(frozen=True)
class CollisionCandidate:
    collision_id: str
    created_at: str
    source_label: str
    target_label: str
    source_domain: str
    target_domain: str
    structural_score: float
    novelty_score: float
    evidence_score: float
    research_value: float
    verdict: str
    bridge_mechanisms: tuple[str, ...] = ()
    bridge_families: tuple[str, ...] = ()
    shared_entities: tuple[str, ...] = ()
    source_entities: tuple[str, ...] = ()
    target_entities: tuple[str, ...] = ()
    bridge_paper_ids: tuple[str, ...] = ()
    rationale: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    source_context: str = ""
    target_context: str = ""


@dataclass(frozen=True)
class GraphDiscoveryCandidate:
    discovery_id: str
    created_at: str
    source_paper_id: str
    target_paper_id: str
    source_title: str
    target_title: str
    source_domain: str
    target_domain: str
    shared_mechanisms: tuple[str, ...] = ()
    shared_families: tuple[str, ...] = ()
    shared_entities: tuple[str, ...] = ()
    structural_score: float = 0.0
    evidence_score: float = 0.0
    novelty_score: float = 0.0
    research_value: float = 0.0
    status: str = "SCREEN_ONLY"
    provenance_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class GapRecord:
    gap_id: str
    created_at: str
    target_domain: str
    gap_kind: str
    label: str
    source_domains: tuple[str, ...]
    source_support_count: int
    target_support_count: int
    source_paper_ids: tuple[str, ...] = ()
    rationale: str = ""
    priority_score: float = 0.0
    status: str = "UNTESTED_GAP"


@dataclass(frozen=True)
class VariableMapping:
    source_variable: str
    target_variable: str
    source_unit: str = ""
    target_unit: str = ""
    relation: str = "UNDECLARED"
    observable: bool = False
    rationale: str = ""


@dataclass(frozen=True)
class TransmutationCandidate:
    candidate_id: str
    created_at: str
    source_equation_id: str
    source_equation_type: str
    source_structural_signature: str
    source_equation: str
    target_problem: str
    source_domain: str
    target_domain: str
    source_variables: tuple[str, ...] = ()
    variable_mappings: tuple[VariableMapping, ...] = ()
    mapping_coverage: float = 0.0
    preserved_operators: tuple[str, ...] = ()
    target_observables: tuple[str, ...] = ()
    causal_hypothesis: str = ""
    falsification_test: str = ""
    stage: str = "PRE_FORMALIZATION"
    proposed_target_equation: str = "NOT_GENERATED_IN_PHASE_3"
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class TransferAudit:
    audit_id: str
    candidate_id: str
    created_at: str
    semantic_status: str
    mathematical_status: str
    dimensional_status: str
    causal_status: str
    observable_status: str
    falsifiability_status: str
    evidence_status: str
    transfer_score: float
    verdict: str
    blockers: tuple[str, ...] = ()
    requirements: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
