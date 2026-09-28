from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest_institutional.scenarios import (
    ScenarioConfig,
    marginal_student_t_paths,
    multivariate_student_t_paths,
    run_institutional_scenario_suite,
)
from backtest_institutional.statistics import (
    cpcv_oos_validation,
    deflated_sharpe_ratio,
    institutional_validation_suite,
    probabilistic_sharpe_ratio,
    sharpe_hac_diagnostics,
)


def _returns(rows: int = 500, seed: int = 20260928) -> pd.Series:
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2020-01-02", periods=rows)
    return pd.Series(rng.standard_t(5, rows) * 0.009 + 0.0003, index=index)


def test_scenario_policy_marks_small_or_zero_cost_runs_exploratory_and_fail_closed():
    suite = run_institutional_scenario_suite(
        _returns(),
        config=ScenarioConfig(
            paths=40,
            horizon_days=10,
            confidence=0.90,
            high_vol_multiplier=0.75,
            liquidity_cost_bps=0.0,
        ),
    )

    policy = suite["policy"]
    assert suite["institutional_eligible"] is False
    assert policy["state"] == "UNAVAILABLE"
    assert "paths 40 < 250" in policy["reason"]
    assert "horizon 10 < 20" in policy["reason"]
    assert "confidence 90.0% < 95.0%" in policy["reason"]
    assert "liquidity cost must be strictly positive" in policy["reason"]
    assert suite["availability"]["Institutional scenario policy"]["state"] == "UNAVAILABLE"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"liquidity_cost_bps": -0.01}, "Liquidity cost must be non-negative"),
        ({"high_vol_multiplier": 0.0}, "High-volatility multiplier must be strictly positive"),
        ({"confidence": float("nan")}, "Scenario confidence"),
    ],
)
def test_scenario_numeric_risk_inputs_reject_invalid_values(kwargs, message):
    with pytest.raises(ValueError, match=message):
        marginal_student_t_paths(_returns(60), ScenarioConfig(**kwargs))


def test_multivariate_student_t_requires_two_aligned_factor_histories():
    strategy = _returns()
    institutional = ScenarioConfig(paths=250, horizon_days=20, confidence=0.95)

    without_factors = run_institutional_scenario_suite(strategy, config=institutional)
    assert without_factors["availability"]["Multivariate Student-t"]["state"] == "UNAVAILABLE"
    assert without_factors["institutional_eligible"] is False
    assert np.isnan(without_factors["summary"].loc["Multivariate Student-t"]).all()
    assert without_factors["availability"]["Marginal Student-t"]["state"] == "AVAILABLE"
    assert without_factors["marginal_student_t"]["metadata"]["multivariate"] is False

    one_factor = pd.DataFrame({"market": strategy * 0.8}, index=strategy.index)
    one_factor_suite = run_institutional_scenario_suite(
        strategy,
        factor_returns=one_factor,
        config=institutional,
    )
    assert one_factor_suite["availability"]["Multivariate Student-t"]["state"] == "UNAVAILABLE"
    with pytest.raises(ValueError, match="at least two aligned"):
        multivariate_student_t_paths(one_factor, institutional)

    rng = np.random.default_rng(7)
    factors = pd.DataFrame(
        {
            "market": rng.normal(0.0002, 0.010, len(strategy)),
            "value": rng.normal(0.0001, 0.012, len(strategy)),
        },
        index=strategy.index,
    )
    with_factors = run_institutional_scenario_suite(
        strategy,
        factor_returns=factors,
        config=institutional,
    )
    assert with_factors["policy"]["state"] == "AVAILABLE"
    assert with_factors["availability"]["Multivariate Student-t"]["state"] == "AVAILABLE"
    assert with_factors["factor_model"]["history_coverage"] == pytest.approx(1.0)

    sparse_factors = factors.iloc[:200]
    sparse = run_institutional_scenario_suite(
        strategy,
        factor_returns=sparse_factors,
        config=institutional,
    )
    assert sparse["availability"]["Multivariate Student-t"]["state"] == "UNAVAILABLE"
    assert "coverage" in sparse["availability"]["Multivariate Student-t"]["reason"]


