from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import backtest_lab
from backtest_lab import (
    _advanced_stress_capacity_bundle,
    _leverage_margin_stress_pack,
    _run_backtest,
    _test_harness_failure_severity_ledger_v14,
)
from tests.test_backtest_manual_truth import _bars, _cfg


pytestmark = pytest.mark.filterwarnings(
    "ignore:is_sparse is deprecated:DeprecationWarning"
)


def test_advanced_stress_bundle_is_complete_read_only_and_fail_closed() -> None:
    close = np.r_[
        np.full(12, 100.0),
        np.linspace(100.0, 135.0, 80),
        np.linspace(135.0, 82.0, 88),
    ]
    bars = _bars(close)
    cfg = _cfg(
        "SMA Trend",
        capital=1_000_000_000.0,
        fee_bps=3.0,
        slippage_bps=5.0,
        fast_ma=3,
        slow_ma=7,
    )
    result = _run_backtest(bars, cfg)
    assert "error" not in result
    before = result["data"].copy(deep=True)

    bundle = _advanced_stress_capacity_bundle(
        bars=bars,
        metrics=result["metrics"],
        integrity=90,
        verdict="VALIDATED",
        research_label="RESEARCH",
        reasons=[],
        notes=[],
        diagnostics={},
        bt=result["data"],
        trades=result["trades"],
        comp_df=pd.DataFrame(),
        wf_df=pd.DataFrame(),
        cost_matrix=pd.DataFrame(),
        sens_matrix=pd.DataFrame(),
        risk_events=result.get("risk_events", pd.DataFrame()),
        cfg=cfg,
    )

    assert bundle["authority"] == "DIAGNOSTIC_ONLY"
    assert bundle["errors"] == {}
    assert bundle["execution"]["enabled"] is True
    assert bundle["liquidity"]["enabled"] is True
    assert not bundle["tail_risk"]["table"].empty
    assert not bundle["event_stress"].empty
    assert bundle["margin"]["level"] == "Disabled"
    assert "DO NOT" in bundle["deployment"]["decision"] or bundle["deployment"]["decision"] == "BLOCKED"
    assert bundle["paper_shadow"]["shadow_mode"] == "RESEARCH ONLY"
    assert bundle["test_harness"]["enabled"] is True
    assert bundle["test_harness"]["automation"] == "AUTOMATIC_ON_EXPLICIT_RUN"
    assert not bundle["test_harness"]["cases"].empty
    assert bundle["test_harness"]["level"] in {"Clean", "Warnings", "Failed", "Critical failure"}
    assert bundle["deployment"]["institutional_gate_decision"] == "HOLD — DATA REQUIRED"
    assert bundle["deployment"]["level"] == "Blocked by institutional gate"
    assert bundle["failure_attribution"]["enabled"] is True
    assert "Capital scale" in set(
        bundle["failure_attribution"]["root_cause_map"]["Area"]
    )
    pd.testing.assert_frame_equal(result["data"], before)


def test_margin_simulation_error_never_returns_a_reassuring_state(monkeypatch) -> None:
    bars = _bars(np.linspace(100.0, 125.0, 80))
    cfg = _cfg("SMA Trend", margin_stress_enabled=True)
    result = _run_backtest(bars, cfg)
    assert "error" not in result

    monkeypatch.setattr(
        backtest_lab,
        "_margin_stress_single_path",
        lambda **_: {
            "path": pd.DataFrame(),
            "events": pd.DataFrame(),
            "summary": {"error": "synthetic failure"},
        },
    )
    pack = _leverage_margin_stress_pack(result["data"], cfg)

    assert pack["enabled"] is False
    assert pack["requested"] is True
    assert pack["level"] == "Unavailable"
    assert "indisponible" in pack["read"].lower()
    assert pack["scenarios"].empty


def test_harness_warning_is_not_duplicated_as_a_critical_failure() -> None:
    pack = {
        "cases": pd.DataFrame(
            [{"Case": "Breakout", "Status": "WARN", "Failure": "no trades"}]
        ),
        "failures": pd.DataFrame(
            [{"Case": "Breakout", "Failure": "no trades"}]
        ),
        "module_checks": pd.DataFrame(),
        "data_integrity_gates": pd.DataFrame(),
        "causality_guard": pd.DataFrame(),
    }
    severity = _test_harness_failure_severity_ledger_v14(pack)

    assert severity["level"] == "Warnings"
    assert severity["fail_count"] == 0
    assert severity["critical_count"] == 0


def test_missing_volume_hides_the_false_zero_impact_curves() -> None:
    app = AppTest.from_string(
        """
import pandas as pd
from backtest_institutional.workspace import _render_liquidity_capacity
_render_liquidity_capacity(
    {
        "enabled": True,
        "level": "UNAVAILABLE — DATA REQUIRED",
        "score": 20.0,
        "read": "Volume absent.",
        "volume_available": False,
        "checks": pd.DataFrame([{"Check": "Volume", "Status": "WARN"}]),
        "capacity_curve": pd.DataFrame(
            {"Target Participation": [0.01], "Conservative Capacity": [0.0]}
        ),
        "impact_stress": pd.DataFrame(
            {"Capital Multiple": [1], "Total Return After Impact": [0.25]}
        ),
    },
    "SYNTH",
)
""",
        default_timeout=30,
    ).run()

    assert not app.exception
    assert any("Capacité non calculable" in item.value for item in app.error)
    assert len(app.get("plotly_chart")) == 0


def test_failed_margin_simulation_is_not_presented_as_disabled() -> None:
    app = AppTest.from_string(
        """
import pandas as pd
from backtest_institutional.workspace import _render_margin_and_events
_render_margin_and_events(
    pd.DataFrame(),
    {
        "enabled": False,
        "requested": True,
        "level": "Unavailable",
        "read": "Stress de marge indisponible : simulation échouée.",
    },
    {},
    "SYNTH",
)
""",
        default_timeout=30,
    ).run()

    assert not app.exception
    assert any("simulation échouée" in item.value for item in app.error)
    assert not any("désactivé" in item.value for item in app.info)
    assert any("Marge activée" in item.value and "OUI" in item.value for item in app.markdown)
