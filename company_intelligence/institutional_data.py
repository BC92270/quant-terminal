"""Institutional / ownership / business ecosystem enrichment for Company Intelligence.

The module is intentionally defensive: every external endpoint may be unavailable because
of provider plan limits, non-US coverage, or transient network failures. Missing data is
represented as an empty frame/list and is never converted into a bullish/bearish signal.
"""
from __future__ import annotations

import os
import re
import json
from pathlib import Path
from datetime import datetime
from html import unescape
from typing import Any

import numpy as np
import pandas as pd
import requests
import streamlit as st
import yfinance as yf
from bs4 import BeautifulSoup

from .common import safe_float, safe_int, clamp, first_present_flexible
from .providers import get_fmp_api_key, fmp_rows, sec_ticker_to_cik
from .institutional_v2 import build_ownership_intelligence, build_insider_intelligence, build_sec_event_intelligence
from .institutional_metrics import calculate_data_confidence, calculate_institutional_overlay

FMP_STABLE_BASE = "https://financialmodelingprep.com/stable"
SEC_ARCHIVE_BASE = "https://www.sec.gov/Archives/edgar/data"
SEC_SUBMISSIONS_BASE = "https://data.sec.gov/submissions"


def _sec_user_agent() -> str:
    return (
        os.getenv("SEC_USER_AGENT", "").strip()
        or "QuantTerminal/1.0 contact@example.com"
    )


def _sec_headers() -> dict[str, str]:
    return {
        "User-Agent": _sec_user_agent(),
        "Accept-Encoding": "gzip, deflate",
        "Accept": "application/json,text/html,application/xhtml+xml",
    }


def _fmp_stable_json(endpoint: str, params: dict[str, Any] | None = None):
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
            if ("invalid api key" in low) or ("limit" in low and "exceed" in low):
                return []
        return payload
    except Exception:
        return []


