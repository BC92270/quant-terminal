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
from .fundamentals import *
from .analysts import *
from .financials import *

# NEWS / CATALYST INTELLIGENCE CENTER — V1
# ============================================================

NEWS_UNIVERSAL_THEMES = {
    "Earnings / Guidance": [
        "earnings", "eps", "revenue", "sales", "profit", "margin", "guidance",
        "outlook", "forecast", "beat", "miss", "quarter", "full year",
        "fy", "q1", "q2", "q3", "q4", "results"
    ],
    "Analyst / Rating": [
        "analyst", "upgrade", "downgrade", "initiates", "coverage",
        "price target", "target price", "rating", "buy", "sell", "hold",
        "outperform", "underperform", "overweight", "neutral"
    ],
    "Commercial Momentum": [
        "contract", "deal", "customer", "order", "backlog", "partnership",
        "agreement", "distribution", "supply agreement", "wins", "awarded",
        "deployment", "rollout"
    ],
    "Product / Innovation": [
        "launch", "product", "platform", "technology", "innovation",
        "ai", "artificial intelligence", "cloud", "software", "chip",
        "model", "service", "feature"
    ],
    "M&A / Strategic Action": [
        "acquisition", "merger", "takeover", "divestiture", "spinoff",
        "spin-off", "joint venture", "strategic review", "sale of",
        "minority stake", "investment"
    ],
    "Regulatory / Legal": [
        "regulator", "regulatory", "sec", "doj", "ftc", "lawsuit",
        "litigation", "probe", "investigation", "approval", "ban",
        "fine", "settlement", "antitrust", "compliance"
    ],
    "Capital Allocation": [
        "buyback", "repurchase", "dividend", "split", "capital return",
        "shareholder return", "offering", "secondary offering",
        "issuance", "dilution"
    ],
    "Balance Sheet / Financing": [
        "debt", "bond", "notes", "credit facility", "refinancing",
        "liquidity", "cash", "leverage", "rating agency", "maturity"
    ],
    "Management / Governance": [
        "ceo", "cfo", "chairman", "board", "management", "resigns",
        "appointed", "succession", "activist", "governance"
    ],
    "Macro / Rates / FX": [
        "inflation", "rates", "fed", "ecb", "dollar", "fx", "currency",
        "macro", "recession", "gdp", "consumer spending", "yields"
    ],
    "Geopolitics / Supply Chain": [
        "tariff", "sanction", "export control", "china", "taiwan",
        "supply chain", "shortage", "shipping", "war", "geopolitical"
    ],
    "Sector Read-through": [
        "peer", "sector", "industry", "competitor", "read-through",
        "demand", "pricing", "inventory", "cycle"
    ],
}

NEWS_SECTOR_THEMES = {
    "Semiconductors": {
        "AI / Accelerators": [
            "gpu", "accelerator", "ai chip", "hbm", "data center",
            "training", "inference", "cuda", "rack-scale"
        ],
        "Foundry / Capacity": [
            "foundry", "wafer", "capacity", "node", "tsmc",
            "advanced packaging", "cowo", "fab"
        ],
        "Memory / Cycle": [
            "dram", "nand", "memory", "hbm", "bit growth", "inventory correction"
        ],
        "Export Controls": [
            "export controls", "china restrictions", "license", "entity list"
        ],
    },
    "Software": {
        "ARR / Subscription": [
            "arr", "subscription", "saas", "renewal", "net retention",
            "nrr", "churn", "seat expansion"
        ],
        "Cloud / AI Monetization": [
            "cloud", "ai monetization", "copilot", "genai", "enterprise ai",
            "usage-based"
        ],
        "Cybersecurity": [
            "security", "cybersecurity", "breach", "zero trust", "endpoint"
        ],
    },
    "Banks": {
        "Credit Quality": [
            "loan loss", "provision", "credit quality", "delinquency",
            "charge-off", "npl", "non-performing"
        ],
        "Rates / NII": [
            "net interest income", "nii", "deposit beta", "yield curve",
            "interest margin"
        ],
        "Capital / Regulation": [
            "cet1", "stress test", "basel", "capital ratio", "buyback approval"
        ],
    },
    "Biotechnology": {
        "Clinical Trial": [
            "phase 1", "phase 2", "phase 3", "clinical trial", "endpoint",
            "primary endpoint", "data readout", "efficacy", "safety"
        ],
        "FDA / Approval": [
            "fda", "pdufa", "approval", "complete response letter",
            "crl", "fast track", "orphan drug"
        ],
        "Pipeline / Partnership": [
            "pipeline", "licensing", "collaboration", "milestone payment"
        ],
    },
    "Pharmaceuticals": {
        "Drug Launch": [
            "drug launch", "prescription", "label expansion", "indication",
            "blockbuster"
        ],
        "Patent / LOE": [
            "patent", "exclusivity", "loss of exclusivity", "generic",
            "biosimilar"
        ],
        "Regulatory": [
            "ema", "fda", "approval", "clinical", "safety warning"
        ],
    },
    "Energy": {
        "Oil / Gas Prices": [
            "oil", "gas", "brent", "wti", "lng", "natural gas",
            "production", "opec"
        ],
        "Reserve / Production": [
            "reserve", "drilling", "well", "production guidance",
            "capex"
        ],
        "Refining / Margins": [
            "refining", "crack spread", "margin", "downstream"
        ],
    },
    "Utilities": {
        "Rates / Regulation": [
            "rate case", "regulated return", "allowed roe", "commission",
            "grid investment"
        ],
        "Power Demand": [
            "electricity demand", "power demand", "data center power",
            "renewables", "nuclear"
        ],
    },
    "Industrials": {
        "Orders / Backlog": [
            "orders", "backlog", "book-to-bill", "industrial demand",
            "factory", "automation"
        ],
        "Supply Chain / Costs": [
            "input costs", "supply chain", "logistics", "inventory"
        ],
    },
    "Defense": {
        "Defense Contract": [
            "defense contract", "pentagon", "dod", "army", "navy",
            "air force", "missile", "radar"
        ],
        "Budget / Geopolitics": [
            "defense budget", "ukraine", "nato", "military spending"
        ],
    },
    "Consumer": {
        "Demand / Pricing": [
            "consumer demand", "pricing", "traffic", "same-store sales",
            "volume", "basket size"
        ],
        "Margins / Input Costs": [
            "gross margin", "input costs", "promotion", "inventory"
        ],
    },
    "Retail": {
        "Same Store Sales": [
            "same-store sales", "comparable sales", "traffic", "ticket",
            "inventory", "markdown"
        ],
        "E-commerce": [
            "online sales", "e-commerce", "digital sales", "marketplace"
        ],
    },
    "Automobiles": {
        "Deliveries / Production": [
            "deliveries", "production", "ev", "vehicle", "unit sales",
            "factory", "gigafactory"
        ],
        "Pricing / Margins": [
            "price cut", "incentives", "gross margin", "battery cost"
        ],
        "Autonomy / Software": [
            "autonomous", "robotaxi", "adas", "self-driving", "software"
        ],
    },
    "Real Estate": {
        "Rates / Cap Rates": [
            "cap rate", "occupancy", "rent growth", "leasing",
            "interest rates", "refinancing"
        ],
        "Asset Sales / Development": [
            "asset sale", "development", "portfolio", "reit"
        ],
    },
    "Telecom": {
        "Subscribers": [
            "subscriber", "churn", "arpu", "fiber", "wireless",
            "broadband"
        ],
        "Spectrum / Capex": [
            "spectrum", "5g", "network", "capex", "tower"
        ],
    },
    "Media": {
        "Streaming / Subscribers": [
            "streaming", "subscriber", "content", "advertising",
            "box office", "sports rights"
        ],
        "Advertising Cycle": [
            "ad market", "advertising", "linear tv", "cpm"
        ],
    },
    "Materials": {
        "Commodity Prices": [
            "copper", "lithium", "steel", "aluminum", "gold",
            "commodity", "mining"
        ],
        "Production / Costs": [
            "production", "mine", "ore", "grade", "cash cost"
        ],
    },
    "Transportation": {
        "Volumes / Pricing": [
            "freight", "volume", "yield", "load factor", "capacity",
            "shipping rates"
        ],
        "Fuel / Labor": [
            "fuel costs", "labor costs", "union", "strike"
        ],
    },
    "Insurance": {
        "Claims / Catastrophe": [
            "claims", "catastrophe", "loss ratio", "combined ratio",
            "hurricane", "wildfire"
        ],
        "Pricing / Reserves": [
            "premium growth", "reserves", "underwriting"
        ],
    },
    "Crypto": {
        "Token / Market Structure": [
            "bitcoin", "ethereum", "crypto", "stablecoin", "exchange",
            "token", "custody"
        ],
        "Regulatory": [
            "sec", "cftc", "spot etf", "regulation", "lawsuit"
        ],
    },
}


NEWS_POSITIVE_TERMS = [
    "beat", "beats", "raise", "raises", "raised", "upgrade", "upgraded",
    "strong", "growth", "record", "surge", "accelerate", "accelerates",
    "profit rises", "higher", "outperform", "approval", "wins",
    "contract", "expands", "partnership", "buyback", "dividend increase"
]

NEWS_NEGATIVE_TERMS = [
    "miss", "misses", "cut", "cuts", "lower", "downgrade", "downgraded",
    "weak", "decline", "falls", "drops", "lawsuit", "probe",
    "investigation", "ban", "fine", "warning", "delay", "loss",
    "restructuring", "layoffs", "dilution", "offering", "bankruptcy"
]


def _news_clean_text(value) -> str:
    try:
        if value is None or pd.isna(value):
            return ""
    except Exception:
        if value is None:
            return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _news_parse_date(value):
    if value is None:
        return pd.NaT

    try:
        if isinstance(value, (int, float)) and value > 1000000000:
            return pd.to_datetime(value, unit="s", errors="coerce")
    except Exception:
        pass

    return pd.to_datetime(value, errors="coerce")


def _news_now_utc_naive():
    now = pd.Timestamp.utcnow()
    try:
        return now.tz_convert(None)
    except Exception:
        try:
            return now.tz_localize(None)
        except Exception:
            return pd.Timestamp(datetime.utcnow())


def _news_sector_key(sector: str = "", industry: str = "") -> str:
    text = f"{sector or ''} {industry or ''}".lower()

    checks = [
        ("Semiconductors", ["semiconductor", "chip", "semi", "gpu"]),
        ("Software", ["software", "saas", "cloud", "application"]),
        ("Banks", ["bank", "financial services", "capital markets"]),
        ("Biotechnology", ["biotech", "biotechnology"]),
        ("Pharmaceuticals", ["pharma", "drug manufacturer", "pharmaceutical"]),
        ("Energy", ["energy", "oil", "gas", "exploration", "lng"]),
        ("Utilities", ["utilities", "utility", "electric", "power"]),
        ("Industrials", ["industrial", "machinery", "automation"]),
        ("Defense", ["defense", "aerospace"]),
        ("Consumer", ["consumer defensive", "consumer staples", "consumer discretionary"]),
        ("Retail", ["retail", "apparel", "department store"]),
        ("Automobiles", ["auto", "automobile", "vehicle", "ev"]),
        ("Real Estate", ["real estate", "reit"]),
        ("Telecom", ["telecom", "communication services", "wireless"]),
        ("Media", ["media", "entertainment", "streaming"]),
        ("Materials", ["materials", "mining", "metals", "chemical"]),
        ("Transportation", ["transportation", "airline", "shipping", "railroad", "logistics"]),
        ("Insurance", ["insurance"]),
        ("Crypto", ["crypto", "blockchain", "digital asset"]),
    ]

    for key, words in checks:
        if any(w in text for w in words):
            return key

    return "General"


def _news_keyword_hits(text: str, keywords: list) -> list:
    text_l = text.lower()
    return [kw for kw in keywords if kw.lower() in text_l]


def _news_contains_token(text: str, token: str) -> bool:
    token = _news_clean_text(token).lower()

    if not token:
        return False

    try:
        return bool(re.search(rf"\b{re.escape(token)}\b", text.lower()))
    except Exception:
        return token in text.lower()


