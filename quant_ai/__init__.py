from .config import AgentConfig, ConfigStore, OrganizationConfig, ProviderSettings, default_organization
from .exports import decision_packet_json, decision_packet_markdown
from .interactive_graph import render_interactive_workflow, workflow_payload
from .orchestrator import CommitteeOrchestrator
from .portfolio import PortfolioMandate, PortfolioReview, review_portfolio
from .quality import CommitteeQuality, evaluate_committee, score_agent_report
from .schemas import (
    AgentReport,
    CIOBrief,
    CommitteeRun,
    DecisionLabel,
    InteractionEvent,
    InteractionKind,
    NodeStatus,
    RequestKind,
    ToolResult,
)
from .strategy import BacktestResult, StrategySpec, run_strategy_backtest
from .tools import QuantContext, build_default_registry


def render_quant_ai_terminal(*args, **kwargs):
    """Lazy compatibility entrypoint; keeps core imports independent of Streamlit."""
    from .ui import render_quant_ai_terminal as render

    return render(*args, **kwargs)

__all__ = [
    "AgentConfig",
    "AgentReport",
    "BacktestResult",
    "CIOBrief",
    "CommitteeOrchestrator",
    "CommitteeQuality",
    "CommitteeRun",
    "ConfigStore",
    "DecisionLabel",
    "InteractionEvent",
    "InteractionKind",
    "NodeStatus",
    "OrganizationConfig",
    "PortfolioMandate",
    "PortfolioReview",
    "ProviderSettings",
    "QuantContext",
    "RequestKind",
    "StrategySpec",
    "ToolResult",
    "build_default_registry",
    "default_organization",
    "decision_packet_json",
    "decision_packet_markdown",
    "evaluate_committee",
    "render_quant_ai_terminal",
    "render_interactive_workflow",
    "review_portfolio",
    "run_strategy_backtest",
    "score_agent_report",
    "workflow_payload",
]
