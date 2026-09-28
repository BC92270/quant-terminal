from __future__ import annotations

from math import erf, sqrt

import numpy as np
import pandas as pd
import pytest

from backtest_institutional.statistics import (
    annualized_sharpe,
    cpcv_oos_validation,
    cscv_probability_of_backtest_overfitting,
    deflated_sharpe_ratio,
    institutional_validation_suite,
    probabilistic_sharpe_ratio,
    white_reality_check,
)


def test_psr_uses_sampling_frequency_sharpe_and_annualized_public_benchmark():
    rng = np.random.default_rng(20260927)
    returns = pd.Series(rng.normal(0.0007, 0.011, 480))
    benchmark_annualized = 0.45

    values = returns.to_numpy()
    sampling_sr = values.mean() / values.std(ddof=1)
    centered = values - values.mean()
    sigma = values.std(ddof=1)
    skew = np.mean(centered**3) / sigma**3
    kurtosis = np.mean(centered**4) / sigma**4
    denominator = sqrt(1.0 - skew * sampling_sr + ((kurtosis - 1.0) / 4.0) * sampling_sr**2)
    z_value = (
        (sampling_sr - benchmark_annualized / sqrt(252))
        * sqrt(len(values) - 1)
        / denominator
    )
    oracle = 0.5 * (1.0 + erf(z_value / sqrt(2.0)))

    daily = probabilistic_sharpe_ratio(
        returns,
        benchmark_sharpe=benchmark_annualized,
        periods=252,
        hac_lags=0,
    )
    equivalent_weekly_benchmark = benchmark_annualized * sqrt(52 / 252)
    weekly_units = probabilistic_sharpe_ratio(
        returns,
        benchmark_sharpe=equivalent_weekly_benchmark,
        periods=52,
        hac_lags=0,
    )

    assert daily == pytest.approx(oracle, abs=1e-12)
    assert weekly_units == pytest.approx(daily, abs=1e-12)
    assert annualized_sharpe(returns, periods=252) == pytest.approx(sampling_sr * sqrt(252))


def test_dsr_is_unavailable_without_a_real_candidate_family_instead_of_false_fifty_percent():
    rng = np.random.default_rng(17)
    selected = pd.Series(rng.normal(0.0008, 0.01, 260))

    direct = deflated_sharpe_ratio(selected, num_trials=1)
    suite = institutional_validation_suite(selected, candidates=None, bootstrap_samples=20)

    assert direct["available"] is False
    assert direct["state"] == "UNAVAILABLE"
    assert np.isnan(direct["expected_max_sharpe"])
    assert np.isnan(direct["deflated_sharpe_probability"])
    assert "candidate" in direct["reason"].lower()
    assert suite["candidate_count"] == 0
    assert suite["dsr"]["available"] is False
    assert np.isnan(suite["dsr"]["deflated_sharpe_probability"])
    assert suite["pbo"]["state"] == "UNAVAILABLE"
    assert suite["cpcv"]["state"] == "UNAVAILABLE"


def test_dsr_uses_candidate_distribution_and_discriminates_positive_from_negative_edge():
    rng = np.random.default_rng(91)
    candidate_returns = pd.DataFrame({
        "c1": rng.normal(0.0001, 0.011, 360),
        "c2": rng.normal(0.0004, 0.012, 360),
        "c3": rng.normal(-0.0002, 0.010, 360),
        "c4": rng.normal(0.0002, 0.014, 360),
    })
    trial_sharpes = [annualized_sharpe(candidate_returns[column]) for column in candidate_returns]
    common_noise = rng.normal(0.0, 0.01, 360)
    positive = pd.Series(common_noise + 0.0012)
    negative = pd.Series(common_noise - 0.0012)

    positive_dsr = deflated_sharpe_ratio(
        positive,
        num_trials=4,
        trial_sharpes=trial_sharpes,
    )
    negative_dsr = deflated_sharpe_ratio(
        negative,
        num_trials=4,
        trial_sharpes=trial_sharpes,
    )

    assert positive_dsr["available"] is True
    assert negative_dsr["available"] is True
    assert positive_dsr["expected_max_sharpe"] == pytest.approx(
        negative_dsr["expected_max_sharpe"]
    )
    assert positive_dsr["deflated_sharpe_probability"] > negative_dsr["deflated_sharpe_probability"]
    assert positive_dsr["deflated_sharpe_probability"] != pytest.approx(0.5)
    assert negative_dsr["deflated_sharpe_probability"] != pytest.approx(0.5)