def _news_company_aliases(ticker: str = "", company_name: str = "") -> list[str]:
    aliases = []

    ticker = _news_clean_text(ticker).upper()
    company_name = _news_clean_text(company_name)

    if ticker:
        aliases.append(ticker)

    if company_name:
        aliases.append(company_name)

        cleaned = re.sub(
            r"\b(inc|inc\.|corp|corp\.|corporation|company|co\.|ltd|limited|plc|class a|common stock)\b",
            "",
            company_name,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        if cleaned:
            aliases.append(cleaned)

        first_word = cleaned.split(" ")[0] if cleaned else ""
        if len(first_word) >= 4:
            aliases.append(first_word)

    aliases = [a.strip() for a in aliases if a and len(a.strip()) >= 2]

    # Déduplication conservatrice
    out = []
    seen = set()

    for alias in aliases:
        key = alias.lower()
        if key not in seen:
            out.append(alias)
            seen.add(key)

    return out


def _news_relevance_analysis(
    title: str,
    summary: str,
    ticker: str = "",
    company_name: str = "",
    sector: str = "",
    industry: str = "",
) -> dict:
    """
    Classification de pertinence plus stricte.

    Objectif :
    - Direct = le ticker / nom société est dans le titre.
    - Sector Context = news sectorielle ou mention société seulement dans le résumé.
    - Macro Context = macro / géopolitique / rates / réglementation large.
    - Weak / Excluded = bruit trop éloigné.

    Correction clé :
    Une news du type "Seagate and Western Digital..." qui mentionne Nvidia
    seulement dans le résumé ne doit plus compter comme Direct NVDA.
    """
    title_text = _news_clean_text(title).lower()
    summary_text = _news_clean_text(summary).lower()
    full_text = f"{title_text} {summary_text}".strip()

    aliases = _news_company_aliases(ticker, company_name)
    ticker_clean = _news_clean_text(ticker).upper()

    title_hits = []
    summary_hits = []

    for alias in aliases:
        alias_clean = _news_clean_text(alias)

        if not alias_clean:
            continue

        is_short_ticker = (
            alias_clean.upper() == ticker_clean
            and len(alias_clean) <= 2
        )

        if is_short_ticker:
            if _news_contains_token(title_text, alias_clean):
                title_hits.append(alias_clean)
            if _news_contains_token(summary_text, alias_clean):
                summary_hits.append(alias_clean)
            continue

        if _news_contains_token(title_text, alias_clean):
            title_hits.append(alias_clean)

        if _news_contains_token(summary_text, alias_clean):
            summary_hits.append(alias_clean)

    title_hits = list(dict.fromkeys(title_hits))
    summary_hits = list(dict.fromkeys(summary_hits))

    sector_key = _news_sector_key(sector, industry)

    sector_keywords = []
    for words in NEWS_SECTOR_THEMES.get(sector_key, {}).values():
        sector_keywords.extend(words)

    sector_hits = _news_keyword_hits(full_text, sector_keywords)

    macro_terms = [
        "fed", "rates", "interest rates", "inflation", "cpi", "ppi",
        "treasury", "dollar", "china", "tariff", "tariffs",
        "export controls", "regulation", "antitrust", "doj",
        "sec", "geopolitical", "recession", "yield", "yields"
    ]

    macro_hits = _news_keyword_hits(full_text, macro_terms)

    market_noise_terms = [
        "personal finance", "your money", "retirement", "etf", "fund",
        "dividend fund", "reit", "crypto", "bitcoin", "mortgage",
        "credit card", "savings account", "best stocks to buy",
        "millionaire", "net worth"
    ]

    noise_hits = _news_keyword_hits(full_text, market_noise_terms)

    direct_title = len(title_hits) > 0
    mentioned_only = len(summary_hits) > 0 and not direct_title
    has_sector_context = len(sector_hits) > 0
    has_macro_context = len(macro_hits) > 0

    if direct_title:
        relevance_type = "Direct"
        relevance_score = 84

    elif mentioned_only and has_sector_context:
        relevance_type = "Sector Context"
        relevance_score = 52

    elif mentioned_only:
        relevance_type = "Sector Context"
        relevance_score = 46

    elif has_sector_context:
        relevance_type = "Sector Context"
        relevance_score = 42

    elif has_macro_context:
        relevance_type = "Macro Context"
        relevance_score = 28

    else:
        relevance_type = "Weak / Excluded"
        relevance_score = 5

    if sector_hits:
        relevance_score += min(12, len(sector_hits) * 3)

    if macro_hits:
        relevance_score += min(6, len(macro_hits) * 2)

    if noise_hits and relevance_type != "Direct":
        relevance_score -= min(30, len(noise_hits) * 10)

    if relevance_type == "Sector Context":
        relevance_score = min(relevance_score, 68)

    if relevance_type == "Macro Context":
        relevance_score = min(relevance_score, 48)

    if relevance_type == "Weak / Excluded":
        relevance_score = min(relevance_score, 20)

    relevance_score = int(clamp(relevance_score, 0, 100))

    return {
        "relevance_type": relevance_type,
        "relevance_score": relevance_score,
        "direct_hits": ", ".join(title_hits[:5]),
        "context_hits": ", ".join((summary_hits + sector_hits + macro_hits)[:8]),
    }


def _news_classify_theme(title: str, summary: str, sector: str = "", industry: str = "") -> dict:
    text = f"{title} {summary}".lower()
    sector_key = _news_sector_key(sector, industry)

    candidates = []

    for theme, keywords in NEWS_UNIVERSAL_THEMES.items():
        hits = _news_keyword_hits(text, keywords)
        if hits:
            candidates.append({
                "theme": theme,
                "subtheme": theme,
                "score": len(hits),
                "hits": hits,
                "type": "Universal",
            })

    sector_map = NEWS_SECTOR_THEMES.get(sector_key, {})
    for subtheme, keywords in sector_map.items():
        hits = _news_keyword_hits(text, keywords)
        if hits:
            candidates.append({
                "theme": sector_key,
                "subtheme": subtheme,
                "score": len(hits) + 1,
                "hits": hits,
                "type": "Sector",
            })

    if not candidates:
        return {
            "theme": "General Market News",
            "subtheme": "Unclassified",
            "theme_score": 0,
            "matched_keywords": "",
            "theme_type": "Fallback",
        }

    best = sorted(candidates, key=lambda x: x["score"], reverse=True)[0]

    return {
        "theme": best["theme"],
        "subtheme": best["subtheme"],
        "theme_score": best["score"],
        "matched_keywords": ", ".join(best["hits"][:6]),
        "theme_type": best["type"],
    }


def _news_sentiment(title: str, summary: str) -> dict:
    text = f"{title} {summary}".lower()

    pos_hits = _news_keyword_hits(text, NEWS_POSITIVE_TERMS)
    neg_hits = _news_keyword_hits(text, NEWS_NEGATIVE_TERMS)

    raw = len(pos_hits) - len(neg_hits)
    score = max(-100, min(100, raw * 22))

    if score >= 22:
        label = "Bullish"
    elif score <= -22:
        label = "Bearish"
    else:
        label = "Neutral"

    return {
        "sentiment": label,
        "sentiment_score": score,
        "positive_hits": ", ".join(pos_hits[:5]),
        "negative_hits": ", ".join(neg_hits[:5]),
    }


def _news_source_score(source: str) -> int:
    source_l = _news_clean_text(source).lower()

    if not source_l:
        return 40

    tier_1 = ["reuters", "bloomberg", "wall street journal", "wsj", "financial times", "ft.com"]
    tier_2 = ["cnbc", "ap", "associated press", "marketwatch", "barron's", "barrons"]
    tier_3 = ["yahoo", "seeking alpha", "investorplace", "benzinga", "zacks"]
    official = ["sec", "company", "press release", "globenewswire", "pr newswire", "business wire"]

    if any(x in source_l for x in official):
        return 85
    if any(x in source_l for x in tier_1):
        return 90
    if any(x in source_l for x in tier_2):
        return 75
    if any(x in source_l for x in tier_3):
        return 60

    return 50


def _news_impact_score(row: dict) -> dict:
    """
    Scoring catalyst plus institutionnel :
    - score fort possible seulement si news Direct ou catalyst très clair ;
    - score plafonné pour Sector Context / Macro Context ;
    - évite que des news contextuelles montent à 80+ comme des news directes.
    """
    theme_score = safe_float(row.get("Theme Score"), 0) or 0
    sentiment_score = abs(safe_float(row.get("Sentiment Score"), 0) or 0)
    source_score = safe_float(row.get("Source Score"), 50) or 50
    age_days = safe_float(row.get("Age Days"), 30) or 30
    relevance_score = safe_float(row.get("Relevance Score"), 0) or 0
    relevance_type = str(row.get("Relevance Type", ""))

    recency_score = 0
    if age_days <= 1:
        recency_score = 22
    elif age_days <= 2:
        recency_score = 19
    elif age_days <= 7:
        recency_score = 14
    elif age_days <= 30:
        recency_score = 8
    elif age_days <= 90:
        recency_score = 4

    text = f"{row.get('Title', '')} {row.get('Summary', '')}".lower()

    high_impact_terms = [
        "guidance", "outlook", "earnings", "eps", "revenue", "margin",
        "contract", "order", "backlog", "partnership", "customer",
        "acquisition", "merger", "approval", "fda", "downgrade",
        "upgrade", "price target", "investigation", "lawsuit",
        "buyback", "dividend", "offering", "dilution",
        "restructuring", "antitrust", "probe", "export controls",
        "tariff", "tariffs", "data center", "ai accelerator",
        "forecast", "supply shortage", "pricing power"
    ]

    event_hits = _news_keyword_hits(text, high_impact_terms)
    event_boost = min(18, len(event_hits) * 5)

    if relevance_type == "Direct":
        relevance_adjustment = 16
        relevance_cap = 100
    elif relevance_type == "Sector Context":
        relevance_adjustment = 2
        relevance_cap = 72
    elif relevance_type == "Macro Context":
        relevance_adjustment = -4
        relevance_cap = 58
    else:
        relevance_adjustment = -28
        relevance_cap = 35

    score = 10
    score += min(20, theme_score * 4.5)
    score += min(14, sentiment_score * 0.18)
    score += recency_score
    score += min(10, source_score * 0.10)
    score += min(16, relevance_score * 0.16)
    score += event_boost
    score += relevance_adjustment

    score = int(round(score))
    score = int(clamp(score, 0, relevance_cap))

    if score >= 75:
        label = "High"
    elif score >= 55:
        label = "Medium"
    else:
        label = "Low"

    return {
        "catalyst_score": score,
        "impact": label,
    }


def _news_flatten_record(record: dict) -> dict:
    if not isinstance(record, dict):
        return {}

    out = dict(record)

    content = record.get("content")
    if isinstance(content, dict):
        provider = content.get("provider") or {}
        if isinstance(provider, dict):
            out["source"] = out.get("source") or provider.get("displayName") or provider.get("name")

        out["title"] = out.get("title") or content.get("title")
        out["summary"] = out.get("summary") or content.get("summary")
        out["url"] = out.get("url") or content.get("canonicalUrl", {}).get("url") if isinstance(content.get("canonicalUrl"), dict) else out.get("url")
        out["publishedDate"] = out.get("publishedDate") or content.get("pubDate") or content.get("displayTime")

    return out


def _news_to_dataframe(news_payload) -> pd.DataFrame:
    if news_payload is None:
        return pd.DataFrame()

    if isinstance(news_payload, pd.DataFrame):
        records = news_payload.to_dict("records")
    elif isinstance(news_payload, list):
        records = news_payload
    elif isinstance(news_payload, dict):
        if isinstance(news_payload.get("articles"), list):
            records = news_payload.get("articles")
        elif isinstance(news_payload.get("news"), list):
            records = news_payload.get("news")
        elif isinstance(news_payload.get("data"), list):
            records = news_payload.get("data")
        else:
            records = [news_payload]
    else:
        return pd.DataFrame()

    clean_records = []

    for rec in records:
        rec = _news_flatten_record(rec)

        title = (
            rec.get("title")
            or rec.get("Title")
            or rec.get("headline")
            or rec.get("Titre")
            or rec.get("newsTitle")
            or rec.get("Catégorie")
            or "News"
        )

        summary = (
            rec.get("summary")
            or rec.get("Summary")
            or rec.get("text")
            or rec.get("content")
            or rec.get("description")
            or rec.get("Brief")
            or rec.get("Résumé")
            or ""
        )

        source = (
            rec.get("source")
            or rec.get("site")
            or rec.get("publisher")
            or rec.get("provider")
            or rec.get("Source")
            or ""
        )

        date_value = (
            rec.get("publishedDate")
            or rec.get("published_at")
            or rec.get("datetime")
            or rec.get("date")
            or rec.get("providerPublishTime")
            or rec.get("Date")
        )

        url = rec.get("url") or rec.get("link") or rec.get("article_url") or ""

        clean_records.append({
            "Date": _news_parse_date(date_value),
            "Title": _news_clean_text(title),
            "Summary": _news_clean_text(summary),
            "Source": _news_clean_text(source),
            "URL": _news_clean_text(url),
        })

    df = pd.DataFrame(clean_records)

    if df.empty:
        return df

    df = df[df["Title"].astype(str).str.len() > 0].copy()

    if df.empty:
        return df

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

    now = _news_now_utc_naive()
    df["Date"] = df["Date"].fillna(now)

    try:
        df["Date"] = df["Date"].dt.tz_localize(None)
    except Exception:
        pass

    df["Dedup Key"] = (
        df["Title"]
        .astype(str)
        .str.lower()
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )

    df = df.drop_duplicates(subset=["Dedup Key"], keep="first")
    df = df.sort_values("Date", ascending=False).reset_index(drop=True)

    return df


def build_news_intelligence_frame(
    news_payload,
    sector: str = "",
    industry: str = "",
    ticker: str = "",
    company_name: str = "",
) -> pd.DataFrame:
    df = _news_to_dataframe(news_payload)

    if df.empty:
        return df

    now = _news_now_utc_naive()

    df["Age Days"] = (now - df["Date"]).dt.total_seconds() / 86400
    df["Age Days"] = df["Age Days"].clip(lower=0)

    classifications = []
    sentiments = []
    relevances = []
    impacts = []

    for _, row in df.iterrows():
        cls = _news_classify_theme(row["Title"], row["Summary"], sector, industry)
        sen = _news_sentiment(row["Title"], row["Summary"])
        rel = _news_relevance_analysis(
            row["Title"],
            row["Summary"],
            ticker=ticker,
            company_name=company_name,
            sector=sector,
            industry=industry,
        )

        base = {
            **row.to_dict(),
            "Theme Score": cls["theme_score"],
            "Sentiment Score": sen["sentiment_score"],
            "Source Score": _news_source_score(row["Source"]),
            "Relevance Score": rel["relevance_score"],
            "Relevance Type": rel["relevance_type"],
        }

        impact = _news_impact_score(base)

        classifications.append(cls)
        sentiments.append(sen)
        relevances.append(rel)
        impacts.append(impact)

    cls_df = pd.DataFrame(classifications)
    sen_df = pd.DataFrame(sentiments)
    rel_df = pd.DataFrame(relevances)
    imp_df = pd.DataFrame(impacts)

    df = pd.concat(
        [
            df.reset_index(drop=True),
            cls_df,
            sen_df,
            rel_df,
            imp_df,
        ],
        axis=1
    )

    df = df.rename(columns={
        "theme": "Catalyst Theme",
        "subtheme": "Catalyst Subtheme",
        "theme_score": "Theme Score",
        "matched_keywords": "Matched Keywords",
        "theme_type": "Theme Type",
        "sentiment": "Sentiment",
        "sentiment_score": "Sentiment Score",
        "relevance_type": "Relevance Type",
        "relevance_score": "Relevance Score",
        "direct_hits": "Direct Hits",
        "context_hits": "Context Hits",
        "catalyst_score": "Catalyst Score",
        "impact": "Impact",
    })

    df["Source Score"] = df["Source"].apply(_news_source_score)

    df["Recency"] = pd.cut(
        df["Age Days"],
        bins=[-1, 2, 7, 30, 90, 100000],
        labels=["0-2j", "3-7j", "8-30j", "31-90j", "90j+"],
    ).astype(str)

    df["Date Display"] = df["Date"].dt.strftime("%Y-%m-%d %H:%M")
    df["Date Short"] = df["Date"].dt.strftime("%Y-%m-%d")

    # Filtre prudent :
    # on retire les news faibles seulement s'il reste au moins une news exploitable.
    exploitable = df[
        df["Relevance Type"].isin(["Direct", "Sector Context", "Macro Context"])
    ].copy()

    if not exploitable.empty:
        df = exploitable

    df = df.sort_values(
        ["Catalyst Score", "Relevance Score", "Date"],
        ascending=[False, False, False]
    ).reset_index(drop=True)

    return df


NEWS_TIME_WINDOW_DAYS = {
    "24h": 1,
    "7j": 7,
    "30j": 30,
    "90j": 90,
    "1 an": 365,
}

NEWS_CORE_TIME_WINDOWS = ["24h", "7j", "30j"]
NEWS_DEEP_TIME_WINDOWS = ["90j", "1 an"]

def _news_limit_for_window(window_label: str) -> int:
    days = NEWS_TIME_WINDOW_DAYS.get(window_label, 30)

    if days <= 1:
        return 120
    if days <= 7:
        return 200
    if days <= 30:
        return 350
    if days <= 90:
        return 500
    return 750


def _news_payload_to_records(news_payload) -> list[dict]:
    if news_payload is None:
        return []

    if isinstance(news_payload, pd.DataFrame):
        return news_payload.to_dict("records")

    if isinstance(news_payload, list):
        return [x for x in news_payload if isinstance(x, dict)]

    if isinstance(news_payload, dict):
        for key in ["articles", "news", "data", "results", "items"]:
            value = news_payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]

        return [news_payload] if news_payload else []

    return []


def _news_merge_payloads(*payloads) -> list[dict]:
    rows = []

    for payload in payloads:
        rows.extend(_news_payload_to_records(payload))

    return rows


# ============================================================
# LOCAL NEWS ARCHIVE — persistent lightweight cache
# ============================================================

NEWS_ARCHIVE_DIR = ".quant_news_archive"
NEWS_ARCHIVE_MAX_RECORDS = 2500


def _news_archive_path(ticker: str) -> str:
    safe_ticker = re.sub(r"[^A-Z0-9_\-]", "", str(ticker or "").upper().strip())

    if not safe_ticker:
        safe_ticker = "UNKNOWN"

    return os.path.join(NEWS_ARCHIVE_DIR, f"{safe_ticker}_news_archive.json")


