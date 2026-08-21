from __future__ import annotations

import numpy as np
import pandas as pd

from quant_ai.alerts import evaluate_alerts
from quant_ai.llm import deterministic_plan
from quant_ai.schemas import NodeStatus
from quant_ai.tools import QuantContext, build_default_registry, market_snapshot, risk_snapshot


def frame(n: int = 400) -> pd.DataFrame:
    rng = np.random.default_rng(17)
    rets = rng.normal(0.00035, 0.012, n)
    close = 100 * np.exp(np.cumsum(rets))
    dates = pd.bdate_range("2025-01-01", periods=n)
    return pd.DataFrame({"date": dates, "open": close * 0.998, "high": close * 1.006, "low": close * 0.994, "close": close, "volume": 1_000_000})


def context() -> QuantContext:
    return QuantContext("TEST", frame(), {}, {}, {})


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


def test_deterministic_planner_is_selective() -> None:
    tools = build_default_registry().names()
    plan = deterministic_plan("Analyse TEST et le risque du portefeuille", "TEST", tools, True)
    specialists = {step.specialist for step in plan.steps}
    assert "quant_pm" in specialists
    assert "risk_manager" in specialists
    assert "portfolio_pm" in specialists


def test_alert_engine() -> None:
    alerts = [{"enabled": True, "ticker": "TEST", "metric": "latest_price", "operator": ">", "threshold": 100.0, "name": "x"}]
    assert evaluate_alerts(alerts, {"latest_price": 101.0}, "TEST")
    assert not evaluate_alerts(alerts, {"latest_price": 99.0}, "TEST")
