from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pandas.testing as pdt

from correlation_matrix_section.correlation_intelligence_v3.dynamic_dependence import (
    fit_dynamic_dcc,
    fit_robust_garch,
    rolling_t_copula_diagnostics,
)
from correlation_matrix_section.correlation_intelligence_v3.covariance_lab import (
    covariance_model_validation,
)
from correlation_matrix_section.correlation_intelligence_v3.institutional_cache import InstitutionalCache
from correlation_matrix_section.correlation_intelligence_v3.market_data_adapters import (
    validate_point_in_time_contract,
)
from correlation_matrix_section.correlation_intelligence_v3.synchronization import (
    epps_effect_curve,
    hayashi_yoshida_correlation,
    hayashi_yoshida_lead_lag,
    hayashi_yoshida_matrix,
)
from correlation_matrix_section.correlation_intelligence_v3.validation_monitor import (
    ValidationLedger,
    correlation_drift_report,
    independent_validation_status,
    rolling_correlation_calibration,
)


def _dynamic_fixture(periods: int = 180, assets: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(711)
    common = rng.standard_t(7, periods) * 0.008
    values: dict[str, np.ndarray] = {}
    loadings = [1.0, 0.78, -0.34, 0.52, -0.18]
    for position in range(assets):
        values[f"A{position + 1}"] = loadings[position] * common + rng.normal(
            0.0, 0.0045 + 0.0005 * position, periods
        )
    return pd.DataFrame(values, index=pd.bdate_range("2025-01-02", periods=periods))


def test_persistent_cache_roundtrip_and_checksum_gate(tmp_path: Path) -> None:
    cache = InstitutionalCache(tmp_path / "cache", default_ttl=300, max_entries=8)
    frame = pd.DataFrame(
        {"AAA": [1.0, 2.0, 3.0], "BBB": [4.0, 5.0, 6.0]},
        index=pd.date_range("2026-01-01", periods=3, tz="UTC"),
    )

    assert cache.put_frame("daily", "frame", frame)
    read_frame = cache.get_frame("daily", "frame")
    assert read_frame.hit
    pdt.assert_frame_equal(read_frame.value, frame, check_freq=False)

    assert cache.put_object("analysis", "bundle", {"state": "governed", "score": 7})
    read_object = cache.get_object("analysis", "bundle")
    assert read_object.hit and read_object.value["state"] == "governed"

    cache_id = cache._cache_id("analysis", "bundle")
    row = cache._row(cache_id)
    assert row is not None
    payload_path = cache.root / str(row[4])
    payload_path.write_bytes(payload_path.read_bytes() + b"tamper")
    rejected = cache.get_object("analysis", "bundle")
    assert not rejected.hit
    assert rejected.reason == "checksum_mismatch"

    status = cache.status()
    assert status["catalog_backend"] in {"duckdb", "sqlite"}
    assert status["arrow_backend"] in {"ready", "fallback_pickle"}


def test_point_in_time_contract_passes_only_complete_temporal_evidence() -> None:
    frame = pd.DataFrame(
        {"AAA": [100.0, 101.0]},
        index=pd.to_datetime(["2026-01-01T21:00:00Z", "2026-01-02T21:00:00Z"]),
    )
    contract = {
        "provider": "fixture archive",
        "as_of": "2026-01-02T21:00:00Z",
        "available_at": "2026-01-02T21:05:00Z",
        "revision_policy": "append-only vintage",
        "license_scope": "internal research",
    }

    accepted = validate_point_in_time_contract(frame, contract)
    assert accepted["status"] == "ok"
    assert accepted["authoritative"] is True
    assert accepted["max_observation"] == "2026-01-02T21:00:00+00:00"

    incomplete = validate_point_in_time_contract(frame, {"provider": "fixture"})
    assert incomplete["authoritative"] is False
    assert incomplete["reason"] == "contract_incomplete"

    future_frame = frame.copy()
    future_frame.loc[pd.Timestamp("2026-01-03T21:00:00Z")] = 102.0
    rejected = validate_point_in_time_contract(future_frame, contract)
    assert rejected["authoritative"] is False
    assert rejected["reason"] == "observation_after_as_of"


def test_drift_monitor_uses_a_strictly_prior_baseline() -> None:
    rng = np.random.default_rng(19)
    baseline = rng.normal(0.0, 0.01, size=(170, 4))
    shock = rng.normal(0.0, 0.012, size=30)
    current = np.column_stack(
        [shock + rng.normal(0.0, 0.001, 30) for _ in range(4)]
    )
    changes = pd.DataFrame(
        np.vstack([baseline, current]),
        index=pd.bdate_range("2025-01-02", periods=200),
        columns=list("ABCD"),
    )

    links, metadata = correlation_drift_report(changes)
    assert metadata["status"] == "ok"
    assert metadata["no_future_leakage"] is True
    assert pd.Timestamp(metadata["baseline_end"]) < pd.Timestamp(metadata["current_start"])
    assert metadata["normalized_frobenius_shift"] > 0.5
    assert metadata["severity"] in {"elevated", "high"}
    assert not links.empty and links["Absolute shift"].is_monotonic_decreasing


def test_chronological_calibration_and_external_validation_contract() -> None:
    changes = _dynamic_fixture(periods=260, assets=3)
    ledger, metadata = rolling_correlation_calibration(
        changes, train_days=126, test_days=21, max_folds=5
    )
    assert metadata["status"] == "ok"
    assert metadata["no_future_leakage"] is True
    assert len(ledger) == metadata["folds"]
    assert (pd.to_datetime(ledger["Train end"]) < pd.to_datetime(ledger["Test start"])).all()
    assert np.isfinite(ledger["Pair RMSE"]).all()

    absent = independent_validation_status({})
    assert absent["independently_validated"] is False
    invalid = independent_validation_status(
        {"correlation_independent_validation": {"reviewer": "A", "result": "PASS"}}
    )
    assert invalid["status"] == "invalid_contract"
    valid = independent_validation_status(
        {
            "correlation_independent_validation": {
                "reviewer": "Independent Model Risk",
                "review_date": "2026-10-10",
                "scope": "Correlation Intelligence V5 numerical implementation",
                "result": "PASS_WITH_LIMITATIONS",
                "evidence_sha256": "a" * 64,
            }
        }
    )
    assert valid["status"] == "verified_contract"
    assert valid["independently_validated"] is True


def test_factor_glasso_alpha_is_selected_once_then_locked_out_of_sample() -> None:
    changes = _dynamic_fixture(periods=190, assets=3)
    _ranking, metadata = covariance_model_validation(
        changes,
        ("Factor-GLasso", "Ledoit-Wolf"),
        train_days=100,
        forecast_horizon=10,
        min_train=80,
        max_folds=4,
        champion_bootstrap_samples=500,
    )
    assert metadata["status"] == "ok"
    assert metadata["factor_glasso_alpha_no_future_leakage"] is True
    assert metadata["factor_glasso_alpha_selection_fold"] == 0
    fold_losses = metadata["fold_losses"]
    factor_folds = fold_losses[fold_losses["Model"] == "Factor-GLasso"]
    assert len(factor_folds) == 4
    assert factor_folds["Fit alpha"].nunique() == 1
    assert factor_folds["Fit alpha"].iloc[0] == metadata["factor_glasso_alpha_lock"]


def test_validation_ledger_is_idempotent(tmp_path: Path) -> None:
    ledger = ValidationLedger(tmp_path / "validation.sqlite3")
    kwargs = dict(
        ticker="AAA",
        as_of="2026-10-10T00:00:00Z",
        metrics={"drift_score": 12.5, "calibration_rmse": 0.14},
        state="normal",
        engine_version="5.0.0",
        data_hash="f" * 64,
        metadata={"authority": "RESEARCH_ONLY"},
    )
    assert ledger.append(**kwargs) == 2
    assert ledger.append(**kwargs) == 0
    history = ledger.history("AAA")
    assert len(history) == 2
    assert set(history["metric"]) == {"drift_score", "calibration_rmse"}


def test_hayashi_yoshida_matrix_lead_lag_and_epps_curve() -> None:
    rng = np.random.default_rng(77)
    observations = 120
    latent = rng.normal(0.0, 0.001, observations)
    left_index = pd.date_range("2026-10-09T13:30:00Z", periods=observations, freq="1min")
    right_index = left_index + pd.Timedelta(seconds=30)
    left = pd.Series(latent + rng.normal(0.0, 0.00015, observations), index=left_index)
    right = pd.Series(0.8 * latent + rng.normal(0.0, 0.00015, observations), index=right_index)
    asynchronous = pd.concat([left.rename("AAA"), right.rename("BBB")], axis=1, sort=False)

    matrix, audit, metadata = hayashi_yoshida_matrix(asynchronous, min_obs=60)
    assert metadata["status"] == "ok"
    assert metadata["daily_data_allowed"] is False
    assert matrix.shape == (2, 2)
    assert np.allclose(np.diag(matrix), 1.0)
    assert matrix.loc["AAA", "BBB"] > 0.5
    assert int(audit.iloc[0]["Synchronous timestamps"]) == 0

    lag_curve, lag_meta = hayashi_yoshida_lead_lag(
        left, right, lag_seconds=(-60, -30, 0, 30, 60), bootstrap_samples=19, seed=3
    )
    assert lag_meta["status"] == "ok"
    assert lag_meta["bootstrap_samples"] == 19
    assert lag_curve["Selected"].sum() == 1
    assert lag_meta["selected_lag_seconds"] in {-60, -30, 0, 30, 60}
    reference_curve = []
    for lag in lag_curve["Lag seconds"]:
        shifted = right.copy()
        shifted.index = shifted.index + pd.to_timedelta(int(lag), unit="s")
        reference_curve.append(hayashi_yoshida_correlation(left, shifted))
    assert np.allclose(lag_curve["HY correlation"], reference_curve, atol=1e-12, equal_nan=True)

    epps = epps_effect_curve(left, right, frequencies=("1min", "5min"), min_bins=3)
    assert list(epps["Aggregation"]) == ["1min", "5min"]
    assert (epps["Common bins"] >= 3).all()


def test_robust_garch_dcc_and_dynamic_t_copula_pass_numerical_gates() -> None:
    changes = _dynamic_fixture(periods=180, assets=3)

    marginal = fit_robust_garch(changes["A1"], min_obs=100, maxiter=140)
    assert marginal.metadata["status"] == "ok"
    assert marginal.metadata["finite_path"] is True
    assert marginal.parameters["alpha"] + marginal.parameters["beta"] < 0.998
    assert (marginal.conditional_variance > 0).all()

    dynamic = fit_dynamic_dcc(
        changes,
        min_obs=100,
        max_direct_assets=2,
        garch_maxiter=140,
        dcc_maxiter=120,
    )
    assert dynamic.metadata["status"] == "ok"
    assert dynamic.metadata["authority"] == "RESEARCH_ONLY"
    assert dynamic.metadata["factor_reduction_applied"] is True
    assert dynamic.metadata["alpha"] + dynamic.metadata["beta"] < 0.999
    assert dynamic.metadata["min_path_eigenvalue"] > 0
    assert dynamic.latest_correlation.shape == (3, 3)
    assert np.allclose(np.diag(dynamic.latest_correlation), 1.0)
    assert not dynamic.correlation_path.empty

    copula = rolling_t_copula_diagnostics(
        changes, "A1", "A2", window=100, step=40, min_obs=80, maxiter=120
    )
    assert copula.metadata["status"] == "ok"
    assert copula.metadata["no_future_leakage"] is True
    valid = copula.diagnostics[copula.diagnostics["converged"].astype(bool)]
    assert not valid.empty
    assert valid["Rho"].between(-0.985, 0.985).all()
    assert valid["Nu"].between(2.051, 80.0).all()
    assert valid["Lower tail dependence"].between(0.0, 1.0).all()


def test_dynamic_estimators_fail_closed_on_insufficient_data() -> None:
    short = _dynamic_fixture(periods=30, assets=2)
    marginal = fit_robust_garch(short["A1"], min_obs=100)
    dynamic = fit_dynamic_dcc(short, min_obs=100)
    copula = rolling_t_copula_diagnostics(short, "A1", "A2", min_obs=80)

    assert marginal.metadata["accepted"] is False
    assert marginal.conditional_variance.empty
    assert dynamic.metadata["accepted"] is False
    assert dynamic.latest_correlation.empty
    assert copula.metadata["accepted"] is False
    assert copula.diagnostics.empty