def _news_records_to_archive_records(records) -> list[dict]:
    """
    Convertit n'importe quel payload news en records stables :
    publishedDate / title / summary / source / url.

    Important :
    - ne touche pas au scoring ;
    - ne touche pas aux providers ;
    - sert seulement à conserver localement ce qui a déjà été vu.
    """
    rows = []

    for item in _news_payload_to_records(records):
        if not isinstance(item, dict):
            continue

        rec = _news_flatten_record(item)

        title = _news_clean_text(
            rec.get("title")
            or rec.get("headline")
            or rec.get("Title")
            or ""
        )

        if not title:
            continue

        summary = _news_clean_text(
            rec.get("summary")
            or rec.get("Summary")
            or rec.get("text")
            or rec.get("content")
            or rec.get("description")
            or ""
        )

        source = _news_clean_text(
            rec.get("source")
            or rec.get("site")
            or rec.get("publisher")
            or rec.get("provider")
            or rec.get("Source")
            or ""
        )

        url = _news_clean_text(
            rec.get("url")
            or rec.get("link")
            or rec.get("article_url")
            or rec.get("URL")
            or ""
        )

        date_value = (
            rec.get("publishedDate")
            or rec.get("published_at")
            or rec.get("datetime")
            or rec.get("date")
            or rec.get("providerPublishTime")
            or rec.get("Date")
        )

        date = _news_parse_date(date_value)

        if pd.isna(date):
            continue

        try:
            date = date.tz_localize(None)
        except Exception:
            pass

        rows.append({
            "publishedDate": pd.to_datetime(date).strftime("%Y-%m-%d %H:%M:%S"),
            "title": title,
            "summary": summary,
            "source": source or "Local Archive",
            "url": url,
        })

    return rows


def load_news_archive(ticker: str) -> list[dict]:
    path = _news_archive_path(ticker)

    if not os.path.exists(path):
        return []

    try:
        import json

        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        if isinstance(payload, list):
            return [x for x in payload if isinstance(x, dict)]

    except Exception:
        return []

    return []


def save_news_archive(ticker: str, *payloads) -> int:
    """
    Sauvegarde les news déjà vues, sans bloquer l'app si le filesystem refuse.

    Retourne le nombre total de lignes conservées.
    """
    if not ticker:
        return 0

    try:
        import json

        os.makedirs(NEWS_ARCHIVE_DIR, exist_ok=True)

        archive_rows = load_news_archive(ticker)

        for payload in payloads:
            archive_rows.extend(_news_records_to_archive_records(payload))

        if not archive_rows:
            return 0

        df = _news_to_dataframe(archive_rows)

        if df.empty:
            return 0

        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df[df["Date"].notna()].copy()

        if df.empty:
            return 0

        df = df.sort_values("Date", ascending=False)
        df = df.drop_duplicates(subset=["Dedup Key"], keep="first")
        df = df.head(NEWS_ARCHIVE_MAX_RECORDS)

        export_rows = []

        for _, row in df.iterrows():
            export_rows.append({
                "publishedDate": row["Date"].strftime("%Y-%m-%d %H:%M:%S"),
                "title": row.get("Title", ""),
                "summary": row.get("Summary", ""),
                "source": row.get("Source", "Local Archive"),
                "url": row.get("URL", ""),
            })

        with open(_news_archive_path(ticker), "w", encoding="utf-8") as f:
            json.dump(export_rows, f, ensure_ascii=False, indent=2)

        return len(export_rows)

    except Exception:
        return 0


@st.cache_data(ttl=900, show_spinner=False)
def get_yahoo_stock_news_window(
    ticker: str,
    company_name: str = "",
    window_label: str = "30j",
    cache_version: str = "yahoo_news_window_v1"
) -> list[dict]:
    """
    Provider complémentaire Yahoo Finance.

    Objectif :
    - Ne pas remplacer FMP.
    - Enrichir les fenêtres 7j / 30j / 90j / 1 an quand FMP retourne peu de lignes.
    - Utiliser deux sources gratuites :
      1) Yahoo Finance Search API
      2) Yahoo Finance RSS headline
    """

    ticker = str(ticker or "").upper().strip()
    company_name = _news_clean_text(company_name)

    if not ticker and not company_name:
        return []

    days = NEWS_TIME_WINDOW_DAYS.get(window_label, 30)
    now = _news_now_utc_naive()
    cutoff = now - pd.Timedelta(days=days)

    rows = []
    seen = set()

    def append_record(record: dict, fallback_source: str = "Yahoo Finance"):
        if not isinstance(record, dict):
            return

        rec = _news_flatten_record(record)

        title = _news_clean_text(
            rec.get("title")
            or rec.get("headline")
            or rec.get("Title")
            or ""
        )

        if not title:
            return

        summary = _news_clean_text(
            rec.get("summary")
            or rec.get("text")
            or rec.get("description")
            or rec.get("content")
            or ""
        )

        source = _news_clean_text(
            rec.get("source")
            or rec.get("publisher")
            or rec.get("provider")
            or fallback_source
        )

        url = _news_clean_text(
            rec.get("url")
            or rec.get("link")
            or rec.get("article_url")
            or ""
        )

        date_value = (
            rec.get("publishedDate")
            or rec.get("providerPublishTime")
            or rec.get("published_at")
            or rec.get("pubDate")
            or rec.get("date")
            or rec.get("datetime")
        )

        date = _news_parse_date(date_value)

        if pd.isna(date):
            return

        try:
            date = date.tz_localize(None)
        except Exception:
            pass

        if date < cutoff or date > now + pd.Timedelta(days=1):
            return

        key = url.lower() if url else title.lower()

        if key in seen:
            return

        seen.add(key)

        rows.append({
            "publishedDate": date.strftime("%Y-%m-%d %H:%M:%S"),
            "title": title,
            "summary": summary,
            "source": source or fallback_source,
            "url": url,
        })

    # ------------------------------------------------------------
    # 1) Yahoo Finance Search API
    # ------------------------------------------------------------
    search_queries = []

    if ticker:
        search_queries.append(ticker)

    if company_name:
        search_queries.append(company_name)

        cleaned_name = re.sub(
            r"\b(inc|inc\.|corp|corp\.|corporation|company|co\.|ltd|limited|plc|class a|common stock)\b",
            "",
            company_name,
            flags=re.IGNORECASE,
        )
        cleaned_name = re.sub(r"\s+", " ", cleaned_name).strip()

        if cleaned_name and cleaned_name != company_name:
            search_queries.append(cleaned_name)

    search_queries = list(dict.fromkeys([q for q in search_queries if q]))[:3]

    for query in search_queries:
        try:
            response = requests.get(
                "https://query2.finance.yahoo.com/v1/finance/search",
                params={
                    "q": query,
                    "quotesCount": 0,
                    "newsCount": 100,
                    "enableFuzzyQuery": False,
                    "quotesQueryId": "tss_match_phrase_query",
                    "newsQueryId": "news_cie_vespa",
                    "listsCount": 0,
                },
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0 QuantTerminal/1.0"},
            )

            if response.status_code != 200:
                continue

            payload = response.json()

            if not isinstance(payload, dict):
                continue

            for article in payload.get("news", []) or []:
                append_record(article, fallback_source="Yahoo Finance Search")

        except Exception:
            continue

    # ------------------------------------------------------------
    # 2) Yahoo Finance RSS headline
    # ------------------------------------------------------------
    if ticker:
        try:
            response = requests.get(
                "https://feeds.finance.yahoo.com/rss/2.0/headline",
                params={
                    "s": ticker,
                    "region": "US",
                    "lang": "en-US",
                },
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0 QuantTerminal/1.0"},
            )

            if response.status_code == 200 and response.content:
                root = ET.fromstring(response.content)

                for item in root.findall(".//item"):
                    title = item.findtext("title") or ""
                    description = item.findtext("description") or ""
                    link = item.findtext("link") or ""
                    pub_date = item.findtext("pubDate") or ""

                    append_record(
                        {
                            "title": title,
                            "summary": description,
                            "url": link,
                            "publishedDate": pub_date,
                            "source": "Yahoo Finance RSS",
                        },
                        fallback_source="Yahoo Finance RSS",
                    )

        except Exception:
            pass

    if not rows:
        return []

    tmp_df = _news_to_dataframe(rows)

    if tmp_df.empty:
        return rows

    tmp_df["Date"] = pd.to_datetime(tmp_df["Date"], errors="coerce")
    tmp_df = tmp_df[tmp_df["Date"].notna()].copy()

    if tmp_df.empty:
        return rows

    try:
        tmp_df["Date"] = tmp_df["Date"].dt.tz_localize(None)
    except Exception:
        pass

    tmp_df = tmp_df[tmp_df["Date"] >= cutoff].copy()

    if tmp_df.empty:
        return []

    tmp_df = tmp_df.sort_values("Date", ascending=False)
    tmp_df = tmp_df.head(_news_limit_for_window(window_label))

    return tmp_df.to_dict("records")


