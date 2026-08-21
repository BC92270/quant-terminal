from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import mc_lab
from monte_carlo.barriers import resolve_barrier_monitoring
from monte_carlo.calibration_sources import resolve_calibration_data


def prices(seed: int, n: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2018-01-02", periods=n)
    returns = rng.normal(0.00025, 0.018, n)
    close = 100.0 * np.exp(np.cumsum(returns))
    spread = np.maximum(close * 0.004, 0.2)
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


def test_auto_calibration_prefers_analysis_long_history():
    display = prices(1, 252)
    long_history = prices(2, 1_500)
    selected, report = resolve_calibration_data(
        display,
        analysis={"monte_carlo": {"calibration_data": long_history}},
        source_mode="auto",
    )
    assert len(selected) == 1_500
    assert report["selected_source"] == "analysis/monte_carlo.calibration_data"
    assert report["auto_discovered"] is True


def test_barrier_monitoring_is_forced_for_non_gbm():
    resolution = resolve_barrier_monitoring("GARCH(1,1) Student-t", "Brownian bridge (GBM)")
    assert resolution["forced"] is True
    assert resolution["effective"] == "Clôture de chaque pas"
    gbm = resolve_barrier_monitoring("GBM normal", "Brownian bridge (GBM)")
    assert gbm["forced"] is False
    assert gbm["effective"] == "Brownian bridge (GBM)"


def test_eligibility_gate_and_matrix_metadata():
    display = prices(3, 252)
    calibration = prices(4, 900)
    lab = mc_lab.build_monte_carlo_lab(
        "ELIG",
        display,
        calibration_data=calibration,
        simulations=250,
        matrix_simulations=250,
        model="GARCH(1,1) Student-t",
        barrier_monitoring="Brownian bridge (GBM)",
        garch_maxiter=300,
        stability_check=False,
    )
    assert lab["ok"]
    assert lab["base"]["calibration_observations"] == 899
    assert lab["settings"]["effective_barrier_monitoring"] == "Clôture de chaque pas"
    assert lab["selected_model_metadata"]["barrier_monitoring_forced"] is True
    assert "eligibility_status" in lab["matrix_df"].columns
    assert "eligible_for_aggregation" in lab["matrix_df"].columns
    assert lab["selected_model_eligibility"]["status"] in {"ELIGIBLE", "WARNING", "INELIGIBLE", "FALLBACK"}


def test_short_sample_excludes_advanced_models():
    short = prices(5, 130)
    lab = mc_lab.build_monte_carlo_lab(
        "SHORT",
        short,
        simulations=250,
        matrix_simulations=250,
        model="GJR-GARCH Student-t",
        garch_min_observations=80,
        garch_maxiter=200,
        stability_check=False,
    )
    assert lab["ok"]
    assert lab["model_eligibility"]["GJR-GARCH Student-t"]["status"] in {"INELIGIBLE", "FALLBACK"}
    assert lab["model_eligibility"]["GJR-GARCH Student-t"]["eligible_for_aggregation"] is False