def _fmp_v4_json(endpoint: str, params: dict[str, Any] | None = None):
    """Legacy-v4 fallback for datasets that can be plan/shape-sensitive on Stable.

    This is intentionally used only after the Stable endpoint fails, so the modern
    contract remains primary. FMP still documents these segmentation datasets in Stable,
    but historical accounts can expose legacy v4 coverage differently.
    """
    key = get_fmp_api_key()
    if not key:
        return []
    query = dict(params or {})
    query["apikey"] = key
    try:
        response = requests.get(
            f"https://financialmodelingprep.com/api/v4/{endpoint.lstrip('/')}",
            params=query,
            timeout=18,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            low = str(payload).lower()
            if ("invalid api key" in low) or ("limit" in low and "exceed" in low):
                return []
        return payload
    except Exception:
        return []


def _to_records(payload) -> list[dict]:
    rows = fmp_rows(payload)
    return [r for r in rows if isinstance(r, dict)]


def _to_frame(payload) -> pd.DataFrame:
    rows = _to_records(payload)
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _clean_symbol(value: Any) -> str:
    return str(value or "").upper().strip().replace(".", "-")


def _quarter_pairs(n: int = 8) -> list[tuple[int, int]]:
    now = datetime.utcnow()
    year = now.year
    quarter = (now.month - 1) // 3 + 1

    # 13F data are delayed; start with the last completed quarter.
    quarter -= 1
    if quarter == 0:
        year -= 1
        quarter = 4

    out: list[tuple[int, int]] = []
    for _ in range(max(1, n)):
        out.append((year, quarter))
        quarter -= 1
        if quarter == 0:
            year -= 1
            quarter = 4
    return out


def _pick(row: dict, keys: list[str], default=None):
    return first_present_flexible(row, keys, default)


def _numeric(row: dict, keys: list[str], default=None):
    return safe_float(_pick(row, keys, default), default)


@st.cache_data(ttl=21600, show_spinner=False)
def load_fmp_ownership_history(symbol: str, quarters: int = 8) -> pd.DataFrame:
    symbol = _clean_symbol(symbol)
    rows: list[dict] = []

    if not get_fmp_api_key() or not symbol:
        return pd.DataFrame()

    for year, quarter in _quarter_pairs(quarters):
        payload = _fmp_stable_json(
            "institutional-ownership/symbol-positions-summary",
            {"symbol": symbol, "year": year, "quarter": quarter},
        )
        for item in _to_records(payload):
            rec = dict(item)
            rec.setdefault("year", year)
            rec.setdefault("quarter", quarter)
            rows.append(rec)

    if not rows:
        return pd.DataFrame()

    normalized: list[dict] = []
    for row in rows:
        year = safe_int(_pick(row, ["year", "calendarYear"]))
        quarter = safe_int(_pick(row, ["quarter", "fiscalQuarter"]))
        normalized.append({
            "Year": year,
            "Quarter": quarter,
            "Period": f"{year} Q{quarter}" if year and quarter else "N/A",
            "Investors": _numeric(row, ["investorsHolding", "numberOfInvestors", "investors", "holders"]),
            "Shares Held": _numeric(row, ["shares", "sharesHeld", "totalShares", "sharesHeldByInstitutions"]),
            "Shares Change": _numeric(row, ["changeInShares", "sharesChange", "changeShares"]),
            "Market Value": _numeric(row, ["totalInvested", "marketValue", "totalMarketValue", "value"]),
            "Ownership %": _numeric(row, ["ownershipPercent", "ownershipPercentage", "institutionalOwnershipPercentage", "ownership"]),
            "Put/Call": _numeric(row, ["putCallRatio", "putCall", "putCallRatioShares"]),
            "Source": "FMP 13F positions summary",
        })

    df = pd.DataFrame(normalized)
    if df.empty:
        return df

    # Some FMP percentages are expressed as 0-100, others may be 0-1.
    if "Ownership %" in df.columns:
        vals = pd.to_numeric(df["Ownership %"], errors="coerce")
        mask = vals.abs() > 1.5
        df.loc[mask, "Ownership %"] = vals[mask] / 100.0

    df["_sort"] = (
        pd.to_numeric(df["Year"], errors="coerce").fillna(0) * 10
        + pd.to_numeric(df["Quarter"], errors="coerce").fillna(0)
    )
    df = df.sort_values("_sort", ascending=False).drop_duplicates("Period", keep="first")
    return df.drop(columns=["_sort"], errors="ignore").reset_index(drop=True)


@st.cache_data(ttl=21600, show_spinner=False)
def load_yfinance_ownership(symbol: str) -> dict[str, pd.DataFrame]:
    symbol = _clean_symbol(symbol)
    empty = {
        "major_holders": pd.DataFrame(),
        "institutional_holders": pd.DataFrame(),
        "mutualfund_holders": pd.DataFrame(),
        "insider_transactions": pd.DataFrame(),
        "insider_purchases": pd.DataFrame(),
        "insider_roster": pd.DataFrame(),
    }
    if not symbol:
        return empty

    try:
        ticker = yf.Ticker(symbol)
    except Exception:
        return empty

    def grab(name: str) -> pd.DataFrame:
        try:
            value = getattr(ticker, name)
            if isinstance(value, pd.DataFrame):
                return value.copy()
        except Exception:
            pass
        return pd.DataFrame()

    return {
        "major_holders": grab("major_holders"),
        "institutional_holders": grab("institutional_holders"),
        "mutualfund_holders": grab("mutualfund_holders"),
        "insider_transactions": grab("insider_transactions"),
        "insider_purchases": grab("insider_purchases"),
        "insider_roster": grab("insider_roster_holders"),
    }


@st.cache_data(ttl=21600, show_spinner=False)
def load_fmp_insider_bundle(symbol: str) -> dict[str, Any]:
    symbol = _clean_symbol(symbol)
    if not get_fmp_api_key() or not symbol:
        return {"transactions": pd.DataFrame(), "statistics": pd.DataFrame()}

    transactions = _to_frame(_fmp_stable_json(
        "insider-trading/search",
        {"symbol": symbol, "page": 0, "limit": 250},
    ))

    if not transactions.empty and "symbol" in transactions.columns:
        transactions = transactions[
            transactions["symbol"].astype(str).str.upper().eq(symbol)
        ].copy()

    statistics = _to_frame(_fmp_stable_json(
        "insider-trading/statistics",
        {"symbol": symbol},
    ))

    return {"transactions": transactions, "statistics": statistics}



def _segment_runtime_cache_dir() -> Path:
    """Writable project-level cache for last-known-good segment snapshots."""
    configured = os.getenv("COMPANY_INTELLIGENCE_CACHE_DIR", "").strip()
    if configured:
        root = Path(configured).expanduser()
    else:
        root = Path.cwd() / ".company_intelligence_cache"
    path = root / "segments"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return path


def _segment_seed_dir() -> Path:
    return Path(__file__).resolve().parent / "data_cache" / "segments"


def _segment_snapshot_paths(symbol: str) -> list[Path]:
    name = f"{_clean_symbol(symbol)}_segments.json"
    return [
        _segment_runtime_cache_dir() / name,
        _segment_seed_dir() / name,
    ]


def _snapshot_rows(df: pd.DataFrame) -> list[dict]:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return []
    out: list[dict] = []
    for _, row in df.iterrows():
        date = pd.to_datetime(row.get("Date"), errors="coerce")
        out.append({
            "date": None if pd.isna(date) else date.strftime("%Y-%m-%d"),
            "fiscalYear": safe_int(row.get("Fiscal Year")),
            "period": str(row.get("Period") or "FY"),
            "currency": str(row.get("Currency") or ""),
            "segment": str(row.get("Segment") or "").strip(),
            "revenue": safe_float(row.get("Revenue")),
        })
    return [r for r in out if r.get("segment") and r.get("revenue") is not None]


def _save_segment_snapshot(symbol: str, product: pd.DataFrame, geographic: pd.DataFrame, source: str) -> None:
    """Persist only valid last-known-good observations; never overwrite with empties."""
    if (not isinstance(product, pd.DataFrame) or product.empty) and (not isinstance(geographic, pd.DataFrame) or geographic.empty):
        return
    path = _segment_runtime_cache_dir() / f"{_clean_symbol(symbol)}_segments.json"
    payload = {
        "symbol": _clean_symbol(symbol),
        "snapshot_type": "last_known_good",
        "observed_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "source": source,
        "product": _snapshot_rows(product),
        "geographic": _snapshot_rows(geographic),
    }
    try:
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _load_segment_snapshot(symbol: str) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Load runtime last-known-good first, then packaged migration seed."""
    for path in _segment_snapshot_paths(symbol):
        try:
            if not path.exists():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                continue
            product = normalize_segment_payload(payload.get("product", []), "Product")
            geographic = normalize_segment_payload(payload.get("geographic", []), "Geography")
            if product.empty and geographic.empty:
                continue
            kind = str(payload.get("snapshot_type") or "persisted_snapshot")
            label = "Persisted last-known-good segment snapshot"
            source_quality = 0.82
            if "migration_seed" in kind:
                label = "Migration seed from prior valid provider snapshot"
                source_quality = 0.78
            if not product.empty:
                product["Source"] = label
            if not geographic.empty:
                geographic["Source"] = label
            return product, geographic, {
                "source_type": kind,
                "source_label": label,
                "source_quality": source_quality,
                "observed_at": payload.get("observed_at"),
                "path": str(path),
            }
        except Exception:
            continue
    return pd.DataFrame(), pd.DataFrame(), {}


@st.cache_data(ttl=21600, show_spinner=False)
def load_fmp_segments(symbol: str, company_data: dict | None = None) -> dict[str, Any]:
    """Resolve segment data through live provider -> persisted last-known-good -> seed.

    V2.4 treats segment disclosures as slow-moving fundamental data. A transient provider
    or plan failure must therefore not erase a previously validated company snapshot.
    Valid live observations are persisted automatically; empty responses never overwrite
    the cache.
    """
    symbol = _clean_symbol(symbol)
    if not symbol:
        return {"product": pd.DataFrame(), "geographic": pd.DataFrame(), "metadata": {}}

    raw = company_data.get("raw_data", {}) if isinstance(company_data, dict) else {}
    raw_fmp = raw.get("fmp", {}) if isinstance(raw, dict) else {}

    product_raw = raw_fmp.get("product_segments_raw", []) if isinstance(raw_fmp, dict) else []
    geographic_raw = raw_fmp.get("geographic_segments_raw", []) if isinstance(raw_fmp, dict) else []

    product_df = normalize_segment_payload(product_raw, "Product")
    geographic_df = normalize_segment_payload(geographic_raw, "Geography")
    product_source = "Central FMP company bundle" if not product_df.empty else None
    geographic_source = "Central FMP company bundle" if not geographic_df.empty else None

    if get_fmp_api_key():
        if product_df.empty:
            for endpoint, params, version in [
                ("revenue-product-segmentation", {"symbol": symbol}, "stable"),
                ("revenue-product-segmentation", {"symbol": symbol, "structure": "flat"}, "stable"),
                ("revenue-product-segmentation", {"symbol": symbol}, "v4"),
            ]:
                payload = _fmp_stable_json(endpoint, params) if version == "stable" else _fmp_v4_json(endpoint, params)
                product_df = normalize_segment_payload(payload, "Product")
                if not product_df.empty:
                    product_source = f"FMP {version} {endpoint}"
                    break

        if geographic_df.empty:
            for endpoint, params, version in [
                ("revenue-geographic-segments", {"symbol": symbol}, "stable"),
                ("revenue-geographic-segmentation", {"symbol": symbol}, "stable"),
                ("revenue-geographic-segments", {"symbol": symbol, "structure": "flat"}, "stable"),
                ("revenue-geographic-segmentation", {"symbol": symbol, "structure": "flat"}, "stable"),
                ("revenue-geographic-segmentation", {"symbol": symbol}, "v4"),
            ]:
                payload = _fmp_stable_json(endpoint, params) if version == "stable" else _fmp_v4_json(endpoint, params)
                geographic_df = normalize_segment_payload(payload, "Geography")
                if not geographic_df.empty:
                    geographic_source = f"FMP {version} {endpoint}"
                    break

    had_live_segment = bool(product_source or geographic_source)
    cached_product, cached_geographic, cache_meta = _load_segment_snapshot(symbol)
    if product_df.empty and not cached_product.empty:
        product_df = cached_product
        product_source = cache_meta.get("source_label")
    if geographic_df.empty and not cached_geographic.empty:
        geographic_df = cached_geographic
        geographic_source = cache_meta.get("source_label")

    if not product_df.empty and product_source and "snapshot" not in product_source.lower() and "seed" not in product_source.lower():
        product_df = product_df.copy(); product_df["Source"] = product_source
    if not geographic_df.empty and geographic_source and "snapshot" not in geographic_source.lower() and "seed" not in geographic_source.lower():
        geographic_df = geographic_df.copy(); geographic_df["Source"] = geographic_source

    # Persist the merged last-known-good view after fallback resolution. This prevents a
    # partial live response from erasing the other dimension already stored on disk.
    if had_live_segment and (not product_df.empty or not geographic_df.empty):
        _save_segment_snapshot(
            symbol,
            product_df,
            geographic_df,
            "; ".join(x for x in [product_source, geographic_source] if x) or "Validated segment data",
        )

    metadata = {
        "product_source": product_source,
        "geographic_source": geographic_source,
        "product_live": bool(product_source and str(product_source).startswith(("Central FMP", "FMP "))),
        "geographic_live": bool(geographic_source and str(geographic_source).startswith(("Central FMP", "FMP "))),
        "snapshot_type": cache_meta.get("source_type") if cache_meta else None,
        "snapshot_observed_at": cache_meta.get("observed_at") if cache_meta else None,
        "snapshot_path": cache_meta.get("path") if cache_meta else None,
        "snapshot_source_quality": cache_meta.get("source_quality") if cache_meta else None,
    }
    return {"product": product_df, "geographic": geographic_df, "metadata": metadata}


def normalize_segment_payload(payload, dimension: str) -> pd.DataFrame:
    """Normalize FMP flat/hierarchical/date-keyed segment responses into long form."""
    rows: list[dict] = []

    metadata_keys = {
        "symbol", "date", "fiscalyear", "fiscal_year", "fiscalYear",
        "period", "reportedcurrency", "reportedCurrency", "currency",
        "calendarYear", "year", "quarter", "structure", "lastUpdated",
    }

    def emit(name, value, meta):
        numeric = safe_float(value)
        if numeric is None:
            return
        name = str(name or "").strip()
        if not name:
            return
        rows.append({
            "Date": pd.to_datetime(meta.get("date"), errors="coerce"),
            "Fiscal Year": safe_int(meta.get("fiscal_year")),
            "Period": str(meta.get("period") or "FY"),
            "Dimension": dimension,
            "Segment": name,
            "Revenue": numeric,
            "Currency": str(meta.get("currency") or ""),
            "Source": "FMP revenue segmentation · central bundle/fallback",
        })

    def looks_like_date_key(value: str) -> bool:
        return bool(re.fullmatch(r"20\d{2}-\d{2}-\d{2}", str(value)))

    def looks_like_year_key(value: str) -> bool:
        return bool(re.fullmatch(r"20\d{2}", str(value)))

    def walk(obj, meta=None):
        meta = dict(meta or {})
        if isinstance(obj, list):
            for item in obj:
                walk(item, meta)
            return
        if not isinstance(obj, dict):
            return

        local = dict(meta)
        local["date"] = _pick(obj, ["date", "fillingDate", "filingDate"], local.get("date"))
        local["fiscal_year"] = _pick(obj, ["fiscalYear", "calendarYear", "year"], local.get("fiscal_year"))
        local["period"] = _pick(obj, ["period", "fiscalPeriod"], local.get("period"))
        local["currency"] = _pick(obj, ["reportedCurrency", "currency"], local.get("currency", ""))

        # Common flat row: {segment: 'Data Center', revenue: ...}
        name = _pick(obj, ["segment", "name", "product", "geography", "region", "country"])
        amount = _numeric(obj, ["revenue", "value", "amount"])
        if name not in [None, ""] and amount is not None:
            emit(name, amount, local)
            return

        # Containers used by different generations of the endpoint.
        for key in ["data", "segments", "revenue", "items", "results"]:
            nested = obj.get(key)
            if isinstance(nested, list):
                walk(nested, local)
            elif isinstance(nested, dict):
                for n, v in nested.items():
                    if isinstance(v, dict):
                        amount2 = _numeric(v, ["revenue", "value", "amount"])
                        if amount2 is not None:
                            emit(n, amount2, local)
                        else:
                            next_meta = dict(local)
                            if looks_like_date_key(str(n)):
                                next_meta["date"] = n
                                next_meta["fiscal_year"] = safe_int(str(n)[:4])
                            elif looks_like_year_key(str(n)):
                                next_meta["fiscal_year"] = safe_int(n)
                            walk(v, next_meta)
                    elif isinstance(v, list):
                        walk(v, local)
                    else:
                        emit(n, v, local)

        # Date/year-keyed wrappers and flat maps where segment names are top-level keys.
        for k, v in obj.items():
            if k in metadata_keys or k in {"data", "segments", "revenue", "items", "results"}:
                continue
            if isinstance(v, dict) and (looks_like_date_key(str(k)) or looks_like_year_key(str(k))):
                next_meta = dict(local)
                if looks_like_date_key(str(k)):
                    next_meta["date"] = k
                    next_meta["fiscal_year"] = safe_int(str(k)[:4])
                else:
                    next_meta["fiscal_year"] = safe_int(k)
                walk(v, next_meta)
            elif isinstance(v, (int, float, str)) and safe_float(v) is not None:
                emit(k, v, local)

    walk(payload)
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["Revenue"] = pd.to_numeric(df["Revenue"], errors="coerce")
    df = df.dropna(subset=["Revenue"])
    df = df[df["Segment"].astype(str).str.strip().ne("")].copy()
    # Remove obvious metadata accidentally interpreted as segments.
    bad_names = {"fiscalyear", "calendaryear", "period", "reportedcurrency", "currency", "symbol", "date"}
    df = df[~df["Segment"].astype(str).str.lower().isin(bad_names)].copy()
    df = df.drop_duplicates(subset=["Date", "Fiscal Year", "Period", "Dimension", "Segment", "Revenue"])

    # If a date exists but fiscal year did not, infer it; this also preserves the historical
    # V1 behavior that successfully rendered NVDA segment history.
    missing_fy = df["Fiscal Year"].isna() & df["Date"].notna()
    if missing_fy.any():
        df.loc[missing_fy, "Fiscal Year"] = df.loc[missing_fy, "Date"].dt.year

    period_total = df.groupby(["Date", "Fiscal Year", "Period"], dropna=False)["Revenue"].transform("sum")
    df["Share"] = np.where(period_total != 0, df["Revenue"] / period_total, np.nan)
    df = df.sort_values(["Segment", "Date", "Fiscal Year"], na_position="last")
    df["Growth"] = df.groupby("Segment")["Revenue"].pct_change()
    return df.sort_values(["Date", "Fiscal Year", "Revenue"], ascending=[False, False, False], na_position="last").reset_index(drop=True)


@st.cache_data(ttl=43200, show_spinner=False)
def load_fmp_peers(symbol: str) -> pd.DataFrame:
    symbol = _clean_symbol(symbol)
    if not get_fmp_api_key() or not symbol:
        return pd.DataFrame()
    return _to_frame(_fmp_stable_json("stock-peers", {"symbol": symbol}))


@st.cache_data(ttl=43200, show_spinner=False)
def load_fmp_governance(symbol: str) -> dict[str, pd.DataFrame]:
    symbol = _clean_symbol(symbol)
    if not get_fmp_api_key() or not symbol:
        return {
            "executives": pd.DataFrame(),
            "compensation": pd.DataFrame(),
            "transcript_dates": pd.DataFrame(),
            "share_float": pd.DataFrame(),
        }

    return {
        "executives": _to_frame(_fmp_stable_json("key-executives", {"symbol": symbol})),
        "compensation": _to_frame(_fmp_stable_json("governance-executive-compensation", {"symbol": symbol})),
        "transcript_dates": _to_frame(_fmp_stable_json("earning-call-transcript-dates", {"symbol": symbol})),
        "share_float": _to_frame(_fmp_stable_json("shares-float", {"symbol": symbol})),
    }


def normalize_yfinance_executives(company_data: dict | None) -> pd.DataFrame:
    """Fallback leadership table from yfinance's companyOfficers payload."""
    raw = company_data.get("raw_data", {}) if isinstance(company_data, dict) else {}
    info = raw.get("info", {}) if isinstance(raw, dict) else {}
    officers = info.get("companyOfficers", []) if isinstance(info, dict) else []
    if not isinstance(officers, list) or not officers:
        return pd.DataFrame()
    rows = []
    for item in officers:
        if not isinstance(item, dict):
            continue
        rows.append({
            "name": item.get("name") or "N/A",
            "title": item.get("title") or "N/A",
            "pay": safe_float(item.get("totalPay") or item.get("totalPayCurrency")),
            "currencyPay": item.get("currency") or info.get("currency") or "",
            "yearBorn": safe_int(item.get("yearBorn")),
            # Yahoo's ``fiscalYear`` is not a title-start year. Only populate this field
            # when the payload explicitly exposes a tenure/appointment year.
            "titleSince": safe_int(first_present_flexible(item, ["titleSince", "since", "yearAppointed", "startYear"])),
            "active": True,
            "source": "Yahoo company officers fallback",
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=43200, show_spinner=False)
def load_sec_submissions(symbol: str) -> dict[str, Any]:
    symbol = _clean_symbol(symbol)
    cik = sec_ticker_to_cik(symbol)
    if not cik:
        return {"cik": None, "filings": pd.DataFrame(), "raw": {}}

    try:
        response = requests.get(
            f"{SEC_SUBMISSIONS_BASE}/CIK{cik}.json",
            headers=_sec_headers(),
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return {"cik": cik, "filings": pd.DataFrame(), "raw": {}}

    recent = (payload.get("filings", {}) or {}).get("recent", {}) or {}
    if not isinstance(recent, dict) or not recent:
        return {"cik": cik, "filings": pd.DataFrame(), "raw": payload}

    max_len = max((len(v) for v in recent.values() if isinstance(v, list)), default=0)
    rows: list[dict] = []
    for i in range(max_len):
        row = {}
        for key, values in recent.items():
            if isinstance(values, list) and i < len(values):
                row[key] = values[i]
        if row:
            rows.append(row)

    filings = pd.DataFrame(rows)
    if not filings.empty:
        for col in ["filingDate", "reportDate", "acceptanceDateTime"]:
            if col in filings.columns:
                filings[col] = pd.to_datetime(filings[col], errors="coerce")
        if "filingDate" in filings.columns:
            filings = filings.sort_values("filingDate", ascending=False)

    return {"cik": cik, "filings": filings.reset_index(drop=True), "raw": payload}


def _filing_url(cik: str, accession: str, primary_document: str) -> str | None:
    if not cik or not accession or not primary_document:
        return None
    cik_plain = str(int(str(cik)))
    accession_plain = re.sub(r"[^0-9]", "", str(accession))
    return f"{SEC_ARCHIVE_BASE}/{cik_plain}/{accession_plain}/{primary_document}"


def _html_to_text(html: str) -> str:
    """Extract readable SEC filing text while preserving paragraph/heading boundaries."""
    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text("\n")
    except Exception:
        text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
        text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
        text = re.sub(r"(?is)<[^>]+>", "\n", text)
        text = unescape(text)

    lines = []
    for line in str(text).splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def _relationship_risk_type(text: str) -> str:
    low = text.lower()
    if any(k in low for k in ["sole source", "single source", "single-source"]):
        return "Single-source dependency"
    if "customer" in low or "customers" in low:
        if any(k in low for k in ["accounted for", "represented", "% of revenue", "concentration"]):
            return "Customer concentration"
        return "Customer dependency"
    if any(k in low for k in ["supplier", "suppliers", "foundry", "foundries", "manufacturer", "manufacturing partner"]):
        if "%" in low and "purchase" in low:
            return "Supplier concentration"
        return "Supplier / supply-chain dependency"
    return "Business relationship disclosure"


def _extract_percent(text: str) -> float | None:
    values = []
    for match in re.findall(r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*%", text):
        value = safe_float(match)
        if value is not None and 0 <= value <= 100:
            values.append(value / 100.0)
    return max(values) if values else None


def _extract_10k_sections(text: str) -> dict[str, str]:
    """Return large, decision-useful 10-K sections and avoid TOC-only matches.

    SEC filing HTML differs materially by issuer. We therefore search for multiple Item
    heading variants, then keep the *largest plausible* chunk for each item. A table of
    contents match is usually tiny and loses the max-length competition.
    """
    if not text:
        return {}

    specs = [
        ("Item 1 — Business", r"(?im)^\s*item\s+1[\.:\-]?\s*(?:business)?\s*$", r"(?im)^\s*item\s+1a[\.:\-]"),
        ("Item 1A — Risk Factors", r"(?im)^\s*item\s+1a[\.:\-]?\s*(?:risk factors)?\s*$", r"(?im)^\s*item\s+1b[\.:\-]"),
        ("Item 7 — MD&A", r"(?im)^\s*item\s+7[\.:\-]?\s*(?:management.{0,80})?$", r"(?im)^\s*item\s+7a[\.:\-]"),
        ("Item 8 — Financial Statements", r"(?im)^\s*item\s+8[\.:\-]?\s*(?:financial statements.{0,80})?$", r"(?im)^\s*item\s+9[\.:\-]"),
    ]
    out: dict[str, str] = {}
    for label, start_pat, end_pat in specs:
        starts = [m.start() for m in re.finditer(start_pat, text)]
        candidates = []
        for pos in starts:
            m_end = re.search(end_pat, text[pos + 20:])
            end = pos + 20 + m_end.start() if m_end else min(len(text), pos + 220_000)
            chunk = text[pos:end].strip()
            if 500 <= len(chunk) <= 250_000:
                candidates.append(chunk)
        if candidates:
            out[label] = max(candidates, key=len)
    if not out:
        out["Full 10-K fallback"] = text[:700_000]
    return out


def _material_relationship_sentence(chunk: str) -> bool:
    low = chunk.lower()
    dependency_terms = [
        "customer", "customers", "supplier", "suppliers", "supply chain",
        "sole source", "single source", "single-source", "foundry", "foundries",
        "manufacturing partner", "contract manufacturer", "purchase commitments",
    ]
    if not any(k in low for k in dependency_terms):
        return False
    reject = [
        "table of contents", "investment portfolio", "marketable securities",
        "portfolio contains industry sector concentration", "credit risk from our investment",
    ]
    if any(k in low for k in reject):
        return False

    pct = _extract_percent(chunk)
    customer_material = (
        ("customer" in low or "customers" in low)
        and any(k in low for k in ["revenue", "sales", "accounted for", "represented", "concentration", "significant amount"])
    )
    supply_material = any(k in low for k in [
        "sole source", "single source", "single-source", "limited number of suppliers",
        "limited number of foundries", "limited number of manufacturing", "supplier concentration",
        "purchase commitment", "depend on", "dependent on",
    ]) and any(k in low for k in ["supplier", "foundry", "manufactur", "source", "supply"])
    return bool((pct is not None and (customer_material or supply_material)) or customer_material or supply_material)


def extract_relationship_disclosures(text: str, max_rows: int = 60) -> pd.DataFrame:
    if not text:
        return pd.DataFrame()

    sections = _extract_10k_sections(text)
    rows: list[dict] = []
    seen: set[tuple[str, str, int]] = set()

    for section_name, section_text in sections.items():
        # Preserve enough context around SEC/XBRL-flattened statements without swallowing
        # a whole page. Split on punctuation and line boundaries.
        chunks = re.split(r"(?<=[.!?;])\s+|\n+", section_text)
        for i, chunk in enumerate(chunks):
            chunk = re.sub(r"\s+", " ", chunk).strip()
            if len(chunk) < 55:
                continue
            if not _material_relationship_sentence(chunk):
                continue

            # Attach one adjacent sentence only when the current sentence is incomplete.
            # Never merge an already explicit customer-% sentence with a following supplier
            # sentence: that would leak the customer percentage into a supply-chain flag.
            context = chunk
            chunk_low = chunk.lower()
            current_pct = _extract_percent(chunk)
            current_strong = any(k in chunk_low for k in ["sole source", "single source", "single-source", "limited number of suppliers", "limited number of foundries"] )
            if i + 1 < len(chunks) and len(context) < 500 and current_pct is None and not current_strong:
                nxt = re.sub(r"\s+", " ", chunks[i + 1]).strip()
                nxt_low = nxt.lower()
                if ("customer" in chunk_low or "customers" in chunk_low) and any(k in nxt_low for k in ["customer", "revenue", "sales", "%"] ) and not any(k in nxt_low for k in ["supplier", "foundry", "manufactur"]):
                    context = f"{context} {nxt}"
                elif any(k in chunk_low for k in ["supplier", "foundry", "manufactur", "supply chain"]) and any(k in nxt_low for k in ["supplier", "foundry", "manufactur", "source", "supply"]):
                    context = f"{context} {nxt}"
            if len(context) > 950:
                context = context[:950].rsplit(" ", 1)[0] + "…"

            low = context.lower()
            # A percentage of revenue generated outside the U.S./by region is geographic
            # exposure, not a single-customer concentration.  Require explicit singular/
            # identifiable customer language before allowing a geographic sentence to be
            # classified as customer concentration.
            geographic_terms = [
                "customers headquartered", "outside the united states", "outside the u.s.",
                "geographic", "country", "countries", "region", "regions", "international",
            ]
            explicit_customer_terms = [
                "one customer", "one direct customer", "a direct customer", "single customer",
                "customer accounted for", "customer represented", "direct customer represented",
            ]
            if any(k in low for k in geographic_terms) and not any(k in low for k in explicit_customer_terms):
                continue

            risk_type = _relationship_risk_type(context)
            pct = _extract_percent(context)
            direct_customer = any(k in low for k in ["direct customer", "one customer", "a customer", "customers accounted"])
            strong_dependency = any(k in low for k in ["sole source", "single source", "single-source", "limited number"])
            revenue_link = any(k in low for k in ["revenue", "sales"])

            confidence = 55
            confidence += 18 if pct is not None else 0
            confidence += 12 if revenue_link else 0
            confidence += 10 if direct_customer else 0
            confidence += 15 if strong_dependency else 0
            confidence += 5 if section_name in ["Item 1 — Business", "Item 1A — Risk Factors", "Item 8 — Financial Statements"] else 0
            confidence = int(min(100, confidence))

            # Deduplicate repeated XBRL/TOC representations by risk type + disclosed % +
            # normalized first 150 chars rather than exact whole-text equality.
            normalized = re.sub(r"[^a-z0-9]+", "", low)[:150]
            pct_key = int(round((pct or -1) * 1000))
            key = (risk_type, normalized, pct_key)
            if key in seen:
                continue
            seen.add(key)

            counterparty = "Unnamed"
            if "direct customer" in low:
                counterparty = "Unnamed direct customer"
            elif "indirect customer" in low:
                counterparty = "Unnamed indirect customer"

            rows.append({
                "Section": section_name,
                "Risk Type": risk_type,
                "Counterparty": counterparty,
                "Disclosed %": pct,
                "Confidence": confidence,
                "Disclosure": context,
            })
            if len(rows) >= max_rows:
                break
        if len(rows) >= max_rows:
            break

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    # Prioritize explicit concentration/single-source disclosures.
    priority = {
        "Customer concentration": 0,
        "Single-source dependency": 1,
        "Supplier concentration": 2,
        "Supplier / supply-chain dependency": 3,
        "Customer dependency": 4,
        "Business relationship disclosure": 5,
    }
    df["_priority"] = df["Risk Type"].map(priority).fillna(9)
    df = df.sort_values(["_priority", "Confidence", "Disclosed %"], ascending=[True, False, False], na_position="last")
    # Repeated Inline-XBRL fragments often restate the same unnamed concentration fact.
    # Keep the highest-confidence representation of identical risk/percentage/counterparty tuples.
    df = df.drop_duplicates(subset=["Risk Type", "Disclosed %", "Counterparty"], keep="first")
    return df.drop(columns="_priority").reset_index(drop=True)


def _relationship_summary(disclosures: pd.DataFrame) -> dict[str, Any]:
    if not isinstance(disclosures, pd.DataFrame) or disclosures.empty:
        return {
            "max_customer_concentration": None,
            "max_supplier_concentration": None,
            "customer_risk_score": None,
            "supplier_risk_score": None,
            "single_source_count": 0,
            "ecosystem_risk_score": None,
            "customer_confidence": 0,
            "supplier_confidence": 0,
        }

    risk = disclosures["Risk Type"].astype(str)
    pct = pd.to_numeric(disclosures.get("Disclosed %"), errors="coerce")
    conf = pd.to_numeric(disclosures.get("Confidence"), errors="coerce")
    customer_mask = risk.str.contains("Customer", case=False, na=False)
    supplier_mask = risk.str.contains("Supplier", case=False, na=False)
    single_mask = risk.str.contains("Single-source", case=False, na=False)

    max_customer = safe_float(pct[customer_mask].max()) if customer_mask.any() and pct[customer_mask].notna().any() else None
    max_supplier = safe_float(pct[supplier_mask].max()) if supplier_mask.any() and pct[supplier_mask].notna().any() else None
    single_count = int(single_mask.sum())
    customer_conf = round(float(conf[customer_mask].mean()), 1) if customer_mask.any() and conf[customer_mask].notna().any() else 0
    supplier_conf = round(float(conf[supplier_mask | single_mask].mean()), 1) if (supplier_mask | single_mask).any() and conf[supplier_mask | single_mask].notna().any() else 0

    # Calibrated risk curve: avoid saturating at ~100 for a 20-25% customer concentration.
    # 10% ~= 45-55, 20% ~= 65-75, 30% ~= 80+, before breadth/confidence adjustments.
    customer_score = None
    if max_customer is not None or customer_mask.any():
        base = 25.0 + clamp((max_customer or 0) * 190, 0, 60)
        breadth_adj = min(10, max(0, int(customer_mask.sum()) - 1) * 2)
        customer_score = round(clamp(base + breadth_adj), 1)

    supplier_score = None
    if max_supplier is not None or supplier_mask.any() or single_count:
        base = 20.0 + clamp((max_supplier or 0) * 150, 0, 45)
        source_adj = min(30, single_count * 12)
        breadth_adj = min(10, int(supplier_mask.sum()) * 2)
        supplier_score = round(clamp(base + source_adj + breadth_adj), 1)

    parts = [x for x in [customer_score, supplier_score] if x is not None]
    ecosystem = round(float(np.mean(parts)), 1) if parts else None
    return {
        "max_customer_concentration": max_customer,
        "max_supplier_concentration": max_supplier,
        "customer_risk_score": customer_score,
        "supplier_risk_score": supplier_score,
        "single_source_count": single_count,
        "ecosystem_risk_score": ecosystem,
        "customer_confidence": customer_conf,
        "supplier_confidence": supplier_conf,
    }


@st.cache_data(ttl=86400, show_spinner=False)
def load_sec_relationship_intelligence(symbol: str) -> dict[str, Any]:
    submissions = load_sec_submissions(symbol)
    cik = submissions.get("cik")
    filings = submissions.get("filings", pd.DataFrame())

    empty = {"disclosures": pd.DataFrame(), "summary": {}, "filing_url": None, "filing_date": None}
    if not cik or not isinstance(filings, pd.DataFrame) or filings.empty or "form" not in filings.columns:
        return empty

    tenk = filings[filings["form"].astype(str).str.upper().isin(["10-K", "10-K/A"])].copy()
    if tenk.empty:
        return empty

    row = tenk.iloc[0]
    url = _filing_url(cik, row.get("accessionNumber"), row.get("primaryDocument"))
    if not url:
        return {**empty, "filing_date": row.get("filingDate")}

    try:
        response = requests.get(url, headers=_sec_headers(), timeout=25)
        response.raise_for_status()
        text = _html_to_text(response.text)
        disclosures = extract_relationship_disclosures(text)
    except Exception:
        disclosures = pd.DataFrame()

    if not disclosures.empty:
        disclosures["Source"] = "SEC 10-K"
        disclosures["Filing Date"] = row.get("filingDate")
        disclosures["URL"] = url

    return {
        "disclosures": disclosures,
        "summary": _relationship_summary(disclosures),
        "filing_url": url,
        "filing_date": row.get("filingDate"),
    }


def _holder_concentration(yf_bundle: dict[str, pd.DataFrame]) -> dict[str, float | None]:
    df = yf_bundle.get("institutional_holders", pd.DataFrame())
    if not isinstance(df, pd.DataFrame) or df.empty:
        return {"top10": None, "hhi": None, "holders": None}

    pct_col = None
    for candidate in ["pctHeld", "% Out", "pct_held", "Percent Out"]:
        if candidate in df.columns:
            pct_col = candidate
            break

    if pct_col is None:
        return {"top10": None, "hhi": None, "holders": len(df)}

    pct = pd.to_numeric(df[pct_col], errors="coerce").dropna().abs()
    if pct.empty:
        return {"top10": None, "hhi": None, "holders": len(df)}
    if pct.max() > 1.5:
        pct = pct / 100.0

    top10 = float(pct.nlargest(10).sum())
    hhi = float((pct ** 2).sum())
    return {"top10": top10, "hhi": hhi, "holders": len(df)}


def _ownership_score(history: pd.DataFrame, concentration: dict[str, Any]) -> float | None:
    if history is None or history.empty:
        return None

    score = 50.0
    latest = history.iloc[0]
    previous = history.iloc[1] if len(history) > 1 else None

    shares_change = safe_float(latest.get("Shares Change"))
    if shares_change is not None:
        score += 10 if shares_change > 0 else -10 if shares_change < 0 else 0

    if previous is not None:
        investors_now = safe_float(latest.get("Investors"))
        investors_prev = safe_float(previous.get("Investors"))
        if investors_now is not None and investors_prev not in [None, 0]:
            chg = investors_now / investors_prev - 1
            score += clamp(chg * 120, -12, 12)

        ownership_now = safe_float(latest.get("Ownership %"))
        ownership_prev = safe_float(previous.get("Ownership %"))
        if ownership_now is not None and ownership_prev is not None:
            score += clamp((ownership_now - ownership_prev) * 80, -10, 10)

    top10 = safe_float(concentration.get("top10"))
    if top10 is not None:
        # High concentration is not necessarily bearish, but it raises crowding risk;
        # only a mild penalty is applied to the conviction score.
        if top10 > 0.75:
            score -= 8
        elif top10 > 0.60:
            score -= 4

    return round(clamp(score), 1)


def _insider_score(fmp_transactions: pd.DataFrame, yf_transactions: pd.DataFrame) -> float | None:
    frames = []
    if isinstance(fmp_transactions, pd.DataFrame) and not fmp_transactions.empty:
        f = fmp_transactions.copy()
        frames.append(f)
    if isinstance(yf_transactions, pd.DataFrame) and not yf_transactions.empty:
        frames.append(yf_transactions.copy())
    if not frames:
        return None

    # FMP is preferred for signed acquisition/disposition semantics.
    df = frames[0]
    acq_col = next((c for c in ["acquisitionOrDisposition", "acquisitionDisposition", "transactionType"] if c in df.columns), None)
    shares_col = next((c for c in ["securitiesTransacted", "shares", "Shares", "Value"] if c in df.columns), None)

    if acq_col is None or shares_col is None:
        return 50.0

    signed = []
    for _, row in df.iterrows():
        raw = str(row.get(acq_col, "")).upper()
        qty = abs(safe_float(row.get(shares_col), 0) or 0)
        if raw in {"A", "ACQUISITION", "BUY", "PURCHASE", "P-PURCHASE"} or "PURCHASE" in raw:
            signed.append(qty)
        elif raw in {"D", "DISPOSITION", "SELL", "SALE", "S-SALE"} or "SALE" in raw:
            signed.append(-qty)

    if not signed or sum(abs(x) for x in signed) == 0:
        return 50.0

    ratio = sum(signed) / sum(abs(x) for x in signed)
    return round(clamp(50 + 35 * ratio), 1)


def _segment_summary(df: pd.DataFrame) -> dict[str, Any]:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return {
            "latest": pd.DataFrame(), "previous": pd.DataFrame(), "hhi": None,
            "top_share": None, "top_share_delta": None, "diversification_score": None,
            "taxonomy_changed": False, "added_segments": [], "removed_segments": [],
        }

    work = df.copy()
    work["Date"] = pd.to_datetime(work.get("Date"), errors="coerce")
    work["Fiscal Year"] = pd.to_numeric(work.get("Fiscal Year"), errors="coerce")

    # Build ordered period keys without assuming every issuer uses the same filing date logic.
    period_keys = (
        work[["Date", "Fiscal Year", "Period"]]
        .drop_duplicates()
        .sort_values(["Date", "Fiscal Year"], ascending=[False, False], na_position="last")
    )
    if period_keys.empty:
        latest = work.copy()
        previous = pd.DataFrame()
    else:
        first = period_keys.iloc[0]
        if pd.notna(first.get("Date")):
            latest = work[work["Date"].eq(first["Date"])].copy()
        else:
            latest = work[work["Fiscal Year"].eq(first["Fiscal Year"])].copy()

        previous = pd.DataFrame()
        if len(period_keys) > 1:
            prev = period_keys.iloc[1]
            if pd.notna(prev.get("Date")):
                previous = work[work["Date"].eq(prev["Date"])].copy()
            else:
                previous = work[work["Fiscal Year"].eq(prev["Fiscal Year"])].copy()

    shares = pd.to_numeric(latest.get("Share"), errors="coerce").dropna()
    if shares.empty:
        return {
            "latest": latest, "previous": previous, "hhi": None, "top_share": None,
            "top_share_delta": None, "diversification_score": None,
            "taxonomy_changed": False, "added_segments": [], "removed_segments": [],
        }

    hhi = float((shares ** 2).sum())
    top_share = float(shares.max())
    diversification = float(clamp((1 - hhi) * 125, 0, 100))

    previous_top = None
    if isinstance(previous, pd.DataFrame) and not previous.empty:
        pshares = pd.to_numeric(previous.get("Share"), errors="coerce").dropna()
        if not pshares.empty:
            previous_top = float(pshares.max())

    latest_labels = {str(x).strip() for x in latest.get("Segment", pd.Series(dtype=str)).dropna() if str(x).strip()}
    previous_labels = {str(x).strip() for x in previous.get("Segment", pd.Series(dtype=str)).dropna() if str(x).strip()}
    added = sorted(latest_labels - previous_labels) if previous_labels else []
    removed = sorted(previous_labels - latest_labels) if previous_labels else []
    taxonomy_changed = bool(previous_labels and (added or removed))

    return {
        "latest": latest.sort_values("Revenue", ascending=False),
        "previous": previous.sort_values("Revenue", ascending=False) if isinstance(previous, pd.DataFrame) and not previous.empty else previous,
        "hhi": hhi,
        "top_share": top_share,
        "top_share_delta": (top_share - previous_top) if previous_top is not None else None,
        "diversification_score": round(diversification, 1),
        "taxonomy_changed": taxonomy_changed,
        "added_segments": added,
        "removed_segments": removed,
    }


def _ecosystem_risk(disclosures: pd.DataFrame) -> float | None:
    if not isinstance(disclosures, pd.DataFrame) or disclosures.empty:
        return None

    score = 20.0
    pct = pd.to_numeric(disclosures.get("Disclosed %"), errors="coerce").dropna()
    if not pct.empty:
        max_pct = float(pct.max())
        score += clamp(max_pct * 90, 0, 50)

    risk_types = disclosures.get("Risk Type", pd.Series(dtype=str)).astype(str)
    sole_sources = risk_types.str.contains("Single-source", case=False, na=False).sum()
    supplier = risk_types.str.contains("Supplier", case=False, na=False).sum()
    score += min(20, sole_sources * 8)
    score += min(10, supplier * 2)
    return round(clamp(score), 1)


@st.cache_data(ttl=21600, show_spinner=False)
def build_institutional_bundle(symbol: str, company_data: dict | None = None) -> dict[str, Any]:
    symbol = _clean_symbol(symbol)

    ownership_history = load_fmp_ownership_history(symbol)
    yf_ownership = load_yfinance_ownership(symbol)
    insider = load_fmp_insider_bundle(symbol)
    segments = load_fmp_segments(symbol, company_data)
    peers = load_fmp_peers(symbol)
    governance = load_fmp_governance(symbol)
    if isinstance(governance, dict) and governance.get("executives", pd.DataFrame()).empty:
        governance = dict(governance)
        governance["executives"] = normalize_yfinance_executives(company_data)
    sec = load_sec_submissions(symbol)
    sec_events = build_sec_event_intelligence(sec.get("filings", pd.DataFrame()) if isinstance(sec, dict) else pd.DataFrame())
    relationships = load_sec_relationship_intelligence(symbol)

    ownership_v2 = build_ownership_intelligence(yf_ownership, ownership_history)
    insider_v2 = build_insider_intelligence(
        insider.get("transactions", pd.DataFrame()),
        yf_ownership.get("insider_transactions", pd.DataFrame()),
    )

    # Preserve the old holder_concentration contract for UI/backward compatibility, but
    # source the values from the richer V2 engine when available.
    own_summary = ownership_v2.get("summary", {}) if isinstance(ownership_v2, dict) else {}
    concentration = {
        "top1": own_summary.get("top1"),
        "top5": own_summary.get("top5"),
        "top10": own_summary.get("top10"),
        "hhi": own_summary.get("hhi"),
        "holders": own_summary.get("holder_records"),
    }

    product_summary = _segment_summary(segments.get("product", pd.DataFrame()))
    geographic_summary = _segment_summary(segments.get("geographic", pd.DataFrame()))
    relationship_summary = relationships.get("summary", {}) if isinstance(relationships, dict) else {}
    ecosystem_risk = relationship_summary.get("ecosystem_risk_score")

    segment_meta = segments.get("metadata", {}) if isinstance(segments, dict) else {}
    snapshot_quality = safe_float(segment_meta.get("snapshot_source_quality"), 0.78) or 0.78
    product_quality = 0.95 if segment_meta.get("product_live") else snapshot_quality if not segments.get("product", pd.DataFrame()).empty else 0.0
    geographic_quality = 0.95 if segment_meta.get("geographic_live") else snapshot_quality if not segments.get("geographic", pd.DataFrame()).empty else 0.0
    yahoo_insider_available = isinstance(yf_ownership.get("insider_transactions"), pd.DataFrame) and not yf_ownership.get("insider_transactions", pd.DataFrame()).empty

    source_quality = {
        "FMP 13F": 1.0 if not ownership_history.empty else 0.0,
        "Yahoo holders": 0.70 if any(isinstance(v, pd.DataFrame) and not v.empty for v in yf_ownership.values()) else 0.0,
        "Insider evidence": 1.0 if not insider.get("transactions", pd.DataFrame()).empty else 0.72 if yahoo_insider_available else 0.0,
        "Product segments": product_quality,
        "Geographic segments": geographic_quality,
        "SEC filings": 1.0 if not sec.get("filings", pd.DataFrame()).empty else 0.0,
        "SEC relationship disclosures": 1.0 if not relationships.get("disclosures", pd.DataFrame()).empty else 0.0,
        "Governance": 0.85 if not governance.get("executives", pd.DataFrame()).empty else 0.0,
        "Provider peers": 0.65 if not peers.empty else 0.0,
    }
    source_flags = {k: bool(v > 0) for k, v in source_quality.items()}
    available_qualities = [v for v in source_quality.values() if v > 0]
    mean_source_quality = float(np.mean(available_qualities)) if available_qualities else 0.0
    cross_validation = 0.75 if source_flags.get("SEC filings") and source_flags.get("Yahoo holders") else 0.55
    confidence_detail = calculate_data_confidence(
        source_flags,
        source_quality=mean_source_quality,
        freshness=0.85,
        cross_validation=cross_validation,
    )
    data_confidence = confidence_detail.get("score", 0.0)

    base_scores = {
        "ownership_score": ownership_v2.get("score") if isinstance(ownership_v2, dict) else None,
        "insider_score": insider_v2.get("score") if isinstance(insider_v2, dict) else None,
        "product_diversification_score": product_summary.get("diversification_score"),
        "geographic_diversification_score": geographic_summary.get("diversification_score"),
        "ecosystem_risk_score": ecosystem_risk,
        "customer_risk_score": relationship_summary.get("customer_risk_score"),
        "supplier_risk_score": relationship_summary.get("supplier_risk_score"),
        "data_confidence": data_confidence,
    }
    overlay = calculate_institutional_overlay(
        ownership_score=base_scores.get("ownership_score"),
        insider_score=base_scores.get("insider_score"),
        product_diversification=base_scores.get("product_diversification_score"),
        geographic_diversification=base_scores.get("geographic_diversification_score"),
        customer_risk=base_scores.get("customer_risk_score"),
        supplier_risk=base_scores.get("supplier_risk_score"),
    )

    return {
        "symbol": symbol,
        "ownership_history": ownership_history,
        "yf_ownership": yf_ownership,
        "holder_concentration": concentration,
        "ownership_v2": ownership_v2,
        "insider": insider,
        "insider_v2": insider_v2,
        "segments": segments,
        "product_summary": product_summary,
        "geographic_summary": geographic_summary,
        "peers": peers,
        "governance": governance,
        "sec": sec,
        "sec_events": sec_events,
        "relationships": relationships,
        "scores": base_scores,
        "overlay": overlay,
        "confidence_detail": confidence_detail,
        "source_flags": source_flags,
        "source_quality": source_quality,
    }

