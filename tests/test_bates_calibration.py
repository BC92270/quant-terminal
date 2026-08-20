from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from monte_carlo.bates_calibration import (
    BATES_CALIBRATION_VERSION,
    BatesCalibrationSettings,
    BatesParameters,
    _champion_decision,
    _other_maturity_degradation_diagnostics,
    bates_call_prices,
    bates_option_prices,
    calibrate_bates,
)
from monte_carlo.heston_calibration import HestonParameters, calibrate_heston, heston_call_prices
from monte_carlo.options_risk_neutral import implied_volatility


def _synthetic_bates_dataset() -> dict:
    spot = 100.0
    r = 0.03
    q = 0.01
    true = BatesParameters(
        kappa=2.1,
        theta=0.045,
        sigma_v=0.58,
        rho=-0.62,
        v0=0.05,
        jump_intensity=1.4,
        jump_mean=-0.09,
        jump_volatility=0.16,
    )
    rows = []
    expiries = [("2026-09-04", 30), ("2026-11-20", 107), ("2027-01-15", 163), ("2027-09-17", 408)]
    for expiration, dte in expiries:
        t = dte / 365.0
        strikes = np.arange(80.0, 121.0, 5.0)
        calls = bates_call_prices(spot, strikes, t, r, q, true, quadrature_nodes=96)
        for i, (strike, call_price) in enumerate(zip(strikes, calls)):
            option_type = "put" if strike < spot else "call"
            price = call_price - spot * np.exp(-q * t) + strike * np.exp(-r * t) if option_type == "put" else call_price
            iv = implied_volatility(float(price), spot, float(strike), t, r, q, option_type)
            role = "HOLDOUT" if i in {1, 6} else "TRAIN"
            log_m = np.log(strike / (spot * np.exp((r - q) * t)))
            if log_m < -0.20:
                bucket = "Left wing"
            elif log_m < -0.08:
                bucket = "Put shoulder"
            elif log_m <= 0.08:
                bucket = "ATM"
            elif log_m <= 0.20:
                bucket = "Call shoulder"
            else:
                bucket = "Right wing"
            rows.append({
                "expiration": expiration,
                "dte": dte,
                "time_to_expiry": t,
                "strike": float(strike),
                "option_type": option_type,
                "effective_q": q,
                "target_iv": iv,
                "effective_iv": iv,
                "log_moneyness": log_m,
                "calibration_weight": 0.0,
                "vega_raw": 10.0,
                "moneyness_bucket": bucket,
                "sample_role": role,
            })
    frame = pd.DataFrame(rows)
    train = frame[frame["sample_role"] == "TRAIN"].copy().reset_index(drop=True)
    holdout = frame[frame["sample_role"] == "HOLDOUT"].copy().reset_index(drop=True)
    train["calibration_weight"] = 1.0 / len(train)
    return {
        "ok": True,
        "status": "PASS",
        "configuration_signature": "SYNTHETIC_BATES",
        "spot": spot,
        "risk_free_rate": r,
        "training_dataset": train,
        "holdout_dataset": holdout,
    }


def _heston_benchmark(dataset: dict) -> dict:
    return calibrate_heston(
        dataset,
        multi_start=2,
        max_nfev=100,
        quadrature_nodes=48,
        seed=17,
        numerical_crosscheck_points=0,
        run_robustness_checks=False,
    )


def test_bates_prices_are_monotone_and_put_call_parity_holds():
    p = BatesParameters(2.0, 0.04, 0.5, -0.7, 0.04, 1.0, -0.08, 0.15)
    strikes = np.array([80.0, 100.0, 120.0])
    calls = bates_call_prices(100.0, strikes, 0.5, 0.03, 0.01, p, 64)
    assert np.all(np.diff(calls) <= 0.0)
    prices = bates_option_prices(100.0, [100.0, 100.0], 0.5, 0.03, 0.01, ["call", "put"], p, 64)
    expected = 100.0 * np.exp(-0.01 * 0.5) - 100.0 * np.exp(-0.03 * 0.5)
    assert abs((prices[0] - prices[1]) - expected) < 1e-8


