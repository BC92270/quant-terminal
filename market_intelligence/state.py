"""Namespaced Streamlit state helpers."""

from __future__ import annotations

from typing import Any, MutableMapping

from .config import VIEW_BY_SLUG, VIEW_SLUGS


DEFAULTS: dict[str, Any] = {
    "mi_active_view": "live",
    "mi_selected_symbol": "NVDA",
    "mi_horizon": "30m",
    "mi_selected_event": "evt-fed-hawkish",
    "mi_refresh_mode": "MANUAL",
    "mi_research_run": None,
    "mi_active_desk": "NOW",
    "mi_navigation_history": [],
    "mi_selected_claim": None,
    "mi_incident_ids": [],
    "mi_context_mode": "FIXTURE_SCENARIO",
}


def initialize_state(state: MutableMapping[str, Any], *, ticker: str | None = None) -> None:
    for key, value in DEFAULTS.items():
        state.setdefault(key, value)
    if ticker and not state.get("mi_context_initialized"):
        state["mi_selected_symbol"] = str(ticker).upper().strip() or "NVDA"
        state["mi_context_initialized"] = True
    if state.get("mi_active_view") not in VIEW_SLUGS:
        state["mi_active_view"] = "live"
    state["mi_active_desk"] = VIEW_BY_SLUG[state["mi_active_view"]].desk


def set_active_view(state: MutableMapping[str, Any], view: str) -> None:
    if view not in VIEW_SLUGS:
        raise ValueError(f"Unknown Market Intelligence view: {view}")
    previous = str(state.get("mi_active_view", "live"))
    state["mi_active_view"] = view
    state["mi_active_desk"] = VIEW_BY_SLUG[view].desk
    if previous != view:
        history = list(state.get("mi_navigation_history") or [])
        history.append({"from": previous, "to": view})
        state["mi_navigation_history"] = history[-20:]
