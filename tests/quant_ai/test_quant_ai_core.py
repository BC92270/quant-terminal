from __future__ import annotations

import json

import numpy as np
import pandas as pd

from quant_ai.alerts import evaluate_alerts
from quant_ai.config import default_config, export_config, ensure_agent_config, upsert_agent
from quant_ai.graph import graph_html
from quant_ai.llm import deterministic_plan
from quant_ai.schemas import NodeStatus
from quant_ai.state import get_statuses
from quant_ai.tools import QuantContext, build_default_registry, market_snapshot, risk_snapshot


def frame(n: int = 400) -> pd.DataFrame:
    rng = np.random.default_rng(17)
    rets = rng.normal(0.00035, 0.012, n)
    close = 100 * np.exp(np.cumsum(rets))
    dates = pd.bdate_range("2025-01-01", periods=n)
    return pd.DataFrame({"date": dates, "open": close * 0.998, "high": close * 1.006, "low": close * 0.994, "close": close, "volume": 1_000_000})


def context(session=None) -> QuantContext:
    return QuantContext("TEST", frame(), {}, session if session is not None else {}, {})


def test_market_snapshot_is_deterministic_and_complete() -> None:
    result = market_snapshot(context())
    assert result.status == NodeStatus.COMPLETE
    assert result.data["ticker"] == "TEST"
    assert result.data["observations"] == 400
    assert result.data["annualized_volatility"] > 0


def test_risk_snapshot_has_var_and_cvar() -> None:
    result = risk_snapshot(context())
    assert result.status == NodeStatus.COMPLETE
    assert result.data["hist_var_95"] > 0
    assert result.data["hist_cvar_95"] >= result.data["hist_var_95"]


def test_registry_unknown_tool_fails_safely() -> None:
    result = build_default_registry().run("does_not_exist", context())
    assert result.status == NodeStatus.ERROR


def test_deterministic_planner_is_selective_and_config_aware() -> None:
    tools = build_default_registry().names()
    cfg = default_config()
    plan = deterministic_plan("Analyse TEST et le risque du portefeuille", "TEST", tools, True, cfg)
    specialists = {step.specialist for step in plan.steps}
    assert "quant_pm" in specialists
    assert "risk_manager" in specialists
    assert "portfolio_pm" in specialists
    cfg["agents"]["portfolio_pm"]["enabled"] = False
    plan2 = deterministic_plan("Analyse TEST et le risque du portefeuille", "TEST", tools, True, cfg)
    assert "portfolio_pm" not in {step.specialist for step in plan2.steps}


def test_alert_engine() -> None:
    alerts = [{"enabled": True, "ticker": "TEST", "metric": "latest_price", "operator": ">", "threshold": 100.0, "name": "x"}]
    assert evaluate_alerts(alerts, {"latest_price": 101.0}, "TEST")
    assert not evaluate_alerts(alerts, {"latest_price": 99.0}, "TEST")


def test_custom_agent_roundtrip_and_no_api_key_in_export() -> None:
    session = {"quant_ai_api_key_v2": "sk-secret-should-never-export"}
    ensure_agent_config(session)
    agent_id = upsert_agent(session, {
        "name": "Event Driven PM",
        "role": "Specialist",
        "mandate": "Study catalysts.",
        "tools": ["market_snapshot", "risk_snapshot"],
        "enabled": True,
        "auto_include": True,
    })
    assert agent_id in session["quant_ai_agent_config_v2"]["agents"]
    payload = export_config(session)
    assert "sk-secret-should-never-export" not in payload
    parsed = json.loads(payload)
    assert parsed["agents"][agent_id]["tools"] == ["market_snapshot", "risk_snapshot"]


def test_graph_is_dark_and_dynamic() -> None:
    session = {}
    cfg = ensure_agent_config(session)
    html = graph_html(get_statuses(session), config=cfg, ai_enabled=False, model="gpt-5.6", selected_node="risk_manager")
    assert "#050a11" in html
    assert "CHIEF RISK" in html.upper()
    assert "AI DISCONNECTED" in html
