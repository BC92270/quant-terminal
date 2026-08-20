# Auto-extracted from Quant Terminal app.py and refactored into package modules.
# Existing runtime logic is preserved unless explicitly marked as a fix.

import os
import re
import time
import requests
from datetime import datetime, timedelta
from html import escape, unescape
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf
import plotly.graph_objects as go

from .common import *
from .providers import *

# COMPANY INTELLIGENCE HELPERS
# ============================================================

def extract_company_profile(company_data: dict) -> dict:
    info = company_data.get("info", {})

    return {
        "name": info.get("longName") or info.get("shortName") or "N/A",
        "symbol": info.get("symbol") or "N/A",
        "sector": info.get("sector") or "N/A",
        "industry": info.get("industry") or "N/A",
        "country": info.get("country") or "N/A",
        "website": info.get("website") or "N/A",
        "employees": safe_int(info.get("fullTimeEmployees")),
        "market_cap": safe_float(info.get("marketCap")),
        "enterprise_value": safe_float(info.get("enterpriseValue")),
        "beta": safe_float(info.get("beta")),
        "currency": info.get("currency") or "N/A",
        "summary": info.get("longBusinessSummary") or "Résumé entreprise indisponible via yfinance.",
    }


def extract_growth_metrics(company_data: dict) -> dict:
    info = company_data.get("info", {})
    financials = company_data.get("financials", pd.DataFrame())
    q_financials = company_data.get("quarterly_financials", pd.DataFrame())
    cashflow = company_data.get("cashflow", pd.DataFrame())

    revenue_ttm = safe_float(info.get("totalRevenue"))
    revenue_growth_yoy = safe_float(info.get("revenueGrowth"))
    earnings_growth_yoy = safe_float(info.get("earningsGrowth"))
    quarterly_earnings_growth = safe_float(info.get("earningsQuarterlyGrowth"))

    revenue_annual = statement_row_series(financials, ["Total Revenue", "Operating Revenue"])
    revenue_quarterly = statement_row_series(q_financials, ["Total Revenue", "Operating Revenue"])
    net_income_annual = statement_row_series(financials, ["Net Income", "Net Income Common Stockholders"])
    fcf_annual = statement_row_series(cashflow, ["Free Cash Flow"])

    annual_revenue_growth = None
    if len(revenue_annual) >= 2 and revenue_annual.iloc[1] != 0:
        annual_revenue_growth = float(revenue_annual.iloc[0] / revenue_annual.iloc[1] - 1)

    quarterly_revenue_growth = None
    if len(revenue_quarterly) >= 5 and revenue_quarterly.iloc[4] != 0:
        quarterly_revenue_growth = float(revenue_quarterly.iloc[0] / revenue_quarterly.iloc[4] - 1)

    latest_net_income = safe_float(net_income_annual.iloc[0]) if len(net_income_annual) > 0 else None
    latest_fcf = safe_float(fcf_annual.iloc[0]) if len(fcf_annual) > 0 else safe_float(info.get("freeCashflow"))
    operating_cashflow = safe_float(info.get("operatingCashflow"))

    return {
        "revenue_ttm": revenue_ttm,
        "revenue_growth_yoy": revenue_growth_yoy,
        "earnings_growth_yoy": earnings_growth_yoy,
        "quarterly_earnings_growth": quarterly_earnings_growth,
        "annual_revenue_growth": annual_revenue_growth,
        "quarterly_revenue_growth": quarterly_revenue_growth,
        "latest_net_income": latest_net_income,
        "latest_free_cash_flow": latest_fcf,
        "operating_cash_flow": operating_cashflow,
    }


def extract_profitability_metrics(company_data: dict) -> dict:
    info = company_data.get("info", {})

    gross_margin = safe_float(info.get("grossMargins"))
    ebitda_margin = safe_float(info.get("ebitdaMargins"))
    operating_margin = safe_float(info.get("operatingMargins"))
    profit_margin = safe_float(info.get("profitMargins"))
    roe = safe_float(info.get("returnOnEquity"))
    roa = safe_float(info.get("returnOnAssets"))
    ebitda = safe_float(info.get("ebitda"))

    return {
        "gross_margin": gross_margin,
        "ebitda_margin": ebitda_margin,
        "operating_margin": operating_margin,
        "profit_margin": profit_margin,
        "roe": roe,
        "roa": roa,
        "ebitda": ebitda,
    }


