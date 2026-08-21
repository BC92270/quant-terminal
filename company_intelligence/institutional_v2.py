"""Second-generation institutional analytics for Company Intelligence.

Design goals
------------
* Treat unavailable data as unavailable, never as a synthetic neutral signal.
* Separate *reported holdings* from inferred positioning proxies.
* Separate informative insider trades from grants/gifts/tax/option mechanics.
* Build peer comparisons from a similarity-ranked universe rather than blindly using a
  provider list as one homogeneous valuation peer set.
* Derive capital-allocation analytics from reported cash-flow / key-metric fields.
* Keep every composite interpretable: raw components are returned alongside scores.

The module is defensive by construction. Provider plans and schemas can differ; every
loader uses candidate field names and falls back gracefully.
"""
from __future__ import annotations

import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
import requests
import streamlit as st
import yfinance as yf

from .common import clamp, first_present_flexible, safe_float, safe_int
from .providers import fmp_rows, get_fmp_api_key
from .institutional_metrics import calculate_roic, calculate_roic_audit, calculate_data_confidence

FMP_STABLE_BASE = "https://financialmodelingprep.com/stable"


# -----------------------------------------------------------------------------
# Generic provider helpers
# -----------------------------------------------------------------------------

def _clean_symbol(value: Any) -> str:
    return str(value or "").upper().strip().replace(".", "-")


