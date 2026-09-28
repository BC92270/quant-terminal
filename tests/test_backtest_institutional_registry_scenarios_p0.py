from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import json
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pytest

from backtest_institutional.registry import ExperimentRegistry, build_run_manifest
from backtest_institutional.reporting import build_governance_bundle
from backtest_institutional.scenarios import (
    ScenarioConfig,
    _circular_block_bootstrap_paths,
    _path_metrics,
    empirical_evt_tail_paths,
    markov_regime_paths,
    multivariate_student_t_paths,
    run_institutional_scenario_suite,
)


def _market_data(rows: int = 180) -> pd.DataFrame:
    index = pd.date_range("2020-01-01", periods=rows, freq="B")
    close = 100.0 * np.cumprod(1.0 + 0.0003 + 0.01 * np.sin(np.arange(rows) / 9.0))
    return pd.DataFrame({"Close": close, "Volume": 1_000_000}, index=index)


def test_manifest_hashes_complete_package_and_research_artifacts(tmp_path):
    package = tmp_path / "backtest_institutional"
    package.mkdir()
    (package / "__init__.py").write_text("VERSION = 1\n", encoding="utf-8")
    nested = package / "nested.py"
    nested.write_text("VALUE = 1\n", encoding="utf-8")
    entrypoint = tmp_path / "backtest_lab.py"
    entrypoint.write_text("from backtest_institutional import VERSION\n", encoding="utf-8")
    bars = _market_data()
    candidates = pd.DataFrame({"a": [0.0, 0.01], "b": [0.0, -0.01]})
    factors = pd.DataFrame({"market": [0.0, 0.02]})
    kwargs = {
        "config": {"alpha": 1},
        "market_data": bars,
        "strategy": "SMA",
        "symbol": "TEST",
        "seed": 7,
        "code_path": entrypoint,
        "package_path": package,
        "candidate_returns": candidates,
        "factor_returns": factors,
        "legacy_result": {"data": pd.DataFrame({"return": [0.0, 0.005]})},
    }
    first = build_run_manifest(**kwargs, created_at="2026-01-01T00:00:00+00:00")
    same_identity = build_run_manifest(**kwargs, created_at="2026-02-01T00:00:00+00:00")
    assert first.run_id == same_identity.run_id
    assert first.metadata["artifact_hashes"].keys() == {
        "candidate_returns", "factor_returns", "legacy_result",
    }
    assert "backtest_institutional/nested.py" in first.metadata["code_inventory"]

    nested.write_text("VALUE = 2\n", encoding="utf-8")
    code_changed = build_run_manifest(**kwargs)
    assert code_changed.code_hash != first.code_hash
    assert code_changed.run_id != first.run_id

    changed_candidates = candidates.copy()
    changed_candidates.loc[1, "a"] = 0.02
    artifact_changed = build_run_manifest(
        **(kwargs | {"candidate_returns": changed_candidates}),
    )
    assert artifact_changed.run_id != code_changed.run_id


