from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
import os
import math
import re
import time

import numpy as np
import pandas as pd
import requests
import streamlit as st

from .config import DEFAULT_BENCHMARKS

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except Exception:  # pragma: no cover
    yf = None
    YFINANCE_AVAILABLE = False


# ============================================================
# SAFE GENERIC HELPERS
# ============================================================


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or isinstance(value, (pd.Series, pd.DataFrame, list, tuple, dict)):
            return default
        x = float(value)
        return x if np.isfinite(x) else default
    except Exception:
        return default


def _get_secret(*names: str) -> str:
    """Resolve a credential without logging or exposing it."""
    for name in names:
        try:
            value = st.secrets.get(name, "")
        except Exception:
            value = ""
        if isinstance(value, str) and value.strip():
            return value.strip()
        value = os.getenv(name, "")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _period_to_outputsize(period: str) -> int:
    return {
        "6mo": 150,
        "1y": 280,
        "2y": 560,
        "5y": 1320,
        "10y": 2600,
    }.get(str(period or "2y").lower(), 560)


def _period_to_dates(period: str) -> tuple[str, str]:
    days = {
        "6mo": 210,
        "1y": 390,
        "2y": 780,
        "5y": 1900,
        "10y": 3800,
    }.get(str(period or "2y").lower(), 780)
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)
    return start.isoformat(), end.isoformat()


def _attach_meta(df: pd.DataFrame, provider: str, attempts: list[dict[str, Any]], symbol: str) -> pd.DataFrame:
    work = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    work.attrs["provider"] = provider
    work.attrs["provider_attempts"] = attempts
    work.attrs["symbol"] = symbol
    return work


def _flatten_columns(df: pd.DataFrame, symbol: str = "") -> pd.DataFrame:
    work = df.copy()
    if isinstance(work.columns, pd.MultiIndex):
        cols = []
        for col in work.columns:
            parts = [str(x) for x in col if str(x) not in {"", "None"}]
            # yfinance single ticker MultiIndex usually (Price, Ticker): keep Price.
            cols.append(parts[0].lower().replace(" ", "_") if parts else "")
        work.columns = cols
    else:
        work.columns = [str(c).lower().replace(" ", "_") for c in work.columns]
    return work


def _standardize_price(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    work = _flatten_columns(df, symbol)

    if isinstance(work.index, pd.DatetimeIndex):
        work = work.reset_index()

    date_col = None
    for candidate in ("date", "datetime", "timestamp", "time", "index"):
        if candidate in work.columns:
            date_col = candidate
            break
    if date_col is None:
        date_like = [c for c in work.columns if "date" in c or "time" in c or c == "t"]
        date_col = date_like[0] if date_like else None

    if date_col is None or "close" not in work.columns:
        return pd.DataFrame()

    work = work.rename(columns={date_col: "date"})
    keep = [c for c in ["date", "open", "high", "low", "close", "adj_close", "volume"] if c in work.columns]
    work = work[keep].copy()

    work["date"] = pd.to_datetime(work["date"], errors="coerce", utc=True)
    for col in ["open", "high", "low", "close", "adj_close", "volume"]:
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce")

    for col in ["open", "high", "low"]:
        if col not in work.columns:
            work[col] = work["close"]
        else:
            work[col] = work[col].fillna(work["close"])

    if "volume" not in work.columns:
        work["volume"] = np.nan

    return (
        work.dropna(subset=["date", "close"])
        .sort_values("date")
        .drop_duplicates("date")
        .reset_index(drop=True)
    )




def _requested_start(period: str) -> pd.Timestamp:
    start, _ = _period_to_dates(period)
    return pd.Timestamp(start, tz="UTC")


def _slice_requested_period(df: pd.DataFrame, period: str) -> pd.DataFrame:
    """Slice a provider response to the requested research horizon."""
    if df is None or df.empty or "date" not in df.columns:
        return pd.DataFrame() if df is None else df
    work = df.copy()
    dates = pd.to_datetime(work["date"], errors="coerce", utc=True)
    start = _requested_start(period)
    work = work.loc[dates >= start].copy()
    return work.sort_values("date").reset_index(drop=True)


def _history_sufficient(df: pd.DataFrame, period: str) -> bool:
    """Reject a short fallback masquerading as a 5Y/10Y history."""
    if df is None or df.empty:
        return False
    minimum = {
        "6mo": 90,
        "1y": 180,
        "2y": 390,
        "5y": 950,
        "10y": 1900,
    }.get(str(period or "2y").lower(), 390)
    return len(df) >= minimum


def _request_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: tuple[int, int] = (5, 25),
    retries: int = 1,
) -> tuple[Any | None, dict[str, Any]]:
    """Small resilient GET helper that preserves HTTP diagnostics.

    V2.3.2 deliberately distinguishes rate limits/entitlement failures from
    generic request errors. A single bounded retry is used for 429/5xx only;
    it never loops indefinitely or hides a provider outage.
    """
    last: dict[str, Any] = {}
    for attempt in range(max(0, int(retries)) + 1):
        try:
            r = requests.get(url, params=params or {}, headers=headers or {}, timeout=timeout)
            http = int(r.status_code)
            last = {"http": http, "attempt": attempt + 1}
            if http == 429:
                last["status"] = "rate_limited"
            elif http in {401, 403}:
                last["status"] = "unauthorized_or_unentitled"
            elif 500 <= http <= 599:
                last["status"] = "provider_server_error"
            elif not (200 <= http < 300):
                last["status"] = "http_error"
            else:
                try:
                    return r.json(), {"status": "ok", "http": http, "attempt": attempt + 1}
                except Exception as exc:
                    return None, {"status": "bad_json", "http": http, "detail": type(exc).__name__}

            if attempt < retries and (http == 429 or 500 <= http <= 599):
                retry_after = r.headers.get("Retry-After", "")
                try:
                    delay = min(max(float(retry_after), 1.0), 5.0)
                except Exception:
                    delay = 1.5 * (attempt + 1)
                time.sleep(delay)
                continue
            return None, last
        except requests.RequestException as exc:
            last = {"status": "request_error", "detail": type(exc).__name__, "attempt": attempt + 1}
            if attempt < retries:
                time.sleep(1.0 * (attempt + 1))
                continue
            return None, last
        except Exception as exc:
            return None, {"status": "request_error", "detail": type(exc).__name__, "attempt": attempt + 1}
    return None, last or {"status": "request_error"}

