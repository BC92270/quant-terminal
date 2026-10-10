from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import StringIO
import json
import os
import re
from typing import Any
from urllib.parse import quote

import numpy as np
import pandas as pd
import requests

from .utils import normalize_ticker
from .institutional_cache import get_correlation_cache

try:
    import yfinance as yf
except Exception:  # pragma: no cover
    yf = None


STOOQ_DAILY_ENDPOINT = "https://stooq.com/q/d/l/"
CBOE_INDEX_HISTORY_ENDPOINT = "https://cdn.cboe.com/api/global/us_indices/daily_prices/{symbol}_History.csv"
CBOE_IMPLIED_CORRELATION_TERM_SYMBOLS: dict[int, str] = {
    21: "COR1M",
    63: "COR3M",
    126: "COR6M",
    189: "COR9M",
    252: "COR1Y",
}
CBOE_IMPLIED_CORRELATION_SKEW_SYMBOLS: dict[str, str] = {
    "Call OTM": "COR10D",
    "Call 30Δ": "COR30D",
    "Put 70Δ": "COR70D",
    "Put OTM": "COR90D",
    "ATM": "COR3M",
}
CBOE_IMPLIED_CORRELATION_SYMBOLS: tuple[str, ...] = tuple(
    dict.fromkeys(
        ["COR3M"]
        + list(CBOE_IMPLIED_CORRELATION_TERM_SYMBOLS.values())
        + list(CBOE_IMPLIED_CORRELATION_SKEW_SYMBOLS.values())
    )
)


@dataclass(frozen=True)
class AdapterReadiness:
    capability: str
    adapter: str
    access: str
    state: str
    authority: str
    detail: str
    source_url: str


def _period_start(period: str, end: date | None = None) -> date:
    end = end or date.today()
    value = str(period or "2y").lower().strip()
    days = {
        "1mo": 45,
        "3mo": 120,
        "6mo": 240,
        "1y": 420,
        "2y": 800,
        "5y": 1900,
        "10y": 3800,
        "max": 9000,
    }.get(value, 800)
    return end - timedelta(days=days)


def _stooq_symbol(ticker: str) -> str | None:
    """Return a conservative Stooq code for ordinary US stocks and ETFs."""

    symbol = normalize_ticker(ticker)
    if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,11}", symbol):
        return None
    if symbol.startswith("^") or symbol.endswith("=X") or symbol.endswith("-USD"):
        return None
    return f"{symbol.lower()}.us"


