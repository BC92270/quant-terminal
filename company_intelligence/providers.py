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

# FMP / EXTERNAL DATA HELPERS
# ============================================================

def get_fmp_api_key() -> str:
    try:
        key = st.secrets.get("FMP_API_KEY", "")
    except Exception:
        key = ""

    if not key:
        key = os.getenv("FMP_API_KEY", "")

    return str(key).strip()


def fmp_enabled() -> bool:
    return bool(get_fmp_api_key())


def fmp_rows(data):
    if data is None:
        return []

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ["data", "results", "items"]:
            if isinstance(data.get(key), list):
                return data.get(key)

        error_keys = ["Error Message", "error", "message"]
        if any(k in data for k in error_keys) and len(data) <= 3:
            return []

        return [data] if data else []

    return []


def fmp_get_json(url: str, params: dict | None = None):
    api_key = get_fmp_api_key()

    if not api_key:
        return []

    request_params = dict(params or {})
    request_params["apikey"] = api_key

    try:
        response = requests.get(url, params=request_params, timeout=15)
        response.raise_for_status()
        data = response.json()

        if isinstance(data, dict):
            text = str(data).lower()
            if "invalid api key" in text or "limit" in text and "exceeded" in text:
                return []

        return data
    except Exception:
        return []


def fmp_first_non_empty(candidates: list[tuple[str, dict]]) -> list[dict]:
    for url, params in candidates:
        rows = fmp_rows(fmp_get_json(url, params))
        if rows:
            return rows
    return []


def fmp_first_payload(candidates: list[tuple[str, dict]]):
    """Return the first non-empty raw JSON payload without flattening its schema.

    Segmentation endpoints can return hierarchical dictionaries.  Using ``fmp_rows`` on
    those responses can destroy the date/segment nesting before the dedicated normalizer
    sees it, so the central company bundle preserves the raw payload.
    """
    for url, params in candidates:
        data = fmp_get_json(url, params)
        if data is None:
            continue
        if isinstance(data, list) and data:
            return data
        if isinstance(data, dict) and data:
            # fmp_get_json already removes the common API-error responses.
            return data
    return []


