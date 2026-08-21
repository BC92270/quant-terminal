from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from monte_carlo.heston_calibration import HestonParameters, heston_call_prices
from monte_carlo.heston_simulation import (
    HESTON_SIMULATION_VERSION,
    HESTON_SIMULATION_SCHEMES,
    build_heston_q_simulation,
)
from monte_carlo.options_risk_neutral import implied_volatility


def _calibration_result(status: str = "PASS") -> dict:
    spot = 100.0
    r = 0.03
    q = 0.01
    parameters = HestonParameters(kappa=1.8, theta=0.045, sigma_v=0.55, rho=-0.65, v0=0.05)
    rows = []
    for expiration, dte in (("2026-09-04", 30), ("2026-11-20", 107), ("2027-01-15", 163)):
        t = dte / 365.0
        strikes = np.arange(80.0, 121.0, 10.0)
        calls = heston_call_prices(spot, strikes, t, r, q, parameters, quadrature_nodes=96)
        for index, (strike, call_price) in enumerate(zip(strikes, calls)):
            option_type = "put" if strike < spot else "call"
            option_price = call_price - spot * np.exp(-q * t) + strike * np.exp(-r * t) if option_type == "put" else call_price
            iv = implied_volatility(float(option_price), spot, float(strike), t, r, q, option_type)
            rows.append({
                "sample_role": "HOLDOUT" if index == 1 else "TRAIN",
                "expiration": expiration,
                "dte": dte,
                "time_to_expiry": t,
                "strike": float(strike),
                "option_type": option_type,
                "effective_q": q,
                "target_price": float(option_price),
                "heston_price": float(option_price),
                "target_iv": float(iv),
                "heston_iv": float(iv),
                "log_moneyness": float(np.log(strike / (spot * np.exp((r - q) * t)))),
                "moneyness_bucket": "ATM" if abs(strike - spot) <= 10 else ("Left wing" if strike < spot else "Right wing"),
            })
    return {
        "ok": True,
        "status": status,
        "configuration_signature": "SYNTHETIC-CALIBRATION",
        "spot": spot,
        "risk_free_rate": r,
        "parameters": parameters.__dict__,
        "fit_table": pd.DataFrame(rows),
        "local_error_summary": {"worst_cell_mean_abs_iv_error": 0.0},
    }


def test_heston_q_simulation_is_reproducible_and_nested():
    first = build_heston_q_simulation(_calibration_result(), paths=1_500, steps_per_year=252, seed=7, convergence_check=False, sample_paths=4)
    second = build_heston_q_simulation(_calibration_result(), paths=1_500, steps_per_year=252, seed=7, convergence_check=False, sample_paths=4)
    assert first["version"] == HESTON_SIMULATION_VERSION
    assert first["status"] in {"PASS", "WARNING"}
    pd.testing.assert_frame_equal(first["terminal_spot_samples"], second["terminal_spot_samples"])
    assert set(first["terminal_spot_samples"].columns) == {"30", "107", "163"}
    assert first["path_quantiles"]["day"].max() >= 162.0


def test_qe_m_analytic_martingale_correction_matches_governed_forward_without_sample_rescaling():
    result = build_heston_q_simulation(_calibration_result(), paths=2_000, steps_per_year=365, seed=11, martingale_correction=True, convergence_check=False, sample_paths=0)
    assert result["settings"]["scheme"] == "Andersen QE-M"
    assert result["martingale_method"] == "Andersen analytic QE-M"
    assert np.max(np.abs(result["distribution_summary"]["forward_bias_bps"])) < 25.0
    assert np.max(np.abs(result["distribution_summary"]["forward_bias_bps"])) > 1e-8
    assert result["max_abs_pre_correction_forward_bias_bps"] >= 0.0
    assert np.isfinite(result["rms_martingale_correction_bps"])


def test_variance_is_nonnegative_and_mean_tracks_heston_expectation():
    result = build_heston_q_simulation(_calibration_result(), paths=3_000, steps_per_year=365, seed=17, convergence_check=False, sample_paths=3)
    assert (result["terminal_variance_samples"].to_numpy(dtype=float) >= 0.0).all()
    assert (result["variance_diagnostics"]["variance_p05"] >= 0.0).all()
    assert result["variance_mean_relative_rmse"] < 0.20


def test_monte_carlo_prices_are_consistent_with_fourier_prices():
    result = build_heston_q_simulation(_calibration_result(), paths=8_000, steps_per_year=365, seed=23, convergence_check=False, sample_paths=0)
    assert result["pricing_summary"]["price_rmse_pct_spot"] < 0.003
    assert result["pricing_summary"]["iv_rmse"] < 0.03
    assert result["pricing_summary"]["confidence_coverage"] >= 0.60


def test_full_truncation_challenger_runs_and_produces_finite_outputs():
    result = build_heston_q_simulation(
        _calibration_result(),
        paths=1_500,
        steps_per_year=365,
        scheme="Full truncation Euler",
        seed=31,
        convergence_check=False,
        sample_paths=0,
    )
    assert result["settings"]["scheme"] in HESTON_SIMULATION_SCHEMES
    assert np.isfinite(result["distribution_summary"]["terminal_mean"]).all()
    assert np.isfinite(result["pricing_validation"]["mc_price"]).all()


def test_convergence_audit_exposes_multiple_time_grids():
    result = build_heston_q_simulation(
        _calibration_result(),
        paths=1_000,
        steps_per_year=252,
        seed=37,
        convergence_check=True,
        convergence_paths=500,
        sample_paths=0,
    )
    assert len(result["convergence"]) >= 2
    assert set(["steps_per_year", "price_rmse_mean", "price_rmse_ci_low", "price_rmse_ci_high", "replications"]).issubset(result["convergence"].columns)
    assert result["convergence_diagnostic"]["status"] in {"CONVERGED", "IMPROVING_NON_MONOTONIC", "INCONCLUSIVE_MC_NOISE", "NOT_CONVERGED"}
    assert len(result["convergence_replications_raw"]) >= len(result["convergence"])


def test_heston_q_simulation_rejects_missing_calibration():
    result = build_heston_q_simulation({"ok": False})
    assert result["ok"] is False
    assert result["status"] == "FAILED"


def test_legacy_qe_label_is_migrated_to_andersen_qe_m():
    result = build_heston_q_simulation(
        _calibration_result(),
        paths=1_000,
        steps_per_year=252,
        scheme="QE variance + log-Euler spot",
        seed=41,
        convergence_check=False,
        sample_paths=0,
    )
    assert result["ok"] is True
    assert result["settings"]["scheme"] == "Andersen QE-M"


def test_uncorrected_qe_is_available_as_explicit_challenger():
    result = build_heston_q_simulation(
        _calibration_result(),
        paths=1_500,
        steps_per_year=252,
        scheme="Andersen QE (uncorrected)",
        seed=43,
        convergence_check=False,
        sample_paths=0,
    )
    assert result["settings"]["scheme"] == "Andersen QE (uncorrected)"
    assert result["martingale_method"] == "None"
    assert np.isfinite(result["pricing_validation"]["mc_price"]).all()
