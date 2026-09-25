from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "scripts" / "market_intelligence_smoke_app.py"


@pytest.mark.parametrize(
    "view",
    [
        "live",
        "events",
        "catalyst-map",
        "narratives",
        "collision",
        "analogues",
        "microstructure",
        "information-gap",
        "cross-asset",
        "forecast",
        "patterns",
        "models",
        "research",
    ],
)
def test_each_market_intelligence_view_renders_without_panel_failure(view: str) -> None:
    app = AppTest.from_file(str(HARNESS))
    app.session_state["mi_active_view"] = view
    app.session_state["mi_selected_symbol"] = "NVDA"
    app.session_state["mi_context_initialized"] = True
    app.session_state["mi_horizon"] = "30m"
    app.run(timeout=30)

    assert not app.exception
    assert not app.error
    assert app.session_state["mi_active_view"] == view
