import sys
from pathlib import Path
import types

import numpy as np
import pandas as pd

if "streamlit" not in sys.modules:
    st = types.ModuleType("streamlit")
    st.secrets = {}
    def _cache_data(*args, **kwargs):
        def deco(fn):
            return fn
        return deco
    st.cache_data = _cache_data
    sys.modules["streamlit"] = st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from market_psychology.behavioral_data import enrich_options_behavior
from market_psychology.engine import build_psychology_state


def _pack():
    rng = np.random.default_rng(7)
    dates = pd.bdate_range(end=pd.Timestamp("2026-08-10", tz="UTC"), periods=700)
    pack = {}
    for sym, mu, vol in [
        ("SPY", 0.0004, 0.010), ("QQQ", 0.0005, 0.013), ("IWM", 0.0003, 0.014),
        ("HYG", 0.0001, 0.004), ("TLT", 0.00005, 0.008), ("GLD", 0.0002, 0.009),
        ("^VIX", 0.0, 0.03),
    ]:
        close = np.clip(18 + np.cumsum(rng.normal(0, 0.2, len(dates))), 10, 45) if sym == "^VIX" else 100 * np.exp(np.cumsum(rng.normal(mu, vol, len(dates))))
        df = pd.DataFrame({"date": dates, "open": close, "high": close*1.01, "low": close*0.99, "close": close, "volume": rng.lognormal(15, 0.2, len(dates))})
        df.attrs["provider"] = "Synthetic"
        df.attrs["provider_attempts"] = []
        pack[sym] = df
    return pack


def _news():
    now = pd.Timestamp("2026-08-10T15:00:00Z")
    rows=[]
    for i in range(36):
        rows.append({
            "published": now-pd.Timedelta(hours=i*4), "provider": "Finnhub" if i%2 else "NewsAPI", "source": "Reuters",
            "title": f"S&P 500 earnings and Fed outlook {i}", "summary": "Earnings growth remains positive while rate cuts are debated.",
            "symbol":"SPY", "provider_sentiment": 0.2, "relevance":0.9, "url":f"https://example.com/{i}",
        })
    return pd.DataFrame(rows)


def _behavioral_data():
    dates = pd.bdate_range(end=pd.Timestamp("2026-08-10", tz="UTC"), periods=100)
    return {
        "coverage_score": 92.0,
        "volatility_tail": {"available": True, "coverage": 5, "metrics": {
            "vix": 18.2, "vix9d": 19.7, "vix3m": 20.5, "vvix": 93.0, "skew": 145.0,
            "vix_z": 0.3, "tail_stress_score": 64.0, "ambiguity_score": 61.0,
        }},
        "breadth": {"available": True, "coverage": 14, "metrics": {
            "breadth_score": 42.0, "participation_fragility_score": 58.0,
            "equal_weight_rel_20d": -0.018, "sector_positive_share_20d": 0.45,
        }},
        "funding_credit": {"available": True, "coverage": 7, "metrics": {
            "funding_stress_score": 58.0, "arbitrage_capacity_score": 55.0, "hy_oas": 3.2, "nfci_risk": -0.1,
        }},
        "positioning": {"available": True, "history": pd.DataFrame({"date":dates, "lev_money_net_pct_oi":np.linspace(-0.1,0.2,len(dates))}), "metrics": {
            "positioning_crowding_score": 84.0, "lev_money_percentile": 92.0, "lev_money_weekly_change": 0.02,
        }},
        "options_behavior": {"available": True, "metrics": {
            "option_tail_demand_score": 72.0, "option_lottery_score": 68.0, "convexity_concentration_score": 66.0,
            "dte_7_share": 0.64, "otm_call_volume_share": 0.58, "oi_top5_strike_share": 0.66,
        }},
        "short_interest": {"available": False, "status": "not_connected"},
    }


def test_option_behavior_enrichment_scores_present():
    out = enrich_options_behavior({
        "available": True, "rows": 500, "put_call_volume": 1.15, "put_call_oi": 1.1,
        "near_term_share": 0.7, "zero_dte_share": 0.2, "dte_7_share": 0.65, "dte_30_share": 0.9,
        "otm_call_volume_share": 0.6, "otm_put_volume_share": 0.55, "put_call_iv_skew": 0.12,
        "oi_top5_strike_share": 0.4, "spot": 600,
    })
    assert out["available"] is True
    m = out["metrics"]
    assert 0 <= m["option_tail_demand_score"] <= 100
    assert 0 <= m["option_lottery_score"] <= 100
    assert m["convexity_concentration_score"] == 40.0


def test_v22_data_layer_changes_observed_mechanism_evidence():
    options = {
        "available": True, "call_volume": 120000, "put_volume": 150000, "call_oi": 500000, "put_oi": 600000,
        "put_call_volume": 1.25, "put_call_oi": 1.2, "call_iv": 0.22, "put_iv": 0.31, "near_term_share": 0.7,
        "rows": 800, "dte_7_share": 0.64, "otm_call_volume_share": 0.58, "otm_put_volume_share": 0.6,
        "put_call_iv_skew": 0.12, "oi_top5_strike_share": 0.66,
    }
    state = build_psychology_state("SPY", _pack(), _news(), options, behavioral_data=_behavioral_data())
    assert state["available"] is True
    assert state["diagnostics"]["behavioral_data_coverage"] == 92.0
    assert state["diagnostics"]["volatility_tail_available"] is True
    assert state["diagnostics"]["positioning_available"] is True
    assert "behavioral_data" in state
    assert 0 <= state["scores"]["fear"] <= 100
    assert 0 <= state["scores"]["arbitrage_capacity"] <= 100
    mech = state["mechanism_table"].set_index("key")
    assert "CFTC" in mech.loc["herding", "evidence"]
    assert "Funding/credit" in mech.loc["arbitrage_capacity", "evidence"]