# ============================================================
# TWELVE DATA — PRIMARY DAILY PRICE FALLBACK
# ============================================================


def _to_twelve_symbol(symbol: str) -> str:
    raw = str(symbol or "").upper().strip()
    if not raw:
        return ""

    fx_map = {
        "EURUSD=X": "EUR/USD",
        "GBPUSD=X": "GBP/USD",
        "USDJPY=X": "USD/JPY",
        "USDCHF=X": "USD/CHF",
        "AUDUSD=X": "AUD/USD",
        "USDCAD=X": "USD/CAD",
        "NZDUSD=X": "NZD/USD",
        "EURJPY=X": "EUR/JPY",
        "EURGBP=X": "EUR/GBP",
        "GBPJPY=X": "GBP/JPY",
    }
    index_map = {
        "^GSPC": "SPX",
        "^IXIC": "IXIC",
        "^DJI": "DJI",
        "^VIX": "VIX",
    }
    commodity_map = {
        "GC=F": "XAU/USD",
        "SI=F": "XAG/USD",
    }

    if raw in fx_map:
        return fx_map[raw]
    if raw in index_map:
        return index_map[raw]
    if raw in commodity_map:
        return commodity_map[raw]

    if raw.endswith("=X"):
        clean = raw[:-2]
        if len(clean) == 6:
            return f"{clean[:3]}/{clean[3:]}"
    if raw.endswith("-USD"):
        return raw.replace("-", "/")

    # Yahoo futures like ES=F / CL=F are not assumed to be valid Twelve Data symbols.
    if raw.endswith("=F"):
        return ""

    return raw


