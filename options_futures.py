# ============================================================
# Options & Futures Intelligence — V2 FUTURES FALLBACK
# Streamlit module for Quant Terminal
# ------------------------------------------------------------
# Public-data derivative proxy using yfinance.
# This is NOT institutional OPRA flow, NOT dealer-positioning truth,
# and NOT investment advice. It is a mechanical diagnostic layer.
# ============================================================

from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

from derivatives_strategy_lab import render_strategy_lab
from derivatives_market_data import (
    DataContext,
    MassiveAPIError,
    ThetaDataAPIError,
    fetch_massive_futures_curve,
    fetch_yahoo_futures_curve,
    fetch_massive_option_chain,
    fetch_massive_option_expirations,
    fetch_thetadata_option_chain,
    fetch_thetadata_option_expirations,
    get_massive_api_key,
    get_thetadata_api_key,
    summarize_chain_quality,
)
from derivatives_workspaces import (
    render_executive_workspace,
    render_export_workspace,
    render_futures_workspace,
    render_gamma_workspace,
    render_positioning_workspace,
    render_surface_workspace,
    render_volatility_workspace,
)


# ============================================================
# Generic helpers
# ============================================================

CONTRACT_SIZE = 100.0
_EPS = 1e-12


def safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        if isinstance(value, (pd.Series, pd.DataFrame, list, tuple, dict)):
            return default
        if pd.isna(value):
            return default
        out = float(value)
        if not np.isfinite(out):
            return default
        return out
    except Exception:
        return default


def safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None:
            return default
        if isinstance(value, (pd.Series, pd.DataFrame, list, tuple, dict)):
            return default
        if pd.isna(value):
            return default
        out = int(value)
        return out
    except Exception:
        return default


def clamp(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    x = safe_float(value, 0.0)
    if x is None:
        x = 0.0
    return max(low, min(high, float(x)))


def fmt_price(value: Any) -> str:
    x = safe_float(value)
    if x is None:
        return "N/A"
    return f"{x:,.2f}"


def fmt_num(value: Any, decimals: int = 2) -> str:
    x = safe_float(value)
    if x is None:
        return "N/A"
    return f"{x:,.{decimals}f}"


def fmt_int(value: Any) -> str:
    x = safe_float(value)
    if x is None:
        return "N/A"
    return f"{int(round(x)):,.0f}"


def fmt_pct(value: Any) -> str:
    x = safe_float(value)
    if x is None:
        return "N/A"
    return f"{x:.2%}"


def fmt_signed_pct(value: Any) -> str:
    x = safe_float(value)
    if x is None:
        return "N/A"
    return f"{x:+.2%}"

def fmt_vol_points(value: Any) -> str:
    x = safe_float(value)
    if x is None:
        return "N/A"
    return f"{x * 100:+.0f} vol pts"

def fmt_score(value: Any) -> str:
    x = safe_float(value)
    if x is None:
        return "N/A"
    return f"{int(round(clamp(x)))}/100"


def fmt_large(value: Any) -> str:
    x = safe_float(value)
    if x is None:
        return "N/A"
    sign = "-" if x < 0 else ""
    x = abs(x)
    if x >= 1_000_000_000_000:
        return f"{sign}{x / 1_000_000_000_000:.2f}T"
    if x >= 1_000_000_000:
        return f"{sign}{x / 1_000_000_000:.2f}B"
    if x >= 1_000_000:
        return f"{sign}{x / 1_000_000:.2f}M"
    if x >= 1_000:
        return f"{sign}{x / 1_000:.2f}K"
    return f"{sign}{x:.2f}"


def clean_ticker_list(raw: str, fallback: Optional[List[str]] = None) -> List[str]:
    fallback = fallback or []
    if not raw:
        return fallback
    parts = []
    for token in str(raw).replace(";", ",").replace("\n", ",").split(","):
        t = token.strip().upper()
        if t:
            parts.append(t)
    out: List[str] = []
    for t in parts:
        if t not in out:
            out.append(t)
    return out or fallback


def normalize_price_frame(price_data: pd.DataFrame) -> pd.DataFrame:
    if price_data is None or price_data.empty:
        return pd.DataFrame()

    df = price_data.copy()
    df.columns = [c[0].lower() if isinstance(c, tuple) else str(c).lower() for c in df.columns]

    rename_map = {
        "datetime": "date",
        "timestamp": "date",
        "adj close": "adj_close",
        "adj_close": "adj_close",
    }
    df = df.rename(columns=rename_map)

    if "date" not in df.columns:
        df = df.reset_index()
        df.columns = [c[0].lower() if isinstance(c, tuple) else str(c).lower() for c in df.columns]
        if "datetime" in df.columns:
            df = df.rename(columns={"datetime": "date"})
        if "index" in df.columns and "date" not in df.columns:
            df = df.rename(columns={"index": "date"})

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.tz_localize(None)
        df = df.dropna(subset=["date"])

    for col in ["open", "high", "low", "close", "adj_close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "close" not in df.columns and "adj_close" in df.columns:
        df["close"] = df["adj_close"]
    if "adj_close" not in df.columns and "close" in df.columns:
        df["adj_close"] = df["close"]

    if "close" in df.columns:
        df = df.dropna(subset=["close"])

    if "date" in df.columns:
        df = df.sort_values("date")

    return df.reset_index(drop=True)


def get_spot(price_data: pd.DataFrame, analysis: Optional[dict] = None) -> Optional[float]:
    analysis = analysis or {}
    for key in ["current_price", "price", "last_price", "spot"]:
        val = safe_float(analysis.get(key))
        if val is not None and val > 0:
            return val
    df = normalize_price_frame(price_data)
    if not df.empty and "close" in df.columns:
        val = safe_float(df["close"].dropna().iloc[-1])
        if val is not None and val > 0:
            return val
    return None


def realized_vol(price_data: pd.DataFrame, window: int = 20) -> Optional[float]:
    df = normalize_price_frame(price_data)
    if df.empty or "adj_close" not in df.columns:
        return None
    ret = np.log(df["adj_close"].astype(float) / df["adj_close"].astype(float).shift(1)).replace([np.inf, -np.inf], np.nan).dropna()
    if len(ret) < max(5, min(window, 10)):
        return None
    use = ret.tail(window)
    vol = safe_float(use.std(ddof=1) * math.sqrt(252))
    return vol


def pct_change_from_series(series: pd.Series, periods: int) -> Optional[float]:
    s = pd.to_numeric(series, errors="coerce").dropna()
    if len(s) <= periods:
        return None
    last = safe_float(s.iloc[-1])
    prev = safe_float(s.iloc[-1 - periods])
    if last is None or prev is None or prev == 0:
        return None
    return (last / prev) - 1.0


def score_label(score: float, low_label: str = "Faible", mid_label: str = "Modéré", high_label: str = "Élevé", very_high_label: str = "Très élevé") -> str:
    s = clamp(score)
    if s >= 80:
        return very_high_label
    if s >= 60:
        return high_label
    if s >= 35:
        return mid_label
    return low_label


def confidence_label(score: float) -> str:
    s = clamp(score)
    if s >= 80:
        return "Solide"
    if s >= 60:
        return "Correcte"
    if s >= 40:
        return "Limitée"
    return "Faible"


def status_from_bool(ok: bool, ok_label: str = "OK", bad_label: str = "Fragile") -> str:
    return ok_label if ok else bad_label


# ============================================================
# Black-Scholes proxy greeks
# ============================================================


def norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_d1(spot: float, strike: float, t: float, r: float, sigma: float, q: float = 0.0) -> Optional[float]:
    if spot <= 0 or strike <= 0 or t <= 0 or sigma <= 0:
        return None
    try:
        return (math.log(spot / strike) + (r - q + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
    except Exception:
        return None


def bs_greeks_proxy(
    spot: float,
    strike: float,
    dte: int,
    iv: float,
    option_type: str,
    r: float = 0.045,
    q: float = 0.0,
) -> Dict[str, Optional[float]]:
    """
    Black-Scholes greeks proxy.

    Prudence :
    - greeks calculés sur IV publique yfinance ;
    - pas une mesure dealer ;
    - vanna/charm sont ajoutés comme proxy descriptif seulement.
    """
    iv = safe_float(iv)
    strike = safe_float(strike)
    spot = safe_float(spot)
    dte = safe_int(dte)

    empty = {
        "delta": None,
        "gamma": None,
        "vega": None,
        "theta": None,
        "vanna": None,
        "charm": None,
    }

    if iv is None or strike is None or spot is None or dte is None:
        return empty

    if iv <= 0 or strike <= 0 or spot <= 0:
        return empty

    t = max(dte / 365.0, 1.0 / 365.0)

    d1 = bs_d1(spot, strike, t, r, iv, q)

    if d1 is None:
        return empty

    d2 = d1 - iv * math.sqrt(t)
    pdf = norm_pdf(d1)

    gamma = math.exp(-q * t) * pdf / max(spot * iv * math.sqrt(t), _EPS)

    # Vega par point de volatilité, cohérent avec le reste du module.
    vega = spot * math.exp(-q * t) * pdf * math.sqrt(t) / 100.0

    if option_type.lower().startswith("c"):
        delta = math.exp(-q * t) * norm_cdf(d1)
        theta = (
            -(spot * math.exp(-q * t) * pdf * iv) / (2 * math.sqrt(t))
            - r * strike * math.exp(-r * t) * norm_cdf(d2)
            + q * spot * math.exp(-q * t) * norm_cdf(d1)
        ) / 365.0
    else:
        delta = -math.exp(-q * t) * norm_cdf(-d1)
        theta = (
            -(spot * math.exp(-q * t) * pdf * iv) / (2 * math.sqrt(t))
            + r * strike * math.exp(-r * t) * norm_cdf(-d2)
            - q * spot * math.exp(-q * t) * norm_cdf(-d1)
        ) / 365.0

    # Vanna proxy : changement de delta pour 1 point de volatilité.
    # Forme classique : dDelta / dVol ≈ -exp(-qT) * pdf(d1) * d2 / sigma.
    # On divise par 100 pour rester en "1 vol point".
    try:
        vanna = -math.exp(-q * t) * pdf * d2 / max(iv, _EPS) / 100.0
    except Exception:
        vanna = None

    # Charm proxy prudent : différence finie du delta sur 1 jour,
    # spot/strike/IV constants.
    charm = None

    try:
        t_next = max((max(dte - 1, 0.5)) / 365.0, 0.5 / 365.0)
        d1_next = bs_d1(spot, strike, t_next, r, iv, q)

        if d1_next is not None:
            if option_type.lower().startswith("c"):
                delta_next = math.exp(-q * t_next) * norm_cdf(d1_next)
            else:
                delta_next = -math.exp(-q * t_next) * norm_cdf(-d1_next)

            charm = delta_next - delta

    except Exception:
        charm = None

    return {
        "delta": delta,
        "gamma": gamma,
        "vega": vega,
        "theta": theta,
        "vanna": vanna,
        "charm": charm,
    }


# ============================================================
# Data access
# ============================================================


@st.cache_data(ttl=900, show_spinner=False)
def get_option_expirations_cached(ticker: str) -> List[str]:
    try:
        tk = yf.Ticker(ticker.upper().strip())
        expirations = list(tk.options or [])
        return [str(x) for x in expirations]
    except Exception:
        return []


@st.cache_data(ttl=300, show_spinner=False)
def get_option_expirations_auto_cached(
    ticker: str,
    _thetadata_api_key: Optional[str],
    _massive_api_key: Optional[str],
) -> Tuple[List[str], Dict[str, Any]]:
    """ThetaData -> Massive -> Yahoo, with explicit provenance at every fallback."""
    provider_errors: List[str] = []
    if _thetadata_api_key:
        try:
            expirations, context = fetch_thetadata_option_expirations(ticker, _thetadata_api_key)
            if expirations:
                return expirations, context.to_dict()
            provider_errors.append(context.message)
        except ThetaDataAPIError as exc:
            provider_errors.append(str(exc))
    if _massive_api_key:
        try:
            expirations, context = fetch_massive_option_expirations(ticker, _massive_api_key)
            if expirations:
                context = DataContext(**{**context.to_dict(), "fallback_used": bool(_thetadata_api_key)})
                return expirations, context.to_dict()
            provider_errors.append(context.message)
        except MassiveAPIError as exc:
            provider_errors.append(str(exc))
    expirations = get_option_expirations_cached(ticker)
    upstream_configured = bool(_thetadata_api_key or _massive_api_key)
    detail = " ".join(dict.fromkeys(error for error in provider_errors if error))
    context = DataContext(
        provider="Yahoo Finance",
        feed="Public options reference",
        status="fallback" if expirations else "unavailable",
        recency="UNSPECIFIED / DELAYED",
        rows=len(expirations),
        fallback_used=upstream_configured,
        message=("Fallback Yahoo. " + detail).strip() if upstream_configured else "Expirations publiques; récence non garantie.",
    )
    return expirations, context.to_dict()


def days_to_expiration(expiration: str) -> int:
    try:
        exp_dt = pd.to_datetime(expiration).to_pydatetime().replace(tzinfo=None)
        now = datetime.utcnow().replace(tzinfo=None)
        return max(int((exp_dt.date() - now.date()).days), 0)
    except Exception:
        return 0


def select_default_expiration_index(expirations: List[str], min_dte: int = 5) -> int:
    """
    Sélection prudente par défaut :
    - évite les 0DTE / 1DTE / 2DTE si possible ;
    - prend la première expiration avec DTE >= min_dte ;
    - fallback index 0 si aucune expiration ne respecte le seuil.
    """
    if not expirations:
        return 0

    for i, exp in enumerate(expirations):
        if days_to_expiration(str(exp)) >= min_dte:
            return i

    return 0


def is_short_dte(dte: Any, threshold: int = 3) -> bool:
    x = safe_int(dte, 0)
    return bool(x is not None and x < threshold)



@st.cache_data(ttl=900, show_spinner=False)
def get_option_chain_cached(ticker: str, expiration: str) -> Tuple[pd.DataFrame, pd.DataFrame, str]:
    try:
        tk = yf.Ticker(ticker.upper().strip())
        chain = tk.option_chain(expiration)
        calls = chain.calls.copy() if chain.calls is not None else pd.DataFrame()
        puts = chain.puts.copy() if chain.puts is not None else pd.DataFrame()
        return calls, puts, "OK"
    except Exception as exc:
        return pd.DataFrame(), pd.DataFrame(), f"Erreur option chain: {exc}"


@st.cache_data(ttl=20, show_spinner=False)
def get_option_chain_auto_cached(
    ticker: str,
    expiration: str,
    _thetadata_api_key: Optional[str],
    _massive_api_key: Optional[str],
) -> Tuple[pd.DataFrame, pd.DataFrame, str, Dict[str, Any]]:
    """Primary ThetaData OPRA snapshot, then Massive, then public Yahoo fallback."""
    provider_errors: List[str] = []
    if _thetadata_api_key:
        try:
            calls, puts, context = fetch_thetadata_option_chain(ticker, expiration, _thetadata_api_key)
            if not calls.empty or not puts.empty:
                return calls, puts, "OK", context.to_dict()
            provider_errors.append(context.message)
        except ThetaDataAPIError as exc:
            provider_errors.append(str(exc))

    if _massive_api_key:
        try:
            calls, puts, context = fetch_massive_option_chain(ticker, expiration, _massive_api_key)
            if not calls.empty or not puts.empty:
                values = context.to_dict()
                values["fallback_used"] = bool(_thetadata_api_key)
                if provider_errors:
                    values["message"] = (values.get("message", "") + " Repli après ThetaData: " + " ".join(dict.fromkeys(provider_errors))).strip()
                return calls, puts, "OK", values
            provider_errors.append(context.message)
        except MassiveAPIError as exc:
            provider_errors.append(str(exc))

    calls, puts, status = get_option_chain_cached(ticker, expiration)
    combined = pd.concat(
        [frame for frame in (calls, puts) if frame is not None and not frame.empty],
        ignore_index=True,
    ) if not (calls.empty and puts.empty) else pd.DataFrame()
    quality = summarize_chain_quality(combined)
    upstream_configured = bool(_thetadata_api_key or _massive_api_key)
    detail = " ".join(dict.fromkeys(error for error in provider_errors if error))
    context = DataContext(
        provider="Yahoo Finance",
        feed="Public options chain",
        status="fallback" if status == "OK" else "unavailable",
        recency="UNSPECIFIED / DELAYED",
        rows=len(combined),
        fallback_used=upstream_configured,
        message=("Fallback Yahoo. " + detail).strip() if upstream_configured else "Chaîne publique; récence et NBBO non garantis.",
        quality=quality,
    )
    return calls, puts, status, context.to_dict()


@st.cache_data(ttl=30, show_spinner=False)
def fetch_surface_auto_cached(
    ticker: str,
    expirations: Tuple[str, ...],
    _thetadata_api_key: Optional[str],
    _massive_api_key: Optional[str],
) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    for expiration in expirations:
        calls, puts, status, _ = get_option_chain_auto_cached(
            ticker, expiration, _thetadata_api_key, _massive_api_key
        )
        if status != "OK":
            continue
        for kind, frame in (("call", calls), ("put", puts)):
            if frame is None or frame.empty:
                continue
            work = frame.copy()
            work["option_type"] = kind
            work["expiration"] = str(expiration)
            work["dte"] = days_to_expiration(str(expiration))
            frames.append(work)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


@st.cache_data(ttl=60, show_spinner=False)
def get_futures_curve_auto_cached(
    product_code: str,
    _massive_api_key: Optional[str],
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Prefer licensed Massive futures snapshots, then reconstruct a public Yahoo curve."""
    provider_errors: List[str] = []

    if _massive_api_key:
        try:
            frame, context = fetch_massive_futures_curve(product_code, _massive_api_key)
            if frame is not None and not frame.empty:
                return frame, context.to_dict()
            if context.message:
                provider_errors.append(context.message)
        except MassiveAPIError as exc:
            provider_errors.append(str(exc))
    else:
        provider_errors.append("Clé Massive absente.")

    yahoo_frame, yahoo_context = fetch_yahoo_futures_curve(product_code, max_contracts=12)
    values = yahoo_context.to_dict()
    values["fallback_used"] = True
    if provider_errors:
        detail = " ".join(dict.fromkeys(error for error in provider_errors if error))
        values["message"] = (str(values.get("message") or "") + " Repli après Massive: " + detail).strip()
    return yahoo_frame, values


@st.cache_data(ttl=900, show_spinner=False)
def get_history_cached(symbol: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
    try:
        df = yf.download(symbol, period=period, interval=interval, auto_adjust=False, progress=False, threads=False)
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.reset_index()
        df.columns = [c[0].lower() if isinstance(c, tuple) else str(c).lower() for c in df.columns]
        df = df.rename(columns={"datetime": "date", "adj close": "adj_close"})
        if "date" not in df.columns and "index" in df.columns:
            df = df.rename(columns={"index": "date"})
        if "close" not in df.columns and "adj_close" in df.columns:
            df["close"] = df["adj_close"]
        if "adj_close" not in df.columns and "close" in df.columns:
            df["adj_close"] = df["close"]
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.tz_localize(None)
        for c in ["open", "high", "low", "close", "adj_close", "volume"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=900, show_spinner=False)
def fetch_surface_cached(ticker: str, expirations: Tuple[str, ...], pause_sec: float = 0.02) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    for exp in expirations:
        calls, puts, status = get_option_chain_cached(ticker, exp)
        if status != "OK":
            continue
        dte = days_to_expiration(exp)
        for opt_type, raw in [("call", calls), ("put", puts)]:
            if raw is None or raw.empty:
                continue
            df = raw.copy()
            df["option_type"] = opt_type
            df["expiration"] = exp
            df["dte"] = dte
            frames.append(df)
        if pause_sec > 0:
            time.sleep(float(pause_sec))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


# ============================================================
# Options cleaning and metrics
# ============================================================


def clean_chain(raw: pd.DataFrame, option_type: str, expiration: str, spot: float) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()

    df = raw.copy()
    df.columns = [str(c).strip() for c in df.columns]

    for col in ["strike", "lastPrice", "bid", "ask", "change", "percentChange", "volume", "openInterest", "impliedVolatility"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    dte = days_to_expiration(expiration)
    df["option_type"] = option_type
    df["expiration"] = expiration
    df["dte"] = dte
    df["mid"] = np.where(
        (df.get("bid", 0).fillna(0) > 0) & (df.get("ask", 0).fillna(0) > 0),
        (df.get("bid", 0).fillna(0) + df.get("ask", 0).fillna(0)) / 2.0,
        df.get("lastPrice", np.nan),
    )
    df["spread"] = df.get("ask", np.nan) - df.get("bid", np.nan)
    df["spread_pct"] = df["spread"] / df["mid"].replace(0, np.nan)
    df["distance_spot"] = df["strike"] / max(spot, _EPS) - 1.0
    df["moneyness"] = df["strike"] / max(spot, _EPS)
    df["notional_oi"] = df.get("openInterest", 0).fillna(0) * df["strike"] * CONTRACT_SIZE
    df["dollar_volume"] = df.get("volume", 0).fillna(0) * df["mid"].fillna(0) * CONTRACT_SIZE

    iv = pd.to_numeric(df.get("impliedVolatility", np.nan), errors="coerce")
    # yfinance IV is decimal. Very large bad prints are clipped.
    df["iv"] = iv.where((iv > 0) & (iv < 5), np.nan)

    greek_rows = []
    for _, row in df.iterrows():
        greek_rows.append(bs_greeks_proxy(spot, safe_float(row.get("strike"), 0.0) or 0.0, dte, safe_float(row.get("iv"), 0.0) or 0.0, option_type))
    if greek_rows:
        gdf = pd.DataFrame(greek_rows)
        for c in gdf.columns:
            df[c] = gdf[c].values

    # Signed gamma scenario convention: calls positive, puts negative.
    # Prefer vendor gamma when present, but preserve the explicit convention warning elsewhere.
    gamma_model = pd.to_numeric(df.get("gamma", pd.Series(index=df.index, dtype=float)), errors="coerce")
    gamma_vendor = pd.to_numeric(df.get("gamma_vendor", pd.Series(index=df.index, dtype=float)), errors="coerce")
    gamma_effective = gamma_vendor.combine_first(gamma_model).fillna(0.0)
    sign = 1.0 if option_type == "call" else -1.0
    df["gex_proxy"] = sign * gamma_effective * df.get("openInterest", 0).fillna(0) * CONTRACT_SIZE * (spot ** 2) * 0.01

    return df.replace([np.inf, -np.inf], np.nan)


def merge_chain_for_display(calls: pd.DataFrame, puts: pd.DataFrame, spot: float, window_pct: float) -> pd.DataFrame:
    c = calls.copy() if calls is not None else pd.DataFrame()
    p = puts.copy() if puts is not None else pd.DataFrame()

    low = spot * (1.0 - window_pct)
    high = spot * (1.0 + window_pct)
    if not c.empty:
        c = c[(c["strike"] >= low) & (c["strike"] <= high)].copy()
    if not p.empty:
        p = p[(p["strike"] >= low) & (p["strike"] <= high)].copy()

    c_cols = ["strike", "lastPrice", "bid", "ask", "mid", "volume", "openInterest", "iv", "delta", "gamma", "gex_proxy"]
    p_cols = ["strike", "lastPrice", "bid", "ask", "mid", "volume", "openInterest", "iv", "delta", "gamma", "gex_proxy"]
    c = c[[x for x in c_cols if x in c.columns]].rename(columns={
        "lastPrice": "call_last", "bid": "call_bid", "ask": "call_ask", "mid": "call_mid",
        "volume": "call_vol", "openInterest": "call_oi", "iv": "call_iv",
        "delta": "call_delta", "gamma": "call_gamma", "gex_proxy": "call_gex_proxy",
    })
    p = p[[x for x in p_cols if x in p.columns]].rename(columns={
        "lastPrice": "put_last", "bid": "put_bid", "ask": "put_ask", "mid": "put_mid",
        "volume": "put_vol", "openInterest": "put_oi", "iv": "put_iv",
        "delta": "put_delta", "gamma": "put_gamma", "gex_proxy": "put_gex_proxy",
    })
    if c.empty and p.empty:
        return pd.DataFrame()
    if c.empty:
        out = p
    elif p.empty:
        out = c
    else:
        out = pd.merge(c, p, on="strike", how="outer")
    out["distance_spot"] = out["strike"] / max(spot, _EPS) - 1.0
    return out.sort_values("strike").reset_index(drop=True)


def liquid_iv_view(
    df: pd.DataFrame,
    spot: float,
    window_pct: float = 0.25,
    min_oi: int = 10,
    min_volume: int = 1,
    max_spread_pct: float = 1.00,
    min_iv: float = 0.03,
    max_iv: float = 3.00,
) -> pd.DataFrame:
    """
    Filtre prudent pour les graphiques IV / smile.
    Ne doit pas être utilisé pour supprimer les OI/walls/max pain.
    Objectif : éviter les IV absurdes sur strikes illiquides.
    """
    if df is None or df.empty:
        return pd.DataFrame()

    out = df.copy()

    for col in ["strike", "iv", "volume", "openInterest", "spread_pct"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    if "strike" not in out.columns or "iv" not in out.columns:
        return pd.DataFrame()

    out = out[
        (out["strike"] >= spot * (1.0 - window_pct))
        & (out["strike"] <= spot * (1.0 + window_pct))
        & (out["iv"] >= min_iv)
        & (out["iv"] <= max_iv)
    ].copy()

    if "spread_pct" in out.columns:
        out = out[(out["spread_pct"].isna()) | (out["spread_pct"] <= max_spread_pct)]

    if "openInterest" in out.columns and "volume" in out.columns:
        out = out[
            (out["openInterest"].fillna(0) >= min_oi)
            | (out["volume"].fillna(0) >= min_volume)
        ]

    return out.sort_values("strike").reset_index(drop=True)


def nearest_row(df: pd.DataFrame, strike_target: float) -> pd.Series:
    if df is None or df.empty or "strike" not in df.columns:
        return pd.Series(dtype=float)
    work = df.copy()
    work["_dist"] = (work["strike"] - strike_target).abs()
    idx = work["_dist"].idxmin()
    return work.loc[idx]


def weighted_avg(series: pd.Series, weights: pd.Series) -> Optional[float]:
    s = pd.to_numeric(series, errors="coerce")
    w = pd.to_numeric(weights, errors="coerce").fillna(0)
    mask = s.notna() & w.notna() & (w > 0)
    if not mask.any():
        return safe_float(s.dropna().mean())
    return safe_float(np.average(s[mask], weights=w[mask]))


def compute_max_pain(calls: pd.DataFrame, puts: pd.DataFrame) -> Tuple[Optional[float], pd.DataFrame]:
    if (calls is None or calls.empty) and (puts is None or puts.empty):
        return None, pd.DataFrame()

    strikes = []
    if calls is not None and not calls.empty:
        strikes.extend(pd.to_numeric(calls["strike"], errors="coerce").dropna().tolist())
    if puts is not None and not puts.empty:
        strikes.extend(pd.to_numeric(puts["strike"], errors="coerce").dropna().tolist())
    strikes = sorted(set([float(x) for x in strikes if np.isfinite(x)]))
    if not strikes:
        return None, pd.DataFrame()

    c_strikes = pd.to_numeric(calls.get("strike", pd.Series(dtype=float)), errors="coerce") if calls is not None and not calls.empty else pd.Series(dtype=float)
    c_oi = pd.to_numeric(calls.get("openInterest", pd.Series(dtype=float)), errors="coerce").fillna(0) if calls is not None and not calls.empty else pd.Series(dtype=float)
    p_strikes = pd.to_numeric(puts.get("strike", pd.Series(dtype=float)), errors="coerce") if puts is not None and not puts.empty else pd.Series(dtype=float)
    p_oi = pd.to_numeric(puts.get("openInterest", pd.Series(dtype=float)), errors="coerce").fillna(0) if puts is not None and not puts.empty else pd.Series(dtype=float)

    rows = []
    for s in strikes:
        call_payout = np.maximum(s - c_strikes, 0) * c_oi * CONTRACT_SIZE if len(c_strikes) else 0
        put_payout = np.maximum(p_strikes - s, 0) * p_oi * CONTRACT_SIZE if len(p_strikes) else 0
        total = safe_float(np.nansum(call_payout) + np.nansum(put_payout), 0.0)
        rows.append({"strike": s, "total_payout": total})
    df = pd.DataFrame(rows)
    if df.empty:
        return None, df
    mp = safe_float(df.loc[df["total_payout"].idxmin(), "strike"])
    return mp, df


def compute_gex_by_strike(calls: pd.DataFrame, puts: pd.DataFrame, spot: float) -> pd.DataFrame:
    frames = []
    for df in [calls, puts]:
        if df is not None and not df.empty and "strike" in df.columns and "gex_proxy" in df.columns:
            frames.append(df[["strike", "gex_proxy", "option_type", "openInterest", "volume", "iv"]].copy())
    if not frames:
        return pd.DataFrame()
    allg = pd.concat(frames, ignore_index=True)
    grp = allg.groupby("strike", as_index=False).agg(
        signed_gex=("gex_proxy", "sum"),
        abs_gex=("gex_proxy", lambda s: float(np.nansum(np.abs(s)))),
        total_oi=("openInterest", "sum"),
        total_vol=("volume", "sum"),
        avg_iv=("iv", "mean"),
    )
    grp = grp.sort_values("strike").reset_index(drop=True)
    grp["cum_gex"] = grp["signed_gex"].cumsum()
    grp["distance_spot"] = grp["strike"] / max(spot, _EPS) - 1.0
    return grp


def gamma_flip_level(
    gex_df: pd.DataFrame,
    spot: Optional[float] = None,
    max_distance: float = 0.15,
    min_abs_gex_ratio: float = 0.005,
) -> Optional[float]:
    """
    Gamma flip prudent :
    - cherche un vrai changement de signe du cumulative GEX ;
    - ignore les zones presque nulles avant le vrai signal ;
    - privilégie le flip le plus proche du spot ;
    - évite les niveaux trop éloignés.
    """
    if gex_df is None or gex_df.empty or "signed_gex" not in gex_df.columns or "strike" not in gex_df.columns:
        return None

    df = gex_df[["strike", "signed_gex"]].copy()
    df["strike"] = pd.to_numeric(df["strike"], errors="coerce")
    df["signed_gex"] = pd.to_numeric(df["signed_gex"], errors="coerce").fillna(0.0)
    df = df.dropna(subset=["strike"]).sort_values("strike").reset_index(drop=True)

    if df.empty or len(df) < 3:
        return None

    spot_val = safe_float(spot)
    if spot_val is not None and spot_val > 0:
        low = spot_val * (1.0 - max_distance)
        high = spot_val * (1.0 + max_distance)
        df = df[(df["strike"] >= low) & (df["strike"] <= high)].copy().reset_index(drop=True)

    if df.empty or len(df) < 3:
        return None

    abs_total = safe_float(np.nansum(np.abs(df["signed_gex"])), 0.0) or 0.0
    if abs_total <= 0:
        return None

    threshold = abs_total * min_abs_gex_ratio
    df["cum_gex_local"] = df["signed_gex"].cumsum()

    strikes = df["strike"].to_numpy(dtype=float)
    cums = df["cum_gex_local"].to_numpy(dtype=float)

    signs = np.zeros(len(cums), dtype=int)
    signs[cums > threshold] = 1
    signs[cums < -threshold] = -1

    candidates = []
    last_idx = None
    last_sign = 0

    for i, sign in enumerate(signs):
        if sign == 0:
            continue

        if last_idx is None:
            last_idx = i
            last_sign = sign
            continue

        if sign != last_sign:
            x0, x1 = strikes[last_idx], strikes[i]
            y0, y1 = cums[last_idx], cums[i]

            if abs(y1 - y0) > _EPS:
                # interpolation linéaire du passage par zéro
                flip = x0 - y0 * (x1 - x0) / (y1 - y0)
            else:
                flip = (x0 + x1) / 2.0

            candidates.append(float(flip))

        last_idx = i
        last_sign = sign

    if not candidates:
        return None

    if spot_val is not None and spot_val > 0:
        candidates = [
            x for x in candidates
            if spot_val * (1.0 - max_distance) <= x <= spot_val * (1.0 + max_distance)
        ]
        if not candidates:
            return None
        return safe_float(min(candidates, key=lambda x: abs(x - spot_val)))

    return safe_float(candidates[0])


def compute_options_metrics(calls: pd.DataFrame, puts: pd.DataFrame, spot: float, dte: int, price_data: pd.DataFrame) -> Dict[str, Any]:
    rv20 = realized_vol(price_data, 20)
    rv60 = realized_vol(price_data, 60)
    rv90 = realized_vol(price_data, 90)

    atm_call = nearest_row(calls, spot)
    atm_put = nearest_row(puts, spot)
    atm_call_iv = safe_float(atm_call.get("iv")) if not atm_call.empty else None
    atm_put_iv = safe_float(atm_put.get("iv")) if not atm_put.empty else None
    atm_values = [x for x in [atm_call_iv, atm_put_iv] if x is not None]
    atm_iv = safe_float(np.nanmean(atm_values)) if atm_values else None

    call_vol = safe_float(pd.to_numeric(calls.get("volume", pd.Series(dtype=float)), errors="coerce").fillna(0).sum(), 0.0) if calls is not None and not calls.empty else 0.0
    put_vol = safe_float(pd.to_numeric(puts.get("volume", pd.Series(dtype=float)), errors="coerce").fillna(0).sum(), 0.0) if puts is not None and not puts.empty else 0.0
    call_oi = safe_float(pd.to_numeric(calls.get("openInterest", pd.Series(dtype=float)), errors="coerce").fillna(0).sum(), 0.0) if calls is not None and not calls.empty else 0.0
    put_oi = safe_float(pd.to_numeric(puts.get("openInterest", pd.Series(dtype=float)), errors="coerce").fillna(0).sum(), 0.0) if puts is not None and not puts.empty else 0.0

    pcr_vol = put_vol / call_vol if call_vol and call_vol > 0 else None
    pcr_oi = put_oi / call_oi if call_oi and call_oi > 0 else None

    call_wall = None
    put_wall = None
    if calls is not None and not calls.empty and "openInterest" in calls.columns:
        tmp = calls.dropna(subset=["strike"]).copy()
        tmp["openInterest"] = pd.to_numeric(tmp["openInterest"], errors="coerce").fillna(0)
        if not tmp.empty and tmp["openInterest"].max() > 0:
            call_wall = safe_float(tmp.loc[tmp["openInterest"].idxmax(), "strike"])
    if puts is not None and not puts.empty and "openInterest" in puts.columns:
        tmp = puts.dropna(subset=["strike"]).copy()
        tmp["openInterest"] = pd.to_numeric(tmp["openInterest"], errors="coerce").fillna(0)
        if not tmp.empty and tmp["openInterest"].max() > 0:
            put_wall = safe_float(tmp.loc[tmp["openInterest"].idxmax(), "strike"])

    max_pain, max_pain_df = compute_max_pain(calls, puts)
    gex_df = compute_gex_by_strike(calls, puts, spot)
    gamma_flip = gamma_flip_level(gex_df, spot=spot, max_distance=0.15)
    net_gex = safe_float(gex_df["signed_gex"].sum(), 0.0) if not gex_df.empty else None
    abs_gex = safe_float(gex_df["abs_gex"].sum(), 0.0) if not gex_df.empty else None

    put_10 = nearest_row(puts, spot * 0.90)
    call_10 = nearest_row(calls, spot * 1.10)
    put_wing_iv = safe_float(put_10.get("iv")) if not put_10.empty else None
    call_wing_iv = safe_float(call_10.get("iv")) if not call_10.empty else None
    skew_10 = None
    if put_wing_iv is not None and call_wing_iv is not None:
        skew_10 = put_wing_iv - call_wing_iv

    expected_move_pct = None
    expected_move_price = None

    # Prudence : sur 0DTE / 1DTE, l'expected move annualisé via IV publique est souvent instable.
    if atm_iv is not None and dte >= 2:
        expected_move_pct = atm_iv * math.sqrt(max(dte, 1) / 365.0)
        expected_move_price = spot * expected_move_pct

    iv_premium_20 = None
    if atm_iv is not None and rv20 is not None and rv20 > 0:
        iv_premium_20 = atm_iv / rv20 - 1.0

    spread_quality = None
    spreads = []
    for df in [calls, puts]:
        if df is not None and not df.empty and "spread_pct" in df.columns:
            atm_window = df[(df["strike"] >= spot * 0.9) & (df["strike"] <= spot * 1.1)]
            spreads.extend(pd.to_numeric(atm_window["spread_pct"], errors="coerce").dropna().clip(lower=0, upper=5).tolist())
    if spreads:
        med_spread = safe_float(np.nanmedian(spreads))
        if med_spread is not None:
            spread_quality = 100 - clamp(med_spread * 300, 0, 100)

    volume_quality = clamp(np.log1p((call_vol or 0) + (put_vol or 0)) / np.log1p(100_000) * 100) if (call_vol or put_vol) else 20
    oi_quality = clamp(np.log1p((call_oi or 0) + (put_oi or 0)) / np.log1p(500_000) * 100) if (call_oi or put_oi) else 20
    iv_quality = 100 if atm_iv is not None else 35
    dte_quality = 100 if dte >= 7 else 55
    spread_q = spread_quality if spread_quality is not None else 55
    confidence = clamp(0.28 * volume_quality + 0.28 * oi_quality + 0.22 * iv_quality + 0.12 * dte_quality + 0.10 * spread_q)

    # Pénalité de confiance sur expirations très courtes.
    if dte < 3:
        confidence = min(confidence, 55.0)
    if dte == 0:
        confidence = min(confidence, 45.0)

    # Scores are risk scores: higher = more risk / more caution.
    iv_premium_score = 50
    if iv_premium_20 is not None:
        iv_premium_score = clamp(50 + iv_premium_20 * 80)

    pcr_score = 45
    if pcr_vol is not None:
        pcr_score += clamp((pcr_vol - 0.7) * 45, -20, 35)
    if pcr_oi is not None:
        pcr_score += clamp((pcr_oi - 0.8) * 35, -15, 30)
    pcr_score = clamp(pcr_score)

    skew_score = 40
    if skew_10 is not None:
        skew_score = clamp(45 + skew_10 * 250)

    gamma_score = 35
    if abs_gex is not None and abs_gex > 0:
        gamma_score = clamp(np.log1p(abs_gex) / np.log1p(1_000_000_000) * 80)
    if call_wall is not None and abs(call_wall / spot - 1.0) < 0.025:
        gamma_score += 10
    if put_wall is not None and abs(put_wall / spot - 1.0) < 0.025:
        gamma_score += 10
    gamma_score = clamp(gamma_score)

    options_risk_score = clamp(
        0.30 * iv_premium_score
        + 0.25 * pcr_score
        + 0.22 * skew_score
        + 0.23 * gamma_score
    )

    # Floor prudent : si la concentration gamma est élevée, le risque options ne doit pas rester "Faible".
    if gamma_score >= 80:
        options_risk_score = max(options_risk_score, 55)
    elif gamma_score >= 70:
        options_risk_score = max(options_risk_score, 45)

    options_risk_score = clamp(options_risk_score)
    options_state = score_label(options_risk_score)

    if dte < 3:
        state_reason = "Expiration très courte : IV, expected move et gamma peuvent être instables. Lecture surtout utile pour OI/walls/futures." 
    elif atm_iv is None:
        state_reason = "IV ATM indisponible : lecture limitée à volume / OI."
    elif iv_premium_20 is not None and iv_premium_20 > 0.35:
        state_reason = "Prime d'IV élevée vs volatilité réalisée : risque de compression de volatilité."
    elif pcr_vol is not None and pcr_vol > 1.1:
        state_reason = "Put/Call volume élevé : demande de protection supérieure à la normale."
    elif skew_10 is not None and skew_10 > 0.08:
        state_reason = "Skew défensif : les puts de protection sont plus chers que les calls comparables."
    elif gamma_score >= 70:
        state_reason = "Options tape exploitable : pas de stress extrême, mais concentration gamma/OI à surveiller autour des walls."
    elif gamma_score >= 60:
        state_reason = "Concentration gamma/OI notable : surveiller le risque de pinning autour des principaux walls."
    elif call_wall is not None and spot < call_wall and abs(call_wall / spot - 1.0) < 0.05:
        state_reason = "Call wall proche : résistance / zone de pinning possible."
    else:
        state_reason = "Options tape exploitable : pas de stress dérivé extrême détecté."

    return {
        "spot": spot,
        "dte": dte,
        "rv20": rv20,
        "rv60": rv60,
        "rv90": rv90,
        "atm_call_iv": atm_call_iv,
        "atm_put_iv": atm_put_iv,
        "atm_iv": atm_iv,
        "iv_premium_20": iv_premium_20,
        "expected_move_pct": expected_move_pct,
        "expected_move_price": expected_move_price,
        "put_wing_iv": put_wing_iv,
        "call_wing_iv": call_wing_iv,
        "skew_10": skew_10,
        "call_vol": call_vol,
        "put_vol": put_vol,
        "call_oi": call_oi,
        "put_oi": put_oi,
        "pcr_vol": pcr_vol,
        "pcr_oi": pcr_oi,
        "call_wall": call_wall,
        "put_wall": put_wall,
        "max_pain": max_pain,
        "max_pain_df": max_pain_df,
        "gex_df": gex_df,
        "net_gex": net_gex,
        "abs_gex": abs_gex,
        "gamma_flip": gamma_flip,
        "iv_premium_score": iv_premium_score,
        "pcr_score": pcr_score,
        "skew_score": skew_score,
        "gamma_score": gamma_score,
        "options_risk_score": options_risk_score,
        "options_state": options_state,
        "confidence": confidence,
        "confidence_label": confidence_label(confidence),
        "state_reason": state_reason,
    }


def compute_term_structure(surface: pd.DataFrame, spot: float) -> pd.DataFrame:
    if surface is None or surface.empty:
        return pd.DataFrame()
    df = surface.copy()
    for col in ["strike", "impliedVolatility", "volume", "openInterest"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["iv"] = df["impliedVolatility"].where((df["impliedVolatility"] > 0) & (df["impliedVolatility"] < 5), np.nan)
    rows = []
    for exp, g in df.groupby("expiration"):
        dte = safe_int(g["dte"].dropna().iloc[0]) if "dte" in g.columns and not g["dte"].dropna().empty else days_to_expiration(str(exp))
        if dte is None:
            dte = 0
        g = g.dropna(subset=["strike"])
        if g.empty:
            continue
        g["dist"] = (g["strike"] - spot).abs()
        near = g.nsmallest(6, "dist")
        atm_iv = weighted_avg(near["iv"], near.get("openInterest", pd.Series([1] * len(near))))
        total_oi = safe_float(pd.to_numeric(g.get("openInterest", pd.Series(dtype=float)), errors="coerce").fillna(0).sum(), 0.0)
        total_vol = safe_float(pd.to_numeric(g.get("volume", pd.Series(dtype=float)), errors="coerce").fillna(0).sum(), 0.0)
        exp_move = atm_iv * math.sqrt(max(dte, 1) / 365.0) if atm_iv is not None else None
        rows.append({
            "expiration": str(exp),
            "dte": dte,
            "atm_iv": atm_iv,
            "expected_move_pct": exp_move,
            "expected_move_price": spot * exp_move if exp_move is not None else None,
            "total_oi": total_oi,
            "total_volume": total_vol,
        })
    return pd.DataFrame(rows).sort_values("dte").reset_index(drop=True)


# ============================================================
# Futures / macro tape
# ============================================================


DEFAULT_FUTURES_SYMBOLS = {
    "NQ=F": {"name": "Nasdaq 100 Fut", "type": "Equity future", "risk_role": "risk_on"},
    "ES=F": {"name": "S&P 500 Fut", "type": "Equity future", "risk_role": "risk_on"},
    "YM=F": {"name": "Dow Fut", "type": "Equity future", "risk_role": "risk_on"},
    "RTY=F": {"name": "Russell Fut", "type": "Equity future", "risk_role": "risk_on"},
    "^VIX": {"name": "VIX", "type": "Volatility", "risk_role": "risk_off"},
    "^TNX": {"name": "US 10Y Yield", "type": "Rates", "risk_role": "pressure_up"},
    "DX-Y.NYB": {"name": "Dollar Index", "type": "FX", "risk_role": "pressure_up"},
    "CL=F": {"name": "Crude Oil", "type": "Commodity", "risk_role": "mixed"},
    "GC=F": {"name": "Gold", "type": "Commodity", "risk_role": "mixed"},
    "QQQ": {"name": "Nasdaq ETF", "type": "ETF", "risk_role": "risk_on"},
    "SPY": {"name": "S&P ETF", "type": "ETF", "risk_role": "risk_on"},
    "SMH": {"name": "Semis ETF", "type": "Sector ETF", "risk_role": "risk_on"},
    "SOXX": {"name": "Semis ETF", "type": "Sector ETF", "risk_role": "risk_on"},
}


def default_macro_universe(ticker: str) -> List[str]:
    t = ticker.upper().strip()
    base = ["NQ=F", "ES=F", "^VIX", "^TNX", "DX-Y.NYB", "QQQ", "SPY", "SMH", "SOXX"]
    if t not in base:
        return base
    return base


def compute_beta(target_df: pd.DataFrame, factor_df: pd.DataFrame, lookback: int = 90) -> Optional[float]:
    if target_df is None or target_df.empty or factor_df is None or factor_df.empty:
        return None
    t = normalize_price_frame(target_df)
    f = normalize_price_frame(factor_df)
    if t.empty or f.empty or "date" not in t.columns or "date" not in f.columns:
        return None
    tr = t[["date", "adj_close"]].copy()
    fr = f[["date", "adj_close"]].copy()
    tr["target_ret"] = np.log(tr["adj_close"] / tr["adj_close"].shift(1))
    fr["factor_ret"] = np.log(fr["adj_close"] / fr["adj_close"].shift(1))
    merged = pd.merge(tr[["date", "target_ret"]], fr[["date", "factor_ret"]], on="date", how="inner").dropna()
    if len(merged) < 20:
        return None
    merged = merged.tail(lookback)
    var = safe_float(merged["factor_ret"].var(ddof=1))
    cov = safe_float(merged[["target_ret", "factor_ret"]].cov().iloc[0, 1])
    if var is None or cov is None or abs(var) < _EPS:
        return None
    return cov / var


def compute_corr(target_df: pd.DataFrame, factor_df: pd.DataFrame, lookback: int = 90) -> Optional[float]:
    if target_df is None or target_df.empty or factor_df is None or factor_df.empty:
        return None
    t = normalize_price_frame(target_df)
    f = normalize_price_frame(factor_df)
    if t.empty or f.empty or "date" not in t.columns or "date" not in f.columns:
        return None
    tr = t[["date", "adj_close"]].copy()
    fr = f[["date", "adj_close"]].copy()
    tr["target_ret"] = np.log(tr["adj_close"] / tr["adj_close"].shift(1))
    fr["factor_ret"] = np.log(fr["adj_close"] / fr["adj_close"].shift(1))
    merged = pd.merge(tr[["date", "target_ret"]], fr[["date", "factor_ret"]], on="date", how="inner").dropna()
    if len(merged) < 20:
        return None
    merged = merged.tail(lookback)
    return safe_float(merged["target_ret"].corr(merged["factor_ret"]))


def compute_macro_tape(ticker: str, price_data: pd.DataFrame, symbols: List[str], period: str = "6mo") -> Tuple[pd.DataFrame, Dict[str, Any]]:
    target_df = normalize_price_frame(price_data)
    rows = []
    score_components = []
    pressure_notes = []

    for sym in symbols:
        hist = get_history_cached(sym, period=period, interval="1d")
        if hist is None or hist.empty:
            rows.append({
                "Instrument": DEFAULT_FUTURES_SYMBOLS.get(sym, {}).get("name", sym),
                "Ticker": sym,
                "Type": DEFAULT_FUTURES_SYMBOLS.get(sym, {}).get("type", "Proxy"),
                "Last": None,
                "1D": None,
                "5D": None,
                "20D": None,
                "Vol 20D": None,
                "Beta ticker": None,
                "Corr": None,
                "Regime": "Données absentes",
                "Lecture": "Téléchargement indisponible ou série vide.",
            })
            continue

        close = hist["adj_close"] if "adj_close" in hist.columns else hist["close"]
        last = safe_float(close.dropna().iloc[-1]) if not close.dropna().empty else None
        r1 = pct_change_from_series(close, 1)
        r5 = pct_change_from_series(close, 5)
        r20 = pct_change_from_series(close, 20)
        ret = np.log(close / close.shift(1)).replace([np.inf, -np.inf], np.nan).dropna()
        vol20 = safe_float(ret.tail(20).std(ddof=1) * math.sqrt(252)) if len(ret) >= 10 else None
        beta = compute_beta(target_df, hist, 90)
        corr = compute_corr(target_df, hist, 90)

        meta = DEFAULT_FUTURES_SYMBOLS.get(sym, {"name": sym, "type": "Proxy", "risk_role": "mixed"})
        role = meta.get("risk_role", "mixed")

        if r1 is None and r5 is None:
            regime = "Neutre"
            contribution = 0
        elif role == "risk_on":
            move = (r1 or 0) * 0.55 + (r5 or 0) * 0.45
            contribution = clamp(50 + move * 700, 0, 100)
            regime = "Support" if contribution >= 58 else "Pression" if contribution <= 42 else "Neutre"
        elif role == "risk_off":
            move = (r1 or 0) * 0.55 + (r5 or 0) * 0.45
            contribution = clamp(50 - move * 700, 0, 100)
            regime = "Support" if contribution >= 58 else "Pression" if contribution <= 42 else "Neutre"
        elif role == "pressure_up":
            move = (r1 or 0) * 0.55 + (r5 or 0) * 0.45
            contribution = clamp(50 - move * 500, 0, 100)
            regime = "Support" if contribution >= 58 else "Pression" if contribution <= 42 else "Neutre"
        else:
            move = (r1 or 0) * 0.55 + (r5 or 0) * 0.45
            contribution = clamp(50 + move * 250, 0, 100)
            regime = "Neutre"

        weight = 1.0
        if sym in ["NQ=F", "QQQ", "SMH", "SOXX"]:
            weight = 1.25
        if sym in ["^VIX", "^TNX"]:
            weight = 1.10
        score_components.append((contribution, weight))

        if regime == "Pression":
            pressure_notes.append(f"{sym} en pression")

        rows.append({
            "Instrument": meta.get("name", sym),
            "Ticker": sym,
            "Type": meta.get("type", "Proxy"),
            "Last": last,
            "1D": r1,
            "5D": r5,
            "20D": r20,
            "Vol 20D": vol20,
            "Beta ticker": beta,
            "Corr": corr,
            "Regime": regime,
            "Lecture": macro_lecture(sym, regime, r1, r5, beta, corr),
        })

    df = pd.DataFrame(rows)
    if score_components:
        total_w = sum(w for _, w in score_components)
        tape_score = sum(s * w for s, w in score_components) / max(total_w, _EPS)
    else:
        tape_score = 50.0

    if tape_score >= 65:
        tape_state = "Risk-on"
    elif tape_score <= 40:
        tape_state = "Risk-off"
    else:
        tape_state = "Mixte"

    if pressure_notes:
        message = "Tape macro à surveiller : " + ", ".join(pressure_notes[:3]) + "."
    elif tape_state == "Risk-on":
        message = "Futures / proxies favorables : contexte macro plutôt porteur."
    elif tape_state == "Risk-off":
        message = "Futures / proxies défavorables : risque d'exécution macro élevé."
    else:
        message = "Tape macro mixte : confirmation dérivée incomplète."

    summary = {"tape_score": clamp(tape_score), "tape_state": tape_state, "message": message}
    return df, summary


def macro_lecture(sym: str, regime: str, r1: Optional[float], r5: Optional[float], beta: Optional[float], corr: Optional[float]) -> str:
    if regime == "Données absentes":
        return "Données indisponibles."
    beta_txt = f" beta {beta:.2f}" if beta is not None else ""
    corr_txt = f" corr {corr:.2f}" if corr is not None else ""
    r1_txt = fmt_signed_pct(r1) if r1 is not None else "N/A"
    r5_txt = fmt_signed_pct(r5) if r5 is not None else "N/A"
    if regime == "Support":
        return f"Support court terme ({r1_txt} 1D, {r5_txt} 5D){beta_txt}{corr_txt}."
    if regime == "Pression":
        return f"Pression court terme ({r1_txt} 1D, {r5_txt} 5D){beta_txt}{corr_txt}."
    return f"Signal macro neutre ({r1_txt} 1D, {r5_txt} 5D){beta_txt}{corr_txt}."


def compute_futures_stress(ticker: str, price_data: pd.DataFrame, macro_df: pd.DataFrame) -> pd.DataFrame:
    if macro_df is None or macro_df.empty:
        return pd.DataFrame()
    shock_map = {
        "NQ=F": -0.02,
        "ES=F": -0.02,
        "QQQ": -0.02,
        "SPY": -0.02,
        "SMH": -0.03,
        "SOXX": -0.03,
        "^VIX": 0.10,
        "^TNX": 0.03,
        "DX-Y.NYB": 0.01,
    }
    rows = []
    for _, row in macro_df.iterrows():
        sym = str(row.get("Ticker", ""))
        beta = safe_float(row.get("Beta ticker"))
        shock = shock_map.get(sym)
        if shock is None or beta is None:
            continue
        role = DEFAULT_FUTURES_SYMBOLS.get(sym, {}).get("risk_role", "mixed")
        if role in ["risk_off", "pressure_up"]:
            impact = -abs(beta * shock) if sym in ["^VIX", "^TNX", "DX-Y.NYB"] else beta * shock
        else:
            impact = beta * shock
        severity = "Bloquant" if impact <= -0.06 else "Élevé" if impact <= -0.035 else "Modéré" if impact <= -0.015 else "Info"
        rows.append({
            "Scénario": f"{sym} {fmt_signed_pct(shock)}",
            "Facteur": sym,
            "Choc facteur": shock,
            "Beta ticker": beta,
            "Corr": safe_float(row.get("Corr")),
            "Impact ticker estimé": impact,
            "Sévérité": severity,
            "Lecture": "Stress macro significatif." if severity in ["Bloquant", "Élevé"] else "Stress macro contenu.",
        })
    return pd.DataFrame(rows)


# ============================================================
# Plot helpers
# ============================================================


def apply_dark_layout(fig: go.Figure, height: int = 520) -> go.Figure:
    fig.update_layout(
        template="plotly_dark",
        height=height,
        margin=dict(l=40, r=40, t=70, b=45),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="v", yanchor="top", y=1.0, xanchor="left", x=1.01),
    )
    return fig


def add_spot_line(fig: go.Figure, spot: float, text: str = "Spot") -> None:
    fig.add_vline(x=spot, line_width=2, line_dash="solid", line_color="white", annotation_text=f"{text} {fmt_price(spot)}", annotation_position="top")


def render_iv_smile(calls: pd.DataFrame, puts: pd.DataFrame, spot: float, title: str) -> None:
    fig = go.Figure()

    c = liquid_iv_view(calls, spot, window_pct=0.25, min_oi=10, min_volume=1, max_spread_pct=1.00)
    p = liquid_iv_view(puts, spot, window_pct=0.25, min_oi=10, min_volume=1, max_spread_pct=1.00)

    if c.empty and p.empty:
        st.info("Smile IV non affiché : données trop illiquides ou IV trop bruitées sur la fenêtre sélectionnée.")
        return

    if not c.empty:
        fig.add_trace(go.Scatter(x=c["strike"], y=c["iv"], mode="lines+markers", name="Calls IV filtrée"))

    if not p.empty:
        fig.add_trace(go.Scatter(x=p["strike"], y=p["iv"], mode="lines+markers", name="Puts IV filtrée"))

    add_spot_line(fig, spot, "Spot")
    fig.update_yaxes(tickformat=".0%", title="Implied volatility")
    fig.update_xaxes(title="Strike")
    fig.update_layout(title=title)
    st.plotly_chart(apply_dark_layout(fig, 520), width="stretch")

    st.caption(
        "Smile filtré : strikes trop éloignés, IV extrêmes, spreads excessifs et lignes illiquides sont exclus du graphique."
    )


def render_oi_chart(calls: pd.DataFrame, puts: pd.DataFrame, spot: float, window_pct: float) -> None:
    low = spot * (1.0 - window_pct)
    high = spot * (1.0 + window_pct)
    fig = go.Figure()
    if calls is not None and not calls.empty:
        c = calls[(calls["strike"] >= low) & (calls["strike"] <= high)].copy()
        fig.add_trace(go.Bar(x=c["strike"], y=c.get("openInterest", 0), name="Call OI"))
    if puts is not None and not puts.empty:
        p = puts[(puts["strike"] >= low) & (puts["strike"] <= high)].copy()
        fig.add_trace(go.Bar(x=p["strike"], y=-pd.to_numeric(p.get("openInterest", 0), errors="coerce").fillna(0), name="Put OI"))
    add_spot_line(fig, spot, "Spot")
    fig.update_layout(title="Open interest par strike — puts en négatif", barmode="relative")
    fig.update_xaxes(title="Strike")
    fig.update_yaxes(title="Open Interest")
    st.plotly_chart(apply_dark_layout(fig, 560), width="stretch")


def build_wall_pinning_diagnostics(
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    spot: float,
    metrics: Dict[str, Any],
    window_pct: float,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Wall Strength / Pinning Diagnostics.

    Objectif :
    - qualifier les principaux walls OI/GEX ;
    - mesurer si les concentrations proches du spot peuvent créer un risque de pinning ;
    - rester prudent : données publiques yfinance, pas une vérité dealer positioning.

    Ne modifie pas le score global dérivés.
    """
    empty_summary = {
        "pinning_state": "N/A",
        "pinning_score": None,
        "dominant_wall": None,
        "dominant_wall_type": "N/A",
        "near_oi_ratio": None,
        "near_gex_ratio": None,
        "wall_balance": "N/A",
    }

    if spot is None or spot <= 0:
        return pd.DataFrame(), empty_summary

    rows = []

    def _prep_side(df: pd.DataFrame, side: str) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()

        out = df.copy()

        for col in ["strike", "openInterest", "volume", "gex_proxy", "iv"]:
            if col not in out.columns:
                out[col] = np.nan
            out[col] = pd.to_numeric(out[col], errors="coerce")

        out = out.dropna(subset=["strike"]).copy()

        if out.empty:
            return pd.DataFrame()

        out["side"] = side
        out["oi"] = out["openInterest"].fillna(0)
        out["vol"] = out["volume"].fillna(0)
        out["abs_gex"] = out["gex_proxy"].abs().fillna(0)
        out["signed_gex"] = out["gex_proxy"].fillna(0)
        out["distance_spot"] = out["strike"] / max(spot, _EPS) - 1.0

        return out[
            (out["strike"] >= spot * (1.0 - window_pct))
            & (out["strike"] <= spot * (1.0 + window_pct))
        ].copy()

    c = _prep_side(calls, "Call")
    p = _prep_side(puts, "Put")

    if c.empty and p.empty:
        return pd.DataFrame(), empty_summary

    frames = []
    if not c.empty:
        frames.append(c)
    if not p.empty:
        frames.append(p)

    all_df = pd.concat(frames, ignore_index=True)

    if all_df.empty:
        return pd.DataFrame(), empty_summary

    grouped = (
        all_df.groupby("strike", as_index=False)
        .agg(
            call_oi=("oi", lambda s: float(s[all_df.loc[s.index, "side"].eq("Call")].sum())),
            put_oi=("oi", lambda s: float(s[all_df.loc[s.index, "side"].eq("Put")].sum())),
            call_vol=("vol", lambda s: float(s[all_df.loc[s.index, "side"].eq("Call")].sum())),
            put_vol=("vol", lambda s: float(s[all_df.loc[s.index, "side"].eq("Put")].sum())),
            signed_gex=("signed_gex", "sum"),
            abs_gex=("abs_gex", "sum"),
        )
    )

    if grouped.empty:
        return pd.DataFrame(), empty_summary

    grouped["total_oi"] = grouped["call_oi"] + grouped["put_oi"]
    grouped["total_vol"] = grouped["call_vol"] + grouped["put_vol"]
    grouped["net_oi"] = grouped["call_oi"] - grouped["put_oi"]
    grouped["distance_spot"] = grouped["strike"] / max(spot, _EPS) - 1.0

    grouped = grouped[grouped["total_oi"] > 0].copy()

    if grouped.empty:
        return pd.DataFrame(), empty_summary

    total_oi = safe_float(grouped["total_oi"].sum(), 0.0) or 0.0
    total_abs_gex = safe_float(grouped["abs_gex"].sum(), 0.0) or 0.0

    max_oi = safe_float(grouped["total_oi"].max(), 0.0) or 0.0
    max_gex = safe_float(grouped["abs_gex"].max(), 0.0) or 0.0
    vol_ref = safe_float(np.nanpercentile(grouped["total_vol"], 85), 0.0) or 0.0

    grouped["oi_concentration"] = grouped["total_oi"] / max(total_oi, _EPS)
    grouped["gex_concentration"] = grouped["abs_gex"] / max(total_abs_gex, _EPS)

    grouped["proximity_score"] = grouped["distance_spot"].abs().map(
        lambda x: 100.0 * max(0.0, 1.0 - min(abs(float(x)) / 0.08, 1.0))
    )

    grouped["oi_score"] = grouped["total_oi"].map(
        lambda x: 100.0 * max(0.0, min(float(x) / max(max_oi, _EPS), 1.0))
    )

    grouped["gex_score"] = grouped["abs_gex"].map(
        lambda x: 100.0 * max(0.0, min(float(x) / max(max_gex, _EPS), 1.0))
    )

    grouped["volume_score"] = grouped["total_vol"].map(
        lambda x: 100.0 * max(0.0, min(float(x) / max(vol_ref, _EPS), 1.0)) if vol_ref > 0 else 35.0
    )

    grouped["wall_strength"] = (
        0.35 * grouped["oi_score"]
        + 0.30 * grouped["gex_score"]
        + 0.25 * grouped["proximity_score"]
        + 0.10 * grouped["volume_score"]
    ).map(lambda x: clamp(x))

    def _wall_type(row: pd.Series) -> str:
        call_oi = safe_float(row.get("call_oi"), 0.0) or 0.0
        put_oi = safe_float(row.get("put_oi"), 0.0) or 0.0
        total = call_oi + put_oi

        if total <= 0:
            return "N/A"

        call_share = call_oi / total
        put_share = put_oi / total

        if call_share >= 0.65:
            return "Call wall"
        if put_share >= 0.65:
            return "Put wall"
        return "Mixed wall"

    grouped["wall_type"] = grouped.apply(_wall_type, axis=1)

    def _wall_reading(row: pd.Series) -> str:
        wall_type = str(row.get("wall_type", "N/A"))
        dist = safe_float(row.get("distance_spot"), 0.0) or 0.0
        strength = safe_float(row.get("wall_strength"), 0.0) or 0.0

        if strength >= 75 and abs(dist) <= 0.03:
            return f"{wall_type} très proche et concentré : zone de pinning/réaction à surveiller."
        if strength >= 60:
            return f"{wall_type} significatif : concentration exploitable mais à confirmer par volume/spreads."
        if abs(dist) <= 0.02:
            return f"{wall_type} proche du spot mais force modérée."
        return f"{wall_type} visible, mais distance ou concentration moins bloquante."

    grouped["lecture"] = grouped.apply(_wall_reading, axis=1)

    near = grouped[grouped["distance_spot"].abs() <= 0.025].copy()

    near_oi_ratio = (
        safe_float(near["total_oi"].sum() / max(total_oi, _EPS), 0.0)
        if not near.empty else 0.0
    )

    near_gex_ratio = (
        safe_float(near["abs_gex"].sum() / max(total_abs_gex, _EPS), 0.0)
        if not near.empty and total_abs_gex > 0 else 0.0
    )

    # Score local : une concentration de 20-25% d'OI proche spot est déjà significative.
    near_oi_score = clamp((near_oi_ratio or 0.0) / 0.25 * 100.0)

    # Score local : une concentration de 30-35% de GEX proche spot est significative.
    near_gex_score = clamp((near_gex_ratio or 0.0) / 0.35 * 100.0)

    if not near.empty:
        local_wall_strength = safe_float(near["wall_strength"].max(), 0.0) or 0.0

        nearest_strong_row = near.sort_values(
            ["wall_strength", "abs_gex", "total_oi"],
            ascending=[False, False, False],
        ).iloc[0]

        nearest_strong_distance = abs(
            safe_float(nearest_strong_row.get("distance_spot"), 1.0) or 1.0
        )
    else:
        local_wall_strength = 0.0
        nearest_strong_distance = None

    proximity_score = 0.0

    if nearest_strong_distance is not None:
        proximity_score = 100.0 * max(
            0.0,
            1.0 - min(nearest_strong_distance / 0.05, 1.0)
        )

    # Score prudent :
    # - on récompense un vrai wall fort proche du spot ;
    # - on évite de classifier "élevé" uniquement parce qu'un strike isolé est proche ;
    # - OI/GEX proches sont normalisés par seuils raisonnables.
    pinning_score = clamp(
        0.32 * local_wall_strength
        + 0.28 * near_gex_score
        + 0.22 * near_oi_score
        + 0.18 * proximity_score
    )

    if pinning_score >= 80:
        pinning_state = "Pinning élevé"
    elif pinning_score >= 60:
        pinning_state = "Pinning à surveiller"
    elif pinning_score >= 40:
        pinning_state = "Pinning modéré"
    else:
        pinning_state = "Pinning faible"

    top = grouped.sort_values("wall_strength", ascending=False).iloc[0]

    call_wall = safe_float(metrics.get("call_wall"))
    put_wall = safe_float(metrics.get("put_wall"))

    if call_wall is not None and put_wall is not None:
        if call_wall > spot and put_wall < spot:
            wall_balance = "Spot encadré"
        elif call_wall > spot and put_wall > spot:
            wall_balance = "Walls au-dessus"
        elif call_wall < spot and put_wall < spot:
            wall_balance = "Walls en-dessous"
        else:
            wall_balance = "Walls mixtes"
    else:
        wall_balance = "Incomplet"

    summary = {
        "pinning_state": pinning_state,
        "pinning_score": pinning_score,
        "dominant_wall": safe_float(top.get("strike")),
        "dominant_wall_type": str(top.get("wall_type", "N/A")),
        "near_oi_ratio": near_oi_ratio,
        "near_gex_ratio": near_gex_ratio,
        "wall_balance": wall_balance,
    }

    grouped = grouped.sort_values("wall_strength", ascending=False).reset_index(drop=True)

    out = grouped[
        [
            "strike",
            "wall_type",
            "wall_strength",
            "distance_spot",
            "total_oi",
            "call_oi",
            "put_oi",
            "total_vol",
            "signed_gex",
            "abs_gex",
            "oi_concentration",
            "gex_concentration",
            "lecture",
        ]
    ].copy()

    return out, summary


def render_wall_pinning_diagnostics(
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    spot: float,
    metrics: Dict[str, Any],
    window_pct: float,
) -> None:
    """
    Affichage Wall Strength / Pinning Diagnostics.
    À placer dans l'onglet OI / Walls après le graphique OI.
    """
    st.markdown("### Wall Strength / Pinning Diagnostics")

    wall_df, summary = build_wall_pinning_diagnostics(
        calls=calls,
        puts=puts,
        spot=spot,
        metrics=metrics,
        window_pct=window_pct,
    )

    if wall_df is None or wall_df.empty:
        st.info("Wall diagnostics indisponible : OI/GEX insuffisants dans la fenêtre sélectionnée.")
        return

    render_card_grid([
        (
            "Pinning state",
            str(summary.get("pinning_state", "N/A")),
            fmt_score(summary.get("pinning_score")),
        ),
        (
            "Dominant wall",
            fmt_price(summary.get("dominant_wall")),
            str(summary.get("dominant_wall_type", "N/A")),
        ),
        (
            "OI proche spot",
            fmt_pct(summary.get("near_oi_ratio")),
            "±2.5% autour spot",
        ),
        (
            "GEX proche spot",
            fmt_pct(summary.get("near_gex_ratio")),
            str(summary.get("wall_balance", "N/A")),
        ),
    ])

    pinning_score = safe_float(summary.get("pinning_score"), 0.0) or 0.0

    if pinning_score >= 75:
        st.warning(
            "Pinning à surveiller : OI/GEX sont concentrés près du spot. Le prix peut réagir autour des walls, surtout proche expiration.",
        )
    elif pinning_score >= 55:
        st.info(
            "Pinning à surveiller : plusieurs walls proches peuvent influencer l'exécution, "
            "mais le signal reste indicatif sur données publiques."
        )
    else:
        st.info(
            "Pinning non bloquant : les principaux walls existent, mais la concentration proche du spot reste contenue."
        )

    fig = go.Figure()

    top_plot = wall_df.sort_values("wall_strength", ascending=False).head(15).copy()
    top_plot = top_plot.sort_values("strike")

    fig.add_trace(
        go.Bar(
            x=top_plot["strike"],
            y=top_plot["wall_strength"],
            name="Wall strength",
            hovertemplate=(
                "Strike %{x:.2f}<br>"
                "Wall strength %{y:.0f}/100"
                "<extra></extra>"
            ),
        )
    )

    add_spot_line(fig, spot, "Spot")

    fig.update_layout(
        title="Wall strength par strike — OI/GEX/proximité/volume",
        xaxis_title="Strike",
        yaxis_title="Wall strength score",
    )

    st.plotly_chart(apply_dark_layout(fig, 460), width="stretch")

    display = wall_df.head(15).copy()
    display["wall_strength"] = display["wall_strength"].map(fmt_score)

    st.dataframe(
        format_display_df(display),
        width="stretch",
        hide_index=True,
    )

    st.caption(
        "Wall Strength = score descriptif combinant concentration OI, concentration GEX, proximité du spot et volume. "
        "Ce n'est pas une mesure institutionnelle du dealer positioning et ne modifie pas le score global dérivés."
    )


def render_max_pain_chart(max_pain_df: pd.DataFrame, max_pain: Optional[float], spot: float) -> None:
    if max_pain_df is None or max_pain_df.empty:
        st.info("Max pain indisponible : open interest insuffisant.")
        return
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=max_pain_df["strike"], y=max_pain_df["total_payout"], mode="lines", name="Payout total"))
    add_spot_line(fig, spot, "Spot")
    if max_pain is not None:
        fig.add_vline(x=max_pain, line_dash="dash", line_color="orange", annotation_text=f"Max pain {fmt_price(max_pain)}")
    fig.update_layout(title="Max pain indicatif — payout théorique à expiration")
    fig.update_xaxes(title="Strike")
    fig.update_yaxes(title="Payout total théorique")
    st.plotly_chart(apply_dark_layout(fig, 480), width="stretch")


def build_greeks_pressure_proxy(
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    spot: float,
    window_pct: float = 0.20,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Greeks Pressure Proxy.

    Objectif :
    - agréger delta/gamma/vega/theta/vanna/charm par strike ;
    - détecter les zones où les greeks publics sont concentrés près du spot ;
    - améliorer la lecture institutionnelle sans prétendre mesurer le vrai dealer positioning.

    Prudence :
    - basé sur IV/OI publics yfinance ;
    - aucun flux OPRA ;
    - aucun sens directionnel certain ;
    - ne modifie pas le score global dérivés.
    """
    empty_summary = {
        "greeks_state": "N/A",
        "greeks_score": None,
        "dominant_pressure_strike": None,
        "net_delta_notional": None,
        "net_gamma_proxy": None,
        "net_charm_notional_1d": None,
        "net_vanna_notional_1vol": None,
        "near_pressure_ratio": None,
        "pressure_bias": "N/A",
    }

    if spot is None or spot <= 0:
        return pd.DataFrame(), empty_summary

    frames = []

    for side, df in [("Call", calls), ("Put", puts)]:
        if df is None or df.empty:
            continue

        tmp = df.copy()
        tmp["side"] = side

        for col in [
            "strike",
            "openInterest",
            "volume",
            "delta",
            "gamma",
            "vega",
            "theta",
            "vanna",
            "charm",
            "gex_proxy",
            "iv",
        ]:
            if col not in tmp.columns:
                tmp[col] = np.nan
            tmp[col] = pd.to_numeric(tmp[col], errors="coerce")

        tmp = tmp.dropna(subset=["strike"]).copy()

        if tmp.empty:
            continue

        tmp["openInterest"] = tmp["openInterest"].fillna(0)
        tmp["volume"] = tmp["volume"].fillna(0)
        tmp["distance_spot"] = tmp["strike"] / max(spot, _EPS) - 1.0

        tmp = tmp[
            (tmp["strike"] >= spot * (1.0 - window_pct))
            & (tmp["strike"] <= spot * (1.0 + window_pct))
            & (tmp["openInterest"] > 0)
        ].copy()

        if tmp.empty:
            continue

        frames.append(tmp)

    if not frames:
        return pd.DataFrame(), empty_summary

    all_df = pd.concat(frames, ignore_index=True)

    if all_df.empty:
        return pd.DataFrame(), empty_summary

    contract_multiplier = CONTRACT_SIZE

    # Exposures indicatives.
    all_df["delta_notional"] = (
        all_df["delta"].fillna(0)
        * all_df["openInterest"].fillna(0)
        * contract_multiplier
        * spot
    )

    all_df["gamma_proxy"] = all_df["gex_proxy"].fillna(0)

    all_df["vega_exposure_1vol"] = (
        all_df["vega"].fillna(0)
        * all_df["openInterest"].fillna(0)
        * contract_multiplier
    )

    all_df["theta_daily"] = (
        all_df["theta"].fillna(0)
        * all_df["openInterest"].fillna(0)
        * contract_multiplier
    )

    # Vanna : variation de delta-notional pour +1 vol point.
    all_df["vanna_delta_notional_1vol"] = (
        all_df["vanna"].fillna(0)
        * all_df["openInterest"].fillna(0)
        * contract_multiplier
        * spot
    )

    # Charm : variation de delta-notional estimée sur 1 jour.
    all_df["charm_delta_notional_1d"] = (
        all_df["charm"].fillna(0)
        * all_df["openInterest"].fillna(0)
        * contract_multiplier
        * spot
    )

    grouped = (
        all_df.groupby("strike", as_index=False)
        .agg(
            total_oi=("openInterest", "sum"),
            total_vol=("volume", "sum"),
            avg_iv=("iv", "mean"),
            delta_notional=("delta_notional", "sum"),
            gamma_proxy=("gamma_proxy", "sum"),
            abs_gamma_proxy=("gamma_proxy", lambda s: float(np.nansum(np.abs(s)))),
            vega_exposure_1vol=("vega_exposure_1vol", "sum"),
            theta_daily=("theta_daily", "sum"),
            vanna_delta_notional_1vol=("vanna_delta_notional_1vol", "sum"),
            charm_delta_notional_1d=("charm_delta_notional_1d", "sum"),
        )
        .sort_values("strike")
        .reset_index(drop=True)
    )

    if grouped.empty:
        return pd.DataFrame(), empty_summary

    grouped["distance_spot"] = grouped["strike"] / max(spot, _EPS) - 1.0

    total_abs_gamma = safe_float(grouped["abs_gamma_proxy"].sum(), 0.0) or 0.0
    total_abs_delta = safe_float(grouped["delta_notional"].abs().sum(), 0.0) or 0.0
    total_abs_vanna = safe_float(grouped["vanna_delta_notional_1vol"].abs().sum(), 0.0) or 0.0
    total_abs_charm = safe_float(grouped["charm_delta_notional_1d"].abs().sum(), 0.0) or 0.0
    total_oi = safe_float(grouped["total_oi"].sum(), 0.0) or 0.0

    max_gamma = safe_float(grouped["abs_gamma_proxy"].max(), 0.0) or 0.0
    max_delta = safe_float(grouped["delta_notional"].abs().max(), 0.0) or 0.0
    max_vanna = safe_float(grouped["vanna_delta_notional_1vol"].abs().max(), 0.0) or 0.0
    max_charm = safe_float(grouped["charm_delta_notional_1d"].abs().max(), 0.0) or 0.0
    max_oi = safe_float(grouped["total_oi"].max(), 0.0) or 0.0

    grouped["gamma_contribution"] = grouped["abs_gamma_proxy"] / max(total_abs_gamma, _EPS)
    grouped["delta_contribution"] = grouped["delta_notional"].abs() / max(total_abs_delta, _EPS)
    grouped["vanna_contribution"] = grouped["vanna_delta_notional_1vol"].abs() / max(total_abs_vanna, _EPS)
    grouped["charm_contribution"] = grouped["charm_delta_notional_1d"].abs() / max(total_abs_charm, _EPS)
    grouped["oi_contribution"] = grouped["total_oi"] / max(total_oi, _EPS)

    grouped["proximity_score"] = grouped["distance_spot"].abs().map(
        lambda x: 100.0 * max(0.0, 1.0 - min(abs(float(x)) / 0.08, 1.0))
    )

    grouped["gamma_score"] = grouped["abs_gamma_proxy"].map(
        lambda x: 100.0 * min(abs(float(x)) / max(max_gamma, _EPS), 1.0)
    )

    grouped["delta_score"] = grouped["delta_notional"].abs().map(
        lambda x: 100.0 * min(abs(float(x)) / max(max_delta, _EPS), 1.0)
    )

    grouped["vanna_score"] = grouped["vanna_delta_notional_1vol"].abs().map(
        lambda x: 100.0 * min(abs(float(x)) / max(max_vanna, _EPS), 1.0)
    )

    grouped["charm_score"] = grouped["charm_delta_notional_1d"].abs().map(
        lambda x: 100.0 * min(abs(float(x)) / max(max_charm, _EPS), 1.0)
    )

    grouped["oi_score"] = grouped["total_oi"].map(
        lambda x: 100.0 * min(float(x) / max(max_oi, _EPS), 1.0)
    )

    grouped["greeks_pressure_score"] = (
        0.26 * grouped["gamma_score"]
        + 0.20 * grouped["charm_score"]
        + 0.18 * grouped["vanna_score"]
        + 0.16 * grouped["delta_score"]
        + 0.12 * grouped["oi_score"]
        + 0.08 * grouped["proximity_score"]
    ).map(lambda x: clamp(x))

    near = grouped[grouped["distance_spot"].abs() <= 0.025].copy()

    if near.empty:
        near_pressure_ratio = 0.0
        local_pressure = 0.0
    else:
        near_abs_pressure = (
            near["abs_gamma_proxy"].abs().sum()
            + near["charm_delta_notional_1d"].abs().sum()
            + near["vanna_delta_notional_1vol"].abs().sum()
        )

        total_abs_pressure = (
            grouped["abs_gamma_proxy"].abs().sum()
            + grouped["charm_delta_notional_1d"].abs().sum()
            + grouped["vanna_delta_notional_1vol"].abs().sum()
        )

        near_pressure_ratio = safe_float(
            near_abs_pressure / max(total_abs_pressure, _EPS),
            0.0,
        ) or 0.0

        local_pressure = safe_float(near["greeks_pressure_score"].max(), 0.0) or 0.0

    near_pressure_score = clamp((near_pressure_ratio or 0.0) / 0.35 * 100.0)

    net_delta = safe_float(grouped["delta_notional"].sum(), 0.0) or 0.0
    net_gamma = safe_float(grouped["gamma_proxy"].sum(), 0.0) or 0.0
    net_charm = safe_float(grouped["charm_delta_notional_1d"].sum(), 0.0) or 0.0
    net_vanna = safe_float(grouped["vanna_delta_notional_1vol"].sum(), 0.0) or 0.0

    delta_imbalance = abs(net_delta) / max(total_abs_delta, _EPS)
    charm_imbalance = abs(net_charm) / max(total_abs_charm, _EPS)
    vanna_imbalance = abs(net_vanna) / max(total_abs_vanna, _EPS)

    imbalance_score = clamp(
        0.45 * delta_imbalance * 100.0
        + 0.30 * charm_imbalance * 100.0
        + 0.25 * vanna_imbalance * 100.0
    )

    greeks_score = clamp(
        0.42 * local_pressure
        + 0.36 * near_pressure_score
        + 0.22 * imbalance_score
    )

    # Prudence : si pas assez de concentration près du spot, on évite un état trop agressif.
    if near_pressure_ratio < 0.10:
        greeks_score = min(greeks_score, 55.0)

    if greeks_score >= 80:
        greeks_state = "Greeks pressure élevée"
    elif greeks_score >= 60:
        greeks_state = "Greeks pressure à surveiller"
    elif greeks_score >= 40:
        greeks_state = "Greeks pressure modérée"
    else:
        greeks_state = "Greeks pressure contenue"

    if net_delta > 0 and net_vanna > 0:
        pressure_bias = "Bias call / vanna positive"
    elif net_delta < 0 and net_vanna < 0:
        pressure_bias = "Bias put / vanna négative"
    elif net_charm > 0:
        pressure_bias = "Charm drift positif"
    elif net_charm < 0:
        pressure_bias = "Charm drift négatif"
    else:
        pressure_bias = "Mixte"

    dominant_row = grouped.sort_values(
        ["greeks_pressure_score", "abs_gamma_proxy", "total_oi"],
        ascending=[False, False, False],
    ).iloc[0]

    def _lecture(row: pd.Series) -> str:
        score = safe_float(row.get("greeks_pressure_score"), 0.0) or 0.0
        dist = safe_float(row.get("distance_spot"), 0.0) or 0.0
        gamma_c = safe_float(row.get("gamma_contribution"), 0.0) or 0.0
        charm_c = safe_float(row.get("charm_contribution"), 0.0) or 0.0
        vanna_c = safe_float(row.get("vanna_contribution"), 0.0) or 0.0

        if score >= 75 and abs(dist) <= 0.03:
            return "Zone greeks très proche : gamma/charm/vanna concentrés, réaction possible autour du strike."
        if gamma_c >= 0.12:
            return "Concentration gamma significative : zone de convexité à surveiller."
        if charm_c >= 0.12:
            return "Charm proxy significatif : delta-notional peut évoluer rapidement avec le passage du temps."
        if vanna_c >= 0.12:
            return "Vanna proxy significatif : delta-notional sensible à une variation d'IV."
        return "Zone greeks visible mais non dominante."

    grouped["lecture"] = grouped.apply(_lecture, axis=1)

    summary = {
        "greeks_state": greeks_state,
        "greeks_score": greeks_score,
        "dominant_pressure_strike": safe_float(dominant_row.get("strike")),
        "net_delta_notional": net_delta,
        "net_gamma_proxy": net_gamma,
        "net_charm_notional_1d": net_charm,
        "net_vanna_notional_1vol": net_vanna,
        "near_pressure_ratio": near_pressure_ratio,
        "pressure_bias": pressure_bias,
    }

    grouped = grouped.sort_values("greeks_pressure_score", ascending=False).reset_index(drop=True)

    out = grouped[
        [
            "strike",
            "greeks_pressure_score",
            "distance_spot",
            "total_oi",
            "total_vol",
            "avg_iv",
            "delta_notional",
            "gamma_proxy",
            "abs_gamma_proxy",
            "vega_exposure_1vol",
            "theta_daily",
            "vanna_delta_notional_1vol",
            "charm_delta_notional_1d",
            "gamma_contribution",
            "vanna_contribution",
            "charm_contribution",
            "lecture",
        ]
    ].copy()

    return out, summary


def render_greeks_pressure_proxy(
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    spot: float,
    window_pct: float,
) -> None:
    """
    Affichage Greeks Pressure Proxy.
    À placer dans l'onglet Gamma Proxy après le GEX chart.
    """
    st.markdown("### Greeks Pressure Proxy")

    greeks_df, summary = build_greeks_pressure_proxy(
        calls=calls,
        puts=puts,
        spot=spot,
        window_pct=window_pct,
    )

    if greeks_df is None or greeks_df.empty:
        st.info("Greeks Pressure Proxy indisponible : greeks/OI insuffisants dans la fenêtre sélectionnée.")
        return

    render_card_grid([
        (
            "Greeks state",
            str(summary.get("greeks_state", "N/A")),
            fmt_score(summary.get("greeks_score")),
        ),
        (
            "Dominant strike",
            fmt_price(summary.get("dominant_pressure_strike")),
            str(summary.get("pressure_bias", "N/A")),
        ),
        (
            "Near pressure",
            fmt_pct(summary.get("near_pressure_ratio")),
            "±2.5% autour spot",
        ),
        (
            "Charm 1D proxy",
            fmt_large(summary.get("net_charm_notional_1d")),
            "Delta-notional drift",
        ),
    ])

    greeks_score = safe_float(summary.get("greeks_score"), 0.0) or 0.0

    if greeks_score >= 75:
        st.warning(
            "Greeks pressure élevée : gamma/charm/vanna sont concentrés près du spot. "
            "Lecture utile pour timing/exécution, mais ce n'est pas une mesure dealer institutionnelle."
        )
    elif greeks_score >= 55:
        st.info(
            "Greeks pressure à surveiller : certaines zones de convexité ou de delta-drift sont visibles, "
            "sans signal bloquant confirmé."
        )
    else:
        st.info(
            "Greeks pressure contenue : pas de concentration majeure détectée sur les greeks publics filtrés."
        )

    plot_df = greeks_df.sort_values("greeks_pressure_score", ascending=False).head(15).copy()
    plot_df = plot_df.sort_values("strike")

    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            x=plot_df["strike"],
            y=plot_df["greeks_pressure_score"],
            name="Greeks pressure score",
            hovertemplate=(
                "Strike %{x:.2f}<br>"
                "Score %{y:.0f}/100"
                "<extra></extra>"
            ),
        )
    )

    add_spot_line(fig, spot, "Spot")

    fig.update_layout(
        title="Greeks pressure par strike — gamma/charm/vanna/delta/OI",
        xaxis_title="Strike",
        yaxis_title="Greeks pressure score",
    )

    st.plotly_chart(
        apply_dark_layout(fig, 460),
        width="stretch",
        key="gamma_tab_greeks_pressure_proxy_chart",
    )

    compact_cols = [
        "strike",
        "greeks_pressure_score",
        "distance_spot",
        "total_oi",
        "total_vol",
        "avg_iv",
        "delta_notional",
        "gamma_proxy",
        "vanna_delta_notional_1vol",
        "charm_delta_notional_1d",
        "lecture",
    ]

    display = greeks_df[[c for c in compact_cols if c in greeks_df.columns]].head(15).copy()

    rename_map = {
        "strike": "Strike",
        "greeks_pressure_score": "Pressure",
        "distance_spot": "Distance spot",
        "total_oi": "Total OI",
        "total_vol": "Volume",
        "avg_iv": "Avg IV",
        "delta_notional": "Delta notional",
        "gamma_proxy": "Gamma proxy",
        "vanna_delta_notional_1vol": "Vanna 1 vol pt",
        "charm_delta_notional_1d": "Charm 1D",
        "lecture": "Lecture",
    }

    display = display.rename(columns=rename_map)

    if "Pressure" in display.columns:
        display["Pressure"] = display["Pressure"].map(fmt_score)

    if "Distance spot" in display.columns:
        display["Distance spot"] = display["Distance spot"].map(fmt_pct)

    for c in ["Total OI", "Volume"]:
        if c in display.columns:
            display[c] = display[c].map(fmt_int)

    if "Avg IV" in display.columns:
        display["Avg IV"] = display["Avg IV"].map(fmt_pct)

    for c in ["Delta notional", "Gamma proxy", "Vanna 1 vol pt", "Charm 1D"]:
        if c in display.columns:
            display[c] = display[c].map(fmt_large)

    st.dataframe(
        display,
        width="stretch",
        hide_index=True,
    )

    with st.expander("Voir table Greeks complète", expanded=False):
        full_display = greeks_df.head(30).copy()
        st.dataframe(
            format_display_df(full_display),
            width="stretch",
            hide_index=True,
        )

    st.caption(
        "Greeks Pressure Proxy = agrégation mécanique de delta/gamma/vega/theta/vanna/charm sur IV publique et OI yfinance. "
        "Charm et vanna sont des approximations Black-Scholes, pas des flux dealer. "
        "Ce bloc améliore le diagnostic d'exécution mais ne modifie pas le score global dérivés."
    )



# ============================================================
# Full Greeks Exposure / Sensitivity Dashboard
# ============================================================

def bs_rho_proxy(
    spot: float,
    strike: float,
    dte: int,
    iv: float,
    option_type: str,
    r: float = 0.045,
    q: float = 0.0,
) -> Optional[float]:
    """
    Rho proxy Black-Scholes.

    Convention :
    - rho par +100 bps de taux, par action optionnelle ;
    - exposition ensuite multipliée par OI * contract size ;
    - proxy descriptif, pas une mesure dealer ni une donnée institutionnelle.
    """
    spot = safe_float(spot)
    strike = safe_float(strike)
    dte = safe_int(dte)
    iv = safe_float(iv)

    if spot is None or strike is None or dte is None or iv is None:
        return None

    if spot <= 0 or strike <= 0 or iv <= 0:
        return None

    t = max(dte / 365.0, 1.0 / 365.0)
    d1 = bs_d1(spot, strike, t, r, iv, q)

    if d1 is None:
        return None

    d2 = d1 - iv * math.sqrt(t)

    try:
        if str(option_type).lower().startswith("c"):
            return strike * t * math.exp(-r * t) * norm_cdf(d2) / 100.0

        return -strike * t * math.exp(-r * t) * norm_cdf(-d2) / 100.0

    except Exception:
        return None


def prepare_full_greeks_rows(
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    spot: float,
    window_pct: float = 0.20,
) -> pd.DataFrame:
    """
    Prépare les lignes options pour le dashboard greeks complet.

    Prudence :
    - on réutilise les greeks déjà calculés si disponibles ;
    - on complète seulement les greeks manquants ;
    - rho est ajouté localement sans modifier les blocs existants ;
    - filtre OI > 0 et fenêtre autour du spot.
    """
    if spot is None or spot <= 0:
        return pd.DataFrame()

    frames = []

    for option_type, df in [("call", calls), ("put", puts)]:
        if df is None or df.empty:
            continue

        tmp = df.copy()
        tmp["option_type"] = option_type

        for col in [
            "strike",
            "openInterest",
            "volume",
            "iv",
            "dte",
            "delta",
            "gamma",
            "vega",
            "theta",
            "vanna",
            "charm",
            "gex_proxy",
        ]:
            if col not in tmp.columns:
                tmp[col] = np.nan
            tmp[col] = pd.to_numeric(tmp[col], errors="coerce")

        tmp = tmp.dropna(subset=["strike"]).copy()

        if tmp.empty:
            continue

        tmp["openInterest"] = tmp["openInterest"].fillna(0)
        tmp["volume"] = tmp["volume"].fillna(0)
        tmp["distance_spot"] = tmp["strike"] / max(spot, _EPS) - 1.0

        tmp = tmp[
            (tmp["strike"] >= spot * (1.0 - window_pct))
            & (tmp["strike"] <= spot * (1.0 + window_pct))
            & (tmp["openInterest"] > 0)
        ].copy()

        if tmp.empty:
            continue

        greek_cols = ["delta", "gamma", "vega", "theta", "vanna", "charm"]

        missing_mask = tmp[greek_cols].isna().any(axis=1)

        if missing_mask.any():
            for idx, row in tmp.loc[missing_mask].iterrows():
                greeks = bs_greeks_proxy(
                    spot=spot,
                    strike=safe_float(row.get("strike"), 0.0) or 0.0,
                    dte=safe_int(row.get("dte"), 1) or 1,
                    iv=safe_float(row.get("iv"), 0.0) or 0.0,
                    option_type=option_type,
                )

                for col in greek_cols:
                    if pd.isna(tmp.at[idx, col]):
                        tmp.at[idx, col] = greeks.get(col)

        tmp["rho_100bp"] = tmp.apply(
            lambda row: bs_rho_proxy(
                spot=spot,
                strike=safe_float(row.get("strike"), 0.0) or 0.0,
                dte=safe_int(row.get("dte"), 1) or 1,
                iv=safe_float(row.get("iv"), 0.0) or 0.0,
                option_type=option_type,
            ),
            axis=1,
        )

        sign = 1.0 if option_type == "call" else -1.0

        recomputed_gex = (
            sign
            * tmp["gamma"].fillna(0)
            * tmp["openInterest"].fillna(0)
            * CONTRACT_SIZE
            * (spot ** 2)
            * 0.01
        )

        tmp["gex_proxy"] = tmp["gex_proxy"].fillna(recomputed_gex)

        tmp["delta_notional"] = (
            tmp["delta"].fillna(0)
            * tmp["openInterest"].fillna(0)
            * CONTRACT_SIZE
            * spot
        )

        tmp["gamma_proxy"] = tmp["gex_proxy"].fillna(0)

        tmp["vega_exposure_1vol"] = (
            tmp["vega"].fillna(0)
            * tmp["openInterest"].fillna(0)
            * CONTRACT_SIZE
        )

        tmp["theta_daily"] = (
            tmp["theta"].fillna(0)
            * tmp["openInterest"].fillna(0)
            * CONTRACT_SIZE
        )

        tmp["vanna_delta_notional_1vol"] = (
            tmp["vanna"].fillna(0)
            * tmp["openInterest"].fillna(0)
            * CONTRACT_SIZE
            * spot
        )

        tmp["charm_delta_notional_1d"] = (
            tmp["charm"].fillna(0)
            * tmp["openInterest"].fillna(0)
            * CONTRACT_SIZE
            * spot
        )

        tmp["rho_exposure_100bp"] = (
            tmp["rho_100bp"].fillna(0)
            * tmp["openInterest"].fillna(0)
            * CONTRACT_SIZE
        )

        frames.append(tmp)

    if not frames:
        return pd.DataFrame()

    out = pd.concat(frames, ignore_index=True)
    return out.replace([np.inf, -np.inf], np.nan)


def build_full_greeks_exposure_dashboard(
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    spot: float,
    window_pct: float = 0.20,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """
    Dashboard complet des greeks.

    Ce bloc ne modifie aucun score existant.
    Il sert à lire :
    - exposition directionnelle delta ;
    - convexité gamma ;
    - sensibilité IV via vega/vanna ;
    - decay via theta/charm ;
    - sensibilité taux via rho.
    """
    empty_summary = {
        "full_greeks_state": "N/A",
        "full_greeks_score": None,
        "dominant_greek": "N/A",
        "dominant_greek_score": None,
        "net_delta_notional": None,
        "net_gamma_proxy": None,
        "net_vega_1vol": None,
        "net_theta_1d": None,
        "net_vanna_1vol": None,
        "net_charm_1d": None,
        "net_rho_100bp": None,
    }

    rows = prepare_full_greeks_rows(
        calls=calls,
        puts=puts,
        spot=spot,
        window_pct=window_pct,
    )

    if rows is None or rows.empty:
        return pd.DataFrame(), pd.DataFrame(), empty_summary

    grouped = (
        rows.groupby("strike", as_index=False)
        .agg(
            total_oi=("openInterest", "sum"),
            total_vol=("volume", "sum"),
            avg_iv=("iv", "mean"),
            delta_notional=("delta_notional", "sum"),
            abs_delta_notional=("delta_notional", lambda s: float(np.nansum(np.abs(s)))),
            gamma_proxy=("gamma_proxy", "sum"),
            abs_gamma_proxy=("gamma_proxy", lambda s: float(np.nansum(np.abs(s)))),
            vega_exposure_1vol=("vega_exposure_1vol", "sum"),
            abs_vega_exposure_1vol=("vega_exposure_1vol", lambda s: float(np.nansum(np.abs(s)))),
            theta_daily=("theta_daily", "sum"),
            abs_theta_daily=("theta_daily", lambda s: float(np.nansum(np.abs(s)))),
            vanna_delta_notional_1vol=("vanna_delta_notional_1vol", "sum"),
            abs_vanna_delta_notional_1vol=("vanna_delta_notional_1vol", lambda s: float(np.nansum(np.abs(s)))),
            charm_delta_notional_1d=("charm_delta_notional_1d", "sum"),
            abs_charm_delta_notional_1d=("charm_delta_notional_1d", lambda s: float(np.nansum(np.abs(s)))),
            rho_exposure_100bp=("rho_exposure_100bp", "sum"),
            abs_rho_exposure_100bp=("rho_exposure_100bp", lambda s: float(np.nansum(np.abs(s)))),
        )
        .sort_values("strike")
        .reset_index(drop=True)
    )

    if grouped.empty:
        return pd.DataFrame(), pd.DataFrame(), empty_summary

    grouped["distance_spot"] = grouped["strike"] / max(spot, _EPS) - 1.0

    specs = [
        {
            "Greek": "Delta",
            "net_col": "delta_notional",
            "abs_col": "abs_delta_notional",
            "unit": "Delta-notional",
            "role": "Sensibilité directionnelle du book public.",
        },
        {
            "Greek": "Gamma",
            "net_col": "gamma_proxy",
            "abs_col": "abs_gamma_proxy",
            "unit": "GEX proxy",
            "role": "Convexité / risque de pinning.",
        },
        {
            "Greek": "Vega",
            "net_col": "vega_exposure_1vol",
            "abs_col": "abs_vega_exposure_1vol",
            "unit": "Vega 1 vol pt",
            "role": "Sensibilité à une variation d'IV.",
        },
        {
            "Greek": "Theta",
            "net_col": "theta_daily",
            "abs_col": "abs_theta_daily",
            "unit": "Theta 1D",
            "role": "Decay journalier théorique.",
        },
        {
            "Greek": "Vanna",
            "net_col": "vanna_delta_notional_1vol",
            "abs_col": "abs_vanna_delta_notional_1vol",
            "unit": "Delta drift 1 vol pt",
            "role": "Variation du delta-notional sous choc IV.",
        },
        {
            "Greek": "Charm",
            "net_col": "charm_delta_notional_1d",
            "abs_col": "abs_charm_delta_notional_1d",
            "unit": "Delta drift 1D",
            "role": "Variation du delta-notional avec le passage du temps.",
        },
        {
            "Greek": "Rho",
            "net_col": "rho_exposure_100bp",
            "abs_col": "abs_rho_exposure_100bp",
            "unit": "Rho 100 bps",
            "role": "Sensibilité théorique à une variation des taux.",
        },
    ]

    greek_rows = []

    near_mask = grouped["distance_spot"].abs() <= 0.025

    for spec in specs:
        greek = spec["Greek"]
        net_col = spec["net_col"]
        abs_col = spec["abs_col"]

        if net_col not in grouped.columns or abs_col not in grouped.columns:
            continue

        total_abs = safe_float(grouped[abs_col].sum(), 0.0) or 0.0
        net_value = safe_float(grouped[net_col].sum(), 0.0) or 0.0

        if total_abs <= 0:
            continue

        near_abs = safe_float(grouped.loc[near_mask, abs_col].sum(), 0.0) or 0.0
        near_share = near_abs / max(total_abs, _EPS)

        dominant_idx = grouped[abs_col].idxmax()
        dominant_row = grouped.loc[dominant_idx]

        dominant_abs = safe_float(dominant_row.get(abs_col), 0.0) or 0.0
        concentration = dominant_abs / max(total_abs, _EPS)

        imbalance = abs(net_value) / max(total_abs, _EPS)

        near_score = clamp(near_share / 0.35 * 100.0)
        concentration_score = clamp(concentration / 0.25 * 100.0)
        imbalance_score = clamp(imbalance * 100.0)

        greek_score = clamp(
            0.40 * near_score
            + 0.35 * concentration_score
            + 0.25 * imbalance_score
        )

        if net_value > 0:
            direction = "Positive"
        elif net_value < 0:
            direction = "Negative"
        else:
            direction = "Neutre"

        if greek == "Theta":
            direction = "Decay négatif" if net_value < 0 else "Decay positif"
        elif greek == "Gamma":
            direction = "Gamma positif proxy" if net_value > 0 else "Gamma négatif proxy"
        elif greek == "Rho":
            direction = "Taux +" if net_value > 0 else "Taux -"

        if greek_score >= 75:
            lecture = f"{greek} dominant ou très concentré : {spec['role']}"
        elif near_share >= 0.25:
            lecture = f"{greek} concentré près du spot : zone sensible pour exécution."
        elif concentration >= 0.20:
            lecture = f"{greek} dominé par un strike spécifique : surveiller {fmt_price(dominant_row.get('strike'))}."
        else:
            lecture = f"{greek} diffus ou non dominant : {spec['role']}"

        greek_rows.append({
            "Greek": greek,
            "Risk score": greek_score,
            "Net exposure": net_value,
            "Abs exposure": total_abs,
            "Near spot share": near_share,
            "Top strike concentration": concentration,
            "Dominant strike": safe_float(dominant_row.get("strike")),
            "Direction": direction,
            "Unit": spec["unit"],
            "Lecture": lecture,
        })

    greek_df = pd.DataFrame(greek_rows)

    if greek_df.empty:
        return pd.DataFrame(), grouped, empty_summary

    greek_df = greek_df.sort_values("Risk score", ascending=False).reset_index(drop=True)

    top_score = safe_float(greek_df["Risk score"].iloc[0], 0.0) or 0.0
    mean_top3 = safe_float(greek_df["Risk score"].head(3).mean(), 0.0) or 0.0

    full_score = clamp(0.60 * top_score + 0.40 * mean_top3)

    if full_score >= 80:
        state = "Greeks stack tendu"
    elif full_score >= 60:
        state = "Greeks stack à surveiller"
    elif full_score >= 40:
        state = "Greeks stack équilibré"
    else:
        state = "Greeks stack contenu"

    dominant = greek_df.iloc[0]

    summary = {
        "full_greeks_state": state,
        "full_greeks_score": full_score,
        "dominant_greek": str(dominant.get("Greek", "N/A")),
        "dominant_greek_score": safe_float(dominant.get("Risk score")),
        "net_delta_notional": safe_float(grouped["delta_notional"].sum(), 0.0),
        "net_gamma_proxy": safe_float(grouped["gamma_proxy"].sum(), 0.0),
        "net_vega_1vol": safe_float(grouped["vega_exposure_1vol"].sum(), 0.0),
        "net_theta_1d": safe_float(grouped["theta_daily"].sum(), 0.0),
        "net_vanna_1vol": safe_float(grouped["vanna_delta_notional_1vol"].sum(), 0.0),
        "net_charm_1d": safe_float(grouped["charm_delta_notional_1d"].sum(), 0.0),
        "net_rho_100bp": safe_float(grouped["rho_exposure_100bp"].sum(), 0.0),
    }

    return greek_df, grouped, summary


def render_full_greeks_exposure_dashboard(
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    spot: float,
    window_pct: float,
) -> None:
    """
    Affichage du dashboard Greeks complet.
    À placer dans Gamma Proxy après Greeks Pressure Proxy.
    """
    st.markdown("### Full Greeks Exposure / Sensitivity Dashboard")

    greek_df, strike_df, summary = build_full_greeks_exposure_dashboard(
        calls=calls,
        puts=puts,
        spot=spot,
        window_pct=window_pct,
    )

    if greek_df is None or greek_df.empty:
        st.info("Full Greeks Dashboard indisponible : greeks/OI insuffisants dans la fenêtre sélectionnée.")
        return

    render_card_grid([
        (
            "Greeks stack",
            str(summary.get("full_greeks_state", "N/A")),
            fmt_score(summary.get("full_greeks_score")),
        ),
        (
            "Dominant greek",
            str(summary.get("dominant_greek", "N/A")),
            fmt_score(summary.get("dominant_greek_score")),
        ),
        (
            "Delta / Gamma",
            f"{fmt_large(summary.get('net_delta_notional'))} / {fmt_large(summary.get('net_gamma_proxy'))}",
            "Net exposures",
        ),
        (
            "Vega / Theta",
            f"{fmt_large(summary.get('net_vega_1vol'))} / {fmt_large(summary.get('net_theta_1d'))}",
            "1 vol pt / 1 jour",
        ),
    ])

    score = safe_float(summary.get("full_greeks_score"), 50.0) or 50.0

    if score >= 80:
        st.warning(
            "Greeks stack tendu : une ou plusieurs sensibilités sont concentrées ou très déséquilibrées. "
            "À utiliser pour timing/exécution, pas comme signal directionnel certain."
        )
    elif score >= 60:
        st.info(
            "Greeks stack à surveiller : certaines sensibilités dominent, mais sans alerte bloquante confirmée."
        )
    else:
        st.info(
            "Greeks stack contenu : les sensibilités publiques sont relativement diffusées sur la fenêtre retenue."
        )

    plot_df = greek_df.copy()

    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            x=plot_df["Greek"],
            y=plot_df["Risk score"],
            name="Greek risk score",
            hovertemplate=(
                "Greek %{x}<br>"
                "Score %{y:.0f}/100"
                "<extra></extra>"
            ),
        )
    )

    fig.add_hline(y=60, line_dash="dot", line_color="orange")
    fig.add_hline(y=75, line_dash="dot", line_color="red")

    fig.update_layout(
        title="Greek sensitivity balance — Delta/Gamma/Vega/Theta/Vanna/Charm/Rho",
        xaxis_title="Greek",
        yaxis_title="Risk score",
    )

    st.plotly_chart(
        apply_dark_layout(fig, 430),
        width="stretch",
        key="gamma_tab_full_greeks_balance_chart",
    )

    display = greek_df.copy()

    if "Risk score" in display.columns:
        display["Risk score"] = display["Risk score"].map(fmt_score)

    for col in ["Net exposure", "Abs exposure"]:
        if col in display.columns:
            display[col] = display[col].map(fmt_large)

    for col in ["Near spot share", "Top strike concentration"]:
        if col in display.columns:
            display[col] = display[col].map(fmt_pct)

    if "Dominant strike" in display.columns:
        display["Dominant strike"] = display["Dominant strike"].map(fmt_price)

    st.dataframe(
        display,
        width="stretch",
        hide_index=True,
    )

    if strike_df is not None and not strike_df.empty:
        detail = strike_df.copy()

        detail["combined_abs_greeks"] = (
            detail["abs_delta_notional"].fillna(0)
            + detail["abs_gamma_proxy"].fillna(0)
            + detail["abs_vega_exposure_1vol"].fillna(0)
            + detail["abs_theta_daily"].fillna(0)
            + detail["abs_vanna_delta_notional_1vol"].fillna(0)
            + detail["abs_charm_delta_notional_1d"].fillna(0)
            + detail["abs_rho_exposure_100bp"].fillna(0)
        )

        detail = detail.sort_values("combined_abs_greeks", ascending=False).head(15)

        detail = detail[
            [
                "strike",
                "distance_spot",
                "total_oi",
                "total_vol",
                "avg_iv",
                "delta_notional",
                "gamma_proxy",
                "vega_exposure_1vol",
                "theta_daily",
                "vanna_delta_notional_1vol",
                "charm_delta_notional_1d",
                "rho_exposure_100bp",
            ]
        ].copy()

        detail = detail.rename(columns={
            "strike": "Strike",
            "distance_spot": "Distance spot",
            "total_oi": "Total OI",
            "total_vol": "Volume",
            "avg_iv": "Avg IV",
            "delta_notional": "Delta notional",
            "gamma_proxy": "Gamma proxy",
            "vega_exposure_1vol": "Vega 1 vol pt",
            "theta_daily": "Theta 1D",
            "vanna_delta_notional_1vol": "Vanna 1 vol pt",
            "charm_delta_notional_1d": "Charm 1D",
            "rho_exposure_100bp": "Rho 100 bps",
        })

        if "Strike" in detail.columns:
            detail["Strike"] = detail["Strike"].map(fmt_price)
        if "Distance spot" in detail.columns:
            detail["Distance spot"] = detail["Distance spot"].map(fmt_pct)
        if "Total OI" in detail.columns:
            detail["Total OI"] = detail["Total OI"].map(fmt_int)
        if "Volume" in detail.columns:
            detail["Volume"] = detail["Volume"].map(fmt_int)
        if "Avg IV" in detail.columns:
            detail["Avg IV"] = detail["Avg IV"].map(fmt_pct)

        for col in [
            "Delta notional",
            "Gamma proxy",
            "Vega 1 vol pt",
            "Theta 1D",
            "Vanna 1 vol pt",
            "Charm 1D",
            "Rho 100 bps",
        ]:
            if col in detail.columns:
                detail[col] = detail[col].map(fmt_large)

        with st.expander("Voir exposition Greeks par strike", expanded=False):
            st.dataframe(
                detail,
                width="stretch",
                hide_index=True,
            )

    st.caption(
        "Full Greeks Dashboard = agrégation mécanique des greeks Black-Scholes proxy sur IV publique et OI yfinance. "
        "Delta, gamma, vega, theta, vanna, charm et rho sont des sensibilités descriptives, pas du dealer positioning institutionnel. "
        "Ce bloc ne modifie aucun score global."
    )


# ============================================================
# Gamma / Greeks Scenario Stress Matrix
# ============================================================

def _prepare_scenario_option_rows(
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    spot: float,
    window_pct: float = 0.20,
) -> pd.DataFrame:
    """
    Prépare les lignes options utilisées pour le stress test spot/IV.

    Prudence :
    - uniquement options avec OI > 0 ;
    - uniquement IV exploitable ;
    - fenêtre autour du spot pour éviter que les strikes extrêmes dominent ;
    - ne modifie aucun score global.
    """
    if spot is None or spot <= 0:
        return pd.DataFrame()

    frames = []

    for opt_type, df in [("call", calls), ("put", puts)]:
        if df is None or df.empty:
            continue

        tmp = df.copy()
        tmp["option_type"] = opt_type

        for col in ["strike", "openInterest", "volume", "iv", "dte"]:
            if col not in tmp.columns:
                tmp[col] = np.nan
            tmp[col] = pd.to_numeric(tmp[col], errors="coerce")

        tmp = tmp.dropna(subset=["strike", "iv"]).copy()

        if tmp.empty:
            continue

        tmp["openInterest"] = tmp["openInterest"].fillna(0)
        tmp["volume"] = tmp["volume"].fillna(0)
        tmp["dte"] = tmp["dte"].fillna(1)
        tmp["distance_spot"] = tmp["strike"] / max(spot, _EPS) - 1.0

        tmp = tmp[
            (tmp["strike"] >= spot * (1.0 - window_pct))
            & (tmp["strike"] <= spot * (1.0 + window_pct))
            & (tmp["iv"] > 0)
            & (tmp["iv"] < 5)
            & (tmp["openInterest"] > 0)
        ].copy()

        if not tmp.empty:
            frames.append(tmp)

    if not frames:
        return pd.DataFrame()

    out = pd.concat(frames, ignore_index=True)
    return out.reset_index(drop=True)


def _compute_scenario_exposures(
    option_rows: pd.DataFrame,
    shocked_spot: float,
    vol_shift: float,
) -> Dict[str, Any]:
    """
    Recalcule les greeks Black-Scholes proxy sous un scénario spot/IV.

    vol_shift = variation absolue de volatilité, ex : +0.05 = +5 vol points.
    """
    if option_rows is None or option_rows.empty or shocked_spot is None or shocked_spot <= 0:
        return {
            "net_delta_notional": None,
            "net_gex_proxy": None,
            "abs_gex_proxy": None,
            "net_charm_1d": None,
            "net_vanna_1vol": None,
            "total_oi": None,
            "total_volume": None,
        }

    net_delta = 0.0
    net_gex = 0.0
    abs_gex = 0.0
    net_charm = 0.0
    net_vanna = 0.0
    total_oi = 0.0
    total_volume = 0.0

    for _, row in option_rows.iterrows():
        strike = safe_float(row.get("strike"))
        base_iv = safe_float(row.get("iv"))
        oi = safe_float(row.get("openInterest"), 0.0) or 0.0
        vol = safe_float(row.get("volume"), 0.0) or 0.0
        dte = safe_int(row.get("dte"), 1) or 1
        opt_type = str(row.get("option_type", "")).lower().strip()

        if strike is None or base_iv is None or oi <= 0 or opt_type not in ["call", "put"]:
            continue

        stressed_iv = base_iv + float(vol_shift)

        # Floor / cap prudent pour éviter des IV négatives ou absurdes.
        stressed_iv = max(0.01, min(stressed_iv, 5.00))

        greeks = bs_greeks_proxy(
            spot=shocked_spot,
            strike=strike,
            dte=dte,
            iv=stressed_iv,
            option_type=opt_type,
        )

        delta = safe_float(greeks.get("delta"), 0.0) or 0.0
        gamma = safe_float(greeks.get("gamma"), 0.0) or 0.0
        charm = safe_float(greeks.get("charm"), 0.0) or 0.0
        vanna = safe_float(greeks.get("vanna"), 0.0) or 0.0

        sign = 1.0 if opt_type == "call" else -1.0

        delta_notional = delta * oi * CONTRACT_SIZE * shocked_spot

        # On conserve la même convention que ton GEX actuel : calls positifs, puts négatifs.
        gex_proxy = sign * gamma * oi * CONTRACT_SIZE * (shocked_spot ** 2) * 0.01

        charm_notional = charm * oi * CONTRACT_SIZE * shocked_spot
        vanna_notional = vanna * oi * CONTRACT_SIZE * shocked_spot

        net_delta += delta_notional
        net_gex += gex_proxy
        abs_gex += abs(gex_proxy)
        net_charm += charm_notional
        net_vanna += vanna_notional
        total_oi += oi
        total_volume += vol

    return {
        "net_delta_notional": net_delta,
        "net_gex_proxy": net_gex,
        "abs_gex_proxy": abs_gex,
        "net_charm_1d": net_charm,
        "net_vanna_1vol": net_vanna,
        "total_oi": total_oi,
        "total_volume": total_volume,
    }


def build_gamma_scenario_stress_matrix(
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    spot: float,
    metrics: Dict[str, Any],
    window_pct: float = 0.20,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Gamma / Greeks Scenario Stress Matrix.

    Objectif :
    - tester mécaniquement la sensibilité des expositions publiques à différents scénarios spot/IV ;
    - détecter les zones où le delta drift, le GEX ou le charm deviennent instables ;
    - rester prudent : ce n'est pas du dealer flow, seulement une simulation proxy Black-Scholes sur IV/OI publics.
    """
    empty_summary = {
        "scenario_state": "N/A",
        "scenario_score": None,
        "worst_scenario": "N/A",
        "worst_delta_drift": None,
        "worst_downside_drift": None,
        "worst_upside_drift": None,
        "gex_sign_flips": 0,
        "base_net_delta": None,
        "base_net_gex": None,
        "message": "Scenario stress indisponible.",
    }

    if spot is None or spot <= 0:
        return pd.DataFrame(), empty_summary

    option_rows = _prepare_scenario_option_rows(
        calls=calls,
        puts=puts,
        spot=spot,
        window_pct=window_pct,
    )

    if option_rows.empty:
        return pd.DataFrame(), empty_summary

    spot_shocks = [-0.05, -0.03, -0.02, -0.01, 0.00, 0.01, 0.02, 0.03, 0.05]
    vol_shocks = [-0.05, 0.00, 0.05]

    base = _compute_scenario_exposures(
        option_rows=option_rows,
        shocked_spot=spot,
        vol_shift=0.0,
    )

    base_delta = safe_float(base.get("net_delta_notional"), 0.0) or 0.0
    base_gex = safe_float(base.get("net_gex_proxy"), 0.0) or 0.0
    base_abs_gex = safe_float(base.get("abs_gex_proxy"), 0.0) or 0.0

    rows = []

    for spot_shock in spot_shocks:
        shocked_spot = spot * (1.0 + spot_shock)

        for vol_shift in vol_shocks:
            expo = _compute_scenario_exposures(
                option_rows=option_rows,
                shocked_spot=shocked_spot,
                vol_shift=vol_shift,
            )

            net_delta = safe_float(expo.get("net_delta_notional"), 0.0) or 0.0
            net_gex = safe_float(expo.get("net_gex_proxy"), 0.0) or 0.0
            abs_gex = safe_float(expo.get("abs_gex_proxy"), 0.0) or 0.0
            net_charm = safe_float(expo.get("net_charm_1d"), 0.0) or 0.0
            net_vanna = safe_float(expo.get("net_vanna_1vol"), 0.0) or 0.0

            delta_drift = net_delta - base_delta
            gex_drift = net_gex - base_gex

            abs_gex_change = None
            if base_abs_gex > 0:
                abs_gex_change = abs_gex / base_abs_gex - 1.0

            sign_flip = False
            if abs(base_gex) > _EPS and abs(net_gex) > _EPS:
                sign_flip = np.sign(base_gex) != np.sign(net_gex)

            if net_gex > 0:
                gex_regime = "Gamma positif proxy"
            elif net_gex < 0:
                gex_regime = "Gamma négatif proxy"
            else:
                gex_regime = "Neutre"

            rows.append({
                "Spot shock": spot_shock,
                "Vol shock": vol_shift,
                "Scenario spot": shocked_spot,
                "Net delta notional": net_delta,
                "Delta drift notional": delta_drift,
                "Net GEX proxy": net_gex,
                "GEX drift": gex_drift,
                "Abs GEX proxy": abs_gex,
                "Abs GEX change": abs_gex_change,
                "Charm 1D": net_charm,
                "Vanna 1 vol pt": net_vanna,
                "GEX sign flip": sign_flip,
                "Regime": gex_regime,
            })

    out = pd.DataFrame(rows)

    if out.empty:
        return pd.DataFrame(), empty_summary

    out["abs_delta_drift"] = pd.to_numeric(out["Delta drift notional"], errors="coerce").abs()
    out["abs_gex_drift"] = pd.to_numeric(out["GEX drift"], errors="coerce").abs()

    worst_idx = out["abs_delta_drift"].idxmax()
    worst_row = out.loc[worst_idx]

    downside = out[out["Spot shock"] < 0].copy()
    upside = out[out["Spot shock"] > 0].copy()

    worst_downside_drift = None
    worst_upside_drift = None

    if not downside.empty:
        worst_downside_drift = safe_float(
            downside.loc[downside["abs_delta_drift"].idxmax(), "Delta drift notional"]
        )

    if not upside.empty:
        worst_upside_drift = safe_float(
            upside.loc[upside["abs_delta_drift"].idxmax(), "Delta drift notional"]
        )

    gex_sign_flips = int(out["GEX sign flip"].fillna(False).sum())

    total_oi = safe_float(option_rows["openInterest"].sum(), 0.0) or 0.0
    oi_notional_ref = max(total_oi * CONTRACT_SIZE * spot, 1.0)

    worst_delta_drift = safe_float(worst_row.get("Delta drift notional"), 0.0) or 0.0
    drift_ratio = abs(worst_delta_drift) / oi_notional_ref

    gex_flip_score = 25.0 if gex_sign_flips > 0 else 0.0
    drift_score = clamp(drift_ratio / 0.08 * 70.0)
    gex_drift_score = clamp((safe_float(out["abs_gex_drift"].max(), 0.0) or 0.0) / max(base_abs_gex, 1.0) * 35.0)

    scenario_score = clamp(
        25.0
        + 0.45 * drift_score
        + 0.35 * gex_drift_score
        + 0.20 * gex_flip_score
    )

    if scenario_score >= 80:
        scenario_state = "Stress convexité élevé"
        message = (
            "Stress scénario élevé : les expositions proxy changent fortement sous choc spot/IV. "
            "À utiliser pour cadrer l'exécution, pas comme signal directionnel certain."
        )
    elif scenario_score >= 60:
        scenario_state = "Stress convexité à surveiller"
        message = (
            "Stress scénario à surveiller : delta drift ou GEX drift visibles sous choc spot/IV, "
            "sans conclusion dealer-flow institutionnelle."
        )
    elif scenario_score >= 40:
        scenario_state = "Stress scénario modéré"
        message = (
            "Stress scénario modéré : les expositions bougent, mais sans instabilité majeure détectée."
        )
    else:
        scenario_state = "Stress scénario contenu"
        message = (
            "Stress scénario contenu : pas de changement violent détecté dans les expositions proxy."
        )

    worst_scenario = (
        f"Spot {fmt_signed_pct(worst_row.get('Spot shock'))} · "
        f"IV {fmt_vol_points(worst_row.get('Vol shock'))}"
    )

    summary = {
        "scenario_state": scenario_state,
        "scenario_score": scenario_score,
        "worst_scenario": worst_scenario,
        "worst_delta_drift": worst_delta_drift,
        "worst_downside_drift": worst_downside_drift,
        "worst_upside_drift": worst_upside_drift,
        "gex_sign_flips": gex_sign_flips,
        "base_net_delta": base_delta,
        "base_net_gex": base_gex,
        "message": message,
    }

    return out.drop(columns=["abs_delta_drift", "abs_gex_drift"], errors="ignore"), summary


def render_gamma_scenario_stress_matrix(
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    spot: float,
    metrics: Dict[str, Any],
    window_pct: float,
) -> None:
    """
    Affichage Gamma / Greeks Scenario Stress Matrix.
    À placer dans Gamma Proxy après Expiration Fragility Monitor.
    """
    st.markdown("### Gamma / Greeks Scenario Stress Matrix")

    scenario_df, summary = build_gamma_scenario_stress_matrix(
        calls=calls,
        puts=puts,
        spot=spot,
        metrics=metrics,
        window_pct=window_pct,
    )

    if scenario_df is None or scenario_df.empty:
        st.info("Scenario stress indisponible : options/OI/IV insuffisants dans la fenêtre sélectionnée.")
        return

    render_card_grid([
        (
            "Scenario state",
            str(summary.get("scenario_state", "N/A")),
            fmt_score(summary.get("scenario_score")),
        ),
        (
            "Worst scenario",
            str(summary.get("worst_scenario", "N/A")),
            "Max delta drift",
        ),
        (
            "Worst delta drift",
            fmt_large(summary.get("worst_delta_drift")),
            "vs scénario spot/IV actuel",
        ),
        (
            "GEX sign flips",
            fmt_int(summary.get("gex_sign_flips")),
            "Sur grille scénario",
        ),
    ])

    score = safe_float(summary.get("scenario_score"), 50.0) or 50.0

    if score >= 75:
        st.warning(summary.get("message", "Stress scénario élevé."))
    elif score >= 55:
        st.info(summary.get("message", "Stress scénario à surveiller."))
    else:
        st.info(summary.get("message", "Stress scénario contenu."))

    # Heatmap delta drift : Spot shock x Vol shock.
    heat = scenario_df.copy()
    heat["Spot shock"] = pd.to_numeric(heat["Spot shock"], errors="coerce")
    heat["Vol shock"] = pd.to_numeric(heat["Vol shock"], errors="coerce")
    heat["Delta drift notional"] = pd.to_numeric(heat["Delta drift notional"], errors="coerce")
    heat = heat.dropna(subset=["Spot shock", "Vol shock", "Delta drift notional"])

    if not heat.empty:
        pivot = heat.pivot_table(
            index="Vol shock",
            columns="Spot shock",
            values="Delta drift notional",
            aggfunc="median",
        ).sort_index().sort_index(axis=1)

        fig = go.Figure()

        fig.add_trace(
            go.Heatmap(
                z=pivot.to_numpy(dtype=float),
                x=[float(x) for x in pivot.columns],
                y=[float(y) for y in pivot.index],
                colorscale="RdBu",
                zmid=0,
                colorbar=dict(title="Delta drift"),
                hovertemplate=(
                    "Spot shock %{x:+.1%}<br>"
                    "Vol shock %{y:+.1%}<br>"
                    "Delta drift %{z:,.0f}"
                    "<extra></extra>"
                ),
            )
        )

        fig.update_layout(
            title="Delta-notional drift sous scénarios spot / IV",
            xaxis_title="Spot shock",
            yaxis_title="Vol shock",
        )
        spot_tickvals = sorted(heat["Spot shock"].dropna().unique())
        vol_tickvals = sorted(heat["Vol shock"].dropna().unique())

        fig.update_xaxes(
            tickvals=spot_tickvals,
            ticktext=[fmt_signed_pct(x) for x in spot_tickvals],
        )

        fig.update_yaxes(
            tickvals=vol_tickvals,
            ticktext=[fmt_vol_points(x) for x in vol_tickvals],
        )

        st.plotly_chart(apply_dark_layout(fig, 480), width="stretch")

    # Ligne GEX sous vol inchangée.
    line_df = scenario_df[
        pd.to_numeric(scenario_df["Vol shock"], errors="coerce").abs() < 1e-9
    ].copy()

    if not line_df.empty:
        line_df = line_df.sort_values("Spot shock")

        fig2 = go.Figure()

        fig2.add_trace(
            go.Scatter(
                x=line_df["Spot shock"],
                y=line_df["Net GEX proxy"],
                mode="lines+markers",
                name="Net GEX proxy",
                hovertemplate=(
                    "Spot shock %{x:+.1%}<br>"
                    "Net GEX %{y:,.0f}"
                    "<extra></extra>"
                ),
            )
        )

        fig2.add_hline(y=0, line_dash="dash", line_color="white")

        fig2.update_layout(
            title="Net GEX proxy sous choc spot — IV inchangée",
            xaxis_title="Spot shock",
            yaxis_title="Net GEX proxy",
        )
        spot_tickvals_2 = sorted(line_df["Spot shock"].dropna().unique())

        fig2.update_xaxes(
            tickvals=spot_tickvals_2,
            ticktext=[fmt_signed_pct(x) for x in spot_tickvals_2],
        )

        st.plotly_chart(apply_dark_layout(fig2, 420), width="stretch")

    display_cols = [
        "Spot shock",
        "Vol shock",
        "Scenario spot",
        "Net delta notional",
        "Delta drift notional",
        "Net GEX proxy",
        "GEX drift",
        "Abs GEX proxy",
        "Abs GEX change",
        "Charm 1D",
        "Vanna 1 vol pt",
        "GEX sign flip",
        "Regime",
    ]

    display = scenario_df[[c for c in display_cols if c in scenario_df.columns]].copy()

    # On met les scénarios les plus sensibles en haut.
    display["_rank"] = pd.to_numeric(display["Delta drift notional"], errors="coerce").abs()
    display = display.sort_values("_rank", ascending=False).drop(columns=["_rank"]).head(15)

    if "Spot shock" in display.columns:
        display["Spot shock"] = display["Spot shock"].map(fmt_signed_pct)

    if "Vol shock" in display.columns:
        display["Vol shock"] = display["Vol shock"].map(fmt_vol_points)

    if "Scenario spot" in display.columns:
        display["Scenario spot"] = display["Scenario spot"].map(fmt_price)

    for c in [
        "Net delta notional",
        "Delta drift notional",
        "Net GEX proxy",
        "GEX drift",
        "Abs GEX proxy",
        "Charm 1D",
        "Vanna 1 vol pt",
    ]:
        if c in display.columns:
            display[c] = display[c].map(fmt_large)

    if "Abs GEX change" in display.columns:
        display["Abs GEX change"] = display["Abs GEX change"].map(fmt_signed_pct)

    if "GEX sign flip" in display.columns:
        display["GEX sign flip"] = display["GEX sign flip"].map(
            lambda x: "Oui" if bool(x) else "Non"
        )

    st.dataframe(
        display,
        width="stretch",
        hide_index=True,
    )

    st.caption(
        "Gamma / Greeks Scenario Stress Matrix = recalcul mécanique des greeks Black-Scholes sous chocs spot/IV. "
        "Basé sur IV publique et open interest yfinance : ce n'est ni du dealer flow, ni une prévision, ni une preuve d'arbitrage. "
        "Le bloc sert surtout à cadrer le risque d'exécution autour des zones convexes."
    )



def render_gex_chart(
    gex_df: pd.DataFrame,
    spot: float,
    gamma_flip: Optional[float],
    window_pct: float = 0.20,
) -> None:
    if gex_df is None or gex_df.empty:
        st.info("Gamma proxy indisponible : IV ou OI insuffisants.")
        return

    plot_df = gex_df.copy()

    for col in ["strike", "signed_gex", "cum_gex"]:
        if col in plot_df.columns:
            plot_df[col] = pd.to_numeric(plot_df[col], errors="coerce")

    plot_df = plot_df.dropna(subset=["strike"]).sort_values("strike").reset_index(drop=True)

    low = spot * (1.0 - window_pct)
    high = spot * (1.0 + window_pct)

    window_df = plot_df[
        (plot_df["strike"] >= low)
        & (plot_df["strike"] <= high)
    ].copy()

    # Fallback prudent si la fenêtre est trop pauvre.
    if len(window_df) >= 5:
        plot_df = window_df
    else:
        plot_df = plot_df.sort_values("abs_gex", ascending=False).head(40).sort_values("strike")

    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            x=plot_df["strike"],
            y=plot_df["signed_gex"],
            name="Signed GEX proxy",
            hovertemplate=(
                "Strike %{x:.2f}<br>"
                "Signed GEX %{y:,.0f}"
                "<extra></extra>"
            ),
        )
    )

    fig.add_trace(
        go.Scatter(
            x=plot_df["strike"],
            y=plot_df["cum_gex"],
            mode="lines",
            name="Cumulative GEX",
            hovertemplate=(
                "Strike %{x:.2f}<br>"
                "Cumulative GEX %{y:,.0f}"
                "<extra></extra>"
            ),
        )
    )

    add_spot_line(fig, spot, "Spot")

    if gamma_flip is not None:
        gf = safe_float(gamma_flip)

        if gf is not None and low <= gf <= high:
            fig.add_vline(
                x=gf,
                line_dash="dot",
                line_color="orange",
                annotation_text=f"Gamma flip {fmt_price(gf)}",
            )

    fig.update_layout(
        title=f"Gamma exposure proxy par strike — fenêtre ±{int(window_pct * 100)}%",
        xaxis_title="Strike",
        yaxis_title="GEX proxy",
    )

    st.plotly_chart(apply_dark_layout(fig, 560), width="stretch")

    st.caption(
        "Graphique GEX borné autour du spot pour éviter que des strikes très éloignés compressent la lecture. "
        "Le calcul global reste inchangé."
    )


def render_term_structure_chart(term_df: pd.DataFrame) -> None:
    if term_df is None or term_df.empty:
        st.info("Term structure indisponible.")
        return
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=term_df["dte"], y=term_df["atm_iv"], mode="lines+markers", name="ATM IV"))
    fig.add_trace(go.Scatter(x=term_df["dte"], y=term_df["expected_move_pct"], mode="lines+markers", name="Expected move"))
    fig.update_layout(title="IV term structure & expected move")
    fig.update_xaxes(title="Jours à expiration")
    fig.update_yaxes(title="%", tickformat=".0%")
    st.plotly_chart(apply_dark_layout(fig, 480), width="stretch")


def build_forward_variance_diagnostics(term_df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Forward Variance / Calendar Diagnostics.

    Objectif :
    - transformer la term structure ATM IV en segments forward ;
    - détecter les poches de forward vol, backwardation/front stress, contango IV ;
    - signaler une décroissance de variance totale comme warning qualité/calendar, pas comme arbitrage certain.

    Prudence :
    - basé uniquement sur ATM IV publique yfinance ;
    - pas une surface OPRA institutionnelle ;
    - ne modifie pas le score global dérivés.
    """
    empty_summary = {
        "calendar_state": "N/A",
        "calendar_score": None,
        "max_forward_iv": None,
        "max_forward_segment": "N/A",
        "max_forward_premium": None,
        "front_calendar_spread": None,
        "overall_term_slope": None,
        "variance_warnings": 0,
    }

    if term_df is None or term_df.empty:
        return pd.DataFrame(), empty_summary

    df = term_df.copy()

    for col in ["dte", "atm_iv", "total_oi", "total_volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "expiration" not in df.columns or "dte" not in df.columns or "atm_iv" not in df.columns:
        return pd.DataFrame(), empty_summary

    df = df.dropna(subset=["expiration", "dte", "atm_iv"]).copy()
    df = df[(df["atm_iv"] > 0) & (df["atm_iv"] < 5) & (df["dte"] >= 0)].copy()
    df = df.sort_values("dte").drop_duplicates(subset=["dte"], keep="first").reset_index(drop=True)

    if len(df) < 2:
        return pd.DataFrame(), empty_summary

    rows: List[Dict[str, Any]] = []

    for i in range(len(df) - 1):
        near = df.iloc[i]
        far = df.iloc[i + 1]

        exp1 = str(near.get("expiration", ""))
        exp2 = str(far.get("expiration", ""))

        dte1 = safe_float(near.get("dte"))
        dte2 = safe_float(far.get("dte"))
        iv1 = safe_float(near.get("atm_iv"))
        iv2 = safe_float(far.get("atm_iv"))

        if dte1 is None or dte2 is None or iv1 is None or iv2 is None:
            continue

        if dte2 <= dte1:
            continue

        # Floor prudent : 0DTE converti en 1 jour pour éviter division par zéro.
        t1 = max(float(dte1), 1.0) / 365.0
        t2 = max(float(dte2), 1.0) / 365.0

        total_var_1 = iv1 * iv1 * t1
        total_var_2 = iv2 * iv2 * t2
        delta_total_var = total_var_2 - total_var_1

        variance_warning = bool(delta_total_var < -1e-8)

        forward_iv = None
        forward_premium = None

        if not variance_warning and (t2 - t1) > _EPS:
            forward_var = delta_total_var / max(t2 - t1, _EPS)
            if forward_var >= 0:
                forward_iv = math.sqrt(forward_var)
                forward_premium = forward_iv - max(iv1, iv2)

        calendar_spread = iv2 - iv1
        mid_dte = (dte1 + dte2) / 2.0

        if variance_warning:
            regime = "Variance warning"
            lecture = (
                "Variance totale décroissante entre deux maturités. "
                "Avec données publiques, lire comme warning qualité/calendar, pas comme arbitrage certain."
            )
        elif calendar_spread <= -0.06:
            regime = "Backwardation front"
            lecture = "Front-end nettement plus cher que l'expiration suivante : stress court terme ou événement à vérifier."
        elif calendar_spread <= -0.03:
            regime = "Backwardation légère"
            lecture = "Front-end plus cher : tension courte maturité présente mais non extrême."
        elif forward_premium is not None and forward_premium >= 0.10:
            regime = "Forward pocket élevée"
            lecture = "Forward IV élevée entre deux expirations : poche de prime événementielle ou bruit de surface à surveiller."
        elif calendar_spread >= 0.05:
            regime = "Contango IV"
            lecture = "Maturité suivante plus chère : structure ascendante, pas de stress front-end dominant sur ce segment."
        else:
            regime = "Normal"
            lecture = "Segment calendar cohérent, sans tension forward majeure."

        rows.append({
            "Segment": f"{exp1} → {exp2}",
            "DTE range": f"{fmt_num(dte1, 0)} → {fmt_num(dte2, 0)}",
            "Near ATM IV": iv1,
            "Far ATM IV": iv2,
            "IV calendar spread": calendar_spread,
            "Forward IV": forward_iv,
            "Forward premium": forward_premium,
            "Total variance Δ": delta_total_var,
            "Variance monotonicity": "Warning" if variance_warning else "OK",
            "Regime": regime,
            "Lecture": lecture,
            "_mid_dte": mid_dte,
        })

    out = pd.DataFrame(rows)

    if out.empty:
        return out, empty_summary

    variance_warnings = int((out["Variance monotonicity"] == "Warning").sum())

    valid_forward = out.dropna(subset=["Forward IV"]).copy()
    max_forward_iv = None
    max_forward_segment = "N/A"
    max_forward_premium = None

    if not valid_forward.empty:
        idx = valid_forward["Forward IV"].idxmax()
        max_forward_iv = safe_float(valid_forward.loc[idx, "Forward IV"])
        max_forward_segment = str(valid_forward.loc[idx, "Segment"])
        max_forward_premium = safe_float(valid_forward["Forward premium"].max())

    front_calendar_spread = safe_float(out["IV calendar spread"].iloc[0]) if not out.empty else None

    first_iv = safe_float(df["atm_iv"].iloc[0])
    last_iv = safe_float(df["atm_iv"].iloc[-1])
    overall_term_slope = None

    if first_iv is not None and last_iv is not None:
        overall_term_slope = last_iv - first_iv

    # Score descriptif : plus haut = plus de tension calendar/forward.
    score = 35.0

    if front_calendar_spread is not None:
        # Front backwardation = stress plus important que contango.
        score += clamp(max(-front_calendar_spread, 0.0) * 520.0, 0.0, 30.0)

    if max_forward_premium is not None:
        score += clamp(max(max_forward_premium, 0.0) * 220.0, 0.0, 25.0)

    if variance_warnings > 0:
        score += min(25.0, variance_warnings * 12.5)

    if overall_term_slope is not None and overall_term_slope < -0.06:
        score += 10.0

    score = clamp(score)

    if variance_warnings > 0:
        calendar_state = "Variance à vérifier"
    elif front_calendar_spread is not None and front_calendar_spread <= -0.06:
        calendar_state = "Backwardation / front stress"
    elif max_forward_premium is not None and max_forward_premium >= 0.10:
        calendar_state = "Forward pocket élevée"
    elif overall_term_slope is not None and overall_term_slope >= 0.04:
        calendar_state = "Contango IV"
    elif overall_term_slope is not None and overall_term_slope <= -0.04:
        calendar_state = "Backwardation IV"
    else:
        calendar_state = "Structure normale"

    summary = {
        "calendar_state": calendar_state,
        "calendar_score": score,
        "max_forward_iv": max_forward_iv,
        "max_forward_segment": max_forward_segment,
        "max_forward_premium": max_forward_premium,
        "front_calendar_spread": front_calendar_spread,
        "overall_term_slope": overall_term_slope,
        "variance_warnings": variance_warnings,
    }

    return out, summary


def render_forward_variance_diagnostics(term_df: pd.DataFrame) -> None:
    """
    Affichage Forward Variance / Calendar Diagnostics.
    À placer dans l'onglet Options Surface après la term structure.
    """
    st.subheader("Forward Variance / Calendar Diagnostics")

    forward_df, summary = build_forward_variance_diagnostics(term_df)

    if forward_df is None or forward_df.empty:
        st.info("Forward variance indisponible : pas assez d'expirations ATM IV propres.")
        return

    render_card_grid([
        (
            "Calendar state",
            str(summary.get("calendar_state", "N/A")),
            fmt_score(summary.get("calendar_score")),
        ),
        (
            "Max forward IV",
            fmt_pct(summary.get("max_forward_iv")),
            str(summary.get("max_forward_segment", "N/A")),
        ),
        (
            "Forward premium max",
            fmt_pct(summary.get("max_forward_premium")),
            "Forward IV - max near/far IV",
        ),
        (
            "Variance warnings",
            fmt_int(summary.get("variance_warnings")),
            "Monotonicité variance totale",
        ),
    ])

    calendar_score = safe_float(summary.get("calendar_score"), 50.0) or 50.0
    variance_warnings = safe_int(summary.get("variance_warnings"), 0) or 0

    if variance_warnings > 0:
        st.warning(
            "Warning calendar : une ou plusieurs paires montrent une variance totale décroissante. "
            "Avec yfinance/public chain, c'est surtout un signal de qualité de données ou de surface bruitée, pas un arbitrage certain."
        )
    elif calendar_score >= 70:
        st.warning(
            "Tension calendar/forward notable : la term structure indique une poche de volatilité ou une pression court terme à surveiller."
        )
    elif calendar_score >= 55:
        st.info(
            "Calendar structure à surveiller : pas bloquant, mais la forme forward n'est pas totalement neutre."
        )
    else:
        st.info(
            "Calendar structure propre : pas de tension forward majeure détectée sur les expirations retenues."
        )

    display_cols = [
        "Segment",
        "DTE range",
        "Near ATM IV",
        "Far ATM IV",
        "IV calendar spread",
        "Forward IV",
        "Forward premium",
        "Variance monotonicity",
        "Regime",
        "Lecture",
    ]

    st.dataframe(
        format_display_df(forward_df[[c for c in display_cols if c in forward_df.columns]]),
        width="stretch",
        hide_index=True,
    )

    # Chart : ATM IV term structure vs forward IV segments.
    fig = go.Figure()

    clean_term = term_df.copy()
    clean_term["dte"] = pd.to_numeric(clean_term.get("dte"), errors="coerce")
    clean_term["atm_iv"] = pd.to_numeric(clean_term.get("atm_iv"), errors="coerce")
    clean_term = clean_term.dropna(subset=["dte", "atm_iv"]).sort_values("dte")

    if not clean_term.empty:
        fig.add_trace(
            go.Scatter(
                x=clean_term["dte"],
                y=clean_term["atm_iv"],
                mode="lines+markers",
                name="ATM IV",
                hovertemplate="DTE %{x:.0f}<br>ATM IV %{y:.2%}<extra></extra>",
            )
        )

    plot_forward = forward_df.dropna(subset=["_mid_dte", "Forward IV"]).copy()

    if not plot_forward.empty:
        fig.add_trace(
            go.Scatter(
                x=plot_forward["_mid_dte"],
                y=plot_forward["Forward IV"],
                mode="lines+markers",
                name="Forward IV segment",
                hovertemplate="Mid DTE %{x:.1f}<br>Forward IV %{y:.2%}<extra></extra>",
            )
        )

    fig.update_layout(
        title="ATM IV vs Forward IV segments",
        xaxis_title="Jours à expiration",
        yaxis_title="Volatilité implicite",
    )
    fig.update_yaxes(tickformat=".0%")

    st.plotly_chart(apply_dark_layout(fig, 480), width="stretch")

    st.caption(
        "Forward variance = extraction mécanique entre deux maturités adjacentes : "
        "fwd_var = (IV2²×T2 - IV1²×T1) / (T2 - T1). "
        "Sur données publiques, ce bloc sert de diagnostic calendar/qualité, pas de preuve d'arbitrage."
    )


# ============================================================
# Event / Earnings Vol Premium diagnostics
# ============================================================

def _normalize_event_timestamp(value: Any) -> Optional[pd.Timestamp]:
    """
    Convertit prudemment une date yfinance en Timestamp sans timezone.
    Retourne une date normalisée à minuit pour comparaison calendar.
    """
    try:
        if value is None:
            return None

        ts = pd.to_datetime(value, errors="coerce")

        if isinstance(ts, pd.DatetimeIndex):
            if len(ts) == 0:
                return None
            ts = ts[0]

        if pd.isna(ts):
            return None

        ts = pd.Timestamp(ts)

        if ts.tzinfo is not None:
            ts = ts.tz_convert(None)

        return pd.Timestamp(ts.date())

    except Exception:
        return None


def _flatten_event_date_candidates(value: Any) -> List[Any]:
    """
    Déplie les formats possibles retournés par yfinance :
    scalar, liste, Series, DataFrame, DatetimeIndex.
    """
    if value is None:
        return []

    if isinstance(value, pd.DataFrame):
        vals: List[Any] = []
        for col in value.columns:
            vals.extend(value[col].dropna().tolist())
        vals.extend(list(value.index))
        return vals

    if isinstance(value, pd.Series):
        return value.dropna().tolist()

    if isinstance(value, pd.DatetimeIndex):
        return list(value)

    if isinstance(value, (list, tuple, set, np.ndarray)):
        return list(value)

    return [value]


@st.cache_data(ttl=3600, show_spinner=False)
def get_event_calendar_cached(ticker: str) -> pd.DataFrame:
    """
    Récupération prudente des dates événementielles via yfinance.

    Priorité :
    - Ticker.calendar quand disponible ;
    - Ticker.get_earnings_dates quand disponible.

    Important :
    - Ces dates publiques peuvent être absentes, approximatives ou sous forme de range.
    - On ne les utilise pas comme vérité institutionnelle.
    """
    ticker = str(ticker or "").upper().strip()

    if not ticker:
        return pd.DataFrame()

    events: List[Dict[str, Any]] = []

    try:
        tk = yf.Ticker(ticker)

        # 1) calendar yfinance
        try:
            cal = getattr(tk, "calendar", None)

            if callable(cal):
                cal = cal()

            if isinstance(cal, dict):
                for key, value in cal.items():
                    k = str(key).lower()

                    if "earn" in k and "date" in k:
                        for candidate in _flatten_event_date_candidates(value):
                            dt = _normalize_event_timestamp(candidate)
                            if dt is not None:
                                events.append({
                                    "event_type": "Earnings",
                                    "event_date": dt,
                                    "source": "yfinance.calendar",
                                    "confidence": 65,
                                })

                    elif "ex-dividend" in k or "ex dividend" in k:
                        for candidate in _flatten_event_date_candidates(value):
                            dt = _normalize_event_timestamp(candidate)
                            if dt is not None:
                                events.append({
                                    "event_type": "Ex-dividend",
                                    "event_date": dt,
                                    "source": "yfinance.calendar",
                                    "confidence": 45,
                                })

            elif isinstance(cal, pd.DataFrame):
                for idx, row in cal.iterrows():
                    label = str(idx).lower()

                    if "earn" in label and "date" in label:
                        for candidate in _flatten_event_date_candidates(row):
                            dt = _normalize_event_timestamp(candidate)
                            if dt is not None:
                                events.append({
                                    "event_type": "Earnings",
                                    "event_date": dt,
                                    "source": "yfinance.calendar",
                                    "confidence": 65,
                                })

            elif isinstance(cal, pd.Series):
                for idx, value in cal.items():
                    label = str(idx).lower()

                    if "earn" in label and "date" in label:
                        for candidate in _flatten_event_date_candidates(value):
                            dt = _normalize_event_timestamp(candidate)
                            if dt is not None:
                                events.append({
                                    "event_type": "Earnings",
                                    "event_date": dt,
                                    "source": "yfinance.calendar",
                                    "confidence": 65,
                                })

        except Exception:
            pass

        # 2) fallback : earnings dates
        try:
            if hasattr(tk, "get_earnings_dates"):
                edf = tk.get_earnings_dates(limit=16)

                if edf is not None and not edf.empty:
                    for idx in edf.index:
                        dt = _normalize_event_timestamp(idx)
                        if dt is not None:
                            events.append({
                                "event_type": "Earnings",
                                "event_date": dt,
                                "source": "yfinance.get_earnings_dates",
                                "confidence": 70,
                            })

                    # Certaines versions mettent la date en colonne.
                    for col in edf.columns:
                        if "earn" in str(col).lower() and "date" in str(col).lower():
                            for candidate in edf[col].dropna().tolist():
                                dt = _normalize_event_timestamp(candidate)
                                if dt is not None:
                                    events.append({
                                        "event_type": "Earnings",
                                        "event_date": dt,
                                        "source": "yfinance.get_earnings_dates",
                                        "confidence": 70,
                                    })

        except Exception:
            pass

    except Exception:
        return pd.DataFrame()

    if not events:
        return pd.DataFrame()

    out = pd.DataFrame(events)
    out = out.dropna(subset=["event_date"]).copy()

    if out.empty:
        return pd.DataFrame()

    out["event_date"] = pd.to_datetime(out["event_date"], errors="coerce").dt.tz_localize(None)
    out = out.dropna(subset=["event_date"])

    # Déduplication prudente par type/date.
    out["_date_key"] = out["event_date"].dt.strftime("%Y-%m-%d")
    out = (
        out.sort_values(["event_date", "confidence"], ascending=[True, False])
        .drop_duplicates(subset=["event_type", "_date_key"], keep="first")
        .drop(columns=["_date_key"])
        .reset_index(drop=True)
    )

    return out


def build_event_vol_premium_diagnostics(
    ticker: str,
    term_df: pd.DataFrame,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Diagnostic Event / Earnings Vol Premium.

    Logique :
    - reprend la term structure ATM IV ;
    - extrait les forward IV par segment ;
    - vérifie si le prochain earnings tombe dans un segment forward ;
    - compare la forward IV et sa prime à la structure.

    Prudence :
    - si la date earnings est absente ou approximative, le bloc reste informatif ;
    - ne prouve pas une prime événementielle ;
    - ne modifie pas le score global dérivés.
    """
    empty_summary = {
        "event_state": "Événement indisponible",
        "event_score": None,
        "next_event_date": None,
        "next_event_dte": None,
        "next_event_type": "N/A",
        "event_segment": "N/A",
        "event_forward_iv": None,
        "event_forward_premium": None,
        "event_source": "N/A",
        "event_confidence": None,
    }

    if term_df is None or term_df.empty:
        return pd.DataFrame(), empty_summary

    forward_df, forward_summary = build_forward_variance_diagnostics(term_df)

    if forward_df is None or forward_df.empty:
        return pd.DataFrame(), empty_summary

    events = get_event_calendar_cached(ticker)

    today = pd.Timestamp(datetime.utcnow().date())

    if events is None or events.empty:
        out = forward_df.copy()
        out["Event date"] = "N/A"
        out["Event DTE"] = "N/A"
        out["Event match"] = "Aucun événement public trouvé"
        out["Event source"] = "N/A"
        out["Event confidence"] = "N/A"
        out["Event lecture"] = (
            "Date earnings/event indisponible via yfinance : impossible d'attribuer la poche forward."
        )

        summary = dict(empty_summary)
        summary["event_state"] = "Earnings non trouvé"
        summary["event_score"] = 35.0

        return out, summary

    events = events.copy()
    events["event_date"] = pd.to_datetime(events["event_date"], errors="coerce").dt.tz_localize(None)
    events = events.dropna(subset=["event_date"])
    events["event_dte"] = (events["event_date"] - today).dt.days

    # On garde les prochains événements. Tolérance -1 jour pour les décalages timezone/publication.
    future_events = events[events["event_dte"] >= -1].copy()

    if future_events.empty:
        out = forward_df.copy()
        out["Event date"] = "N/A"
        out["Event DTE"] = "N/A"
        out["Event match"] = "Pas d'événement futur"
        out["Event source"] = "N/A"
        out["Event confidence"] = "N/A"
        out["Event lecture"] = "Aucun événement futur exploitable dans le calendrier yfinance."

        summary = dict(empty_summary)
        summary["event_state"] = "Pas d'événement futur"
        summary["event_score"] = 35.0

        return out, summary


    # Priorité prudente :
    # 1) Earnings d'abord, car c'est le vrai driver potentiel de forward IV.
    # 2) Ex-dividend seulement si aucun earnings futur n'est disponible.
    earnings_events = future_events[
        future_events["event_type"].astype(str).str.lower().str.contains("earn", na=False)
    ].copy()

    if not earnings_events.empty:
        next_event = earnings_events.sort_values("event_date").iloc[0]
        event_priority_note = "Earnings prioritaire"
    else:
        next_event = future_events.sort_values("event_date").iloc[0]
        event_priority_note = "Aucun earnings futur trouvé ; fallback calendrier public"

    next_event_date = pd.Timestamp(next_event.get("event_date"))
    next_event_type = str(next_event.get("event_type", "Event"))
    next_event_source = str(next_event.get("source", "N/A"))
    next_event_confidence = safe_float(next_event.get("confidence"), 50.0)
    next_event_dte = safe_int(next_event.get("event_dte"))

    # Ex-dividend ou événement non-earnings : on baisse volontairement la portée du diagnostic.
    is_earnings_event = "earn" in str(next_event_type).lower()

    if not is_earnings_event:
        next_event_confidence = min(next_event_confidence or 45.0, 45.0)

    term = term_df.copy()

    for col in ["dte", "atm_iv"]:
        if col in term.columns:
            term[col] = pd.to_numeric(term[col], errors="coerce")

    term = term.dropna(subset=["expiration", "dte", "atm_iv"]).copy()
    term["_exp_date"] = pd.to_datetime(term["expiration"], errors="coerce").dt.tz_localize(None)
    term = term.dropna(subset=["_exp_date"]).sort_values("dte").reset_index(drop=True)

    if len(term) < 2:
        return pd.DataFrame(), empty_summary

    rows: List[Dict[str, Any]] = []

    # Médiane forward utile pour lecture relative.
    valid_forward = pd.to_numeric(forward_df.get("Forward IV", pd.Series(dtype=float)), errors="coerce").dropna()
    median_forward_iv = safe_float(valid_forward.median()) if not valid_forward.empty else None

    event_row_found = False
    event_segment = "N/A"
    event_forward_iv = None
    event_forward_premium = None

    for i in range(len(term) - 1):
        near = term.iloc[i]
        far = term.iloc[i + 1]

        exp1 = str(near.get("expiration", ""))
        exp2 = str(far.get("expiration", ""))
        segment_name = f"{exp1} → {exp2}"

        exp1_date = pd.Timestamp(near.get("_exp_date")).normalize()
        exp2_date = pd.Timestamp(far.get("_exp_date")).normalize()

        fwd_row = forward_df[forward_df["Segment"].astype(str) == segment_name]

        if fwd_row.empty:
            base = {
                "Segment": segment_name,
                "DTE range": f"{fmt_num(near.get('dte'), 0)} → {fmt_num(far.get('dte'), 0)}",
                "Near ATM IV": near.get("atm_iv"),
                "Far ATM IV": far.get("atm_iv"),
                "Forward IV": None,
                "Forward premium": None,
                "Regime": "N/A",
                "Variance monotonicity": "N/A",
            }
        else:
            r = fwd_row.iloc[0]
            base = {
                "Segment": segment_name,
                "DTE range": r.get("DTE range"),
                "Near ATM IV": r.get("Near ATM IV"),
                "Far ATM IV": r.get("Far ATM IV"),
                "Forward IV": r.get("Forward IV"),
                "Forward premium": r.get("Forward premium"),
                "Regime": r.get("Regime"),
                "Variance monotonicity": r.get("Variance monotonicity"),
            }

        fwd_iv = safe_float(base.get("Forward IV"))
        fwd_premium = safe_float(base.get("Forward premium"))

        event_match = "Hors segment"
        lecture = "Le prochain événement public ne tombe pas dans ce segment forward."

        # Segment forward = variance entre near expiry et far expiry.
        # Date-only : on reste volontairement prudent.
        if exp1_date < next_event_date <= exp2_date:
            event_match = "Dans segment forward"
            event_row_found = True
            event_segment = segment_name
            event_forward_iv = fwd_iv
            event_forward_premium = fwd_premium

            if fwd_premium is not None and fwd_premium >= 0.10:
                lecture = (
                    "Forward IV élevée sur le segment contenant l'événement : "
                    "prime événementielle plausible, à confirmer avec calendrier officiel et liquidité."
                )
            elif fwd_premium is not None and fwd_premium >= 0.04:
                lecture = (
                    "Événement présent dans le segment et prime forward modérée : "
                    "effet event possible mais non extrême."
                )
            else:
                lecture = (
                    "Événement présent dans le segment, mais prime forward limitée : "
                    "pas de stress événementiel clair dans les données publiques."
                )

        elif next_event_date == exp1_date:
            event_match = "Même date que near expiry"
            lecture = (
                "L'événement tombe sur la date de l'expiration near. "
                "Avec une date publique sans heure de publication, l'attribution est incertaine."
            )

        elif fwd_premium is not None and fwd_premium >= 0.10:
            lecture = (
                "Poche forward élevée sans correspondance avec le prochain événement public identifié : "
                "possible bruit de surface, autre catalyseur ou calendrier incomplet."
            )

        if median_forward_iv is not None and fwd_iv is not None:
            relative_fwd_premium = fwd_iv - median_forward_iv
        else:
            relative_fwd_premium = None

        row = dict(base)
        row.update({
            "Event type": next_event_type,
            "Event date": next_event_date.strftime("%Y-%m-%d"),
            "Event DTE": next_event_dte,
            "Event match": event_match,
            "Event priority": event_priority_note,
            "Event source": next_event_source,
            "Event confidence": next_event_confidence,
            "Forward IV vs median": relative_fwd_premium,
            "Event lecture": lecture,
        })

        rows.append(row)

    out = pd.DataFrame(rows)

    max_forward_premium = safe_float(forward_summary.get("max_forward_premium"))
    max_forward_iv = safe_float(forward_summary.get("max_forward_iv"))

    if event_row_found:
        if event_forward_premium is not None and event_forward_premium >= 0.10:
            event_state = "Prime event plausible"
            event_score = 68.0
        elif event_forward_premium is not None and event_forward_premium >= 0.04:
            event_state = "Prime event modérée"
            event_score = 55.0
        else:
            event_state = "Event sans prime claire"
            event_score = 42.0

    elif max_forward_premium is not None and max_forward_premium >= 0.10:
        event_state = "Forward pocket non expliquée"
        event_score = 60.0
    else:
        event_state = "Pas de prime event claire"
        event_score = 40.0

    summary = {
        "event_state": event_state,
        "event_score": event_score,
        "next_event_date": next_event_date.strftime("%Y-%m-%d"),
        "next_event_dte": next_event_dte,
        "next_event_type": next_event_type,
        "event_segment": event_segment,
        "event_forward_iv": event_forward_iv if event_forward_iv is not None else max_forward_iv,
        "event_forward_premium": event_forward_premium if event_forward_premium is not None else max_forward_premium,
        "event_source": next_event_source,
        "event_confidence": next_event_confidence,
    }

    return out, summary


def render_event_vol_premium_diagnostics(ticker: str, term_df: pd.DataFrame) -> None:
    """
    Affichage Event / Earnings Vol Premium.
    À placer sous Forward Variance / Calendar Diagnostics.
    """
    st.subheader("Event / Earnings Vol Premium")

    event_df, summary = build_event_vol_premium_diagnostics(ticker, term_df)

    if event_df is None or event_df.empty:
        st.info("Event vol premium indisponible : term structure ou calendrier événementiel insuffisant.")
        return

    render_card_grid([
        (
            "Event state",
            str(summary.get("event_state", "N/A")),
            fmt_score(summary.get("event_score")),
        ),
        (
            "Next event",
            str(summary.get("next_event_date", "N/A")),
            str(summary.get("next_event_type", "N/A")) + " · DTE " + fmt_int(summary.get("next_event_dte")),
        ),
        (
            "Event segment",
            str(summary.get("event_segment", "N/A")),
            "Source " + str(summary.get("event_source", "N/A")),
        ),
        (
            "Event forward premium",
            fmt_pct(summary.get("event_forward_premium")),
            "Forward IV " + fmt_pct(summary.get("event_forward_iv")),
        ),
    ])

    event_score = safe_float(summary.get("event_score"), 40.0) or 40.0
    event_state = str(summary.get("event_state", ""))

    if event_state == "Prime event plausible":
        st.warning(
            "Prime événementielle plausible : la poche de forward IV coïncide avec le prochain événement public identifié. "
            "À confirmer avec calendrier officiel, heure de publication et liquidité options."
        )
    elif event_state == "Forward pocket non expliquée":
        st.warning(
            "Forward pocket élevée non expliquée par le prochain événement public yfinance : "
            "possible autre catalyseur, bruit de surface ou calendrier incomplet."
        )
    elif event_score >= 50:
        st.info(
            "Événement identifié mais prime forward non extrême. Lecture utile, pas bloquante."
        )
    else:
        st.info(
            "Pas de prime événementielle claire détectée dans les expirations retenues."
        )

    display_cols = [
        "Segment",
        "DTE range",
        "Near ATM IV",
        "Far ATM IV",
        "Forward IV",
        "Forward premium",
        "Forward IV vs median",
        "Event type",
        "Event date",
        "Event DTE",
        "Event match",
        "Event priority",
        "Event source",
        "Event confidence",
        "Regime",
        "Event lecture",
    ]

    st.dataframe(
        format_display_df(event_df[[c for c in display_cols if c in event_df.columns]]),
        width="stretch",
        hide_index=True,
    )

    st.caption(
        "Event / Earnings Vol Premium = rapprochement mécanique entre forward variance et calendrier public yfinance. "
        "Ce n'est pas une preuve d'arbitrage ni une confirmation institutionnelle : les dates peuvent être approximatives, "
        "absentes ou dépendantes de l'heure de publication."
    )


# ============================================================
# Surface Integrity / No-Arbitrage Sanity Check
# ============================================================

def prepare_surface_integrity_points(
    surface: pd.DataFrame,
    spot: float,
    window_pct: float,
    min_oi: int = 10,
    min_volume: int = 1,
    max_spread_pct: float = 1.00,
) -> pd.DataFrame:
    """
    Prépare les lignes utilisées pour le contrôle d'intégrité de surface.
    Objectif : auditer les prix publics sans modifier les signaux.
    """
    if surface is None or surface.empty or spot is None or spot <= 0:
        return pd.DataFrame()

    df = surface.copy()
    df.columns = [str(c).strip() for c in df.columns]

    required = ["strike", "option_type", "expiration"]
    if any(c not in df.columns for c in required):
        return pd.DataFrame()

    for col in ["strike", "bid", "ask", "lastPrice", "volume", "openInterest", "dte"]:
        if col not in df.columns:
            df[col] = np.nan
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["volume"] = df["volume"].fillna(0)
    df["openInterest"] = df["openInterest"].fillna(0)
    df["option_type"] = df["option_type"].astype(str).str.lower().str.strip()
    df = df[df["option_type"].isin(["call", "put"])].copy()

    if df.empty:
        return pd.DataFrame()

    df["mid"] = np.where(
        (df["bid"] > 0) & (df["ask"] > 0),
        (df["bid"] + df["ask"]) / 2.0,
        df["lastPrice"],
    )

    df["spread"] = df["ask"] - df["bid"]
    df["spread_pct"] = df["spread"] / df["mid"].replace(0, np.nan)
    df["moneyness"] = df["strike"] / max(spot, _EPS)
    df["distance_spot"] = df["moneyness"] - 1.0

    df["bad_quote"] = (
        (df["bid"].notna() & (df["bid"] < 0))
        | (df["ask"].notna() & (df["ask"] < 0))
        | (df["bid"].notna() & df["ask"].notna() & (df["bid"] > df["ask"]) & (df["ask"] > 0))
    )

    df["mid_valid"] = df["mid"].notna() & (df["mid"] > 0)

    df["intrinsic"] = np.where(
        df["option_type"].eq("call"),
        np.maximum(spot - df["strike"], 0.0),
        np.maximum(df["strike"] - spot, 0.0),
    )

    df["price_tolerance"] = np.maximum(0.05, df["mid"].abs().fillna(0) * 0.015)

    df = df[
        (df["strike"].notna())
        & (df["moneyness"] >= 1.0 - window_pct)
        & (df["moneyness"] <= 1.0 + window_pct)
    ].copy()

    if df.empty:
        return pd.DataFrame()

    spread_ok = (
        df["spread_pct"].isna()
        | ((df["spread_pct"] >= 0) & (df["spread_pct"] <= max_spread_pct))
    )

    liquidity_ok = (
        (df["openInterest"] >= min_oi)
        | (df["volume"] >= min_volume)
    )

    df["used_for_integrity"] = (
        df["mid_valid"]
        & (~df["bad_quote"])
        & spread_ok
        & liquidity_ok
    )

    return df.sort_values(["expiration", "option_type", "strike"]).reset_index(drop=True)


def _vertical_and_butterfly_checks(clean_points: pd.DataFrame) -> Dict[str, int]:
    vertical_checks = 0
    vertical_violations = 0
    butterfly_checks = 0
    butterfly_violations = 0

    if clean_points is None or clean_points.empty:
        return {
            "vertical_checks": 0,
            "vertical_violations": 0,
            "butterfly_checks": 0,
            "butterfly_violations": 0,
        }

    for (exp, opt_type), g in clean_points.groupby(["expiration", "option_type"]):
        work = g[["strike", "mid"]].copy()
        work["strike"] = pd.to_numeric(work["strike"], errors="coerce")
        work["mid"] = pd.to_numeric(work["mid"], errors="coerce")
        work = work.dropna(subset=["strike", "mid"])

        if work.empty:
            continue

        work = (
            work.groupby("strike", as_index=False)
            .agg(mid=("mid", "median"))
            .sort_values("strike")
            .reset_index(drop=True)
        )

        if len(work) < 3:
            continue

        strikes = work["strike"].to_numpy(dtype=float)
        mids = work["mid"].to_numpy(dtype=float)

        diffs = np.diff(mids)
        pair_tol = np.maximum(0.05, 0.015 * np.maximum(np.abs(mids[:-1]), np.abs(mids[1:])))

        if len(diffs) > 0:
            vertical_checks += int(len(diffs))

            if str(opt_type).lower() == "call":
                vertical_violations += int(np.sum(diffs > pair_tol))
            else:
                vertical_violations += int(np.sum(diffs < -pair_tol))

        dk = np.diff(strikes)
        valid_gap = dk > 0

        if valid_gap.sum() < 2:
            continue

        slopes = np.diff(mids)[valid_gap] / dk[valid_gap]

        if len(slopes) < 2:
            continue

        slope_changes = np.diff(slopes)
        slope_tol = 0.08

        butterfly_checks += int(len(slope_changes))
        butterfly_violations += int(np.sum(slope_changes < -slope_tol))

    return {
        "vertical_checks": vertical_checks,
        "vertical_violations": vertical_violations,
        "butterfly_checks": butterfly_checks,
        "butterfly_violations": butterfly_violations,
    }


def _synthetic_forward_noise(clean_points: pd.DataFrame, spot: float) -> Tuple[Optional[float], int, int]:
    """
    Proxy put-call parity sans taux/dividende : F ≈ K + C - P.
    On ne cherche pas l'arbitrage ; on mesure seulement la dispersion intra-expiration.
    """
    if clean_points is None or clean_points.empty or spot is None or spot <= 0:
        return None, 0, 0

    calls = clean_points[clean_points["option_type"] == "call"][["expiration", "strike", "mid"]].copy()
    puts = clean_points[clean_points["option_type"] == "put"][["expiration", "strike", "mid"]].copy()

    if calls.empty or puts.empty:
        return None, 0, 0

    pairs = pd.merge(
        calls.rename(columns={"mid": "call_mid"}),
        puts.rename(columns={"mid": "put_mid"}),
        on=["expiration", "strike"],
        how="inner",
    )

    if pairs.empty:
        return None, 0, 0

    pairs["synthetic_forward"] = pairs["strike"] + pairs["call_mid"] - pairs["put_mid"]

    noises: List[float] = []
    checks = 0
    warnings = 0

    for _, g in pairs.groupby("expiration"):
        vals = pd.to_numeric(g["synthetic_forward"], errors="coerce").dropna()

        if len(vals) < 5:
            continue

        q25 = safe_float(np.nanpercentile(vals, 25))
        q75 = safe_float(np.nanpercentile(vals, 75))

        if q25 is None or q75 is None:
            continue

        rel_iqr = max(q75 - q25, 0.0) / max(spot, _EPS)
        noises.append(float(rel_iqr))
        checks += 1

        if rel_iqr >= 0.025:
            warnings += 1

    if not noises:
        return None, checks, warnings

    return safe_float(np.nanmedian(noises)), checks, warnings


def build_surface_integrity_diagnostics(
    surface: pd.DataFrame,
    spot: float,
    window_pct: float,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Surface Integrity / No-Arbitrage Sanity Check.

    Avec données publiques yfinance, les violations sont surtout des warnings qualité/stale quotes.
    """
    empty_summary = {
        "integrity_state": "N/A",
        "integrity_risk_score": None,
        "surface_rows": 0,
        "used_rows": 0,
        "expirations": 0,
        "warnings": 0,
        "synthetic_forward_noise": None,
    }

    points = prepare_surface_integrity_points(surface, spot, window_pct)

    if points.empty:
        rows = [{
            "Bloc": "Surface integrity",
            "Valeur": "Indisponible",
            "Lecture": "Pas assez de prix options exploitables dans la fenêtre sélectionnée.",
        }]
        return pd.DataFrame(rows), empty_summary

    clean = points[points["used_for_integrity"]].copy()

    scope_rows = int(len(points))
    used_rows = int(len(clean))
    n_exp = int(points["expiration"].nunique()) if "expiration" in points.columns else 0

    bad_quote_count = int(points["bad_quote"].sum()) if "bad_quote" in points.columns else 0
    invalid_mid_count = int((~points["mid_valid"]).sum()) if "mid_valid" in points.columns else 0
    wide_spread_count = int(((points["spread_pct"] > 1.00) & points["spread_pct"].notna()).sum())

    if clean.empty:
        rows = [
            {
                "Bloc": "Surface integrity",
                "Valeur": "Fragile · 80/100",
                "Lecture": "Aucune ligne assez propre après filtres bid/ask, spread et liquidité.",
            },
            {
                "Bloc": "Bid/ask hygiene",
                "Valeur": f"Bad quotes {fmt_int(bad_quote_count)} · spreads larges {fmt_int(wide_spread_count)} · mids invalides {fmt_int(invalid_mid_count)}",
                "Lecture": "La surface doit être lue comme audit, pas comme signal exploitable.",
            },
        ]

        summary = dict(empty_summary)
        summary.update({
            "integrity_state": "Surface fragile",
            "integrity_risk_score": 80.0,
            "surface_rows": scope_rows,
            "used_rows": used_rows,
            "expirations": n_exp,
            "warnings": bad_quote_count + wide_spread_count + invalid_mid_count,
        })

        return pd.DataFrame(rows), summary

    intrinsic_checks = int(len(clean))
    intrinsic_violations = int((clean["mid"] + clean["price_tolerance"] < clean["intrinsic"]).sum())

    noarb = _vertical_and_butterfly_checks(clean)
    synthetic_noise, synthetic_checks, synthetic_warnings = _synthetic_forward_noise(clean, spot)

    vertical_checks = int(noarb.get("vertical_checks", 0))
    vertical_violations = int(noarb.get("vertical_violations", 0))
    butterfly_checks = int(noarb.get("butterfly_checks", 0))
    butterfly_violations = int(noarb.get("butterfly_violations", 0))

    quote_rate = bad_quote_count / max(scope_rows, 1)
    invalid_mid_rate = invalid_mid_count / max(scope_rows, 1)
    wide_spread_rate = wide_spread_count / max(scope_rows, 1)
    intrinsic_rate = intrinsic_violations / max(intrinsic_checks, 1)
    vertical_rate = vertical_violations / max(vertical_checks, 1)
    butterfly_rate = butterfly_violations / max(butterfly_checks, 1)

    noise_penalty = 0.0
    if synthetic_noise is not None:
        noise_penalty = clamp(synthetic_noise * 900.0, 0.0, 35.0)

    coverage_penalty = 15.0 if used_rows < 40 else 8.0 if used_rows < 80 else 0.0
    expiry_penalty = 8.0 if n_exp < 3 else 0.0

    risk_score = clamp(
        8.0
        + quote_rate * 40.0
        + invalid_mid_rate * 25.0
        + wide_spread_rate * 30.0
        + intrinsic_rate * 60.0
        + vertical_rate * 45.0
        + butterfly_rate * 50.0
        + noise_penalty
        + coverage_penalty
        + expiry_penalty
    )

    if risk_score >= 75:
        integrity_state = "Surface bruitée"
    elif risk_score >= 55:
        integrity_state = "Surface fragile"
    elif risk_score >= 35:
        integrity_state = "Surface exploitable"
    else:
        integrity_state = "Surface propre"

    total_warnings = (
        bad_quote_count
        + invalid_mid_count
        + wide_spread_count
        + intrinsic_violations
        + vertical_violations
        + butterfly_violations
        + synthetic_warnings
    )

    rows = [
        {
            "Bloc": "Surface integrity",
            "Valeur": f"{integrity_state} · {fmt_score(risk_score)}",
            "Lecture": "Score de risque qualité basé sur quotes, spreads, intrinsic, monotonie, convexité et forward synthétique.",
        },
        {
            "Bloc": "Coverage utilisée",
            "Valeur": f"{fmt_int(used_rows)} / {fmt_int(scope_rows)} lignes · expirations {fmt_int(n_exp)}",
            "Lecture": "Lignes retenues après filtres liquidité, spread et mid valide.",
        },
        {
            "Bloc": "Bid/ask hygiene",
            "Valeur": f"Bad quotes {fmt_int(bad_quote_count)} · spreads larges {fmt_int(wide_spread_count)} · mids invalides {fmt_int(invalid_mid_count)}",
            "Lecture": "Contrôle des prix publics avant toute lecture de surface.",
        },
        {
            "Bloc": "Intrinsic sanity",
            "Valeur": f"{fmt_int(intrinsic_violations)} / {fmt_int(intrinsic_checks)} violations",
            "Lecture": "Mid inférieur à l'intrinsic avec tolérance. Souvent signe de quote stale ou illiquide.",
        },
        {
            "Bloc": "Vertical monotonicity",
            "Valeur": f"{fmt_int(vertical_violations)} / {fmt_int(vertical_checks)} violations",
            "Lecture": "Calls théoriquement décroissants avec le strike, puts théoriquement croissants.",
        },
        {
            "Bloc": "Butterfly convexity",
            "Valeur": f"{fmt_int(butterfly_violations)} / {fmt_int(butterfly_checks)} violations",
            "Lecture": "Prix optionnels approximativement convexes en strike. Test tolérant sur données publiques.",
        },
        {
            "Bloc": "Synthetic forward consistency",
            "Valeur": f"Noise {fmt_pct(synthetic_noise)} · warnings {fmt_int(synthetic_warnings)} / {fmt_int(synthetic_checks)} expirations",
            "Lecture": "Proxy put-call parity K + Call - Put. Dispersion élevée = surface moins fiable, pas preuve d'arbitrage.",
        },
    ]

    summary = {
        "integrity_state": integrity_state,
        "integrity_risk_score": risk_score,
        "surface_rows": scope_rows,
        "used_rows": used_rows,
        "expirations": n_exp,
        "warnings": total_warnings,
        "synthetic_forward_noise": synthetic_noise,
    }

    return pd.DataFrame(rows), summary


def render_surface_integrity_diagnostics(surface: pd.DataFrame, spot: float, window_pct: float) -> None:
    """
    Affichage Surface Integrity / No-Arbitrage Sanity Check.
    À placer dans Options Surface, juste après la table de chaîne options et avant la 3D map.
    """
    st.markdown("### Surface Integrity / No-Arbitrage Sanity Check")

    integrity_df, summary = build_surface_integrity_diagnostics(surface, spot, window_pct)

    if integrity_df is None or integrity_df.empty:
        st.info("Surface integrity indisponible : données insuffisantes.")
        return

    render_card_grid([
        (
            "Integrity state",
            str(summary.get("integrity_state", "N/A")),
            fmt_score(summary.get("integrity_risk_score")),
        ),
        (
            "Lignes utilisées",
            f"{fmt_int(summary.get('used_rows'))} / {fmt_int(summary.get('surface_rows'))}",
            "Après filtres qualité",
        ),
        (
            "Soft no-arb warnings",
            fmt_int(summary.get("warnings")),
            "Warnings qualité, pas arbitrage certain",
        ),
        (
            "Synthetic forward noise",
            fmt_pct(summary.get("synthetic_forward_noise")),
            "Dispersion K + C - P",
        ),
    ])

    score = safe_float(summary.get("integrity_risk_score"), 50.0) or 50.0

    if score >= 75:
        st.warning(
            "Surface quality fragile : plusieurs incohérences de prix apparaissent dans les données publiques. "
            "La 3D, la heatmap et le forward calendar doivent être lus comme audit visuel, pas comme signal propre."
        )
    elif score >= 55:
        st.info(
            "Surface exploitable mais imparfaite : quelques warnings qualité existent. "
            "Les zones extrêmes doivent être confirmées par liquidité et spreads."
        )
    else:
        st.info(
            "Surface propre : quelques warnings mécaniques mineurs existent, "
            "mais aucun signal majeur de mauvaise qualité n'est détecté sur les prix publics filtrés."
        )

    st.dataframe(integrity_df, width="stretch", hide_index=True)

    st.caption(
        "No-Arbitrage Sanity Check = contrôle mécanique sur données publiques : bid/ask, intrinsic, monotonie, convexité et put-call parity proxy. "
        "Ce bloc sert à qualifier la surface, pas à prouver un arbitrage ni à modifier le score global dérivés."
    )


def iv_surface_quality_params(mode: str) -> Dict[str, float]:
    """
    Paramètres de nettoyage pour la surface IV.
    Prudence : on ne veut pas qu'une IV illiquide ou un spread absurde déforme la 3D map.
    """
    if mode == "Strict":
        return {
            "min_oi": 25,
            "min_volume": 3,
            "max_spread_pct": 0.60,
            "min_iv": 0.03,
            "max_iv": 2.00,
        }

    if mode == "Large":
        return {
            "min_oi": 0,
            "min_volume": 0,
            "max_spread_pct": 2.00,
            "min_iv": 0.02,
            "max_iv": 3.50,
        }

    # Standard = défaut prudent mais pas trop restrictif.
    return {
        "min_oi": 10,
        "min_volume": 1,
        "max_spread_pct": 1.00,
        "min_iv": 0.03,
        "max_iv": 2.50,
    }


def prepare_iv_surface_points(
    surface: pd.DataFrame,
    spot: float,
    option_side: str = "combined",
    window_pct: float = 0.20,
    max_dte: int = 180,
    quality_mode: str = "Standard",
) -> pd.DataFrame:
    """
    Prépare les points IV multi-expirations pour une surface 3D.

    option_side:
    - combined : calls + puts agrégés
    - call     : calls uniquement
    - put      : puts uniquement
    """
    if surface is None or surface.empty or spot is None or spot <= 0:
        return pd.DataFrame()

    params = iv_surface_quality_params(quality_mode)

    df = surface.copy()
    df.columns = [str(c).strip() for c in df.columns]

    required = ["strike", "impliedVolatility", "expiration", "dte", "option_type"]
    if any(c not in df.columns for c in required):
        return pd.DataFrame()

    for col in ["strike", "impliedVolatility", "bid", "ask", "lastPrice", "volume", "openInterest", "dte"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["option_type"] = df["option_type"].astype(str).str.lower().str.strip()

    if option_side in ["call", "put"]:
        df = df[df["option_type"] == option_side].copy()

    if df.empty:
        return pd.DataFrame()

    bid = pd.to_numeric(df["bid"], errors="coerce") if "bid" in df.columns else pd.Series(np.nan, index=df.index)
    ask = pd.to_numeric(df["ask"], errors="coerce") if "ask" in df.columns else pd.Series(np.nan, index=df.index)
    last = pd.to_numeric(df["lastPrice"], errors="coerce") if "lastPrice" in df.columns else pd.Series(np.nan, index=df.index)

    df["mid"] = np.where(
        (bid > 0) & (ask > 0),
        (bid + ask) / 2.0,
        last,
    )

    df["spread"] = ask - bid
    df["spread_pct"] = df["spread"] / df["mid"].replace(0, np.nan)

    df["iv"] = pd.to_numeric(df["impliedVolatility"], errors="coerce")
    df["iv"] = df["iv"].where(
        (df["iv"] >= params["min_iv"]) &
        (df["iv"] <= params["max_iv"]),
        np.nan,
    )

    df["volume"] = pd.to_numeric(df.get("volume", 0), errors="coerce").fillna(0)
    df["openInterest"] = pd.to_numeric(df.get("openInterest", 0), errors="coerce").fillna(0)
    df["dte"] = pd.to_numeric(df["dte"], errors="coerce")
    df["strike"] = pd.to_numeric(df["strike"], errors="coerce")

    df["moneyness"] = df["strike"] / max(spot, _EPS)
    df["distance_spot"] = df["moneyness"] - 1.0

    df = df.dropna(subset=["strike", "iv", "moneyness", "dte", "expiration"]).copy()

    if df.empty:
        return pd.DataFrame()

    df = df[
        (df["moneyness"] >= 1.0 - window_pct)
        & (df["moneyness"] <= 1.0 + window_pct)
        & (df["dte"] >= 0)
        & (df["dte"] <= max_dte)
    ].copy()

    if df.empty:
        return pd.DataFrame()

    liquidity_mask = (
        (df["openInterest"] >= params["min_oi"])
        | (df["volume"] >= params["min_volume"])
    )

    spread_mask = (
        df["spread_pct"].isna()
        | ((df["spread_pct"] >= 0) & (df["spread_pct"] <= params["max_spread_pct"]))
    )

    df = df[liquidity_mask & spread_mask].copy()

    if df.empty:
        return pd.DataFrame()

    return df.sort_values(["dte", "moneyness"]).reset_index(drop=True)


def build_iv_surface_grid(
    points: pd.DataFrame,
    window_pct: float,
    grid_size: int = 55,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, List[str]]:
    """
    Convertit les points IV filtrés en grille interpolée pour go.Surface.
    Interpolation simple, volontairement prudente : pas de lissage agressif.
    """
    if points is None or points.empty:
        return np.array([]), np.array([]), np.array([[]]), []

    df = points.copy()
    df["dte"] = pd.to_numeric(df["dte"], errors="coerce")
    df["moneyness"] = pd.to_numeric(df["moneyness"], errors="coerce")
    df["iv"] = pd.to_numeric(df["iv"], errors="coerce")
    df = df.dropna(subset=["dte", "moneyness", "iv", "expiration"])

    if df.empty:
        return np.array([]), np.array([]), np.array([[]]), []

    x_grid = np.linspace(1.0 - window_pct, 1.0 + window_pct, grid_size)

    rows = []
    y_values = []
    exp_labels = []

    grouped = df.groupby(["expiration", "dte"], sort=True)

    for (exp, dte), g in grouped:
        g = g.copy()
        if len(g) < 4:
            continue

        # Agrégation des doublons par moneyness approximative.
        g["m_bin"] = g["moneyness"].round(4)
        g["weight"] = g["openInterest"].fillna(0) + g["volume"].fillna(0) + 1.0

        agg_rows = []
        for m_bin, h in g.groupby("m_bin"):
            weights = pd.to_numeric(h["weight"], errors="coerce").fillna(1.0)
            iv_values = pd.to_numeric(h["iv"], errors="coerce")
            mask = iv_values.notna() & weights.notna() & (weights > 0)
            if mask.any():
                iv_avg = float(np.average(iv_values[mask], weights=weights[mask]))
            else:
                iv_avg = safe_float(iv_values.mean())
            if iv_avg is not None:
                agg_rows.append({"moneyness": float(m_bin), "iv": iv_avg})

        agg = pd.DataFrame(agg_rows).dropna()
        if len(agg) < 4:
            continue

        agg = agg.sort_values("moneyness")
        x_obs = agg["moneyness"].to_numpy(dtype=float)
        z_obs = agg["iv"].to_numpy(dtype=float)

        z_row = np.full_like(x_grid, np.nan, dtype=float)
        inside = (x_grid >= np.nanmin(x_obs)) & (x_grid <= np.nanmax(x_obs))

        if inside.any():
            z_row[inside] = np.interp(x_grid[inside], x_obs, z_obs)

        if np.isfinite(z_row).sum() < 4:
            continue

        rows.append(z_row)
        y_values.append(float(dte))
        exp_labels.append(str(exp))

    if not rows:
        return np.array([]), np.array([]), np.array([[]]), []

    return x_grid, np.array(y_values, dtype=float), np.vstack(rows), exp_labels


def iv_surface_quality_score(points: pd.DataFrame) -> Tuple[float, str]:
    """
    Score indicatif de qualité de surface, uniquement pour guider la lecture.
    """
    if points is None or points.empty:
        return 0.0, "Faible"

    n_points = len(points)
    n_exp = points["expiration"].nunique() if "expiration" in points.columns else 0

    median_spread = None
    if "spread_pct" in points.columns:
        spreads = pd.to_numeric(points["spread_pct"], errors="coerce").dropna()
        if not spreads.empty:
            median_spread = safe_float(spreads.median())

    point_score = clamp(n_points / 180.0 * 100.0)
    exp_score = clamp(n_exp / 6.0 * 100.0)

    if median_spread is None:
        spread_score = 55.0
    else:
        spread_score = clamp(100.0 - median_spread * 140.0)

    score = clamp(0.45 * point_score + 0.35 * exp_score + 0.20 * spread_score)

    # Prudence : avec données publiques yfinance, on évite un score quasi institutionnel.
    score = min(score, 88.0)

    if score >= 80:
        label = "Bonne"
    elif score >= 60:
        label = "Correcte"
    elif score >= 40:
        label = "Limitée"
    else:
        label = "Faible"

    return score, label


def build_iv_heatmap_matrix(
    points: pd.DataFrame,
    moneyness_step: float = 0.01,
) -> Tuple[List[float], List[float], np.ndarray, pd.DataFrame]:
    """
    Construit une matrice 2D pour Heatmap IV.

    Entrée :
    - points déjà filtrés par prepare_iv_surface_points
    - pas de nouvel appel data
    - pas de nouveau filtre directionnel

    Sortie :
    - x_vals = buckets de moneyness K/S
    - y_vals = DTE
    - z_vals = IV médiane
    - pivot = DataFrame DTE x Moneyness
    """
    if points is None or points.empty:
        return [], [], np.array([[]]), pd.DataFrame(), None

    df = points.copy()

    required = ["dte", "moneyness", "iv"]
    if any(col not in df.columns for col in required):
        return [], [], np.array([[]]), pd.DataFrame(), None

    for col in required:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=required).copy()

    if df.empty:
        return [], [], np.array([[]]), pd.DataFrame(), None

    df = df[
        (df["dte"] >= 0)
        & (df["moneyness"] > 0)
        & (df["iv"] > 0)
        & (df["iv"] < 5)
    ].copy()

    if df.empty:
        return [], [], np.array([[]]), pd.DataFrame(), None

    # Bucketisation prudente : évite une heatmap trop fragmentée.
    df["m_bucket"] = (df["moneyness"] / moneyness_step).round() * moneyness_step
    df["m_bucket"] = df["m_bucket"].round(4)

    # Agrégation médiane : plus robuste qu'une moyenne sur données publiques.
    agg = (
        df.groupby(["dte", "m_bucket"], as_index=False)
        .agg(
            iv=("iv", "median"),
            points=("iv", "count"),
        )
    )

    if agg.empty:
        return [], [], np.array([[]]), pd.DataFrame(), None

    pivot = (
        agg.pivot_table(
            index="dte",
            columns="m_bucket",
            values="iv",
            aggfunc="median",
        )
        .sort_index()
        .sort_index(axis=1)
    )
    coverage = float(np.isfinite(pivot.to_numpy(dtype=float)).sum()) / max(
        pivot.shape[0] * pivot.shape[1],
        1
    )

    if pivot.empty:
        return [], [], np.array([[]]), pd.DataFrame(), None

    x_vals = [float(x) for x in pivot.columns.to_list()]
    y_vals = [float(y) for y in pivot.index.to_list()]
    z_vals = pivot.to_numpy(dtype=float)

    return x_vals, y_vals, z_vals, pivot, coverage


def render_iv_heatmap(
    points: pd.DataFrame,
    side_label: str,
    window_pct: float,
    height: int = 560,
) -> None:
    """
    Heatmap 2D IV : Moneyness x DTE.

    Prudence :
    - réutilise les points déjà filtrés de la 3D ;
    - pas d'interpolation agressive ;
    - la couleur est bornée par percentiles pour éviter qu'une IV aberrante écrase la lecture ;
    - les valeurs affichées au hover restent les valeurs brutes de la matrice.
    """
    x_vals, y_vals, z_vals, pivot, coverage = build_iv_heatmap_matrix(
        points=points,
        moneyness_step=0.01,
    )

    if pivot.empty or z_vals.size == 0:
        st.info("Heatmap IV indisponible : données insuffisantes après filtrage.")
        return

    finite_z = z_vals[np.isfinite(z_vals)]

    zmin = None
    zmax = None

    if finite_z.size >= 20:
        zmin_candidate = safe_float(np.nanpercentile(finite_z, 2))
        zmax_candidate = safe_float(np.nanpercentile(finite_z, 98))

        if zmin_candidate is not None and zmax_candidate is not None:
            zmax_candidate = min(zmax_candidate, 1.50)

            if zmax_candidate > zmin_candidate:
                zmin = zmin_candidate
                zmax = zmax_candidate

    heatmap_kwargs = dict(
        z=z_vals,
        x=x_vals,
        y=y_vals,
        colorscale="Plasma",
        colorbar=dict(
            title="IV",
            tickformat=".0%",
        ),
        hovertemplate=(
            "Moneyness K/S %{x:.1%}<br>"
            "DTE %{y:.0f}<br>"
            "IV %{z:.2%}"
            "<extra></extra>"
        ),
        zsmooth=False,
        name="IV Heatmap",
    )

    if zmin is not None and zmax is not None:
        heatmap_kwargs["zmin"] = zmin
        heatmap_kwargs["zmax"] = zmax

    fig = go.Figure()
    fig.add_trace(go.Heatmap(**heatmap_kwargs))

    # Ligne ATM : K/S = 100%.
    fig.add_vline(
        x=1.0,
        line_width=2,
        line_dash="dot",
        line_color="white",
        annotation_text="ATM",
        annotation_position="top",
    )

    fig.update_layout(
        title=f"IV Heatmap — {side_label} · fenêtre ±{int(window_pct * 100)}%",
        xaxis_title="Moneyness K/S",
        yaxis_title="Jours à expiration",
        hovermode="closest",
    )

    fig.update_xaxes(tickformat=".0%")
    fig.update_yaxes(title="Jours à expiration")

    st.plotly_chart(
        apply_dark_layout(fig, height),
        width="stretch",
    )

    coverage_txt = fmt_pct(coverage) if coverage is not None else "N/A"

    st.caption(
        f"Heatmap prudente : mêmes points filtrés que la surface 3D. "
        f"Couverture effective de la grille : {coverage_txt}. "
        f"Échelle couleur bornée : {fmt_pct(zmin)} → {fmt_pct(zmax)}. "
        f"Les valeurs hautes du tableau peuvent dépasser cette borne car elles sont conservées pour audit."
    )


def build_iv_heatmap_summary(points: pd.DataFrame) -> pd.DataFrame:
    """
    Résumé analytique de la heatmap.
    Ne change aucun score global : uniquement lecture descriptive.
    """
    if points is None or points.empty:
        return pd.DataFrame()

    df = points.copy()

    for col in ["iv", "moneyness", "dte"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["iv", "moneyness", "dte"]).copy()

    if df.empty:
        return pd.DataFrame()

    def median_iv(mask) -> Optional[float]:
        vals = pd.to_numeric(df.loc[mask, "iv"], errors="coerce").dropna()
        if vals.empty:
            return None
        return safe_float(vals.median())

    atm_iv = median_iv((df["moneyness"] >= 0.98) & (df["moneyness"] <= 1.02))
    put_wing_iv = median_iv(df["moneyness"] <= 0.95)
    call_wing_iv = median_iv(df["moneyness"] >= 1.05)

    skew_5 = None
    if put_wing_iv is not None and call_wing_iv is not None:
        skew_5 = put_wing_iv - call_wing_iv

    short_iv = median_iv(df["dte"] <= 7)
    long_iv = median_iv(df["dte"] >= 14)

    term_spread = None
    if short_iv is not None and long_iv is not None:
        term_spread = short_iv - long_iv

    high_zone = "N/A"
    raw_max_zone = "N/A"

    valid_iv = pd.to_numeric(df["iv"], errors="coerce").dropna()

    if not valid_iv.empty:
        # Niveau haut robuste : évite qu'un seul print extrême domine la lecture.
        robust_threshold = safe_float(np.nanpercentile(valid_iv, 95))

        if robust_threshold is not None:
            high_df = df[df["iv"] >= robust_threshold].copy()

            if not high_df.empty:
                high_zone = (
                    f"{fmt_pct(high_df['iv'].median())} médian · "
                    f"K/S {fmt_pct(high_df['moneyness'].median())} · "
                    f"DTE {fmt_int(high_df['dte'].median())}"
                )

        # Max brut gardé uniquement comme information d'audit.
        raw_max_row = df.loc[df["iv"].idxmax()]

        if not raw_max_row.empty:
            raw_max_zone = (
                f"{fmt_pct(raw_max_row.get('iv'))} · "
                f"K/S {fmt_pct(raw_max_row.get('moneyness'))} · "
                f"DTE {fmt_int(raw_max_row.get('dte'))}"
            )

    rows = [
        {
            "Bloc": "ATM IV médiane",
            "Valeur": fmt_pct(atm_iv),
            "Lecture": "Niveau médian d'IV autour de K/S 100%.",
        },
        {
            "Bloc": "Put wing IV",
            "Valeur": fmt_pct(put_wing_iv),
            "Lecture": "IV médiane sur zone put wing, K/S ≤ 95%.",
        },
        {
            "Bloc": "Call wing IV",
            "Valeur": fmt_pct(call_wing_iv),
            "Lecture": "IV médiane sur zone call wing, K/S ≥ 105%.",
        },
        {
            "Bloc": "Skew 5%",
            "Valeur": fmt_pct(skew_5),
            "Lecture": "Put wing IV - Call wing IV. Positif = puts plus chers.",
        },
        {
            "Bloc": "Short vs longer DTE",
            "Valeur": fmt_pct(term_spread),
            "Lecture": "IV court terme ≤ 7D moins IV ≥ 14D. Positif = front-end plus tendu.",
        },
        {
            "Bloc": "Zone IV haute robuste",
            "Valeur": high_zone,
            "Lecture": "Zone haute basée sur le top 5% des IV filtrées, plus robuste que le max brut.",
        },
        {
            "Bloc": "IV max brute filtrée",
            "Valeur": raw_max_zone,
            "Lecture": "Point maximal conservé après filtre. À lire comme audit, pas comme niveau représentatif.",
        },
    ]

    return pd.DataFrame(rows)


def build_vol_surface_regime(points: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Diagnostic prudent du régime de surface de volatilité.

    Objectif :
    - lire la forme de la surface IV sans ajouter de nouvelle donnée ;
    - détecter front-end stress, contango/backwardation, skew, convexité et dispersion ;
    - rester descriptif : ne modifie pas le score global options/futures.

    Entrée :
    - points filtrés issus de prepare_iv_surface_points()

    Sortie :
    - regime_df : table de lecture
    - summary   : métriques clés pour cards/UI
    """
    if points is None or points.empty:
        return pd.DataFrame(), {
            "surface_regime": "N/A",
            "surface_regime_score": None,
            "term_state": "N/A",
            "skew_state": "N/A",
            "curvature_state": "N/A",
        }

    df = points.copy()

    required = ["iv", "moneyness", "dte"]
    if any(c not in df.columns for c in required):
        return pd.DataFrame(), {
            "surface_regime": "N/A",
            "surface_regime_score": None,
            "term_state": "N/A",
            "skew_state": "N/A",
            "curvature_state": "N/A",
        }

    for col in required + ["spread_pct"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["iv", "moneyness", "dte"]).copy()

    df = df[
        (df["iv"] > 0)
        & (df["iv"] < 5)
        & (df["moneyness"] > 0)
        & (df["dte"] >= 0)
    ].copy()

    if df.empty:
        return pd.DataFrame(), {
            "surface_regime": "N/A",
            "surface_regime_score": None,
            "term_state": "N/A",
            "skew_state": "N/A",
            "curvature_state": "N/A",
        }

    def zone_median_iv(
        m_low: Optional[float] = None,
        m_high: Optional[float] = None,
        dte_low: Optional[float] = None,
        dte_high: Optional[float] = None,
    ) -> Optional[float]:
        mask = pd.Series(True, index=df.index)

        if m_low is not None:
            mask &= df["moneyness"] >= float(m_low)
        if m_high is not None:
            mask &= df["moneyness"] <= float(m_high)
        if dte_low is not None:
            mask &= df["dte"] >= float(dte_low)
        if dte_high is not None:
            mask &= df["dte"] <= float(dte_high)

        vals = pd.to_numeric(df.loc[mask, "iv"], errors="coerce").dropna()
        if vals.empty:
            return None

        return safe_float(vals.median())

    atm_iv = zone_median_iv(0.98, 1.02)
    atm_short = zone_median_iv(0.98, 1.02, None, 7)
    atm_long = zone_median_iv(0.98, 1.02, 14, None)

    put_wing_95 = zone_median_iv(None, 0.95)
    call_wing_105 = zone_median_iv(1.05, None)

    put_deep_90 = zone_median_iv(None, 0.90)
    call_deep_110 = zone_median_iv(1.10, None)

    front_spread = None
    if atm_short is not None and atm_long is not None:
        front_spread = atm_short - atm_long

    skew_5 = None
    if put_wing_95 is not None and call_wing_105 is not None:
        skew_5 = put_wing_95 - call_wing_105

    downside_convexity = None
    if put_deep_90 is not None and atm_iv is not None:
        downside_convexity = put_deep_90 - atm_iv

    upside_convexity = None
    if call_deep_110 is not None and atm_iv is not None:
        upside_convexity = call_deep_110 - atm_iv

    smile_curvature = None
    if put_wing_95 is not None and call_wing_105 is not None and atm_iv is not None:
        smile_curvature = ((put_wing_95 + call_wing_105) / 2.0) - atm_iv

    valid_iv = pd.to_numeric(df["iv"], errors="coerce").dropna()
    iv_p10 = safe_float(np.nanpercentile(valid_iv, 10)) if len(valid_iv) >= 10 else None
    iv_p90 = safe_float(np.nanpercentile(valid_iv, 90)) if len(valid_iv) >= 10 else None

    iv_dispersion = None
    if iv_p10 is not None and iv_p90 is not None:
        iv_dispersion = iv_p90 - iv_p10

    median_spread = None
    if "spread_pct" in df.columns:
        spreads = pd.to_numeric(df["spread_pct"], errors="coerce").dropna()
        if not spreads.empty:
            median_spread = safe_float(spreads.median())

    # -----------------------------
    # Régimes lisibles
    # -----------------------------
    if front_spread is None:
        term_state = "Indisponible"
        term_lecture = "Pas assez de points ATM sur les maturités courtes et longues."
    elif front_spread >= 0.08:
        term_state = "Front-end stress"
        term_lecture = "IV très courte nettement supérieure aux maturités plus longues."
    elif front_spread >= 0.03:
        term_state = "Backwardation légère"
        term_lecture = "Front-end plus cher que le reste de la surface."
    elif front_spread <= -0.04:
        term_state = "Contango IV"
        term_lecture = "Maturités longues plus chères que le court terme."
    else:
        term_state = "Structure plate"
        term_lecture = "Pas de tension majeure sur la pente temporelle."

    if skew_5 is None:
        skew_state = "Indisponible"
        skew_lecture = "Pas assez de points comparables entre put wing et call wing."
    elif skew_5 >= 0.07:
        skew_state = "Skew put défensif"
        skew_lecture = "Les puts OTM sont nettement plus chers que les calls OTM comparables."
    elif skew_5 >= 0.025:
        skew_state = "Skew put modéré"
        skew_lecture = "Prime de protection présente mais non extrême."
    elif skew_5 <= -0.03:
        skew_state = "Call wing plus chère"
        skew_lecture = "La convexité upside est plus chère que la protection downside."
    else:
        skew_state = "Skew équilibré"
        skew_lecture = "Pas d'asymétrie majeure entre aile put et aile call."

    if smile_curvature is None:
        curvature_state = "Indisponible"
        curvature_lecture = "Pas assez de points pour mesurer la courbure du smile."
    elif smile_curvature >= 0.07:
        curvature_state = "Convexité élevée"
        curvature_lecture = "Les ailes sont nettement plus chères que l'ATM."
    elif smile_curvature >= 0.025:
        curvature_state = "Smile incurvé"
        curvature_lecture = "Convexité visible mais non extrême."
    elif smile_curvature <= -0.01:
        curvature_state = "Smile plat/inversé"
        curvature_lecture = "Les ailes ne portent pas de prime claire vs ATM."
    else:
        curvature_state = "Convexité contenue"
        curvature_lecture = "Courbure du smile modérée."

    # -----------------------------
    # Score de tension de surface
    # Score descriptif, pas un signal directionnel.
    # -----------------------------
    front_score = 50.0
    if front_spread is not None:
        front_score = clamp(45.0 + front_spread * 650.0)

    skew_score = 45.0
    if skew_5 is not None:
        # Skew put positif = plus défensif ; skew call négatif = information aussi, mais moins pénalisante.
        skew_score = clamp(45.0 + max(skew_5, 0.0) * 520.0 + max(-skew_5, 0.0) * 250.0)

    curvature_score = 40.0
    if smile_curvature is not None:
        curvature_score = clamp(40.0 + smile_curvature * 650.0)

    dispersion_score = 35.0
    if iv_dispersion is not None:
        dispersion_score = clamp(iv_dispersion * 260.0)

    raw_surface_score = clamp(
        0.30 * front_score
        + 0.25 * skew_score
        + 0.25 * curvature_score
        + 0.20 * dispersion_score
    )

    # Prudence : si peu de points, on évite de classifier trop agressivement.
    quality_score, quality_label = iv_surface_quality_score(df)

    if quality_score < 45:
        surface_score = min(raw_surface_score, 55.0)
    elif quality_score < 60:
        surface_score = min(raw_surface_score, 70.0)
    else:
        surface_score = raw_surface_score

    surface_score = clamp(surface_score)

    # Ajustement prudent : une surface en contango IV réduit le risque de stress immédiat.
    # Objectif : éviter qu'une convexité élevée seule classe la surface comme trop tendue.
    contango_adjustment = 0.0

    front_spread_num = safe_float(front_spread, None)

    if front_spread_num is not None and front_spread_num < -0.04:
        contango_adjustment = -5.0
        surface_score = max(0.0, surface_score + contango_adjustment)

    if surface_score >= 75:
        surface_regime = "Surface très tendue"
    elif surface_score >= 65:
        surface_regime = "Surface tendue"
    elif surface_score >= 50:
        surface_regime = "Normale surveillée"
    elif surface_score >= 35:
        surface_regime = "Surface normale"
    else:
        surface_regime = "Surface calme"

    rows = [
        {
            "Bloc": "Surface regime",
            "Valeur": f"{surface_regime} · {fmt_score(surface_score)}",
            "Lecture": "Score descriptif basé sur pente temporelle, skew, courbure et dispersion IV.",
        },
        {
            "Bloc": "Term structure",
            "Valeur": f"{term_state} · spread {fmt_pct(front_spread)}",
            "Lecture": term_lecture,
        },
        {
            "Bloc": "Put/Call skew",
            "Valeur": f"{skew_state} · skew {fmt_pct(skew_5)}",
            "Lecture": skew_lecture,
        },
        {
            "Bloc": "Smile curvature",
            "Valeur": f"{curvature_state} · curvature {fmt_pct(smile_curvature)}",
            "Lecture": curvature_lecture,
        },
        {
            "Bloc": "Downside convexity",
            "Valeur": fmt_pct(downside_convexity),
            "Lecture": "Put deep wing IV moins ATM IV. Positif = protection downside plus chère.",
        },
        {
            "Bloc": "Upside convexity",
            "Valeur": fmt_pct(upside_convexity),
            "Lecture": "Call deep wing IV moins ATM IV. Positif = convexité upside plus chère.",
        },
        {
            "Bloc": "IV dispersion",
            "Valeur": fmt_pct(iv_dispersion),
            "Lecture": "Écart robuste P90 - P10 des IV filtrées.",
        },
        {
            "Bloc": "Data quality",
            "Valeur": f"{quality_label} · {fmt_score(quality_score)}",
            "Lecture": f"Points {fmt_int(len(df))}, expirations {fmt_int(df['dte'].nunique())}, spread médian {fmt_pct(median_spread)}.",
        },
    ]

    summary = {
        "surface_regime": surface_regime,
        "surface_regime_score": surface_score,
        "term_state": term_state,
        "front_spread": front_spread,
        "skew_state": skew_state,
        "skew_5": skew_5,
        "curvature_state": curvature_state,
        "smile_curvature": smile_curvature,
        "iv_dispersion": iv_dispersion,
        "quality_score": quality_score,
        "quality_label": quality_label,
    }

    return pd.DataFrame(rows), summary


def render_iv_surface_3d(surface: pd.DataFrame, spot: float, window_pct: float) -> None:
    """
    Affiche une vraie 3D IV Surface :
    X = moneyness K/S
    Y = DTE
    Z = implied volatility
    """
    st.subheader("3D IV Surface")

    if surface is None or surface.empty:
        st.info("Surface IV 3D indisponible : aucune donnée multi-expiration chargée.")
        return

    c1, c2, c3 = st.columns([1.0, 1.0, 1.0])

    with c1:
        side_label = st.selectbox(
            "Type de surface",
            ["Call + Put moyen", "Calls seulement", "Puts seulement"],
            index=0,
            key="iv_surface_side",
        )

    with c2:
        max_dte = st.selectbox(
            "DTE max",
            [30, 60, 90, 180],
            index=2,
            key="iv_surface_max_dte",
        )

    with c3:
        quality_mode = st.selectbox(
            "Filtre qualité",
            ["Strict", "Standard", "Large"],
            index=1,
            key="iv_surface_quality",
            help="Strict = moins de bruit mais moins de points. Large = plus de points mais plus de risque d'IV aberrante.",
        )

    side_map = {
        "Call + Put moyen": "combined",
        "Calls seulement": "call",
        "Puts seulement": "put",
    }

    option_side = side_map.get(side_label, "combined")

    points = prepare_iv_surface_points(
        surface=surface,
        spot=spot,
        option_side=option_side,
        window_pct=window_pct,
        max_dte=int(max_dte),
        quality_mode=quality_mode,
    )

    if points.empty:
        st.warning(
            "Surface IV 3D non affichée : trop peu de points après filtrage. "
            "Essaie le filtre 'Large' ou une fenêtre de strikes plus large."
        )
        return

    x_grid, y_grid, z_grid, exp_labels = build_iv_surface_grid(points, window_pct=window_pct, grid_size=55)

    z_display = z_grid.copy()
    finite_z = z_display[np.isfinite(z_display)]

    if finite_z.size >= 20:
        z_low = np.nanpercentile(finite_z, 2)
        z_high = np.nanpercentile(finite_z, 98)

        # Cap visuel prudent : évite qu'une IV aberrante écrase toute la surface.
        z_high = min(z_high, 1.50)

        z_display = np.clip(z_display, z_low, z_high)
    else:
        z_display = z_grid

    if x_grid.size == 0 or y_grid.size == 0 or z_grid.size == 0:
        st.warning("Surface IV 3D non affichée : interpolation insuffisante après filtrage.")
        return

    quality_score, quality_label = iv_surface_quality_score(points)

    fig = go.Figure()

    fig.add_trace(
        go.Surface(
            x=x_grid,
            y=y_grid,
            z=z_display,
            name="IV surface",
            colorbar=dict(title="IV"),
            hovertemplate=(
                "Moneyness K/S %{x:.2%}<br>"
                "DTE %{y:.0f}<br>"
                "IV %{z:.2%}"
                "<extra></extra>"
            ),
        )
    )

    # ATM ridge = coupe de la surface autour de K/S = 100%.
    atm_idx = int(np.nanargmin(np.abs(x_grid - 1.0)))
    atm_z = z_display[:, atm_idx]
    valid_atm = np.isfinite(atm_z)

    if valid_atm.any():
        fig.add_trace(
            go.Scatter3d(
                x=np.full(valid_atm.sum(), 1.0),
                y=y_grid[valid_atm],
                z=atm_z[valid_atm],
                mode="lines+markers",
                name="ATM ridge",
                hovertemplate=(
                    "ATM ridge<br>"
                    "DTE %{y:.0f}<br>"
                    "ATM IV %{z:.2%}"
                    "<extra></extra>"
                ),
            )
        )

    fig.update_layout(
        title=f"3D IV Surface — {side_label} · fenêtre ±{int(window_pct * 100)}%",
        scene=dict(
            xaxis=dict(title="Moneyness K/S", tickformat=".0%"),
            yaxis=dict(title="Jours à expiration"),
            zaxis=dict(title="Implied volatility", tickformat=".0%"),
        ),
        scene_camera=dict(eye=dict(x=1.55, y=-1.75, z=0.85)),
    )

    st.plotly_chart(apply_dark_layout(fig, 720), width="stretch")

    # ------------------------------------------------------------
    # 2D IV Heatmap — lecture institutionnelle complémentaire
    # ------------------------------------------------------------
    st.markdown("### IV Heatmap — lecture 2D")

    render_iv_heatmap(
        points=points,
        side_label=side_label,
        window_pct=window_pct,
        height=560,
    )

    heatmap_summary = build_iv_heatmap_summary(points)

    if not heatmap_summary.empty:
        st.dataframe(
            heatmap_summary,
            width="stretch",
            hide_index=True,
        )

    # ------------------------------------------------------------
    # Vol Surface Regime Diagnostics
    # ------------------------------------------------------------
    regime_df, regime_summary = build_vol_surface_regime(points)

    if regime_df is not None and not regime_df.empty:
        st.markdown("### Vol Surface Regime Diagnostics")

        render_card_grid([
            (
                "Surface regime",
                str(regime_summary.get("surface_regime", "N/A")),
                fmt_score(regime_summary.get("surface_regime_score")),
            ),
            (
                "Term structure",
                str(regime_summary.get("term_state", "N/A")),
                "Front spread " + fmt_pct(regime_summary.get("front_spread")),
            ),
            (
                "Skew",
                str(regime_summary.get("skew_state", "N/A")),
                "Skew 5% " + fmt_pct(regime_summary.get("skew_5")),
            ),
            (
                "Curvature",
                str(regime_summary.get("curvature_state", "N/A")),
                "Smile curvature " + fmt_pct(regime_summary.get("smile_curvature")),
            ),
        ])

        surface_score = safe_float(regime_summary.get("surface_regime_score"), 50.0) or 50.0

        if surface_score >= 75:
            st.warning(
                "Surface IV tendue : front-end, skew ou convexité indiquent une prime de risque élevée. "
                "Lecture à confirmer avec liquidité et contexte événementiel."
            )
        elif surface_score >= 60:
            st.info(
                "Surface IV modérément tendue : la volatilité n'est pas bloquante, mais la forme de surface mérite surveillance."
            )
        else:
            st.info(
                "Surface IV sans tension majeure détectée sur les points filtrés."
            )

        st.dataframe(
            regime_df,
            width="stretch",
            hide_index=True,
        )

        st.caption(
            "Vol Surface Regime = diagnostic descriptif de la forme de surface IV. "
            "Il ne remplace pas une surface OPRA/SVI institutionnelle et ne modifie pas encore le score global dérivés."
        )

    diag = pd.DataFrame([
        {
            "Bloc": "Surface usability",
            "Valeur": f"{quality_label} · {fmt_score(quality_score)}",
            "Lecture": "Score indicatif basé sur nombre de points, nombre d'expirations et spread médian.",
        },
        {
            "Bloc": "Points retenus",
            "Valeur": fmt_int(len(points)),
            "Lecture": "Nombre de lignes options conservées après filtre liquidité / spread / IV.",
        },
        {
            "Bloc": "Expirations retenues",
            "Valeur": fmt_int(points["expiration"].nunique()),
            "Lecture": "Plus il y a d'expirations propres, plus la surface est lisible.",
        },
        {
            "Bloc": "DTE range",
            "Valeur": f"{fmt_num(points['dte'].min(), 0)} → {fmt_num(points['dte'].max(), 0)} jours",
            "Lecture": "Plage temporelle couverte par la surface.",
        },
        {
            "Bloc": "IV médiane",
            "Valeur": fmt_pct(points["iv"].median()),
            "Lecture": "Niveau médian d'IV sur les points filtrés.",
        },
    ])

    st.dataframe(diag, width="stretch", hide_index=True)

    st.caption(
        "Lecture prudente : la surface 3D est interpolée à partir d'IV publiques yfinance. L'affichage est winsorisé pour éviter qu'une IV aberrante déforme la lecture. "
        "Les strikes illiquides, spreads excessifs et IV aberrantes sont filtrés, mais ce n'est pas une surface institutionnelle OPRA."
    )


def render_macro_chart(macro_df: pd.DataFrame) -> None:
    if macro_df is None or macro_df.empty:
        st.info("Futures / macro tape indisponible.")
        return
    df = macro_df.copy()
    df = df.dropna(subset=["5D"])
    if df.empty:
        st.info("Rendements 5D indisponibles pour les proxies.")
        return
    fig = go.Figure()
    fig.add_trace(go.Bar(x=df["Ticker"], y=df["5D"], name="5D return"))
    fig.add_hline(y=0, line_dash="dash", line_color="white")
    fig.update_layout(title="Futures / Macro proxies — performance 5D")
    fig.update_xaxes(title="Proxy")
    fig.update_yaxes(title="Return", tickformat=".1%")
    st.plotly_chart(apply_dark_layout(fig, 480), width="stretch")


def render_stress_chart(stress_df: pd.DataFrame) -> None:
    if stress_df is None or stress_df.empty:
        st.info("Stress futures indisponible.")
        return
    fig = go.Figure()
    fig.add_trace(go.Bar(x=stress_df["Scénario"], y=stress_df["Impact ticker estimé"], name="Impact estimé"))
    fig.add_hline(y=0, line_dash="dash", line_color="white")
    fig.update_layout(title="Stress mécanique estimé via beta")
    fig.update_xaxes(title="Scénario")
    fig.update_yaxes(title="Impact ticker estimé", tickformat=".1%")
    st.plotly_chart(apply_dark_layout(fig, 480), width="stretch")


# ============================================================
# Display formatting
# ============================================================


def format_display_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    out = df.copy()


    price_cols = {
        "spot", "strike", "last", "bid", "ask", "mid",
        "call_last", "put_last",
        "call_bid", "call_ask", "call_mid",
        "put_bid", "put_ask", "put_mid",
        "call_wall", "put_wall", "max_pain", "gamma_flip",
        "expected_move_price",
    }

    numeric_2_cols = {
        "corr", "beta ticker", "beta", "delta", "gamma", "vega", "theta",
        "r²", "r2", "call_delta", "put_delta", "call_gamma", "put_gamma",
        "pcr_vol", "pcr_oi",
    }

    integer_cols = {
        "volume", "openinterest", "open interest", "oi", "obs", "dte",
        "call_vol", "put_vol", "total_volume",
        "call_oi", "put_oi", "total_oi",
        "lower tail obs", "upper tail obs",
        "lower co-tail obs", "upper co-tail obs",
    }

    for c in out.columns:
        lc = c.lower().strip()

        if "concentration" in lc:
            out[c] = out[c].map(lambda x: fmt_pct(x) if safe_float(x) is not None else "N/A")
            continue

        if (
            lc in price_cols
            or lc.endswith("_price")
            or lc.endswith("_wall")
            or lc.endswith("_pain")
        ):
            out[c] = out[c].map(lambda x: fmt_price(x) if safe_float(x) is not None else "N/A")

        elif (
            lc in integer_cols
            or lc.endswith("_oi")
            or lc.endswith("_vol")
            or lc.endswith("_volume")
            or lc == "openinterest"
        ):
            out[c] = out[c].map(lambda x: fmt_int(x) if safe_float(x) is not None else "N/A")

        elif (
            "gex" in lc
            or "notional" in lc
            or "payout" in lc
            or "dollar" in lc
        ):
            out[c] = out[c].map(lambda x: fmt_large(x) if safe_float(x) is not None else "N/A")

        elif (
            "iv" in lc
            or "pct" in lc
            or "return" in lc
            or "distance" in lc
            or "dist" in lc
            or "concentration" in lc
            or "ratio" in lc
            or lc in [
                "1d", "5d", "20d",
                "median 1d", "median 5d", "median 20d",
                "vol 10d", "vol 20d", "vol 60d",
                "median vol 10d", "median vol 20d", "median vol 60d",
                "vol10/vol60", "median vol ratio",
            ]
            or "premium" in lc
            or "choc" in lc
            or "impact" in lc
            or "expected_move" in lc
            or "move" in lc
        ):
            out[c] = out[c].map(lambda x: fmt_pct(x) if safe_float(x) is not None else "N/A")

        elif lc in numeric_2_cols or "beta" in lc or lc == "corr":
            out[c] = out[c].map(lambda x: "N/A" if safe_float(x) is None else f"{float(x):.2f}")

    return out


def render_card_grid(cards: List[Tuple[str, str, str]]) -> None:
    if not cards:
        return
    cols = st.columns(len(cards))
    for col, (label, value, sub) in zip(cols, cards):
        with col:
            st.markdown(
                f"""
                <div style="border:1px solid rgba(120,140,170,.35); border-radius:14px; padding:16px 18px; min-height:118px; background:rgba(20,25,36,.45);">
                    <div style="font-size:0.88rem; color:rgba(230,235,245,.72); font-weight:700; margin-bottom:8px;">{label}</div>
                    <div style="font-size:1.85rem; font-weight:800; line-height:1.05; color:white;">{value}</div>
                    <div style="font-size:0.86rem; color:rgba(230,235,245,.62); margin-top:8px;">{sub}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def alert_by_score(message: str, score: float) -> None:
    if score >= 80:
        st.error(message)
    elif score >= 60:
        st.warning(message)
    else:
        st.info(message)



# ============================================================
# Futures / Macro Intelligence — regime decomposition
# ============================================================

MACRO_SLEEVE_MAP = {
    "Equity index": ["NQ=F", "ES=F", "YM=F", "RTY=F", "QQQ", "SPY"],
    "Volatility": ["^VIX", "^VIX9D", "^VXN"],
    "Rates": ["^TNX", "^FVX", "^TYX"],
    "Dollar": ["DX-Y.NYB", "UUP"],
    "Semis / sector": ["SMH", "SOXX", "XLK"],
    "Commodities": ["CL=F", "GC=F"],
}


def macro_row_directional_score(row: pd.Series) -> Optional[float]:
    """
    Score directionnel macro par instrument.
    0 = pression forte, 50 = neutre, 100 = support fort.
    Ne modifie aucun score existant : diagnostic additionnel uniquement.
    """
    regime = str(row.get("Regime", ""))
    if regime == "Données absentes":
        return None

    sym = str(row.get("Ticker", "")).strip().upper()
    role = DEFAULT_FUTURES_SYMBOLS.get(sym, {}).get("risk_role", "mixed")

    parts = []
    for col, weight in [("1D", 0.40), ("5D", 0.40), ("20D", 0.20)]:
        val = safe_float(row.get(col))
        if val is not None:
            parts.append((val, weight))

    if not parts:
        return None

    total_w = sum(w for _, w in parts)
    move = sum(v * w for v, w in parts) / max(total_w, _EPS)

    if role == "risk_on":
        score = 50.0 + move * 650.0
    elif role in ["risk_off", "pressure_up"]:
        score = 50.0 - move * 650.0
    else:
        score = 50.0 + move * 250.0

    return clamp(score)


def compute_macro_regime_decomposition(macro_df: pd.DataFrame) -> Tuple[Dict[str, Any], pd.DataFrame]:
    """
    Décompose le tape macro par familles : equity, vol, rates, dollar, semis, commodities.
    Le but est de rendre le bloc futures plus institutionnel sans recalculer le moteur options.
    """
    if macro_df is None or macro_df.empty:
        return {
            "macro_regime": "Indisponible",
            "macro_regime_score": 50.0,
            "primary_driver": "N/A",
            "breadth": "N/A",
            "coverage": "0/0",
            "message": "Décomposition futures/macro indisponible.",
        }, pd.DataFrame()

    df = macro_df.copy()
    df["Ticker"] = df["Ticker"].astype(str).str.upper().str.strip()

    rows = []

    for sleeve, symbols in MACRO_SLEEVE_MAP.items():
        symbols_norm = [s.upper().strip() for s in symbols]
        g = df[df["Ticker"].isin(symbols_norm)].copy()

        if g.empty:
            continue

        scores = []
        weights = []

        for _, row in g.iterrows():
            s = macro_row_directional_score(row)
            if s is None:
                continue

            corr = abs(safe_float(row.get("Corr"), 0.0) or 0.0)
            beta = abs(safe_float(row.get("Beta ticker"), 0.0) or 0.0)

            # Pondération prudente : plus le proxy est corrélé/beta-relevant, plus il compte.
            w = 1.0 + min(corr, 1.0) * 0.35 + min(beta, 2.0) * 0.10
            scores.append(s)
            weights.append(w)

        if not scores:
            sleeve_score = 50.0
        else:
            sleeve_score = sum(s * w for s, w in zip(scores, weights)) / max(sum(weights), _EPS)

        support_count = sum(1 for s in scores if s >= 58)
        pressure_count = sum(1 for s in scores if s <= 42)

        if sleeve_score >= 62:
            sleeve_regime = "Support"
        elif sleeve_score <= 42:
            sleeve_regime = "Pression"
        else:
            sleeve_regime = "Neutre"

        r1 = pd.to_numeric(g.get("1D", pd.Series(dtype=float)), errors="coerce").median()
        r5 = pd.to_numeric(g.get("5D", pd.Series(dtype=float)), errors="coerce").median()
        r20 = pd.to_numeric(g.get("20D", pd.Series(dtype=float)), errors="coerce").median()
        vol20 = pd.to_numeric(g.get("Vol 20D", pd.Series(dtype=float)), errors="coerce").median()
        beta_med = pd.to_numeric(g.get("Beta ticker", pd.Series(dtype=float)), errors="coerce").median()
        corr_med = pd.to_numeric(g.get("Corr", pd.Series(dtype=float)), errors="coerce").median()

        rows.append({
            "Sleeve": sleeve,
            "_score_num": sleeve_score,
            "Score": fmt_score(sleeve_score),
            "Regime": sleeve_regime,
            "Tickers": ", ".join(g["Ticker"].tolist()),
            "1D median": r1,
            "5D median": r5,
            "20D median": r20,
            "Vol 20D median": vol20,
            "Beta median": beta_med,
            "Corr median": corr_med,
            "Support proxies": support_count,
            "Pressure proxies": pressure_count,
            "Lecture": macro_sleeve_lecture(sleeve, sleeve_regime, sleeve_score, support_count, pressure_count),
        })

    decomp = pd.DataFrame(rows)

    if decomp.empty:
        return {
            "macro_regime": "Indisponible",
            "macro_regime_score": 50.0,
            "primary_driver": "N/A",
            "breadth": "N/A",
            "coverage": f"0/{len(macro_df)}",
            "message": "Décomposition futures/macro indisponible.",
        }, decomp

    global_score = safe_float(decomp["_score_num"].mean(), 50.0) or 50.0

    support_sleeves = int((decomp["_score_num"] >= 58).sum())
    pressure_sleeves = int((decomp["_score_num"] <= 42).sum())

    decomp["_distance_neutral"] = (decomp["_score_num"] - 50.0).abs()
    driver_row = decomp.sort_values("_distance_neutral", ascending=False).iloc[0]
    primary_driver = str(driver_row.get("Sleeve", "N/A"))

    if global_score >= 62 and pressure_sleeves == 0:
        macro_regime = "Macro support"
        message = "Régime futures/macro favorable : les principaux proxies confirment le risque-on."
    elif global_score <= 42 and support_sleeves == 0:
        macro_regime = "Macro pression"
        message = "Régime futures/macro défavorable : pression macro visible sur les proxies suivis."
    elif support_sleeves > 0 and pressure_sleeves > 0:
        macro_regime = "Macro divergent"
        message = "Régime futures/macro divergent : certaines familles confirment, d'autres contredisent."
    else:
        macro_regime = "Macro mixte"
        message = "Régime futures/macro mixte : confirmation partielle, sans alignement complet."

    available = int((macro_df["Regime"].astype(str) != "Données absentes").sum()) if "Regime" in macro_df.columns else len(macro_df)
    total = len(macro_df)

    summary = {
        "macro_regime": macro_regime,
        "macro_regime_score": clamp(global_score),
        "primary_driver": primary_driver,
        "breadth": f"{support_sleeves} support / {pressure_sleeves} pression",
        "coverage": f"{available}/{total}",
        "message": message,
    }

    return summary, decomp


def macro_sleeve_lecture(
    sleeve: str,
    regime: str,
    score: float,
    support_count: int,
    pressure_count: int
) -> str:
    if regime == "Support":
        return f"{sleeve} en support macro ; {support_count} proxy(s) positif(s), score {fmt_score(score)}."
    if regime == "Pression":
        return f"{sleeve} en pression macro ; {pressure_count} proxy(s) négatif(s), score {fmt_score(score)}."
    return f"{sleeve} neutre ou mixte ; pas de domination claire des proxies."


def render_macro_regime_chart(decomp: pd.DataFrame) -> None:
    if decomp is None or decomp.empty or "_score_num" not in decomp.columns:
        return

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=decomp["Sleeve"],
        y=decomp["_score_num"],
        name="Macro sleeve score",
    ))
    fig.add_hline(y=50, line_dash="dash", line_color="white")
    fig.add_hline(y=62, line_dash="dot", line_color="rgba(120,180,255,.65)")
    fig.add_hline(y=42, line_dash="dot", line_color="rgba(255,180,120,.65)")
    fig.update_layout(title="Macro regime decomposition — score par famille")
    fig.update_xaxes(title="Famille macro / futures")
    fig.update_yaxes(title="Score", range=[0, 100])

    st.plotly_chart(apply_dark_layout(fig, 430), width="stretch")


def render_macro_regime_dashboard(macro_df: pd.DataFrame) -> Dict[str, Any]:
    summary, decomp = compute_macro_regime_decomposition(macro_df)

    st.subheader("Futures / Macro Regime Dashboard")

    cards = [
        ("Macro regime", str(summary.get("macro_regime", "N/A")), fmt_score(summary.get("macro_regime_score"))),
        ("Primary driver", str(summary.get("primary_driver", "N/A")), "Famille dominante"),
        ("Breadth", str(summary.get("breadth", "N/A")), "Support / pression"),
        ("Data coverage", str(summary.get("coverage", "N/A")), "Proxies disponibles"),
    ]
    render_card_grid(cards)

    global_score = safe_float(summary.get("macro_regime_score"), 50.0) or 50.0
    risk_score = 100.0 - global_score if global_score >= 50 else 50.0 + abs(50.0 - global_score)
    alert_by_score(str(summary.get("message", "Régime macro indisponible.")), risk_score)

    if decomp is not None and not decomp.empty:
        render_macro_regime_chart(decomp)

        display_cols = [
            "Sleeve",
            "Score",
            "Regime",
            "Tickers",
            "1D median",
            "5D median",
            "20D median",
            "Vol 20D median",
            "Beta median",
            "Corr median",
            "Support proxies",
            "Pressure proxies",
            "Lecture",
        ]
        st.dataframe(
            format_display_df(decomp[[c for c in display_cols if c in decomp.columns]]),
            width="stretch",
            hide_index=True,
        )

    st.caption(
        "Macro Regime Dashboard = décomposition descriptive des futures/proxies déjà téléchargés. "
        "Ce bloc ne modifie pas les scores options, gamma, greeks ou decision gate."
    )

    return summary


# ============================================================
# Cross-Asset Confirmation Matrix
# ============================================================

def _cross_asset_family(row: pd.Series) -> str:
    """
    Classe un proxy futures/macro en famille lisible.
    Ne modifie aucun calcul existant.
    """
    ticker = str(row.get("Ticker", "")).upper()
    typ = str(row.get("Type", ""))

    if ticker in ["NQ=F", "ES=F", "YM=F", "RTY=F"]:
        return "Equity futures"

    if ticker in ["QQQ", "SPY"]:
        return "Equity ETF"

    if ticker in ["SMH", "SOXX"]:
        return "Semis / leadership"

    if ticker in ["^VIX", "VIX"]:
        return "Volatility"

    if ticker in ["^TNX", "^TYX", "^FVX"]:
        return "Rates"

    if ticker in ["DX-Y.NYB", "DXY", "UUP"]:
        return "Dollar / FX"

    if ticker in ["CL=F", "GC=F"]:
        return "Commodities"

    if "Volatility" in typ:
        return "Volatility"

    if "Rates" in typ:
        return "Rates"

    if "FX" in typ:
        return "Dollar / FX"

    if "Sector" in typ:
        return "Sector / leadership"

    return "Other proxy"


def _cross_asset_role(ticker: str) -> str:
    """
    Rôle macro indicatif.
    Support = favorable au risk-on / au setup action.
    Pressure = pression macro.
    """
    t = str(ticker or "").upper().strip()

    if t in ["NQ=F", "ES=F", "YM=F", "RTY=F", "QQQ", "SPY", "SMH", "SOXX"]:
        return "Risk-on"

    if t in ["^VIX", "VIX"]:
        return "Risk-off inverse"

    if t in ["^TNX", "^TYX", "^FVX"]:
        return "Rates pressure"

    if t in ["DX-Y.NYB", "DXY", "UUP"]:
        return "Dollar pressure"

    return "Context"


def _cross_asset_weight(family: str) -> float:
    """
    Pondération légère par famille.
    Prudence : poids simples, pas de modèle prédictif.
    """
    family = str(family)

    if family == "Volatility":
        return 1.25

    if family == "Semis / leadership":
        return 1.20

    if family == "Equity futures":
        return 1.15

    if family in ["Rates", "Dollar / FX"]:
        return 1.10

    if family == "Equity ETF":
        return 1.00

    return 0.85


def _cross_asset_proxy_score(row: pd.Series) -> float:
    """
    Score de confirmation par proxy.
    0 = pression forte
    50 = neutre
    100 = support fort

    Utilise uniquement les rendements déjà présents dans macro_df.
    """
    ticker = str(row.get("Ticker", "")).upper().strip()
    role = _cross_asset_role(ticker)

    r1 = safe_float(row.get("1D"), 0.0) or 0.0
    r5 = safe_float(row.get("5D"), 0.0) or 0.0
    r20 = safe_float(row.get("20D"), 0.0) or 0.0

    # Mix court/moyen terme : 5D dominant, 1D réactif, 20D contexte.
    move = 0.35 * r1 + 0.45 * r5 + 0.20 * r20

    if role == "Risk-on":
        score = 50.0 + move * 650.0

    elif role == "Risk-off inverse":
        # VIX en hausse = pression, VIX en baisse = support.
        score = 50.0 - move * 700.0

    elif role in ["Rates pressure", "Dollar pressure"]:
        # Taux / dollar en hausse = pression pour croissance / duration.
        score = 50.0 - move * 500.0

    else:
        # Commodities / autres : contexte moins directionnel.
        score = 50.0 + move * 180.0

    return clamp(score)


def _cross_asset_regime(score: Any) -> str:
    s = safe_float(score, 50.0) or 50.0

    if s >= 65:
        return "Support fort"

    if s >= 58:
        return "Support"

    if s <= 35:
        return "Pression forte"

    if s <= 42:
        return "Pression"

    return "Neutre"


def _cross_asset_lecture(row: pd.Series) -> str:
    family = str(row.get("Family", "N/A"))
    regime = str(row.get("Regime", "N/A"))
    ticker = str(row.get("Ticker", "N/A"))
    score = safe_float(row.get("_score_num"), 50.0) or 50.0
    corr = safe_float(row.get("Corr"))

    corr_txt = ""

    if corr is not None:
        corr_txt = f" Corrélation ticker {corr:.2f}."

    if regime in ["Support fort", "Support"]:
        return f"{ticker} confirme le tape via {family}. Score {fmt_score(score)}.{corr_txt}"

    if regime in ["Pression forte", "Pression"]:
        return f"{ticker} contredit le tape via {family}. Score {fmt_score(score)}.{corr_txt}"

    return f"{ticker} neutre sur {family}. Pas de confirmation nette.{corr_txt}"


def build_cross_asset_confirmation_matrix(
    macro_df: pd.DataFrame,
    macro_summary: Optional[Dict[str, Any]] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Cross-Asset Confirmation Matrix.

    Objectif :
    - vérifier si equity futures, ETF, semis, VIX, taux, dollar et commodities confirment ou divergent ;
    - produire une lecture futures/macro plus équilibrée ;
    - ne modifie aucun score options/gamma/greeks/decision gate.
    """
    macro_summary = macro_summary or {}

    empty_summary = {
        "confirmation_state": "Indisponible",
        "confirmation_score": None,
        "support_count": 0,
        "pressure_count": 0,
        "neutral_count": 0,
        "primary_divergence": "N/A",
        "message": "Confirmation cross-asset indisponible.",
    }

    if macro_df is None or macro_df.empty:
        return pd.DataFrame(), empty_summary

    required = ["Ticker", "1D", "5D", "20D"]

    if any(c not in macro_df.columns for c in required):
        return pd.DataFrame(), empty_summary

    df = macro_df.copy()

    if "Regime" in df.columns:
        df = df[df["Regime"].astype(str) != "Données absentes"].copy()

    if df.empty:
        return pd.DataFrame(), empty_summary

    rows = []

    for _, row in df.iterrows():
        ticker = str(row.get("Ticker", "N/A"))
        family = _cross_asset_family(row)
        role = _cross_asset_role(ticker)
        weight = _cross_asset_weight(family)
        score = _cross_asset_proxy_score(row)
        regime = _cross_asset_regime(score)

        rows.append({
            "Family": family,
            "Ticker": ticker,
            "Instrument": row.get("Instrument", ticker),
            "Role": role,
            "_score_num": score,
            "Score": fmt_score(score),
            "Regime": regime,
            "Weight": weight,
            "1D": row.get("1D"),
            "5D": row.get("5D"),
            "20D": row.get("20D"),
            "Vol 20D": row.get("Vol 20D"),
            "Beta ticker": row.get("Beta ticker"),
            "Corr": row.get("Corr"),
            "Existing tape regime": row.get("Regime", "N/A"),
        })

    out = pd.DataFrame(rows)

    if out.empty:
        return out, empty_summary

    # Décomposition par famille d'abord pour éviter le double comptage
    # des proxies très corrélés : NQ/QQQ/SPY/ES ou SMH/SOXX.
    family_decomp = (
        out.groupby("Family", as_index=False)
        .agg(
            Score_num=("_score_num", "mean"),
            Proxies=("Ticker", lambda s: ", ".join(s.astype(str).tolist())),
            Support=("Regime", lambda s: int(pd.Series(s).isin(["Support fort", "Support"]).sum())),
            Pressure=("Regime", lambda s: int(pd.Series(s).isin(["Pression forte", "Pression"]).sum())),
            Neutral=("Regime", lambda s: int(pd.Series(s).eq("Neutre").sum())),
        )
    )

    family_decomp["Family weight"] = family_decomp["Family"].map(_cross_asset_weight).fillna(1.0)
    family_decomp["Weighted score"] = family_decomp["Score_num"] * family_decomp["Family weight"]

    total_family_weight = safe_float(family_decomp["Family weight"].sum(), 0.0) or 0.0

    if total_family_weight <= 0:
        confirmation_score = safe_float(family_decomp["Score_num"].mean(), 50.0) or 50.0
    else:
        confirmation_score = safe_float(
            family_decomp["Weighted score"].sum() / total_family_weight,
            50.0,
        ) or 50.0

    family_decomp["Score"] = family_decomp["Score_num"].map(fmt_score)
    family_decomp["Regime"] = family_decomp["Score_num"].map(_cross_asset_regime)

    support_count = int(family_decomp["Regime"].isin(["Support fort", "Support"]).sum())
    pressure_count = int(family_decomp["Regime"].isin(["Pression forte", "Pression"]).sum())
    neutral_count = int(family_decomp["Regime"].eq("Neutre").sum())

    pressure_df = out[out["Regime"].isin(["Pression forte", "Pression"])].copy()

    if not pressure_df.empty:
        primary_divergence = str(
            pressure_df.sort_values("_score_num", ascending=True).iloc[0].get("Ticker", "N/A")
        )
    else:
        primary_divergence = "Aucune divergence majeure"

    # Seuils plus prudents :
    # - Confirmation large seulement si le support est vraiment large par familles.
    # - 60-74 = support constructif, mais pas validation totale.
    if confirmation_score >= 75 and pressure_count == 0 and support_count >= 4 and neutral_count <= 1:
        confirmation_state = "Confirmation large"
        message = "Cross-asset largement favorable : la majorité des familles futures/macro confirment le tape."

    elif confirmation_score >= 60 and pressure_count <= 1 and support_count >= 3:
        confirmation_state = "Support cross-asset"
        message = "Cross-asset constructif : plusieurs familles confirment le tape, mais l'alignement n'est pas total."

    elif pressure_count >= 2 and support_count >= 2:
        confirmation_state = "Divergence macro"
        message = "Cross-asset divergent : certaines familles soutiennent le setup, d'autres le contredisent."

    elif confirmation_score <= 42 and support_count <= 1:
        confirmation_state = "Pression large"
        message = "Cross-asset défavorable : plusieurs familles macro/futures exercent une pression."

    else:
        confirmation_state = "Confirmation mixte"
        message = "Cross-asset mixte : pas de validation nette ni de blocage macro clair."

    out["Lecture"] = out.apply(_cross_asset_lecture, axis=1)

    # Colonnes techniques gardées pour calcul, mais la table affichée sera propre.
    summary = {
        "confirmation_state": confirmation_state,
        "confirmation_score": clamp(confirmation_score),
        "support_count": support_count,
        "pressure_count": pressure_count,
        "neutral_count": neutral_count,
        "primary_divergence": primary_divergence,
        "message": message,
        "family_decomp": family_decomp,
    }

    out = out.sort_values("_score_num", ascending=False).reset_index(drop=True)

    return out, summary


def render_cross_asset_confirmation_matrix(
    macro_df: pd.DataFrame,
    macro_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Affichage Cross-Asset Confirmation Matrix.
    À placer dans l'onglet Futures / Macro après Macro Regime Dashboard.
    """
    st.subheader("Cross-Asset Confirmation Matrix")

    confirm_df, summary = build_cross_asset_confirmation_matrix(
        macro_df=macro_df,
        macro_summary=macro_summary,
    )

    if confirm_df is None or confirm_df.empty:
        st.info("Cross-asset confirmation indisponible : proxies macro insuffisants.")
        return summary

    render_card_grid([
        (
            "Confirmation state",
            str(summary.get("confirmation_state", "N/A")),
            fmt_score(summary.get("confirmation_score")),
        ),
        (
            "Family breadth",
            f"{fmt_int(summary.get('support_count'))} support / {fmt_int(summary.get('pressure_count'))} pression",
            f"{fmt_int(summary.get('neutral_count'))} familles neutres",
        ),
        (
            "Primary divergence",
            str(summary.get("primary_divergence", "N/A")),
            "Proxy contradicteur principal",
        ),
        (
            "Base tape",
            str((macro_summary or {}).get("tape_state", "N/A")),
            "Score brut " + fmt_score((macro_summary or {}).get("tape_score")),
        ),
    ])

    score = safe_float(summary.get("confirmation_score"), 50.0) or 50.0
    state = str(summary.get("confirmation_state", ""))

    if state in ["Pression large", "Divergence macro"]:
        alert_by_score(
            str(summary.get("message", "Cross-asset divergent.")),
            72.0,
        )
    elif score >= 58:
        alert_by_score(
            str(summary.get("message", "Cross-asset favorable.")),
            35.0,
        )
    else:
        alert_by_score(
            str(summary.get("message", "Cross-asset mixte.")),
            55.0,
        )

    family_decomp = summary.get("family_decomp", pd.DataFrame())

    if isinstance(family_decomp, pd.DataFrame) and not family_decomp.empty:
        fig = go.Figure()

        plot_family = family_decomp.sort_values("Score_num", ascending=False)

        fig.add_trace(
            go.Bar(
                x=plot_family["Family"],
                y=plot_family["Score_num"],
                name="Family confirmation score",
                hovertemplate=(
                    "%{x}<br>"
                    "Score %{y:.0f}/100"
                    "<extra></extra>"
                ),
            )
        )

        fig.add_hline(y=50, line_dash="dash", line_color="white")
        fig.add_hline(y=58, line_dash="dot", line_color="rgba(120,180,255,.65)")
        fig.add_hline(y=42, line_dash="dot", line_color="rgba(255,180,120,.65)")

        fig.update_layout(
            title="Cross-asset confirmation — score par famille",
            xaxis_title="Famille",
            yaxis_title="Score",
        )

        fig.update_yaxes(range=[0, 100])

        st.plotly_chart(apply_dark_layout(fig, 430), width="stretch")

        family_display = family_decomp.copy()
        family_display = family_display.drop(columns=["Score_num"], errors="ignore")

        st.dataframe(
            family_display,
            width="stretch",
            hide_index=True,
        )

    display_cols = [
        "Family",
        "Ticker",
        "Instrument",
        "Role",
        "Score",
        "Regime",
        "1D",
        "5D",
        "20D",
        "Vol 20D",
        "Beta ticker",
        "Corr",
        "Existing tape regime",
        "Lecture",
    ]

    st.dataframe(
        format_display_df(confirm_df[[c for c in display_cols if c in confirm_df.columns]]),
        width="stretch",
        hide_index=True,
    )

    st.caption(
        "Cross-Asset Confirmation Matrix = lecture mécanique des futures/proxies déjà chargés : equity futures, ETF, semis, VIX, taux, dollar et commodities. "
        "Ce bloc sert à valider ou contredire le contexte futures/macro ; il ne modifie aucun score options, gamma, greeks ou decision gate."
    )

    return summary



# ============================================================
# Futures Divergence / Leadership Monitor
# ============================================================

def _leadership_family_score(decomp: pd.DataFrame, family: str) -> Optional[float]:
    if decomp is None or decomp.empty or "Family" not in decomp.columns or "Score_num" not in decomp.columns:
        return None

    row = decomp[decomp["Family"].astype(str).eq(str(family))]

    if row.empty:
        return None

    return safe_float(row["Score_num"].iloc[0])


def _leadership_family_order(family: str) -> int:
    order = {
        "Equity futures": 1,
        "Equity ETF": 2,
        "Semis / leadership": 3,
        "Volatility": 4,
        "Rates": 5,
        "Dollar / FX": 6,
        "Commodities": 7,
        "Other": 99,
    }
    return order.get(str(family), 99)


def _leadership_proxy_lecture(row: pd.Series) -> str:
    family = str(row.get("Family", "N/A"))
    regime = str(row.get("Regime", "N/A"))
    ticker = str(row.get("Ticker", "N/A"))

    if family == "Equity futures":
        if regime in ["Support fort", "Support"]:
            return f"{ticker} confirme le cœur futures du tape."
        if regime in ["Pression forte", "Pression"]:
            return f"{ticker} contredit le tape futures : divergence à surveiller."
        return f"{ticker} neutre : pas de confirmation claire par les futures."

    if family == "Equity ETF":
        if regime in ["Support fort", "Support"]:
            return f"{ticker} confirme via ETF equity, utile mais moins pur que futures."
        if regime in ["Pression forte", "Pression"]:
            return f"{ticker} pèse sur la confirmation equity ETF."
        return f"{ticker} neutre côté ETF."

    if family == "Semis / leadership":
        if regime in ["Support fort", "Support"]:
            return f"{ticker} soutient le leadership semis."
        if regime in ["Pression forte", "Pression"]:
            return f"{ticker} affaiblit le leadership semis."
        return f"{ticker} neutre sur le leadership sectoriel."

    if family == "Volatility":
        if regime in ["Support fort", "Support"]:
            return f"{ticker} confirme par détente volatilité."
        if regime in ["Pression forte", "Pression"]:
            return f"{ticker} signale pression volatilité."
        return f"{ticker} neutre côté volatilité."

    if family in ["Rates", "Dollar / FX"]:
        if regime in ["Support fort", "Support"]:
            return f"{ticker} ne crée pas de pression macro nette."
        if regime in ["Pression forte", "Pression"]:
            return f"{ticker} crée une pression macro à surveiller."
        return f"{ticker} neutre côté {family}."

    return "Proxy macro lisible mais non dominant."


def build_futures_leadership_monitor(
    macro_df: pd.DataFrame,
    macro_summary: Optional[Dict[str, Any]] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Futures Divergence / Leadership Monitor.

    Objectif :
    - séparer le vrai cœur futures des confirmations ETF / semis / volatilité ;
    - détecter si le support vient des futures principaux ou seulement de proxys secondaires ;
    - ne modifie aucun score options, gamma, greeks, macro ou decision gate.
    """
    macro_summary = macro_summary or {}

    empty_summary = {
        "leadership_state": "Indisponible",
        "leadership_risk_score": None,
        "leader_family": "N/A",
        "laggard_family": "N/A",
        "leadership_gap": None,
        "futures_core_score": None,
        "equity_confirmation_score": None,
        "support_count": 0,
        "pressure_count": 0,
        "message": "Leadership futures indisponible.",
        "family_decomp": pd.DataFrame(),
    }

    if macro_df is None or macro_df.empty:
        return pd.DataFrame(), empty_summary

    required = ["Ticker", "1D", "5D", "20D"]

    if any(c not in macro_df.columns for c in required):
        return pd.DataFrame(), empty_summary

    df = macro_df.copy()

    if "Regime" in df.columns:
        df = df[df["Regime"].astype(str) != "Données absentes"].copy()

    if df.empty:
        return pd.DataFrame(), empty_summary

    rows = []

    for _, row in df.iterrows():
        ticker = str(row.get("Ticker", "N/A"))
        family = _cross_asset_family(row)
        role = _cross_asset_role(ticker)
        score = _cross_asset_proxy_score(row)
        regime = _cross_asset_regime(score)

        rows.append({
            "Family": family,
            "Ticker": ticker,
            "Instrument": row.get("Instrument", ticker),
            "Role": role,
            "_score_num": score,
            "Score": fmt_score(score),
            "Regime": regime,
            "1D": row.get("1D"),
            "5D": row.get("5D"),
            "20D": row.get("20D"),
            "Vol 20D": row.get("Vol 20D"),
            "Beta ticker": row.get("Beta ticker"),
            "Corr": row.get("Corr"),
            "Existing tape regime": row.get("Regime", "N/A"),
        })

    out = pd.DataFrame(rows)

    if out.empty:
        return out, empty_summary

    out["Lecture"] = out.apply(_leadership_proxy_lecture, axis=1)

    family_decomp = (
        out.groupby("Family", as_index=False)
        .agg(**{
            "Score_num": ("_score_num", "mean"),
            "Proxies": ("Ticker", lambda s: ", ".join(s.astype(str).tolist())),
            "Proxy count": ("Ticker", "count"),
            "Support": ("Regime", lambda s: int(pd.Series(s).isin(["Support fort", "Support"]).sum())),
            "Pressure": ("Regime", lambda s: int(pd.Series(s).isin(["Pression forte", "Pression"]).sum())),
            "Neutral": ("Regime", lambda s: int(pd.Series(s).eq("Neutre").sum())),
            "Median 1D": ("1D", "median"),
            "Median 5D": ("5D", "median"),
            "Median 20D": ("20D", "median"),
            "Median vol 20D": ("Vol 20D", "median"),
            "Median beta": ("Beta ticker", "median"),
            "Median corr": ("Corr", "median"),
        })
    )

    family_decomp["Score"] = family_decomp["Score_num"].map(fmt_score)
    family_decomp["Regime"] = family_decomp["Score_num"].map(_cross_asset_regime)
    family_decomp["_order"] = family_decomp["Family"].map(_leadership_family_order)

    family_decomp = family_decomp.sort_values(["_order", "Score_num"], ascending=[True, False]).reset_index(drop=True)

    futures_score = _leadership_family_score(family_decomp, "Equity futures")
    etf_score = _leadership_family_score(family_decomp, "Equity ETF")
    semis_score = _leadership_family_score(family_decomp, "Semis / leadership")
    vol_score = _leadership_family_score(family_decomp, "Volatility")
    rates_score = _leadership_family_score(family_decomp, "Rates")
    dollar_score = _leadership_family_score(family_decomp, "Dollar / FX")

    equity_scores = [x for x in [futures_score, etf_score, semis_score] if x is not None]
    equity_confirmation_score = safe_float(np.nanmean(equity_scores)) if equity_scores else None

    leader_row = family_decomp.sort_values("Score_num", ascending=False).iloc[0]
    laggard_row = family_decomp.sort_values("Score_num", ascending=True).iloc[0]

    leader_family = str(leader_row.get("Family", "N/A"))
    laggard_family = str(laggard_row.get("Family", "N/A"))

    leader_score = safe_float(leader_row.get("Score_num"), 50.0) or 50.0
    laggard_score = safe_float(laggard_row.get("Score_num"), 50.0) or 50.0
    leadership_gap = leader_score - laggard_score

    support_count = int(family_decomp["Regime"].isin(["Support fort", "Support"]).sum())
    pressure_count = int(family_decomp["Regime"].isin(["Pression forte", "Pression"]).sum())
    neutral_count = int(family_decomp["Regime"].eq("Neutre").sum())

    futures_gap_candidates = []

    if futures_score is not None and etf_score is not None:
        futures_gap_candidates.append(abs(futures_score - etf_score))

    if futures_score is not None and semis_score is not None:
        futures_gap_candidates.append(abs(futures_score - semis_score))

    futures_confirmation_gap = max(futures_gap_candidates) if futures_gap_candidates else 0.0

    score_values = pd.to_numeric(family_decomp["Score_num"], errors="coerce").dropna()

    if len(score_values) >= 2:
        dispersion_score = clamp(float(score_values.std(ddof=0)) / 25.0 * 100.0)
    else:
        dispersion_score = 0.0

    futures_gap_score = clamp(futures_confirmation_gap / 30.0 * 100.0)

    contradiction_score = 0.0
    if support_count >= 1 and pressure_count >= 1:
        contradiction_score = 70.0
    if support_count >= 2 and pressure_count >= 2:
        contradiction_score = 90.0

    pressure_score = clamp(pressure_count / max(len(family_decomp), 1) * 100.0)

    leadership_risk_score = clamp(
        0.35 * dispersion_score
        + 0.30 * futures_gap_score
        + 0.22 * contradiction_score
        + 0.13 * pressure_score
    )

    # Classification prudente.
    if support_count >= 2 and pressure_count >= 2:
        leadership_state = "Divergence active"
        leadership_risk_score = max(leadership_risk_score, 72.0)
        message = (
            "Leadership divergent : plusieurs familles soutiennent le tape tandis que d'autres le contredisent. "
            "Ne pas lire le support macro comme totalement confirmé."
        )

    elif (
        futures_score is not None and etf_score is not None and semis_score is not None
        and futures_score >= 58 and etf_score >= 58 and semis_score >= 58
        and pressure_count == 0
    ):
        leadership_state = "Leadership confirmé"
        leadership_risk_score = min(leadership_risk_score, 35.0)
        message = (
            "Leadership futures confirmé : futures core, ETF et semis soutiennent le tape sans pression macro majeure."
        )

    elif semis_score is not None and semis_score >= 70 and (futures_score is None or futures_score < 58):
        leadership_state = "Leadership étroit"
        leadership_risk_score = max(leadership_risk_score, 58.0)
        message = (
            "Leadership étroit : le support vient surtout des semis/leadership, mais les futures core ne confirment pas pleinement."
        )

    elif futures_score is not None and futures_score >= 58 and (
        (etf_score is not None and etf_score < 50)
        or (semis_score is not None and semis_score < 50)
    ):
        leadership_state = "Futures partiellement confirmés"
        leadership_risk_score = max(leadership_risk_score, 52.0)
        message = (
            "Futures core constructifs, mais confirmation ETF/semis incomplète. "
            "Le tape est exploitable, pas totalement aligné."
        )

    elif futures_score is not None and futures_score < 50 and (
        (etf_score is not None and etf_score >= 58)
        or (semis_score is not None and semis_score >= 58)
    ):
        leadership_state = "Support hors futures"
        leadership_risk_score = max(leadership_risk_score, 58.0)
        message = (
            "Support surtout porté par ETF/secteurs, pas par les futures core. "
            "À traiter comme confirmation secondaire."
        )

    elif vol_score is not None and vol_score >= 70 and (
        equity_confirmation_score is None or equity_confirmation_score < 55
    ):
        leadership_state = "Support défensif"
        leadership_risk_score = max(leadership_risk_score, 60.0)
        message = (
            "Support principalement lié à la volatilité plutôt qu'aux actifs risk-on. "
            "La confirmation directionnelle reste fragile."
        )

    elif leadership_gap >= 28:
        leadership_state = "Leadership dispersé"
        leadership_risk_score = max(leadership_risk_score, 55.0)
        message = (
            "Leadership dispersé : les familles macro/futures ne progressent pas avec la même intensité."
        )

    else:
        leadership_state = "Leadership mixte"
        leadership_risk_score = max(min(leadership_risk_score, 58.0), 40.0)
        message = (
            "Leadership mixte : pas de divergence majeure, mais pas de confirmation futures parfaitement large."
        )

    # Pression macro spécifique : taux/dollar.
    if rates_score is not None and rates_score <= 42:
        message += " Taux en pression."
    if dollar_score is not None and dollar_score <= 42:
        message += " Dollar en pression."

    family_decomp["Lecture"] = family_decomp.apply(
        lambda r: (
            "Famille leader du tape." if str(r.get("Family")) == leader_family
            else "Famille la plus faible du tape." if str(r.get("Family")) == laggard_family
            else "Famille contributive ou neutre dans la confirmation macro."
        ),
        axis=1,
    )

    summary = {
        "leadership_state": leadership_state,
        "leadership_risk_score": leadership_risk_score,
        "leader_family": leader_family,
        "laggard_family": laggard_family,
        "leadership_gap": leadership_gap,
        "futures_core_score": futures_score,
        "equity_confirmation_score": equity_confirmation_score,
        "support_count": support_count,
        "pressure_count": pressure_count,
        "neutral_count": neutral_count,
        "message": message,
        "family_decomp": family_decomp,
    }

    out = out.sort_values(["Family", "_score_num"], ascending=[True, False]).reset_index(drop=True)

    return out, summary


def render_futures_leadership_monitor(
    macro_df: pd.DataFrame,
    macro_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Affichage Futures Divergence / Leadership Monitor.
    À placer dans l'onglet Futures Tape après Cross-Asset Confirmation Matrix.
    """
    st.subheader("Futures Divergence / Leadership Monitor")

    leadership_df, summary = build_futures_leadership_monitor(
        macro_df=macro_df,
        macro_summary=macro_summary,
    )

    if leadership_df is None or leadership_df.empty:
        st.info("Leadership monitor indisponible : données futures/macro insuffisantes.")
        return summary

    leadership_risk_score = safe_float(summary.get("leadership_risk_score"), None)

    leadership_display_score = (
        clamp(100.0 - leadership_risk_score)
        if leadership_risk_score is not None
        else safe_float(summary.get("futures_core_score"), 50.0)
    )

    render_card_grid([
        (
            "Leadership state",
            str(summary.get("leadership_state", "N/A")),
            fmt_score(leadership_display_score),
        ),
        (
            "Leader / laggard",
            str(summary.get("leader_family", "N/A")),
            "Faible : " + str(summary.get("laggard_family", "N/A")),
        ),
        (
            "Futures core",
            fmt_score(summary.get("futures_core_score")),
            "NQ/ES/YM/RTY si disponibles",
        ),
        (
            "Leadership gap",
            fmt_num(summary.get("leadership_gap"), 1),
            "Écart leader - retardataire",
        ),
    ])

    risk_score = safe_float(summary.get("leadership_risk_score"), 50.0) or 50.0
    alert_by_score(str(summary.get("message", "Leadership futures mixte.")), risk_score)

    family_decomp = summary.get("family_decomp", pd.DataFrame())

    if isinstance(family_decomp, pd.DataFrame) and not family_decomp.empty:
        plot_df = family_decomp.copy()
        plot_df["Score_num"] = pd.to_numeric(plot_df["Score_num"], errors="coerce")
        plot_df = plot_df.dropna(subset=["Score_num"]).sort_values("_order")

        if not plot_df.empty:
            fig = go.Figure()

            fig.add_trace(
                go.Bar(
                    x=plot_df["Family"],
                    y=plot_df["Score_num"],
                    name="Family leadership score",
                    hovertemplate=(
                        "%{x}<br>"
                        "Score %{y:.0f}/100"
                        "<extra></extra>"
                    ),
                )
            )

            fig.add_hline(y=50, line_dash="dash", line_color="white")
            fig.add_hline(y=58, line_dash="dot", line_color="rgba(120,180,255,.65)")
            fig.add_hline(y=42, line_dash="dot", line_color="rgba(255,180,120,.65)")

            fig.update_layout(
                title="Futures / macro leadership — score par famille",
                xaxis_title="Famille",
                yaxis_title="Score",
            )
            fig.update_yaxes(range=[0, 100])

            st.plotly_chart(apply_dark_layout(fig, 430), width="stretch")

        family_display_cols = [
            "Family",
            "Proxies",
            "Proxy count",
            "Support",
            "Pressure",
            "Neutral",
            "Score",
            "Regime",
            "Median 1D",
            "Median 5D",
            "Median 20D",
            "Median vol 20D",
            "Median beta",
            "Median corr",
            "Lecture",
        ]

        st.dataframe(
            format_display_df(family_decomp[[c for c in family_display_cols if c in family_decomp.columns]]),
            width="stretch",
            hide_index=True,
        )

    with st.expander("Voir proxies futures/macro détaillés", expanded=False):
        proxy_display_cols = [
            "Family",
            "Ticker",
            "Instrument",
            "Role",
            "Score",
            "Regime",
            "1D",
            "5D",
            "20D",
            "Vol 20D",
            "Beta ticker",
            "Corr",
            "Existing tape regime",
            "Lecture",
        ]

        st.dataframe(
            format_display_df(leadership_df[[c for c in proxy_display_cols if c in leadership_df.columns]]),
            width="stretch",
            hide_index=True,
        )

    st.caption(
        "Futures Divergence / Leadership Monitor = lecture mécanique des familles futures/macro déjà téléchargées. "
        "Il distingue futures core, ETF, semis, volatilité, taux et dollar pour éviter de confondre support sectoriel et confirmation futures large. "
        "Ce bloc ne modifie aucun score options, gamma, greeks, macro ou decision gate."
    )

    return summary



# ============================================================
# Futures Momentum / Trend Confirmation
# ============================================================

def _momentum_family(row: pd.Series) -> str:
    """
    Classe locale pour le bloc momentum.
    On ne dépend pas d'une autre fonction pour éviter les effets de bord.
    """
    ticker = str(row.get("Ticker", "")).upper()
    typ = str(row.get("Type", ""))

    if ticker in ["NQ=F", "ES=F", "YM=F", "RTY=F"]:
        return "Equity futures"

    if ticker in ["QQQ", "SPY"]:
        return "Equity ETF"

    if ticker in ["SMH", "SOXX"]:
        return "Semis / leadership"

    if ticker == "^VIX":
        return "Volatility"

    if ticker == "^TNX":
        return "Rates"

    if ticker == "DX-Y.NYB":
        return "Dollar / FX"

    if ticker in ["CL=F", "GC=F"]:
        return "Commodities"

    if "FUT" in typ.upper():
        return "Other futures"

    return "Other"


def _momentum_family_order(family: str) -> int:
    order = {
        "Equity futures": 1,
        "Equity ETF": 2,
        "Semis / leadership": 3,
        "Volatility": 4,
        "Rates": 5,
        "Dollar / FX": 6,
        "Commodities": 7,
        "Other futures": 8,
        "Other": 99,
    }
    return order.get(str(family), 99)


def _momentum_role_sign(ticker: str) -> float:
    """
    +1 = hausse du proxy confirme le risk-on.
    -1 = baisse du proxy confirme le risk-on.

    Exemple :
    - NQ/ES/QQQ/SPY/SMH/SOXX : hausse = support.
    - VIX, taux, dollar : baisse = support.
    """
    ticker = str(ticker).upper().strip()

    if ticker in ["^VIX", "^TNX", "DX-Y.NYB"]:
        return -1.0

    return 1.0


def _momentum_score_from_returns(
    ticker: str,
    r1: Optional[float],
    r5: Optional[float],
    r20: Optional[float],
    vol20: Optional[float],
) -> float:
    """
    Score directionnel descriptif.
    Plus haut = momentum plus favorable au tape risk-on.

    Ne modifie aucun score macro/options/gamma existant.
    """
    sign = _momentum_role_sign(ticker)

    x1 = safe_float(r1, 0.0) or 0.0
    x5 = safe_float(r5, 0.0) or 0.0
    x20 = safe_float(r20, 0.0) or 0.0

    # Momentum multi-horizon.
    directional_move = sign * (
        0.25 * x1
        + 0.35 * x5
        + 0.40 * x20
    )

    score = 50.0 + directional_move * 520.0

    # Petit bonus si les 3 horizons sont alignés.
    signed_moves = [sign * x for x in [x1, x5, x20]]
    support_count = sum(1 for x in signed_moves if x > 0)
    pressure_count = sum(1 for x in signed_moves if x < 0)

    if support_count == 3:
        score += 8.0
    elif support_count == 2:
        score += 3.0

    if pressure_count == 3:
        score -= 8.0
    elif pressure_count == 2:
        score -= 3.0

    # Pénalité douce si volatilité 20D très élevée : momentum moins propre.
    v = safe_float(vol20)

    if v is not None and v > 0.45:
        score -= min(10.0, (v - 0.45) * 35.0)

    return clamp(score)


def _momentum_regime(score: Any) -> str:
    s = safe_float(score, 50.0) or 50.0

    if s >= 75:
        return "Momentum fort"
    if s >= 58:
        return "Support momentum"
    if s <= 35:
        return "Pression forte"
    if s <= 42:
        return "Pression momentum"

    return "Neutre"


def _momentum_proxy_lecture(row: pd.Series) -> str:
    ticker = str(row.get("Ticker", "N/A"))
    family = str(row.get("Family", "N/A"))
    regime = str(row.get("Regime", "N/A"))
    r1 = row.get("1D")
    r5 = row.get("5D")
    r20 = row.get("20D")

    perf_txt = f"1D {fmt_signed_pct(r1)}, 5D {fmt_signed_pct(r5)}, 20D {fmt_signed_pct(r20)}"

    if regime in ["Momentum fort", "Support momentum"]:
        return f"{ticker} confirme le momentum {family}. {perf_txt}."

    if regime in ["Pression forte", "Pression momentum"]:
        return f"{ticker} contredit le tape momentum {family}. {perf_txt}."

    return f"{ticker} neutre ou mixte sur momentum. {perf_txt}."


def build_futures_momentum_confirmation(
    macro_df: pd.DataFrame,
    macro_summary: Optional[Dict[str, Any]] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Futures Momentum / Trend Confirmation.

    Objectif :
    - séparer la confirmation momentum court/moyen terme du simple niveau de tape macro ;
    - lire 1D / 5D / 20D / vol 20D par famille ;
    - ne modifier aucun score options, gamma, greeks, macro ou decision gate.
    """
    macro_summary = macro_summary or {}

    empty_summary = {
        "momentum_state": "Indisponible",
        "momentum_score": None,
        "primary_trend": "N/A",
        "weakest_trend": "N/A",
        "support_count": 0,
        "pressure_count": 0,
        "neutral_count": 0,
        "alignment_score": None,
        "message": "Momentum futures indisponible.",
        "family_decomp": pd.DataFrame(),
    }

    if macro_df is None or macro_df.empty:
        return pd.DataFrame(), empty_summary

    required = ["Ticker", "1D", "5D", "20D"]

    if any(c not in macro_df.columns for c in required):
        return pd.DataFrame(), empty_summary

    df = macro_df.copy()

    for col in ["1D", "5D", "20D", "Vol 20D", "Beta ticker", "Corr"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    rows = []

    for _, row in df.iterrows():
        ticker = str(row.get("Ticker", "")).upper().strip()

        if not ticker:
            continue

        family = _momentum_family(row)
        score = _momentum_score_from_returns(
            ticker=ticker,
            r1=row.get("1D"),
            r5=row.get("5D"),
            r20=row.get("20D"),
            vol20=row.get("Vol 20D"),
        )

        sign = _momentum_role_sign(ticker)
        signed_moves = [
            sign * (safe_float(row.get("1D"), 0.0) or 0.0),
            sign * (safe_float(row.get("5D"), 0.0) or 0.0),
            sign * (safe_float(row.get("20D"), 0.0) or 0.0),
        ]

        support_horizons = int(sum(1 for x in signed_moves if x > 0))
        pressure_horizons = int(sum(1 for x in signed_moves if x < 0))

        acceleration = None
        r5 = safe_float(row.get("5D"))
        r20 = safe_float(row.get("20D"))

        if r5 is not None and r20 is not None:
            acceleration = sign * (r5 - r20 / 4.0)

        regime = _momentum_regime(score)

        rows.append({
            "Family": family,
            "_family_order": _momentum_family_order(family),
            "Ticker": ticker,
            "Instrument": row.get("Instrument", ticker),
            "Role sign": sign,
            "1D": row.get("1D"),
            "5D": row.get("5D"),
            "20D": row.get("20D"),
            "Vol 20D": row.get("Vol 20D"),
            "Beta ticker": row.get("Beta ticker"),
            "Corr": row.get("Corr"),
            "Momentum score num": score,
            "Momentum score": fmt_score(score),
            "Regime": regime,
            "Support horizons": support_horizons,
            "Pressure horizons": pressure_horizons,
            "Acceleration proxy": acceleration,
        })

    out = pd.DataFrame(rows)

    if out.empty:
        return pd.DataFrame(), empty_summary

    out["Lecture"] = out.apply(_momentum_proxy_lecture, axis=1)

    family_rows = []

    for family, g in out.groupby("Family"):
        scores = pd.to_numeric(g["Momentum score num"], errors="coerce").dropna()

        if scores.empty:
            continue

        score_num = safe_float(scores.median(), 50.0) or 50.0

        support_proxies = int(g["Regime"].isin(["Momentum fort", "Support momentum"]).sum())
        pressure_proxies = int(g["Regime"].isin(["Pression forte", "Pression momentum"]).sum())
        neutral_proxies = int(g["Regime"].eq("Neutre").sum())

        tickers = ", ".join(g["Ticker"].astype(str).tolist())

        family_rows.append({
            "Family": family,
            "_order": _momentum_family_order(family),
            "Tickers": tickers,
            "Proxy count": int(len(g)),
            "Score num": score_num,
            "Score": fmt_score(score_num),
            "Regime": _momentum_regime(score_num),
            "Support proxies": support_proxies,
            "Pressure proxies": pressure_proxies,
            "Neutral proxies": neutral_proxies,
            "Median 1D": safe_float(pd.to_numeric(g["1D"], errors="coerce").median()),
            "Median 5D": safe_float(pd.to_numeric(g["5D"], errors="coerce").median()),
            "Median 20D": safe_float(pd.to_numeric(g["20D"], errors="coerce").median()),
            "Median vol 20D": safe_float(pd.to_numeric(g["Vol 20D"], errors="coerce").median()),
            "Median beta": safe_float(pd.to_numeric(g["Beta ticker"], errors="coerce").median()),
            "Median corr": safe_float(pd.to_numeric(g["Corr"], errors="coerce").median()),
        })

    family_decomp = pd.DataFrame(family_rows)

    if family_decomp.empty:
        return out, empty_summary

    family_weights = {
        "Equity futures": 1.25,
        "Equity ETF": 1.00,
        "Semis / leadership": 1.15,
        "Volatility": 1.10,
        "Rates": 0.95,
        "Dollar / FX": 0.95,
        "Commodities": 0.75,
        "Other futures": 0.75,
        "Other": 0.50,
    }

    family_decomp["Weight"] = family_decomp["Family"].map(
        lambda x: family_weights.get(str(x), 0.50)
    )

    family_decomp["Weighted score"] = family_decomp["Score num"] * family_decomp["Weight"]

    total_weight = safe_float(family_decomp["Weight"].sum(), 0.0) or 0.0

    if total_weight > 0:
        momentum_score = safe_float(
            family_decomp["Weighted score"].sum() / total_weight,
            50.0,
        ) or 50.0
    else:
        momentum_score = safe_float(family_decomp["Score num"].mean(), 50.0) or 50.0

    support_count = int(family_decomp["Regime"].isin(["Momentum fort", "Support momentum"]).sum())
    pressure_count = int(family_decomp["Regime"].isin(["Pression forte", "Pression momentum"]).sum())
    neutral_count = int(family_decomp["Regime"].eq("Neutre").sum())

    total_families = max(int(len(family_decomp)), 1)
    alignment_score = clamp((support_count / total_families) * 100.0)

    primary_trend = str(
        family_decomp.sort_values("Score num", ascending=False).iloc[0].get("Family", "N/A")
    )

    weakest_trend = str(
        family_decomp.sort_values("Score num", ascending=True).iloc[0].get("Family", "N/A")
    )

    if momentum_score >= 72 and pressure_count == 0 and support_count >= 3:
        momentum_state = "Momentum confirmé"
        message = "Momentum futures/macro confirmé : plusieurs familles progressent dans le même sens."

    elif momentum_score >= 58 and pressure_count <= 1:
        momentum_state = "Momentum constructif"
        message = "Momentum constructif : le tape est soutenu, mais l'alignement reste partiel."

    elif pressure_count >= 2 and support_count >= 2:
        momentum_state = "Momentum divergent"
        message = "Momentum divergent : certaines familles confirment le tape, d'autres le contredisent."

    elif momentum_score <= 42:
        momentum_state = "Momentum défavorable"
        message = "Momentum défavorable : les proxies futures/macro pèsent sur le tape."

    else:
        momentum_state = "Momentum mixte"
        message = "Momentum mixte : pas de confirmation directionnelle nette par les futures/proxies."

    family_decomp["Lecture"] = family_decomp.apply(
        lambda r: (
            "Famille momentum dominante."
            if str(r.get("Family")) == primary_trend
            else "Famille momentum la plus faible."
            if str(r.get("Family")) == weakest_trend
            else "Famille contributive ou neutre dans le momentum."
        ),
        axis=1,
    )

    family_decomp = family_decomp.sort_values("_order").reset_index(drop=True)

    summary = {
        "momentum_state": momentum_state,
        "momentum_score": clamp(momentum_score),
        "primary_trend": primary_trend,
        "weakest_trend": weakest_trend,
        "support_count": support_count,
        "pressure_count": pressure_count,
        "neutral_count": neutral_count,
        "alignment_score": alignment_score,
        "message": message,
        "family_decomp": family_decomp,
    }

    out = out.sort_values(["_family_order", "Momentum score num"], ascending=[True, False]).reset_index(drop=True)

    return out, summary


def render_futures_momentum_confirmation(
    macro_df: pd.DataFrame,
    macro_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Affichage Futures Momentum / Trend Confirmation.
    À placer dans Futures Tape après Futures Divergence / Leadership Monitor.
    """
    st.subheader("Futures Momentum / Trend Confirmation")

    momentum_df, summary = build_futures_momentum_confirmation(
        macro_df=macro_df,
        macro_summary=macro_summary,
    )

    if momentum_df is None or momentum_df.empty:
        st.info("Momentum futures indisponible : données macro/futures insuffisantes.")
        return summary

    render_card_grid([
        (
            "Momentum state",
            str(summary.get("momentum_state", "N/A")),
            fmt_score(summary.get("momentum_score")),
        ),
        (
            "Primary trend",
            str(summary.get("primary_trend", "N/A")),
            "Famille dominante",
        ),
        (
            "Breadth",
            f"{fmt_int(summary.get('support_count'))} support / {fmt_int(summary.get('pressure_count'))} pression",
            f"{fmt_int(summary.get('neutral_count'))} neutre",
        ),
        (
            "Alignment",
            fmt_score(summary.get("alignment_score")),
            "Familles en support",
        ),
    ])

    score = safe_float(summary.get("momentum_score"), 50.0) or 50.0
    state = str(summary.get("momentum_state", ""))

    if state in ["Momentum défavorable", "Momentum divergent"]:
        alert_by_score(str(summary.get("message", "Momentum futures divergent.")), 72.0)
    elif score >= 58:
        alert_by_score(str(summary.get("message", "Momentum futures constructif.")), 35.0)
    else:
        alert_by_score(str(summary.get("message", "Momentum futures mixte.")), 55.0)

    family_decomp = summary.get("family_decomp", pd.DataFrame())

    if isinstance(family_decomp, pd.DataFrame) and not family_decomp.empty:
        plot_df = family_decomp.copy()
        plot_df["Score num"] = pd.to_numeric(plot_df["Score num"], errors="coerce")
        plot_df = plot_df.dropna(subset=["Score num"]).sort_values("_order")

        if not plot_df.empty:
            fig = go.Figure()

            fig.add_trace(
                go.Bar(
                    x=plot_df["Family"],
                    y=plot_df["Score num"],
                    name="Momentum score",
                    hovertemplate=(
                        "%{x}<br>"
                        "Score %{y:.0f}/100"
                        "<extra></extra>"
                    ),
                )
            )

            fig.add_hline(y=50, line_dash="dash", line_color="white")
            fig.add_hline(y=58, line_dash="dot", line_color="rgba(120,180,255,.65)")
            fig.add_hline(y=42, line_dash="dot", line_color="rgba(255,180,120,.65)")

            fig.update_layout(
                title="Futures momentum confirmation — score par famille",
                xaxis_title="Famille",
                yaxis_title="Score",
            )

            fig.update_yaxes(range=[0, 100])

            st.plotly_chart(apply_dark_layout(fig, 430), width="stretch")

        family_display = family_decomp.copy()

        for col in ["Median 1D", "Median 5D", "Median 20D", "Median vol 20D"]:
            if col in family_display.columns:
                family_display[col] = family_display[col].map(fmt_signed_pct if col != "Median vol 20D" else fmt_pct)

        for col in ["Median beta", "Median corr", "Weight", "Weighted score"]:
            if col in family_display.columns:
                family_display[col] = family_display[col].map(lambda x: fmt_num(x, 2))

        family_cols = [
            "Family",
            "Tickers",
            "Proxy count",
            "Score",
            "Regime",
            "Support proxies",
            "Pressure proxies",
            "Neutral proxies",
            "Median 1D",
            "Median 5D",
            "Median 20D",
            "Median vol 20D",
            "Median beta",
            "Median corr",
            "Lecture",
        ]

        st.dataframe(
            family_display[[c for c in family_cols if c in family_display.columns]],
            width="stretch",
            hide_index=True,
        )

    detail = momentum_df.copy()

    display_cols = [
        "Family",
        "Ticker",
        "Instrument",
        "Momentum score",
        "Regime",
        "1D",
        "5D",
        "20D",
        "Vol 20D",
        "Beta ticker",
        "Corr",
        "Support horizons",
        "Pressure horizons",
        "Acceleration proxy",
        "Lecture",
    ]

    detail = detail[[c for c in display_cols if c in detail.columns]].copy()

    for col in ["1D", "5D", "20D", "Acceleration proxy"]:
        if col in detail.columns:
            detail[col] = detail[col].map(fmt_signed_pct)

    if "Vol 20D" in detail.columns:
        detail["Vol 20D"] = detail["Vol 20D"].map(fmt_pct)

    for col in ["Beta ticker", "Corr"]:
        if col in detail.columns:
            detail[col] = detail[col].map(lambda x: fmt_num(x, 2))

    with st.expander("Voir proxies momentum détaillés", expanded=False):
        st.dataframe(
            detail,
            width="stretch",
            hide_index=True,
        )

    st.caption(
        "Futures Momentum / Trend Confirmation = lecture mécanique des rendements 1D/5D/20D, "
        "volatilité 20D, beta et corrélation des futures/proxies déjà chargés. "
        "Ce bloc ne modifie aucun score options, gamma, greeks, macro ou decision gate."
    )

    return summary



# ============================================================
# Export
# ============================================================


def build_export_df(ticker: str, expiration: str, metrics: Dict[str, Any], macro_summary: Dict[str, Any], macro_df: pd.DataFrame) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []

    def add(section: str, item: str, metric_1: Any = "", metric_2: Any = "", metric_3: Any = "", metric_4: Any = "", lecture: str = "") -> None:
        rows.append({
            "section": section,
            "item": item,
            "metric_1": metric_1,
            "metric_2": metric_2,
            "metric_3": metric_3,
            "metric_4": metric_4,
            "lecture": lecture,
        })

    add("metadata", "ticker", ticker)
    add("metadata", "expiration", expiration, f"DTE {metrics.get('dte')}")
    add("metadata", "spot", fmt_price(metrics.get("spot")))

    add("executive", "options_state", metrics.get("options_state"), fmt_score(metrics.get("options_risk_score")), lecture=metrics.get("state_reason", ""))
    add("executive", "confidence", metrics.get("confidence_label"), fmt_score(metrics.get("confidence")))
    add("volatility", "atm_iv", fmt_pct(metrics.get("atm_iv")), "RV20 " + fmt_pct(metrics.get("rv20")), "premium " + fmt_pct(metrics.get("iv_premium_20")))
    add("volatility", "expected_move", fmt_pct(metrics.get("expected_move_pct")), fmt_price(metrics.get("expected_move_price")))
    add("positioning", "put_call", "PCR vol " + fmt_num(metrics.get("pcr_vol")), "PCR OI " + fmt_num(metrics.get("pcr_oi")))
    add("walls", "call_wall", fmt_price(metrics.get("call_wall")))
    add("walls", "put_wall", fmt_price(metrics.get("put_wall")))
    add("walls", "max_pain", fmt_price(metrics.get("max_pain")))
    add("gamma", "net_gex_proxy", fmt_large(metrics.get("net_gex")), "gamma_flip " + fmt_price(metrics.get("gamma_flip")))
    add("macro", "tape_state", macro_summary.get("tape_state"), fmt_score(macro_summary.get("tape_score")), lecture=macro_summary.get("message", ""))

    if macro_df is not None and not macro_df.empty:
        for _, row in macro_df.iterrows():
            add(
                "macro_proxy",
                str(row.get("Ticker", "")),
                fmt_signed_pct(row.get("1D")),
                fmt_signed_pct(row.get("5D")),
                "beta " + fmt_num(row.get("Beta ticker")),
                str(row.get("Regime", "")),
                str(row.get("Lecture", "")),
            )

    return pd.DataFrame(rows)



# ============================================================
# Derivatives Execution Playbook
# ============================================================

def _nearest_derivative_level(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """
    Trouve le niveau dérivé le plus proche du spot parmi :
    gamma flip, call wall, put wall, max pain.

    Pure lecture d'exécution :
    - pas de nouveau calcul de signal ;
    - ne modifie aucun score global ;
    - sert uniquement à identifier une zone sensible proche.
    """
    spot = safe_float(metrics.get("spot"))

    if spot is None or spot <= 0:
        return {
            "name": "N/A",
            "level": None,
            "distance": None,
        }

    candidates = []

    for name, key in [
        ("Gamma flip", "gamma_flip"),
        ("Call wall", "call_wall"),
        ("Put wall", "put_wall"),
        ("Max pain", "max_pain"),
    ]:
        level = safe_float(metrics.get(key))

        if level is None or level <= 0:
            continue

        distance = level / max(spot, _EPS) - 1.0

        candidates.append({
            "name": name,
            "level": level,
            "distance": distance,
            "abs_distance": abs(distance),
        })

    if not candidates:
        return {
            "name": "N/A",
            "level": None,
            "distance": None,
        }

    nearest = sorted(candidates, key=lambda x: x["abs_distance"])[0]

    return {
        "name": nearest.get("name", "N/A"),
        "level": nearest.get("level"),
        "distance": nearest.get("distance"),
    }


def build_derivatives_execution_playbook(
    metrics: Dict[str, Any],
    macro_summary: Dict[str, Any],
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Derivatives Execution Playbook.

    Objectif :
    - convertir les signaux options/futures existants en règles d'exécution ;
    - identifier les zones où il faut éviter de chase ;
    - qualifier taille, timing et confirmation macro.

    Important :
    - ne modifie aucun score existant ;
    - ne recalcule pas la surface ;
    - ne prétend pas mesurer le dealer flow réel.
    """
    nearest = _nearest_derivative_level(metrics)

    spot = safe_float(metrics.get("spot"))
    dte = safe_int(metrics.get("dte"))

    options_score = safe_float(metrics.get("options_risk_score"), 50.0) or 50.0
    gamma_score = safe_float(metrics.get("gamma_score"), 50.0) or 50.0
    iv_score = safe_float(metrics.get("iv_premium_score"), 50.0) or 50.0
    pcr_score = safe_float(metrics.get("pcr_score"), 50.0) or 50.0
    skew_score = safe_float(metrics.get("skew_score"), 50.0) or 50.0

    tape_score = safe_float(macro_summary.get("tape_score"), 50.0) or 50.0
    tape_state = str(macro_summary.get("tape_state", "N/A"))

    # Tape score élevé = soutien macro. Pour le risque d'exécution,
    # on inverse donc le score macro.
    macro_risk = clamp(100.0 - tape_score)

    if tape_state == "Risk-off":
        macro_risk = clamp(macro_risk + 12.0)

    nearest_distance = safe_float(nearest.get("distance"))

    if nearest_distance is None:
        level_score = 35.0
    else:
        abs_dist = abs(nearest_distance)

        if abs_dist <= 0.01:
            level_score = 100.0
        elif abs_dist <= 0.025:
            level_score = 75.0
        elif abs_dist <= 0.05:
            level_score = 50.0
        else:
            level_score = 25.0

    execution_score = clamp(
        0.28 * options_score
        + 0.24 * gamma_score
        + 0.16 * iv_score
        + 0.12 * max(pcr_score, skew_score)
        + 0.12 * macro_risk
        + 0.08 * level_score
    )

    # Ajustements d'exécution uniquement.
    if dte is not None and dte <= 2:
        execution_score = max(execution_score, 62.0)

    if gamma_score >= 75 and level_score >= 70:
        execution_score = max(execution_score, 70.0)

    execution_score = clamp(execution_score)

    if execution_score >= 80:
        execution_state = "Exécution très sensible"
        execution_mode = "Fractionner / attendre confirmation"
        sizing = "Réduite"
        message = (
            "Risque d'exécution élevé : éviter le chase, privilégier les limites, "
            "fractionner l'entrée et surveiller les niveaux dérivés proches."
        )
    elif execution_score >= 65:
        execution_state = "Exécution à surveiller"
        execution_mode = "Entrée progressive"
        sizing = "Progressive"
        message = (
            "Exécution sensible : les options/futures ne bloquent pas forcément le setup, "
            "mais le timing et les niveaux proches comptent."
        )
    elif execution_score >= 45:
        execution_state = "Exécution contrôlée"
        execution_mode = "Standard avec limites"
        sizing = "Normale contrôlée"
        message = (
            "Risque d'exécution modéré : utiliser des ordres limités et confirmer le tape, "
            "mais aucun blocage majeur n'est détecté."
        )
    else:
        execution_state = "Exécution fluide"
        execution_mode = "Standard"
        sizing = "Normale"
        message = (
            "Risque d'exécution contenu : pas de contrainte dérivée majeure détectée."
        )

    iv_premium = safe_float(metrics.get("iv_premium_20"))
    expected_move_pct = safe_float(metrics.get("expected_move_pct"))
    expected_move_price = safe_float(metrics.get("expected_move_price"))

    if iv_premium is not None and iv_premium >= 0.30:
        vol_discipline = "Éviter achat vol agressif"
        vol_lecture = "IV chère vs réalisé : préférer structures moins exposées à la compression de vol."
    elif iv_premium is not None and iv_premium <= -0.15:
        vol_discipline = "Vol relativement basse"
        vol_lecture = "IV sous réalisé : convexité potentiellement moins chère, mais à confirmer par liquidité."
    else:
        vol_discipline = "Discipline normale"
        vol_lecture = "Prime IV non extrême ou indisponible."

    if nearest_distance is not None and abs(nearest_distance) <= 0.015:
        level_lecture = (
            "Spot très proche d'un niveau dérivé : éviter les entrées impulsives exactement sur la zone."
        )
    elif nearest_distance is not None and abs(nearest_distance) <= 0.035:
        level_lecture = (
            "Niveau dérivé proche : surveiller réaction, pinning ou accélération autour de cette zone."
        )
    else:
        level_lecture = (
            "Aucun niveau dérivé majeur immédiatement collé au spot."
        )

    if tape_state == "Risk-off":
        macro_lecture = "Macro tape défavorable : confirmation futures prioritaire avant exécution."
    elif tape_state == "Risk-on":
        macro_lecture = "Macro tape favorable : contexte d'exécution plus porteur."
    else:
        macro_lecture = "Macro tape mixte : ne pas surpondérer le signal dérivé seul."

    rows = [
        {
            "Bloc": "Execution stance",
            "Valeur": f"{execution_state} · {fmt_score(execution_score)}",
            "Lecture": message,
        },
        {
            "Bloc": "Execution mode",
            "Valeur": execution_mode,
            "Lecture": "Mode indicatif pour gérer timing, slippage et risque de réaction autour des niveaux options.",
        },
        {
            "Bloc": "Position sizing",
            "Valeur": sizing,
            "Lecture": "Taille indicative selon sensibilité dérivée, gamma, niveau proche et tape macro.",
        },
        {
            "Bloc": "Nearest derivative level",
            "Valeur": f"{nearest.get('name', 'N/A')} · {fmt_price(nearest.get('level'))} · {fmt_signed_pct(nearest.get('distance'))}",
            "Lecture": level_lecture,
        },
        {
            "Bloc": "Gamma / pinning risk",
            "Valeur": f"Gamma score {fmt_score(gamma_score)}",
            "Lecture": "Plus le score gamma est élevé, plus les réactions autour des walls/flip peuvent influencer l'exécution.",
        },
        {
            "Bloc": "Volatility discipline",
            "Valeur": vol_discipline,
            "Lecture": vol_lecture,
        },
        {
            "Bloc": "Expected move context",
            "Valeur": f"{fmt_pct(expected_move_pct)} · ± {fmt_price(expected_move_price)}",
            "Lecture": "Bande indicative issue de l'ATM IV. Sur DTE court, à lire comme approximation.",
        },
        {
            "Bloc": "Macro confirmation",
            "Valeur": f"{tape_state} · {fmt_score(tape_score)}",
            "Lecture": macro_lecture,
        },
    ]

    summary = {
        "execution_state": execution_state,
        "execution_score": execution_score,
        "execution_mode": execution_mode,
        "sizing": sizing,
        "nearest_level_name": nearest.get("name"),
        "nearest_level": nearest.get("level"),
        "nearest_level_distance": nearest.get("distance"),
        "message": message,
    }

    return pd.DataFrame(rows), summary


def render_derivatives_execution_playbook(
    metrics: Dict[str, Any],
    macro_summary: Dict[str, Any],
) -> None:
    """
    Affichage du playbook d'exécution dérivés.
    À placer dans l'onglet Executive, après la Lecture synthétique.
    """
    st.subheader("Derivatives Execution Playbook")

    playbook_df, summary = build_derivatives_execution_playbook(
        metrics=metrics,
        macro_summary=macro_summary,
    )

    if playbook_df is None or playbook_df.empty:
        st.info("Execution Playbook indisponible : métriques options/futures insuffisantes.")
        return

    render_card_grid([
        (
            "Execution state",
            str(summary.get("execution_state", "N/A")),
            fmt_score(summary.get("execution_score")),
        ),
        (
            "Execution mode",
            str(summary.get("execution_mode", "N/A")),
            "Timing / slippage",
        ),
        (
            "Position sizing",
            str(summary.get("sizing", "N/A")),
            "Indicatif",
        ),
        (
            "Nearest level",
            fmt_price(summary.get("nearest_level")),
            str(summary.get("nearest_level_name", "N/A")) + " · " + fmt_signed_pct(summary.get("nearest_level_distance")),
        ),
    ])

    score = safe_float(summary.get("execution_score"), 50.0) or 50.0

    if score >= 75:
        st.warning(summary.get("message", "Risque d'exécution élevé."))
    elif score >= 55:
        st.info(summary.get("message", "Risque d'exécution à surveiller."))
    else:
        st.success(summary.get("message", "Risque d'exécution contenu."))

    st.dataframe(
        playbook_df,
        width="stretch",
        hide_index=True,
    )

    st.caption(
        "Execution Playbook = synthèse mécanique des métriques déjà calculées : IV, skew, put/call, gamma, niveaux dérivés et futures tape. "
        "Ce bloc ne modifie aucun score global et ne constitue pas une recommandation d'investissement."
    )



# ============================================================
# Global Derivatives Risk Overlay / Decision Gate
# ============================================================

def build_global_derivatives_decision_gate(
    metrics: Dict[str, Any],
    macro_summary: Dict[str, Any],
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Global Derivatives Risk Overlay / Decision Gate.

    Objectif :
    - synthétiser les signaux dérivés déjà calculés ;
    - donner un gate d'exécution : Clear / Controlled / Caution / Wait ;
    - ne pas modifier les scores existants ;
    - ne pas recalculer la surface ;
    - ne pas produire une recommandation d'investissement.

    Ce bloc est un overlay d'exécution, pas un moteur de décision autonome.
    """
    nearest = _nearest_derivative_level(metrics)

    playbook_df, playbook_summary = build_derivatives_execution_playbook(
        metrics=metrics,
        macro_summary=macro_summary,
    )

    options_score = safe_float(metrics.get("options_risk_score"), 50.0) or 50.0
    gamma_score = safe_float(metrics.get("gamma_score"), 50.0) or 50.0
    iv_score = safe_float(metrics.get("iv_premium_score"), 50.0) or 50.0
    pcr_score = safe_float(metrics.get("pcr_score"), 50.0) or 50.0
    skew_score = safe_float(metrics.get("skew_score"), 50.0) or 50.0
    confidence = safe_float(metrics.get("confidence"), 50.0) or 50.0
    dte = safe_int(metrics.get("dte"))

    tape_score = safe_float(macro_summary.get("tape_score"), 50.0) or 50.0
    tape_state = str(macro_summary.get("tape_state", "N/A"))

    execution_score = safe_float(
        playbook_summary.get("execution_score"),
        50.0,
    ) or 50.0

    nearest_distance = safe_float(nearest.get("distance"))

    if nearest_distance is None:
        level_score = 35.0
    else:
        abs_dist = abs(nearest_distance)

        if abs_dist <= 0.01:
            level_score = 100.0
        elif abs_dist <= 0.025:
            level_score = 78.0
        elif abs_dist <= 0.05:
            level_score = 55.0
        else:
            level_score = 25.0

    if dte is None:
        dte_risk = 45.0
    elif dte <= 1:
        dte_risk = 90.0
    elif dte <= 3:
        dte_risk = 78.0
    elif dte <= 7:
        dte_risk = 62.0
    elif dte <= 14:
        dte_risk = 45.0
    else:
        dte_risk = 30.0

    macro_risk = clamp(100.0 - tape_score)

    if tape_state == "Risk-off":
        macro_risk = clamp(macro_risk + 12.0)
    elif tape_state == "Risk-on":
        macro_risk = clamp(macro_risk - 6.0)

    skew_pcr_risk = max(pcr_score, skew_score)
    data_risk = clamp(100.0 - confidence)

    component_scores = {
        "Options tape": options_score,
        "Gamma / walls": gamma_score,
        "Execution": execution_score,
        "Macro tape": macro_risk,
        "Vol premium": iv_score,
        "Skew / PCR": skew_pcr_risk,
        "Nearest level": level_score,
        "Short DTE": dte_risk,
        "Data quality": data_risk,
    }

    gate_risk_score = clamp(
        0.20 * options_score
        + 0.18 * gamma_score
        + 0.16 * execution_score
        + 0.13 * macro_risk
        + 0.11 * iv_score
        + 0.09 * skew_pcr_risk
        + 0.07 * level_score
        + 0.04 * dte_risk
        + 0.02 * data_risk
    )

    primary_risk = max(
        component_scores.items(),
        key=lambda kv: safe_float(kv[1], 0.0) or 0.0,
    )[0]

    if confidence < 35:
        gate_state = "Data check"
        gate_action = "Attendre données propres"
        gate_mode = "No decision"
        sizing = "N/A"
        message = (
            "Decision Gate limité : la qualité ou la couverture des données est insuffisante. "
            "Vérifier la chaîne options, les spreads et la liquidité avant toute lecture."
        )
    elif gate_risk_score >= 78:
        gate_state = "Wait confirmation"
        gate_action = "Ne pas chaser"
        gate_mode = "Confirmation obligatoire"
        sizing = "Réduite / attente"
        message = (
            "Decision Gate restrictif : le risque dérivé ou macro est élevé. "
            "Attendre confirmation prix/tape et éviter les entrées impulsives autour des niveaux sensibles."
        )
    elif gate_risk_score >= 62:
        gate_state = "Caution"
        gate_action = "Entrée progressive"
        gate_mode = "Limites + confirmation"
        sizing = "Progressive"
        message = (
            "Decision Gate prudent : le setup n'est pas bloqué, mais plusieurs contraintes d'exécution existent. "
            "Favoriser une entrée progressive, avec niveaux et tape futures surveillés."
        )
    elif gate_risk_score >= 45:
        gate_state = "Controlled execution"
        gate_action = "Standard contrôlé"
        gate_mode = "Ordres limites"
        sizing = "Normale contrôlée"
        message = (
            "Decision Gate contrôlé : risque d'exécution modéré. "
            "Les dérivés ne bloquent pas le setup, mais les niveaux proches restent à respecter."
        )
    else:
        gate_state = "Clear execution"
        gate_action = "Standard"
        gate_mode = "Risque dérivé contenu"
        sizing = "Normale"
        message = (
            "Decision Gate fluide : pas de contrainte dérivée majeure détectée. "
            "La lecture reste dépendante du tape marché et de la liquidité."
        )

    if primary_risk == "Macro tape":
        confirmation = "Confirmation futures/proxies avant exécution."
    elif primary_risk in ["Gamma / walls", "Nearest level"]:
        confirmation = "Réaction claire autour du gamma flip, wall ou max pain."
    elif primary_risk == "Vol premium":
        confirmation = "Éviter achat vol agressif si l'IV reste chère."
    elif primary_risk == "Short DTE":
        confirmation = "Surveiller intraday : gamma/charm peuvent changer vite."
    elif primary_risk == "Data quality":
        confirmation = "Confirmer spreads, OI, volume et IV avant lecture."
    else:
        confirmation = "Confirmation prix + tape futures."

    rows = [
        {
            "Bloc": "Decision gate",
            "Score": fmt_score(gate_risk_score),
            "Signal": gate_state,
            "Lecture": message,
        },
        {
            "Bloc": "Primary risk driver",
            "Score": fmt_score(component_scores.get(primary_risk)),
            "Signal": primary_risk,
            "Lecture": "Composante qui pèse le plus dans le risque d'exécution agrégé.",
        },
        {
            "Bloc": "Execution action",
            "Score": fmt_score(execution_score),
            "Signal": gate_action,
            "Lecture": "Mode indicatif : timing, limites, fractionnement et discipline d'entrée.",
        },
        {
            "Bloc": "Position sizing",
            "Score": "N/A",
            "Signal": sizing,
            "Lecture": "Taille indicative issue du risque dérivé/macro. Ne remplace pas le risk management.",
        },
        {
            "Bloc": "Nearest derivative level",
            "Score": fmt_score(level_score),
            "Signal": f"{nearest.get('name', 'N/A')} · {fmt_price(nearest.get('level'))}",
            "Lecture": "Distance au niveau : " + fmt_signed_pct(nearest.get("distance")),
        },
        {
            "Bloc": "Macro confirmation",
            "Score": fmt_score(macro_risk),
            "Signal": tape_state,
            "Lecture": macro_summary.get("message", "Macro tape indisponible."),
        },
        {
            "Bloc": "Required confirmation",
            "Score": "N/A",
            "Signal": confirmation,
            "Lecture": "Condition de validation avant d'augmenter l'agressivité d'exécution.",
        },
    ]

    summary = {
        "gate_state": gate_state,
        "gate_risk_score": gate_risk_score,
        "gate_action": gate_action,
        "gate_mode": gate_mode,
        "sizing": sizing,
        "primary_risk": primary_risk,
        "nearest_level_name": nearest.get("name"),
        "nearest_level": nearest.get("level"),
        "nearest_level_distance": nearest.get("distance"),
        "confirmation": confirmation,
        "message": message,
    }

    return pd.DataFrame(rows), summary


def render_global_derivatives_decision_gate(
    metrics: Dict[str, Any],
    macro_summary: Dict[str, Any],
) -> None:
    """
    Affichage Global Derivatives Risk Overlay / Decision Gate.
    À placer dans l'onglet Executive, après le Derivatives Execution Playbook.
    """
    st.subheader("Global Derivatives Risk Overlay / Decision Gate")

    gate_df, summary = build_global_derivatives_decision_gate(
        metrics=metrics,
        macro_summary=macro_summary,
    )

    if gate_df is None or gate_df.empty:
        st.info("Decision Gate indisponible : métriques dérivées ou macro insuffisantes.")
        return

    render_card_grid([
        (
            "Decision gate",
            str(summary.get("gate_state", "N/A")),
            fmt_score(summary.get("gate_risk_score")),
        ),
        (
            "Action",
            str(summary.get("gate_action", "N/A")),
            str(summary.get("gate_mode", "N/A")),
        ),
        (
            "Primary risk",
            str(summary.get("primary_risk", "N/A")),
            str(summary.get("confirmation", "N/A")),
        ),
        (
            "Nearest level",
            fmt_price(summary.get("nearest_level")),
            str(summary.get("nearest_level_name", "N/A")) + " · " + fmt_signed_pct(summary.get("nearest_level_distance")),
        ),
    ])

    score = safe_float(summary.get("gate_risk_score"), 50.0) or 50.0

    if score >= 75:
        st.warning(summary.get("message", "Decision Gate restrictif."))
    elif score >= 55:
        st.info(summary.get("message", "Decision Gate à surveiller."))
    else:
        st.success(summary.get("message", "Decision Gate fluide."))

    st.dataframe(
        gate_df,
        width="stretch",
        hide_index=True,
    )

    st.caption(
        "Decision Gate = overlay mécanique d'exécution basé sur les scores déjà calculés : options risk, gamma, IV, skew/PCR, macro tape, DTE, niveau dérivé proche et qualité des données. "
        "Il ne modifie aucun score existant et ne constitue pas une recommandation d'investissement."
    )



# ============================================================
# Derivatives Audit Trail / Run Ledger
# ============================================================

def _audit_value_present(value: Any) -> bool:
    """
    Présence simple d'une donnée pour audit trail.
    Ne juge pas la qualité du signal, seulement la disponibilité.
    """
    if value is None:
        return False

    if isinstance(value, str):
        v = value.strip().lower()
        return v not in ["", "n/a", "nan", "none", "null"]

    if isinstance(value, (pd.Series, pd.DataFrame, list, tuple, dict)):
        try:
            return len(value) > 0
        except Exception:
            return False

    x = safe_float(value)
    if x is None:
        return True

    return np.isfinite(x)


def _audit_status_from_risk(score: Any) -> str:
    """
    Score élevé = risque élevé.
    Utilisé uniquement pour la lecture audit, pas pour recalculer un signal.
    """
    s = safe_float(score)

    if s is None:
        return "N/A"

    if s >= 75:
        return "High"
    if s >= 55:
        return "Watch"
    return "OK"


def _audit_status_from_quality(score: Any) -> str:
    """
    Score élevé = meilleure qualité.
    """
    s = safe_float(score)

    if s is None:
        return "N/A"

    if s >= 70:
        return "OK"
    if s >= 45:
        return "Watch"
    return "Low"


def build_derivatives_audit_trail(
    ticker: str,
    expiration: str,
    metrics: Dict[str, Any],
    macro_summary: Dict[str, Any],
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Derivatives Audit Trail / Run Ledger.

    Objectif :
    - tracer les données et signaux utilisés dans le module ;
    - rendre le diagnostic plus institutionnel ;
    - faciliter l'export / relecture / comparaison entre runs ;
    - ne modifier aucun score existant.

    Ce bloc est uniquement un registre d'audit.
    """

    metrics = metrics or {}
    macro_summary = macro_summary or {}

    try:
        gate_df, gate_summary = build_global_derivatives_decision_gate(
            metrics=metrics,
            macro_summary=macro_summary,
        )
    except Exception:
        gate_df, gate_summary = pd.DataFrame(), {}

    try:
        playbook_df, playbook_summary = build_derivatives_execution_playbook(
            metrics=metrics,
            macro_summary=macro_summary,
        )
    except Exception:
        playbook_df, playbook_summary = pd.DataFrame(), {}

    now_utc = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    core_fields = {
        "spot": metrics.get("spot"),
        "expiration": expiration,
        "dte": metrics.get("dte"),
        "atm_iv": metrics.get("atm_iv"),
        "rv20": metrics.get("rv20"),
        "expected_move_pct": metrics.get("expected_move_pct"),
        "pcr_vol": metrics.get("pcr_vol"),
        "pcr_oi": metrics.get("pcr_oi"),
        "gamma_score": metrics.get("gamma_score"),
        "options_risk_score": metrics.get("options_risk_score"),
        "confidence": metrics.get("confidence"),
        "macro_tape_score": macro_summary.get("tape_score"),
    }

    missing_fields = [
        k for k, v in core_fields.items()
        if not _audit_value_present(v)
    ]

    completeness_score = clamp(
        100.0 * (len(core_fields) - len(missing_fields)) / max(len(core_fields), 1)
    )

    if completeness_score >= 90:
        audit_state = "Run traçable"
    elif completeness_score >= 70:
        audit_state = "Run partiel"
    else:
        audit_state = "Run fragile"

    rows: List[Dict[str, Any]] = []

    def add(
        section: str,
        check: str,
        status: str,
        value: Any = "",
        evidence: str = "",
        action: str = "",
    ) -> None:
        rows.append({
            "Section": section,
            "Check": check,
            "Status": status,
            "Value": value,
            "Evidence": evidence,
            "Action": action,
        })

    # -----------------------------
    # Run metadata
    # -----------------------------
    add(
        "Run metadata",
        "Timestamp",
        "OK",
        now_utc,
        "Horodatage UTC du diagnostic.",
        "Permet de comparer plusieurs runs."
    )

    add(
        "Run metadata",
        "Ticker",
        "OK" if _audit_value_present(ticker) else "N/A",
        str(ticker).upper().strip(),
        "Sous-jacent analysé.",
        "Vérifier le ticker si les données sont vides."
    )

    add(
        "Run metadata",
        "Expiration sélectionnée",
        "OK" if _audit_value_present(expiration) else "N/A",
        str(expiration),
        "Expiration utilisée pour la chaîne options principale.",
        "Comparer avec les autres expirations dans la surface."
    )

    add(
        "Run metadata",
        "DTE",
        _audit_status_from_risk(70 if is_short_dte(metrics.get("dte"), threshold=3) else 25),
        fmt_int(metrics.get("dte")),
        "DTE court = greeks/charm/gamma plus instables.",
        "Sur DTE très court, privilégier lecture intraday et spreads."
    )

    # -----------------------------
    # Data quality
    # -----------------------------
    add(
        "Data quality",
        "Data completeness",
        _audit_status_from_quality(completeness_score),
        fmt_score(completeness_score),
        "Champs critiques disponibles : "
        + f"{len(core_fields) - len(missing_fields)} / {len(core_fields)}.",
        "Champs manquants : " + (", ".join(missing_fields) if missing_fields else "aucun")
    )

    add(
        "Data quality",
        "Options confidence",
        _audit_status_from_quality(metrics.get("confidence")),
        f"{metrics.get('confidence_label', 'N/A')} · {fmt_score(metrics.get('confidence'))}",
        "Score interne basé sur volume, OI, IV, DTE et spreads.",
        "Si faible, confirmer manuellement bid/ask, volume et OI."
    )

    add(
        "Data quality",
        "ATM IV / RV availability",
        "OK" if _audit_value_present(metrics.get("atm_iv")) and _audit_value_present(metrics.get("rv20")) else "Watch",
        f"ATM IV {fmt_pct(metrics.get('atm_iv'))} · RV20 {fmt_pct(metrics.get('rv20'))}",
        "Comparaison utilisée pour prime d'IV.",
        "Si RV ou IV absente, ne pas surpondérer la prime vol."
    )

    add(
        "Data quality",
        "Expected move availability",
        "OK" if _audit_value_present(metrics.get("expected_move_pct")) else "Watch",
        f"{fmt_pct(metrics.get('expected_move_pct'))} · ± {fmt_price(metrics.get('expected_move_price'))}",
        "Expected move proxy basé sur ATM IV.",
        "Sur DTE court, lecture indicative uniquement."
    )

    # -----------------------------
    # Signal stack
    # -----------------------------
    add(
        "Signal stack",
        "Options risk",
        _audit_status_from_risk(metrics.get("options_risk_score")),
        f"{metrics.get('options_state', 'N/A')} · {fmt_score(metrics.get('options_risk_score'))}",
        str(metrics.get("state_reason", "N/A")),
        "Ne pas utiliser isolément : croiser avec macro, gamma et qualité."
    )

    add(
        "Signal stack",
        "IV premium",
        _audit_status_from_risk(metrics.get("iv_premium_score")),
        f"Score {fmt_score(metrics.get('iv_premium_score'))} · Premium {fmt_pct(metrics.get('iv_premium_20'))}",
        f"ATM IV {fmt_pct(metrics.get('atm_iv'))} vs RV20 {fmt_pct(metrics.get('rv20'))}.",
        "Sur IV chère, éviter d'interpréter le signal comme directionnel."
    )

    add(
        "Signal stack",
        "Put/Call positioning",
        _audit_status_from_risk(metrics.get("pcr_score")),
        f"PCR vol {fmt_num(metrics.get('pcr_vol'))} · PCR OI {fmt_num(metrics.get('pcr_oi'))}",
        "Score positioning : " + fmt_score(metrics.get("pcr_score")),
        "Lire comme demande de protection / spéculation, pas comme certitude."
    )

    add(
        "Signal stack",
        "Skew",
        _audit_status_from_risk(metrics.get("skew_score")),
        f"Put wing {fmt_pct(metrics.get('put_wing_iv'))} · Call wing {fmt_pct(metrics.get('call_wing_iv'))}",
        "Skew 10% : " + fmt_pct(metrics.get("skew_10")),
        "Un skew défensif augmente la sensibilité downside, pas une prédiction."
    )

    add(
        "Signal stack",
        "Gamma / walls",
        _audit_status_from_risk(metrics.get("gamma_score")),
        f"Gamma score {fmt_score(metrics.get('gamma_score'))}",
        f"Net GEX {fmt_large(metrics.get('net_gex'))} · Flip {fmt_price(metrics.get('gamma_flip'))}",
        "Surveiller réaction autour des walls et gamma flip."
    )

    add(
        "Signal stack",
        "Macro tape",
        _audit_status_from_risk(100.0 - (safe_float(macro_summary.get("tape_score"), 50.0) or 50.0)),
        f"{macro_summary.get('tape_state', 'N/A')} · {fmt_score(macro_summary.get('tape_score'))}",
        str(macro_summary.get("message", "N/A")),
        "Si macro tape défavorable, ne pas surpondérer le signal options seul."
    )

    # -----------------------------
    # Decision / execution
    # -----------------------------
    add(
        "Decision overlay",
        "Decision gate",
        _audit_status_from_risk(gate_summary.get("gate_risk_score")),
        f"{gate_summary.get('gate_state', 'N/A')} · {fmt_score(gate_summary.get('gate_risk_score'))}",
        str(gate_summary.get("message", "N/A")),
        "Respecter le gate avant d'augmenter l'agressivité."
    )

    add(
        "Decision overlay",
        "Execution action",
        _audit_status_from_risk(playbook_summary.get("execution_score")),
        f"{gate_summary.get('gate_action', playbook_summary.get('execution_mode', 'N/A'))}",
        f"Mode {gate_summary.get('gate_mode', 'N/A')} · sizing {gate_summary.get('sizing', playbook_summary.get('sizing', 'N/A'))}",
        "Utiliser limites, fractionnement et confirmation prix."
    )

    add(
        "Decision overlay",
        "Primary risk driver",
        "Watch" if _audit_value_present(gate_summary.get("primary_risk")) else "N/A",
        str(gate_summary.get("primary_risk", "N/A")),
        "Driver principal extrait du Decision Gate.",
        "Traiter ce driver comme première contrainte d'exécution."
    )

    add(
        "Decision overlay",
        "Nearest derivative level",
        _audit_status_from_risk(
            78.0 if safe_float(gate_summary.get("nearest_level_distance")) is not None
            and abs(safe_float(gate_summary.get("nearest_level_distance")) or 0.0) <= 0.025
            else 35.0
        ),
        f"{gate_summary.get('nearest_level_name', 'N/A')} · {fmt_price(gate_summary.get('nearest_level'))}",
        "Distance : " + fmt_signed_pct(gate_summary.get("nearest_level_distance")),
        "Surveiller réaction autour du niveau avant d'accélérer l'exécution."
    )

    add(
        "Decision overlay",
        "Required confirmation",
        "Watch",
        str(gate_summary.get("confirmation", "N/A")),
        "Condition de validation issue du Decision Gate.",
        "Ne pas ignorer cette condition dans le plan d'entrée."
    )

    # -----------------------------
    # Execution checklist
    # -----------------------------
    add(
        "Execution checklist",
        "Market order discipline",
        "OK",
        "Ordre marché déconseillé",
        "Le module dérivés sert surtout à cadrer timing/slippage.",
        "Préférer ordres limites ou entrée fractionnée si niveau proche."
    )

    add(
        "Execution checklist",
        "Level reaction check",
        "Watch" if _audit_value_present(gate_summary.get("nearest_level")) else "N/A",
        f"Niveau proche {fmt_price(gate_summary.get('nearest_level'))}",
        str(gate_summary.get("nearest_level_name", "N/A")),
        "Attendre confirmation prix si le spot approche du niveau dérivé."
    )

    add(
        "Execution checklist",
        "Liquidity check",
        _audit_status_from_quality(metrics.get("confidence")),
        f"Call OI {fmt_int(metrics.get('call_oi'))} · Put OI {fmt_int(metrics.get('put_oi'))}",
        "OI et volume utilisés comme proxy de robustesse.",
        "Confirmer spreads sur la chaîne avant toute lecture fine."
    )

    audit_df = pd.DataFrame(rows)

    status_counts = (
        audit_df["Status"]
        .astype(str)
        .value_counts()
        .to_dict()
        if not audit_df.empty and "Status" in audit_df.columns
        else {}
    )

    summary = {
        "audit_state": audit_state,
        "audit_score": completeness_score,
        "missing_fields": missing_fields,
        "missing_count": len(missing_fields),
        "watch_count": int(status_counts.get("Watch", 0)),
        "high_count": int(status_counts.get("High", 0)),
        "low_count": int(status_counts.get("Low", 0)),
        "gate_state": gate_summary.get("gate_state", "N/A"),
        "gate_action": gate_summary.get("gate_action", "N/A"),
        "primary_risk": gate_summary.get("primary_risk", "N/A"),
    }

    return audit_df, summary


def render_derivatives_audit_trail(
    ticker: str,
    expiration: str,
    metrics: Dict[str, Any],
    macro_summary: Dict[str, Any],
) -> None:
    """
    Affichage Derivatives Audit Trail / Run Ledger.
    À placer dans l'onglet Executive, sous le Decision Gate.
    """
    st.subheader("Derivatives Audit Trail / Run Ledger")

    audit_df, summary = build_derivatives_audit_trail(
        ticker=ticker,
        expiration=expiration,
        metrics=metrics,
        macro_summary=macro_summary,
    )

    if audit_df is None or audit_df.empty:
        st.info("Audit trail indisponible : données insuffisantes.")
        return

    render_card_grid([
        (
            "Audit state",
            str(summary.get("audit_state", "N/A")),
            fmt_score(summary.get("audit_score")),
        ),
        (
            "Decision gate",
            str(summary.get("gate_state", "N/A")),
            str(summary.get("gate_action", "N/A")),
        ),
        (
            "Primary risk",
            str(summary.get("primary_risk", "N/A")),
            f"Watch {fmt_int(summary.get('watch_count'))} · High {fmt_int(summary.get('high_count'))}",
        ),
        (
            "Missing fields",
            fmt_int(summary.get("missing_count")),
            ", ".join(summary.get("missing_fields", [])[:3]) if summary.get("missing_fields") else "Aucun champ critique manquant",
        ),
    ])

    audit_score = safe_float(summary.get("audit_score"), 100.0) or 100.0

    if audit_score < 70:
        st.warning(
            "Audit trail partiel : certains champs critiques sont absents. "
            "Le diagnostic reste lisible, mais l'export doit être interprété avec réserve."
        )
    elif safe_int(summary.get("high_count"), 0) and safe_int(summary.get("high_count"), 0) > 0:
        st.info(
            "Audit trail complet : un ou plusieurs risques élevés sont identifiés, "
            "mais ils sont tracés et reliés à une action d'exécution."
        )
    else:
        st.success(
            "Audit trail complet : données principales disponibles et diagnostic traçable."
        )

    st.dataframe(
        audit_df,
        width="stretch",
        hide_index=True,
    )

    csv = audit_df.to_csv(index=False).encode("utf-8")

    st.download_button(
        "Télécharger audit trail CSV",
        data=csv,
        file_name=f"derivatives_audit_trail_{str(ticker).upper()}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
        key=f"download_derivatives_audit_trail_{str(ticker).upper()}_{str(expiration)}",
    )

    st.caption(
        "Audit Trail = registre mécanique des données, scores, checks et conditions d'exécution. "
        "Il ne recalcule aucun signal, ne modifie aucun score existant et sert uniquement à la traçabilité du run."
    )



# ============================================================
# Tabs
# ============================================================


def render_executive_tab(ticker: str, expiration: str, metrics: Dict[str, Any], macro_summary: Dict[str, Any]) -> None:
    st.subheader("Executive Derivatives Ticket")

    cards = [
        ("Options state", str(metrics.get("options_state", "N/A")), fmt_score(metrics.get("options_risk_score"))),
        ("ATM IV", fmt_pct(metrics.get("atm_iv")), "RV20 " + fmt_pct(metrics.get("rv20"))),
        ("Expected move", fmt_pct(metrics.get("expected_move_pct")), "± " + fmt_price(metrics.get("expected_move_price"))),
        ("Put/Call vol", fmt_num(metrics.get("pcr_vol")), "OI " + fmt_num(metrics.get("pcr_oi"))),
        ("Call / Put wall", f"{fmt_price(metrics.get('call_wall'))} / {fmt_price(metrics.get('put_wall'))}", "Max pain " + fmt_price(metrics.get("max_pain"))),
        ("Futures tape", str(macro_summary.get("tape_state", "N/A")), fmt_score(macro_summary.get("tape_score"))),
    ]
    render_card_grid(cards)

    alert_by_score(str(metrics.get("state_reason", "Lecture options indisponible.")), safe_float(metrics.get("options_risk_score"), 50) or 50)
    st.caption(
        f"Ticker {ticker} · Expiration {expiration} · DTE {metrics.get('dte')} · "
        f"Confiance {metrics.get('confidence_label')} ({fmt_score(metrics.get('confidence'))}) · "
        "Données options publiques yfinance."
    )

    st.subheader("Lecture synthétique")
    df = pd.DataFrame([
        {
            "Bloc": "Volatility premium",
            "Valeur": f"ATM IV {fmt_pct(metrics.get('atm_iv'))} · RV20 {fmt_pct(metrics.get('rv20'))}",
            "Score": fmt_score(metrics.get("iv_premium_score")),
            "Lecture": "IV chère vs réalisé." if safe_float(metrics.get("iv_premium_20"), 0) and safe_float(metrics.get("iv_premium_20"), 0) > 0.25 else "Prime IV non extrême ou indisponible.",
        },
        {
            "Bloc": "Options positioning",
            "Valeur": f"PCR vol {fmt_num(metrics.get('pcr_vol'))} · PCR OI {fmt_num(metrics.get('pcr_oi'))}",
            "Score": fmt_score(metrics.get("pcr_score")),
            "Lecture": "Demande de puts élevée." if safe_float(metrics.get("pcr_vol"), 0) and safe_float(metrics.get("pcr_vol"), 0) > 1.0 else "Positionnement non excessivement défensif.",
        },
        {
            "Bloc": "Skew",
            "Valeur": f"Put wing {fmt_pct(metrics.get('put_wing_iv'))} · Call wing {fmt_pct(metrics.get('call_wing_iv'))}",
            "Score": fmt_score(metrics.get("skew_score")),
            "Lecture": "Skew défensif." if safe_float(metrics.get("skew_10"), 0) and safe_float(metrics.get("skew_10"), 0) > 0.06 else "Skew contenu ou symétrique.",
        },
        {
            "Bloc": "Gamma / walls",
            "Valeur": f"Net GEX {fmt_large(metrics.get('net_gex'))} · flip {fmt_price(metrics.get('gamma_flip'))}",
            "Score": fmt_score(metrics.get("gamma_score")),
            "Lecture": "Concentration OI/gamma à surveiller." if safe_float(metrics.get("gamma_score"), 0) and safe_float(metrics.get("gamma_score"), 0) > 60 else "Gamma proxy non bloquant.",
        },
        {
            "Bloc": "Futures tape",
            "Valeur": f"{macro_summary.get('tape_state', 'N/A')} · {fmt_score(macro_summary.get('tape_score'))}",
            "Score": fmt_score(macro_summary.get("tape_score")),
            "Lecture": macro_summary.get("message", ""),
        },
    ])
    st.dataframe(df, width="stretch", hide_index=True)

    render_derivatives_execution_playbook(metrics, macro_summary)

    render_global_derivatives_decision_gate(metrics, macro_summary)

    render_derivatives_audit_trail(ticker, expiration, metrics, macro_summary)


def render_options_surface_tab(ticker: str, calls: pd.DataFrame, puts: pd.DataFrame, surface: pd.DataFrame, spot: float, expiration: str, window_pct: float) -> None:
    st.subheader("Options Chain / Surface")

    merged = merge_chain_for_display(calls, puts, spot, window_pct)

    if merged.empty:
        st.warning("Chaîne options vide ou hors fenêtre.")
    else:
        show_cols = [
            "strike", "distance_spot",
            "call_bid", "call_ask", "call_mid", "call_vol", "call_oi", "call_iv", "call_delta",
            "put_bid", "put_ask", "put_mid", "put_vol", "put_oi", "put_iv", "put_delta",
        ]
        st.dataframe(
            format_display_df(merged[[c for c in show_cols if c in merged.columns]]),
            width="stretch",
            hide_index=True,
        )

    
    render_surface_integrity_diagnostics(surface, spot, window_pct)

    # Nouveau bloc institutionnel : vraie surface IV 3D multi-expirations.
    render_iv_surface_3d(surface, spot, window_pct)

    st.subheader("Volatility Smile")
    render_iv_smile(calls, puts, spot, f"IV smile — {expiration}")

    st.subheader("Term Structure")
    term = compute_term_structure(surface, spot)

    if not term.empty:
        st.dataframe(format_display_df(term), width="stretch", hide_index=True)

    render_term_structure_chart(term)

    # Nouveau bloc institutionnel prudent :
    # lecture de la forward variance entre expirations adjacentes.
    render_forward_variance_diagnostics(term)

    # Nouveau bloc prudent :
    # rapproche forward variance et calendrier earnings/public events.
    render_event_vol_premium_diagnostics(ticker, term)


def render_oi_tab(calls: pd.DataFrame, puts: pd.DataFrame, spot: float, metrics: Dict[str, Any], window_pct: float) -> None:
    st.subheader("Open Interest / Walls")
    cards = [
        ("Call wall", fmt_price(metrics.get("call_wall")), "Plus gros call OI"),
        ("Put wall", fmt_price(metrics.get("put_wall")), "Plus gros put OI"),
        ("Max pain", fmt_price(metrics.get("max_pain")), "Payout min indicatif"),
        ("Total call OI", fmt_int(metrics.get("call_oi")), "Contrats"),
        ("Total put OI", fmt_int(metrics.get("put_oi")), "Contrats"),
    ]
    render_card_grid(cards)

    render_oi_chart(calls, puts, spot, window_pct)

    render_wall_pinning_diagnostics(calls, puts, spot, metrics, window_pct)

    top_rows = []
    if calls is not None and not calls.empty:
        c = calls.copy()
        c["openInterest"] = pd.to_numeric(c.get("openInterest", 0), errors="coerce").fillna(0)
        for _, r in c.nlargest(8, "openInterest").iterrows():
            top_rows.append({"Type": "Call", "Strike": r.get("strike"), "OI": r.get("openInterest"), "Volume": r.get("volume"), "IV": r.get("iv"), "Distance spot": r.get("distance_spot")})
    if puts is not None and not puts.empty:
        p = puts.copy()
        p["openInterest"] = pd.to_numeric(p.get("openInterest", 0), errors="coerce").fillna(0)
        for _, r in p.nlargest(8, "openInterest").iterrows():
            top_rows.append({"Type": "Put", "Strike": r.get("strike"), "OI": r.get("openInterest"), "Volume": r.get("volume"), "IV": r.get("iv"), "Distance spot": r.get("distance_spot")})
    if top_rows:
        st.subheader("Top OI strikes")
        st.dataframe(format_display_df(pd.DataFrame(top_rows)), width="stretch", hide_index=True)

    st.subheader("Max Pain")
    render_max_pain_chart(metrics.get("max_pain_df", pd.DataFrame()), metrics.get("max_pain"), spot)
    st.caption("Max pain = diagnostic mécanique basé sur OI actuel, pas une prédiction de clôture.")


def render_volatility_tab(metrics: Dict[str, Any], calls: pd.DataFrame, puts: pd.DataFrame, spot: float, expiration: str) -> None:
    st.subheader("Volatility / Skew Diagnostics")
    cards = [
        ("ATM IV", fmt_pct(metrics.get("atm_iv")), "Call " + fmt_pct(metrics.get("atm_call_iv")) + " · Put " + fmt_pct(metrics.get("atm_put_iv"))),
        ("RV20 / RV60", f"{fmt_pct(metrics.get('rv20'))} / {fmt_pct(metrics.get('rv60'))}", "RV90 " + fmt_pct(metrics.get("rv90"))),
        ("IV premium", fmt_pct(metrics.get("iv_premium_20")), "ATM IV vs RV20"),
        ("10% put-call skew", fmt_pct(metrics.get("skew_10")), "Put wing - Call wing"),
        ("Expected move", fmt_pct(metrics.get("expected_move_pct")), "± " + fmt_price(metrics.get("expected_move_price"))),
    ]
    render_card_grid(cards)
    alert_by_score(
        "Prime de volatilité élevée : attention à payer trop cher la convexité." if safe_float(metrics.get("iv_premium_20"), 0) and safe_float(metrics.get("iv_premium_20"), 0) > 0.35 else "Volatilité implicite non extrême vs réalisé, lecture à confirmer avec la liquidité.",
        safe_float(metrics.get("iv_premium_score"), 50) or 50,
    )
    render_iv_smile(calls, puts, spot, f"Smile / Skew — {expiration}")

    rows = pd.DataFrame([
        {"Métrique": "ATM IV", "Valeur": fmt_pct(metrics.get("atm_iv")), "Lecture": "Volatilité implicite proche du spot."},
        {"Métrique": "RV20", "Valeur": fmt_pct(metrics.get("rv20")), "Lecture": "Volatilité réalisée 20 jours."},
        {"Métrique": "IV premium", "Valeur": fmt_pct(metrics.get("iv_premium_20")), "Lecture": "Premium d'IV vs volatilité réalisée."},
        {"Métrique": "Put wing IV", "Valeur": fmt_pct(metrics.get("put_wing_iv")), "Lecture": "Proxy put autour de -10%."},
        {"Métrique": "Call wing IV", "Valeur": fmt_pct(metrics.get("call_wing_iv")), "Lecture": "Proxy call autour de +10%."},
        {"Métrique": "Skew 10%", "Valeur": fmt_pct(metrics.get("skew_10")), "Lecture": "Put wing IV - Call wing IV."},
    ])
    st.dataframe(rows, width="stretch", hide_index=True)



# ============================================================
# Expiration Risk / 0DTE Fragility Monitor
# ============================================================

def build_expiration_fragility_monitor(
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    metrics: Dict[str, Any],
    spot: float,
    window_pct: float,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """
    Expiration Risk / 0DTE Fragility Monitor.

    Objectif :
    - mesurer la fragilité locale de l'expiration sélectionnée ;
    - détecter le risque 0DTE / très court DTE ;
    - combiner gamma proche spot, OI proche spot, walls, gamma flip, volume/OI et charm proxy.

    Prudence :
    - basé sur données publiques yfinance ;
    - pas une mesure OPRA ;
    - pas une vérité dealer positioning ;
    - ne modifie pas le score global dérivés.
    """
    empty_summary = {
        "expiration_state": "N/A",
        "expiration_score": None,
        "expiration": metrics.get("expiration", "N/A") if isinstance(metrics, dict) else "N/A",
        "dte": metrics.get("dte") if isinstance(metrics, dict) else None,
        "move_proxy_pct": None,
        "move_proxy_price": None,
        "near_oi_ratio": None,
        "near_gex_ratio": None,
        "very_near_oi_ratio": None,
        "nearest_level_name": "N/A",
        "nearest_level": None,
        "nearest_level_distance": None,
        "gamma_flip_distance": None,
        "volume_oi_ratio": None,
        "near_charm_ratio": None,
        "message": "Expiration fragility indisponible.",
    }

    if spot is None or spot <= 0:
        return pd.DataFrame(), pd.DataFrame(), empty_summary

    def _prep(df: pd.DataFrame, side: str) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()

        out = df.copy()

        needed = [
            "strike", "openInterest", "volume", "iv",
            "delta", "gamma", "charm", "vanna", "gex_proxy",
        ]

        for col in needed:
            if col not in out.columns:
                out[col] = np.nan
            out[col] = pd.to_numeric(out[col], errors="coerce")

        out = out.dropna(subset=["strike"]).copy()

        if out.empty:
            return pd.DataFrame()

        out["side"] = side
        out["oi"] = out["openInterest"].fillna(0)
        out["vol"] = out["volume"].fillna(0)
        out["distance_spot"] = out["strike"] / max(spot, _EPS) - 1.0

        out = out[
            (out["strike"] >= spot * (1.0 - window_pct))
            & (out["strike"] <= spot * (1.0 + window_pct))
            & ((out["oi"] > 0) | (out["vol"] > 0))
        ].copy()

        if out.empty:
            return pd.DataFrame()

        out["signed_gex"] = out["gex_proxy"].fillna(0)
        out["abs_gex"] = out["signed_gex"].abs()

        out["delta_notional"] = (
            out["delta"].fillna(0)
            * out["oi"].fillna(0)
            * CONTRACT_SIZE
            * spot
        )

        out["charm_delta_notional_1d"] = (
            out["charm"].fillna(0)
            * out["oi"].fillna(0)
            * CONTRACT_SIZE
            * spot
        )

        out["vanna_delta_notional_1vol"] = (
            out["vanna"].fillna(0)
            * out["oi"].fillna(0)
            * CONTRACT_SIZE
            * spot
        )

        return out

    frames = []

    c = _prep(calls, "Call")
    p = _prep(puts, "Put")

    if not c.empty:
        frames.append(c)
    if not p.empty:
        frames.append(p)

    if not frames:
        return pd.DataFrame(), pd.DataFrame(), empty_summary

    all_df = pd.concat(frames, ignore_index=True)

    if all_df.empty:
        return pd.DataFrame(), pd.DataFrame(), empty_summary

    grouped = (
        all_df.groupby("strike", as_index=False)
        .agg(
            total_oi=("oi", "sum"),
            total_vol=("vol", "sum"),
            avg_iv=("iv", "mean"),
            signed_gex=("signed_gex", "sum"),
            abs_gex=("abs_gex", "sum"),
            delta_notional=("delta_notional", "sum"),
            charm_delta_notional_1d=("charm_delta_notional_1d", "sum"),
            vanna_delta_notional_1vol=("vanna_delta_notional_1vol", "sum"),
        )
        .sort_values("strike")
        .reset_index(drop=True)
    )

    if grouped.empty:
        return pd.DataFrame(), pd.DataFrame(), empty_summary

    grouped["distance_spot"] = grouped["strike"] / max(spot, _EPS) - 1.0

    total_oi = safe_float(grouped["total_oi"].sum(), 0.0) or 0.0
    total_vol = safe_float(grouped["total_vol"].sum(), 0.0) or 0.0
    total_abs_gex = safe_float(grouped["abs_gex"].sum(), 0.0) or 0.0
    total_abs_charm = safe_float(grouped["charm_delta_notional_1d"].abs().sum(), 0.0) or 0.0

    near = grouped[grouped["distance_spot"].abs() <= 0.025].copy()
    very_near = grouped[grouped["distance_spot"].abs() <= 0.010].copy()

    near_oi_ratio = (
        safe_float(near["total_oi"].sum() / max(total_oi, _EPS), 0.0)
        if total_oi > 0 and not near.empty else 0.0
    )

    very_near_oi_ratio = (
        safe_float(very_near["total_oi"].sum() / max(total_oi, _EPS), 0.0)
        if total_oi > 0 and not very_near.empty else 0.0
    )

    near_gex_ratio = (
        safe_float(near["abs_gex"].sum() / max(total_abs_gex, _EPS), 0.0)
        if total_abs_gex > 0 and not near.empty else 0.0
    )

    near_charm_ratio = (
        safe_float(near["charm_delta_notional_1d"].abs().sum() / max(total_abs_charm, _EPS), 0.0)
        if total_abs_charm > 0 and not near.empty else 0.0
    )

    dte = safe_int(metrics.get("dte")) if isinstance(metrics, dict) else None
    if dte is None:
        dte = 0

    atm_iv = safe_float(metrics.get("atm_iv")) if isinstance(metrics, dict) else None

    move_proxy_pct = None
    move_proxy_price = None

    if atm_iv is not None and atm_iv > 0:
        # 0DTE : proxy intraday minimal 0.5 jour pour éviter un expected move nul.
        effective_days = max(float(dte), 0.5)
        move_proxy_pct = safe_float(atm_iv * math.sqrt(effective_days / 365.0))
        move_proxy_price = safe_float(spot * move_proxy_pct) if move_proxy_pct is not None else None

    level_candidates: List[Tuple[str, Optional[float]]] = [
        ("Call wall", safe_float(metrics.get("call_wall"))),
        ("Put wall", safe_float(metrics.get("put_wall"))),
        ("Max pain", safe_float(metrics.get("max_pain"))),
        ("Gamma flip", safe_float(metrics.get("gamma_flip"))),
    ]

    valid_levels = [
        (name, val, abs(val / max(spot, _EPS) - 1.0))
        for name, val in level_candidates
        if val is not None and val > 0
    ]

    if valid_levels:
        nearest_name, nearest_level, nearest_dist = min(valid_levels, key=lambda x: x[2])
    else:
        nearest_name, nearest_level, nearest_dist = "N/A", None, None

    gamma_flip = safe_float(metrics.get("gamma_flip")) if isinstance(metrics, dict) else None
    gamma_flip_distance = None

    if gamma_flip is not None and gamma_flip > 0:
        gamma_flip_distance = abs(gamma_flip / max(spot, _EPS) - 1.0)

    volume_oi_ratio = None
    if total_oi > 0:
        volume_oi_ratio = total_vol / max(total_oi, _EPS)

    # -----------------------------
    # Scoring prudent
    # -----------------------------
    if dte <= 0:
        dte_score = 100.0
    elif dte == 1:
        dte_score = 92.0
    elif dte == 2:
        dte_score = 82.0
    elif dte <= 5:
        dte_score = 68.0
    elif dte <= 7:
        dte_score = 56.0
    elif dte <= 14:
        dte_score = 38.0
    else:
        dte_score = 22.0

    near_oi_score = clamp((near_oi_ratio or 0.0) / 0.25 * 100.0)
    very_near_oi_score = clamp((very_near_oi_ratio or 0.0) / 0.12 * 100.0)
    near_gex_score = clamp((near_gex_ratio or 0.0) / 0.35 * 100.0)

    if nearest_dist is not None:
        wall_distance_score = clamp((0.06 - nearest_dist) / 0.06 * 100.0)
    else:
        wall_distance_score = 20.0

    if gamma_flip_distance is not None:
        flip_score = clamp((0.05 - gamma_flip_distance) / 0.05 * 100.0)
    else:
        flip_score = 20.0

    if volume_oi_ratio is not None:
        volume_score = clamp(volume_oi_ratio / 0.75 * 100.0)
    else:
        volume_score = 20.0

    if total_abs_charm > 0:
        charm_score = clamp((near_charm_ratio or 0.0) / 0.35 * 100.0)
    else:
        charm_score = 20.0

    move_wall_inside = False

    if move_proxy_pct is not None and nearest_dist is not None:
        move_wall_inside = nearest_dist <= move_proxy_pct

    expiration_score = clamp(
        0.24 * dte_score
        + 0.21 * near_gex_score
        + 0.14 * near_oi_score
        + 0.07 * very_near_oi_score
        + 0.14 * wall_distance_score
        + 0.08 * flip_score
        + 0.06 * volume_score
        + 0.06 * charm_score
    )

    if move_wall_inside:
        expiration_score = clamp(expiration_score + 6.0)

    # Floors prudents : très court DTE + concentration proche spot.
    if dte <= 1 and near_gex_ratio >= 0.25:
        expiration_score = max(expiration_score, 70.0)

    if dte <= 1 and near_oi_ratio >= 0.20:
        expiration_score = max(expiration_score, 65.0)

    # Cap qualité : si la chaîne est quasi vide, on évite une conclusion trop agressive.
    if total_oi < 250 and total_abs_gex <= 0:
        expiration_score = min(expiration_score, 55.0)

    if expiration_score >= 80:
        expiration_state = "Expiration très fragile"
    elif expiration_score >= 65:
        expiration_state = "Fragilité expiration élevée"
    elif expiration_score >= 50:
        expiration_state = "Fragilité à surveiller"
    elif expiration_score >= 35:
        expiration_state = "Fragilité modérée"
    else:
        expiration_state = "Expiration stable"

    if dte <= 1 and expiration_score >= 65:
        message = (
            "Expiration très courte : gamma/OI proches du spot peuvent amplifier les réactions intraday. "
            "Lecture utile pour exécution, pas pour signal structurel."
        )
    elif near_gex_ratio >= 0.30:
        message = (
            "GEX fortement concentré près du spot : risque de réaction autour des strikes proches."
        )
    elif move_wall_inside:
        message = (
            "Un niveau clé est situé dans l'expected move proxy : risque de test/pinning pendant l'expiration."
        )
    elif expiration_score >= 50:
        message = (
            "Fragilité expiration à surveiller : plusieurs facteurs locaux sont visibles mais non bloquants."
        )
    else:
        message = (
            "Expiration non fragile sur les contrôles retenus : pas de concentration locale majeure détectée."
        )

    # Score par strike pour le graphique.
    max_oi = safe_float(grouped["total_oi"].max(), 0.0) or 0.0
    max_gex = safe_float(grouped["abs_gex"].max(), 0.0) or 0.0
    max_vol = safe_float(grouped["total_vol"].max(), 0.0) or 0.0
    max_charm = safe_float(grouped["charm_delta_notional_1d"].abs().max(), 0.0) or 0.0

    grouped["proximity_score"] = grouped["distance_spot"].abs().map(
        lambda x: 100.0 * max(0.0, 1.0 - min(abs(float(x)) / 0.06, 1.0))
    )

    grouped["oi_score"] = grouped["total_oi"].map(
        lambda x: 100.0 * min(float(x) / max(max_oi, _EPS), 1.0)
    )

    grouped["gex_score"] = grouped["abs_gex"].map(
        lambda x: 100.0 * min(float(x) / max(max_gex, _EPS), 1.0)
    )

    grouped["vol_score"] = grouped["total_vol"].map(
        lambda x: 100.0 * min(float(x) / max(max_vol, _EPS), 1.0) if max_vol > 0 else 20.0
    )

    grouped["charm_score"] = grouped["charm_delta_notional_1d"].abs().map(
        lambda x: 100.0 * min(float(x) / max(max_charm, _EPS), 1.0) if max_charm > 0 else 20.0
    )

    grouped["expiry_fragility_score"] = (
        0.30 * grouped["gex_score"]
        + 0.25 * grouped["oi_score"]
        + 0.20 * grouped["proximity_score"]
        + 0.15 * grouped["vol_score"]
        + 0.10 * grouped["charm_score"]
    ).map(lambda x: clamp(x))

    rows = [
        {
            "Bloc": "Expiration / DTE",
            "Valeur": f"{metrics.get('expiration', 'N/A')} · DTE {fmt_int(dte)}",
            "Score": fmt_score(dte_score),
            "Lecture": "Plus le DTE est court, plus la convexité/charm/gamma peuvent devenir instables.",
        },
        {
            "Bloc": "Expected move proxy",
            "Valeur": f"{fmt_pct(move_proxy_pct)} · ± {fmt_price(move_proxy_price)}",
            "Score": "N/A",
            "Lecture": "Proxy basé sur ATM IV. Sur DTE très court, lecture approximative avec floor 0.5 jour uniquement si nécessaire.",
        },
        {
            "Bloc": "OI proche spot",
            "Valeur": f"{fmt_pct(near_oi_ratio)} en ±2.5% · {fmt_pct(very_near_oi_ratio)} en ±1%",
            "Score": fmt_score(near_oi_score),
            "Lecture": "Concentration d'open interest autour du spot.",
        },
        {
            "Bloc": "GEX proche spot",
            "Valeur": fmt_pct(near_gex_ratio),
            "Score": fmt_score(near_gex_score),
            "Lecture": "Part du GEX absolu concentrée autour du spot.",
        },
        {
            "Bloc": "Niveau clé le plus proche",
            "Valeur": f"{nearest_name} · {fmt_price(nearest_level)} · distance {fmt_pct(nearest_dist)}",
            "Score": fmt_score(wall_distance_score),
            "Lecture": "Wall, max pain ou gamma flip le plus proche du spot.",
        },
        {
            "Bloc": "Gamma flip distance",
            "Valeur": fmt_pct(gamma_flip_distance),
            "Score": fmt_score(flip_score),
            "Lecture": "Distance du gamma flip au spot. Plus c'est proche, plus la zone est sensible.",
        },
        {
            "Bloc": "Volume / OI activation",
            "Valeur": fmt_pct(volume_oi_ratio),
            "Score": fmt_score(volume_score),
            "Lecture": "Volume relatif à l'OI sur l'expiration sélectionnée. Proxy d'activation du tape.",
        },
        {
            "Bloc": "Charm proche spot",
            "Valeur": fmt_pct(near_charm_ratio),
            "Score": fmt_score(charm_score),
            "Lecture": "Part du charm proxy concentrée autour du spot. Approximation Black-Scholes, pas flux dealer.",
        },
    ]

    summary = {
        "expiration_state": expiration_state,
        "expiration_score": expiration_score,
        "expiration": metrics.get("expiration", "N/A"),
        "dte": dte,
        "move_proxy_pct": move_proxy_pct,
        "move_proxy_price": move_proxy_price,
        "near_oi_ratio": near_oi_ratio,
        "near_gex_ratio": near_gex_ratio,
        "very_near_oi_ratio": very_near_oi_ratio,
        "nearest_level_name": nearest_name,
        "nearest_level": nearest_level,
        "nearest_level_distance": nearest_dist,
        "gamma_flip_distance": gamma_flip_distance,
        "volume_oi_ratio": volume_oi_ratio,
        "near_charm_ratio": near_charm_ratio,
        "move_wall_inside": move_wall_inside,
        "message": message,
    }

    return grouped, pd.DataFrame(rows), summary


def render_expiration_fragility_monitor(
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    metrics: Dict[str, Any],
    spot: float,
    window_pct: float,
) -> None:
    """
    Affichage Expiration Risk / 0DTE Fragility Monitor.
    À placer dans Gamma Proxy après Greeks Pressure Proxy.
    """
    st.markdown("### Expiration Risk / Short-DTE Fragility Monitor")

    expiry_df, diag_df, summary = build_expiration_fragility_monitor(
        calls=calls,
        puts=puts,
        metrics=metrics,
        spot=spot,
        window_pct=window_pct,
    )

    if expiry_df is None or expiry_df.empty:
        st.info("Expiration Fragility Monitor indisponible : OI/GEX/greeks insuffisants sur l'expiration sélectionnée.")
        return

    render_card_grid([
        (
            "Expiration state",
            str(summary.get("expiration_state", "N/A")),
            fmt_score(summary.get("expiration_score")),
        ),
        (
            "Selected expiry",
            str(summary.get("expiration", "N/A")),
            "DTE " + fmt_int(summary.get("dte")),
        ),
        (
            "Near OI / GEX",
            f"{fmt_pct(summary.get('near_oi_ratio'))} / {fmt_pct(summary.get('near_gex_ratio'))}",
            "±2.5% autour spot",
        ),
        (
            "Nearest key level",
            fmt_price(summary.get("nearest_level")),
            str(summary.get("nearest_level_name", "N/A")) + " · " + fmt_pct(summary.get("nearest_level_distance")),
        ),
    ])

    score = safe_float(summary.get("expiration_score"), 50.0) or 50.0

    if score >= 75:
        st.warning(summary.get("message", "Expiration fragile à surveiller."))
    elif score >= 50:
        st.info(summary.get("message", "Fragilité expiration modérée."))
    else:
        st.info(summary.get("message", "Expiration non fragile sur les contrôles retenus."))

    fig = go.Figure()

    plot_df = expiry_df.sort_values("expiry_fragility_score", ascending=False).head(20).copy()
    plot_df = plot_df.sort_values("strike")

    fig.add_trace(
        go.Bar(
            x=plot_df["strike"],
            y=plot_df["expiry_fragility_score"],
            name="Expiry fragility",
            hovertemplate=(
                "Strike %{x:.2f}<br>"
                "Fragility %{y:.0f}/100"
                "<extra></extra>"
            ),
        )
    )

    add_spot_line(fig, spot, "Spot")

    # Niveaux clés.
    key_levels = [
        ("Call wall", safe_float(metrics.get("call_wall")), "orange"),
        ("Put wall", safe_float(metrics.get("put_wall")), "cyan"),
        ("Max pain", safe_float(metrics.get("max_pain")), "yellow"),
        ("Gamma flip", safe_float(metrics.get("gamma_flip")), "red"),
    ]

    x_min = safe_float(plot_df["strike"].min())
    x_max = safe_float(plot_df["strike"].max())

    for label, level, color in key_levels:
        if level is None or level <= 0:
            continue
        if x_min is not None and x_max is not None and not (x_min <= level <= x_max):
            continue

        fig.add_vline(
            x=level,
            line_dash="dot",
            line_color=color,
            annotation_text=label,
            annotation_position="top",
        )

    fig.update_layout(
        title="Expiration fragility par strike — gamma/OI/proximité/volume/charm",
        xaxis_title="Strike",
        yaxis_title="Fragility score",
    )

    st.plotly_chart(apply_dark_layout(fig, 460), width="stretch")

    st.dataframe(
        diag_df,
        width="stretch",
        hide_index=True,
    )

    compact = expiry_df.sort_values("expiry_fragility_score", ascending=False).head(15).copy()

    display = compact[
        [
            "strike",
            "expiry_fragility_score",
            "distance_spot",
            "total_oi",
            "total_vol",
            "avg_iv",
            "signed_gex",
            "abs_gex",
            "charm_delta_notional_1d",
        ]
    ].copy()

    display = display.rename(columns={
        "strike": "Strike",
        "expiry_fragility_score": "Fragility",
        "distance_spot": "Distance spot",
        "total_oi": "Total OI",
        "total_vol": "Volume",
        "avg_iv": "Avg IV",
        "signed_gex": "Signed GEX",
        "abs_gex": "Abs GEX",
        "charm_delta_notional_1d": "Charm 1D",
    })

    if "Fragility" in display.columns:
        display["Fragility"] = display["Fragility"].map(fmt_score)
    if "Distance spot" in display.columns:
        display["Distance spot"] = display["Distance spot"].map(fmt_pct)
    if "Total OI" in display.columns:
        display["Total OI"] = display["Total OI"].map(fmt_int)
    if "Volume" in display.columns:
        display["Volume"] = display["Volume"].map(fmt_int)
    if "Avg IV" in display.columns:
        display["Avg IV"] = display["Avg IV"].map(fmt_pct)

    for col in ["Signed GEX", "Abs GEX", "Charm 1D"]:
        if col in display.columns:
            display[col] = display[col].map(fmt_large)

    st.dataframe(
        display,
        width="stretch",
        hide_index=True,
    )

    st.caption(
        "Expiration Fragility Monitor = diagnostic mécanique de l'expiration sélectionnée : DTE, OI/GEX proche spot, walls, gamma flip, volume/OI et charm proxy. "
        "Sur données publiques yfinance, il sert au timing et à l'exécution ; ce n'est pas une mesure institutionnelle OPRA/dealer flow et il ne modifie pas le score global dérivés."
    )


# ============================================================
# Futures Relative Strength / Underlying Confirmation
# ============================================================

def _relative_strength_family(row: pd.Series) -> str:
    ticker = str(row.get("Ticker", "")).upper().strip()
    typ = str(row.get("Type", ""))

    if ticker in ["NQ=F", "ES=F", "YM=F", "RTY=F"]:
        return "Equity futures"

    if ticker in ["QQQ", "SPY"]:
        return "Equity ETF"

    if ticker in ["SMH", "SOXX"]:
        return "Semis / leadership"

    if ticker in ["^VIX", "VIX"]:
        return "Volatility"

    if ticker in ["^TNX", "^TYX", "^FVX"]:
        return "Rates"

    if ticker in ["DX-Y.NYB", "DXY", "UUP"]:
        return "Dollar / FX"

    if ticker in ["CL=F", "GC=F"]:
        return "Commodities"

    if "Volatility" in typ:
        return "Volatility"

    if "Rates" in typ:
        return "Rates"

    if "FX" in typ:
        return "Dollar / FX"

    if "Sector" in typ:
        return "Sector / leadership"

    return "Other proxy"


def _relative_strength_weight(family: str, ticker: str, corr: Any) -> float:
    """
    Pondération de pertinence pour la relative strength.

    Prudence :
    - les futures/ETF/semis sont de vrais benchmarks directionnels ;
    - VIX/taux/dollar sont utiles en contexte mais moins propres comme benchmark relatif ;
    - la corrélation module le poids, sans supprimer brutalement les données.
    """
    family = str(family)
    ticker = str(ticker).upper().strip()

    base = 0.60

    if family == "Semis / leadership":
        base = 1.30
    elif family == "Equity futures":
        base = 1.20
    elif family == "Equity ETF":
        base = 1.15
    elif family in ["Volatility", "Rates", "Dollar / FX"]:
        base = 0.70
    elif family == "Commodities":
        base = 0.45

    c = safe_float(corr)

    if c is None:
        corr_weight = 0.75
    else:
        corr_weight = 0.55 + 0.45 * min(abs(c) / 0.70, 1.0)

    return float(base * corr_weight)


def _relative_strength_score_from_alpha(
    alpha_1d: Any,
    alpha_5d: Any,
    alpha_20d: Any,
    corr: Any,
) -> float:
    """
    Score 0-100 de sur/sous-performance beta-adjusted.

    alpha = rendement ticker - beta * rendement proxy.
    """
    a1 = safe_float(alpha_1d, 0.0) or 0.0
    a5 = safe_float(alpha_5d, 0.0) or 0.0
    a20 = safe_float(alpha_20d, 0.0) or 0.0

    weighted_alpha = 0.20 * a1 + 0.35 * a5 + 0.45 * a20

    score = 50.0 + weighted_alpha * 260.0

    c = safe_float(corr)

    # Si la corrélation est très faible, on ramène doucement vers neutre.
    if c is not None and abs(c) < 0.20:
        score = 50.0 + (score - 50.0) * 0.65

    return clamp(score)


def _relative_strength_regime(score: Any) -> str:
    s = safe_float(score, 50.0) or 50.0

    if s >= 75:
        return "Surperformance forte"
    if s >= 58:
        return "Surperformance"
    if s <= 35:
        return "Sous-performance forte"
    if s <= 42:
        return "Sous-performance"

    return "Neutre"


def _relative_strength_lecture(row: pd.Series) -> str:
    ticker = str(row.get("Ticker", "N/A"))
    family = str(row.get("Family", "N/A"))
    regime = str(row.get("Regime", "N/A"))

    alpha_5d = row.get("Alpha 5D")
    alpha_20d = row.get("Alpha 20D")
    beta = row.get("Beta ticker")
    corr = row.get("Corr")

    detail = (
        f"Alpha 5D {fmt_signed_pct(alpha_5d)}, "
        f"alpha 20D {fmt_signed_pct(alpha_20d)}, "
        f"beta {fmt_num(beta, 2)}, corr {fmt_num(corr, 2)}."
    )

    if regime in ["Surperformance forte", "Surperformance"]:
        return f"Le sous-jacent surperforme {ticker} / {family}. {detail}"

    if regime in ["Sous-performance forte", "Sous-performance"]:
        return f"Le sous-jacent sous-performe {ticker} / {family}. {detail}"

    return f"Relative strength neutre face à {ticker} / {family}. {detail}"


def build_futures_relative_strength_confirmation(
    ticker: str,
    price_data: pd.DataFrame,
    macro_df: pd.DataFrame,
    macro_summary: Optional[Dict[str, Any]] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Futures Relative Strength / Underlying Confirmation.

    Objectif :
    - comparer le sous-jacent analysé aux futures/ETF/proxies déjà chargés ;
    - mesurer la sur/sous-performance beta-adjusted ;
    - distinguer un vrai leadership du ticker d'un simple soutien du marché ;
    - ne modifier aucun score options, gamma, greeks, macro ou decision gate.
    """
    macro_summary = macro_summary or {}

    empty_summary = {
        "relative_state": "Indisponible",
        "relative_score": None,
        "primary_benchmark": "N/A",
        "weakest_benchmark": "N/A",
        "outperform_count": 0,
        "underperform_count": 0,
        "neutral_count": 0,
        "median_alpha_5d": None,
        "median_alpha_20d": None,
        "avg_beta": None,
        "message": "Relative strength indisponible.",
    }

    if macro_df is None or macro_df.empty:
        return pd.DataFrame(), empty_summary

    target = normalize_price_frame(price_data)

    if target.empty or "adj_close" not in target.columns:
        return pd.DataFrame(), empty_summary

    target_close = pd.to_numeric(target["adj_close"], errors="coerce").dropna()

    if len(target_close) < 25:
        return pd.DataFrame(), empty_summary

    target_1d = pct_change_from_series(target_close, 1)
    target_5d = pct_change_from_series(target_close, 5)
    target_20d = pct_change_from_series(target_close, 20)

    if target_1d is None and target_5d is None and target_20d is None:
        return pd.DataFrame(), empty_summary

    df = macro_df.copy()

    required = ["Ticker", "1D", "5D", "20D"]

    if any(c not in df.columns for c in required):
        return pd.DataFrame(), empty_summary

    for col in ["1D", "5D", "20D", "Vol 20D", "Beta ticker", "Corr"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    rows = []

    for _, row in df.iterrows():
        proxy = str(row.get("Ticker", "")).upper().strip()

        if not proxy or proxy == str(ticker).upper().strip():
            continue

        family = _relative_strength_family(row)

        proxy_1d = safe_float(row.get("1D"))
        proxy_5d = safe_float(row.get("5D"))
        proxy_20d = safe_float(row.get("20D"))

        beta = safe_float(row.get("Beta ticker"))
        corr = safe_float(row.get("Corr"))

        # Fallback prudent : si beta absent, beta=1 pour les benchmarks equity/sector,
        # sinon beta=0 pour les proxies macro moins directement comparables.
        if beta is None:
            if family in ["Equity futures", "Equity ETF", "Semis / leadership", "Sector / leadership"]:
                beta = 1.0
            else:
                beta = 0.0

        expected_1d = beta * proxy_1d if proxy_1d is not None else None
        expected_5d = beta * proxy_5d if proxy_5d is not None else None
        expected_20d = beta * proxy_20d if proxy_20d is not None else None

        alpha_1d = None
        alpha_5d = None
        alpha_20d = None

        if target_1d is not None and expected_1d is not None:
            alpha_1d = target_1d - expected_1d

        if target_5d is not None and expected_5d is not None:
            alpha_5d = target_5d - expected_5d

        if target_20d is not None and expected_20d is not None:
            alpha_20d = target_20d - expected_20d

        if alpha_1d is None and alpha_5d is None and alpha_20d is None:
            continue

        score = _relative_strength_score_from_alpha(
            alpha_1d=alpha_1d,
            alpha_5d=alpha_5d,
            alpha_20d=alpha_20d,
            corr=corr,
        )

        regime = _relative_strength_regime(score)

        relevance_weight = _relative_strength_weight(
            family=family,
            ticker=proxy,
            corr=corr,
        )

        rows.append({
            "Family": family,
            "Ticker": proxy,
            "Instrument": row.get("Instrument", proxy),
            "Target 1D": target_1d,
            "Target 5D": target_5d,
            "Target 20D": target_20d,
            "Proxy 1D": proxy_1d,
            "Proxy 5D": proxy_5d,
            "Proxy 20D": proxy_20d,
            "Beta ticker": beta,
            "Corr": corr,
            "Expected 1D": expected_1d,
            "Expected 5D": expected_5d,
            "Expected 20D": expected_20d,
            "Alpha 1D": alpha_1d,
            "Alpha 5D": alpha_5d,
            "Alpha 20D": alpha_20d,
            "Relative score num": score,
            "Score": fmt_score(score),
            "Regime": regime,
            "Relevance weight": relevance_weight,
        })

    out = pd.DataFrame(rows)

    if out.empty:
        return pd.DataFrame(), empty_summary

    out["Lecture"] = out.apply(_relative_strength_lecture, axis=1)

    total_weight = safe_float(out["Relevance weight"].sum(), 0.0) or 0.0

    if total_weight <= 0:
        relative_score = safe_float(out["Relative score num"].mean(), 50.0) or 50.0
    else:
        relative_score = safe_float(
            np.average(out["Relative score num"], weights=out["Relevance weight"]),
            50.0,
        ) or 50.0

    outperform_count = int(out["Regime"].isin(["Surperformance forte", "Surperformance"]).sum())
    underperform_count = int(out["Regime"].isin(["Sous-performance forte", "Sous-performance"]).sum())
    neutral_count = int(out["Regime"].eq("Neutre").sum())

    core = out[out["Family"].isin(["Equity futures", "Equity ETF", "Semis / leadership", "Sector / leadership"])].copy()

    if core.empty:
        core = out.copy()

    median_alpha_5d = safe_float(pd.to_numeric(core["Alpha 5D"], errors="coerce").median())
    median_alpha_20d = safe_float(pd.to_numeric(core["Alpha 20D"], errors="coerce").median())
    avg_beta = safe_float(pd.to_numeric(core["Beta ticker"], errors="coerce").median())

    # Benchmark principal prudent :
    # - les cartes principales doivent privilégier les vrais benchmarks directionnels
    #   equity futures / ETF / sector leadership ;
    # - VIX, taux et dollar restent dans la table, mais ne pilotent pas "Best benchmark".
    core_benchmark_families = [
        "Equity futures",
        "Equity ETF",
        "Semis / leadership",
        "Sector / leadership",
    ]

    core_ranked = out[out["Family"].isin(core_benchmark_families)].copy()

    if core_ranked.empty:
        core_ranked = out.copy()

    core_ranked["Relative score num"] = pd.to_numeric(
        core_ranked["Relative score num"],
        errors="coerce",
    )

    core_ranked = core_ranked.dropna(subset=["Relative score num"])

    if core_ranked.empty:
        primary_benchmark = "N/A"
        weakest_benchmark = "N/A"
        primary_benchmark_family = "N/A"
        weakest_benchmark_family = "N/A"
    else:
        best_row = core_ranked.sort_values(
            "Relative score num",
            ascending=False,
        ).iloc[0]

        weak_row = core_ranked.sort_values(
            "Relative score num",
            ascending=True,
        ).iloc[0]

        primary_benchmark = str(best_row.get("Ticker", "N/A"))
        weakest_benchmark = str(weak_row.get("Ticker", "N/A"))
        primary_benchmark_family = str(best_row.get("Family", "N/A"))
        weakest_benchmark_family = str(weak_row.get("Family", "N/A"))

    core_outperform_count = int(
        core_ranked["Regime"].isin(["Surperformance forte", "Surperformance"]).sum()
    ) if not core_ranked.empty else 0

    core_underperform_count = int(
        core_ranked["Regime"].isin(["Sous-performance forte", "Sous-performance"]).sum()
    ) if not core_ranked.empty else 0

    core_neutral_count = int(
        core_ranked["Regime"].eq("Neutre").sum()
    ) if not core_ranked.empty else 0

    if relative_score >= 75 and underperform_count == 0:
        relative_state = "Surperformance confirmée"
        message = "Relative strength confirmée : le sous-jacent surperforme ses benchmarks/proxies de façon large."

    elif relative_score >= 60 and underperform_count <= 1:
        relative_state = "Relative strength constructive"
        message = "Relative strength constructive : le sous-jacent fait mieux que ses benchmarks, mais la confirmation n'est pas totale."

    elif relative_score <= 42 and outperform_count <= 1:
        relative_state = "Sous-performance relative"
        message = "Sous-performance relative : le sous-jacent ne confirme pas le tape macro/futures."

    elif outperform_count >= 2 and underperform_count >= 2:
        relative_state = "Relative strength divergente"
        message = "Relative strength divergente : le ticker surperforme certains benchmarks mais sous-performe d'autres."

    else:
        relative_state = "Relative strength neutre"
        message = "Relative strength neutre : pas de leadership clair du sous-jacent face aux benchmarks."

    summary = {
        "relative_state": relative_state,
        "relative_score": clamp(relative_score),
        "primary_benchmark": primary_benchmark,
        "weakest_benchmark": weakest_benchmark,
        "primary_benchmark_family": primary_benchmark_family,
        "weakest_benchmark_family": weakest_benchmark_family,
        "core_outperform_count": core_outperform_count,
        "core_underperform_count": core_underperform_count,
        "core_neutral_count": core_neutral_count,
        "outperform_count": outperform_count,
        "underperform_count": underperform_count,
        "neutral_count": neutral_count,
        "median_alpha_5d": median_alpha_5d,
        "median_alpha_20d": median_alpha_20d,
        "avg_beta": avg_beta,
        "message": message,
    }

    out = out.sort_values("Relative score num", ascending=False).reset_index(drop=True)

    return out, summary


def render_futures_relative_strength_confirmation(
    ticker: str,
    price_data: pd.DataFrame,
    macro_df: pd.DataFrame,
    macro_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Affichage Futures Relative Strength / Underlying Confirmation.
    À placer dans Futures Tape après Futures Momentum / Trend Confirmation.
    """
    st.subheader("Futures Relative Strength / Underlying Confirmation")

    rs_df, summary = build_futures_relative_strength_confirmation(
        ticker=ticker,
        price_data=price_data,
        macro_df=macro_df,
        macro_summary=macro_summary,
    )

    if rs_df is None or rs_df.empty:
        st.info("Relative strength indisponible : données ticker/proxies insuffisantes.")
        return summary

    render_card_grid([
        (
            "Relative state",
            str(summary.get("relative_state", "N/A")),
            fmt_score(summary.get("relative_score")),
        ),
        (
            "Best core benchmark",
            str(summary.get("primary_benchmark", "N/A")),
            str(summary.get("primary_benchmark_family", "Benchmark core")),
        ),
        (
            "Alpha 5D / 20D",
            f"{fmt_signed_pct(summary.get('median_alpha_5d'))} / {fmt_signed_pct(summary.get('median_alpha_20d'))}",
            "Médiane vs benchmarks core",
        ),
        (
            "Core breadth",
            f"{fmt_int(summary.get('core_outperform_count'))} out / {fmt_int(summary.get('core_underperform_count'))} under",
            f"{fmt_int(summary.get('core_neutral_count'))} core neutre",
        ),
    ])

    score = safe_float(summary.get("relative_score"), 50.0) or 50.0
    state = str(summary.get("relative_state", ""))

    if state in ["Sous-performance relative", "Relative strength divergente"]:
        alert_by_score(str(summary.get("message", "Relative strength à surveiller.")), 72.0)
    elif score >= 60:
        alert_by_score(str(summary.get("message", "Relative strength constructive.")), 35.0)
    else:
        alert_by_score(str(summary.get("message", "Relative strength neutre.")), 55.0)

    plot_df = rs_df.copy()
    plot_df["Relative score num"] = pd.to_numeric(plot_df["Relative score num"], errors="coerce")
    plot_df = plot_df.dropna(subset=["Relative score num"]).head(12)

    if not plot_df.empty:
        fig = go.Figure()

        fig.add_trace(
            go.Bar(
                x=plot_df["Ticker"],
                y=plot_df["Relative score num"],
                name="Relative strength score",
                hovertemplate=(
                    "%{x}<br>"
                    "Score %{y:.0f}/100"
                    "<extra></extra>"
                ),
            )
        )

        fig.add_hline(y=50, line_dash="dash", line_color="white")
        fig.add_hline(y=58, line_dash="dot", line_color="rgba(120,180,255,.65)")
        fig.add_hline(y=42, line_dash="dot", line_color="rgba(255,180,120,.65)")

        fig.update_layout(
            title="Relative strength vs benchmarks/proxies",
            xaxis_title="Benchmark / proxy",
            yaxis_title="Score",
        )

        fig.update_yaxes(range=[0, 100])

        st.plotly_chart(apply_dark_layout(fig, 430), width="stretch")

    display_cols = [
        "Family",
        "Ticker",
        "Instrument",
        "Score",
        "Regime",
        "Target 1D",
        "Target 5D",
        "Target 20D",
        "Proxy 1D",
        "Proxy 5D",
        "Proxy 20D",
        "Alpha 1D",
        "Alpha 5D",
        "Alpha 20D",
        "Beta ticker",
        "Corr",
        "Relevance weight",
        "Lecture",
    ]

    display = rs_df[[c for c in display_cols if c in rs_df.columns]].copy()

    for c in [
        "Target 1D",
        "Target 5D",
        "Target 20D",
        "Proxy 1D",
        "Proxy 5D",
        "Proxy 20D",
        "Alpha 1D",
        "Alpha 5D",
        "Alpha 20D",
    ]:
        if c in display.columns:
            display[c] = display[c].map(fmt_signed_pct)

    for c in ["Beta ticker", "Corr", "Relevance weight"]:
        if c in display.columns:
            display[c] = display[c].map(lambda x: fmt_num(x, 2))

    st.dataframe(
        display,
        width="stretch",
        hide_index=True,
    )

    st.caption(
        "Relative Strength = comparaison mécanique du rendement du sous-jacent contre les futures/ETF/proxies, "
        "avec alpha beta-adjusted : alpha = rendement ticker - beta × rendement proxy. "
        "Ce bloc sert à confirmer si le ticker mène ou subit le tape macro ; il ne modifie aucun score options, gamma, greeks, macro ou decision gate."
    )

    return summary



# ============================================================
# Futures Volatility / Risk Compression Monitor
# ============================================================

def _futures_vol_family(row: pd.Series) -> str:
    ticker = str(row.get("Ticker", "")).upper().strip()
    typ = str(row.get("Type", ""))

    if ticker in ["NQ=F", "ES=F", "YM=F", "RTY=F"]:
        return "Equity futures"

    if ticker in ["QQQ", "SPY"]:
        return "Equity ETF"

    if ticker in ["SMH", "SOXX"]:
        return "Semis / leadership"

    if ticker in ["^VIX", "VIX"]:
        return "Volatility"

    if ticker in ["^TNX", "^TYX", "^FVX"]:
        return "Rates"

    if ticker in ["DX-Y.NYB", "DXY", "UUP"]:
        return "Dollar / FX"

    if ticker in ["CL=F", "GC=F"]:
        return "Commodities"

    if "Volatility" in typ:
        return "Volatility"
    if "Rates" in typ:
        return "Rates"
    if "FX" in typ:
        return "Dollar / FX"
    if "Sector" in typ:
        return "Semis / leadership"

    return "Other"


def _ann_vol_from_close(close: pd.Series, window: int) -> Optional[float]:
    s = pd.to_numeric(close, errors="coerce").dropna()

    if len(s) < max(8, window // 2):
        return None

    ret = np.log(s / s.shift(1)).replace([np.inf, -np.inf], np.nan).dropna()

    if len(ret) < max(8, window // 2):
        return None

    return safe_float(ret.tail(window).std(ddof=1) * math.sqrt(252))


def _vol_pressure_score_from_row(
    ticker: str,
    family: str,
    r1: Any,
    r5: Any,
    r20: Any,
    vol10: Any,
    vol20: Any,
    vol60: Any,
) -> float:
    """
    Score 0-100.
    Plus le score est élevé, plus la pression volatilité / risk-off est forte.
    """
    ticker = str(ticker).upper().strip()
    family = str(family)

    r1 = safe_float(r1, 0.0) or 0.0
    r5 = safe_float(r5, 0.0) or 0.0
    r20 = safe_float(r20, 0.0) or 0.0

    v10 = safe_float(vol10)
    v20 = safe_float(vol20)
    v60 = safe_float(vol60)

    trend = 0.45 * r5 + 0.35 * r20 + 0.20 * r1

    vol_level_score = 50.0
    if v20 is not None:
        vol_level_score = clamp((v20 - 0.12) / 0.45 * 100.0)

    vol_accel_score = 50.0
    if v10 is not None and v60 is not None and v60 > 0:
        vol_accel_score = clamp(50.0 + ((v10 / v60) - 1.0) * 85.0)

    if family in ["Equity futures", "Equity ETF", "Semis / leadership"]:
        # Risk-on : baisse + vol qui monte = pression.
        trend_pressure = clamp(50.0 - trend * 650.0)
        score = 0.45 * trend_pressure + 0.35 * vol_accel_score + 0.20 * vol_level_score

    elif family == "Volatility":
        # VIX : hausse = pression ; baisse = compression constructive.
        vix_move_pressure = clamp(50.0 + (0.55 * r5 + 0.45 * r20) * 520.0)
        score = 0.70 * vix_move_pressure + 0.30 * vol_accel_score

    elif family in ["Rates", "Dollar / FX"]:
        # Taux/dollar : hausse rapide = pression macro.
        macro_pressure = clamp(50.0 + (0.60 * r5 + 0.40 * r20) * 420.0)
        score = 0.60 * macro_pressure + 0.25 * vol_accel_score + 0.15 * vol_level_score

    else:
        score = 0.50 * vol_accel_score + 0.30 * vol_level_score + 0.20 * clamp(50.0 - trend * 250.0)

    return clamp(score)


def _vol_pressure_regime(score: Any) -> str:
    s = safe_float(score, 50.0) or 50.0

    if s >= 75:
        return "Pression vol forte"
    if s >= 60:
        return "Pression vol"
    if s <= 35:
        return "Compression constructive"
    if s <= 45:
        return "Vol contenue"

    return "Neutre"


def _vol_pressure_lecture(row: pd.Series) -> str:
    ticker = str(row.get("Ticker", "N/A"))
    family = str(row.get("Family", "N/A"))
    regime = str(row.get("Regime", "N/A"))

    details = (
        f"1D {fmt_signed_pct(row.get('1D'))}, "
        f"5D {fmt_signed_pct(row.get('5D'))}, "
        f"20D {fmt_signed_pct(row.get('20D'))}, "
        f"vol10 {fmt_pct(row.get('Vol 10D'))}, "
        f"vol20 {fmt_pct(row.get('Vol 20D'))}, "
        f"vol60 {fmt_pct(row.get('Vol 60D'))}."
    )

    if regime in ["Pression vol forte", "Pression vol"]:
        return f"{ticker} / {family} montre une pression volatilité ou risk-off. {details}"

    if regime in ["Compression constructive", "Vol contenue"]:
        return f"{ticker} / {family} soutient une compression de volatilité ou un tape plus stable. {details}"

    return f"{ticker} / {family} neutre sur volatilité. {details}"


def build_futures_volatility_regime_monitor(
    ticker: str,
    price_data: pd.DataFrame,
    macro_df: pd.DataFrame,
    macro_summary: Optional[Dict[str, Any]] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Futures Volatility / Risk Compression Monitor.

    Objectif :
    - lire si le tape futures est soutenu par compression de vol ou fragilisé par expansion de vol ;
    - séparer VIX, futures equity, ETF, semis, rates et dollar ;
    - utiliser uniquement les données déjà accessibles via yfinance ;
    - ne modifier aucun score options, gamma, greeks, macro ou decision gate.
    """
    macro_summary = macro_summary or {}

    empty_summary = {
        "vol_state": "Indisponible",
        "vol_pressure_score": None,
        "primary_pressure": "N/A",
        "primary_support": "N/A",
        "target_rv10": None,
        "target_rv20": None,
        "target_rv60": None,
        "support_count": 0,
        "pressure_count": 0,
        "neutral_count": 0,
        "message": "Volatility regime indisponible.",
        "family_decomp": pd.DataFrame(),
    }

    if macro_df is None or macro_df.empty:
        return pd.DataFrame(), empty_summary

    target = normalize_price_frame(price_data)

    if target.empty or "adj_close" not in target.columns:
        return pd.DataFrame(), empty_summary

    target_close = pd.to_numeric(target["adj_close"], errors="coerce").dropna()

    if len(target_close) < 25:
        return pd.DataFrame(), empty_summary

    target_rv10 = _ann_vol_from_close(target_close, 10)
    target_rv20 = _ann_vol_from_close(target_close, 20)
    target_rv60 = _ann_vol_from_close(target_close, 60)

    rows = []

    for _, row in macro_df.iterrows():
        proxy = str(row.get("Ticker", "")).upper().strip()

        if not proxy:
            continue

        hist = get_history_cached(proxy, period="6mo", interval="1d")

        if hist is None or hist.empty:
            continue

        h = normalize_price_frame(hist)

        if h.empty or "adj_close" not in h.columns:
            continue

        close = pd.to_numeric(h["adj_close"], errors="coerce").dropna()

        if len(close) < 25:
            continue

        r1 = pct_change_from_series(close, 1)
        r5 = pct_change_from_series(close, 5)
        r20 = pct_change_from_series(close, 20)

        vol10 = _ann_vol_from_close(close, 10)
        vol20 = _ann_vol_from_close(close, 20)
        vol60 = _ann_vol_from_close(close, 60)

        family = _futures_vol_family(row)

        pressure_score = _vol_pressure_score_from_row(
            ticker=proxy,
            family=family,
            r1=r1,
            r5=r5,
            r20=r20,
            vol10=vol10,
            vol20=vol20,
            vol60=vol60,
        )

        regime = _vol_pressure_regime(pressure_score)

        vol_ratio = None
        if vol10 is not None and vol60 is not None and vol60 > 0:
            vol_ratio = vol10 / vol60

        rows.append({
            "Family": family,
            "Ticker": proxy,
            "Instrument": row.get("Instrument", proxy),
            "Score num": pressure_score,
            "Score": fmt_score(pressure_score),
            "Regime": regime,
            "1D": r1,
            "5D": r5,
            "20D": r20,
            "Vol 10D": vol10,
            "Vol 20D": vol20,
            "Vol 60D": vol60,
            "Vol10/Vol60": vol_ratio,
            "Beta ticker": row.get("Beta ticker"),
            "Corr": row.get("Corr"),
        })

    out = pd.DataFrame(rows)

    if out.empty:
        return pd.DataFrame(), empty_summary

    out["Lecture"] = out.apply(_vol_pressure_lecture, axis=1)

    family_rows = []

    for family, g in out.groupby("Family"):
        scores = pd.to_numeric(g["Score num"], errors="coerce").dropna()

        if scores.empty:
            continue

        family_score = safe_float(scores.median(), 50.0) or 50.0

        support = int(g["Regime"].isin(["Compression constructive", "Vol contenue"]).sum())
        pressure = int(g["Regime"].isin(["Pression vol forte", "Pression vol"]).sum())
        neutral = int(g["Regime"].eq("Neutre").sum())

        regime = _vol_pressure_regime(family_score)

        family_rows.append({
            "Family": family,
            "Proxies": ", ".join(sorted(g["Ticker"].astype(str).unique())),
            "Proxy count": int(len(g)),
            "Support": support,
            "Pressure": pressure,
            "Neutral": neutral,
            "Score num": family_score,
            "Score": fmt_score(family_score),
            "Regime": regime,
            "Median 1D": safe_float(pd.to_numeric(g["1D"], errors="coerce").median()),
            "Median 5D": safe_float(pd.to_numeric(g["5D"], errors="coerce").median()),
            "Median 20D": safe_float(pd.to_numeric(g["20D"], errors="coerce").median()),
            "Median vol 10D": safe_float(pd.to_numeric(g["Vol 10D"], errors="coerce").median()),
            "Median vol 20D": safe_float(pd.to_numeric(g["Vol 20D"], errors="coerce").median()),
            "Median vol 60D": safe_float(pd.to_numeric(g["Vol 60D"], errors="coerce").median()),
            "Median vol ratio": safe_float(pd.to_numeric(g["Vol10/Vol60"], errors="coerce").median()),
        })

    family_decomp = pd.DataFrame(family_rows)

    if family_decomp.empty:
        return out, empty_summary

    # Pondération : VIX et semis comptent plus pour NVDA/tech, futures equity ensuite.
    def _fam_weight(family: str) -> float:
        if family == "Volatility":
            return 1.30
        if family == "Semis / leadership":
            return 1.25
        if family == "Equity futures":
            return 1.15
        if family == "Equity ETF":
            return 1.10
        if family in ["Rates", "Dollar / FX"]:
            return 1.05
        return 0.75

    family_decomp["Weight"] = family_decomp["Family"].map(_fam_weight)
    total_w = safe_float(family_decomp["Weight"].sum(), 1.0) or 1.0

    vol_pressure_score = safe_float(
        (family_decomp["Score num"] * family_decomp["Weight"]).sum() / max(total_w, _EPS),
        50.0,
    ) or 50.0

    pressure_count = int(family_decomp["Regime"].isin(["Pression vol forte", "Pression vol"]).sum())
    support_count = int(family_decomp["Regime"].isin(["Compression constructive", "Vol contenue"]).sum())
    neutral_count = int(family_decomp["Regime"].eq("Neutre").sum())

    pressure_row = family_decomp.sort_values("Score num", ascending=False).iloc[0]
    support_row = family_decomp.sort_values("Score num", ascending=True).iloc[0]

    raw_primary_pressure = str(pressure_row.get("Family", "N/A"))
    raw_primary_support = str(support_row.get("Family", "N/A"))

    max_pressure_score = safe_float(pressure_row.get("Score num"), 50.0) or 50.0
    min_pressure_score = safe_float(support_row.get("Score num"), 50.0) or 50.0

    primary_pressure = (
        raw_primary_pressure
        if max_pressure_score >= 60
        else "Aucune pression majeure"
    ) 

    primary_support = (
        raw_primary_support
        if min_pressure_score <= 40
        else "Aucune compression majeure"
    )

    if vol_pressure_score >= 75 or pressure_count >= 3:
        vol_state = "Vol pressure élevée"
        message = "Pression volatilité élevée : le tape futures devient plus fragile, surtout si VIX/taux/dollar confirment."

    elif vol_pressure_score >= 60:
        vol_state = "Vol pressure à surveiller"
        message = "Volatility regime à surveiller : expansion de vol partielle, exécution moins propre."

    elif vol_pressure_score <= 40 and support_count >= 3:
        vol_state = "Compression constructive"
        message = "Compression volatilité constructive : le tape futures est plus stable et soutient mieux le setup."

    elif pressure_count >= 2 and support_count >= 2:
        vol_state = "Vol regime divergent"
        message = "Volatility regime divergent : certaines familles compressent, d'autres signalent de la pression."

    else:
        vol_state = "Vol regime neutre"
        message = "Volatility regime neutre : pas de pression ou compression dominante."

    family_decomp["Lecture"] = family_decomp.apply(
        lambda r: (
            "Famille principale de pression volatilité."
            if str(r.get("Family")) == primary_pressure
            else "Famille principale de compression/support volatilité."
            if str(r.get("Family")) == primary_support
            else "Famille contributive ou neutre sur le régime de vol."
        ),
        axis=1,
    )

    family_decomp = family_decomp.sort_values("Score num", ascending=False).reset_index(drop=True)

    summary = {
        "vol_state": vol_state,
        "vol_pressure_score": clamp(vol_pressure_score),
        "primary_pressure": primary_pressure,
        "primary_support": primary_support,
        "target_rv10": target_rv10,
        "target_rv20": target_rv20,
        "target_rv60": target_rv60,
        "support_count": support_count,
        "pressure_count": pressure_count,
        "neutral_count": neutral_count,
        "message": message,
        "family_decomp": family_decomp,
        "raw_primary_pressure": raw_primary_pressure,
        "raw_primary_support": raw_primary_support, 
    }

    out = out.sort_values("Score num", ascending=False).reset_index(drop=True)

    return out, summary


def render_futures_volatility_regime_monitor(
    ticker: str,
    price_data: pd.DataFrame,
    macro_df: pd.DataFrame,
    macro_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Affichage Futures Volatility / Risk Compression Monitor.
    À placer dans Futures Tape après Futures Relative Strength.
    """
    st.subheader("Futures Volatility / Risk Compression Monitor")

    vol_df, summary = build_futures_volatility_regime_monitor(
        ticker=ticker,
        price_data=price_data,
        macro_df=macro_df,
        macro_summary=macro_summary,
    )

    if vol_df is None or vol_df.empty:
        st.info("Volatility regime futures indisponible : données futures/proxies insuffisantes.")
        return summary

    render_card_grid([
        (
            "Vol regime",
            str(summary.get("vol_state", "N/A")),
            fmt_score(summary.get("vol_pressure_score")),
        ),
        (
            "Primary pressure",
            str(summary.get("primary_pressure", "N/A")),
            "Plus fragile : " + str(summary.get("raw_primary_pressure", "N/A")),
        ),
        (
            "Primary compression",
            str(summary.get("primary_support", "N/A")),
            "Plus stable : " + str(summary.get("raw_primary_support", "N/A")),
        ),
        (
            "Target RV 10/20/60",
            f"{fmt_pct(summary.get('target_rv10'))} / {fmt_pct(summary.get('target_rv20'))} / {fmt_pct(summary.get('target_rv60'))}",
            str(ticker).upper(),
        ),
    ])

    score = safe_float(summary.get("vol_pressure_score"), 50.0) or 50.0

    if score >= 70:
        alert_by_score(str(summary.get("message", "Vol pressure élevée.")), 78.0)
    elif score <= 42:
        alert_by_score(str(summary.get("message", "Compression constructive.")), 32.0)
    else:
        alert_by_score(str(summary.get("message", "Vol regime neutre.")), 55.0)

    family_decomp = summary.get("family_decomp", pd.DataFrame())

    if isinstance(family_decomp, pd.DataFrame) and not family_decomp.empty:
        plot_df = family_decomp.copy()
        plot_df["Score num"] = pd.to_numeric(plot_df["Score num"], errors="coerce")
        plot_df = plot_df.dropna(subset=["Score num"])

        if not plot_df.empty:
            fig = go.Figure()

            fig.add_trace(
                go.Bar(
                    x=plot_df["Family"],
                    y=plot_df["Score num"],
                    name="Vol pressure score",
                    hovertemplate=(
                        "%{x}<br>"
                        "Vol pressure %{y:.0f}/100"
                        "<extra></extra>"
                    ),
                )
            )

            fig.add_hline(y=50, line_dash="dash", line_color="white")
            fig.add_hline(y=60, line_dash="dot", line_color="rgba(255,180,120,.70)")
            fig.add_hline(y=40, line_dash="dot", line_color="rgba(120,180,255,.70)")

            fig.update_layout(
                title="Futures volatility regime — pression / compression par famille",
                xaxis_title="Famille",
                yaxis_title="Vol pressure score",
            )

            fig.update_yaxes(range=[0, 100])

            st.plotly_chart(apply_dark_layout(fig, 430), width="stretch")

        family_cols = [
            "Family",
            "Proxies",
            "Proxy count",
            "Support",
            "Pressure",
            "Neutral",
            "Score",
            "Regime",
            "Median 1D",
            "Median 5D",
            "Median 20D",
            "Median vol 10D",
            "Median vol 20D",
            "Median vol 60D",
            "Median vol ratio",
            "Lecture",
        ]

        st.dataframe(
            format_display_df(family_decomp[[c for c in family_cols if c in family_decomp.columns]]),
            width="stretch",
            hide_index=True,
        )

    with st.expander("Voir proxies volatility regime détaillés", expanded=False):
        proxy_cols = [
            "Family",
            "Ticker",
            "Instrument",
            "Score",
            "Regime",
            "1D",
            "5D",
            "20D",
            "Vol 10D",
            "Vol 20D",
            "Vol 60D",
            "Vol10/Vol60",
            "Beta ticker",
            "Corr",
            "Lecture",
        ]

        st.dataframe(
            format_display_df(vol_df[[c for c in proxy_cols if c in vol_df.columns]]),
            width="stretch",
            hide_index=True,
        )

    st.caption(
        "Futures Volatility / Risk Compression Monitor = lecture mécanique de la compression/expansion de volatilité sur futures, ETF, VIX, taux et dollar. "
        "Score élevé = pression volatilité/risk-off ; score bas = compression constructive. "
        "Ce bloc ne modifie aucun score options, gamma, greeks, macro ou decision gate."
    )

    return summary


# ============================================================
# Futures Breadth / Internal Participation Monitor
# ============================================================

def _participation_score_from_row(row: pd.Series) -> float:
    """
    Score 0-100.
    Plus le score est élevé, plus la participation futures/macro est constructive.
    Lecture basée sur le régime déjà calculé par compute_macro_tape.
    """
    regime = str(row.get("Regime", "")).lower().strip()

    r1 = safe_float(row.get("1D"), 0.0) or 0.0
    r5 = safe_float(row.get("5D"), 0.0) or 0.0
    r20 = safe_float(row.get("20D"), 0.0) or 0.0
    corr = safe_float(row.get("Corr"))

    trend_strength = abs(0.20 * r1 + 0.45 * r5 + 0.35 * r20)

    if "support" in regime:
        score = 64.0 + clamp(trend_strength * 900.0, 0.0, 28.0)
    elif "pression" in regime:
        score = 38.0 - clamp(trend_strength * 650.0, 0.0, 24.0)
    elif "absent" in regime:
        score = 25.0
    else:
        score = 50.0 + clamp((0.20 * r1 + 0.45 * r5 + 0.35 * r20) * 250.0, -8.0, 8.0)

    # Petite pénalité si la corrélation au ticker est très faible : participation moins exploitable.
    if corr is not None and abs(corr) < 0.10:
        score -= 5.0

    return clamp(score)


def build_futures_breadth_participation_monitor(
    macro_df: pd.DataFrame,
    macro_summary: Optional[Dict[str, Any]] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Futures Breadth / Internal Participation Monitor.

    Objectif :
    - mesurer si le tape futures/macro est large ou concentré ;
    - distinguer support diffus vs support porté par 1-2 familles ;
    - identifier les poches de pression internes.

    Prudence :
    - utilise uniquement les proxies déjà chargés dans macro_df ;
    - ne télécharge rien ;
    - ne modifie aucun score options, gamma, greeks, macro ou decision gate.
    """
    macro_summary = macro_summary or {}

    empty_summary = {
        "breadth_state": "N/A",
        "breadth_score": None,
        "family_support": 0,
        "family_pressure": 0,
        "family_neutral": 0,
        "proxy_support": 0,
        "proxy_pressure": 0,
        "proxy_neutral": 0,
        "leader_family": "N/A",
        "laggard_family": "N/A",
        "concentration_risk": None,
        "message": "Participation futures/macro indisponible.",
        "proxy_decomp": pd.DataFrame(),
    }

    if macro_df is None or macro_df.empty:
        return pd.DataFrame(), empty_summary

    df = macro_df.copy()

    required = ["Ticker", "Regime"]
    if any(c not in df.columns for c in required):
        return pd.DataFrame(), empty_summary

    for col in ["1D", "5D", "20D", "Vol 20D", "Beta ticker", "Corr"]:
        if col not in df.columns:
            df[col] = np.nan
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["Family"] = df.apply(_futures_vol_family, axis=1)
    df["Participation score num"] = df.apply(_participation_score_from_row, axis=1)

    def _proxy_regime(row: pd.Series) -> str:
        s = safe_float(row.get("Participation score num"), 50.0) or 50.0
        regime = str(row.get("Regime", "")).lower()

        if "absent" in regime:
            return "Données absentes"
        if s >= 72:
            return "Participation forte"
        if s >= 58:
            return "Support participatif"
        if s <= 35:
            return "Pression interne forte"
        if s <= 43:
            return "Pression interne"
        return "Neutre"

    df["Participation regime"] = df.apply(_proxy_regime, axis=1)

    proxy_support = int(df["Participation regime"].astype(str).str.contains("Support|Participation forte", case=False, na=False).sum())
    proxy_pressure = int(df["Participation regime"].astype(str).str.contains("Pression", case=False, na=False).sum())
    proxy_neutral = int(len(df) - proxy_support - proxy_pressure)

    family_rows = []

    family_weights = {
        "Equity futures": 1.20,
        "Equity ETF": 1.00,
        "Semis / leadership": 1.15,
        "Volatility": 1.20,
        "Rates": 1.10,
        "Dollar / FX": 1.10,
        "Commodities": 0.85,
        "Other": 0.75,
    }

    for family, g in df.groupby("Family"):
        g = g.copy()

        proxy_count = int(len(g))
        support_count = int(g["Participation regime"].astype(str).str.contains("Support|Participation forte", case=False, na=False).sum())
        pressure_count = int(g["Participation regime"].astype(str).str.contains("Pression", case=False, na=False).sum())
        neutral_count = int(proxy_count - support_count - pressure_count)

        median_score = safe_float(g["Participation score num"].median(), 50.0) or 50.0
        dispersion = safe_float(g["Participation score num"].std(ddof=0), 0.0) or 0.0

        support_ratio = support_count / max(proxy_count, 1)
        pressure_ratio = pressure_count / max(proxy_count, 1)

        family_score = clamp(
            0.62 * median_score
            + 24.0 * support_ratio
            - 22.0 * pressure_ratio
            - 0.18 * dispersion
            + (4.0 if proxy_count >= 2 else 0.0)
        )

        if family_score >= 75:
            family_regime = "Participation large"
        elif family_score >= 60:
            family_regime = "Support participatif"
        elif family_score <= 38:
            family_regime = "Participation fragile"
        elif family_score <= 45:
            family_regime = "Pression interne"
        else:
            family_regime = "Neutre"

        if support_count >= 2 and pressure_count == 0:
            lecture = "Participation familiale large : plusieurs proxies confirment le même sens."
        elif support_count >= 1 and pressure_count == 0:
            lecture = "Participation familiale constructive mais encore concentrée."
        elif pressure_count >= 2:
            lecture = "Pression interne large dans cette famille."
        elif pressure_count >= 1:
            lecture = "Pression interne ponctuelle à surveiller."
        else:
            lecture = "Famille neutre ou mixte, sans participation nette."

        family_rows.append({
            "Family": family,
            "Tickers": ", ".join([str(x) for x in g["Ticker"].dropna().unique().tolist()]),
            "Proxy count": proxy_count,
            "Support proxies": support_count,
            "Pressure proxies": pressure_count,
            "Neutral proxies": neutral_count,
            "Family weight": family_weights.get(str(family), 0.75),
            "Score num": family_score,
            "Score": fmt_score(family_score),
            "Regime": family_regime,
            "Median 1D": safe_float(g["1D"].median()),
            "Median 5D": safe_float(g["5D"].median()),
            "Median 20D": safe_float(g["20D"].median()),
            "Median vol 20D": safe_float(g["Vol 20D"].median()),
            "Median beta": safe_float(g["Beta ticker"].median()),
            "Median corr": safe_float(g["Corr"].median()),
            "Dispersion": dispersion,
            "Lecture": lecture,
        })

    family_df = pd.DataFrame(family_rows)

    if family_df.empty:
        return pd.DataFrame(), empty_summary

    family_df = family_df.sort_values("Score num", ascending=False).reset_index(drop=True)

    family_support = int(
        family_df["Regime"]
        .astype(str)
        .str.contains("Support|Participation large", case=False, na=False)
        .sum()
    )

    # Prudence logique :
    # "Participation fragile" = faiblesse / manque de participation,
    # mais pas une vraie pression interne.
    family_pressure = int(
        family_df["Regime"]
        .astype(str)
        .str.contains("Pression", case=False, na=False)
        .sum()
    )

    family_fragile = int(
        family_df["Regime"]
        .astype(str)
        .str.contains("fragile", case=False, na=False)
        .sum()
    )

    family_neutral = int(len(family_df) - family_support - family_pressure)

    weighted_score = safe_float(
        np.average(
            pd.to_numeric(family_df["Score num"], errors="coerce").fillna(50.0),
            weights=pd.to_numeric(family_df["Family weight"], errors="coerce").fillna(1.0),
        ),
        50.0,
    ) or 50.0

    family_breadth_score = clamp((family_support / max(len(family_df), 1)) * 100.0)
    proxy_breadth_score = clamp((proxy_support / max(len(df), 1)) * 100.0)

    top_family_score = safe_float(family_df["Score num"].max(), 50.0) or 50.0
    second_family_score = safe_float(family_df["Score num"].nlargest(2).iloc[-1], top_family_score) if len(family_df) >= 2 else top_family_score

    leader_gap = max(0.0, top_family_score - (second_family_score or top_family_score))
    concentration_risk = clamp(leader_gap / 35.0 * 100.0)

    breadth_score = clamp(
        0.58 * weighted_score
        + 0.27 * family_breadth_score
        + 0.15 * proxy_breadth_score
        - 8.0 * family_pressure
        - 3.0 * family_fragile
        - 0.08 * concentration_risk
    )

    if breadth_score >= 75:
        breadth_state = "Participation large"
        message = "Participation futures/macro large : plusieurs familles confirment le tape."

    elif breadth_score >= 60:
        breadth_state = "Participation constructive"
        message = "Participation futures/macro constructive : soutien visible, mais pas parfaitement généralisé."

    elif breadth_score >= 42:
        breadth_state = "Participation partielle"
        message = "Participation futures/macro partielle : soutien visible, mais largeur interne incomplète."

    elif family_pressure == 0 and proxy_support > proxy_pressure:
        breadth_state = "Participation fragile"
        message = "Participation futures/macro fragile mais non divergente : soutien présent, encore trop concentré."

    else:
        breadth_state = "Participation faible"
        message = "Participation futures/macro faible : soutien trop concentré ou présence de pression interne."

    if family_pressure > 0 and breadth_score >= 60:
        message += " Une ou plusieurs familles restent toutefois en divergence."

    leader_family = str(family_df.iloc[0].get("Family", "N/A"))
    laggard_family = str(family_df.sort_values("Score num", ascending=True).iloc[0].get("Family", "N/A"))

    proxy_decomp = df.copy()
    proxy_decomp["Score"] = proxy_decomp["Participation score num"].map(fmt_score)

    proxy_cols = [
        "Family",
        "Ticker",
        "Instrument",
        "Type",
        "Regime",
        "Participation regime",
        "Score",
        "1D",
        "5D",
        "20D",
        "Vol 20D",
        "Beta ticker",
        "Corr",
        "Lecture",
    ]

    proxy_decomp = proxy_decomp[[c for c in proxy_cols if c in proxy_decomp.columns]].copy()

    summary = {
        "breadth_state": breadth_state,
        "breadth_score": breadth_score,
        "family_support": family_support,
        "family_pressure": family_pressure,
        "family_fragile": family_fragile,
        "family_neutral": family_neutral,
        "proxy_support": proxy_support,
        "proxy_pressure": proxy_pressure,
        "proxy_neutral": proxy_neutral,
        "leader_family": leader_family,
        "laggard_family": laggard_family,
        "concentration_risk": concentration_risk,
        "message": message,
        "proxy_decomp": proxy_decomp,
    }

    return family_df, summary


def render_futures_breadth_participation_monitor(
    macro_df: pd.DataFrame,
    macro_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Affichage Futures Breadth / Internal Participation Monitor.
    À placer dans Futures Tape après le bloc Volatility / Risk Compression.
    """
    st.subheader("Futures Breadth / Internal Participation Monitor")

    breadth_df, summary = build_futures_breadth_participation_monitor(
        macro_df=macro_df,
        macro_summary=macro_summary,
    )

    if breadth_df is None or breadth_df.empty:
        st.info("Breadth futures indisponible : données futures/proxies insuffisantes.")
        return summary

    render_card_grid([
        (
            "Breadth state",
            str(summary.get("breadth_state", "N/A")),
            fmt_score(summary.get("breadth_score")),
        ),
        (
            "Family breadth",
            f"{fmt_int(summary.get('family_support'))} support / {fmt_int(summary.get('family_pressure'))} pression",
            f"{fmt_int(summary.get('family_neutral'))} neutres dont {fmt_int(summary.get('family_fragile'))} fragiles",
        ),
        (
            "Proxy breadth",
            f"{fmt_int(summary.get('proxy_support'))} support / {fmt_int(summary.get('proxy_pressure'))} pression",
            f"{fmt_int(summary.get('proxy_neutral'))} neutres",
        ),
        (
            "Leader / laggard",
            str(summary.get("leader_family", "N/A")),
            "Faible : " + str(summary.get("laggard_family", "N/A")),
        ),
    ])

    score = safe_float(summary.get("breadth_score"), 50.0) or 50.0

    if score >= 75:
        st.info(str(summary.get("message", "Participation futures/macro large.")))
    elif score >= 55:
        st.info(str(summary.get("message", "Participation futures/macro constructive mais partielle.")))
    else:
        st.warning(str(summary.get("message", "Participation futures/macro faible ou divergente.")))

    plot_df = breadth_df.sort_values("Score num", ascending=False).copy()

    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            x=plot_df["Family"],
            y=plot_df["Score num"],
            name="Breadth score",
            hovertemplate=(
                "Family %{x}<br>"
                "Score %{y:.0f}/100"
                "<extra></extra>"
            ),
        )
    )

    fig.add_hline(y=58, line_dash="dot", line_color="rgba(90,160,255,0.75)")
    fig.add_hline(y=50, line_dash="dash", line_color="white")
    fig.add_hline(y=42, line_dash="dot", line_color="orange")

    fig.update_layout(
        title="Futures internal participation — score par famille",
        xaxis_title="Famille",
        yaxis_title="Score",
    )

    st.plotly_chart(apply_dark_layout(fig, 460), width="stretch")

    family_display = breadth_df.copy()

    family_display["Median 1D"] = family_display["Median 1D"].map(fmt_signed_pct)
    family_display["Median 5D"] = family_display["Median 5D"].map(fmt_signed_pct)
    family_display["Median 20D"] = family_display["Median 20D"].map(fmt_signed_pct)
    family_display["Median vol 20D"] = family_display["Median vol 20D"].map(fmt_pct)
    family_display["Median beta"] = family_display["Median beta"].map(lambda x: fmt_num(x, 2))
    family_display["Median corr"] = family_display["Median corr"].map(lambda x: fmt_num(x, 2))
    family_display["Family weight"] = family_display["Family weight"].map(lambda x: fmt_num(x, 2))
    family_display["Dispersion"] = family_display["Dispersion"].map(lambda x: fmt_num(x, 1))

    family_cols = [
        "Family",
        "Tickers",
        "Proxy count",
        "Support proxies",
        "Pressure proxies",
        "Neutral proxies",
        "Family weight",
        "Score",
        "Regime",
        "Median 1D",
        "Median 5D",
        "Median 20D",
        "Median vol 20D",
        "Median beta",
        "Median corr",
        "Dispersion",
        "Lecture",
    ]

    st.dataframe(
        family_display[[c for c in family_cols if c in family_display.columns]],
        width="stretch",
        hide_index=True,
    )

    proxy_decomp = summary.get("proxy_decomp", pd.DataFrame())

    if proxy_decomp is not None and not proxy_decomp.empty:
        with st.expander("Voir proxies participation détaillés", expanded=False):
            proxy_display = proxy_decomp.copy()

            for c in ["1D", "5D", "20D"]:
                if c in proxy_display.columns:
                    proxy_display[c] = proxy_display[c].map(fmt_signed_pct)

            if "Vol 20D" in proxy_display.columns:
                proxy_display["Vol 20D"] = proxy_display["Vol 20D"].map(fmt_pct)

            if "Beta ticker" in proxy_display.columns:
                proxy_display["Beta ticker"] = proxy_display["Beta ticker"].map(lambda x: fmt_num(x, 2))

            if "Corr" in proxy_display.columns:
                proxy_display["Corr"] = proxy_display["Corr"].map(lambda x: fmt_num(x, 2))

            st.dataframe(
                proxy_display,
                width="stretch",
                hide_index=True,
            )

    st.caption(
        "Futures Breadth / Internal Participation Monitor = lecture mécanique de la largeur interne du tape futures/macro. "
        "Il mesure si le soutien est diffus ou concentré par famille/proxy. "
        "Ce bloc ne modifie aucun score options, gamma, greeks, macro ou decision gate."
    )

    return summary


# ============================================================
# Futures Final Risk Stack — Liquidity / Beta Stability / Stress / Divergence / Decision
# À coller dans options_futures.py après render_futures_breadth_participation_monitor(...)
# et avant render_gamma_tab(...).
# ============================================================


def _futures_core_family(row: pd.Series) -> str:
    """
    Famille locale futures/macro.
    Duplication volontaire : évite de dépendre d'un bloc précédent et limite les effets de bord.
    """
    ticker = str(row.get("Ticker", "")).upper().strip()
    typ = str(row.get("Type", ""))

    if ticker in ["NQ=F", "ES=F", "YM=F", "RTY=F"]:
        return "Equity futures"
    if ticker in ["QQQ", "SPY"]:
        return "Equity ETF"
    if ticker in ["SMH", "SOXX"]:
        return "Semis / leadership"
    if ticker in ["^VIX", "VIX"]:
        return "Volatility"
    if ticker in ["^TNX", "^TYX", "^FVX"]:
        return "Rates"
    if ticker in ["DX-Y.NYB", "DXY", "UUP"]:
        return "Dollar / FX"
    if ticker in ["CL=F", "GC=F"]:
        return "Commodities"

    if "Volatility" in typ:
        return "Volatility"
    if "Rates" in typ:
        return "Rates"
    if "FX" in typ:
        return "Dollar / FX"
    if "Sector" in typ:
        return "Sector / leadership"
    if "Fut" in typ or "future" in typ.lower():
        return "Other futures"

    return "Other proxy"


def _futures_family_order(family: str) -> int:
    order = {
        "Equity futures": 1,
        "Equity ETF": 2,
        "Semis / leadership": 3,
        "Volatility": 4,
        "Rates": 5,
        "Dollar / FX": 6,
        "Commodities": 7,
        "Sector / leadership": 8,
        "Other futures": 9,
        "Other proxy": 99,
    }
    return order.get(str(family), 99)


def _futures_family_weight(family: str) -> float:
    weights = {
        "Equity futures": 1.20,
        "Equity ETF": 1.05,
        "Semis / leadership": 1.15,
        "Volatility": 1.25,
        "Rates": 1.10,
        "Dollar / FX": 1.10,
        "Commodities": 0.65,
        "Sector / leadership": 0.85,
        "Other futures": 0.75,
        "Other proxy": 0.55,
    }
    return float(weights.get(str(family), 0.70))


def _futures_regime_support_score(regime: Any, fallback: float = 50.0) -> float:
    """
    Convertit un régime textuel en score de support 0-100.
    Ici score élevé = support du tape ; score bas = pression.
    """
    txt = str(regime or "").lower()

    if "support fort" in txt or "momentum fort" in txt or "surperformance forte" in txt:
        return 82.0
    if "support" in txt or "constructif" in txt or "surperformance" in txt:
        return 64.0
    if "pression forte" in txt or "sous-performance forte" in txt:
        return 22.0
    if "pression" in txt or "défavorable" in txt or "sous-performance" in txt:
        return 36.0
    if "diverg" in txt:
        return 45.0
    if "neutre" in txt or "mixte" in txt:
        return 50.0

    return fallback


def _futures_base_proxy_frame(macro_df: pd.DataFrame) -> pd.DataFrame:
    if macro_df is None or macro_df.empty:
        return pd.DataFrame()

    df = macro_df.copy()
    df["Family"] = df.apply(_futures_core_family, axis=1)
    df["_family_order"] = df["Family"].map(_futures_family_order)
    df["_family_weight"] = df["Family"].map(_futures_family_weight)

    scores = []
    for _, row in df.iterrows():
        fallback = 50.0
        r1 = safe_float(row.get("1D"), 0.0) or 0.0
        r5 = safe_float(row.get("5D"), 0.0) or 0.0
        move = 0.45 * r1 + 0.55 * r5
        ticker = str(row.get("Ticker", "")).upper().strip()
        role = DEFAULT_FUTURES_SYMBOLS.get(ticker, {}).get("risk_role", "mixed")

        if role == "risk_on":
            fallback = clamp(50.0 + move * 700.0)
        elif role == "risk_off":
            fallback = clamp(50.0 - move * 700.0)
        elif role == "pressure_up":
            fallback = clamp(50.0 - move * 500.0)
        else:
            fallback = clamp(50.0 + move * 250.0)

        scores.append(_futures_regime_support_score(row.get("Regime"), fallback=fallback))

    df["Support score num"] = scores
    return df


def _weighted_mean_or_none(values: Iterable[Any], weights: Iterable[Any]) -> Optional[float]:
    vals = pd.to_numeric(pd.Series(list(values)), errors="coerce")
    w = pd.to_numeric(pd.Series(list(weights)), errors="coerce").fillna(0.0)
    mask = vals.notna() & w.notna() & (w > 0)
    if not mask.any():
        clean = vals.dropna()
        return safe_float(clean.mean()) if not clean.empty else None
    return safe_float(np.average(vals[mask], weights=w[mask]))


# ============================================================
# 1) Futures Liquidity / Microstructure Monitor
# ============================================================

def _futures_history_microstructure_stats(symbol: str, period: str = "3mo") -> Dict[str, Any]:
    hist = get_history_cached(symbol, period=period, interval="1d")
    df = normalize_price_frame(hist)

    empty = {
        "last_volume": None,
        "median_volume_20d": None,
        "volume_ratio": None,
        "zero_volume_ratio": None,
        "range_ratio": None,
        "move_z": None,
        "data_lag_days": None,
        "obs": 0,
        "micro_risk_score": 70.0,
        "volume_available": False,
    }

    if df is None or df.empty or "adj_close" not in df.columns:
        return empty

    obs = int(len(df))
    close = pd.to_numeric(df["adj_close"], errors="coerce").dropna()

    if len(close) < 10:
        out = dict(empty)
        out["obs"] = obs
        out["micro_risk_score"] = 65.0
        return out

    ret = np.log(close / close.shift(1)).replace([np.inf, -np.inf], np.nan).dropna()
    last_ret = safe_float(ret.iloc[-1]) if not ret.empty else None
    sigma20 = safe_float(ret.tail(20).std(ddof=1)) if len(ret) >= 10 else None
    move_z = abs(last_ret) / sigma20 if last_ret is not None and sigma20 is not None and sigma20 > _EPS else None

    volume_available = False
    last_volume = None
    median_volume_20d = None
    volume_ratio = None
    zero_volume_ratio = None

    if "volume" in df.columns:
        vol = pd.to_numeric(df["volume"], errors="coerce")
        non_missing = vol.dropna()
        if not non_missing.empty and safe_float(non_missing.tail(30).sum(), 0.0) > 0:
            volume_available = True
            last_volume = safe_float(non_missing.iloc[-1])
            median_volume_20d = safe_float(non_missing.tail(20).median())
            if median_volume_20d is not None and median_volume_20d > 0:
                volume_ratio = (last_volume or 0.0) / median_volume_20d
            zero_volume_ratio = safe_float((non_missing.tail(30) <= 0).mean())

    range_ratio = None
    if all(c in df.columns for c in ["high", "low", "close"]):
        high = pd.to_numeric(df["high"], errors="coerce")
        low = pd.to_numeric(df["low"], errors="coerce")
        px = pd.to_numeric(df["close"], errors="coerce")
        daily_range = ((high - low) / px.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).dropna()
        if len(daily_range) >= 10:
            last_range = safe_float(daily_range.iloc[-1])
            median_range = safe_float(daily_range.tail(20).median())
            if last_range is not None and median_range is not None and median_range > 0:
                range_ratio = last_range / median_range

    data_lag_days = None
    if "date" in df.columns and not df["date"].dropna().empty:
        last_date = pd.to_datetime(df["date"].dropna().iloc[-1], errors="coerce")
        if pd.notna(last_date):
            data_lag_days = max(int((pd.Timestamp(datetime.utcnow().date()) - pd.Timestamp(last_date).normalize()).days), 0)

    if volume_available:
        vr = safe_float(volume_ratio)
        if vr is None:
            volume_pressure = 55.0
        elif vr < 0.35:
            volume_pressure = 78.0
        elif vr < 0.70:
            volume_pressure = 58.0
        elif vr > 3.00:
            volume_pressure = 52.0
        else:
            volume_pressure = 28.0
        zvr = safe_float(zero_volume_ratio, 0.0) or 0.0
        if zvr >= 0.20:
            volume_pressure = max(volume_pressure, 70.0)
    else:
        volume_pressure = 45.0

    mz = safe_float(move_z)
    noise_pressure = 35.0 if mz is None else clamp((mz - 0.75) / 2.50 * 100.0)
    rr = safe_float(range_ratio)
    range_pressure = 35.0 if rr is None else clamp((rr - 0.85) / 2.00 * 100.0)

    if data_lag_days is None:
        data_pressure = 55.0
    elif data_lag_days <= 3:
        data_pressure = 15.0
    elif data_lag_days <= 7:
        data_pressure = 40.0
    else:
        data_pressure = 78.0

    obs_pressure = 0.0 if obs >= 45 else 12.0 if obs >= 25 else 25.0
    micro_risk_score = clamp(
        0.32 * volume_pressure
        + 0.26 * noise_pressure
        + 0.20 * range_pressure
        + 0.16 * data_pressure
        + 0.06 * obs_pressure
    )

    return {
        "last_volume": last_volume,
        "median_volume_20d": median_volume_20d,
        "volume_ratio": volume_ratio,
        "zero_volume_ratio": zero_volume_ratio,
        "range_ratio": range_ratio,
        "move_z": move_z,
        "data_lag_days": data_lag_days,
        "obs": obs,
        "micro_risk_score": micro_risk_score,
        "volume_available": volume_available,
    }


def build_futures_liquidity_microstructure_monitor(
    macro_df: pd.DataFrame,
    macro_summary: Optional[Dict[str, Any]] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    macro_summary = macro_summary or {}

    empty_summary = {
        "liquidity_state": "Indisponible",
        "liquidity_risk_score": None,
        "primary_fragility": "N/A",
        "coverage": 0,
        "volume_coverage": 0,
        "message": "Liquidity / microstructure indisponible.",
        "proxy_decomp": pd.DataFrame(),
    }

    base = _futures_base_proxy_frame(macro_df)
    if base.empty:
        return pd.DataFrame(), empty_summary

    rows = []
    for _, row in base.iterrows():
        ticker = str(row.get("Ticker", "")).upper().strip()
        stats = _futures_history_microstructure_stats(ticker)
        risk = safe_float(stats.get("micro_risk_score"), 65.0) or 65.0

        if risk >= 75:
            regime = "Microstructure fragile"
            lecture = "Volume, range ou fraîcheur des données fragiles : signal futures moins exploitable."
        elif risk >= 55:
            regime = "Liquidity à surveiller"
            lecture = "Microstructure exploitable mais bruit ou volume à surveiller."
        elif risk >= 35:
            regime = "Liquidity correcte"
            lecture = "Volume et range globalement exploitables."
        else:
            regime = "Microstructure stable"
            lecture = "Lecture futures propre : pas de fragilité microstructure majeure."

        rows.append({
            "Family": row.get("Family"),
            "Ticker": ticker,
            "Instrument": row.get("Instrument"),
            "Regime": regime,
            "Risk score num": risk,
            "Score": fmt_score(risk),
            "Last volume": stats.get("last_volume"),
            "Median volume 20D": stats.get("median_volume_20d"),
            "Volume ratio": stats.get("volume_ratio"),
            "Zero-volume ratio": stats.get("zero_volume_ratio"),
            "Range ratio": stats.get("range_ratio"),
            "Move z-score": stats.get("move_z"),
            "Data lag days": stats.get("data_lag_days"),
            "Obs": stats.get("obs"),
            "Volume available": bool(stats.get("volume_available")),
            "_family_order": row.get("_family_order"),
            "_family_weight": row.get("_family_weight"),
            "Lecture": lecture,
        })

    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(), empty_summary

    family_rows = []
    for family, g in out.groupby("Family"):
        risk = _weighted_mean_or_none(g["Risk score num"], g["_family_weight"])
        risk = safe_float(risk, 50.0) or 50.0
        regime = "Fragile" if risk >= 75 else "À surveiller" if risk >= 55 else "Correcte" if risk >= 35 else "Stable"
        family_rows.append({
            "Family": family,
            "Tickers": ", ".join(g["Ticker"].astype(str).tolist()),
            "Proxy count": int(len(g)),
            "Risk score num": risk,
            "Score": fmt_score(risk),
            "Regime": regime,
            "Median volume ratio": safe_float(pd.to_numeric(g["Volume ratio"], errors="coerce").median()),
            "Median move z-score": safe_float(pd.to_numeric(g["Move z-score"], errors="coerce").median()),
            "Median range ratio": safe_float(pd.to_numeric(g["Range ratio"], errors="coerce").median()),
            "Volume coverage": int(g["Volume available"].sum()),
            "_order": _futures_family_order(family),
            "Lecture": "Famille principale de fragilité microstructure." if risk >= 55 else "Famille microstructure exploitable.",
        })

    family_df = pd.DataFrame(family_rows).sort_values(["Risk score num", "_order"], ascending=[False, True]).reset_index(drop=True)
    weights = family_df["Family"].map(_futures_family_weight)
    liquidity_risk = _weighted_mean_or_none(family_df["Risk score num"], weights)
    liquidity_risk = safe_float(liquidity_risk, 50.0) or 50.0
    primary_fragility = str(family_df.iloc[0].get("Family", "N/A"))
    coverage = int(len(out))
    volume_coverage = int(out["Volume available"].sum())

    if liquidity_risk >= 75:
        liquidity_state = "Microstructure fragile"
        message = "Liquidity/microstructure fragile : attention aux faux signaux futures, volume ou stale data."
    elif liquidity_risk >= 55:
        liquidity_state = "Liquidity à surveiller"
        message = "Liquidity futures à surveiller : les proxies restent lisibles mais pas parfaitement propres."
    elif liquidity_risk >= 35:
        liquidity_state = "Liquidity correcte"
        message = "Liquidity futures correcte : pas de blocage microstructure majeur."
    else:
        liquidity_state = "Microstructure stable"
        message = "Microstructure futures stable : le tape est exploitable."

    summary = {
        "liquidity_state": liquidity_state,
        "liquidity_risk_score": liquidity_risk,
        "primary_fragility": primary_fragility,
        "coverage": coverage,
        "volume_coverage": volume_coverage,
        "message": message,
        "proxy_decomp": out.sort_values("Risk score num", ascending=False).reset_index(drop=True),
    }

    return family_df, summary


def render_futures_liquidity_microstructure_monitor(
    macro_df: pd.DataFrame,
    macro_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    st.subheader("Futures Liquidity / Microstructure Monitor")
    family_df, summary = build_futures_liquidity_microstructure_monitor(macro_df=macro_df, macro_summary=macro_summary)

    if family_df is None or family_df.empty:
        st.info("Liquidity / Microstructure futures indisponible : données historiques insuffisantes.")
        return summary

    render_card_grid([
        ("Liquidity state", str(summary.get("liquidity_state", "N/A")), fmt_score(summary.get("liquidity_risk_score"))),
        ("Primary fragility", str(summary.get("primary_fragility", "N/A")), "Famille la plus bruitée"),
        ("Coverage", f"{fmt_int(summary.get('coverage'))} proxies", f"{fmt_int(summary.get('volume_coverage'))} avec volume"),
        ("Tape usability", "Exploitable" if (safe_float(summary.get("liquidity_risk_score"), 50.0) or 50.0) < 65 else "Fragile", "Microstructure publique"),
    ])

    risk = safe_float(summary.get("liquidity_risk_score"), 50.0) or 50.0
    if risk >= 70:
        st.warning(str(summary.get("message", "Microstructure futures fragile.")))
    elif risk >= 55:
        st.info(str(summary.get("message", "Liquidity futures à surveiller.")))
    else:
        st.info(str(summary.get("message", "Liquidity futures correcte.")))

    plot_df = family_df.sort_values("Risk score num", ascending=False)
    fig = go.Figure()
    fig.add_trace(go.Bar(x=plot_df["Family"], y=plot_df["Risk score num"], name="Microstructure risk", hovertemplate="Famille %{x}<br>Risk %{y:.0f}/100<extra></extra>"))
    fig.add_hline(y=55, line_dash="dot", line_color="orange")
    fig.add_hline(y=35, line_dash="dot", line_color="rgba(120,180,255,.70)")
    fig.update_layout(title="Futures microstructure risk — volume/range/stale data", xaxis_title="Famille", yaxis_title="Risk score")
    fig.update_yaxes(range=[0, 100])
    st.plotly_chart(apply_dark_layout(fig, 430), width="stretch")

    st.dataframe(
        format_display_df(family_df[[c for c in [
            "Family", "Tickers", "Proxy count", "Score", "Regime",
            "Median volume ratio", "Median move z-score", "Median range ratio",
            "Volume coverage", "Lecture",
        ] if c in family_df.columns]]),
        width="stretch",
        hide_index=True,
    )

    proxy_decomp = summary.get("proxy_decomp", pd.DataFrame())
    if isinstance(proxy_decomp, pd.DataFrame) and not proxy_decomp.empty:
        with st.expander("Voir proxies microstructure détaillés", expanded=False):
            st.dataframe(
                format_display_df(proxy_decomp[[c for c in [
                    "Family", "Ticker", "Instrument", "Regime", "Score",
                    "Last volume", "Median volume 20D", "Volume ratio",
                    "Zero-volume ratio", "Range ratio", "Move z-score",
                    "Data lag days", "Obs", "Lecture",
                ] if c in proxy_decomp.columns]]),
                width="stretch",
                hide_index=True,
            )

    st.caption(
        "Futures Liquidity / Microstructure Monitor = diagnostic mécanique du volume, range, bruit de rendement et fraîcheur des séries futures/proxies. "
        "Il sert à juger l'exploitabilité du tape ; il ne modifie aucun score options, gamma, greeks, macro ou decision gate."
    )
    return summary


# ============================================================
# 2) Futures Correlation / Beta Stability Monitor
# ============================================================

def _rolling_beta_corr_stats(target_df: pd.DataFrame, factor_df: pd.DataFrame, lookback: int) -> Dict[str, Any]:
    t = normalize_price_frame(target_df)
    f = normalize_price_frame(factor_df)
    if t.empty or f.empty or "date" not in t.columns or "date" not in f.columns:
        return {"beta": None, "corr": None, "obs": 0}

    tr = t[["date", "adj_close"]].copy()
    fr = f[["date", "adj_close"]].copy()
    tr["target_ret"] = np.log(tr["adj_close"] / tr["adj_close"].shift(1))
    fr["factor_ret"] = np.log(fr["adj_close"] / fr["adj_close"].shift(1))
    merged = pd.merge(tr[["date", "target_ret"]], fr[["date", "factor_ret"]], on="date", how="inner").replace([np.inf, -np.inf], np.nan).dropna()

    if merged.empty:
        return {"beta": None, "corr": None, "obs": 0}

    merged = merged.tail(int(lookback))
    obs = int(len(merged))
    min_obs = 15 if lookback <= 20 else 35
    if obs < min_obs:
        return {"beta": None, "corr": None, "obs": obs}

    var = safe_float(merged["factor_ret"].var(ddof=1))
    cov = safe_float(merged[["target_ret", "factor_ret"]].cov().iloc[0, 1])
    corr = safe_float(merged["target_ret"].corr(merged["factor_ret"]))
    beta = cov / var if var is not None and abs(var) > _EPS and cov is not None else None
    return {"beta": beta, "corr": corr, "obs": obs}


def build_futures_correlation_beta_stability_monitor(
    ticker: str,
    price_data: pd.DataFrame,
    macro_df: pd.DataFrame,
    macro_summary: Optional[Dict[str, Any]] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    macro_summary = macro_summary or {}
    empty_summary = {
        "stability_state": "Indisponible",
        "stability_risk_score": None,
        "primary_instability": "N/A",
        "usable_proxies": 0,
        "message": "Correlation / beta stability indisponible.",
        "proxy_decomp": pd.DataFrame(),
    }

    base = _futures_base_proxy_frame(macro_df)
    target = normalize_price_frame(price_data)
    if base.empty or target.empty:
        return pd.DataFrame(), empty_summary

    rows = []
    for _, row in base.iterrows():
        sym = str(row.get("Ticker", "")).upper().strip()
        hist = get_history_cached(sym, period="9mo", interval="1d")
        s20 = _rolling_beta_corr_stats(target, hist, 20)
        s90 = _rolling_beta_corr_stats(target, hist, 90)

        beta_20 = safe_float(s20.get("beta"))
        beta_90 = safe_float(s90.get("beta"))
        corr_20 = safe_float(s20.get("corr"))
        corr_90 = safe_float(s90.get("corr"))
        obs_20 = safe_int(s20.get("obs"), 0) or 0
        obs_90 = safe_int(s90.get("obs"), 0) or 0
        beta_drift = beta_20 - beta_90 if beta_20 is not None and beta_90 is not None else None
        corr_drift = abs(corr_20) - abs(corr_90) if corr_20 is not None and corr_90 is not None else None

        if beta_20 is None or beta_90 is None or corr_20 is None or corr_90 is None:
            risk = 70.0
            regime = "Stabilité indisponible"
            lecture = "Historique insuffisant ou corrélation non exploitable."
        else:
            beta_drift_abs = abs(beta_drift or 0.0)
            corr_fade = max(abs(corr_90) - abs(corr_20), 0.0)
            corr_low = max(0.45 - abs(corr_20), 0.0)
            risk = clamp(18.0 + clamp(beta_drift_abs / 1.00 * 34.0) + clamp(corr_fade / 0.25 * 26.0) + clamp(corr_low / 0.45 * 22.0))
            if risk >= 75:
                regime = "Beta/corr instable"
                lecture = "Relation proxy/ticker instable : ne pas surpondérer ce proxy."
            elif risk >= 55:
                regime = "Stabilité à surveiller"
                lecture = "Beta ou corrélation bouge : signal exploitable mais moins robuste."
            elif risk >= 35:
                regime = "Stabilité correcte"
                lecture = "Relation proxy/ticker acceptable."
            else:
                regime = "Beta/corr stable"
                lecture = "Relation proxy/ticker stable sur court et moyen terme."

        rows.append({
            "Family": row.get("Family"),
            "Ticker": sym,
            "Instrument": row.get("Instrument"),
            "Risk score num": risk,
            "Score": fmt_score(risk),
            "Regime": regime,
            "Beta 20D": beta_20,
            "Beta 90D": beta_90,
            "Beta drift": beta_drift,
            "Corr 20D": corr_20,
            "Corr 90D": corr_90,
            "Corr drift": corr_drift,
            "Obs 20D": obs_20,
            "Obs 90D": obs_90,
            "_family_order": row.get("_family_order"),
            "_family_weight": row.get("_family_weight"),
            "Lecture": lecture,
        })

    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(), empty_summary

    family_rows = []
    for family, g in out.groupby("Family"):
        risk = _weighted_mean_or_none(g["Risk score num"], g["_family_weight"])
        risk = safe_float(risk, 55.0) or 55.0
        regime = "Instable" if risk >= 75 else "À surveiller" if risk >= 55 else "Correcte" if risk >= 35 else "Stable"
        family_rows.append({
            "Family": family,
            "Tickers": ", ".join(g["Ticker"].astype(str).tolist()),
            "Proxy count": int(len(g)),
            "Risk score num": risk,
            "Score": fmt_score(risk),
            "Regime": regime,
            "Median beta 20D": safe_float(pd.to_numeric(g["Beta 20D"], errors="coerce").median()),
            "Median beta 90D": safe_float(pd.to_numeric(g["Beta 90D"], errors="coerce").median()),
            "Median corr 20D": safe_float(pd.to_numeric(g["Corr 20D"], errors="coerce").median()),
            "Median corr 90D": safe_float(pd.to_numeric(g["Corr 90D"], errors="coerce").median()),
            "_order": _futures_family_order(family),
            "Lecture": "Famille la plus instable." if risk >= 55 else "Famille stable ou exploitable.",
        })

    family_df = pd.DataFrame(family_rows).sort_values(["Risk score num", "_order"], ascending=[False, True]).reset_index(drop=True)
    weights = family_df["Family"].map(_futures_family_weight)
    stability_risk = _weighted_mean_or_none(family_df["Risk score num"], weights)
    stability_risk = safe_float(stability_risk, 50.0) or 50.0
    usable = int((out["Risk score num"] < 70).sum())
    primary_instability = str(family_df.iloc[0].get("Family", "N/A"))

    if stability_risk >= 75:
        stability_state = "Beta/corr instable"
        message = "Stabilité beta/corr fragile : plusieurs proxies deviennent moins fiables."
    elif stability_risk >= 55:
        stability_state = "Stabilité à surveiller"
        message = "Stabilité beta/corr à surveiller : certains proxies perdent en robustesse."
    elif stability_risk >= 35:
        stability_state = "Stabilité correcte"
        message = "Stabilité beta/corr correcte : les proxies restent exploitables."
    else:
        stability_state = "Beta/corr stable"
        message = "Beta/corr stables : le contexte futures/proxies est fiable."

    summary = {
        "stability_state": stability_state,
        "stability_risk_score": stability_risk,
        "primary_instability": primary_instability,
        "usable_proxies": usable,
        "message": message,
        "proxy_decomp": out.sort_values("Risk score num", ascending=False).reset_index(drop=True),
    }
    return family_df, summary


def render_futures_correlation_beta_stability_monitor(
    ticker: str,
    price_data: pd.DataFrame,
    macro_df: pd.DataFrame,
    macro_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    st.subheader("Futures Correlation / Beta Stability Monitor")
    family_df, summary = build_futures_correlation_beta_stability_monitor(ticker=ticker, price_data=price_data, macro_df=macro_df, macro_summary=macro_summary)

    if family_df is None or family_df.empty:
        st.info("Correlation / Beta Stability indisponible : historique insuffisant.")
        return summary

    render_card_grid([
        ("Stability state", str(summary.get("stability_state", "N/A")), fmt_score(summary.get("stability_risk_score"))),
        ("Primary instability", str(summary.get("primary_instability", "N/A")), "Famille la moins stable"),
        ("Usable proxies", fmt_int(summary.get("usable_proxies")), "Risk score < 70"),
        ("Proxy reliability", "Correcte" if (safe_float(summary.get("stability_risk_score"), 50.0) or 50.0) < 60 else "À confirmer", str(ticker).upper()),
    ])

    risk = safe_float(summary.get("stability_risk_score"), 50.0) or 50.0
    if risk >= 70:
        st.warning(str(summary.get("message", "Beta/corr instable.")))
    elif risk >= 55:
        st.info(str(summary.get("message", "Stabilité à surveiller.")))
    else:
        st.info(str(summary.get("message", "Beta/corr stable.")))

    plot_df = family_df.sort_values("Risk score num", ascending=False)
    fig = go.Figure()
    fig.add_trace(go.Bar(x=plot_df["Family"], y=plot_df["Risk score num"], name="Stability risk", hovertemplate="Famille %{x}<br>Risk %{y:.0f}/100<extra></extra>"))
    fig.add_hline(y=55, line_dash="dot", line_color="orange")
    fig.add_hline(y=35, line_dash="dot", line_color="rgba(120,180,255,.70)")
    fig.update_layout(title="Correlation / beta stability — risk par famille", xaxis_title="Famille", yaxis_title="Risk score")
    fig.update_yaxes(range=[0, 100])
    st.plotly_chart(apply_dark_layout(fig, 430), width="stretch")

    st.dataframe(
        format_display_df(family_df[[c for c in [
            "Family", "Tickers", "Proxy count", "Score", "Regime",
            "Median beta 20D", "Median beta 90D", "Median corr 20D", "Median corr 90D", "Lecture",
        ] if c in family_df.columns]]),
        width="stretch",
        hide_index=True,
    )

    proxy_decomp = summary.get("proxy_decomp", pd.DataFrame())
    if isinstance(proxy_decomp, pd.DataFrame) and not proxy_decomp.empty:
        with st.expander("Voir proxies beta/corr détaillés", expanded=False):
            st.dataframe(
                format_display_df(proxy_decomp[[c for c in [
                    "Family", "Ticker", "Instrument", "Score", "Regime", "Beta 20D", "Beta 90D", "Beta drift",
                    "Corr 20D", "Corr 90D", "Corr drift", "Obs 20D", "Obs 90D", "Lecture",
                ] if c in proxy_decomp.columns]]),
                width="stretch",
                hide_index=True,
            )

    st.caption(
        "Correlation / Beta Stability Monitor = comparaison rolling 20D vs 90D entre le ticker et les futures/proxies. "
        "Score élevé = proxy moins robuste ; ce bloc ne modifie aucun score options, gamma, greeks, macro ou decision gate."
    )
    return summary


# ============================================================
# 3) Futures Scenario Stress Matrix
# ============================================================

def _futures_stress_scenarios() -> List[Dict[str, Any]]:
    return [
        {"Scenario": "Risk-on continuation", "Shock family": "Equity + semis up / VIX down", "shocks": {"NQ=F": 0.020, "ES=F": 0.015, "YM=F": 0.012, "RTY=F": 0.018, "QQQ": 0.020, "SPY": 0.015, "SMH": 0.025, "SOXX": 0.025, "^VIX": -0.080, "DX-Y.NYB": -0.004, "^TNX": 0.000}},
        {"Scenario": "Equity futures selloff", "Shock family": "Core futures -3%", "shocks": {"NQ=F": -0.035, "ES=F": -0.030, "YM=F": -0.025, "RTY=F": -0.035, "QQQ": -0.035, "SPY": -0.030, "SMH": -0.040, "SOXX": -0.040, "^VIX": 0.180, "DX-Y.NYB": 0.008, "^TNX": -0.015}},
        {"Scenario": "Vol shock", "Shock family": "VIX +20%", "shocks": {"^VIX": 0.200, "NQ=F": -0.020, "ES=F": -0.018, "QQQ": -0.020, "SPY": -0.018}},
        {"Scenario": "Rates shock", "Shock family": "10Y yield up", "shocks": {"^TNX": 0.060, "NQ=F": -0.012, "QQQ": -0.012, "SMH": -0.015, "SOXX": -0.015}},
        {"Scenario": "Dollar squeeze", "Shock family": "DXY +2%", "shocks": {"DX-Y.NYB": 0.020, "NQ=F": -0.010, "ES=F": -0.008, "QQQ": -0.010, "SPY": -0.008}},
        {"Scenario": "Semis leadership break", "Shock family": "SMH/SOXX -5%", "shocks": {"SMH": -0.050, "SOXX": -0.050, "NQ=F": -0.018, "QQQ": -0.020}},
        {"Scenario": "Vol compression", "Shock family": "VIX -12%", "shocks": {"^VIX": -0.120, "NQ=F": 0.012, "ES=F": 0.010, "QQQ": 0.012, "SPY": 0.010}},
        {"Scenario": "Risk-on divergence", "Shock family": "Equity up but VIX/DXY/rates up", "shocks": {"NQ=F": 0.012, "ES=F": 0.010, "QQQ": 0.012, "SPY": 0.010, "^VIX": 0.080, "DX-Y.NYB": 0.010, "^TNX": 0.030}},
    ]


def build_futures_scenario_stress_matrix(
    ticker: str,
    price_data: pd.DataFrame,
    macro_df: pd.DataFrame,
    macro_summary: Optional[Dict[str, Any]] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    macro_summary = macro_summary or {}
    empty_summary = {"scenario_state": "Indisponible", "scenario_risk_score": None, "worst_scenario": "N/A", "worst_impact": None, "positive_scenarios": 0, "negative_scenarios": 0, "message": "Futures scenario stress indisponible."}
    base = _futures_base_proxy_frame(macro_df)
    if base.empty:
        return pd.DataFrame(), pd.DataFrame(), empty_summary

    detail_rows = []
    scenario_rows = []

    for scenario in _futures_stress_scenarios():
        scenario_name = str(scenario.get("Scenario", "Scenario"))
        shock_family = str(scenario.get("Shock family", "N/A"))
        shocks = dict(scenario.get("shocks", {}))
        contrib_rows = []

        for _, row in base.iterrows():
            sym = str(row.get("Ticker", "")).upper().strip()
            family = str(row.get("Family", "N/A"))
            beta = safe_float(row.get("Beta ticker"))
            corr = safe_float(row.get("Corr"))
            shock = safe_float(shocks.get(sym))
            if shock is None or beta is None:
                continue
            corr_weight = 0.55 + 0.45 * min(abs(corr) / 0.70, 1.0) if corr is not None else 0.55
            family_weight = _futures_family_weight(family)
            contribution = beta * shock
            contrib_rows.append({"Scenario": scenario_name, "Shock family": shock_family, "Family": family, "Ticker": sym, "Shock": shock, "Beta ticker": beta, "Corr": corr, "Contribution": contribution, "Weight": family_weight * corr_weight})

        if not contrib_rows:
            scenario_rows.append({"Scenario": scenario_name, "Shock family": shock_family, "Estimated target impact": None, "Abs impact": None, "Stress score num": 55.0, "Score": fmt_score(55), "Regime": "Non mesurable", "Family dispersion": None, "Proxy count": 0, "Lecture": "Pas assez de betas exploitables pour ce scénario."})
            continue

        tmp = pd.DataFrame(contrib_rows)
        family_impacts = []
        for family, g in tmp.groupby("Family"):
            impact = _weighted_mean_or_none(g["Contribution"], g["Weight"])
            if impact is not None:
                family_impacts.append({"Family": family, "Impact": impact, "Weight": _futures_family_weight(family)})

        fam = pd.DataFrame(family_impacts)
        if fam.empty:
            estimated_impact = None
            dispersion = None
        else:
            estimated_impact = _weighted_mean_or_none(fam["Impact"], fam["Weight"])
            dispersion = safe_float(pd.to_numeric(fam["Impact"], errors="coerce").std(ddof=0))

        impact = safe_float(estimated_impact, 0.0) or 0.0
        dispersion_val = safe_float(dispersion, 0.0) or 0.0
        stress_score = clamp(45.0 + max(-impact, 0.0) * 750.0 + max(impact, 0.0) * 120.0 + dispersion_val * 350.0)

        if stress_score >= 75:
            regime = "Stress élevé"
            lecture = "Scénario défavorable ou très dispersé : risque d'exécution futures élevé."
        elif stress_score >= 55:
            regime = "Stress à surveiller"
            lecture = "Scénario sensible : impact ou dispersion notable."
        elif stress_score >= 40:
            regime = "Stress contenu"
            lecture = "Scénario absorbable par le tape futures actuel."
        else:
            regime = "Support scénario"
            lecture = "Scénario plutôt favorable au tape."

        scenario_rows.append({"Scenario": scenario_name, "Shock family": shock_family, "Estimated target impact": estimated_impact, "Abs impact": abs(impact), "Stress score num": stress_score, "Score": fmt_score(stress_score), "Regime": regime, "Family dispersion": dispersion, "Proxy count": int(len(tmp)), "Lecture": lecture})
        detail_rows.extend(contrib_rows)

    scenario_df = pd.DataFrame(scenario_rows)
    detail_df = pd.DataFrame(detail_rows)
    if scenario_df.empty:
        return pd.DataFrame(), pd.DataFrame(), empty_summary

    worst = scenario_df.sort_values("Stress score num", ascending=False).iloc[0]
    scenario_risk = safe_float(pd.to_numeric(scenario_df["Stress score num"], errors="coerce").mean(), 55.0) or 55.0
    worst_impact = safe_float(worst.get("Estimated target impact"))
    positive_scenarios = int((pd.to_numeric(scenario_df["Estimated target impact"], errors="coerce") > 0).sum())
    negative_scenarios = int((pd.to_numeric(scenario_df["Estimated target impact"], errors="coerce") < 0).sum())

    if scenario_risk >= 75:
        scenario_state = "Stress futures élevé"
        message = "Scenario stress futures élevé : certains chocs peuvent fortement dégrader le contexte."
    elif scenario_risk >= 55:
        scenario_state = "Stress futures à surveiller"
        message = "Scenario stress futures à surveiller : le tape reste sensible à certains chocs."
    elif scenario_risk >= 40:
        scenario_state = "Stress futures contenu"
        message = "Scenario stress futures contenu : pas de vulnérabilité majeure sur la grille."
    else:
        scenario_state = "Stress futures favorable"
        message = "Scenario stress futures favorable : la grille reste constructive."

    summary = {"scenario_state": scenario_state, "scenario_risk_score": scenario_risk, "worst_scenario": str(worst.get("Scenario", "N/A")), "worst_impact": worst_impact, "positive_scenarios": positive_scenarios, "negative_scenarios": negative_scenarios, "message": message}
    return scenario_df.sort_values("Stress score num", ascending=False).reset_index(drop=True), detail_df, summary


def render_futures_scenario_stress_matrix(
    ticker: str,
    price_data: pd.DataFrame,
    macro_df: pd.DataFrame,
    macro_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    st.subheader("Futures Scenario Stress Matrix")
    scenario_df, detail_df, summary = build_futures_scenario_stress_matrix(ticker=ticker, price_data=price_data, macro_df=macro_df, macro_summary=macro_summary)

    if scenario_df is None or scenario_df.empty:
        st.info("Futures scenario stress indisponible : betas ou proxies insuffisants.")
        return summary

    render_card_grid([
        ("Scenario state", str(summary.get("scenario_state", "N/A")), fmt_score(summary.get("scenario_risk_score"))),
        ("Worst scenario", str(summary.get("worst_scenario", "N/A")), "Impact " + fmt_signed_pct(summary.get("worst_impact"))),
        ("Scenario breadth", f"{fmt_int(summary.get('positive_scenarios'))} positifs / {fmt_int(summary.get('negative_scenarios'))} négatifs", "Grille stress futures"),
        ("Stress usage", "Execution risk", "Pas une prévision"),
    ])

    risk = safe_float(summary.get("scenario_risk_score"), 55.0) or 55.0
    if risk >= 70:
        st.warning(str(summary.get("message", "Scenario stress élevé.")))
    elif risk >= 55:
        st.info(str(summary.get("message", "Scenario stress à surveiller.")))
    else:
        st.info(str(summary.get("message", "Scenario stress contenu.")))

    plot_df = scenario_df.sort_values("Stress score num", ascending=False).copy()
    fig = go.Figure()
    fig.add_trace(go.Bar(x=plot_df["Scenario"], y=plot_df["Estimated target impact"], name="Estimated target impact", hovertemplate="%{x}<br>Impact %{y:+.2%}<extra></extra>"))
    fig.add_hline(y=0, line_dash="dash", line_color="white")
    fig.update_layout(title="Futures scenario stress — impact ticker estimé", xaxis_title="Scenario", yaxis_title="Estimated impact")
    fig.update_yaxes(tickformat=".1%")
    st.plotly_chart(apply_dark_layout(fig, 430), width="stretch")

    st.dataframe(
        format_display_df(scenario_df[[c for c in ["Scenario", "Shock family", "Score", "Regime", "Estimated target impact", "Family dispersion", "Proxy count", "Lecture"] if c in scenario_df.columns]]),
        width="stretch",
        hide_index=True,
    )

    if isinstance(detail_df, pd.DataFrame) and not detail_df.empty:
        with st.expander("Voir contributions scenario détaillées", expanded=False):
            st.dataframe(format_display_df(detail_df[[c for c in ["Scenario", "Family", "Ticker", "Shock", "Beta ticker", "Corr", "Contribution", "Weight"] if c in detail_df.columns]]), width="stretch", hide_index=True)

    st.caption(
        "Futures Scenario Stress Matrix = stress mécanique des proxies futures/macro via beta/corr. "
        "Le résultat sert au cadrage d'exécution ; ce n'est ni une prévision, ni un signal directionnel certain."
    )
    return summary


# ============================================================
# 4) Macro Divergence / Risk-Off Early Warning
# ============================================================

def _family_support_scores_from_macro(macro_df: pd.DataFrame) -> pd.DataFrame:
    base = _futures_base_proxy_frame(macro_df)
    if base.empty:
        return pd.DataFrame()

    rows = []
    for family, g in base.groupby("Family"):
        score = _weighted_mean_or_none(g["Support score num"], g["_family_weight"])
        score = safe_float(score, 50.0) or 50.0
        rows.append({"Family": family, "Score num": score, "Score": fmt_score(score), "Regime": "Support" if score >= 58 else "Pression" if score <= 42 else "Neutre", "Tickers": ", ".join(g["Ticker"].astype(str).tolist()), "_order": _futures_family_order(family)})
    return pd.DataFrame(rows).sort_values("_order").reset_index(drop=True)


def _family_score_lookup(family_df: pd.DataFrame, family: str) -> Optional[float]:
    if family_df is None or family_df.empty:
        return None
    m = family_df[family_df["Family"].astype(str).eq(str(family))]
    if m.empty:
        return None
    return safe_float(m.iloc[0].get("Score num"))


def build_macro_divergence_early_warning(
    macro_df: pd.DataFrame,
    macro_summary: Optional[Dict[str, Any]] = None,
    breadth_summary: Optional[Dict[str, Any]] = None,
    relative_strength_summary: Optional[Dict[str, Any]] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    macro_summary = macro_summary or {}
    breadth_summary = breadth_summary or {}
    relative_strength_summary = relative_strength_summary or {}
    empty_summary = {"divergence_state": "Indisponible", "divergence_risk_score": None, "primary_warning": "N/A", "warning_count": 0, "message": "Macro divergence indisponible."}

    family_df = _family_support_scores_from_macro(macro_df)
    if family_df.empty:
        return pd.DataFrame(), pd.DataFrame(), empty_summary

    equity_fut = _family_score_lookup(family_df, "Equity futures")
    equity_etf = _family_score_lookup(family_df, "Equity ETF")
    semis = _family_score_lookup(family_df, "Semis / leadership")
    vol = _family_score_lookup(family_df, "Volatility")
    rates = _family_score_lookup(family_df, "Rates")
    dollar = _family_score_lookup(family_df, "Dollar / FX")
    equity_vals = [x for x in [equity_fut, equity_etf] if x is not None]
    equity_core = safe_float(np.nanmean(equity_vals)) if equity_vals else None
    rules = []

    def add_rule(name: str, score: float, evidence: str, lecture: str) -> None:
        s = clamp(score)
        status = "Alerte" if s >= 70 else "À surveiller" if s >= 55 else "OK"
        rules.append({"Check": name, "Status": status, "Risk score num": s, "Score": fmt_score(s), "Evidence": evidence, "Lecture": lecture})

    if equity_core is not None and vol is not None:
        if equity_core >= 58 and vol <= 42:
            score, lecture = 78.0, "Les indices soutiennent le tape mais la volatilité contredit : risk-on fragile."
        elif equity_core >= 58 and vol < 50:
            score, lecture = 58.0, "Volatility pas pleinement confirmante malgré support equity."
        else:
            score, lecture = 25.0, "Pas de divergence majeure equity/vol."
        add_rule("Equity vs Volatility", score, f"Equity core {fmt_score(equity_core)} · Volatility {fmt_score(vol)}", lecture)

    pressure_scores = [x for x in [rates, dollar] if x is not None]
    macro_pressure = safe_float(np.nanmean(pressure_scores)) if pressure_scores else None
    if equity_core is not None and macro_pressure is not None:
        if equity_core >= 58 and macro_pressure <= 42:
            score, lecture = 72.0, "Equity support mais dollar/taux en pression : confirmation macro incomplète."
        elif equity_core >= 58 and macro_pressure < 50:
            score, lecture = 55.0, "Dollar/taux ne confirment pas totalement le risk-on."
        else:
            score, lecture = 25.0, "Pas de divergence majeure equity vs dollar/taux."
        add_rule("Equity vs Dollar/Rates", score, f"Equity core {fmt_score(equity_core)} · Dollar/Rates {fmt_score(macro_pressure)}", lecture)

    if semis is not None and equity_fut is not None:
        if semis >= 75 and equity_fut < 55:
            score, lecture = 76.0, "Leadership semis fort mais futures core insuffisants : soutien trop étroit."
        elif semis >= 70 and equity_fut < 60:
            score, lecture = 58.0, "Semis en tête, futures core moins convaincants."
        else:
            score, lecture = 25.0, "Leadership semis cohérent avec le reste du tape."
        add_rule("Semis leadership breadth", score, f"Semis {fmt_score(semis)} · Equity futures {fmt_score(equity_fut)}", lecture)

    family_support = safe_float(breadth_summary.get("family_support"))
    family_pressure = safe_float(breadth_summary.get("family_pressure"))
    breadth_score = safe_float(breadth_summary.get("breadth_score"))
    if family_support is not None or breadth_score is not None:
        if (family_support is not None and family_support <= 2) or (family_pressure is not None and family_pressure >= 2):
            score, lecture = 68.0, "Participation concentrée ou pression interne : confirmation moins large."
        elif breadth_score is not None and breadth_score < 45:
            score, lecture = 62.0, "Breadth faible : le support macro/futures manque de largeur."
        else:
            score, lecture = 28.0, "Breadth compatible avec le tape actuel."
        add_rule("Internal breadth warning", score, f"Family support {fmt_int(family_support)} · pressure {fmt_int(family_pressure)} · score {fmt_score(breadth_score)}", lecture)

    rel_score = safe_float(relative_strength_summary.get("relative_score"))
    rel_state = str(relative_strength_summary.get("relative_state", "N/A"))
    if rel_score is not None:
        if rel_score <= 42:
            score, lecture = 72.0, "Le sous-jacent sous-performe les benchmarks : le tape macro ne se transmet pas bien au ticker."
        elif rel_score < 50:
            score, lecture = 55.0, "Relative strength inférieure à neutre : confirmation sous-jacent partielle."
        else:
            score, lecture = 24.0, "Le sous-jacent confirme suffisamment les benchmarks."
        add_rule("Underlying relative confirmation", score, f"{rel_state} · {fmt_score(rel_score)}", lecture)

    if not rules:
        return family_df, pd.DataFrame(), empty_summary

    rules_df = pd.DataFrame(rules).sort_values("Risk score num", ascending=False).reset_index(drop=True)
    divergence_risk = safe_float(0.60 * pd.to_numeric(rules_df["Risk score num"], errors="coerce").max() + 0.40 * pd.to_numeric(rules_df["Risk score num"], errors="coerce").mean(), 50.0) or 50.0
    divergence_risk = clamp(divergence_risk)
    warning_count = int((pd.to_numeric(rules_df["Risk score num"], errors="coerce") >= 55).sum())
    primary_warning = str(rules_df.iloc[0].get("Check", "N/A"))

    if divergence_risk >= 75:
        divergence_state = "Risk-off warning"
        message = "Early warning actif : plusieurs divergences futures/macro contredisent le tape."
    elif divergence_risk >= 55:
        divergence_state = "Divergence à surveiller"
        message = "Divergence futures/macro à surveiller : confirmation incomplète ou leadership étroit."
    elif divergence_risk >= 35:
        divergence_state = "Divergence contenue"
        message = "Divergence contenue : pas de contradiction majeure."
    else:
        divergence_state = "Tape cohérent"
        message = "Tape futures/macro cohérent : pas d'early warning notable."

    summary = {"divergence_state": divergence_state, "divergence_risk_score": divergence_risk, "primary_warning": primary_warning, "warning_count": warning_count, "message": message}
    return family_df, rules_df, summary


def render_macro_divergence_early_warning(
    macro_df: pd.DataFrame,
    macro_summary: Optional[Dict[str, Any]] = None,
    breadth_summary: Optional[Dict[str, Any]] = None,
    relative_strength_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    st.subheader("Macro Divergence / Risk-Off Early Warning")
    family_df, rules_df, summary = build_macro_divergence_early_warning(macro_df=macro_df, macro_summary=macro_summary, breadth_summary=breadth_summary, relative_strength_summary=relative_strength_summary)

    if rules_df is None or rules_df.empty:
        st.info("Macro Divergence / Early Warning indisponible : données futures/proxies insuffisantes.")
        return summary

    render_card_grid([
        ("Divergence state", str(summary.get("divergence_state", "N/A")), fmt_score(summary.get("divergence_risk_score"))),
        ("Primary warning", str(summary.get("primary_warning", "N/A")), "Risque principal"),
        ("Warnings", fmt_int(summary.get("warning_count")), "Checks ≥ 55/100"),
        ("Tape coherence", "Fragile" if (safe_float(summary.get("divergence_risk_score"), 50.0) or 50.0) >= 55 else "Correcte", "Cross-check macro"),
    ])

    risk = safe_float(summary.get("divergence_risk_score"), 50.0) or 50.0
    if risk >= 70:
        st.warning(str(summary.get("message", "Risk-off warning actif.")))
    elif risk >= 55:
        st.info(str(summary.get("message", "Divergence à surveiller.")))
    else:
        st.info(str(summary.get("message", "Tape cohérent.")))

    plot_df = rules_df.sort_values("Risk score num", ascending=False).copy()
    fig = go.Figure()
    fig.add_trace(go.Bar(x=plot_df["Check"], y=plot_df["Risk score num"], name="Divergence risk", hovertemplate="%{x}<br>Risk %{y:.0f}/100<extra></extra>"))
    fig.add_hline(y=55, line_dash="dot", line_color="orange")
    fig.add_hline(y=35, line_dash="dot", line_color="rgba(120,180,255,.70)")
    fig.update_layout(title="Macro divergence checks — early warning", xaxis_title="Check", yaxis_title="Risk score")
    fig.update_yaxes(range=[0, 100])
    st.plotly_chart(apply_dark_layout(fig, 430), width="stretch")

    st.dataframe(rules_df[[c for c in ["Check", "Status", "Score", "Evidence", "Lecture"] if c in rules_df.columns]], width="stretch", hide_index=True)

    if isinstance(family_df, pd.DataFrame) and not family_df.empty:
        with st.expander("Voir scores famille utilisés", expanded=False):
            st.dataframe(family_df[[c for c in ["Family", "Tickers", "Score", "Regime"] if c in family_df.columns]], width="stretch", hide_index=True)

    st.caption(
        "Macro Divergence / Risk-Off Early Warning = contrôles de cohérence entre futures equity, VIX, dollar, taux, semis, breadth et relative strength. "
        "Il détecte les confirmations incomplètes ; il ne modifie aucun score options, gamma, greeks, macro ou decision gate."
    )
    return summary


# ============================================================
# 5) Futures Decision Overlay
# ============================================================

def _summary_score_any(summary: Optional[Dict[str, Any]], keys: List[str], default: float = 50.0) -> float:
    summary = summary or {}
    for key in keys:
        val = safe_float(summary.get(key))
        if val is not None:
            return clamp(val)
    return float(default)


def build_futures_decision_overlay(
    macro_summary: Optional[Dict[str, Any]] = None,
    leadership_summary: Optional[Dict[str, Any]] = None,
    momentum_summary: Optional[Dict[str, Any]] = None,
    relative_strength_summary: Optional[Dict[str, Any]] = None,
    volatility_summary: Optional[Dict[str, Any]] = None,
    breadth_summary: Optional[Dict[str, Any]] = None,
    liquidity_summary: Optional[Dict[str, Any]] = None,
    stability_summary: Optional[Dict[str, Any]] = None,
    scenario_summary: Optional[Dict[str, Any]] = None,
    divergence_summary: Optional[Dict[str, Any]] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    macro_summary = macro_summary or {}
    leadership_summary = leadership_summary or {}
    momentum_summary = momentum_summary or {}
    relative_strength_summary = relative_strength_summary or {}
    volatility_summary = volatility_summary or {}
    breadth_summary = breadth_summary or {}
    liquidity_summary = liquidity_summary or {}
    stability_summary = stability_summary or {}
    scenario_summary = scenario_summary or {}
    divergence_summary = divergence_summary or {}

    macro_score = _summary_score_any(macro_summary, ["tape_score"], 50.0)
    leadership_risk = _summary_score_any(leadership_summary, ["leadership_risk_score"], 50.0)
    leadership_support = clamp(100.0 - leadership_risk)
    momentum_score = _summary_score_any(momentum_summary, ["momentum_score"], 50.0)
    relative_score = _summary_score_any(relative_strength_summary, ["relative_score"], 50.0)
    vol_pressure = _summary_score_any(volatility_summary, ["vol_pressure_score"], 50.0)
    vol_support = clamp(100.0 - vol_pressure)
    breadth_score = _summary_score_any(breadth_summary, ["breadth_score"], 50.0)

    liquidity_risk = _summary_score_any(liquidity_summary, ["liquidity_risk_score"], 50.0)
    stability_risk = _summary_score_any(stability_summary, ["stability_risk_score"], 50.0)
    scenario_risk = _summary_score_any(scenario_summary, ["scenario_risk_score"], 50.0)
    divergence_risk = _summary_score_any(divergence_summary, ["divergence_risk_score"], 50.0)

    support_score = clamp(0.24 * macro_score + 0.16 * leadership_support + 0.18 * momentum_score + 0.16 * relative_score + 0.12 * vol_support + 0.14 * breadth_score)
    execution_risk = clamp(0.22 * liquidity_risk + 0.20 * stability_risk + 0.24 * scenario_risk + 0.26 * divergence_risk + 0.08 * max(0.0, 50.0 - breadth_score) * 2.0)
    final_score = clamp(0.62 * support_score + 0.38 * (100.0 - execution_risk))

    if final_score >= 72 and execution_risk < 55:
        decision_state, action, sizing = "Futures support validé", "Exécution standard", "Normal"
        message = "Overlay futures favorable : support large et risque d'exécution contenu."
    elif final_score >= 58 and execution_risk < 70:
        decision_state, action, sizing = "Futures constructifs contrôlés", "Standard contrôlé", "Normale contrôlée"
        message = "Overlay futures constructif mais non parfait : exécution possible avec contrôle des niveaux et du tape."
    elif final_score >= 45:
        decision_state, action, sizing = "Futures mixtes", "Entrée progressive", "Progressive"
        message = "Overlay futures mixte : attendre confirmation ou fractionner l'exécution."
    else:
        decision_state, action, sizing = "Futures défavorables", "Attendre confirmation", "Réduite / attente"
        message = "Overlay futures défavorable : le contexte macro/futures ne confirme pas suffisamment."

    primary_risk = max(
        [
            ("Liquidity / Microstructure", liquidity_risk),
            ("Beta/Corr stability", stability_risk),
            ("Scenario stress", scenario_risk),
            ("Macro divergence", divergence_risk),
            ("Breadth weakness", clamp(max(0.0, 50.0 - breadth_score) * 2.0)),
        ],
        key=lambda x: x[1],
    )[0]

    rows = [
        {"Bloc": "Futures decision", "Score": fmt_score(final_score), "Signal": decision_state, "Lecture": message},
        {"Bloc": "Support score", "Score": fmt_score(support_score), "Signal": "Support" if support_score >= 58 else "Mixte" if support_score >= 42 else "Pression", "Lecture": "Agrégation macro, leadership, momentum, relative strength, vol compression et breadth."},
        {"Bloc": "Execution risk", "Score": fmt_score(execution_risk), "Signal": primary_risk, "Lecture": "Agrégation liquidity, beta/corr stability, scenario stress, divergence et breadth weakness."},
        {"Bloc": "Macro tape", "Score": fmt_score(macro_score), "Signal": str(macro_summary.get("tape_state", "N/A")), "Lecture": str(macro_summary.get("message", "N/A"))},
        {"Bloc": "Momentum", "Score": fmt_score(momentum_score), "Signal": str(momentum_summary.get("momentum_state", "N/A")), "Lecture": str(momentum_summary.get("message", "N/A"))},
        {"Bloc": "Relative strength", "Score": fmt_score(relative_score), "Signal": str(relative_strength_summary.get("relative_state", "N/A")), "Lecture": str(relative_strength_summary.get("message", "N/A"))},
        {"Bloc": "Liquidity", "Score": fmt_score(liquidity_risk), "Signal": str(liquidity_summary.get("liquidity_state", "N/A")), "Lecture": str(liquidity_summary.get("message", "N/A"))},
        {"Bloc": "Beta/Corr stability", "Score": fmt_score(stability_risk), "Signal": str(stability_summary.get("stability_state", "N/A")), "Lecture": str(stability_summary.get("message", "N/A"))},
        {"Bloc": "Scenario stress", "Score": fmt_score(scenario_risk), "Signal": str(scenario_summary.get("scenario_state", "N/A")), "Lecture": str(scenario_summary.get("message", "N/A"))},
        {"Bloc": "Macro divergence", "Score": fmt_score(divergence_risk), "Signal": str(divergence_summary.get("divergence_state", "N/A")), "Lecture": str(divergence_summary.get("message", "N/A"))},
    ]

    summary = {
        "futures_decision_state": decision_state,
        "futures_decision_score": final_score,
        "futures_support_score": support_score,
        "futures_execution_risk": execution_risk,
        "futures_action": action,
        "futures_sizing": sizing,
        "primary_futures_risk": primary_risk,
        "message": message,
    }
    return pd.DataFrame(rows), summary


def render_futures_decision_overlay(
    macro_summary: Optional[Dict[str, Any]] = None,
    leadership_summary: Optional[Dict[str, Any]] = None,
    momentum_summary: Optional[Dict[str, Any]] = None,
    relative_strength_summary: Optional[Dict[str, Any]] = None,
    volatility_summary: Optional[Dict[str, Any]] = None,
    breadth_summary: Optional[Dict[str, Any]] = None,
    liquidity_summary: Optional[Dict[str, Any]] = None,
    stability_summary: Optional[Dict[str, Any]] = None,
    scenario_summary: Optional[Dict[str, Any]] = None,
    divergence_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    st.subheader("Futures Decision Overlay")
    overlay_df, summary = build_futures_decision_overlay(
        macro_summary=macro_summary,
        leadership_summary=leadership_summary,
        momentum_summary=momentum_summary,
        relative_strength_summary=relative_strength_summary,
        volatility_summary=volatility_summary,
        breadth_summary=breadth_summary,
        liquidity_summary=liquidity_summary,
        stability_summary=stability_summary,
        scenario_summary=scenario_summary,
        divergence_summary=divergence_summary,
    )

    render_card_grid([
        ("Futures decision", str(summary.get("futures_decision_state", "N/A")), fmt_score(summary.get("futures_decision_score"))),
        ("Action", str(summary.get("futures_action", "N/A")), str(summary.get("futures_sizing", "N/A"))),
        ("Support / risk", f"{fmt_score(summary.get('futures_support_score'))} / {fmt_score(summary.get('futures_execution_risk'))}", "Support score / execution risk"),
        ("Primary risk", str(summary.get("primary_futures_risk", "N/A")), "Risque futures principal"),
    ])

    final_score = safe_float(summary.get("futures_decision_score"), 50.0) or 50.0
    execution_risk = safe_float(summary.get("futures_execution_risk"), 50.0) or 50.0
    if final_score < 45 or execution_risk >= 75:
        st.warning(str(summary.get("message", "Overlay futures défavorable.")))
    elif execution_risk >= 60:
        st.info(str(summary.get("message", "Overlay futures constructif mais à contrôler.")))
    else:
        st.info(str(summary.get("message", "Overlay futures favorable.")))

    if overlay_df is not None and not overlay_df.empty:
        st.dataframe(overlay_df, width="stretch", hide_index=True)

    st.caption(
        "Futures Decision Overlay = synthèse mécanique de la partie futures/macro uniquement. "
        "Il ne remplace pas le risk management, ne modifie aucun score options/gamma/greeks, et ne constitue pas une recommandation d'investissement."
    )
    return summary




def render_gamma_tab(
    metrics: Dict[str, Any],
    spot: float,
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    window_pct: float,
) -> None:
    st.subheader("Gamma Exposure Proxy")

    gex_df = metrics.get("gex_df", pd.DataFrame())
    gamma_flip = metrics.get("gamma_flip")
    gamma_flip_sub = "Cumulative sign change" if gamma_flip is not None else "Aucun flip exploitable ±20%"

    cards = [
        ("Net GEX proxy", fmt_large(metrics.get("net_gex")), "Signed calls/puts"),
        ("Abs GEX proxy", fmt_large(metrics.get("abs_gex")), "Concentration brute"),
        ("Gamma flip", fmt_price(gamma_flip), gamma_flip_sub),
        ("Gamma score", fmt_score(metrics.get("gamma_score")), "Risque de pinning"),
    ]

    render_card_grid(cards)

    render_gex_chart(
        gex_df=gex_df,
        spot=spot,
        gamma_flip=metrics.get("gamma_flip"),
        window_pct=window_pct,
    )

    render_greeks_pressure_proxy(
        calls=calls,
        puts=puts,
        spot=spot,
        window_pct=window_pct,
    )

    render_full_greeks_exposure_dashboard(
        calls=calls,
        puts=puts,
        spot=spot,
        window_pct=window_pct,
    )

    render_expiration_fragility_monitor(
        calls=calls,
        puts=puts,
        metrics=metrics,
        spot=spot,
        window_pct=window_pct,
    )

    render_gamma_scenario_stress_matrix(
        calls=calls,
        puts=puts,
        spot=spot,
        metrics=metrics,
        window_pct=window_pct,
    )

    if gex_df is not None and not gex_df.empty:
        show = gex_df.copy()
        show["distance_spot"] = show["strike"] / max(spot, _EPS) - 1.0
        show = show.sort_values("abs_gex", ascending=False).head(15)

        st.subheader("Top gamma concentration")

        st.dataframe(
            format_display_df(show),
            width="stretch",
            hide_index=True,
        )

    st.caption(
        "Gamma proxy = calcul Black-Scholes approximatif sur IV publique et OI. "
        "Ce n'est pas une mesure institutionnelle de dealer gamma."
    )


def render_futures_tab(ticker: str, price_data: pd.DataFrame, macro_df: pd.DataFrame, macro_summary: Dict[str, Any]) -> None:
    st.subheader("Futures / Macro Tape")

    cards = [
        ("Tape state", str(macro_summary.get("tape_state", "N/A")), fmt_score(macro_summary.get("tape_score"))),
        ("Message", str(macro_summary.get("message", "N/A"))[:32] + "...", "Synthèse"),
    ]
    render_card_grid(cards)

    alert_by_score(
        str(macro_summary.get("message", "Tape macro indisponible.")),
        100 - (safe_float(macro_summary.get("tape_score"), 50) or 50)
    )

    # Nouveau bloc institutionnel futures/macro.
    render_macro_regime_dashboard(macro_df)

    # Confirmation cross-asset : futures, ETF, vol, taux, dollar, semis.
    render_cross_asset_confirmation_matrix(
        macro_df=macro_df,
        macro_summary=macro_summary,
    )

    
    leadership_summary = render_futures_leadership_monitor(
        macro_df=macro_df,
        macro_summary=macro_summary,
    )

    momentum_summary = render_futures_momentum_confirmation(
        macro_df=macro_df,
        macro_summary=macro_summary,
    )

    relative_strength_summary = render_futures_relative_strength_confirmation(
        ticker=ticker,
        price_data=price_data,
        macro_df=macro_df,
        macro_summary=macro_summary,
    )

    volatility_summary = render_futures_volatility_regime_monitor(
        ticker=ticker,
        price_data=price_data,
        macro_df=macro_df,
        macro_summary=macro_summary,
    )

    breadth_summary = render_futures_breadth_participation_monitor(
        macro_df=macro_df,
        macro_summary=macro_summary,
    )

    liquidity_summary = render_futures_liquidity_microstructure_monitor(
        macro_df=macro_df,
        macro_summary=macro_summary,
    )

    stability_summary = render_futures_correlation_beta_stability_monitor(
        ticker=ticker,
        price_data=price_data,
        macro_df=macro_df,
        macro_summary=macro_summary,
    )

    scenario_summary = render_futures_scenario_stress_matrix(
        ticker=ticker,
        price_data=price_data,
        macro_df=macro_df,
        macro_summary=macro_summary,
    )

    divergence_summary = render_macro_divergence_early_warning(
        macro_df=macro_df,
        macro_summary=macro_summary,
        breadth_summary=breadth_summary,
        relative_strength_summary=relative_strength_summary,
    )

    futures_decision_summary = render_futures_decision_overlay(
        macro_summary=macro_summary,
        leadership_summary=leadership_summary,
        momentum_summary=momentum_summary,
        relative_strength_summary=relative_strength_summary,
        volatility_summary=volatility_summary,
        breadth_summary=breadth_summary,
        liquidity_summary=liquidity_summary,
        stability_summary=stability_summary,
        scenario_summary=scenario_summary,
        divergence_summary=divergence_summary,
    )


    st.subheader("Futures / Macro proxies")
    if macro_df is not None and not macro_df.empty:
        display_cols = [
            "Instrument",
            "Ticker",
            "Type",
            "Last",
            "1D",
            "5D",
            "20D",
            "Vol 20D",
            "Beta ticker",
            "Corr",
            "Regime",
            "Lecture",
        ]
        st.dataframe(
            format_display_df(macro_df[[c for c in display_cols if c in macro_df.columns]]),
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("Futures / macro tape indisponible.")

    render_macro_chart(macro_df)

    st.subheader("Macro beta stress")
    stress_df = compute_futures_stress(ticker, price_data, macro_df)
    if not stress_df.empty:
        st.dataframe(format_display_df(stress_df), width="stretch", hide_index=True)

    render_stress_chart(stress_df)

    st.caption(
        "Stress mécanique = beta estimé sur rendements récents × choc du facteur. "
        "Ce n'est pas une prévision."
    )


def render_export_tab(ticker: str, expiration: str, metrics: Dict[str, Any], macro_df: pd.DataFrame, macro_summary: Dict[str, Any]) -> None:
    st.subheader("Export Options & Futures Summary")
    export_df = build_export_df(ticker, expiration, metrics, macro_summary, macro_df)
    st.dataframe(export_df.fillna("N/A"), width="stretch", hide_index=True)
    csv = export_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Télécharger le résumé options/futures CSV",
        csv,
        file_name=f"options_futures_summary_{ticker.upper()}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
    )


# ============================================================
# Main renderer
# ============================================================


def render_options_futures_v1(ticker: str, price_data: pd.DataFrame, analysis: Optional[dict] = None) -> None:
    """
    Main Streamlit entry point.

    Expected app.py usage:
        from options_futures import render_options_futures_v1
        render_options_futures_v1(ticker=ticker, price_data=price_data, analysis=analysis)
    """

    ticker = str(ticker or "").upper().strip()
    analysis = analysis or {}
    spot = get_spot(price_data, analysis)
    try:
        thetadata_api_key = get_thetadata_api_key(st.secrets)
        massive_api_key = get_massive_api_key(st.secrets)
    except Exception:
        thetadata_api_key = None
        massive_api_key = None

    st.title(f"Options & Futures Intelligence — {ticker}")

    if not ticker:
        st.error("Ticker manquant.")
        return
    if spot is None or spot <= 0:
        st.error("Prix spot indisponible : impossible de calculer options/futures correctement.")
        return

    st.caption(
        "Workspace décisionnel : ThetaData/OPRA prioritaire, Massive en second provider et Yahoo en fallback public. "
        "La provenance, la récence et les limitations d'entitlement restent explicites. Aucun ordre n'est transmis."
    )

    expirations, expiration_context = get_option_expirations_auto_cached(
        ticker, thetadata_api_key, massive_api_key
    )
    if not expirations:
        st.warning("Aucune expiration options disponible. La partie futures reste exploitable.")

    default_universe = ", ".join(default_macro_universe(ticker))

    with st.expander("Paramètres options/futures", expanded=False):
        c1, c2, c3 = st.columns([1.2, 1.0, 1.0])
        with c1:
            expiration = None
            if expirations:
                default_exp_idx = select_default_expiration_index(expirations, min_dte=5)
                expiration = st.selectbox(
                    "Expiration options",
                    expirations,
                    index=default_exp_idx,
                    help="Sélection prudente : par défaut, le module évite les expirations trop courtes quand une expiration >= 5 jours existe.",
                )

                selected_dte_preview = days_to_expiration(str(expiration))
                if selected_dte_preview < 3:
                    st.warning(
                        "Expiration très courte / 0DTE : les IV, expected move, gamma et smile peuvent être instables. "
                        "Lecture à utiliser surtout comme diagnostic intraday/OI, pas comme signal structurel."
                    )
            else:
                expiration = "N/A"
        with c2:
            window_pct = st.selectbox("Fenêtre strikes", [0.10, 0.15, 0.20, 0.30, 0.50], index=2, format_func=lambda x: f"±{int(x * 100)}%")
        with c3:
            scan_choice = st.selectbox("Surface expirations", ["6 premières", "12 premières", "Toutes <= 180D"], index=0)

        st.caption(
            "Providers options — ThetaData: " + ("configuré" if thetadata_api_key else "non configuré")
            + " · Massive: " + ("configuré" if massive_api_key else "non configuré")
            + " · Yahoo: fallback automatique"
        )

        futures_product = st.selectbox(
            "Produit futures",
            ["NQ", "ES", "RTY", "CL", "GC", "ZB", "6E"],
            index=0,
            help=(
                "Massive est utilisé en priorité pour la courbe licenciée. Si l'entitlement snapshot manque, "
                "le terminal reconstruit une courbe publique retardée à partir des contrats Yahoo explicites."
            ),
        )

        macro_raw = st.text_area(
            "Futures / proxies macro",
            value=default_universe,
            help="Exemples : NQ=F, ES=F, ^VIX, ^TNX, DX-Y.NYB, QQQ, SPY, SMH, SOXX",
        )

    selected_expirations: List[str] = []
    if expirations:
        if scan_choice == "6 premières":
            selected_expirations = expirations[:6]
        elif scan_choice == "12 premières":
            selected_expirations = expirations[:12]
        else:
            selected_expirations = [e for e in expirations if days_to_expiration(e) <= 180]
            if not selected_expirations:
                selected_expirations = expirations[:6]

    calls = pd.DataFrame()
    puts = pd.DataFrame()
    chain_status = "No options"
    metrics: Dict[str, Any] = {
        "spot": spot,
        "dte": 0,
        "options_risk_score": 50,
        "options_state": "N/A",
        "confidence": 35,
        "confidence_label": "Faible",
        "state_reason": "Chaîne options indisponible.",
    }
    surface = pd.DataFrame()

    if expirations and expiration != "N/A":
        with st.spinner("Téléchargement options chain..."):
            raw_calls, raw_puts, chain_status, data_context = get_option_chain_auto_cached(
                ticker, str(expiration), thetadata_api_key, massive_api_key
            )
            # ThetaData Greeks/IV snapshots include the contemporaneous underlying midpoint.
            # Prefer it for option analytics when available; otherwise preserve the terminal spot.
            vendor_spots: List[float] = []
            for raw_frame in (raw_calls, raw_puts):
                if raw_frame is not None and not raw_frame.empty and "underlyingPrice" in raw_frame.columns:
                    vendor_spots.extend(
                        pd.to_numeric(raw_frame["underlyingPrice"], errors="coerce").dropna().astype(float).tolist()
                    )
            if vendor_spots:
                vendor_spot = safe_float(np.nanmedian(vendor_spots))
                if vendor_spot is not None and vendor_spot > 0:
                    spot = vendor_spot
            calls = clean_chain(raw_calls, "call", str(expiration), spot)
            puts = clean_chain(raw_puts, "put", str(expiration), spot)
            dte = days_to_expiration(str(expiration))
            metrics = compute_options_metrics(calls, puts, spot, dte, price_data)
            metrics["expiration"] = str(expiration)

        with st.spinner("Construction surface multi-expirations..."):
            surface = fetch_surface_auto_cached(
                ticker, tuple(selected_expirations), thetadata_api_key, massive_api_key
            )
    else:
        data_context = dict(expiration_context)

    macro_symbols = clean_ticker_list(macro_raw, default_macro_universe(ticker))
    with st.spinner("Téléchargement futures / macro proxies..."):
        macro_df, macro_summary = compute_macro_tape(ticker, price_data, macro_symbols, period="6mo")

    with st.spinner("Construction de la courbe futures..."):
        futures_curve, futures_context = get_futures_curve_auto_cached(futures_product, massive_api_key)

    st.caption(
        f"{data_context.get('provider', 'Source inconnue')} · {data_context.get('recency', 'UNKNOWN')} · "
        f"Spot {fmt_price(spot)} · Expiration {expiration} · DTE {metrics.get('dte', 0)} · "
        f"Courbe futures {futures_product} · Proxies cross-asset {len(macro_symbols)}"
    )

    tabs = st.tabs([
        "Executive Cockpit",
        "Strategy Lab",
        "Options Market",
        "Positioning / OI",
        "Volatility",
        "Gamma & Greeks",
        "Futures Curve",
        "Export & Audit",
    ])

    with tabs[0]:
        render_executive_workspace(ticker, str(expiration), spot, metrics, macro_summary, calls, puts, data_context)
    with tabs[1]:
        render_strategy_lab(
            ticker=ticker,
            calls=calls,
            puts=puts,
            spot=spot,
            expiration=str(expiration),
            metrics=metrics,
            macro_summary=macro_summary,
            data_context=data_context,
        )
    with tabs[2]:
        render_surface_workspace(ticker, calls, puts, surface, spot, str(expiration), window_pct, data_context)
    with tabs[3]:
        render_positioning_workspace(calls, puts, spot, metrics, window_pct, data_context)
    with tabs[4]:
        render_volatility_workspace(metrics, calls, puts, surface, spot, str(expiration), data_context)
    with tabs[5]:
        render_gamma_workspace(metrics, spot, calls, puts, window_pct, data_context)
    with tabs[6]:
        render_futures_workspace(ticker, price_data, macro_df, macro_summary, futures_curve, futures_context, futures_product)
    with tabs[7]:
        render_export_workspace(
            ticker, str(expiration), metrics, calls, puts, surface, macro_df,
            futures_curve, data_context, futures_context,
        )


def composite_message(composite: float, metrics: Dict[str, Any], macro_summary: Dict[str, Any]) -> str:
    state_reason = str(metrics.get("state_reason", ""))
    tape_state = str(macro_summary.get("tape_state", ""))
    if composite >= 80:
        return "Risque dérivés très élevé : ne pas ignorer IV/OI/futures avant exécution. " + state_reason
    if composite >= 60:
        return "Risque dérivés élevé : setup exploitable seulement avec taille prudente et contrôle du timing. " + state_reason
    if composite >= 35:
        if tape_state == "Risk-off":
            return "Risque dérivés modéré mais tape macro défavorable : attendre confirmation peut être préférable."
        return "Risque dérivés modéré : options/futures ne bloquent pas, mais la lecture reste indicative."
    return "Risque dérivés contenu : pas de signal options/futures bloquant détecté."
