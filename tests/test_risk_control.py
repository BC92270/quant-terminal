from __future__ import annotations

from pathlib import Path
import textwrap

import numpy as np
import pandas as pd
import pytest

from risk_control.engine import (
    RiskParameters,
    build_institutional_risk_snapshot,
    build_tail_model_comparison,
    data_quality_assessment,
    drawdown_diagnostics,
    liquidity_diagnostics,
    position_and_reverse_stress,
    simple_returns,
    var_backtests,
)


def _market_frame(seed: int = 19, rows: int = 700) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=rows)
    innovations = rng.standard_t(df=6, size=rows) * 0.011 + 0.00025
    close = 100.0 * np.exp(np.cumsum(innovations))
    frame = pd.DataFrame(
        {
            "date": dates,
            "open": close,
            "high": close * 1.005,
            "low": close * 0.995,
            "close": close,
            "volume": 2_000_000.0,
        }
    )
    frame.attrs["data_context"] = {
        "provider": "Test Provider",
        "status": "ok",
        "recency": "LIVE",
        "rows": rows,
    }
    return frame


def test_tail_models_are_deterministic_and_expected_shortfall_is_beyond_var():
    returns = simple_returns(_market_frame())
    first = build_tail_model_comparison(returns, horizon=10, confidence=0.975, seed=77)
    second = build_tail_model_comparison(returns, horizon=10, confidence=0.975, seed=77)

    assert set(first["Model"]) >= {
        "Historical simulation",
        "Gaussian parametric",
        "Student-t simulation",
        "Filtered historical (EWMA)",
    }
    pd.testing.assert_frame_equal(first, second)
    eligible = first.dropna(subset=["VaR", "ES"])
    assert (eligible["ES"] <= eligible["VaR"] + 1e-12).all()
    assert (eligible["VaR"] < 0).all()


def test_liquidity_capacity_uses_notional_and_adv_participation():
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=80)
    frame = pd.DataFrame({"date": dates, "close": 100.0, "volume": 10_000.0})
    parameters = RiskParameters(position_notional=500_000.0, adv_participation=0.10)

    result = liquidity_diagnostics(frame, parameters)

    assert result["adv20"] == pytest.approx(1_000_000.0)
    assert result["position_adv"] == pytest.approx(0.50)
    assert result["days_to_liquidate"] == pytest.approx(5.0)
    assert result["status"] == "CONSTRAINED"


@pytest.mark.parametrize(
    ("side", "expected_shock"),
    [("Long", -0.10), ("Short", 0.10)],
)
def test_reverse_stress_solves_asset_shock_for_portfolio_loss_limit(side, expected_shock):
    parameters = RiskParameters(
        side=side,
        portfolio_nav=1_000_000.0,
        position_notional=100_000.0,
        loss_limit_pct=0.01,
    )
    result = position_and_reverse_stress(
        parameters=parameters,
        price=100.0,
        stop_short=95.0,
        stop_structural=90.0,
        conservative_var=-0.06,
        conservative_es=-0.08,
    )
    assert result["shock_to_loss_limit"] == pytest.approx(expected_shock)
    assert result["es_dollars"] == pytest.approx(8_000.0)
    assert result["max_notional_es"] == pytest.approx(125_000.0)


def test_drawdown_depth_and_duration_are_computed_from_price_path():
    frame = pd.DataFrame(
        {
            "date": pd.bdate_range("2026-01-02", periods=6),
            "close": [100.0, 110.0, 88.0, 99.0, 111.0, 105.0],
        }
    )
    result = drawdown_diagnostics(frame)

    assert result["max_drawdown"] == pytest.approx(-0.20)
    assert result["current_drawdown"] == pytest.approx(105.0 / 111.0 - 1.0)
    assert result["max_underwater_days"] == 2
    assert result["recovery_days"] == 2


def test_var_backtest_returns_coverage_and_independence_diagnostics():
    result = var_backtests(simple_returns(_market_frame(rows=900)), confidence=0.975, window=125)

    assert set(result["summary"]["Model"]) == {"Historical VaR", "EWMA Gaussian VaR"}
    assert result["summary"]["observations"].min() >= 100
    for column in ("kupiec_p_value", "independence_p_value", "conditional_p_value"):
        assert result["summary"][column].between(0.0, 1.0).all()
    assert {"Historical VaR exception", "EWMA Gaussian VaR exception"}.issubset(result["series"].columns)