def test_candidate_tests_use_complete_intersection_and_never_zero_fill_missing_returns():
    index = pd.bdate_range("2025-01-02", periods=120)
    oscillation = np.where(np.arange(120) % 2, 0.0005, -0.0005)
    candidates = pd.DataFrame({
        "a": 0.001 + oscillation,
        "b": 0.0007 - oscillation,
        "c": -0.0001 + oscillation * 0.5,
    }, index=index)
    candidates.loc[index[10], "b"] = np.nan
    candidates.loc[index[80], "c"] = np.inf
    complete = candidates.replace([np.inf, -np.inf], np.nan).dropna(how="any")

    reality = white_reality_check(candidates, bootstrap_samples=30, seed=5)
    pbo = cscv_probability_of_backtest_overfitting(candidates, partitions=6)

    assert reality["observations"] == 118
    assert reality["dropped_incomplete_rows"] == 2
    assert reality["observed_max_mean"] == pytest.approx(complete.mean().max())
    assert "never zero-filled" in reality["missing_policy"]
    assert pbo["observations"] == 118
    assert pbo["dropped_incomplete_rows"] == 2
    assert pbo["available"] is True


def test_cpcv_selects_only_on_train_and_executes_held_out_candidate_returns():
    index = pd.bdate_range("2025-01-02", periods=120)
    oscillation = np.where(np.arange(120) % 2, 0.0005, -0.0005)
    candidate_a = np.where(np.arange(120) < 90, 0.01, -0.02) + oscillation
    candidate_b = 0.001 - oscillation
    candidates = pd.DataFrame({"A": candidate_a, "B": candidate_b}, index=index)

    result = cpcv_oos_validation(
        candidates["A"],
        candidates,
        total_folds=4,
        test_folds=1,
        purge=0,
        embargo=0,
    )
    last_fold = next(path for path in result["path_results"] if path["test_fold_ids"] == [3])

    assert result["available"] is True
    assert result["paths_requested"] == 4
    assert result["paths_executed"] == 4
    assert last_fold["selected_candidate"] == "A"
    assert last_fold["oos_mean_return"] == pytest.approx(-0.02)
    assert last_fold["oos_sharpe"] < 0

    changed = candidates.copy()
    changed.loc[index[90]:, "A"] = 0.05 + oscillation[90:]
    changed_result = cpcv_oos_validation(
        changed["A"],
        changed,
        total_folds=4,
        test_folds=1,
        purge=0,
        embargo=0,
    )
    changed_last_fold = next(
        path for path in changed_result["path_results"] if path["test_fold_ids"] == [3]
    )

    assert changed_last_fold["selected_candidate"] == last_fold["selected_candidate"]
    assert changed_last_fold["train_sharpe"] == pytest.approx(last_fold["train_sharpe"])
    assert changed_last_fold["oos_mean_return"] == pytest.approx(0.05)
    assert changed_last_fold["oos_sharpe"] > 0


def test_validation_suite_exposes_executed_cpcv_paths_and_alignment_state():
    rng = np.random.default_rng(404)
    index = pd.bdate_range("2024-01-02", periods=160)
    candidates = pd.DataFrame({
        "alpha": rng.normal(0.0007, 0.01, len(index)),
        "beta": rng.normal(0.0002, 0.012, len(index)),
        "gamma": rng.normal(-0.0001, 0.009, len(index)),
    }, index=index)
    selected = candidates["alpha"].copy()
    candidates.loc[index[7], "beta"] = np.nan

    suite = institutional_validation_suite(
        selected,
        candidates=candidates,
        bootstrap_samples=20,
        cpcv_total_folds=4,
        cpcv_test_folds=1,
        cpcv_purge=2,
        cpcv_embargo=2,
    )

    assert suite["candidate_alignment"]["state"] == "AVAILABLE"
    assert suite["candidate_alignment"]["observations"] == 159
    assert suite["candidate_alignment"]["dropped_incomplete_rows"] == 1
    assert suite["cpcv"]["available"] is True
    assert suite["cpcv_splits"] == suite["cpcv"]["paths_executed"] == 4
    assert len(suite["cpcv"]["path_results"]) == 4
    assert all("selected_candidate" in path for path in suite["cpcv"]["path_results"])