def download_stooq_daily(
    tickers: list[str],
    period: str = "2y",
    *,
    timeout_seconds: float = 7.0,
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Download research-grade daily closes from Stooq without credentials.

    This is deliberately a coverage fallback, not a point-in-time corporate-action
    archive. Unsupported symbols are ignored and every returned series is labelled
    ``FREE_RESEARCH_NOT_POINT_IN_TIME`` by the caller.
    """

    end = date.today()
    start = _period_start(period, end)
    frames: list[pd.Series] = []
    providers: dict[str, str] = {}
    candidates: list[tuple[str, str]] = []
    for raw_ticker in list(dict.fromkeys(tickers)):
        ticker = normalize_ticker(raw_ticker)
        vendor_symbol = _stooq_symbol(ticker)
        if vendor_symbol is None:
            continue
        candidates.append((ticker, vendor_symbol))

    def fetch(candidate: tuple[str, str]) -> tuple[str, pd.Series | None]:
        ticker, vendor_symbol = candidate
        params = {
            "s": vendor_symbol,
            "d1": start.strftime("%Y%m%d"),
            "d2": end.strftime("%Y%m%d"),
            "i": "d",
        }
        try:
            response = requests.get(
                STOOQ_DAILY_ENDPOINT,
                params=params,
                timeout=timeout_seconds,
                headers={"User-Agent": "QuantTerminal-Research/5.0 (+https://github.com/BC92270/quant-terminal)"},
            )
            response.raise_for_status()
            if "No data" in response.text or len(response.text) < 30:
                return ticker, None
            raw = pd.read_csv(StringIO(response.text))
            lower = {str(c).lower(): c for c in raw.columns}
            if "date" not in lower or "close" not in lower:
                return ticker, None
            index = pd.to_datetime(raw[lower["date"]], errors="coerce")
            close = pd.to_numeric(raw[lower["close"]], errors="coerce")
            series = pd.Series(close.to_numpy(), index=index, name=ticker).dropna().sort_index()
            series = series[~series.index.duplicated(keep="last")]
            if len(series) < 20:
                return ticker, None
            return ticker, series
        except Exception:
            return ticker, None

    with ThreadPoolExecutor(max_workers=min(8, max(1, len(candidates)))) as executor:
        futures = [executor.submit(fetch, candidate) for candidate in candidates]
        for future in as_completed(futures):
            ticker, series = future.result()
            if series is not None:
                frames.append(series)
                providers[ticker] = "Stooq public CSV fallback"
    if not frames:
        return pd.DataFrame(), {}
    frame = pd.concat(frames, axis=1).sort_index()
    frame.index = pd.to_datetime(frame.index, errors="coerce").tz_localize(None)
    return frame, providers


def download_cboe_index_history(
    symbols: list[str] | tuple[str, ...],
    *,
    timeout_seconds: float = 7.0,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load public Cboe index history CSVs through a strict schema adapter.

    The function does not guess available symbols. Callers must supply explicitly
    governed Cboe index mnemonics, for example a correlation-index symbol verified
    against the current Cboe product directory. Failed or changed schemas are
    returned fail-closed rather than silently reinterpreted.
    """

    governed_symbols = list(dict.fromkeys(str(x).upper().strip() for x in symbols if str(x).strip()))
    cache = get_correlation_cache()
    cache_key = json.dumps(
        {
            "symbols": governed_symbols,
            "as_of_date": pd.Timestamp.now(tz="UTC").date().isoformat(),
            "schema": "cboe-public-index-history-v1",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    cached_frame = cache.get_frame("cboe_index_history", cache_key)
    cached_meta = cache.get_object("cboe_index_history_meta", cache_key)
    if cached_frame.hit and isinstance(cached_frame.value, pd.DataFrame):
        metadata = cached_meta.value if cached_meta.hit and isinstance(cached_meta.value, dict) else {}
        return cached_frame.value, {
            **metadata,
            "cache_hit": True,
            "cache_backend": cached_frame.backend,
            "cache_age_seconds": cached_frame.age_seconds,
        }

    histories_by_symbol: dict[str, pd.Series] = {}
    failures: dict[str, str] = {
        raw_symbol: "invalid_symbol"
        for raw_symbol in governed_symbols
        if not re.fullmatch(r"[A-Z0-9]{2,16}", raw_symbol)
    }
    range_warnings: dict[str, int] = {}
    valid_symbols = [
        raw_symbol
        for raw_symbol in governed_symbols
        if re.fullmatch(r"[A-Z0-9]{2,16}", raw_symbol)
    ]

    def fetch(raw_symbol: str) -> tuple[str, pd.Series | None, str | None, int]:
        url = CBOE_INDEX_HISTORY_ENDPOINT.format(symbol=quote(raw_symbol, safe=""))
        try:
            response = requests.get(
                url,
                timeout=timeout_seconds,
                headers={"User-Agent": "QuantTerminal-Research/5.0"},
            )
            response.raise_for_status()
            frame = pd.read_csv(StringIO(response.text))
            lower = {str(c).strip().lower(): c for c in frame.columns}
            date_col = lower.get("date")
            close_col = lower.get("close") or lower.get("value")
            if date_col is None or close_col is None:
                return raw_symbol, None, "schema_mismatch", 0
            values = pd.to_numeric(frame[close_col], errors="coerce")
            # Cboe correlation index levels are commonly published on a 0-100 scale.
            if values.dropna().median() > 1.5:
                values = values / 100.0
            series = pd.Series(
                values.to_numpy(),
                index=pd.to_datetime(frame[date_col], errors="coerce"),
                name=raw_symbol,
            ).dropna().sort_index()
            # Published skew indices can temporarily exceed the theoretical
            # [-1, 1] correlation interval. Preserve the official observation,
            # disclose it, and reject only clearly broken scales.
            if len(series) < 20 or not series.between(-2.5, 2.5).all():
                return raw_symbol, None, "invalid_range_or_depth", 0
            outside_unit = int((~series.between(-1.0, 1.0)).sum())
            return raw_symbol, series, None, outside_unit
        except Exception as exc:
            return raw_symbol, None, type(exc).__name__, 0

    # Each public index is an independent CSV. Parallel loading keeps the
    # readiness action bounded by the slowest endpoint instead of the sum of
    # every timeout, while deterministic assembly below preserves input order.
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(valid_symbols)))) as executor:
        futures = [executor.submit(fetch, raw_symbol) for raw_symbol in valid_symbols]
        for future in as_completed(futures):
            raw_symbol, series, failure, outside_unit = future.result()
            if failure is not None or series is None:
                failures[raw_symbol] = failure or "unavailable"
                continue
            histories_by_symbol[raw_symbol] = series
            if outside_unit:
                range_warnings[raw_symbol] = outside_unit

    accepted = [symbol for symbol in valid_symbols if symbol in histories_by_symbol]
    histories = [histories_by_symbol[symbol] for symbol in accepted]
    result = pd.concat(histories, axis=1).sort_index() if histories else pd.DataFrame()
    metadata = {
        "status": "ok" if accepted else "unavailable",
        "source": "Cboe public index history",
        "source_url_template": CBOE_INDEX_HISTORY_ENDPOINT,
        "accepted_symbols": accepted,
        "failures": failures,
        "outside_unit_interval_observations": range_warnings,
        "authority": "PUBLIC_DELAYED_RESEARCH_ONLY",
        "cache_hit": False,
        "universe_scope": "Cboe published index methodology; not the active terminal universe",
    }
    if not result.empty:
        cache.put_frame(
            "cboe_index_history",
            cache_key,
            result,
            metadata={"authority": "PUBLIC_DELAYED_RESEARCH_ONLY"},
        )
        cache.put_object(
            "cboe_index_history_meta",
            cache_key,
            metadata,
            metadata={"authority": "PUBLIC_DELAYED_RESEARCH_ONLY"},
        )
    return result, metadata


