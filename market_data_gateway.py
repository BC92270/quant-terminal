"""Provider-aware historical OHLCV gateway for routed terminal workspaces.

Configured providers are attempted first.  Keyless official reference APIs are
used for the asset classes they actually cover, and Yahoo remains the final
best-effort fallback.  Every successful frame carries a non-sensitive
``data_context`` attribute so analytics can display provenance and recency.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
import re
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd
import requests

from provider_config import resolve_secret


TWELVE_DATA_ROOT = "https://api.twelvedata.com"
ALPHA_VANTAGE_ROOT = "https://www.alphavantage.co/query"
COINGECKO_ROOT = "https://api.coingecko.com/api/v3"
COINGECKO_PRO_ROOT = "https://pro-api.coingecko.com/api/v3"
FRANKFURTER_ROOT = "https://api.frankfurter.dev/v2"


class MarketDataProviderError(RuntimeError):
    """Sanitized provider failure safe to expose in fallback diagnostics."""


@dataclass(frozen=True)
class HistoryContext:
    provider: str
    status: str
    recency: str
    rows: int
    fallback_used: bool = False
    message: str = ""
    attempted: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["attempted"] = list(self.attempted)
        return value


CRYPTO_IDS: dict[str, str] = {
    "AAVE": "aave",
    "ADA": "cardano",
    "AVAX": "avalanche-2",
    "BNB": "binancecoin",
    "BTC": "bitcoin",
    "DOGE": "dogecoin",
    "DOT": "polkadot",
    "ETH": "ethereum",
    "LINK": "chainlink",
    "LTC": "litecoin",
    "MATIC": "matic-network",
    "SOL": "solana",
    "UNI": "uniswap",
    "XRP": "ripple",
}

_FX_PATTERN = re.compile(r"^([A-Z]{3})([A-Z]{3})=X$")
_CRYPTO_PATTERN = re.compile(r"^([A-Z0-9]{2,12})-([A-Z]{3,5})$")


def _http_get(
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = 15.0,
    request_get: Callable[..., Any] | None = None,
) -> Any:
    getter = request_get or requests.get
    response = getter(url, params=dict(params or {}), headers=dict(headers or {}), timeout=timeout)
    response.raise_for_status()
    return response


def _normalize_history(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    data = frame.copy()
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = [str(column[0]).strip().lower() for column in data.columns]
    else:
        data.columns = [str(column).strip().lower().replace(" ", "_") for column in data.columns]
    aliases = {"datetime": "date", "timestamp": "date", "adj_close": "adj_close"}
    data = data.rename(columns={key: value for key, value in aliases.items() if key in data.columns})
    if "date" not in data.columns:
        data = data.reset_index()
        data.columns = [str(column).strip().lower().replace(" ", "_") for column in data.columns]
        data = data.rename(columns={"datetime": "date", "timestamp": "date", "index": "date"})
    if "date" not in data.columns or "close" not in data.columns:
        return pd.DataFrame()
    data["date"] = pd.to_datetime(data["date"], errors="coerce", utc=True).dt.tz_convert(None)
    for column in ("open", "high", "low", "close", "adj_close", "volume"):
        if column not in data.columns:
            data[column] = np.nan
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data["adj_close"] = data["adj_close"].where(data["adj_close"].notna(), data["close"])
    for column in ("open", "high", "low"):
        data[column] = data[column].where(data[column].notna(), data["close"])
    return (
        data[["date", "open", "high", "low", "close", "adj_close", "volume"]]
        .dropna(subset=["date", "close"])
        .sort_values("date")
        .drop_duplicates("date", keep="last")
        .reset_index(drop=True)
    )


def _period_days(period: str) -> int:
    return {
        "1mo": 35,
        "3mo": 100,
        "6mo": 190,
        "1y": 370,
        "2y": 740,
        "5y": 1_840,
        "10y": 3_675,
        "max": 7_500,
    }.get(str(period).lower(), 370)


def _period_output_size(period: str, interval: str) -> int:
    days = _period_days(period)
    if interval == "1wk":
        return min(5_000, max(40, days // 7 + 10))
    if interval == "1mo":
        return min(5_000, max(24, days // 30 + 6))
    return min(5_000, max(120, int(days * 0.78) + 20))


def _asset_kind(symbol: str) -> str:
    value = str(symbol).upper().strip()
    if _FX_PATTERN.match(value):
        return "fx"
    if _CRYPTO_PATTERN.match(value):
        return "crypto"
    return "market"


def _vendor_symbol(symbol: str) -> str:
    value = str(symbol).upper().strip()
    fx = _FX_PATTERN.match(value)
    if fx:
        return f"{fx.group(1)}/{fx.group(2)}"
    crypto = _CRYPTO_PATTERN.match(value)
    if crypto:
        return f"{crypto.group(1)}/{crypto.group(2)}"
    return value


def fetch_twelve_data_history(
    symbol: str,
    period: str,
    interval: str,
    api_key: str,
    *,
    request_get: Callable[..., Any] | None = None,
) -> tuple[pd.DataFrame, HistoryContext]:
    if not api_key:
        raise MarketDataProviderError("Twelve Data key is not configured.")
    interval_name = {"1d": "1day", "1wk": "1week", "1mo": "1month"}.get(interval, interval)
    try:
        response = _http_get(
            f"{TWELVE_DATA_ROOT}/time_series",
            params={
                "symbol": _vendor_symbol(symbol),
                "interval": interval_name,
                "outputsize": _period_output_size(period, interval),
                "order": "ASC",
                "timezone": "UTC",
                "apikey": api_key,
            },
            request_get=request_get,
        )
        payload = response.json()
    except Exception as exc:
        raise MarketDataProviderError(f"Twelve Data unavailable: {type(exc).__name__}.") from None
    if not isinstance(payload, dict) or payload.get("status") == "error":
        raise MarketDataProviderError("Twelve Data rejected the request or entitlement.")
    values = payload.get("values")
    if not isinstance(values, list):
        raise MarketDataProviderError("Twelve Data returned no time series.")
    frame = _normalize_history(pd.DataFrame(values).rename(columns={"datetime": "date"}))
    if frame.empty:
        raise MarketDataProviderError("Twelve Data returned an empty time series.")
    return frame, HistoryContext("Twelve Data", "ok", "PROVIDER DEPENDENT", len(frame), message="Configured time-series provider.")


def fetch_alpha_vantage_history(
    symbol: str,
    period: str,
    interval: str,
    api_key: str,
    *,
    request_get: Callable[..., Any] | None = None,
) -> tuple[pd.DataFrame, HistoryContext]:
    if not api_key:
        raise MarketDataProviderError("Alpha Vantage key is not configured.")
    kind = _asset_kind(symbol)
    value = str(symbol).upper().strip()
    params: dict[str, Any] = {"apikey": api_key, "datatype": "json"}
    if kind == "fx":
        match = _FX_PATTERN.match(value)
        assert match is not None
        params.update({"function": "FX_DAILY", "from_symbol": match.group(1), "to_symbol": match.group(2), "outputsize": "full"})
        series_hint = "Time Series FX"
    elif kind == "crypto":
        match = _CRYPTO_PATTERN.match(value)
        assert match is not None
        params.update({"function": "DIGITAL_CURRENCY_DAILY", "symbol": match.group(1), "market": match.group(2)})
        series_hint = "Time Series (Digital Currency Daily)"
    else:
        function = {"1wk": "TIME_SERIES_WEEKLY", "1mo": "TIME_SERIES_MONTHLY"}.get(interval, "TIME_SERIES_DAILY")
        params.update({"function": function, "symbol": value})
        if function == "TIME_SERIES_DAILY":
            params["outputsize"] = "full" if _period_days(period) > 190 else "compact"
        series_hint = "Time Series"
    try:
        response = _http_get(ALPHA_VANTAGE_ROOT, params=params, request_get=request_get)
        payload = response.json()
    except Exception as exc:
        raise MarketDataProviderError(f"Alpha Vantage unavailable: {type(exc).__name__}.") from None
    if not isinstance(payload, dict) or any(key in payload for key in ("Error Message", "Information", "Note")):
        raise MarketDataProviderError("Alpha Vantage rejected the request, quota or entitlement.")
    series = next((value for key, value in payload.items() if series_hint in str(key) and isinstance(value, dict)), None)
    if not isinstance(series, dict):
        raise MarketDataProviderError("Alpha Vantage returned no compatible time series.")
    rows: list[dict[str, Any]] = []
    for stamp, values in series.items():
        if not isinstance(values, dict):
            continue
        normalized = {str(key).split(". ", 1)[-1].lower(): value for key, value in values.items()}
        def field(name: str) -> Any:
            exact = normalized.get(name)
            if exact is not None:
                return exact
            return next((item for key, item in normalized.items() if key.startswith(name + " ") or key.endswith(" " + name)), np.nan)
        rows.append({"date": stamp, "open": field("open"), "high": field("high"), "low": field("low"), "close": field("close"), "volume": field("volume")})
    frame = _normalize_history(pd.DataFrame(rows))
    if frame.empty:
        raise MarketDataProviderError("Alpha Vantage returned an empty time series.")
    cutoff = pd.Timestamp(date.today() - timedelta(days=_period_days(period)))
    frame = frame.loc[frame["date"] >= cutoff].reset_index(drop=True)
    return frame, HistoryContext("Alpha Vantage", "ok", "PROVIDER DEPENDENT", len(frame), message="Configured historical time-series provider.")


def _resample_reference(frame: pd.DataFrame, interval: str) -> pd.DataFrame:
    if interval not in {"1wk", "1mo"} or frame.empty:
        return frame
    rule = "W-FRI" if interval == "1wk" else "ME"
    indexed = frame.set_index("date")
    output = indexed.resample(rule).agg({"open": "first", "high": "max", "low": "min", "close": "last", "adj_close": "last", "volume": "sum"})
    return output.dropna(subset=["close"]).reset_index()


def fetch_frankfurter_history(
    symbol: str,
    period: str,
    interval: str,
    *,
    request_get: Callable[..., Any] | None = None,
) -> tuple[pd.DataFrame, HistoryContext]:
    match = _FX_PATTERN.match(str(symbol).upper().strip())
    if not match:
        raise MarketDataProviderError("Frankfurter only supports ISO currency pairs.")
    base, quote = match.groups()
    start = date.today() - timedelta(days=_period_days(period))
    try:
        response = _http_get(
            f"{FRANKFURTER_ROOT}/rates",
            params={"from": start.isoformat(), "base": base, "quotes": quote},
            request_get=request_get,
        )
        payload = response.json()
    except Exception as exc:
        raise MarketDataProviderError(f"Frankfurter unavailable: {type(exc).__name__}.") from None
    rows: list[dict[str, Any]] = []
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            rate = item.get("rate")
            if str(item.get("quote", quote)).upper() == quote:
                rows.append({"date": item.get("date"), "close": rate})
    elif isinstance(payload, dict) and isinstance(payload.get("rates"), dict):
        for stamp, values in payload["rates"].items():
            rate = values.get(quote) if isinstance(values, dict) else values
            rows.append({"date": stamp, "close": rate})
    frame = _normalize_history(pd.DataFrame(rows))
    frame = _resample_reference(frame, interval)
    if frame.empty:
        raise MarketDataProviderError("Frankfurter returned an empty FX reference series.")
    return frame, HistoryContext(
        "Frankfurter v2",
        "reference",
        "DAILY CENTRAL-BANK REFERENCE",
        len(frame),
        message="Reference FX rates; OHLC is synthesized from daily reference closes and is not executable pricing.",
    )


def fetch_coingecko_history(
    symbol: str,
    period: str,
    interval: str,
    *,
    demo_key: str = "",
    pro_key: str = "",
    request_get: Callable[..., Any] | None = None,
) -> tuple[pd.DataFrame, HistoryContext]:
    match = _CRYPTO_PATTERN.match(str(symbol).upper().strip())
    if not match or match.group(1) not in CRYPTO_IDS:
        raise MarketDataProviderError("CoinGecko mapping is unavailable for this route symbol.")
    asset, quote = match.groups()
    root = COINGECKO_PRO_ROOT if pro_key else COINGECKO_ROOT
    headers: dict[str, str] = {}
    if pro_key:
        headers["x-cg-pro-api-key"] = pro_key
    elif demo_key:
        headers["x-cg-demo-api-key"] = demo_key
    try:
        response = _http_get(
            f"{root}/coins/{CRYPTO_IDS[asset]}/market_chart",
            params={"vs_currency": quote.lower(), "days": min(_period_days(period), 3650), "interval": "daily"},
            headers=headers,
            request_get=request_get,
        )
        payload = response.json()
    except Exception as exc:
        raise MarketDataProviderError(f"CoinGecko unavailable: {type(exc).__name__}.") from None
    prices = payload.get("prices") if isinstance(payload, dict) else None
    volumes = payload.get("total_volumes") if isinstance(payload, dict) else None
    if not isinstance(prices, list):
        raise MarketDataProviderError("CoinGecko returned no market history.")
    volume_map = {int(item[0]): item[1] for item in volumes or [] if isinstance(item, list) and len(item) >= 2}
    rows = [
        {"date": pd.to_datetime(item[0], unit="ms", utc=True), "close": item[1], "volume": volume_map.get(int(item[0]), np.nan)}
        for item in prices
        if isinstance(item, list) and len(item) >= 2
    ]
    frame = _resample_reference(_normalize_history(pd.DataFrame(rows)), interval)
    if frame.empty:
        raise MarketDataProviderError("CoinGecko returned an empty market history.")
    return frame, HistoryContext(
        "CoinGecko",
        "reference",
        "DAILY AGGREGATE",
        len(frame),
        message="Aggregated crypto reference prices; OHLC is synthesized from daily closes.",
    )


def fetch_yahoo_history(
    symbol: str,
    period: str,
    interval: str,
    *,
    download_func: Callable[..., Any] | None = None,
) -> tuple[pd.DataFrame, HistoryContext]:
    if download_func is None:
        import yfinance as yf  # type: ignore
        download_func = yf.download
    try:
        raw = download_func(symbol, period=period, interval=interval, progress=False, auto_adjust=False)
    except Exception as exc:
        raise MarketDataProviderError(f"Yahoo unavailable: {type(exc).__name__}.") from None
    frame = _normalize_history(raw)
    if frame.empty:
        raise MarketDataProviderError("Yahoo returned an empty time series.")
    return frame, HistoryContext(
        "Yahoo Finance",
        "fallback",
        "UNSPECIFIED / DELAYED",
        len(frame),
        message="Public best-effort fallback; exchange entitlement and recency are not guaranteed.",
    )


def fetch_price_history(
    symbol: str,
    period: str = "1y",
    interval: str = "1d",
    *,
    secrets: Mapping[str, Any] | None = None,
    request_get: Callable[..., Any] | None = None,
    yahoo_download: Callable[..., Any] | None = None,
) -> tuple[pd.DataFrame, HistoryContext]:
    """Resolve a historical series without hiding provider fallbacks."""

    symbol = str(symbol).upper().strip()
    attempted: list[str] = []
    failures: list[str] = []
    twelve_key = resolve_secret("TWELVE_DATA_API_KEY", secrets)
    alpha_key = resolve_secret("ALPHA_VANTAGE_API_KEY", secrets)
    kind = _asset_kind(symbol)

    candidates: list[tuple[str, Callable[[], tuple[pd.DataFrame, HistoryContext]]]] = []
    if twelve_key:
        candidates.append(("Twelve Data", lambda: fetch_twelve_data_history(symbol, period, interval, twelve_key, request_get=request_get)))
    if alpha_key:
        candidates.append(("Alpha Vantage", lambda: fetch_alpha_vantage_history(symbol, period, interval, alpha_key, request_get=request_get)))
    if kind == "fx":
        candidates.append(("Frankfurter v2", lambda: fetch_frankfurter_history(symbol, period, interval, request_get=request_get)))
    if kind == "crypto":
        candidates.append(("CoinGecko", lambda: fetch_coingecko_history(
            symbol,
            period,
            interval,
            demo_key=resolve_secret("COINGECKO_DEMO_API_KEY", secrets),
            pro_key=resolve_secret("COINGECKO_API_KEY", secrets),
            request_get=request_get,
        )))
    candidates.append(("Yahoo Finance", lambda: fetch_yahoo_history(symbol, period, interval, download_func=yahoo_download)))

    for provider, loader in candidates:
        attempted.append(provider)
        try:
            frame, context = loader()
        except MarketDataProviderError as exc:
            failures.append(str(exc))
            continue
        fallback = len(attempted) > 1 or context.status in {"fallback", "reference"}
        message = context.message
        if failures:
            message = f"{message} Prior providers unavailable: {' '.join(dict.fromkeys(failures))}".strip()
        context = HistoryContext(
            provider=context.provider,
            status=context.status,
            recency=context.recency,
            rows=len(frame),
            fallback_used=fallback,
            message=message,
            attempted=tuple(attempted),
        )
        frame.attrs["data_context"] = context.to_dict()
        return frame, context
    raise MarketDataProviderError("No historical market-data provider returned a usable series.")
