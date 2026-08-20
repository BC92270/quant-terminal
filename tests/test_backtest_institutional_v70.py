from __future__ import annotations

import ast
from dataclasses import asdict
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd

from backtest_institutional.data_catalog import assess_market_data
from backtest_institutional.engine import run_institutional_stack
from backtest_institutional.execution import ExecutionModelConfig, calibrate_power_impact, simulate_execution
from backtest_institutional.registry import ExperimentRegistry, build_run_manifest
from backtest_institutional.scenarios import ScenarioConfig, run_institutional_scenario_suite
from backtest_institutional.statistics import (
    benjamini_hochberg,
    cscv_probability_of_backtest_overfitting,
    hansen_spa_test,
    holm_bonferroni,
    purged_combinatorial_splits,
    white_reality_check,
)
from backtest_institutional.types import AvailabilityState, ValidationState


def market_frame(n: int = 260, with_volume: bool = True) -> pd.DataFrame:
    rng = np.random.default_rng(123)
    index = pd.bdate_range("2022-01-03", periods=n)
    returns = rng.normal(0.0004, 0.012, n)
    close = 100 * np.cumprod(1 + returns)
    open_ = close * (1 + rng.normal(0, 0.0015, n))
    high = np.maximum(open_, close) * (1 + rng.uniform(0.0005, 0.006, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0.0005, 0.006, n))
    data = {"Open": open_, "High": high, "Low": low, "Close": close}
    if with_volume:
        data["Volume"] = rng.integers(1_000_000, 3_000_000, n)
    return pd.DataFrame(data, index=index)


def test_catalog_is_explicit_and_fail_closed():
    bars = market_frame(with_volume=False)
    assessment = assess_market_data(
        bars, symbol="TEST", source="unit", required_capabilities=("volume_impact",)
    )
    assert assessment.capabilities["volume_impact"].state == AvailabilityState.UNAVAILABLE
    assert assessment.verdict == ValidationState.UNAVAILABLE
    assert "DATA REQUIRED" in assessment.capabilities["volume_impact"].reason

    broken = bars.copy()
    broken.iloc[5, broken.columns.get_loc("High")] = broken.iloc[5]["Low"] - 1
    invalid = assess_market_data(broken, symbol="TEST", source="unit")
    assert invalid.verdict == ValidationState.FAIL
    assert any("invalid OHLC" in issue for issue in invalid.issues)


def test_event_ledger_costs_latency_partial_fills_and_unavailable_volume():
    bars = market_frame(120, with_volume=True)
    target = pd.Series(np.where(np.arange(len(bars)) % 20 < 10, 0.8, -0.4), index=bars.index)
    config = ExecutionModelConfig(
        model="square_root", initial_capital=5_000_000, max_participation=0.0001,
        annual_borrow_bps=125,
    )
    result = simulate_execution(bars, target, symbol="TEST", config=config)
    assert result.status in {AvailabilityState.AVAILABLE, AvailabilityState.PARTIAL}
    assert result.fills
    assert result.diagnostics["lookahead_guard_bars"] == 1
    assert result.diagnostics["total_cost"] > 0
    assert result.diagnostics["partial_orders"] > 0
    assert result.daily.index.equals(bars.index)
    assert result.fills[0].timestamp != str(bars.index[0])

    no_volume = simulate_execution(
        bars.drop(columns=["Volume"]), target, symbol="TEST", config=config
    )
    assert no_volume.status == AvailabilityState.UNAVAILABLE
    assert no_volume.diagnostics["fail_closed"] is True

    zero_volume_bars = bars.copy()
    zero_volume_bars["Volume"] = 0.0
    zero_catalog = assess_market_data(
        zero_volume_bars, symbol="TEST", source="unit",
        required_capabilities=("volume_impact",),
    )
    assert zero_catalog.capabilities["volume_impact"].state == AvailabilityState.UNAVAILABLE
    zero_execution = simulate_execution(
        zero_volume_bars, target, symbol="TEST", config=config
    )
    assert zero_execution.status == AvailabilityState.UNAVAILABLE

    constant = simulate_execution(
        bars.drop(columns=["Volume"]), target, symbol="TEST",
        config=ExecutionModelConfig(model="constant", annual_borrow_bps=100),
    )
    assert constant.status == AvailabilityState.AVAILABLE
    assert constant.fills


def test_impact_calibration_recovers_coefficient():
    p = np.array([0.001, 0.004, 0.01, 0.04, 0.09])
    coefficient = 0.12
    bps = 10_000 * coefficient * np.sqrt(p)
    fit = calibrate_power_impact(p, bps)
    assert abs(fit["impact_coefficient"] - coefficient) < 1e-10
    assert fit["rmse_bps"] < 1e-8