@st.cache_data(ttl=900, show_spinner=False)
def get_finnhub_company_news_window(
    ticker: str,
    window_label: str = "30j",
    cache_version: str = "finnhub_company_news_v1"
) -> list[dict]:
    """
    Provider complémentaire Finnhub Company News.

    Objectif :
    - Ajouter une vraie source ticker-directe.
    - Ne pas remplacer FMP / Yahoo / GDELT.
    - Utiliser l'infra Finnhub déjà présente dans le code.
    """

    ticker = str(ticker or "").upper().strip()

    if not ticker or not finnhub_enabled():
        return []

    days = NEWS_TIME_WINDOW_DAYS.get(window_label, 30)
    now = _news_now_utc_naive()
    cutoff = now - pd.Timedelta(days=days)

    from_date = cutoff.strftime("%Y-%m-%d")
    to_date = (now + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    try:
        payload = finnhub_get_json(
            "company-news",
            {
                "symbol": ticker,
                "from": from_date,
                "to": to_date,
            }
        )
    except Exception:
        payload = []

    records = finnhub_rows(payload)

    if not records:
        return []

    rows = []
    seen = set()

    for item in records:
        if not isinstance(item, dict):
            continue

        title = _news_clean_text(
            item.get("headline")
            or item.get("title")
            or ""
        )

        if not title:
            continue

        summary = _news_clean_text(
            item.get("summary")
            or item.get("description")
            or ""
        )

        source = _news_clean_text(
            item.get("source")
            or "Finnhub"
        )

        url = _news_clean_text(
            item.get("url")
            or item.get("link")
            or ""
        )

        date_value = (
            item.get("datetime")
            or item.get("publishedDate")
            or item.get("date")
        )

        date = _news_parse_date(date_value)

        if pd.isna(date):
            continue

        try:
            date = date.tz_localize(None)
        except Exception:
            pass

        if date < cutoff or date > now + pd.Timedelta(days=1):
            continue

        key = url.lower() if url else title.lower()

        if key in seen:
            continue

        seen.add(key)

        rows.append({
            "publishedDate": date.strftime("%Y-%m-%d %H:%M:%S"),
            "title": title,
            "summary": summary,
            "source": source or "Finnhub",
            "url": url,
        })

    if not rows:
        return []

    tmp_df = _news_to_dataframe(rows)

    if tmp_df.empty:
        return rows

    tmp_df["Date"] = pd.to_datetime(tmp_df["Date"], errors="coerce")
    tmp_df = tmp_df[tmp_df["Date"].notna()].copy()

    if tmp_df.empty:
        return rows

    try:
        tmp_df["Date"] = tmp_df["Date"].dt.tz_localize(None)
    except Exception:
        pass

    tmp_df = tmp_df[tmp_df["Date"] >= cutoff].copy()

    if tmp_df.empty:
        return []

    tmp_df = tmp_df.sort_values("Date", ascending=False)
    tmp_df = tmp_df.head(_news_limit_for_window(window_label))

    return tmp_df.to_dict("records")


@st.cache_data(ttl=900, show_spinner=False)
def get_fmp_stock_news_window(
    ticker: str,
    window_label: str,
    cache_version: str = "news_window_chunked_v4"
) -> list[dict]:
    """
    Fetch news réellement dépendant de la fenêtre choisie.

    Pourquoi cette version :
    - Certains endpoints news renvoient seulement les 10/20 derniers articles,
      même avec limit/page/from/to.
    - Donc 24h, 7j, 30j et 1 an peuvent afficher le même univers.
    - On découpe la fenêtre en tranches de dates pour forcer la récupération
      d'articles plus anciens.
    - On garde FMP + yfinance, sans toucher au reste du pipeline.
    """
    ticker = str(ticker or "").upper().strip()

    if not ticker:
        return []

    days = NEWS_TIME_WINDOW_DAYS.get(window_label, 30)
    now = _news_now_utc_naive()
    target_limit = _news_limit_for_window(window_label)

    base_v3 = "https://financialmodelingprep.com/api/v3"
    base_stable = "https://financialmodelingprep.com/stable"

    rows = []
    seen = set()

    def record_key(record: dict) -> str:
        rec = _news_flatten_record(record)

        title = _news_clean_text(
            rec.get("title")
            or rec.get("headline")
            or rec.get("Title")
            or ""
        ).lower()

        url = _news_clean_text(
            rec.get("url")
            or rec.get("link")
            or rec.get("article_url")
            or ""
        ).lower()

        date_value = (
            rec.get("publishedDate")
            or rec.get("published_at")
            or rec.get("datetime")
            or rec.get("date")
            or rec.get("providerPublishTime")
            or rec.get("Date")
            or ""
        )

        date_text = str(date_value)[:19]

        if url:
            return f"url::{url}"

        return f"title::{title}::{date_text}"

    def append_unique(candidate_rows: list[dict]) -> int:
        added = 0

        for item in candidate_rows or []:
            if not isinstance(item, dict):
                continue

            key = record_key(item)

            if not key or key in seen:
                continue

            seen.add(key)
            rows.append(item)
            added += 1

        return added

    def record_mentions_ticker(record: dict) -> bool:
        rec = _news_flatten_record(record)

        symbol_fields = [
            rec.get("symbol"),
            rec.get("symbols"),
            rec.get("ticker"),
            rec.get("tickers"),
            rec.get("relatedTickers"),
        ]

        for raw_symbols in symbol_fields:
            if isinstance(raw_symbols, list):
                symbols = [str(x).upper().strip() for x in raw_symbols]
            else:
                symbols = re.split(r"[,\s;|]+", str(raw_symbols or "").upper())

            if ticker in symbols:
                return True

        title = _news_clean_text(
            rec.get("title")
            or rec.get("headline")
            or rec.get("Title")
            or ""
        )

        summary = _news_clean_text(
            rec.get("summary")
            or rec.get("text")
            or rec.get("content")
            or rec.get("description")
            or ""
        )

        blob = f"{title} {summary}".upper()

        try:
            return bool(re.search(rf"\b{re.escape(ticker)}\b", blob))
        except Exception:
            return ticker in blob

    def date_chunks_for_window() -> list[tuple[str, str]]:
        """
        Découpe latest -> oldest.

        Objectif :
        - 24h : 1 bloc.
        - 7j : blocs courts.
        - 30j : blocs de 5 jours.
        - 90j : blocs de 15 jours.
        - 1 an : blocs mensuels environ.
        """
        if days <= 1:
            chunk_days = 1
        elif days <= 7:
            chunk_days = 2
        elif days <= 30:
            chunk_days = 5
        elif days <= 90:
            chunk_days = 15
        else:
            chunk_days = 30

        oldest = pd.Timestamp(now - pd.Timedelta(days=days + 1)).normalize()
        cursor_end = pd.Timestamp(now).normalize()

        chunks = []

        while cursor_end >= oldest:
            cursor_start = max(
                oldest,
                cursor_end - pd.Timedelta(days=chunk_days - 1)
            )

            chunks.append((
                cursor_start.strftime("%Y-%m-%d"),
                cursor_end.strftime("%Y-%m-%d"),
            ))

            cursor_end = cursor_start - pd.Timedelta(days=1)

        return chunks

    def fetch_endpoint_pages(url: str, base_params: dict, max_pages: int = 1):
        empty_pages = 0

        for page in range(max_pages):
            params = dict(base_params)
            params["page"] = page

            candidate_rows = fmp_rows(fmp_get_json(url, params))

            if not candidate_rows:
                empty_pages += 1
                if empty_pages >= 1:
                    break
                continue

            append_unique(candidate_rows)

            if len(rows) >= target_limit:
                break

    if fmp_enabled():
        chunks = date_chunks_for_window()

        # Plus la fenêtre est courte, plus on peut tenter une pagination légère.
        # Pour 1 an, on privilégie les chunks plutôt que beaucoup de pages.
        max_pages_per_chunk = 2 if days <= 30 else 1
        limit_per_call = 100

        for from_date, to_date in chunks:
            # Endpoint legacy/v3 : souvent le plus utile pour from/to.
            fetch_endpoint_pages(
                f"{base_v3}/stock_news",
                {
                    "tickers": ticker,
                    "from": from_date,
                    "to": to_date,
                    "limit": limit_per_call,
                },
                max_pages=max_pages_per_chunk,
            )

            # Endpoint stable search stock news.
            fetch_endpoint_pages(
                f"{base_stable}/news/stock",
                {
                    "symbols": ticker,
                    "from": from_date,
                    "to": to_date,
                    "limit": limit_per_call,
                },
                max_pages=max_pages_per_chunk,
            )

            if len(rows) >= target_limit:
                break

        # Fallback sans date : utile si from/to est ignoré par le plan/API.
        # On le garde après les chunks pour ne pas polluer les anciennes fenêtres.
        if len(rows) < min(20, target_limit):
            for page in range(0, 5):
                fetch_endpoint_pages(
                    f"{base_v3}/stock_news",
                    {
                        "tickers": ticker,
                        "limit": limit_per_call,
                    },
                    max_pages=1,
                )

                fetch_endpoint_pages(
                    f"{base_stable}/news/stock",
                    {
                        "symbols": ticker,
                        "limit": limit_per_call,
                    },
                    max_pages=1,
                )

                if len(rows) >= min(50, target_limit):
                    break

        # Fallback global latest : seulement pour récupérer des mentions ticker.
        # Ce flux est souvent récent, donc il ne résout pas l'historique seul,
        # mais il enrichit les fenêtres courtes.
        if len(rows) < min(20, target_limit):
            latest_pages = 3 if days <= 7 else 6

            for page in range(latest_pages):
                latest_rows = fmp_rows(
                    fmp_get_json(
                        f"{base_stable}/news/stock-latest",
                        {
                            "page": page,
                            "limit": limit_per_call,
                        },
                    )
                )

                if not latest_rows:
                    break

                ticker_rows = [
                    item for item in latest_rows
                    if isinstance(item, dict) and record_mentions_ticker(item)
                ]

                append_unique(ticker_rows)

                if len(rows) >= min(50, target_limit):
                    break

    # yfinance reste en appoint, pas en remplacement.
    try:
        yf_rows = yf.Ticker(ticker).news or []
        append_unique([x for x in yf_rows if isinstance(x, dict)])
    except Exception:
        pass

    if not rows:
        return []

    tmp_df = _news_to_dataframe(rows)

    if tmp_df.empty:
        return rows

    tmp_df["Date"] = pd.to_datetime(tmp_df["Date"], errors="coerce")
    tmp_df = tmp_df[tmp_df["Date"].notna()].copy()

    if tmp_df.empty:
        return rows

    try:
        tmp_df["Date"] = tmp_df["Date"].dt.tz_localize(None)
    except Exception:
        pass

    cutoff = now - pd.Timedelta(days=days)

    tmp_df = tmp_df[tmp_df["Date"] >= cutoff].copy()

    if tmp_df.empty:
        return []

    tmp_df = tmp_df.sort_values("Date", ascending=False)
    tmp_df = tmp_df.head(target_limit)

    return tmp_df.to_dict("records")


@st.cache_data(ttl=1800, show_spinner=False)
def get_gdelt_stock_news_window(
    ticker: str,
    company_name: str = "",
    sector: str = "",
    industry: str = "",
    window_label: str = "30j",
    cache_version: str = "gdelt_news_v1"
) -> list[dict]:
    """
    Provider news historique complémentaire via GDELT DOC API.

    Objectif :
    - Corriger le problème où FMP / yfinance renvoient seulement quelques news récentes.
    - Rendre les fenêtres 7j / 30j / 90j / 1 an réellement différentes.
    - Ne pas écraser FMP : GDELT enrichit seulement l'univers de news.
    """

    ticker = str(ticker or "").upper().strip()
    company_name = _news_clean_text(company_name)

    if not ticker and not company_name:
        return []

    days = NEWS_TIME_WINDOW_DAYS.get(window_label, 30)
    now = _news_now_utc_naive()
    cutoff = now - pd.Timedelta(days=days)

    aliases = _news_company_aliases(ticker, company_name)

    # Garde-fou : éviter les tickers trop courts ou ambigus seuls.
    cleaned_aliases = []

    for alias in aliases:
        alias = _news_clean_text(alias)

        if not alias:
            continue

        if alias.upper() == ticker and len(alias) <= 2:
            continue

        if len(alias) < 3:
            continue

        cleaned_aliases.append(alias)

    if not cleaned_aliases and company_name:
        cleaned_aliases.append(company_name)

    if not cleaned_aliases and ticker:
        cleaned_aliases.append(ticker)

    # Limite la requête pour éviter une query GDELT trop longue.
    cleaned_aliases = list(dict.fromkeys(cleaned_aliases))[:4]

    if not cleaned_aliases:
        return []

    query = " OR ".join([f'"{alias}"' for alias in cleaned_aliases])

    # Pour les tickers très connus, on garde le ticker dans la requête.
    if ticker and len(ticker) >= 3 and ticker not in cleaned_aliases:
        query = f'({query}) OR "{ticker}"'

    endpoint = "https://api.gdeltproject.org/api/v2/doc/doc"

    if days <= 1:
        chunk_days = 1
        max_records_per_chunk = 75
        hard_limit = 120
    elif days <= 7:
        chunk_days = 2
        max_records_per_chunk = 75
        hard_limit = 180
    elif days <= 30:
        chunk_days = 7
        max_records_per_chunk = 100
        hard_limit = 250
    elif days <= 90:
        chunk_days = 15
        max_records_per_chunk = 100
        hard_limit = 350
    else:
        chunk_days = 30
        max_records_per_chunk = 100
        hard_limit = 500

    def gdelt_datetime(value) -> str:
        ts = pd.Timestamp(value)

        try:
            ts = ts.tz_localize(None)
        except Exception:
            pass

        return ts.strftime("%Y%m%d%H%M%S")

    def parse_gdelt_date(value):
        if value is None:
            return pd.NaT

        text = str(value).strip()

        try:
            cleaned = text.replace("T", "").replace("Z", "")
            if re.fullmatch(r"\d{14}", cleaned):
                return pd.to_datetime(cleaned, format="%Y%m%d%H%M%S", errors="coerce")
        except Exception:
            pass

        return pd.to_datetime(value, errors="coerce")

    rows = []
    seen = set()

    def append_article(article: dict):
        if not isinstance(article, dict):
            return

        title = _news_clean_text(
            article.get("title")
            or article.get("name")
            or ""
        )

        if not title:
            return

        url = _news_clean_text(
            article.get("url")
            or article.get("link")
            or article.get("id")
            or ""
        )

        date_value = (
            article.get("seendate")
            or article.get("seenDate")
            or article.get("date")
            or article.get("publishedDate")
        )

        date = parse_gdelt_date(date_value)

        if pd.isna(date):
            return

        try:
            date = date.tz_localize(None)
        except Exception:
            pass

        if date < cutoff or date > now + pd.Timedelta(days=1):
            return

        domain = _news_clean_text(
            article.get("domain")
            or article.get("source")
            or article.get("sourceDomain")
            or "GDELT"
        )

        source_country = _news_clean_text(article.get("sourceCountry") or "")
        language = _news_clean_text(article.get("language") or "")

        source = f"GDELT · {domain}" if domain else "GDELT"

        if source_country:
            source = f"{source} · {source_country}"

        summary_parts = []

        if language:
            summary_parts.append(f"Langue détectée : {language}")

        summary_parts.append(title)

        key = url.lower() if url else title.lower()

        if key in seen:
            return

        seen.add(key)

        rows.append({
            "publishedDate": date.strftime("%Y-%m-%d %H:%M:%S"),
            "title": title,
            "summary": " — ".join(summary_parts),
            "source": source,
            "url": url,
        })

    cursor_end = now
    oldest = cutoff

    while cursor_end >= oldest and len(rows) < hard_limit:
        cursor_start = max(oldest, cursor_end - pd.Timedelta(days=chunk_days))

        params = {
            "query": query,
            "mode": "artlist",
            "format": "json",
            "sort": "hybridrel",
            "maxrecords": max_records_per_chunk,
            "startdatetime": gdelt_datetime(cursor_start),
            "enddatetime": gdelt_datetime(cursor_end),
        }

        try:
            response = requests.get(
                endpoint,
                params=params,
                timeout=15,
                headers={"User-Agent": "QuantTerminal/1.0"}
            )

            if response.status_code == 200:
                payload = response.json()

                articles = []

                if isinstance(payload, dict):
                    articles = payload.get("articles") or payload.get("items") or []

                if isinstance(articles, list):
                    for article in articles:
                        append_article(article)

        except Exception:
            pass

        cursor_end = cursor_start - pd.Timedelta(seconds=1)

    if not rows:
        return []

    tmp_df = _news_to_dataframe(rows)

    if tmp_df.empty:
        return rows

    tmp_df["Date"] = pd.to_datetime(tmp_df["Date"], errors="coerce")
    tmp_df = tmp_df[tmp_df["Date"].notna()].copy()

    if tmp_df.empty:
        return rows

    try:
        tmp_df["Date"] = tmp_df["Date"].dt.tz_localize(None)
    except Exception:
        pass

    tmp_df = tmp_df[tmp_df["Date"] >= cutoff].copy()

    if tmp_df.empty:
        return []

    tmp_df = tmp_df.sort_values("Date", ascending=False)
    tmp_df = tmp_df.head(hard_limit)

    return tmp_df.to_dict("records")


def filter_news_by_time_window(news_df: pd.DataFrame, window_label: str) -> pd.DataFrame:
    if news_df is None or news_df.empty:
        return pd.DataFrame()

    days = NEWS_TIME_WINDOW_DAYS.get(window_label, 30)

    out = news_df.copy()
    out["Date"] = pd.to_datetime(out["Date"], errors="coerce")

    now = _news_now_utc_naive()
    cutoff = now - pd.Timedelta(days=days)

    out = out[
        out["Date"].notna()
        & (out["Date"] >= cutoff)
    ].copy()

    return out.sort_values(
        ["Catalyst Score", "Relevance Score", "Date"],
        ascending=[False, False, False]
    ).reset_index(drop=True)


def _news_fmt_pct_from_ratio(value):
    value = safe_float(value)
    if value is None:
        return "N/A"
    return f"{value:.2%}"


def _news_signal_summary(df: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "avg_score": None,
            "top_theme": "N/A",
            "bullish_count": 0,
            "bearish_count": 0,
            "high_impact_count": 0,
            "high_neutral_count": 0,
            "latest_date": "N/A",
        }

    top_theme = "N/A"
    try:
        top_theme = (
            df.groupby("Catalyst Theme")["Catalyst Score"]
            .sum()
            .sort_values(ascending=False)
            .index[0]
        )
    except Exception:
        pass

    high_neutral_count = int(
        ((df["Impact"] == "High") & (df["Sentiment"] == "Neutral")).sum()
    )

    return {
        "avg_score": safe_float(df["Catalyst Score"].mean()),
        "top_theme": top_theme,
        "bullish_count": int((df["Sentiment"] == "Bullish").sum()),
        "bearish_count": int((df["Sentiment"] == "Bearish").sum()),
        "high_impact_count": int((df["Impact"] == "High").sum()),
        "high_neutral_count": high_neutral_count,
        "latest_date": df["Date"].max().strftime("%Y-%m-%d") if not df["Date"].isna().all() else "N/A",
    }


def render_latest_news_intelligence_center_v1(
    news_payload,
    sector: str = "",
    industry: str = "",
    ticker: str = "",
    company_name: str = "",
    key_prefix: str = "news_intelligence_v1",
):
    
    st.subheader("Latest News — Catalyst Intelligence Center")

    deep_history_scan = st.checkbox(
        "Deep history scan",
        value=False,
        help="Active les fenêtres 90j / 1 an. Plus lent car le module charge davantage d'historique provider.",
        key=f"{key_prefix}_deep_history_scan",
    )

    time_window_options = NEWS_CORE_TIME_WINDOWS.copy()

    if deep_history_scan:
        time_window_options += NEWS_DEEP_TIME_WINDOWS

    default_index = 0

    if deep_history_scan and "90j" in time_window_options:
        default_index = time_window_options.index("90j")

    time_window = st.radio(
        "Période news",
        time_window_options,
        index=default_index,
        horizontal=True,
        key=f"{key_prefix}_time_window_deep" if deep_history_scan else f"{key_prefix}_time_window_core",
    )

    deep_history_mode = time_window in NEWS_DEEP_TIME_WINDOWS

    fmp_window_payload = []
    yahoo_window_payload = []
    finnhub_window_payload = []
    gdelt_window_payload = []

    try:
        fmp_window_payload = get_fmp_stock_news_window(ticker, time_window)
    except Exception:
        fmp_window_payload = []

    try:
        yahoo_window_payload = get_yahoo_stock_news_window(
            ticker=ticker,
            company_name=company_name,
            window_label=time_window,
        )
    except Exception:
        yahoo_window_payload = []

    try:
        finnhub_window_payload = get_finnhub_company_news_window(
            ticker=ticker,
            window_label=time_window,
        )
    except Exception:
        finnhub_window_payload = []
    # GDELT est réservé au Deep history scan.
    # Objectif : garder 24h / 7j / 30j rapides et éviter de ralentir le module standard.
    if deep_history_mode:
        try:
            gdelt_window_payload = get_gdelt_stock_news_window(
                ticker=ticker,
                company_name=company_name,
                sector=sector,
                industry=industry,
                window_label=time_window,
            )
        except Exception:
            gdelt_window_payload = []
    else:
        gdelt_window_payload = []

    provider_window_payload = _news_merge_payloads(
        fmp_window_payload,
        yahoo_window_payload,
        finnhub_window_payload,
        gdelt_window_payload,
    )

    # ------------------------------------------------------------
    # Local archive merge
    # ------------------------------------------------------------
    # certains providers ne renvoient plus les news vues quelques jours avant.
    # L'archive locale permet de garder les news déjà observées par le terminal
    # et de remplir correctement la timeline 7j / 30j sans ajouter d'appels API.
    archived_news_payload = load_news_archive(ticker)

    combined_news_payload = _news_merge_payloads(
        provider_window_payload,
        archived_news_payload,
        news_payload,
    )

    news_df = build_news_intelligence_frame(
        combined_news_payload,
        sector=sector,
        industry=industry,
        ticker=ticker,
        company_name=company_name,
    )

    archive_count = save_news_archive(
        ticker,
        provider_window_payload,
        news_payload,
    )

    if news_df.empty:
        st.info("Aucune news exploitable disponible pour ce ticker.")
        return

    loaded_exploitable_count = len(news_df)
    provider_loaded_count = len(_news_payload_to_records(provider_window_payload))
    fmp_loaded_count = len(_news_payload_to_records(fmp_window_payload))
    yahoo_loaded_count = len(_news_payload_to_records(yahoo_window_payload))
    finnhub_loaded_count = len(_news_payload_to_records(finnhub_window_payload))
    gdelt_loaded_count = len(_news_payload_to_records(gdelt_window_payload))
    base_loaded_count = len(_news_payload_to_records(news_payload))
    archive_loaded_count = len(_news_payload_to_records(archived_news_payload))

    filtered_news_df = filter_news_by_time_window(news_df, time_window)

    if filtered_news_df.empty:
        st.info(f"Aucune news exploitable sur la période sélectionnée : {time_window}.")

        with st.expander("Voir les news disponibles hors filtre", expanded=False):
            fallback_df = news_df.copy()

            if "Date Display" in fallback_df.columns:
                fallback_df = fallback_df[[
                    "Date Display",
                    "Title",
                    "Relevance Type",
                    "Catalyst Theme",
                    "Sentiment",
                    "Impact",
                    "Catalyst Score",
                    "Source",
                ]].rename(columns={
                    "Date Display": "Date",
                    "Title": "News",
                    "Relevance Type": "Pertinence",
                    "Catalyst Theme": "Theme",
                    "Catalyst Score": "Score catalyst",
                })

                st.dataframe(fallback_df.head(20), use_container_width=True, hide_index=True)

        return

    news_df = filtered_news_df

    if len(news_df) < 5 and time_window != "24h":
        st.warning(
            f"Couverture news faible sur {time_window} : seulement {len(news_df)} news exploitables. "
            "Le provider principal semble limiter l'historique disponible. "
            "Yahoo/GDELT sont utilisés en complément, mais le module ne crée pas de fausses news."
        )

    summary = _news_signal_summary(news_df)

    direct_count = int((news_df["Relevance Type"] == "Direct").sum()) if "Relevance Type" in news_df.columns else 0
    context_count = int(news_df["Relevance Type"].isin(["Sector Context", "Macro Context"]).sum()) if "Relevance Type" in news_df.columns else 0

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Dernière news", summary["latest_date"])
    c2.metric("Direct ticker news", direct_count)
    c3.metric("Context news", context_count)
    c4.metric(
        "B / Be / HI Neutral",
        f"{summary['bullish_count']} / {summary['bearish_count']} / {summary['high_neutral_count']}"
    )
    c5.metric("Top theme", summary["top_theme"])
    c6.metric(
        "Avg Catalyst Score",
        "N/A" if summary["avg_score"] is None else f"{summary['avg_score']:.0f}/100"
    )

    history_mode_note = (
        "Deep history scan actif : 90j / 1 an peuvent être plus lents et dépendent fortement de l'historique réellement disponible chez les providers."
        if deep_history_mode
        else
        "Mode rapide actif : 24h / 7j / 30j uniquement. Active Deep history scan pour 90j / 1 an."
    )

    st.caption(
        f"Fenêtre {time_window} : {len(news_df)} article(s) après filtre. "
        f"Univers chargé avant filtre : {loaded_exploitable_count} exploitable(s), "
        f"{provider_loaded_count} ligne(s) provider fenêtre "
        f"({fmp_loaded_count} FMP/YF + {yahoo_loaded_count} Yahoo + "
        f"{finnhub_loaded_count} Finnhub + {gdelt_loaded_count} GDELT), "
        f"{base_loaded_count} ligne(s) cache initial, "
        f"{archive_loaded_count} ligne(s) archive locale, "
        f"{archive_count} ligne(s) conservées en archive. "
        f"{history_mode_note} "
        "Les news contextuelles sont volontairement plafonnées pour ne pas être confondues avec des catalysts directs."
    )
    

    with st.expander("Table de lecture news", expanded=False):
        reading_df = news_df[[
            "Date Display",
            "Title",
            "Relevance Type",
            "Relevance Score",
            "Catalyst Theme",
            "Catalyst Subtheme",
            "Sentiment",
            "Impact",
            "Catalyst Score",
            "Source",
            "Recency",
        ]].copy()

        reading_df = reading_df.rename(columns={
            "Date Display": "Date",
            "Title": "News",
            "Relevance Type": "Pertinence",
            "Relevance Score": "Score pertinence",
            "Catalyst Theme": "Theme",
            "Catalyst Subtheme": "Sous-thème",
            "Catalyst Score": "Score catalyst",
        })

        st.dataframe(reading_df.head(20), use_container_width=True, hide_index=True)

    view = st.radio(
        "Vue news",
        ["Briefing", "Catalyst Map", "Timeline", "Sources"],
        horizontal=True,
        key=f"{key_prefix}_view",
    )

    if view == "Briefing":
        st.markdown("### Briefing priorisé")

        # Nombre de news affichables dans le briefing priorisé.
        # On ne limite plus artificiellement à 10.
        # Garde-fou UI : max 50 pour éviter une page énorme.
        available_news_count = int(len(news_df))
        max_allowed = min(available_news_count, 50)

        if max_allowed <= 0:
            st.info("Aucune news disponible dans cette fenêtre.")
            return

        # Options propres : 5 / 10 / 15 / 20 / 25 / 30 / 40 / 50 selon disponibilité.
        candidate_options = [5, 10, 15, 20, 25, 30, 40, 50]
        briefing_options = [x for x in candidate_options if x <= max_allowed]

        # Si moins de 5 news, on met directement le nombre disponible.
        if not briefing_options:
            briefing_options = [max_allowed]

        # Toujours inclure exactement le max disponible si ce n'est pas déjà dedans.
        if max_allowed not in briefing_options:
            briefing_options.append(max_allowed)

        briefing_options = sorted(set(briefing_options))

        # Par défaut : 10 si possible, sinon max disponible.
        default_limit = min(10, max_allowed)

        if default_limit not in briefing_options:
            lower_or_equal = [x for x in briefing_options if x <= default_limit]
            default_limit = lower_or_equal[-1] if lower_or_equal else briefing_options[-1]

        # Streamlit select_slider peut bugger avec une seule option.
        if len(briefing_options) == 1:
            briefing_limit = briefing_options[0]
            st.caption(f"{briefing_limit} news disponible(s) dans cette fenêtre.")
        else:
            briefing_limit = st.select_slider(
                "Nombre de news affichées",
                options=briefing_options,
                value=default_limit,
                key=f"{key_prefix}_briefing_limit_{time_window}_{available_news_count}",
            )

        briefing_df = news_df.head(briefing_limit).copy()

        compact_rows = []

        for _, row in briefing_df.iterrows():
            compact_rows.append({
                "Date": row.get("Date Display", "N/A"),
                "Score": f"{safe_float(row.get('Catalyst Score'), 0):.0f}/100",
                "Impact": row.get("Impact", "N/A"),
                "Pertinence": row.get("Relevance Type", "N/A"),
                "Theme": row.get("Catalyst Theme", "N/A"),
                "Source": row.get("Source", "N/A"),
                "Titre": row.get("Title", "News"),
            })

        compact_df = pd.DataFrame(compact_rows)

        st.dataframe(
            compact_df,
            use_container_width=True,
            hide_index=True,
            height=min(720, 88 + 38 * len(compact_df))
        )

        with st.expander("Détails du briefing", expanded=False):
            for _, row in briefing_df.iterrows():
                score = safe_float(row.get("Catalyst Score"), 0) or 0
                date_display = row.get("Date Display", "N/A")
                impact = row.get("Impact", "N/A")
                sentiment = row.get("Sentiment", "N/A")
                relevance_type = row.get("Relevance Type", "N/A")
                source = row.get("Source", "N/A")
                title = row.get("Title", "News")
                theme = row.get("Catalyst Theme", "N/A")
                subtheme = row.get("Catalyst Subtheme", "N/A")
                keywords = row.get("Matched Keywords", "")
                direct_hits = row.get("Direct Hits", "")
                context_hits = row.get("Context Hits", "")
                summary_text = _news_clean_text(row.get("Summary", ""))

                header = (
                    f"{date_display} · {score:.0f}/100 · {impact} · "
                    f"{sentiment} · {relevance_type} · {source}"
                )

                with st.expander(f"{header} — {str(title)[:110]}", expanded=False):
                    if sentiment == "Bullish":
                        interpretation = "Lecture positive : catalyseur favorable, à confirmer par le prix, les volumes ou la prochaine guidance."
                    elif sentiment == "Bearish":
                        interpretation = "Lecture négative : risque ou pression potentielle sur les attentes."
                    else:
                        if impact == "High":
                            interpretation = "Lecture neutre mais importante : catalyst informationnel fort, sans biais directionnel suffisant."
                        else:
                            interpretation = "Lecture neutre : information utile, sans signal directionnel fort à elle seule."

                    st.markdown(f"**Titre :** {title}")
                    st.markdown(f"**Lecture :** {interpretation}")
                    st.markdown(f"**Thème :** {theme} / {subtheme}")
                    st.markdown(f"**Pertinence :** {relevance_type}")

                    if summary_text:
                        st.markdown(f"**Résumé :** {summary_text[:650]}")

                    if direct_hits:
                        st.markdown(f"**Mentions directes détectées :** {direct_hits}")

                    if context_hits:
                        st.markdown(f"**Contexte détecté :** {context_hits}")

                    if keywords:
                        st.markdown(f"**Mots-clés catalyst :** {keywords}")

    elif view == "Catalyst Map":
        st.markdown("### Catalyst Map — thèmes dominants")

        theme_df = (
            news_df
            .groupby(["Catalyst Theme", "Catalyst Subtheme"], as_index=False)
            .agg(
                News_Count=("Title", "count"),
                Avg_Catalyst_Score=("Catalyst Score", "mean"),
                Max_Catalyst_Score=("Catalyst Score", "max"),
                Bullish_Count=("Sentiment", lambda s: int((s == "Bullish").sum())),
                Bearish_Count=("Sentiment", lambda s: int((s == "Bearish").sum())),
                Direct_Count=("Relevance Type", lambda s: int((s == "Direct").sum())),
                Context_Count=("Relevance Type", lambda s: int(s.isin(["Sector Context", "Macro Context"]).sum())),
            )
        )

        theme_df["Avg_Catalyst_Score"] = theme_df["Avg_Catalyst_Score"].round(1)
        theme_df["Catalyst Bucket"] = (
            theme_df["Catalyst Theme"].astype(str)
            + " → "
            + theme_df["Catalyst Subtheme"].astype(str)
        )

        theme_df = theme_df.sort_values("Avg_Catalyst_Score", ascending=True)

        fig = go.Figure()

        fig.add_trace(go.Bar(
            x=theme_df["Avg_Catalyst_Score"],
            y=theme_df["Catalyst Bucket"],
            orientation="h",
            text=theme_df["News_Count"].apply(lambda x: f"n={x}"),
            textposition="outside",
            customdata=np.stack([
                theme_df["Catalyst Theme"],
                theme_df["Catalyst Subtheme"],
                theme_df["News_Count"],
                theme_df["Bullish_Count"],
                theme_df["Bearish_Count"],
                theme_df["Direct_Count"],
                theme_df["Context_Count"],
                theme_df["Max_Catalyst_Score"],
            ], axis=-1),
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Theme: %{customdata[0]}<br>"
                "Sous-thème: %{customdata[1]}<br>"
                "Avg score: %{x:.1f}/100<br>"
                "Max score: %{customdata[7]:.0f}/100<br>"
                "News count: %{customdata[2]}<br>"
                "Direct: %{customdata[5]}<br>"
                "Context: %{customdata[6]}<br>"
                "Bullish: %{customdata[3]}<br>"
                "Bearish: %{customdata[4]}"
                "<extra></extra>"
            ),
            name="Catalyst score",
        ))

        fig.add_vline(x=50, line_dash="dash", annotation_text="Neutre")
        fig.add_vline(x=75, line_dash="dot", annotation_text="High")

        fig.update_layout(
            height=max(420, 110 + 58 * len(theme_df)),
            title="Catalyst Map — intensité moyenne par thème",
            xaxis_title="Catalyst Score",
            yaxis_title="Theme → sous-thème",
            margin=dict(l=20, r=20, t=70, b=40),
        )

        st.plotly_chart(fig, use_container_width=True)

        display_theme_df = theme_df.sort_values("Max_Catalyst_Score", ascending=False).rename(columns={
            "Catalyst Theme": "Theme",
            "Catalyst Subtheme": "Sous-thème",
            "News_Count": "Nombre de news",
            "Avg_Catalyst_Score": "Score moyen",
            "Max_Catalyst_Score": "Score max",
            "Bullish_Count": "Bullish",
            "Bearish_Count": "Bearish",
            "Direct_Count": "Direct",
            "Context_Count": "Context",
        })

        display_theme_df = display_theme_df[[
            "Theme",
            "Sous-thème",
            "Nombre de news",
            "Score moyen",
            "Score max",
            "Direct",
            "Context",
            "Bullish",
            "Bearish",
        ]]

        st.dataframe(display_theme_df, use_container_width=True, hide_index=True)

    elif view == "Timeline":
        st.markdown("### Timeline — évolution des catalysts")

        timeline_df = news_df.sort_values("Date").copy()
        timeline_df["Date"] = pd.to_datetime(timeline_df["Date"], errors="coerce")
        timeline_df = timeline_df.dropna(subset=["Date"]).copy()

        if timeline_df.empty:
            st.info("Aucune date exploitable pour construire la timeline.")
            return

        window_days = NEWS_TIME_WINDOW_DAYS.get(time_window, 30)

        timeline_window_end = _news_now_utc_naive()
        timeline_window_start = timeline_window_end - pd.Timedelta(days=window_days)

        # Sécurité si un provider renvoie une news légèrement future vs horloge serveur.
        latest_point = timeline_df["Date"].max()

        if latest_point is not None and not pd.isna(latest_point) and latest_point > timeline_window_end:
            timeline_window_end = latest_point
            timeline_window_start = timeline_window_end - pd.Timedelta(days=window_days)

        timeline_x_range = [
            timeline_window_start.to_pydatetime(),
            timeline_window_end.to_pydatetime(),
        ]

        unique_days = timeline_df["Date"].dt.date.nunique()

        fig = go.Figure()

        # Ranking seulement pour le vrai cas 24h mono-journée.
        # Sur 7j / 30j / 90j / 1 an, on force une vraie timeline même si les points sont concentrés.
        if time_window == "24h" and unique_days <= 1:
            ranking_df = timeline_df.sort_values(
                ["Catalyst Score", "Relevance Score"],
                ascending=[True, True]
            ).copy()

            label_series = ranking_df["Title"].astype(str).str.slice(0, 75)

            fig.add_trace(go.Bar(
                x=ranking_df["Catalyst Score"],
                y=label_series,
                orientation="h",
                text=ranking_df["Catalyst Score"].apply(lambda x: f"{x:.0f}/100"),
                textposition="auto",
                customdata=np.stack([
                    ranking_df["Sentiment"],
                    ranking_df["Impact"],
                    ranking_df["Relevance Type"],
                    ranking_df["Catalyst Theme"],
                    ranking_df["Source"],
                ], axis=-1),
                hovertemplate=(
                    "<b>%{y}</b><br>"
                    "Score: %{x}/100<br>"
                    "Sentiment: %{customdata[0]}<br>"
                    "Impact: %{customdata[1]}<br>"
                    "Pertinence: %{customdata[2]}<br>"
                    "Theme: %{customdata[3]}<br>"
                    "Source: %{customdata[4]}"
                    "<extra></extra>"
                ),
                name="Catalyst Score",
            ))

            fig.add_vline(x=75, line_dash="dash", annotation_text="High impact")
            fig.add_vline(x=50, line_dash="dot", annotation_text="Neutre")

            fig.update_layout(
                height=max(420, 120 + 42 * len(ranking_df)),
                title="Catalysts du jour — ranking par score",
                xaxis_title="Catalyst Score",
                yaxis_title="News",
                margin=dict(l=20, r=20, t=70, b=40),
            )

        else:
            fig.add_trace(go.Scatter(
                x=timeline_df["Date"],
                y=timeline_df["Catalyst Score"],
                mode="markers",
                text=timeline_df["Title"],
                customdata=np.stack([
                    timeline_df["Sentiment"],
                    timeline_df["Impact"],
                    timeline_df["Relevance Type"],
                    timeline_df["Catalyst Theme"],
                    timeline_df["Catalyst Subtheme"],
                    timeline_df["Source"],
                ], axis=-1),
                marker=dict(
                    size=np.clip(timeline_df["Catalyst Score"] / 4, 8, 22),
                    opacity=0.85,
                ),
                hovertemplate=(
                    "<b>%{text}</b><br>"
                    "Date: %{x|%Y-%m-%d %H:%M}<br>"
                    "Score: %{y}/100<br>"
                    "Sentiment: %{customdata[0]}<br>"
                    "Impact: %{customdata[1]}<br>"
                    "Pertinence: %{customdata[2]}<br>"
                    "Theme: %{customdata[3]}<br>"
                    "Sous-thème: %{customdata[4]}<br>"
                    "Source: %{customdata[5]}"
                    "<extra></extra>"
                ),
                name="Catalyst Score",
            ))

            # ------------------------------------------------------------
            # Timeline labels — titres visibles sur le graphe
            # ------------------------------------------------------------
            # Les points restent tous affichés.
            # On affiche seulement les labels des news les plus importantes
            # pour éviter de rendre le graphe illisible quand il y a 100+ news.
            max_timeline_labels = int(min(20, len(timeline_df)))

            if max_timeline_labels > 0:
                timeline_label_count = st.slider(
                    "Nombre de titres affichés sur la timeline",
                    min_value=0,
                    max_value=max_timeline_labels,
                    value=min(10, max_timeline_labels),
                    step=1,
                    key=f"news_timeline_label_count_{time_window}",
                )

                if timeline_label_count > 0:
                    label_df = timeline_df.copy()

                    impact_rank_map = {
                        "High": 3,
                        "Medium": 2,
                        "Low": 1,
                    }

                    label_df["_ImpactRank"] = (
                        label_df["Impact"]
                        .astype(str)
                        .map(impact_rank_map)
                        .fillna(0)
                    )

                    label_df["_DirectRank"] = (
                        label_df["Relevance Type"]
                        .astype(str)
                        .eq("Direct")
                        .astype(int)
                    )

                    label_df = (
                        label_df
                        .sort_values(
                            ["Catalyst Score", "_DirectRank", "_ImpactRank", "Date"],
                            ascending=[False, False, False, False]
                        )
                        .head(timeline_label_count)
                        .sort_values("Date")
                        .copy()
                    )

                    def compact_timeline_title(value, max_len=58):
                        text = str(value or "").strip()
                        if len(text) <= max_len:
                            return text
                        return text[:max_len - 1] + "…"

                    label_df["_TimelineLabel"] = label_df["Title"].apply(compact_timeline_title)

                    text_positions = [
                        "top center",
                        "bottom center",
                        "middle right",
                        "middle left",
                    ]

                    label_df["_TextPosition"] = [
                        text_positions[i % len(text_positions)]
                        for i in range(len(label_df))
                    ]

                    fig.add_trace(go.Scatter(
                        x=label_df["Date"],
                        y=label_df["Catalyst Score"],
                        mode="text",
                        text=label_df["_TimelineLabel"],
                        textposition=label_df["_TextPosition"],
                        textfont=dict(size=10),
                        hoverinfo="skip",
                        showlegend=False,
                        cliponaxis=False,
                    ))

            fig.add_hline(y=75, line_dash="dash", annotation_text="High impact")
            fig.add_hline(y=50, line_dash="dot", annotation_text="Neutre")

            tick_format = "%H:%M\n%d %b" if window_days <= 1 else "%d %b"

            fig.update_layout(
                height=520,
                title=f"News Catalyst Timeline — événements discrets · fenêtre {time_window}",
                xaxis_title="Date",
                yaxis_title="Catalyst Score",
                xaxis=dict(
                    range=timeline_x_range,
                    tickformat=tick_format,
                    automargin=True,
                ),
                margin=dict(l=20, r=90, t=90, b=40),
            )

            st.caption(
                f"Timeline calée sur la fenêtre {time_window} : "
                f"{timeline_window_start.strftime('%Y-%m-%d %H:%M')} → "
                f"{timeline_window_end.strftime('%Y-%m-%d %H:%M')}. "
                "Les périodes sans news restent volontairement vides."
            )

        st.plotly_chart(fig, use_container_width=True)

    elif view == "Sources":
        st.markdown("### Sources — couverture et fiabilité")

        source_df = (
            news_df
            .groupby("Source", as_index=False)
            .agg(
                News_Count=("Title", "count"),
                Avg_Catalyst_Score=("Catalyst Score", "mean"),
                Source_Score=("Source Score", "mean"),
                Latest_Date=("Date", "max"),
            )
        )

        source_df["Avg_Catalyst_Score"] = source_df["Avg_Catalyst_Score"].round(1)
        source_df["Source_Score"] = source_df["Source_Score"].round(0).astype(int)
        source_df["Latest_Date"] = source_df["Latest_Date"].dt.strftime("%Y-%m-%d")
        source_df = source_df.sort_values(["Source_Score", "News_Count"], ascending=[False, False])

        fig = go.Figure()

        fig.add_trace(go.Bar(
            x=source_df["Source"],
            y=source_df["News_Count"],
            text=source_df["News_Count"],
            textposition="outside",
            customdata=np.stack([
                source_df["Avg_Catalyst_Score"],
                source_df["Source_Score"],
                source_df["Latest_Date"],
            ], axis=-1),
            hovertemplate=(
                "<b>%{x}</b><br>"
                "News count: %{y}<br>"
                "Avg catalyst score: %{customdata[0]}/100<br>"
                "Source score: %{customdata[1]}/100<br>"
                "Latest date: %{customdata[2]}"
                "<extra></extra>"
            ),
            name="News count",
        ))

        fig.update_layout(
            height=420,
            title="News coverage by source",
            xaxis_title="Source",
            yaxis_title="Nombre de news",
            margin=dict(l=20, r=20, t=70, b=80),
        )

        st.plotly_chart(fig, use_container_width=True)

        display_source_df = source_df.rename(columns={
            "Source": "Source",
            "News_Count": "Nombre de news",
            "Avg_Catalyst_Score": "Score catalyst moyen",
            "Source_Score": "Score source",
            "Latest_Date": "Dernière news",
        })

        st.dataframe(display_source_df, use_container_width=True, hide_index=True)


