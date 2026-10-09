from __future__ import annotations

import numpy as np
import pandas as pd

from correlation_matrix_section.correlation_intelligence_v3.covariance_lab import (
    covariance_estimate,
    factor_graphical_covariance,
)
from correlation_matrix_section.correlation_intelligence_v3.estimators import correlation_matrix
from correlation_matrix_section.correlation_intelligence_v3.precision import (
    temporal_forward_splits,
    temporal_graphical_lasso,
)


def synthetic_returns(n: int = 260, p: int = 6, seed: int = 410) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    market = rng.normal(0.0, 0.012, n)
    sector = 0.55 * market + rng.normal(0.0, 0.009, n)
    values = np.column_stack(
        [
            (0.30 + 0.08 * i) * market
            + (0.65 - 0.06 * i) * sector
            + rng.normal(0.0, 0.007 + 0.0005 * i, n)
            for i in range(p)
        ]
    )
    return pd.DataFrame(
        values,
        index=pd.bdate_range("2025-01-02", periods=n),
        columns=[f"A{i}" for i in range(p)],
    )


def assert_finite_spd(matrix: np.ndarray) -> None:
    assert np.isfinite(matrix).all()
    assert np.allclose(matrix, matrix.T, atol=1e-10)
    assert float(np.linalg.eigvalsh(matrix).min()) > 0.0


def test_temporal_splits_are_expanding_forward_only():
    splits = temporal_forward_splits(100, n_splits=4, min_train_size=52)
    assert len(splits) == 4
    previous_train_size = 0
    previous_test_end = 51
    for train, test in splits:
        assert train[0] == 0
        assert len(train) > previous_train_size
        assert train[-1] < test[0]
        assert not np.intersect1d(train, test).size
        assert test[0] == previous_test_end + 1
        previous_train_size = len(train)
        previous_test_end = int(test[-1])
    assert previous_test_end == 99


def test_temporal_graphical_lasso_is_deterministic_auditable_and_spd():
    x = synthetic_returns().to_numpy(dtype=float)
    first = temporal_graphical_lasso(x)
    second = temporal_graphical_lasso(x)

    assert np.allclose(first.covariance, second.covariance)
    assert np.allclose(first.precision, second.precision)
    assert first.metadata["alpha"] == second.metadata["alpha"]
    assert first.metadata["status"] == "ok"
    assert first.metadata["cv_scheme"] == "expanding-window forward validation"
    assert first.metadata["score"] == "out-of-sample Gaussian log-likelihood"
    assert first.metadata["fold_count"] >= 2
    assert first.metadata["no_future_leakage"] is True
    assert first.metadata["converged"] is True
    assert first.metadata["fallback"] is None
    assert first.metadata["fallback_used"] is False
    assert isinstance(first.metadata["warning_count"], int)
    assert all(fold["train_end"] < fold["test_start"] for fold in first.metadata["folds"])
    assert_finite_spd(first.covariance)
    assert_finite_spd(first.precision)


def test_partial_api_preserves_dataframe_default_and_exposes_metadata():
    returns = synthetic_returns()
    legacy = correlation_matrix(returns, 252, "Partial", 80)
    matrix, metadata = correlation_matrix(
        returns, 252, "Partial", 80, return_metadata=True
    )

    assert isinstance(legacy, pd.DataFrame)
    assert legacy.equals(matrix)
    assert metadata["estimator"] == "Partial"
    for field in ["cv_scheme", "alpha", "folds", "converged", "fallback", "warning_count"]:
        assert field in metadata
    assert metadata["no_future_leakage"] is True
    values = matrix.to_numpy(dtype=float)
    assert np.isfinite(values).all()
    assert np.allclose(values, values.T)
    assert np.allclose(np.diag(values), 1.0)
    assert metadata["psd_projection_applied"] is False
    assert metadata["portfolio_eligible"] is False
    assert "positive semidefiniteness is not required" in metadata["matrix_contract"]


def test_degenerate_case_uses_finite_explicit_fallback():
    x = np.ones((80, 5), dtype=float)
    fit = temporal_graphical_lasso(x)

    assert fit.metadata["status"] == "fallback"
    assert fit.metadata["converged"] is False
    assert fit.metadata["fallback_used"] is True
    assert fit.metadata["fallback"] == "Ledoit-Wolf covariance + SPD precision"
    assert fit.metadata["fallback_reason"] == "degenerate_feature_scale"
    assert "warnings" in fit.metadata
    assert fit.metadata["warning_count"] == len(fit.metadata["warnings"])
    assert_finite_spd(fit.covariance)
    assert_finite_spd(fit.precision)


def test_factor_glasso_uses_same_temporal_selection_and_metadata():
    returns = synthetic_returns(n=300)
    covariance, metadata = factor_graphical_covariance(returns)
    forecast = covariance_estimate(
        returns, "Factor-GLasso", days=252, min_obs=100
    )

    assert metadata["method"] == "Factor + Temporal Graphical Lasso residual"
    assert metadata["cv_scheme"] == "expanding-window forward validation"
    assert metadata["no_future_leakage"] is True
    assert metadata["alpha"] is not None
    assert metadata["fallback_used"] is False
    assert metadata["alpha_grid"] == [0.01, 0.04, 0.16, 0.64]
    assert metadata["fold_count"] == 3
    assert metadata["nested_search_policy"].startswith(
        "4 log-spaced alphas x 3 expanding forward folds"
    )
    assert metadata["max_iter"] == 150
    for field in ["cv_scheme", "alpha", "folds", "converged", "fallback", "warning_count"]:
        assert field in forecast.metadata
    assert_finite_spd(covariance.to_numpy(dtype=float))
    assert_finite_spd(forecast.covariance.to_numpy(dtype=float))
