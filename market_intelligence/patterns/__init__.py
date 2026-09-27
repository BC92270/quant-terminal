"""Institutional pattern discovery exports.

Only the standard-library contracts are imported eagerly.  The feature and
engine modules are resolved on first use so unrelated Market Intelligence
pages do not import NumPy, scikit-learn or the ML Lab stack.
"""

from importlib import import_module
from typing import Any

from .contracts import (
    GateState,
    ModelValidationScore,
    PatternBridgeState,
    PatternCandidate,
    PatternCandidateState,
    PatternDiscoveryConfig,
    PatternDiscoveryReport,
    PatternFitArtifact,
    PatternGate,
    PatternInputAudit,
    PatternRunState,
    PatternStrategyBridge,
)

__all__ = [
    "GateState",
    "ModelValidationScore",
    "PatternBridgeState",
    "PatternCandidate",
    "PatternCandidateState",
    "PatternDiscoveryConfig",
    "PatternDiscoveryReport",
    "PatternFitArtifact",
    "PatternGate",
    "PatternInputAudit",
    "PatternRunState",
    "PatternStrategyBridge",
    "build_pattern_feature_bundle",
    "build_pattern_strategy_bridge",
    "causal_pattern_features",
    "discover_market_patterns",
    "normalize_price_history",
    "pattern_report_json",
]


_LAZY_EXPORTS = {
    "build_pattern_strategy_bridge": (".bridge", "build_pattern_strategy_bridge"),
    "build_pattern_feature_bundle": (".features", "build_pattern_feature_bundle"),
    "causal_pattern_features": (".features", "causal_pattern_features"),
    "normalize_price_history": (".features", "normalize_price_history"),
    "discover_market_patterns": (".engine", "discover_market_patterns"),
    "pattern_report_json": (".engine", "pattern_report_json"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
