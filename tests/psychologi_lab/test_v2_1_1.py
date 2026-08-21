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

from market_psychology.narrative_nlp import analyze_news_corpus, extract_belief


def _row(title, summary="", provider="Finnhub", source="Yahoo", hours=0, relevance=0.9):
    return {
        "published": pd.Timestamp("2026-08-10T15:00:00Z") - pd.Timedelta(hours=hours),
        "provider": provider,
        "source": source,
        "title": title,
        "summary": summary,
        "symbol": "SPY",
        "provider_sentiment": np.nan,
        "relevance": relevance,
        "url": f"https://example.com/{abs(hash(title)) % 100000}",
    }


def test_question_recommendation_is_weak_not_direct_bullish_statement():
    b = extract_belief("DraftKings After Earnings: Buy, Hold, or Run?", "", None, document_relevance=0.4)
    assert b.inference_type == "WEAK INFERENCE"
    assert b.direction == "NEUTRAL / MIXED"
    assert b.confidence <= 0.46


def test_unrelated_single_stock_stories_do_not_become_rates_narrative():
    df = pd.DataFrame([
        _row("DraftKings After Earnings: Buy, Hold, or Run?", hours=0),
        _row("3 Beaten-Down Healthcare Stocks to Buy in August", hours=1),
        _row("Super Micro Computer Continues Its 3-Month Fall", hours=2),
        _row("Wall Street Lunch: GameStop CEO Reconsiders eBay Takeover", hours=3),
        _row("Why Market Headlines May Miss The Bigger Picture", hours=4),
        _row("S&P 500 Companies' Second-Quarter Profit Boomed", "Earnings growth for the S&P 500 remains strong.", hours=5),
        _row("Fed rate cuts expected after softer inflation", "Powell and Treasury yields remain central to the market outlook.", hours=6),
        _row("AI demand accelerates as hyperscaler data center capex expands", "Semiconductor demand remains strong.", hours=7),
    ])
    out = analyze_news_corpus(df, symbol="SPY")
    nar = out["narratives"]
    assert not nar.empty
    rates = nar[nar["Narrative"] == "Rates / Fed"]
    if not rates.empty:
        assert float(rates.iloc[0]["Share"]) < 0.50
    assert "Appeared 24 / Wall St / 24 Wall" not in set(nar["Narrative"].astype(str))
    assert "Portfolio / Holdings / Million" not in set(nar["Narrative"].astype(str))
    assert out["resolved_coverage"] < 100


def test_story_level_grouping_compresses_syndicated_variants():
    df = pd.DataFrame([
        _row("Fed signals rate cuts as inflation cools", "Federal Reserve officials signaled easier policy.", "Finnhub", "Reuters", 0),
        _row("Fed signals rate cuts as inflation cools", "Federal Reserve officials signaled easier policy.", "NewsAPI", "Reuters", 1),
        _row("Federal Reserve signals rate cuts as inflation cools", "Officials point to softer CPI and lower yields.", "Alpha Vantage", "CNBC", 2),
        _row("AI chip demand accelerates", "Data center capex supports semiconductor demand.", "Finnhub", "Bloomberg", 3),
    ])
    out = analyze_news_corpus(df, symbol="SPY")
    assert out["story_count"] < out["count"]
    assert out["duplicate_story_docs"] >= 1
    assert out["story_compression"] > 0


def test_semantic_quality_is_multidimensional_not_automatic_100():
    df = pd.DataFrame([
        _row("S&P 500 earnings rise", "Profits and revenue improve.", hours=0),
        _row("Fed rate cuts debated", "Powell says inflation remains uncertain.", hours=5),
        _row("AI chip demand expands", "Semiconductor data center demand is strong.", hours=10),
        _row("Healthcare stock jumps on trial", "A biotech company reported results.", hours=15),
        _row("Oil prices rise on geopolitical risk", "Crude markets react to conflict.", hours=20),
        _row("ETF inflows support equities", "Passive fund flows increased.", hours=25),
    ])
    out = analyze_news_corpus(df, symbol="SPY")
    for key in ["semantic_validity_score", "label_confidence_score", "belief_extraction_quality", "nlp_evidence_score"]:
        assert 0 <= out[key] <= 100
    assert out["nlp_evidence_score"] < 100
    assert not out["narrative_belief_matrix"].empty
    assert not out["narrative_phase_space"].empty
