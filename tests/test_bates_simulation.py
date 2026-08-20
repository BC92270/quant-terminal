from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from monte_carlo.bates_calibration import BatesParameters, bates_call_prices
from monte_carlo.bates_simulation import BATES_SIMULATION_VERSION, build_bates_q_simulation
from monte_carlo.heston_calibration import HestonParameters, heston_call_prices
from monte_carlo.options_risk_neutral import implied_volatility


def _calibration_results(jump_intensity: float = 0.8) -> tuple[dict, dict]:
    spot = 100.0
    r = 0.03
    q = 0.01
    bates = BatesParameters(
        kappa=2.0,
        theta=0.045,
        sigma_v=0.55,
        rho=-0.60,
        v0=0.05,
        jump_intensity=jump_intensity,
        jump_mean=-0.08,
        jump_volatility=0.16,
    )
    heston = HestonParameters(
        kappa=bates.kappa,
        theta=bates.theta,
        sigma_v=bates.sigma_v,
        rho=bates.rho,
        v0=bates.v0,
    )
    bates_rows = []
    heston_rows = []
    for expiration, dte in (("2026-09-04", 30), ("2026-11-20", 107), ("2027-01-15", 163)):
        t = dte / 365.0
        strikes = np.arange(85.0, 116.0, 10.0)
        b_calls = bates_call_prices(spot, strikes, t, r, q, bates, quadrature_nodes=96)
        h_calls = heston_call_prices(spot, strikes, t, r, q, heston, quadrature_nodes=96)
        for index, strike in enumerate(strikes):
            option_type = "put" if strike < spot else "call"
            b_price = float(b_calls[index])
            h_price = float(h_calls[index])
            if option_type == "put":
                parity = spot * np.exp(-q * t) - strike * np.exp(-r * t)
                b_price -= parity
                h_price -= parity
            b_iv = implied_volatility(b_price, spot, float(strike), t, r, q, option_type)
            h_iv = implied_volatility(h_price, spot, float(strike), t, r, q, option_type)
            log_m = float(np.log(strike / (spot * np.exp((r - q) * t))))
            bucket = "ATM" if abs(log_m) <= 0.08 else ("Left wing" if log_m < 0 else "Right wing")
            role = "HOLDOUT" if index == 1 else "TRAIN"
            common = {
                "sample_role": role,
                "expiration": expiration,
                "dte": dte,
                "time_to_expiry": t,
                "strike": float(strike),
                "option_type": option_type,
                "effective_q": q,
                "log_moneyness": log_m,
                "moneyness_bucket": bucket,
            }
            bates_rows.append({
                **common,
                "target_price": b_price,
                "bates_price": b_price,
                "target_iv": b_iv,
                "bates_iv": b_iv,
            })
            heston_rows.append({
                **common,
                "target_price": h_price,
                "heston_price": h_price,
                "target_iv": h_iv,
                "heston_iv": h_iv,
            })
    heston_result = {
        "ok": True,
        "status": "WARNING",
        "configuration_signature": "SYNTHETIC-HESTON",
        "spot": spot,
        "risk_free_rate": r,
        "parameters": heston.__dict__,
        "fit_table": pd.DataFrame(heston_rows),
        "local_error_summary": {"worst_cell_mean_abs_iv_error": 0.0},
    }
    bates_result = {
        "ok": True,
        "status": "PASS",
        "champion_status": "BATES_CHAMPION",
        "configuration_signature": "SYNTHETIC-BATES",
        "heston_signature": "SYNTHETIC-HESTON",
        "spot": spot,
        "risk_free_rate": r,
        "parameters": bates.__dict__,
        "fit_table": pd.DataFrame(bates_rows),
    }
    return bates_result, heston_result


def test_bates_q_simulation_is_reproducible_and_nested():
    bates, heston = _calibration_results()
    first = build_bates_q_simulation(
        bates,
        heston,
        paths=1_500,
        steps_per_year=252,
        seed=7,
        time_convergence_check=False,
        path_convergence_check=False,
        sample_paths=4,
    )
    second = build_bates_q_simulation(
        bates,
        heston,
        paths=1_500,
        steps_per_year=252,
        seed=7,
        time_convergence_check=False,
        path_convergence_check=False,
        sample_paths=4,
    )
    assert first["version"] == BATES_SIMULATION_VERSION
    assert first["status"] in {"PASS", "WARNING"}
    pd.testing.assert_frame_equal(first["terminal_spot_samples"], second["terminal_spot_samples"])
    pd.testing.assert_frame_equal(first["jump_count_samples"], second["jump_count_samples"])
    assert set(first["terminal_spot_samples"].columns) == {"30", "107", "163"}


def test_zero_jump_bates_matches_heston_common_random_numbers():
    bates, heston = _calibration_results(jump_intensity=0.0)
    result = build_bates_q_simulation(
        bates,
        heston,
        paths=2_000,
        steps_per_year=365,
        seed=11,
        time_convergence_check=False,
        path_convergence_check=False,
        sample_paths=0,
        simulate_heston_benchmark=True,
    )
    assert result["heston_terminal_samples"].shape == result["terminal_spot_samples"].shape
    np.testing.assert_allclose(
        result["terminal_spot_samples"].to_numpy(dtype=float),
        result["heston_terminal_samples"].to_numpy(dtype=float),
        rtol=0.0,
        atol=1e-11,
    )
    assert result["jump_count_samples"].to_numpy(dtype=float).max() == 0.0