def extract_valuation_metrics(company_data: dict) -> dict:
    info = company_data.get("info", {})

    return {
        "trailing_pe": safe_float(info.get("trailingPE")),
        "forward_pe": safe_float(info.get("forwardPE")),
        "peg_ratio": safe_float(info.get("pegRatio") or info.get("trailingPegRatio")),
        "price_to_sales": safe_float(info.get("priceToSalesTrailing12Months")),
        "price_to_book": safe_float(info.get("priceToBook")),
        "ev_to_revenue": safe_float(info.get("enterpriseToRevenue")),
        "ev_to_ebitda": safe_float(info.get("enterpriseToEbitda")),
        "market_cap": safe_float(info.get("marketCap")),
        "enterprise_value": safe_float(info.get("enterpriseValue")),
    }



def extract_forward_metrics(company_data: dict, valuation: dict, analysts: dict, growth: dict) -> dict:
    info = company_data.get("info", {})

    revenue_growth_forward = safe_float(info.get("revenueGrowth"))
    earnings_growth_forward = safe_float(info.get("earningsGrowth"))
    quarterly_earnings_growth = safe_float(info.get("earningsQuarterlyGrowth"))

    trailing_pe = valuation.get("trailing_pe")
    forward_pe = valuation.get("forward_pe")

    forward_pe_discount = None
    if trailing_pe not in [None, 0] and forward_pe is not None:
        forward_pe_discount = forward_pe / trailing_pe - 1

    implied_eps_growth = None
    if forward_pe not in [None, 0] and trailing_pe is not None:
        implied_eps_growth = trailing_pe / forward_pe - 1

    target_mean_upside = analysts.get("upside_mean")

    if revenue_growth_forward is None:
        revenue_growth_forward = growth.get("revenue_growth_yoy") or growth.get("annual_revenue_growth")

    if earnings_growth_forward is None:
        earnings_growth_forward = growth.get("earnings_growth_yoy")

    if quarterly_earnings_growth is None:
        quarterly_earnings_growth = growth.get("quarterly_earnings_growth")

    if revenue_growth_forward is not None and earnings_growth_forward is not None:
        if revenue_growth_forward >= 0.10 and earnings_growth_forward >= 0.15:
            forward_bias = "Accélération positive"
        elif revenue_growth_forward >= 0 and earnings_growth_forward >= 0:
            forward_bias = "Croissance forward positive mais modérée"
        elif revenue_growth_forward < 0 or earnings_growth_forward < 0:
            forward_bias = "Dégradation forward"
        else:
            forward_bias = "Forward mixte"
    else:
        forward_bias = "Forward incomplet"

    return {
        "forward_bias": forward_bias,
        "revenue_growth_forward": revenue_growth_forward,
        "earnings_growth_forward": earnings_growth_forward,
        "quarterly_earnings_growth": quarterly_earnings_growth,
        "trailing_pe": trailing_pe,
        "forward_pe": forward_pe,
        "forward_pe_discount": forward_pe_discount,
        "implied_eps_growth": implied_eps_growth,
        "peg_ratio": valuation.get("peg_ratio"),
        "target_mean_upside": target_mean_upside,
        "target_high_upside": analysts.get("upside_high"),
        "recommendation_key": analysts.get("recommendation_key"),
    }


