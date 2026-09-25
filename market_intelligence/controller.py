"""Workspace orchestration with panel-level failure isolation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import streamlit as st

from .demo import build_workspace_snapshot
from .state import initialize_state
from .ui.common import render_data_contract
from .ui.shell import render_context_controls, render_navigation, render_shell_header
from .ui.theme import inject_market_intelligence_theme


def _renderers() -> dict[str, Callable[[Any], None]]:
    from .ui.catalyst_collision import render_catalyst_collision
    from .ui.catalyst_map import render_catalyst_map
    from .ui.cross_asset import render_cross_asset
    from .ui.discovered_patterns import render_discovered_patterns
    from .ui.event_explorer import render_event_explorer
    from .ui.forecast_surface import render_forecast_surface
    from .ui.historical_analogues import render_historical_analogues
    from .ui.information_gap import render_information_gap
    from .ui.live_intelligence import render_live_intelligence
    from .ui.microstructure_intelligence import render_microstructure_intelligence
    from .ui.model_observatory import render_model_observatory
    from .ui.narrative_monitor import render_narrative_monitor
    from .ui.research_validation import render_research_validation

    return {
        "live": render_live_intelligence,
        "events": render_event_explorer,
        "catalyst-map": render_catalyst_map,
        "narratives": render_narrative_monitor,
        "collision": render_catalyst_collision,
        "analogues": render_historical_analogues,
        "microstructure": render_microstructure_intelligence,
        "information-gap": render_information_gap,
        "cross-asset": render_cross_asset,
        "forecast": render_forecast_surface,
        "patterns": render_discovered_patterns,
        "models": render_model_observatory,
        "research": render_research_validation,
    }


def render_market_intelligence_lab(
    ticker: str = "SPY",
    price_data: Any = None,
    analysis: Any = None,
) -> None:
    initialize_state(st.session_state, ticker=ticker)
    inject_market_intelligence_theme()
    selected_symbol = st.session_state.get("mi_selected_symbol") or ticker or "NVDA"
    snapshot = build_workspace_snapshot(selected_symbol, price_data=price_data, analysis=analysis)
    render_shell_header(snapshot)
    render_context_controls(snapshot)
    active_view = render_navigation()
    renderer = _renderers().get(active_view, _renderers()["live"])
    try:
        renderer(snapshot)
    except Exception as exc:
        st.error(f"This panel degraded safely: {type(exc).__name__}: {exc}")
        st.info("The rest of Quant Terminal remains available. Select another Market Intelligence view or return to Command Center.")
    render_data_contract(snapshot)
