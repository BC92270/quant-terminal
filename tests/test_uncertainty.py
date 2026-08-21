from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import mc_lab
from monte_carlo.uncertainty import (
    UNCERTAINTY_VERSION,
    build_parameter_model_uncertainty,
    resolve_uncertainty_model_weights,
)


def prices(seed: int = 31, n: int = 850) -> pd.DataFrame:
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


def lab_fixture() -> dict:
    return mc_lab.build_monte_carlo_lab(
        "UNC",
        prices(),
        simulations=250,
        matrix_simulations=250,
        scenario="Conservateur",
        model="GBM normal",
        seed=17,
        stability_check=False,
        garch_maxiter=250,
    )


def validation_fixture() -> dict:
    return {
        "ok": True,
        "leaderboard": pd.DataFrame(
            [
                {"Model": "GBM normal", "Mean CRPS": 0.04, "Governed rank score": 2.0},
                {"Model": "Historical bootstrap", "Mean CRPS": 0.02, "Governed rank score": 1.0},
            ]
        ),
    }


def test_uncertainty_public_api_and_reproducibility():
    lab = lab_fixture()
    kwargs = dict(
        lab=lab,
        models=["GBM normal"],
        parameter_draws=20,
        paths_per_draw=60,
        mean_block_length=10,
        seed=41,
    )
    first = build_parameter_model_uncertainty(**kwargs)
    second = build_parameter_model_uncertainty(**kwargs)
    assert first["ok"] and second["ok"]
    assert first["uncertainty_version"] == UNCERTAINTY_VERSION
    assert first["configuration_signature"] == second["configuration_signature"]
    np.testing.assert_array_equal(first["paths_by_horizon"][90], second["paths_by_horizon"][90])


def test_nested_paths_and_risk_ordering():
    result = build_parameter_model_uncertainty(
        lab_fixture(),
        models=["GBM normal"],
        parameter_draws=20,
        paths_per_draw=50,
        seed=7,
    )
    assert result["ok"]
    np.testing.assert_array_equal(result["paths_by_horizon"][30], result["paths_by_horizon"][90][:, :31])
    for summary in result["summaries_by_horizon"].values():
        assert summary["es_5"] <= summary["var_5"] + 1e-12
        total = (
            summary["prob_target_before_stop"]
            + summary["prob_stop_before_target"]
            + summary["prob_same_day_ambiguous"]
            + summary["prob_neither"]
        )
        assert abs(total - 100.0) < 1e-10


def test_variance_decomposition_is_nonnegative_and_sums_to_one():
    result = build_parameter_model_uncertainty(
        lab_fixture(),
        models=["GBM normal", "Historical bootstrap"],
        parameter_draws=20,
        paths_per_draw=50,
        seed=9,
    )
    assert result["ok"]
    frame = result["variance_decomposition"]
    for column in ("Aleatory share", "Parameter share", "Model share", "Epistemic share"):
        assert (frame[column] >= -1e-12).all()
    np.testing.assert_allclose(
        frame["Aleatory share"] + frame["Parameter share"] + frame["Model share"],
        np.ones(len(frame)),
        atol=1e-10,
    )
    assert (frame["Model share"] > 0).any()


def test_parameter_and_metric_intervals_are_ordered():
    result = build_parameter_model_uncertainty(
        lab_fixture(),
        models=["GBM normal"],
        parameter_draws=25,
        paths_per_draw=50,
        confidence_level=0.95,
        seed=19,
    )
    assert result["ok"]
    for table_name in ("parameter_interval_table", "metric_interval_table"):
        table = result[table_name]
        assert not table.empty
        assert (table["CI low"] <= table["Median"]).all()
        assert (table["Median"] <= table["CI high"]).all()


def test_validation_weight_resolution_prefers_lower_crps():
    lab = lab_fixture()
    result = resolve_uncertainty_model_weights(
        lab,
        models=["GBM normal", "Historical bootstrap"],
        method="Validation inverse CRPS",
        validation_result=validation_fixture(),
    )
    assert result["method_effective"] == "Validation inverse CRPS"
    assert abs(sum(result["weights"].values()) - 1.0) < 1e-12
    assert result["weights"]["Historical bootstrap"] > result["weights"]["GBM normal"]
