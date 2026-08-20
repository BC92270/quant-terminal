import sys
from pathlib import Path

import numpy as np
import pandas as pd

import types

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

from market_psychology.data import _balanced_news_sample
from market_psychology.engine import build_psychology_state
from market_psychology.narrative_nlp import analyze_news_corpus, extract_belief


def _synthetic_news(n=48):
    now = pd.Timestamp("2026-08-10T15:00:00Z")
    themes = [
        ("Nvidia AI demand accelerates as data center capex expands", "Hyperscalers expect strong semiconductor demand next quarter.", 0.6),
        ("Fed rate cuts expected after softer inflation", "Markets may price easier monetary policy as CPI cools.", 0.1),
        ("S&P 500 rally extends to record high", "Momentum remains strong although valuation concerns remain.", 0.4),
        ("Geopolitical tensions lift energy risk", "Conflict could increase uncertainty and volatility.", -0.5),
    ]
    providers = ["Finnhub", "FMP", "Alpha Vantage", "NewsAPI"]
    sources = ["Reuters", "Bloomberg", "CNBC", "FT"]
    rows = []
    for i in range(n):
        title, summary, sentiment = themes[i % len(themes)]
        rows.append({
            "published": now - pd.Timedelta(hours=3 * i),
            "provider": providers[i % len(providers)],
            "source": sources[i % len(sources)],
            "title": f"{title} {i}",
            "summary": summary,
            "symbol": "SPY",
            "provider_sentiment": sentiment,
            "relevance": 0.8,
            "url": f"https://example.com/{i}",
        })
    return pd.DataFrame(rows)


def _pack():
    rng = np.random.default_rng(3)
    dates = pd.bdate_range(end=pd.Timestamp("2026-08-10", tz="UTC"), periods=800)
    pack = {}
    for sym, mu, vol in [
        ("SPY", 0.0004, 0.010), ("QQQ", 0.0005, 0.013), ("IWM", 0.0003, 0.014),
        ("HYG", 0.0001, 0.004), ("TLT", 0.00005, 0.008), ("GLD", 0.0002, 0.009),
        ("^VIX", 0.0, 0.03),
    ]:
        if sym == "^VIX":
            close = np.clip(19 + np.cumsum(rng.normal(0, 0.2, len(dates))), 10, 45)
        else:
            close = 100 * np.exp(np.cumsum(rng.normal(mu, vol, len(dates))))
        df = pd.DataFrame({
            "date": dates, "open": close, "high": close * 1.01, "low": close * 0.99,
            "close": close, "volume": rng.lognormal(15, 0.25, len(dates)),
        })
        df.attrs["provider"] = "SyntheticTest"
        df.attrs["provider_attempts"] = []
        pack[sym] = df
    return pack


def test_belief_parser_is_directional_and_auditable():
    b = extract_belief(
        "AI demand accelerates",
        "Management expects strong growth next quarter as data center capex expands.",
        0.6,
    )
    assert b.direction == "BULLISH"
    assert b.horizon == "1–6 MONTHS"
    assert b.driver in {"Demand / growth", "Technology / innovation"}
    assert b.confidence > 0.5
    assert b.claim


def test_semantic_corpus_returns_narratives_and_beliefs():
    out = analyze_news_corpus(_synthetic_news())
    assert out["count"] > 0
    assert out["provider_count"] >= 2
    assert not out["narratives"].empty
    assert not out["beliefs"].empty
    assert 0 <= out["belief_disagreement"] <= 100
    assert 0 <= out["narrative_state_score"] <= 100
    assert "AGGLOMERATIVE" in out["backend"] or "FALLBACK" in out["backend"]


def test_balanced_provider_sample_avoids_single_provider_monopoly():
    df = _synthetic_news(40)
    # Add a dominant provider with many newer rows.
    extra = df.iloc[:20].copy()
    extra["provider"] = "Dominant"
    extra["published"] = pd.date_range("2026-08-10", periods=len(extra), freq="min", tz="UTC")
    combined = pd.concat([extra, df], ignore_index=True)
    sampled = _balanced_news_sample(combined, 20)
    assert len(sampled) <= 20
    assert sampled["provider"].nunique() >= 3


def test_full_state_pipeline_with_v21_news():
    news = _synthetic_news(52)
    options = {
        "available": True, "call_volume": 120000, "put_volume": 95000,
        "call_oi": 500000, "put_oi": 540000, "put_call_volume": 0.79,
        "put_call_oi": 1.08, "call_iv": 0.22, "put_iv": 0.28,
        "near_term_share": 0.62, "rows": 800,
    }
    state = build_psychology_state("SPY", _pack(), news, options)
    assert state["available"] is True
    assert state["diagnostics"]["news_count"] > 0
    assert "dominant_narrative" in state["diagnostics"]
    assert not state["news"]["beliefs"].empty
    assert 0 <= state["scores"]["narrative"] <= 100
