from __future__ import annotations

"""Institutional Behavioral Data Layer (V2.2.1).

This module intentionally separates observed market data from psychological inference.
It is best-effort and non-blocking: every provider can fail independently and all
outputs carry source/coverage metadata. No synthetic market observations are created.
"""

from datetime import datetime, timedelta, timezone
from io import StringIO
from typing import Any
import math
import os

import numpy as np
import pandas as pd
import requests
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay
import streamlit as st

from .data import fetch_price_history

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except Exception:  # pragma: no cover
    yf = None
    YFINANCE_AVAILABLE = False


CBOE_HISTORY_URLS: dict[str, str] = {
    "VIX": "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv",
    "VVIX": "https://cdn.cboe.com/api/global/us_indices/daily_prices/VVIX_History.csv",
    "VIX9D": "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX9D_History.csv",
    # These follow Cboe's public historical-file naming convention. They are
    # best-effort only and automatically fall back to public price proxies.
    "VIX3M": "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX3M_History.csv",
    "SKEW": "https://cdn.cboe.com/api/global/us_indices/daily_prices/SKEW_History.csv",
}

FRED_SERIES: dict[str, str] = {
    "vix_fred": "VIXCLS",
    "hy_oas": "BAMLH0A0HYM2",
    "ig_oas": "BAMLC0A0CM",
    "nfci": "NFCI",
    "nfci_risk": "NFCIRISK",
    "nfci_credit": "NFCICREDIT",
    "nfci_leverage": "NFCILEVERAGE",
    "stlfsi": "STLFSI4",
}

SECTOR_ETFS: tuple[str, ...] = (
    "XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY",
)
BREADTH_ETFS: tuple[str, ...] = (
    "SPY", "RSP", "QQQ", "QQEW", "IWM", "SPHB", "SPLV", *SECTOR_ETFS,
)


def _get_secret(*names: str) -> str:
    for name in names:
        try:
            value = st.secrets.get(name, "")
        except Exception:
            value = ""
        if isinstance(value, str) and value.strip():
            return value.strip()
        env_value = os.getenv(name, "")
        if isinstance(env_value, str) and env_value.strip():
            return env_value.strip()
    return ""


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        x = float(value)
        return x if np.isfinite(x) else default
    except Exception:
        return default


_US_FEDERAL_BDAY = CustomBusinessDay(calendar=USFederalHolidayCalendar())


def _cftc_availability_date(report_date: Any) -> pd.Timestamp | pd.NaT:
    """Conservative daily-availability timestamp for COT/TFF observations.

    CFTC COT/TFF reports generally describe Tuesday positions and are normally
    released Friday at 15:30 ET. For a daily close-based research engine we avoid
    using the release inside that same Friday session and make the observation
    eligible only from the first *full* U.S. federal business session after the
    regular release cycle. Tuesday + four U.S. federal business days gives Monday
    in an ordinary week and automatically moves later around federal holidays.

    This intentionally sacrifices a small amount of freshness to eliminate the
    report-date look-ahead that would occur if Tuesday data were used on Tuesday.
    """
    ts = pd.to_datetime(report_date, errors="coerce", utc=True)
    if pd.isna(ts):
        return pd.NaT
    naive = pd.Timestamp(ts).tz_convert("UTC").normalize().tz_localize(None)
    available = naive + 4 * _US_FEDERAL_BDAY
    return pd.Timestamp(available).tz_localize("UTC")


def _period_start(period: str) -> pd.Timestamp:
    days = {"6mo": 210, "1y": 390, "2y": 780, "5y": 1900, "10y": 3800}.get(str(period).lower(), 780)
    return pd.Timestamp(datetime.now(timezone.utc).date() - timedelta(days=days), tz="UTC")


def _robust_z_last(series: pd.Series, window: int = 252, min_periods: int = 30) -> float | None:
    s = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if len(s) < min_periods:
        return None
    h = s.tail(window)
    med = float(h.median())
    mad = float((h - med).abs().median())
    if mad > 1e-12:
        return float((h.iloc[-1] - med) / (1.4826 * mad))
    sd = float(h.std())
    return float((h.iloc[-1] - med) / sd) if sd > 1e-12 else 0.0


def _z_score_to_100(z: Any, center: float = 50.0, amplitude: float = 32.0) -> float:
    zz = _safe_float(z, 0.0) or 0.0
    return float(np.clip(center + amplitude * np.tanh(zz / 2.0), 0.0, 100.0))


def _last(series: pd.Series) -> float | None:
    s = pd.to_numeric(series, errors="coerce").dropna()
    return _safe_float(s.iloc[-1]) if not s.empty else None


def _ret(frame: pd.DataFrame, days: int) -> float | None:
    if frame is None or frame.empty or "close" not in frame.columns:
        return None
    s = pd.to_numeric(frame["close"], errors="coerce").dropna()
    if len(s) <= days:
        return None
    return _safe_float(s.iloc[-1] / s.iloc[-days - 1] - 1.0)


