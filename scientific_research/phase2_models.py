from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProvenanceRecord:
    provenance_id: str
    paper_id: str
    source_kind: str
    sentence_index: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    excerpt: str = ""
    source_digest: str = ""


@dataclass(frozen=True)
class ClaimRecord:
    claim_id: str
    paper_id: str
    text: str
    claim_type: str
    extraction_confidence: float
    support_status: str
    provenance_id: str
    statistical_cues: tuple[str, ...] = ()
    # Phase 2.5.1: finer semantics without breaking legacy stored records.
    claim_subtype: str = ""
    explicitness: str = "EXPLICIT_SOURCE_CLAIM"


@dataclass(frozen=True)
class AssumptionRecord:
    assumption_id: str
    paper_id: str
    text: str
    category: str
    explicitness: str
    extraction_confidence: float
    provenance_id: str


@dataclass(frozen=True)
class SemanticEntityRecord:
    entity_id: str
    paper_id: str
    entity_type: str
    canonical_label: str
    matched_text: str
    extraction_confidence: float
    provenance_id: str


@dataclass(frozen=True)
class EquationStructure:
    equation_id: str
    paper_id: str
    raw: str
    normalized: str
    equation_type: str
    variables: tuple[str, ...] = ()
    parameters: tuple[str, ...] = ()
    operators: tuple[str, ...] = ()
    derivative_order: int = 0
    stochastic_terms: tuple[str, ...] = ()
    geometry_terms: tuple[str, ...] = ()
    integral_terms: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    dimensional_status: str = "UNKNOWN"
    structural_signature: str = ""
    provenance_id: str = ""


@dataclass(frozen=True)
class KnowledgeNode:
    node_id: str
    node_type: str
    label: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeEdge:
    edge_id: str
    source: str
    target: str
    relation: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class UnderstandingBundle:
    understanding_id: str
    paper_id: str
    created_at: str
    source_digest: str
    source_kind: str
    domain: str
    problem: str
    claims: tuple[ClaimRecord, ...] = ()
    assumptions: tuple[AssumptionRecord, ...] = ()
    equations: tuple[EquationStructure, ...] = ()
    mechanisms: dict[str, float] = field(default_factory=dict)
    mechanism_families: dict[str, tuple[str, ...]] = field(default_factory=dict)
    variables: tuple[str, ...] = ()
    knowledge_nodes: tuple[KnowledgeNode, ...] = ()
    knowledge_edges: tuple[KnowledgeEdge, ...] = ()
    warnings: tuple[str, ...] = ()
    # Phase 2.5 hardening. Defaults keep Phase-2 stored objects readable.
    semantic_entities: tuple[SemanticEntityRecord, ...] = ()
    problem_provenance_id: str = ""
    mechanism_provenance_ids: dict[str, tuple[str, ...]] = field(default_factory=dict)
    ontology_version: str = ""
    # Phase 6.3 extraction genealogy. Defaults preserve legacy JSON records.
    extractor_version: str = "LEGACY_UNVERSIONED"
    compiler_signature: str = ""
    parent_understanding_id: str = ""
    revision_id: str = ""