def test_zero_jump_bates_matches_heston_prices():
    h = HestonParameters(2.0, 0.04, 0.5, -0.7, 0.04)
    b = BatesParameters(2.0, 0.04, 0.5, -0.7, 0.04, 0.0, -0.08, 0.15)
    strikes = np.arange(80.0, 125.0, 5.0)
    hp = heston_call_prices(100.0, strikes, 0.75, 0.03, 0.01, h, 64)
    bp = bates_call_prices(100.0, strikes, 0.75, 0.03, 0.01, b, 64)
    assert np.allclose(hp, bp, atol=1e-10)


def test_bates_calibration_exposes_champion_challenger_and_low_synthetic_error():
    dataset = _synthetic_bates_dataset()
    heston = _heston_benchmark(dataset)
    result = calibrate_bates(
        dataset,
        heston,
        multi_start=3,
        max_nfev=140,
        quadrature_nodes=48,
        seed=23,
        numerical_crosscheck_points=2,
        require_bic_improvement=False,
    )
    assert result["version"] == BATES_CALIBRATION_VERSION
    assert result["ok"] is True
    assert result["status"] in {"PASS", "WARNING"}
    assert result["champion_status"] in {
        "HESTON_CHAMPION",
        "BATES_CHAMPION",
        "BATES_RESEARCH_ONLY",
        "INCONCLUSIVE",
    }
    assert result["train_metrics"]["iv_rmse"] < 0.035
    assert result["holdout_metrics"]["iv_rmse"] < 0.05
    assert len(result["multi_start_solutions"]) == 3
    assert set(["jump_intensity", "jump_mean", "jump_volatility"]).issubset(result["parameters"])
    assert len(result["comparison_table"]) == 2
    assert isinstance(result["champion_gate_table"], pd.DataFrame)
    assert "Other-maturity absolute degradation" in set(result["champion_gate_table"]["gate"])


def test_bates_calibration_requires_heston_benchmark():
    result = calibrate_bates(_synthetic_bates_dataset(), {})
    assert result["ok"] is False
    assert result["champion_status"] == "BATES_REJECTED"


def test_true_bates_surface_promotes_bates_after_complexity_gate():
    dataset = _synthetic_bates_dataset()
    heston = _heston_benchmark(dataset)
    result = calibrate_bates(
        dataset,
        heston,
        multi_start=2,
        max_nfev=140,
        quadrature_nodes=48,
        seed=23,
        numerical_crosscheck_points=0,
        require_bic_improvement=True,
    )
    assert result["champion_status"] == "BATES_CHAMPION"
    assert result["champion_comparison"]["holdout_improvement"] > 0.10
    assert result["champion_comparison"]["front_wing_improvement"] > 0.20
    assert result["champion_comparison"]["bic_delta_heston_minus_bates"] > 0.0


