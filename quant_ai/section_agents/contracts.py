"""Typed contracts for contextual Quant Terminal section assistants.

The section-assistant layer deliberately uses standard-library dataclasses.
Pydantic is not a core Quant Terminal dependency, and importing this package
must remain cheap enough for the existing Streamlit application and tests.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _primitive(value: Any) -> Any:
    """Convert nested contracts into a JSON-safe representation."""

    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _primitive(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _primitive(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_primitive(item) for item in value]
    return value


class GovernanceMode(str, Enum):
    RESEARCH_ONLY = "RESEARCH_ONLY"


class ResponseStatus(str, Enum):
    ANSWERED = "ANSWERED"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    WAITING_EVIDENCE = "WAITING_EVIDENCE"
    NOT_CONNECTED = "NOT_CONNECTED"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    DEGRADED_ERROR = "DEGRADED_ERROR"


class EvidenceGrade(str, Enum):
    VERIFIED = "VERIFIED"
    DERIVED = "DERIVED"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"


class ToolRiskLevel(str, Enum):
    READ_ONLY = "READ_ONLY"
    UI_NAVIGATION = "UI_NAVIGATION"
    RESEARCH_MUTATION = "RESEARCH_MUTATION"
    FINANCIAL_ACTION = "FINANCIAL_ACTION"


@dataclass(frozen=True, slots=True)
class SectionManifest:
    """Versioned description of one independently governed assistant."""

    section_id: str
    function: str
    label: str
    description: str
    mode: str | None
    default_asset: str
    default_symbol: str
    audiences: tuple[str, ...]
    special_route: str | None = None
    force_context: bool = False
    mandate: str = ""
    knowledge_collections: tuple[str, ...] = ()
    allowed_context_keys: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    denied_capabilities: tuple[str, ...] = ()
    quick_actions: tuple[str, ...] = ()
    schema_version: str = "1.0"

    @property
    def code(self) -> str:
        """Compatibility alias for ``institutional_router.WorkspaceSpec.code``."""

        return self.section_id

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)


@dataclass(frozen=True, slots=True)
class DataSourceRef:
    source_id: str
    title: str = ""
    as_of: str = ""
    vintage: str = ""
    freshness: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)


@dataclass(frozen=True, slots=True)
class SectionContextEnvelope:
    """Allowlisted, bounded state supplied to a section assistant."""

    section_id: str
    request_id: str = field(default_factory=lambda: uuid4().hex)
    conversation_id: str = ""
    user_id: str = ""
    tenant_id: str = ""
    route: str = ""
    active_view: str = ""
    security: str = ""
    primary_function: str = ""
    asset_type: str = ""
    symbols: tuple[str, ...] = ()
    date_range: Mapping[str, Any] = field(default_factory=dict)
    filters: Mapping[str, Any] = field(default_factory=dict)
    widget_values: Mapping[str, Any] = field(default_factory=dict)
    section_state: Mapping[str, Any] = field(default_factory=dict)
    data_sources: tuple[DataSourceRef, ...] = ()
    permissions: tuple[str, ...] = ()
    data_as_of: str = ""
    context_hash: str = ""
    governance_mode: GovernanceMode = GovernanceMode.RESEARCH_ONLY
    created_at: str = field(default_factory=utc_now)
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)


@dataclass(frozen=True, slots=True)
class SectionAgentRequest:
    section_id: str
    message: str
    context: SectionContextEnvelope
    locale: str = "fr-FR"
    requested_mode: str = "guide"
    request_id: str = ""

    @property
    def effective_request_id(self) -> str:
        return self.request_id or self.context.request_id

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)


@dataclass(frozen=True, slots=True)
class Citation:
    source_id: str
    title: str
    locator: str = ""
    as_of: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)


@dataclass(frozen=True, slots=True)
class SuggestedAction:
    action_id: str
    label: str
    description: str = ""
    risk_level: ToolRiskLevel = ToolRiskLevel.READ_ONLY
    requires_confirmation: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    code: str
    reason: str
    governance_mode: GovernanceMode = GovernanceMode.RESEARCH_ONLY
    required_confirmation: bool = False
    blocked_capabilities: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)


@dataclass(frozen=True, slots=True)
class SectionResponseDraft:
    """Provider-neutral draft returned by an optional response adapter."""

    answer_markdown: str
    status: ResponseStatus = ResponseStatus.ANSWERED
    evidence_grade: EvidenceGrade = EvidenceGrade.UNKNOWN
    citations: tuple[Citation, ...] = ()
    facts: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    suggested_actions: tuple[SuggestedAction, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SectionAgentResponse:
    run_id: str
    request_id: str
    section_id: str
    status: ResponseStatus
    answer_markdown: str
    evidence_grade: EvidenceGrade
    policy_decision: PolicyDecision
    context_hash: str = ""
    citations: tuple[Citation, ...] = ()
    facts: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    suggested_actions: tuple[SuggestedAction, ...] = ()
    warnings: tuple[str, ...] = ()
    provider: str = "deterministic"
    model: str = "deterministic-fallback"
    latency_ms: int = 0
    created_at: str = field(default_factory=utc_now)
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)


@dataclass(frozen=True, slots=True)
class SectionAuditRecord:
    """Minimal audit record compatible with :class:`quant_ai.state.AuditStore`."""

    run_id: str
    request_id: str
    section_id: str
    conversation_id: str
    user_id: str
    tenant_id: str
    message_hash: str
    context_hash: str
    status: ResponseStatus
    evidence_grade: EvidenceGrade
    policy_decision: PolicyDecision
    provider: str
    model: str
    latency_ms: int
    record_type: str = "section_agent"
    created_at: str = field(default_factory=utc_now)
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)