def test_statistical_suite_is_deterministic_and_multiple_test_aware():
    rng = np.random.default_rng(9)
    candidates = pd.DataFrame({
        "a": rng.normal(0.0007, 0.01, 360),
        "b": rng.normal(0.0002, 0.012, 360),
        "c": rng.normal(-0.0001, 0.009, 360),
        "d": rng.normal(0.0004, 0.015, 360),
    })
    rc1 = white_reality_check(candidates, bootstrap_samples=80, seed=4)
    rc2 = white_reality_check(candidates, bootstrap_samples=80, seed=4)
    spa = hansen_spa_test(candidates, bootstrap_samples=80, seed=4)
    pbo = cscv_probability_of_backtest_overfitting(candidates)
    assert rc1 == rc2
    assert 0 <= rc1["p_value"] <= 1
    assert 0 <= spa["p_value"] <= 1
    assert 0 <= pbo["pbo"] <= 1

    splits = purged_combinatorial_splits(180, total_folds=6, test_folds=2, purge=3, embargo=4)
    assert len(splits) == 15
    for train, test in splits:
        assert not set(train).intersection(test)

    p_values = [0.001, 0.02, 0.06, 0.4]
    holm = holm_bonferroni(p_values)
    fdr = benjamini_hochberg(p_values)
    assert holm.loc[0, "reject"]
    assert fdr.loc[0, "reject"]
    assert (holm["adjusted_p"].dropna().between(0, 1)).all()


def test_scenario_suite_covers_five_families_and_reverse_stress():
    returns = market_frame(300)["Close"].pct_change().dropna()
    config = ScenarioConfig(horizon_days=63, paths=60, seed=77)
    first = run_institutional_scenario_suite(returns, config=config)
    second = run_institutional_scenario_suite(returns, config=config)
    assert len(first["summary"]) == 5
    pd.testing.assert_frame_equal(first["summary"], second["summary"])
    assert set(first["summary"].index) == {
        "Historical bootstrap", "Multivariate Student-t", "Markov regime switching",
        "EVT empirical tail", "Liquidity spiral",
    }
    assert first["reverse_stress"]["multiplier"] >= 1
    assert abs(sum(first["regime_mix"].values()) - 1) < 1e-12


def test_manifest_registry_and_bundle_are_reproducible(tmp_path):
    bars = market_frame(80)
    kwargs = dict(
        config={"alpha": 1, "beta": [2, 3]}, market_data=bars, strategy="SMA",
        symbol="TEST", seed=5, code_path="backtest_lab.py",
    )
    first = build_run_manifest(**kwargs)
    second = build_run_manifest(**kwargs)
    assert first.run_id == second.run_id
    assert first.config_hash == second.config_hash
    registry = ExperimentRegistry(tmp_path / "registry")
    path = registry.persist(first, {"decision": "HOLD"})
    assert registry.persist(first, {"decision": "HOLD"}) == path
    assert registry.get(first.run_id)["manifest"]["run_id"] == first.run_id
    assert registry.lineage(first.run_id) == [first.run_id]


def test_full_stack_and_governance_bundle():
    bars = market_frame(180)
    exposure = pd.Series(np.where(np.arange(len(bars)) % 40 < 25, 0.7, 0.0), index=bars.index)
    strategy_returns = exposure * bars["Close"].pct_change().fillna(0)
    legacy = pd.DataFrame({
        "exposure": exposure,
        "strategy_return": strategy_returns,
        "equity": 1_000_000 * (1 + strategy_returns).cumprod(),
    }, index=bars.index)
    candidates = pd.DataFrame({
        "base": strategy_returns,
        "lagged": strategy_returns.shift(1).fillna(0),
        "half": strategy_returns * 0.5,
    }, index=bars.index)
    run = run_institutional_stack(
        bars=bars,
        legacy_result={"data": legacy},
        strategy="Unit Strategy",
        symbol="TEST",
        config_payload={"capital": 1_000_000},
        execution_config=ExecutionModelConfig(model="square_root", annual_borrow_bps=100),
        scenario_config=ScenarioConfig(horizon_days=40, paths=40, seed=10),
        candidate_returns=candidates,
        seed=10,
    )
    assert run.manifest.run_id.startswith("BT-")
    assert run.validation["candidate_count"] == 3
    assert len(run.scenarios["summary"]) == 5
    assert run.gate["fail_closed"] is True
    with ZipFile(BytesIO(run.bundle)) as archive:
        names = set(archive.namelist())
    assert {"manifest.json", "model_card.json", "data_catalog.json", "tables/fills.csv"}.issubset(names)


def test_ui_routes_preserve_all_sections_and_export_is_lazy_safe():
    source = Path("backtest_lab.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    render = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "render_backtest_lab_mode")
    tab_call = next(
        node for node in ast.walk(render)
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "tabs"
        and any(keyword.arg == "key" and isinstance(keyword.value, ast.Constant) and keyword.value.value == "bt_main_tabs_v60" for keyword in node.keywords)
    )
    labels = [element.value for element in tab_call.args[0].elts]
    assert labels == [
        "Executive", "Performance", "Trades", "Robustness", "Validation",
        "Regimes", "Strategy Compare", "Export", "Institutional V7",
    ]
    assert "test_harness_pack=test_harness_pack" not in source
    assert 'test_harness_pack=locals().get("test_harness_pack", {})' in source
    assert "if tabs[8].open:" in source
    assert "UNAVAILABLE — DATA REQUIRED" in source