def download_yfinance_intraday_returns(
    tickers: list[str],
    *,
    period: str = "5d",
    interval: str = "5m",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Recent no-key intraday research snapshot for the HY adapter.

    Yahoo's public interface is not an institutional point-in-time source. The
    returned sparse frame preserves missing bars and never forward-fills prices.
    """

    governed = list(dict.fromkeys(normalize_ticker(t) for t in tickers if str(t).strip()))[:8]
    if yf is None or len(governed) < 2:
        return pd.DataFrame(), {"status": "unavailable", "reason": "yfinance_missing_or_too_few_assets"}
    try:
        raw = yf.download(
            tickers=governed,
            period=str(period),
            interval=str(interval),
            progress=False,
            auto_adjust=True,
            threads=True,
            group_by="column",
        )
    except Exception as exc:
        return pd.DataFrame(), {"status": "unavailable", "reason": type(exc).__name__}
    if raw is None or raw.empty:
        return pd.DataFrame(), {"status": "unavailable", "reason": "empty_provider_response"}
    prices = pd.DataFrame(index=pd.to_datetime(raw.index, errors="coerce", utc=True))
    for ticker in governed:
        series = None
        if isinstance(raw.columns, pd.MultiIndex):
            for field in ("Close", "Adj Close"):
                try:
                    if (field, ticker) in raw.columns:
                        series = raw[(field, ticker)]
                        break
                    if field in raw.columns.get_level_values(0) and ticker in raw[field].columns:
                        series = raw[field][ticker]
                        break
                except Exception:
                    continue
        elif len(governed) == 1:
            for field in ("Close", "Adj Close"):
                if field in raw.columns:
                    series = raw[field]
                    break
        if series is not None:
            prices[ticker] = pd.to_numeric(series, errors="coerce").to_numpy()
    prices = prices[~prices.index.isna()].sort_index()
    prices = prices[~prices.index.duplicated(keep="last")]
    eligible = [c for c in prices.columns if int(prices[c].notna().sum()) >= 30]
    prices = prices[eligible]
    if prices.shape[1] < 2:
        return pd.DataFrame(), {"status": "insufficient_data", "eligible_assets": eligible}
    returns = pd.DataFrame(index=prices.index)
    for column in prices.columns:
        values = pd.to_numeric(prices[column], errors="coerce")
        returns[column] = np.log(values.where(values > 0) / values.shift(1).where(values.shift(1) > 0))
    returns = returns.replace([np.inf, -np.inf], np.nan).dropna(how="all")
    return returns, {
        "status": "ok",
        "source": "yfinance recent intraday compatibility snapshot",
        "authority": "FREE_RESEARCH_NOT_POINT_IN_TIME",
        "period": str(period),
        "interval": str(interval),
        "assets": list(returns.columns),
        "rows": int(len(returns)),
        "first_timestamp": returns.index.min().isoformat() if len(returns) else None,
        "last_timestamp": returns.index.max().isoformat() if len(returns) else None,
        "no_forward_fill": True,
    }


def validate_point_in_time_contract(
    frame: pd.DataFrame,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    """Fail-closed validation for externally injected point-in-time observations."""

    metadata = metadata or {}
    required = {"provider", "as_of", "available_at", "revision_policy", "license_scope"}
    missing = sorted(required.difference(metadata))
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return {"status": "failed", "authoritative": False, "reason": "empty_frame", "missing_fields": missing}
    if missing:
        return {"status": "failed", "authoritative": False, "reason": "contract_incomplete", "missing_fields": missing}
    textual = ["provider", "revision_policy", "license_scope"]
    empty_text = [field for field in textual if not str(metadata.get(field, "")).strip()]
    if empty_text:
        return {
            "status": "failed",
            "authoritative": False,
            "reason": "contract_empty_fields",
            "empty_fields": empty_text,
            "missing_fields": [],
        }
    try:
        as_of = pd.Timestamp(metadata["as_of"])
        available_at = pd.Timestamp(metadata["available_at"])
        if as_of.tzinfo is None:
            as_of = as_of.tz_localize("UTC")
        else:
            as_of = as_of.tz_convert("UTC")
        if available_at.tzinfo is None:
            available_at = available_at.tz_localize("UTC")
        else:
            available_at = available_at.tz_convert("UTC")
    except Exception:
        return {"status": "failed", "authoritative": False, "reason": "invalid_timestamps", "missing_fields": []}
    if available_at < as_of:
        return {"status": "failed", "authoritative": False, "reason": "available_before_observation", "missing_fields": []}
    try:
        temporal_index = pd.to_datetime(frame.index, errors="coerce", utc=True)
        if temporal_index.isna().any():
            raise ValueError("non-temporal index")
        max_observation = temporal_index.max()
    except Exception:
        return {
            "status": "failed",
            "authoritative": False,
            "reason": "invalid_observation_index",
            "missing_fields": [],
        }
    if max_observation > as_of:
        return {
            "status": "failed",
            "authoritative": False,
            "reason": "observation_after_as_of",
            "max_observation": max_observation.isoformat(),
            "as_of": as_of.isoformat(),
            "missing_fields": [],
        }
    return {
        "status": "ok",
        "authoritative": True,
        "provider": str(metadata["provider"]),
        "as_of": as_of.isoformat(),
        "available_at": available_at.isoformat(),
        "revision_policy": str(metadata["revision_policy"]),
        "license_scope": str(metadata["license_scope"]),
        "max_observation": max_observation.isoformat(),
        "rows": int(frame.shape[0]),
        "columns": int(frame.shape[1]),
    }


def adapter_readiness() -> list[AdapterReadiness]:
    """Describe real connector readiness without synthetic provider-health claims."""

    return [
        AdapterReadiness(
            "Daily market history",
            "App central layer / injected PIT contract",
            "Configured by host application",
            "ready",
            "POINT_IN_TIME only when contract passes",
            "Primary path with explicit provider, as_of, available_at, revisions and license scope.",
            "https://github.com/BC92270/quant-terminal",
        ),
        AdapterReadiness(
            "Free daily fallback",
            "Yahoo Finance + Stooq public CSV",
            "No API key",
            "ready",
            "FREE_RESEARCH_NOT_POINT_IN_TIME",
            "Cached Arrow snapshots; no institutional SLA or survivorship/corporate-action guarantee.",
            STOOQ_DAILY_ENDPOINT,
        ),
        AdapterReadiness(
            "Vendor market data",
            "Databento / ThetaData / Twelve Data router",
            "Credentials required",
            "adapter",
            "Depends on vendor entitlement",
            "Credential-aware injection contract is ready; no credential is embedded in the app.",
            "https://databento.com/docs",
        ),
        AdapterReadiness(
            "Implied correlation",
            "Cboe public index history + option-surface injection",
            "Public index history; live surfaces licensed",
            "limited",
            "PUBLIC_DELAYED_RESEARCH_ONLY",
            "Public index history can be ingested; universe-specific constituent surfaces remain adapter-driven.",
            "https://www.cboe.com/us/indices/market_statistics/historical_data/",
        ),
        AdapterReadiness(
            "Intraday asynchronous data",
            "Injected trades/bars + recent yfinance research snapshot",
            "Recent snapshot without key; full archive requires vendor",
            "limited",
            "RESEARCH_ONLY",
            "HY/Epps/lead-lag engine accepts timestamped asynchronous returns and fails closed on daily data.",
            "https://ranaroussi.github.io/yfinance/",
        ),
        AdapterReadiness(
            "Distributed cache",
            "DuckDB + Arrow + optional Redis",
            "Local cache free; Redis URL optional",
            "ready" if not os.getenv("CORRELATION_REDIS_URL") else "limited",
            "LOCAL_COMPUTE_CACHE",
            "DuckDB catalog and Arrow artifacts are local; Redis activates only through CORRELATION_REDIS_URL.",
            "https://duckdb.org/docs/stable/clients/python/overview",
        ),
    ]
