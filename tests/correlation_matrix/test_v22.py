import numpy as np
import pandas as pd

from correlation_matrix_section.correlation_intelligence_v3.config import CorrelationConfig
from correlation_matrix_section.correlation_intelligence_v3.data import load_data_bundle
from correlation_matrix_section.correlation_intelligence_v3.engine import CorrelationEngine
from correlation_matrix_section.correlation_intelligence_v3.factor import multivariate_factor_model
from correlation_matrix_section.correlation_intelligence_v3.portfolio import hedge_candidates
from correlation_matrix_section.correlation_intelligence_v3.regimes import conditional_pair_table
from correlation_matrix_section.correlation_intelligence_v3.tail import empirical_tail_metrics


def synthetic_levels(n=520, seed=11):
    rng = np.random.default_rng(seed)
    m = rng.normal(0, 0.011, n)
    sec = 0.65 * m + rng.normal(0, 0.008, n)
    ret = {
        "AAA": 0.85 * m + 0.55 * sec + rng.normal(0, 0.009, n),
        "BBB": 0.70 * m + 0.45 * sec + rng.normal(0, 0.010, n),
        "CCC": 0.25 * m + rng.normal(0, 0.012, n),
        "SPY": m,
        "SMH": sec,
        "TLT": -0.20 * m + rng.normal(0, 0.006, n),
        "HYG": 0.30 * m + rng.normal(0, 0.004, n),
        "UUP": -0.15 * m + rng.normal(0, 0.004, n),
    }
    idx = pd.bdate_range("2024-01-02", periods=n)
    return pd.DataFrame({k: 100 * np.exp(np.cumsum(v)) for k, v in ret.items()}, index=idx)


def test_primary_app_overrides_overlap_but_keeps_backfill():
    central = synthetic_levels()
    # app only has the latest ~1Y and is deliberately offset to prove overlap authority
    app_idx = central.index[-252:]
    app = pd.DataFrame({"date": app_idx, "adj_close": central.loc[app_idx, "AAA"].values * 1.001})
    db = load_data_bundle(
        list(central.columns),
        "AAA",
        app,
        "2y",
        {"correlation_prices": central, "correlation_data_source": "central"},
    )
    assert len(db.levels["AAA"].dropna()) == len(central)
    assert db.levels.loc[app_idx[-1], "AAA"] == app.iloc[-1]["adj_close"]
    assert "backfill" in db.provider_map["AAA"].lower()
    q = db.quality.set_index("Ticker")
    assert q.loc["AAA", "Coverage %"] > 0.95
    assert q.loc["AAA", "Internal missing %"] < 0.01


def test_factor_v22_has_standardized_beta_vif_and_standardized_condition():
    levels = synthetic_levels()
    ch = np.log(levels / levels.shift(1))
    table, meta = multivariate_factor_model("AAA", ch, ["SPY", "SMH", "HYG", "TLT", "UUP"], 252)
    assert not table.empty
    assert "Standardized Beta" in table.columns
    assert "VIF" in table.columns
    assert meta["Condition number standardized"] is not None
    assert meta["Multicollinearity"] in {"Controlled", "Elevated", "Severe"}


def test_tail_evidence_penalizes_small_uncertain_tail_sample():
    levels = synthetic_levels(n=120)
    ch = np.log(levels / levels.shift(1))
    m = empirical_tail_metrics("AAA", "BBB", ch, 90, 0.10)
    assert "Tail evidence score" in m
    assert "Tail evidence" in m
    assert "Tail quality" in m
    assert 0 <= m["Tail evidence score"] <= 100


def test_engine_splits_peer_rmt_from_full_universe_and_prioritizes_systematic_hedge():
    levels = synthetic_levels()
    cfg = CorrelationConfig()
    b = CorrelationEngine(cfg).analyse(
        "AAA",
        list(levels.columns),
        None,
        180,
        "2y",
        {"correlation_prices": levels, "correlation_data_source": "synthetic"},
    )
    assert b.rmt_full_summary["status"] == "ok"
    assert b.rmt_summary["status"] == "ok"
    assert len(b.rmt_peer_universe) < len(b.changes.columns)
    assert b.summary["best_hedge_type"] != "Peer Equity"


def test_hedge_robustness_and_regime_quality_fields_exist():
    levels = synthetic_levels()
    ch = np.log(levels / levels.shift(1))
    types = {"BBB": "Peer Equity", "SPY": "Benchmark", "SMH": "ETF / Sector", "TLT": "Rates ETF"}
    h = hedge_candidates("AAA", ch, ["BBB", "SPY", "SMH", "TLT"], 180, (30, 90, 180, 252), types)
    assert not h.empty
    for col in ["Robust hedge score", "OOS vol reduction", "Stability", "Hedge ratio 90D", "Vol reduction 180D"]:
        assert col in h.columns

    r = conditional_pair_table("AAA", ch, ["BBB", "SPY"], "SPY", 180, 12, 30)
    assert not r.empty
    assert "Risk-On quality" in r.columns
    assert "Risk-Off CI low" in r.columns
    assert "Stress quality" in r.columns
