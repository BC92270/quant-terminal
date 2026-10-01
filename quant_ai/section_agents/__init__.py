"""Public API for Quant Terminal contextual section assistants."""

from .adapters import DeterministicSectionAdapter, LLMSectionAdapter
from .audit import SectionAuditStore
from .context import SectionContextBuilder
from .contracts import (
    Citation,
    DataSourceRef,
    EvidenceGrade,
    GovernanceMode,
    PolicyDecision,
    ResponseStatus,
    SectionAgentRequest,
    SectionAgentResponse,
    SectionContextEnvelope,
    SectionManifest,
    SuggestedAction,
    ToolRiskLevel,
)
from .manifests import (
    ALL_SECTION_MANIFESTS,
    NAVIGATOR_MANIFEST,
    TRADING_PLAN_MANIFEST,
    WORKSPACE_CODES,
    WORKSPACE_MANIFESTS,
)
from .policy import SectionPolicy
from .registry import SectionAgentRegistry, build_default_section_registry, resolve_section_id
from .service import SectionAgentService

__all__ = [
    "ALL_SECTION_MANIFESTS",
    "Citation",
    "DataSourceRef",
    "DeterministicSectionAdapter",
    "EvidenceGrade",
    "GovernanceMode",
    "LLMSectionAdapter",
    "NAVIGATOR_MANIFEST",
    "PolicyDecision",
    "ResponseStatus",
    "SectionAgentRegistry",
    "SectionAgentRequest",
    "SectionAgentResponse",
    "SectionAgentService",
    "SectionAuditStore",
    "SectionContextBuilder",
    "SectionContextEnvelope",
    "SectionManifest",
    "SectionPolicy",
    "SuggestedAction",
    "TRADING_PLAN_MANIFEST",
    "ToolRiskLevel",
    "WORKSPACE_CODES",
    "WORKSPACE_MANIFESTS",
    "build_default_section_registry",
    "resolve_section_id",
]
