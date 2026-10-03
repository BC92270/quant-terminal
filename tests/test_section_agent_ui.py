from __future__ import annotations

from streamlit.testing.v1 import AppTest

from quant_ai.ui_components.section_assistant import resolve_section_id


def test_mode_and_special_routes_resolve_to_section_ids() -> None:
    assert resolve_section_id("Correlation Matrix") == "corr"
    assert resolve_section_id("market-intelligence") == "market_intelligence"
    assert resolve_section_id("scientific-research") == "scientific_research"
    assert resolve_section_id("Decision Engine Lite") == "decision"
    assert resolve_section_id("Trading Plan") == "trading_plan"
    assert resolve_section_id("unknown") is None


def test_streamlit_panel_renders_and_answers_in_local_mode() -> None:
    app = '''
from quant_ai.ui_components.section_assistant import render_section_assistant
render_section_assistant(
    "risk",
    security="SPY",
    primary_function="Risk Monitor",
    raw_context={
        "data_as_of": "2026-10-01",
        "section_state": {"analysis_available": True},
    },
    expanded=True,
)
'''
    test_app = AppTest.from_string(app, default_timeout=20).run()
    assert not list(test_app.exception)
    assert test_app.expander[0].label == "◈ ASSISTANT RISK MONITOR · SUPPORT CONTEXTUEL"
    assert test_app.text_area[0].label == "Votre question"

    test_app.text_area[0].set_value("Aide-moi à utiliser cette section")
    test_app.button[-1].click().run()

    assert not list(test_app.exception)
    assert len(test_app.chat_message) == 2
    history = test_app.session_state["section_agent_history::risk"]
    assert history[0]["response"]["status"] == "ANSWERED"
    assert "Risk Monitor" in history[0]["response"]["answer_markdown"]