def _standardize_close(df: pd.DataFrame, symbol: str = "") -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    work = df.copy()
    if isinstance(work.columns, pd.MultiIndex):
        # Supports yfinance group_by='ticker' extraction and single-name frames.
        if symbol and symbol in work.columns.get_level_values(0):
            work = work[symbol].copy()
        elif symbol and symbol in work.columns.get_level_values(-1):
            try:
                work = work.xs(symbol, axis=1, level=-1)
            except Exception:
                pass
        if isinstance(work.columns, pd.MultiIndex):
            work.columns = [str(c[0]) for c in work.columns]
    work.columns = [str(c).lower().replace(" ", "_") for c in work.columns]
    if isinstance(work.index, pd.DatetimeIndex):
        work = work.reset_index()
    date_col = next((c for c in ("date", "datetime", "timestamp", "index") if c in work.columns), None)
    if date_col is None:
        return pd.DataFrame()
    close_col = "close" if "close" in work.columns else "adj_close" if "adj_close" in work.columns else None
    if close_col is None:
        return pd.DataFrame()
    work = work.rename(columns={date_col: "date", close_col: "close"})[["date", "close"]]
    work["date"] = pd.to_datetime(work["date"], errors="coerce", utc=True)
    work["close"] = pd.to_numeric(work["close"], errors="coerce")
    return work.dropna().drop_duplicates("date").sort_values("date").reset_index(drop=True)


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_cboe_history(index_name: str, period: str = "2y") -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fetch and normalize a public Cboe volatility-index history.

    Cboe historical CSV schemas are not perfectly uniform. VIX/VIX9D/VIX3M
    generally expose OHLC columns, while some index files (notably VVIX/SKEW)
    can expose a single index-value column. V2.2.1 accepts both layouts and
    refuses to guess if more than one plausible value column remains.
    """
    name = str(index_name).upper().strip()
    url = CBOE_HISTORY_URLS.get(name)
    if not url:
        return pd.DataFrame(), {"provider": "Cboe", "series": name, "status": "unsupported"}
    try:
        r = requests.get(url, timeout=(5, 20), headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        raw = pd.read_csv(StringIO(r.text))
    except Exception as exc:
        return pd.DataFrame(), {"provider": "Cboe", "series": name, "status": "request_error", "detail": type(exc).__name__}

    raw.columns = [str(c).strip().lower().replace(" ", "_") for c in raw.columns]
    date_col = next((c for c in raw.columns if c in {"date", "trade_date"} or "date" in c), None)
    if date_col is None:
        return pd.DataFrame(), {"provider": "Cboe", "series": name, "status": "schema_error", "columns": list(raw.columns)[:10]}

    # Prefer an explicit close/value field, then the index ticker itself. Some
    # Cboe files are DATE,VVIX or DATE,SKEW rather than OHLC.
    name_col = name.lower()
    preferred = ("close", "close_value", "value", name_col, "index_value")
    value_col = next((c for c in preferred if c in raw.columns), None)
    if value_col is None:
        close_like = [c for c in raw.columns if c != date_col and (c.endswith("close") or c.endswith("_value"))]
        if len(close_like) == 1:
            value_col = close_like[0]
    if value_col is None:
        # Last conservative fallback: if there is exactly one non-date column
        # that parses materially as numeric, treat it as the index value.
        candidates = []
        for c in raw.columns:
            if c == date_col:
                continue
            numeric = pd.to_numeric(raw[c], errors="coerce")
            if numeric.notna().mean() >= 0.80:
                candidates.append(c)
        if len(candidates) == 1:
            value_col = candidates[0]
    if value_col is None:
        return pd.DataFrame(), {
            "provider": "Cboe", "series": name, "status": "schema_error",
            "columns": list(raw.columns)[:12],
        }

    out = raw[[date_col, value_col]].rename(columns={date_col: "date", value_col: "value"})
    out["date"] = pd.to_datetime(out["date"], errors="coerce", utc=True)
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    out = out.dropna().sort_values("date")
    start = _period_start(period)
    out = out[out["date"] >= start].drop_duplicates("date").reset_index(drop=True)
    return out, {
        "provider": "Cboe", "series": name,
        "status": "ok" if not out.empty else "empty", "rows": int(len(out)),
        "value_column": value_col,
    }

@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_yf_close(symbol: str, period: str = "2y") -> tuple[pd.DataFrame, dict[str, Any]]:
    if not YFINANCE_AVAILABLE:
        return pd.DataFrame(), {"provider": "Yahoo", "symbol": symbol, "status": "disabled"}
    try:
        raw = yf.download(symbol, period=period, interval="1d", auto_adjust=False, progress=False, threads=False)
        out = _standardize_close(raw, symbol)
        return out, {"provider": "Yahoo", "symbol": symbol, "status": "ok" if not out.empty else "empty", "rows": int(len(out))}
    except Exception as exc:
        return pd.DataFrame(), {"provider": "Yahoo", "symbol": symbol, "status": "request_error", "detail": type(exc).__name__}


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_twelve_close(symbol: str, period: str = "2y") -> tuple[pd.DataFrame, dict[str, Any]]:
    key = _get_secret("TWELVE_DATA_API_KEY")
    if not key:
        return pd.DataFrame(), {"provider": "Twelve Data", "symbol": symbol, "status": "disabled"}
    try:
        outputsize = {"1y": 280, "2y": 560, "5y": 1320}.get(str(period).lower(), 560)
        r = requests.get(
            "https://api.twelvedata.com/time_series",
            params={"symbol": symbol, "interval": "1day", "outputsize": min(outputsize, 5000), "apikey": key, "timezone": "UTC"},
            timeout=(5, 20),
        )
        r.raise_for_status()
        payload = r.json()
        values = payload.get("values", []) if isinstance(payload, dict) else []
        if not isinstance(values, list) or not values:
            return pd.DataFrame(), {"provider": "Twelve Data", "symbol": symbol, "status": "empty"}
        raw = pd.DataFrame(values).rename(columns={"datetime": "date"})
        out = _standardize_close(raw, symbol)
        return out, {"provider": "Twelve Data", "symbol": symbol, "status": "ok" if not out.empty else "empty", "rows": int(len(out))}
    except Exception as exc:
        return pd.DataFrame(), {"provider": "Twelve Data", "symbol": symbol, "status": "request_error", "detail": type(exc).__name__}


def _fetch_public_price(symbol: str, period: str = "2y") -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Reuse the terminal's full price waterfall and its Streamlit cache.

    This prevents the behavioral layer from running a second isolated provider
    stack (which previously caused breadth to fail under API rate limits even
    when the main terminal already had valid Twelve Data prices).
    """
    try:
        df = fetch_price_history(symbol, period=period, interval="1d")
    except Exception as exc:
        return pd.DataFrame(), [{"provider": "Price waterfall", "symbol": symbol, "status": "error", "detail": type(exc).__name__}]
    attempts = list(df.attrs.get("provider_attempts", [])) if isinstance(df, pd.DataFrame) else []
    if isinstance(df, pd.DataFrame) and not df.empty:
        provider = str(df.attrs.get("provider", "Price waterfall"))
        attempts.append({"provider": provider, "symbol": symbol, "status": "selected", "rows": int(len(df))})
        return _standardize_close(df, symbol), attempts
    return pd.DataFrame(), attempts


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_fred_series(series_id: str, period: str = "2y") -> tuple[pd.DataFrame, dict[str, Any]]:
    key = _get_secret("FRED_API_KEY")
    if not key:
        return pd.DataFrame(), {"provider": "FRED", "series": series_id, "status": "disabled"}
    start = _period_start(period).date().isoformat()
    try:
        r = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={
                "series_id": series_id,
                "api_key": key,
                "file_type": "json",
                "observation_start": start,
                "sort_order": "asc",
            },
            timeout=(5, 20),
        )
        r.raise_for_status()
        payload = r.json()
        obs = payload.get("observations", []) if isinstance(payload, dict) else []
        if not isinstance(obs, list) or not obs:
            return pd.DataFrame(), {"provider": "FRED", "series": series_id, "status": "empty"}
        out = pd.DataFrame(obs)[["date", "value"]].copy()
        out["date"] = pd.to_datetime(out["date"], errors="coerce", utc=True)
        out["value"] = pd.to_numeric(out["value"], errors="coerce")
        out = out.dropna().sort_values("date").reset_index(drop=True)
        return out, {"provider": "FRED", "series": series_id, "status": "ok" if not out.empty else "empty", "rows": int(len(out))}
    except Exception as exc:
        return pd.DataFrame(), {"provider": "FRED", "series": series_id, "status": "request_error", "detail": type(exc).__name__}


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_volatility_tail_layer(period: str = "2y") -> dict[str, Any]:
    histories: dict[str, pd.DataFrame] = {}
    attempts: list[dict[str, Any]] = []

    proxy_symbols = {"VIX": "^VIX", "VVIX": "^VVIX", "VIX9D": "^VIX9D", "VIX3M": "^VIX3M", "SKEW": "^SKEW"}
    for name in ("VIX", "VVIX", "VIX9D", "VIX3M", "SKEW"):
        df, meta = _fetch_cboe_history(name, period)
        attempts.append(meta)
        if df.empty:
            # Reuse the same provider waterfall as the rest of the terminal.
            # This makes Yahoo/Massive/Twelve/FMP/Alpha fallbacks visible and
            # keeps provider selection consistent across workspaces.
            pdf, pattempts = _fetch_public_price(proxy_symbols[name], period)
            attempts.extend(pattempts)
            if not pdf.empty:
                df = pdf.rename(columns={"close": "value"})[["date", "value"]]
        if name == "VIX" and df.empty:
            fdf, fmeta = _fetch_fred_series(FRED_SERIES["vix_fred"], period)
            attempts.append(fmeta)
            if not fdf.empty:
                df = fdf
        histories[name] = df

    merged: pd.DataFrame | None = None
    for name, df in histories.items():
        if df is None or df.empty:
            continue
        w = df[["date", "value"]].rename(columns={"value": name.lower()})
        merged = w if merged is None else pd.merge(merged, w, on="date", how="outer")
    history = (merged.sort_values("date").reset_index(drop=True) if merged is not None else pd.DataFrame())

    latest = {name.lower(): _last(df["value"]) if not df.empty else None for name, df in histories.items()}
    vix_z = _robust_z_last(histories["VIX"]["value"], 252, 30) if not histories["VIX"].empty else None
    vvix_z = _robust_z_last(histories["VVIX"]["value"], 252, 30) if not histories["VVIX"].empty else None
    skew_z = _robust_z_last(histories["SKEW"]["value"], 252, 30) if not histories["SKEW"].empty else None

    vix = latest.get("vix")
    vix9d = latest.get("vix9d")
    vix3m = latest.get("vix3m")
    vvix = latest.get("vvix")
    skew = latest.get("skew")
    front_slope = (vix9d - vix) if vix9d is not None and vix is not None else None
    term_slope = (vix3m - vix) if vix3m is not None and vix is not None else None
    vvix_ratio = (vvix / vix) if vvix is not None and vix not in {None, 0} else None

    term_stress = 0.0
    if front_slope is not None:
        term_stress += 0.7 * max(-front_slope, 0.0) / 5.0
    if term_slope is not None:
        term_stress += 0.8 * max(-term_slope, 0.0) / 8.0

    # Missing components are excluded and remaining weights are re-normalized.
    # V2.2 treated absent VVIX/SKEW as neutral 50, which overstated precision.
    tail_components: list[tuple[float, float]] = []
    if vix_z is not None:
        tail_components.append((_z_score_to_100(vix_z), 0.38))
    if vvix_z is not None:
        tail_components.append((_z_score_to_100(vvix_z), 0.28))
    if skew_z is not None:
        tail_components.append((_z_score_to_100(skew_z), 0.18))
    if front_slope is not None or term_slope is not None:
        tail_components.append((float(np.clip(50 + 32 * np.tanh(term_stress), 0, 100)), 0.16))
    if tail_components:
        tail_score = float(np.clip(sum(v*w for v,w in tail_components) / sum(w for _,w in tail_components), 0, 100))
    else:
        tail_score = None

    ambiguity_components: list[tuple[float, float]] = []
    if vvix_z is not None:
        ambiguity_components.append((_z_score_to_100(vvix_z), 0.55))
    if skew_z is not None:
        ambiguity_components.append((_z_score_to_100(skew_z), 0.45))
    ambiguity_score = (
        float(np.clip(sum(v*w for v,w in ambiguity_components) / sum(w for _,w in ambiguity_components), 0, 100))
        if ambiguity_components else None
    )

    available_count = sum(1 for df in histories.values() if isinstance(df, pd.DataFrame) and not df.empty)
    coverage_ratio = float(available_count / 5.0)
    return {
        "available": available_count > 0,
        "history": history,
        "histories": histories,
        "metrics": {
            **latest,
            "vix_z": vix_z,
            "vvix_z": vvix_z,
            "skew_z": skew_z,
            "front_slope": front_slope,
            "term_slope": term_slope,
            "vvix_vix_ratio": vvix_ratio,
            "tail_stress_score": tail_score,
            "ambiguity_score": ambiguity_score,
            "tail_measurement_confidence": 100.0 * coverage_ratio,
        },
        "coverage": available_count,
        "coverage_total": 5,
        "coverage_ratio": coverage_ratio,
        "missing": [name for name, df in histories.items() if df is None or df.empty],
        "attempts": attempts,
        "source_note": "Cboe official volatility-index histories where available; full terminal price-waterfall fallbacks are labeled in diagnostics.",
    }

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_funding_credit_layer(period: str = "2y") -> dict[str, Any]:
    series: dict[str, pd.DataFrame] = {}
    attempts: list[dict[str, Any]] = []
    for key, series_id in FRED_SERIES.items():
        if key == "vix_fred":
            continue
        df, meta = _fetch_fred_series(series_id, period)
        attempts.append(meta)
        series[key] = df

    metrics: dict[str, Any] = {}
    zmap: dict[str, Any] = {}
    for key, df in series.items():
        metrics[key] = _last(df["value"]) if not df.empty else None
        zmap[f"{key}_z"] = _robust_z_last(df["value"], 156 if "nfci" in key or key == "stlfsi" else 252, 30) if not df.empty else None

    hy_z = zmap.get("hy_oas_z") or 0.0
    ig_z = zmap.get("ig_oas_z") or 0.0
    nfci_risk_z = zmap.get("nfci_risk_z") or 0.0
    stlfsi_z = zmap.get("stlfsi_z") or 0.0
    stress_score = float(np.clip(
        0.34 * _z_score_to_100(hy_z)
        + 0.20 * _z_score_to_100(ig_z)
        + 0.28 * _z_score_to_100(nfci_risk_z)
        + 0.18 * _z_score_to_100(stlfsi_z),
        0, 100,
    ))
    arbitrage_capacity = float(np.clip(100 - 0.78 * stress_score, 0, 100))
    coverage = sum(1 for df in series.values() if not df.empty)
    return {
        "available": coverage > 0,
        "series": series,
        "metrics": {**metrics, **zmap, "funding_stress_score": stress_score, "arbitrage_capacity_score": arbitrage_capacity},
        "coverage": coverage,
        "coverage_total": len(series),
        "attempts": attempts,
        "source_note": "FRED-observed credit and financial-conditions series; weekly series are carried as their latest published observation, not interpolated into fake daily data.",
    }


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_breadth_prices(period: str = "2y") -> tuple[dict[str, pd.DataFrame], list[dict[str, Any]]]:
    frames: dict[str, pd.DataFrame] = {}
    attempts: list[dict[str, Any]] = []

    # Fast batch first. If Yahoo is blocked/rate-limited in Codespaces, every
    # missing symbol falls through to the already-tested terminal waterfall.
    if YFINANCE_AVAILABLE:
        try:
            raw = yf.download(list(BREADTH_ETFS), period=period, interval="1d", auto_adjust=False, progress=False, threads=True, group_by="ticker")
            for symbol in BREADTH_ETFS:
                try:
                    out = _standardize_close(raw, symbol)
                except Exception:
                    out = pd.DataFrame()
                if not out.empty:
                    frames[symbol] = out
            attempts.append({"provider": "Yahoo batch", "status": "ok" if frames else "empty", "symbols": len(frames)})
        except Exception as exc:
            attempts.append({"provider": "Yahoo batch", "status": "request_error", "detail": type(exc).__name__})

    # Reuse data.fetch_price_history so Streamlit can reuse cached SPY/QQQ/IWM
    # observations already fetched for the current run. This is slower only for
    # genuinely missing symbols and is much more resilient to single-provider
    # failures than the isolated Twelve-only V2.2 fallback.
    for symbol in BREADTH_ETFS:
        if symbol in frames:
            continue
        df, meta_list = _fetch_public_price(symbol, period)
        attempts.extend(meta_list)
        if not df.empty:
            frames[symbol] = df
    return frames, attempts

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_breadth_layer(period: str = "2y") -> dict[str, Any]:
    frames, attempts = _fetch_breadth_prices(period)
    ret20 = {s: _ret(df, 20) for s, df in frames.items()}
    metrics: dict[str, Any] = {
        "equal_weight_rel_20d": (ret20.get("RSP") - ret20.get("SPY")) if ret20.get("RSP") is not None and ret20.get("SPY") is not None else None,
        "nasdaq_equal_rel_20d": (ret20.get("QQEW") - ret20.get("QQQ")) if ret20.get("QQEW") is not None and ret20.get("QQQ") is not None else None,
        "smallcap_rel_20d": (ret20.get("IWM") - ret20.get("SPY")) if ret20.get("IWM") is not None and ret20.get("SPY") is not None else None,
        "highbeta_lowvol_rel_20d": (ret20.get("SPHB") - ret20.get("SPLV")) if ret20.get("SPHB") is not None and ret20.get("SPLV") is not None else None,
    }

    sector_rets = [ret20[s] for s in SECTOR_ETFS if ret20.get(s) is not None]
    metrics["sector_positive_share_20d"] = float(np.mean([x > 0 for x in sector_rets])) if sector_rets else None
    metrics["sector_dispersion_20d"] = float(np.std(sector_rets, ddof=1)) if len(sector_rets) >= 2 else None

    above_ma: list[bool] = []
    for s in SECTOR_ETFS:
        df = frames.get(s)
        if df is None or df.empty or len(df) < 20:
            continue
        close = pd.to_numeric(df["close"], errors="coerce").dropna()
        if len(close) >= 20:
            above_ma.append(bool(close.iloc[-1] > close.tail(20).mean()))
    metrics["sector_above_ma20_share"] = float(np.mean(above_ma)) if above_ma else None

    breadth_components = []
    for key, scale in (("equal_weight_rel_20d", 0.04), ("nasdaq_equal_rel_20d", 0.05), ("smallcap_rel_20d", 0.06), ("highbeta_lowvol_rel_20d", 0.08)):
        value = metrics.get(key)
        if value is not None:
            breadth_components.append(50 + 35 * np.tanh(value / scale))
    if metrics.get("sector_positive_share_20d") is not None:
        breadth_components.append(100 * metrics["sector_positive_share_20d"])
    if metrics.get("sector_above_ma20_share") is not None:
        breadth_components.append(100 * metrics["sector_above_ma20_share"])
    metrics["breadth_score"] = float(np.clip(np.mean(breadth_components), 0, 100)) if breadth_components else None
    metrics["participation_fragility_score"] = 100 - metrics["breadth_score"] if metrics.get("breadth_score") is not None else None

    coverage = len(frames)
    core_symbols = ("SPY", "RSP", "QQQ", "QQEW", "IWM", "SPHB", "SPLV")
    core_coverage = sum(1 for s in core_symbols if s in frames)
    sector_coverage = sum(1 for s in SECTOR_ETFS if s in frames)
    coverage_ratio = float(coverage / len(BREADTH_ETFS)) if BREADTH_ETFS else 0.0
    # Core factor/equal-weight proxies carry more information than a single
    # sector ETF, so availability requires at least four core series.
    available = core_coverage >= 4 and metrics.get("breadth_score") is not None
    return {
        "available": available,
        "frames": frames,
        "metrics": metrics,
        "coverage": coverage,
        "coverage_total": len(BREADTH_ETFS),
        "coverage_ratio": coverage_ratio,
        "core_coverage": core_coverage,
        "core_total": len(core_symbols),
        "sector_coverage": sector_coverage,
        "sector_total": len(SECTOR_ETFS),
        "attempts": attempts,
        "source_note": "ETF-based participation proxies (equal-weight, size, factor and sector breadth). They are breadth proxies, not constituent-level advance/decline statistics.",
    }


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_cftc_positioning_layer(symbol: str = "SPY", weeks: int = 180) -> dict[str, Any]:
    """Fetch weekly CFTC Traders in Financial Futures positioning.

    The current V2.2.1 public implementation deliberately maps broad U.S. equity
    workspaces to the E-mini S&P 500 TFF contract. It is market-level positioning,
    not single-stock positioning.
    """
    endpoint = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"
    contract_code = "13874A"  # E-mini S&P 500 TFF market code.
    params = {
        "$select": ",".join([
            "market_and_exchange_names", "report_date_as_yyyy_mm_dd", "cftc_contract_market_code", "open_interest_all",
            "dealer_positions_long_all", "dealer_positions_short_all",
            "asset_mgr_positions_long", "asset_mgr_positions_short",
            "lev_money_positions_long", "lev_money_positions_short",
        ]),
        "$where": f"cftc_contract_market_code='{contract_code}'",
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$limit": str(max(60, min(int(weeks), 260))),
    }
    try:
        r = requests.get(endpoint, params=params, timeout=(5, 20), headers={"User-Agent": "QuantTerminal/MarketPsychology"})
        r.raise_for_status()
        rows = r.json()
        if not isinstance(rows, list) or not rows:
            return {"available": False, "status": "empty", "history": pd.DataFrame(), "metrics": {}, "source": "CFTC TFF Futures Only"}
        df = pd.DataFrame(rows)
    except Exception as exc:
        return {"available": False, "status": "request_error", "detail": type(exc).__name__, "history": pd.DataFrame(), "metrics": {}, "source": "CFTC TFF Futures Only"}

    numeric_cols = [
        "open_interest_all", "dealer_positions_long_all", "dealer_positions_short_all",
        "asset_mgr_positions_long", "asset_mgr_positions_short", "lev_money_positions_long", "lev_money_positions_short",
    ]
    if "report_date_as_yyyy_mm_dd" not in df.columns:
        return {"available": False, "status": "schema_error", "history": pd.DataFrame(), "metrics": {}, "source": "CFTC TFF Futures Only"}
    df["date"] = pd.to_datetime(df["report_date_as_yyyy_mm_dd"], errors="coerce", utc=True)
    df["availability_date"] = df["date"].map(_cftc_availability_date)
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            df[col] = np.nan
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    if df.empty:
        return {"available": False, "status": "normalize_empty", "history": pd.DataFrame(), "metrics": {}, "source": "CFTC TFF Futures Only"}

    oi = df["open_interest_all"].replace(0, np.nan)
    df["lev_money_net"] = df["lev_money_positions_long"] - df["lev_money_positions_short"]
    df["asset_mgr_net"] = df["asset_mgr_positions_long"] - df["asset_mgr_positions_short"]
    df["dealer_net"] = df["dealer_positions_long_all"] - df["dealer_positions_short_all"]
    df["lev_money_net_pct_oi"] = df["lev_money_net"] / oi
    df["asset_mgr_net_pct_oi"] = df["asset_mgr_net"] / oi
    df["dealer_net_pct_oi"] = df["dealer_net"] / oi
    # Only observations that have passed the conservative publication-availability
    # gate are eligible for the current snapshot. Historical rows remain intact for
    # charting, but memory alignment uses availability_date rather than report date.
    now_utc = pd.Timestamp.now(tz="UTC")
    eligible = df[df["availability_date"].notna() & (df["availability_date"] <= now_utc)].copy()
    if eligible.empty:
        return {
            "available": False,
            "status": "no_published_observation",
            "history": df,
            "metrics": {},
            "source": "CFTC TFF Futures Only",
            "availability_policy": "REPORT_DATE_PLUS_4_US_FEDERAL_BUSINESS_DAYS",
        }

    lev = eligible["lev_money_net_pct_oi"].dropna()
    current = _last(lev)
    pct = None
    if current is not None and len(lev) >= 20:
        hist = lev.tail(156)
        pct = float(100.0 * (hist <= current).mean())
    weekly_change = None
    if len(lev) >= 2:
        weekly_change = float(lev.iloc[-1] - lev.iloc[-2])
    crowding = None
    if pct is not None:
        crowding = float(np.clip(2.0 * abs(pct - 50.0), 0, 100))
    current_row = eligible.iloc[-1]
    metrics = {
        "as_of": current_row["date"],
        "available_from": current_row["availability_date"],
        "lev_money_net_pct_oi": current,
        "lev_money_percentile": pct,
        "lev_money_weekly_change": weekly_change,
        "asset_mgr_net_pct_oi": _safe_float(current_row.get("asset_mgr_net_pct_oi")),
        "dealer_net_pct_oi": _safe_float(current_row.get("dealer_net_pct_oi")),
        "open_interest": _safe_float(current_row.get("open_interest_all")),
        "positioning_crowding_score": crowding,
        "proxy_contract": str(current_row.get("market_and_exchange_names", "E-mini S&P 500")),
    }
    return {
        "available": True,
        "status": "ok",
        "history": df,
        "metrics": metrics,
        "source": "CFTC TFF Futures Only",
        "scope": "Broad U.S. equity market proxy; not single-stock positioning",
        "availability_policy": "REPORT_DATE_PLUS_4_US_FEDERAL_BUSINESS_DAYS",
        "availability_note": "Daily research uses the first full U.S. federal business session after the normal Friday COT release cycle; report-date values are never used on the preceding Tuesday.",
    }


