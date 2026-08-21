from pathlib import Path
import ast

import numpy as np
import pandas as pd

import backtest_lab as bt


def _cfg():
    return bt.BacktestConfig(
        strategy="SMA Trend",
        capital=100_000.0,
        position_pct=100.0,
        fee_bps=2.0,
        slippage_bps=3.0,
        fast_ma=20,
        slow_ma=100,
        breakout_window=55,
        rsi_window=14,
        rsi_entry=30.0,
        rsi_exit=55.0,
        vol_window=20,
        vol_threshold=0.03,
        allow_short=False,
    )


def test_institutional_scenario_pack_is_deterministic_and_complete():
    rng = np.random.default_rng(11)
    frame = pd.DataFrame(
        {"strategy_return": rng.normal(0.0002, 0.012, 700)}
    )
    first = bt._institutional_scenario_lab_v60_pack(
        frame, None, _cfg(), n_paths=500, horizon=126, block_size=20, seed=73
    )
    second = bt._institutional_scenario_lab_v60_pack(
        frame, None, _cfg(), n_paths=500, horizon=126, block_size=20, seed=73
    )

    assert first["available"] is True
    assert first["summary"]["Scenario"].tolist() == [
        "IID bootstrap",
        "Stationary block",
        "High-vol regime",
        "Historical crisis overlay",
        "Liquidity freeze",
    ]
    assert set(first["summary"]["Decision"]) <= {"PASS", "WATCH", "FAIL"}
    np.testing.assert_allclose(
        first["summary"]["P05 terminal"],
        second["summary"]["P05 terminal"],
    )
    np.testing.assert_allclose(first["fan"]["Median"], second["fan"]["Median"])


def test_lazy_validation_navigation_preserves_all_legacy_workbenches():
    source = Path(bt.__file__).read_text(encoding="utf-8")
    module = ast.parse(source)
    render = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "render_backtest_lab_mode"
    )
    call_names = {
        getattr(node.func, "id", getattr(node.func, "attr", ""))
        for node in ast.walk(render)
        if isinstance(node, ast.Call)
    }
    expected = {
        "_render_overfit_multiple_testing_lab_v1",
        "_render_econometric_diagnostics",
        "_render_cross_asset_validation_v1",
        "_render_factor_benchmark_attribution_v2",
        "_render_oos_validation_v2",
        "_render_execution_realism_layer_v28",
        "_render_liquidity_capacity_layer_v29",
        "_render_internal_test_harness_v1",
        "_render_live_deployment_readiness_v30",
        "_render_paper_shadow_live_protocol_v31",
        "_render_failure_attribution_redesign_map_v32",
        "_render_signal_regime_redesign_workbench_v33",
        "_render_research_mutation_blueprint_v34",
        "_render_brt_mutation_ledger_v35c",
        "_render_controlled_mutation_runner_v36",
        "_render_signal_candidate_factory_v37",
        "_render_strategy_source_expansion_v38",
        "_render_economic_hypothesis_signal_source_builder_v39",
        "_render_source_candidate_runner_v40",
        "_render_source_failure_forensics_v41",
        "_render_signal_activity_repair_v42",
        "_render_brt_signal_activity_mutation_runner_v43",
        "_render_mutation_trade_failure_decomposition_v44",
    }

    assert expected <= call_names
    assert 'key="bt_main_tabs_v60"' in source
    assert 'key="bt_validation_desks_v60"' in source
    assert "_render_institutional_scenario_lab_v60(" in source
    assert 'test_harness_pack=locals().get("test_harness_pack"' in source