def test_hac_effective_sample_size_reduces_psr_and_dsr_confidence_for_smoothed_returns():
    rng = np.random.default_rng(31)
    innovations = rng.normal(0.0, 1.0, 700)
    smoothed = pd.Series(innovations).rolling(12).mean().dropna().reset_index(drop=True)
    smoothed = (smoothed - smoothed.mean()) / smoothed.std(ddof=1) * 0.01 + 0.0008
    shuffled = pd.Series(rng.permutation(smoothed.to_numpy()))

    smoothed_hac = sharpe_hac_diagnostics(smoothed)
    shuffled_hac = sharpe_hac_diagnostics(shuffled)
    assert smoothed_hac["variance_inflation"] > shuffled_hac["variance_inflation"]
    assert smoothed_hac["effective_sample_size"] < shuffled_hac["effective_sample_size"]

    smoothed_psr = probabilistic_sharpe_ratio(smoothed)
    shuffled_psr = probabilistic_sharpe_ratio(shuffled)
    assert 0.5 < smoothed_psr < shuffled_psr

    trials = [-0.40, -0.15, 0.00, 0.10]
    smoothed_dsr = deflated_sharpe_ratio(smoothed, num_trials=4, trial_sharpes=trials)
    shuffled_dsr = deflated_sharpe_ratio(shuffled, num_trials=4, trial_sharpes=trials)
    assert smoothed_dsr["available"] is True
    assert smoothed_dsr["effective_sample_size"] < shuffled_dsr["effective_sample_size"]
    assert 0.5 < smoothed_dsr["deflated_sharpe_probability"] < shuffled_dsr["deflated_sharpe_probability"]
    assert "Bartlett HAC" in smoothed_dsr["serial_dependence_method"]


def test_candidate_history_coverage_is_measured_against_full_selected_history():
    rng = np.random.default_rng(44)
    index = pd.bdate_range("2024-01-02", periods=200)
    selected = pd.Series(rng.normal(0.0005, 0.01, len(index)), index=index)
    candidates = pd.DataFrame(
        {
            "a": rng.normal(0.0004, 0.01, 100),
            "b": rng.normal(0.0002, 0.012, 100),
        },
        index=index[-100:],
    )

    cpcv = cpcv_oos_validation(selected, candidates)
    suite = institutional_validation_suite(selected, candidates=candidates, bootstrap_samples=10)

    assert cpcv["available"] is False
    assert cpcv["history_coverage"] == pytest.approx(0.5)
    assert cpcv["observations"] == 100
    assert "80.0%" in cpcv["reason"]
    assert "never zero-filled" in cpcv["missing_policy"]
    assert suite["candidate_alignment"]["state"] == "UNAVAILABLE"
    assert suite["candidate_alignment"]["history_coverage"] == pytest.approx(0.5)
    assert suite["dsr"]["state"] == "UNAVAILABLE"
    assert suite["pbo"]["state"] == "UNAVAILABLE"


def test_cpcv_requires_both_minimum_path_count_and_execution_fraction():
    rng = np.random.default_rng(55)
    index = pd.bdate_range("2023-01-02", periods=120)
    candidates = pd.DataFrame(
        {
            "a": rng.normal(0.0005, 0.010, len(index)),
            "b": rng.normal(0.0002, 0.011, len(index)),
            "c": rng.normal(-0.0001, 0.009, len(index)),
        },
        index=index,
    )

    too_few = cpcv_oos_validation(
        candidates["a"],
        candidates,
        total_folds=3,
        test_folds=1,
        purge=0,
        embargo=0,
    )
    assert too_few["paths_executed"] == 3
    assert too_few["path_execution_fraction"] == pytest.approx(1.0)
    assert too_few["available"] is False
    assert "at least 4 paths" in too_few["reason"]

    low_fraction = cpcv_oos_validation(
        candidates["a"],
        candidates,
        total_folds=6,
        test_folds=2,
        purge=15,
        embargo=15,
        min_train_observations=50,
    )
    assert low_fraction["paths_executed"] >= 4
    assert low_fraction["path_execution_fraction"] < 0.80
    assert low_fraction["available"] is False
    assert low_fraction["state"] == "UNAVAILABLE"