def enrich_options_behavior(options: dict[str, Any]) -> dict[str, Any]:
    """Normalize the richer option metrics added by data.fetch_options_snapshot.

    This helper never manufactures dealer direction. Gross convexity / OI concentration
    are explicitly labelled as structural proxies.
    """
    if not isinstance(options, dict) or not options.get("available"):
        return {"available": False, "metrics": {}}
    metrics = {
        "put_call_volume": _safe_float(options.get("put_call_volume")),
        "put_call_oi": _safe_float(options.get("put_call_oi")),
        "near_term_share": _safe_float(options.get("near_term_share")),
        "zero_dte_share": _safe_float(options.get("zero_dte_share")),
        "dte_7_share": _safe_float(options.get("dte_7_share")),
        "dte_30_share": _safe_float(options.get("dte_30_share")),
        "otm_call_volume_share": _safe_float(options.get("otm_call_volume_share")),
        "otm_put_volume_share": _safe_float(options.get("otm_put_volume_share")),
        "put_call_iv_skew": _safe_float(options.get("put_call_iv_skew")),
        "oi_top5_strike_share": _safe_float(options.get("oi_top5_strike_share")),
        "spot": _safe_float(options.get("spot")),
        "rows": int(options.get("rows", 0) or 0),
        "listed_expiry_count": int(options.get("listed_expiry_count", 0) or 0),
        "loaded_expiry_count": int(options.get("loaded_expiry_count", 0) or 0),
        "max_dte_loaded": options.get("max_dte_loaded"),
        "tenor_denominator_complete": bool(options.get("tenor_denominator_complete", False)),
        "tenor_denominator_status": str(options.get("tenor_denominator_status", "UNAVAILABLE")),
        "tenor_denominator_volume": _safe_float(options.get("tenor_denominator_volume")),
    }
    tail_parts = []
    if metrics["put_call_volume"] is not None:
        tail_parts.append(50 + 30 * np.tanh((metrics["put_call_volume"] - 0.9) / 0.45))
    if metrics["put_call_iv_skew"] is not None:
        tail_parts.append(50 + 35 * np.tanh(metrics["put_call_iv_skew"] / 0.15))
    if metrics["otm_put_volume_share"] is not None:
        tail_parts.append(100 * metrics["otm_put_volume_share"])
    lottery_parts = []
    if metrics["otm_call_volume_share"] is not None:
        lottery_parts.append(100 * metrics["otm_call_volume_share"])
    if metrics["dte_7_share"] is not None:
        lottery_parts.append(100 * metrics["dte_7_share"])
    if metrics["zero_dte_share"] is not None:
        lottery_parts.append(100 * metrics["zero_dte_share"])
    metrics["option_tail_demand_score"] = float(np.clip(np.mean(tail_parts), 0, 100)) if tail_parts else None
    metrics["option_lottery_score"] = float(np.clip(np.mean(lottery_parts), 0, 100)) if lottery_parts else None
    concentration = metrics.get("oi_top5_strike_share")
    metrics["convexity_concentration_score"] = float(np.clip(100 * concentration, 0, 100)) if concentration is not None else None
    return {
        "available": True,
        "metrics": metrics,
        "source": "Public option-chain snapshot",
        "scope": (
            "Current snapshot only; not licensed historical OPRA order flow and not signed dealer gamma. "
            f"Tenor shares use the audited loaded expiry universe ({metrics.get('tenor_denominator_status')})."
        ),
    }


