from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from monte_carlo.heston_calibration import (
    HESTON_CALIBRATION_VERSION,
    HestonParameters,
    calibrate_heston,
    heston_call_prices,
    heston_option_prices,
)
from monte_carlo.options_risk_neutral import black_scholes_price, implied_volatility


def _synthetic_dataset() -> dict:
    spot = 100.0
    r = 0.03
    q = 0.01
    true = HestonParameters(kappa=1.8, theta=0.045, sigma_v=0.55, rho=-0.65, v0=0.05)
    rows = []
    expiries = [("2026-09-04", 30), ("2026-11-20", 107), ("2027-01-15", 163), ("2027-09-17", 408)]
    for expiration, dte in expiries:
        t = dte / 365.0
        strikes = np.arange(75.0, 126.0, 5.0)
        calls = heston_call_prices(spot, strikes, t, r, q, true, quadrature_nodes=96)
        for i, (strike, call_price) in enumerate(zip(strikes, calls)):
            option_type = "put" if strike < spot else "call"
            if option_type == "put":
                price = call_price - spot * np.exp(-q * t) + strike * np.exp(-r * t)
            else:
                price = call_price
            iv = implied_volatility(float(price), spot, float(strike), t, r, q, option_type)
            role = "HOLDOUT" if i in {2, 7} else "TRAIN"
            rows.append({
                "expiration": expiration,
                "dte": dte,
                "time_to_expiry": t,
                "strike": float(strike),
                "option_type": option_type,
                "effective_q": q,
                "target_iv": iv,
                "effective_iv": iv,
                "log_moneyness": np.log(strike / (spot * np.exp((r - q) * t))),
                "calibration_weight": 0.0,
                "vega_raw": 10.0,
                "moneyness_bucket": "ATM",
                "sample_role": role,
            })
    frame = pd.DataFrame(rows)
    train = frame[frame["sample_role"] == "TRAIN"].copy().reset_index(drop=True)
    holdout = frame[frame["sample_role"] == "HOLDOUT"].copy().reset_index(drop=True)
    train["calibration_weight"] = 1.0 / len(train)
    return {
        "ok": True,
        "status": "PASS",
        "configuration_signature": "SYNTHETIC",
        "spot": spot,
        "risk_free_rate": r,
        "training_dataset": train,
        "holdout_dataset": holdout,
    }


def test_heston_prices_are_monotone_in_strike_and_put_call_parity_holds():
    parameters = HestonParameters(2.0, 0.04, 0.5, -0.7, 0.04)
    strikes = np.array([80.0, 100.0, 120.0])
    calls = heston_call_prices(100.0, strikes, 0.5, 0.03, 0.01, parameters, quadrature_nodes=64)
    assert np.all(np.diff(calls) <= 0.0)
    prices = heston_option_prices(100.0, [100.0, 100.0], 0.5, 0.03, 0.01, ["call", "put"], parameters, 64)
    parity = prices[0] - prices[1]
    expected = 100.0 * np.exp(-0.01 * 0.5) - 100.0 * np.exp(-0.03 * 0.5)
    assert abs(parity - expected) < 1e-8


def test_heston_calibration_recovers_synthetic_surface_with_low_holdout_error():
    result = calibrate_heston(
        _synthetic_dataset(),
        multi_start=3,
        max_nfev=180,
        quadrature_nodes=48,
        feller_penalty=0.25,
        seed=11,
        numerical_crosscheck_points=3,
    )
    assert result["version"] == HESTON_CALIBRATION_VERSION
    assert result["status"] in {"PASS", "WARNING"}
    assert result["ok"] is True
    assert result["train_metrics"]["iv_rmse"] < 0.025
    assert result["holdout_metrics"]["iv_rmse"] < 0.035
    assert result["maximum_crosscheck_error"] < 1e-4
    assert len(result["multi_start_solutions"]) == 3
    assert set(["kappa", "theta", "sigma_v", "rho", "v0"]).issubset(result["parameters"])


def test_heston_calibration_is_reproducible_for_same_seed():
    first = calibrate_heston(_synthetic_dataset(), multi_start=2, max_nfev=120, quadrature_nodes=48, seed=7, numerical_crosscheck_points=0)
    second = calibrate_heston(_synthetic_dataset(), multi_start=2, max_nfev=120, quadrature_nodes=48, seed=7, numerical_crosscheck_points=0)
    for name in ("kappa", "theta", "sigma_v", "rho", "v0"):
        assert np.isclose(first["parameters"][name], second["parameters"][name])
    assert first["configuration_signature"] == second["configuration_signature"]


def test_heston_calibration_rejects_missing_dataset_metadata():
    result = calibrate_heston({"ok": True, "training_dataset": pd.DataFrame({"strike": [100.0]})})
    assert result["ok"] is False
    assert result["status"] == "FAILED"


def test_hard_feller_constraint_enforces_admissibility():
    result = calibrate_heston(
        _synthetic_dataset(),
        multi_start=2,
        max_nfev=120,
        quadrature_nodes=48,
        feller_policy="Hard Feller constraint",
        feller_penalty=0.0,
        kappa_upper_bound=20.0,
        seed=5,
        numerical_crosscheck_points=0,
        run_robustness_checks=False,
    )
    assert result["ok"] is True
    assert result["feller_ratio"] >= 0.999
    assert result["settings"]["feller_policy"] == "Hard Feller constraint"


def test_heston_robustness_and_local_error_diagnostics_are_exposed():
    result = calibrate_heston(
        _synthetic_dataset(),
        multi_start=2,
        max_nfev=100,
        quadrature_nodes=48,
        feller_policy="No penalty",
        kappa_upper_bound=12.0,
        seed=9,
        numerical_crosscheck_points=0,
        run_robustness_checks=True,
        robustness_max_nfev=40,
    )
    assert result["robustness_status"] in {"STABLE", "BOUND_SENSITIVE", "FELLER_SENSITIVE", "MIXED_SENSITIVITY", "FAILED"}
    assert isinstance(result["robustness_table"], pd.DataFrame)
    assert not result["robustness_table"].empty
    assert isinstance(result["local_error_table"], pd.DataFrame)
    assert "worst_cell_mean_abs_iv_error" in result["local_error_summary"]
    assert "relative_cost_bps" in result["multi_start_solutions"].columns


def test_kappa_upper_bound_is_governed_and_recorded():
    result = calibrate_heston(
        _synthetic_dataset(),
        multi_start=1,
        max_nfev=80,
        quadrature_nodes=48,
        kappa_upper_bound=8.0,
        run_robustness_checks=False,
        numerical_crosscheck_points=0,
    )
    assert result["bounds"]["kappa"][1] == 8.0
    assert result["parameters"]["kappa"] <= 8.0 + 1e-8