@st.cache_data(ttl=1800, show_spinner=False)
def get_fmp_company_bundle(ticker: str) -> dict:
    ticker = ticker.upper().strip()

    if not fmp_enabled():
        return {
            "enabled": False,
            "income_annual": [],
            "income_quarterly": [],
            "cashflow_annual": [],
            "cashflow_quarterly": [],
            "balance_annual": [],
            "balance_quarterly": [],
            "ratios_annual": [],
            "ratios_quarterly": [],
            "key_metrics_annual": [],
            "key_metrics_quarterly": [],
            "estimates_annual": [],
            "estimates_quarterly": [],
            "earnings_calendar": [],
            "earnings_surprises": [],
            "price_target_consensus": [],
            "news": [],
            "product_segments_raw": [],
            "geographic_segments_raw": [],
        }

    base_v3 = "https://financialmodelingprep.com/api/v3"
    base_v4 = "https://financialmodelingprep.com/api/v4"
    base_stable = "https://financialmodelingprep.com/stable"

    def statement(endpoint_v3: str, endpoint_stable: str, period: str, limit: int = 20):
        return fmp_first_non_empty([
            (
                f"{base_v3}/{endpoint_v3}/{ticker}",
                {"period": period, "limit": limit},
            ),
            (
                f"{base_stable}/{endpoint_stable}",
                {"symbol": ticker, "period": period, "limit": limit},
            ),
        ])

    def analyst_estimates(period: str, limit: int) -> list[dict]:
        period_candidates = [period]

        if period == "quarter":
            period_candidates.append("quarterly")

        if period == "annual":
            period_candidates.append("yearly")

        candidates = []

        for p in period_candidates:
            candidates.extend([
                (
                    f"{base_stable}/analyst-estimates",
                    {"symbol": ticker, "period": p, "page": 0, "limit": limit},
                ),
                (
                    f"{base_v3}/analyst-estimates/{ticker}",
                    {"period": p, "limit": limit},
                ),
            ])

        return fmp_first_non_empty(candidates)

    income_annual = statement("income-statement", "income-statement", "annual", 20)
    income_quarterly = statement("income-statement", "income-statement", "quarter", 32)

    cashflow_annual = statement("cash-flow-statement", "cash-flow-statement", "annual", 20)
    cashflow_quarterly = statement("cash-flow-statement", "cash-flow-statement", "quarter", 32)

    balance_annual = statement("balance-sheet-statement", "balance-sheet-statement", "annual", 20)
    balance_quarterly = statement("balance-sheet-statement", "balance-sheet-statement", "quarter", 32)

    ratios_annual = statement("ratios", "ratios", "annual", 40)
    ratios_quarterly = statement("ratios", "ratios", "quarter", 40)

    key_metrics_annual = statement("key-metrics", "key-metrics", "annual", 40)
    key_metrics_quarterly = statement("key-metrics", "key-metrics", "quarter", 40)

    estimates_annual = analyst_estimates("annual", 20)
    estimates_quarterly = analyst_estimates("quarter", 24)

    earnings_calendar = fmp_first_non_empty([
        (
            f"{base_stable}/earnings-calendar",
            {"symbol": ticker, "limit": 24},
        ),
        (
            f"{base_v3}/historical/earning_calendar/{ticker}",
            {"limit": 24},
        ),
    ])

    earnings_surprises = fmp_first_non_empty([
        (
            f"{base_v3}/earnings-surprises/{ticker}",
            {"limit": 24},
        ),
        (
            f"{base_stable}/earnings-surprises",
            {"symbol": ticker, "limit": 24},
        ),
    ])

    price_target_consensus = fmp_first_non_empty([
        (
            f"{base_v4}/price-target-consensus",
            {"symbol": ticker},
        ),
        (
            f"{base_stable}/price-target-consensus",
            {"symbol": ticker},
        ),
    ])

    news = fmp_first_non_empty([
        (
            f"{base_v3}/stock_news",
            {"tickers": ticker, "limit": 50},
        ),
        (
            f"{base_stable}/news/stock",
            {"symbols": ticker, "limit": 50},
        ),
    ])

    # Preserve segmentation in the same central company bundle used by Core Financials.
    # This is intentionally raw: the institutional normalizer owns schema interpretation.
    # ``structure=flat`` is supported by current FMP segment APIs, while the no-structure
    # fallback preserves compatibility with accounts that previously returned usable data
    # only under the default representation.
    product_segments_raw = fmp_first_payload([
        (f"{base_stable}/revenue-product-segmentation", {"symbol": ticker, "structure": "flat"}),
        (f"{base_stable}/revenue-product-segmentation", {"symbol": ticker}),
        (f"{base_v4}/revenue-product-segmentation", {"symbol": ticker}),
    ])
    geographic_segments_raw = fmp_first_payload([
        # Both spellings have existed in FMP documentation/changelog generations.
        (f"{base_stable}/revenue-geographic-segments", {"symbol": ticker, "structure": "flat"}),
        (f"{base_stable}/revenue-geographic-segmentation", {"symbol": ticker, "structure": "flat"}),
        (f"{base_stable}/revenue-geographic-segmentation", {"symbol": ticker}),
        (f"{base_v4}/revenue-geographic-segmentation", {"symbol": ticker}),
    ])

    return {
        "enabled": True,
        "income_annual": income_annual,
        "income_quarterly": income_quarterly,
        "cashflow_annual": cashflow_annual,
        "cashflow_quarterly": cashflow_quarterly,
        "balance_annual": balance_annual,
        "balance_quarterly": balance_quarterly,
        "ratios_annual": ratios_annual,
        "ratios_quarterly": ratios_quarterly,
        "key_metrics_annual": key_metrics_annual,
        "key_metrics_quarterly": key_metrics_quarterly,
        "estimates_annual": estimates_annual,
        "estimates_quarterly": estimates_quarterly,
        "earnings_calendar": earnings_calendar,
        "earnings_surprises": earnings_surprises,
        "price_target_consensus": price_target_consensus,
        "news": news,
        "product_segments_raw": product_segments_raw,
        "geographic_segments_raw": geographic_segments_raw,
    }