def _fmp_json(endpoint: str, params: dict[str, Any] | None = None):
    key = get_fmp_api_key()
    if not key:
        return []
    query = dict(params or {})
    query["apikey"] = key
    try:
        response = requests.get(
            f"{FMP_STABLE_BASE}/{endpoint.lstrip('/')}",
            params=query,
            timeout=18,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            low = str(payload).lower()
            if "invalid api key" in low or ("limit" in low and "exceed" in low):
                return []
        return payload
    except Exception:
        return []


def _records(payload) -> list[dict]:
    return [x for x in fmp_rows(payload) if isinstance(x, dict)]


def _frame(payload) -> pd.DataFrame:
    rows = _records(payload)
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _pick(row: dict | pd.Series, keys: list[str], default=None):
    obj = row.to_dict() if isinstance(row, pd.Series) else row
    return first_present_flexible(obj or {}, keys, default)


def _num(row: dict | pd.Series, keys: list[str], default=None):
    return safe_float(_pick(row, keys, default), default)


def _pct_normalize(value) -> float | None:
    value = safe_float(value)
    if value is None or pd.isna(value):
        return None
    # Holder feeds can expose either 0.08 or 8.0 for 8%.
    if abs(value) > 1.5:
        return value / 100.0
    return value


def _date_series(df: pd.DataFrame, candidates: list[str]) -> pd.Series:
    for col in candidates:
        if col in df.columns:
            return pd.to_datetime(df[col], errors="coerce", utc=True).dt.tz_convert(None)
    return pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")


# -----------------------------------------------------------------------------
# Ownership V2
# -----------------------------------------------------------------------------

_PASSIVE_PATTERNS = [
    r"\bindex\b", r"\bs&p\b", r"\bspdr\b", r"\bishares\b", r"\betf\b",
    r"total stock market", r"total market", r"nasdaq[- ]?100", r"\bqqq\b",
    r"russell", r"index fund", r"index trust", r"institutional index",
]

_MIXED_MANAGER_PATTERNS = [
    r"blackrock", r"vanguard", r"state street", r"fidelity", r"fmr",
    r"jpmorgan", r"morgan stanley", r"goldman sachs", r"invesco", r"geode",
    r"capital group", r"wellington", r"t\. rowe price", r"price \(t\.rowe\)",
]


def classify_holder(name: Any, layer: str = "institution") -> str:
    text = re.sub(r"\s+", " ", str(name or "").strip().lower())
    if not text:
        return "Unknown"
    if any(re.search(p, text, flags=re.I) for p in _PASSIVE_PATTERNS):
        return "Passive / Index"
    if layer == "fund":
        return "Active fund"
    if any(re.search(p, text, flags=re.I) for p in _MIXED_MANAGER_PATTERNS):
        return "Asset manager / Mixed"
    if any(k in text for k in ["pension", "retirement", "teachers", "public employees"]):
        return "Pension / Long-only"
    if any(k in text for k in ["capital management", "partners", "advisors", "investment management", "asset management"]):
        return "Active / Manager"
    return "Institution / Other"


def _normalize_holder_frame(df: pd.DataFrame, layer: str) -> pd.DataFrame:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()
    out = df.copy()

    holder_col = next((c for c in ["Holder", "holder", "Name", "name"] if c in out.columns), None)
    pct_col = next((c for c in ["pctHeld", "% Out", "pct_held", "Percent Out", "percentageOut"] if c in out.columns), None)
    change_col = next((c for c in ["pctChange", "pct_change", "% Change", "Percent Change"] if c in out.columns), None)
    shares_col = next((c for c in ["Shares", "shares", "sharesHeld"] if c in out.columns), None)
    value_col = next((c for c in ["Value", "value", "marketValue"] if c in out.columns), None)
    date_col = next((c for c in ["Date Reported", "DateReported", "dateReported", "reportDate"] if c in out.columns), None)

    norm = pd.DataFrame(index=out.index)
    norm["Holder"] = out[holder_col].astype(str) if holder_col else "N/A"
    norm["Layer"] = layer
    norm["Holder Type"] = norm["Holder"].apply(lambda x: classify_holder(x, layer=layer))
    norm["Pct Held"] = out[pct_col].apply(_pct_normalize) if pct_col else np.nan
    norm["Pct Change"] = pd.to_numeric(out[change_col], errors="coerce") if change_col else np.nan
    norm["Shares"] = pd.to_numeric(out[shares_col], errors="coerce") if shares_col else np.nan
    norm["Value"] = pd.to_numeric(out[value_col], errors="coerce") if value_col else np.nan
    norm["Date Reported"] = pd.to_datetime(out[date_col], errors="coerce") if date_col else pd.NaT

    # pctChange is normally fractional, but guard against feeds using whole percentages.
    finite_change = pd.to_numeric(norm["Pct Change"], errors="coerce")
    if finite_change.notna().any() and finite_change.abs().quantile(0.9) > 2.0:
        norm["Pct Change"] = finite_change / 100.0

    return norm.reset_index(drop=True)


def build_ownership_intelligence(
    yf_bundle: dict[str, pd.DataFrame],
    fmp_history: pd.DataFrame | None = None,
) -> dict[str, Any]:
    yf_bundle = yf_bundle if isinstance(yf_bundle, dict) else {}
    institutional = _normalize_holder_frame(yf_bundle.get("institutional_holders", pd.DataFrame()), "institution")
    funds = _normalize_holder_frame(yf_bundle.get("mutualfund_holders", pd.DataFrame()), "fund")

    if institutional.empty:
        return {
            "holders": institutional,
            "funds": funds,
            "summary": {},
            "score": None,
            "score_basis": "Unavailable",
        }

    weights = pd.to_numeric(institutional["Pct Held"], errors="coerce").fillna(0).clip(lower=0)
    changes = pd.to_numeric(institutional["Pct Change"], errors="coerce")
    valid_change = changes.notna()

    top1 = float(weights.nlargest(1).sum()) if weights.sum() > 0 else None
    top5 = float(weights.nlargest(5).sum()) if weights.sum() > 0 else None
    top10 = float(weights.nlargest(10).sum()) if weights.sum() > 0 else None
    hhi = float((weights ** 2).sum()) if weights.sum() > 0 else None

    up = int((changes > 0.0025).sum()) if valid_change.any() else 0
    down = int((changes < -0.0025).sum()) if valid_change.any() else 0
    stable = int((valid_change & changes.between(-0.0025, 0.0025)).sum()) if valid_change.any() else 0
    breadth_n = up + down
    breadth = (up - down) / breadth_n if breadth_n else None

    # Position-change proxy: a robust signed indicator, not a cash-flow estimate.
    # tanh caps very large pctChange observations and prevents a single holder from dominating.
    if valid_change.any() and weights[valid_change].sum() > 0:
        robust_change = np.tanh(changes[valid_change].clip(-0.50, 0.50) / 0.10)
        weighted_proxy = float(np.average(robust_change, weights=weights[valid_change]))
    elif valid_change.any():
        weighted_proxy = float(np.nanmean(np.tanh(changes[valid_change].clip(-0.50, 0.50) / 0.10)))
    else:
        weighted_proxy = None

    # A large asset manager can contain both passive and discretionary books.  Treating
    # every BlackRock/Vanguard/State Street aggregate as "active" created a false equality
    # between total and active proxies in V2.1.  Only clearly discretionary holder types
    # contribute to Active Position Proxy.
    active_mask = institutional["Holder Type"].isin([
        "Active / Manager", "Active fund", "Pension / Long-only", "Institution / Other"
    ])
    active_valid = valid_change & active_mask
    if active_valid.any() and weights[active_valid].sum() > 0:
        active_proxy = float(np.average(
            np.tanh(changes[active_valid].clip(-0.50, 0.50) / 0.10),
            weights=weights[active_valid],
        ))
    elif active_valid.any():
        active_proxy = float(np.nanmean(np.tanh(changes[active_valid].clip(-0.50, 0.50) / 0.10)))
    else:
        active_proxy = None

    passive_share = None
    if not funds.empty:
        fund_weights = pd.to_numeric(funds["Pct Held"], errors="coerce").fillna(0).clip(lower=0)
        denom = float(fund_weights.sum())
        if denom > 0:
            passive_share = float(fund_weights[funds["Holder Type"].eq("Passive / Index")].sum() / denom)

    score = None
    score_basis = "Yahoo holder change proxy"
    # Prefer a real multi-quarter 13F aggregate when available; otherwise use the clearly
    # labelled Yahoo reported-holder change proxy.
    if isinstance(fmp_history, pd.DataFrame) and not fmp_history.empty:
        score = 50.0
        latest = fmp_history.iloc[0]
        prev = fmp_history.iloc[1] if len(fmp_history) > 1 else None
        sh_chg = safe_float(latest.get("Shares Change"))
        if sh_chg is not None:
            score += 10 if sh_chg > 0 else -10 if sh_chg < 0 else 0
        if prev is not None:
            inv_now = safe_float(latest.get("Investors"))
            inv_prev = safe_float(prev.get("Investors"))
            if inv_now is not None and inv_prev not in [None, 0]:
                score += clamp((inv_now / inv_prev - 1) * 120, -12, 12)
            own_now = safe_float(latest.get("Ownership %"))
            own_prev = safe_float(prev.get("Ownership %"))
            if own_now is not None and own_prev is not None:
                score += clamp((own_now - own_prev) * 80, -10, 10)
        if weighted_proxy is not None:
            score += 5 * weighted_proxy
        score = round(clamp(score), 1)
        score_basis = "FMP 13F aggregate + holder proxy"
    elif weighted_proxy is not None or breadth is not None:
        score = 50.0
        if weighted_proxy is not None:
            score += 18 * weighted_proxy
        if active_proxy is not None:
            score += 10 * active_proxy
        if breadth is not None:
            score += 10 * breadth
        # Concentration is treated as crowding / fragility, not direction.
        if top10 is not None and top10 > 0.75:
            score -= 5
        elif top10 is not None and top10 > 0.60:
            score -= 2
        score = round(clamp(score), 1)

    summary = {
        "top1": top1,
        "top5": top5,
        "top10": top10,
        "hhi": hhi,
        "holder_records": int(len(institutional)),
        "up_holders": up,
        "down_holders": down,
        "stable_holders": stable,
        "breadth": breadth,
        "weighted_position_change_proxy": weighted_proxy,
        "active_position_change_proxy": active_proxy,
        "passive_fund_share": passive_share,
        "score_basis": score_basis,
    }
    return {
        "holders": institutional,
        "funds": funds,
        "summary": summary,
        "score": score,
        "score_basis": score_basis,
    }


# -----------------------------------------------------------------------------
# Insider V2
# -----------------------------------------------------------------------------

_INSIDER_CATEGORY_MAP = {
    "P": "Open-market purchase",
    "S": "Open-market sale",
    "A": "Grant / award",
    "G": "Gift",
    "F": "Tax withholding / issuer payment",
    "M": "Option exercise / conversion",
    "D": "Disposition to issuer",
    "C": "Conversion",
}


def _classify_insider_transaction(text: str, code: str, acq_disp: str) -> tuple[str, bool, int]:
    low = str(text or "").lower()
    code_u = str(code or "").strip().upper()
    acq_u = str(acq_disp or "").strip().upper()

    # Explicit Form 4 transaction codes first.
    compact_code = re.split(r"[- /]", code_u)[0] if code_u else ""
    if compact_code in _INSIDER_CATEGORY_MAP:
        cat = _INSIDER_CATEGORY_MAP[compact_code]
        if compact_code == "P":
            return cat, True, +1
        if compact_code == "S":
            return cat, True, -1
        return cat, False, 0

    if any(k in low for k in ["open market purchase", "purchase at", "bought", "buy"]):
        return "Open-market purchase", True, +1
    if any(k in low for k in ["open market sale", "sold", "sale at", "sale of"]):
        return "Open-market sale", True, -1
    if any(k in low for k in ["award", "grant", "restricted stock", "rsu"]):
        return "Grant / award", False, 0
    if "gift" in low:
        return "Gift", False, 0
    if any(k in low for k in ["tax", "withholding"]):
        return "Tax withholding / issuer payment", False, 0
    if any(k in low for k in ["option", "exercise", "conversion"]):
        return "Option exercise / conversion", False, 0

    # Acquisition/disposition alone is not enough to call an open-market trade.
    if acq_u == "A":
        return "Other acquisition", False, 0
    if acq_u == "D":
        return "Other disposition", False, 0
    return "Other / unclassified", False, 0


def _role_weight(role: Any) -> float:
    low = str(role or "").lower()
    if any(k in low for k in ["chief executive", " ceo", "chief financial", " cfo"]):
        return 1.50
    if "president" in low or "chief operating" in low or "coo" in low:
        return 1.25
    if "director" in low:
        return 1.00
    return 0.85


def normalize_insider_transactions(
    fmp_transactions: pd.DataFrame,
    yf_transactions: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    if isinstance(fmp_transactions, pd.DataFrame) and not fmp_transactions.empty:
        for _, r in fmp_transactions.iterrows():
            code = _pick(r, ["transactionType", "transactionCode", "type"] , "")
            acq = _pick(r, ["acquisitionOrDisposition", "acquisitionDisposition"], "")
            text = _pick(r, ["transactionDescription", "securityName", "transactionType"], "")
            category, informative, direction = _classify_insider_transaction(str(text), str(code), str(acq))
            shares = abs(_num(r, ["securitiesTransacted", "shares", "securitiesOwned"], 0) or 0)
            price = abs(_num(r, ["price", "transactionPrice"], 0) or 0)
            value = shares * price if shares and price else _num(r, ["value", "transactionValue"], 0) or 0
            role = _pick(r, ["typeOfOwner", "reportingOwnerRelationship", "position", "title"], "")
            rows.append({
                "Date": pd.to_datetime(_pick(r, ["transactionDate", "filingDate", "date"]), errors="coerce"),
                "Insider": _pick(r, ["reportingName", "insiderName", "name"], "N/A"),
                "Role": role,
                "Category": category,
                "Informative": bool(informative),
                "Direction": int(direction),
                "Shares": shares,
                "Price": price if price else np.nan,
                "Value": value if value else np.nan,
                "Role Weight": _role_weight(role),
                "Source": "FMP insider",
                "Raw Text": str(text),
            })

    # Yahoo is a useful fallback and often exposes readable transaction text.
    if isinstance(yf_transactions, pd.DataFrame) and not yf_transactions.empty:
        for _, r in yf_transactions.iterrows():
            text = str(_pick(r, ["Text", "text", "Transaction", "transaction"], ""))
            code = str(_pick(r, ["Transaction", "transaction", "Code"], ""))
            category, informative, direction = _classify_insider_transaction(text, code, "")
            shares = abs(_num(r, ["Shares", "shares"], 0) or 0)
            value = abs(_num(r, ["Value", "value"], 0) or 0)
            price = value / shares if value and shares else np.nan
            role = _pick(r, ["Position", "position", "Title", "title"], "")
            rows.append({
                "Date": pd.to_datetime(_pick(r, ["Start Date", "startDate", "Date", "date"]), errors="coerce"),
                "Insider": _pick(r, ["Insider", "insider", "Name", "name"], "N/A"),
                "Role": role,
                "Category": category,
                "Informative": bool(informative),
                "Direction": int(direction),
                "Shares": shares,
                "Price": price,
                "Value": value if value else np.nan,
                "Role Weight": _role_weight(role),
                "Source": "Yahoo insider",
                "Raw Text": text,
            })

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out = out.drop_duplicates(subset=["Date", "Insider", "Category", "Shares", "Source"], keep="first")
    return out.sort_values("Date", ascending=False, na_position="last").reset_index(drop=True)


def build_insider_intelligence(
    fmp_transactions: pd.DataFrame,
    yf_transactions: pd.DataFrame,
) -> dict[str, Any]:
    tx = normalize_insider_transactions(fmp_transactions, yf_transactions)
    if tx.empty:
        return {"transactions": tx, "summary": {}, "score": None}

    now = pd.Timestamp.utcnow().tz_localize(None)
    informative = tx[tx["Informative"].eq(True)].copy()
    if informative.empty:
        return {
            "transactions": tx,
            "summary": {
                "informative_count_90d": 0,
                "status": "No informative open-market activity",
            },
            "score": None,
        }

    informative["Age Days"] = (now - pd.to_datetime(informative["Date"], errors="coerce")).dt.days
    recent90 = informative[informative["Age Days"].between(0, 90, inclusive="both")].copy()
    recent180 = informative[informative["Age Days"].between(0, 180, inclusive="both")].copy()

    basis = recent180 if not recent180.empty else informative.head(50).copy()
    weighted_value = pd.to_numeric(basis["Value"], errors="coerce")
    has_value = weighted_value.notna().sum() >= max(1, len(basis) // 3)

    if has_value:
        magnitude = weighted_value.fillna(0).abs()
    else:
        magnitude = pd.to_numeric(basis["Shares"], errors="coerce").fillna(0).abs()

    role_w = pd.to_numeric(basis["Role Weight"], errors="coerce").fillna(1.0)
    signed = magnitude * role_w * pd.to_numeric(basis["Direction"], errors="coerce").fillna(0)
    denom = float((magnitude * role_w).sum())
    net_ratio = float(signed.sum() / denom) if denom > 0 else None

    buyers90 = recent90[recent90["Direction"] > 0]["Insider"].dropna().astype(str).nunique()
    sellers90 = recent90[recent90["Direction"] < 0]["Insider"].dropna().astype(str).nunique()
    buys90 = int((recent90["Direction"] > 0).sum())
    sells90 = int((recent90["Direction"] < 0).sum())

    score = None
    if net_ratio is not None:
        score = 50 + 32 * net_ratio
        if buyers90 >= 3 and buys90 > sells90:
            score += 8
        elif sellers90 >= 3 and sells90 > buys90:
            score -= 8
        score = round(clamp(score), 1)

    summary = {
        "informative_count_90d": int(len(recent90)),
        "informative_count_180d": int(len(recent180)),
        "buyers_90d": int(buyers90),
        "sellers_90d": int(sellers90),
        "buy_transactions_90d": buys90,
        "sell_transactions_90d": sells90,
        "net_informative_ratio": net_ratio,
        "basis": "Value-weighted" if has_value else "Share-weighted",
        "status": "Informative open-market activity" if len(recent90) else "No informative activity in last 90d",
    }
    return {"transactions": tx, "summary": summary, "score": score}


# -----------------------------------------------------------------------------
# Peer Intelligence V2
# -----------------------------------------------------------------------------

PEER_METRIC_CONTRACT = {
    "Revenue Growth": "TTM YoY: latest four reported quarters vs prior four quarters",
    "Gross Margin": "TTM gross profit / TTM revenue",
    "Operating Margin": "TTM operating income / TTM revenue",
    "FCF Margin": "TTM free cash flow / TTM revenue",
    "ROIC": "TTM NOPAT / average invested capital (debt + equity - cash); canonical engine shared with Capital Allocation",
    "FCF Yield": "TTM free cash flow / current market capitalization",
    "P/E TTM": "Trailing earnings multiple",
    "Forward P/E": "Forward/NTM earnings multiple from available consensus field",
    "EV/Sales": "Enterprise value / trailing revenue",
    "EV/EBITDA": "Enterprise value / trailing EBITDA",
}


def _statement_series(statement: pd.DataFrame, names: list[str]) -> pd.Series:
    if not isinstance(statement, pd.DataFrame) or statement.empty:
        return pd.Series(dtype=float)
    for name in names:
        if name in statement.index:
            values = pd.to_numeric(statement.loc[name], errors="coerce").dropna()
            if values.empty:
                continue
            try:
                idx = pd.to_datetime(values.index, errors="coerce")
                values.index = idx
                values = values[values.index.notna()].sort_index(ascending=False)
            except Exception:
                pass
            return values
    return pd.Series(dtype=float)


def _ttm_sum(statement: pd.DataFrame, names: list[str]) -> float | None:
    series = _statement_series(statement, names)
    if series.empty:
        return None
    # Quarterly statements need four observations. Annual fallbacks are accepted as one
    # reported period only when quarterly coverage is not available at the caller level.
    n = min(4, len(series))
    return safe_float(series.iloc[:n].sum())


def _ttm_yoy_growth(statement: pd.DataFrame, names: list[str]) -> float | None:
    series = _statement_series(statement, names)
    if len(series) < 8:
        return None
    current = safe_float(series.iloc[:4].sum())
    previous = safe_float(series.iloc[4:8].sum())
    if current is None or previous in [None, 0]:
        return None
    return current / previous - 1


def _statement_point(statement: pd.DataFrame, names: list[str], position: int = 0) -> float | None:
    series = _statement_series(statement, names)
    if series.empty or position >= len(series):
        return None
    return safe_float(series.iloc[position])


def _fcf_from_statements(cashflow: pd.DataFrame) -> float | None:
    direct = _ttm_sum(cashflow, ["Free Cash Flow"])
    if direct is not None:
        return direct
    ocf = _ttm_sum(cashflow, ["Operating Cash Flow", "Total Cash From Operating Activities"])
    capex = _ttm_sum(cashflow, ["Capital Expenditure", "Capital Expenditures"])
    if ocf is None or capex is None:
        return None
    # yfinance commonly reports capex as a negative outflow.
    return ocf + capex if capex < 0 else ocf - abs(capex)


def _invested_capital_at(balance: pd.DataFrame, position: int = 0) -> float | None:
    direct = _statement_point(balance, ["Invested Capital"], position)
    if direct is not None and direct > 0:
        return direct
    debt = _statement_point(balance, ["Total Debt", "Long Term Debt And Capital Lease Obligation", "Long Term Debt"], position)
    equity = _statement_point(balance, ["Stockholders Equity", "Total Stockholder Equity", "Common Stock Equity"], position)
    cash = _statement_point(balance, ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents", "Cash"], position)
    if equity is None:
        return None
    invested = (debt or 0.0) + equity - (cash or 0.0)
    return invested if invested > 0 else None


def _roic_audit_from_yfinance_frames(financials_q: pd.DataFrame, balance_q: pd.DataFrame) -> dict[str, Any]:
    """Canonical TTM ROIC bridge over quarterly yfinance statements."""
    operating_income = _ttm_sum(financials_q, ["Operating Income"])
    pretax = _ttm_sum(financials_q, ["Pretax Income", "Income Before Tax"])
    tax = _ttm_sum(financials_q, ["Tax Provision", "Income Tax Expense"])
    prior_pos = 4 if isinstance(balance_q, pd.DataFrame) and len(balance_q.columns) >= 5 else 1
    audit = calculate_roic_audit(
        operating_income=operating_income,
        pretax_income=pretax,
        tax_expense=tax,
        current_debt=_statement_point(balance_q, ["Total Debt", "Long Term Debt And Capital Lease Obligation", "Long Term Debt"], 0),
        current_equity=_statement_point(balance_q, ["Stockholders Equity", "Total Stockholder Equity", "Common Stock Equity"], 0),
        current_cash=_statement_point(balance_q, ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents", "Cash"], 0),
        prior_debt=_statement_point(balance_q, ["Total Debt", "Long Term Debt And Capital Lease Obligation", "Long Term Debt"], prior_pos),
        prior_equity=_statement_point(balance_q, ["Stockholders Equity", "Total Stockholder Equity", "Common Stock Equity"], prior_pos),
        prior_cash=_statement_point(balance_q, ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents", "Cash"], prior_pos),
        current_invested_capital=_statement_point(balance_q, ["Invested Capital"], 0),
        prior_invested_capital=_statement_point(balance_q, ["Invested Capital"], prior_pos),
    )
    audit["basis"] = "TTM · latest four quarters / prior-year invested-capital observation"
    return audit


def _roic_from_yfinance_frames(financials_q: pd.DataFrame, balance_q: pd.DataFrame) -> float | None:
    """Canonical TTM ROIC wrapper over quarterly yfinance statements."""
    return safe_float(_roic_audit_from_yfinance_frames(financials_q, balance_q).get("roic"))


def _company_snapshot(symbol: str) -> dict[str, Any]:
    """Similarity snapshot under a strict cross-company metric contract.

    Operating metrics are calculated from the same TTM statement definitions for target
    and peers whenever quarterly statements are available. Provider ratios are fallbacks,
    not mixed silently with statement-derived values.
    """
    symbol = _clean_symbol(symbol)
    profile_rows = _records(_fmp_json("profile", {"symbol": symbol}))
    profile = profile_rows[0] if profile_rows else {}
    key_rows = _records(_fmp_json("key-metrics-ttm", {"symbol": symbol}))
    key = key_rows[0] if key_rows else {}
    ratio_rows = _records(_fmp_json("ratios-ttm", {"symbol": symbol}))
    ratios = ratio_rows[0] if ratio_rows else {}

    yf_info: dict[str, Any] = {}
    q_fin = pd.DataFrame(); q_cf = pd.DataFrame(); q_bs = pd.DataFrame()
    annual_fin = pd.DataFrame(); annual_cf = pd.DataFrame(); annual_bs = pd.DataFrame()
    try:
        ticker_obj = yf.Ticker(symbol)
        info = ticker_obj.info
        if isinstance(info, dict):
            yf_info = info
        try: q_fin = ticker_obj.quarterly_financials
        except Exception: pass
        try: q_cf = ticker_obj.quarterly_cashflow
        except Exception: pass
        try: q_bs = ticker_obj.quarterly_balance_sheet
        except Exception: pass
        try: annual_fin = ticker_obj.financials
        except Exception: pass
        try: annual_cf = ticker_obj.cashflow
        except Exception: pass
        try: annual_bs = ticker_obj.balance_sheet
        except Exception: pass
    except Exception:
        pass

    def first(*values):
        for value in values:
            if value is None:
                continue
            try:
                if pd.isna(value):
                    continue
            except Exception:
                pass
            return value
        return None

    market_cap = first(safe_float(profile.get("marketCap")), safe_float(yf_info.get("marketCap")))

    # Strict TTM contract. Annual statement fallback is used only when quarterly data do
    # not expose a usable numerator/denominator.
    revenue_ttm = _ttm_sum(q_fin, ["Total Revenue", "Operating Revenue"])
    gross_profit_ttm = _ttm_sum(q_fin, ["Gross Profit"])
    operating_income_ttm = _ttm_sum(q_fin, ["Operating Income"])
    fcf_ttm = _fcf_from_statements(q_cf)
    revenue_growth = _ttm_yoy_growth(q_fin, ["Total Revenue", "Operating Revenue"])

    if revenue_ttm in [None, 0]:
        revenue_ttm = _statement_point(annual_fin, ["Total Revenue", "Operating Revenue"], 0) or safe_float(yf_info.get("totalRevenue"))
    if gross_profit_ttm is None:
        gross_profit_ttm = _statement_point(annual_fin, ["Gross Profit"], 0)
    if operating_income_ttm is None:
        operating_income_ttm = _statement_point(annual_fin, ["Operating Income"], 0)
    if fcf_ttm is None:
        fcf_ttm = _statement_point(annual_cf, ["Free Cash Flow"], 0)
        if fcf_ttm is None:
            fcf_ttm = safe_float(yf_info.get("freeCashflow"))

    gross_margin = gross_profit_ttm / revenue_ttm if gross_profit_ttm is not None and revenue_ttm not in [None, 0] else safe_float(yf_info.get("grossMargins"))
    operating_margin = operating_income_ttm / revenue_ttm if operating_income_ttm is not None and revenue_ttm not in [None, 0] else safe_float(yf_info.get("operatingMargins"))
    fcf_margin = fcf_ttm / revenue_ttm if fcf_ttm is not None and revenue_ttm not in [None, 0] else None

    roic_audit = _roic_audit_from_yfinance_frames(q_fin, q_bs)
    roic_calc = safe_float(roic_audit.get("roic"))
    if roic_calc is None and not annual_fin.empty and not annual_bs.empty:
        # Same canonical formula, explicitly using annual current/prior observations.
        prior_pos = 1 if len(annual_bs.columns) >= 2 else 0
        roic_audit = calculate_roic_audit(
            operating_income=_statement_point(annual_fin, ["Operating Income"], 0),
            pretax_income=_statement_point(annual_fin, ["Pretax Income", "Income Before Tax"], 0),
            tax_expense=_statement_point(annual_fin, ["Tax Provision", "Income Tax Expense"], 0),
            current_debt=_statement_point(annual_bs, ["Total Debt", "Long Term Debt"], 0),
            current_equity=_statement_point(annual_bs, ["Stockholders Equity", "Total Stockholder Equity", "Common Stock Equity"], 0),
            current_cash=_statement_point(annual_bs, ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents", "Cash"], 0),
            prior_debt=_statement_point(annual_bs, ["Total Debt", "Long Term Debt"], prior_pos),
            prior_equity=_statement_point(annual_bs, ["Stockholders Equity", "Total Stockholder Equity", "Common Stock Equity"], prior_pos),
            prior_cash=_statement_point(annual_bs, ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents", "Cash"], prior_pos),
            current_invested_capital=_statement_point(annual_bs, ["Invested Capital"], 0),
            prior_invested_capital=_statement_point(annual_bs, ["Invested Capital"], prior_pos),
        )
        roic_audit["basis"] = "FY fallback · latest fiscal year / prior fiscal-year invested capital"
        roic_calc = safe_float(roic_audit.get("roic"))

    roic = first(roic_calc, _num(key, ["returnOnInvestedCapitalTTM", "returnOnInvestedCapital"]), safe_float(yf_info.get("returnOnInvestedCapital")))
    if roic_calc is None:
        roic_audit = {}
    fcf_yield = (fcf_ttm / market_cap) if fcf_ttm is not None and market_cap not in [None, 0] else first(_num(key, ["freeCashFlowYieldTTM", "freeCashFlowYield"]), None)

    return {
        "Symbol": symbol,
        "Company": first(profile.get("companyName"), yf_info.get("longName"), yf_info.get("shortName"), symbol),
        "Sector": first(profile.get("sector"), yf_info.get("sector"), ""),
        "Industry": first(profile.get("industry"), yf_info.get("industry"), ""),
        "Market Cap": market_cap,
        "Price": first(safe_float(profile.get("price")), safe_float(yf_info.get("currentPrice"))),
        "Revenue Growth": first(revenue_growth, safe_float(yf_info.get("revenueGrowth"))),
        "Gross Margin": gross_margin,
        "Operating Margin": operating_margin,
        "FCF Margin": fcf_margin,
        "ROIC": roic,
        "FCF Yield": fcf_yield,
        "P/E TTM": first(_num(ratios, ["priceToEarningsRatioTTM", "priceEarningsRatioTTM", "priceEarningsRatio"]), safe_float(yf_info.get("trailingPE"))),
        "Forward P/E": safe_float(yf_info.get("forwardPE")),
        "EV/Sales": first(_num(ratios, ["enterpriseValueMultipleRevenueTTM", "enterpriseValueToSalesTTM", "enterpriseValueToRevenueTTM"]), safe_float(yf_info.get("enterpriseToRevenue"))),
        "EV/EBITDA": first(_num(ratios, ["enterpriseValueMultipleTTM", "enterpriseValueToEBITDATTM"]), safe_float(yf_info.get("enterpriseToEbitda"))),
        "Metric Basis": "TTM statement contract + valuation fallbacks",
        "Source": "Yahoo statements + FMP TTM ratios fallback",
        "_ROIC Audit": roic_audit,
    }


def _curated_peer_candidates(target: dict[str, Any]) -> list[str]:
    """Deterministic fallback universe when provider peer/screener endpoints are gated.

    The lists are intentionally broad candidate pools.  They are still similarity-ranked
    by the normal engine, so this fallback does not imply every name is a valuation peer.
    """
    industry = str(target.get("Industry") or "").lower()
    sector = str(target.get("Sector") or "").lower()
    pools = {
        "semiconductor": ["AMD", "AVGO", "QCOM", "MRVL", "INTC", "MU", "ADI", "TXN", "ARM", "MCHP", "NXPI", "ON", "MPWR"],
        "software": ["MSFT", "ORCL", "CRM", "ADBE", "NOW", "INTU", "SNOW", "DDOG", "MDB", "PLTR"],
        "internet": ["GOOGL", "META", "AMZN", "NFLX", "PINS", "SNAP", "UBER", "ABNB", "DASH"],
        "bank": ["JPM", "BAC", "WFC", "C", "GS", "MS", "PNC", "USB", "BK", "STT"],
        "insurance": ["BRK-B", "PGR", "CB", "AIG", "MET", "PRU", "ALL", "TRV"],
        "biotech": ["AMGN", "GILD", "VRTX", "REGN", "BIIB", "MRNA", "ALNY", "BMRN"],
        "pharmaceutical": ["LLY", "JNJ", "MRK", "PFE", "ABBV", "BMY", "AZN", "NVS"],
        "oil": ["XOM", "CVX", "COP", "EOG", "OXY", "SLB", "HAL", "MPC", "VLO"],
        "aerospace": ["GE", "RTX", "LMT", "NOC", "GD", "BA", "TDG", "HEI"],
        "automotive": ["TSLA", "GM", "F", "TM", "HMC", "RIVN", "STLA"],
        "retail": ["WMT", "COST", "TGT", "HD", "LOW", "TJX", "ROST", "BBY"],
        "reit": ["PLD", "AMT", "EQIX", "WELL", "SPG", "O", "PSA", "DLR"],
    }
    for key, values in pools.items():
        if key in industry:
            return values.copy()
    if "technology" in sector:
        return ["MSFT", "AAPL", "AVGO", "AMD", "QCOM", "ORCL", "CRM", "ADBE", "NOW", "INTU"]
    if "financial" in sector:
        return pools["bank"].copy()
    if "health" in sector:
        return pools["pharmaceutical"].copy()
    if "energy" in sector:
        return pools["oil"].copy()
    return []


@st.cache_data(ttl=43200, show_spinner=False)
def _screener_candidates(sector: str, industry: str, limit: int = 80) -> pd.DataFrame:
    if not get_fmp_api_key():
        return pd.DataFrame()
    params: dict[str, Any] = {"limit": int(limit), "isEtf": "false", "isFund": "false"}
    if industry:
        params["industry"] = industry
    elif sector:
        params["sector"] = sector
    return _frame(_fmp_json("company-screener", params))


def _similarity(target: dict, peer: dict, provider_peer: bool) -> float:
    score = 0.0
    target_ind = str(target.get("Industry") or "").strip().lower()
    peer_ind = str(peer.get("Industry") or "").strip().lower()
    target_sec = str(target.get("Sector") or "").strip().lower()
    peer_sec = str(peer.get("Sector") or "").strip().lower()
    if target_ind and peer_ind and target_ind == peer_ind:
        score += 50
    elif target_ind and peer_ind and (target_ind in peer_ind or peer_ind in target_ind):
        score += 38
    if target_sec and peer_sec and target_sec == peer_sec:
        score += 18

    tm = safe_float(target.get("Market Cap"))
    pm = safe_float(peer.get("Market Cap"))
    if tm and pm and tm > 0 and pm > 0:
        log_dist = abs(math.log10(tm) - math.log10(pm))
        score += max(0, 18 - 12 * log_dist)
    if provider_peer:
        score += 6
    return float(score)


def _percentile(values: pd.Series, target_value: float | None, higher_is_better: bool = True) -> float | None:
    target_value = safe_float(target_value)
    vals = pd.to_numeric(values, errors="coerce").dropna()
    if target_value is None or vals.empty:
        return None
    rank = float((vals <= target_value).mean())
    pct = 100 * rank
    return pct if higher_is_better else 100 - pct


@st.cache_data(ttl=43200, show_spinner=False)
def load_peer_intelligence(symbol: str, raw_peer_symbols: tuple[str, ...] = ()) -> dict[str, Any]:
    symbol = _clean_symbol(symbol)
    if not symbol:
        return {"table": pd.DataFrame(), "summary": pd.DataFrame(), "scores": {}}

    target = _company_snapshot(symbol)
    raw_set = {_clean_symbol(x) for x in raw_peer_symbols if _clean_symbol(x) and _clean_symbol(x) != symbol}

    screener = _screener_candidates(str(target.get("Sector") or ""), str(target.get("Industry") or ""), 80)
    candidates: list[str] = list(raw_set)
    # Provider-independent deterministic fallback.  This prevents the entire peer workspace
    # from disappearing when stock-peers/company-screener is outside the user's FMP plan.
    for s in _curated_peer_candidates(target):
        s = _clean_symbol(s)
        if s and s != symbol and s not in candidates:
            candidates.append(s)
    if not screener.empty:
        sym_col = next((c for c in ["symbol", "Symbol"] if c in screener.columns), None)
        if sym_col:
            for s in screener[sym_col].astype(str).tolist():
                s = _clean_symbol(s)
                if s and s != symbol and s not in candidates:
                    candidates.append(s)

    # Keep request volume bounded. Raw provider peers get first priority.
    candidates = list(dict.fromkeys(list(raw_set) + candidates))[:24]
    snapshots: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        future_map = {pool.submit(_company_snapshot, s): s for s in candidates}
        for future in as_completed(future_map):
            try:
                snap = future.result()
                if isinstance(snap, dict) and snap.get("Symbol"):
                    snapshots.append(snap)
            except Exception:
                pass

    scored = []
    for snap in snapshots:
        sim = _similarity(target, snap, snap.get("Symbol") in raw_set)
        same_ind = str(snap.get("Industry") or "").strip().lower() == str(target.get("Industry") or "").strip().lower()
        same_sec = str(snap.get("Sector") or "").strip().lower() == str(target.get("Sector") or "").strip().lower()
        peer_type = "Direct / same industry" if same_ind else "Sector comparable" if same_sec else "Ecosystem / provider"
        item = {k: v for k, v in snap.items() if not str(k).startswith("_")}
        item["Similarity"] = round(sim, 1)
        item["Peer Type"] = peer_type
        scored.append(item)

    scored = sorted(scored, key=lambda x: x.get("Similarity", 0), reverse=True)
    direct = [x for x in scored if x["Peer Type"] == "Direct / same industry"][:10]
    if len(direct) < 6:
        for x in scored:
            if x in direct:
                continue
            direct.append(x)
            if len(direct) >= 8:
                break

    selected = direct[:10]
    target_roic_audit = target.get("_ROIC Audit", {}) if isinstance(target, dict) else {}
    target_public = {k: v for k, v in target.items() if not str(k).startswith("_")}
    if not selected:
        return {"table": pd.DataFrame(), "summary": pd.DataFrame(), "scores": {}, "target": target_public, "roic_audit": target_roic_audit}

    target_row = dict(target_public)
    target_row["Similarity"] = 100.0
    target_row["Peer Type"] = "Target"
    table = pd.DataFrame([target_row] + selected)

    metric_policy = {
        "Revenue Growth": True,
        "Gross Margin": True,
        "Operating Margin": True,
        "FCF Margin": True,
        "ROIC": True,
        "FCF Yield": True,
        "P/E TTM": False,
        "Forward P/E": False,
        "EV/Sales": False,
        "EV/EBITDA": False,
    }
    peer_only = table[table["Peer Type"].ne("Target")].copy()
    summary_rows = []
    quality_pcts = []
    valuation_pcts = []
    for metric, higher_better in metric_policy.items():
        if metric not in table.columns:
            continue
        target_value = safe_float(target_row.get(metric))
        peer_vals = pd.to_numeric(peer_only[metric], errors="coerce")
        median = safe_float(peer_vals.median()) if peer_vals.notna().any() else None
        pct = _percentile(peer_vals, target_value, higher_is_better=higher_better)
        premium = None
        if metric in {"P/E TTM", "Forward P/E", "EV/Sales", "EV/EBITDA"} and target_value is not None and median not in [None, 0]:
            premium = target_value / median - 1
        summary_rows.append({
            "Metric": metric,
            "Target": target_value,
            "Peer Median": median,
            "Target Percentile": pct,
            "Premium / Discount": premium,
            "Higher Is Better": higher_better,
        })
        if pct is not None:
            if metric in {"Revenue Growth", "Gross Margin", "Operating Margin", "FCF Margin", "ROIC"}:
                quality_pcts.append(pct)
            elif metric in {"FCF Yield", "P/E TTM", "Forward P/E", "EV/Sales", "EV/EBITDA"}:
                valuation_pcts.append(pct)

    scores = {
        "relative_quality_percentile": round(float(np.mean(quality_pcts)), 1) if quality_pcts else None,
        "valuation_cheapness_percentile": round(float(np.mean(valuation_pcts)), 1) if valuation_pcts else None,
    }
    if scores["relative_quality_percentile"] is not None and scores["valuation_cheapness_percentile"] is not None:
        scores["relative_fundamental_score"] = round(
            0.62 * scores["relative_quality_percentile"] + 0.38 * scores["valuation_cheapness_percentile"], 1
        )
    else:
        scores["relative_fundamental_score"] = scores["relative_quality_percentile"]

    peer_metric_presence = {
        metric: safe_float(target_row.get(metric)) is not None and pd.to_numeric(peer_only.get(metric, pd.Series(dtype=float)), errors="coerce").notna().sum() >= 4
        for metric in metric_policy
    }
    peer_confidence = calculate_data_confidence(
        peer_metric_presence,
        source_quality=0.78,
        freshness=0.90,
        cross_validation=0.72,
    )
    scores["data_confidence"] = peer_confidence["score"]

    return {
        "target": target_public,
        "roic_audit": target_roic_audit,
        "table": table,
        "summary": pd.DataFrame(summary_rows),
        "scores": scores,
        "universe_size": len(scored),
        "metric_contract": PEER_METRIC_CONTRACT,
        "confidence_detail": peer_confidence,
    }


# -----------------------------------------------------------------------------
# Capital Allocation Intelligence
# -----------------------------------------------------------------------------

def _positive_cash(row: dict, keys: list[str]) -> float | None:
    value = _num(row, keys)
    return abs(value) if value is not None else None


def _yf_cashflow_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return []
    aliases = {
        "operatingCashFlow": ["Operating Cash Flow", "Total Cash From Operating Activities"],
        "freeCashFlow": ["Free Cash Flow"],
        "capitalExpenditure": ["Capital Expenditure", "Capital Expenditures"],
        "commonStockRepurchased": ["Repurchase Of Capital Stock", "Repurchase Of Stock", "Common Stock Repurchase"],
        "commonStockIssued": ["Issuance Of Capital Stock", "Common Stock Issuance"],
        "dividendsPaid": ["Cash Dividends Paid", "Common Stock Dividend Paid", "Common Stock Dividend Paid"],
        "stockBasedCompensation": ["Stock Based Compensation"],
        "acquisitionsNet": ["Net Business Purchases", "Acquisitions Net"],
        "debtRepayment": ["Repayment Of Debt", "Long Term Debt Payments"],
        "proceedsFromDebt": ["Issuance Of Debt", "Long Term Debt Issuance"],
    }
    out = []
    for col in df.columns:
        rec: dict[str, Any] = {"date": pd.to_datetime(col, errors="coerce")}
        try:
            rec["calendarYear"] = int(pd.to_datetime(col).year)
        except Exception:
            rec["calendarYear"] = None
        for target, names in aliases.items():
            for name in names:
                if name in df.index:
                    val = safe_float(df.loc[name, col])
                    if val is not None:
                        rec[target] = val
                        break
        # yfinance often reports repurchases as negative financing cash flow.  Preserve the
        # sign here; _positive_cash normalizes economic magnitude later.
        if len(rec) > 2:
            out.append(rec)
    return out


def _roic_from_annual_dicts(income_rows: list[dict], balance_rows: list[dict]) -> dict[int, float]:
    """Fiscal-year ROIC using the same canonical formula as TTM ROIC."""
    inc_by_year: dict[int, dict] = {}
    bal_by_year: dict[int, dict] = {}
    for row in income_rows:
        if not isinstance(row, dict):
            continue
        year = safe_int(_pick(row, ["calendarYear", "fiscalYear", "year"]))
        if year:
            inc_by_year[year] = row
    for row in balance_rows:
        if not isinstance(row, dict):
            continue
        year = safe_int(_pick(row, ["calendarYear", "fiscalYear", "year"]))
        if year:
            bal_by_year[year] = row

    result: dict[int, float] = {}
    for year, inc in inc_by_year.items():
        current = bal_by_year.get(year, {})
        prior = bal_by_year.get(year - 1, {})
        roic = calculate_roic(
            operating_income=_num(inc, ["operatingIncome", "ebit"]),
            pretax_income=_num(inc, ["incomeBeforeTax", "pretaxIncome"]),
            tax_expense=_num(inc, ["incomeTaxExpense", "taxProvision"]),
            current_debt=_num(current, ["totalDebt", "longTermDebt", "longTermDebtNoncurrent"]),
            current_equity=_num(current, ["totalStockholdersEquity", "totalEquity", "stockholdersEquity"]),
            current_cash=_num(current, ["cashAndCashEquivalents", "cashAndShortTermInvestments", "cashAndCashEquivalentsAndShortTermInvestments"]),
            prior_debt=_num(prior, ["totalDebt", "longTermDebt", "longTermDebtNoncurrent"]),
            prior_equity=_num(prior, ["totalStockholdersEquity", "totalEquity", "stockholdersEquity"]),
            prior_cash=_num(prior, ["cashAndCashEquivalents", "cashAndShortTermInvestments", "cashAndCashEquivalentsAndShortTermInvestments"]),
            current_invested_capital=_num(current, ["investedCapital"]),
            prior_invested_capital=_num(prior, ["investedCapital"]),
        )
        if roic is not None:
            result[year] = roic
    return result


def _annual_yf_value_map(statement: pd.DataFrame, names: list[str]) -> dict[int, float]:
    series = _statement_series(statement, names)
    out: dict[int, float] = {}
    for idx, value in series.items():
        try:
            year = int(pd.Timestamp(idx).year)
        except Exception:
            continue
        val = safe_float(value)
        if val is not None:
            out[year] = val
    return out


def _roic_from_company_raw(company: dict | None) -> dict[int, float]:
    raw = company.get("raw_data", {}) if isinstance(company, dict) else {}
    fmp = raw.get("fmp", {}) if isinstance(raw, dict) else {}
    fmp_result = _roic_from_annual_dicts(
        [x for x in (fmp.get("income_annual", []) if isinstance(fmp, dict) else []) if isinstance(x, dict)],
        [x for x in (fmp.get("balance_annual", []) if isinstance(fmp, dict) else []) if isinstance(x, dict)],
    )
    if fmp_result:
        return fmp_result

    financials = raw.get("financials", pd.DataFrame()) if isinstance(raw, dict) else pd.DataFrame()
    balance = raw.get("balance_sheet", pd.DataFrame()) if isinstance(raw, dict) else pd.DataFrame()
    op = _annual_yf_value_map(financials, ["Operating Income"])
    pretax = _annual_yf_value_map(financials, ["Pretax Income", "Income Before Tax"])
    tax = _annual_yf_value_map(financials, ["Tax Provision", "Income Tax Expense"])
    debt = _annual_yf_value_map(balance, ["Total Debt", "Long Term Debt"])
    equity = _annual_yf_value_map(balance, ["Stockholders Equity", "Total Stockholder Equity", "Common Stock Equity"])
    cash = _annual_yf_value_map(balance, ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents", "Cash"])
    result = {}
    for year, op_val in op.items():
        roic = calculate_roic(
            operating_income=op_val,
            pretax_income=pretax.get(year),
            tax_expense=tax.get(year),
            current_debt=debt.get(year),
            current_equity=equity.get(year),
            current_cash=cash.get(year),
            prior_debt=debt.get(year - 1),
            prior_equity=equity.get(year - 1),
            prior_cash=cash.get(year - 1),
        )
        if roic is not None:
            result[year] = roic
    return result


def _roic_ttm_from_company_raw(company: dict | None, symbol: str | None = None) -> float | None:
    """Resolve canonical TTM ROIC from the shared company bundle.

    Priority: shared yfinance quarterly statements -> shared FMP quarterly statements ->
    similarity snapshot fallback. Every path ultimately calls ``calculate_roic``.
    """
    raw = company.get("raw_data", {}) if isinstance(company, dict) else {}
    q_fin = raw.get("quarterly_financials", pd.DataFrame()) if isinstance(raw, dict) else pd.DataFrame()
    q_bs = raw.get("quarterly_balance_sheet", pd.DataFrame()) if isinstance(raw, dict) else pd.DataFrame()
    if isinstance(q_fin, pd.DataFrame) and not q_fin.empty and isinstance(q_bs, pd.DataFrame) and not q_bs.empty:
        value = _roic_from_yfinance_frames(q_fin, q_bs)
        if value is not None:
            return value

    fmp = raw.get("fmp", {}) if isinstance(raw, dict) else {}
    income_rows = [x for x in (fmp.get("income_quarterly", []) if isinstance(fmp, dict) else []) if isinstance(x, dict)]
    balance_rows = [x for x in (fmp.get("balance_quarterly", []) if isinstance(fmp, dict) else []) if isinstance(x, dict)]

    def order(rows: list[dict]) -> list[dict]:
        def key(row):
            dt = pd.to_datetime(_pick(row, ["date", "fillingDate", "filingDate"]), errors="coerce")
            return pd.Timestamp.min if pd.isna(dt) else dt
        return sorted(rows, key=key, reverse=True)

    income_rows = order(income_rows)
    balance_rows = order(balance_rows)
    if len(income_rows) >= 4 and balance_rows:
        op_vals = [_num(r, ["operatingIncome", "ebit"]) for r in income_rows[:4]]
        pretax_vals = [_num(r, ["incomeBeforeTax", "pretaxIncome"]) for r in income_rows[:4]]
        tax_vals = [_num(r, ["incomeTaxExpense", "taxProvision"]) for r in income_rows[:4]]
        op = sum(x for x in op_vals if x is not None) if any(x is not None for x in op_vals) else None
        pretax = sum(x for x in pretax_vals if x is not None) if any(x is not None for x in pretax_vals) else None
        tax = sum(x for x in tax_vals if x is not None) if any(x is not None for x in tax_vals) else None
        current = balance_rows[0]
        prior = balance_rows[4] if len(balance_rows) >= 5 else balance_rows[1] if len(balance_rows) >= 2 else {}
        value = calculate_roic(
            operating_income=op,
            pretax_income=pretax,
            tax_expense=tax,
            current_debt=_num(current, ["totalDebt", "longTermDebt", "longTermDebtNoncurrent"]),
            current_equity=_num(current, ["totalStockholdersEquity", "totalEquity", "stockholdersEquity"]),
            current_cash=_num(current, ["cashAndCashEquivalents", "cashAndShortTermInvestments", "cashAndCashEquivalentsAndShortTermInvestments"]),
            prior_debt=_num(prior, ["totalDebt", "longTermDebt", "longTermDebtNoncurrent"]),
            prior_equity=_num(prior, ["totalStockholdersEquity", "totalEquity", "stockholdersEquity"]),
            prior_cash=_num(prior, ["cashAndCashEquivalents", "cashAndShortTermInvestments", "cashAndCashEquivalentsAndShortTermInvestments"]),
            current_invested_capital=_num(current, ["investedCapital"]),
            prior_invested_capital=_num(prior, ["investedCapital"]),
        )
        if value is not None:
            return value

    if symbol:
        try:
            return safe_float(_company_snapshot(symbol).get("ROIC"))
        except Exception:
            return None
    return None


def _capital_allocation_components(latest: pd.Series, roic_override: float | None = None) -> dict[str, float | None]:
    """Interpretable allocation sub-scores; missing dimensions remain missing."""
    fcf = safe_float(latest.get("Free Cash Flow"))
    net_buyback = safe_float(latest.get("Net Buyback"))
    shareholder_yield = safe_float(latest.get("Shareholder Yield"))
    distributions = safe_float(latest.get("Distributions / FCF"))
    sbc_fcf = safe_float(latest.get("SBC / FCF"))
    reinvestment = safe_float(latest.get("Reinvestment / FCF"))
    roic = safe_float(roic_override) if safe_float(roic_override) is not None else safe_float(latest.get("FY ROIC", latest.get("ROIC")))
    net_debt = safe_float(latest.get("Net Debt Issuance"))

    capital_return = None
    if fcf is not None or net_buyback is not None or shareholder_yield is not None:
        score = 50.0
        if fcf is not None: score += 12 if fcf > 0 else -25
        if net_buyback is not None: score += 10 if net_buyback > 0 else -10 if net_buyback < 0 else 0
        if shareholder_yield is not None: score += 12 if 0.005 <= shareholder_yield <= 0.08 else 5 if shareholder_yield > 0 else -8
        if distributions is not None: score += 10 if 0 <= distributions <= 0.85 else 2 if distributions <= 1.10 else -15
        capital_return = clamp(score)

    capital_efficiency = None
    if roic is not None:
        capital_efficiency = clamp(25 + 220 * roic) if roic >= 0 else clamp(25 + 100 * roic)

    dilution = None
    if sbc_fcf is not None:
        dilution = 92 if sbc_fcf <= 0.08 else 82 if sbc_fcf <= 0.15 else 65 if sbc_fcf <= 0.30 else 45 if sbc_fcf <= 0.50 else 25

    reinvestment_score = None
    if reinvestment is not None:
        if reinvestment < 0:
            reinvestment_score = 35
        elif reinvestment <= 0.80:
            reinvestment_score = 72
        elif reinvestment <= 1.25:
            reinvestment_score = 62
        elif reinvestment <= 1.75:
            reinvestment_score = 52
        else:
            reinvestment_score = 42

    balance_score = None
    if net_debt is not None and fcf not in [None, 0]:
        ratio = net_debt / abs(fcf)
        balance_score = 82 if ratio <= -0.10 else 72 if ratio <= 0.10 else 58 if ratio <= 0.50 else 35

    return {
        "capital_return_score": safe_float(capital_return),
        "capital_efficiency_score": safe_float(capital_efficiency),
        "dilution_score": safe_float(dilution),
        "reinvestment_score": safe_float(reinvestment_score),
        "balance_sheet_allocation_score": safe_float(balance_score),
    }


def load_capital_allocation_intelligence(symbol: str, company: dict | None = None) -> dict[str, Any]:
    """Capital allocation with provider enrichment and Core-Financials fallbacks."""
    symbol = _clean_symbol(symbol)
    if not symbol:
        return {"history": pd.DataFrame(), "summary": {}, "score": None, "confidence": 0}

    raw = company.get("raw_data", {}) if isinstance(company, dict) else {}
    raw_fmp = raw.get("fmp", {}) if isinstance(raw, dict) else {}
    roic_by_year = _roic_from_company_raw(company)
    roic_ttm = _roic_ttm_from_company_raw(company, symbol)

    # Reuse data already loaded by Core Financials first.  This avoids blank screens and
    # duplicate API consumption.  Only call FMP directly when the shared bundle has no rows.
    cf_rows = [x for x in (raw_fmp.get("cashflow_annual", []) if isinstance(raw_fmp, dict) else []) if isinstance(x, dict)]
    km_rows = [x for x in (raw_fmp.get("key_metrics_annual", []) if isinstance(raw_fmp, dict) else []) if isinstance(x, dict)]
    source = "Core Financials / FMP shared bundle"
    if not cf_rows:
        cf_rows = _records(_fmp_json("cash-flow-statement", {"symbol": symbol, "period": "annual", "limit": 8}))
        source = "FMP cash-flow"
    if not km_rows:
        km_rows = _records(_fmp_json("key-metrics", {"symbol": symbol, "period": "annual", "limit": 8}))

    if not cf_rows:
        cf_rows = _yf_cashflow_rows(raw.get("cashflow", pd.DataFrame()) if isinstance(raw, dict) else pd.DataFrame())
        source = "Yahoo cash-flow fallback"

    info = raw.get("info", {}) if isinstance(raw, dict) else {}
    profile_rows = _records(_fmp_json("profile", {"symbol": symbol})) if not info else []
    profile = profile_rows[0] if profile_rows else {}

    km_by_year: dict[int, dict] = {}
    for r in km_rows:
        year = safe_int(_pick(r, ["calendarYear", "fiscalYear", "year"]))
        if year:
            km_by_year[year] = r

    rows = []
    for r in cf_rows:
        year = safe_int(_pick(r, ["calendarYear", "fiscalYear", "year"]))
        date = pd.to_datetime(_pick(r, ["date", "fillingDate", "filingDate"]), errors="coerce")
        km = km_by_year.get(year or -1, {})
        market_cap = _num(km, ["marketCap", "marketCapitalization"]) or safe_float(info.get("marketCap")) or safe_float(profile.get("marketCap"))
        fcf = _num(r, ["freeCashFlow", "freeCashflow"])
        ocf = _num(r, ["operatingCashFlow", "netCashProvidedByOperatingActivities"])
        buybacks = _positive_cash(r, ["commonStockRepurchased", "repurchasesOfCapitalStock", "repurchaseOfStock", "commonStockRepurchasedAndRetired"])
        issuance = _positive_cash(r, ["commonStockIssued", "issuanceOfCapitalStock", "proceedsFromStockOptions", "proceedsFromIssuanceOfCommonStock"])
        dividends = _positive_cash(r, ["dividendsPaid", "commonDividendsPaid", "dividendPaid"])
        sbc = _positive_cash(r, ["stockBasedCompensation", "stockBasedCompensationExpense"])
        capex = _positive_cash(r, ["capitalExpenditure", "capitalExpenditures", "investmentsInPropertyPlantAndEquipment"])
        acquisitions = _positive_cash(r, ["acquisitionsNet", "acquisitions", "businessAcquisitionsNetOfCashAcquired"])
        debt_repayment = _positive_cash(r, ["debtRepayment", "repaymentOfDebt", "longTermDebtRepayments"])
        debt_issuance = _positive_cash(r, ["proceedsFromDebt", "issuanceOfDebt", "longTermDebtIssued", "proceedsFromIssuanceOfLongTermDebt"])
        # Historical row is explicitly fiscal-year ROIC. Canonical statement-derived
        # FY ROIC is preferred over provider fields; TTM ROIC is displayed separately.
        fy_roic = safe_float(roic_by_year.get(year)) if year is not None else None
        if fy_roic is None:
            fy_roic = _num(km, ["returnOnInvestedCapital"])

        net_buyback = (buybacks or 0) - (issuance or 0) if buybacks is not None or issuance is not None else None
        distributions = (net_buyback or 0) + (dividends or 0) if net_buyback is not None or dividends is not None else None
        shareholder_yield = distributions / market_cap if distributions is not None and market_cap not in [None, 0] else None
        fcf_coverage = distributions / fcf if distributions is not None and fcf not in [None, 0] and fcf > 0 else None
        sbc_fcf = sbc / fcf if sbc is not None and fcf not in [None, 0] and fcf > 0 else None
        reinvestment = ((capex or 0) + (acquisitions or 0)) / fcf if fcf not in [None, 0] and fcf > 0 else None
        net_debt_issuance = (debt_issuance or 0) - (debt_repayment or 0) if debt_issuance is not None or debt_repayment is not None else None

        rows.append({
            "Date": date, "Fiscal Year": year, "Operating Cash Flow": ocf, "Free Cash Flow": fcf,
            "Buybacks": buybacks, "Stock Issuance": issuance, "Net Buyback": net_buyback,
            "Dividends": dividends, "SBC": sbc, "Capex": capex, "Acquisitions": acquisitions,
            "Debt Issuance": debt_issuance, "Debt Repayment": debt_repayment,
            "Net Debt Issuance": net_debt_issuance, "FY ROIC": fy_roic, "Market Cap": market_cap,
            "Shareholder Yield": shareholder_yield, "Distributions / FCF": fcf_coverage,
            "SBC / FCF": sbc_fcf, "Reinvestment / FCF": reinvestment, "Source": source,
        })

    hist = pd.DataFrame(rows)
    if hist.empty:
        return {"history": hist, "summary": {}, "score": None, "confidence": 0}
    hist = hist.sort_values(["Fiscal Year", "Date"], ascending=[False, False], na_position="last").reset_index(drop=True)
    latest = hist.iloc[0]
    previous = hist.iloc[1] if len(hist) > 1 else None

    coverage_fields = {
        "Free Cash Flow": safe_float(latest.get("Free Cash Flow")) is not None,
        "Buybacks": safe_float(latest.get("Buybacks")) is not None,
        "Stock Issuance": safe_float(latest.get("Stock Issuance")) is not None,
        "Dividends": safe_float(latest.get("Dividends")) is not None,
        "SBC": safe_float(latest.get("SBC")) is not None,
        "Capex": safe_float(latest.get("Capex")) is not None,
        "Acquisitions": safe_float(latest.get("Acquisitions")) is not None,
        "Debt Issuance": safe_float(latest.get("Debt Issuance")) is not None,
        "Debt Repayment": safe_float(latest.get("Debt Repayment")) is not None,
        "ROIC TTM": roic_ttm is not None,
    }
    source_quality = 0.92 if "shared bundle" in source.lower() else 0.86 if source.startswith("FMP") else 0.65 if "Yahoo" in source else 0.70
    yf_cross = isinstance(raw.get("cashflow"), pd.DataFrame) and not raw.get("cashflow", pd.DataFrame()).empty if isinstance(raw, dict) else False
    fmp_cross = bool(cf_rows and isinstance(raw_fmp, dict) and raw_fmp.get("cashflow_annual"))
    confidence_detail = calculate_data_confidence(
        coverage_fields,
        source_quality=source_quality,
        freshness=0.85,
        cross_validation=0.75 if yf_cross and fmp_cross else 0.55,
    )
    confidence = confidence_detail["score"]

    components = _capital_allocation_components(latest, roic_override=roic_ttm)
    available_components = [v for v in components.values() if v is not None]
    score = None
    if len(available_components) >= 3:
        # Equal-weight the interpretable dimensions that are actually observed. Missing ROIC
        # therefore cannot silently receive a neutral value and cannot support a 90+ score.
        score = round(float(np.mean(available_components)), 1)
        if components.get("capital_efficiency_score") is None:
            score = min(score, 85.0)
        if confidence < 50:
            score = min(score, 75.0)

    fcf = safe_float(latest.get("Free Cash Flow")); roic = safe_float(roic_ttm); net_buyback = safe_float(latest.get("Net Buyback"))
    shareholder_yield = safe_float(latest.get("Shareholder Yield")); coverage = safe_float(latest.get("Distributions / FCF")); sbc_fcf = safe_float(latest.get("SBC / FCF")); net_debt = safe_float(latest.get("Net Debt Issuance"))


    def delta(col: str):
        if previous is None: return None
        a = safe_float(latest.get(col)); b = safe_float(previous.get(col))
        return None if a is None or b is None else a - b

    summary = {
        "fiscal_year": safe_int(latest.get("Fiscal Year")), "shareholder_yield": shareholder_yield,
        "net_buyback": net_buyback, "dividends": safe_float(latest.get("Dividends")), "sbc_fcf": sbc_fcf,
        "roic": roic, "roic_basis": "TTM canonical NOPAT / average invested capital",
        "fy_roic": safe_float(latest.get("FY ROIC")),
        "reinvestment_fcf": safe_float(latest.get("Reinvestment / FCF")),
        "distribution_fcf": coverage, "net_debt_issuance": net_debt,
        "delta_net_buyback": delta("Net Buyback"), "delta_sbc_fcf": delta("SBC / FCF"),
        "delta_shareholder_yield": delta("Shareholder Yield"), "confidence": confidence,
        "confidence_detail": confidence_detail,
        "source": source,
        **components,
    }
    return {"history": hist, "summary": summary, "score": score, "confidence": confidence, "confidence_detail": confidence_detail, "components": components}


# -----------------------------------------------------------------------------
# SEC event materiality
# -----------------------------------------------------------------------------

_8K_ITEM_MATERIALITY = {
    "1.01": (2, "Material definitive agreement"),
    "1.02": (2, "Termination of material agreement"),
    "1.03": (3, "Bankruptcy / receivership"),
    "1.05": (3, "Material cybersecurity incident"),
    "2.01": (3, "Acquisition / disposition of assets"),
    "2.02": (2, "Results of operations / financial condition"),
    "2.03": (2, "Material financial obligation"),
    "2.04": (3, "Acceleration / increase of financial obligation"),
    "2.05": (2, "Exit / disposal activities"),
    "2.06": (3, "Material impairment"),
    "3.01": (2, "Delisting / listing-standard event"),
    "3.02": (2, "Unregistered equity issuance"),
    "4.01": (2, "Auditor change"),
    "4.02": (3, "Non-reliance on financial statements"),
    "5.02": (3, "Director / principal-officer change"),
    "5.03": (2, "Charter / bylaws change"),
    "5.07": (1, "Shareholder vote"),
    "7.01": (1, "Regulation FD disclosure"),
    "8.01": (1, "Other material event"),
    "9.01": (0, "Financial statements / exhibits"),
}


def _split_sec_items(value: Any) -> list[str]:
    text = str(value or "")
    return re.findall(r"\b\d\.\d{2}\b", text)


def _sec_event_descriptor(form: str, items: Any = None) -> tuple[int, str, str]:
    form_u = str(form or "").upper().strip()
    if form_u == "8-K" or form_u.startswith("8-K/"):
        parsed = _split_sec_items(items)
        if parsed:
            ranked = sorted(
                ((_8K_ITEM_MATERIALITY.get(x, (1, f"8-K Item {x}"))[0], x, _8K_ITEM_MATERIALITY.get(x, (1, f"8-K Item {x}"))[1]) for x in parsed),
                reverse=True,
            )
            materiality, item, title = ranked[0]
            return materiality, "8-K", f"{item} · {title}"
        return 1, "8-K", "Current report"
    if form_u in {"10-K", "10-K/A"}:
        return 2, "Periodic report", "Annual report"
    if form_u in {"10-Q", "10-Q/A"}:
        return 2, "Periodic report", "Quarterly report"
    if "13D" in form_u:
        return 3, "Ownership / activism", "Schedule 13D beneficial-ownership event"
    if "13G" in form_u:
        return 2, "Ownership", "Schedule 13G beneficial-ownership update"
    if form_u.startswith("DEF 14A") or form_u == "DEF14A":
        return 2, "Governance", "Proxy statement"
    if form_u == "4" or form_u.startswith("4/"):
        return 1, "Insider ownership", "Form 4 insider transaction filing"
    if form_u == "3" or form_u.startswith("3/"):
        return 0, "Insider ownership", "Form 3 initial ownership filing"
    if form_u == "144":
        return 1, "Insider / affiliate sale", "Form 144 proposed sale"
    return 1, "Other filing", form_u or "SEC filing"


def build_sec_event_intelligence(filings: pd.DataFrame, lookback_days: int = 90) -> dict[str, Any]:
    """Classify SEC filings by information materiality rather than counting all forms equally."""
    if not isinstance(filings, pd.DataFrame) or filings.empty:
        return {"table": pd.DataFrame(), "summary": {"material_events_30d": 0, "high_events_90d": 0}}
    work = filings.copy()
    date_col = next((c for c in ["filingDate", "reportDate", "date"] if c in work.columns), None)
    form_col = next((c for c in ["form", "Form"] if c in work.columns), None)
    if date_col is None or form_col is None:
        return {"table": pd.DataFrame(), "summary": {"material_events_30d": 0, "high_events_90d": 0}}
    work["Event Date"] = pd.to_datetime(work[date_col], errors="coerce", utc=True).dt.tz_convert(None)
    cutoff = pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(days=lookback_days)
    work = work[work["Event Date"].notna() & (work["Event Date"] >= cutoff)].copy()
    rows = []
    for _, row in work.iterrows():
        form = str(row.get(form_col) or "")
        materiality, category, title = _sec_event_descriptor(form, row.get("items"))
        label = "High" if materiality >= 3 else "Medium" if materiality == 2 else "Low" if materiality == 1 else "Administrative"
        rows.append({
            "Event Date": row.get("Event Date"),
            "Form": form,
            "Items": row.get("items"),
            "Category": category,
            "Event": title,
            "Materiality": materiality,
            "Materiality Label": label,
            "Accession Number": row.get("accessionNumber"),
            "Primary Document": row.get("primaryDocument"),
            "Source": "SEC EDGAR",
        })
    table = pd.DataFrame(rows)
    if table.empty:
        return {"table": table, "summary": {"material_events_30d": 0, "high_events_90d": 0}}
    table = table.sort_values(["Event Date", "Materiality"], ascending=[False, False]).reset_index(drop=True)
    cutoff30 = pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(days=30)
    recent30 = table[table["Event Date"] >= cutoff30]
    summary = {
        "material_events_30d": int((recent30["Materiality"] >= 2).sum()),
        "high_events_90d": int((table["Materiality"] >= 3).sum()),
        "latest_material_event": table[table["Materiality"] >= 2].iloc[0].to_dict() if (table["Materiality"] >= 2).any() else None,
    }
    return {"table": table, "summary": summary}


# -----------------------------------------------------------------------------
# What Changed? engine
# -----------------------------------------------------------------------------

def _alpha_revision_signal(company: dict) -> dict[str, Any] | None:
    raw = company.get("raw_data", {}) if isinstance(company, dict) else {}
    alpha = raw.get("alpha", {}) if isinstance(raw, dict) else {}
    payload = alpha.get("earnings_estimates", {}) if isinstance(alpha, dict) else {}
    if not isinstance(payload, dict):
        return None
    records = payload.get("estimates")
    if not isinstance(records, list) or not records:
        return None

    parsed = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        date = pd.to_datetime(rec.get("date"), errors="coerce")
        horizon = str(rec.get("horizon", ""))
        eps = safe_float(rec.get("eps_estimate_average"))
        eps30 = safe_float(rec.get("eps_estimate_average_30_days_ago"))
        rev = safe_float(rec.get("revenue_estimate_average"))
        rev30 = safe_float(rec.get("revenue_estimate_average_30_days_ago"))
        if eps is None and rev is None:
            continue
        parsed.append((date, horizon, eps, eps30, rev, rev30))
    if not parsed:
        return None

    today = pd.Timestamp.utcnow().tz_localize(None)
    future = [x for x in parsed if pd.notna(x[0]) and x[0] >= today - pd.Timedelta(days=90)]
    pool = future or parsed
    pool = sorted(pool, key=lambda x: x[0] if pd.notna(x[0]) else pd.Timestamp.max)
    date, horizon, eps, eps30, rev, rev30 = pool[0]
    eps_rev = eps / eps30 - 1 if eps is not None and eps30 not in [None, 0] else None
    rev_rev = rev / rev30 - 1 if rev is not None and rev30 not in [None, 0] else None
    vals = [x for x in [eps_rev, rev_rev] if x is not None]
    combined = float(np.mean(vals)) if vals else None
    return {
        "date": date,
        "horizon": horizon,
        "eps_revision_30d": eps_rev,
        "revenue_revision_30d": rev_rev,
        "combined_revision_30d": combined,
        "source": "Alpha Vantage earnings estimates",
    }


def build_what_changed(company: dict) -> dict[str, Any]:
    """Separate directional thesis deltas from structural states and material events."""
    inst = company.get("institutional", {}) if isinstance(company, dict) else {}
    rows: list[dict[str, Any]] = []

    def add(cls: str, dimension: str, window: str, direction: str, materiality: int, signal: str, detail: str, confidence: int, source: str):
        rows.append({
            "Class": cls, "Dimension": dimension, "Window": window, "Direction": direction,
            "Materiality": int(materiality), "Signal": signal, "Detail": detail,
            "Confidence": int(confidence), "Source": source,
        })

    revisions = _alpha_revision_signal(company)
    if revisions:
        val = safe_float(revisions.get("combined_revision_30d"))
        if val is not None:
            direction = "Positive" if val > 0.01 else "Negative" if val < -0.01 else "Stable"
            add("Directional Change", "Estimate revisions", "30d", direction, 3 if abs(val) >= 0.03 else 2,
                f"Combined revision {val:+.2%}",
                f"EPS {revisions.get('eps_revision_30d'):+.2%}" if revisions.get("eps_revision_30d") is not None else "EPS N/A",
                90, revisions.get("source", "Alpha Vantage"))

    own = inst.get("ownership_v2", {}) if isinstance(inst, dict) else {}
    own_sum = own.get("summary", {}) if isinstance(own, dict) else {}
    proxy = safe_float(own_sum.get("weighted_position_change_proxy")); breadth = safe_float(own_sum.get("breadth"))
    if proxy is not None or breadth is not None:
        vals = [x for x in [proxy, breadth] if x is not None]
        comb = float(np.mean(vals)) if vals else 0.0
        direction = "Positive" if comb > 0.12 else "Negative" if comb < -0.12 else "Stable"
        add("Directional Change", "Institutional positioning", "Latest reported holder change", direction, 2,
            f"Weighted proxy {proxy:+.2f}" if proxy is not None else "Weighted proxy N/A",
            f"Breadth {breadth:+.2f}" if breadth is not None else "Breadth N/A", 65, own.get("score_basis", "Yahoo / 13F"))

    insider = inst.get("insider_v2", {}) if isinstance(inst, dict) else {}; ins_sum = insider.get("summary", {}) if isinstance(insider, dict) else {}
    ins_score = safe_float(insider.get("score")) if isinstance(insider, dict) else None
    if ins_score is not None:
        direction = "Positive" if ins_score >= 60 else "Negative" if ins_score <= 40 else "Stable"
        add("Directional Change", "Insider activity", "90d", direction, 2, f"Informative insider score {ins_score:.0f}/100",
            f"Buyers {ins_sum.get('buyers_90d', 0)} · Sellers {ins_sum.get('sellers_90d', 0)}", 80, "Form 4 / insider feed")
    elif ins_sum:
        add("Directional Change", "Insider activity", "90d", "N/A", 1, "No informative open-market activity", str(ins_sum.get("status", "")), 80, "Form 4 / insider feed")

    for label, key in [("Product concentration", "product_summary"), ("Geographic concentration", "geographic_summary")]:
        summary = inst.get(key, {}) if isinstance(inst, dict) else {}; delta = safe_float(summary.get("top_share_delta")) if isinstance(summary, dict) else None
        if delta is not None:
            taxonomy_changed = bool(summary.get("taxonomy_changed"))
            direction = "Mixed" if taxonomy_changed else "Negative" if delta > 0.03 else "Positive" if delta < -0.03 else "Stable"
            detail = "Taxonomy changed; concentration delta is not treated as a clean economic change." if taxonomy_changed else "Higher concentration increases dependency risk."
            signal = "Taxonomy changed · delta N/M" if taxonomy_changed else f"Largest-segment share {delta * 100:+.2f} pp"
            add("Directional Change", label, "Latest FY vs prior FY", direction, 1 if taxonomy_changed else (2 if abs(delta) >= 0.05 else 1),
                signal, detail, 55 if taxonomy_changed else 85, "FMP revenue segmentation")

    relationships = inst.get("relationships", {}) if isinstance(inst, dict) else {}; rel_summary = relationships.get("summary", {}) if isinstance(relationships, dict) else {}
    max_customer = safe_float(rel_summary.get("max_customer_concentration"))
    if max_customer is not None:
        risk_level = "High" if max_customer >= 0.20 else "Moderate" if max_customer >= 0.10 else "Low"
        add("Structural State", "Customer concentration", "Latest 10-K", "Risk", 3 if max_customer >= 0.20 else 2,
            f"{risk_level} · largest explicit customer {max_customer:.1%}", "Dependency snapshot; excluded from directional Change Balance.",
            int(rel_summary.get("customer_confidence") or 85), "SEC 10-K")
    max_supplier = safe_float(rel_summary.get("max_supplier_concentration")); single = safe_int(rel_summary.get("single_source_count"), 0) or 0
    if max_supplier is not None or single:
        add("Structural State", "Supply-chain dependency", "Latest 10-K", "Risk", 3 if single else 2,
            f"Supplier concentration {_fmt_pct_local(max_supplier)} · single-source flags {single}", "Structural operating dependency; excluded from directional Change Balance.",
            int(rel_summary.get("supplier_confidence") or 75), "SEC 10-K")

    cap = inst.get("capital_allocation", {}) if isinstance(inst, dict) else {}; cap_sum = cap.get("summary", {}) if isinstance(cap, dict) else {}
    delta_buyback = safe_float(cap_sum.get("delta_net_buyback")); delta_sbc = safe_float(cap_sum.get("delta_sbc_fcf"))
    if delta_buyback is not None:
        direction = "Positive" if delta_buyback > 0 else "Negative" if delta_buyback < 0 else "Stable"
        add("Directional Change", "Net buyback", "Latest FY vs prior FY", direction, 2, "Capital return changed", f"Δ net buyback {delta_buyback:,.0f}", int(cap_sum.get("confidence") or 70), str(cap_sum.get("source") or "Cash-flow"))
    if delta_sbc is not None:
        direction = "Negative" if delta_sbc > 0.05 else "Positive" if delta_sbc < -0.05 else "Stable"
        add("Directional Change", "SBC burden", "Latest FY vs prior FY", direction, 2 if abs(delta_sbc) >= 0.10 else 1,
            f"SBC / FCF change {delta_sbc:+.1%}", "Higher SBC/FCF implies greater dilution pressure.", int(cap_sum.get("confidence") or 70), str(cap_sum.get("source") or "Cash-flow"))

    sec_events = inst.get("sec_events", {}) if isinstance(inst, dict) else {}
    event_table = sec_events.get("table", pd.DataFrame()) if isinstance(sec_events, dict) else pd.DataFrame()
    if not isinstance(event_table, pd.DataFrame) or event_table.empty:
        sec = inst.get("sec", {}) if isinstance(inst, dict) else {}
        filings = sec.get("filings", pd.DataFrame()) if isinstance(sec, dict) else pd.DataFrame()
        sec_events = build_sec_event_intelligence(filings, lookback_days=90)
        event_table = sec_events.get("table", pd.DataFrame())
    if isinstance(event_table, pd.DataFrame) and not event_table.empty:
        cutoff30 = pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(days=30)
        recent_material = event_table[
            (pd.to_datetime(event_table["Event Date"], errors="coerce") >= cutoff30)
            & (pd.to_numeric(event_table["Materiality"], errors="coerce") >= 2)
        ].copy()
        # Routine Form 3/4 filings are intentionally excluded from the material-event count.
        for _, ev in recent_material.head(5).iterrows():
            mat = int(safe_int(ev.get("Materiality"), 2) or 2)
            add(
                "Material Event",
                str(ev.get("Event") or ev.get("Form") or "SEC event"),
                "30d",
                "Material",
                mat,
                f"{ev.get('Form', 'SEC')} · {ev.get('Materiality Label', 'Medium')}",
                f"Category: {ev.get('Category', 'N/A')} · Items: {ev.get('Items', 'N/A')}",
                100,
                "SEC EDGAR",
            )

    peer = inst.get("peer_intelligence", {}) if isinstance(inst, dict) else {}; peer_scores = peer.get("scores", {}) if isinstance(peer, dict) else {}; rel_score = safe_float(peer_scores.get("relative_fundamental_score"))
    if rel_score is not None:
        direction = "Positive" if rel_score >= 65 else "Negative" if rel_score <= 35 else "Mixed"
        add("Structural State", "Relative fundamentals", "Current", direction, 2, f"Peer-relative score {rel_score:.0f}/100", "Current relative quality/valuation state; not counted as a time delta.", 70, "Similarity-ranked peer snapshot")

    sentiment = company.get("sentiment", {}) if isinstance(company, dict) else {}
    if isinstance(sentiment, dict) and sentiment.get("global_sentiment"):
        label = str(sentiment.get("global_sentiment")); direction = "Positive" if "positif" in label.lower() else "Negative" if "négatif" in label.lower() else "Mixed"
        add("Directional Change", "Newsflow", "Current loaded window", direction, 1, label, f"Mechanical news score {sentiment.get('raw_score', 'N/A')}", 55, "Company news pipeline")

    df = pd.DataFrame(rows)
    if df.empty:
        return {"table": df, "summary": {"bias": "N/A", "positive": 0, "negative": 0, "structural_risks": 0, "events": 0, "confidence": 0}}

    directional = df[df["Class"].eq("Directional Change")].copy()
    signed_map = {"Positive": 1, "Negative": -1, "Stable": 0, "Mixed": 0, "N/A": 0}
    if directional.empty:
        balance = 0.0; bias = "No directional signal"
    else:
        weights = pd.to_numeric(directional["Materiality"], errors="coerce").fillna(1).clip(1, 3)
        signed = directional["Direction"].map(signed_map).fillna(0) * weights
        balance = float(signed.sum() / max(1, weights.sum()))
        bias = "Improving" if balance > 0.20 else "Deteriorating" if balance < -0.20 else "Mixed / stable"

    all_weights = pd.to_numeric(df["Materiality"], errors="coerce").fillna(1).clip(1, 3)
    summary = {
        "bias": bias,
        "positive": int(directional["Direction"].eq("Positive").sum()),
        "negative": int(directional["Direction"].eq("Negative").sum()),
        "structural_risks": int(((df["Class"] == "Structural State") & (df["Direction"] == "Risk")).sum()),
        "events": int((df["Class"] == "Material Event").sum()),
        "material": int((pd.to_numeric(df["Materiality"], errors="coerce") >= 2).sum()),
        "confidence": round(float(np.average(pd.to_numeric(df["Confidence"], errors="coerce").fillna(0), weights=all_weights)), 1),
        "balance": round(balance, 3),
    }
    order = {"Directional Change": 0, "Structural State": 1, "Material Event": 2}
    df["_order"] = df["Class"].map(order).fillna(9)
    return {"table": df.sort_values(["_order", "Materiality", "Confidence"], ascending=[True, False, False]).drop(columns="_order").reset_index(drop=True), "summary": summary}


def _fmt_pct_local(value) -> str:
    value = safe_float(value)
    return "N/A" if value is None else f"{value:.1%}"
