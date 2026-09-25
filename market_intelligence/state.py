"""Namespaced Streamlit state helpers."""

from __future__ import annotations

from typing import Any, MutableMapping

from .config import VIEW_SLUGS


DEFAULTS: dict[str, Any] = {
    "mi_active_view": "live",
    "mi_selected_symbol": "NVDA",
    "mi_horizon": "30m",
    "mi_selected_event": "evt-fed-hawkish",
    "mi_refresh_mode": "MANUAL",
    "mi_research_run": None,
}


def initialize_state(state: MutableMapping[str, Any], *, ticker: str | None = None) -> None:
    for key, value in DEFAULTS.items():
        state.setdefault(key, value)
    if ticker and not state.get("mi_context_initialized"):
        state["mi_selected_symbol"] = str(ticker).upper().strip() or "NVDA"
        state["mi_context_initialized"] = True
    if state.get("mi_active_view") not in VIEW_SLUGS:
        state["mi_active_view"] = "live"


def set_active_view(state: MutableMapping[str, Any], view: str) -> None:
    if view not in VIEW_SLUGS:
        raise ValueError(f"Unknown Market Intelligence view: {view}")
    state["mi_active_view"] = view