def _fetch_twelve_daily(symbol: str, period: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    key = _get_secret("TWELVE_DATA_API_KEY")
    if not key:
        return pd.DataFrame(), {"provider": "Twelve Data", "status": "disabled"}

    td_symbol = _to_twelve_symbol(symbol)
    if not td_symbol:
        return pd.DataFrame(), {"provider": "Twelve Data", "status": "unsupported_symbol"}

    payload, diag = _request_json(
        "https://api.twelvedata.com/time_series",
        params={
            "symbol": td_symbol,
            "interval": "1day",
            "outputsize": min(_period_to_outputsize(period), 5000),
            "apikey": key,
            "format": "JSON",
            "timezone": "UTC",
        },
        retries=1,
    )
    if payload is None:
        return pd.DataFrame(), {"provider": "Twelve Data", **diag}
    if not isinstance(payload, dict):
        return pd.DataFrame(), {"provider": "Twelve Data", "status": "bad_payload", **diag}
    if payload.get("status") == "error" or not isinstance(payload.get("values"), list):
        code = payload.get("code")
        message = str(payload.get("message") or "")[:160]
        status = "rate_limited" if code == 429 or "limit" in message.lower() else "api_error"
        return pd.DataFrame(), {"provider": "Twelve Data", "status": status, "api_code": code, "detail": message, **diag}

    raw = pd.DataFrame(payload.get("values") or []).rename(columns={"datetime": "date"})
    df = _slice_requested_period(_standardize_price(raw, symbol), period)
    if df.empty:
        return pd.DataFrame(), {"provider": "Twelve Data", "status": "normalize_empty", **diag}
    if not _history_sufficient(df, period):
        return pd.DataFrame(), {"provider": "Twelve Data", "status": "insufficient_history", "rows": int(len(df)), "provider_symbol": td_symbol, **diag}

    return df, {"provider": "Twelve Data", "status": "ok", "rows": int(len(df)), "provider_symbol": td_symbol, **diag}

# ============================================================
# MASSIVE / POLYGON — SECONDARY DAILY PRICE FALLBACK
# ============================================================


def _to_massive_symbol(symbol: str) -> str:
    raw = str(symbol or "").upper().strip()
    if raw == "^VIX":
        return "I:VIX"
    # Do not invent mappings for Yahoo FX/futures aliases here.
    if raw.endswith("=X") or raw.endswith("=F"):
        return ""
    return raw


def _fetch_massive_daily(symbol: str, period: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    key = _get_secret("MASSIVE_API_KEY", "MASSIVEAPI_KEY", "POLYGON_API_KEY")
    if not key:
        return pd.DataFrame(), {"provider": "Massive", "status": "disabled"}

    provider_symbol = _to_massive_symbol(symbol)
    if not provider_symbol:
        return pd.DataFrame(), {"provider": "Massive", "status": "unsupported_symbol"}

    start, end = _period_to_dates(period)
    # Current Massive REST docs authenticate this endpoint with apiKey in the
    # query string. V2.3.1 used an Authorization header, which can yield 401/403.
    payload, diag = _request_json(
        f"https://api.massive.com/v2/aggs/ticker/{provider_symbol}/range/1/day/{start}/{end}",
        params={"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": key},
        headers={"Accept": "application/json", "User-Agent": "QuantTerminal/market-psychology"},
        retries=1,
    )
    if payload is None:
        return pd.DataFrame(), {"provider": "Massive", **diag}
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list) or not results:
        return pd.DataFrame(), {"provider": "Massive", "status": "empty_or_unentitled", **diag}

    rows = []
    for item in results:
        if not isinstance(item, dict):
            continue
        rows.append({
            "date": pd.to_datetime(item.get("t"), unit="ms", errors="coerce", utc=True),
            "open": item.get("o"), "high": item.get("h"), "low": item.get("l"),
            "close": item.get("c"), "volume": item.get("v"),
        })
    df = _slice_requested_period(_standardize_price(pd.DataFrame(rows), symbol), period)
    if df.empty:
        return pd.DataFrame(), {"provider": "Massive", "status": "normalize_empty", **diag}
    if not _history_sufficient(df, period):
        return pd.DataFrame(), {"provider": "Massive", "status": "insufficient_history_or_plan_limit", "rows": int(len(df)), "provider_symbol": provider_symbol, **diag}
    return df, {"provider": "Massive", "status": "ok", "rows": int(len(df)), "provider_symbol": provider_symbol, **diag}

# ============================================================
# FMP — TERTIARY DAILY PRICE FALLBACK
# ============================================================


def _fetch_fmp_daily(symbol: str, period: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    key = _get_secret("FMP_API_KEY", "FINANCIAL_MODELING_PREP_API_KEY")
    raw_symbol = str(symbol or "").upper().strip()
    if not key:
        return pd.DataFrame(), {"provider": "FMP", "status": "disabled"}
    if not raw_symbol or raw_symbol.startswith("^") or raw_symbol.endswith("=X") or raw_symbol.endswith("=F"):
        return pd.DataFrame(), {"provider": "FMP", "status": "unsupported_symbol"}

    start, end = _period_to_dates(period)
    # FMP's current documented EOD endpoint is under /stable. Keep a light-chart
    # fallback because some plans expose light history but not the full OHLCV feed.
    endpoints = (
        ("full", "https://financialmodelingprep.com/stable/historical-price-eod/full"),
        ("light", "https://financialmodelingprep.com/stable/historical-price-eod/light"),
    )
    last_diag: dict[str, Any] = {}
    for mode, url in endpoints:
        payload, diag = _request_json(
            url,
            params={"symbol": raw_symbol, "from": start, "to": end, "apikey": key},
            retries=1,
        )
        last_diag = diag
        if payload is None:
            if diag.get("status") in {"rate_limited", "provider_server_error"}:
                continue
            # entitlement on full can still permit light
            if mode == "full":
                continue
            return pd.DataFrame(), {"provider": "FMP", **diag}

        rows = payload if isinstance(payload, list) else (payload.get("historical") if isinstance(payload, dict) else None)
        if not isinstance(rows, list) or not rows:
            if mode == "full":
                continue
            return pd.DataFrame(), {"provider": "FMP", "status": "empty_or_unentitled", **diag}

        raw = pd.DataFrame(rows).rename(columns={"adjClose": "adj_close", "price": "close"})
        df = _slice_requested_period(_standardize_price(raw, symbol), period)
        if df.empty:
            if mode == "full":
                continue
            return pd.DataFrame(), {"provider": "FMP", "status": "normalize_empty", **diag}
        if not _history_sufficient(df, period):
            if mode == "full":
                continue
            return pd.DataFrame(), {"provider": "FMP", "status": "insufficient_history", "rows": int(len(df)), "endpoint": mode, **diag}
        return df, {"provider": "FMP", "status": "ok", "rows": int(len(df)), "endpoint": mode, **diag}

    return pd.DataFrame(), {"provider": "FMP", "status": last_diag.get("status", "empty_or_unentitled"), **last_diag}

# ============================================================
# ALPHA VANTAGE — LAST LICENSED FALLBACK FOR US EQUITIES/ETFS
# ============================================================


def _fetch_alpha_daily(symbol: str, period: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    key = _get_secret("ALPHA_VANTAGE_API_KEY")
    raw_symbol = str(symbol or "").upper().strip()
    if not key:
        return pd.DataFrame(), {"provider": "Alpha Vantage", "status": "disabled"}
    if not raw_symbol or raw_symbol.startswith("^") or raw_symbol.endswith("=X") or raw_symbol.endswith("=F"):
        return pd.DataFrame(), {"provider": "Alpha Vantage", "status": "unsupported_symbol"}

    needs_full = str(period).lower() in {"2y", "5y", "10y"}
    payload, diag = _request_json(
        "https://www.alphavantage.co/query",
        params={
            "function": "TIME_SERIES_DAILY",
            "symbol": raw_symbol,
            "outputsize": "full" if needs_full else "compact",
            "apikey": key,
        },
        retries=0,
    )
    if payload is None:
        return pd.DataFrame(), {"provider": "Alpha Vantage", **diag}
    series = payload.get("Time Series (Daily)") if isinstance(payload, dict) else None
    if not isinstance(series, dict) or not series:
        info = str(payload.get("Information") or payload.get("Note") or "")[:180] if isinstance(payload, dict) else ""
        if needs_full and ("premium" in info.lower() or "full" in info.lower()):
            status = "premium_full_history_required"
        elif "frequency" in info.lower() or "rate" in info.lower() or "limit" in info.lower():
            status = "rate_limited"
        else:
            status = "empty_or_unentitled"
        return pd.DataFrame(), {"provider": "Alpha Vantage", "status": status, "detail": info, **diag}

    rows = []
    for date_str, item in series.items():
        if isinstance(item, dict):
            rows.append({"date": date_str, "open": item.get("1. open"), "high": item.get("2. high"), "low": item.get("3. low"), "close": item.get("4. close"), "volume": item.get("5. volume")})
    df = _slice_requested_period(_standardize_price(pd.DataFrame(rows), symbol), period)
    if df.empty:
        return pd.DataFrame(), {"provider": "Alpha Vantage", "status": "normalize_empty", **diag}
    if not _history_sufficient(df, period):
        return pd.DataFrame(), {"provider": "Alpha Vantage", "status": "insufficient_history", "rows": int(len(df)), **diag}
    return df, {"provider": "Alpha Vantage", "status": "ok", "rows": int(len(df)), **diag}

# ============================================================
# YFINANCE PUBLIC FALLBACK
# ============================================================


def _fetch_yfinance_daily(symbol: str, period: str, interval: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not YFINANCE_AVAILABLE:
        return pd.DataFrame(), {"provider": "yfinance", "status": "package_unavailable"}
    try:
        kwargs = dict(interval=interval, progress=False, auto_adjust=False, threads=False)
        # For long horizons explicit dates are more reliable than Yahoo's period
        # shortcut and are officially supported by yfinance.
        if str(period).lower() in {"5y", "10y"}:
            start, end = _period_to_dates(period)
            raw = yf.download(symbol, start=start, end=end, **kwargs)
        else:
            raw = yf.download(symbol, period=period, **kwargs)
        df = _slice_requested_period(_standardize_price(raw, symbol), period)
        if df.empty:
            return pd.DataFrame(), {"provider": "yfinance", "status": "empty"}
        if not _history_sufficient(df, period):
            return pd.DataFrame(), {"provider": "yfinance", "status": "insufficient_history", "rows": int(len(df))}
        return df, {"provider": "yfinance", "status": "ok", "rows": int(len(df))}
    except Exception as exc:
        return pd.DataFrame(), {"provider": "yfinance", "status": "request_error", "detail": type(exc).__name__}

# ============================================================
# PRICE WATERFALL
# ============================================================


def fetch_price_history_uncached(symbol: str, period: str = "2y", interval: str = "1d") -> pd.DataFrame:
    """Execute the real price-provider waterfall without Streamlit memoization.

    V2.5.3 exposes the network waterfall separately from the cached public helper.
    Normal terminal code should continue to call :func:`fetch_price_history`; only
    explicit resilience/retry paths (external replication) should call this function.

    The lab never fabricates prices. If every provider fails an empty frame is
    returned with sanitized attempt metadata in ``DataFrame.attrs``.
    """
    symbol = str(symbol or "SPY").upper().strip()
    attempts: list[dict[str, Any]] = []

    # Long-history research should prefer licensed EOD endpoints before the
    # public Yahoo fallback. For shorter horizons we preserve the established
    # order that has worked well in the terminal.
    if str(period).lower() in {"5y", "10y"}:
        providers = (
            lambda: _fetch_twelve_daily(symbol, period),
            lambda: _fetch_massive_daily(symbol, period),
            lambda: _fetch_fmp_daily(symbol, period),
            lambda: _fetch_yfinance_daily(symbol, period, interval),
            lambda: _fetch_alpha_daily(symbol, period),
        )
    else:
        providers = (
            lambda: _fetch_twelve_daily(symbol, period),
            lambda: _fetch_massive_daily(symbol, period),
            lambda: _fetch_yfinance_daily(symbol, period, interval),
            lambda: _fetch_fmp_daily(symbol, period),
            lambda: _fetch_alpha_daily(symbol, period),
        )

    for provider_call in providers:
        df, meta = provider_call()
        attempts.append(dict(meta or {}))
        if isinstance(df, pd.DataFrame) and not df.empty:
            provider_name = str(meta.get("provider", "Unknown"))
            return _attach_meta(df, provider_name, attempts, symbol)

    return _attach_meta(pd.DataFrame(), "Unavailable", attempts, symbol)


@st.cache_data(ttl=600, show_spinner=False)
def fetch_price_history(symbol: str, period: str = "2y", interval: str = "1d") -> pd.DataFrame:
    """Cached public price-history helper used by the normal terminal workflow.

    The actual provider waterfall lives in :func:`fetch_price_history_uncached`.
    Keeping the cache only at this wrapper level lets external replication perform
    a *true* second network attempt without clearing or poisoning the rest of the
    application's cache.
    """
    return fetch_price_history_uncached(symbol, period=period, interval=interval)


def fetch_market_pack(
    target_symbol: str,
    period: str = "2y",
    benchmarks: tuple[str, ...] = DEFAULT_BENCHMARKS,
) -> dict[str, pd.DataFrame]:
    """Fetch the target first and stop immediately if it is unavailable.

    V2.3.2 also caps benchmark history at 1Y because the psychology engine only
    uses benchmark returns for recent cross-asset dispersion/correlation. This
    prevents a 5Y/10Y Memory run from multiplying long-history provider calls
    across every benchmark before the target itself has been validated.
    """
    target = str(target_symbol or "SPY").upper().strip()
    pack: dict[str, pd.DataFrame] = {}
    target_df = fetch_price_history(target, period=period, interval="1d")
    pack[target] = target_df
    if target_df is None or target_df.empty:
        return pack

    benchmark_period = "1y" if str(period).lower() in {"2y", "5y", "10y"} else period
    for s in benchmarks:
        symbol = str(s or "").upper().strip()
        if not symbol or symbol == target or symbol in pack:
            continue
        pack[symbol] = fetch_price_history(symbol, period=benchmark_period, interval="1d")
    return pack


# ============================================================
# NEWS / OPTIONS — BEST EFFORT, NON-BLOCKING
# ============================================================


def _news_content(item: dict[str, Any]) -> dict[str, Any]:
    content = item.get("content")
    return content if isinstance(content, dict) else {}


def _news_query(symbol: str) -> str:
    """Human-search query for broad providers; provider-native ticker endpoints still use the raw symbol."""
    raw = str(symbol or "SPY").upper().strip()
    aliases = {
        "SPY": '"S&P 500" OR SPY',
        "QQQ": '"Nasdaq 100" OR QQQ',
        "IWM": '"Russell 2000" OR IWM',
        "DIA": '"Dow Jones" OR DIA',
        "TLT": '"Treasury bonds" OR TLT',
        "HYG": '"high yield bonds" OR HYG',
        "GLD": 'gold OR GLD',
        "^GSPC": '"S&P 500"',
        "^IXIC": 'Nasdaq',
        "^VIX": 'VIX OR volatility',
    }
    return aliases.get(raw, raw)


def _news_frame(rows: list[dict[str, Any]], provider: str) -> pd.DataFrame:
    cols = ["published", "source", "title", "summary", "symbol", "provider", "url", "provider_sentiment", "relevance"]
    if not rows:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(rows)
    for col in cols:
        if col not in df.columns:
            df[col] = np.nan
    df["provider"] = provider
    df["published"] = pd.to_datetime(df["published"], errors="coerce", utc=True)
    df["title"] = df["title"].fillna("").astype(str).str.strip()
    df["summary"] = df["summary"].fillna("").astype(str).str.strip()
    df["source"] = df["source"].fillna(provider).astype(str)
    df["url"] = df["url"].fillna("").astype(str)
    df["provider_sentiment"] = pd.to_numeric(df["provider_sentiment"], errors="coerce")
    df["relevance"] = pd.to_numeric(df["relevance"], errors="coerce")
    return df[df["title"].str.len() >= 5][cols].reset_index(drop=True)


def _fetch_news_yahoo(symbol: str, limit: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not YFINANCE_AVAILABLE:
        return _news_frame([], "Yahoo"), {"provider": "Yahoo", "status": "package_unavailable"}
    try:
        items = yf.Ticker(symbol).news or []
    except Exception as exc:
        return _news_frame([], "Yahoo"), {"provider": "Yahoo", "status": "request_error", "detail": type(exc).__name__}
    rows: list[dict[str, Any]] = []
    for item in items[: max(1, int(limit))]:
        if not isinstance(item, dict):
            continue
        content = _news_content(item)
        title = item.get("title") or content.get("title") or ""
        summary = item.get("summary") or content.get("summary") or content.get("description") or ""
        source: Any = item.get("publisher") or item.get("provider") or content.get("provider") or "Yahoo"
        if isinstance(source, dict):
            source = source.get("displayName") or source.get("name") or "Yahoo"
        ts = item.get("providerPublishTime") or item.get("pubDate") or content.get("pubDate") or content.get("displayTime")
        published = pd.NaT
        try:
            if isinstance(ts, (int, float)):
                published = pd.Timestamp(datetime.fromtimestamp(ts, tz=timezone.utc))
            elif ts:
                published = pd.to_datetime(ts, utc=True, errors="coerce")
        except Exception:
            pass
        url = item.get("link") or item.get("canonicalUrl") or content.get("canonicalUrl") or content.get("clickThroughUrl") or ""
        if isinstance(url, dict):
            url = url.get("url") or ""
        rows.append({
            "published": published,
            "source": str(source),
            "title": str(title),
            "summary": str(summary),
            "symbol": symbol,
            "url": str(url),
            "provider_sentiment": np.nan,
            "relevance": 0.65,
        })
    df = _news_frame(rows, "Yahoo")
    return df, {"provider": "Yahoo", "status": "ok" if not df.empty else "empty", "rows": int(len(df))}


def _fetch_news_finnhub(symbol: str, limit: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    key = _get_secret("FINNHUB_API_KEY")
    if not key:
        return _news_frame([], "Finnhub"), {"provider": "Finnhub", "status": "disabled"}
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=14)
    try:
        response = requests.get(
            "https://finnhub.io/api/v1/company-news",
            params={"symbol": symbol, "from": start.isoformat(), "to": end.isoformat(), "token": key},
            timeout=(5, 20),
        )
        http = int(response.status_code)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return _news_frame([], "Finnhub"), {"provider": "Finnhub", "status": "request_error", "detail": type(exc).__name__}
    if not isinstance(payload, list):
        return _news_frame([], "Finnhub"), {"provider": "Finnhub", "status": "bad_payload", "http": http}
    rows = []
    for item in payload[: max(1, int(limit))]:
        if not isinstance(item, dict):
            continue
        rows.append({
            "published": pd.to_datetime(item.get("datetime"), unit="s", errors="coerce", utc=True),
            "source": item.get("source") or "Finnhub",
            "title": item.get("headline") or "",
            "summary": item.get("summary") or "",
            "symbol": symbol,
            "url": item.get("url") or "",
            "provider_sentiment": np.nan,
            "relevance": 0.90,
        })
    df = _news_frame(rows, "Finnhub")
    return df, {"provider": "Finnhub", "status": "ok" if not df.empty else "empty", "rows": int(len(df)), "http": http}


def _fetch_news_fmp(symbol: str, limit: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    key = _get_secret("FMP_API_KEY", "FINANCIAL_MODELING_PREP_API_KEY")
    if not key:
        return _news_frame([], "FMP"), {"provider": "FMP", "status": "disabled"}
    try:
        response = requests.get(
            "https://financialmodelingprep.com/stable/news/stock",
            params={"symbols": symbol, "limit": min(max(int(limit), 20), 100), "apikey": key},
            timeout=(5, 20),
        )
        http = int(response.status_code)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return _news_frame([], "FMP"), {"provider": "FMP", "status": "request_error", "detail": type(exc).__name__}
    if not isinstance(payload, list):
        return _news_frame([], "FMP"), {"provider": "FMP", "status": "bad_payload", "http": http}
    rows = []
    for item in payload[: max(1, int(limit))]:
        if not isinstance(item, dict):
            continue
        rows.append({
            "published": item.get("publishedDate") or item.get("publishedAt") or item.get("date"),
            "source": item.get("publisher") or item.get("site") or item.get("source") or "FMP",
            "title": item.get("title") or "",
            "summary": item.get("text") or item.get("snippet") or item.get("description") or "",
            "symbol": symbol,
            "url": item.get("url") or "",
            "provider_sentiment": np.nan,
            "relevance": 0.90,
        })
    df = _news_frame(rows, "FMP")
    return df, {"provider": "FMP", "status": "ok" if not df.empty else "empty_or_unentitled", "rows": int(len(df)), "http": http}


def _fetch_news_alpha(symbol: str, limit: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    key = _get_secret("ALPHA_VANTAGE_API_KEY")
    if not key:
        return _news_frame([], "Alpha Vantage"), {"provider": "Alpha Vantage", "status": "disabled"}
    try:
        response = requests.get(
            "https://www.alphavantage.co/query",
            params={
                "function": "NEWS_SENTIMENT",
                "tickers": symbol,
                "sort": "LATEST",
                "limit": min(max(int(limit), 20), 200),
                "apikey": key,
            },
            timeout=(5, 25),
        )
        http = int(response.status_code)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return _news_frame([], "Alpha Vantage"), {"provider": "Alpha Vantage", "status": "request_error", "detail": type(exc).__name__}
    feed = payload.get("feed") if isinstance(payload, dict) else None
    if not isinstance(feed, list):
        status = "rate_limited_or_unentitled" if isinstance(payload, dict) and (payload.get("Note") or payload.get("Information")) else "bad_payload"
        return _news_frame([], "Alpha Vantage"), {"provider": "Alpha Vantage", "status": status, "http": http}
    rows = []
    for item in feed[: max(1, int(limit))]:
        if not isinstance(item, dict):
            continue
        sentiment = _safe_float(item.get("overall_sentiment_score"))
        relevance = None
        ticker_sent = item.get("ticker_sentiment")
        if isinstance(ticker_sent, list):
            for trow in ticker_sent:
                if isinstance(trow, dict) and str(trow.get("ticker", "")).upper() == symbol:
                    relevance = _safe_float(trow.get("relevance_score"))
                    ticker_sentiment = _safe_float(trow.get("ticker_sentiment_score"))
                    if ticker_sentiment is not None:
                        sentiment = ticker_sentiment
                    break
        published = item.get("time_published")
        if published:
            published = pd.to_datetime(str(published), format="%Y%m%dT%H%M%S", errors="coerce", utc=True)
        rows.append({
            "published": published,
            "source": item.get("source") or "Alpha Vantage",
            "title": item.get("title") or "",
            "summary": item.get("summary") or "",
            "symbol": symbol,
            "url": item.get("url") or "",
            "provider_sentiment": sentiment,
            "relevance": relevance if relevance is not None else 0.75,
        })
    df = _news_frame(rows, "Alpha Vantage")
    return df, {"provider": "Alpha Vantage", "status": "ok" if not df.empty else "empty", "rows": int(len(df)), "http": http}


def _fetch_news_newsapi(symbol: str, limit: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    key = _get_secret("NEWSAPI_KEY", "NEWS_API_KEY")
    if not key:
        return _news_frame([], "NewsAPI"), {"provider": "NewsAPI", "status": "disabled"}
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=7)
    try:
        response = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": _news_query(symbol),
                "searchIn": "title,description",
                "from": start.isoformat(),
                "to": end.isoformat(),
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": min(max(int(limit), 20), 100),
                "page": 1,
                "apiKey": key,
            },
            timeout=(5, 25),
        )
        http = int(response.status_code)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return _news_frame([], "NewsAPI"), {"provider": "NewsAPI", "status": "request_error", "detail": type(exc).__name__}
    articles = payload.get("articles") if isinstance(payload, dict) else None
    if not isinstance(articles, list):
        return _news_frame([], "NewsAPI"), {"provider": "NewsAPI", "status": "bad_payload", "http": http}
    rows = []
    for item in articles[: max(1, int(limit))]:
        if not isinstance(item, dict):
            continue
        source = item.get("source") or {}
        if isinstance(source, dict):
            source = source.get("name") or "NewsAPI"
        rows.append({
            "published": item.get("publishedAt"),
            "source": source,
            "title": item.get("title") or "",
            "summary": item.get("description") or item.get("content") or "",
            "symbol": symbol,
            "url": item.get("url") or "",
            "provider_sentiment": np.nan,
            "relevance": 0.62,
        })
    df = _news_frame(rows, "NewsAPI")
    return df, {"provider": "NewsAPI", "status": "ok" if not df.empty else "empty_or_plan_limited", "rows": int(len(df)), "http": http}


def _news_exact_key(title: str) -> str:
    text = re.sub(r"[^a-z0-9 ]", " ", str(title or "").lower())
    return re.sub(r"\s+", " ", text).strip()


def _balanced_news_sample(combined: pd.DataFrame, limit: int) -> pd.DataFrame:
    if combined.empty:
        return combined
    work = combined.copy()
    work["_title_key"] = work["title"].map(_news_exact_key)
    work = work[work["_title_key"].str.len() >= 5]
    work = work.sort_values(["published", "relevance"], ascending=[False, False], na_position="last")
    work = work.drop_duplicates("_title_key", keep="first").reset_index(drop=True)
    providers = [p for p in work["provider"].dropna().astype(str).unique().tolist() if p]
    if not providers:
        return work.head(limit).drop(columns=["_title_key"], errors="ignore")

    # Round-robin keeps one high-volume provider from monopolizing the corpus.
    pools = {p: work[work["provider"].astype(str) == p].copy().reset_index() for p in providers}
    pointers = {p: 0 for p in providers}
    selected: list[int] = []
    while len(selected) < limit:
        progressed = False
        for provider in providers:
            pool = pools[provider]
            ptr = pointers[provider]
            if ptr < len(pool):
                idx = int(pool.loc[ptr, "index"])
                pointers[provider] += 1
                if idx not in selected:
                    selected.append(idx)
                    progressed = True
                    if len(selected) >= limit:
                        break
        if not progressed:
            break
    if len(selected) < limit:
        for idx in work.index:
            if idx not in selected:
                selected.append(int(idx))
                if len(selected) >= limit:
                    break
    return work.loc[selected].sort_values("published", ascending=False, na_position="last").drop(columns=["_title_key"], errors="ignore").reset_index(drop=True)


@st.cache_data(ttl=600, show_spinner=False)
def fetch_news(symbol: str, limit: int = 40) -> pd.DataFrame:
    """
    V2.1 multi-source current news corpus.

    Enabled adapters are queried independently and failures never block the lab:
      - Finnhub company news
      - FMP search stock news
      - Alpha Vantage NEWS_SENTIMENT
      - NewsAPI Everything
      - Yahoo public news fallback

    The returned DataFrame carries sanitized provider-attempt diagnostics in attrs.
    Exact headline duplicates are removed here; semantic near-duplicates are removed
    later in narrative_nlp.py so the NLP layer can report that redundancy explicitly.
    """
    symbol = str(symbol or "SPY").upper().strip()
    limit = max(1, int(limit))
    per_provider = min(100, max(20, int(math.ceil(limit * 0.75))))
    attempts: list[dict[str, Any]] = []
    frames: list[pd.DataFrame] = []

    provider_calls = (
        lambda: _fetch_news_finnhub(symbol, per_provider),
        lambda: _fetch_news_fmp(symbol, per_provider),
        lambda: _fetch_news_alpha(symbol, per_provider),
        lambda: _fetch_news_newsapi(symbol, per_provider),
        lambda: _fetch_news_yahoo(symbol, per_provider),
    )
    for call in provider_calls:
        df, meta = call()
        attempts.append(dict(meta or {}))
        if isinstance(df, pd.DataFrame) and not df.empty:
            frames.append(df)

    if not frames:
        empty = _news_frame([], "Unavailable")
        empty.attrs["provider_attempts"] = attempts
        empty.attrs["raw_provider_rows"] = 0
        empty.attrs["requested_limit"] = limit
        return empty

    combined = pd.concat(frames, ignore_index=True, sort=False)
    raw_rows = int(len(combined))
    combined = _balanced_news_sample(combined, limit)
    combined.attrs["provider_attempts"] = attempts
    combined.attrs["raw_provider_rows"] = raw_rows
    combined.attrs["requested_limit"] = limit
    combined.attrs["provider_count"] = int(combined["provider"].nunique()) if not combined.empty else 0
    return combined


@st.cache_data(ttl=600, show_spinner=False)
def fetch_options_snapshot(symbol: str, max_expiries: int = 12) -> dict[str, Any]:
    """Best-effort current option-chain snapshot with audited tenor denominators.

    V2.2.1 loads a wider expiry universe than V2.2 and records exactly what was
    loaded. Short-tenor volume shares are suppressed when the loaded chain does
    not extend beyond 30 calendar days, preventing a three-near-expiry snapshot
    from mechanically reporting <=7D share = 100%.

    The function does *not* infer dealer direction. OI/strike concentration and
    moneyness/tenor shares are structural proxies only.
    """
    symbol = str(symbol or "SPY").upper().strip()
    empty = {
        "available": False, "expiries": [], "call_volume": None, "put_volume": None,
        "call_oi": None, "put_oi": None, "put_call_volume": None, "put_call_oi": None,
        "call_iv": None, "put_iv": None, "near_term_share": None, "rows": 0,
        "spot": None, "zero_dte_share": None, "dte_7_share": None, "dte_30_share": None,
        "otm_call_volume_share": None, "otm_put_volume_share": None, "put_call_iv_skew": None,
        "oi_top5_strike_share": None, "listed_expiry_count": 0, "loaded_expiry_count": 0,
        "max_dte_loaded": None, "tenor_denominator_complete": False,
        "tenor_denominator_status": "UNAVAILABLE", "tenor_denominator_volume": None,
    }
    if not YFINANCE_AVAILABLE:
        return empty
    try:
        ticker = yf.Ticker(symbol)
        all_expiries = list(ticker.options or [])
    except Exception:
        return empty
    if not all_expiries:
        return empty

    now_date = datetime.now(timezone.utc).date()
    expiry_meta: list[tuple[str, int]] = []
    for expiry in all_expiries:
        exp_ts = pd.to_datetime(expiry, errors="coerce")
        if pd.isna(exp_ts):
            continue
        dte = max((exp_ts.date() - now_date).days, 0)
        expiry_meta.append((expiry, dte))
    expiry_meta.sort(key=lambda x: x[1])
    if not expiry_meta:
        return empty

    # Load up to max_expiries, but guarantee inclusion of the first expiry beyond
    # 30D when one exists so <=7D shares have a non-tautological denominator.
    selected = expiry_meta[: max(1, int(max_expiries))]
    if not any(dte > 30 for _, dte in selected):
        farther = next(((e, d) for e, d in expiry_meta if d > 30), None)
        if farther is not None and farther not in selected:
            selected.append(farther)
    expiries = [e for e, _ in selected]

    spot = None
    try:
        fi = getattr(ticker, "fast_info", None)
        if fi is not None:
            for k in ("last_price", "lastPrice"):
                try:
                    spot = _safe_float(fi[k])
                except Exception:
                    pass
                if spot is not None:
                    break
    except Exception:
        spot = None
    if spot is None:
        try:
            h = ticker.history(period="5d", interval="1d", auto_adjust=False)
            if h is not None and not h.empty and "Close" in h.columns:
                spot = _safe_float(pd.to_numeric(h["Close"], errors="coerce").dropna().iloc[-1])
        except Exception:
            spot = None

    call_frames: list[pd.DataFrame] = []
    put_frames: list[pd.DataFrame] = []
    used_expiries: list[str] = []
    dte_by_expiry = dict(expiry_meta)
    for expiry in expiries:
        try:
            chain = ticker.option_chain(expiry)
            calls = chain.calls.copy() if chain.calls is not None else pd.DataFrame()
            puts = chain.puts.copy() if chain.puts is not None else pd.DataFrame()
            dte = dte_by_expiry.get(expiry, np.nan)
            if not calls.empty:
                calls["expiry"] = expiry
                calls["dte"] = dte
                calls["option_type"] = "call"
                call_frames.append(calls)
            if not puts.empty:
                puts["expiry"] = expiry
                puts["dte"] = dte
                puts["option_type"] = "put"
                put_frames.append(puts)
            if not calls.empty or not puts.empty:
                used_expiries.append(expiry)
        except Exception:
            continue

    calls = pd.concat(call_frames, ignore_index=True) if call_frames else pd.DataFrame()
    puts = pd.concat(put_frames, ignore_index=True) if put_frames else pd.DataFrame()
    if calls.empty and puts.empty:
        return {**empty, "listed_expiry_count": len(all_expiries)}

    def total(frame: pd.DataFrame, col: str) -> float | None:
        if frame.empty or col not in frame.columns:
            return None
        vals = pd.to_numeric(frame[col], errors="coerce").dropna()
        return float(vals.sum()) if not vals.empty else None

    def mean(frame: pd.DataFrame, col: str) -> float | None:
        if frame.empty or col not in frame.columns:
            return None
        vals = pd.to_numeric(frame[col], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        vals = vals[(vals >= 0) & (vals <= 10)]
        return float(vals.mean()) if not vals.empty else None

    call_volume = total(calls, "volume")
    put_volume = total(puts, "volume")
    call_oi = total(calls, "openInterest")
    put_oi = total(puts, "openInterest")

    def ratio(a: float | None, b: float | None) -> float | None:
        return a / b if a is not None and b not in {None, 0} else None

    all_opts = pd.concat([calls, puts], ignore_index=True, sort=False)
    all_opts["volume_num"] = pd.to_numeric(all_opts.get("volume", 0), errors="coerce").fillna(0.0)
    all_opts["oi_num"] = pd.to_numeric(all_opts.get("openInterest", 0), errors="coerce").fillna(0.0)
    all_volume = float(all_opts["volume_num"].sum())

    loaded_dtes = pd.to_numeric(all_opts.get("dte", pd.Series(dtype=float)), errors="coerce").dropna()
    max_dte_loaded = int(loaded_dtes.max()) if not loaded_dtes.empty else None
    tenor_denominator_complete = bool(max_dte_loaded is not None and max_dte_loaded > 30 and len(used_expiries) >= 2)
    if tenor_denominator_complete:
        tenor_status = f"AUDITED_LOADED_UNIVERSE_TO_{max_dte_loaded}D"
    elif max_dte_loaded is not None:
        tenor_status = f"TRUNCATED_AT_{max_dte_loaded}D"
    else:
        tenor_status = "UNAVAILABLE"

    near_term_share = None
    if used_expiries and all_volume > 0:
        first = used_expiries[0]
        near_term_share = float(all_opts.loc[all_opts["expiry"] == first, "volume_num"].sum() / all_volume)

    zero_dte_share = dte_7_share = dte_30_share = None
    if all_volume > 0 and "dte" in all_opts.columns and tenor_denominator_complete:
        dte_num = pd.to_numeric(all_opts["dte"], errors="coerce")
        zero_dte_share = float(all_opts.loc[dte_num <= 0, "volume_num"].sum() / all_volume)
        dte_7_share = float(all_opts.loc[dte_num <= 7, "volume_num"].sum() / all_volume)
        dte_30_share = float(all_opts.loc[dte_num <= 30, "volume_num"].sum() / all_volume)

    otm_call_volume_share = otm_put_volume_share = None
    put_call_iv_skew = None
    if spot is not None and spot > 0:
        for frame in (calls, puts):
            if not frame.empty and "strike" in frame.columns:
                frame["strike_num"] = pd.to_numeric(frame["strike"], errors="coerce")
                frame["volume_num"] = pd.to_numeric(frame.get("volume", 0), errors="coerce").fillna(0.0)
                frame["iv_num"] = pd.to_numeric(frame.get("impliedVolatility", np.nan), errors="coerce")
        cv = float(calls["volume_num"].sum()) if not calls.empty and "volume_num" in calls.columns else 0.0
        pv = float(puts["volume_num"].sum()) if not puts.empty and "volume_num" in puts.columns else 0.0
        if cv > 0:
            otm_call_volume_share = float(calls.loc[calls["strike_num"] >= spot * 1.02, "volume_num"].sum() / cv)
        if pv > 0:
            otm_put_volume_share = float(puts.loc[puts["strike_num"] <= spot * 0.98, "volume_num"].sum() / pv)
        put_band = puts[(puts["strike_num"] >= spot * 0.90) & (puts["strike_num"] <= spot * 0.99)] if not puts.empty else pd.DataFrame()
        call_band = calls[(calls["strike_num"] >= spot * 1.01) & (calls["strike_num"] <= spot * 1.10)] if not calls.empty else pd.DataFrame()
        piv = pd.to_numeric(put_band.get("iv_num", pd.Series(dtype=float)), errors="coerce").dropna()
        civ = pd.to_numeric(call_band.get("iv_num", pd.Series(dtype=float)), errors="coerce").dropna()
        if not piv.empty and not civ.empty:
            put_call_iv_skew = float(piv.median() - civ.median())

    oi_top5_strike_share = None
    if "strike" in all_opts.columns and float(all_opts["oi_num"].sum()) > 0:
        oi_by_strike = all_opts.groupby(pd.to_numeric(all_opts["strike"], errors="coerce"))["oi_num"].sum().sort_values(ascending=False)
        if not oi_by_strike.empty:
            oi_top5_strike_share = float(oi_by_strike.head(5).sum() / oi_by_strike.sum())

    return {
        "available": True,
        "expiries": used_expiries,
        "spot": spot,
        "call_volume": call_volume,
        "put_volume": put_volume,
        "call_oi": call_oi,
        "put_oi": put_oi,
        "put_call_volume": ratio(put_volume, call_volume),
        "put_call_oi": ratio(put_oi, call_oi),
        "call_iv": mean(calls, "impliedVolatility"),
        "put_iv": mean(puts, "impliedVolatility"),
        "near_term_share": near_term_share,
        "zero_dte_share": zero_dte_share,
        "dte_7_share": dte_7_share,
        "dte_30_share": dte_30_share,
        "otm_call_volume_share": otm_call_volume_share,
        "otm_put_volume_share": otm_put_volume_share,
        "put_call_iv_skew": put_call_iv_skew,
        "oi_top5_strike_share": oi_top5_strike_share,
        "rows": int(len(calls) + len(puts)),
        "listed_expiry_count": int(len(all_expiries)),
        "loaded_expiry_count": int(len(used_expiries)),
        "max_dte_loaded": max_dte_loaded,
        "tenor_denominator_complete": tenor_denominator_complete,
        "tenor_denominator_status": tenor_status,
        "tenor_denominator_volume": all_volume if all_volume > 0 else None,
    }

def latest_close(frame: pd.DataFrame) -> float | None:
    if frame is None or frame.empty or "close" not in frame.columns:
        return None
    s = pd.to_numeric(frame["close"], errors="coerce").dropna()
    return _safe_float(s.iloc[-1]) if not s.empty else None
