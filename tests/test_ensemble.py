from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import mc_lab
from monte_carlo.ensemble import build_validated_ensemble, derive_ensemble_weights


def prices(seed: int = 11, n: int = 900) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-02", periods=n)
    returns = rng.normal(0.00025, 0.017, n)
    close = 100.0 * np.exp(np.cumsum(returns))
    spread = np.maximum(close * 0.004, 0.25)
    return pd.DataFrame(
        {
            "date": dates,
            "open": close,
            "high": close + spread,
            "low": np.maximum(0.01, close - spread),
            "close": close,
            "volume": 1_000_000,
        }
    )


def validation_fixture(status: str = "VALIDATED", origins: int = 40) -> dict:
    models = ["GBM normal", "Historical bootstrap", "GARCH(1,1) Student-t"]
    leaderboard_rows = []
    forecast_rows = []
    dates = pd.bdate_range("2025-01-02", periods=origins)
    rng = np.random.default_rng(17)
    for rank, model in enumerate(models, start=1):
        leaderboard_rows.append(
            {
                "Model": model,
                "Validation status": status,
                "Forecasts": origins,
                "Validation rank": rank,
                "Mean CRPS": 0.030 + 0.003 * rank,
                "Mean log score": 1.2 - 0.02 * rank,
                "Mean interval score 90%": 0.20 + 0.01 * rank,
                "Coverage penalty": 0.03 + 0.01 * rank,
                "Barrier multiclass Brier": 0.12 + 0.01 * rank,
                "Fallback rate": 0.0,
                "Eligible-origin share": 1.0,
                "Governed rank score": float(rank),
            }
        )
        realized = rng.normal(0.0, 0.03, origins)
        errors = rng.normal(0.0, 0.01 + 0.001 * rank, origins)
        for date, value, error in zip(dates, realized, errors):
            forecast_rows.append(
                {
                    "model": model,
                    "origin_date": date,
                    "realized_return": float(value),
                    "predictive_mean": float(value - error),
                    "crps": float(abs(error) + 0.02 + 0.002 * rank),
                }
            )
    return {
        "ok": True,
        "configuration_signature": "VALIDATION123",
        "forecast_origins": origins,
        "leaderboard": pd.DataFrame(leaderboard_rows),
        "forecasts": pd.DataFrame(forecast_rows),
    }


def test_ensemble_gate_blocks_warning_models_by_default():
    result = derive_ensemble_weights(
        validation_fixture(status="WARNING", origins=40),
        minimum_models=2,
        minimum_forecasts=20,
        include_warning=False,
    )
    assert result["ok"] is False
    assert result["status"] == "BLOCKED"


def test_weights_sum_to_one_and_respect_cap():
    result = derive_ensemble_weights(
        validation_fixture(),
        method="Governed composite",
        max_weight=0.40,
        minimum_models=3,
        minimum_forecasts=20,
        bootstrap_repetitions=25,
        seed=3,
    )
    assert result["ok"]
    weights = np.array(list(result["weights"].values()))
    assert abs(float(weights.sum()) - 1.0) < 1e-12
    assert float(weights.max()) <= 0.4000001
    assert result["status"] == "ACTIVE"
    assert (result["weight_table"]["Weight CI high"] >= result["weight_table"]["Weight CI low"]).all()


def test_validated_ensemble_builds_nested_paths_and_risk_summary():
    lab = mc_lab.build_monte_carlo_lab(
        "ENS",
        prices(),
        simulations=250,
        matrix_simulations=250,
        scenario="Conservateur",
        model="GBM normal",
        stability_check=False,
        garch_maxiter=250,
    )
    assert lab["ok"]
    ensemble = build_validated_ensemble(
        lab=lab,
        validation_result=validation_fixture(),
        method="Inverse CRPS",
        simulations=600,
        max_weight=0.45,
        minimum_models=3,
        minimum_forecasts=20,
        bootstrap_repetitions=10,
        seed=9,
    )
    assert ensemble["ok"]
    assert ensemble["status"] == "ACTIVE"
    assert ensemble["paths_by_horizon"][90].shape[0] == 600
    np.testing.assert_array_equal(ensemble["paths_by_horizon"][30], ensemble["paths_by_horizon"][90][:, :31])
    for summary in ensemble["summaries_by_horizon"].values():
        total = (
            summary["prob_target_before_stop"]
            + summary["prob_stop_before_target"]
            + summary["prob_same_day_ambiguous"]
            + summary["prob_neither"]
        )
        assert abs(total - 100.0) < 1e-10
        assert summary["es_5"] <= summary["var_5"] + 1e-12
