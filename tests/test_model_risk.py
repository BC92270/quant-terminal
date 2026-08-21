from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from monte_carlo.bates_calibration import BatesParameters, bates_call_prices, calibrate_bates
from monte_carlo.heston_calibration import calibrate_heston
from monte_carlo.model_risk import (
    MODEL_RISK_STATUSES,
    MODEL_RISK_VERSION,
    build_model_risk_governance,
)
from monte_carlo.options_risk_neutral import implied_volatility


def _dataset() -> dict:
    spot = 100.0
    r = 0.03
    q = 0.01
    true = BatesParameters(2.1, 0.045, 0.58, -0.62, 0.05, 1.4, -0.09, 0.16)
    rows = []
    for expiration, dte in [("E1", 30), ("E2", 90), ("E3", 180), ("E4", 360)]:
        t = dte / 365.0
        strikes = np.arange(80.0, 121.0, 10.0)
        calls = bates_call_prices(spot, strikes, t, r, q, true, quadrature_nodes=48)
        for index, (strike, call_price) in enumerate(zip(strikes, calls)):
            option_type = "put" if strike < spot else "call"
            price = call_price - spot * np.exp(-q * t) + strike * np.exp(-r * t) if option_type == "put" else call_price
            iv = implied_volatility(float(price), spot, float(strike), t, r, q, option_type)
            log_m = np.log(strike / (spot * np.exp((r - q) * t)))
            bucket = (
                "Left wing" if log_m < -0.20 else
                "Put shoulder" if log_m < -0.08 else
                "ATM" if log_m <= 0.08 else
                "Call shoulder" if log_m <= 0.20 else
                "Right wing"
            )
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
                "sample_role": "HOLDOUT" if index == 1 else "TRAIN",
            })
    frame = pd.DataFrame(rows)
    train = frame[frame["sample_role"] == "TRAIN"].copy().reset_index(drop=True)
    holdout = frame[frame["sample_role"] == "HOLDOUT"].copy().reset_index(drop=True)
    train["calibration_weight"] = 1.0 / len(train)
    return {
        "ok": True,
        "status": "PASS",
        "configuration_signature": "MODEL_RISK_SYNTHETIC",
        "spot": spot,
        "risk_free_rate": r,
        "training_dataset": train,
        "holdout_dataset": holdout,
    }


@lru_cache(maxsize=1)
def _source_results():
    dataset = _dataset()
    heston = calibrate_heston(
        dataset,
        multi_start=1,
        max_nfev=40,
        quadrature_nodes=32,
        numerical_crosscheck_points=0,
        run_robustness_checks=False,
    )
    bates = calibrate_bates(
        dataset,
        heston,
        multi_start=1,
        max_nfev=50,
        quadrature_nodes=32,
        numerical_crosscheck_points=0,
        require_bic_improvement=False,
    )
    return dataset, heston, bates


def _run(seed: int = 17):
    dataset, heston, bates = _source_results()
    return build_model_risk_governance(
        dataset,
        heston,
        bates,
        bootstrap_draws=3,
        max_nfev_per_draw=25,
        quadrature_nodes=32,
        seed=seed,
        profile_grid_points=3,
        run_maturity_jackknife=True,
        minimum_bootstrap_success_rate=0.50,
    )


def test_model_risk_governance_builds_all_institutional_audits():
    result = _run()
    assert result["version"] == MODEL_RISK_VERSION
    assert result["status"] in MODEL_RISK_STATUSES
    assert result["ok"] is True
    assert len(result["bootstrap_draws"]) == 3
    assert set(result["parameter_intervals"]["model"]) == {"Heston", "Bates"}
    assert set(result["identifiability_summary"]["model"]) == {"Heston", "Bates"}
    assert not result["parameter_correlations"].empty
    assert not result["cost_profiles"].empty
    assert not result["maturity_sensitivity"].empty
    assert "Source champion decision" in set(result["gate_table"]["gate"])
    assert result["model_card"]["final_status"] == result["status"]
    assert result["bootstrap_summary"]["bates_success_rate"] >= 2 / 3


def test_model_risk_governance_is_reproducible_for_same_seed():
    first = _run(seed=29)
    second = _run(seed=29)
    columns = ["heston_kappa", "bates_jump_intensity", "holdout_improvement", "bates_selected"]
    pd.testing.assert_frame_equal(
        first["bootstrap_draws"][columns].reset_index(drop=True),
        second["bootstrap_draws"][columns].reset_index(drop=True),
        check_exact=False,
        rtol=1e-10,
        atol=1e-12,
    )
    assert first["configuration_signature"] == second["configuration_signature"]


def test_model_risk_fails_transparently_without_source_calibrations():
    result = build_model_risk_governance({"ok": False}, {}, {}, bootstrap_draws=2)
    assert result["ok"] is False
    assert result["status"] == "FAILED"
    assert result["reason"]


def test_model_risk_finishing_exposes_decision_drivers_and_evidence_tier():
    result = _run(seed=31)
    diagnostics = result["decision_diagnostics"]
    assert diagnostics["evidence_tier"] == "PRELIMINARY"
    assert diagnostics["bootstrap_draws"] == 3
    assert diagnostics["relative_model_preference"] in {"HESTON", "BATES"}
    assert diagnostics["absolute_production_status"] in {"ELIGIBLE", "NOT_ELIGIBLE"}
    assert diagnostics["largest_bates_interval"]["parameter"]
    assert diagnostics["largest_maturity_sensitivity"]["driving_parameter"]
    assert "Bootstrap evidence depth" in set(result["gate_table"]["gate"])
    assert "Heston source parameters away from bounds" in set(result["gate_table"]["gate"])
    assert "Bates bootstrap intervals away from bounds" in set(result["gate_table"]["gate"])
    assert not result["parameter_bound_diagnostics"].empty
    card = result["model_card"]
    assert card["relative_model_preference"] == diagnostics["relative_model_preference"]
    assert card["absolute_production_status"] == diagnostics["absolute_production_status"]
    assert card["evidence_tier"] == diagnostics["evidence_tier"]


def test_model_risk_bound_diagnostics_flags_source_and_ci_contact():
    from monte_carlo.model_risk import _parameter_bound_diagnostics

    intervals = pd.DataFrame([
        {
            "model": "Heston",
            "parameter": "kappa",
            "ci_low": 14.0,
            "ci_high": 20.0,
        },
        {
            "model": "Heston",
            "parameter": "theta",
            "ci_low": 0.10,
            "ci_high": 0.20,
        },
    ])
    table, source_flags, interval_flags = _parameter_bound_diagnostics(
        "Heston",
        {"kappa": 20.0, "theta": 0.15},
        {"kappa": (0.05, 20.0), "theta": (0.0025, 1.5)},
        intervals,
        0.01,
    )
    kappa = table[table["parameter"] == "kappa"].iloc[0]
    assert bool(kappa["source_near_bound"]) is True
    assert kappa["source_bound_side"] == "UPPER"
    assert bool(kappa["ci_touches_bound"]) is True
    assert "Heston kappa near upper bound" in source_flags
    assert "Heston kappa bootstrap CI touches upper bound" in interval_flags
