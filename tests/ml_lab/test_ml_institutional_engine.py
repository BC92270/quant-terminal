import json

import numpy as np
import pandas as pd
import pytest

from ml_lab.institutional_engine import (
    CONTROL_PLANE_VERSION,
    LocalExperimentRegistry,
    block_bootstrap_sharpe_interval,
    build_institutional_control_report,
    causal_feature_frame,
    conformal_binary_sets,
    dataset_fingerprint,
    deflated_sharpe_probability,
    expected_calibration_error,
    point_in_time_audit,
    population_stability_index,
    promotion_decision,
    report_to_json,
    temporal_holdout_audit,
)
from ml_lab.institutional_ui import compute_research_readiness


def _institutional_frames(rows: int = 218) -> tuple[pd.DataFrame, pd.DataFrame]:
    index = pd.date_range("2025-01-02", periods=rows, freq="B", tz="UTC")
    directional = ["TP first", "SL first"] * ((rows - 6) // 2)
    labels = pd.DataFrame(
        {"tb_label": directional + ["Timeout"] * 6},
        index=index,
    )
    x = np.linspace(-1.0, 1.0, rows)
    features = pd.DataFrame(
        {
            "momentum_5": x,
            "volatility_20": 0.20 + 0.02 * np.sin(np.arange(rows) / 11.0),
            "volume_zscore": np.cos(np.arange(rows) / 9.0),
        },
        index=index,
    )
    return labels, features


def test_control_plane_version_and_fingerprint_are_deterministic():
    labels, features = _institutional_frames()
    first = dataset_fingerprint(labels, features, horizon=20)
    second = dataset_fingerprint(labels.copy(), features.copy(), horizon=20)
    changed = dataset_fingerprint(labels, features.assign(momentum_5=features["momentum_5"] + 1), horizon=20)

    assert CONTROL_PLANE_VERSION == "ML-CONTROL-PLANE-V2.0"
    assert len(first) == 64
    assert first == second
    assert first != changed


def test_point_in_time_audit_passes_causal_frame_and_blocks_target_leakage():
    labels, features = _institutional_frames()

    accepted = point_in_time_audit(labels, features, horizon=20)
    blocked = point_in_time_audit(labels, features.assign(future_return=0.01), horizon=20)

    assert accepted["passed"] is True
    assert accepted["execution_lag_bars"] == 1
    assert accepted["purge_bars"] == 20
    assert blocked["passed"] is False
    assert blocked["forbidden_columns"] == ["future_return"]


def test_temporal_holdout_is_locked_after_full_horizon_purge():
    labels, _ = _institutional_frames()

    audit = temporal_holdout_audit(labels, horizon=20)

    assert audit["passed"] is True
    assert audit["purge_rows"] == 20
    assert audit["holdout_rows"] >= 30
    assert audit["train_rows"] >= 60
    assert audit["holdout_start"] < audit["holdout_end"]


def test_nvda_sized_research_frame_reaches_evidence_based_80_not_100():
    labels, features = _institutional_frames()

    readiness = compute_research_readiness(labels, features, horizon=20)

    assert readiness["score"] == 80
    assert readiness["status"] == "Institutional research"
    assert readiness["gates"]["Sample size"] is False
    assert readiness["gates"]["Point-in-time controls"] is True
    assert readiness["gates"]["Locked temporal holdout"] is True


def test_population_stability_index_detects_distribution_shift():
    reference = np.linspace(-2.0, 2.0, 300)
    identical = population_stability_index(reference, reference)
    shifted = population_stability_index(reference, reference + 3.0)

    assert identical == pytest.approx(0.0, abs=1e-12)
    assert shifted > 0.25


def test_calibration_and_conformal_abstention_contract():
    y = np.tile([0, 1], 50)
    calibrated = np.where(y == 1, 0.8, 0.2)

    ece = expected_calibration_error(y, calibrated)
    sets, qhat = conformal_binary_sets(y, calibrated, [0.05, 0.50, 0.95], alpha=0.10)

    assert 0.0 <= ece <= 0.21
    assert 0.0 <= qhat <= 1.0
    assert sets["Set size"].between(0, 2).all()
    assert bool(sets.loc[1, "Abstain"]) is True


def test_block_bootstrap_and_deflated_sharpe_are_deterministic():
    rng = np.random.default_rng(123)
    returns = rng.normal(0.001, 0.01, 180)

    first = block_bootstrap_sharpe_interval(returns, simulations=120, seed=7)
    second = block_bootstrap_sharpe_interval(returns, simulations=120, seed=7)
    probability = deflated_sharpe_probability(returns, trials=25)

    assert first == second
    assert first["lower"] <= first["upper"]
    assert 0.0 <= probability <= 1.0


def test_promotion_gate_requires_economic_calibration_and_drift_evidence():
    baseline = {"balanced_accuracy": 0.52, "brier": 0.25}
    eligible = {
        "oos_rows": 180,
        "balanced_accuracy": 0.56,
        "brier": 0.22,
        "ece": 0.04,
        "max_feature_psi": 0.12,
        "net_sharpe": 0.70,
        "max_drawdown": -0.12,
    }
    blocked = dict(eligible, max_feature_psi=0.40)

    assert promotion_decision(eligible, baseline)["status"] == "ELIGIBLE_FOR_SHADOW_REVIEW"
    assert promotion_decision(blocked, baseline)["status"] == "BLOCKED"


def test_local_registry_is_idempotent_and_champion_is_approval_gated(tmp_path):
    registry = LocalExperimentRegistry(tmp_path / "registry.jsonl")
    record = {
        "dataset_id": "abc",
        "promotion": {"status": "ELIGIBLE_FOR_SHADOW_REVIEW"},
    }

    first = registry.append(record)
    second = registry.append(record)

    assert first["run_id"] == second["run_id"]
    assert len(registry.list()) == 1
    with pytest.raises(PermissionError):
        registry.promote(first["run_id"], "champion")
    promoted = registry.promote(first["run_id"], "champion", approval_note="Independent validation committee")
    assert promoted["stage"] == "champion"


def test_control_report_is_json_exportable_and_contains_all_evidence():
    labels, features = _institutional_frames()
    report = build_institutional_control_report(labels, features, horizon=20)

    exported = json.loads(report_to_json(report))

    assert exported["point_in_time"]["passed"] is True
    assert exported["holdout"]["passed"] is True
    assert exported["governance"]["autonomous_trading"] is False
    assert exported["dataset_id"] == report["dataset_id"]


def test_model_matrix_quarantines_forward_targets_and_raw_price_levels():
    labels, features = _institutional_frames()
    enriched = features.assign(
        close=np.linspace(100, 120, len(features)),
        forward_return_20d=0.05,
    )

    eligible, excluded = causal_feature_frame(enriched)
    report = build_institutional_control_report(labels, enriched, horizon=20)

    assert "close" in excluded
    assert "forward_return_20d" in excluded
    assert "close" not in eligible
    assert "forward_return_20d" not in eligible
    assert report["point_in_time"]["passed"] is True
    assert report["governance"]["quarantined_feature_count"] == 2


def test_governance_json_replaces_non_finite_values_with_null():
    payload = {"metric": float("nan"), "nested": {"value": float("inf")}}

    exported = json.loads(report_to_json(payload))

    assert exported == {"metric": None, "nested": {"value": None}}
