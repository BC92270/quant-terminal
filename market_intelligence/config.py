"""Configuration for the Market Intelligence research workspace.

The package deliberately keeps research thresholds and display metadata in one
place.  None of the values below is a claim of predictive validity; promotion
thresholds remain task-specific and are evaluated by the research registry.
"""

from __future__ import annotations

from dataclasses import dataclass


SCHEMA_VERSION = "mi-2.0.0"
WORKSPACE_VERSION = "Market Intelligence V2 · Institutional Control Plane"
ROUTE_NAME = "market-intelligence"
SESSION_FLAG = "market_intelligence_open"


@dataclass(frozen=True, slots=True)
class ViewSpec:
    slug: str
    short_label: str
    label: str
    desk: str


VIEW_SPECS: tuple[ViewSpec, ...] = (
    ViewSpec("live", "LIVE", "Live Intelligence", "NOW"),
    ViewSpec("events", "EVENTS", "Event Explorer", "NOW"),
    ViewSpec("catalyst-map", "MAP", "Catalyst Map", "NOW"),
    ViewSpec("narratives", "NARRATIVE", "Narrative Monitor", "NOW"),
    ViewSpec("collision", "COLLISION", "Catalyst Collision", "STATE"),
    ViewSpec("analogues", "ANALOGUES", "Historical Analogues", "STATE"),
    ViewSpec("microstructure", "MICRO", "Microstructure Intelligence", "STATE"),
    ViewSpec("information-gap", "INFO GAP", "Information Gap", "STATE"),
    ViewSpec("cross-asset", "CROSS-ASSET", "Cross-Asset Propagation", "FUSION"),
    ViewSpec("forecast", "FORECAST", "Forecast Surface", "FUSION"),
    ViewSpec("patterns", "PATTERNS", "Machine-Discovered Patterns", "GOVERN"),
    ViewSpec("models", "MODELS", "Model Observatory", "GOVERN"),
    ViewSpec("research", "VALIDATION", "Research & Validation", "GOVERN"),
)

VIEW_BY_SLUG = {view.slug: view for view in VIEW_SPECS}
VIEW_SLUGS = tuple(VIEW_BY_SLUG)

DESK_SEQUENCE: tuple[str, ...] = ("NOW", "STATE", "FUSION", "GOVERN")
DESK_WORKFLOW: dict[str, tuple[str, str]] = {
    "NOW": ("01 · OBSERVE", "What changed and what is directly observable?"),
    "STATE": ("02 · EXPLAIN", "Which mechanisms, conflicts and residuals fit the evidence?"),
    "FUSION": ("03 · SYNTHESIZE", "How do horizons, modalities and linked assets interact?"),
    "GOVERN": ("04 · GOVERN", "Is the evidence reproducible, controlled and reviewable?"),
}

INTERACTION_STATES = frozenset(
    {
        "positive_confirmation",
        "positive_weak_confirmation",
        "catalyst_rejection",
        "negative_confirmation",
        "negative_weak_confirmation",
        "negative_catalyst_absorption",
        "collision_instability",
        "unexplained_information_flow",
    }
)

PROVIDER_STATUSES = frozenset(
    {"live", "cached", "delayed", "unavailable", "research_only", "simulated"}
)

# Transparent, descriptive thresholds for the fixture-state classifier.  They
# are not model-promotion thresholds and never produce a trading instruction.
ABSORPTION_SELL_FLOW_Z = -0.75
ABSORPTION_REPLENISHMENT_Z = 0.75
ABSORPTION_IMPACT_TREND = -0.15
COLLISION_HIGH = 0.70
UNEXPLAINED_HIGH = 0.70