def test_snapshot_preserves_provider_lineage_and_builds_actionable_controls():
    frame = _market_frame()
    price = float(frame["close"].iloc[-1])
    result = build_institutional_risk_snapshot(
        frame,
        price=price,
        parameters=RiskParameters(position_notional=250_000.0, loss_limit_pct=0.01),
        stop_short=price * 0.95,
        stop_structural=price * 0.90,
    )

    assert result["data_quality"]["provider"]["provider"] == "Test Provider"
    assert result["control_status"] in {"GREEN", "AMBER", "RED"}
    assert not result["alerts"].empty
    assert {"Custom shock", "Conservative model ES"}.issubset(set(result["scenarios"]["Scenario"]))
    assert result["position"]["binding_notional_limit"] is not None


def test_fallback_or_delayed_provider_creates_provenance_warning():
    frame = _market_frame()
    frame.attrs["data_context"] = {
        "provider": "Fallback Feed",
        "status": "fallback",
        "recency": "UNSPECIFIED / DELAYED",
    }
    price = float(frame["close"].iloc[-1])
    result = build_institutional_risk_snapshot(
        frame,
        price=price,
        parameters=RiskParameters(),
        stop_short=price * 0.95,
        stop_structural=price * 0.90,
    )
    provenance = result["alerts"].loc[result["alerts"]["Control"] == "Data provenance"].iloc[0]
    assert provenance["Severity"] == "WARNING"
    assert result["control_status"] in {"AMBER", "RED"}


def test_data_quality_disables_volume_confidence_when_volume_is_absent():
    frame = _market_frame().drop(columns="volume")
    quality = data_quality_assessment(frame)
    assert quality["score"] < 100.0
    assert quality["checks"].loc[quality["checks"]["Check"] == "Volume coverage", "Status"].iloc[0] == "WARN"


def test_app_routes_risk_monitor_to_the_imported_renderer():
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    assert "render_risk_monitor_v2(ticker, price_data, analysis)" in source
    assert "render_risk_monitor_mode(ticker, price_data, analysis)" not in source


def test_risk_monitor_streamlit_smoke_has_no_runtime_exception(tmp_path):
    streamlit_testing = pytest.importorskip("streamlit.testing.v1")
    root = Path(__file__).resolve().parents[1]
    harness = tmp_path / "risk_monitor_harness.py"
    harness.write_text(
        textwrap.dedent(
            f"""
            import sys
            sys.path.insert(0, {str(root)!r})
            import numpy as np
            import pandas as pd
            from risk_monitor import render_risk_monitor_v2

            rng = np.random.default_rng(22)
            dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=320)
            returns = rng.standard_t(7, size=320) * 0.009 + 0.0002
            close = 100.0 * np.exp(np.cumsum(returns))
            frame = pd.DataFrame({{
                "date": dates,
                "open": close,
                "high": close * 1.004,
                "low": close * 0.996,
                "close": close,
                "volume": 1_500_000.0,
            }})
            frame.attrs["data_context"] = {{
                "provider": "UI Test Feed", "status": "ok", "recency": "LIVE", "rows": len(frame)
            }}
            price = float(close[-1])
            analysis = {{
                "latest_price": price,
                "atr": price * 0.015,
                "effective_volatility": 0.20,
                "max_drawdown": -0.14,
                "signal": "WATCH",
                "global_score": 62.0,
                "levels_52w": {{"distance_high": -0.08, "distance_low": 0.22}},
                "momentum_v2": {{"status": "OK"}},
                "trading_plan": {{
                    "entry_aggressive": price * 0.99,
                    "entry_prudent": price * 0.98,
                    "stop_short": price * 0.95,
                    "stop_structural": price * 0.90,
                    "target_1": price * 1.08,
                    "target_2": price * 1.15,
                    "risk_regime": "NORMAL",
                }},
            }}
            render_risk_monitor_v2("UITEST", frame, analysis)
            """
        ),
        encoding="utf-8",
    )
    app = streamlit_testing.AppTest.from_file(str(harness), default_timeout=40).run()
    assert not app.exception
    assert app.tabs[0].label == "Control Tower"
    assert app.tabs[-1].label == "Audit & Export"
