from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from monte_carlo.walk_forward import build_walk_forward_validation


def synthetic_prices(seed: int = 31, n: int = 420) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-02", periods=n)
    returns = rng.normal(0.00025, 0.017, n)
    close = 100.0 * np.exp(np.cumsum(returns))
    spread = np.maximum(close * 0.005, 0.25)
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


def test_walk_forward_outputs_scores_and_is_reproducible():
    kwargs = dict(
        ticker="WF",
        price_data=synthetic_prices(),
        models=["GBM normal", "GBM Student-t calibré"],
        horizon=7,
        forecast_origins=8,
        origin_stride=5,
        paths_per_origin=250,
        minimum_training_observations=120,
        seed=19,
    )
    first = build_walk_forward_validation(**kwargs)
    second = build_walk_forward_validation(**kwargs)
    assert first["ok"] and second["ok"]
    pd.testing.assert_frame_equal(first["forecasts"], second["forecasts"])
    pd.testing.assert_frame_equal(first["leaderboard"], second["leaderboard"])
    assert len(first["forecasts"]) == 16
    assert set(first["leaderboard"]["Model"]) == {"GBM normal", "GBM Student-t calibré"}
    assert first["configuration_signature"] == second["configuration_signature"]


def test_walk_forward_is_leakage_safe_and_metrics_are_well_formed():
    result = build_walk_forward_validation(
        ticker="WF",
        price_data=synthetic_prices(),
        models=["GBM normal", "Historical bootstrap"],
        horizon=1,
        forecast_origins=10,
        origin_stride=3,
        paths_per_origin=250,
        minimum_training_observations=120,
        seed=23,
    )
    assert result["ok"]
    forecasts = result["forecasts"]
    assert np.all(forecasts["origin_date"] < forecasts["realization_date"])
    assert forecasts["pit"].between(0.0, 1.0).all()
    assert (forecasts["crps"] >= 0.0).all()
    assert forecasts["inside_90"].dtype == bool
    assert set(forecasts["actual_barrier_outcome"]).issubset({"target", "stop", "ambiguous", "neither"})
    assert not result["quantile_calibration"].empty
    assert not result["pit_histogram"].empty


def test_conditional_walk_forward_runs_and_surfaces_governance():
    result = build_walk_forward_validation(
        ticker="WFGARCH",
        price_data=synthetic_prices(n=600),
        models=["GARCH(1,1) Student-t"],
        horizon=7,
        forecast_origins=3,
        origin_stride=20,
        paths_per_origin=200,
        minimum_training_observations=252,
        garch_maxiter=200,
        garch_min_observations=120,
        seed=29,
    )
    assert result["ok"]
    forecasts = result["forecasts"]
    assert len(forecasts) == 3
    assert "eligibility_status" in forecasts.columns
    assert "fallback_used" in forecasts.columns
    assert result["leaderboard"].iloc[0]["Validation status"] in {
        "VALIDATED",
        "WARNING",
        "INSUFFICIENT",
        "REJECTED",
    }


def test_warning_leader_is_not_promoted_to_validated_recommendation():
    result = build_walk_forward_validation(
        ticker="WFPOWER",
        price_data=synthetic_prices(n=500),
        models=["GBM normal", "Historical bootstrap"],
        horizon=7,
        forecast_origins=8,
        origin_stride=7,
        paths_per_origin=250,
        minimum_training_observations=120,
        seed=41,
    )
    assert result["ok"]
    assert result["recommended_model"] is None
    assert result["research_leader"] in {"GBM normal", "Historical bootstrap"}
    assert result["ensemble_ready"] is False