def test_registry_ignores_created_at_only_but_remains_immutable(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    common = {
        "config": {"capital": 1_000_000},
        "market_data": _market_data(),
        "strategy": "Unit",
        "symbol": "TEST",
        "seed": 4,
        "code_path": package,
        "package_path": package,
    }
    first = build_run_manifest(**common, created_at="2026-01-01T00:00:00+00:00")
    later = build_run_manifest(**common, created_at="2026-01-02T00:00:00+00:00")
    registry = ExperimentRegistry(tmp_path / "registry")
    path = registry.persist(first, {"decision": "HOLD"})
    assert registry.persist(later, {"decision": "HOLD"}) == path
    assert registry.get(first.run_id)["manifest"]["created_at"] == first.created_at
    with pytest.raises(RuntimeError, match="Immutable run collision"):
        registry.persist(later, {"decision": "TRADE"})


def test_governance_bundle_contains_full_configs_candidates_and_checksums(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    manifest = build_run_manifest(
        config={"capital": 1_000_000},
        market_data=_market_data(),
        strategy="Unit",
        symbol="TEST",
        seed=8,
        code_path=package,
        package_path=package,
        created_at="2026-01-01T00:00:00+00:00",
    )
    candidates = pd.DataFrame({"base": [0.0, 0.01], "challenger": [0.0, -0.01]})
    factors = pd.DataFrame({"market": [0.0, 0.02], "value": [0.0, 0.01]})
    kwargs = {
        "manifest": manifest,
        "config": {"capital": 1_000_000},
        "data_catalog": {"verdict": "PASS", "capabilities": {}},
        "execution": {"model": "square_root"},
        "validation": {"candidate_count": 2},
        "scenarios": {"seed": 8},
        "v7_configs": {
            "execution": {"model": "square_root", "max_participation": 0.10},
            "scenario": ScenarioConfig(paths=20, horizon_days=10),
            "point_in_time": True,
        },
        "candidate_returns": candidates,
        "factor_returns": factors,
        "legacy_result": {"metrics": {"sharpe": 0.5}},
        "additional_artifacts": {"promotion_note": "research only"},
    }
    first = build_governance_bundle(**kwargs)
    assert first == build_governance_bundle(**kwargs)
    with ZipFile(BytesIO(first)) as archive:
        names = set(archive.namelist())
        assert {
            "configs/v7.json",
            "artifacts/candidate_returns.csv",
            "artifacts/factor_returns.csv",
            "artifacts/legacy_result.json",
            "artifacts/promotion_note.txt",
            "artifact_manifest.json",
        }.issubset(names)
        config = json.loads(archive.read("configs/v7.json"))
        assert config["execution"]["max_participation"] == 0.10
        inventory = json.loads(archive.read("artifact_manifest.json"))["files"]
        for name, descriptor in inventory.items():
            content = archive.read(name)
            assert descriptor["sha256"] == sha256(content).hexdigest()
            assert descriptor["bytes"] == len(content)
        assert all(item.date_time == (1980, 1, 1, 0, 0, 0) for item in archive.infolist())


def test_drawdown_metrics_use_initial_nav_and_configured_target():
    paths = np.asarray([[-0.15, 0.00], [-0.05, 0.00]])
    ten_percent = _path_metrics(paths, 0.975, target_drawdown=-0.10)
    twenty_percent = _path_metrics(paths, 0.975, target_drawdown=-0.20)
    assert ten_percent["median_max_drawdown"] == pytest.approx(-0.10)
    assert ten_percent["breach_probability"] == 0.5
    assert twenty_percent["breach_probability"] == 0.0


def test_historical_bootstrap_preserves_observed_blocks():
    returns = np.arange(23, dtype=float)
    simulated = _circular_block_bootstrap_paths(
        returns,
        paths=8,
        horizon=12,
        block_length=4,
        seed=17,
    )
    for path in simulated:
        for start in range(0, 12, 4):
            block = path[start:start + 4].astype(int)
            assert np.array_equal(block[1:], (block[:-1] + 1) % len(returns))


def test_markov_is_empirically_calibrated_and_explicitly_a_proxy():
    rng = np.random.default_rng(18)
    returns = pd.Series(np.r_[
        rng.normal(0.0005, 0.006, 180),
        rng.normal(-0.003, 0.025, 60),
        rng.normal(0.0002, 0.010, 120),
    ])
    _, _, metadata = markov_regime_paths(
        returns,
        ScenarioConfig(paths=20, horizon_days=15, seed=11),
        return_metadata=True,
    )
    transition = np.asarray(metadata["transition_matrix"])
    assert metadata["is_latent_hmm"] is False
    assert "calibrated" in metadata["method"]
    assert np.allclose(transition.sum(axis=1), 1.0)
    assert sum(metadata["state_counts"]) == len(returns)


def test_evt_fails_closed_on_small_sample_and_calibrates_gpd():
    rng = np.random.default_rng(19)
    config = ScenarioConfig(paths=30, horizon_days=15, seed=12)
    with pytest.raises(ValueError, match="needed for EVT"):
        empirical_evt_tail_paths(pd.Series(rng.normal(0, 0.01, 100)), config)

    returns = pd.Series(rng.standard_t(5, 500) * 0.012)
    paths, metadata = empirical_evt_tail_paths(returns, config)
    assert paths.shape == (30, 15)
    assert metadata["status"] == "CALIBRATED"
    assert "generalized Pareto" in metadata["method"]
    assert metadata["tail_observations"] >= config.evt_min_tail_observations
    assert -1.0 < metadata["shape"] < 1.0


def test_crisis_correlation_is_used_and_factor_paths_are_aggregated():
    rng = np.random.default_rng(20)
    factors = pd.DataFrame({
        "market": rng.normal(0.0002, 0.010, 400),
        "value": rng.normal(0.0001, 0.012, 400),
    })
    low_config = ScenarioConfig(paths=100, horizon_days=25, seed=13, crisis_correlation=0.0)
    high_config = replace(low_config, crisis_correlation=0.80)
    low = multivariate_student_t_paths(factors, low_config)
    high = multivariate_student_t_paths(factors, high_config)
    low_correlation = np.corrcoef(low[:, :, 0].ravel(), low[:, :, 1].ravel())[0, 1]
    high_correlation = np.corrcoef(high[:, :, 0].ravel(), high[:, :, 1].ravel())[0, 1]
    assert high_correlation > 0.70
    assert high_correlation > low_correlation + 0.50

    strategy = 0.20 * factors["market"] + 1.50 * factors["value"] + rng.normal(0, 0.002, len(factors))
    suite = run_institutional_scenario_suite(
        strategy,
        factor_returns=factors,
        config=ScenarioConfig(paths=30, horizon_days=15, seed=14),
    )
    exposures = suite["factor_model"]["exposures"]
    assert exposures["market"] == pytest.approx(0.20, abs=0.05)
    assert exposures["value"] == pytest.approx(1.50, abs=0.05)
    assert suite["historical_bootstrap"]["method"] == "circular moving-block bootstrap"
