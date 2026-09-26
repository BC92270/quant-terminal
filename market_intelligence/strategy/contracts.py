"""Typed contracts for evidence-linked strategic decision support.

This domain deliberately sits above research governance and below any capital
or execution authority.  It may recommend a research or monitoring process,
but it can never produce an order, a BUY/SELL instruction, or an execution
authorization.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from ..contracts import as_utc
from ..evidence import canonical_hash


class DecisionPurpose(str, Enum):
    RESEARCH_PRIORITIZATION = "RESEARCH_PRIORITIZATION"
    MARKET_MONITORING = "MARKET_MONITORING"
    RISK_POSTURE_REVIEW = "RISK_POSTURE_REVIEW"


class StrategicDisposition(str, Enum):
    BLOCKED_CONTEXT = "BLOCKED_CONTEXT"
    REMEDIATE_CONTROLS = "REMEDIATE_CONTROLS"
    ACQUIRE_EVIDENCE = "ACQUIRE_EVIDENCE"
    MONITOR = "MONITOR"
    READY_FOR_HUMAN_REVIEW = "READY_FOR_HUMAN_REVIEW"


class OptionClass(str, Enum):
    PROCESS = "PROCESS"
    PORTFOLIO_REVIEW = "PORTFOLIO_REVIEW"
    EXECUTION = "EXECUTION"


class OptionStatus(str, Enum):
    RECOMMENDED = "RECOMMENDED"
    AVAILABLE = "AVAILABLE"
    BLOCKED = "BLOCKED"
    PROHIBITED = "PROHIBITED"


class ClaimKind(str, Enum):
    OBSERVED = "OBSERVED"
    DERIVED = "DERIVED"
    COUNTEREVIDENCE = "COUNTEREVIDENCE"
    ASSUMPTION = "ASSUMPTION"
    UNKNOWN = "UNKNOWN"


class ImpactState(str, Enum):
    ASSESSED = "ASSESSED"
    WAITING_EVIDENCE = "WAITING_EVIDENCE"
    UNPRICED = "UNPRICED"


class HumanDisposition(str, Enum):
    RETURN_FOR_EVIDENCE = "RETURN_FOR_EVIDENCE"
    DEFER = "DEFER"
    REJECT_MEMO = "REJECT_MEMO"
    ADVANCE_TO_INDEPENDENT_REVIEW = "ADVANCE_TO_INDEPENDENT_REVIEW"


class MemoValidity(str, Enum):
    CURRENT = "CURRENT"
    EXPIRED = "EXPIRED"


def _require_text(value: str, label: str) -> None:
    if not str(value).strip():
        raise ValueError(f"{label} cannot be empty")


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _require_enum(value: object, enum_type: type[Enum], label: str) -> None:
    if not isinstance(value, enum_type):
        raise TypeError(f"{label} must be a {enum_type.__name__}")


@dataclass(frozen=True, slots=True)
class DecisionContext:
    context_id: str
    requested_symbol: str
    subject_symbol: str
    as_of: datetime
    horizon: str
    purpose: DecisionPurpose
    question: str
    mandate_status: str
    exposure_status: str
    owner_role: str
    owner_status: str
    fixture_symbol: str
    context_integrity: str
    context_reason: str
    fusion_allowed: bool
    context_admissible: bool
    constraints: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of", as_utc(self.as_of))
        for name in (
            "context_id",
            "requested_symbol",
            "subject_symbol",
            "horizon",
            "question",
            "mandate_status",
            "exposure_status",
            "owner_role",
            "owner_status",
            "fixture_symbol",
            "context_integrity",
            "context_reason",
        ):
            _require_text(str(getattr(self, name)), name)
        _require_enum(self.purpose, DecisionPurpose, "purpose")
        if type(self.fusion_allowed) is not bool or type(self.context_admissible) is not bool:
            raise TypeError("fusion_allowed and context_admissible must be booleans")
        for name in ("requested_symbol", "subject_symbol", "fixture_symbol"):
            if getattr(self, name) != str(getattr(self, name)).upper():
                raise ValueError(f"{name} must be normalized to uppercase")
        expected_admissible = (
            self.context_integrity == "MATCHED"
            and self.fusion_allowed
            and self.requested_symbol == self.subject_symbol
            and self.fixture_symbol == self.subject_symbol
        )
        if self.context_admissible != expected_admissible:
            raise ValueError("context_admissible is inconsistent with the governed context contract")
        if self.context_id != "MI-SCTX-" + canonical_hash(self.hash_material())[:20].upper():
            raise ValueError("Strategic context ID does not match its canonical content")
        if not self.constraints:
            raise ValueError("Decision context requires explicit constraints")

    def hash_material(self) -> dict[str, Any]:
        return {
            "requested_symbol": self.requested_symbol,
            "subject_symbol": self.subject_symbol,
            "as_of": self.as_of,
            "horizon": self.horizon,
            "purpose": self.purpose,
            "question": self.question,
            "mandate_status": self.mandate_status,
            "exposure_status": self.exposure_status,
            "owner_role": self.owner_role,
            "owner_status": self.owner_status,
            "fixture_symbol": self.fixture_symbol,
            "context_integrity": self.context_integrity,
            "context_reason": self.context_reason,
            "fusion_allowed": self.fusion_allowed,
            "context_admissible": self.context_admissible,
            "constraints": self.constraints,
        }


@dataclass(frozen=True, slots=True)
class StrategicClaim:
    claim_id: str
    kind: ClaimKind
    statement: str
    source_view: str
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_enum(self.kind, ClaimKind, "kind")
        for name in ("claim_id", "statement", "source_view"):
            _require_text(str(getattr(self, name)), name)
        if self.kind in {ClaimKind.OBSERVED, ClaimKind.DERIVED, ClaimKind.COUNTEREVIDENCE} and not self.evidence_ids:
            raise ValueError(f"{self.kind.value} claims require evidence IDs")


@dataclass(frozen=True, slots=True)
class StrategicOption:
    option_id: str
    label: str
    option_class: OptionClass
    status: OptionStatus
    thesis: str
    strategic_benefit: str
    downside: str
    reversibility: str
    evidence_strength: str
    principal_blocker: str
    trigger: str
    invalidation: str
    destination_view: str
    execution_allowed: bool = False

    def __post_init__(self) -> None:
        _require_enum(self.option_class, OptionClass, "option_class")
        _require_enum(self.status, OptionStatus, "status")
        for name in (
            "option_id",
            "label",
            "thesis",
            "strategic_benefit",
            "downside",
            "reversibility",
            "evidence_strength",
            "principal_blocker",
            "trigger",
            "invalidation",
            "destination_view",
        ):
            _require_text(str(getattr(self, name)), name)
        if self.execution_allowed:
            raise ValueError("Strategic research options cannot authorize execution")
        if self.option_class == OptionClass.EXECUTION and self.status != OptionStatus.PROHIBITED:
            raise ValueError("Execution-class options must remain PROHIBITED")

    @property
    def selectable_for_session_record(self) -> bool:
        return self.option_class == OptionClass.PROCESS and self.status in {
            OptionStatus.RECOMMENDED,
            OptionStatus.AVAILABLE,
        }


@dataclass(frozen=True, slots=True)
class ImpactAssessment:
    dimension: str
    state: ImpactState
    assessment: str
    limitation: str
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_enum(self.state, ImpactState, "state")
        for name in ("dimension", "assessment", "limitation"):
            _require_text(str(getattr(self, name)), name)
        if self.state == ImpactState.ASSESSED and not self.evidence_ids:
            raise ValueError("Assessed impacts require evidence IDs")


@dataclass(frozen=True, slots=True)
class MonitoringRule:
    rule_id: str
    metric: str
    current_observation: str
    warning_trigger: str
    invalidation_condition: str
    owner_role: str
    source_view: str
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "rule_id",
            "metric",
            "current_observation",
            "warning_trigger",
            "invalidation_condition",
            "owner_role",
            "source_view",
        ):
            _require_text(str(getattr(self, name)), name)


@dataclass(frozen=True, slots=True)
class StrategicDecisionMemo:
    memo_id: str
    content_hash: str
    schema_version: str
    engine_version: str
    policy_version: str
    context: DecisionContext
    basis_packet_id: str
    basis_validation_run_id: str
    basis_evidence_root: str
    research_state: str
    disposition: StrategicDisposition
    recommended_process_option_id: str
    preferred_portfolio_option_id: str | None
    process_summary: str
    portfolio_summary: str
    decision_strength: str
    options: tuple[StrategicOption, ...]
    claims: tuple[StrategicClaim, ...]
    impacts: tuple[ImpactAssessment, ...]
    monitoring_rules: tuple[MonitoringRule, ...]
    blockers: tuple[str, ...]
    next_evidence: tuple[str, ...]
    review_at: datetime
    expires_at: datetime
    authority: str = "ADVISORY_ONLY"
    human_review_required: bool = True
    execution_allowed: bool = False
    order_payload: None = None

    def __post_init__(self) -> None:
        if not isinstance(self.context, DecisionContext):
            raise TypeError("context must be a DecisionContext")
        _require_enum(self.disposition, StrategicDisposition, "disposition")
        object.__setattr__(self, "review_at", as_utc(self.review_at))
        object.__setattr__(self, "expires_at", as_utc(self.expires_at))
        for name in (
            "memo_id",
            "schema_version",
            "engine_version",
            "policy_version",
            "basis_packet_id",
            "basis_validation_run_id",
            "research_state",
            "recommended_process_option_id",
            "process_summary",
            "portfolio_summary",
            "decision_strength",
            "authority",
        ):
            _require_text(str(getattr(self, name)), name)
        if not _is_sha256(self.content_hash) or not _is_sha256(self.basis_evidence_root):
            raise ValueError("Strategic decision hashes must be SHA-256 hex digests")
        if self.memo_id != "MI-SDM-" + self.content_hash[:20].upper():
            raise ValueError("memo_id must derive from content_hash")
        if self.review_at < self.context.as_of or self.expires_at < self.review_at:
            raise ValueError("Strategic review clock must satisfy as_of <= review_at <= expires_at")
        if self.authority != "ADVISORY_ONLY" or self.execution_allowed or self.order_payload is not None:
            raise ValueError("Strategic decisions are advisory-only and cannot carry orders")
        if not self.human_review_required:
            raise ValueError("Strategic decisions always require human review")
        identifiers = [option.option_id for option in self.options]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Strategic option IDs must be unique")
        selected = next(
            (option for option in self.options if option.option_id == self.recommended_process_option_id),
            None,
        )
        if selected is None or selected.option_class != OptionClass.PROCESS:
            raise ValueError("Recommended process option must exist and be a PROCESS option")
        if selected.status != OptionStatus.RECOMMENDED:
            raise ValueError("Recommended process option must carry RECOMMENDED status")
        if sum(option.status == OptionStatus.RECOMMENDED for option in self.options) != 1:
            raise ValueError("Strategic memo must contain exactly one recommended process option")
        claim_ids = [claim.claim_id for claim in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("Strategic claim IDs must be unique")
        rule_ids = [rule.rule_id for rule in self.monitoring_rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("Strategic monitoring rule IDs must be unique")
        impact_dimensions = [impact.dimension for impact in self.impacts]
        if len(impact_dimensions) != len(set(impact_dimensions)):
            raise ValueError("Strategic impact dimensions must be unique")
        if self.preferred_portfolio_option_id is not None:
            portfolio = next(
                (option for option in self.options if option.option_id == self.preferred_portfolio_option_id),
                None,
            )
            if portfolio is None or portfolio.option_class != OptionClass.PORTFOLIO_REVIEW:
                raise ValueError("Preferred portfolio option must reference a portfolio-review option")
            if portfolio.status != OptionStatus.AVAILABLE:
                raise ValueError("Preferred portfolio option must be available for separate human review")
        if not self.options or not self.claims or not self.impacts or not self.monitoring_rules:
            raise ValueError("Strategic memo requires options, claims, impacts and monitoring rules")
        if canonical_hash(self.hash_material()) != self.content_hash:
            raise ValueError("Strategic decision content hash mismatch")

    def hash_material(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "engine_version": self.engine_version,
            "policy_version": self.policy_version,
            "context": self.context,
            "basis_packet_id": self.basis_packet_id,
            "basis_validation_run_id": self.basis_validation_run_id,
            "basis_evidence_root": self.basis_evidence_root,
            "research_state": self.research_state,
            "disposition": self.disposition,
            "recommended_process_option_id": self.recommended_process_option_id,
            "preferred_portfolio_option_id": self.preferred_portfolio_option_id,
            "process_summary": self.process_summary,
            "portfolio_summary": self.portfolio_summary,
            "decision_strength": self.decision_strength,
            "options": self.options,
            "claims": self.claims,
            "impacts": self.impacts,
            "monitoring_rules": self.monitoring_rules,
            "blockers": self.blockers,
            "next_evidence": self.next_evidence,
            "review_at": self.review_at,
            "expires_at": self.expires_at,
            "authority": self.authority,
            "human_review_required": self.human_review_required,
            "execution_allowed": self.execution_allowed,
            "order_payload": self.order_payload,
        }