def render_latest_news_briefing_v6(company_analysis: dict, ticker: str):
    company_analysis = company_analysis if isinstance(company_analysis, dict) else {}

    profile_ctx = (
        company_analysis.get("profile")
        or company_analysis.get("asset_profile")
        or company_analysis.get("assetProfile")
        or {}
    )

    raw_ctx = company_analysis.get("raw_data", {})
    raw_ctx = raw_ctx if isinstance(raw_ctx, dict) else {}

    info_ctx = raw_ctx.get("info", {})
    info_ctx = info_ctx if isinstance(info_ctx, dict) else {}

    company_name = (
        profile_ctx.get("name")
        or profile_ctx.get("longName")
        or profile_ctx.get("shortName")
        or info_ctx.get("longName")
        or info_ctx.get("shortName")
        or ticker
    )

    sector = (
        company_analysis.get("sector")
        or profile_ctx.get("sector")
        or profile_ctx.get("Sector")
        or info_ctx.get("sector")
        or ""
    )

    industry = (
        company_analysis.get("industry")
        or profile_ctx.get("industry")
        or profile_ctx.get("Industry")
        or info_ctx.get("industry")
        or ""
    )

    # Priorité aux news brutes provider.
    # Important : on évite de repasser par l'ancien brief préfiltré
    # s'il existe des news brutes, car il perd trop de contexte.
    raw_news_payload = _news_merge_payloads(
        company_analysis.get("news"),
        company_analysis.get("latest_news"),
        company_analysis.get("stock_news"),
        company_analysis.get("fmp_news"),
        company_analysis.get("articles"),
        raw_ctx.get("news"),
        raw_ctx.get("yf_news"),
    )

    if not raw_news_payload and isinstance(company_analysis.get("sentiment"), dict):
        sentiment = company_analysis.get("sentiment", {})
        raw_news_payload = (
            sentiment.get("news_table")
            or sentiment.get("news")
            or sentiment.get("latest_news")
        )

    if raw_news_payload is not None:
        render_latest_news_intelligence_center_v1(
            raw_news_payload,
            sector=sector,
            industry=industry,
            ticker=ticker,
            company_name=company_name,
            key_prefix=f"latest_news_ic_v6_{ticker}"
        )
        return

    # Fallback legacy seulement si les news brutes sont absentes.
    legacy_brief_df = pd.DataFrame()

    try:
        legacy_brief_df = build_news_briefing_rows(company_analysis, ticker)
    except Exception:
        legacy_brief_df = pd.DataFrame()

    if legacy_brief_df is not None and not legacy_brief_df.empty:
        news_payload = []

        for _, row in legacy_brief_df.iterrows():
            news_payload.append({
                "date": row.get("Date"),
                "title": row.get("Titre") or row.get("Title") or row.get("Catégorie") or "News",
                "summary": row.get("Brief") or row.get("Summary") or "",
                "source": row.get("Source") or "N/A",
                "url": row.get("URL") or row.get("Url") or row.get("Lien") or "",
            })

        render_latest_news_intelligence_center_v1(
            news_payload,
            sector=sector,
            industry=industry,
            ticker=ticker,
            company_name=company_name,
            key_prefix=f"latest_news_ic_v6_{ticker}"
        )
        return

    st.info("Aucune news exploitable disponible pour ce ticker.")