def test_jump_count_matches_poisson_intensity_within_sampling_noise():
    bates, heston = _calibration_results(jump_intensity=1.2)
    result = build_bates_q_simulation(
        bates,
        heston,
        paths=8_000,
        steps_per_year=252,
        seed=17,
        time_convergence_check=False,
        path_convergence_check=False,
        sample_paths=0,
    )
    summary = result["jump_count_summary"]
    assert np.max(np.abs(summary["jump_count_z"].to_numpy(dtype=float))) < 4.0
    assert (summary["probability_at_least_one_jump"] > 0.0).all()


def test_bates_monte_carlo_prices_are_consistent_with_fourier():
    bates, heston = _calibration_results(jump_intensity=0.7)
    result = build_bates_q_simulation(
        bates,
        heston,
        paths=10_000,
        steps_per_year=365,
        seed=23,
        time_convergence_check=False,
        path_convergence_check=False,
        sample_paths=0,
    )
    assert result["pricing_summary"]["price_rmse_pct_spot"] < 0.006
    assert result["pricing_summary"]["iv_rmse"] < 0.04
    assert result["pricing_summary"]["confidence_coverage"] >= 0.50


def test_forward_bias_has_sampling_uncertainty_and_jump_attribution():
    bates, heston = _calibration_results(jump_intensity=0.9)
    result = build_bates_q_simulation(
        bates,
        heston,
        paths=3_000,
        steps_per_year=365,
        seed=29,
        time_convergence_check=False,
        path_convergence_check=False,
        sample_paths=0,
    )
    required = {
        "forward_bias_bps",
        "forward_bias_se_bps",
        "forward_bias_z",
        "forward_bias_ci_low_bps",
        "forward_bias_ci_high_bps",
    }
    assert required.issubset(result["distribution_summary"].columns)
    assert np.isfinite(result["distribution_summary"]["forward_bias_z"]).all()
    assert not result["jump_attribution"].empty
    assert "jump_es_5_contribution" in result["jump_attribution"]


def test_replicated_time_and_path_convergence_tables_are_exposed():
    bates, heston = _calibration_results(jump_intensity=0.4)
    result = build_bates_q_simulation(
        bates,
        heston,
        paths=1_000,
        steps_per_year=182,
        seed=37,
        time_convergence_check=True,
        convergence_paths=500,
        convergence_replications=2,
        path_convergence_check=True,
        path_convergence_base_paths=1_000,
        path_convergence_replications=2,
        sample_paths=0,
    )
    assert len(result["time_convergence"]) >= 2
    assert len(result["path_convergence"]) >= 2
    assert result["time_convergence_diagnostic"]["status"] in {
        "CONVERGED", "IMPROVING_NON_MONOTONIC", "INCONCLUSIVE_MC_NOISE", "NOT_CONVERGED"
    }
    assert result["path_convergence_diagnostic"]["status"] in {
        "PRECISION_CONVERGED", "IMPROVING_NON_MONOTONIC", "INCONCLUSIVE_MC_NOISE", "NOT_CONVERGED"
    }


def test_bates_q_simulation_rejects_missing_calibration():
    result = build_bates_q_simulation({"ok": False})
    assert result["ok"] is False
    assert result["status"] == "FAILED"


def test_low_vega_iv_residuals_are_separated_from_price_failures():
    from monte_carlo.bates_simulation import _classify_iv_residuals

    source = pd.DataFrame(
        [
            {
                "mc_fourier_iv_error": 0.0365,
                "mc_fourier_z_score": 0.40,
                "fourier_inside_mc_ci": True,
                "vega_per_iv_point": 0.001,
            },
            {
                "mc_fourier_iv_error": 0.0040,
                "mc_fourier_z_score": 0.30,
                "fourier_inside_mc_ci": True,
                "vega_per_iv_point": 0.10,
            },
            {
                "mc_fourier_iv_error": 0.0200,
                "mc_fourier_z_score": 3.20,
                "fourier_inside_mc_ci": False,
                "vega_per_iv_point": 0.10,
            },
        ]
    )
    classified, summary = _classify_iv_residuals(source, 0.95)
    assert classified.loc[0, "iv_residual_diagnostic"] == "LOW_VEGA_IV_AMPLIFICATION"
    assert classified.loc[1, "iv_residual_diagnostic"] == "PASS"
    assert classified.loc[2, "iv_residual_diagnostic"] == "PRICE_ERROR_STATISTICALLY_SIGNIFICANT"
    assert summary["low_vega_amplification_count"] == 1
    assert summary["statistically_significant_price_error_count"] == 1
    assert summary["max_abs_iv_error_pp"] == 3.65


def test_source_champion_reason_uses_governed_notes():
    from monte_carlo.bates_simulation import _source_champion_reason

    calibration = {
        "champion_status": "BATES_RESEARCH_ONLY",
        "champion_notes": [
            "Holdout improvement is below the required threshold.",
            "Jump parameters remain weakly identified.",
        ],
    }
    reason = _source_champion_reason(calibration)
    assert "Holdout improvement" in reason
    assert "weakly identified" in reason


def test_bates_simulation_propagates_source_model_role_and_reason():
    bates, heston = _calibration_results(jump_intensity=0.4)
    bates["champion_status"] = "BATES_RESEARCH_ONLY"
    bates["champion_notes"] = ["Pseudo-BIC improvement is insufficient after complexity penalty."]
    result = build_bates_q_simulation(
        bates,
        heston,
        paths=1_000,
        steps_per_year=182,
        seed=41,
        time_convergence_check=False,
        path_convergence_check=False,
        sample_paths=0,
    )
    assert result["bates_champion_status"] == "BATES_RESEARCH_ONLY"
    assert "Pseudo-BIC" in result["bates_champion_reason"]
    assert any("challenger/research output" in warning for warning in result["warnings"])
    assert "iv_residual_diagnostic" in result["pricing_validation"].columns
    assert "vega_per_iv_point" in result["pricing_validation"].columns