def extract_balance_sheet_metrics(company_data: dict) -> dict:
    info = company_data.get("info", {})
    balance_sheet = company_data.get("balance_sheet", pd.DataFrame())
    cashflow = company_data.get("cashflow", pd.DataFrame())

    total_cash = safe_float(info.get("totalCash"))
    total_debt = safe_float(info.get("totalDebt"))
    current_ratio = safe_float(info.get("currentRatio"))
    quick_ratio = safe_float(info.get("quickRatio"))
    debt_to_equity = safe_float(info.get("debtToEquity"))
    total_revenue = safe_float(info.get("totalRevenue"))
    operating_cashflow = safe_float(info.get("operatingCashflow"))
    free_cashflow = safe_float(info.get("freeCashflow"))

    if total_cash is None:
        total_cash = extract_statement_value(balance_sheet, ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"])

    if total_debt is None:
        total_debt = extract_statement_value(balance_sheet, ["Total Debt", "Long Term Debt"])

    if operating_cashflow is None:
        operating_cashflow = extract_statement_value(cashflow, ["Operating Cash Flow", "Total Cash From Operating Activities"])

    if free_cashflow is None:
        free_cashflow = extract_statement_value(cashflow, ["Free Cash Flow"])

    net_debt = None
    if total_debt is not None and total_cash is not None:
        net_debt = total_debt - total_cash

    cash_to_debt = None
    if total_cash is not None and total_debt not in [None, 0]:
        cash_to_debt = total_cash / total_debt

    fcf_margin = None
    if free_cashflow is not None and total_revenue not in [None, 0]:
        fcf_margin = free_cashflow / total_revenue

    return {
        "total_cash": total_cash,
        "total_debt": total_debt,
        "net_debt": net_debt,
        "cash_to_debt": cash_to_debt,
        "current_ratio": current_ratio,
        "quick_ratio": quick_ratio,
        "debt_to_equity": debt_to_equity,
        "operating_cash_flow": operating_cashflow,
        "free_cash_flow": free_cashflow,
        "fcf_margin": fcf_margin,
    }


def extract_analyst_metrics(company_data: dict, latest_price: float) -> dict:
    info = company_data.get("info", {})
    recommendations = company_data.get("recommendations", pd.DataFrame())

    target_low = safe_float(info.get("targetLowPrice"))
    target_mean = safe_float(info.get("targetMeanPrice"))
    target_median = safe_float(info.get("targetMedianPrice"))
    target_high = safe_float(info.get("targetHighPrice"))
    recommendation_mean = safe_float(info.get("recommendationMean"))
    recommendation_key = info.get("recommendationKey") or "N/A"
    number_of_analysts = safe_int(info.get("numberOfAnalystOpinions"))

    upside_mean = target_mean / latest_price - 1 if target_mean and latest_price else None
    upside_high = target_high / latest_price - 1 if target_high and latest_price else None
    downside_low = target_low / latest_price - 1 if target_low and latest_price else None

    recent_recommendations = []
    recommendation_trend = pd.DataFrame()

    if isinstance(recommendations, pd.DataFrame) and not recommendations.empty:
        rec_df = recommendations.copy().reset_index()
        rec_df.columns = [str(c) for c in rec_df.columns]

        consensus_cols = ["strongBuy", "buy", "hold", "sell", "strongSell"]
        lower_map = {c.lower(): c for c in rec_df.columns}
        has_consensus = all(c.lower() in lower_map for c in consensus_cols)

        if has_consensus:
            normalized_rows = []
            for _, row in rec_df.iterrows():
                period = row.get("period", row.get("Period", row.get("index", "N/A")))
                strong_buy = safe_int(row.get(lower_map["strongbuy"]), 0) or 0
                buy = safe_int(row.get(lower_map["buy"]), 0) or 0
                hold = safe_int(row.get(lower_map["hold"]), 0) or 0
                sell = safe_int(row.get(lower_map["sell"]), 0) or 0
                strong_sell = safe_int(row.get(lower_map["strongsell"]), 0) or 0
                total = strong_buy + buy + hold + sell + strong_sell
                bullish_ratio = (strong_buy + buy) / total if total else None

                normalized_rows.append({
                    "Période": period,
                    "Strong Buy": strong_buy,
                    "Buy": buy,
                    "Hold": hold,
                    "Sell": sell,
                    "Strong Sell": strong_sell,
                    "Total": total,
                    "Ratio bullish": bullish_ratio,
                })

            recommendation_trend = pd.DataFrame(normalized_rows)
        else:
            rec_df = rec_df.tail(20)
            for _, row in rec_df.iterrows():
                date_value = row.get("Date", row.get("date", row.get("index", "")))
                if date_value not in [None, ""]:
                    date_value = str(date_value)[:10]
                else:
                    date_value = "N/A"

                firm = row.get("Firm", row.get("firm", row.get("To Firm", "N/A")))
                to_grade = row.get("To Grade", row.get("toGrade", row.get("to_grade", "N/A")))
                from_grade = row.get("From Grade", row.get("fromGrade", row.get("from_grade", "N/A")))
                action = row.get("Action", row.get("action", "N/A"))

                if any(str(x) not in ["N/A", "nan", "None", ""] for x in [firm, to_grade, from_grade, action]):
                    recent_recommendations.append({
                        "Date": date_value,
                        "Firme": firm,
                        "Nouvelle note": to_grade,
                        "Ancienne note": from_grade,
                        "Action": action,
                    })

    return {
        "target_low": target_low,
        "target_mean": target_mean,
        "target_median": target_median,
        "target_high": target_high,
        "upside_mean": upside_mean,
        "upside_high": upside_high,
        "downside_low": downside_low,
        "recommendation_mean": recommendation_mean,
        "recommendation_key": recommendation_key,
        "number_of_analysts": number_of_analysts,
        "recent_recommendations": recent_recommendations,
        "recommendation_trend": recommendation_trend,
    }


def extract_news_sentiment(company_data: dict) -> dict:
    raw_news = company_data.get("news", [])

    positive_keywords = [
        "beat", "beats", "upgrade", "upgraded", "outperform", "strong", "growth", "record",
        "surge", "bullish", "raise", "raised", "positive", "demand", "profit", "partnership",
        "guidance", "accelerate", "leader", "optimistic", "buy", "ai", "launch", "expansion",
        "approval", "contract", "winner", "resilient", "margin expansion", "raises", "boost",
        "boosts", "deal", "customer", "orders", "backlog", "datacenter", "data center"
    ]

    negative_keywords = [
        "miss", "downgrade", "downgraded", "underperform", "weak", "lawsuit", "probe",
        "risk", "bearish", "cut", "lowered", "negative", "slowdown", "ban", "restriction",
        "concern", "pressure", "sell", "warning", "margin pressure", "investigation",
        "delay", "export", "loss", "decline", "fraud", "recall", "sinks", "falls",
        "drops", "disappoints", "guidance cut"
    ]

    rows = []
    total_score = 0

    for item in raw_news[:60]:
        if not isinstance(item, dict):
            continue

        content = item.get("content", {}) if isinstance(item.get("content", {}), dict) else {}

        title = (
            item.get("title")
            or content.get("title")
            or ""
        )

        summary = (
            item.get("summary")
            or item.get("text")
            or content.get("summary")
            or content.get("description")
            or content.get("previewText")
            or ""
        )

        provider = (
            item.get("publisher")
            or item.get("provider")
            or item.get("site")
            or item.get("source")
            or "N/A"
        )

        provider_obj = content.get("provider")
        if isinstance(provider_obj, dict):
            provider = provider_obj.get("displayName") or provider_obj.get("name") or provider

        canonical = content.get("canonicalUrl", {})
        if isinstance(canonical, dict):
            canonical_url = canonical.get("url", "")
        else:
            canonical_url = ""

        link = (
            item.get("link")
            or item.get("url")
            or item.get("article_url")
            or canonical_url
            or ""
        )

        publish_time = (
            item.get("providerPublishTime")
            or item.get("publishedDate")
            or item.get("published_date")
            or item.get("pubDate")
            or content.get("pubDate")
            or content.get("displayTime")
        )

        if publish_time:
            try:
                if isinstance(publish_time, (int, float)):
                    date = pd.to_datetime(publish_time, unit="s").strftime("%Y-%m-%d")
                else:
                    date = pd.to_datetime(publish_time).strftime("%Y-%m-%d")
            except Exception:
                date = "N/A"
        else:
            date = "N/A"

        if not title and not summary:
            continue

        normalized = f"{title} {summary}".lower()

        positive_hits = [
            kw for kw in positive_keywords
            if re.search(rf"\b{re.escape(kw.lower())}\b", normalized)
        ]

        negative_hits = [
            kw for kw in negative_keywords
            if re.search(rf"\b{re.escape(kw.lower())}\b", normalized)
        ]

        score = len(positive_hits) - len(negative_hits)
        total_score += score

        if score > 0:
            sentiment_label = "Positif"
        elif score < 0:
            sentiment_label = "Négatif"
        else:
            sentiment_label = "Neutre"

        rows.append({
            "Date": date,
            "Titre": title,
            "Résumé": summary,
            "Source": provider,
            "Sentiment mécanique": sentiment_label,
            "Score": score,
            "Mots positifs": ", ".join(positive_hits),
            "Mots négatifs": ", ".join(negative_hits),
            "Lien": link,
        })

    news_table = pd.DataFrame(rows)

    if not news_table.empty and "Date" in news_table.columns:
        news_table = news_table.sort_values("Date", ascending=False)

    if len(rows) == 0:
        global_sentiment = "Indisponible"
    elif total_score >= 3:
        global_sentiment = "Plutôt positif"
    elif total_score <= -3:
        global_sentiment = "Plutôt négatif"
    else:
        global_sentiment = "Neutre / mixte"

    return {
        "news_table": news_table,
        "raw_score": total_score,
        "global_sentiment": global_sentiment,
        "news_count": len(rows),
    }

def score_growth(metrics: dict) -> int:
    score = 50

    revenue_growth = metrics.get("revenue_growth_yoy")
    annual_revenue_growth = metrics.get("annual_revenue_growth")
    earnings_growth = metrics.get("earnings_growth_yoy")
    quarterly_earnings_growth = metrics.get("quarterly_earnings_growth")
    fcf = metrics.get("latest_free_cash_flow")

    for growth in [revenue_growth, annual_revenue_growth]:
        if growth is None:
            continue
        if growth >= 0.25:
            score += 15
        elif growth >= 0.10:
            score += 10
        elif growth >= 0.03:
            score += 5
        elif growth < 0:
            score -= 12

    for growth in [earnings_growth, quarterly_earnings_growth]:
        if growth is None:
            continue
        if growth >= 0.25:
            score += 10
        elif growth >= 0.10:
            score += 6
        elif growth < 0:
            score -= 10

    if fcf is not None:
        score += 5 if fcf > 0 else -8

    return int(clamp(round(score)))


def score_profitability(metrics: dict) -> int:
    score = 45

    gross_margin = metrics.get("gross_margin")
    operating_margin = metrics.get("operating_margin")
    profit_margin = metrics.get("profit_margin")
    roe = metrics.get("roe")
    roa = metrics.get("roa")

    if gross_margin is not None:
        if gross_margin >= 0.60:
            score += 15
        elif gross_margin >= 0.40:
            score += 10
        elif gross_margin >= 0.25:
            score += 5
        elif gross_margin < 0.15:
            score -= 5

    if operating_margin is not None:
        if operating_margin >= 0.30:
            score += 15
        elif operating_margin >= 0.15:
            score += 10
        elif operating_margin >= 0.05:
            score += 5
        elif operating_margin < 0:
            score -= 12

    if profit_margin is not None:
        if profit_margin >= 0.25:
            score += 12
        elif profit_margin >= 0.10:
            score += 8
        elif profit_margin >= 0.03:
            score += 4
        elif profit_margin < 0:
            score -= 12

    if roe is not None:
        if roe >= 0.25:
            score += 10
        elif roe >= 0.12:
            score += 6
        elif roe < 0:
            score -= 8

    if roa is not None:
        if roa >= 0.10:
            score += 6
        elif roa >= 0.04:
            score += 3
        elif roa < 0:
            score -= 5

    return int(clamp(round(score)))


def score_balance_sheet(metrics: dict) -> int:
    score = 50

    cash_to_debt = metrics.get("cash_to_debt")
    current_ratio = metrics.get("current_ratio")
    quick_ratio = metrics.get("quick_ratio")
    debt_to_equity = metrics.get("debt_to_equity")
    net_debt = metrics.get("net_debt")
    fcf_margin = metrics.get("fcf_margin")

    if cash_to_debt is not None:
        if cash_to_debt >= 1.0:
            score += 15
        elif cash_to_debt >= 0.5:
            score += 8
        elif cash_to_debt < 0.2:
            score -= 10

    if current_ratio is not None:
        if current_ratio >= 2:
            score += 8
        elif current_ratio >= 1:
            score += 4
        else:
            score -= 8

    if quick_ratio is not None:
        if quick_ratio >= 1.5:
            score += 6
        elif quick_ratio >= 1:
            score += 3
        else:
            score -= 5

    if debt_to_equity is not None:
        if debt_to_equity <= 50:
            score += 8
        elif debt_to_equity <= 150:
            score += 2
        elif debt_to_equity > 250:
            score -= 12

    if net_debt is not None:
        score += 5 if net_debt <= 0 else -3

    if fcf_margin is not None:
        if fcf_margin >= 0.20:
            score += 8
        elif fcf_margin >= 0.08:
            score += 4
        elif fcf_margin < 0:
            score -= 8

    return int(clamp(round(score)))


def score_valuation(valuation: dict, growth: dict, profitability: dict) -> int:
    score = 55

    forward_pe = valuation.get("forward_pe")
    trailing_pe = valuation.get("trailing_pe")
    peg = valuation.get("peg_ratio")
    ps = valuation.get("price_to_sales")
    ev_ebitda = valuation.get("ev_to_ebitda")
    revenue_growth = growth.get("revenue_growth_yoy") or growth.get("annual_revenue_growth") or 0
    operating_margin = profitability.get("operating_margin") or 0

    quality_adjustment = 0
    if revenue_growth >= 0.20:
        quality_adjustment += 8
    elif revenue_growth >= 0.10:
        quality_adjustment += 4

    if operating_margin >= 0.25:
        quality_adjustment += 6
    elif operating_margin >= 0.15:
        quality_adjustment += 3

    if forward_pe is not None:
        if forward_pe <= 15:
            score += 15
        elif forward_pe <= 25:
            score += 8
        elif forward_pe <= 40:
            score += 0
        elif forward_pe <= 65:
            score -= 10
        else:
            score -= 18

    if trailing_pe is not None:
        if trailing_pe <= 20:
            score += 8
        elif trailing_pe <= 35:
            score += 3
        elif trailing_pe > 70:
            score -= 10

    if peg is not None and peg > 0:
        if peg <= 1:
            score += 12
        elif peg <= 2:
            score += 5
        elif peg > 3:
            score -= 10

    if ps is not None:
        if ps <= 3:
            score += 10
        elif ps <= 8:
            score += 2
        elif ps > 15:
            score -= 12

    if ev_ebitda is not None:
        if ev_ebitda <= 12:
            score += 8
        elif ev_ebitda <= 25:
            score += 2
        elif ev_ebitda > 40:
            score -= 10

    score += quality_adjustment
    return int(clamp(round(score)))



def score_forward_quality(forward: dict) -> int:
    score = 50

    revenue_growth_forward = forward.get("revenue_growth_forward")
    earnings_growth_forward = forward.get("earnings_growth_forward")
    quarterly_earnings_growth = forward.get("quarterly_earnings_growth")
    forward_pe_discount = forward.get("forward_pe_discount")
    implied_eps_growth = forward.get("implied_eps_growth")
    target_mean_upside = forward.get("target_mean_upside")

    if revenue_growth_forward is not None:
        if revenue_growth_forward >= 0.20:
            score += 18
        elif revenue_growth_forward >= 0.10:
            score += 10
        elif revenue_growth_forward >= 0.03:
            score += 5
        elif revenue_growth_forward < 0:
            score -= 12

    if earnings_growth_forward is not None:
        if earnings_growth_forward >= 0.25:
            score += 18
        elif earnings_growth_forward >= 0.10:
            score += 10
        elif earnings_growth_forward < 0:
            score -= 12

    if quarterly_earnings_growth is not None:
        if quarterly_earnings_growth >= 0.20:
            score += 10
        elif quarterly_earnings_growth < 0:
            score -= 8

    if forward_pe_discount is not None:
        if forward_pe_discount <= -0.25:
            score += 12
        elif forward_pe_discount <= -0.10:
            score += 6
        elif forward_pe_discount > 0.15:
            score -= 8

    if implied_eps_growth is not None:
        if implied_eps_growth >= 0.20:
            score += 10
        elif implied_eps_growth < 0:
            score -= 8

    if target_mean_upside is not None:
        if target_mean_upside >= 0.20:
            score += 8
        elif target_mean_upside >= 0.05:
            score += 4
        elif target_mean_upside < 0:
            score -= 8

    return int(clamp(round(score)))


def calculate_company_composite_score(company_analysis: dict) -> int:
    scores = company_analysis.get("scores", {})

    growth = scores.get("growth_score", 50)
    profitability = scores.get("profitability_score", 50)
    balance = scores.get("balance_score", 50)
    valuation = scores.get("valuation_score", 50)
    forward = scores.get("forward_score", 50)
    surprise = scores.get("estimate_surprise_score", 50)
    analysts = scores.get("analyst_score", 50)
    sentiment = scores.get("sentiment_score", 50)

    composite = (
        0.18 * growth
        + 0.18 * profitability
        + 0.12 * balance
        + 0.14 * valuation
        + 0.16 * forward
        + 0.12 * surprise
        + 0.07 * analysts
        + 0.03 * sentiment
    )

    return int(clamp(round(composite)))


def get_company_quality_label(score: int) -> str:
    if score >= 80:
        return "Qualité entreprise élevée"
    if score >= 65:
        return "Profil entreprise solide"
    if score >= 50:
        return "Profil entreprise correct mais mixte"
    if score >= 35:
        return "Profil entreprise fragile"
    return "Profil entreprise faible"


def generate_company_diagnosis(company_analysis: dict) -> str:
    scores = company_analysis.get("scores", {})
    composite = scores.get("company_score", 50)
    growth = scores.get("growth_score", 50)
    valuation = scores.get("valuation_score", 50)
    profitability = scores.get("profitability_score", 50)
    analysts = scores.get("analyst_score", 50)

    parts = [get_company_quality_label(composite) + "."]

    if growth >= 75:
        parts.append("La croissance est forte.")
    elif growth >= 55:
        parts.append("La croissance reste correcte.")
    else:
        parts.append("La croissance est faible ou irrégulière.")

    if profitability >= 75:
        parts.append("La rentabilité est robuste.")
    elif profitability >= 55:
        parts.append("La rentabilité est acceptable.")
    else:
        parts.append("La rentabilité est fragile.")

    if valuation >= 70:
        parts.append("La valorisation reste raisonnable au regard des métriques disponibles.")
    elif valuation >= 45:
        parts.append("La valorisation est exigeante mais pas forcément excessive si la croissance continue.")
    else:
        parts.append("La valorisation est tendue : privilégier les entrées sur repli.")

    if analysts >= 65:
        parts.append("Le consensus analyste est favorable.")
    elif analysts >= 45:
        parts.append("Le consensus analyste est neutre à modérément positif.")
    else:
        parts.append("Le consensus analyste est peu favorable ou insuffisamment robuste.")

    return " ".join(parts)



def generate_forward_diagnosis(forward: dict) -> str:
    parts = []

    bias = forward.get("forward_bias", "Forward incomplet")
    parts.append(f"Lecture forward : {bias}.")

    revenue_growth = forward.get("revenue_growth_forward")
    earnings_growth = forward.get("earnings_growth_forward")
    forward_discount = forward.get("forward_pe_discount")
    target_upside = forward.get("target_mean_upside")

    if revenue_growth is not None:
        if revenue_growth >= 0.15:
            parts.append("La croissance attendue du chiffre d'affaires reste forte.")
        elif revenue_growth >= 0:
            parts.append("La croissance attendue du chiffre d'affaires reste positive mais modérée.")
        else:
            parts.append("La croissance attendue du chiffre d'affaires est négative.")

    if earnings_growth is not None:
        if earnings_growth >= 0.20:
            parts.append("La croissance attendue des bénéfices est élevée.")
        elif earnings_growth >= 0:
            parts.append("Les bénéfices attendus progressent modérément.")
        else:
            parts.append("Les bénéfices attendus se dégradent.")

    if forward_discount is not None:
        if forward_discount <= -0.25:
            parts.append("Le Forward P/E est nettement inférieur au Trailing P/E, ce qui implique une amélioration attendue des résultats.")
        elif forward_discount > 0:
            parts.append("Le Forward P/E n'offre pas de détente évidente face au Trailing P/E.")

    if target_upside is not None:
        if target_upside >= 0.15:
            parts.append("Le target moyen des analystes implique encore un potentiel notable.")
        elif target_upside < 0:
            parts.append("Le target moyen implique un potentiel négatif.")

    return " ".join(parts)


def score_analysts(metrics: dict) -> int:
    score = 50

    upside_mean = metrics.get("upside_mean")
    downside_low = metrics.get("downside_low")
    recommendation_mean = metrics.get("recommendation_mean")
    number_of_analysts = metrics.get("number_of_analysts")

    if upside_mean is not None:
        if upside_mean >= 0.25:
            score += 20
        elif upside_mean >= 0.10:
            score += 12
        elif upside_mean >= 0.03:
            score += 5
        elif upside_mean < 0:
            score -= 12

    if downside_low is not None:
        if downside_low <= -0.30:
            score -= 8
        elif downside_low <= -0.15:
            score -= 4

    if recommendation_mean is not None:
        if recommendation_mean <= 1.8:
            score += 15
        elif recommendation_mean <= 2.5:
            score += 8
        elif recommendation_mean <= 3.2:
            score += 0
        else:
            score -= 10

    if number_of_analysts is not None:
        if number_of_analysts >= 25:
            score += 5
        elif number_of_analysts >= 10:
            score += 3
        elif number_of_analysts <= 3:
            score -= 3

    return int(clamp(round(score)))


# ============================================================