def _market_feeling_label_from_news(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return "N/A"

    bullish = int((df["Sentiment"] == "Bullish").sum()) if "Sentiment" in df.columns else 0
    bearish = int((df["Sentiment"] == "Bearish").sum()) if "Sentiment" in df.columns else 0
    neutral = int((df["Sentiment"] == "Neutral").sum()) if "Sentiment" in df.columns else 0

    high_bullish = int(
        ((df["Sentiment"] == "Bullish") & (df["Impact"] == "High")).sum()
    ) if {"Sentiment", "Impact"}.issubset(df.columns) else 0

    high_bearish = int(
        ((df["Sentiment"] == "Bearish") & (df["Impact"] == "High")).sum()
    ) if {"Sentiment", "Impact"}.issubset(df.columns) else 0

    total = max(len(df), 1)
    balance = (bullish - bearish) / total

    if high_bearish > high_bullish and bearish >= bullish:
        return "Risque négatif"

    if high_bullish > high_bearish and bullish >= bearish:
        return "Constructif"

    if balance >= 0.25:
        return "Plutôt positif"

    if balance <= -0.25:
        return "Plutôt négatif"

    if neutral >= max(bullish, bearish):
        return "Neutre / mixte"

    return "Mixte"


def _market_impact_weight(value) -> float:
    text = str(value or "").strip().lower()

    if text == "high":
        return 3.0
    if text == "medium":
        return 2.0
    if text == "low":
        return 1.0

    return 1.0


def _market_sentiment_direction(value) -> int:
    text = str(value or "").strip().lower()

    if text == "bullish":
        return 1
    if text == "bearish":
        return -1

    return 0


def _market_ratio(num, den) -> float:
    den = safe_float(den, 0) or 0

    if den == 0:
        return 0.0

    return float(num) / float(den)


def _market_quality_bucket(score: float) -> str:
    score = safe_float(score, 50) or 50

    if score >= 75:
        return "Fort"
    if score >= 60:
        return "Moyen +"
    if score >= 45:
        return "Moyen"
    if score >= 30:
        return "Faible"
    return "Très faible"


def _market_short_label(value: str) -> str:
    """
    Labels courts pour éviter les valeurs coupées dans st.metric.
    Ne change aucune logique de calcul, seulement l'affichage KPI.
    """
    text = str(value or "N/A").strip()

    replacements = {
        "Constructif prudent": "Prudent +",
        "Constructif bruité": "Constr. bruit",
        "Constructif modéré": "Constructif",
        "Constructif +": "Constr. +",
        "Constructif": "Constructif",
        "Bruité": "Bruité",
        "Support bruité": "Support bruit",
        "Neutre / mixte": "Neutre",
        "Support 2ndaire": "Support sec.",
        "Support sec.": "Support sec.",
        "Support setup": "Support fort",
        "Support fort": "Support fort",
        "À confirmer": "À confirmer",
        "Fragilise": "Fragilise",
        "Risque négatif": "Risque -",
        "Contradictoire": "Contradictoire",
        "Bullish": "Bullish net",
        "Bearish": "Bearish net",
        "Bullish net": "Bullish net",
        "Bearish net": "Bearish net",
        "Équilibré": "Équilibré",
        "Élevée": "Élevée",
        "Moyenne": "Moyenne",
        "Faible": "Faible",
        "Très élevé": "Très élevé",
        "Élevé": "Élevé",
        "Moyen +": "Moyen +",
        "Moyen": "Moyen",
        "Bas": "Bas",
        "Fort": "Fort",
        "Propre": "Propre",
        "Mixte": "Mixte",
        "Bruit élevé": "Bruit élevé",
    }

    return replacements.get(text, text)


def _market_build_overlay_metrics(df: pd.DataFrame) -> dict:
    """
    Market Mood Overlay — version finale prudente.

    Objectif :
    - séparer signal directionnel, bruit neutre et contradiction ;
    - ne pas rendre le mood trop bullish quand le flux est surtout contextuel ;
    - garder les clés existantes pour ne rien casser côté render.
    """
    if df is None or df.empty:
        return {
            "market_mood": "N/A",
            "setup_impact": "N/A",
            "direct_signal": "N/A",
            "context_noise": "N/A",
            "bull_bear_pressure": "N/A",
            "contradiction": "N/A",
            "quality": "N/A",
            "news_count": 0,
            "summary_table": pd.DataFrame(),
        }

    work = df.copy()

    for col in ["Sentiment", "Impact", "Relevance Type", "Catalyst Score", "Relevance Score"]:
        if col not in work.columns:
            work[col] = ""

    work["Catalyst Score"] = pd.to_numeric(work["Catalyst Score"], errors="coerce")
    work["Relevance Score"] = pd.to_numeric(work["Relevance Score"], errors="coerce")

    work["_impact_weight"] = work["Impact"].apply(_market_impact_weight)
    work["_direction"] = work["Sentiment"].apply(_market_sentiment_direction)

    total_news = int(len(work))
    total_weight = max(float(work["_impact_weight"].sum()), 1.0)

    direct_mask = work["Relevance Type"].astype(str).str.lower().eq("direct")
    context_mask = ~direct_mask

    direct_count = int(direct_mask.sum())
    context_count = int(context_mask.sum())

    direct_ratio = _market_ratio(direct_count, total_news)
    context_ratio = _market_ratio(context_count, total_news)

    high_mask = work["Impact"].astype(str).str.lower().eq("high")
    high_impact_count = int(high_mask.sum())
    direct_high_count = int((direct_mask & high_mask).sum())

    bullish_mask = work["_direction"] > 0
    bearish_mask = work["_direction"] < 0
    neutral_mask = work["_direction"] == 0

    bullish_count = int(bullish_mask.sum())
    bearish_count = int(bearish_mask.sum())
    neutral_count = int(neutral_mask.sum())

    bullish_pressure = float(work.loc[bullish_mask, "_impact_weight"].sum())
    bearish_pressure = float(work.loc[bearish_mask, "_impact_weight"].sum())
    neutral_pressure = float(work.loc[neutral_mask, "_impact_weight"].sum())

    directional_pressure = bullish_pressure + bearish_pressure

    net_pressure = _market_ratio(
        bullish_pressure - bearish_pressure,
        max(directional_pressure, 1.0)
    )

    net_pressure_score = clamp(50 + 50 * net_pressure)
    neutral_weight_ratio = _market_ratio(neutral_pressure, total_weight)

    avg_catalyst = safe_float(work["Catalyst Score"].dropna().mean(), 50) or 50

    avg_direct_catalyst = safe_float(
        work.loc[direct_mask, "Catalyst Score"].dropna().mean(),
        avg_catalyst
    ) or avg_catalyst

    direct_signal_score = clamp(
        0.55 * avg_direct_catalyst
        + 25 * min(direct_ratio * 2, 1)
        + 10 * min(direct_high_count, 3) / 3
        + 10 * min(direct_count, 8) / 8
    )

    context_noise_score = clamp(context_ratio * 100)

    if directional_pressure <= 0:
        contradiction_score = 0
    else:
        contradiction_score = clamp(
            100 * min(bullish_pressure, bearish_pressure)
            / max(bullish_pressure, bearish_pressure, 1)
        )

    high_bullish = int((bullish_mask & high_mask).sum())
    high_bearish = int((bearish_mask & high_mask).sum())

    if high_bullish > 0 and high_bearish > 0:
        contradiction_score = clamp(contradiction_score + 15)

    # Setup score volontairement prudent :
    # le bruit contextuel et le poids neutre pénalisent le signal final.
    setup_score = clamp(
        0.34 * net_pressure_score
        + 0.26 * direct_signal_score
        + 0.22 * avg_catalyst
        + 0.18 * (100 - contradiction_score)
        - 0.18 * max(context_noise_score - 55, 0)
        - 0.10 * max(neutral_weight_ratio * 100 - 45, 0)
    )

    if context_noise_score >= 82:
        context_noise_label = "Très élevé"
    elif context_noise_score >= 65:
        context_noise_label = "Élevé"
    elif context_noise_score >= 45:
        context_noise_label = "Moyen"
    else:
        context_noise_label = "Bas"

    if direct_signal_score >= 75:
        direct_signal_label = "Fort"
    elif direct_signal_score >= 60:
        direct_signal_label = "Moyen +"
    elif direct_signal_score >= 45:
        direct_signal_label = "Moyen"
    else:
        direct_signal_label = "Faible"

    if contradiction_score >= 65:
        contradiction_label = "Élevée"
    elif contradiction_score >= 35:
        contradiction_label = "Moyenne"
    else:
        contradiction_label = "Faible"

    if net_pressure_score >= 65:
        bull_bear_label = "Bullish net"
    elif net_pressure_score <= 35:
        bull_bear_label = "Bearish net"
    else:
        bull_bear_label = "Équilibré"

    if setup_score >= 72 and direct_signal_score >= 60 and context_noise_score < 70:
        setup_impact = "Support fort"
    elif setup_score >= 58 and direct_signal_score >= 48:
        setup_impact = "Support sec."
    elif setup_score <= 42:
        setup_impact = "Fragilise"
    else:
        setup_impact = "À confirmer"

    # Label final volontairement conservateur.
    if contradiction_score >= 70:
        market_mood = "Contradictoire"
    elif context_noise_score >= 82 and direct_signal_score < 55:
        market_mood = "Bruité"
    elif net_pressure_score >= 66 and direct_signal_score >= 60 and context_noise_score < 65:
        market_mood = "Constructif +"
    elif net_pressure_score >= 58 and direct_signal_score >= 50:
        market_mood = "Constructif prudent" if context_noise_score >= 65 else "Constructif"
    elif net_pressure_score <= 38 and direct_signal_score >= 45 and contradiction_score < 60:
        market_mood = "Risque négatif"
    elif context_noise_score >= 70:
        market_mood = "Support bruité"
    else:
        market_mood = "Neutre / mixte"

    signal_quality_score = clamp(
        0.45 * direct_signal_score
        + 0.30 * (100 - context_noise_score)
        + 0.25 * (100 - contradiction_score)
    )

    if signal_quality_score >= 70:
        quality = "Propre"
    elif signal_quality_score >= 48:
        quality = "Mixte"
    else:
        quality = "Bruit élevé"

    summary_rows = [
        {
            "Dimension": "Direct Signal",
            "Lecture": direct_signal_label,
            "Score": round(direct_signal_score, 1),
            "Détail": f"{direct_count} direct(s), dont {direct_high_count} high impact.",
        },
        {
            "Dimension": "Context Noise",
            "Lecture": context_noise_label,
            "Score": round(context_noise_score, 1),
            "Détail": f"{context_count} contextuel(s) sur {total_news} news. Neutral weight {neutral_weight_ratio:.0%}. Score élevé = bruit élevé.",
        },
        {
            "Dimension": "Bull / Bear",
            "Lecture": bull_bear_label,
            "Score": round(net_pressure_score, 1),
            "Détail": f"Bullish {bullish_count} / Bearish {bearish_count}. Neutral séparé : {neutral_count}.",
        },
        {
            "Dimension": "Neutral Noise",
            "Lecture": "Dominant" if neutral_weight_ratio >= 0.50 else "Secondaire",
            "Score": round(neutral_weight_ratio * 100, 1),
            "Détail": f"Pression neutre pondérée {neutral_pressure:.1f}/{total_weight:.1f}.",
        },
        {
            "Dimension": "Contradiction",
            "Lecture": contradiction_label,
            "Score": round(contradiction_score, 1),
            "Détail": f"Pression bullish pondérée {bullish_pressure:.1f} vs bearish {bearish_pressure:.1f}. Score élevé = contradiction élevée.",
        },
        {
            "Dimension": "Setup Contribution",
            "Lecture": setup_impact,
            "Score": round(setup_score, 1),
            "Détail": "Signal direct + pression directionnelle + qualité catalyst, pénalisé si bruit contextuel dominant.",
        },
        {
            "Dimension": "Newsflow Quality",
            "Lecture": quality,
            "Score": round(signal_quality_score, 1),
            "Détail": "Qualité du signal informationnel après retraitement du bruit et des contradictions.",
        },
    ]

    return {
        "market_mood": market_mood,
        "setup_impact": setup_impact,
        "direct_signal": direct_signal_label,
        "context_noise": context_noise_label,
        "bull_bear_pressure": bull_bear_label,
        "contradiction": contradiction_label,
        "quality": quality,
        "news_count": total_news,
        "direct_count": direct_count,
        "context_count": context_count,
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
        "neutral_count": neutral_count,
        "high_impact_count": high_impact_count,
        "bullish_pressure": bullish_pressure,
        "bearish_pressure": bearish_pressure,
        "neutral_pressure": neutral_pressure,
        "directional_pressure": directional_pressure,
        "neutral_weight_ratio": neutral_weight_ratio,
        "net_pressure_score": net_pressure_score,
        "direct_signal_score": direct_signal_score,
        "context_noise_score": context_noise_score,
        "contradiction_score": contradiction_score,
        "setup_score": setup_score,
        "avg_catalyst": avg_catalyst,
        "signal_quality_score": signal_quality_score,
        "summary_table": pd.DataFrame(summary_rows),
    }


def _market_format_news_table(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    display_cols = [
        "Date Display",
        "Title",
        "Relevance Type",
        "Relevance Score",
        "Catalyst Theme",
        "Catalyst Subtheme",
        "Sentiment",
        "Impact",
        "Catalyst Score",
        "Source",
    ]

    existing_cols = [c for c in display_cols if c in df.columns]
    out = df[existing_cols].copy()

    out = out.rename(columns={
        "Date Display": "Date",
        "Title": "Titre",
        "Relevance Type": "Pertinence",
        "Relevance Score": "Score pertinence",
        "Catalyst Theme": "Theme",
        "Catalyst Subtheme": "Sous-thème",
        "Catalyst Score": "Score catalyst",
    })

    return out


def _market_build_contradiction_table(df: pd.DataFrame) -> pd.DataFrame:
    """
    Contradiction map finale prudente.

    Objectif :
    - détecter les thèmes où bullish et bearish coexistent réellement ;
    - pénaliser les petits échantillons ;
    - éviter de surclasser une contradiction faible en catalyst quality ;
    - ajouter Priority / Action pour rendre la lecture exploitable.
    """
    if df is None or df.empty:
        return pd.DataFrame()

    required = {"Catalyst Theme", "Sentiment", "Impact", "Catalyst Score", "Title"}
    if not required.issubset(df.columns):
        return pd.DataFrame()

    work = df.copy()

    work["Catalyst Theme"] = (
        work["Catalyst Theme"]
        .fillna("Unclassified")
        .astype(str)
        .replace("", "Unclassified")
    )

    work["Catalyst Score"] = pd.to_numeric(
        work["Catalyst Score"],
        errors="coerce"
    ).fillna(50)

    if "Relevance Score" in work.columns:
        work["Relevance Score"] = pd.to_numeric(
            work["Relevance Score"],
            errors="coerce"
        ).fillna(0)

    if "Date" in work.columns:
        work["Date"] = pd.to_datetime(work["Date"], errors="coerce")

    work["_impact_weight"] = work["Impact"].apply(_market_impact_weight)
    work["_direction"] = work["Sentiment"].apply(_market_sentiment_direction)

    rows = []

    def _top_title(sub_df: pd.DataFrame) -> str:
        if sub_df is None or sub_df.empty:
            return ""

        sort_cols = []
        ascending = []

        for col in ["Catalyst Score", "Relevance Score", "Date"]:
            if col in sub_df.columns:
                sort_cols.append(col)
                ascending.append(False)

        if sort_cols:
            sub_df = sub_df.sort_values(sort_cols, ascending=ascending)

        return str(sub_df.iloc[0].get("Title", ""))[:160]

    for theme, sub in work.groupby("Catalyst Theme"):
        bullish = sub[sub["_direction"] > 0]
        bearish = sub[sub["_direction"] < 0]

        if bullish.empty or bearish.empty:
            continue

        bullish_pressure = float(bullish["_impact_weight"].sum())
        bearish_pressure = float(bearish["_impact_weight"].sum())

        raw_contradiction_score = clamp(
            100 * min(bullish_pressure, bearish_pressure)
            / max(bullish_pressure, bearish_pressure, 1)
        )

        theme_news_count = int(len(sub))
        avg_catalyst = safe_float(sub["Catalyst Score"].mean(), 0) or 0

        if theme_news_count >= 10:
            sample_quality = "Robuste"
            sample_factor = 1.00
        elif theme_news_count >= 6:
            sample_quality = "Correct"
            sample_factor = 0.85
        elif theme_news_count >= 3:
            sample_quality = "Faible"
            sample_factor = 0.65
        else:
            sample_quality = "Très faible"
            sample_factor = 0.45

        adjusted_contradiction_score = raw_contradiction_score * sample_factor

        # Qualité catalyst : une contradiction avec avg catalyst faible doit rester secondaire.
        if avg_catalyst < 45:
            adjusted_contradiction_score *= 0.70
        elif avg_catalyst < 50:
            adjusted_contradiction_score *= 0.85
        elif avg_catalyst >= 65:
            adjusted_contradiction_score *= 1.05

        # Cap décisionnel :
        # une contradiction équilibrée mais faible en catalyst quality
        # ne doit pas ressortir comme un signal fort sur le graphe.
        if avg_catalyst < 45:
            adjusted_contradiction_score = min(adjusted_contradiction_score, 40)
        elif avg_catalyst < 50:
            adjusted_contradiction_score = min(adjusted_contradiction_score, 45)
        elif theme_news_count < 6:
            adjusted_contradiction_score = min(adjusted_contradiction_score, 45)
        elif bullish_pressure < 3 or bearish_pressure < 3:
            adjusted_contradiction_score = min(adjusted_contradiction_score, 50)

        adjusted_contradiction_score = clamp(adjusted_contradiction_score)

        if (
            adjusted_contradiction_score >= 65
            and avg_catalyst >= 60
            and theme_news_count >= 6
        ):
            priority = "High"
            action = "Contradiction réelle : lire les deux côtés avant décision."
            priority_rank = 0
        elif (
            adjusted_contradiction_score >= 45
            and avg_catalyst >= 50
            and theme_news_count >= 3
        ):
            priority = "Medium"
            action = "Contradiction exploitable, mais pas suffisante seule."
            priority_rank = 1
        elif adjusted_contradiction_score >= 30:
            priority = "Low"
            action = "Bruit mixte à surveiller, faible poids décisionnel."
            priority_rank = 2
        else:
            priority = "Watch"
            action = "Signal trop faible pour influencer le setup."
            priority_rank = 3

        rows.append({
            "Priority": priority,
            "Theme": theme,
            "News count": theme_news_count,
            "Sample quality": sample_quality,
            "Bullish news": int(len(bullish)),
            "Bearish news": int(len(bearish)),
            "Bullish pressure": round(bullish_pressure, 1),
            "Bearish pressure": round(bearish_pressure, 1),
            "Raw contradiction": round(raw_contradiction_score, 1),
            "Contradiction score": round(adjusted_contradiction_score, 1),
            "Avg catalyst": round(avg_catalyst, 1),
            "Action": action,
            "Top bullish": _top_title(bullish),
            "Top bearish": _top_title(bearish),
            "_priority_rank": priority_rank,
        })

    if not rows:
        return pd.DataFrame()

    out = pd.DataFrame(rows)

    out = (
        out
        .sort_values(
            ["_priority_rank", "Contradiction score", "Avg catalyst", "News count"],
            ascending=[True, False, False, False]
        )
        .drop(columns=["_priority_rank"], errors="ignore")
        .reset_index(drop=True)
    )

    return out


def render_market_feeling_news_v2(
    company_analysis: dict,
    ticker: str,
    scores: dict | None = None,
):
    """
    Market Mood Overlay v3.

    Objectif :
    - ne plus dupliquer Latest News ;
    - transformer Market Feeling en couche décisionnelle ;
    - réutiliser exactement les mêmes news normalisées que Latest News ;
    - éviter tout appel provider supplémentaire ;
    - garder la section légère et rapide.
    """
    st.subheader("Market Mood Overlay — Newsflow vs Setup")

    company_analysis = company_analysis if isinstance(company_analysis, dict) else {}
    scores = scores or {}

    profile_ctx = (
        company_analysis.get("profile")
        or company_analysis.get("asset_profile")
        or company_analysis.get("assetProfile")
        or {}
    )

    raw_ctx = company_analysis.get("raw_data", {})
    raw_ctx = raw_ctx if isinstance(raw_ctx, dict) else {}

    info_ctx = raw_ctx.get("info", {})
    info_ctx = info_ctx if isinstance(info_ctx, dict) else {}

    company_name = (
        profile_ctx.get("name")
        or profile_ctx.get("longName")
        or profile_ctx.get("shortName")
        or info_ctx.get("longName")
        or info_ctx.get("shortName")
        or ticker
    )

    sector = (
        company_analysis.get("sector")
        or profile_ctx.get("sector")
        or profile_ctx.get("Sector")
        or info_ctx.get("sector")
        or ""
    )

    industry = (
        company_analysis.get("industry")
        or profile_ctx.get("industry")
        or profile_ctx.get("Industry")
        or info_ctx.get("industry")
        or ""
    )

    raw_news_payload = _news_merge_payloads(
        company_analysis.get("news"),
        company_analysis.get("latest_news"),
        company_analysis.get("stock_news"),
        company_analysis.get("fmp_news"),
        company_analysis.get("articles"),
        raw_ctx.get("news"),
        raw_ctx.get("yf_news"),
    )

    archived_news_payload = []

    try:
        archived_news_payload = load_news_archive(ticker)
    except Exception:
        archived_news_payload = []

    combined_news_payload = _news_merge_payloads(
        archived_news_payload,
        raw_news_payload,
    )

    news_df = build_news_intelligence_frame(
        combined_news_payload,
        sector=sector,
        industry=industry,
        ticker=ticker,
        company_name=company_name,
    )

    if news_df.empty:
        st.warning("Aucune news exploitable pour le Market Mood Overlay.")
        return

    available_windows = ["24h", "7j", "30j", "90j", "1 an"]

    market_window = st.radio(
        "Fenêtre Market Mood",
        available_windows,
        index=1,
        horizontal=True,
        key=f"market_mood_overlay_window_{ticker}",
    )

    filtered_df = filter_news_by_time_window(news_df, market_window)

    if filtered_df.empty:
        st.info(f"Aucune news exploitable sur la fenêtre {market_window}.")
        return

    filtered_df = filtered_df.sort_values(
        ["Catalyst Score", "Relevance Score", "Date"],
        ascending=[False, False, False],
    ).reset_index(drop=True)

    overlay = _market_build_overlay_metrics(filtered_df)

    col1, col2, col3, col4, col5, col6 = st.columns(6)

    col1.metric("Market Mood", _market_short_label(overlay.get("market_mood", "N/A")))
    col2.metric("Setup Impact", _market_short_label(overlay.get("setup_impact", "N/A")))
    col3.metric("Direct Signal", _market_short_label(overlay.get("direct_signal", "N/A")))
    col4.metric("Context Noise", _market_short_label(overlay.get("context_noise", "N/A")))
    col5.metric("Bull / Bear", _market_short_label(overlay.get("bull_bear_pressure", "N/A")))
    col6.metric("Contradiction", _market_short_label(overlay.get("contradiction", "N/A")))

    st.caption(
        f"Fenêtre {market_window} · {overlay.get('news_count', 0)} news analysée(s) · "
        f"Direct {overlay.get('direct_count', 0)} / Context {overlay.get('context_count', 0)} · "
        f"Bullish {overlay.get('bullish_count', 0)} / Bearish {overlay.get('bearish_count', 0)} / Neutral {overlay.get('neutral_count', 0)}. "
        "Cette section ne refait aucun appel provider : elle réinterprète le newsflow déjà chargé par Latest News."
    )

    view = st.radio(
        "Vue Market Mood",
        ["Signal Overlay", "Bull / Bear Balance", "Contradictions"],
        horizontal=True,
        key=f"market_mood_overlay_view_{ticker}",
    )

    if view == "Signal Overlay":
        st.markdown("#### Lecture décisionnelle")

        summary_table = overlay.get("summary_table", pd.DataFrame())

        if summary_table is not None and not summary_table.empty:
            st.dataframe(
                summary_table,
                use_container_width=True,
                hide_index=True,
            )

        st.markdown("#### Top news qui pilotent le mood")

        if len(filtered_df) <= 5:
            max_rows = len(filtered_df)
            st.caption(f"{max_rows} news disponible(s) dans cette fenêtre.")
        else:
            max_rows = st.slider(
                "Nombre de news affichées",
                min_value=5,
                max_value=max(5, min(50, len(filtered_df))),
                value=min(15, max(5, len(filtered_df))),
                step=5,
                key=f"market_mood_overlay_rows_{ticker}",
            )

        relevance_text = filtered_df["Relevance Type"].astype(str).str.lower()
        direct_drivers = filtered_df[relevance_text.str.contains("direct", na=False)].copy()
        context_noise = filtered_df[~relevance_text.str.contains("direct", na=False)].copy()

        directional_news = filtered_df[
            filtered_df["Sentiment"].astype(str).isin(["Bullish", "Bearish"])
        ].copy()

        if directional_news.empty:
            directional_news = filtered_df.copy()

        top_news_df = _market_format_news_table(directional_news.head(max_rows))

        if top_news_df.empty:
            st.info("Aucune ligne exploitable à afficher.")
        else:
            st.dataframe(
                top_news_df,
                use_container_width=True,
                hide_index=True,
            )

        with st.expander("Direct drivers — signal ticker pur", expanded=True):
            direct_display = _market_format_news_table(
                direct_drivers
                .sort_values(["Catalyst Score", "Relevance Score", "Date"], ascending=[False, False, False])
                .head(max_rows)
            )

            if direct_display.empty:
                st.info("Aucune news directe sur cette fenêtre.")
            else:
                st.dataframe(
                    direct_display,
                    use_container_width=True,
                    hide_index=True,
                )

        with st.expander("Context / neutral noise — bruit utile mais non décisif", expanded=False):
            context_display = _market_format_news_table(
                context_noise
                .sort_values(["Catalyst Score", "Relevance Score", "Date"], ascending=[False, False, False])
                .head(max_rows)
            )

            if context_display.empty:
                st.info("Aucune news contextuelle sur cette fenêtre.")
            else:
                st.dataframe(
                    context_display,
                    use_container_width=True,
                    hide_index=True,
                )

        with st.expander("Audit rapide — liens des news utilisées", expanded=False):
            link_col = None

            for candidate in ["URL", "Link", "Lien", "url", "link"]:
                if candidate in filtered_df.columns:
                    link_col = candidate
                    break

            if link_col is None:
                st.info("Aucun lien disponible dans le dataset normalisé.")
            else:
                link_cols = [
                    c for c in ["Date Display", "Title", "Source", link_col]
                    if c in filtered_df.columns
                ]

                links_df = filtered_df[link_cols].copy()
                links_df = links_df[links_df[link_col].astype(str).str.len() > 0]

                links_df = links_df.rename(columns={
                    "Date Display": "Date",
                    "Title": "Titre",
                    link_col: "Lien",
                })

                st.dataframe(
                    links_df.head(max_rows),
                    use_container_width=True,
                    hide_index=True,
                )

    elif view == "Bull / Bear Balance":
        st.markdown("#### Pression directionnelle pondérée par impact")

        bullish_pressure = safe_float(overlay.get("bullish_pressure"), 0) or 0
        bearish_pressure = safe_float(overlay.get("bearish_pressure"), 0) or 0
        neutral_pressure = safe_float(overlay.get("neutral_pressure"), 0) or 0
        directional_pressure = safe_float(overlay.get("directional_pressure"), 0) or 0

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Bullish pressure", round(bullish_pressure, 1))
        k2.metric("Bearish pressure", round(bearish_pressure, 1))
        k3.metric("Neutral noise", round(neutral_pressure, 1))
        k4.metric("Net score", f"{round(safe_float(overlay.get('net_pressure_score'), 50) or 50, 1)}/100")

        pressure_df = pd.DataFrame([
            {
                "Signal": "Bullish",
                "Pression pondérée": bullish_pressure,
                "Nombre de news": overlay.get("bullish_count", 0),
            },
            {
                "Signal": "Bearish",
                "Pression pondérée": bearish_pressure,
                "Nombre de news": overlay.get("bearish_count", 0),
            },
        ])

        if directional_pressure <= 0:
            st.info("Aucune pression directionnelle nette : le flux est principalement neutre/contextuel.")
        else:
            fig = go.Figure()

            fig.add_trace(go.Bar(
                x=pressure_df["Signal"],
                y=pressure_df["Pression pondérée"],
                text=pressure_df["Pression pondérée"],
                textposition="auto",
                name="Pression directionnelle",
            ))

            fig.update_layout(
                height=420,
                title=f"Bull / Bear Balance — fenêtre {market_window}",
                xaxis_title="Signal",
                yaxis_title="Pression pondérée",
                margin=dict(l=20, r=20, t=70, b=40),
            )

            st.plotly_chart(fig, use_container_width=True)

        st.caption(
            "Le neutre est volontairement séparé : il mesure le bruit / contexte, "
            "mais ne doit pas être interprété comme une pression directionnelle."
        )

        balance_work = filtered_df.copy()
        balance_work["_impact_weight"] = balance_work["Impact"].apply(_market_impact_weight)

        balance_table = (
            balance_work
            .groupby(["Sentiment", "Impact"], as_index=False)
            .agg({
                "Title": "count",
                "_impact_weight": "sum",
                "Catalyst Score": "mean",
            })
            .rename(columns={
                "Title": "Nombre de news",
                "_impact_weight": "Pression pondérée",
                "Catalyst Score": "Score catalyst moyen",
            })
            .sort_values(["Sentiment", "Pression pondérée"], ascending=[True, False])
        )

        if not balance_table.empty:
            balance_table["Pression pondérée"] = balance_table["Pression pondérée"].round(1)
            balance_table["Score catalyst moyen"] = balance_table["Score catalyst moyen"].round(1)

            st.dataframe(
                balance_table,
                use_container_width=True,
                hide_index=True,
            )

    elif view == "Contradictions":
        st.markdown("#### Contradictions du newsflow")

        contradiction_df = _market_build_contradiction_table(filtered_df)

        if contradiction_df.empty:
            st.success(
                "Pas de contradiction forte détectée entre signaux bullish et bearish sur les mêmes thèmes."
            )
        else:
            fig = go.Figure()

            fig.add_trace(go.Bar(
                x=contradiction_df["Contradiction score"],
                y=contradiction_df["Theme"],
                orientation="h",
                text=contradiction_df["Contradiction score"].round(1),
                textposition="auto",
                customdata=contradiction_df[[
                    "Priority",
                    "Action",
                    "Bullish news",
                    "Bearish news",
                    "Bullish pressure",
                    "Bearish pressure",
                    "Avg catalyst",
                    "Sample quality",
                    "Top bullish",
                    "Top bearish",
                ]],
                hovertemplate=(
                    "<b>%{y}</b><br>"
                    "Priority: %{customdata[0]}<br>"
                    "Action: %{customdata[1]}<br><br>"
                    "Contradiction: %{x:.1f}/100<br>"
                    "Bullish news: %{customdata[2]} · Pressure: %{customdata[4]}<br>"
                    "Bearish news: %{customdata[3]} · Pressure: %{customdata[5]}<br>"
                    "Avg catalyst: %{customdata[6]}/100<br>"
                    "Sample: %{customdata[7]}<br><br>"
                    "Top bullish: %{customdata[8]}<br>"
                    "Top bearish: %{customdata[9]}"
                    "<extra></extra>"
                ),
                name="Contradiction score",
            ))

            fig.update_layout(
                height=max(420, 80 + 45 * len(contradiction_df)),
                title=f"Contradiction Map — fenêtre {market_window}",
                xaxis_title="Contradiction score",
                yaxis_title="Theme",
                margin=dict(l=20, r=20, t=70, b=40),
            )

            st.plotly_chart(fig, use_container_width=True)

            st.dataframe(
                contradiction_df,
                use_container_width=True,
                hide_index=True,
            )

        st.markdown("#### News bearish à surveiller")

        bearish_df = filtered_df[
            filtered_df["Sentiment"].astype(str).str.lower().eq("bearish")
        ].copy() if "Sentiment" in filtered_df.columns else pd.DataFrame()

        if bearish_df.empty:
            st.info("Aucune news bearish détectée sur cette fenêtre.")
        else:
            bearish_df["Catalyst Score"] = pd.to_numeric(
                bearish_df["Catalyst Score"],
                errors="coerce"
            ).fillna(50)

            if "Relevance Score" in bearish_df.columns:
                bearish_df["Relevance Score"] = pd.to_numeric(
                    bearish_df["Relevance Score"],
                    errors="coerce"
                ).fillna(0)
            else:
                bearish_df["Relevance Score"] = 0

            bearish_df["_impact_weight"] = bearish_df["Impact"].apply(_market_impact_weight)

            bearish_df["_direct_boost"] = np.where(
                bearish_df["Relevance Type"].astype(str).str.lower().eq("direct"),
                1,
                0
            ) if "Relevance Type" in bearish_df.columns else 0

            bearish_df["_watch_score"] = (
                bearish_df["Catalyst Score"]
                + 6 * bearish_df["_impact_weight"]
                + 8 * bearish_df["_direct_boost"]
                + 0.10 * bearish_df["Relevance Score"]
            )

            actionable_bearish = bearish_df[
                (bearish_df["Catalyst Score"] >= 45)
                | (bearish_df["Impact"].astype(str).str.lower().isin(["medium", "high"]))
                | (bearish_df["_direct_boost"] > 0)
            ].copy()

            if actionable_bearish.empty:
                actionable_bearish = bearish_df.copy()

            actionable_bearish = actionable_bearish.sort_values(
                ["_watch_score", "Catalyst Score", "Relevance Score", "Date"],
                ascending=[False, False, False, False],
            )

            st.caption(
                "Filtre prudent : priorité aux bearish directs, medium/high impact ou catalyst score >= 45."
            )

            st.dataframe(
                _market_format_news_table(actionable_bearish.head(12)),
                use_container_width=True,
                hide_index=True,
            )
