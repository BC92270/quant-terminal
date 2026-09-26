from __future__ import annotations

import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

from market_intelligence.config import DESK_SEQUENCE, VIEW_SPECS, VIEW_SLUGS
from market_intelligence.demo import build_workspace_snapshot
from market_intelligence.governance import assess_workspace
from market_intelligence.ui.common import esc, tone_for_status
from market_intelligence.ui.institutional_control import decision_dossier_json


ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "scripts" / "market_intelligence_smoke_app.py"


def _app(view: str = "live", symbol: str = "NVDA") -> AppTest:
    app = AppTest.from_file(str(HARNESS))
    app.session_state["mi_active_view"] = view
    app.session_state["mi_selected_symbol"] = symbol
    app.session_state["mi_context_initialized"] = True
    app.session_state["mi_horizon"] = "30m"
    return app.run(timeout=30)


def test_workflow_preserves_all_thirteen_unique_views() -> None:
    assert DESK_SEQUENCE == ("NOW", "STATE", "FUSION", "GOVERN")
    assert len(VIEW_SPECS) == 13
    assert len(VIEW_SLUGS) == len(set(VIEW_SLUGS)) == 13
    assert {view.desk for view in VIEW_SPECS} == set(DESK_SEQUENCE)


def test_status_tones_fail_closed_for_missing_or_blocked_states() -> None:
    assert tone_for_status(None) == "muted"
    assert tone_for_status("UNAVAILABLE") == "muted"
    assert tone_for_status("WAITING_EVIDENCE") == "amber"
    assert tone_for_status("BLOCKED") == "red"
    assert tone_for_status("DISABLED") == "red"
    assert tone_for_status("FOUNDATION PASS") == "green"


def test_control_room_exposes_decision_evidence_and_execution_boundaries() -> None:
    app = _app("live")
    assert not app.exception
    rendered = "\n".join(str(item.value) for item in app.markdown)
    assert "Current state" in rendered
    assert "What changed" in rendered
    assert "Contradiction" in rendered
    assert "WAITING_EVIDENCE" in rendered
    assert "EXECUTION" in rendered
    assert "DISABLED" in rendered
    assert "Claim boundary and next evidence" in rendered


def test_non_fixture_symbol_shows_context_isolation_warning() -> None:
    app = _app("live", symbol="AAPL")
    assert not app.exception
    assert any("Context isolation active" in str(item.value) for item in app.warning)
    assert any("requested AAPL" in str(item.value) for item in app.warning)


def test_navigation_moves_between_workflow_stages_without_removing_views() -> None:
    app = _app("live")
    app.button(key="mi_desk_govern").click().run(timeout=30)
    assert app.session_state["mi_active_view"] == "patterns"
    assert app.session_state["mi_active_desk"] == "GOVERN"
    app.button(key="mi_nav_research").click().run(timeout=30)
    assert app.session_state["mi_active_view"] == "research"
    assert app.session_state["mi_navigation_history"][-1] == {"from": "patterns", "to": "research"}


def test_external_text_escaping_primitive_blocks_html_injection() -> None:
    payload = '<img src=x onerror="alert(1)">'
    escaped = esc(payload)
    assert "<img" not in escaped
    assert "&lt;img" in escaped
    assert "onerror" in escaped


def test_model_observatory_exposes_typed_registry_and_fail_closed_controls() -> None:
    app = _app("models")
    assert not app.exception
    rendered = "\n".join(str(item.value) for item in app.markdown)
    assert "TYPED INVENTORY" in rendered
    assert "WAITING_EVIDENCE" in rendered
    assert "Promotion path is closed" in rendered
    tables = [element.value for element in app.dataframe]
    assert any("Artifact hash" in table.columns for table in tables)
    assert any("Source status" in table.columns for table in tables)


def test_research_view_exports_a_reproducible_evidence_dossier() -> None:
    app = _app("research")
    assert not app.exception
    downloads = app.get("download_button")
    assert len(downloads) == 1
    assert downloads[0].label == "EXPORT REPRODUCIBLE EVIDENCE DOSSIER · JSON"
    rendered = "\n".join(str(item.value) for item in app.markdown)
    assert "Immutable decision identity" in rendered
    assert "HASH-CHAINED EVIDENCE" in rendered
    tables = [element.value for element in app.dataframe]
    assert any("Record hash" in table.columns for table in tables)
    assert any("Blocking now" in table.columns for table in tables)


def test_evidence_dossier_contains_replayable_source_contracts() -> None:
    snapshot = build_workspace_snapshot("NVDA")
    payload = json.loads(decision_dossier_json(assess_workspace(snapshot), snapshot))
    assert payload["replay_contract"]["engine"] == "market_intelligence.governance.assess_workspace"
    assert payload["replay_contract"]["evaluation_clock"] == "SNAPSHOT_AS_OF"
    assert payload["source_contracts"]["symbol"] == "NVDA"
    assert len(payload["source_contracts"]["events"]) == len(snapshot.events)
    assert len(payload["source_contracts"]["forecasts"]) == len(snapshot.forecasts)
    assert payload["scenario_definitions"]


def test_focus_horizon_drives_forecast_cards_and_table_selection() -> None:
    app = _app("forecast")
    app.selectbox(key="mi_horizon").select("1h").run(timeout=30)
    assert not app.exception
    assert app.session_state["mi_horizon"] == "1h"
    rendered = "\n".join(str(item.value) for item in app.markdown)
    assert "FOCUS 1H" in rendered
    tables = [element.value for element in app.dataframe]
    forecast = next(table for table in tables if {"Focus", "Horizon"}.issubset(table.columns))
    selected = forecast.loc[forecast["Focus"] == "● SELECTED"]
    assert selected["Horizon"].tolist() == ["1h"]


def test_snapshot_construction_failure_isolated_with_canonical_fallback() -> None:
    app = AppTest.from_string(
        """
from collections.abc import Mapping
import streamlit as st
from market_intelligence import render_market_intelligence_lab

class ExplodingMapping(Mapping):
    def __getitem__(self, key):
        raise RuntimeError("secret provider failure")
    def __iter__(self):
        return iter(("price",))
    def __len__(self):
        return 1
    def get(self, key, default=None):
        raise RuntimeError("secret provider failure")

st.set_page_config(layout="wide")
render_market_intelligence_lab(ticker="NVDA", analysis=ExplodingMapping())
"""
    ).run(timeout=30)
    assert not app.exception
    assert any("Input context isolated safely" in str(item.value) for item in app.error)
    assert any("canonical NVDA fixture" in str(item.value) for item in app.warning)
    rendered = "\n".join(str(item.value) for item in app.markdown)
    assert "Institutional Control Plane" in rendered
    assert "secret provider failure" not in rendered


def test_governance_failure_remains_fail_closed_and_navigation_survives() -> None:
    app = AppTest.from_string(
        """
import streamlit as st
import market_intelligence.ui.institutional_control as control
from market_intelligence import render_market_intelligence_lab

def fail_governance(snapshot):
    raise RuntimeError("secret governance failure")

original_assess_workspace = control.assess_workspace
control.assess_workspace = fail_governance
st.set_page_config(layout="wide")
try:
    render_market_intelligence_lab(ticker="NVDA")
finally:
    control.assess_workspace = original_assess_workspace
"""
    ).run(timeout=30)
    assert not app.exception
    assert any("Governance control plane isolated safely" in str(item.value) for item in app.error)
    assert any("fail-closed posture enforced" in str(item.value) for item in app.warning)
    assert app.button(key="mi_desk_govern")
    rendered = "\n".join(str(item.value) for item in app.markdown)
    assert "secret governance failure" not in rendered