# ============================================================
# ADDITIONAL FUNDAMENTAL PROVIDERS — ALPHA VANTAGE / SEC
# ============================================================

def get_alpha_vantage_api_key() -> str:
    try:
        key = st.secrets.get("ALPHA_VANTAGE_API_KEY", "")
    except Exception:
        key = ""

    if not key:
        key = os.getenv("ALPHA_VANTAGE_API_KEY", "")

    return str(key).strip()


def alpha_enabled() -> bool:
    return bool(get_alpha_vantage_api_key())


def alpha_get_json(function_name: str, symbol: str) -> dict:
    api_key = get_alpha_vantage_api_key()

    if not api_key:
        return {}

    try:
        response = requests.get(
            "https://www.alphavantage.co/query",
            params={
                "function": function_name,
                "symbol": symbol.upper().strip(),
                "apikey": api_key,
            },
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()

        if not isinstance(data, dict):
            return {}

        # Important : on ne masque plus les erreurs Alpha.
        # Sinon le debug affiche seulement [] et on ne sait pas si c'est un rate limit,
        # une limitation de plan ou une vraie absence de données.
        if any(k in data for k in ["Note", "Information", "Error Message"]):
            return {"_alpha_error": data}

        return data

    except Exception as e:
        return {"_alpha_exception": str(e)}


@st.cache_data(ttl=7200, show_spinner=False)
def get_alpha_vantage_bundle(ticker: str) -> dict:
    ticker = ticker.upper().strip()

    empty = {
        "enabled": False,
        "income_statement": {},
        "cash_flow": {},
        "balance_sheet": {},
        "earnings": {},
        "earnings_estimates": {},
    }

    if not alpha_enabled():
        return empty

    def is_alpha_error(payload: dict) -> bool:
        return (
            isinstance(payload, dict)
            and (
                "_alpha_error" in payload
                or "_alpha_exception" in payload
            )
        )

    def alpha_call(function_name: str) -> dict:
        payload = alpha_get_json(function_name, ticker)

        # Alpha gratuit : éviter les appels trop rapprochés.
        time.sleep(1.25)

        return payload

    # Priorité : estimates d'abord, car c'est ce qu'on cherche à améliorer.
    earnings_estimates = alpha_call("EARNINGS_ESTIMATES")

    # Si Alpha bloque déjà ici, inutile de brûler 4 autres appels.
    if is_alpha_error(earnings_estimates):
        return {
            "enabled": True,
            "income_statement": {},
            "cash_flow": {},
            "balance_sheet": {},
            "earnings": {},
            "earnings_estimates": earnings_estimates,
        }

    earnings = alpha_call("EARNINGS")

    if is_alpha_error(earnings):
        return {
            "enabled": True,
            "income_statement": {},
            "cash_flow": {},
            "balance_sheet": {},
            "earnings": earnings,
            "earnings_estimates": earnings_estimates,
        }

    income_statement = alpha_call("INCOME_STATEMENT")

    if is_alpha_error(income_statement):
        return {
            "enabled": True,
            "income_statement": income_statement,
            "cash_flow": {},
            "balance_sheet": {},
            "earnings": earnings,
            "earnings_estimates": earnings_estimates,
        }

    cash_flow = alpha_call("CASH_FLOW")

    if is_alpha_error(cash_flow):
        return {
            "enabled": True,
            "income_statement": income_statement,
            "cash_flow": cash_flow,
            "balance_sheet": {},
            "earnings": earnings,
            "earnings_estimates": earnings_estimates,
        }

    balance_sheet = alpha_call("BALANCE_SHEET")

    return {
        "enabled": True,
        "income_statement": income_statement,
        "cash_flow": cash_flow,
        "balance_sheet": balance_sheet,
        "earnings": earnings,
        "earnings_estimates": earnings_estimates,
    }


# ============================================================
# FINNHUB — EPS / REVENUE ESTIMATES + EARNINGS SURPRISE
# ============================================================

def get_finnhub_api_key() -> str:
    try:
        key = st.secrets.get("FINNHUB_API_KEY", "")
    except Exception:
        key = ""

    if not key:
        key = os.getenv("FINNHUB_API_KEY", "")

    return str(key).strip()


def finnhub_enabled() -> bool:
    return bool(get_finnhub_api_key())


def finnhub_rows(payload, preferred_keys: list[str] | None = None) -> list[dict]:
    if payload is None:
        return []

    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]

    if isinstance(payload, dict):
        keys = preferred_keys or []
        keys += ["earningsCalendar", "data", "result", "results", "items"]

        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]

        return [payload] if payload else []

    return []