def test_other_maturity_gate_uses_holdout_and_reports_absolute_change():
    heston = {
        "maturity_errors": pd.DataFrame(
            [
                {"sample_role": "TRAIN", "expiration": "E1", "dte": 16, "count": 10, "iv_rmse": 0.010},
                {"sample_role": "TRAIN", "expiration": "E2", "dte": 30, "count": 10, "iv_rmse": 0.001},
                {"sample_role": "HOLDOUT", "expiration": "E1", "dte": 16, "count": 4, "iv_rmse": 0.020},
                {"sample_role": "HOLDOUT", "expiration": "E2", "dte": 30, "count": 4, "iv_rmse": 0.0135},
                {"sample_role": "HOLDOUT", "expiration": "E3", "dte": 72, "count": 4, "iv_rmse": 0.0080},
            ]
        )
    }
    bates = pd.DataFrame(
        [
            {"sample_role": "TRAIN", "expiration": "E1", "dte": 16, "count": 10, "iv_rmse": 0.008},
            {"sample_role": "TRAIN", "expiration": "E2", "dte": 30, "count": 10, "iv_rmse": 0.010},
            {"sample_role": "HOLDOUT", "expiration": "E1", "dte": 16, "count": 4, "iv_rmse": 0.006},
            {"sample_role": "HOLDOUT", "expiration": "E2", "dte": 30, "count": 4, "iv_rmse": 0.0163},
            {"sample_role": "HOLDOUT", "expiration": "E3", "dte": 72, "count": 4, "iv_rmse": 0.0060},
        ]
    )
    diagnostics = _other_maturity_degradation_diagnostics(heston, bates)
    assert diagnostics["sample_role"] == "HOLDOUT"
    assert np.isclose(diagnostics["maximum_relative_degradation"], (0.0163 - 0.0135) / 0.0135)
    assert np.isclose(diagnostics["maximum_absolute_degradation"], 0.0028)
    assert set(diagnostics["comparison_table"]["expiration"]) == {"E2", "E3"}


def test_champion_gate_allows_small_absolute_nonfront_deterioration():
    fit_h = pd.DataFrame(
        [
            {"sample_role": "TRAIN", "iv_error": value, "dte": 16, "moneyness_bucket": bucket}
            for value, bucket in [(-0.05, "Left wing"), (0.05, "Right wing"), (0.0, "ATM")]
        ]
        + [
            {"sample_role": "HOLDOUT", "iv_error": value, "dte": 16, "moneyness_bucket": bucket}
            for value, bucket in [(-0.05, "Left wing"), (0.05, "Right wing")]
        ]
    )
    fit_b = pd.DataFrame(
        [
            {"sample_role": "TRAIN", "iv_error": value, "dte": 16, "moneyness_bucket": bucket}
            for value, bucket in [(-0.01, "Left wing"), (0.01, "Right wing"), (0.0, "ATM")]
        ]
        + [
            {"sample_role": "HOLDOUT", "iv_error": value, "dte": 16, "moneyness_bucket": bucket}
            for value, bucket in [(-0.01, "Left wing"), (0.01, "Right wing")]
        ]
    )
    heston = {
        "ok": True,
        "status": "WARNING",
        "train_metrics": {"iv_rmse": 0.010},
        "holdout_metrics": {"iv_rmse": 0.0157},
        "fit_table": fit_h,
    }
    bates = {
        "ok": True,
        "status": "PASS",
        "train_metrics": {"iv_rmse": 0.0071},
        "holdout_metrics": {"iv_rmse": 0.0090},
        "front_wing_iv_rmse": 0.011,
        "fit_table": fit_b,
        "other_maturity_degradation": {
            "sample_role": "HOLDOUT",
            "maximum_relative_degradation": 0.207,
            "maximum_absolute_degradation": 0.0028,
            "weighted_mean_relative_degradation": -0.05,
            "weighted_mean_absolute_degradation": -0.001,
        },
        "parameters": {"jump_intensity": 0.333, "jump_mean": -0.137, "jump_volatility": 0.293},
        "solution_stability": {"jump_maximum_normalized_range": 0.0},
        "warnings": [],
    }
    settings = BatesCalibrationSettings(
        minimum_holdout_improvement=0.10,
        minimum_front_wing_improvement=0.20,
        maximum_other_maturity_degradation=0.15,
        maximum_other_maturity_absolute_degradation=0.0035,
        require_bic_improvement=False,
    )
    status, metrics, notes, gate_table = _champion_decision(heston, bates, settings)
    assert status == "BATES_CHAMPION"
    assert metrics["controlled_elsewhere"] is True
    rel_gate = gate_table[gate_table["gate"] == "Other-maturity relative degradation"].iloc[0]
    abs_gate = gate_table[gate_table["gate"] == "Other-maturity absolute degradation"].iloc[0]
    assert bool(rel_gate["passed"]) is False
    assert bool(abs_gate["passed"]) is True
    assert notes
