"""Regression smoke test for the core Company Intelligence analysis contract."""
import pandas as pd
import company_intelligence.earnings as earnings


def test_market_feeling_score_is_available():
    assert earnings.score_market_feeling({"raw_score": 2, "news_count": 3}) == 62
    assert earnings.score_market_feeling({"raw_score": 0, "news_count": 0}) == 50


def test_analyze_company_intelligence_empty_bundle(monkeypatch):
    empty_bundle = {
        "info": {"symbol": "TEST"},
        "financials": pd.DataFrame(),
        "quarterly_financials": pd.DataFrame(),
        "balance_sheet": pd.DataFrame(),
        "quarterly_balance_sheet": pd.DataFrame(),
        "cashflow": pd.DataFrame(),
        "quarterly_cashflow": pd.DataFrame(),
        "recommendations": pd.DataFrame(),
        "earnings_dates": pd.DataFrame(),
        "news": [],
        "yf_news": [],
        "alpha": {},
        "sec": {},
        "finnhub": {},
        "fmp": {"earnings_calendar": [], "earnings_surprises": []},
    }
    monkeypatch.setattr(earnings, "get_company_intelligence_data", lambda ticker: empty_bundle)
    result = earnings.analyze_company_intelligence("TEST", 100.0)
    assert result["scores"]["sentiment_score"] == 50
    assert "company_score" in result["scores"]
