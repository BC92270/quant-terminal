"""Fail-closed Market Intelligence research governance."""

from .contracts import (
    DecisionState,
    GateResult,
    GateStatus,
    GovernanceAssessment,
    InstitutionalPolicy,
    ResearchBoundary,
    ResearchDecisionPacket,
    ResearchPosture,
    ValidationRun,
)
from .engine import GOVERNANCE_ENGINE_VERSION, assess_workspace, build_research_decision_packet

__all__ = [
    "DecisionState",
    "GateResult",
    "GateStatus",
    "GOVERNANCE_ENGINE_VERSION",
    "GovernanceAssessment",
    "InstitutionalPolicy",
    "ResearchBoundary",
    "ResearchDecisionPacket",
    "ResearchPosture",
    "ValidationRun",
    "assess_workspace",
    "build_research_decision_packet",
]