def fetch_short_interest_status() -> dict[str, Any]:
    client_id = _get_secret("FINRA_CLIENT_ID")
    client_secret = _get_secret("FINRA_CLIENT_SECRET")
    if client_id and client_secret:
        return {
            "available": False,
            "status": "credentials_present_not_enabled",
            "note": "FINRA credentials detected, but V2.2.1 deliberately does not assume authorization semantics without an explicit Query API connection test.",
        }
    return {
        "available": False,
        "status": "not_connected",
        "note": "FINRA short-sale volume / short-interest API credentials are not connected. Daily short-sale volume must not be relabelled as short interest.",
    }


def _freshness_score(last_date: Any, full_days: float, stale_days: float) -> float:
    try:
        ts = pd.to_datetime(last_date, errors="coerce", utc=True)
        if pd.isna(ts):
            return 0.0
        age = max((pd.Timestamp.now(tz="UTC") - ts).total_seconds() / 86400.0, 0.0)
        if age <= full_days:
            return 100.0
        if age >= stale_days:
            return 0.0
        return float(100.0 * (stale_days - age) / max(stale_days - full_days, 1e-9))
    except Exception:
        return 0.0


def _latest_date_from_frames(frames: dict[str, pd.DataFrame]) -> pd.Timestamp | None:
    dates = []
    for df in frames.values():
        if isinstance(df, pd.DataFrame) and not df.empty and "date" in df.columns:
            s = pd.to_datetime(df["date"], errors="coerce", utc=True).dropna()
            if not s.empty:
                dates.append(s.max())
    return max(dates) if dates else None


