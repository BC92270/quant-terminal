from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    PARTIAL = "partial"
    NOT_AVAILABLE = "not_available"
    ERROR = "error"


class DecisionLabel(str, Enum):
    STRONG_BUY = "STRONG BUY"
    BUY = "BUY"
    WATCH = "WATCH"
    HOLD = "HOLD"
    REDUCE = "REDUCE"
    AVOID = "AVOID"
    HEDGE = "HEDGE"
    ABSTAIN = "ABSTAIN"


class RequestKind(str, Enum):
    SECURITY_RESEARCH = "security_research"
    STRATEGY_TEST = "strategy_test"
    PORTFOLIO_REVIEW = "portfolio_review"
    REBALANCE = "rebalance"
    HEDGE_DESIGN = "hedge_design"
    SCENARIO_ANALYSIS = "scenario_analysis"
    RISK_REVIEW = "risk_review"
    SCREENING = "screening"
    GENERAL = "general"


class InteractionKind(str, Enum):
    DISPATCH = "dispatch"
    TOOL_CALL = "tool_call"
    REPORT = "report"
    CONSULT = "consult"
    CHALLENGE = "challenge"
    SUPPORT = "support"
    VETO = "veto"
    SIGN_OFF = "sign_off"
    SYNTHESIS = "synthesis"


@dataclass(slots=True)
class Evidence:
    source: str
    title: str
    value: Any
    detail: str = ""
    as_of: str = ""
    quality: float = 0.7

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ToolResult:
    name: str
    status: NodeStatus
    data: dict[str, Any] = field(default_factory=dict)
    evidence: list[Evidence] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload


@dataclass(slots=True)
class PlanStep:
    specialist: str
    tools: list[str]
    objective: str
    reason: str


@dataclass(slots=True)
class CommitteePlan:
    query: str
    ticker: str
    steps: list[PlanStep]
    required_tools: list[str]
    coverage: list[str] = field(default_factory=list)
    request_kind: str = RequestKind.GENERAL.value


@dataclass(slots=True)
class AgentReport:
    agent_id: str
    agent_name: str
    role: str
    status: NodeStatus = NodeStatus.COMPLETE
    stance: str = "ABSTAIN"
    confidence: float = 0.0
    thesis: str = ""
    rationale: list[str] = field(default_factory=list)
    evidence_used: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    invalidation: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    dissent: str = ""
    assumptions: list[str] = field(default_factory=list)
    scenarios: list[str] = field(default_factory=list)
    monitoring: list[str] = field(default_factory=list)
    raw_text: str = ""
    latency_ms: int = 0
    model: str = "deterministic"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload


@dataclass(slots=True)
class InteractionEvent:
    source: str
    target: str
    kind: str
    message: str
    status: NodeStatus = NodeStatus.COMPLETE
    evidence: list[str] = field(default_factory=list)
    effect: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    event_id: str = field(default_factory=lambda: uuid4().hex[:10])

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload


@dataclass(slots=True)
class CIOBrief:
    decision: str = DecisionLabel.ABSTAIN.value
    confidence: float = 0.0
    headline: str = "Insufficient evidence"
    executive_summary: str = ""
    thesis: list[str] = field(default_factory=list)
    catalysts: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    invalidation: list[str] = field(default_factory=list)
    implementation: list[str] = field(default_factory=list)
    sizing: str = "No position proposed"
    time_horizon: str = "Unspecified"
    dissent: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    approval_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CommitteeRun:
    query: str
    ticker: str
    plan: CommitteePlan
    tools: dict[str, ToolResult]
    reports: list[AgentReport]
    brief: CIOBrief
    interactions: list[InteractionEvent] = field(default_factory=list)
    run_id: str = field(default_factory=lambda: uuid4().hex[:12])
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    provider: str = "deterministic"
    model: str = "deterministic"
    warnings: list[str] = field(default_factory=list)
    elapsed_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "query": self.query,
            "ticker": self.ticker,
            "provider": self.provider,
            "model": self.model,
            "warnings": list(self.warnings),
            "elapsed_ms": self.elapsed_ms,
            "plan": asdict(self.plan),
            "tools": {name: result.to_dict() for name, result in self.tools.items()},
            "reports": [report.to_dict() for report in self.reports],
            "interactions": [event.to_dict() for event in self.interactions],
            "brief": self.brief.to_dict(),
        }
