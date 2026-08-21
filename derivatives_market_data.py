"""Secure market-data adapters for the derivatives workspace.

The public functions in this module do not depend on Streamlit.  They return
plain data frames and metadata so the UI can display provenance, entitlement,
freshness and quality without leaking credentials or confusing delayed data
with a real-time feed.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from provider_config import resolve_secret


MASSIVE_API_ROOT = "https://api.massive.com"
MASSIVE_SECRET_NAMES: Tuple[str, ...] = (
    "MASSIVE_API_KEY",
    "MASSIVEAPI_KEY",
    "POLYGON_API_KEY",
)
THETADATA_SECRET_NAMES: Tuple[str, ...] = (
    "THETADATA_API_KEY",
    "THETA_DATA_API_KEY",
    "THETA_API_KEY",
)
TRADIER_API_ROOT = "https://api.tradier.com"
TRADIER_SANDBOX_ROOT = "https://sandbox.tradier.com"
TRADIER_SECRET_NAMES: Tuple[str, ...] = (
    "TRADIER_API_TOKEN",
    "TRADIER_ACCESS_TOKEN",
)
TRADIER_ENVIRONMENT_NAMES: Tuple[str, ...] = (
    "TRADIER_ENV",
    "TRADIER_ENVIRONMENT",
)


class ThetaDataAPIError(RuntimeError):
    """Sanitized ThetaData failure safe to show in the UI."""

    def __init__(self, message: str, category: str = "request"):
        super().__init__(message)
        self.category = category


class MassiveAPIError(RuntimeError):
    """A sanitized Massive REST failure safe to show in the UI."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class TradierAPIError(RuntimeError):
    """A sanitized Tradier REST failure safe to show in the UI."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class DataContext:
    provider: str = "Unavailable"
    feed: str = "Options"
    status: str = "unavailable"
    recency: str = "UNKNOWN"
    quote_timestamp: Optional[str] = None
    request_id: Optional[str] = None
    rows: int = 0
    pages: int = 0
    fallback_used: bool = False
    message: str = ""
    quality: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _get_secret(secrets: Mapping[str, Any], names: Sequence[str]) -> Optional[str]:
    """Return the first configured credential without logging or exposing it."""

    return resolve_secret(names, secrets) or None


def get_thetadata_api_key(secrets: Mapping[str, Any]) -> Optional[str]:
    """Resolve the ThetaData API key from Streamlit-like secrets."""

    return _get_secret(secrets, THETADATA_SECRET_NAMES)


def get_massive_api_key(secrets: Mapping[str, Any]) -> Optional[str]:
    """Resolve the Massive/Polygon API key from Streamlit-like secrets."""

    return _get_secret(secrets, MASSIVE_SECRET_NAMES)


def get_tradier_api_token(secrets: Mapping[str, Any]) -> Optional[str]:
    """Resolve the Tradier bearer token from Streamlit secrets or the environment."""

    return _get_secret(secrets, TRADIER_SECRET_NAMES)


def get_tradier_sandbox(secrets: Mapping[str, Any]) -> bool:
    """Return whether the explicitly configured Tradier environment is sandbox."""

    value = resolve_secret(TRADIER_ENVIRONMENT_NAMES, secrets).strip().lower()
    return value in {"sandbox", "paper", "test", "testing"}


def _safe_float(value: Any) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else float("nan")
    except (TypeError, ValueError):
        return float("nan")


def _iso_timestamp(value: Any) -> Optional[str]:
    """Normalize seconds/ms/us/ns epoch values to an ISO UTC timestamp."""

    number = _safe_float(value)
    if not math.isfinite(number) or number <= 0:
        return None
    absolute = abs(number)
    if absolute >= 1e17:
        unit = "ns"
    elif absolute >= 1e14:
        unit = "us"
    elif absolute >= 1e11:
        unit = "ms"
    else:
        unit = "s"
    try:
        stamp = pd.to_datetime(number, unit=unit, utc=True)
        return stamp.isoformat()
    except Exception:
        return None



def _theta_client(api_key: str):
    """Create a direct ThetaData v3 Python client lazily.

    The official Python library is optional so Yahoo/Massive fallbacks keep the
    terminal importable on environments where ``thetadata`` is not installed.
    ThetaData's current direct client requires Python 3.12+ and thetadata 1.0.9+
    for API-key authentication.
    """

    if not api_key:
        raise ThetaDataAPIError("Clé API ThetaData absente.", "auth")
    try:
        from thetadata import ThetaClient  # type: ignore
    except ImportError as exc:
        raise ThetaDataAPIError(
            "Bibliothèque ThetaData absente. Installer `thetadata>=1.0.9` sous Python 3.12+.",
            "dependency",
        ) from exc
    try:
        return ThetaClient(api_key=api_key, dataframe_type="pandas")
    except Exception as exc:
        message = str(exc).lower()
        if any(token in message for token in ("auth", "credential", "api key", "unauthorized")):
            raise ThetaDataAPIError("Authentification ThetaData refusée.", "auth") from None
        raise ThetaDataAPIError(f"Connexion ThetaData impossible: {type(exc).__name__}.", "request") from None


def _theta_call(client: Any, method: str, **kwargs: Any) -> pd.DataFrame:
    """Call one documented ThetaData v3 Python method and normalize to pandas."""

    fn = getattr(client, method, None)
    if fn is None or not callable(fn):
        raise ThetaDataAPIError(
            f"Méthode ThetaData `{method}` indisponible; mettre à jour la bibliothèque.",
            "dependency",
        )
    try:
        frame = fn(**kwargs)
    except Exception as exc:
        text = str(exc).lower()
        if any(token in text for token in ("subscription", "entitlement", "permission", "forbidden", "not authorized")):
            raise ThetaDataAPIError(f"Entitlement ThetaData insuffisant pour `{method}`.", "entitlement") from None
        if any(token in text for token in ("auth", "credential", "api key", "unauthorized")):
            raise ThetaDataAPIError("Authentification ThetaData refusée.", "auth") from None
        raise ThetaDataAPIError(f"ThetaData `{method}` indisponible: {type(exc).__name__}.", "request") from None
    if frame is None:
        return pd.DataFrame()
    if isinstance(frame, pd.DataFrame):
        return frame.copy()
    try:
        if hasattr(frame, "to_pandas"):
            return frame.to_pandas()
        return pd.DataFrame(frame)
    except Exception as exc:
        raise ThetaDataAPIError(f"Réponse ThetaData `{method}` non convertible en DataFrame.", "schema") from exc


def _theta_expiration(value: str) -> date:
    try:
        return pd.Timestamp(value).date()
    except Exception as exc:
        raise ThetaDataAPIError(f"Expiration ThetaData invalide: {value}.", "schema") from exc


def _theta_timestamp_iso(value: Any) -> Optional[str]:
    """Normalize ThetaData timestamps to UTC without treating naïve ET as UTC."""

    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    try:
        stamp = pd.Timestamp(value)
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize("America/New_York", ambiguous="NaT", nonexistent="shift_forward")
        if pd.isna(stamp):
            return None
        return stamp.tz_convert("UTC").isoformat()
    except Exception:
        return None


def _theta_contract_symbol(underlying: str, expiration: Any, right: Any, strike: Any) -> Optional[str]:
    try:
        exp = pd.Timestamp(expiration).strftime("%y%m%d")
        cp = "C" if str(right).lower().startswith("c") else "P"
        strike_code = int(round(float(strike) * 1000.0))
        return f"{str(underlying).upper().strip()}{exp}{cp}{strike_code:08d}"
    except Exception:
        return None


def _theta_keys(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    out.columns = [str(column).strip() for column in out.columns]
    rename = {"symbol": "underlying", "right": "option_type"}
    out = out.rename(columns={key: value for key, value in rename.items() if key in out.columns})
    if "option_type" in out.columns:
        out["option_type"] = out["option_type"].astype(str).str.lower().replace({"c": "call", "p": "put"})
    if "expiration" in out.columns:
        out["expiration"] = pd.to_datetime(out["expiration"], errors="coerce").dt.strftime("%Y-%m-%d")
    if "strike" in out.columns:
        out["strike"] = pd.to_numeric(out["strike"], errors="coerce")
    return out


def _theta_merge(base: pd.DataFrame, extra: pd.DataFrame, columns: Mapping[str, str]) -> pd.DataFrame:
    """Left-merge a ThetaData snapshot on contract identity with selected names."""

    if base is None or base.empty or extra is None or extra.empty:
        return base
    work = _theta_keys(extra)
    keys = [key for key in ("underlying", "expiration", "strike", "option_type") if key in base.columns and key in work.columns]
    if len(keys) < 3:
        return base
    keep = keys + [source for source in columns if source in work.columns]
    work = work[keep].copy().rename(columns={source: target for source, target in columns.items() if source in work.columns})
    work = work.drop_duplicates(subset=keys, keep="last")
    return base.merge(work, on=keys, how="left")


def _theta_latest_timestamp(frame: pd.DataFrame) -> Optional[str]:
    if frame is None or frame.empty or "quoteTimestamp" not in frame.columns:
        return None
    stamps = pd.to_datetime(frame["quoteTimestamp"], errors="coerce", utc=True).dropna()
    return stamps.max().isoformat() if not stamps.empty else None


def _theta_recency(frame: pd.DataFrame) -> str:
    """Classify actual freshness from the OPRA quote timestamp rather than the plan name."""

    latest = _theta_latest_timestamp(frame)
    if latest is None:
        return "UNKNOWN"
    stamp = pd.Timestamp(latest)
    now = pd.Timestamp.now(tz="UTC")
    age = max((now - stamp).total_seconds(), 0.0)
    if age <= 5 * 60:
        return "REAL-TIME"
    try:
        if stamp.tz_convert("America/New_York").date() == now.tz_convert("America/New_York").date():
            return "SAME-DAY / STALE"
    except Exception:
        pass
    return "LAST SESSION"


def fetch_thetadata_option_expirations(ticker: str, api_key: str) -> Tuple[List[str], DataContext]:
    """Load available option expirations through the official ThetaData v3 Python library."""

    ticker = str(ticker).upper().strip()
    client = _theta_client(api_key)
    frame = _theta_call(client, "option_list_expirations", symbol=ticker)
    if frame.empty or "expiration" not in frame.columns:
        values: List[str] = []
    else:
        parsed = pd.to_datetime(frame["expiration"], errors="coerce").dropna()
        today = pd.Timestamp.now(tz="America/New_York").date()
        values = sorted({stamp.strftime("%Y-%m-%d") for stamp in parsed if stamp.date() >= today})
    return values, DataContext(
        provider="ThetaData",
        feed="Options reference",
        status="ok" if values else "empty",
        recency="REFERENCE",
        rows=len(values),
        pages=1,
        message="Expirations ThetaData v3." if values else "Aucune expiration ThetaData active retournée.",
    )


def fetch_thetadata_option_chain(
    ticker: str,
    expiration: str,
    api_key: str,
) -> Tuple[pd.DataFrame, pd.DataFrame, DataContext]:
    """Build an institutional option-chain snapshot from ThetaData OPRA fields.

    Quote, OI, trade and OHLC endpoints are available independently.  Pro Greeks
    are opportunistic: an entitlement failure there does not discard otherwise
    valid NBBO/OI data.  Standard accounts fall back to ThetaData IV and the
    terminal's local model Greeks.
    """

    ticker = str(ticker).upper().strip()
    exp = _theta_expiration(expiration)
    common = {"symbol": ticker, "expiration": exp, "strike": "*", "right": "both"}
    client = _theta_client(api_key)

    quote = _theta_keys(_theta_call(client, "option_snapshot_quote", **common))
    if quote.empty:
        return pd.DataFrame(), pd.DataFrame(), DataContext(
            provider="ThetaData / OPRA",
            feed="Consolidated options snapshot",
            status="empty",
            recency="UNKNOWN",
            rows=0,
            pages=1,
            message="Snapshot NBBO ThetaData vide (marché fermé ou aucune quote éligible).",
        )

    frame = quote.copy()
    if "timestamp" in frame.columns:
        frame["quoteTimestamp"] = frame["timestamp"].map(_theta_timestamp_iso)
    frame = frame.rename(columns={
        "bid_size": "bidSize",
        "ask_size": "askSize",
        "bid_exchange": "bidExchange",
        "ask_exchange": "askExchange",
        "bid_condition": "bidCondition",
        "ask_condition": "askCondition",
    })

    feature_notes: List[str] = []
    calls_made = 1

    try:
        oi = _theta_call(client, "option_snapshot_open_interest", **common)
        calls_made += 1
        frame = _theta_merge(frame, oi, {"open_interest": "openInterest"})
    except ThetaDataAPIError as exc:
        feature_notes.append(str(exc))

    try:
        ohlc = _theta_call(client, "option_snapshot_ohlc", **common)
        calls_made += 1
        frame = _theta_merge(frame, ohlc, {"volume": "volume", "close": "sessionClose", "count": "tradeCount"})
    except ThetaDataAPIError as exc:
        feature_notes.append(str(exc))

    try:
        trade = _theta_call(client, "option_snapshot_trade", **common)
        calls_made += 1
        trade_keys = _theta_keys(trade)
        if not trade_keys.empty and "timestamp" in trade_keys.columns:
            trade_keys["tradeTimestampTheta"] = trade_keys["timestamp"].map(_theta_timestamp_iso)
        frame = _theta_merge(frame, trade_keys, {
            "price": "lastPrice",
            "size": "lastTradeSize",
            "exchange": "lastTradeExchange",
            "condition": "lastTradeCondition",
            "tradeTimestampTheta": "tradeTimestamp",
        })
    except ThetaDataAPIError as exc:
        feature_notes.append(str(exc))

    greeks_loaded = False
    try:
        greeks = _theta_call(client, "option_snapshot_greeks_all", **common)
        calls_made += 1
        greek_keys = _theta_keys(greeks)
        if not greek_keys.empty and "timestamp" in greek_keys.columns:
            greek_keys["greeksTimestampTheta"] = greek_keys["timestamp"].map(_theta_timestamp_iso)
        if not greek_keys.empty and "underlying_timestamp" in greek_keys.columns:
            greek_keys["underlyingTimestampTheta"] = greek_keys["underlying_timestamp"].map(_theta_timestamp_iso)
        frame = _theta_merge(frame, greek_keys, {
            "implied_vol": "impliedVolatility",
            "delta": "delta_vendor",
            "gamma": "gamma_vendor",
            "theta": "theta_vendor",
            "vega": "vega_vendor",
            "rho": "rho_vendor",
            "vanna": "vanna_vendor",
            "vomma": "vomma_vendor",
            "charm": "charm_vendor",
            "speed": "speed_vendor",
            "color": "color_vendor",
            "zomma": "zomma_vendor",
            "underlying_price": "underlyingPrice",
            "underlyingTimestampTheta": "underlyingTimestamp",
            "greeksTimestampTheta": "greeksTimestamp",
            "iv_error": "ivError",
        })
        greeks_loaded = any(column in frame.columns and frame[column].notna().any() for column in ("delta_vendor", "gamma_vendor"))
    except ThetaDataAPIError as exc:
        feature_notes.append(str(exc))

    if not greeks_loaded:
        try:
            iv = _theta_call(client, "option_snapshot_greeks_implied_volatility", **common)
            calls_made += 1
            iv_keys = _theta_keys(iv)
            if not iv_keys.empty and "underlying_timestamp" in iv_keys.columns:
                iv_keys["underlyingTimestampTheta"] = iv_keys["underlying_timestamp"].map(_theta_timestamp_iso)
            frame = _theta_merge(frame, iv_keys, {
                "implied_vol": "impliedVolatility",
                "underlying_price": "underlyingPrice",
                "underlyingTimestampTheta": "underlyingTimestamp",
                "iv_error": "ivError",
            })
        except ThetaDataAPIError as exc:
            feature_notes.append(str(exc))

    # Canonical fields consumed by the existing workspaces.
    if "underlying" not in frame.columns:
        frame["underlying"] = ticker
    frame["provider"] = "ThetaData / OPRA"
    frame["quoteTimeframe"] = "REAL-TIME ENDPOINT"
    frame["tradeTimeframe"] = "REAL-TIME ENDPOINT"
    frame["exerciseStyle"] = "UNKNOWN"  # Exercise style is reference data; never infer it from OPRA quotes.
    frame["contractMultiplier"] = 100.0
    frame["contractSymbol"] = [
        _theta_contract_symbol(ticker, expiration, right, strike)
        for right, strike in zip(frame.get("option_type", pd.Series(index=frame.index)), frame.get("strike", pd.Series(index=frame.index)))
    ]

    if "lastPrice" not in frame.columns:
        frame["lastPrice"] = pd.to_numeric(frame.get("sessionClose", np.nan), errors="coerce")
    elif "sessionClose" in frame.columns:
        frame["lastPrice"] = pd.to_numeric(frame["lastPrice"], errors="coerce").combine_first(
            pd.to_numeric(frame["sessionClose"], errors="coerce")
        )

    numeric = [
        "strike", "bid", "ask", "bidSize", "askSize", "lastPrice", "lastTradeSize",
        "volume", "tradeCount", "openInterest", "impliedVolatility", "underlyingPrice",
        "contractMultiplier", "delta_vendor", "gamma_vendor", "theta_vendor", "vega_vendor",
        "rho_vendor", "vanna_vendor", "vomma_vendor", "charm_vendor", "speed_vendor",
        "color_vendor", "zomma_vendor", "ivError",
    ]
    for column in numeric:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame = frame.dropna(subset=[column for column in ("strike", "option_type") if column in frame.columns])
    frame = frame.sort_values(["option_type", "strike"], na_position="last").reset_index(drop=True)
    calls = frame[frame["option_type"].astype(str).str.lower().eq("call")].copy()
    puts = frame[frame["option_type"].astype(str).str.lower().eq("put")].copy()

    quality = summarize_chain_quality(frame)
    quality["vendor_greeks"] = bool(greeks_loaded)
    quality["vendor"] = "ThetaData"
    quality["nbbo_source"] = "OPRA"
    recency = _theta_recency(frame)
    latest = _theta_latest_timestamp(frame)
    note = "Greeks ThetaData Pro." if greeks_loaded else "Greeks vendor indisponibles; modèle local utilisé en repli."
    if feature_notes:
        # Keep only sanitized unique feature messages; never surface raw credentials/errors.
        note += " " + " ".join(dict.fromkeys(feature_notes))
    return calls, puts, DataContext(
        provider="ThetaData / OPRA",
        feed="Consolidated options NBBO + OI + IV/Greeks",
        status="ok" if not frame.empty else "empty",
        recency=recency,
        quote_timestamp=latest,
        rows=len(frame),
        pages=calls_made,
        fallback_used=False,
        message=f"OPRA NBBO ThetaData v3. {note}".strip(),
        quality=quality,
    )


def _append_query(url: str, params: Optional[Mapping[str, Any]]) -> str:
    if not params:
        return url
    clean = {key: value for key, value in params.items() if value is not None}
    if not clean:
        return url
    split = urlsplit(url)
    existing = split.query
    query = urlencode(clean)
    combined = f"{existing}&{query}" if existing else query
    return urlunsplit((split.scheme, split.netloc, split.path, combined, split.fragment))


def _tradier_iso_timestamp(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    numeric = _iso_timestamp(value)
    if numeric is not None:
        return numeric
    try:
        stamp = pd.Timestamp(value)
        if pd.isna(stamp):
            return None
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize("America/New_York", ambiguous="NaT", nonexistent="shift_forward")
        if pd.isna(stamp):
            return None
        return stamp.tz_convert("UTC").isoformat()
    except Exception:
        return None


def tradier_get_json(
    path: str,
    access_token: str,
    *,
    sandbox: bool = False,
    params: Optional[Mapping[str, Any]] = None,
    timeout: float = 12.0,
) -> Dict[str, Any]:
    """Call a documented Tradier market-data endpoint with a bearer header."""

    if not access_token:
        raise TradierAPIError("Token API Tradier absent.")
    if not str(path).startswith("/"):
        raise TradierAPIError("Route Tradier invalide.")
    root = TRADIER_SANDBOX_ROOT if sandbox else TRADIER_API_ROOT
    url = _append_query(root + path, params)
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": "QuantTerminal/derivatives-workspace",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        status = int(getattr(exc, "code", 0) or 0)
        if status == 401:
            raise TradierAPIError("Authentification Tradier refusée.", status) from None
        if status == 403:
            raise TradierAPIError("Entitlement Tradier insuffisant pour cet endpoint.", status) from None
        if status == 429:
            raise TradierAPIError("Limite de requêtes Tradier atteinte.", status) from None
        raise TradierAPIError(f"Tradier HTTP {status or 'error'}.", status) from None
    except (URLError, TimeoutError) as exc:
        raise TradierAPIError(f"Tradier indisponible: {type(exc).__name__}.") from None
    except json.JSONDecodeError:
        raise TradierAPIError("Réponse Tradier JSON invalide.") from None
    if not isinstance(payload, dict):
        raise TradierAPIError("Réponse Tradier non structurée.")
    if payload.get("errors"):
        raise TradierAPIError("Tradier a refusé la requête ou l'entitlement.")
    return payload


def fetch_tradier_option_expirations(
    ticker: str,
    access_token: str,
    *,
    sandbox: bool = False,
) -> Tuple[List[str], DataContext]:
    """Load active US option expirations from Tradier Markets."""

    payload = tradier_get_json(
        "/v1/markets/options/expirations",
        access_token,
        sandbox=sandbox,
        params={"symbol": str(ticker).upper().strip(), "includeAllRoots": "true", "strikes": "false"},
    )
    values = (payload.get("expirations") or {}).get("date")
    if isinstance(values, str):
        values = [values]
    parsed = pd.to_datetime(pd.Series(values or [], dtype=object), errors="coerce").dropna()
    today = pd.Timestamp.now(tz="America/New_York").date()
    expirations = sorted({stamp.strftime("%Y-%m-%d") for stamp in parsed if stamp.date() >= today})
    return expirations, DataContext(
        provider="Tradier",
        feed="US options reference",
        status="ok" if expirations else "empty",
        recency="REFERENCE",
        rows=len(expirations),
        pages=1,
        message="Expirations Tradier Markets." if expirations else "Aucune expiration active retournée par Tradier.",
    )


def fetch_tradier_option_chain(
    ticker: str,
    expiration: str,
    access_token: str,
    *,
    sandbox: bool = False,
) -> Tuple[pd.DataFrame, pd.DataFrame, DataContext]:
    """Load one Tradier option chain and retain vendor IV and ORATS Greeks."""

    payload = tradier_get_json(
        "/v1/markets/options/chains",
        access_token,
        sandbox=sandbox,
        params={
            "symbol": str(ticker).upper().strip(),
            "expiration": str(expiration),
            "greeks": "true",
        },
    )
    values = (payload.get("options") or {}).get("option")
    if isinstance(values, dict):
        values = [values]
    rows: List[Dict[str, Any]] = []
    for item in values or []:
        if not isinstance(item, dict):
            continue
        greeks = item.get("greeks") if isinstance(item.get("greeks"), dict) else {}
        quote_stamp = _tradier_iso_timestamp(item.get("trade_date") or greeks.get("updated_at"))
        rows.append(
            {
                "contractSymbol": item.get("symbol"),
                "strike": item.get("strike"),
                "lastPrice": item.get("last"),
                "bid": item.get("bid"),
                "ask": item.get("ask"),
                "bidSize": item.get("bidsize"),
                "askSize": item.get("asksize"),
                "change": item.get("change"),
                "percentChange": item.get("change_percentage"),
                "volume": item.get("volume"),
                "openInterest": item.get("open_interest"),
                "impliedVolatility": greeks.get("mid_iv", greeks.get("smv_vol")),
                "option_type": item.get("option_type", item.get("type")),
                "expiration": item.get("expiration_date", expiration),
                "contractMultiplier": item.get("contract_size", 100),
                "delta_vendor": greeks.get("delta"),
                "gamma_vendor": greeks.get("gamma"),
                "theta_vendor": greeks.get("theta"),
                "vega_vendor": greeks.get("vega"),
                "rho_vendor": greeks.get("rho"),
                "quoteTimestamp": quote_stamp,
                "tradeTimestamp": _tradier_iso_timestamp(item.get("trade_date")),
                "quoteTimeframe": "DELAYED" if sandbox else "ENTITLEMENT",
                "tradeTimeframe": "DELAYED" if sandbox else "ENTITLEMENT",
                "underlyingPrice": item.get("underlying_price"),
                "provider": "Tradier / OPRA",
            }
        )
    frame = pd.DataFrame(rows)
    if not frame.empty:
        numeric = [
            "strike", "lastPrice", "bid", "ask", "bidSize", "askSize", "change",
            "percentChange", "volume", "openInterest", "impliedVolatility",
            "contractMultiplier", "delta_vendor", "gamma_vendor", "theta_vendor",
            "vega_vendor", "rho_vendor", "underlyingPrice",
        ]
        for column in numeric:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame["option_type"] = frame["option_type"].astype(str).str.lower().replace({"c": "call", "p": "put"})
        frame = frame.sort_values(["option_type", "strike"], na_position="last").reset_index(drop=True)
    calls = frame.loc[frame["option_type"].eq("call")].copy() if not frame.empty else pd.DataFrame()
    puts = frame.loc[frame["option_type"].eq("put")].copy() if not frame.empty else pd.DataFrame()
    latest = None
    if not frame.empty:
        stamps = pd.to_datetime(frame["quoteTimestamp"], errors="coerce", utc=True).dropna()
        if not stamps.empty:
            latest = stamps.max().isoformat()
    recency = "DELAYED 15M / SANDBOX" if sandbox else "ACCOUNT ENTITLEMENT"
    return calls, puts, DataContext(
        provider="Tradier / OPRA",
        feed="US options chain + ORATS Greeks",
        status="ok" if not frame.empty else "empty",
        recency=recency,
        quote_timestamp=latest,
        rows=len(frame),
        pages=1,
        message=(
            "Chaîne Tradier; IV/Greeks de courtoisie ORATS."
            if not frame.empty
            else "Chaîne Tradier vide pour cette expiration."
        ),
        quality=summarize_chain_quality(frame),
    )


def _validated_url(path_or_url: str) -> str:
    if path_or_url.startswith("/"):
        return MASSIVE_API_ROOT + path_or_url
    split = urlsplit(path_or_url)
    if split.scheme != "https" or split.netloc != "api.massive.com":
        raise MassiveAPIError("Pagination Massive refusée: hôte inattendu.")
    return path_or_url


def massive_get_json(
    path_or_url: str,
    api_key: str,
    params: Optional[Mapping[str, Any]] = None,
    timeout: float = 12.0,
    attempts: int = 2,
) -> Dict[str, Any]:
    """Call Massive with a Bearer header; the credential never enters the URL."""

    if not api_key:
        raise MassiveAPIError("Clé API Massive absente.")
    url = _append_query(_validated_url(path_or_url), params)
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "QuantTerminal/derivatives-workspace",
        },
        method="GET",
    )
    last_error: Optional[Exception] = None
    for attempt in range(max(1, attempts)):
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise MassiveAPIError("Réponse Massive non structurée.")
            if str(payload.get("status", "OK")).upper() in {"ERROR", "NOT_AUTHORIZED"}:
                raise MassiveAPIError(str(payload.get("error") or payload.get("message") or "Erreur Massive."))
            return payload
        except HTTPError as exc:
            status = int(getattr(exc, "code", 0) or 0)
            if status == 401:
                raise MassiveAPIError("Authentification Massive refusée.", status) from None
            if status == 403:
                raise MassiveAPIError("Entitlement Massive insuffisant pour cet endpoint.", status) from None
            if status == 429:
                last_error = MassiveAPIError("Limite de requêtes Massive atteinte.", status)
            else:
                last_error = MassiveAPIError(f"Massive HTTP {status or 'error'}.", status)
        except (URLError, TimeoutError) as exc:
            last_error = MassiveAPIError(f"Massive indisponible: {type(exc).__name__}.")
        except json.JSONDecodeError:
            last_error = MassiveAPIError("Réponse Massive JSON invalide.")
        if attempt + 1 < max(1, attempts):
            time.sleep(0.35 * (attempt + 1))
    if isinstance(last_error, MassiveAPIError):
        raise last_error
    raise MassiveAPIError("Échec Massive non identifié.")


def fetch_massive_option_expirations(
    ticker: str,
    api_key: str,
    limit: int = 1000,
    max_pages: int = 5,
) -> Tuple[List[str], DataContext]:
    """Load active option expirations from the reference contracts endpoint."""

    ticker = str(ticker).upper().strip()
    path: Optional[str] = "/v3/reference/options/contracts"
    params: Optional[Dict[str, Any]] = {
        "underlying_ticker": ticker,
        "expired": "false",
        "limit": min(max(int(limit), 1), 1000),
        "sort": "expiration_date",
        "order": "asc",
    }
    expirations: set[str] = set()
    pages = 0
    request_id: Optional[str] = None
    while path and pages < max_pages:
        payload = massive_get_json(path, api_key, params=params)
        request_id = request_id or payload.get("request_id")
        for item in payload.get("results") or []:
            expiration = item.get("expiration_date") if isinstance(item, dict) else None
            if expiration:
                expirations.add(str(expiration))
        pages += 1
        path = payload.get("next_url")
        params = None
    values = sorted(expirations)
    return values, DataContext(
        provider="Massive",
        feed="Options reference",
        status="ok" if values else "empty",
        recency="REFERENCE",
        request_id=request_id,
        rows=len(values),
        pages=pages,
        message="Expirations actives Massive." if values else "Aucune expiration active retournée.",
    )


def _snapshot_row(item: Mapping[str, Any]) -> Dict[str, Any]:
    details = item.get("details") or {}
    quote = item.get("last_quote") or {}
    trade = item.get("last_trade") or {}
    day = item.get("day") or {}
    greeks = item.get("greeks") or {}
    underlying = item.get("underlying_asset") or {}
    quote_ts = quote.get("last_updated")
    trade_ts = trade.get("sip_timestamp", trade.get("last_updated"))
    return {
        "contractSymbol": details.get("ticker"),
        "strike": details.get("strike_price"),
        "lastPrice": trade.get("price", day.get("close")),
        "bid": quote.get("bid"),
        "ask": quote.get("ask"),
        "bidSize": quote.get("bid_size"),
        "askSize": quote.get("ask_size"),
        "volume": day.get("volume", trade.get("size")),
        "openInterest": item.get("open_interest"),
        "impliedVolatility": item.get("implied_volatility"),
        "option_type": details.get("contract_type"),
        "expiration": details.get("expiration_date"),
        "exerciseStyle": details.get("exercise_style"),
        "contractMultiplier": details.get("shares_per_contract", 100),
        "delta_vendor": greeks.get("delta"),
        "gamma_vendor": greeks.get("gamma"),
        "theta_vendor": greeks.get("theta"),
        "vega_vendor": greeks.get("vega"),
        "quoteTimestamp": _iso_timestamp(quote_ts),
        "tradeTimestamp": _iso_timestamp(trade_ts),
        "quoteTimeframe": str(quote.get("timeframe") or "UNKNOWN").upper(),
        "tradeTimeframe": str(trade.get("timeframe") or "UNKNOWN").upper(),
        "underlyingPrice": underlying.get("price"),
        "underlyingTimestamp": _iso_timestamp(underlying.get("last_updated")),
        "underlyingTimeframe": str(underlying.get("timeframe") or "UNKNOWN").upper(),
        "breakEvenPrice": item.get("break_even_price"),
        "fairMarketValue": item.get("fmv"),
        "provider": "Massive / OPRA",
    }


def _dominant_timeframe(frame: pd.DataFrame) -> str:
    values: List[str] = []
    for column in ("quoteTimeframe", "tradeTimeframe"):
        if column in frame.columns:
            values.extend(frame[column].dropna().astype(str).str.upper().tolist())
    values = [value for value in values if value and value != "UNKNOWN"]
    if not values:
        return "UNKNOWN"
    if any("DELAY" in value for value in values):
        return "DELAYED"
    if any("REAL" in value for value in values):
        return "REAL-TIME"
    return pd.Series(values).mode().iat[0]


def summarize_chain_quality(frame: pd.DataFrame, now: Optional[datetime] = None) -> Dict[str, Any]:
    if frame is None or frame.empty:
        return {
            "quote_coverage": 0.0,
            "two_sided_coverage": 0.0,
            "iv_coverage": 0.0,
            "greeks_coverage": 0.0,
            "oi_coverage": 0.0,
            "median_spread_pct": None,
            "median_quote_age_seconds": None,
        }
    total = float(len(frame))
    bid = pd.to_numeric(frame.get("bid", pd.Series(index=frame.index, dtype=float)), errors="coerce")
    ask = pd.to_numeric(frame.get("ask", pd.Series(index=frame.index, dtype=float)), errors="coerce")
    mid = (bid + ask) / 2.0
    two_sided = (bid > 0) & (ask > 0) & (ask >= bid)
    iv = pd.to_numeric(frame.get("impliedVolatility", pd.Series(index=frame.index, dtype=float)), errors="coerce")
    oi = pd.to_numeric(frame.get("openInterest", pd.Series(index=frame.index, dtype=float)), errors="coerce")
    delta = pd.to_numeric(frame.get("delta_vendor", pd.Series(index=frame.index, dtype=float)), errors="coerce")
    gamma = pd.to_numeric(frame.get("gamma_vendor", pd.Series(index=frame.index, dtype=float)), errors="coerce")
    spread_pct = ((ask - bid) / mid.replace(0, np.nan)).where(two_sided)
    ages: List[float] = []
    reference = now or datetime.now(timezone.utc)
    for value in frame.get("quoteTimestamp", pd.Series(index=frame.index, dtype=object)).dropna():
        try:
            stamp = pd.Timestamp(value)
            if stamp.tzinfo is None:
                stamp = stamp.tz_localize("UTC")
            ages.append(max((reference - stamp.to_pydatetime()).total_seconds(), 0.0))
        except Exception:
            continue
    return {
        "quote_coverage": float((bid.notna() | ask.notna()).sum() / total),
        "two_sided_coverage": float(two_sided.sum() / total),
        "iv_coverage": float(iv.notna().sum() / total),
        "greeks_coverage": float((delta.notna() & gamma.notna()).sum() / total),
        "oi_coverage": float(oi.notna().sum() / total),
        "median_spread_pct": float(spread_pct.median()) if spread_pct.notna().any() else None,
        "median_quote_age_seconds": float(np.median(ages)) if ages else None,
    }


def fetch_massive_option_chain(
    ticker: str,
    expiration: str,
    api_key: str,
    max_pages: int = 8,
) -> Tuple[pd.DataFrame, pd.DataFrame, DataContext]:
    """Fetch a complete expiry snapshot and preserve Massive vendor Greeks."""

    ticker = str(ticker).upper().strip()
    path: Optional[str] = f"/v3/snapshot/options/{ticker}"
    params: Optional[Dict[str, Any]] = {
        "expiration_date": str(expiration),
        "limit": 250,
        "sort": "strike_price",
        "order": "asc",
    }
    rows: List[Dict[str, Any]] = []
    pages = 0
    request_id: Optional[str] = None
    while path and pages < max_pages:
        payload = massive_get_json(path, api_key, params=params)
        request_id = request_id or payload.get("request_id")
        rows.extend(_snapshot_row(item) for item in (payload.get("results") or []) if isinstance(item, dict))
        pages += 1
        path = payload.get("next_url")
        params = None
    frame = pd.DataFrame(rows)
    if not frame.empty:
        numeric = [
            "strike", "lastPrice", "bid", "ask", "bidSize", "askSize", "volume",
            "openInterest", "impliedVolatility", "contractMultiplier", "delta_vendor",
            "gamma_vendor", "theta_vendor", "vega_vendor", "underlyingPrice",
            "breakEvenPrice", "fairMarketValue",
        ]
        for column in numeric:
            if column in frame.columns:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame.sort_values(["option_type", "strike"], na_position="last").reset_index(drop=True)
    calls = frame[frame.get("option_type", pd.Series(dtype=object)).astype(str).str.lower().eq("call")].copy() if not frame.empty else pd.DataFrame()
    puts = frame[frame.get("option_type", pd.Series(dtype=object)).astype(str).str.lower().eq("put")].copy() if not frame.empty else pd.DataFrame()
    latest = None
    if not frame.empty and "quoteTimestamp" in frame.columns:
        parsed = pd.to_datetime(frame["quoteTimestamp"], errors="coerce", utc=True).dropna()
        if not parsed.empty:
            latest = parsed.max().isoformat()
    quality = summarize_chain_quality(frame)
    recency = _dominant_timeframe(frame)
    status = "ok" if not frame.empty else "empty"
    return calls, puts, DataContext(
        provider="Massive / OPRA",
        feed="Consolidated options snapshot",
        status=status,
        recency=recency,
        quote_timestamp=latest,
        request_id=request_id,
        rows=len(frame),
        pages=pages,
        message=(
            f"NBBO/quotes OPRA {recency.lower()} selon entitlement." if not frame.empty
            else "Snapshot Massive vide pour cette expiration."
        ),
        quality=quality,
    )


def merge_data_context(
    primary: DataContext,
    *,
    status: Optional[str] = None,
    fallback_used: Optional[bool] = None,
    message: Optional[str] = None,
    quality: Optional[Dict[str, Any]] = None,
) -> DataContext:
    values = primary.to_dict()
    if status is not None:
        values["status"] = status
    if fallback_used is not None:
        values["fallback_used"] = fallback_used
    if message is not None:
        values["message"] = message
    if quality is not None:
        values["quality"] = quality
    return DataContext(**values)


def fetch_massive_futures_curve(
    product_code: str,
    api_key: str,
    max_contracts: int = 24,
) -> Tuple[pd.DataFrame, DataContext]:
    """Load active contract metadata and snapshots for one futures product."""

    product_code = str(product_code).upper().strip()
    contracts_payload = massive_get_json(
        "/futures/v1/contracts",
        api_key,
        params={
            "product_code": product_code,
            "active": "true",
            "type": "single",
            "limit": min(max(int(max_contracts), 1), 1000),
            "sort": "last_trade_date.asc",
        },
    )
    contracts = {
        str(item.get("ticker")): item
        for item in (contracts_payload.get("results") or [])
        if isinstance(item, dict) and item.get("ticker")
    }
    snapshot_payload = massive_get_json(
        "/futures/v1/snapshot",
        api_key,
        params={"product_code": product_code, "limit": min(max(int(max_contracts), 1), 50000), "sort": "ticker.asc"},
    )
    rows: List[Dict[str, Any]] = []
    timestamps: List[str] = []
    for item in snapshot_payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or "")
        contract = contracts.get(ticker, {})
        quote = item.get("last_quote") or {}
        trade = item.get("last_trade") or {}
        session = item.get("session") or {}
        bid = _safe_float(quote.get("bid"))
        ask = _safe_float(quote.get("ask"))
        last = _safe_float(trade.get("price"))
        settlement = _safe_float(session.get("settlement_price"))
        if math.isfinite(bid) and math.isfinite(ask) and ask >= bid:
            mark = (bid + ask) / 2.0
        elif math.isfinite(last):
            mark = last
        else:
            mark = settlement
        quote_stamp = _iso_timestamp(quote.get("last_updated") or quote.get("bid_timestamp") or quote.get("ask_timestamp"))
        if quote_stamp:
            timestamps.append(quote_stamp)
        rows.append(
            {
                "ticker": ticker,
                "product_code": item.get("product_code", product_code),
                "name": contract.get("name"),
                "trading_venue": contract.get("trading_venue"),
                "last_trade_date": contract.get("last_trade_date"),
                "settlement_date": contract.get("settlement_date"),
                "days_to_maturity": contract.get("days_to_maturity"),
                "tick_size": contract.get("trade_tick_size"),
                "bid": bid,
                "ask": ask,
                "bid_size": quote.get("bid_size"),
                "ask_size": quote.get("ask_size"),
                "last": last,
                "mark": mark,
                "settlement": settlement,
                "previous_settlement": session.get("previous_settlement"),
                "change": session.get("change"),
                "change_percent": session.get("change_percent"),
                "open": session.get("open"),
                "high": session.get("high"),
                "low": session.get("low"),
                "volume": session.get("volume"),
                "quote_timestamp": quote_stamp,
                "trade_timestamp": _iso_timestamp(trade.get("last_updated")),
            }
        )
    frame = pd.DataFrame(rows)
    if not frame.empty:
        for column in [
            "days_to_maturity", "tick_size", "bid", "ask", "bid_size", "ask_size",
            "last", "mark", "settlement", "previous_settlement", "change",
            "change_percent", "open", "high", "low", "volume",
        ]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame["last_trade_date"] = pd.to_datetime(frame["last_trade_date"], errors="coerce")
        frame = frame.sort_values(["last_trade_date", "ticker"], na_position="last").reset_index(drop=True)
        valid_marks = frame["mark"].replace([np.inf, -np.inf], np.nan).dropna()
        front = float(valid_marks.iloc[0]) if not valid_marks.empty else float("nan")
        frame["vs_front_pct"] = frame["mark"] / front - 1.0 if math.isfinite(front) and front != 0 else np.nan
        maturity = pd.to_numeric(frame["days_to_maturity"], errors="coerce")
        frame["annualized_roll_pct"] = np.where(
            (maturity > 0) & math.isfinite(front) & (front != 0),
            (frame["mark"] / front - 1.0) * 365.0 / maturity,
            np.nan,
        )
    latest = None
    if timestamps:
        parsed = pd.to_datetime(pd.Series(timestamps), errors="coerce", utc=True).dropna()
        if not parsed.empty:
            latest = parsed.max().isoformat()
    return frame, DataContext(
        provider="Massive / CME venues",
        feed="Futures contracts + snapshot",
        status="ok" if not frame.empty else "empty",
        recency="REAL-TIME" if not frame.empty else "UNKNOWN",
        quote_timestamp=latest,
        request_id=snapshot_payload.get("request_id") or contracts_payload.get("request_id"),
        rows=len(frame),
        pages=2,
        message=(
            f"Courbe {product_code}: contrats actifs et snapshots Massive."
            if not frame.empty
            else f"Aucun snapshot Massive pour {product_code}."
        ),
    )

# ============================================================
# Public Yahoo futures curve fallback
# ============================================================

FUTURES_MONTH_CODES: Dict[int, str] = {
    1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
    7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z",
}

# Yahoo individual-contract symbols follow ROOT + month code + 2-digit year + venue suffix.
# The mapping is deliberately small and explicit: every supported product in the UI has a
# verified public Yahoo naming convention.  Values such as tick size are static contract
# reference metadata, never live market observations.
YAHOO_FUTURES_PRODUCTS: Dict[str, Dict[str, Any]] = {
    "NQ": {"root": "NQ", "suffix": "CME", "venue": "CME", "months": (3, 6, 9, 12), "tick_size": 0.25, "name": "E-mini Nasdaq-100"},
    "ES": {"root": "ES", "suffix": "CME", "venue": "CME", "months": (3, 6, 9, 12), "tick_size": 0.25, "name": "E-mini S&P 500"},
    "RTY": {"root": "RTY", "suffix": "CME", "venue": "CME", "months": (3, 6, 9, 12), "tick_size": 0.10, "name": "E-mini Russell 2000"},
    "CL": {"root": "CL", "suffix": "NYM", "venue": "NYMEX", "months": tuple(range(1, 13)), "tick_size": 0.01, "name": "WTI Crude Oil"},
    "GC": {"root": "GC", "suffix": "CMX", "venue": "COMEX", "months": tuple(range(1, 13)), "tick_size": 0.10, "name": "Gold"},
    "ZB": {"root": "ZB", "suffix": "CBT", "venue": "CBOT", "months": (3, 6, 9, 12), "tick_size": 0.03125, "name": "U.S. Treasury Bond"},
    "6E": {"root": "6E", "suffix": "CME", "venue": "CME", "months": (3, 6, 9, 12), "tick_size": 0.00005, "name": "Euro FX"},
}


def _yahoo_futures_contract_candidates(
    product_code: str,
    *,
    now: Optional[datetime] = None,
    lookahead_months: int = 40,
) -> List[Dict[str, Any]]:
    """Generate Yahoo individual futures tickers without pretending to know exact last-trade dates."""

    product_code = str(product_code).upper().strip()
    spec = YAHOO_FUTURES_PRODUCTS.get(product_code)
    if spec is None:
        raise ValueError(f"Produit futures Yahoo non supporté: {product_code}")
    reference = now or datetime.now(timezone.utc)
    current_year, current_month = reference.year, reference.month
    allowed_months = set(int(month) for month in spec["months"])
    candidates: List[Dict[str, Any]] = []
    for offset in range(max(int(lookahead_months), 1) + 1):
        absolute = current_year * 12 + (current_month - 1) + offset
        year = absolute // 12
        month = absolute % 12 + 1
        if month not in allowed_months:
            continue
        month_code = FUTURES_MONTH_CODES[month]
        yahoo_ticker = f"{spec['root']}{month_code}{year % 100:02d}.{spec['suffix']}"
        contract_month = pd.Timestamp(year=year, month=month, day=1)
        candidates.append(
            {
                "ticker": yahoo_ticker,
                "contract_month": contract_month,
                "product_code": product_code,
                "name": f"{spec['name']} {contract_month.strftime('%b %Y')}",
                "trading_venue": spec["venue"],
                "tick_size": spec["tick_size"],
            }
        )
    return candidates


def _extract_yahoo_history(raw: pd.DataFrame, symbol: str, requested_symbols: Sequence[str]) -> pd.DataFrame:
    """Normalize yfinance single- and multi-symbol download layouts."""

    if raw is None or raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        level0 = {str(value) for value in raw.columns.get_level_values(0)}
        level1 = {str(value) for value in raw.columns.get_level_values(1)} if raw.columns.nlevels > 1 else set()
        try:
            if symbol in level0:
                out = raw[symbol].copy()
            elif symbol in level1:
                out = raw.xs(symbol, axis=1, level=1, drop_level=True).copy()
            else:
                return pd.DataFrame()
        except Exception:
            return pd.DataFrame()
    else:
        if len(requested_symbols) != 1 or symbol != requested_symbols[0]:
            return pd.DataFrame()
        out = raw.copy()
    out.columns = [str(column[0] if isinstance(column, tuple) else column).strip().lower().replace(" ", "_") for column in out.columns]
    return out


def _timestamp_to_iso(value: Any) -> Optional[str]:
    try:
        stamp = pd.Timestamp(value)
        if pd.isna(stamp):
            return None
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize("UTC")
        else:
            stamp = stamp.tz_convert("UTC")
        return stamp.isoformat()
    except Exception:
        return None


def fetch_yahoo_futures_curve(
    product_code: str,
    max_contracts: int = 12,
    *,
    now: Optional[datetime] = None,
    download_func: Optional[Any] = None,
) -> Tuple[pd.DataFrame, DataContext]:
    """Build a delayed public futures curve from explicit Yahoo contract symbols.

    Governance:
    - this is a fallback, never described as NBBO or executable;
    - `mark` is the latest public Yahoo close/bar value, not an exchange settlement;
    - exact Last Trade / First Notice dates are intentionally left blank when the public
      download does not supply them;
    - annualized_roll_pct is therefore a *contract-month curve slope proxy*, not a true
      realized roll yield or carry calculation.
    """

    product_code = str(product_code).upper().strip()
    if product_code not in YAHOO_FUTURES_PRODUCTS:
        return pd.DataFrame(), DataContext(
            provider="Yahoo Finance",
            feed="Public futures contract curve",
            status="unavailable",
            recency="DELAYED / PUBLIC",
            message=f"Produit {product_code} non supporté par le fallback Yahoo.",
        )

    candidates = _yahoo_futures_contract_candidates(product_code, now=now)
    # Ask for more symbols than ultimately displayed because distant or newly-listed
    # contracts can legitimately have no public bar yet.
    request_count = min(max(int(max_contracts) * 2, int(max_contracts)), len(candidates))
    requested = candidates[:request_count]
    symbols = [item["ticker"] for item in requested]

    if download_func is None:
        try:
            import yfinance as yf  # type: ignore
        except Exception as exc:
            return pd.DataFrame(), DataContext(
                provider="Yahoo Finance",
                feed="Public futures contract curve",
                status="unavailable",
                recency="DELAYED / PUBLIC",
                message=f"yfinance indisponible: {type(exc).__name__}.",
            )
        download_func = yf.download

    try:
        raw = download_func(
            symbols,
            period="5d",
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=True,
            group_by="ticker",
        )
    except Exception as exc:
        return pd.DataFrame(), DataContext(
            provider="Yahoo Finance",
            feed="Public futures contract curve",
            status="unavailable",
            recency="DELAYED / PUBLIC",
            message=f"Fallback futures Yahoo indisponible: {type(exc).__name__}.",
        )

    rows: List[Dict[str, Any]] = []
    timestamps: List[str] = []
    for contract in requested:
        hist = _extract_yahoo_history(raw, contract["ticker"], symbols)
        if hist.empty or "close" not in hist.columns:
            continue
        close = pd.to_numeric(hist["close"], errors="coerce").dropna()
        if close.empty:
            continue
        last_index = close.index[-1]
        try:
            last_row = hist.loc[last_index]
            if isinstance(last_row, pd.DataFrame):
                last_row = last_row.iloc[-1]
        except Exception:
            last_row = hist.iloc[-1]
        last = _safe_float(close.iloc[-1])
        if not math.isfinite(last) or last <= 0:
            continue
        previous = _safe_float(close.iloc[-2]) if len(close) >= 2 else float("nan")
        change = last - previous if math.isfinite(previous) else float("nan")
        change_pct = last / previous - 1.0 if math.isfinite(previous) and previous != 0 else float("nan")
        stamp = _timestamp_to_iso(last_index)
        if stamp:
            timestamps.append(stamp)
        rows.append(
            {
                "ticker": contract["ticker"],
                "product_code": product_code,
                "name": contract["name"],
                "trading_venue": contract["trading_venue"],
                "contract_month": contract["contract_month"],
                "last_trade_date": pd.NaT,
                "settlement_date": pd.NaT,
                "days_to_maturity": np.nan,
                "tick_size": contract["tick_size"],
                "bid": np.nan,
                "ask": np.nan,
                "bid_size": np.nan,
                "ask_size": np.nan,
                "last": last,
                "mark": last,
                "settlement": np.nan,
                "previous_settlement": np.nan,
                "previous_close": previous if math.isfinite(previous) else np.nan,
                "change": change,
                "change_percent": change_pct,
                "open": _safe_float(last_row.get("open")) if hasattr(last_row, "get") else float("nan"),
                "high": _safe_float(last_row.get("high")) if hasattr(last_row, "get") else float("nan"),
                "low": _safe_float(last_row.get("low")) if hasattr(last_row, "get") else float("nan"),
                "volume": _safe_float(last_row.get("volume")) if hasattr(last_row, "get") else float("nan"),
                "quote_timestamp": stamp,
                "trade_timestamp": stamp,
                "mark_source": "Yahoo public close/bar",
            }
        )

    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame, DataContext(
            provider="Yahoo Finance",
            feed="Public futures contract curve",
            status="unavailable",
            recency="DELAYED / PUBLIC",
            rows=0,
            fallback_used=True,
            message=f"Aucun contrat public Yahoo exploitable trouvé pour {product_code}.",
        )

    frame["contract_month"] = pd.to_datetime(frame["contract_month"], errors="coerce")
    frame = frame.sort_values(["contract_month", "ticker"], na_position="last").head(max(int(max_contracts), 1)).reset_index(drop=True)
    valid = frame["mark"].replace([np.inf, -np.inf], np.nan).dropna()
    if not valid.empty:
        front_idx = valid.index[0]
        front_mark = float(frame.loc[front_idx, "mark"])
        front_month = pd.Timestamp(frame.loc[front_idx, "contract_month"])
        frame["vs_front_pct"] = frame["mark"] / front_mark - 1.0 if front_mark != 0 else np.nan
        tenor = (frame["contract_month"] - front_month).dt.days.astype(float)
        frame["curve_tenor_days"] = tenor
        frame["annualized_roll_pct"] = np.where(
            (tenor > 0) & (front_mark != 0),
            (frame["mark"] / front_mark - 1.0) * 365.0 / tenor,
            np.nan,
        )
    else:
        frame["vs_front_pct"] = np.nan
        frame["curve_tenor_days"] = np.nan
        frame["annualized_roll_pct"] = np.nan

    latest: Optional[str] = None
    if timestamps:
        parsed = pd.to_datetime(pd.Series(timestamps), errors="coerce", utc=True).dropna()
        if not parsed.empty:
            latest = parsed.max().isoformat()
    return frame, DataContext(
        provider="Yahoo Finance",
        feed="Public futures contract curve",
        status="fallback",
        recency="DELAYED / PUBLIC",
        quote_timestamp=latest,
        rows=len(frame),
        pages=1,
        fallback_used=True,
        message=(
            f"Courbe {product_code} reconstruite à partir de contrats Yahoo explicites. "
            "Marks publics retardés; aucun NBBO, settlement officiel ou date Last Trade n'est revendiqué. "
            "La pente annualisée est un proxy par mois de contrat."
        ),
        quality={
            "executable_quotes": False,
            "official_settlement": False,
            "exact_last_trade_dates": False,
            "curve_method": "explicit Yahoo contracts / contract-month slope",
        },
    )
