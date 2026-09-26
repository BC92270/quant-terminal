"""Typed governance contracts for institutional research decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ..contracts import as_utc
from ..data.quality import LayerQuality
from ..evidence import EvidenceLedger, canonical_hash
from ..models.registry import ModelRegistry
from ..risk.scenarios import RiskEnvelope


class GateStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WAITING_EVIDENCE = "WAITING_EVIDENCE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class DecisionState(str, Enum):
    WAITING_EVIDENCE = "WAITING_EVIDENCE"
    ELIGIBLE_FOR_HUMAN_REVIEW = "ELIGIBLE_FOR_HUMAN_REVIEW"
    REJECTED = "REJECTED"


class ResearchBoundary(str, Enum):
    RESEARCH_ONLY = "RESEARCH_ONLY"


class ResearchPosture(str, Enum):
    OBSERVE_ONLY = "OBSERVE_ONLY"


@dataclass(frozen=True, slots=True)
class InstitutionalPolicy:
    version: str = "mi-governance-policy-3.0.0"
    require_current_data: bool = True
    require_calibration: bool = True
    require_chronological_oos: bool = True
    require_shadow_history: bool = True
    require_human_review: bool = True

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("InstitutionalPolicy version cannot be empty")


@dataclass(frozen=True, slots=True)
class GateResult:
    gate_id: str
    label: str
    status: GateStatus
    blocking: bool
    reason: str
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.gate_id.strip() or not self.label.strip() or not self.reason.strip():
            raise ValueError("Gate ID, label and reason cannot be empty")

    @property
    def blocks_progression(self) -> bool:
        return self.blocking and self.status in {GateStatus.FAIL, GateStatus.WAITING_EVIDENCE}


def _valid_digest(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


@dataclass(frozen=True, slots=True)
class ValidationRun:
    run_id: str
    engine_version: str
    policy_version: str
    started_at: datetime
    completed_at: datetime
    gates: tuple[GateResult, ...]
    evidence_root: str

    def __post_init__(self) -> None:
        if not self.run_id.strip() or not self.engine_version.strip() or not self.policy_version.strip():
            raise ValueError("Validation run identifiers cannot be empty")
        object.__setattr__(self, "started_at", as_utc(self.started_at))
        object.__setattr__(self, "completed_at", as_utc(self.completed_at))
        if self.completed_at < self.started_at:
            raise ValueError("Validation completed_at cannot precede started_at")
        if not _valid_digest(self.evidence_root):
            raise ValueError("evidence_root must be a SHA-256 hex digest")
        identifiers = [gate.gate_id for gate in self.gates]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Validation run contains duplicate gate IDs")
        expected_id = "MI-VAL-" + canonical_hash(self.hash_material())[:20]
        if self.run_id != expected_id:
            raise ValueError("Validation run ID does not match its canonical content")

    def hash_material(self) -> dict[str, object]:
        return {
            "engine": self.engine_version,
            "policy": self.policy_version,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "gates": self.gates,
            "evidence_root": self.evidence_root,
        }

    @property
    def blocking_results(self) -> tuple[GateResult, ...]:
        return tuple(gate for gate in self.gates if gate.blocks_progression)

    @property
    def eligible_for_human_review(self) -> bool:
        return bool(self.gates) and not self.blocking_results


@dataclass(frozen=True, slots=True)
class ResearchDecisionPacket:
    packet_id: str
    symbol: str
    as_of: datetime
    boundary: ResearchBoundary
    state: DecisionState
    posture: ResearchPosture
    execution_allowed: bool
    human_review_required: bool
    quality: tuple[LayerQuality, ...]
    validation: ValidationRun
    evidence_root: str
    interaction_state: str
    model_keys: tuple[str, ...]
    risk_state: str
    blockers: tuple[str, ...] = ()
    uncertainty_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.packet_id.strip() or not self.symbol.strip():
            raise ValueError("Decision packet identifiers cannot be empty")
        object.__setattr__(self, "as_of", as_utc(self.as_of))
        if self.boundary != ResearchBoundary.RESEARCH_ONLY:
            raise ValueError("Market Intelligence decision packets must remain RESEARCH_ONLY")
        if self.posture != ResearchPosture.OBSERVE_ONLY:
            raise ValueError("Market Intelligence strategic research supports OBSERVE_ONLY posture")
        if self.execution_allowed:
            raise ValueError("Research decision packets cannot authorize execution")
        if self.evidence_root != self.validation.evidence_root or not _valid_digest(self.evidence_root):
            raise ValueError("Decision and validation evidence roots must match")
        if self.state == DecisionState.ELIGIBLE_FOR_HUMAN_REVIEW and self.blockers:
            raise ValueError("Eligible decision packets cannot contain blockers")
        if self.state != DecisionState.ELIGIBLE_FOR_HUMAN_REVIEW and not self.blockers:
            raise ValueError("Non-eligible decision packets require explicit blockers")
        expected_id = "MI-DEC-" + canonical_hash(self.hash_material())[:20]
        if self.packet_id != expected_id:
            raise ValueError("Decision packet ID does not match its canonical content")

    def hash_material(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "as_of": self.as_of,
            "boundary": self.boundary,
            "state": self.state,
            "posture": self.posture,
            "execution_allowed": self.execution_allowed,
            "human_review_required": self.human_review_required,
            "quality": self.quality,
            "validation": self.validation,
            "evidence_root": self.evidence_root,
            "interaction_state": self.interaction_state,
            "model_keys": self.model_keys,
            "risk_state": self.risk_state,
            "blockers": self.blockers,
            "uncertainty_flags": self.uncertainty_flags,
        }


@dataclass(frozen=True, slots=True)
class GovernanceAssessment:
    decision: ResearchDecisionPacket
    ledger: EvidenceLedger
    model_registry: ModelRegistry
    risk_envelope: RiskEnvelope

    def __post_init__(self) -> None:
        self.ledger.verify()
        if self.ledger.root_hash != self.decision.evidence_root:
            raise ValueError("Governance assessment ledger root does not match decision packet")
        blocking = self.decision.validation.blocking_results
        hard_failures = tuple(result for result in blocking if result.status == GateStatus.FAIL)
        if self.decision.state == DecisionState.ELIGIBLE_FOR_HUMAN_REVIEW and blocking:
            raise ValueError("Eligible governance assessments cannot retain blocking validation results")
        if self.decision.state == DecisionState.REJECTED and not hard_failures:
            raise ValueError("Rejected governance assessments require a blocking FAIL result")
        if self.decision.state == DecisionState.WAITING_EVIDENCE and (not blocking or hard_failures):
            raise ValueError("WAITING_EVIDENCE requires non-failing blocking results")