def finnhub_get_json(endpoint: str, params: dict | None = None):
    token = get_finnhub_api_key()

    if not token:
        return {}

    request_params = dict(params or {})
    request_params["token"] = token

    try:
        response = requests.get(
            f"https://finnhub.io/api/v1/{endpoint.lstrip('/')}",
            params=request_params,
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()

        if isinstance(data, dict):
            msg = str(data).lower()
            if "error" in msg and len(data) <= 3:
                return {}

        return data

    except Exception:
        return {}


@st.cache_data(ttl=1800, show_spinner=False)
def get_finnhub_bundle(ticker: str) -> dict:
    ticker = ticker.upper().strip()

    if not finnhub_enabled():
        return {
            "enabled": False,
            "earnings_calendar": {},
            "eps_estimate_annual": {},
            "eps_estimate_quarterly": {},
            "revenue_estimate_annual": {},
            "revenue_estimate_quarterly": {},
        }

    today = datetime.utcnow().date()
    start = today - timedelta(days=365 * 8)
    end = today + timedelta(days=365 * 2)

    earnings_calendar_payload = finnhub_get_json(
        "calendar/earnings",
        {
            "symbol": ticker,
            "from": start.isoformat(),
            "to": end.isoformat(),
        },
    )

    if isinstance(earnings_calendar_payload, dict):
        earnings_calendar_rows = earnings_calendar_payload.get("earningsCalendar", [])
    elif isinstance(earnings_calendar_payload, list):
        earnings_calendar_rows = earnings_calendar_payload
    else:
        earnings_calendar_rows = []

    return {
        "enabled": True,
        "earnings_calendar": earnings_calendar_rows,
        "eps_estimate_annual": finnhub_get_json(
            "stock/eps-estimate",
            {"symbol": ticker, "freq": "annual"},
        ),
        "eps_estimate_quarterly": finnhub_get_json(
            "stock/eps-estimate",
            {"symbol": ticker, "freq": "quarterly"},
        ),
        "revenue_estimate_annual": finnhub_get_json(
            "stock/revenue-estimate",
            {"symbol": ticker, "freq": "annual"},
        ),
        "revenue_estimate_quarterly": finnhub_get_json(
            "stock/revenue-estimate",
            {"symbol": ticker, "freq": "quarterly"},
        ),
    }

def get_finnhub_earnings_calendar_rows(ticker: str) -> list[dict]:
    """
    Helper optionnel. Non utilisé par le pipeline principal.
    """
    today = datetime.utcnow().date()
    start_date = f"{today.year - 8}-01-01"
    end_date = f"{today.year + 2}-12-31"

    payload = finnhub_get_json(
        "calendar/earnings",
        {
            "symbol": ticker.upper().strip(),
            "from": start_date,
            "to": end_date,
        }
    )

    return finnhub_rows(payload, ["earningsCalendar"])


def sec_headers() -> dict:
    # La SEC demande un User-Agent identifiable. Garde une valeur stable.
    return {
        "User-Agent": "QuantTerminal/1.0 contact@example.com",
        "Accept-Encoding": "gzip, deflate",
        "Host": "data.sec.gov",
    }


@st.cache_data(ttl=86400, show_spinner=False)
def sec_ticker_to_cik(ticker: str):
    ticker = ticker.upper().strip()

    try:
        response = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers={"User-Agent": "QuantTerminal/1.0 contact@example.com"},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()

        if not isinstance(data, dict):
            return None

        for _, row in data.items():
            if str(row.get("ticker", "")).upper() == ticker:
                cik = str(row.get("cik_str", "")).zfill(10)
                return cik

    except Exception:
        return None

    return None


@st.cache_data(ttl=86400, show_spinner=False)
def get_sec_companyfacts_bundle(ticker: str) -> dict:
    cik = sec_ticker_to_cik(ticker)

    if not cik:
        return {
            "enabled": False,
            "cik": None,
            "companyfacts": {},
        }

    try:
        response = requests.get(
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
            headers=sec_headers(),
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()

        if not isinstance(data, dict):
            data = {}

        return {
            "enabled": True,
            "cik": cik,
            "companyfacts": data,
        }

    except Exception:
        return {
            "enabled": False,
            "cik": cik,
            "companyfacts": {},
        }


@st.cache_data(ttl=1800, show_spinner=False)
def get_company_intelligence_data(ticker: str) -> dict:
    ticker_obj = yf.Ticker(ticker)

    def safe_call(callable_obj, default):
        try:
            value = callable_obj()
            if value is None:
                return default
            return value
        except Exception:
            return default

    info = safe_call(lambda: ticker_obj.info, {})
    financials = safe_call(lambda: ticker_obj.financials, pd.DataFrame())
    quarterly_financials = safe_call(lambda: ticker_obj.quarterly_financials, pd.DataFrame())
    balance_sheet = safe_call(lambda: ticker_obj.balance_sheet, pd.DataFrame())
    quarterly_balance_sheet = safe_call(lambda: ticker_obj.quarterly_balance_sheet, pd.DataFrame())
    cashflow = safe_call(lambda: ticker_obj.cashflow, pd.DataFrame())
    quarterly_cashflow = safe_call(lambda: ticker_obj.quarterly_cashflow, pd.DataFrame())
    recommendations = safe_call(lambda: ticker_obj.recommendations, pd.DataFrame())
    earnings_dates = safe_call(lambda: ticker_obj.earnings_dates, pd.DataFrame())
    yf_news = safe_call(lambda: ticker_obj.news, [])

    fmp_bundle = get_fmp_company_bundle(ticker)
    if not isinstance(fmp_bundle, dict):
        fmp_bundle = {
            "enabled": False,
            "income_annual": [],
            "income_quarterly": [],
            "cashflow_annual": [],
            "cashflow_quarterly": [],
            "balance_annual": [],
            "balance_quarterly": [],
            "ratios_annual": [],
            "ratios_quarterly": [],
            "key_metrics_annual": [],
            "key_metrics_quarterly": [],
            "estimates_annual": [],
            "estimates_quarterly": [],
            "earnings_calendar": [],
            "earnings_surprises": [],
            "price_target_consensus": [],
            "news": [],
            "product_segments_raw": [],
            "geographic_segments_raw": [],
        }
    
    alpha_bundle = get_alpha_vantage_bundle(ticker)
    sec_bundle = get_sec_companyfacts_bundle(ticker)
    finnhub_bundle = get_finnhub_bundle(ticker)

    final_news = fmp_bundle.get("news") or yf_news

    return {
        "info": info if isinstance(info, dict) else {},
        "financials": financials if isinstance(financials, pd.DataFrame) else pd.DataFrame(),
        "quarterly_financials": quarterly_financials if isinstance(quarterly_financials, pd.DataFrame) else pd.DataFrame(),
        "balance_sheet": balance_sheet if isinstance(balance_sheet, pd.DataFrame) else pd.DataFrame(),
        "quarterly_balance_sheet": quarterly_balance_sheet if isinstance(quarterly_balance_sheet, pd.DataFrame) else pd.DataFrame(),
        "cashflow": cashflow if isinstance(cashflow, pd.DataFrame) else pd.DataFrame(),
        "quarterly_cashflow": quarterly_cashflow if isinstance(quarterly_cashflow, pd.DataFrame) else pd.DataFrame(),
        "recommendations": recommendations if isinstance(recommendations, pd.DataFrame) else pd.DataFrame(),
        "earnings_dates": earnings_dates if isinstance(earnings_dates, pd.DataFrame) else pd.DataFrame(),
        "news": final_news if isinstance(final_news, list) else [],
        "yf_news": yf_news if isinstance(yf_news, list) else [],
        "alpha": alpha_bundle,
        "sec": sec_bundle,
        "finnhub": finnhub_bundle,
        "fmp": fmp_bundle,
    }

def finnhub_calendar_to_income_estimate_long(
    company_data: dict,
    frequency: str
) -> pd.DataFrame:
    finnhub = company_data.get("finnhub", {})

    if not isinstance(finnhub, dict):
        return empty_estimate_long()

    if frequency == "Annuel":
        return empty_estimate_long()

    records = finnhub.get("earnings_calendar", []) or []

    if not isinstance(records, list) or not records:
        return empty_estimate_long()

    rows = []

    for item in records:
        if not isinstance(item, dict):
            continue

        date = parse_date_safe(first_present_flexible(item, [
            "date",
            "reportedDate",
            "reportDate",
            "fiscalDateEnding",
        ]))

        if pd.isna(date):
            continue

        eps_estimate = safe_float(first_present_flexible(item, [
            "epsEstimate",
            "epsEstimated",
            "estimatedEPS",
            "estimatedEps",
        ]))

        revenue_estimate = safe_float(first_present_flexible(item, [
            "revenueEstimate",
            "revenueEstimated",
            "estimatedRevenue",
        ]))

        if eps_estimate is not None:
            rows.append({
                "Date Estimate": date,
                "Period": period_label(date, "Trimestriel"),
                "Frequency": "Trimestriel",
                "Metric": "EPS",
                "Estimate": eps_estimate,
                "Source Estimate": "Finnhub earnings calendar",
            })

        if revenue_estimate is not None:
            rows.append({
                "Date Estimate": date,
                "Period": period_label(date, "Trimestriel"),
                "Frequency": "Trimestriel",
                "Metric": "Revenue",
                "Estimate": revenue_estimate,
                "Source Estimate": "Finnhub earnings calendar",
            })

    if not rows:
        return empty_estimate_long()

    quarterly = pd.DataFrame(rows)
    quarterly["Date Estimate"] = pd.to_datetime(quarterly["Date Estimate"], errors="coerce")
    quarterly["Estimate"] = pd.to_numeric(quarterly["Estimate"], errors="coerce")
    quarterly = quarterly.dropna(subset=["Estimate"])

    if quarterly.empty:
        return empty_estimate_long()

    if frequency == "Trimestriel":
        return quarterly[ESTIMATE_LONG_COLUMNS]

    # Agrégation annuelle approximative depuis les trimestres disponibles :
    # Revenue annual = somme des revenue estimates trimestrielles.
    # EPS annual = somme des EPS estimates trimestrielles.
    annual_rows = []

    quarterly["Year"] = quarterly["Date Estimate"].dt.year

    grouped = (
        quarterly.groupby(["Year", "Metric"], as_index=False)
        .agg({
            "Estimate": "sum",
            "Date Estimate": "max",
        })
    )

    for _, row in grouped.iterrows():
        year = int(row["Year"])
        metric = row["Metric"]
        estimate = safe_float(row["Estimate"])

        if estimate is None:
            continue

        annual_rows.append({
            "Date Estimate": row["Date Estimate"],
            "Period": f"FY {year}",
            "Frequency": "Annuel",
            "Metric": metric,
            "Estimate": estimate,
            "Source Estimate": "Finnhub earnings calendar aggregate",
        })

    if not annual_rows:
        return empty_estimate_long()

    return pd.DataFrame(annual_rows)[ESTIMATE_LONG_COLUMNS]
