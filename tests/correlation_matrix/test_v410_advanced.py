import numpy as np
import pandas as pd

from correlation_matrix_section.correlation_intelligence_v3.advanced_estimators import (
    distance_correlation_matrix,
    nonlinear_dependency_ranking,
    regularized_tyler_correlation,
)
from correlation_matrix_section.correlation_intelligence_v3.breaks import (
    _candidate_shifts,
    _corr_distance_array,
)
from correlation_matrix_section.correlation_intelligence_v3.factor import multivariate_factor_model
from correlation_matrix_section.correlation_intelligence_v3.engine import governed_universe
from correlation_matrix_section.correlation_intelligence_v3.portfolio import allocation_model_comparison
from correlation_matrix_section.correlation_intelligence_v3.regimes import (
    conditional_pair_table,
    regime_labels,
)
from correlation_matrix_section.correlation_intelligence_v3.structure import cluster_stability_bootstrap
from correlation_matrix_section.correlation_intelligence_v3.tail import fit_copulas
from correlation_matrix_section.dependency_intelligence.config import DependencyConfig
from correlation_matrix_section.dependency_intelligence.structural import lead_lag_table


def _returns(n=520, seed=410):
    rng = np.random.default_rng(seed)
    market = rng.normal(0, 0.012, n)
    sector = 0.55 * market + rng.normal(0, 0.009, n)
    frame = pd.DataFrame(
        {
            "AAA": 0.75 * market + 0.65 * sector + rng.normal(0, 0.006, n),
            "BBB": 0.70 * market + 0.55 * sector + rng.normal(0, 0.007, n),
            "CCC": -0.15 * market + rng.normal(0, 0.009, n),
            "DDD": -0.10 * market + rng.normal(0, 0.010, n),
            "SPY": market,
            "SMH": sector,
        },
        index=pd.bdate_range("2023-01-02", periods=n),
    )
    return frame


def test_regularized_tyler_is_finite_psd_and_auditable():
    rt = _returns(n=240)
    rt.iloc[25, :4] *= 25.0
    rt["NEW_WITHOUT_HISTORY"] = np.nan
    rt.loc[rt.index[-10:], "NEW_WITHOUT_HISTORY"] = np.linspace(-0.01, 0.01, 10)
    result = regularized_tyler_correlation(rt, 220, min_obs=80)
    assert result.metadata["status"] == "ok"
    assert result.metadata["converged"] is True
    assert result.metadata["iterations"] <= 300
    assert "NEW_WITHOUT_HISTORY" not in result.matrix.columns
    matrix = result.matrix.to_numpy(dtype=float)
    assert np.isfinite(matrix).all()
    assert np.allclose(matrix, matrix.T, atol=1e-10)
    assert np.allclose(np.diag(matrix), 1.0)
    assert np.linalg.eigvalsh(matrix).min() > 0


def test_governed_universe_uses_ex_ante_order_and_explicit_override_only():
    available = ["AAA", "BBB", "CCC", "DDD"]
    assert governed_universe("AAA", available, max_assets=3) == ["AAA", "BBB", "CCC"]
    assert governed_universe(
        "AAA", available, supplied=["DDD", "MISSING", "BBB", "DDD"], max_assets=4
    ) == ["AAA", "DDD", "BBB"]


def test_vectorized_break_scan_matches_direct_window_correlations():
    values = _returns(n=260).to_numpy(dtype=float)
    splits, fast = _candidate_shifts(values, w=50, step=7)
    direct = np.asarray(
        [
            _corr_distance_array(values[split - 50 : split], values[split : split + 50])
            for split in splits
        ]
    )
    assert np.allclose(fast, direct, atol=2e-12, rtol=2e-12)


def test_distance_correlation_detects_nonlinearity_but_has_no_portfolio_authority():
    rng = np.random.default_rng(19)
    x = rng.uniform(-1, 1, 320)
    y = x * x + rng.normal(0, 0.03, len(x))
    z = rng.normal(size=len(x))
    rt = pd.DataFrame({"X": x, "Y": y, "Z": z})
    result = distance_correlation_matrix(rt, 320, min_obs=80)
    assert result.matrix.loc["X", "Y"] > 0.35
    assert abs(rt["X"].corr(rt["Y"])) < 0.15
    assert result.metadata["portfolio_eligible"] is False
    ranking = nonlinear_dependency_ranking("X", rt, 320, 80)
    assert ranking.iloc[0]["Ticker"] == "Y"