def build_behavioral_data_layer(symbol: str, period: str, options: dict[str, Any]) -> dict[str, Any]:
    vol = fetch_volatility_tail_layer(period)
    breadth = fetch_breadth_layer(period)
    funding = fetch_funding_credit_layer(period)
    positioning = fetch_cftc_positioning_layer(symbol)
    option_behavior = enrich_options_behavior(options)
    short_interest = fetch_short_interest_status()

    blocks = {
        "volatility_tail": vol,
        "breadth": breadth,
        "funding_credit": funding,
        "positioning": positioning,
        "options_behavior": option_behavior,
        "short_interest": short_interest,
    }

    # Availability is completeness-weighted, not a binary provider check.
    vol_comp = float(np.clip(vol.get("coverage", 0) / max(vol.get("coverage_total", 5), 1), 0, 1))
    breadth_comp = float(np.clip(breadth.get("coverage", 0) / max(breadth.get("coverage_total", len(BREADTH_ETFS)), 1), 0, 1))
    funding_comp = float(np.clip(funding.get("coverage", 0) / max(funding.get("coverage_total", 1), 1), 0, 1))
    ph = positioning.get("history", pd.DataFrame())
    positioning_comp = float(np.clip((len(ph) if isinstance(ph, pd.DataFrame) else 0) / 52.0, 0, 1)) if positioning.get("available") else 0.0
    om = option_behavior.get("metrics", {}) if isinstance(option_behavior, dict) else {}
    rows = float(om.get("rows", 0) or 0)
    option_rows_comp = float(np.clip(rows / 500.0, 0, 1))
    tenor_complete = bool(om.get("tenor_denominator_complete", False))
    option_comp = option_rows_comp * (1.0 if tenor_complete else 0.70)
    short_comp = 1.0 if short_interest.get("available") else 0.0

    weights = {
        "volatility_tail": 1.25,
        "breadth": 1.25,
        "funding_credit": 1.00,
        "positioning": 0.85,
        "options_behavior": 1.00,
        "short_interest": 0.55,
    }
    completeness = {
        "volatility_tail": vol_comp,
        "breadth": breadth_comp,
        "funding_credit": funding_comp,
        "positioning": positioning_comp,
        "options_behavior": option_comp,
        "short_interest": short_comp,
    }
    availability_score = float(100 * sum(completeness[k] * weights[k] for k in weights) / sum(weights.values()))

    # Freshness is calculated against the publication cadence of each source.
    vol_last = _latest_date_from_frames(vol.get("histories", {}) if isinstance(vol.get("histories", {}), dict) else {})
    breadth_last = _latest_date_from_frames(breadth.get("frames", {}) if isinstance(breadth.get("frames", {}), dict) else {})
    funding_last = _latest_date_from_frames(funding.get("series", {}) if isinstance(funding.get("series", {}), dict) else {})
    position_last = positioning.get("metrics", {}).get("as_of") if isinstance(positioning.get("metrics", {}), dict) else None
    freshness_parts = {
        "volatility_tail": _freshness_score(vol_last, 4, 12) if vol_comp > 0 else 0.0,
        "breadth": _freshness_score(breadth_last, 4, 12) if breadth_comp > 0 else 0.0,
        "funding_credit": _freshness_score(funding_last, 10, 35) if funding_comp > 0 else 0.0,
        "positioning": _freshness_score(position_last, 12, 28) if positioning_comp > 0 else 0.0,
        "options_behavior": 100.0 if option_behavior.get("available") else 0.0,
        "short_interest": 100.0 if short_interest.get("available") else 0.0,
    }
    freshness_score = float(sum(freshness_parts[k] * weights[k] for k in weights) / sum(weights.values()))

    # Identification quality measures how directly each observable constrains
    # the intended mechanism, not whether the API answered successfully.
    id_base = {
        "volatility_tail": 76.0,
        "breadth": 70.0,
        "funding_credit": 82.0,
        "positioning": 66.0,
        "options_behavior": 62.0,
        "short_interest": 72.0,
    }
    identification_score = float(sum(id_base[k] * completeness[k] * weights[k] for k in weights) / sum(weights.values()))
    evidence_score = float(np.clip(0.45 * availability_score + 0.25 * freshness_score + 0.30 * identification_score, 0, 100))

    return {
        "available": any(bool(v.get("available")) for k, v in blocks.items() if k != "short_interest"),
        # Backward-compatible key: now means actual data availability/completeness.
        "coverage_score": availability_score,
        "availability_score": availability_score,
        "freshness_score": freshness_score,
        "identification_score": identification_score,
        "evidence_score": evidence_score,
        "block_completeness": completeness,
        "block_freshness": freshness_parts,
        **blocks,
    }

