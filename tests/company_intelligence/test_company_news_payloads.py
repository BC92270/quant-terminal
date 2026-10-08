"""Regression coverage for provider-shaped Company Intelligence news payloads."""
from __future__ import annotations

import pandas as pd

import company_intelligence.news as news
from company_intelligence.institutional_desk import build_desk_context


def test_latest_news_briefing_accepts_dataframe_in_sentiment(monkeypatch):
    captured = {}

    def _capture(payload, **kwargs):
        captured["payload"] = payload
        captured["ticker"] = kwargs.get("ticker")

    monkeypatch.setattr(news, "render_latest_news_intelligence_center_v1", _capture)

    news.render_latest_news_briefing_v6(
        {
            "profile": {"name": "Example Corp"},
            "sentiment": {
                "news_table": pd.DataFrame(
                    [{"title": "Example catalyst", "source": "Primary source"}]
                )
            },
        },
        "EXM",
    )

    assert captured["ticker"] == "EXM"
    assert captured["payload"][0]["title"] == "Example catalyst"


def test_desk_context_keeps_missing_scores_unavailable_and_handles_frames():
    context = build_desk_context(
        "EXM",
        {
            "company_analysis": {
                "profile": {"name": "Example Corp", "market_cap": 1_000_000},
                "scores": {},
                "raw_data": {
                    "info": {"regularMarketPrice": 42.0},
                    "fmp": {"enabled": False},
                    "sec": pd.DataFrame([{"accession": "0001"}]),
                },
            }
        },
    )

    assert context["company_score"] is None
    assert context["posture"] == "Evidence pending"
    assert context["provider_flags"]["FMP estimates"] is False
    assert context["provider_flags"]["SEC / filings"] is True