def test_survival_copulas_expose_lower_and_upper_tail_challengers():
    fits = fit_copulas("AAA", "BBB", _returns(n=300), days=252).set_index("Model")
    assert {"Clayton", "Survival Clayton", "Gumbel", "Survival Gumbel"}.issubset(fits.index)
    assert fits.loc["Clayton", "λL"] > 0 and fits.loc["Clayton", "λU"] == 0
    assert fits.loc["Survival Clayton", "λL"] == 0 and fits.loc["Survival Clayton", "λU"] > 0
    assert fits.loc["Gumbel", "λL"] == 0 and fits.loc["Gumbel", "λU"] > 0
    assert fits.loc["Survival Gumbel", "λL"] > 0 and fits.loc["Survival Gumbel", "λU"] == 0


def test_cluster_consensus_and_allocation_lab_are_temporally_auditable():
    rt = _returns()
    pairs, consensus, cluster_meta = cluster_stability_bootstrap(
        rt, 252, min_obs=80, bootstrap_samples=39, block=5, seed=8
    )
    assert cluster_meta["status"] == "ok"
    assert cluster_meta["bootstrap_valid"] == 39
    assert np.allclose(np.diag(consensus), 1.0)
    assert ((consensus >= 0) & (consensus <= 1)).all().all()
    assert not pairs.empty

    summary, weights, meta = allocation_model_comparison(
        rt, list(rt.columns), train_days=252, test_days=21, min_train=126, max_folds=4
    )
    assert meta["status"] == "ok"
    assert meta["no_look_ahead"] is True
    assert set(summary["Method"]) == {
        "Equal weight", "Inverse volatility", "HRP", "Long-only minimum variance"
    }
    totals = weights.groupby("Method")["Weight"].sum()
    assert np.allclose(totals, 1.0)
    folds = meta["fold_results"]
    assert all(pd.Timestamp(a) < pd.Timestamp(b) for a, b in zip(folds["Train end"], folds["Test start"]))


def test_factor_fdr_and_regime_block_bootstrap_are_exposed():
    rt = _returns(n=360)
    table, meta = multivariate_factor_model("AAA", rt, ["SPY", "SMH", "CCC", "DDD"], 252)
    assert "BH q-value" in table
    assert "FDR supported 10%" in table
    assert "Benjamini-Hochberg" in meta["multiple_testing"]
    assert meta["selection_order"].startswith("caller-supplied ex-ante")

    labels = regime_labels(rt, "SPY", vol_window=20, trend_window=20)
    assert labels["Risk regime"].iloc[:38].isna().all()
    assert labels["Risk regime"].notna().any()

    regimes = conditional_pair_table(
        "AAA", rt, ["BBB"], "SPY", 252, 12, 30,
        bootstrap_samples=49, block_length=5, random_seed=2,
    )
    assert regimes.iloc[0]["CI method"].startswith("moving-block bootstrap")
    assert regimes.iloc[0]["Full CI reps"] >= 30
    assert "20D market trend" in regimes.iloc[0]["Regime definition"]


def test_lead_lag_inference_uses_one_prewhitened_estimand():
    rng = np.random.default_rng(1234)
    n = 520
    a = np.zeros(n)
    eps = rng.normal(size=n)
    for t in range(1, n):
        a[t] = 0.25 * a[t - 1] + eps[t]
    b = np.zeros(n)
    noise = rng.normal(scale=0.55, size=n)
    for t in range(2, n):
        b[t] = 0.65 * a[t - 2] + 0.20 * b[t - 1] + noise[t]
    frame = pd.DataFrame({"A": a, "B": b}, index=pd.bdate_range("2024-01-02", periods=n))
    cfg = DependencyConfig(min_pair_obs=80, lead_lag_bootstrap_samples=199, random_seed=7)
    out = lead_lag_table("A", "B", frame, max_lag=5, min_obs=80, cfg=cfg)
    nz = out[out["Lag days"] != 0]
    selected = nz.loc[nz["Abs inference correlation"].idxmax()]
    assert int(selected["Lag days"]) == 2
    assert selected["Evidence"] == "Supported"
    assert bool(selected["CI contains estimate"])
    assert float(selected["Inference CI low"]) <= float(selected["Prewhitened correlation"]) <= float(selected["Inference CI high"])
    assert "circular-shift max-stat" in selected["Inference method"]
