from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import mc_lab
from monte_carlo.tail_event import (
    build_tail_event_stress,
    calibrate_merton_jumps,
    fit_evt_tail,
    historical_event_library,
)


def heavy_tail_prices(seed: int = 41, n: int = 1400) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-02", periods=n)
    base = rng.standard_t(4.8, n) / np.sqrt(4.8 / 2.8) * 0.018 + 0.00025
    jump_mask = rng.random(n) < 0.015
    base[jump_mask] += rng.normal(-0.07, 0.025, jump_mask.sum())
    close = 100.0 * np.exp(np.cumsum(base))
    overnight = rng.normal(0.0, 0.006, n)
    overnight[rng.random(n) < 0.01] -= rng.uniform(0.04, 0.12, (rng.random(n) < 0.01).sum()) if False else 0
    open_ = close * np.exp(rng.normal(0.0, 0.005, n))
    spread = np.maximum(close * 0.008, 0.25)
    return pd.DataFrame(
        {
            "date": dates,
            "open": open_,
            "high": np.maximum(open_, close) + spread,
            "low": np.maximum(0.01, np.minimum(open_, close) - spread),
            "close": close,
            "volume": 1_000_000,
        }
    )


def test_evt_fit_and_jump_calibration_are_finite():
    frame = heavy_tail_prices()
    returns = np.log(frame["close"] / frame["close"].shift(1)).dropna().to_numpy()
    evt = fit_evt_tail(returns, threshold_quantile=0.95, bootstrap_repetitions=20, seed=7)
    assert evt["ok"]
    assert evt["exceedances"] >= 20
    assert np.isfinite(evt["shape"])
    assert np.isfinite(evt["metrics"]["var_99_loss"])
    assert evt["metrics"]["es_99_loss"] >= evt["metrics"]["var_99_loss"]
    jump = calibrate_merton_jumps(returns)
    assert jump["ok"]
    assert jump["jump_intensity_ann"] > 0
    assert jump["jump_log_sigma"] > 0


def test_event_library_is_non_overlapping_and_has_sequences():
    library = historical_event_library(heavy_tail_prices(), events_per_window=2)
    assert not library.empty
    assert set([1, 5, 10, 20]).intersection(set(library["Window"]))
    assert library["Sequence"].map(lambda value: isinstance(value, np.ndarray) and value.size >= 1).all()
    assert (library["Cumulative return"] <= 0.0).any()


def test_evt_stress_is_reproducible_and_worsens_tail_risk():
    frame = heavy_tail_prices()
    lab = mc_lab.build_monte_carlo_lab(
        "TAIL",
        frame.tail(300),
        calibration_data=frame,
        simulations=500,
        matrix_simulations=250,
        scenario="Conservateur",
        model="GBM normal",
        stability_check=False,
        garch_maxiter=250,
    )
    first = build_tail_event_stress(
        lab,
        stress_type="EVT tail injection",
        simulations=1000,
        threshold_quantile=0.95,
        evt_intensity_multiplier=2.0,
        severity_multiplier=1.5,
        bootstrap_repetitions=10,
        seed=13,
    )
    second = build_tail_event_stress(
        lab,
        stress_type="EVT tail injection",
        simulations=1000,
        threshold_quantile=0.95,
        evt_intensity_multiplier=2.0,
        severity_multiplier=1.5,
        bootstrap_repetitions=10,
        seed=13,
    )
    assert first["ok"] and second["ok"]
    np.testing.assert_array_equal(first["paths_by_horizon"][90], second["paths_by_horizon"][90])
    stressed = first["summaries_by_horizon"][30]
    baseline = first["baseline_summaries_by_horizon"][30]
    assert stressed["es_5"] <= baseline["es_5"]
    assert stressed["prob_ruin"] >= baseline["prob_ruin"]
    total = (
        stressed["prob_target_before_stop"]
        + stressed["prob_stop_before_target"]
        + stressed["prob_same_day_ambiguous"]
        + stressed["prob_neither"]
    )
    assert abs(total - 100.0) < 1e-10


def test_historical_replay_and_custom_shock_build():
    frame = heavy_tail_prices()
    lab = mc_lab.build_monte_carlo_lab(
        "EVENT",
        frame.tail(300),
        calibration_data=frame,
        simulations=250,
        matrix_simulations=250,
        stability_check=False,
        garch_maxiter=200,
    )
    replay = build_tail_event_stress(
        lab,
        stress_type="Historical crisis replay",
        simulations=500,
        severity_multiplier=1.25,
        bootstrap_repetitions=0,
        seed=8,
    )
    custom = build_tail_event_stress(
        lab,
        stress_type="Custom deterministic shock",
        simulations=500,
        custom_shock=-0.20,
        event_day=5,
        bootstrap_repetitions=0,
        seed=8,
    )
    assert replay["ok"] and custom["ok"]
    assert replay["stress_metadata"]["replay_length"] >= 1
    assert custom["summaries_by_horizon"][30]["es_5"] < custom["baseline_summaries_by_horizon"][30]["es_5"]
