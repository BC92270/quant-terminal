from __future__ import annotations

import numpy as np
import pandas as pd

import correlation_matrix_section.correlation_intelligence_v3.connectedness as connectedness


def _stable_var_returns(n: int = 420, seed: int = 410) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    coefficients = np.array([
        [0.28, 0.10, 0.00],
        [0.00, 0.22, 0.12],
        [0.06, 0.00, 0.18],
    ])
    covariance = np.array([
        [1.0, 0.25, 0.10],
        [0.25, 1.0, 0.18],
        [0.10, 0.18, 1.0],
    ]) * 1e-4
    chol = np.linalg.cholesky(covariance)
    values = np.zeros((n, 3))
    for idx in range(1, n):
        values[idx] = coefficients @ values[idx - 1] + chol @ rng.normal(size=3)
    return pd.DataFrame(values[50:], columns=["A", "B", "C"])


class _ExplicitlyUnstableFit:
    bic = 0.0
    sigma_u = np.eye(3)
    coefs = np.zeros((1, 3, 3))
    resid = pd.DataFrame(np.ones((140, 3)), columns=["A", "B", "C"])

    def is_stable(self, verbose: bool = False) -> bool:
        return False


class _ExplicitlyUnstableVAR:
    def __init__(self, data: pd.DataFrame):
        self.data = data

    def fit(self, lag: int, trend: str = "c") -> _ExplicitlyUnstableFit:
        return _ExplicitlyUnstableFit()


class _UnverifiedStabilityFit(_ExplicitlyUnstableFit):
    resid = _stable_var_returns(n=240).reset_index(drop=True)

    def is_stable(self, verbose: bool = False) -> bool:
        raise RuntimeError("diagnostic unavailable")


class _UnverifiedStabilityVAR(_ExplicitlyUnstableVAR):
    def fit(self, lag: int, trend: str = "c") -> _UnverifiedStabilityFit:
        return _UnverifiedStabilityFit()


def test_time_connectedness_stable_var_is_normalized_and_audited():
    matrix, directional, meta = connectedness.generalized_fevd(
        _stable_var_returns(), horizon=20, maxlags=2, min_obs=100,
    )

    assert meta["status"] == "ok"
    assert meta["authoritative"] is True
    assert meta["VAR stable"] is True
    assert meta["fit_diagnostics_ok"] is True
    assert meta["fevd_checks_pass"] is True
    assert meta["fevd_finite"] is True
    assert meta["fevd_rows_normalized"] is True
    assert meta["residual_covariance_condition"] >= 1.0
    assert 0.0 <= meta["residual_ljung_box_min_pvalue"] <= 1.0
    assert 0.0 <= meta["residual_portmanteau_pvalue"] <= 1.0
    assert meta["residual_portmanteau_adjusted"] is True
    assert meta["residual_whiteness_pass_5pct"] is True
    assert meta["lag_selection_status"] == "admissible_candidate_selected"
    assert meta["admissible_lag_count"] >= 1
    selected = next(row for row in meta["lag_candidates"] if row["lag"] == meta["VAR lag"])
    assert selected["admissible"] is True
    assert set(meta["residual_ljung_box_pvalues"]) == {"A", "B", "C"}
    assert np.allclose(matrix.sum(axis=1).to_numpy(), 100.0, atol=1e-6)
    assert not directional.empty


def test_spectral_connectedness_stable_var_is_normalized_and_audited():
    bands, directional, meta = connectedness.spectral_connectedness(
        _stable_var_returns(), maxlags=2, min_obs=100, n_freq=128,
    )

    assert meta["status"] == "ok"
    assert meta["authoritative"] is True
    assert meta["VAR stable"] is True
    assert meta["spectral_fevd_checks_pass"] is True
    assert meta["spectral_fevd_rows_normalized"] is True
    assert meta["spectral_band_values_finite"] is True
    assert meta["spectral_total_tci_bounded"] is True
    assert abs(float(meta["spectral_fevd_row_sum_max_error"])) < 1e-6
    assert not bands.empty and not directional.empty


def test_explicitly_unstable_var_is_fail_closed_in_both_paths(monkeypatch):
    monkeypatch.setattr(connectedness, "VAR", _ExplicitlyUnstableVAR)
    data = _stable_var_returns(n=240)

    time_matrix, time_table, time_meta = connectedness.generalized_fevd(
        data, horizon=10, maxlags=1, min_obs=100,
    )
    spectral_bands, spectral_table, spectral_meta = connectedness.spectral_connectedness(
        data, maxlags=1, min_obs=100, n_freq=64,
    )

    for first, second, meta in (
        (time_matrix, time_table, time_meta),
        (spectral_bands, spectral_table, spectral_meta),
    ):
        assert first.empty and second.empty
        assert meta["status"] == "unstable_var"
        assert meta["authoritative"] is False
        assert meta["VAR stable"] is False
        assert "TCI" not in meta
        assert "suppressed" in meta["non_authoritative_reason"]


def test_unavailable_stability_diagnostic_is_also_fail_closed(monkeypatch):
    monkeypatch.setattr(connectedness, "VAR", _UnverifiedStabilityVAR)
    data = _stable_var_returns(n=240)

    for fn in (connectedness.generalized_fevd, connectedness.spectral_connectedness):
        first, second, meta = fn(data, maxlags=1, min_obs=100)
        assert first.empty and second.empty
        assert meta["status"] == "stability_unverified"
        assert meta["authoritative"] is False
        assert meta["VAR stable"] is None
        assert "stability_check_unavailable" in meta["diagnostic_warnings"]


def test_small_or_degenerate_samples_return_metadata_without_raising():
    tiny = pd.DataFrame({"A": [0.0, 0.1], "B": [0.0, 0.2]})
    for fn in (connectedness.generalized_fevd, connectedness.spectral_connectedness):
        first, second, meta = fn(tiny, min_obs=20)
        assert first.empty and second.empty
        assert meta["status"] == "insufficient_data"

    degenerate = pd.DataFrame({"A": np.ones(140), "B": np.ones(140)})
    for fn in (connectedness.generalized_fevd, connectedness.spectral_connectedness):
        first, second, meta = fn(degenerate, min_obs=100)
        assert first.empty and second.empty
        assert meta["status"] == "insufficient_data"
