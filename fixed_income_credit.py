"""
Fixed Income & Credit Analytics — single-file institutional workstation.

Paste this entire file into ``fixed_income_credit.py`` at the project root.
It contains the public-data adapters, fixed-income/credit analytics engine,
and Streamlit user interface in one standalone module.

Public entry point
------------------
``render_fixed_income_credit_analytics(ticker=None, price_data=None, analysis=None)``

Design principles
-----------------
* No silent synthetic fallback. Demo data is only used in explicit demo mode.
* Public and licensed-provider data are clearly separated.
* All Streamlit widget keys use the ``fic_`` prefix.
* The module can render without a prior Equity-style ticker analysis.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from io import BytesIO, StringIO
import json
import os
from math import erf, exp, isfinite, log, sqrt
from pathlib import Path
import re
import time
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

try:
    import yfinance as yf
except Exception:  # pragma: no cover
    yf = None

try:
    from scipy.optimize import brentq, least_squares
except Exception:  # pragma: no cover
    brentq = None
    least_squares = None



# ============================================================================
# DATA ADAPTERS AND LINEAGE
# ============================================================================

DEFAULT_TIMEOUT = 20
CACHE_ROOT = Path(os.getenv("QT_FIC_CACHE_DIR", ".quant_cache/fixed_income_credit"))
CACHE_ROOT.mkdir(parents=True, exist_ok=True)


@dataclass
class DataLineage:
    series_id: str
    provider: str
    source_url: str
    as_of: datetime | None = None
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    frequency: str = ""
    unit: str = ""
    currency: str | None = None
    tenor: str | None = None
    rating: str | None = None
    transformation: str | None = None
    status: str = "OK"
    is_proxy: bool = False
    is_stale: bool = False
    notes: str = ""


@dataclass
class DataResult:
    frame: pd.DataFrame = field(default_factory=pd.DataFrame)
    lineage: list[DataLineage] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    provider_required: bool = False

    @property
    def ok(self) -> bool:
        return isinstance(self.frame, pd.DataFrame) and not self.frame.empty

    def monitor_rows(self) -> list[dict[str, Any]]:
        rows = []
        for item in self.lineage:
            row = asdict(item)
            for key in ["as_of", "retrieved_at"]:
                if row.get(key) is not None:
                    row[key] = pd.Timestamp(row[key]).isoformat()
            rows.append(row)
        if not rows and self.errors:
            rows.append(
                {
                    "series_id": "N/A",
                    "provider": "N/A",
                    "source_url": "",
                    "status": "ERROR",
                    "notes": " | ".join(self.errors),
                }
            )
        return rows


# -----------------------------------------------------------------------------
# Configuration and HTTP
# -----------------------------------------------------------------------------

def get_secret(name: str, default: str = "") -> str:
    value = ""
    if st is not None:
        try:
            value = st.secrets.get(name, "")
        except Exception:
            value = ""
    if not value:
        value = os.getenv(name, default)
    return str(value or "").strip()


def sec_user_agent() -> str:
    configured = get_secret("SEC_USER_AGENT", "")
    if configured:
        return configured
    return "QuantTerminal fixed-income research contact@example.com"


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": sec_user_agent(),
            "Accept": "application/json,text/csv,text/plain,*/*",
            "Accept-Encoding": "gzip, deflate",
        }
    )
    return s


def _cache_path(key: str, suffix: str = ".json") -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", key)[:180]
    return CACHE_ROOT / f"{safe}{suffix}"


def _read_cache(key: str, max_age_seconds: int) -> Any | None:
    path = _cache_path(key)
    if not path.exists():
        return None
    age = time.time() - path.stat().st_mtime
    if age > max_age_seconds:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_cache(key: str, payload: Any) -> None:
    path = _cache_path(key)
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
    except Exception:
        pass


def request_json(
    url: str,
    params: Mapping[str, Any] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    cache_key: str | None = None,
    cache_ttl: int = 900,
    extra_headers: Mapping[str, str] | None = None,
) -> Any:
    if cache_key:
        cached = _read_cache(cache_key, cache_ttl)
        if cached is not None:
            return cached
    s = _session()
    if extra_headers:
        s.headers.update(dict(extra_headers))
    response = s.get(url, params=dict(params or {}), timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if cache_key:
        _write_cache(cache_key, payload)
    return payload


def request_text(
    url: str,
    params: Mapping[str, Any] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    extra_headers: Mapping[str, str] | None = None,
) -> str:
    s = _session()
    if extra_headers:
        s.headers.update(dict(extra_headers))
    response = s.get(url, params=dict(params or {}), timeout=timeout)
    response.raise_for_status()
    return response.text


def _as_of_from_frame(frame: pd.DataFrame) -> datetime | None:
    if frame is None or frame.empty or "date" not in frame.columns:
        return None
    dates = pd.to_datetime(frame["date"], errors="coerce", utc=True).dropna()
    return dates.max().to_pydatetime() if not dates.empty else None


def _stale(as_of: datetime | None, frequency: str) -> bool:
    if as_of is None:
        return True
    now = datetime.now(timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    limits = {
        "Intraday": timedelta(hours=2),
        "Daily": timedelta(days=5),
        "Weekly": timedelta(days=12),
        "Monthly": timedelta(days=50),
        "Quarterly": timedelta(days=140),
    }
    return now - as_of > limits.get(frequency, timedelta(days=30))


# -----------------------------------------------------------------------------
# FRED
# -----------------------------------------------------------------------------

US_NOMINAL_CURVE_SERIES: dict[str, str] = {
    "1M": "DGS1MO",
    "3M": "DGS3MO",
    "6M": "DGS6MO",
    "1Y": "DGS1",
    "2Y": "DGS2",
    "3Y": "DGS3",
    "5Y": "DGS5",
    "7Y": "DGS7",
    "10Y": "DGS10",
    "20Y": "DGS20",
    "30Y": "DGS30",
}

US_REAL_CURVE_SERIES: dict[str, str] = {
    "5Y": "DFII5",
    "7Y": "DFII7",
    "10Y": "DFII10",
    "20Y": "DFII20",
    "30Y": "DFII30",
}

INFLATION_SERIES: dict[str, str] = {
    "5Y Breakeven": "T5YIE",
    "10Y Breakeven": "T10YIE",
    "5Y5Y Forward Inflation": "T5YIFR",
}

CREDIT_OAS_SERIES: dict[str, str] = {
    "US IG OAS": "BAMLC0A0CM",
    "US BBB OAS": "BAMLC0A4CBBB",
    "US HY OAS": "BAMLH0A0HYM2",
    "US BB OAS": "BAMLH0A1HYBB",
    "US B OAS": "BAMLH0A2HYB",
    "US CCC & Lower OAS": "BAMLH0A3HYC",
}

FUNDING_STRESS_SERIES: dict[str, str] = {
    "SOFR": "SOFR",
    "Effective Fed Funds": "DFF",
    "Financial Stress Index": "STLFSI4",
    "10Y-2Y": "T10Y2Y",
    "10Y-3M": "T10Y3M",
}


def _fred_api_series(series_id: str, start_date: str | None = None) -> pd.DataFrame:
    api_key = get_secret("FRED_API_KEY")
    if not api_key:
        raise RuntimeError("FRED_API_KEY not configured")
    params: dict[str, Any] = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "asc",
    }
    if start_date:
        params["observation_start"] = start_date
    payload = request_json(
        "https://api.stlouisfed.org/fred/series/observations",
        params=params,
        cache_key=f"fred_api_{series_id}_{start_date or 'all'}",
        cache_ttl=1800,
    )
    observations = payload.get("observations", []) if isinstance(payload, dict) else []
    frame = pd.DataFrame(observations)
    if frame.empty:
        return pd.DataFrame(columns=["date", series_id])
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame[series_id] = pd.to_numeric(frame["value"].replace(".", np.nan), errors="coerce")
    return frame[["date", series_id]].dropna(subset=["date"]).sort_values("date")


def _fred_csv_series(series_id: str, start_date: str | None = None) -> pd.DataFrame:
    params: dict[str, Any] = {"id": series_id}
    if start_date:
        params["cosd"] = start_date
    text = request_text("https://fred.stlouisfed.org/graph/fredgraph.csv", params=params)
    frame = pd.read_csv(StringIO(text))
    if frame.empty:
        return pd.DataFrame(columns=["date", series_id])
    date_col = "DATE" if "DATE" in frame.columns else frame.columns[0]
    value_col = series_id if series_id in frame.columns else frame.columns[-1]
    frame["date"] = pd.to_datetime(frame[date_col], errors="coerce")
    frame[series_id] = pd.to_numeric(frame[value_col].replace(".", np.nan), errors="coerce")
    return frame[["date", series_id]].dropna(subset=["date"]).sort_values("date")


def fetch_fred_series(
    series: Mapping[str, str],
    start_date: str | None = None,
    unit: str = "Percent",
    frequency: str = "Daily",
) -> DataResult:
    frames: list[pd.DataFrame] = []
    lineage: list[DataLineage] = []
    errors: list[str] = []
    for label, series_id in series.items():
        try:
            try:
                one = _fred_api_series(series_id, start_date=start_date)
                source_url = "https://api.stlouisfed.org/fred/series/observations"
            except Exception:
                one = _fred_csv_series(series_id, start_date=start_date)
                source_url = "https://fred.stlouisfed.org/graph/fredgraph.csv"
            if one.empty:
                raise RuntimeError("No observations returned")
            one = one.rename(columns={series_id: label})
            frames.append(one)
            as_of = _as_of_from_frame(one)
            lineage.append(
                DataLineage(
                    series_id=series_id,
                    provider="Federal Reserve Bank of St. Louis / FRED",
                    source_url=source_url,
                    as_of=as_of,
                    frequency=frequency,
                    unit=unit,
                    status="OK",
                    is_stale=_stale(as_of, frequency),
                )
            )
        except Exception as exc:
            errors.append(f"{series_id}: {exc}")
            lineage.append(
                DataLineage(
                    series_id=series_id,
                    provider="Federal Reserve Bank of St. Louis / FRED",
                    source_url="https://fred.stlouisfed.org/",
                    frequency=frequency,
                    unit=unit,
                    status="ERROR",
                    is_stale=True,
                    notes=str(exc),
                )
            )
    if not frames:
        return DataResult(lineage=lineage, errors=errors)
    merged = frames[0]
    for one in frames[1:]:
        merged = pd.merge(merged, one, on="date", how="outer")
    merged = merged.sort_values("date").reset_index(drop=True)
    return DataResult(frame=merged, lineage=lineage, errors=errors)


def load_us_nominal_curve_history(start_date: str | None = None) -> DataResult:
    return fetch_fred_series(US_NOMINAL_CURVE_SERIES, start_date=start_date, unit="Percent", frequency="Daily")


def load_us_real_curve_history(start_date: str | None = None) -> DataResult:
    return fetch_fred_series(US_REAL_CURVE_SERIES, start_date=start_date, unit="Percent", frequency="Daily")


def load_inflation_history(start_date: str | None = None) -> DataResult:
    return fetch_fred_series(INFLATION_SERIES, start_date=start_date, unit="Percent", frequency="Daily")


def load_credit_spread_history(start_date: str | None = None) -> DataResult:
    # ICE BofA OAS series are published by FRED in percentage points.
    # Convert once at the adapter boundary so every downstream credit model uses bp.
    result = fetch_fred_series(CREDIT_OAS_SERIES, start_date=start_date, unit="Percent", frequency="Daily")
    if result.frame is not None and not result.frame.empty:
        for column in CREDIT_OAS_SERIES:
            if column in result.frame:
                result.frame[column] = pd.to_numeric(result.frame[column], errors="coerce") * 100.0
        for lineage in result.lineage:
            lineage.unit = "Basis points"
            lineage.notes = (lineage.notes + " | " if lineage.notes else "") + "Converted from FRED percentage points to basis points at ingestion."
    return result


def load_funding_stress_history(start_date: str | None = None) -> DataResult:
    return fetch_fred_series(FUNDING_STRESS_SERIES, start_date=start_date, unit="Mixed", frequency="Daily")


# -----------------------------------------------------------------------------
# U.S. Treasury official daily curve and auction data
# -----------------------------------------------------------------------------

def load_treasury_official_curve(year: int | None = None, curve_type: str = "nominal") -> DataResult:
    year = int(year or datetime.now().year)
    type_map = {
        "nominal": "daily_treasury_yield_curve",
        "real": "daily_treasury_real_yield_curve",
        "bill": "daily_treasury_bill_rates",
    }
    data_type = type_map.get(curve_type, type_map["nominal"])
    url = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/all/all"
    params = {"_format": "csv", "page": "", "type": data_type, "field_tdr_date_value": str(year)}
    try:
        text = request_text(url, params=params, extra_headers={"Referer": "https://home.treasury.gov/"})
        frame = pd.read_csv(StringIO(text))
        if frame.empty:
            raise RuntimeError("Treasury CSV returned no rows")
        frame.columns = [str(c).strip() for c in frame.columns]
        date_col = next((c for c in frame.columns if c.lower() == "date"), frame.columns[0])
        frame = frame.rename(columns={date_col: "date"})
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        for col in frame.columns:
            if col != "date":
                frame[col] = pd.to_numeric(frame[col], errors="coerce")
        frame = frame.dropna(subset=["date"]).sort_values("date")
        as_of = _as_of_from_frame(frame)
        lineage = DataLineage(
            series_id=f"US_TREASURY_{curve_type.upper()}_{year}",
            provider="U.S. Department of the Treasury",
            source_url=url,
            as_of=as_of,
            frequency="Daily",
            unit="Percent",
            status="OK",
            is_stale=_stale(as_of, "Daily"),
            notes="Official par curve; indicative bid-side quotations, not transactions.",
        )
        return DataResult(frame=frame, lineage=[lineage])
    except Exception as exc:
        return DataResult(
            errors=[str(exc)],
            lineage=[
                DataLineage(
                    series_id=f"US_TREASURY_{curve_type.upper()}_{year}",
                    provider="U.S. Department of the Treasury",
                    source_url=url,
                    frequency="Daily",
                    unit="Percent",
                    status="ERROR",
                    is_stale=True,
                    notes=str(exc),
                )
            ],
        )


def load_treasury_auctions(
    start_date: str | None = None,
    end_date: str | None = None,
    page_size: int = 500,
) -> DataResult:
    end = pd.Timestamp(end_date or pd.Timestamp.today()).date()
    start = pd.Timestamp(start_date or (pd.Timestamp(end) - pd.DateOffset(years=2))).date()
    url = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query"
    params = {
        "filter": f"auction_date:gte:{start.isoformat()},auction_date:lte:{end.isoformat()}",
        "sort": "-auction_date",
        "page[size]": min(max(int(page_size), 1), 10000),
    }
    try:
        payload = request_json(url, params=params, cache_key=f"auctions_{start}_{end}_{page_size}", cache_ttl=3600)
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        frame = pd.DataFrame(rows)
        if frame.empty:
            raise RuntimeError("FiscalData returned no auction rows")
        date_cols = [c for c in frame.columns if c.endswith("_date")]
        for col in date_cols:
            frame[col] = pd.to_datetime(frame[col], errors="coerce")
        numeric_candidates = [
            "offering_amt",
            "total_accepted",
            "competitive_accepted",
            "noncompetitive_accepted",
            "high_yield",
            "high_rate",
            "high_discount_rate",
            "bid_to_cover_ratio",
            "direct_bidder_accepted",
            "indirect_bidder_accepted",
            "primary_dealer_accepted",
        ]
        for col in numeric_candidates:
            if col in frame.columns:
                frame[col] = pd.to_numeric(frame[col], errors="coerce")
        as_of = None
        if "auction_date" in frame.columns and frame["auction_date"].notna().any():
            as_of = frame["auction_date"].max().to_pydatetime().replace(tzinfo=timezone.utc)
        lineage = DataLineage(
            series_id="TREASURY_SECURITIES_AUCTIONS",
            provider="U.S. Treasury Fiscal Data",
            source_url=url,
            as_of=as_of,
            frequency="Event",
            unit="Mixed",
            status="OK",
            is_stale=False,
        )
        return DataResult(frame=frame, lineage=[lineage])
    except Exception as exc:
        return DataResult(
            errors=[str(exc)],
            lineage=[
                DataLineage(
                    series_id="TREASURY_SECURITIES_AUCTIONS",
                    provider="U.S. Treasury Fiscal Data",
                    source_url=url,
                    frequency="Event",
                    unit="Mixed",
                    status="ERROR",
                    is_stale=True,
                    notes=str(exc),
                )
            ],
        )


# -----------------------------------------------------------------------------
# ECB Data Portal - official SDMX 2.1 REST service
# -----------------------------------------------------------------------------

ECB_AAA_SPOT_SERIES: dict[str, str] = {
    "3M": "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_3M",
    "1Y": "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_1Y",
    "2Y": "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y",
    "3Y": "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_3Y",
    "5Y": "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_5Y",
    "7Y": "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_7Y",
    "10Y": "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y",
    "20Y": "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_20Y",
    "30Y": "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_30Y",
}


def _ecb_csv_series(key: str, start_date: str | None = None) -> pd.DataFrame:
    url = f"https://data-api.ecb.europa.eu/service/data/YC/{key}"
    params: dict[str, Any] = {"format": "csvdata", "detail": "dataonly"}
    if start_date:
        params["startPeriod"] = start_date
    text = request_text(url, params=params, extra_headers={"Accept": "text/csv"})
    frame = pd.read_csv(StringIO(text))
    if frame.empty:
        return pd.DataFrame()
    date_col = next((c for c in frame.columns if c.upper() in {"TIME_PERIOD", "DATE"}), None)
    value_col = next((c for c in frame.columns if c.upper() in {"OBS_VALUE", "VALUE"}), None)
    if date_col is None or value_col is None:
        raise RuntimeError(f"Unexpected ECB CSV schema: {list(frame.columns)[:12]}")
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(frame[date_col], errors="coerce"),
            "value": pd.to_numeric(frame[value_col], errors="coerce"),
        }
    ).dropna(subset=["date"])
    return out.sort_values("date")


def load_ecb_aaa_curve_history(start_date: str | None = None) -> DataResult:
    frames: list[pd.DataFrame] = []
    lineage: list[DataLineage] = []
    errors: list[str] = []
    for tenor, key in ECB_AAA_SPOT_SERIES.items():
        url = f"https://data-api.ecb.europa.eu/service/data/YC/{key}"
        try:
            one = _ecb_csv_series(key, start_date=start_date).rename(columns={"value": tenor})
            if one.empty:
                raise RuntimeError("No observations returned")
            frames.append(one)
            as_of = _as_of_from_frame(one)
            lineage.append(
                DataLineage(
                    series_id=f"YC.{key}",
                    provider="ECB Data Portal",
                    source_url=url,
                    as_of=as_of,
                    frequency="Daily",
                    unit="Percent",
                    currency="EUR",
                    tenor=tenor,
                    status="OK",
                    is_stale=_stale(as_of, "Daily"),
                    notes="AAA euro-area nominal spot curve; Svensson, continuous compounding.",
                )
            )
        except Exception as exc:
            errors.append(f"{tenor}: {exc}")
            lineage.append(
                DataLineage(
                    series_id=f"YC.{key}",
                    provider="ECB Data Portal",
                    source_url=url,
                    frequency="Daily",
                    unit="Percent",
                    currency="EUR",
                    tenor=tenor,
                    status="ERROR",
                    is_stale=True,
                    notes=str(exc),
                )
            )
    if not frames:
        return DataResult(lineage=lineage, errors=errors)
    merged = frames[0]
    for one in frames[1:]:
        merged = pd.merge(merged, one, on="date", how="outer")
    return DataResult(frame=merged.sort_values("date").reset_index(drop=True), lineage=lineage, errors=errors)


# -----------------------------------------------------------------------------
# Market proxies via yfinance
# -----------------------------------------------------------------------------

FIXED_INCOME_PROXY_UNIVERSE: dict[str, str] = {
    "SHY": "1-3Y Treasury ETF",
    "IEF": "7-10Y Treasury ETF",
    "TLT": "20+Y Treasury ETF",
    "TIP": "TIPS ETF",
    "LQD": "Investment Grade Credit ETF",
    "HYG": "High Yield Credit ETF",
    "JNK": "High Yield Credit ETF",
    "EMB": "Emerging Market Sovereign ETF",
    "BND": "US Aggregate Bond ETF",
    "AGG": "US Aggregate Bond ETF",
    "ZT=F": "2Y Treasury Future",
    "ZF=F": "5Y Treasury Future",
    "ZN=F": "10Y Treasury Future",
    "ZB=F": "30Y Treasury Future",
    "UB=F": "Ultra Treasury Future",
    "^MOVE": "MOVE Index proxy when Yahoo supports it",
}


def load_market_proxy_history(
    symbols: Sequence[str] | None = None,
    period: str = "2y",
    interval: str = "1d",
) -> DataResult:
    symbols = list(symbols or FIXED_INCOME_PROXY_UNIVERSE.keys())
    if yf is None:
        return DataResult(
            errors=["yfinance package is not installed"],
            lineage=[
                DataLineage(
                    series_id=",".join(symbols),
                    provider="Yahoo Finance via yfinance",
                    source_url="https://finance.yahoo.com/",
                    frequency="Daily",
                    unit="Price",
                    status="ERROR",
                    is_proxy=True,
                    is_stale=True,
                    notes="Install yfinance to enable market proxies.",
                )
            ],
        )
    frames = []
    lineage = []
    errors = []
    for symbol in symbols:
        try:
            raw = yf.download(symbol, period=period, interval=interval, progress=False, auto_adjust=True, threads=False)
            if raw is None or raw.empty:
                raise RuntimeError("No Yahoo observations")
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = [str(c[0]).lower() for c in raw.columns]
            else:
                raw.columns = [str(c).lower() for c in raw.columns]
            raw = raw.reset_index()
            date_col = "Date" if "Date" in raw.columns else "Datetime" if "Datetime" in raw.columns else raw.columns[0]
            close_col = "close" if "close" in raw.columns else next((c for c in raw.columns if "close" in str(c).lower()), None)
            if close_col is None:
                raise RuntimeError("Close column unavailable")
            one = pd.DataFrame({"date": pd.to_datetime(raw[date_col], errors="coerce"), symbol: pd.to_numeric(raw[close_col], errors="coerce")})
            one = one.dropna(subset=["date"]).sort_values("date")
            frames.append(one)
            as_of = _as_of_from_frame(one)
            lineage.append(
                DataLineage(
                    series_id=symbol,
                    provider="Yahoo Finance via yfinance",
                    source_url="https://finance.yahoo.com/",
                    as_of=as_of,
                    frequency="Daily",
                    unit="Adjusted price",
                    status="OK",
                    is_proxy=True,
                    is_stale=_stale(as_of, "Daily"),
                    notes=FIXED_INCOME_PROXY_UNIVERSE.get(symbol, "Market proxy"),
                )
            )
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")
    if not frames:
        return DataResult(lineage=lineage, errors=errors)
    merged = frames[0]
    for one in frames[1:]:
        merged = pd.merge(merged, one, on="date", how="outer")
    return DataResult(frame=merged.sort_values("date").reset_index(drop=True), lineage=lineage, errors=errors)


# -----------------------------------------------------------------------------
# OpenFIGI and SEC EDGAR
# -----------------------------------------------------------------------------

def map_openfigi(id_type: str, id_value: str) -> DataResult:
    url = "https://api.openfigi.com/v3/mapping"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    api_key = get_secret("OPENFIGI_API_KEY")
    if api_key:
        headers["X-OPENFIGI-APIKEY"] = api_key
    try:
        s = _session()
        s.headers.update(headers)
        response = s.post(url, json=[{"idType": id_type, "idValue": id_value}], timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        first = payload[0] if isinstance(payload, list) and payload else {}
        data = first.get("data", []) if isinstance(first, dict) else []
        frame = pd.DataFrame(data)
        lineage = DataLineage(
            series_id=f"{id_type}:{id_value}",
            provider="OpenFIGI",
            source_url=url,
            frequency="On demand",
            unit="Security master",
            status="OK" if not frame.empty else "WAIT",
            notes=first.get("error", "") if isinstance(first, dict) else "",
        )
        return DataResult(frame=frame, lineage=[lineage], warnings=[first.get("error", "")] if isinstance(first, dict) and first.get("error") else [])
    except Exception as exc:
        return DataResult(
            errors=[str(exc)],
            lineage=[DataLineage(series_id=f"{id_type}:{id_value}", provider="OpenFIGI", source_url=url, status="ERROR", notes=str(exc))],
        )


def sec_ticker_to_cik(ticker: str) -> tuple[str | None, str | None]:
    url = "https://www.sec.gov/files/company_tickers.json"
    try:
        payload = request_json(url, cache_key="sec_company_tickers", cache_ttl=86400)
        for item in payload.values() if isinstance(payload, dict) else []:
            if str(item.get("ticker", "")).upper() == str(ticker).upper():
                return str(item.get("cik_str", "")).zfill(10), item.get("title")
    except Exception:
        return None, None
    return None, None


def load_sec_companyfacts(ticker: str) -> DataResult:
    cik, company_name = sec_ticker_to_cik(ticker)
    if not cik:
        return DataResult(errors=[f"Unable to map ticker {ticker} to a CIK"])
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    try:
        payload = request_json(url, cache_key=f"sec_companyfacts_{cik}", cache_ttl=21600)
        facts = payload.get("facts", {}).get("us-gaap", {}) if isinstance(payload, dict) else {}
        rows: list[dict[str, Any]] = []
        for tag, definition in facts.items():
            units = definition.get("units", {}) if isinstance(definition, dict) else {}
            for unit, observations in units.items():
                if not isinstance(observations, list):
                    continue
                for obs in observations:
                    if not isinstance(obs, dict):
                        continue
                    rows.append(
                        {
                            "tag": tag,
                            "label": definition.get("label", tag),
                            "description": definition.get("description", ""),
                            "unit": unit,
                            "value": obs.get("val"),
                            "start": obs.get("start"),
                            "end": obs.get("end"),
                            "filed": obs.get("filed"),
                            "form": obs.get("form"),
                            "fy": obs.get("fy"),
                            "fp": obs.get("fp"),
                            "accn": obs.get("accn"),
                            "frame": obs.get("frame"),
                        }
                    )
        frame = pd.DataFrame(rows)
        for col in ["start", "end", "filed"]:
            if col in frame.columns:
                frame[col] = pd.to_datetime(frame[col], errors="coerce")
        lineage = DataLineage(
            series_id=f"SEC_COMPANYFACTS_{cik}",
            provider="U.S. Securities and Exchange Commission / EDGAR",
            source_url=url,
            as_of=datetime.now(timezone.utc),
            frequency="Filing",
            unit="Mixed XBRL",
            status="OK",
            notes=f"{company_name or ticker}; SEC user agent must identify the application and contact.",
        )
        warnings = []
        if "contact@example.com" in sec_user_agent():
            warnings.append("Configure SEC_USER_AGENT with a real application name and contact email before production use.")
        return DataResult(frame=frame, lineage=[lineage], warnings=warnings)
    except Exception as exc:
        return DataResult(
            errors=[str(exc)],
            lineage=[DataLineage(series_id=f"SEC_COMPANYFACTS_{cik}", provider="SEC EDGAR", source_url=url, status="ERROR", notes=str(exc))],
        )


def latest_sec_fact(frame: pd.DataFrame, tags: Sequence[str], unit_preference: Sequence[str] = ("USD", "USD/shares", "shares")) -> float | None:
    if frame is None or frame.empty:
        return None
    sub = frame[frame["tag"].isin(tags)].copy()
    if sub.empty:
        return None
    sub = sub[sub["form"].isin(["10-K", "10-Q", "20-F", "40-F", "6-K"])]
    if sub.empty:
        return None
    for unit in unit_preference:
        one = sub[sub["unit"] == unit].sort_values(["end", "filed"])
        values = pd.to_numeric(one["value"], errors="coerce").dropna()
        if not values.empty:
            return float(values.iloc[-1])
    values = pd.to_numeric(sub.sort_values(["end", "filed"])["value"], errors="coerce").dropna()
    return float(values.iloc[-1]) if not values.empty else None


def derive_issuer_credit_fundamentals(companyfacts: pd.DataFrame) -> dict[str, float | None]:
    total_debt = latest_sec_fact(
        companyfacts,
        [
            "LongTermDebtAndFinanceLeaseObligationsCurrent",
            "LongTermDebtCurrent",
            "ShortTermBorrowings",
            "LongTermDebtAndFinanceLeaseObligations",
            "LongTermDebtNoncurrent",
        ],
    )
    cash = latest_sec_fact(companyfacts, ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"])
    operating_income = latest_sec_fact(companyfacts, ["OperatingIncomeLoss"])
    depreciation = latest_sec_fact(companyfacts, ["DepreciationDepletionAndAmortization", "DepreciationDepletionAndAmortizationPropertyPlantAndEquipment"])
    interest_expense = latest_sec_fact(companyfacts, ["InterestExpenseNonOperating", "InterestAndDebtExpense"])
    operating_cashflow = latest_sec_fact(companyfacts, ["NetCashProvidedByUsedInOperatingActivities"])
    capex = latest_sec_fact(companyfacts, ["PaymentsToAcquirePropertyPlantAndEquipment"])
    current_assets = latest_sec_fact(companyfacts, ["AssetsCurrent"])
    current_liabilities = latest_sec_fact(companyfacts, ["LiabilitiesCurrent"])
    ebitda = None if operating_income is None else operating_income + (depreciation or 0.0)
    fcf = None if operating_cashflow is None else operating_cashflow - abs(capex or 0.0)
    net_debt = None if total_debt is None else total_debt - (cash or 0.0)
    return {
        "total_debt": total_debt,
        "cash": cash,
        "net_debt": net_debt,
        "ebitda_proxy": ebitda,
        "free_cash_flow_proxy": fcf,
        "interest_expense": interest_expense,
        "net_leverage": net_debt / ebitda if net_debt is not None and ebitda not in (None, 0) else None,
        "interest_coverage": ebitda / abs(interest_expense) if ebitda is not None and interest_expense not in (None, 0) else None,
        "liquidity_ratio": current_assets / current_liabilities if current_assets is not None and current_liabilities not in (None, 0) else None,
        "fcf_to_debt": fcf / total_debt if fcf is not None and total_debt not in (None, 0) else None,
    }


# -----------------------------------------------------------------------------
# User-provided / licensed datasets
# -----------------------------------------------------------------------------

def parse_uploaded_table(file_obj: Any) -> DataResult:
    name = str(getattr(file_obj, "name", "uploaded"))
    try:
        if name.lower().endswith(".csv"):
            frame = pd.read_csv(file_obj)
        elif name.lower().endswith((".xlsx", ".xls")):
            frame = pd.read_excel(file_obj)
        elif name.lower().endswith(".parquet"):
            frame = pd.read_parquet(file_obj)
        else:
            raise ValueError("Supported formats: CSV, XLSX/XLS, Parquet")
        lineage = DataLineage(
            series_id=name,
            provider="User upload",
            source_url="local upload",
            as_of=datetime.now(timezone.utc),
            frequency="User supplied",
            unit="As provided",
            status="OK",
            notes="No vendor entitlement or field semantics inferred automatically.",
        )
        return DataResult(frame=frame, lineage=[lineage])
    except Exception as exc:
        return DataResult(errors=[str(exc)])


def trace_provider_status() -> DataResult:
    return DataResult(
        provider_required=True,
        warnings=[
            "Public FINRA reports support market-level and compliance analytics, but full transaction-level TRACE history and end-of-day files require the appropriate FINRA data product or entitlement."
        ],
        lineage=[
            DataLineage(
                series_id="TRACE_TRANSACTION_DATA",
                provider="FINRA TRACE",
                source_url="https://www.finra.org/finra-data/browse-catalog",
                frequency="Transaction / daily depending product",
                unit="Price, yield, volume and trade metadata",
                status="PROVIDER_REQUIRED",
                notes="Do not substitute simulated trades for licensed TRACE observations.",
            )
        ],
    )


def licensed_provider_registry() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"dataset": "Bond evaluated prices / reference data", "status": "PROVIDER REQUIRED", "examples": "Bloomberg, LSEG, ICE, FactSet, S&P Capital IQ"},
            {"dataset": "Single-name CDS / CDX / iTraxx", "status": "PROVIDER REQUIRED", "examples": "Bloomberg, LSEG, ICE, S&P Global"},
            {"dataset": "Swap / OIS curves", "status": "PUBLIC PARTIAL / PROVIDER REQUIRED", "examples": "Central banks, Bloomberg, LSEG"},
            {"dataset": "Swaption / cap-floor surfaces", "status": "PROVIDER REQUIRED", "examples": "Bloomberg, LSEG, CME, ICE"},
            {"dataset": "TRACE transaction history", "status": "FINRA PRODUCT / ENTITLEMENT", "examples": "FINRA"},
            {"dataset": "Ratings, transitions and defaults", "status": "PROVIDER REQUIRED FOR FULL MATRICES", "examples": "Moody's, S&P, Fitch"},
            {"dataset": "Dealer axes / inventories", "status": "PROVIDER REQUIRED", "examples": "Dealer feeds, Bloomberg ALLQ, MarketAxess"},
        ]
    )


# -----------------------------------------------------------------------------
# Explicit demo data - never called silently by live loaders
# -----------------------------------------------------------------------------

def demo_curve_history(days: int = 900, seed: int = 7) -> DataResult:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
    tenors = list(US_NOMINAL_CURVE_SERIES.keys())
    years = np.array([1 / 12, 0.25, 0.5, 1, 2, 3, 5, 7, 10, 20, 30], dtype=float)
    level = 3.5 + np.cumsum(rng.normal(0, 0.018, days))
    slope = -0.4 + np.cumsum(rng.normal(0, 0.008, days))
    curvature = np.cumsum(rng.normal(0, 0.004, days))
    matrix = []
    for i in range(days):
        base = level[i] + slope[i] * np.exp(-years / 5) + curvature[i] * years * np.exp(-years / 4)
        matrix.append(base + rng.normal(0, 0.006, len(years)))
    frame = pd.DataFrame(matrix, columns=tenors)
    frame.insert(0, "date", dates)
    lineage = DataLineage(
        series_id="EXPLICIT_DEMO_CURVE",
        provider="Quant Terminal demo generator",
        source_url="local deterministic generator",
        as_of=datetime.now(timezone.utc),
        frequency="Daily",
        unit="Percent",
        status="DEMO",
        is_proxy=True,
        notes="Explicit demo mode only; not observed market data.",
    )
    return DataResult(frame=frame, lineage=[lineage], warnings=["DEMO DATA - NOT MARKET OBSERVATIONS"])


def demo_credit_history(days: int = 900, seed: int = 11) -> DataResult:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
    market = np.maximum(0, np.cumsum(rng.normal(0, 1.8, days)))
    ig = 90 + 0.35 * market + rng.normal(0, 3, days)
    hy = 330 + 1.4 * market + rng.normal(0, 12, days)
    frame = pd.DataFrame(
        {
            "date": dates,
            "US IG OAS": np.maximum(40, ig),
            "US BBB OAS": np.maximum(65, ig + 55 + rng.normal(0, 4, days)),
            "US HY OAS": np.maximum(180, hy),
            "US BB OAS": np.maximum(150, hy - 80 + rng.normal(0, 8, days)),
            "US B OAS": np.maximum(250, hy + 120 + rng.normal(0, 12, days)),
            "US CCC & Lower OAS": np.maximum(500, hy + 650 + rng.normal(0, 30, days)),
        }
    )
    lineage = DataLineage(
        series_id="EXPLICIT_DEMO_CREDIT",
        provider="Quant Terminal demo generator",
        source_url="local deterministic generator",
        as_of=datetime.now(timezone.utc),
        frequency="Daily",
        unit="Basis points",
        status="DEMO",
        is_proxy=True,
        notes="Explicit demo mode only; not observed market data.",
    )
    return DataResult(frame=frame, lineage=[lineage], warnings=["DEMO DATA - NOT MARKET OBSERVATIONS"])


def build_data_monitor(results: Mapping[str, DataResult]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for dataset, result in results.items():
        for row in result.monitor_rows():
            row["dataset"] = dataset
            rows.append(row)
        if not result.lineage and result.provider_required:
            rows.append({"dataset": dataset, "status": "PROVIDER_REQUIRED"})
    if not rows:
        return pd.DataFrame(columns=["dataset", "provider", "series_id", "status", "as_of", "is_stale", "notes"])
    frame = pd.DataFrame(rows)
    preferred = ["dataset", "provider", "series_id", "status", "as_of", "retrieved_at", "frequency", "unit", "is_proxy", "is_stale", "notes", "source_url"]
    return frame[[c for c in preferred if c in frame.columns]]

# ============================================================================
# ANALYTICS ENGINE
# ============================================================================

# -----------------------------------------------------------------------------
# Generic helpers
# -----------------------------------------------------------------------------

def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        out = float(value)
        if not np.isfinite(out):
            return default
        return out
    except Exception:
        return default


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _as_timestamp(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_convert(None)
    return ts.normalize()


def _normal_cdf(x: float) -> float:
    """Standard normal CDF without requiring scipy.stats."""
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def _normal_pdf(x: float) -> float:
    return exp(-0.5 * x * x) / sqrt(2.0 * np.pi)


def _normal_ppf(p: float) -> float:
    """Acklam rational approximation to the inverse standard normal CDF."""
    p = clamp(p, 1e-12, 1 - 1e-12)
    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    ]
    d = [
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    ]
    plow = 0.02425
    phigh = 1 - plow
    if p < plow:
        q = sqrt(-2 * log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q) + 1
        )
    if p <= phigh:
        q = p - 0.5
        r = q * q
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (
            (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r) + 1
        )
    q = sqrt(-2 * log(1 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
        ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q) + 1
    )


# -----------------------------------------------------------------------------
# Domain objects
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class CurvePoint:
    tenor_years: float
    rate: float
    label: str = ""


@dataclass
class BondSpec:
    face_value: float = 100.0
    coupon_rate: float = 0.05
    settlement_date: date | datetime | pd.Timestamp = field(default_factory=lambda: pd.Timestamp.today().date())
    maturity_date: date | datetime | pd.Timestamp = field(
        default_factory=lambda: (pd.Timestamp.today() + pd.DateOffset(years=5)).date()
    )
    coupon_frequency: int = 2
    day_count: str = "30/360"
    redemption_value: float | None = None
    clean_price: float | None = None
    market_yield: float | None = None
    spread: float = 0.0
    currency: str = "USD"
    issuer: str = ""
    identifier: str = ""
    callable: bool = False
    call_date: date | datetime | pd.Timestamp | None = None
    call_price: float | None = None

    def __post_init__(self) -> None:
        self.face_value = float(self.face_value)
        self.coupon_rate = float(self.coupon_rate)
        self.coupon_frequency = int(self.coupon_frequency)
        self.redemption_value = float(self.redemption_value or self.face_value)
        self.spread = float(self.spread or 0.0)
        if self.coupon_frequency not in {1, 2, 4, 12}:
            raise ValueError("coupon_frequency must be one of 1, 2, 4, 12")
        if _as_timestamp(self.maturity_date) <= _as_timestamp(self.settlement_date):
            raise ValueError("maturity_date must be after settlement_date")


@dataclass(frozen=True)
class ScenarioShock:
    name: str
    parallel_rate_bp: float = 0.0
    short_rate_bp: float = 0.0
    long_rate_bp: float = 0.0
    spread_bp: float = 0.0
    fx_pct: float = 0.0
    liquidity_haircut_pct: float = 0.0
    recovery_rate_change: float = 0.0
    volatility_multiplier: float = 1.0


DEFAULT_SCENARIOS: tuple[ScenarioShock, ...] = (
    ScenarioShock("Parallel +50 bp", parallel_rate_bp=50),
    ScenarioShock("Parallel -50 bp", parallel_rate_bp=-50),
    ScenarioShock("Bear steepener", parallel_rate_bp=25, short_rate_bp=0, long_rate_bp=50),
    ScenarioShock("Bull steepener", parallel_rate_bp=-25, short_rate_bp=-50, long_rate_bp=0),
    ScenarioShock("Bear flattener", parallel_rate_bp=25, short_rate_bp=50, long_rate_bp=0),
    ScenarioShock("Bull flattener", parallel_rate_bp=-25, short_rate_bp=0, long_rate_bp=-50),
    ScenarioShock("IG spread +75 bp", spread_bp=75),
    ScenarioShock("HY spread +300 bp", spread_bp=300, liquidity_haircut_pct=2.0),
    ScenarioShock("Rates +100 / spread +150", parallel_rate_bp=100, spread_bp=150),
    ScenarioShock("Liquidity shock", liquidity_haircut_pct=5.0),
)


# -----------------------------------------------------------------------------
# Day count, schedules and fixed-rate bond analytics
# -----------------------------------------------------------------------------

def year_fraction(start: Any, end: Any, convention: str = "ACT/365") -> float:
    s = _as_timestamp(start)
    e = _as_timestamp(end)
    if e < s:
        return -year_fraction(e, s, convention)
    c = convention.upper().replace(" ", "")
    if c in {"ACT/365", "ACT365", "ACT/365F"}:
        return (e - s).days / 365.0
    if c in {"ACT/360", "ACT360"}:
        return (e - s).days / 360.0
    if c in {"30/360", "30E/360", "BOND"}:
        d1 = min(s.day, 30)
        d2 = min(e.day, 30) if d1 == 30 else e.day
        return ((e.year - s.year) * 360 + (e.month - s.month) * 30 + (d2 - d1)) / 360.0
    if c in {"ACT/ACT", "ACTACT"}:
        if s.year == e.year:
            denom = 366.0 if pd.Timestamp(s.year, 12, 31).is_leap_year else 365.0
            return (e - s).days / denom
        total = 0.0
        cursor = s
        while cursor.year < e.year:
            year_end = pd.Timestamp(cursor.year + 1, 1, 1)
            denom = 366.0 if cursor.is_leap_year else 365.0
            total += (year_end - cursor).days / denom
            cursor = year_end
        denom = 366.0 if cursor.is_leap_year else 365.0
        total += (e - cursor).days / denom
        return total
    raise ValueError(f"Unsupported day-count convention: {convention}")


def generate_coupon_schedule(
    settlement_date: Any,
    maturity_date: Any,
    frequency: int = 2,
) -> pd.DatetimeIndex:
    settlement = _as_timestamp(settlement_date)
    maturity = _as_timestamp(maturity_date)
    months = int(round(12 / frequency))
    dates: list[pd.Timestamp] = [maturity]
    cursor = maturity
    for _ in range(1200):
        cursor = cursor - pd.DateOffset(months=months)
        dates.append(cursor)
        if cursor <= settlement:
            break
    if dates[-1] > settlement:
        raise ValueError("Unable to build coupon schedule")
    return pd.DatetimeIndex(sorted(dates))


def previous_next_coupon(spec: BondSpec) -> tuple[pd.Timestamp, pd.Timestamp]:
    schedule = generate_coupon_schedule(spec.settlement_date, spec.maturity_date, spec.coupon_frequency)
    settlement = _as_timestamp(spec.settlement_date)
    prev_dates = schedule[schedule <= settlement]
    next_dates = schedule[schedule > settlement]
    previous = prev_dates[-1] if len(prev_dates) else schedule[0]
    next_coupon = next_dates[0] if len(next_dates) else _as_timestamp(spec.maturity_date)
    return previous, next_coupon


def accrued_interest(spec: BondSpec) -> float:
    previous, next_coupon = previous_next_coupon(spec)
    elapsed = year_fraction(previous, spec.settlement_date, spec.day_count)
    period = year_fraction(previous, next_coupon, spec.day_count)
    if period <= 0:
        return 0.0
    coupon = spec.face_value * spec.coupon_rate / spec.coupon_frequency
    return coupon * clamp(elapsed / period, 0.0, 1.0)


def bond_cashflows(spec: BondSpec) -> pd.DataFrame:
    settlement = _as_timestamp(spec.settlement_date)
    schedule = generate_coupon_schedule(spec.settlement_date, spec.maturity_date, spec.coupon_frequency)
    future_dates = schedule[schedule > settlement]
    coupon = spec.face_value * spec.coupon_rate / spec.coupon_frequency
    rows: list[dict[str, Any]] = []
    for d in future_dates:
        amount = coupon
        principal = 0.0
        if d == future_dates[-1]:
            principal = float(spec.redemption_value or spec.face_value)
            amount += principal
        rows.append(
            {
                "date": d,
                "time_years": year_fraction(settlement, d, "ACT/365"),
                "coupon": coupon,
                "principal": principal,
                "cashflow": amount,
            }
        )
    return pd.DataFrame(rows)


def dirty_price_from_ytm(spec: BondSpec, ytm: float) -> float:
    ytm = float(ytm)
    cashflows = bond_cashflows(spec)
    if cashflows.empty:
        return 0.0
    freq = spec.coupon_frequency
    base = 1.0 + ytm / freq
    if base <= 0:
        return float("inf")
    periods = cashflows["time_years"].to_numpy(float) * freq
    return float(np.sum(cashflows["cashflow"].to_numpy(float) / np.power(base, periods)))


def clean_price_from_ytm(spec: BondSpec, ytm: float) -> float:
    return dirty_price_from_ytm(spec, ytm) - accrued_interest(spec)


def _bisect_root(fn, low: float, high: float, tol: float = 1e-11, max_iter: int = 300) -> float:
    f_low = fn(low)
    f_high = fn(high)
    if not np.isfinite(f_low) or not np.isfinite(f_high) or f_low * f_high > 0:
        raise ValueError("Root is not bracketed")
    for _ in range(max_iter):
        mid = 0.5 * (low + high)
        f_mid = fn(mid)
        if abs(f_mid) < tol or abs(high - low) < tol:
            return mid
        if f_low * f_mid <= 0:
            high = mid
            f_high = f_mid
        else:
            low = mid
            f_low = f_mid
    return 0.5 * (low + high)


def ytm_from_clean_price(spec: BondSpec, clean_price: float) -> float:
    target_dirty = float(clean_price) + accrued_interest(spec)

    def objective(y: float) -> float:
        return dirty_price_from_ytm(spec, y) - target_dirty

    low = -0.95 * spec.coupon_frequency
    high = 5.0
    if brentq is not None:
        return float(brentq(objective, low, high, maxiter=500))
    return float(_bisect_root(objective, low, high))


def bond_risk_metrics(spec: BondSpec, ytm: float, bump_bp: float = 1.0) -> dict[str, float]:
    ytm = float(ytm)
    price_dirty = dirty_price_from_ytm(spec, ytm)
    price_clean = price_dirty - accrued_interest(spec)
    cf = bond_cashflows(spec)
    if cf.empty or price_dirty <= 0:
        return {
            "clean_price": price_clean,
            "dirty_price": price_dirty,
            "macaulay_duration": np.nan,
            "modified_duration": np.nan,
            "convexity": np.nan,
            "dv01": np.nan,
        }
    freq = spec.coupon_frequency
    t = cf["time_years"].to_numpy(float)
    values = cf["cashflow"].to_numpy(float) / np.power(1 + ytm / freq, t * freq)
    macaulay = float(np.sum(t * values) / price_dirty)
    modified = macaulay / (1 + ytm / freq)
    bump = float(bump_bp) / 10000.0
    p_down = dirty_price_from_ytm(spec, ytm - bump)
    p_up = dirty_price_from_ytm(spec, ytm + bump)
    dv01 = (p_down - p_up) / 2.0
    convexity = (p_down + p_up - 2 * price_dirty) / (price_dirty * bump * bump)
    return {
        "clean_price": float(price_clean),
        "dirty_price": float(price_dirty),
        "accrued_interest": float(accrued_interest(spec)),
        "current_yield": float(spec.face_value * spec.coupon_rate / price_clean) if price_clean else np.nan,
        "macaulay_duration": float(macaulay),
        "modified_duration": float(modified),
        "effective_duration": float((p_down - p_up) / (2 * price_dirty * bump)),
        "convexity": float(convexity),
        "dv01": float(dv01),
        "yield": float(ytm),
    }


def price_from_zero_curve(spec: BondSpec, tenors: Sequence[float], zero_rates: Sequence[float], z_spread: float = 0.0) -> float:
    cf = bond_cashflows(spec)
    if cf.empty:
        return 0.0
    x = np.asarray(tenors, dtype=float)
    y = np.asarray(zero_rates, dtype=float)
    order = np.argsort(x)
    x, y = x[order], y[order]
    t = cf["time_years"].to_numpy(float)
    z = np.interp(t, x, y, left=y[0], right=y[-1]) + float(z_spread)
    discounts = np.exp(-z * t)
    dirty = float(np.sum(cf["cashflow"].to_numpy(float) * discounts))
    return dirty - accrued_interest(spec)


def z_spread_from_price(
    spec: BondSpec,
    clean_price: float,
    tenors: Sequence[float],
    zero_rates: Sequence[float],
) -> float:
    target = float(clean_price)

    def objective(spread: float) -> float:
        return price_from_zero_curve(spec, tenors, zero_rates, spread) - target

    if brentq is not None:
        return float(brentq(objective, -0.20, 5.0, maxiter=500))
    return float(_bisect_root(objective, -0.20, 5.0))


def key_rate_durations(
    spec: BondSpec,
    tenors: Sequence[float],
    zero_rates: Sequence[float],
    key_tenors: Sequence[float] = (0.5, 1, 2, 3, 5, 7, 10, 20, 30),
    bump_bp: float = 1.0,
) -> pd.DataFrame:
    x = np.asarray(tenors, dtype=float)
    y = np.asarray(zero_rates, dtype=float)
    base = price_from_zero_curve(spec, x, y)
    bump = float(bump_bp) / 10000.0
    rows = []
    for key in key_tenors:
        width = max(0.5, key * 0.35)
        weights = np.maximum(1.0 - np.abs(x - key) / width, 0.0)
        up = price_from_zero_curve(spec, x, y + bump * weights)
        down = price_from_zero_curve(spec, x, y - bump * weights)
        duration = (down - up) / (2 * base * bump) if base else np.nan
        dv01 = (down - up) / 2.0
        rows.append({"tenor": float(key), "key_rate_duration": float(duration), "dv01": float(dv01)})
    return pd.DataFrame(rows)


# -----------------------------------------------------------------------------
# Yield-curve analytics
# -----------------------------------------------------------------------------

TENOR_LABEL_TO_YEARS: dict[str, float] = {
    "1M": 1 / 12,
    "1.5M": 1.5 / 12,
    "2M": 2 / 12,
    "3M": 0.25,
    "4M": 4 / 12,
    "6M": 0.5,
    "1Y": 1.0,
    "2Y": 2.0,
    "3Y": 3.0,
    "5Y": 5.0,
    "7Y": 7.0,
    "10Y": 10.0,
    "20Y": 20.0,
    "30Y": 30.0,
}


def normalize_curve_history(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    df = frame.copy()
    if "date" not in df.columns:
        df = df.reset_index().rename(columns={df.index.name or "index": "date"})
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    rename: dict[str, str] = {}
    for col in df.columns:
        text = str(col).strip().upper().replace(" ", "")
        text = text.replace("YR", "Y").replace("MO", "M")
        if text in TENOR_LABEL_TO_YEARS:
            rename[col] = text
    df = df.rename(columns=rename)
    tenor_cols = [c for c in TENOR_LABEL_TO_YEARS if c in df.columns]
    for col in tenor_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df[["date", *tenor_cols]].dropna(subset=["date"]).sort_values("date").reset_index(drop=True)


def latest_curve(frame: pd.DataFrame) -> pd.DataFrame:
    df = normalize_curve_history(frame)
    if df.empty:
        return pd.DataFrame(columns=["tenor", "tenor_years", "rate"])
    row = df.dropna(how="all", subset=[c for c in df.columns if c != "date"]).iloc[-1]
    rows = []
    for label, years in TENOR_LABEL_TO_YEARS.items():
        if label in df.columns and pd.notna(row[label]):
            rows.append({"tenor": label, "tenor_years": years, "rate": float(row[label])})
    return pd.DataFrame(rows).sort_values("tenor_years").reset_index(drop=True)


def curve_snapshot_metrics(curve: pd.DataFrame) -> dict[str, float | str | None]:
    if curve is None or curve.empty:
        return {}
    lookup = {str(r.tenor).upper(): float(r.rate) for r in curve.itertuples()}

    def spread(long: str, short: str) -> float | None:
        if long not in lookup or short not in lookup:
            return None
        return (lookup[long] - lookup[short]) * 100.0  # bp when rates are percentages

    def fly(short: str, belly: str, long: str) -> float | None:
        if not all(x in lookup for x in (short, belly, long)):
            return None
        return (2 * lookup[belly] - lookup[short] - lookup[long]) * 100.0

    s2s10 = spread("10Y", "2Y")
    s5s30 = spread("30Y", "5Y")
    s3m10 = spread("10Y", "3M")
    if s2s10 is None:
        regime = "N/A"
    elif s2s10 < -25:
        regime = "Deeply inverted"
    elif s2s10 < 0:
        regime = "Inverted"
    elif s2s10 < 50:
        regime = "Flat"
    else:
        regime = "Steep"
    return {
        "2s10s_bp": s2s10,
        "5s30s_bp": s5s30,
        "3m10y_bp": s3m10,
        "2s5s10s_fly_bp": fly("2Y", "5Y", "10Y"),
        "5s10s30s_fly_bp": fly("5Y", "10Y", "30Y"),
        "curve_regime": regime,
        "level_10y": lookup.get("10Y"),
    }


def curve_change_table(frame: pd.DataFrame, lags: Mapping[str, int] | None = None) -> pd.DataFrame:
    df = normalize_curve_history(frame)
    if df.empty:
        return pd.DataFrame()
    lags = lags or {"1D": 1, "5D": 5, "1M": 21, "3M": 63, "1Y": 252}
    tenor_cols = [c for c in df.columns if c != "date"]
    current = df.iloc[-1]
    rows = []
    for tenor in tenor_cols:
        row: dict[str, Any] = {"tenor": tenor, "current": safe_float(current[tenor])}
        for label, lag in lags.items():
            if len(df) > lag and pd.notna(df.iloc[-1 - lag][tenor]) and pd.notna(current[tenor]):
                row[f"change_{label}_bp"] = (float(current[tenor]) - float(df.iloc[-1 - lag][tenor])) * 100.0
            else:
                row[f"change_{label}_bp"] = np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def historical_curve_percentiles(frame: pd.DataFrame, window: int = 756) -> pd.DataFrame:
    df = normalize_curve_history(frame)
    if df.empty:
        return pd.DataFrame()
    work = df.tail(window)
    rows = []
    for tenor in [c for c in work.columns if c != "date"]:
        series = work[tenor].dropna()
        if series.empty:
            continue
        current = float(series.iloc[-1])
        percentile = float((series <= current).mean())
        z = float((current - series.mean()) / series.std(ddof=1)) if series.std(ddof=1) > 0 else 0.0
        rows.append(
            {
                "tenor": tenor,
                "current": current,
                "percentile": percentile,
                "z_score": z,
                "min": float(series.min()),
                "max": float(series.max()),
            }
        )
    return pd.DataFrame(rows)


def pca_curve_factors(frame: pd.DataFrame, n_components: int = 3, on_changes: bool = True) -> dict[str, Any]:
    df = normalize_curve_history(frame)
    tenor_cols = [c for c in df.columns if c != "date"]
    matrix = df[tenor_cols].astype(float)
    if on_changes:
        matrix = matrix.diff()
    matrix = matrix.dropna()
    if matrix.shape[0] < 5 or matrix.shape[1] < 2:
        return {"available": False, "reason": "Insufficient complete curve history"}
    x = matrix.to_numpy(float)
    x = x - x.mean(axis=0, keepdims=True)
    std = x.std(axis=0, ddof=1)
    std[std == 0] = 1.0
    z = x / std
    u, s, vt = np.linalg.svd(z, full_matrices=False)
    k = min(n_components, vt.shape[0])
    explained = (s * s) / np.sum(s * s)
    loadings = pd.DataFrame(vt[:k].T, index=tenor_cols, columns=[f"PC{i+1}" for i in range(k)]).reset_index(names="tenor")
    scores = pd.DataFrame(u[:, :k] * s[:k], columns=[f"PC{i+1}" for i in range(k)])
    scores.insert(0, "date", matrix.index.map(lambda i: df.loc[i, "date"]).to_numpy())
    return {
        "available": True,
        "explained_variance": pd.DataFrame(
            {"factor": [f"PC{i+1}" for i in range(k)], "explained_variance": explained[:k]}
        ),
        "loadings": loadings,
        "scores": scores,
    }


def nelson_siegel_svensson_rate(
    maturities: Sequence[float],
    beta0: float,
    beta1: float,
    beta2: float,
    beta3: float,
    tau1: float,
    tau2: float,
) -> np.ndarray:
    t = np.asarray(maturities, dtype=float)
    t = np.maximum(t, 1e-8)
    tau1 = max(float(tau1), 1e-6)
    tau2 = max(float(tau2), 1e-6)
    x1 = t / tau1
    x2 = t / tau2
    f1 = (1 - np.exp(-x1)) / x1
    f2 = f1 - np.exp(-x1)
    f3 = (1 - np.exp(-x2)) / x2 - np.exp(-x2)
    return beta0 + beta1 * f1 + beta2 * f2 + beta3 * f3


def fit_nelson_siegel_svensson(curve: pd.DataFrame) -> dict[str, Any]:
    if curve is None or curve.empty or len(curve) < 4:
        return {"available": False, "reason": "At least four curve points are required"}
    t = pd.to_numeric(curve["tenor_years"], errors="coerce").to_numpy(float)
    y = pd.to_numeric(curve["rate"], errors="coerce").to_numpy(float)
    mask = np.isfinite(t) & np.isfinite(y)
    t, y = t[mask], y[mask]
    if len(t) < 4:
        return {"available": False, "reason": "Insufficient valid curve points"}
    initial = np.array([y[-1], y[0] - y[-1], 0.0, 0.0, 1.5, 5.0])

    def residuals(params: np.ndarray) -> np.ndarray:
        return nelson_siegel_svensson_rate(t, *params) - y

    if least_squares is not None:
        fit = least_squares(
            residuals,
            initial,
            bounds=(np.array([-20, -30, -30, -30, 0.05, 0.05]), np.array([30, 30, 30, 30, 30, 60])),
            max_nfev=10000,
        )
        params = fit.x
        success = bool(fit.success)
    else:  # fixed taus, linear least squares fallback
        tau1, tau2 = 1.5, 5.0
        x1 = t / tau1
        x2 = t / tau2
        design = np.column_stack(
            [
                np.ones_like(t),
                (1 - np.exp(-x1)) / x1,
                (1 - np.exp(-x1)) / x1 - np.exp(-x1),
                (1 - np.exp(-x2)) / x2 - np.exp(-x2),
            ]
        )
        betas = np.linalg.lstsq(design, y, rcond=None)[0]
        params = np.r_[betas, tau1, tau2]
        success = True
    fitted = nelson_siegel_svensson_rate(t, *params)
    residual = y - fitted
    return {
        "available": True,
        "success": success,
        "parameters": {
            "beta0": float(params[0]),
            "beta1": float(params[1]),
            "beta2": float(params[2]),
            "beta3": float(params[3]),
            "tau1": float(params[4]),
            "tau2": float(params[5]),
        },
        "rmse": float(np.sqrt(np.mean(residual * residual))),
        "fit": pd.DataFrame({"tenor_years": t, "observed": y, "fitted": fitted, "residual": residual}),
    }


def zero_rates_to_discount_factors(tenors: Sequence[float], zero_rates: Sequence[float], rates_in_percent: bool = True) -> pd.DataFrame:
    t = np.asarray(tenors, dtype=float)
    r = np.asarray(zero_rates, dtype=float)
    if rates_in_percent:
        r = r / 100.0
    discount = np.exp(-r * t)
    return pd.DataFrame({"tenor_years": t, "zero_rate": r, "discount_factor": discount})


def instantaneous_forward_rates(tenors: Sequence[float], zero_rates: Sequence[float], rates_in_percent: bool = True) -> pd.DataFrame:
    t = np.asarray(tenors, dtype=float)
    r = np.asarray(zero_rates, dtype=float)
    if rates_in_percent:
        r = r / 100.0
    order = np.argsort(t)
    t, r = t[order], r[order]
    rt = r * t
    fwd = np.gradient(rt, t)
    return pd.DataFrame({"tenor_years": t, "zero_rate": r, "instantaneous_forward": fwd})


def carry_roll_down(
    curve: pd.DataFrame,
    maturity_years: float,
    holding_period_years: float = 1 / 12,
    duration: float | None = None,
) -> dict[str, float]:
    if curve is None or curve.empty:
        return {"yield": np.nan, "carry": np.nan, "roll_down": np.nan, "total": np.nan}
    x = curve["tenor_years"].to_numpy(float)
    y = curve["rate"].to_numpy(float) / 100.0
    current_yield = float(np.interp(maturity_years, x, y))
    rolled_maturity = max(maturity_years - holding_period_years, x.min())
    rolled_yield = float(np.interp(rolled_maturity, x, y))
    assumed_duration = duration if duration is not None else max(0.1, maturity_years * 0.85)
    carry = current_yield * holding_period_years
    roll = -assumed_duration * (rolled_yield - current_yield)
    return {"yield": current_yield, "carry": carry, "roll_down": roll, "total": carry + roll}


# -----------------------------------------------------------------------------
# Relative value and econometrics
# -----------------------------------------------------------------------------

def rolling_zscore(series: pd.Series, window: int = 252, min_periods: int | None = None) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    mp = min_periods or max(20, window // 4)
    mean = s.rolling(window, min_periods=mp).mean()
    std = s.rolling(window, min_periods=mp).std(ddof=1).replace(0, np.nan)
    return (s - mean) / std


def mean_reversion_half_life(series: pd.Series) -> float | None:
    s = pd.to_numeric(series, errors="coerce").dropna()
    if len(s) < 20:
        return None
    lag = s.shift(1).dropna()
    delta = s.diff().dropna()
    aligned = pd.concat([lag, delta], axis=1).dropna()
    x = np.column_stack([np.ones(len(aligned)), aligned.iloc[:, 0].to_numpy(float)])
    y = aligned.iloc[:, 1].to_numpy(float)
    beta = np.linalg.lstsq(x, y, rcond=None)[0][1]
    if beta >= 0:
        return None
    return float(-log(2) / beta)


def cointegration_residual(y: pd.Series, x: pd.Series) -> dict[str, Any]:
    frame = pd.concat([pd.to_numeric(y, errors="coerce"), pd.to_numeric(x, errors="coerce")], axis=1).dropna()
    if len(frame) < 20:
        return {"available": False, "reason": "Insufficient overlapping observations"}
    yy = frame.iloc[:, 0].to_numpy(float)
    xx = frame.iloc[:, 1].to_numpy(float)
    design = np.column_stack([np.ones(len(xx)), xx])
    alpha, beta = np.linalg.lstsq(design, yy, rcond=None)[0]
    residual = yy - (alpha + beta * xx)
    residual_series = pd.Series(residual, index=frame.index, name="residual")
    return {
        "available": True,
        "alpha": float(alpha),
        "beta": float(beta),
        "residual": residual_series,
        "z_score": rolling_zscore(residual_series, min(252, max(20, len(residual_series) // 2))),
        "half_life": mean_reversion_half_life(residual_series),
    }


def dv01_neutral_notional(long_dv01_per_100: float, short_dv01_per_100: float, long_notional: float = 1_000_000) -> float:
    if short_dv01_per_100 == 0:
        raise ValueError("short_dv01_per_100 cannot be zero")
    return abs(long_notional * long_dv01_per_100 / short_dv01_per_100)


# -----------------------------------------------------------------------------
# Credit analytics
# -----------------------------------------------------------------------------

def hazard_rate_from_spread(spread_bp: float, recovery_rate: float = 0.40) -> float:
    recovery_rate = clamp(recovery_rate, 0.0, 0.99)
    return max(0.0, float(spread_bp) / 10000.0 / (1.0 - recovery_rate))


def cumulative_default_probability(hazard_rate: float, years: float) -> float:
    return float(1.0 - exp(-max(0.0, hazard_rate) * max(0.0, years)))


def expected_credit_loss(
    exposure: float,
    spread_bp: float,
    horizon_years: float = 1.0,
    recovery_rate: float = 0.40,
) -> float:
    hazard = hazard_rate_from_spread(spread_bp, recovery_rate)
    pd_default = cumulative_default_probability(hazard, horizon_years)
    return float(exposure * pd_default * (1.0 - recovery_rate))


def credit_index_dashboard(history: pd.DataFrame) -> pd.DataFrame:
    if history is None or history.empty:
        return pd.DataFrame()
    df = history.copy()
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.sort_values("date")
    rows = []
    for col in [c for c in df.columns if c != "date"]:
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        if s.empty:
            continue
        current = float(s.iloc[-1])
        change_1d = current - float(s.iloc[-2]) if len(s) > 1 else np.nan
        change_1m = current - float(s.iloc[-22]) if len(s) > 21 else np.nan
        percentile = float((s.tail(2520) <= current).mean())
        z = float((current - s.tail(756).mean()) / s.tail(756).std(ddof=1)) if s.tail(756).std(ddof=1) > 0 else 0.0
        rows.append(
            {
                "index": col,
                "oas_bp": current,
                "change_1d_bp": change_1d,
                "change_1m_bp": change_1m,
                "percentile": percentile,
                "z_score": z,
                "hazard_rate_40pct_recovery": hazard_rate_from_spread(current, 0.40),
            }
        )
    return pd.DataFrame(rows)


def build_credit_regime(history: pd.DataFrame) -> dict[str, Any]:
    dashboard = credit_index_dashboard(history)
    if dashboard.empty:
        return {"available": False, "label": "N/A", "score": np.nan, "components": pd.DataFrame()}
    rows = dashboard.copy()
    # Higher score = more stress.
    rows["stress_component"] = (
        rows["percentile"].clip(0, 1) * 50
        + np.maximum(rows["z_score"], 0).clip(0, 4) / 4 * 25
        + np.maximum(rows["change_1m_bp"], 0).fillna(0).clip(0, 300) / 300 * 25
    )
    score = float(rows["stress_component"].mean())
    if score >= 75:
        label = "Dislocation"
    elif score >= 60:
        label = "Stress"
    elif score >= 45:
        label = "Deterioration"
    elif score >= 30:
        label = "Late-cycle / neutral"
    else:
        label = "Compression"
    return {"available": True, "label": label, "score": score, "components": rows}


def issuer_credit_score(metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Transparent internal score, not a rating-agency grade."""
    leverage = safe_float(metrics.get("net_leverage"), 3.0) or 3.0
    coverage = safe_float(metrics.get("interest_coverage"), 3.0) or 3.0
    liquidity = safe_float(metrics.get("liquidity_ratio"), 1.0) or 1.0
    fcf_debt = safe_float(metrics.get("fcf_to_debt"), 0.05) or 0.05
    short_term_share = safe_float(metrics.get("short_term_debt_share"), 0.2) or 0.2
    market_spread = safe_float(metrics.get("market_spread_bp"), 200.0) or 200.0

    leverage_score = clamp(100 - leverage * 15, 0, 100)
    coverage_score = clamp(coverage * 12.5, 0, 100)
    liquidity_score = clamp(liquidity * 50, 0, 100)
    cashflow_score = clamp(50 + fcf_debt * 250, 0, 100)
    refinancing_score = clamp(100 - short_term_share * 120, 0, 100)
    market_score = clamp(100 - market_spread / 8, 0, 100)
    components = {
        "leverage": leverage_score,
        "coverage": coverage_score,
        "liquidity": liquidity_score,
        "cashflow": cashflow_score,
        "refinancing": refinancing_score,
        "market": market_score,
    }
    weights = {"leverage": 0.25, "coverage": 0.20, "liquidity": 0.15, "cashflow": 0.15, "refinancing": 0.10, "market": 0.15}
    composite = float(sum(components[k] * weights[k] for k in components))
    if composite >= 80:
        tier = "Strong"
    elif composite >= 65:
        tier = "Adequate"
    elif composite >= 50:
        tier = "Vulnerable"
    elif composite >= 35:
        tier = "Weak"
    else:
        tier = "Distressed"
    return {
        "score": composite,
        "tier": tier,
        "components": pd.DataFrame(
            [{"dimension": k, "score": v, "weight": weights[k], "contribution": v * weights[k]} for k, v in components.items()]
        ),
        "disclaimer": "Internal transparent analytical score; not a Moody's, S&P or Fitch rating.",
    }


# -----------------------------------------------------------------------------
# Portfolio analytics, risk and scenarios
# -----------------------------------------------------------------------------

PORTFOLIO_COLUMNS = [
    "identifier",
    "issuer",
    "sector",
    "rating",
    "currency",
    "quantity",
    "market_value",
    "clean_price",
    "yield",
    "duration",
    "spread_duration",
    "convexity",
    "dv01",
    "cs01",
    "spread_bp",
    "maturity_years",
    "fx_beta",
    "pd_1y",
    "recovery_rate",
    "spread_vol_bp",
    "bid_ask_bp",
    "daily_volume_mm",
    "issue_size_mm",
]


def normalize_portfolio(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=PORTFOLIO_COLUMNS)
    df = frame.copy()
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    aliases = {
        "ytm": "yield",
        "yield_to_maturity": "yield",
        "mod_duration": "duration",
        "modified_duration": "duration",
        "marketvalue": "market_value",
        "mv": "market_value",
        "oas": "spread_bp",
        "spread": "spread_bp",
        "maturity": "maturity_years",
    }
    df = df.rename(columns={k: v for k, v in aliases.items() if k in df.columns})
    for col in PORTFOLIO_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan if col not in {"identifier", "issuer", "sector", "rating", "currency"} else ""
    numeric_cols = [c for c in PORTFOLIO_COLUMNS if c not in {"identifier", "issuer", "sector", "rating", "currency"}]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["currency"] = df["currency"].replace("", "USD").fillna("USD").astype(str).str.upper().str.strip()
    df["rating"] = df["rating"].fillna("").astype(str).str.upper().str.strip()
    df["recovery_rate"] = df["recovery_rate"].fillna(0.40).clip(0.0, 0.99)
    df["pd_1y"] = df["pd_1y"].clip(0.0, 1.0)
    df["quantity"] = df["quantity"].fillna(1.0)
    df["market_value"] = df["market_value"].where(df["market_value"].notna(), df["quantity"] * df["clean_price"])
    df["dv01"] = df["dv01"].where(df["dv01"].notna(), df["market_value"] * df["duration"] / 10000.0)
    df["cs01"] = df["cs01"].where(df["cs01"].notna(), df["market_value"] * df["spread_duration"] / 10000.0)
    return df[PORTFOLIO_COLUMNS].copy()


def _weighted_average(df: pd.DataFrame, value_col: str, weight_col: str = "market_value") -> float:
    valid = df[[value_col, weight_col]].dropna()
    if valid.empty or valid[weight_col].abs().sum() == 0:
        return np.nan
    return float(np.average(valid[value_col], weights=valid[weight_col].abs()))


def portfolio_summary(frame: pd.DataFrame) -> dict[str, Any]:
    df = normalize_portfolio(frame)
    if df.empty:
        return {"available": False, "positions": df}
    total_mv = float(df["market_value"].sum())
    summary = {
        "available": True,
        "market_value": total_mv,
        "gross_market_value": float(df["market_value"].abs().sum()),
        "weighted_yield": _weighted_average(df, "yield"),
        "duration": _weighted_average(df, "duration"),
        "spread_duration": _weighted_average(df, "spread_duration"),
        "convexity": _weighted_average(df, "convexity"),
        "dv01": float(df["dv01"].sum(skipna=True)),
        "cs01": float(df["cs01"].sum(skipna=True)),
        "weighted_spread_bp": _weighted_average(df, "spread_bp"),
        "positions": df,
    }
    dimensions = {}
    for dim in ["issuer", "sector", "rating", "currency"]:
        grouped = df.groupby(dim, dropna=False)["market_value"].sum().sort_values(ascending=False)
        table = grouped.rename("market_value").reset_index()
        table["weight"] = table["market_value"] / total_mv if total_mv else np.nan
        dimensions[dim] = table
    summary["breakdowns"] = dimensions
    if total_mv:
        weights = df["market_value"] / total_mv
        summary["issuer_hhi"] = float(
            df.assign(_w=weights).groupby("issuer")["_w"].sum().pow(2).sum()
        )
    else:
        summary["issuer_hhi"] = np.nan
    return summary


def curve_twist_shock_bp(maturity_years: float, scenario: ScenarioShock) -> float:
    t = max(0.0, float(maturity_years))
    # Smooth interpolation between short and long anchors; parallel is common component.
    long_weight = clamp((t - 2.0) / 28.0, 0.0, 1.0)
    short_weight = 1.0 - long_weight
    return float(scenario.parallel_rate_bp + scenario.short_rate_bp * short_weight + scenario.long_rate_bp * long_weight)


def scenario_pnl(frame: pd.DataFrame, scenario: ScenarioShock) -> dict[str, Any]:
    df = normalize_portfolio(frame)
    if df.empty:
        return {"available": False, "scenario": asdict(scenario), "positions": pd.DataFrame()}
    rows = []
    for _, row in df.iterrows():
        mv = safe_float(row["market_value"], 0.0) or 0.0
        duration = safe_float(row["duration"], 0.0) or 0.0
        spread_duration = safe_float(row["spread_duration"], 0.0) or 0.0
        convexity = safe_float(row["convexity"], 0.0) or 0.0
        maturity = safe_float(row["maturity_years"], 10.0) or 10.0
        fx_beta = safe_float(row["fx_beta"], 0.0) or 0.0
        rate_bp = curve_twist_shock_bp(maturity, scenario)
        dy = rate_bp / 10000.0
        ds = scenario.spread_bp / 10000.0
        rate_pnl = mv * (-duration * dy + 0.5 * convexity * dy * dy)
        spread_pnl = mv * (-spread_duration * ds)
        fx_pnl = mv * fx_beta * scenario.fx_pct / 100.0
        liquidity_pnl = -abs(mv) * scenario.liquidity_haircut_pct / 100.0
        total = rate_pnl + spread_pnl + fx_pnl + liquidity_pnl
        rows.append(
            {
                "identifier": row["identifier"],
                "issuer": row["issuer"],
                "market_value": mv,
                "rate_shock_bp": rate_bp,
                "spread_shock_bp": scenario.spread_bp,
                "rate_pnl": rate_pnl,
                "spread_pnl": spread_pnl,
                "fx_pnl": fx_pnl,
                "liquidity_pnl": liquidity_pnl,
                "total_pnl": total,
                "return_pct": total / abs(mv) if mv else np.nan,
            }
        )
    positions = pd.DataFrame(rows)
    totals = positions[["rate_pnl", "spread_pnl", "fx_pnl", "liquidity_pnl", "total_pnl"]].sum().to_dict()
    return {"available": True, "scenario": asdict(scenario), "positions": positions, "totals": totals}


def run_scenario_matrix(frame: pd.DataFrame, scenarios: Sequence[ScenarioShock] = DEFAULT_SCENARIOS) -> pd.DataFrame:
    rows = []
    for scenario in scenarios:
        result = scenario_pnl(frame, scenario)
        if result.get("available"):
            totals = result["totals"]
            rows.append({"scenario": scenario.name, **totals})
    return pd.DataFrame(rows)


def historical_var_es(pnl_series: pd.Series, confidence: float = 0.95) -> dict[str, float]:
    pnl = pd.to_numeric(pnl_series, errors="coerce").dropna()
    if pnl.empty:
        return {"var": np.nan, "expected_shortfall": np.nan, "confidence": confidence}
    loss = -pnl
    var = float(loss.quantile(confidence))
    tail = loss[loss >= var]
    es = float(tail.mean()) if not tail.empty else var
    return {"var": max(0.0, var), "expected_shortfall": max(0.0, es), "confidence": confidence}


def parametric_var_es(
    portfolio_value: float,
    annual_volatility: float,
    confidence: float = 0.95,
    horizon_days: int = 1,
) -> dict[str, float]:
    z = _normal_ppf(confidence)
    sigma_h = float(annual_volatility) * sqrt(max(horizon_days, 1) / 252.0)
    var = abs(float(portfolio_value)) * z * sigma_h
    es_multiplier = _normal_pdf(z) / (1.0 - confidence)
    es = abs(float(portfolio_value)) * sigma_h * es_multiplier
    return {"var": var, "expected_shortfall": es, "confidence": confidence, "horizon_days": horizon_days}


def factor_pnl_history(
    frame: pd.DataFrame,
    rate_changes_bp: pd.Series,
    spread_changes_bp: pd.Series | None = None,
    fx_returns: pd.Series | None = None,
) -> pd.Series:
    summary = portfolio_summary(frame)
    if not summary.get("available"):
        return pd.Series(dtype=float)
    rate = pd.to_numeric(rate_changes_bp, errors="coerce")
    spread = pd.to_numeric(spread_changes_bp, errors="coerce") if spread_changes_bp is not None else pd.Series(0.0, index=rate.index)
    fx = pd.to_numeric(fx_returns, errors="coerce") if fx_returns is not None else pd.Series(0.0, index=rate.index)
    aligned = pd.concat([rate.rename("rate"), spread.rename("spread"), fx.rename("fx")], axis=1).fillna(0.0)
    dv01 = summary["dv01"]
    cs01 = summary["cs01"]
    fx_exposure = float(normalize_portfolio(frame).eval("market_value * fx_beta").sum(skipna=True))
    return -dv01 * aligned["rate"] - cs01 * aligned["spread"] + fx_exposure * aligned["fx"]


def hedge_notional_least_squares(
    target_exposures: Sequence[float],
    hedge_matrix: Sequence[Sequence[float]],
    hedge_names: Sequence[str] | None = None,
) -> pd.DataFrame:
    target = np.asarray(target_exposures, dtype=float)
    matrix = np.asarray(hedge_matrix, dtype=float)
    if matrix.ndim != 2:
        raise ValueError("hedge_matrix must be two-dimensional")
    if target.ndim != 1 or matrix.shape[0] != target.size:
        raise ValueError("target_exposures must match the row count of hedge_matrix")
    if not np.isfinite(target).all() or not np.isfinite(matrix).all():
        raise ValueError("target_exposures and hedge_matrix must contain finite values")
    if matrix.shape[1] == 0:
        raise ValueError("hedge_matrix must contain at least one hedge instrument")
    names = list(hedge_names or [f"Hedge {i+1}" for i in range(matrix.shape[1])])
    if len(names) != matrix.shape[1]:
        raise ValueError("hedge_names must match the column count of hedge_matrix")
    notionals = np.linalg.lstsq(matrix, -target, rcond=None)[0]
    residual = target + matrix @ notionals
    out = pd.DataFrame({"hedge": names, "notional": notionals})
    out.attrs["residual_exposure"] = residual
    out.attrs["residual_norm"] = float(np.linalg.norm(residual))
    out.attrs["matrix_rank"] = int(np.linalg.matrix_rank(matrix))
    out.attrs["condition_number"] = float(np.linalg.cond(matrix))
    return out


# -----------------------------------------------------------------------------
# Strategy validation helpers
# -----------------------------------------------------------------------------

def backtest_zscore_strategy(
    spread: pd.Series,
    entry_z: float = 1.5,
    exit_z: float = 0.25,
    stop_z: float = 3.0,
    window: int = 252,
    cost_bp: float = 1.0,
) -> dict[str, Any]:
    s = pd.to_numeric(spread, errors="coerce").dropna()
    if len(s) < max(window // 2, 30):
        return {"available": False, "reason": "Insufficient history"}
    z = rolling_zscore(s, window=window)
    position = pd.Series(0.0, index=s.index)
    current = 0.0
    for i in range(len(s)):
        zi = z.iloc[i]
        if not np.isfinite(zi):
            position.iloc[i] = current
            continue
        if current == 0:
            if zi >= entry_z:
                current = -1.0
            elif zi <= -entry_z:
                current = 1.0
        elif current > 0:
            if zi >= -exit_z or zi <= -stop_z:
                current = 0.0
        else:
            if zi <= exit_z or zi >= stop_z:
                current = 0.0
        position.iloc[i] = current
    changes = position.diff().abs().fillna(position.abs())
    # The input spread and resulting P&L are expressed in basis points.  Trading
    # costs must therefore remain in bp as well (the previous /10,000 conversion
    # understated costs by four orders of magnitude).
    pnl = position.shift(1).fillna(0.0) * (-s.diff().fillna(0.0)) - changes * cost_bp
    equity = pnl.cumsum()
    ann_mean = pnl.mean() * 252
    ann_vol = pnl.std(ddof=1) * sqrt(252)
    sharpe = ann_mean / ann_vol if ann_vol > 0 else np.nan
    drawdown = equity - equity.cummax()
    return {
        "available": True,
        "frame": pd.DataFrame({"spread": s, "z_score": z, "position": position, "pnl": pnl, "equity": equity}),
        "metrics": {
            "annualized_pnl": float(ann_mean),
            "annualized_vol": float(ann_vol),
            "annualized_pnl_bp": float(ann_mean),
            "annualized_vol_bp": float(ann_vol),
            "sharpe": float(sharpe),
            "max_drawdown": float(drawdown.min()),
            "turnover": float(changes.sum()),
            "hit_rate": float((pnl > 0).mean()),
            "half_life": mean_reversion_half_life(s),
        },
    }


def performance_metrics(returns: pd.Series, periods_per_year: int = 252) -> dict[str, float]:
    r = pd.to_numeric(returns, errors="coerce").dropna()
    if r.empty:
        return {}
    equity = (1 + r).cumprod()
    dd = equity / equity.cummax() - 1
    ann_return = float((equity.iloc[-1] ** (periods_per_year / len(r)) - 1)) if equity.iloc[-1] > 0 else np.nan
    ann_vol = float(r.std(ddof=1) * sqrt(periods_per_year))
    downside = r[r < 0].std(ddof=1) * sqrt(periods_per_year)
    return {
        "annualized_return": ann_return,
        "annualized_volatility": ann_vol,
        "sharpe": ann_return / ann_vol if ann_vol > 0 else np.nan,
        "sortino": ann_return / downside if downside and downside > 0 else np.nan,
        "max_drawdown": float(dd.min()),
        "calmar": ann_return / abs(dd.min()) if dd.min() < 0 else np.nan,
        "skew": float(r.skew()),
        "kurtosis": float(r.kurtosis()),
        "hit_rate": float((r > 0).mean()),
    }


# -----------------------------------------------------------------------------
# Institutional credit curve, migration, IRRBB, liquidity and decision engines
# -----------------------------------------------------------------------------

def _linear_discount_factor(t: float, discount_curve: Any = 0.04) -> float:
    """Continuously compounded discount factor from a flat rate or tenor/rate curve."""
    maturity = max(float(t), 0.0)
    if np.isscalar(discount_curve):
        rate = float(discount_curve)
    else:
        curve = pd.DataFrame(discount_curve).copy()
        if curve.shape[1] < 2:
            raise ValueError("discount_curve must contain tenor and zero-rate columns")
        tenors = pd.to_numeric(curve.iloc[:, 0], errors="coerce").to_numpy(dtype=float)
        rates = pd.to_numeric(curve.iloc[:, 1], errors="coerce").to_numpy(dtype=float)
        valid = np.isfinite(tenors) & np.isfinite(rates)
        if not valid.any():
            raise ValueError("discount_curve contains no valid observations")
        order = np.argsort(tenors[valid])
        tenors, rates = tenors[valid][order], rates[valid][order]
        rate = float(np.interp(maturity, tenors, rates, left=rates[0], right=rates[-1]))
    return float(np.exp(-rate * maturity))


def piecewise_survival_probability(
    t: float,
    hazard_tenors: Sequence[float],
    hazard_rates: Sequence[float],
) -> float:
    """Survival probability under non-negative piecewise-constant hazards."""
    horizon = max(float(t), 0.0)
    tenors = np.asarray(hazard_tenors, dtype=float)
    hazards = np.asarray(hazard_rates, dtype=float)
    if tenors.ndim != 1 or hazards.ndim != 1 or len(tenors) != len(hazards) or len(tenors) == 0:
        raise ValueError("hazard_tenors and hazard_rates must be equal-length one-dimensional arrays")
    if not np.all(np.diff(tenors) > 0) or (tenors <= 0).any() or (hazards < 0).any():
        raise ValueError("hazard tenors must increase and hazard rates must be non-negative")
    elapsed, cumulative = 0.0, 0.0
    for endpoint, hazard in zip(tenors, hazards):
        width = min(horizon, endpoint) - elapsed
        if width > 0:
            cumulative += float(hazard) * width
            elapsed += width
        if elapsed >= horizon:
            break
    if elapsed < horizon:
        cumulative += float(hazards[-1]) * (horizon - elapsed)
    return float(np.exp(-cumulative))


def cds_leg_pv(
    maturity: float,
    hazard_tenors: Sequence[float],
    hazard_rates: Sequence[float],
    recovery_rate: float = 0.40,
    discount_curve: Any = 0.04,
    payments_per_year: int = 4,
) -> dict[str, float]:
    """Unit-spread premium and protection legs with midpoint accrual-on-default."""
    maturity = float(maturity)
    recovery = float(recovery_rate)
    if maturity <= 0 or payments_per_year <= 0 or not 0 <= recovery < 1:
        raise ValueError("maturity, frequency or recovery rate is invalid")
    dt = 1.0 / payments_per_year
    grid = np.arange(dt, maturity + dt * 0.5, dt)
    if grid.size == 0 or grid[-1] < maturity - 1e-10:
        grid = np.append(grid, maturity)
    grid[-1] = maturity
    previous_t, previous_survival = 0.0, 1.0
    premium_pv, protection_pv = 0.0, 0.0
    for payment_t in grid:
        period = float(payment_t - previous_t)
        survival = piecewise_survival_probability(payment_t, hazard_tenors, hazard_rates)
        default_probability = max(previous_survival - survival, 0.0)
        discount = _linear_discount_factor(payment_t, discount_curve)
        premium_pv += discount * period * (survival + 0.5 * default_probability)
        protection_pv += discount * (1.0 - recovery) * default_probability
        previous_t, previous_survival = float(payment_t), survival
    return {
        "rpv01": float(premium_pv),
        "protection_leg": float(protection_pv),
        "survival_probability": float(previous_survival),
        "default_probability": float(1.0 - previous_survival),
    }


def cds_par_spread_bp(
    maturity: float,
    hazard_tenors: Sequence[float],
    hazard_rates: Sequence[float],
    recovery_rate: float = 0.40,
    discount_curve: Any = 0.04,
    payments_per_year: int = 4,
) -> float:
    legs = cds_leg_pv(maturity, hazard_tenors, hazard_rates, recovery_rate, discount_curve, payments_per_year)
    return float(10000.0 * legs["protection_leg"] / legs["rpv01"]) if legs["rpv01"] > 0 else np.nan


def _bounded_bisection(function: Callable[[float], float], low: float, high: float, tolerance: float = 1e-10) -> float:
    f_low, f_high = function(low), function(high)
    if not np.isfinite(f_low) or not np.isfinite(f_high) or f_low * f_high > 0:
        return float(low if abs(f_low) <= abs(f_high) else high)
    for _ in range(100):
        mid = 0.5 * (low + high)
        f_mid = function(mid)
        if abs(f_mid) <= tolerance or high - low <= tolerance:
            return float(mid)
        if f_low * f_mid <= 0:
            high, f_high = mid, f_mid
        else:
            low, f_low = mid, f_mid
    return float(0.5 * (low + high))


def calibrate_cds_hazard_curve(
    tenors: Sequence[float],
    par_spreads_bp: Sequence[float],
    recovery_rate: float = 0.40,
    discount_curve: Any = 0.04,
    payments_per_year: int = 4,
) -> pd.DataFrame:
    """Bootstrap a piecewise-constant hazard curve from par CDS quotes."""
    quotes = pd.DataFrame({"tenor_years": tenors, "market_spread_bp": par_spreads_bp})
    quotes = quotes.apply(pd.to_numeric, errors="coerce").dropna().sort_values("tenor_years")
    if quotes.empty or (quotes <= 0).any().any() or quotes["tenor_years"].duplicated().any():
        raise ValueError("CDS tenors and spreads must be positive, finite and unique")
    calibrated_tenors: list[float] = []
    calibrated_hazards: list[float] = []
    rows: list[dict[str, float]] = []
    for tenor, quote in quotes.itertuples(index=False, name=None):
        trial_tenors = calibrated_tenors + [float(tenor)]
        objective = lambda hazard: cds_par_spread_bp(
            tenor,
            trial_tenors,
            calibrated_hazards + [hazard],
            recovery_rate,
            discount_curve,
            payments_per_year,
        ) - float(quote)
        hazard = _bounded_bisection(objective, 1e-10, 20.0)
        calibrated_tenors.append(float(tenor))
        calibrated_hazards.append(float(hazard))
        legs = cds_leg_pv(tenor, calibrated_tenors, calibrated_hazards, recovery_rate, discount_curve, payments_per_year)
        model_spread = cds_par_spread_bp(tenor, calibrated_tenors, calibrated_hazards, recovery_rate, discount_curve, payments_per_year)
        rows.append(
            {
                "tenor_years": float(tenor),
                "market_spread_bp": float(quote),
                "hazard_rate_pct": 100.0 * hazard,
                "survival_probability_pct": 100.0 * legs["survival_probability"],
                "cumulative_default_probability_pct": 100.0 * legs["default_probability"],
                "risky_pv01_years": legs["rpv01"],
                "model_spread_bp": model_spread,
                "calibration_residual_bp": model_spread - float(quote),
            }
        )
    result = pd.DataFrame(rows)
    result.attrs["hazard_tenors"] = calibrated_tenors
    result.attrs["hazard_rates"] = calibrated_hazards
    result.attrs["recovery_rate"] = float(recovery_rate)
    result.attrs["methodology"] = "Piecewise-constant hazard bootstrap; quarterly premium; midpoint accrual-on-default."
    return result


def cds_forward_default_table(calibration: pd.DataFrame) -> pd.DataFrame:
    if calibration.empty:
        return pd.DataFrame()
    out = calibration[["tenor_years", "survival_probability_pct"]].copy()
    survival = out["survival_probability_pct"] / 100.0
    out["marginal_default_probability_pct"] = 100.0 * (survival.shift(fill_value=1.0) - survival).clip(lower=0.0)
    previous_t = out["tenor_years"].shift(fill_value=0.0)
    previous_survival = survival.shift(fill_value=1.0)
    interval = (out["tenor_years"] - previous_t).clip(lower=1e-8)
    out["forward_hazard_pct"] = -100.0 * np.log((survival / previous_survival).clip(lower=1e-12)) / interval
    return out


def bond_cds_basis(
    bond_spread_bp: float,
    cds_spread_bp: float,
    bid_ask_bp: float = 0.0,
    funding_basis_bp: float = 0.0,
) -> dict[str, float]:
    raw = float(bond_spread_bp) - float(cds_spread_bp)
    liquidity_charge = max(float(bid_ask_bp), 0.0) / 2.0
    adjusted = raw - liquidity_charge - float(funding_basis_bp)
    return {
        "raw_basis_bp": raw,
        "liquidity_charge_bp": liquidity_charge,
        "funding_basis_bp": float(funding_basis_bp),
        "liquidity_funding_adjusted_basis_bp": adjusted,
    }


RATING_STATES = ["AAA", "AA", "A", "BBB", "BB", "B", "CCC", "D"]
ILLUSTRATIVE_TRANSITION_MATRIX = pd.DataFrame(
    [
        [90.81, 8.33, 0.68, 0.06, 0.12, 0.00, 0.00, 0.00],
        [0.70, 90.65, 7.79, 0.64, 0.06, 0.14, 0.02, 0.00],
        [0.09, 2.27, 91.05, 5.52, 0.74, 0.26, 0.01, 0.06],
        [0.02, 0.33, 5.95, 86.93, 5.30, 1.17, 0.12, 0.18],
        [0.03, 0.14, 0.67, 7.73, 80.53, 8.84, 1.00, 1.06],
        [0.00, 0.11, 0.24, 0.43, 6.48, 83.46, 4.07, 5.21],
        [0.19, 0.00, 0.29, 0.58, 1.55, 12.78, 64.86, 19.75],
        [0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 100.00],
    ],
    index=RATING_STATES,
    columns=RATING_STATES,
)
RATING_SPREAD_LEVELS_BP = {"AAA": 45.0, "AA": 65.0, "A": 95.0, "BBB": 155.0, "BB": 320.0, "B": 560.0, "CCC": 1100.0}


def validate_transition_matrix(matrix: pd.DataFrame | Sequence[Sequence[float]]) -> pd.DataFrame:
    frame = pd.DataFrame(matrix, index=RATING_STATES, columns=RATING_STATES, dtype=float)
    if frame.shape != (len(RATING_STATES), len(RATING_STATES)) or not np.isfinite(frame.to_numpy()).all():
        raise ValueError("transition matrix must be a finite 8x8 matrix")
    if (frame < 0).any().any():
        raise ValueError("transition probabilities cannot be negative")
    row_sums = frame.sum(axis=1)
    if (row_sums <= 0).any():
        raise ValueError("each transition-matrix row must have positive mass")
    frame = frame.div(row_sums, axis=0)
    frame.loc["D"] = [0.0] * 7 + [1.0]
    return frame


def transition_matrix_horizon(matrix: pd.DataFrame | Sequence[Sequence[float]], years: int = 1) -> pd.DataFrame:
    if int(years) < 1:
        raise ValueError("years must be at least one")
    one_year = validate_transition_matrix(matrix)
    powered = np.linalg.matrix_power(one_year.to_numpy(), int(years))
    return pd.DataFrame(powered, index=RATING_STATES, columns=RATING_STATES)


def migration_distribution(
    initial_rating: str,
    matrix: pd.DataFrame | Sequence[Sequence[float]] = ILLUSTRATIVE_TRANSITION_MATRIX,
    years: int = 1,
) -> pd.Series:
    rating = str(initial_rating).upper().strip()
    if rating not in RATING_STATES:
        raise ValueError(f"unsupported rating: {rating}")
    return transition_matrix_horizon(matrix, years).loc[rating].rename("probability")


def credit_migration_var(
    portfolio: pd.DataFrame,
    matrix: pd.DataFrame | Sequence[Sequence[float]] = ILLUSTRATIVE_TRANSITION_MATRIX,
    simulations: int = 10000,
    confidence: float = 0.99,
    asset_correlation: float = 0.20,
    seed: int = 42,
) -> dict[str, Any]:
    """One-factor Gaussian credit migration VaR using mark-to-spread and LGD losses."""
    df = normalize_portfolio(portfolio)
    df = df[df["rating"].isin(RATING_STATES[:-1]) & df["market_value"].notna()].reset_index(drop=True)
    if df.empty:
        return {"available": False, "reason": "No positions with supported ratings"}
    n_sims = int(simulations)
    if n_sims < 500 or not 0.0 < confidence < 1.0 or not 0.0 <= asset_correlation < 1.0:
        raise ValueError("invalid simulations, confidence or asset correlation")
    transition = validate_transition_matrix(matrix)
    rng = np.random.default_rng(int(seed))
    systematic = rng.standard_normal((n_sims, 1))
    idiosyncratic = rng.standard_normal((n_sims, len(df)))
    latent = sqrt(asset_correlation) * systematic + sqrt(1.0 - asset_correlation) * idiosyncratic
    uniforms = np.vectorize(_normal_cdf, otypes=[float])(-latent)
    portfolio_pnl = np.zeros(n_sims, dtype=float)
    expected_default_loss = 0.0
    transition_rows: list[dict[str, Any]] = []
    for column, row in df.iterrows():
        rating = row["rating"]
        probabilities = transition.loc[rating].to_numpy(dtype=float)
        state_index = np.searchsorted(np.cumsum(probabilities), uniforms[:, column], side="right").clip(0, len(RATING_STATES) - 1)
        mv = float(row["market_value"])
        spread_duration = safe_float(row["spread_duration"], safe_float(row["duration"], 0.0)) or 0.0
        current_spread = safe_float(row["spread_bp"], RATING_SPREAD_LEVELS_BP.get(rating, 0.0)) or 0.0
        recovery = safe_float(row["recovery_rate"], 0.40) or 0.40
        state_pnl = np.zeros(n_sims, dtype=float)
        for target_index, target_rating in enumerate(RATING_STATES):
            mask = state_index == target_index
            if target_rating == "D":
                state_pnl[mask] = -abs(mv) * (1.0 - recovery)
            else:
                target_spread = RATING_SPREAD_LEVELS_BP[target_rating]
                state_pnl[mask] = -mv * spread_duration * (target_spread - current_spread) / 10000.0
        portfolio_pnl += state_pnl
        default_probability = float(probabilities[-1])
        expected_default_loss += abs(mv) * (1.0 - recovery) * default_probability
        transition_rows.append(
            {
                "identifier": row["identifier"],
                "rating": rating,
                "market_value": mv,
                "one_year_default_probability_pct": 100.0 * default_probability,
                "expected_default_loss": abs(mv) * (1.0 - recovery) * default_probability,
            }
        )
    loss = -portfolio_pnl
    var = float(np.quantile(loss, confidence))
    tail = loss[loss >= var]
    es = float(tail.mean()) if tail.size else var
    return {
        "available": True,
        "credit_var": max(var, 0.0),
        "expected_shortfall": max(es, 0.0),
        "expected_pnl": float(portfolio_pnl.mean()),
        "expected_default_loss": float(expected_default_loss),
        "unexpected_loss": max(var - expected_default_loss, 0.0),
        "confidence": float(confidence),
        "asset_correlation": float(asset_correlation),
        "simulations": n_sims,
        "loss_distribution": pd.Series(loss, name="credit_loss"),
        "position_expected_loss": pd.DataFrame(transition_rows),
    }


BASEL_IRRBB_SHOCKS_BP: dict[str, dict[str, float]] = {
    "USD": {"parallel": 200.0, "short": 300.0, "long": 225.0},
    "EUR": {"parallel": 200.0, "short": 250.0, "long": 100.0},
    "GBP": {"parallel": 250.0, "short": 300.0, "long": 150.0},
    "JPY": {"parallel": 100.0, "short": 100.0, "long": 100.0},
    "CHF": {"parallel": 100.0, "short": 150.0, "long": 100.0},
    "CAD": {"parallel": 200.0, "short": 300.0, "long": 150.0},
    "AUD": {"parallel": 300.0, "short": 450.0, "long": 300.0},
}
BASEL_IRRBB_SCENARIOS = ["Parallel up", "Parallel down", "Steepener", "Flattener", "Short up", "Short down"]


def basel_irrbb_shock_bp(maturity_years: float, scenario: str, currency: str = "USD") -> float:
    parameters = BASEL_IRRBB_SHOCKS_BP.get(str(currency).upper(), BASEL_IRRBB_SHOCKS_BP["USD"])
    t = max(float(maturity_years), 0.0)
    short_component = parameters["short"] * np.exp(-t / 4.0)
    long_component = parameters["long"] * (1.0 - np.exp(-t / 4.0))
    name = str(scenario).strip().lower()
    if name == "parallel up":
        return parameters["parallel"]
    if name == "parallel down":
        return -parameters["parallel"]
    if name == "steepener":
        return float(-0.65 * short_component + 0.90 * long_component)
    if name == "flattener":
        return float(0.80 * short_component - 0.60 * long_component)
    if name == "short up":
        return float(short_component)
    if name == "short down":
        return float(-short_component)
    raise ValueError(f"unsupported IRRBB scenario: {scenario}")


def irrbb_eve_scenarios(portfolio: pd.DataFrame, tier1_capital: float | None = None) -> dict[str, Any]:
    df = normalize_portfolio(portfolio)
    df = df[df["market_value"].notna()].copy()
    if df.empty:
        return {"available": False, "reason": "No portfolio positions"}
    scenario_rows, position_rows = [], []
    for scenario in BASEL_IRRBB_SCENARIOS:
        total = 0.0
        for _, row in df.iterrows():
            maturity = safe_float(row["maturity_years"], 10.0) or 10.0
            shock_bp = basel_irrbb_shock_bp(maturity, scenario, row["currency"] or "USD")
            dy = shock_bp / 10000.0
            mv = float(row["market_value"])
            duration = safe_float(row["duration"], 0.0) or 0.0
            convexity = safe_float(row["convexity"], 0.0) or 0.0
            delta_eve = mv * (-duration * dy + 0.5 * convexity * dy * dy)
            total += delta_eve
            position_rows.append({"scenario": scenario, "identifier": row["identifier"], "currency": row["currency"], "shock_bp": shock_bp, "delta_eve": delta_eve})
        row_result: dict[str, Any] = {"scenario": scenario, "delta_eve": total}
        if tier1_capital and tier1_capital > 0:
            row_result["delta_eve_pct_tier1"] = 100.0 * total / float(tier1_capital)
        scenario_rows.append(row_result)
    scenarios = pd.DataFrame(scenario_rows).sort_values("delta_eve")
    worst = scenarios.iloc[0]
    return {
        "available": True,
        "scenarios": scenarios.reset_index(drop=True),
        "positions": pd.DataFrame(position_rows),
        "worst_scenario": worst["scenario"],
        "worst_delta_eve": float(worst["delta_eve"]),
        "worst_loss_pct_tier1": -float(worst.get("delta_eve_pct_tier1", np.nan)),
        "scope_note": "EVE approximation only; NII requires contractual repricing, optionality and behavioral cash-flow data.",
    }


def normalize_trace_trades(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["timestamp", "identifier", "price", "quantity", "yield", "side", "venue"])
    trades = frame.copy()
    trades.columns = [str(column).strip().lower().replace(" ", "_") for column in trades.columns]
    aliases = {
        "date": "timestamp", "datetime": "timestamp", "time": "timestamp", "cusip": "identifier",
        "isin": "identifier", "size": "quantity", "volume": "quantity", "trade_price": "price",
        "ytm": "yield", "buy_sell": "side", "capacity": "venue",
    }
    trades = trades.rename(columns={source: target for source, target in aliases.items() if source in trades.columns and target not in trades.columns})
    for column in ["timestamp", "identifier", "price", "quantity", "yield", "side", "venue"]:
        if column not in trades:
            trades[column] = np.nan if column in {"price", "quantity", "yield"} else ""
    trades["timestamp"] = pd.to_datetime(trades["timestamp"], errors="coerce", utc=True)
    for column in ["price", "quantity", "yield"]:
        trades[column] = pd.to_numeric(trades[column], errors="coerce")
    trades = trades.dropna(subset=["timestamp", "price", "quantity"])
    trades = trades[(trades["price"] > 0) & (trades["quantity"] > 0)].sort_values("timestamp")
    trades["notional"] = trades["price"] / 100.0 * trades["quantity"]
    return trades.reset_index(drop=True)


def trace_liquidity_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    trades = normalize_trace_trades(frame)
    if trades.empty:
        return {"available": False, "reason": "No valid trade rows", "trades": trades}
    total_volume = float(trades["quantity"].sum())
    vwap = float(np.average(trades["price"], weights=trades["quantity"]))
    daily = trades.set_index("timestamp").resample("1D").agg(price=("price", "last"), volume=("quantity", "sum"), notional=("notional", "sum"), trades=("price", "size"))
    active = daily[daily["trades"] > 0]
    business_days = max(len(pd.bdate_range(trades["timestamp"].min().date(), trades["timestamp"].max().date())), 1)
    zero_ratio = max(0.0, 1.0 - len(active) / business_days)
    returns = active["price"].pct_change()
    amihud = (returns.abs() / active["notional"].replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).mean() * 1_000_000
    price_changes = trades["price"].diff().dropna()
    roll_spread_bp = np.nan
    if len(price_changes) >= 3:
        covariance = float(np.cov(price_changes.iloc[1:], price_changes.iloc[:-1], ddof=1)[0, 1])
        if covariance < 0:
            roll_spread_bp = 2.0 * sqrt(-covariance) / trades["price"].mean() * 10000.0
    side_concentration = np.nan
    valid_sides = trades["side"].replace("", np.nan).dropna()
    if not valid_sides.empty:
        side_concentration = float(valid_sides.value_counts(normalize=True).max())
    return {
        "available": True,
        "trades": trades,
        "daily": daily.reset_index(),
        "trade_count": int(len(trades)),
        "total_volume": total_volume,
        "total_notional": float(trades["notional"].sum()),
        "vwap": vwap,
        "active_days": int(len(active)),
        "zero_trading_day_ratio": float(zero_ratio),
        "amihud_per_usd_mm": float(amihud) if np.isfinite(amihud) else np.nan,
        "roll_spread_bp": float(roll_spread_bp) if np.isfinite(roll_spread_bp) else np.nan,
        "price_dispersion_bp": float(trades["price"].std(ddof=1) / vwap * 10000.0) if len(trades) > 1 else 0.0,
        "yield_dispersion_bp": float(trades["yield"].std(ddof=1) * 10000.0) if trades["yield"].notna().sum() > 1 else np.nan,
        "largest_side_concentration": side_concentration,
        "days_since_last_trade": int((pd.Timestamp.now(tz="UTC").normalize() - trades["timestamp"].max().normalize()).days),
    }


def liquidation_cost_curve(
    position_value: float,
    daily_volume: float,
    bid_ask_bp: float,
    spread_volatility_bp: float,
    horizons_days: Sequence[int] = (1, 2, 3, 5, 10, 20),
    max_participation: float = 0.20,
    impact_multiplier: float = 0.50,
) -> pd.DataFrame:
    position, adv = abs(float(position_value)), max(float(daily_volume), 1e-12)
    if not 0 < max_participation <= 1 or min(horizons_days) < 1:
        raise ValueError("participation and horizons are invalid")
    rows = []
    minimum_days = position / (adv * max_participation)
    for horizon in horizons_days:
        participation = position / (adv * float(horizon))
        feasible = participation <= max_participation
        impact_bp = max(float(spread_volatility_bp), 0.0) * float(impact_multiplier) * sqrt(max(participation, 0.0))
        cost_bp = max(float(bid_ask_bp), 0.0) / 2.0 + impact_bp
        rows.append({
            "horizon_days": int(horizon), "required_participation_pct": 100.0 * participation,
            "feasible": feasible, "half_spread_bp": max(float(bid_ask_bp), 0.0) / 2.0,
            "market_impact_bp": impact_bp, "total_cost_bp": cost_bp,
            "estimated_cost": position * cost_bp / 10000.0, "minimum_exit_days": minimum_days,
        })
    return pd.DataFrame(rows)


def investment_committee_score(
    valuation_z: float,
    carry_roll_bp: float,
    credit_score: float,
    liquidity_score: float,
    stress_loss_pct: float,
    data_confidence_pct: float,
    hard_stops: Mapping[str, bool] | None = None,
) -> dict[str, Any]:
    components = {
        "valuation": 100.0 / (1.0 + np.exp(float(valuation_z))),
        "carry_roll": clamp(50.0 + 2.0 * float(carry_roll_bp), 0.0, 100.0),
        "credit": clamp(float(credit_score), 0.0, 100.0),
        "liquidity": clamp(float(liquidity_score), 0.0, 100.0),
        "stress": clamp(100.0 - 5.0 * max(float(stress_loss_pct), 0.0), 0.0, 100.0),
        "data": clamp(float(data_confidence_pct), 0.0, 100.0),
    }
    weights = {"valuation": 0.20, "carry_roll": 0.15, "credit": 0.25, "liquidity": 0.15, "stress": 0.15, "data": 0.10}
    score = float(sum(components[key] * weights[key] for key in components))
    stops = {str(key): bool(value) for key, value in (hard_stops or {}).items()}
    breached = [name for name, flag in stops.items() if flag]
    if breached:
        decision, max_position_pct = "REJECT / ESCALATE", 0.0
    elif score >= 75:
        decision, max_position_pct = "APPROVE", min(5.0, 1.0 + (score - 75.0) / 10.0)
    elif score >= 60:
        decision, max_position_pct = "WATCHLIST / SMALL RISK", min(1.5, 0.25 + (score - 60.0) / 20.0)
    else:
        decision, max_position_pct = "REJECT / REWORK", 0.0
    table = pd.DataFrame([{"dimension": key, "score": value, "weight": weights[key], "contribution": value * weights[key]} for key, value in components.items()])
    return {"score": score, "decision": decision, "max_position_pct_nav": max_position_pct, "components": table, "hard_stop_breaches": breached}


def investment_committee_memo(
    issuer: str,
    security: str,
    score_result: Mapping[str, Any],
    thesis: str,
    catalysts: str,
    risks: str,
    mitigants: str,
) -> str:
    breaches = ", ".join(score_result.get("hard_stop_breaches", [])) or "None"
    return f"""# Fixed Income Investment Committee Memo

**Issuer / Security:** {issuer} / {security}  
**Decision:** {score_result.get('decision', 'N/A')}  
**Transparent score:** {safe_float(score_result.get('score'), np.nan):.1f}/100  
**Maximum position:** {safe_float(score_result.get('max_position_pct_nav'), 0.0):.2f}% of NAV  
**Hard-stop breaches:** {breaches}

## Thesis
{thesis or 'Not provided.'}

## Catalysts
{catalysts or 'Not provided.'}

## Principal risks
{risks or 'Not provided.'}

## Mitigants and hedge plan
{mitigants or 'Not provided.'}

## Governance note
This memo is an analytical decision aid. Validate market-data lineage, legal terms, liquidity, limits, compliance and executable levels before risk is authorized.
"""

# ============================================================================
# STREAMLIT WORKSTATION UI
# ============================================================================

MODULE_VERSION = "1.0.0"
MODULE_NAME = "Fixed Income & Credit Analytics"

DESK_PAGES: dict[str, list[str]] = {
    "OVERVIEW": ["Command Center", "Data Monitor"],
    "RATES": [
        "Sovereign Curves",
        "Curve Construction",
        "Relative Value",
        "Inflation & Real Rates",
        "Futures & Volatility",
        "Auctions & Supply",
    ],
    "CREDIT": ["Credit Markets", "Issuer Credit", "Bond Analytics", "Liquidity & TRACE"],
    "PORTFOLIO": ["Portfolio Analytics", "Risk & Attribution", "Stress & Scenario Lab"],
    "RESEARCH": ["Strategy Lab", "Econometric Diagnostics", "Data Quality & Methodology"],
}


# -----------------------------------------------------------------------------
# Cached data adapters
# -----------------------------------------------------------------------------

@st.cache_data(ttl=1800, show_spinner=False)
def _cached_us_curve(start_date: str | None) -> DataResult:
    return load_us_nominal_curve_history(start_date)


@st.cache_data(ttl=1800, show_spinner=False)
def _cached_us_real(start_date: str | None) -> DataResult:
    return load_us_real_curve_history(start_date)


@st.cache_data(ttl=1800, show_spinner=False)
def _cached_inflation(start_date: str | None) -> DataResult:
    return load_inflation_history(start_date)


@st.cache_data(ttl=1800, show_spinner=False)
def _cached_credit(start_date: str | None) -> DataResult:
    # Schema v2: all public credit OAS fields are normalized to basis points.
    normalized_result = load_credit_spread_history(start_date)
    return normalized_result


@st.cache_data(ttl=1800, show_spinner=False)
def _cached_funding(start_date: str | None) -> DataResult:
    return load_funding_stress_history(start_date)


@st.cache_data(ttl=1800, show_spinner=False)
def _cached_ecb(start_date: str | None) -> DataResult:
    return load_ecb_aaa_curve_history(start_date)


@st.cache_data(ttl=900, show_spinner=False)
def _cached_auctions(start_date: str, end_date: str) -> DataResult:
    return load_treasury_auctions(start_date=start_date, end_date=end_date, page_size=2000)


@st.cache_data(ttl=900, show_spinner=False)
def _cached_market_proxies(symbols: tuple[str, ...], period: str) -> DataResult:
    return load_market_proxy_history(symbols=symbols, period=period, interval="1d")


@st.cache_data(ttl=21600, show_spinner=False)
def _cached_sec_companyfacts(ticker: str) -> DataResult:
    return load_sec_companyfacts(ticker)


# -----------------------------------------------------------------------------
# UI helpers
# -----------------------------------------------------------------------------

def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or pd.isna(value):
            return default
        out = float(value)
        if not np.isfinite(out):
            return default
        return out
    except Exception:
        return default


def _fmt_num(value: Any, digits: int = 2) -> str:
    x = _safe_float(value)
    return "N/A" if x is None else f"{x:,.{digits}f}"


def _fmt_pct(value: Any, digits: int = 2) -> str:
    x = _safe_float(value)
    return "N/A" if x is None else f"{x:.{digits}%}"


def _fmt_bp(value: Any, digits: int = 1) -> str:
    x = _safe_float(value)
    return "N/A" if x is None else f"{x:+,.{digits}f} bp"


def _fmt_money(value: Any, currency: str = "USD") -> str:
    x = _safe_float(value)
    if x is None:
        return "N/A"
    symbol = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}.get(currency, f"{currency} ")
    ax = abs(x)
    if ax >= 1e9:
        return f"{symbol}{x / 1e9:,.2f}bn"
    if ax >= 1e6:
        return f"{symbol}{x / 1e6:,.2f}m"
    if ax >= 1e3:
        return f"{symbol}{x / 1e3:,.2f}k"
    return f"{symbol}{x:,.2f}"


def _inject_css() -> None:
    st.markdown(
        """
        <style>
        .fic-hero {
            border: 1px solid rgba(90,205,255,.24);
            border-radius: 22px;
            padding: 20px 24px;
            margin: 4px 0 14px 0;
            background:
                radial-gradient(circle at 10% 0%, rgba(85,232,255,.13), transparent 32%),
                radial-gradient(circle at 92% 0%, rgba(78,110,255,.12), transparent 34%),
                linear-gradient(180deg, rgba(5,16,34,.96), rgba(2,8,20,.96));
            box-shadow: 0 0 44px rgba(40,160,255,.08);
        }
        .fic-kicker {color:#55e8ff;font-size:.70rem;font-weight:950;letter-spacing:.22em;text-transform:uppercase;}
        .fic-title {color:#f8fbff;font-size:2rem;font-weight:950;line-height:1.05;margin-top:5px;}
        .fic-sub {color:rgba(220,235,250,.70);font-size:.90rem;line-height:1.42;margin-top:8px;max-width:1180px;}
        .fic-section {
            color:#55e8ff;font-size:.75rem;font-weight:950;letter-spacing:.18em;text-transform:uppercase;
            border-bottom:1px solid rgba(90,205,255,.13);padding:0 0 7px 0;margin:6px 0 12px 0;
        }
        .fic-note {
            border:1px solid rgba(90,205,255,.16);border-radius:14px;padding:10px 12px;
            background:rgba(5,18,36,.58);color:rgba(224,237,250,.74);font-size:.78rem;line-height:1.38;
        }
        .fic-live {color:#62ffbf;font-weight:900;}
        .fic-demo {color:#ffd56a;font-weight:900;}
        .fic-provider {color:#ff9a8b;font-weight:900;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _section(title: str) -> None:
    st.markdown(f"<div class='fic-section'>{title}</div>", unsafe_allow_html=True)


def _data_mode() -> str:
    mode = st.session_state.get("fic_data_mode", "Live public data")
    return str(mode)


def _result_or_demo(result: DataResult, kind: str) -> DataResult:
    if result.ok:
        return result
    if _data_mode() == "Explicit demo data":
        return demo_curve_history() if kind == "curve" else demo_credit_history()
    return result


def _show_result_status(result: DataResult, compact: bool = True) -> None:
    if result.warnings:
        for message in result.warnings[:3]:
            st.warning(message)
    if result.errors:
        message = " | ".join(result.errors[:3])
        if compact:
            st.caption(f"Data error: {message}")
        else:
            st.error(message)
    if result.provider_required:
        st.info("Provider or entitlement required for this dataset. No synthetic substitute is used.")


def _lineage_caption(result: DataResult) -> None:
    if not result.lineage:
        return
    ok_items = [x for x in result.lineage if x.status in {"OK", "DEMO"}]
    if not ok_items:
        return
    def _as_of_sort_key(item: DataLineage) -> int:
        if item.as_of is None:
            return -1
        try:
            return int(pd.Timestamp(item.as_of).value)
        except Exception:
            return -1

    latest = max(ok_items, key=_as_of_sort_key)
    as_of = pd.Timestamp(latest.as_of).strftime("%Y-%m-%d") if latest.as_of else "N/A"
    proxy = " · PROXY" if latest.is_proxy else ""
    st.caption(f"Source: {latest.provider} · As of {as_of} · {latest.unit}{proxy}")


def _download_csv_button(frame: pd.DataFrame, filename: str, key: str) -> None:
    if frame is None or frame.empty:
        return
    st.download_button(
        "Download CSV",
        frame.to_csv(index=False).encode("utf-8"),
        file_name=filename,
        mime="text/csv",
        key=key,
    )


def _curve_figure(curves: Mapping[str, pd.DataFrame], title: str) -> go.Figure:
    fig = go.Figure()
    for label, curve in curves.items():
        if curve is None or curve.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=curve["tenor_years"],
                y=curve["rate"],
                mode="lines+markers",
                name=label,
                hovertemplate="%{x:.2f}Y · %{y:.3f}%<extra>" + label + "</extra>",
            )
        )
    fig.update_layout(
        template="plotly_dark",
        height=455,
        margin=dict(l=10, r=10, t=48, b=10),
        title=title,
        xaxis_title="Maturity (years)",
        yaxis_title="Yield (%)",
        hovermode="x unified",
        legend=dict(orientation="h", y=1.03),
    )
    return fig


def _line_chart(frame: pd.DataFrame, columns: Sequence[str], title: str, y_title: str, height: int = 420) -> go.Figure:
    fig = go.Figure()
    if frame is not None and not frame.empty:
        for col in columns:
            if col not in frame.columns:
                continue
            fig.add_trace(go.Scatter(x=frame["date"], y=frame[col], mode="lines", name=col))
    fig.update_layout(
        template="plotly_dark",
        height=height,
        margin=dict(l=10, r=10, t=48, b=10),
        title=title,
        xaxis_title="Date",
        yaxis_title=y_title,
        hovermode="x unified",
        legend=dict(orientation="h", y=1.03),
    )
    return fig


def _latest_value(frame: pd.DataFrame, column: str) -> float | None:
    if frame is None or frame.empty or column not in frame.columns:
        return None
    s = pd.to_numeric(frame[column], errors="coerce").dropna()
    return float(s.iloc[-1]) if not s.empty else None


def _start_date_for_years(years: int) -> str:
    return (pd.Timestamp.today() - pd.DateOffset(years=years)).strftime("%Y-%m-%d")


def _empty_portfolio_template() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "identifier": "",
                "issuer": "",
                "sector": "",
                "rating": "",
                "currency": "USD",
                "quantity": 1.0,
                "market_value": 0.0,
                "clean_price": 100.0,
                "yield": 0.0,
                "duration": 0.0,
                "spread_duration": 0.0,
                "convexity": 0.0,
                "dv01": np.nan,
                "cs01": np.nan,
                "spread_bp": 0.0,
                "maturity_years": 5.0,
                "fx_beta": 0.0,
            }
        ]
    )


def _explicit_demo_portfolio() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"identifier": "DEMO-UST2", "issuer": "US Treasury", "sector": "Sovereign", "rating": "AA", "currency": "USD", "quantity": 1, "market_value": 2_000_000, "clean_price": 99.2, "yield": 0.043, "duration": 1.85, "spread_duration": 0.0, "convexity": 4.0, "dv01": np.nan, "cs01": 0.0, "spread_bp": 0, "maturity_years": 2, "fx_beta": 0, "pd_1y": 0.0002, "recovery_rate": 0.40, "spread_vol_bp": 18, "bid_ask_bp": 0.5, "daily_volume_mm": 5000, "issue_size_mm": 45000},
            {"identifier": "DEMO-IG5", "issuer": "Demo Industrial", "sector": "Industrials", "rating": "BBB", "currency": "USD", "quantity": 1, "market_value": 1_250_000, "clean_price": 96.8, "yield": 0.057, "duration": 4.4, "spread_duration": 4.2, "convexity": 24.0, "dv01": np.nan, "cs01": np.nan, "spread_bp": 155, "maturity_years": 5.3, "fx_beta": 0, "pd_1y": 0.0018, "recovery_rate": 0.40, "spread_vol_bp": 45, "bid_ask_bp": 4, "daily_volume_mm": 7.5, "issue_size_mm": 1250},
            {"identifier": "DEMO-HY7", "issuer": "Demo Telecom", "sector": "Communications", "rating": "B", "currency": "USD", "quantity": 1, "market_value": 750_000, "clean_price": 91.5, "yield": 0.086, "duration": 3.7, "spread_duration": 3.5, "convexity": 18.0, "dv01": np.nan, "cs01": np.nan, "spread_bp": 480, "maturity_years": 6.8, "fx_beta": 0, "pd_1y": 0.0521, "recovery_rate": 0.35, "spread_vol_bp": 110, "bid_ask_bp": 18, "daily_volume_mm": 2.0, "issue_size_mm": 650},
        ]
    )


def _portfolio_state() -> pd.DataFrame:
    if "fic_portfolio_df" not in st.session_state:
        st.session_state["fic_portfolio_df"] = _empty_portfolio_template()
    return st.session_state["fic_portfolio_df"]


# -----------------------------------------------------------------------------
# Overview pages
# -----------------------------------------------------------------------------

def _render_command_center() -> None:
    _section("Fixed Income Command Center")
    start = _start_date_for_years(5)
    us = _result_or_demo(_cached_us_curve(start), "curve")
    credit = _result_or_demo(_cached_credit(start), "credit")
    inflation = _cached_inflation(start)
    funding = _cached_funding(start)

    curve = latest_curve(us.frame)
    metrics = curve_snapshot_metrics(curve)
    credit_regime = build_credit_regime(credit.frame)

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("US 2Y", f"{_latest_value(us.frame, '2Y') or np.nan:.2f}%" if _latest_value(us.frame, "2Y") is not None else "N/A")
    c2.metric("US 10Y", f"{_latest_value(us.frame, '10Y') or np.nan:.2f}%" if _latest_value(us.frame, "10Y") is not None else "N/A")
    c3.metric("2s10s", _fmt_bp(metrics.get("2s10s_bp")))
    c4.metric("US IG OAS", f"{_latest_value(credit.frame, 'US IG OAS'):.0f} bp" if _latest_value(credit.frame, "US IG OAS") is not None else "N/A")
    c5.metric("US HY OAS", f"{_latest_value(credit.frame, 'US HY OAS'):.0f} bp" if _latest_value(credit.frame, "US HY OAS") is not None else "N/A")
    c6.metric("Credit regime", credit_regime.get("label", "N/A"), delta=f"Stress {credit_regime.get('score', np.nan):.1f}/100" if credit_regime.get("available") else None)

    left, right = st.columns([1.1, 1])
    with left:
        if not curve.empty:
            st.plotly_chart(_curve_figure({"Current US curve": curve}, "US Treasury curve"), width="stretch")
        else:
            st.info("US curve unavailable. No synthetic data is used unless Explicit demo data is selected.")
        _lineage_caption(us)
    with right:
        dashboard = credit_index_dashboard(credit.frame)
        if not dashboard.empty:
            show = dashboard[["index", "oas_bp", "change_1d_bp", "change_1m_bp", "percentile", "z_score"]].copy()
            st.dataframe(show, width="stretch", hide_index=True)
        else:
            st.info("Credit spread data unavailable.")
        _lineage_caption(credit)

    col1, col2 = st.columns(2)
    with col1:
        if inflation.ok:
            st.plotly_chart(_line_chart(inflation.frame.tail(750), [c for c in inflation.frame.columns if c != "date"], "Inflation compensation", "%"), width="stretch")
        _show_result_status(inflation)
    with col2:
        if funding.ok:
            cols = [c for c in ["SOFR", "Effective Fed Funds", "Financial Stress Index"] if c in funding.frame.columns]
            st.plotly_chart(_line_chart(funding.frame.tail(750), cols, "Funding and financial stress", "Level"), width="stretch")
        _show_result_status(funding)

    st.markdown(
        "<div class='fic-note'>The command center separates observed public data, market proxies and provider-required datasets. "
        "A missing source is surfaced as unavailable; it is not replaced silently by simulated observations.</div>",
        unsafe_allow_html=True,
    )


def _render_data_monitor() -> None:
    _section("Data Monitor & Lineage")
    years = st.selectbox("Monitoring window", [2, 5, 10], index=1, key="fic_monitor_years")
    start = _start_date_for_years(years)
    results = {
        "US nominal curve": _cached_us_curve(start),
        "US real curve": _cached_us_real(start),
        "Inflation compensation": _cached_inflation(start),
        "Credit OAS": _cached_credit(start),
        "Funding / stress": _cached_funding(start),
        "ECB AAA curve": _cached_ecb(start),
        "TRACE": trace_provider_status(),
    }
    monitor = build_data_monitor(results)
    st.dataframe(monitor, width="stretch", hide_index=True)
    _download_csv_button(monitor, "fixed_income_data_lineage.csv", "fic_monitor_download")
    st.markdown("#### Configuration status")
    rows = [
        {"configuration": "FRED_API_KEY", "required": "No; public CSV fallback available", "purpose": "Official FRED JSON API and metadata"},
        {"configuration": "SEC_USER_AGENT", "required": "Yes for production", "purpose": "Identifiable SEC EDGAR requests"},
        {"configuration": "OPENFIGI_API_KEY", "required": "No", "purpose": "Higher OpenFIGI mapping rate limits"},
        {"configuration": "yfinance", "required": "Optional", "purpose": "ETF and futures market proxies"},
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


# -----------------------------------------------------------------------------
# Rates pages
# -----------------------------------------------------------------------------

def _select_curve_result() -> tuple[str, DataResult]:
    market = st.selectbox("Curve universe", ["United States nominal", "United States real", "Euro area AAA spot"], key="fic_curve_market")
    years = st.selectbox("History", [2, 5, 10, 20], index=1, key="fic_curve_years")
    start = _start_date_for_years(years)
    if market == "United States nominal":
        return market, _result_or_demo(_cached_us_curve(start), "curve")
    if market == "United States real":
        return market, _cached_us_real(start)
    return market, _cached_ecb(start)


def _historical_curve_at_lag(frame: pd.DataFrame, lag: int) -> pd.DataFrame:
    df = normalize_curve_history(frame)
    if df.empty or len(df) <= lag:
        return pd.DataFrame()
    row = df.iloc[-1 - lag]
    rows = []
    for tenor, years in TENOR_LABEL_TO_YEARS.items():
        if tenor in df.columns and pd.notna(row[tenor]):
            rows.append({"tenor": tenor, "tenor_years": years, "rate": float(row[tenor])})
    return pd.DataFrame(rows).sort_values("tenor_years")


def _render_sovereign_curves() -> None:
    _section("Sovereign Curves")
    market, result = _select_curve_result()
    _show_result_status(result, compact=False)
    if not result.ok:
        return
    frame = normalize_curve_history(result.frame)
    current = latest_curve(frame)
    comparisons = {
        "Current": current,
        "1D ago": _historical_curve_at_lag(frame, 1),
        "1M ago": _historical_curve_at_lag(frame, 21),
        "1Y ago": _historical_curve_at_lag(frame, 252),
    }
    st.plotly_chart(_curve_figure(comparisons, market), width="stretch")
    metrics = curve_snapshot_metrics(current)
    cols = st.columns(5)
    cols[0].metric("2s10s", _fmt_bp(metrics.get("2s10s_bp")))
    cols[1].metric("5s30s", _fmt_bp(metrics.get("5s30s_bp")))
    cols[2].metric("3m10y", _fmt_bp(metrics.get("3m10y_bp")))
    cols[3].metric("2s5s10s fly", _fmt_bp(metrics.get("2s5s10s_fly_bp")))
    cols[4].metric("Curve regime", str(metrics.get("curve_regime", "N/A")))

    changes = curve_change_table(frame)
    percentiles = historical_curve_percentiles(frame)
    left, right = st.columns(2)
    with left:
        st.markdown("#### Curve moves")
        st.dataframe(changes, width="stretch", hide_index=True)
    with right:
        st.markdown("#### Historical location")
        st.dataframe(percentiles, width="stretch", hide_index=True)
    _lineage_caption(result)
    _download_csv_button(frame, "sovereign_curve_history.csv", "fic_curve_download")


def _render_curve_construction() -> None:
    _section("Curve Construction Lab")
    st.caption("Nelson–Siegel–Svensson calibration, discount factors and instantaneous forward rates. The public curve is used as input; no dealer quote is inferred.")
    source = st.radio("Input", ["Live public curve", "Upload tenor/rate CSV"], horizontal=True, key="fic_curve_build_source")
    curve = pd.DataFrame()
    if source == "Live public curve":
        _, result = _select_curve_result()
        _show_result_status(result)
        curve = latest_curve(result.frame)
    else:
        uploaded = st.file_uploader("CSV with tenor_years and rate columns", type=["csv"], key="fic_curve_build_upload")
        if uploaded is not None:
            data = pd.read_csv(uploaded)
            if {"tenor_years", "rate"}.issubset(data.columns):
                curve = data[["tenor_years", "rate"]].dropna().sort_values("tenor_years")
            else:
                st.error("Required columns: tenor_years, rate")
    if curve.empty:
        st.info("Provide a valid curve input.")
        return

    fit = fit_nelson_siegel_svensson(curve)
    if not fit.get("available"):
        st.error(fit.get("reason", "Calibration unavailable"))
        return
    fit_frame = fit["fit"]
    fitted_curve = pd.DataFrame({"tenor_years": fit_frame["tenor_years"], "rate": fit_frame["fitted"]})
    observed_curve = pd.DataFrame({"tenor_years": fit_frame["tenor_years"], "rate": fit_frame["observed"]})
    st.plotly_chart(_curve_figure({"Observed": observed_curve, "NSS fitted": fitted_curve}, "Curve calibration"), width="stretch")

    c1, c2 = st.columns([1, 1.4])
    with c1:
        st.metric("Calibration RMSE", f"{fit['rmse']:.5f} percentage points")
        st.dataframe(pd.DataFrame([fit["parameters"]]), width="stretch", hide_index=True)
    with c2:
        zero = zero_rates_to_discount_factors(fitted_curve["tenor_years"], fitted_curve["rate"], rates_in_percent=True)
        forward = instantaneous_forward_rates(fitted_curve["tenor_years"], fitted_curve["rate"], rates_in_percent=True)
        combined = zero.merge(forward[["tenor_years", "instantaneous_forward"]], on="tenor_years")
        combined["zero_rate_pct"] = combined["zero_rate"] * 100
        combined["instantaneous_forward_pct"] = combined["instantaneous_forward"] * 100
        st.dataframe(combined, width="stretch", hide_index=True)
        _download_csv_button(combined, "constructed_curve.csv", "fic_curve_construct_download")


def _render_relative_value() -> None:
    _section("Relative Value & Curve Trades")
    _, result = _select_curve_result()
    _show_result_status(result)
    if not result.ok:
        return
    frame = normalize_curve_history(result.frame)
    tenors = [c for c in frame.columns if c != "date"]
    c1, c2, c3 = st.columns(3)
    short_tenor = c1.selectbox("Short-leg tenor", tenors, index=min(4, len(tenors) - 1), key="fic_rv_short")
    long_tenor = c2.selectbox("Long-leg tenor", tenors, index=min(8, len(tenors) - 1), key="fic_rv_long")
    window = c3.selectbox("Z-score window", [63, 126, 252, 504], index=2, key="fic_rv_window")
    spread = (frame[long_tenor] - frame[short_tenor]) * 100.0
    z = rolling_zscore(spread, window=window)
    rv = pd.DataFrame({"date": frame["date"], "spread_bp": spread, "z_score": z}).dropna(subset=["spread_bp"])
    latest_spread = _safe_float(rv["spread_bp"].iloc[-1]) if not rv.empty else None
    latest_z = _safe_float(rv["z_score"].dropna().iloc[-1]) if rv["z_score"].notna().any() else None
    half_life = mean_reversion_half_life(rv["spread_bp"])
    cols = st.columns(4)
    cols[0].metric(f"{long_tenor}-{short_tenor}", _fmt_bp(latest_spread))
    cols[1].metric("Z-score", _fmt_num(latest_z))
    cols[2].metric("Half-life", f"{half_life:.1f} days" if half_life is not None else "Not mean-reverting")
    current_curve = latest_curve(frame)
    maturity_lookup = dict(zip(current_curve["tenor"], current_curve["tenor_years"])) if not current_curve.empty else {}
    long_carry = carry_roll_down(current_curve, maturity_lookup.get(long_tenor, 10), holding_period_years=1 / 12)
    short_carry = carry_roll_down(current_curve, maturity_lookup.get(short_tenor, 2), holding_period_years=1 / 12)
    cols[3].metric("Approx. 1M carry+roll spread", _fmt_bp((long_carry.get("total", 0) - short_carry.get("total", 0)) * 10000))

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=rv["date"], y=rv["spread_bp"], mode="lines", name="Spread (bp)"))
    fig.update_layout(template="plotly_dark", height=420, title=f"{long_tenor} minus {short_tenor}", yaxis_title="bp", hovermode="x unified")
    st.plotly_chart(fig, width="stretch")
    st.dataframe(rv.tail(250), width="stretch", hide_index=True)


def _render_inflation_real_rates() -> None:
    _section("Inflation & Real Rates")
    start = _start_date_for_years(st.selectbox("History", [2, 5, 10, 20], index=2, key="fic_inflation_years"))
    nominal = _cached_us_curve(start)
    real = _cached_us_real(start)
    inflation = _cached_inflation(start)
    if inflation.ok:
        st.plotly_chart(_line_chart(inflation.frame, [c for c in inflation.frame.columns if c != "date"], "Market inflation compensation", "%"), width="stretch")
    _show_result_status(inflation)

    if nominal.ok and real.ok and "10Y" in nominal.frame.columns and "10Y" in real.frame.columns:
        merged = pd.merge(nominal.frame[["date", "10Y"]], real.frame[["date", "10Y"]], on="date", suffixes=("_nominal", "_real"))
        merged["Nominal minus real 10Y"] = merged["10Y_nominal"] - merged["10Y_real"]
        if inflation.ok and "10Y Breakeven" in inflation.frame.columns:
            merged = pd.merge(merged, inflation.frame[["date", "10Y Breakeven"]], on="date", how="left")
            merged["Cross-check residual"] = merged["Nominal minus real 10Y"] - merged["10Y Breakeven"]
        st.plotly_chart(_line_chart(merged.tail(2500), [c for c in ["Nominal minus real 10Y", "10Y Breakeven", "Cross-check residual"] if c in merged.columns], "10Y inflation decomposition cross-check", "%"), width="stretch")
        st.caption("Nominal minus real yield is a simple breakeven proxy. Published inflation compensation may differ because of curve methodology, liquidity and risk premia.")


def _render_futures_volatility() -> None:
    _section("Futures, ETFs & Volatility")
    universe = ["ZT=F", "ZF=F", "ZN=F", "ZB=F", "UB=F", "SHY", "IEF", "TLT", "TIP", "LQD", "HYG"]
    selected = st.multiselect("Market proxies", universe, default=["ZN=F", "ZB=F", "TLT", "LQD", "HYG"], key="fic_proxy_symbols")
    period = st.selectbox("Period", ["6mo", "1y", "2y", "5y"], index=2, key="fic_proxy_period")
    if not selected:
        st.info("Select at least one proxy.")
        return
    result = _cached_market_proxies(tuple(selected), period)
    _show_result_status(result, compact=False)
    if not result.ok:
        return
    prices = result.frame.copy().sort_values("date")
    normalized = prices.copy()
    for col in selected:
        s = pd.to_numeric(prices.get(col), errors="coerce")
        first = s.dropna().iloc[0] if s.notna().any() else np.nan
        normalized[col] = s / first * 100 if pd.notna(first) and first != 0 else np.nan
    st.plotly_chart(_line_chart(normalized, selected, "Normalized fixed-income market proxies", "Index = 100"), width="stretch")
    returns = prices.set_index("date")[selected].pct_change()
    metrics = []
    for col in selected:
        s = returns[col].dropna()
        if s.empty:
            continue
        metrics.append({"symbol": col, "annualized_vol": s.std() * np.sqrt(252), "1M_return": prices[col].dropna().iloc[-1] / prices[col].dropna().iloc[-22] - 1 if prices[col].dropna().shape[0] > 21 else np.nan, "max_drawdown": (prices[col] / prices[col].cummax() - 1).min()})
    st.dataframe(pd.DataFrame(metrics), width="stretch", hide_index=True)
    corr = returns.corr()
    fig = go.Figure(go.Heatmap(z=corr.values, x=corr.columns, y=corr.index, zmin=-1, zmax=1, colorbar_title="Corr"))
    fig.update_layout(template="plotly_dark", height=480, title="Return correlation")
    st.plotly_chart(fig, width="stretch")
    _lineage_caption(result)


def _render_auctions_supply() -> None:
    _section("Treasury Auctions & Supply")
    c1, c2 = st.columns(2)
    start = c1.date_input("Start date", value=(pd.Timestamp.today() - pd.DateOffset(years=2)).date(), key="fic_auction_start")
    end = c2.date_input("End date", value=pd.Timestamp.today().date(), key="fic_auction_end")
    result = _cached_auctions(str(start), str(end))
    _show_result_status(result, compact=False)
    if not result.ok:
        return
    df = result.frame.copy()
    bid_col = next((c for c in ["bid_to_cover_ratio", "bid_to_cover"] if c in df.columns), None)
    amount_col = next((c for c in ["offering_amt", "total_accepted", "offering_amount"] if c in df.columns), None)
    yield_col = next((c for c in ["high_yield", "high_rate", "high_discount_rate"] if c in df.columns), None)
    cols = st.columns(4)
    cols[0].metric("Auctions", f"{len(df):,}")
    cols[1].metric("Latest auction", pd.Timestamp(df["auction_date"].max()).strftime("%Y-%m-%d") if "auction_date" in df.columns else "N/A")
    cols[2].metric("Median bid-to-cover", _fmt_num(df[bid_col].median()) if bid_col else "N/A")
    cols[3].metric("Total offering", _fmt_money(df[amount_col].sum()) if amount_col else "N/A")

    if amount_col and "security_term" in df.columns:
        supply = df.groupby("security_term", dropna=False)[amount_col].sum().sort_values(ascending=False).reset_index()
        fig = go.Figure(go.Bar(x=supply["security_term"], y=supply[amount_col], name="Offered"))
        fig.update_layout(template="plotly_dark", height=420, title="Supply by security term", xaxis_title="Security term", yaxis_title="Amount")
        st.plotly_chart(fig, width="stretch")
    if bid_col and "auction_date" in df.columns:
        chart = df.dropna(subset=[bid_col]).sort_values("auction_date")
        st.plotly_chart(_line_chart(chart.rename(columns={"auction_date": "date", bid_col: "Bid-to-cover"}), ["Bid-to-cover"], "Auction demand", "Ratio"), width="stretch")

    preferred = [c for c in ["auction_date", "issue_date", "maturity_date", "security_type", "security_term", "reopening", "cusip", amount_col, yield_col, bid_col, "direct_bidder_accepted", "indirect_bidder_accepted", "primary_dealer_accepted"] if c and c in df.columns]
    st.dataframe(df[preferred].head(500), width="stretch", hide_index=True)
    _lineage_caption(result)
    _download_csv_button(df, "treasury_auctions.csv", "fic_auction_download")


# -----------------------------------------------------------------------------
# Credit pages
# -----------------------------------------------------------------------------

def _render_credit_markets() -> None:
    _section("Credit Markets")
    years = st.selectbox("History", [2, 5, 10, 20], index=2, key="fic_credit_years")
    result = _result_or_demo(_cached_credit(_start_date_for_years(years)), "credit")
    _show_result_status(result, compact=False)
    if not result.ok:
        return
    dashboard = credit_index_dashboard(result.frame)
    regime = build_credit_regime(result.frame)
    cols = st.columns(4)
    cols[0].metric("Credit regime", regime.get("label", "N/A"))
    cols[1].metric("Stress score", f"{regime.get('score', np.nan):.1f}/100" if regime.get("available") else "N/A")
    ig = dashboard.loc[dashboard["index"] == "US IG OAS", "oas_bp"]
    hy = dashboard.loc[dashboard["index"] == "US HY OAS", "oas_bp"]
    cols[2].metric("US IG OAS", f"{ig.iloc[0]:.0f} bp" if not ig.empty else "N/A")
    cols[3].metric("US HY OAS", f"{hy.iloc[0]:.0f} bp" if not hy.empty else "N/A")
    st.plotly_chart(_line_chart(result.frame, [c for c in result.frame.columns if c != "date"], "ICE BofA option-adjusted spreads via FRED", "Basis points"), width="stretch")
    st.dataframe(dashboard, width="stretch", hide_index=True)
    if regime.get("available"):
        st.markdown("#### Regime contributions")
        st.dataframe(regime["components"], width="stretch", hide_index=True)
    st.caption("The hazard-rate column uses the first-order approximation spread / (1 - recovery). It is not a full CDS calibration.")
    _lineage_caption(result)


def _render_issuer_credit(default_ticker: str | None) -> None:
    _section("Issuer Credit Analytics")
    ticker = st.text_input("Issuer equity ticker for SEC mapping", value=(default_ticker or "AAPL").replace("=F", ""), key="fic_issuer_ticker").upper().strip()
    market_spread = st.number_input("Observed / user-supplied market spread (bp)", min_value=0.0, max_value=5000.0, value=150.0, step=5.0, key="fic_issuer_spread")
    if not ticker:
        st.info("Enter a ticker.")
        return
    result = _cached_sec_companyfacts(ticker)
    _show_result_status(result, compact=False)
    if not result.ok:
        return
    fundamentals = derive_issuer_credit_fundamentals(result.frame)
    metrics = {
        "net_leverage": fundamentals.get("net_leverage"),
        "interest_coverage": fundamentals.get("interest_coverage"),
        "liquidity_ratio": fundamentals.get("liquidity_ratio"),
        "fcf_to_debt": fundamentals.get("fcf_to_debt"),
        "short_term_debt_share": 0.20,
        "market_spread_bp": market_spread,
    }
    score = issuer_credit_score(metrics)
    cols = st.columns(5)
    cols[0].metric("Internal score", f"{score['score']:.1f}/100")
    cols[1].metric("Tier", score["tier"])
    cols[2].metric("Net leverage", _fmt_num(fundamentals.get("net_leverage")))
    cols[3].metric("Interest coverage", _fmt_num(fundamentals.get("interest_coverage")))
    cols[4].metric("Liquidity ratio", _fmt_num(fundamentals.get("liquidity_ratio")))
    display = pd.DataFrame([{"metric": k, "value": v} for k, v in fundamentals.items()])
    left, right = st.columns(2)
    with left:
        st.markdown("#### SEC-derived fundamentals")
        st.dataframe(display, width="stretch", hide_index=True)
    with right:
        st.markdown("#### Transparent score components")
        st.dataframe(score["components"], width="stretch", hide_index=True)
    st.warning(score["disclaimer"])

    with st.expander("Security master / OpenFIGI mapping"):
        id_type = st.selectbox("Identifier type", ["TICKER", "ID_ISIN", "ID_CUSIP"], key="fic_figi_type")
        id_value = st.text_input("Identifier value", value=ticker if id_type == "TICKER" else "", key="fic_figi_value")
        if st.button("Map identifier", key="fic_figi_map") and id_value:
            figi = map_openfigi(id_type, id_value)
            _show_result_status(figi, compact=False)
            if figi.ok:
                st.dataframe(figi.frame, width="stretch", hide_index=True)
    _lineage_caption(result)


def _render_bond_analytics() -> None:
    _section("Bond Pricing & Security Analytics")
    st.caption("Fixed-rate bullet bond analytics with clean/dirty price, accrued interest, yield, duration, convexity, DV01, z-spread and key-rate duration.")
    today = pd.Timestamp.today().date()
    c1, c2, c3, c4 = st.columns(4)
    face = c1.number_input("Face value", min_value=1.0, value=100.0, step=100.0, key="fic_bond_face")
    coupon_pct = c2.number_input("Coupon (%)", min_value=0.0, max_value=30.0, value=5.0, step=0.125, key="fic_bond_coupon")
    settlement = c3.date_input("Settlement", value=today, key="fic_bond_settlement")
    maturity = c4.date_input("Maturity", value=(pd.Timestamp(today) + pd.DateOffset(years=7)).date(), min_value=today + timedelta(days=1), key="fic_bond_maturity")
    c5, c6, c7, c8 = st.columns(4)
    frequency = c5.selectbox("Coupon frequency", [1, 2, 4], index=1, key="fic_bond_frequency")
    day_count = c6.selectbox("Day count", ["30/360", "ACT/365", "ACT/360", "ACT/ACT"], key="fic_bond_daycount")
    solve_mode = c7.radio("Solve", ["Price from yield", "Yield from price"], horizontal=False, key="fic_bond_solve")
    input_value = c8.number_input("Yield (%)" if solve_mode == "Price from yield" else "Clean price", min_value=-5.0 if solve_mode == "Price from yield" else 0.01, max_value=1000.0, value=5.25 if solve_mode == "Price from yield" else 98.5, step=0.05, key="fic_bond_input")

    try:
        spec = BondSpec(face_value=face, coupon_rate=coupon_pct / 100.0, settlement_date=settlement, maturity_date=maturity, coupon_frequency=frequency, day_count=day_count)
        if solve_mode == "Price from yield":
            ytm = input_value / 100.0
            clean_price = clean_price_from_ytm(spec, ytm)
        else:
            clean_price = input_value
            ytm = ytm_from_clean_price(spec, clean_price)
        risk = bond_risk_metrics(spec, ytm)
    except Exception as exc:
        st.error(f"Bond calculation error: {exc}")
        return

    cols = st.columns(6)
    cols[0].metric("Clean price", _fmt_num(clean_price, 4))
    cols[1].metric("Dirty price", _fmt_num(risk.get("dirty_price"), 4))
    cols[2].metric("YTM", _fmt_pct(ytm, 4))
    cols[3].metric("Modified duration", _fmt_num(risk.get("modified_duration"), 4))
    cols[4].metric("Convexity", _fmt_num(risk.get("convexity"), 2))
    cols[5].metric("DV01 / 100 face", _fmt_num(risk.get("dv01"), 5))

    cashflows = bond_cashflows(spec)
    left, right = st.columns([1, 1.2])
    with left:
        st.markdown("#### Cash-flow schedule")
        st.dataframe(cashflows, width="stretch", hide_index=True)
    with right:
        st.markdown("#### Yield-curve spread analytics")
        curve_result = _result_or_demo(_cached_us_curve(_start_date_for_years(5)), "curve")
        curve = latest_curve(curve_result.frame)
        if not curve.empty:
            tenors = curve["tenor_years"].to_numpy(float)
            zero = curve["rate"].to_numpy(float) / 100.0
            try:
                z_spread = z_spread_from_price(spec, clean_price, tenors, zero)
                st.metric("Approximate z-spread", f"{z_spread * 10000:.1f} bp")
                krd = key_rate_durations(spec, tenors, zero)
                st.dataframe(krd, width="stretch", hide_index=True)
            except Exception as exc:
                st.caption(f"Z-spread/KRD unavailable: {exc}")
        else:
            st.info("A zero-curve input is required for z-spread and KRD.")
    _download_csv_button(cashflows, "bond_cashflows.csv", "fic_bond_cf_download")


def _render_liquidity_trace() -> None:
    _section("Liquidity & TRACE")
    status = trace_provider_status()
    _show_result_status(status, compact=False)
    st.dataframe(pd.DataFrame(status.monitor_rows()), width="stretch", hide_index=True)
    st.markdown("#### User-supplied transaction file")
    uploaded = st.file_uploader("Upload entitled or public transaction data (CSV/XLSX/Parquet)", type=["csv", "xlsx", "xls", "parquet"], key="fic_trace_upload")
    if uploaded is None:
        st.caption("No transaction file loaded. The workstation will not fabricate TRACE trades.")
        return
    result = parse_uploaded_table(uploaded)
    _show_result_status(result, compact=False)
    if not result.ok:
        return
    df = result.frame.copy()
    st.dataframe(df.head(1000), width="stretch", hide_index=True)
    lower = {str(c).lower(): c for c in df.columns}
    price_col = next((lower[k] for k in ["price", "trade_price", "last_price"] if k in lower), None)
    volume_col = next((lower[k] for k in ["volume", "quantity", "par_value", "size"] if k in lower), None)
    time_col = next((lower[k] for k in ["date", "trade_date", "timestamp", "execution_time"] if k in lower), None)
    metrics = []
    if price_col:
        p = pd.to_numeric(df[price_col], errors="coerce").dropna()
        metrics.append({"metric": "Price dispersion", "value": p.std(ddof=1)})
        metrics.append({"metric": "Price range", "value": p.max() - p.min()})
    if volume_col:
        v = pd.to_numeric(df[volume_col], errors="coerce").dropna()
        metrics.append({"metric": "Reported volume", "value": v.sum()})
        metrics.append({"metric": "Median trade size", "value": v.median()})
    metrics.append({"metric": "Trade count", "value": len(df)})
    if time_col:
        timestamps = pd.to_datetime(df[time_col], errors="coerce").dropna()
        if not timestamps.empty:
            metrics.append({"metric": "Last trade", "value": timestamps.max()})
    st.dataframe(pd.DataFrame(metrics), width="stretch", hide_index=True)


# -----------------------------------------------------------------------------
# Portfolio pages
# -----------------------------------------------------------------------------

def _portfolio_input_block() -> pd.DataFrame:
    top = st.columns([1, 1, 1.5])
    uploaded = top[0].file_uploader("Portfolio CSV/XLSX", type=["csv", "xlsx", "xls"], key="fic_portfolio_upload")
    if uploaded is not None:
        result = parse_uploaded_table(uploaded)
        if result.ok:
            st.session_state["fic_portfolio_df"] = normalize_portfolio(result.frame)
        else:
            _show_result_status(result, compact=False)
    if top[1].button("Load explicit demo portfolio", key="fic_portfolio_demo"):
        st.session_state["fic_portfolio_df"] = _explicit_demo_portfolio()
        st.session_state["fic_portfolio_demo_active"] = True
    if top[2].button("Reset blank template", key="fic_portfolio_reset"):
        st.session_state["fic_portfolio_df"] = _empty_portfolio_template()
        st.session_state["fic_portfolio_demo_active"] = False
    if st.session_state.get("fic_portfolio_demo_active", False):
        st.warning("EXPLICIT DEMO PORTFOLIO — not actual holdings.")
    edited = st.data_editor(
        _portfolio_state(),
        width="stretch",
        num_rows="dynamic",
        key="fic_portfolio_editor",
    )
    st.session_state["fic_portfolio_df"] = edited
    return normalize_portfolio(edited)


def _render_portfolio_analytics() -> None:
    _section("Portfolio Analytics")
    portfolio = _portfolio_input_block()
    summary = portfolio_summary(portfolio)
    if not summary.get("available") or summary["market_value"] == 0:
        st.info("Enter non-zero market values to calculate portfolio analytics.")
        return
    cols = st.columns(7)
    cols[0].metric("Market value", _fmt_money(summary["market_value"]))
    cols[1].metric("Weighted yield", _fmt_pct(summary["weighted_yield"]))
    cols[2].metric("Duration", _fmt_num(summary["duration"]))
    cols[3].metric("Spread duration", _fmt_num(summary["spread_duration"]))
    cols[4].metric("DV01", _fmt_money(summary["dv01"]))
    cols[5].metric("CS01", _fmt_money(summary["cs01"]))
    cols[6].metric("Issuer HHI", _fmt_num(summary["issuer_hhi"], 3))
    tabs = st.tabs(["Issuer", "Sector", "Rating", "Currency", "Positions"])
    for tab, dim in zip(tabs[:4], ["issuer", "sector", "rating", "currency"]):
        with tab:
            st.dataframe(summary["breakdowns"][dim], width="stretch", hide_index=True)
    with tabs[4]:
        st.dataframe(summary["positions"], width="stretch", hide_index=True)
    _download_csv_button(summary["positions"], "fixed_income_portfolio.csv", "fic_portfolio_download")


def _render_risk_attribution() -> None:
    _section("Risk & Attribution")
    portfolio = normalize_portfolio(_portfolio_state())
    summary = portfolio_summary(portfolio)
    if not summary.get("available") or summary["market_value"] == 0:
        st.info("Populate the portfolio in Portfolio Analytics first.")
        return
    cols = st.columns(5)
    cols[0].metric("DV01", _fmt_money(summary["dv01"]))
    cols[1].metric("CS01", _fmt_money(summary["cs01"]))
    cols[2].metric("Duration", _fmt_num(summary["duration"]))
    cols[3].metric("Spread duration", _fmt_num(summary["spread_duration"]))
    cols[4].metric("Convexity", _fmt_num(summary["convexity"]))

    work = summary["positions"].copy()
    bins = [-np.inf, 1, 3, 5, 7, 10, 20, np.inf]
    labels = ["0-1Y", "1-3Y", "3-5Y", "5-7Y", "7-10Y", "10-20Y", "20Y+"]
    work["maturity_bucket"] = pd.cut(work["maturity_years"], bins=bins, labels=labels)
    ladder = work.groupby("maturity_bucket", observed=False)[["dv01", "cs01", "market_value"]].sum().reset_index()
    st.markdown("#### Key maturity risk ladder")
    st.dataframe(ladder, width="stretch", hide_index=True)

    c1, c2, c3 = st.columns(3)
    annual_vol = c1.number_input("Portfolio annual volatility assumption", min_value=0.0, max_value=1.0, value=0.06, step=0.005, key="fic_risk_vol")
    confidence = c2.selectbox("Confidence", [0.95, 0.975, 0.99], index=0, key="fic_risk_conf")
    horizon = c3.selectbox("Horizon (days)", [1, 5, 10, 20], index=0, key="fic_risk_horizon")
    var = parametric_var_es(summary["market_value"], annual_vol, confidence, horizon)
    cols = st.columns(2)
    cols[0].metric("Parametric VaR", _fmt_money(var["var"]))
    cols[1].metric("Parametric Expected Shortfall", _fmt_money(var["expected_shortfall"]))
    st.caption("Parametric VaR is a distributional approximation. The scenario lab should remain the primary tool for nonlinear, spread and liquidity shocks.")


def _render_stress_lab() -> None:
    _section("Stress & Scenario Lab")
    portfolio = normalize_portfolio(_portfolio_state())
    summary = portfolio_summary(portfolio)
    if not summary.get("available") or summary["market_value"] == 0:
        st.info("Populate the portfolio in Portfolio Analytics first.")
        return
    matrix = run_scenario_matrix(portfolio)
    st.dataframe(matrix, width="stretch", hide_index=True)
    if not matrix.empty:
        fig = go.Figure(go.Bar(x=matrix["scenario"], y=matrix["total_pnl"], name="P&L"))
        fig.update_layout(template="plotly_dark", height=430, title="Scenario P&L", yaxis_title="P&L", xaxis_tickangle=-30)
        st.plotly_chart(fig, width="stretch")

    st.markdown("#### Custom scenario")
    c1, c2, c3, c4 = st.columns(4)
    parallel = c1.number_input("Parallel rate shock (bp)", min_value=-1000.0, max_value=1000.0, value=50.0, step=5.0, key="fic_stress_parallel")
    short = c2.number_input("Short-end twist (bp)", min_value=-1000.0, max_value=1000.0, value=0.0, step=5.0, key="fic_stress_short")
    long = c3.number_input("Long-end twist (bp)", min_value=-1000.0, max_value=1000.0, value=0.0, step=5.0, key="fic_stress_long")
    spread = c4.number_input("Spread shock (bp)", min_value=-2000.0, max_value=5000.0, value=100.0, step=10.0, key="fic_stress_spread")
    c5, c6 = st.columns(2)
    liquidity = c5.number_input("Liquidity haircut (%)", min_value=0.0, max_value=100.0, value=0.0, step=0.25, key="fic_stress_liquidity")
    fx = c6.number_input("FX shock (%)", min_value=-50.0, max_value=50.0, value=0.0, step=0.5, key="fic_stress_fx")
    custom = ScenarioShock("Custom", parallel_rate_bp=parallel, short_rate_bp=short, long_rate_bp=long, spread_bp=spread, liquidity_haircut_pct=liquidity, fx_pct=fx)
    result = scenario_pnl(portfolio, custom)
    if result.get("available"):
        totals = result["totals"]
        cols = st.columns(5)
        for col, key, label in zip(cols, ["rate_pnl", "spread_pnl", "fx_pnl", "liquidity_pnl", "total_pnl"], ["Rates", "Spread", "FX", "Liquidity", "Total"]):
            col.metric(label, _fmt_money(totals.get(key)))
        st.dataframe(result["positions"], width="stretch", hide_index=True)


# -----------------------------------------------------------------------------
# Research pages
# -----------------------------------------------------------------------------

def _render_strategy_lab() -> None:
    _section("Rates & Credit Strategy Lab")
    st.caption("Universal validation of a curve spread signal with publication-safe historical data, costs, position state and diagnostics.")
    _, result = _select_curve_result()
    _show_result_status(result)
    if not result.ok:
        return
    frame = normalize_curve_history(result.frame)
    tenors = [c for c in frame.columns if c != "date"]
    c1, c2, c3, c4 = st.columns(4)
    short = c1.selectbox("Short tenor", tenors, index=min(4, len(tenors) - 1), key="fic_strategy_short")
    long = c2.selectbox("Long tenor", tenors, index=min(8, len(tenors) - 1), key="fic_strategy_long")
    entry = c3.number_input("Entry z", min_value=0.25, max_value=5.0, value=1.5, step=0.25, key="fic_strategy_entry")
    cost = c4.number_input("Round-turn cost proxy (bp)", min_value=0.0, max_value=100.0, value=1.0, step=0.25, key="fic_strategy_cost")
    spread = (frame[long] - frame[short]) * 100.0
    spread.index = frame["date"]
    result_bt = backtest_zscore_strategy(spread, entry_z=entry, cost_bp=cost, window=252)
    if not result_bt.get("available"):
        st.error(result_bt.get("reason", "Backtest unavailable"))
        return
    metrics = result_bt["metrics"]
    cols = st.columns(6)
    cols[0].metric("Sharpe", _fmt_num(metrics.get("sharpe")))
    cols[1].metric("Annualized P&L", _fmt_num(metrics.get("annualized_pnl"), 4))
    cols[2].metric("Annualized vol", _fmt_num(metrics.get("annualized_vol"), 4))
    cols[3].metric("Max drawdown", _fmt_num(metrics.get("max_drawdown"), 4))
    cols[4].metric("Turnover", _fmt_num(metrics.get("turnover"), 1))
    cols[5].metric("Half-life", f"{metrics.get('half_life'):.1f}d" if metrics.get("half_life") else "N/A")
    bt = result_bt["frame"].reset_index().rename(columns={"index": "date"})
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=bt["date"], y=bt["equity"], mode="lines", name="Cumulative P&L"))
    fig.update_layout(template="plotly_dark", height=430, title="Strategy cumulative P&L", hovermode="x unified")
    st.plotly_chart(fig, width="stretch")
    st.dataframe(bt.tail(500), width="stretch", hide_index=True)
    st.warning("Research output only. The simple spread backtest does not yet model futures conversion factors, CTD switches, financing or executable bid/ask quotes unless supplied by the user.")


def _render_econometric_diagnostics() -> None:
    _section("Econometric Diagnostics")
    _, result = _select_curve_result()
    _show_result_status(result)
    if not result.ok:
        return
    frame = normalize_curve_history(result.frame)
    pca = pca_curve_factors(frame, n_components=3, on_changes=True)
    if pca.get("available"):
        cols = st.columns(2)
        with cols[0]:
            st.markdown("#### PCA explained variance")
            st.dataframe(pca["explained_variance"], width="stretch", hide_index=True)
        with cols[1]:
            st.markdown("#### Factor loadings")
            st.dataframe(pca["loadings"], width="stretch", hide_index=True)
        fig = go.Figure()
        for pc in [c for c in pca["loadings"].columns if c.startswith("PC")]:
            fig.add_trace(go.Scatter(x=pca["loadings"]["tenor"], y=pca["loadings"][pc], mode="lines+markers", name=pc))
        fig.update_layout(template="plotly_dark", height=420, title="Curve PCA loadings")
        st.plotly_chart(fig, width="stretch")
    else:
        st.info(pca.get("reason", "PCA unavailable"))

    tenors = [c for c in frame.columns if c != "date"]
    if len(tenors) >= 2:
        c1, c2 = st.columns(2)
        y_name = c1.selectbox("Dependent tenor", tenors, index=min(8, len(tenors) - 1), key="fic_econ_y")
        x_name = c2.selectbox("Hedge tenor", tenors, index=min(4, len(tenors) - 1), key="fic_econ_x")
        coint = cointegration_residual(frame[y_name], frame[x_name])
        if coint.get("available"):
            cols = st.columns(3)
            cols[0].metric("Hedge beta", _fmt_num(coint["beta"], 4))
            cols[1].metric("Intercept", _fmt_num(coint["alpha"], 4))
            cols[2].metric("Residual half-life", f"{coint['half_life']:.1f}d" if coint.get("half_life") else "Not mean-reverting")
            residual = coint["residual"]
            z = coint["z_score"]
            diagnostic = pd.DataFrame({"date": frame.loc[residual.index, "date"].to_numpy(), "residual": residual.to_numpy(), "z_score": z.to_numpy()})
            st.plotly_chart(_line_chart(diagnostic, ["residual", "z_score"], "Relative-value residual diagnostics", "Level"), width="stretch")


def _render_methodology() -> None:
    _section("Data Quality & Methodology")
    st.markdown(
        """
        ### Analytical controls
        - **Observed, proxy and demo data are distinct states.** Explicit demo data is opt-in and labelled.
        - **Rates are not prices.** Yield indices are not treated as directly tradable securities in portfolio execution.
        - **Curve semantics are preserved.** Par, zero/spot, forward and real yields are identified separately.
        - **Bond risk is finite-difference checked.** DV01, effective duration and convexity are calculated around the same pricing function.
        - **Credit proxies are labelled.** Spread/(1-recovery) is a first-order hazard approximation, not a calibrated CDS model.
        - **Provider gaps remain visible.** TRACE transaction history, CDS, complete swaps and volatility surfaces require the relevant product or entitlement.
        """
    )
    st.markdown("#### Provider registry")
    st.dataframe(licensed_provider_registry(), width="stretch", hide_index=True)
    st.markdown("#### Core formulas")
    st.latex(r"P=\sum_{t=1}^{n} CF_t D(0,t)")
    st.latex(r"\frac{\Delta P}{P}\approx-D_{mod}\Delta y+\frac{1}{2}C(\Delta y)^2-D_s\Delta s")
    st.latex(r"\lambda\approx\frac{s}{1-R}")
    st.markdown(
        "<div class='fic-note'>Production deployment should configure SEC_USER_AGENT, document all API keys in .streamlit/secrets.toml, "
        "and preserve vendor entitlements outside the repository. No secret is expected in source code.</div>",
        unsafe_allow_html=True,
    )


# -----------------------------------------------------------------------------
# Main router
# -----------------------------------------------------------------------------

PAGE_RENDERERS: dict[str, Callable[..., None]] = {
    "Command Center": _render_command_center,
    "Data Monitor": _render_data_monitor,
    "Sovereign Curves": _render_sovereign_curves,
    "Curve Construction": _render_curve_construction,
    "Relative Value": _render_relative_value,
    "Inflation & Real Rates": _render_inflation_real_rates,
    "Futures & Volatility": _render_futures_volatility,
    "Auctions & Supply": _render_auctions_supply,
    "Credit Markets": _render_credit_markets,
    "Bond Analytics": _render_bond_analytics,
    "Liquidity & TRACE": _render_liquidity_trace,
    "Portfolio Analytics": _render_portfolio_analytics,
    "Risk & Attribution": _render_risk_attribution,
    "Stress & Scenario Lab": _render_stress_lab,
    "Strategy Lab": _render_strategy_lab,
    "Econometric Diagnostics": _render_econometric_diagnostics,
    "Data Quality & Methodology": _render_methodology,
}


def _render_fixed_income_credit_analytics_v1(
    ticker: str | None = None,
    price_data: pd.DataFrame | None = None,
    analysis: dict | None = None,
) -> None:
    """Public entry point used by app.py."""
    _inject_css()
    st.markdown(
        f"""
        <div class="fic-hero">
            <div class="fic-kicker">INSTITUTIONAL RATES · CREDIT · PORTFOLIO RISK</div>
            <div class="fic-title">Fixed Income & Credit Analytics</div>
            <div class="fic-sub">
                Sovereign curves, curve construction, relative value, inflation, futures, auctions, credit spreads,
                issuer analysis, bond pricing, portfolio DV01/CS01, scenario risk and econometric diagnostics.
                Standalone workstation · version {MODULE_VERSION}.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    top1, top2, top3 = st.columns([1, 1.2, 2.2])
    data_mode = top1.selectbox(
        "Data mode",
        ["Live public data", "Explicit demo data"],
        index=0 if st.session_state.get("fic_data_mode", "Live public data") == "Live public data" else 1,
        key="fic_data_mode",
    )
    desk = top2.selectbox("Desk", list(DESK_PAGES), key="fic_desk")
    page = top3.radio("Workspace", DESK_PAGES[desk], horizontal=True, key=f"fic_page_{desk.lower()}")

    if data_mode == "Explicit demo data":
        st.warning("EXPLICIT DEMO DATA MODE — generated observations are not market data. Public/provider data remains clearly separated.")

    renderer = PAGE_RENDERERS.get(page)
    if page == "Issuer Credit":
        _render_issuer_credit(ticker)
    elif renderer is not None:
        renderer()
    else:
        st.error(f"Unknown Fixed Income workspace: {page}")


__all__ = ["render_fixed_income_credit_analytics"]

# ============================================================================
# V4 INSTITUTIONAL DECISION ENGINES
# ============================================================================

TREASURY_FUTURES_BASKET_COLUMNS = [
    "security", "clean_price", "conversion_factor", "accrued_today",
    "accrued_delivery", "interim_coupon_per_100", "cash_dv01_per_100k",
]


def treasury_futures_delivery_analytics(
    basket: pd.DataFrame,
    futures_price: float,
    settlement_date: Any,
    delivery_date: Any,
    repo_rate_pct: float,
    position_face: float = 10_000_000.0,
    contract_size: float = 100_000.0,
    day_basis: int = 360,
) -> dict[str, Any]:
    """Screen a Treasury delivery basket for gross/net basis and implied repo.

    Prices and accrued interest are per 100 face. Exchange-published conversion
    factors and delivery accrued interest must be supplied; neither is inferred.
    """
    if basket is None or basket.empty:
        return {"available": False, "reason": "A non-empty deliverable basket is required"}
    start, end = pd.Timestamp(settlement_date).normalize(), pd.Timestamp(delivery_date).normalize()
    days = int((end - start).days)
    if days <= 0:
        raise ValueError("delivery_date must be after settlement_date")
    if contract_size <= 0 or position_face < 0 or day_basis <= 0:
        raise ValueError("position_face, contract_size and day_basis must be valid")
    work = basket.copy()
    work.columns = [str(c).strip().lower().replace(" ", "_") for c in work.columns]
    aliases = {"cusip": "security", "cash_price": "clean_price", "cf": "conversion_factor", "dv01": "cash_dv01_per_100k"}
    work = work.rename(columns={k: v for k, v in aliases.items() if k in work.columns})
    for column in TREASURY_FUTURES_BASKET_COLUMNS:
        if column not in work.columns:
            work[column] = "" if column == "security" else np.nan
    for column in [c for c in TREASURY_FUTURES_BASKET_COLUMNS if c != "security"]:
        work[column] = pd.to_numeric(work[column], errors="coerce")
    work = work.dropna(subset=["clean_price", "conversion_factor", "accrued_today", "accrued_delivery"]).copy()
    work = work[(work["clean_price"] > 0) & (work["conversion_factor"] > 0)]
    if work.empty:
        return {"available": False, "reason": "No row has valid price, conversion factor and accrued interest"}
    work["interim_coupon_per_100"] = work["interim_coupon_per_100"].fillna(0.0)
    work["dirty_cash_price"] = work["clean_price"] + work["accrued_today"]
    work["invoice_price"] = float(futures_price) * work["conversion_factor"] + work["accrued_delivery"]
    financing_fraction = float(repo_rate_pct) / 100.0 * days / float(day_basis)
    work["financing_cost_per_100"] = work["dirty_cash_price"] * financing_fraction
    work["delivery_proceeds_per_100"] = work["invoice_price"] + work["interim_coupon_per_100"]
    work["gross_basis_points"] = work["clean_price"] - float(futures_price) * work["conversion_factor"]
    work["carry_to_delivery_points"] = (
        work["interim_coupon_per_100"] + work["accrued_delivery"]
        - work["accrued_today"] - work["financing_cost_per_100"]
    )
    work["net_basis_points"] = work["gross_basis_points"] - work["carry_to_delivery_points"]
    work["net_basis_32nds"] = work["net_basis_points"] * 32.0
    work["delivery_pnl_per_100"] = -work["net_basis_points"]
    work["implied_repo_pct"] = (
        (work["delivery_proceeds_per_100"] - work["dirty_cash_price"])
        / work["dirty_cash_price"] * float(day_basis) / days * 100.0
    )
    work["repo_specialness_bp"] = (work["implied_repo_pct"] - float(repo_rate_pct)) * 100.0
    work["cf_hedge_contracts"] = float(position_face) / float(contract_size) * work["conversion_factor"]
    work["futures_dv01_per_contract"] = work["cash_dv01_per_100k"] / work["conversion_factor"]
    work["dv01_hedge_contracts"] = np.where(
        work["futures_dv01_per_contract"].abs() > 0,
        (float(position_face) / 100_000.0 * work["cash_dv01_per_100k"]) / work["futures_dv01_per_contract"],
        np.nan,
    )
    work = work.sort_values(["implied_repo_pct", "net_basis_points"], ascending=[False, True]).reset_index(drop=True)
    work["ctd_rank"] = np.arange(1, len(work) + 1)
    ctd = work.iloc[0]
    hedge = ctd["dv01_hedge_contracts"] if pd.notna(ctd["dv01_hedge_contracts"]) else ctd["cf_hedge_contracts"]
    return {
        "available": True, "basket": work,
        "ctd_security": str(ctd["security"] or "Row 1"),
        "ctd_implied_repo_pct": float(ctd["implied_repo_pct"]),
        "ctd_net_basis_32nds": float(ctd["net_basis_32nds"]),
        "ctd_contracts": float(hedge), "days_to_delivery": days,
        "methodology": "Invoice price, carry-to-delivery, net basis and annualised implied-repo screen; timing of interim coupons is simplified.",
    }


CREDIT_RV_COLUMNS = [
    "security", "issuer", "sector", "rating", "maturity_years", "oas_bp",
    "yield_pct", "spread_duration", "bid_ask_bp", "daily_volume_mm", "pd_1y", "recovery_rate",
]


def credit_relative_value_screen(universe: pd.DataFrame, funding_bp: float = 0.0, stress_spread_bp: float = 100.0) -> dict[str, Any]:
    """Cross-sectional OAS fair-value, carry, liquidity and downside screen."""
    if universe is None or universe.empty:
        return {"available": False, "reason": "A bond universe is required"}
    df = universe.copy()
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    aliases = {"cusip": "security", "oas": "oas_bp", "ytm": "yield_pct", "duration": "spread_duration", "volume_mm": "daily_volume_mm"}
    df = df.rename(columns={k: v for k, v in aliases.items() if k in df.columns})
    for column in CREDIT_RV_COLUMNS:
        if column not in df.columns:
            df[column] = "" if column in {"security", "issuer", "sector", "rating"} else np.nan
    for column in [c for c in CREDIT_RV_COLUMNS if c not in {"security", "issuer", "sector", "rating"}]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna(subset=["maturity_years", "oas_bp", "spread_duration"]).copy()
    df = df[(df["maturity_years"] > 0) & (df["spread_duration"] >= 0)]
    if len(df) < 8:
        return {"available": False, "reason": "At least eight valid securities are required for a cross-sectional fair-value fit"}
    df["rating"] = df["rating"].fillna("NR").replace("", "NR").astype(str).str.upper()
    df["sector"] = df["sector"].fillna("Other").replace("", "Other").astype(str)
    df["issuer"] = df["issuer"].fillna("").astype(str)
    df["security"] = df["security"].fillna("").astype(str)
    df["pd_1y"] = df["pd_1y"].fillna(0.0).clip(0.0, 1.0)
    df["recovery_rate"] = df["recovery_rate"].fillna(0.40).clip(0.0, 0.95)
    df["bid_ask_bp"] = df["bid_ask_bp"].fillna(df["bid_ask_bp"].median()).fillna(20.0).clip(lower=0.0)
    df["daily_volume_mm"] = df["daily_volume_mm"].fillna(0.0).clip(lower=0.0)
    features = pd.DataFrame({"log_maturity": np.log1p(df["maturity_years"]), "sqrt_maturity": np.sqrt(df["maturity_years"])}, index=df.index)
    categorical = pd.get_dummies(df[["rating", "sector"]], drop_first=True, dtype=float)
    x = pd.concat([pd.Series(1.0, index=df.index, name="intercept"), features, categorical], axis=1)
    y = df["oas_bp"].to_numpy(dtype=float)
    weights = 1.0 / np.sqrt(1.0 + df["bid_ask_bp"].to_numpy(dtype=float))
    beta = np.linalg.lstsq(x.to_numpy(dtype=float) * weights[:, None], y * weights, rcond=None)[0]
    df["fair_oas_bp"] = x.to_numpy(dtype=float) @ beta
    df["oas_residual_bp"] = df["oas_bp"] - df["fair_oas_bp"]
    residual_median = float(df["oas_residual_bp"].median())
    mad = float((df["oas_residual_bp"] - residual_median).abs().median())
    robust_scale = max(1.4826 * mad, float(df["oas_residual_bp"].std(ddof=1)), 1.0)
    df["residual_z"] = (df["oas_residual_bp"] - residual_median) / robust_scale
    peer = df.groupby(["rating", "sector"], dropna=False)["oas_residual_bp"]
    peer_mean, peer_std, peer_count = peer.transform("mean"), peer.transform("std"), peer.transform("count")
    df["peer_z"] = np.where(peer_count >= 3, (df["oas_residual_bp"] - peer_mean) / peer_std.replace(0.0, np.nan), df["residual_z"])
    df["peer_z"] = pd.to_numeric(df["peer_z"], errors="coerce").fillna(df["residual_z"]).clip(-5.0, 5.0)
    df["expected_loss_bp"] = df["pd_1y"] * (1.0 - df["recovery_rate"]) * 10_000.0
    df["excess_carry_bp"] = df["oas_bp"] - df["expected_loss_bp"] - float(funding_bp)
    volume_component = np.sqrt(df["daily_volume_mm"] / (df["daily_volume_mm"] + 5.0)).fillna(0.0)
    df["liquidity_score"] = (100.0 * np.exp(-df["bid_ask_bp"] / 80.0) * (0.35 + 0.65 * volume_component)).clip(0.0, 100.0)
    df["stress_loss_pct"] = df["spread_duration"] * float(stress_spread_bp) / 100.0
    raw_score = 50.0 + 12.0 * df["peer_z"] + df["excess_carry_bp"].clip(-300, 500) / 20.0 + 0.20 * (df["liquidity_score"] - 50.0) - 1.25 * df["stress_loss_pct"]
    df["opportunity_score"] = raw_score.clip(0.0, 100.0)
    df["screen"] = np.select(
        [df["liquidity_score"] < 25, df["opportunity_score"] >= 70, df["opportunity_score"] <= 30],
        ["ILLIQUID — REVIEW", "CHEAP / REVIEW LONG", "RICH / REVIEW SHORT"], default="NEUTRAL",
    )
    residual = df["oas_residual_bp"].to_numpy(dtype=float)
    rmse = float(np.sqrt(np.mean(residual ** 2)))
    denominator = float(np.sum((y - y.mean()) ** 2))
    r2 = float(1.0 - np.sum(residual ** 2) / denominator) if denominator > 0 else np.nan
    return {
        "available": True,
        "screen": df.sort_values(["opportunity_score", "liquidity_score"], ascending=[False, False]).reset_index(drop=True),
        "model_rmse_bp": rmse, "model_r2": r2, "observations": int(len(df)), "feature_count": int(x.shape[1]),
        "methodology": "Weighted cross-sectional OAS fit by maturity, rating and sector; robust residual, expected loss, liquidity and stress overlay.",
    }


PNL_ATTRIBUTION_COLUMNS = ["rate_change_bp", "spread_change_bp", "roll_down_bp", "fx_return_pct", "realized_pnl"]


def fixed_income_pnl_attribution(frame: pd.DataFrame, horizon_days: int = 1) -> dict[str, Any]:
    """First/second-order fixed-income P&L explain with an explicit residual."""
    if frame is None or frame.empty:
        return {"available": False, "reason": "A portfolio is required"}
    raw = frame.copy()
    raw.columns = [str(c).strip().lower().replace(" ", "_") for c in raw.columns]
    base = normalize_portfolio(raw)
    for column in PNL_ATTRIBUTION_COLUMNS:
        values = pd.to_numeric(raw[column], errors="coerce") if column in raw.columns else pd.Series(np.nan, index=raw.index)
        base[column] = values.reindex(raw.index).to_numpy()
    shocks = ["rate_change_bp", "spread_change_bp", "roll_down_bp", "fx_return_pct"]
    base[shocks] = base[shocks].fillna(0.0)
    days = max(int(horizon_days), 1)
    base["carry_pnl"] = base["market_value"].fillna(0.0) * base["yield"].fillna(0.0) / 100.0 * days / 365.0
    base["rates_pnl"] = -base["dv01"].fillna(0.0) * base["rate_change_bp"]
    base["spread_pnl"] = -base["cs01"].fillna(0.0) * base["spread_change_bp"]
    base["roll_down_pnl"] = -base["dv01"].fillna(0.0) * base["roll_down_bp"]
    dy = base["rate_change_bp"] / 10_000.0
    base["convexity_pnl"] = 0.5 * base["market_value"].fillna(0.0) * base["convexity"].fillna(0.0) * dy.pow(2)
    base["fx_pnl"] = base["market_value"].fillna(0.0) * base["fx_beta"].fillna(0.0) * base["fx_return_pct"] / 100.0
    components = ["carry_pnl", "rates_pnl", "spread_pnl", "roll_down_pnl", "convexity_pnl", "fx_pnl"]
    base["explained_pnl"] = base[components].sum(axis=1)
    base["unexplained_pnl"] = base["realized_pnl"] - base["explained_pnl"]
    totals = {column: float(base[column].sum(skipna=True)) for column in components + ["explained_pnl", "realized_pnl", "unexplained_pnl"]}
    gross_mv = float(base["market_value"].abs().sum())
    totals["explained_return_pct"] = totals["explained_pnl"] / gross_mv * 100.0 if gross_mv else np.nan
    return {
        "available": True, "positions": base, "totals": totals,
        "realized_available": bool(base["realized_pnl"].notna().any()), "horizon_days": days,
    }


def portfolio_concentration_dashboard(frame: pd.DataFrame, issuer_limit_pct: float = 10.0) -> dict[str, Any]:
    """Gross-exposure concentration, effective breadth and sensitivity concentration."""
    df = normalize_portfolio(frame)
    gross = float(df["market_value"].abs().sum()) if not df.empty else 0.0
    if df.empty or gross <= 0:
        return {"available": False, "reason": "A portfolio with non-zero market value is required"}
    tables: dict[str, pd.DataFrame] = {}
    for dimension in ["issuer", "sector", "rating", "currency"]:
        grouped = df.groupby(dimension, dropna=False).agg(
            gross_market_value=("market_value", lambda s: float(s.abs().sum())),
            net_market_value=("market_value", "sum"), dv01=("dv01", "sum"), cs01=("cs01", "sum"),
        ).reset_index()
        grouped["gross_weight_pct"] = grouped["gross_market_value"] / gross * 100.0
        tables[dimension] = grouped.sort_values("gross_weight_pct", ascending=False).reset_index(drop=True)
    issuer = tables["issuer"]
    weights = issuer["gross_weight_pct"] / 100.0
    hhi = float(np.sum(weights.pow(2)))
    breaches = issuer[issuer["gross_weight_pct"] > float(issuer_limit_pct)].copy()
    risk_rows = []
    for risk in ["dv01", "cs01"]:
        total_abs = float(df[risk].abs().sum())
        if total_abs > 0:
            shares = df.assign(_risk=df[risk].abs()).groupby("issuer", dropna=False)["_risk"].sum() / total_abs
            risk_hhi = float(np.sum(shares.pow(2)))
            risk_rows.append({"risk": risk.upper(), "top_issuer_share_pct": float(shares.max() * 100.0), "hhi": risk_hhi, "effective_names": float(1.0 / risk_hhi)})
    return {
        "available": True, "gross_market_value": gross, "issuer_hhi": hhi,
        "effective_issuers": float(1.0 / hhi) if hhi > 0 else np.nan,
        "top_issuer_pct": float(issuer["gross_weight_pct"].iloc[0]),
        "top5_pct": float(issuer["gross_weight_pct"].head(5).sum()),
        "limit_breaches": breaches, "tables": tables, "risk_concentration": pd.DataFrame(risk_rows),
    }


def factor_pnl_components(
    frame: pd.DataFrame,
    rate_changes_bp: pd.Series,
    spread_changes_bp: pd.Series | None = None,
    fx_returns: pd.Series | None = None,
) -> pd.DataFrame:
    summary = portfolio_summary(frame)
    if not summary.get("available"):
        return pd.DataFrame()
    rate = pd.to_numeric(rate_changes_bp, errors="coerce").rename("rate")
    spread = pd.to_numeric(spread_changes_bp, errors="coerce").rename("spread") if spread_changes_bp is not None else pd.Series(0.0, index=rate.index, name="spread")
    fx = pd.to_numeric(fx_returns, errors="coerce").rename("fx") if fx_returns is not None else pd.Series(0.0, index=rate.index, name="fx")
    shocks = pd.concat([rate, spread, fx], axis=1).dropna(subset=["rate"]).fillna(0.0)
    fx_exposure = float(normalize_portfolio(frame).eval("market_value * fx_beta").sum(skipna=True))
    return pd.DataFrame({
        "Rates": -float(summary["dv01"]) * shocks["rate"],
        "Credit spread": -float(summary["cs01"]) * shocks["spread"],
        "FX": fx_exposure * shocks["fx"],
    }, index=shocks.index)


def liquidity_adjusted_expected_shortfall(
    daily_factor_pnl: pd.DataFrame,
    liquidity_horizons: Mapping[str, int],
    confidence: float = 0.975,
    base_horizon_days: int = 10,
) -> dict[str, Any]:
    """FRTB-style liquidity-horizon ES aggregation for a screening dashboard."""
    pnl = pd.DataFrame(daily_factor_pnl).apply(pd.to_numeric, errors="coerce").dropna(how="all").fillna(0.0)
    base = int(base_horizon_days)
    if pnl.empty or len(pnl) < max(60, base * 3):
        return {"available": False, "reason": "Insufficient factor P&L history"}
    if not 0.5 < confidence < 1.0 or base <= 0:
        raise ValueError("confidence or base horizon is invalid")
    horizon_by_factor = {column: max(base, int(liquidity_horizons.get(column, base))) for column in pnl.columns}
    base_pnl = pnl.rolling(base).sum().dropna()
    full_es = historical_var_es(base_pnl.sum(axis=1), confidence)["expected_shortfall"]
    unique_horizons = sorted(set([base] + list(horizon_by_factor.values())))
    aggregate_square = float(full_es) ** 2
    rows = [{"bucket_days": base, "included_factors": "All", "base_es": full_es, "scaled_es": full_es}]
    previous = base
    for horizon in unique_horizons[1:]:
        factors = [name for name, factor_horizon in horizon_by_factor.items() if factor_horizon >= horizon]
        if not factors:
            previous = horizon
            continue
        bucket_es = historical_var_es(base_pnl[factors].sum(axis=1), confidence)["expected_shortfall"]
        scaled = float(bucket_es) * sqrt((horizon - previous) / base)
        aggregate_square += scaled ** 2
        rows.append({"bucket_days": horizon, "included_factors": ", ".join(factors), "base_es": bucket_es, "scaled_es": scaled})
        previous = horizon
    adjusted = sqrt(max(aggregate_square, 0.0))
    return {
        "available": True, "base_es": float(full_es), "liquidity_adjusted_es": float(adjusted),
        "uplift_pct": (adjusted / full_es - 1.0) * 100.0 if full_es > 0 else np.nan,
        "confidence": float(confidence), "components": pd.DataFrame(rows), "factor_horizons": horizon_by_factor,
    }


def newey_west_tstat(series: pd.Series, max_lag: int | None = None) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna().to_numpy(dtype=float)
    n = len(values)
    if n < 10:
        return np.nan
    lag = int(max_lag if max_lag is not None else max(1, round(4.0 * (n / 100.0) ** (2.0 / 9.0))))
    demeaned = values - values.mean()
    long_run = float(np.dot(demeaned, demeaned) / n)
    for k in range(1, min(lag, n - 1) + 1):
        gamma = float(np.dot(demeaned[k:], demeaned[:-k]) / n)
        long_run += 2.0 * (1.0 - k / (lag + 1.0)) * gamma
    standard_error = sqrt(max(long_run, 0.0) / n)
    return float(values.mean() / standard_error) if standard_error > 0 else np.nan


def probabilistic_sharpe_ratio(series: pd.Series, benchmark_sharpe: float = 0.0) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    n = len(values)
    sd = float(values.std(ddof=1)) if n > 1 else 0.0
    if n < 30 or sd <= 0:
        return np.nan
    daily_sharpe = float(values.mean() / sd)
    benchmark_daily = float(benchmark_sharpe) / sqrt(252.0)
    skewness, kurtosis = float(values.skew()), float(values.kurtosis() + 3.0)
    denominator = sqrt(max(1e-12, 1.0 - skewness * daily_sharpe + (kurtosis - 1.0) * daily_sharpe ** 2 / 4.0))
    return float(_normal_cdf((daily_sharpe - benchmark_daily) * sqrt(n - 1.0) / denominator))


def walk_forward_signal_validation(
    spread_bp: pd.Series,
    entry_z: float = 1.5,
    exit_z: float = 0.25,
    stop_z: float = 3.0,
    window: int = 252,
    cost_bp: float = 1.0,
    minimum_train: int = 504,
    test_size: int = 126,
) -> dict[str, Any]:
    """Sequential, non-overlapping out-of-sample validation of a z-score signal."""
    spread = pd.to_numeric(spread_bp, errors="coerce").dropna()
    if len(spread) < minimum_train + max(42, test_size):
        return {"available": False, "reason": "Insufficient history for the requested walk-forward design"}
    folds, oos_parts, fold_id = [], [], 1
    for start in range(int(minimum_train), len(spread), int(test_size)):
        end = min(start + int(test_size), len(spread))
        result = backtest_zscore_strategy(spread.iloc[:end], entry_z, exit_z, stop_z, window, cost_bp)
        if not result.get("available"):
            continue
        test = result["frame"].iloc[start:end].copy()
        if test.empty:
            continue
        annual_mean, annual_vol = float(test["pnl"].mean() * 252.0), float(test["pnl"].std(ddof=1) * sqrt(252.0))
        fold_equity = test["pnl"].cumsum()
        folds.append({
            "fold": fold_id, "train_end": str(spread.index[start - 1]), "test_start": str(spread.index[start]),
            "test_end": str(spread.index[end - 1]), "observations": int(len(test)),
            "sharpe": annual_mean / annual_vol if annual_vol > 0 else np.nan,
            "pnl_bp": float(test["pnl"].sum()), "max_drawdown_bp": float((fold_equity - fold_equity.cummax()).min()),
            "turnover": float(test["position"].diff().abs().fillna(0.0).sum()),
        })
        test["fold"] = fold_id
        oos_parts.append(test)
        fold_id += 1
    if not oos_parts:
        return {"available": False, "reason": "No walk-forward fold was produced"}
    oos = pd.concat(oos_parts).sort_index()
    annual_mean, annual_vol = float(oos["pnl"].mean() * 252.0), float(oos["pnl"].std(ddof=1) * sqrt(252.0))
    equity = oos["pnl"].cumsum()
    return {
        "available": True, "folds": pd.DataFrame(folds), "oos": oos,
        "metrics": {
            "oos_sharpe": annual_mean / annual_vol if annual_vol > 0 else np.nan,
            "annualized_pnl_bp": annual_mean, "annualized_vol_bp": annual_vol,
            "max_drawdown_bp": float((equity - equity.cummax()).min()),
            "newey_west_tstat": newey_west_tstat(oos["pnl"]),
            "probabilistic_sharpe": probabilistic_sharpe_ratio(oos["pnl"]),
            "positive_fold_ratio": float((pd.DataFrame(folds)["sharpe"] > 0).mean()),
            "turnover": float(oos["position"].diff().abs().fillna(0.0).sum()),
        },
    }


# ============================================================================
# V5 CREDIT DECISION ENGINES
# ============================================================================

def merton_distance_to_default(
    equity_value: float,
    equity_volatility: float,
    debt_face_value: float,
    risk_free_rate: float = 0.04,
    horizon_years: float = 1.0,
    asset_drift: float | None = None,
) -> dict[str, float | bool | str]:
    """Infer firm asset value/volatility and Merton distance-to-default.

    Equity volatility and rates are decimals. The model solves the Black-Scholes
    equity-as-call equations and reports both risk-neutral and physical DD when
    an asset drift is supplied.
    """
    equity, sigma_e, debt = float(equity_value), float(equity_volatility), float(debt_face_value)
    rate, horizon = float(risk_free_rate), float(horizon_years)
    if equity <= 0 or sigma_e <= 0 or debt <= 0 or horizon <= 0:
        raise ValueError("equity value, equity volatility, debt and horizon must be positive")

    def equations(log_parameters: np.ndarray) -> np.ndarray:
        asset, sigma_a = np.exp(log_parameters)
        d1 = (np.log(asset / debt) + (rate + 0.5 * sigma_a ** 2) * horizon) / (sigma_a * sqrt(horizon))
        d2 = d1 - sigma_a * sqrt(horizon)
        model_equity = asset * _normal_cdf(float(d1)) - debt * exp(-rate * horizon) * _normal_cdf(float(d2))
        model_sigma_e = _normal_cdf(float(d1)) * asset * sigma_a / equity
        return np.array([(model_equity - equity) / equity, (model_sigma_e - sigma_e) / sigma_e], dtype=float)

    asset_guess = equity + debt * exp(-rate * horizon)
    sigma_guess = max(0.01, sigma_e * equity / asset_guess)
    converged = False
    if least_squares is not None:
        solution = least_squares(
            equations,
            np.log([asset_guess, sigma_guess]),
            bounds=(np.log([max(equity, 1e-8), 1e-4]), np.log([max(asset_guess * 100.0, debt * 100.0), 5.0])),
            max_nfev=5000,
            xtol=1e-12,
            ftol=1e-12,
            gtol=1e-12,
        )
        asset_value, asset_volatility = np.exp(solution.x)
        converged = bool(solution.success and np.linalg.norm(equations(solution.x)) < 1e-5)
    else:
        asset_value, asset_volatility = asset_guess, sigma_guess
        for _ in range(200):
            d1 = (log(asset_value / debt) + (rate + 0.5 * asset_volatility ** 2) * horizon) / (asset_volatility * sqrt(horizon))
            delta = max(_normal_cdf(d1), 1e-6)
            new_sigma = max(1e-4, sigma_e * equity / (delta * asset_value))
            d2 = d1 - new_sigma * sqrt(horizon)
            new_asset = equity + debt * exp(-rate * horizon) * _normal_cdf(d2)
            if abs(new_asset - asset_value) / asset_value < 1e-9 and abs(new_sigma - asset_volatility) < 1e-9:
                converged = True
                asset_value, asset_volatility = new_asset, new_sigma
                break
            asset_value, asset_volatility = new_asset, new_sigma
    risk_neutral_dd = (log(asset_value / debt) + (rate - 0.5 * asset_volatility ** 2) * horizon) / (asset_volatility * sqrt(horizon))
    drift = rate if asset_drift is None else float(asset_drift)
    physical_dd = (log(asset_value / debt) + (drift - 0.5 * asset_volatility ** 2) * horizon) / (asset_volatility * sqrt(horizon))
    d1 = (log(asset_value / debt) + (rate + 0.5 * asset_volatility ** 2) * horizon) / (asset_volatility * sqrt(horizon))
    return {
        "available": True,
        "converged": converged,
        "asset_value": float(asset_value),
        "asset_volatility": float(asset_volatility),
        "debt_to_assets": float(debt / asset_value),
        "equity_delta": float(_normal_cdf(d1)),
        "risk_neutral_distance_to_default": float(risk_neutral_dd),
        "risk_neutral_pd": float(_normal_cdf(-risk_neutral_dd)),
        "physical_distance_to_default": float(physical_dd),
        "physical_pd": float(_normal_cdf(-physical_dd)),
        "model": "Merton equity-as-call structural screen",
    }


def cds_standard_coupon_metrics(
    calibration: pd.DataFrame,
    maturity_years: float,
    standard_coupon_bp: float,
    notional: float,
    recovery_rate: float = 0.40,
    discount_curve: Any = 0.04,
    payments_per_year: int = 4,
    protection_side: str = "Buy protection",
) -> dict[str, Any]:
    """Approximate standard-coupon upfront, CS01 and jump-to-default economics."""
    if calibration is None or calibration.empty:
        return {"available": False, "reason": "A calibrated hazard curve is required"}
    hazards = calibration.attrs.get("hazard_rates")
    tenors = calibration.attrs.get("hazard_tenors")
    if not hazards or not tenors:
        raise ValueError("calibration attributes do not contain the hazard curve")
    maturity, principal = float(maturity_years), abs(float(notional))
    if maturity <= 0 or principal <= 0:
        raise ValueError("maturity and notional must be positive")
    legs = cds_leg_pv(maturity, tenors, hazards, recovery_rate, discount_curve, payments_per_year)
    par_spread = 10000.0 * legs["protection_leg"] / legs["rpv01"]
    clean_upfront_fraction = (par_spread - float(standard_coupon_bp)) / 10000.0 * legs["rpv01"]
    sign = 1.0 if str(protection_side).lower().startswith("buy") else -1.0
    mark_to_market = sign * principal * clean_upfront_fraction
    cs01 = principal * legs["rpv01"] / 10000.0
    jump_to_default = sign * (principal * (1.0 - float(recovery_rate)) - mark_to_market)
    shocks = np.array([-250, -100, -50, -25, 25, 50, 100, 250], dtype=float)
    scenario = pd.DataFrame({"spread_shock_bp": shocks, "approx_mtm_change": sign * cs01 * shocks})
    return {
        "available": True,
        "par_spread_bp": float(par_spread),
        "standard_coupon_bp": float(standard_coupon_bp),
        "risky_pv01_years": float(legs["rpv01"]),
        "clean_upfront_pct": float(clean_upfront_fraction * 100.0),
        "clean_upfront_amount": float(principal * clean_upfront_fraction),
        "mark_to_market": float(mark_to_market),
        "cs01": float(cs01),
        "jump_to_default": float(jump_to_default),
        "cumulative_default_probability_pct": float(100.0 * legs["default_probability"]),
        "annual_coupon_amount": float(principal * float(standard_coupon_bp) / 10000.0),
        "scenario": scenario,
    }


def credit_carry_breakeven(
    market_value: float,
    yield_pct: float,
    funding_pct: float,
    oas_bp: float,
    spread_duration: float,
    rate_duration: float,
    convexity: float,
    horizon_years: float,
    default_probability: float,
    recovery_rate: float,
    roll_down_bp: float = 0.0,
    rate_change_bp: float = 0.0,
    spread_scenarios_bp: Sequence[float] = (-300, -200, -100, -50, 0, 50, 100, 200, 300),
) -> dict[str, Any]:
    """Expected credit return decomposition and spread-widening breakeven."""
    mv, horizon = float(market_value), float(horizon_years)
    if mv == 0 or horizon <= 0 or spread_duration < 0 or rate_duration < 0:
        raise ValueError("market value, horizon and durations are invalid")
    pd_h = clamp(float(default_probability), 0.0, 1.0)
    recovery = clamp(float(recovery_rate), 0.0, 0.99)
    dv01 = mv * float(rate_duration) / 10000.0
    cs01 = mv * float(spread_duration) / 10000.0
    gross_carry = mv * float(yield_pct) / 100.0 * horizon
    funding_cost = mv * float(funding_pct) / 100.0 * horizon
    expected_default_loss = abs(mv) * pd_h * (1.0 - recovery)
    roll_pnl = -dv01 * float(roll_down_bp)
    rates_pnl = -dv01 * float(rate_change_bp)
    dy = float(rate_change_bp) / 10000.0
    convexity_pnl = 0.5 * mv * float(convexity) * dy ** 2
    pre_spread_pnl = gross_carry - funding_cost - expected_default_loss + roll_pnl + rates_pnl + convexity_pnl
    breakeven = pre_spread_pnl / cs01 if abs(cs01) > 1e-12 else np.nan
    rows = []
    for shock in spread_scenarios_bp:
        spread_pnl = -cs01 * float(shock)
        total = pre_spread_pnl + spread_pnl
        rows.append({"spread_change_bp": float(shock), "spread_pnl": spread_pnl, "expected_total_pnl": total, "expected_return_pct": total / abs(mv) * 100.0})
    return {
        "available": True,
        "gross_carry": float(gross_carry), "funding_cost": float(funding_cost),
        "expected_default_loss": float(expected_default_loss), "roll_down_pnl": float(roll_pnl),
        "rates_pnl": float(rates_pnl), "convexity_pnl": float(convexity_pnl),
        "expected_pnl_before_spread_move": float(pre_spread_pnl),
        "expected_return_before_spread_move_pct": float(pre_spread_pnl / abs(mv) * 100.0),
        "spread_breakeven_widening_bp": float(breakeven), "dv01": float(dv01), "cs01": float(cs01),
        "carry_to_expected_loss": float((gross_carry - funding_cost) / expected_default_loss) if expected_default_loss > 0 else np.inf,
        "scenario": pd.DataFrame(rows), "oas_bp": float(oas_bp),
    }


def recovery_waterfall(
    capital_structure: pd.DataFrame,
    enterprise_values: Sequence[float],
    workout_cost_pct: float = 5.0,
) -> dict[str, Any]:
    """Absolute-priority waterfall with pari-passu allocation within each rank."""
    if capital_structure is None or capital_structure.empty:
        return {"available": False, "reason": "A capital structure is required"}
    claims = capital_structure.copy()
    claims.columns = [str(c).strip().lower().replace(" ", "_") for c in claims.columns]
    aliases = {"instrument": "security", "amount": "claim", "rank": "priority"}
    claims = claims.rename(columns={k: v for k, v in aliases.items() if k in claims.columns})
    for column in ["security", "class", "priority", "claim"]:
        if column not in claims.columns:
            claims[column] = "" if column in {"security", "class"} else np.nan
    claims["priority"] = pd.to_numeric(claims["priority"], errors="coerce")
    claims["claim"] = pd.to_numeric(claims["claim"], errors="coerce")
    claims = claims.dropna(subset=["priority", "claim"])
    claims = claims[claims["claim"] > 0].sort_values(["priority", "security"]).reset_index(drop=True)
    if claims.empty:
        return {"available": False, "reason": "No positive claim with a valid priority"}
    cost = clamp(float(workout_cost_pct) / 100.0, 0.0, 0.95)
    detail_rows, summary_rows = [], []
    total_claim = float(claims["claim"].sum())
    for scenario_number, enterprise_value in enumerate(enterprise_values, 1):
        gross_ev = max(float(enterprise_value), 0.0)
        distributable = gross_ev * (1.0 - cost)
        remaining = distributable
        scenario_recovery = np.zeros(len(claims), dtype=float)
        for priority, group in claims.groupby("priority", sort=True):
            group_claim = float(group["claim"].sum())
            allocation = min(remaining, group_claim)
            if group_claim > 0:
                scenario_recovery[group.index] = allocation * group["claim"].to_numpy(dtype=float) / group_claim
            remaining -= allocation
            if remaining <= 0:
                remaining = 0.0
        label = f"EV {gross_ev:,.0f}"
        for index, row in claims.iterrows():
            amount = float(scenario_recovery[index])
            detail_rows.append({
                "scenario": label, "enterprise_value": gross_ev, "security": row["security"], "class": row["class"],
                "priority": row["priority"], "claim": row["claim"], "recovery_amount": amount,
                "recovery_pct": amount / float(row["claim"]) * 100.0, "loss_amount": float(row["claim"]) - amount,
            })
        summary_rows.append({
            "scenario": label, "enterprise_value": gross_ev, "workout_cost": gross_ev * cost,
            "distributable_value": distributable, "total_claims": total_claim,
            "debt_recovery_pct": min(distributable, total_claim) / total_claim * 100.0,
            "equity_residual": max(remaining, 0.0),
        })
    return {"available": True, "detail": pd.DataFrame(detail_rows), "summary": pd.DataFrame(summary_rows), "claims": claims}


def covenant_headroom_analysis(covenants: pd.DataFrame) -> dict[str, Any]:
    """Evaluate current and stressed headroom for maximum/minimum tests."""
    if covenants is None or covenants.empty:
        return {"available": False, "reason": "Covenant inputs are required"}
    frame = covenants.copy()
    frame.columns = [str(c).strip().lower().replace(" ", "_") for c in frame.columns]
    for column in ["covenant", "test_type", "current", "limit", "stress_change"]:
        if column not in frame.columns:
            frame[column] = "" if column in {"covenant", "test_type"} else np.nan
    for column in ["current", "limit", "stress_change"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["current", "limit"]).copy()
    frame["stress_change"] = frame["stress_change"].fillna(0.0)
    frame["stressed_value"] = frame["current"] + frame["stress_change"]
    is_maximum = frame["test_type"].astype(str).str.lower().str.startswith("max")
    frame["current_headroom"] = np.where(is_maximum, frame["limit"] - frame["current"], frame["current"] - frame["limit"])
    frame["stressed_headroom"] = np.where(is_maximum, frame["limit"] - frame["stressed_value"], frame["stressed_value"] - frame["limit"])
    frame["stressed_headroom_pct_of_limit"] = frame["stressed_headroom"] / frame["limit"].abs().replace(0, np.nan) * 100.0
    frame["status"] = np.select([frame["stressed_headroom"] < 0, frame["stressed_headroom_pct_of_limit"] < 10], ["BREACH", "TIGHT"], default="PASS")
    return {
        "available": True, "table": frame,
        "breaches": int((frame["status"] == "BREACH").sum()), "tight_tests": int((frame["status"] == "TIGHT").sum()),
        "minimum_headroom_pct": float(frame["stressed_headroom_pct_of_limit"].min()) if not frame.empty else np.nan,
    }


WATCHLIST_COLUMNS = [
    "issuer", "rating", "oas_bp", "oas_z", "spread_change_1m_bp", "equity_drawdown_pct",
    "net_leverage", "interest_coverage", "liquidity_score", "maturity_12m_pct", "pd_1y", "covenant_headroom_pct",
]


def credit_watchlist_score(universe: pd.DataFrame) -> dict[str, Any]:
    """Transparent multi-signal early-warning ranking; higher score means more risk."""
    if universe is None or universe.empty:
        return {"available": False, "reason": "An issuer watchlist is required"}
    df = universe.copy()
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    for column in WATCHLIST_COLUMNS:
        if column not in df.columns:
            df[column] = "" if column in {"issuer", "rating"} else np.nan
    numeric = [c for c in WATCHLIST_COLUMNS if c not in {"issuer", "rating"}]
    for column in numeric:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna(subset=["issuer"]).copy()
    if df.empty:
        return {"available": False, "reason": "No valid issuer row"}
    defaults = {"oas_bp": 200.0, "oas_z": 0.0, "spread_change_1m_bp": 0.0, "equity_drawdown_pct": 0.0, "net_leverage": 3.0, "interest_coverage": 3.0, "liquidity_score": 50.0, "maturity_12m_pct": 10.0, "pd_1y": 0.01, "covenant_headroom_pct": 20.0}
    for column, value in defaults.items():
        df[column] = df[column].fillna(value)
    df["market_component"] = (50.0 + 15.0 * df["oas_z"].clip(-3, 4) + df["spread_change_1m_bp"].clip(-200, 400) / 5.0).clip(0, 100)
    df["equity_component"] = (-df["equity_drawdown_pct"].clip(-60, 0) * 1.7).clip(0, 100)
    df["fundamental_component"] = (df["net_leverage"].clip(0, 10) * 8.0 + (4.0 - df["interest_coverage"]).clip(0, 4) * 12.0).clip(0, 100)
    df["liquidity_component"] = (100.0 - df["liquidity_score"].clip(0, 100))
    df["refinancing_component"] = (df["maturity_12m_pct"].clip(0, 100) * 0.8 + (15.0 - df["covenant_headroom_pct"]).clip(0, 50) * 1.2).clip(0, 100)
    df["default_component"] = (df["pd_1y"].clip(0, 0.25) / 0.10 * 100.0).clip(0, 100)
    weights = {"market_component": 0.25, "equity_component": 0.10, "fundamental_component": 0.20, "liquidity_component": 0.15, "refinancing_component": 0.15, "default_component": 0.15}
    df["watch_score"] = sum(df[column] * weight for column, weight in weights.items())
    flags = []
    for row in df.itertuples(index=False):
        row_flags = []
        if row.pd_1y >= 0.10: row_flags.append("PD ≥10%")
        if row.interest_coverage < 1.5: row_flags.append("Coverage <1.5x")
        if row.covenant_headroom_pct < 0: row_flags.append("Covenant breach")
        if row.oas_z >= 2.0: row_flags.append("OAS z ≥2")
        if row.spread_change_1m_bp >= 100: row_flags.append("Spread +100bp")
        if row.liquidity_score < 20: row_flags.append("Illiquid")
        flags.append(" · ".join(row_flags))
    df["hard_flags"] = flags
    severe_flag = df["hard_flags"].str.contains(r"PD ≥10%|Covenant breach", regex=True, na=False)
    multiple_flags = df["hard_flags"].str.count("·").ge(1)
    df["status"] = np.select(
        [(df["watch_score"] >= 75) | severe_flag | multiple_flags, df["watch_score"] >= 55, df["watch_score"] >= 40],
        ["CRITICAL", "WATCH", "MONITOR"], default="STABLE",
    )
    df = df.sort_values(["watch_score", "pd_1y"], ascending=[False, False]).reset_index(drop=True)
    return {
        "available": True, "watchlist": df, "critical": int((df["status"] == "CRITICAL").sum()),
        "watch": int((df["status"] == "WATCH").sum()), "median_score": float(df["watch_score"].median()),
        "weights": pd.DataFrame([{"component": k, "weight": v} for k, v in weights.items()]),
    }


def credit_market_diagnostics(history: pd.DataFrame) -> dict[str, Any]:
    """Credit beta, breadth, correlation and decompression diagnostics."""
    if history is None or history.empty:
        return {"available": False, "reason": "Credit spread history is required"}
    df = history.copy()
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.sort_values("date").set_index("date")
    df = df.apply(pd.to_numeric, errors="coerce")
    valid = [c for c in CREDIT_OAS_SERIES if c in df.columns]
    if not valid:
        return {"available": False, "reason": "No recognised credit OAS series"}
    changes = df[valid].diff()
    one_month = df[valid].iloc[-1] - df[valid].iloc[max(0, len(df) - 22)]
    widening_breadth = float((one_month > 0).mean())
    ig, hy = changes.get("US IG OAS"), changes.get("US HY OAS")
    beta, corr_60, corr_252 = np.nan, np.nan, np.nan
    if ig is not None and hy is not None:
        aligned = pd.concat([ig.rename("ig"), hy.rename("hy")], axis=1).dropna()
        if len(aligned) >= 20 and aligned["ig"].var() > 0:
            beta = float(aligned.tail(756).cov().loc["hy", "ig"] / aligned.tail(756)["ig"].var())
            corr_60 = float(aligned.tail(60).corr().loc["hy", "ig"])
            corr_252 = float(aligned.tail(252).corr().loc["hy", "ig"])
    dispersion = float(df[valid].iloc[-1].std(ddof=1)) if len(valid) > 1 else np.nan
    return {
        "available": True, "widening_breadth": widening_breadth, "hy_ig_beta": beta,
        "hy_ig_corr_60d": corr_60, "hy_ig_corr_252d": corr_252,
        "cross_quality_dispersion_bp": dispersion, "one_month_changes": one_month.rename("change_1m_bp").reset_index().rename(columns={"index": "series"}),
        "change_correlation": changes.tail(756).corr(),
    }


# ============================================================================
# INSTITUTIONAL WORKSTATION V2.2 — GENUINE OVERRIDE
# ============================================================================
# This block intentionally overrides the first-generation UI router while
# preserving the tested public-data adapters and pricing/risk engines above.
# It is part of the same single file and requires no additional Python module.
# ============================================================================

MODULE_VERSION = "8.0.0-industrialized-core"


def _fic_v2_css() -> None:
    st.markdown(
        """
        <style>
        :root {
            --fic-bg:#030711;
            --fic-panel:#07111f;
            --fic-panel-2:#091729;
            --fic-border:rgba(91,198,255,.20);
            --fic-cyan:#5be7ff;
            --fic-blue:#4b7dff;
            --fic-green:#58e6ad;
            --fic-amber:#f2c96d;
            --fic-red:#ff7272;
            --fic-text:#f5f8fc;
            --fic-muted:rgba(213,227,242,.66);
        }
        .fic2-hero {
            border:1px solid rgba(91,198,255,.25);
            border-radius:18px;
            padding:14px 18px 13px 18px;
            margin:2px 0 9px 0;
            background:
                radial-gradient(circle at 8% 0%,rgba(91,231,255,.13),transparent 30%),
                radial-gradient(circle at 92% 0%,rgba(75,125,255,.15),transparent 34%),
                linear-gradient(180deg,rgba(7,19,39,.98),rgba(3,9,21,.98));
            box-shadow:0 18px 50px rgba(0,0,0,.20),inset 0 0 28px rgba(79,178,255,.025);
        }
        .fic2-kicker{color:var(--fic-cyan);font-size:.66rem;font-weight:900;letter-spacing:.22em;text-transform:uppercase}
        .fic2-title{font-size:1.55rem;font-weight:920;letter-spacing:-.025em;line-height:1.05;color:var(--fic-text);margin-top:4px}
        .fic2-sub{font-size:.78rem;line-height:1.38;color:var(--fic-muted);max-width:1220px;margin-top:6px}
        .fic2-statusbar{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px;margin:8px 0 10px 0}
        .fic2-status{
            border:1px solid rgba(91,198,255,.16);border-radius:13px;padding:9px 10px;
            background:linear-gradient(180deg,rgba(8,21,40,.78),rgba(4,12,25,.78));min-height:50px
        }
        .fic2-status-k{font-size:.58rem;color:rgba(208,226,243,.55);letter-spacing:.15em;text-transform:uppercase;font-weight:850}
        .fic2-status-v{font-size:.82rem;color:#fff;font-weight:850;margin-top:5px;overflow-wrap:anywhere}
        .fic2-section{color:var(--fic-cyan);font-size:.69rem;font-weight:900;letter-spacing:.19em;text-transform:uppercase;border-bottom:1px solid rgba(91,198,255,.13);padding-bottom:7px;margin:7px 0 12px 0}
        .fic2-card{
            border:1px solid rgba(91,198,255,.16);border-radius:16px;padding:13px 14px;
            background:linear-gradient(180deg,rgba(8,21,40,.77),rgba(4,12,25,.75));
            box-shadow:inset 0 0 24px rgba(79,178,255,.025)
        }
        .fic2-card-title{font-size:.68rem;color:var(--fic-cyan);letter-spacing:.15em;text-transform:uppercase;font-weight:900;margin-bottom:7px}
        .fic2-card-value{font-size:1.20rem;color:#fff;font-weight:900;line-height:1.05}
        .fic2-card-note{font-size:.70rem;color:var(--fic-muted);line-height:1.35;margin-top:6px}
        .fic2-chip{display:inline-block;border:1px solid rgba(91,198,255,.18);border-radius:999px;padding:4px 8px;margin:2px 3px 2px 0;background:rgba(8,21,40,.72);font-size:.65rem;font-weight:850;color:#dcecff}
        .fic2-good{color:var(--fic-green)!important}.fic2-warn{color:var(--fic-amber)!important}.fic2-bad{color:var(--fic-red)!important}
        .fic2-method{border-left:3px solid rgba(91,231,255,.65);background:rgba(7,20,38,.64);border-radius:0 12px 12px 0;padding:10px 12px;color:rgba(222,235,247,.72);font-size:.74rem;line-height:1.45}
        .fic2-rail{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px;margin:6px 0 12px 0}
        .fic2-rail>div{border:1px solid rgba(91,198,255,.14);border-radius:11px;padding:8px 10px;background:rgba(5,15,30,.72)}
        .fic2-rail-k{font-size:.57rem;color:rgba(208,226,243,.52);letter-spacing:.13em;text-transform:uppercase;font-weight:850}
        .fic2-rail-v{font-size:.76rem;color:#eef7ff;font-weight:850;margin-top:3px}
        [data-testid="stMetric"]{border:1px solid rgba(91,198,255,.16)!important;background:linear-gradient(180deg,rgba(8,21,40,.75),rgba(4,12,25,.72))!important;border-radius:15px!important;padding:11px 12px!important;min-height:88px!important}
        [data-testid="stMetricLabel"] p{font-size:.72rem!important;color:rgba(213,227,242,.68)!important}
        [data-testid="stMetricValue"]{font-size:1.35rem!important}
        [data-testid="stDataFrame"]{border:1px solid rgba(91,198,255,.12);border-radius:13px;overflow:hidden}
        div[data-baseweb="select"]>div,input,textarea{border-color:rgba(91,198,255,.23)!important;background:rgba(5,16,31,.86)!important}

        [data-testid="stTabs"] [data-baseweb="tab-list"]{
            gap:6px;padding:5px;border:1px solid rgba(91,198,255,.14);border-radius:13px;
            background:rgba(4,13,27,.72)
        }
        [data-testid="stTabs"] button[data-baseweb="tab"]{
            border-radius:9px!important;padding:8px 13px!important;font-size:.72rem!important;
            font-weight:850!important;letter-spacing:.03em
        }
        [data-testid="stTabs"] button[data-baseweb="tab"][aria-selected="true"]{
            background:linear-gradient(135deg,rgba(75,125,255,.28),rgba(91,231,255,.16))!important;
            color:#fff!important
        }
        [data-testid="stFileUploader"]{border:1px dashed rgba(91,198,255,.25);border-radius:13px;padding:4px;background:rgba(5,15,30,.55)}
        .stDownloadButton>button{border:1px solid rgba(91,198,255,.30)!important;border-radius:10px!important;background:linear-gradient(135deg,rgba(21,68,128,.55),rgba(8,37,70,.70))!important;font-weight:800!important}
        [data-testid="stDataFrame"]{box-shadow:0 12px 30px rgba(0,0,0,.12)}
        div[data-testid="stExpander"]{border:1px solid rgba(91,198,255,.14)!important;border-radius:13px!important;background:rgba(5,15,30,.50)!important}
        @media(max-width:1000px){.fic2-statusbar,.fic2-rail{grid-template-columns:repeat(2,minmax(0,1fr))}}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _fic_section(title: str) -> None:
    st.markdown(f"<div class='fic2-section'>{title}</div>", unsafe_allow_html=True)


def _fic_html_card(title: str, value: str, note: str = "", state: str = "") -> str:
    state_cls = {"good": "fic2-good", "warn": "fic2-warn", "bad": "fic2-bad"}.get(state, "")
    return (
        "<div class='fic2-card'>"
        f"<div class='fic2-card-title'>{title}</div>"
        f"<div class='fic2-card-value {state_cls}'>{value}</div>"
        f"<div class='fic2-card-note'>{note}</div>"
        "</div>"
    )


def _fic_last_non_null(frame: pd.DataFrame, column: str) -> float | None:
    if frame is None or frame.empty or column not in frame.columns:
        return None
    s = pd.to_numeric(frame[column], errors="coerce").dropna()
    return _safe_float(s.iloc[-1]) if not s.empty else None


def _fic_change(frame: pd.DataFrame, column: str, lag: int, multiplier: float = 1.0) -> float | None:
    if frame is None or frame.empty or column not in frame.columns:
        return None
    s = pd.to_numeric(frame[column], errors="coerce").dropna()
    if len(s) <= lag:
        return None
    return float((s.iloc[-1] - s.iloc[-1 - lag]) * multiplier)


def _fic_series_stat(frame: pd.DataFrame, column: str, unit: str = "level", window: int = 756) -> dict[str, Any]:
    if frame is None or frame.empty or column not in frame.columns:
        return {"name": column, "latest": None, "change_1d": None, "change_1w": None, "change_1m": None, "z_score": None, "percentile": None, "unit": unit}
    s = pd.to_numeric(frame[column], errors="coerce").dropna()
    if s.empty:
        return {"name": column, "latest": None, "change_1d": None, "change_1w": None, "change_1m": None, "z_score": None, "percentile": None, "unit": unit}
    hist = s.tail(window)
    sd = hist.std(ddof=1)
    latest = float(s.iloc[-1])
    return {
        "name": column,
        "latest": latest,
        "change_1d": float(s.iloc[-1] - s.iloc[-2]) if len(s) > 1 else np.nan,
        "change_1w": float(s.iloc[-1] - s.iloc[-6]) if len(s) > 5 else np.nan,
        "change_1m": float(s.iloc[-1] - s.iloc[-22]) if len(s) > 21 else np.nan,
        "z_score": float((latest - hist.mean()) / sd) if pd.notna(sd) and sd > 0 else 0.0,
        "percentile": float((hist <= latest).mean()) if not hist.empty else np.nan,
        "unit": unit,
    }


def _fic_spread_history(frame: pd.DataFrame, long_tenor: str, short_tenor: str) -> pd.DataFrame:
    df = normalize_curve_history(frame)
    if df.empty or long_tenor not in df.columns or short_tenor not in df.columns:
        return pd.DataFrame(columns=["date", "spread_bp"])
    out = df[["date", long_tenor, short_tenor]].copy()
    out["spread_bp"] = (pd.to_numeric(out[long_tenor], errors="coerce") - pd.to_numeric(out[short_tenor], errors="coerce")) * 100.0
    return out[["date", "spread_bp"]].dropna().reset_index(drop=True)


def _fic_curve_fly_history(frame: pd.DataFrame, wing1: str, belly: str, wing2: str) -> pd.DataFrame:
    df = normalize_curve_history(frame)
    if df.empty or any(x not in df.columns for x in [wing1, belly, wing2]):
        return pd.DataFrame(columns=["date", "fly_bp"])
    out = df[["date", wing1, belly, wing2]].copy()
    out["fly_bp"] = (2.0 * out[belly] - out[wing1] - out[wing2]) * 100.0
    return out[["date", "fly_bp"]].dropna().reset_index(drop=True)


def _fic_data_quality_score(results: Mapping[str, DataResult]) -> tuple[float, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    for name, result in results.items():
        ok = bool(result.ok)
        lineage = result.lineage or []
        stale = any(bool(x.is_stale) for x in lineage) if lineage else not ok
        proxy = any(bool(x.is_proxy) for x in lineage) if lineage else False
        status_score = 100.0 if ok else 0.0
        if stale:
            status_score -= 30.0
        if proxy:
            status_score -= 10.0
        if result.errors:
            status_score -= min(30.0, 8.0 * len(result.errors))
        rows.append({"dataset": name, "available": ok, "stale": stale, "proxy": proxy, "score": max(0.0, status_score), "errors": len(result.errors)})
    table = pd.DataFrame(rows)
    return (float(table["score"].mean()) if not table.empty else 0.0, table)


def _fic_rates_regime(curve_history: pd.DataFrame) -> dict[str, Any]:
    df = normalize_curve_history(curve_history)
    if df.empty:
        return {"label": "UNAVAILABLE", "score": 50.0, "drivers": []}
    current = latest_curve(df)
    snap = curve_snapshot_metrics(current)
    ten_y_1m = _fic_change(df, "10Y", 21, 100.0)
    two_y_1m = _fic_change(df, "2Y", 21, 100.0)
    slope_now = snap.get("2s10s_bp")
    slope_1m = None
    spread = _fic_spread_history(df, "10Y", "2Y")
    if len(spread) > 21:
        slope_1m = float(spread["spread_bp"].iloc[-1] - spread["spread_bp"].iloc[-22])
    level_move = np.nanmean([x for x in [ten_y_1m, two_y_1m] if x is not None]) if any(x is not None for x in [ten_y_1m, two_y_1m]) else 0.0
    slope_move = slope_1m or 0.0
    if level_move >= 10 and slope_move >= 5:
        label = "BEAR STEEPENER"
    elif level_move >= 10 and slope_move < 5:
        label = "BEAR FLATTENER"
    elif level_move <= -10 and slope_move >= 5:
        label = "BULL STEEPENER"
    elif level_move <= -10 and slope_move < 5:
        label = "BULL FLATTENER"
    else:
        label = "RANGE / TRANSITION"
    pressure = clamp(50.0 + level_move * 0.9 + abs(slope_move) * 0.25, 0.0, 100.0)
    return {
        "label": label,
        "score": pressure,
        "drivers": [f"10Y 1M {_fmt_bp(ten_y_1m)}", f"2Y 1M {_fmt_bp(two_y_1m)}", f"2s10s {_fmt_bp(slope_now)}", f"Slope 1M {_fmt_bp(slope_move)}"],
    }


def _fic_inflation_regime(inflation_history: pd.DataFrame) -> dict[str, Any]:
    if inflation_history is None or inflation_history.empty:
        return {"label": "UNAVAILABLE", "score": 50.0, "drivers": []}
    be10 = _fic_last_non_null(inflation_history, "10Y Breakeven")
    fwd = _fic_last_non_null(inflation_history, "5Y5Y Forward Inflation")
    be10_1m = _fic_change(inflation_history, "10Y Breakeven", 21, 100.0)
    fwd_1m = _fic_change(inflation_history, "5Y5Y Forward Inflation", 21, 100.0)
    if fwd is not None and fwd >= 2.65 and (fwd_1m or 0) > 5:
        label = "DE-ANCHORING RISK"
    elif (be10_1m or 0) >= 10:
        label = "RE-ACCELERATION"
    elif (be10_1m or 0) <= -10:
        label = "DISINFLATIONARY"
    else:
        label = "ANCHORED"
    score = clamp(50.0 + ((be10 or 2.25) - 2.25) * 35.0 + (be10_1m or 0) * 0.6 + max(0.0, ((fwd or 2.25) - 2.4) * 45.0), 0.0, 100.0)
    return {"label": label, "score": score, "drivers": [f"10Y BE {_fmt_num(be10)}%", f"10Y BE 1M {_fmt_bp(be10_1m)}", f"5Y5Y {_fmt_num(fwd)}%", f"5Y5Y 1M {_fmt_bp(fwd_1m)}"]}


def _fic_funding_regime(funding_history: pd.DataFrame) -> dict[str, Any]:
    if funding_history is None or funding_history.empty:
        return {"label": "UNAVAILABLE", "score": 50.0, "drivers": []}
    stress = _fic_last_non_null(funding_history, "Financial Stress Index")
    sofr = _fic_last_non_null(funding_history, "SOFR")
    effr = _fic_last_non_null(funding_history, "Effective Fed Funds")
    basis_bp = (sofr - effr) * 100 if sofr is not None and effr is not None else None
    if (stress or 0) >= 1.5 or abs(basis_bp or 0) >= 20:
        label = "STRESSED"
    elif (stress or 0) >= 0.5 or abs(basis_bp or 0) >= 10:
        label = "TIGHTENING"
    else:
        label = "NORMAL"
    score = clamp(35.0 + max(0.0, stress or 0) * 25.0 + abs(basis_bp or 0) * 1.4, 0.0, 100.0)
    return {"label": label, "score": score, "drivers": [f"Stress index {_fmt_num(stress)}", f"SOFR-EFFR {_fmt_bp(basis_bp)}"]}


def _fic_credit_regime_v2(credit_history: pd.DataFrame) -> dict[str, Any]:
    base = build_credit_regime(credit_history)
    if not base.get("available"):
        return {"label": "UNAVAILABLE", "score": 50.0, "drivers": []}
    ig = _fic_last_non_null(credit_history, "US IG OAS")
    hy = _fic_last_non_null(credit_history, "US HY OAS")
    hy_1m = _fic_change(credit_history, "US HY OAS", 21, 1.0)
    ig_1m = _fic_change(credit_history, "US IG OAS", 21, 1.0)
    label = str(base.get("label", "NEUTRAL")).upper()
    return {"label": label, "score": float(base.get("score", 50.0)), "drivers": [f"IG {ig:.0f} bp" if ig is not None else "IG N/A", f"HY {hy:.0f} bp" if hy is not None else "HY N/A", f"IG 1M {_fmt_bp(ig_1m)}", f"HY 1M {_fmt_bp(hy_1m)}"]}


def _fic_opportunity_monitor(curve_history: pd.DataFrame, credit_history: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    spread_specs = [("2s10s", "10Y", "2Y"), ("2s30s", "30Y", "2Y"), ("5s30s", "30Y", "5Y"), ("3m10y", "10Y", "3M")]
    for name, long_tenor, short_tenor in spread_specs:
        h = _fic_spread_history(curve_history, long_tenor, short_tenor)
        if h.empty:
            continue
        stat = _fic_series_stat(h, "spread_bp", "bp")
        rows.append({"structure": name, "asset_class": "Rates spread", "latest": stat["latest"], "z_score": stat["z_score"], "percentile": stat["percentile"], "1M_move": stat["change_1m"], "signal": "RICH" if (stat["z_score"] or 0) <= -1.5 else "CHEAP" if (stat["z_score"] or 0) >= 1.5 else "NEUTRAL"})
    fly_specs = [("2s5s10s", "2Y", "5Y", "10Y"), ("2s10s30s", "2Y", "10Y", "30Y"), ("5s10s30s", "5Y", "10Y", "30Y")]
    for name, w1, b, w2 in fly_specs:
        h = _fic_curve_fly_history(curve_history, w1, b, w2).rename(columns={"fly_bp": "value"})
        if h.empty:
            continue
        stat = _fic_series_stat(h, "value", "bp")
        rows.append({"structure": name, "asset_class": "Butterfly", "latest": stat["latest"], "z_score": stat["z_score"], "percentile": stat["percentile"], "1M_move": stat["change_1m"], "signal": "BELLY RICH" if (stat["z_score"] or 0) <= -1.5 else "BELLY CHEAP" if (stat["z_score"] or 0) >= 1.5 else "NEUTRAL"})
    if credit_history is not None and not credit_history.empty:
        for col in [c for c in CREDIT_OAS_SERIES if c in credit_history.columns]:
            stat = _fic_series_stat(credit_history, col, "bp")
            rows.append({"structure": col, "asset_class": "Credit OAS", "latest": stat["latest"], "z_score": stat["z_score"], "percentile": stat["percentile"], "1M_move": stat["change_1m"], "signal": "TIGHT" if (stat["z_score"] or 0) <= -1.5 else "WIDE" if (stat["z_score"] or 0) >= 1.5 else "NEUTRAL"})
    out = pd.DataFrame(rows)
    if not out.empty:
        out["dislocation_score"] = out["z_score"].abs() * 50.0 + (out["percentile"] - 0.5).abs() * 50.0
        out = out.sort_values("dislocation_score", ascending=False).reset_index(drop=True)
    return out


def _fic_curve_snapshot_at_lag(frame: pd.DataFrame, lag: int) -> pd.DataFrame:
    df = normalize_curve_history(frame)
    if df.empty:
        return pd.DataFrame(columns=["tenor", "tenor_years", "rate"])
    idx = max(0, len(df) - 1 - int(lag))
    row = df.iloc[idx]
    rows = []
    for tenor, years in TENOR_LABEL_TO_YEARS.items():
        if tenor in df.columns and pd.notna(row[tenor]):
            rows.append({"tenor": tenor, "tenor_years": years, "rate": float(row[tenor])})
    return pd.DataFrame(rows).sort_values("tenor_years")


def _fic_bootstrap_par_curve(curve: pd.DataFrame, frequency: int = 2) -> pd.DataFrame:
    """Approximate bootstrap from par yields using piecewise-linear discount factors."""
    if curve is None or curve.empty:
        return pd.DataFrame()
    work = curve[["tenor_years", "rate"]].copy().dropna().sort_values("tenor_years")
    known_t: list[float] = [0.0]
    known_df: list[float] = [1.0]
    rows: list[dict[str, float]] = []

    def interp_df(t: float, extra_t: float | None = None, extra_df: float | None = None) -> float:
        tx = np.array(known_t + ([extra_t] if extra_t is not None else []), dtype=float)
        dx = np.array(known_df + ([extra_df] if extra_df is not None else []), dtype=float)
        order = np.argsort(tx)
        tx, dx = tx[order], dx[order]
        return float(np.interp(t, tx, dx))

    for row in work.itertuples(index=False):
        maturity = float(row.tenor_years)
        par = float(row.rate) / 100.0
        if maturity <= 1.0 / frequency + 1e-9:
            df_t = 1.0 / (1.0 + par * maturity)
        else:
            coupon = par / frequency
            coupon_times = np.arange(1.0 / frequency, maturity + 1e-9, 1.0 / frequency)
            coupon_times = coupon_times[coupon_times < maturity - 1e-8]

            def pv_error(df_terminal: float) -> float:
                coupon_pv = sum(coupon * interp_df(float(t), maturity, df_terminal) for t in coupon_times)
                return coupon_pv + (1.0 + coupon) * df_terminal - 1.0

            low, high = 1e-8, min(1.5, known_df[-1] + 0.10)
            try:
                if brentq is not None:
                    df_t = float(brentq(pv_error, low, high, maxiter=200))
                else:
                    df_t = _bisect_root(pv_error, low, high)
            except Exception:
                df_t = float(np.exp(-par * maturity))
        df_t = float(np.clip(df_t, 1e-8, 1.5))
        zero = -np.log(df_t) / maturity if maturity > 0 else par
        known_t.append(maturity)
        known_df.append(df_t)
        rows.append({"tenor_years": maturity, "par_rate_pct": par * 100.0, "discount_factor": df_t, "zero_rate_pct": zero * 100.0})
    out = pd.DataFrame(rows)
    if not out.empty:
        fwd = instantaneous_forward_rates(out["tenor_years"], out["zero_rate_pct"], rates_in_percent=True)
        out = out.merge(fwd[["tenor_years", "instantaneous_forward"]], on="tenor_years", how="left")
        out["instantaneous_forward_pct"] = out["instantaneous_forward"] * 100.0
    return out


def _fic_fit_nss_regularized(curve: pd.DataFrame, model: str = "NSS regularized") -> dict[str, Any]:
    if curve is None or curve.empty or len(curve) < 4:
        return {"available": False, "reason": "At least four valid zero-curve points are required"}
    t = pd.to_numeric(curve["tenor_years"], errors="coerce").to_numpy(float)
    y = pd.to_numeric(curve["rate"], errors="coerce").to_numpy(float)
    mask = np.isfinite(t) & np.isfinite(y) & (t > 0)
    t, y = t[mask], y[mask]
    if len(t) < 4:
        return {"available": False, "reason": "Insufficient curve points"}
    if model == "Linear zero interpolation":
        fitted = y.copy()
        residual = y - fitted
        return {"available": True, "model": model, "parameters": {}, "rmse": 0.0, "mae": 0.0, "max_abs_residual": 0.0, "fit": pd.DataFrame({"tenor_years": t, "observed": y, "fitted": fitted, "residual": residual})}

    use_ns = model == "Nelson-Siegel"
    starts = [
        np.array([y[-1], y[0] - y[-1], 0.0, 0.0, 1.5, 7.0]),
        np.array([y[-1], y[0] - y[-1], 1.0, -1.0, 0.8, 4.0]),
        np.array([np.nanmean(y), y[0] - np.nanmean(y), -1.0, 1.0, 3.0, 12.0]),
        np.array([y[-1], y[0] - y[-1], 2.0, -2.0, 5.0, 20.0]),
    ]

    def model_values(params: np.ndarray) -> np.ndarray:
        p = params.copy()
        if use_ns:
            p[3] = 0.0
            p[5] = max(p[4] * 2.0, p[4] + 0.1)
        return nelson_siegel_svensson_rate(t, *p)

    def residuals(params: np.ndarray) -> np.ndarray:
        fit = model_values(params)
        regularization = np.array([
            0.02 * params[2],
            0.02 * params[3],
            0.03 * max(0.0, 0.15 - params[4]),
            0.03 * max(0.0, params[4] - params[5]),
        ])
        return np.r_[fit - y, regularization]

    best = None
    if least_squares is not None:
        lower = np.array([-5.0, -15.0, -20.0, -20.0, 0.10, 0.25])
        upper = np.array([15.0, 15.0, 20.0, 20.0, 15.0, 40.0])
        for start in starts:
            start = np.clip(start, lower + 1e-6, upper - 1e-6)
            try:
                fit_obj = least_squares(residuals, start, bounds=(lower, upper), max_nfev=20000, loss="soft_l1")
                score = float(np.sum(residuals(fit_obj.x) ** 2))
                if best is None or score < best[0]:
                    best = (score, fit_obj.x, bool(fit_obj.success))
            except Exception:
                continue
    if best is None:
        base = fit_nelson_siegel_svensson(curve)
        if not base.get("available"):
            return base
        params = base["parameters"]
        p = np.array([params[k] for k in ["beta0", "beta1", "beta2", "beta3", "tau1", "tau2"]])
        success = bool(base.get("success", True))
    else:
        _, p, success = best
    if use_ns:
        p[3] = 0.0
        p[5] = max(p[4] * 2.0, p[4] + 0.1)
    fitted = nelson_siegel_svensson_rate(t, *p)
    residual = y - fitted
    rmse = float(np.sqrt(np.mean(residual ** 2)))
    mae = float(np.mean(np.abs(residual)))
    max_abs = float(np.max(np.abs(residual)))
    # Residuals are percentage points: convert to bp before applying an explicit,
    # interpretable penalty.  The former coefficients forced any merely imperfect
    # public-curve fit to 0/100 and destroyed the diagnostic value of the score.
    rmse_bp, max_abs_bp = rmse * 100.0, max_abs * 100.0
    quality = clamp(100.0 - 5.0 * rmse_bp - 1.5 * max_abs_bp, 0.0, 100.0)
    return {
        "available": True,
        "success": success,
        "model": model,
        "quality_score": quality,
        "parameters": {"beta0": float(p[0]), "beta1": float(p[1]), "beta2": float(p[2]), "beta3": float(p[3]), "tau1": float(p[4]), "tau2": float(p[5])},
        "rmse": rmse,
        "mae": mae,
        "max_abs_residual": max_abs,
        "fit": pd.DataFrame({"tenor_years": t, "observed": y, "fitted": fitted, "residual": residual}),
    }


def _fic_trade_builder(curve_history: pd.DataFrame, short_tenor: str, long_tenor: str, anchor_notional: float, window: int, holding_months: int) -> dict[str, Any]:
    hist = _fic_spread_history(curve_history, long_tenor, short_tenor)
    if hist.empty:
        return {"available": False}
    hist["z_score"] = rolling_zscore(hist["spread_bp"], window=window)
    latest = float(hist["spread_bp"].iloc[-1])
    latest_z = _safe_float(hist["z_score"].dropna().iloc[-1]) if hist["z_score"].notna().any() else None
    percentile = float((hist["spread_bp"].tail(max(window, 252)) <= latest).mean())
    half_life = mean_reversion_half_life(hist["spread_bp"])
    curve = latest_curve(curve_history)
    lookup_y = dict(zip(curve["tenor"], curve["rate"]))
    lookup_t = dict(zip(curve["tenor"], curve["tenor_years"]))
    t_short = float(lookup_t.get(short_tenor, 2.0))
    t_long = float(lookup_t.get(long_tenor, 10.0))
    d_short = max(0.10, 0.86 * t_short)
    d_long = max(0.10, 0.86 * t_long)
    dv01_short_per_100 = d_short * 100.0 / 10000.0
    dv01_long_per_100 = d_long * 100.0 / 10000.0
    opposite_notional = dv01_neutral_notional(dv01_long_per_100, dv01_short_per_100, long_notional=anchor_notional)
    if (latest_z or 0.0) >= 0:
        # Spread is statistically wide: receive/long the long end and pay/short the short end.
        long_action, short_action = "RECEIVE / LONG", "PAY / SHORT"
        long_notional = anchor_notional
        short_notional = -opposite_notional
    else:
        # Spread is statistically tight: pay/short the long end and receive/long the short end.
        long_action, short_action = "PAY / SHORT", "RECEIVE / LONG"
        long_notional = -anchor_notional
        short_notional = opposite_notional
    hp = holding_months / 12.0
    long_carry = carry_roll_down(curve, t_long, holding_period_years=hp, duration=d_long)
    short_carry = carry_roll_down(curve, t_short, holding_period_years=hp, duration=d_short)
    net_carry_roll_bp = (long_carry.get("total", 0.0) - short_carry.get("total", 0.0)) * 10000.0
    long_dv01 = long_notional * d_long / 10000.0
    short_dv01 = short_notional * d_short / 10000.0
    residual_dv01 = long_dv01 + short_dv01
    quality = clamp(abs(latest_z or 0.0) * 22.0 + max(0.0, 2.0 - abs((half_life or 250.0) / 125.0)) * 12.0 + max(-10.0, min(15.0, net_carry_roll_bp)), 0.0, 100.0)
    ticket = pd.DataFrame([
        {"leg": "Long-end leg", "action": long_action, "tenor": long_tenor, "notional": abs(long_notional), "signed_dv01": long_dv01, "yield_pct": lookup_y.get(long_tenor)},
        {"leg": "Short-end leg", "action": short_action, "tenor": short_tenor, "notional": abs(short_notional), "signed_dv01": short_dv01, "yield_pct": lookup_y.get(short_tenor)},
    ])
    scenario_rows = []
    for move in [-50, -25, -10, 10, 25, 50]:
        # Symmetric twist: long-end yield changes by +move/2 and short-end by -move/2.
        long_yield_move = move / 2.0
        short_yield_move = -move / 2.0
        pnl = -long_dv01 * long_yield_move - short_dv01 * short_yield_move
        scenario_rows.append({"curve_spread_move_bp": move, "approx_pnl": pnl})
    return {
        "available": True, "history": hist, "spread_bp": latest, "z_score": latest_z, "percentile": percentile,
        "half_life": half_life, "net_carry_roll_bp": net_carry_roll_bp, "quality_score": quality,
        "ticket": ticket, "residual_dv01": residual_dv01, "gross_notional": abs(long_notional) + abs(short_notional),
        "scenarios": pd.DataFrame(scenario_rows),
    }


def _fic_render_command_center_v2() -> None:
    _fic_section("Cross-Asset Fixed Income Command Center")
    start = _start_date_for_years(10)
    us = _result_or_demo(_cached_us_curve(start), "curve")
    credit = _result_or_demo(_cached_credit(start), "credit")
    inflation = _cached_inflation(start)
    funding = _cached_funding(start)
    results = {"US curve": us, "Credit OAS": credit, "Inflation": inflation, "Funding": funding}
    quality, quality_table = _fic_data_quality_score(results)
    rates_regime = _fic_rates_regime(us.frame)
    credit_regime = _fic_credit_regime_v2(credit.frame)
    inflation_regime = _fic_inflation_regime(inflation.frame)
    funding_regime = _fic_funding_regime(funding.frame)
    snap = curve_snapshot_metrics(latest_curve(us.frame))

    kpis = st.columns(7)
    kpis[0].metric("US 2Y", f"{_fic_last_non_null(us.frame, '2Y'):.2f}%" if _fic_last_non_null(us.frame, "2Y") is not None else "N/A", _fmt_bp(_fic_change(us.frame, "2Y", 1, 100.0)))
    kpis[1].metric("US 10Y", f"{_fic_last_non_null(us.frame, '10Y'):.2f}%" if _fic_last_non_null(us.frame, "10Y") is not None else "N/A", _fmt_bp(_fic_change(us.frame, "10Y", 1, 100.0)))
    kpis[2].metric("2s10s", _fmt_bp(snap.get("2s10s_bp")))
    kpis[3].metric("IG OAS", f"{_fic_last_non_null(credit.frame, 'US IG OAS'):.0f} bp" if _fic_last_non_null(credit.frame, "US IG OAS") is not None else "N/A", _fmt_bp(_fic_change(credit.frame, "US IG OAS", 21)))
    kpis[4].metric("HY OAS", f"{_fic_last_non_null(credit.frame, 'US HY OAS'):.0f} bp" if _fic_last_non_null(credit.frame, "US HY OAS") is not None else "N/A", _fmt_bp(_fic_change(credit.frame, "US HY OAS", 21)))
    kpis[5].metric("10Y Breakeven", f"{_fic_last_non_null(inflation.frame, '10Y Breakeven'):.2f}%" if _fic_last_non_null(inflation.frame, "10Y Breakeven") is not None else "N/A")
    kpis[6].metric("Data quality", f"{quality:.0f}/100")

    cols = st.columns(4)
    regimes = [("Rates", rates_regime), ("Credit", credit_regime), ("Inflation", inflation_regime), ("Funding", funding_regime)]
    for col, (name, regime) in zip(cols, regimes):
        state = "bad" if regime["score"] >= 75 else "warn" if regime["score"] >= 55 else "good"
        with col:
            st.markdown(_fic_html_card(f"{name} regime", regime["label"], f"Pressure score {regime['score']:.0f}/100<br>" + " · ".join(regime["drivers"]), state), unsafe_allow_html=True)

    left, right = st.columns([1.22, 1.0])
    with left:
        curves = {"Current": latest_curve(us.frame), "1M ago": _fic_curve_snapshot_at_lag(us.frame, 21), "1Y ago": _fic_curve_snapshot_at_lag(us.frame, 252)}
        st.plotly_chart(_curve_figure(curves, "US Treasury curve — current versus history"), width="stretch")
    with right:
        opportunities = _fic_opportunity_monitor(us.frame, credit.frame)
        st.markdown("#### Opportunity monitor")
        if opportunities.empty:
            st.info("No statistically usable structures available.")
        else:
            show = opportunities.head(12).copy()
            show["percentile"] = show["percentile"].map(lambda x: f"{x:.0%}" if pd.notna(x) else "N/A")
            st.dataframe(show, width="stretch", hide_index=True)

    b1, b2 = st.columns([1.25, 1.0])
    with b1:
        monitor = _fic_market_monitor_frame(us.frame, credit.frame, inflation.frame, funding.frame)
        st.markdown("#### Multi-horizon monitor")
        st.dataframe(monitor, width="stretch", hide_index=True)
    with b2:
        st.markdown("#### Data-state audit")
        st.dataframe(quality_table, width="stretch", hide_index=True)
    st.markdown("<div class='fic2-method'>Decision hierarchy: observed public data → normalized market state → transparent regime classification → relative-value candidates. Missing or stale datasets remain visible and are never silently replaced by live-looking synthetic observations.</div>", unsafe_allow_html=True)


def _fic_market_monitor_frame(curve: pd.DataFrame, credit: pd.DataFrame, inflation: pd.DataFrame, funding: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for col in ["2Y", "5Y", "10Y", "30Y"]:
        if col in curve.columns:
            stat = _fic_series_stat(curve, col, "%")
            rows.append({"market": col, "group": "Rates", **{k: stat[k] for k in ["latest", "change_1d", "change_1w", "change_1m", "z_score", "percentile"]}})
    for name, l, s in [("2s10s", "10Y", "2Y"), ("5s30s", "30Y", "5Y"), ("3m10y", "10Y", "3M")]:
        h = _fic_spread_history(curve, l, s)
        if not h.empty:
            stat = _fic_series_stat(h, "spread_bp", "bp")
            rows.append({"market": name, "group": "Curve", **{k: stat[k] for k in ["latest", "change_1d", "change_1w", "change_1m", "z_score", "percentile"]}})
    for col in ["10Y Breakeven", "5Y5Y Forward Inflation"]:
        if col in inflation.columns:
            stat = _fic_series_stat(inflation, col, "%")
            rows.append({"market": col, "group": "Inflation", **{k: stat[k] for k in ["latest", "change_1d", "change_1w", "change_1m", "z_score", "percentile"]}})
    for col in ["US IG OAS", "US BBB OAS", "US HY OAS", "US BB OAS"]:
        if col in credit.columns:
            stat = _fic_series_stat(credit, col, "bp")
            rows.append({"market": col, "group": "Credit", **{k: stat[k] for k in ["latest", "change_1d", "change_1w", "change_1m", "z_score", "percentile"]}})
    if "Financial Stress Index" in funding.columns:
        stat = _fic_series_stat(funding, "Financial Stress Index", "index")
        rows.append({"market": "Financial Stress", "group": "Funding", **{k: stat[k] for k in ["latest", "change_1d", "change_1w", "change_1m", "z_score", "percentile"]}})
    out = pd.DataFrame(rows)
    if not out.empty:
        out["state"] = np.where(out["z_score"] >= 1.5, "HIGH / WIDE", np.where(out["z_score"] <= -1.5, "LOW / TIGHT", "NORMAL"))
        out["percentile"] = out["percentile"].map(lambda x: f"{x:.0%}" if pd.notna(x) else "N/A")
    return out


def _fic_render_market_monitor_v2() -> None:
    _fic_section("Institutional Market Monitor")
    years = st.selectbox("History", [2, 5, 10, 20], index=2, key="fic2_mm_years")
    start = _start_date_for_years(years)
    us, credit, inflation, funding = _cached_us_curve(start), _cached_credit(start), _cached_inflation(start), _cached_funding(start)
    monitor = _fic_market_monitor_frame(us.frame, credit.frame, inflation.frame, funding.frame)
    st.dataframe(monitor, width="stretch", hide_index=True)
    if us.ok:
        changes = curve_change_table(us.frame)
        cols = [c for c in changes.columns if c.startswith("change_")]
        if cols:
            z = changes[cols].to_numpy(float)
            fig = go.Figure(go.Heatmap(z=z, x=[c.replace("change_", "").replace("_bp", "") for c in cols], y=changes["tenor"], zmid=0, colorscale="RdBu_r", colorbar_title="bp"))
            fig.update_layout(template="plotly_dark", height=430, title="Treasury curve move heatmap")
            st.plotly_chart(fig, width="stretch")
    dislocations = _fic_opportunity_monitor(us.frame, credit.frame)
    if not dislocations.empty:
        fig = go.Figure()
        for group, sub in dislocations.groupby("asset_class"):
            fig.add_trace(go.Scatter(x=sub["z_score"], y=sub["1M_move"], mode="markers+text", text=sub["structure"], textposition="top center", name=group, marker={"size": 11}))
        fig.add_vline(x=0, line_dash="dot")
        fig.add_hline(y=0, line_dash="dot")
        fig.update_layout(template="plotly_dark", height=500, title="Valuation versus one-month momentum", xaxis_title="Historical z-score", yaxis_title="1M move")
        st.plotly_chart(fig, width="stretch")


def _fic_render_curve_monitor_v2() -> None:
    _fic_section("Sovereign Curve Monitor")
    market, result = _select_curve_result()
    _show_result_status(result, compact=False)
    if not result.ok:
        return
    frame = normalize_curve_history(result.frame)
    c1, c2 = st.columns([1.5, 1.0])
    with c1:
        curves = {"Current": latest_curve(frame), "1D": _fic_curve_snapshot_at_lag(frame, 1), "1W": _fic_curve_snapshot_at_lag(frame, 5), "1M": _fic_curve_snapshot_at_lag(frame, 21), "1Y": _fic_curve_snapshot_at_lag(frame, 252)}
        st.plotly_chart(_curve_figure(curves, f"{market} — curve history overlay"), width="stretch")
    with c2:
        snapshot = curve_snapshot_metrics(latest_curve(frame))
        rows = [
            {"metric": key, "value": _fmt_num(value) if isinstance(value, (int, float, np.number)) else str(value)}
            for key, value in snapshot.items()
        ]
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        regime = _fic_rates_regime(frame)
        st.markdown(_fic_html_card("Rates regime", regime["label"], " · ".join(regime["drivers"]), "bad" if regime["score"] > 70 else "warn" if regime["score"] > 50 else "good"), unsafe_allow_html=True)
    changes = curve_change_table(frame)
    percentiles = historical_curve_percentiles(frame, window=756)
    l, r = st.columns(2)
    with l:
        st.markdown("#### Curve change matrix")
        st.dataframe(changes, width="stretch", hide_index=True)
    with r:
        st.markdown("#### Historical valuation")
        st.dataframe(percentiles, width="stretch", hide_index=True)
    pca = pca_curve_factors(frame, n_components=3, on_changes=True)
    if pca.get("available"):
        p1, p2 = st.columns([1.0, 1.35])
        with p1:
            st.markdown("#### PCA factor share")
            st.dataframe(pca["explained_variance"], width="stretch", hide_index=True)
        with p2:
            fig = go.Figure()
            for pc in [c for c in pca["loadings"].columns if c.startswith("PC")]:
                fig.add_trace(go.Scatter(x=pca["loadings"]["tenor"], y=pca["loadings"][pc], mode="lines+markers", name=pc))
            fig.update_layout(template="plotly_dark", height=390, title="Level / slope / curvature factor loadings")
            st.plotly_chart(fig, width="stretch")


def _fic_render_curve_construction_v2() -> None:
    _fic_section("Curve Construction & Model Validation")
    st.caption("Par, zero and forward semantics are separated. Public par yields are bootstrapped before zero-curve fitting; no dealer quote is inferred.")
    source = st.radio("Input", ["Live public curve", "Upload tenor/rate CSV"], horizontal=True, key="fic2_cc_source")
    curve_type = st.selectbox("Input curve semantics", ["Par yield", "Zero / spot yield"], key="fic2_cc_semantics")
    model = st.selectbox("Model", ["NSS regularized", "Nelson-Siegel", "Linear zero interpolation"], key="fic2_cc_model")
    curve = pd.DataFrame()
    if source == "Live public curve":
        _, result = _select_curve_result()
        _show_result_status(result)
        if result.ok:
            curve = latest_curve(result.frame)
    else:
        uploaded = st.file_uploader("CSV columns: tenor_years, rate", type=["csv"], key="fic2_cc_upload")
        if uploaded is not None:
            try:
                curve = pd.read_csv(uploaded)
                curve["tenor_years"] = pd.to_numeric(curve["tenor_years"], errors="coerce")
                curve["rate"] = pd.to_numeric(curve["rate"], errors="coerce")
                curve = curve.dropna(subset=["tenor_years", "rate"])
            except Exception as exc:
                st.error(str(exc))
    if curve.empty:
        st.info("A valid curve is required.")
        return
    if curve_type == "Par yield":
        boot = _fic_bootstrap_par_curve(curve)
        zero_curve = boot[["tenor_years", "zero_rate_pct"]].rename(columns={"zero_rate_pct": "rate"})
    else:
        zero_curve = curve[["tenor_years", "rate"]].copy()
        boot = zero_rates_to_discount_factors(zero_curve["tenor_years"], zero_curve["rate"], rates_in_percent=True)
        boot["zero_rate_pct"] = boot["zero_rate"] * 100.0
        fwd = instantaneous_forward_rates(zero_curve["tenor_years"], zero_curve["rate"], rates_in_percent=True)
        boot = boot.merge(fwd[["tenor_years", "instantaneous_forward"]], on="tenor_years", how="left")
        boot["instantaneous_forward_pct"] = boot["instantaneous_forward"] * 100.0
    fit = _fic_fit_nss_regularized(zero_curve, model=model)
    if not fit.get("available"):
        st.error(fit.get("reason", "Calibration unavailable"))
        return
    fit_frame = fit["fit"].sort_values("tenor_years")
    dense_t = np.linspace(max(0.05, fit_frame["tenor_years"].min()), fit_frame["tenor_years"].max(), 240)
    if fit.get("parameters"):
        p = fit["parameters"]
        dense_rate = nelson_siegel_svensson_rate(dense_t, p["beta0"], p["beta1"], p["beta2"], p["beta3"], p["tau1"], p["tau2"])
    else:
        dense_rate = np.interp(dense_t, fit_frame["tenor_years"], fit_frame["fitted"])
    dense_zero = pd.DataFrame({"tenor_years": dense_t, "rate": dense_rate})
    dense_df = zero_rates_to_discount_factors(dense_t, dense_rate, rates_in_percent=True)
    dense_fwd = instantaneous_forward_rates(dense_t, dense_rate, rates_in_percent=True)
    dense = dense_df.merge(dense_fwd[["tenor_years", "instantaneous_forward"]], on="tenor_years")
    dense["zero_rate_pct"] = dense["zero_rate"] * 100.0
    dense["instantaneous_forward_pct"] = dense["instantaneous_forward"] * 100.0
    monotone = bool((dense["discount_factor"].diff().dropna() <= 1e-8).all())
    forward_min = float(dense["instantaneous_forward_pct"].min())
    forward_max = float(dense["instantaneous_forward_pct"].max())
    quality = float(fit.get("quality_score", 100.0))
    k = st.columns(6)
    k[0].metric("Model", fit.get("model", model))
    k[1].metric("Quality", f"{quality:.0f}/100")
    k[2].metric("RMSE", f"{fit['rmse']:.4f} pp")
    k[3].metric("MAE", f"{fit['mae']:.4f} pp")
    k[4].metric("Max residual", f"{fit['max_abs_residual']:.4f} pp")
    k[5].metric("DF monotone", "PASS" if monotone else "FAIL")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=fit_frame["tenor_years"], y=fit_frame["observed"], mode="markers", name="Observed zero"))
    fig.add_trace(go.Scatter(x=dense_t, y=dense_rate, mode="lines", name="Fitted zero"))
    fig.update_layout(template="plotly_dark", height=430, title="Zero-curve calibration", xaxis_title="Maturity (years)", yaxis_title="Yield (%)")
    st.plotly_chart(fig, width="stretch")
    c1, c2 = st.columns(2)
    with c1:
        fig_df = go.Figure(go.Scatter(x=dense["tenor_years"], y=dense["discount_factor"], mode="lines", name="Discount factor"))
        fig_df.update_layout(template="plotly_dark", height=350, title="Discount function")
        st.plotly_chart(fig_df, width="stretch")
    with c2:
        fig_fw = go.Figure(go.Scatter(x=dense["tenor_years"], y=dense["instantaneous_forward_pct"], mode="lines", name="Instantaneous forward"))
        fig_fw.update_layout(template="plotly_dark", height=350, title=f"Forward curve · range {forward_min:.2f}% to {forward_max:.2f}%")
        st.plotly_chart(fig_fw, width="stretch")
    t1, t2 = st.columns([1.0, 1.5])
    with t1:
        st.markdown("#### Parameters")
        st.dataframe(pd.DataFrame([fit.get("parameters", {})]), width="stretch", hide_index=True)
    with t2:
        st.markdown("#### Calibration residuals")
        st.dataframe(fit_frame, width="stretch", hide_index=True)
    _download_csv_button(dense, "fixed_income_zero_forward_curve_v2.csv", "fic2_cc_download")


def _fic_render_relative_value_v2() -> None:
    _fic_section("Relative Value & DV01-Neutral Trade Builder")
    _, result = _select_curve_result()
    _show_result_status(result)
    if not result.ok:
        return
    frame = normalize_curve_history(result.frame)
    tenors = [c for c in frame.columns if c != "date"]
    c1, c2, c3, c4, c5 = st.columns(5)
    short_tenor = c1.selectbox("Short tenor", tenors, index=min(4, len(tenors)-1), key="fic2_rv_short")
    long_tenor = c2.selectbox("Long tenor", tenors, index=min(8, len(tenors)-1), key="fic2_rv_long")
    window = c3.selectbox("Z-score window", [63,126,252,504,756], index=2, key="fic2_rv_window")
    anchor = c4.number_input("Anchor notional", min_value=100_000.0, max_value=1_000_000_000.0, value=10_000_000.0, step=1_000_000.0, key="fic2_rv_anchor")
    holding = c5.selectbox("Holding period", [1,3,6,12], index=0, key="fic2_rv_holding")
    if long_tenor == short_tenor:
        st.warning("Select two different tenors.")
        return
    trade = _fic_trade_builder(frame, short_tenor, long_tenor, anchor, window, holding)
    if not trade.get("available"):
        st.info("Trade construction unavailable.")
        return
    k = st.columns(7)
    k[0].metric(f"{long_tenor}-{short_tenor}", _fmt_bp(trade["spread_bp"]))
    k[1].metric("Z-score", _fmt_num(trade["z_score"]))
    k[2].metric("Percentile", f"{trade['percentile']:.0%}")
    k[3].metric("Half-life", f"{trade['half_life']:.1f}d" if trade["half_life"] else "N/A")
    k[4].metric("Carry + roll", _fmt_bp(trade["net_carry_roll_bp"]))
    k[5].metric("Residual DV01", _fmt_money(trade["residual_dv01"]))
    k[6].metric("Setup quality", f"{trade['quality_score']:.0f}/100")
    hist = trade["history"]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hist["date"], y=hist["spread_bp"], mode="lines", name="Spread"))
    mean = hist["spread_bp"].rolling(window).mean()
    std = hist["spread_bp"].rolling(window).std()
    fig.add_trace(go.Scatter(x=hist["date"], y=mean, mode="lines", name="Rolling mean"))
    fig.add_trace(go.Scatter(x=hist["date"], y=mean+2*std, mode="lines", name="+2σ", line={"dash":"dot"}))
    fig.add_trace(go.Scatter(x=hist["date"], y=mean-2*std, mode="lines", name="-2σ", line={"dash":"dot"}))
    fig.update_layout(template="plotly_dark", height=430, title="Curve-spread valuation envelope", yaxis_title="bp", hovermode="x unified")
    st.plotly_chart(fig, width="stretch")
    l, r = st.columns([1.2, 1.0])
    with l:
        st.markdown("#### Proposed DV01-neutral ticket")
        st.dataframe(trade["ticket"], width="stretch", hide_index=True)
        st.caption(f"Gross notional {_fmt_money(trade['gross_notional'])}. Mechanical mean-reversion construction; execution instruments, CTD, conversion factors and funding must be supplied for production use.")
    with r:
        st.markdown("#### Spread-shock P&L")
        st.dataframe(trade["scenarios"], width="stretch", hide_index=True)


def _fic_render_inflation_v2() -> None:
    _fic_section("Inflation Compensation & Real-Rate Regime")
    years = st.selectbox("History", [2,5,10,20], index=2, key="fic2_inf_years")
    start = _start_date_for_years(years)
    nominal, real, inflation = _cached_us_curve(start), _cached_us_real(start), _cached_inflation(start)
    regime = _fic_inflation_regime(inflation.frame)
    k = st.columns(6)
    k[0].metric("5Y BE", f"{_fic_last_non_null(inflation.frame,'5Y Breakeven'):.2f}%" if _fic_last_non_null(inflation.frame,"5Y Breakeven") is not None else "N/A", _fmt_bp(_fic_change(inflation.frame,"5Y Breakeven",21,100.0)))
    k[1].metric("10Y BE", f"{_fic_last_non_null(inflation.frame,'10Y Breakeven'):.2f}%" if _fic_last_non_null(inflation.frame,"10Y Breakeven") is not None else "N/A", _fmt_bp(_fic_change(inflation.frame,"10Y Breakeven",21,100.0)))
    k[2].metric("5Y5Y", f"{_fic_last_non_null(inflation.frame,'5Y5Y Forward Inflation'):.2f}%" if _fic_last_non_null(inflation.frame,"5Y5Y Forward Inflation") is not None else "N/A")
    k[3].metric("5Y real", f"{_fic_last_non_null(real.frame,'5Y'):.2f}%" if _fic_last_non_null(real.frame,"5Y") is not None else "N/A")
    k[4].metric("10Y real", f"{_fic_last_non_null(real.frame,'10Y'):.2f}%" if _fic_last_non_null(real.frame,"10Y") is not None else "N/A")
    k[5].metric("Inflation regime", regime["label"], f"Pressure {regime['score']:.0f}/100")
    if inflation.ok:
        st.plotly_chart(_line_chart(inflation.frame, [c for c in inflation.frame.columns if c != "date"], "Market inflation compensation", "%"), width="stretch")
    if nominal.ok and real.ok and "10Y" in nominal.frame.columns and "10Y" in real.frame.columns:
        merged = pd.merge(nominal.frame[["date","10Y"]], real.frame[["date","10Y"]], on="date", suffixes=("_nominal","_real"))
        merged["Nominal minus real 10Y"] = merged["10Y_nominal"] - merged["10Y_real"]
        if inflation.ok and "10Y Breakeven" in inflation.frame.columns:
            merged = pd.merge(merged, inflation.frame[["date","10Y Breakeven"]], on="date", how="left")
            merged["Cross-check residual"] = merged["Nominal minus real 10Y"] - merged["10Y Breakeven"]
        st.plotly_chart(_line_chart(merged, [c for c in ["Nominal minus real 10Y","10Y Breakeven","Cross-check residual"] if c in merged.columns], "Nominal-real decomposition and methodology residual", "%"), width="stretch")
    st.markdown("<div class='fic2-method'>Breakeven inflation is compensation embedded in nominal versus inflation-linked pricing. It is not a pure survey expectation and can incorporate liquidity, indexation and inflation-risk premia.</div>", unsafe_allow_html=True)


def _fic_render_futures_v2() -> None:
    _fic_section("Futures, ETF Proxies & Duration-Normalized Volatility")
    universe = ["ZT=F","ZF=F","ZN=F","ZB=F","UB=F","SHY","IEF","TLT","TIP","LQD","HYG","EMB"]
    selected = st.multiselect("Market proxies", universe, default=["ZN=F","ZB=F","TLT","LQD","HYG"], key="fic2_proxy_symbols")
    period = st.selectbox("Period", ["6mo","1y","2y","5y","10y"], index=2, key="fic2_proxy_period")
    if not selected:
        st.info("Select at least one instrument.")
        return
    result = _cached_market_proxies(tuple(selected), period)
    _show_result_status(result, compact=False)
    if not result.ok:
        return
    prices = result.frame.sort_values("date").copy()
    normalized = prices[["date"]].copy()
    returns = pd.DataFrame(index=prices.index)
    duration_proxy = {"ZT=F":1.9,"ZF=F":4.5,"ZN=F":7.5,"ZB=F":15.5,"UB=F":19.0,"SHY":1.8,"IEF":7.2,"TLT":16.0,"TIP":6.7,"LQD":8.2,"HYG":3.7,"EMB":6.8}
    metrics=[]
    for symbol in selected:
        s = pd.to_numeric(prices.get(symbol), errors="coerce")
        valid = s.dropna()
        if valid.empty:
            continue
        normalized[symbol] = s / valid.iloc[0] * 100.0
        ret = s.pct_change()
        returns[symbol] = ret
        vol = ret.std() * np.sqrt(252)
        dur = duration_proxy.get(symbol, np.nan)
        metrics.append({"symbol":symbol,"annualized_vol":vol,"duration_proxy":dur,"vol_per_duration":vol/dur if pd.notna(dur) and dur else np.nan,"1M_return":valid.iloc[-1]/valid.iloc[-22]-1 if len(valid)>21 else np.nan,"max_drawdown":(s/s.cummax()-1).min()})
    st.plotly_chart(_line_chart(normalized, [c for c in selected if c in normalized.columns], "Normalized fixed-income market proxies", "Index = 100"), width="stretch")
    st.dataframe(pd.DataFrame(metrics), width="stretch", hide_index=True)
    corr = returns.corr()
    c1,c2=st.columns(2)
    with c1:
        fig=go.Figure(go.Heatmap(z=corr.values,x=corr.columns,y=corr.index,zmin=-1,zmax=1,zmid=0,colorscale="RdBu_r",colorbar_title="Corr"))
        fig.update_layout(template="plotly_dark",height=430,title="Static return correlation")
        st.plotly_chart(fig,width="stretch")
    with c2:
        if len(selected)>=2:
            a,b=selected[0],selected[1]
            rc=returns[a].rolling(63).corr(returns[b])
            rcdf=pd.DataFrame({"date":prices["date"],f"63D corr {a}/{b}":rc})
            st.plotly_chart(_line_chart(rcdf,[f"63D corr {a}/{b}"],"Rolling correlation","Correlation"),width="stretch")
    st.markdown("<div class='fic2-method'>Yahoo instruments are labelled market proxies. Production futures analytics still require deliverable baskets, conversion factors, CTD, implied repo, exchange open interest and executable transaction costs.</div>",unsafe_allow_html=True)


def _fic_auction_bucket(term: Any, security_type: Any) -> str:
    t=str(term or "").lower(); typ=str(security_type or "").lower()
    if "bill" in typ or "week" in t or "day" in t:
        return "Bills"
    years=[]
    m=re.search(r"(\d+)\s*-?year",t)
    if m: years=[int(m.group(1))]
    y=years[0] if years else None
    if y is None: return "Other"
    if y<=3:return "2-3Y Notes"
    if y<=7:return "5-7Y Notes"
    if y<=12:return "10Y Notes"
    if y<=22:return "20Y Bonds"
    return "30Y Bonds"


def _fic_render_auctions_v2() -> None:
    _fic_section("Treasury Auctions, Demand & Duration Supply")
    c1,c2,c3=st.columns([1,1,1])
    start=c1.date_input("Start date",value=(pd.Timestamp.today()-pd.DateOffset(years=2)).date(),key="fic2_auc_start")
    end=c2.date_input("End date",value=pd.Timestamp.today().date(),key="fic2_auc_end")
    include_bills=c3.toggle("Include Treasury bills",value=False,key="fic2_auc_bills")
    result=_cached_auctions(str(start),str(end)); _show_result_status(result,compact=False)
    if not result.ok:return
    df=result.frame.copy()
    if "auction_date" in df.columns:df["auction_date"]=pd.to_datetime(df["auction_date"],errors="coerce")
    bid_col=next((c for c in ["bid_to_cover_ratio","bid_to_cover"] if c in df.columns),None)
    amt_col=next((c for c in ["offering_amt","total_accepted","offering_amount"] if c in df.columns),None)
    sec_type="security_type" if "security_type" in df.columns else None
    term_col="security_term" if "security_term" in df.columns else None
    df["bucket"]=[_fic_auction_bucket(t,typ) for t,typ in zip(df[term_col] if term_col else [""]*len(df),df[sec_type] if sec_type else [""]*len(df))]
    filtered=df if include_bills else df[df["bucket"]!="Bills"]
    k=st.columns(6)
    k[0].metric("Auctions",f"{len(filtered):,}")
    k[1].metric("Latest",pd.Timestamp(filtered["auction_date"].max()).strftime("%Y-%m-%d") if not filtered.empty and "auction_date" in filtered.columns else "N/A")
    k[2].metric("Median bid/cover",_fmt_num(filtered[bid_col].median()) if bid_col else "N/A")
    k[3].metric("Demand volatility",_fmt_num(filtered[bid_col].std()) if bid_col else "N/A")
    k[4].metric("Gross offering",_fmt_money(filtered[amt_col].sum()) if amt_col else "N/A")
    reopen_col="reopening" if "reopening" in filtered.columns else None
    reopen_count=int(filtered[reopen_col].astype(str).str.lower().isin(["yes","true","1"]).sum()) if reopen_col else 0
    k[5].metric("Reopenings",str(reopen_count))
    if amt_col:
        supply=filtered.groupby("bucket",dropna=False)[amt_col].sum().sort_values(ascending=False).reset_index()
        fig=go.Figure(go.Bar(x=supply["bucket"],y=supply[amt_col],name="Offering"))
        fig.update_layout(template="plotly_dark",height=410,title="Supply by economic maturity bucket",yaxis_title="Amount")
        st.plotly_chart(fig,width="stretch")
    if bid_col and "auction_date" in filtered.columns:
        chart=filtered.dropna(subset=[bid_col]).sort_values("auction_date").copy()
        chart["bid_cover_z"]=(chart[bid_col]-chart[bid_col].rolling(60,min_periods=20).mean())/chart[bid_col].rolling(60,min_periods=20).std()
        c1,c2=st.columns(2)
        with c1:st.plotly_chart(_line_chart(chart.rename(columns={"auction_date":"date",bid_col:"Bid-to-cover"}),["Bid-to-cover"],"Auction demand","Ratio"),width="stretch")
        with c2:st.plotly_chart(_line_chart(chart.rename(columns={"auction_date":"date"}),["bid_cover_z"],"Demand normalization","Z-score"),width="stretch")
    preferred=[c for c in ["auction_date","issue_date","maturity_date",sec_type,term_col,"bucket",reopen_col,"cusip",amt_col,bid_col,"high_yield","high_rate","direct_bidder_accepted","indirect_bidder_accepted","primary_dealer_accepted"] if c and c in filtered.columns]
    st.dataframe(filtered[preferred].sort_values("auction_date",ascending=False).head(500),width="stretch",hide_index=True)
    _download_csv_button(filtered,"treasury_auction_supply_v2.csv","fic2_auc_download")


def _fic_render_credit_monitor_v2() -> None:
    _fic_section("Credit Market Monitor & Implied Default Risk")
    years=st.selectbox("History",[2,5,10,20],index=2,key="fic2_credit_years")
    recovery=st.slider("Recovery assumption",0.0,0.8,0.40,0.05,key="fic2_credit_recovery")
    result=_result_or_demo(_cached_credit(_start_date_for_years(years)),"credit"); _show_result_status(result,compact=False)
    if not result.ok:return
    regime=_fic_credit_regime_v2(result.frame)
    dashboard=credit_index_dashboard(result.frame)
    if dashboard.empty:return
    dashboard=dashboard.copy()
    dashboard["hazard_rate"] = dashboard["oas_bp"].map(lambda x: hazard_rate_from_spread(x,recovery) if pd.notna(x) else np.nan)
    dashboard["5Y_default_probability"] = dashboard["hazard_rate"].map(lambda x: cumulative_default_probability(x,5) if pd.notna(x) else np.nan)
    k=st.columns(6)
    for i,col in enumerate(["US IG OAS","US BBB OAS","US HY OAS","US BB OAS","US B OAS"]):
        val=_fic_last_non_null(result.frame,col)
        k[i].metric(col.replace("US ",""),f"{val:.0f} bp" if val is not None else "N/A",_fmt_bp(_fic_change(result.frame,col,21)))
    k[5].metric("Credit regime",regime["label"],f"Stress {regime['score']:.0f}/100")
    st.dataframe(dashboard,width="stretch",hide_index=True)
    fig=go.Figure()
    for col in [c for c in CREDIT_OAS_SERIES if c in result.frame.columns]:
        fig.add_trace(go.Scatter(x=result.frame["date"],y=result.frame[col],mode="lines",name=col))
    fig.update_layout(template="plotly_dark",height=470,title="Credit OAS term and quality complex",yaxis_title="bp",hovermode="x unified")
    st.plotly_chart(fig,width="stretch")
    if all(c in result.frame.columns for c in ["US HY OAS","US IG OAS"]):
        diff=pd.DataFrame({"date":result.frame["date"],"HY-IG differential":result.frame["US HY OAS"]-result.frame["US IG OAS"]})
        st.plotly_chart(_line_chart(diff,["HY-IG differential"],"Credit beta differential","bp"),width="stretch")
    diagnostics = credit_market_diagnostics(result.frame)
    if diagnostics.get("available"):
        st.markdown("#### Breadth, beta & cross-quality dependence")
        d = st.columns(5)
        d[0].metric("Widening breadth", f"{diagnostics['widening_breadth']:.0%}")
        d[1].metric("HY / IG beta", _fmt_num(diagnostics["hy_ig_beta"]))
        d[2].metric("HY-IG corr 60D", _fmt_num(diagnostics["hy_ig_corr_60d"]))
        d[3].metric("HY-IG corr 1Y", _fmt_num(diagnostics["hy_ig_corr_252d"]))
        d[4].metric("Quality dispersion", _fmt_bp(diagnostics["cross_quality_dispersion_bp"]))
        left, right = st.columns([0.75, 1.25])
        with left:
            st.dataframe(diagnostics["one_month_changes"], width="stretch", hide_index=True)
        with right:
            corr = diagnostics["change_correlation"]
            heatmap = go.Figure(go.Heatmap(z=corr.to_numpy(), x=corr.columns.tolist(), y=corr.index.tolist(), zmin=-1, zmax=1, zmid=0, colorscale="RdBu", colorbar_title="ρ"))
            heatmap.update_layout(template="plotly_dark", height=390, title="Daily OAS-change correlation")
            st.plotly_chart(heatmap, width="stretch")
    st.markdown("<div class='fic2-method'>Hazard and default probabilities use a constant-hazard, constant-recovery approximation. They are screening measures, not calibrated CDS survival curves.</div>",unsafe_allow_html=True)


def _fic_render_factor_risk_v2() -> None:
    _fic_section("Portfolio Factor Risk")
    portfolio=normalize_portfolio(_portfolio_state()); summary=portfolio_summary(portfolio)
    if not summary.get("available") or summary.get("market_value",0)==0:
        st.info("Populate the portfolio in Portfolio Analytics first.");return
    positions=summary["positions"].copy()
    bins=[-np.inf,1,3,5,7,10,20,np.inf]; labels=["0-1Y","1-3Y","3-5Y","5-7Y","7-10Y","10-20Y","20Y+"]
    positions["key_rate_bucket"]=pd.cut(positions["maturity_years"],bins=bins,labels=labels)
    krd=positions.groupby("key_rate_bucket",observed=False)[["dv01","market_value"]].sum().reset_index()
    cs=positions.groupby("rating",dropna=False)[["cs01","market_value"]].sum().reset_index().sort_values("cs01",ascending=False)
    fx=positions.groupby("currency",dropna=False)["market_value"].sum().reset_index()
    k=st.columns(7)
    k[0].metric("Net MV",_fmt_money(summary["market_value"]))
    k[1].metric("Gross MV",_fmt_money(summary["gross_market_value"]))
    k[2].metric("DV01",_fmt_money(summary["dv01"]))
    k[3].metric("CS01",_fmt_money(summary["cs01"]))
    k[4].metric("Duration",_fmt_num(summary["duration"]))
    k[5].metric("Spread duration",_fmt_num(summary["spread_duration"]))
    gross_net=summary["gross_market_value"]/abs(summary["market_value"]) if summary["market_value"] else np.nan
    k[6].metric("Gross / net",_fmt_num(gross_net))
    c1,c2,c3=st.columns(3)
    with c1:st.markdown("#### Key-rate DV01 proxy");st.dataframe(krd,width="stretch",hide_index=True)
    with c2:st.markdown("#### Credit CS01 by rating");st.dataframe(cs,width="stretch",hide_index=True)
    with c3:st.markdown("#### Currency market value");st.dataframe(fx,width="stretch",hide_index=True)
    a,b,c=st.columns(3)
    vol=a.number_input("Annual portfolio vol",min_value=0.0,max_value=1.0,value=0.06,step=0.005,key="fic2_factor_vol")
    conf=b.selectbox("Confidence",[0.95,0.975,0.99],index=1,key="fic2_factor_conf")
    horizon=c.selectbox("Horizon",[1,5,10,20],index=2,key="fic2_factor_horizon")
    risk=parametric_var_es(summary["market_value"],vol,conf,horizon)
    x,y=st.columns(2);x.metric("Parametric VaR",_fmt_money(risk["var"]));y.metric("Parametric ES",_fmt_money(risk["expected_shortfall"]))


def _fic_render_stress_v2() -> None:
    _fic_section("Stress Testing & Loss Attribution")
    portfolio=normalize_portfolio(_portfolio_state()); summary=portfolio_summary(portfolio)
    if not summary.get("available") or summary.get("market_value",0)==0:
        st.info("Populate the portfolio first.");return
    matrix=run_scenario_matrix(portfolio)
    if matrix.empty:return
    matrix["loss_pct_nav"]=matrix["total_pnl"]/abs(summary["market_value"])
    worst=matrix.sort_values("total_pnl").iloc[0]
    k=st.columns(4);k[0].metric("Worst scenario",str(worst["scenario"]));k[1].metric("Worst P&L",_fmt_money(worst["total_pnl"]));k[2].metric("Loss / NAV",_fmt_pct(worst["loss_pct_nav"]));k[3].metric("Scenarios",str(len(matrix)))
    fig=go.Figure()
    for col,name in [("rate_pnl","Rates"),("spread_pnl","Spread"),("fx_pnl","FX"),("liquidity_pnl","Liquidity")]:
        fig.add_trace(go.Bar(x=matrix["scenario"],y=matrix[col],name=name))
    fig.update_layout(template="plotly_dark",height=470,barmode="relative",title="Scenario loss decomposition",xaxis_tickangle=-25)
    st.plotly_chart(fig,width="stretch")
    st.dataframe(matrix,width="stretch",hide_index=True)
    selected=st.selectbox("Position attribution scenario",matrix["scenario"].tolist(),key="fic2_stress_scenario")
    scenario_lookup={x.name:x for x in DEFAULT_SCENARIOS}
    scenario=scenario_lookup.get(selected)
    if scenario:
        detailed=scenario_pnl(portfolio,scenario)
        if detailed.get("available"):
            pos=detailed["positions"].sort_values("total_pnl")
            st.dataframe(pos,width="stretch",hide_index=True)


def _fic_render_hedge_optimizer_v2() -> None:
    _fic_section("DV01 / CS01 Hedge Optimizer")
    portfolio=normalize_portfolio(_portfolio_state()); summary=portfolio_summary(portfolio)
    if not summary.get("available") or summary.get("market_value",0)==0:
        st.info("Populate the portfolio first.");return
    c1,c2,c3=st.columns(3)
    target_dv01=c1.number_input("Target residual DV01",value=0.0,step=100.0,key="fic2_hedge_target_dv01")
    target_cs01=c2.number_input("Target residual CS01",value=0.0,step=100.0,key="fic2_hedge_target_cs01")
    max_notional=c3.number_input("Max absolute notional",min_value=100_000.0,max_value=10_000_000_000.0,value=100_000_000.0,step=1_000_000.0,key="fic2_hedge_max")
    hedge_table=pd.DataFrame([
        {"hedge":"2Y Treasury proxy","dv01_per_1m":185.0,"cs01_per_1m":0.0},
        {"hedge":"5Y Treasury proxy","dv01_per_1m":445.0,"cs01_per_1m":0.0},
        {"hedge":"10Y Treasury proxy","dv01_per_1m":750.0,"cs01_per_1m":0.0},
        {"hedge":"30Y Treasury proxy","dv01_per_1m":1550.0,"cs01_per_1m":0.0},
        {"hedge":"LQD credit proxy","dv01_per_1m":820.0,"cs01_per_1m":800.0},
        {"hedge":"HYG credit proxy","dv01_per_1m":370.0,"cs01_per_1m":350.0},
    ])
    edited=st.data_editor(hedge_table,width="stretch",key="fic2_hedge_editor")
    target=np.array([summary["dv01"]-target_dv01,summary["cs01"]-target_cs01],dtype=float)
    matrix=np.vstack([pd.to_numeric(edited["dv01_per_1m"],errors="coerce").fillna(0).to_numpy(),pd.to_numeric(edited["cs01_per_1m"],errors="coerce").fillna(0).to_numpy()])
    notionals_m=np.linalg.lstsq(matrix,-target,rcond=None)[0]
    notionals=np.clip(notionals_m*1_000_000.0,-max_notional,max_notional)
    contributions=matrix*(notionals/1_000_000.0)
    residual=target+contributions.sum(axis=1)
    out=edited.copy();out["recommended_notional"]=notionals;out["dv01_contribution"]=contributions[0];out["cs01_contribution"]=contributions[1]
    k=st.columns(4);k[0].metric("Current DV01",_fmt_money(summary["dv01"]));k[1].metric("Current CS01",_fmt_money(summary["cs01"]));k[2].metric("Residual DV01",_fmt_money(residual[0]));k[3].metric("Residual CS01",_fmt_money(residual[1]))
    st.dataframe(out,width="stretch",hide_index=True)
    st.caption("Sensitivities are editable contract/proxy inputs. Replace defaults with actual CTD-adjusted futures DV01 or instrument-level risk before execution.")


def _fic_render_strategy_v2() -> None:
    _fic_section("Strategy Validation — In/Out of Sample")
    _,result=_select_curve_result();_show_result_status(result)
    if not result.ok:return
    frame=normalize_curve_history(result.frame);tenors=[c for c in frame.columns if c!="date"]
    c1,c2,c3,c4,c5=st.columns(5)
    short=c1.selectbox("Short tenor",tenors,index=min(4,len(tenors)-1),key="fic2_strat_short")
    long=c2.selectbox("Long tenor",tenors,index=min(8,len(tenors)-1),key="fic2_strat_long")
    entry=c3.selectbox("Entry z",[0.75,1.0,1.25,1.5,2.0,2.5],index=3,key="fic2_strat_entry")
    exit_z=c4.selectbox("Exit z",[0.0,0.25,0.5,0.75],index=1,key="fic2_strat_exit")
    cost=c5.number_input("Round-turn cost (bp)",min_value=0.0,max_value=50.0,value=1.0,step=0.25,key="fic2_strat_cost")
    spread=(frame[long]-frame[short])*100.0;spread.index=frame["date"]
    split=max(300,int(len(spread)*0.70))
    full=backtest_zscore_strategy(spread,entry_z=entry,exit_z=exit_z,cost_bp=cost,window=252)
    ins=backtest_zscore_strategy(spread.iloc[:split],entry_z=entry,exit_z=exit_z,cost_bp=cost,window=min(252,max(63,split//3)))
    oos=backtest_zscore_strategy(spread.iloc[split:],entry_z=entry,exit_z=exit_z,cost_bp=cost,window=min(126,max(42,len(spread.iloc[split:])//3)))
    if not full.get("available"):st.error("Backtest unavailable");return
    fm=full["metrics"];im=ins.get("metrics",{});om=oos.get("metrics",{})
    k=st.columns(7)
    k[0].metric("Full Sharpe",_fmt_num(fm.get("sharpe")));k[1].metric("IS Sharpe",_fmt_num(im.get("sharpe")));k[2].metric("OOS Sharpe",_fmt_num(om.get("sharpe")));k[3].metric("Max DD",_fmt_num(fm.get("max_drawdown"),4));k[4].metric("Turnover",_fmt_num(fm.get("turnover"),1));k[5].metric("Half-life",f"{fm.get('half_life'):.1f}d" if fm.get("half_life") else "N/A");k[6].metric("OOS stability","PASS" if (om.get("sharpe") or -99)>0 and (im.get("sharpe") or 0)*(om.get("sharpe") or 0)>=0 else "FAIL")
    bt=full["frame"].reset_index().rename(columns={"index":"date"})
    st.plotly_chart(_line_chart(bt,["equity"],"Strategy cumulative P&L","P&L"),width="stretch")
    robust=[]
    for e in [1.0,1.25,1.5,2.0,2.5]:
        for w in [63,126,252,504]:
            r=backtest_zscore_strategy(spread,entry_z=e,exit_z=exit_z,cost_bp=cost,window=w)
            robust.append({"entry_z":e,"window":w,"sharpe":r.get("metrics",{}).get("sharpe"),"max_drawdown":r.get("metrics",{}).get("max_drawdown"),"turnover":r.get("metrics",{}).get("turnover")})
    st.markdown("#### Parameter robustness grid")
    st.dataframe(pd.DataFrame(robust),width="stretch",hide_index=True)
    st.warning("Research output only. Futures delivery options, CTD switches, financing, publication lags and executable bid/ask quotes are not inferred unless explicitly supplied.")


def _fic_render_cds_curve_v3() -> None:
    _fic_section("CDS Curve, Survival & Bond Basis")
    st.caption("Bootstrap a tenor-by-tenor survival curve, reconcile CDS quotes and decompose the cash-bond/CDS basis.")
    controls = st.columns(4)
    recovery = controls[0].slider("Recovery rate", 0.0, 0.80, 0.40, 0.01, key="fic3_cds_recovery")
    zero_rate_pct = controls[1].number_input("Flat zero rate (%)", -2.0, 20.0, 4.0, 0.10, key="fic3_cds_zero")
    frequency = controls[2].selectbox("Premium frequency", [1, 2, 4], index=2, key="fic3_cds_frequency")
    basis_tenor = controls[3].selectbox("Basis tenor", [1, 2, 3, 5, 7, 10], index=3, key="fic3_cds_basis_tenor")
    default_quotes = pd.DataFrame({"tenor_years": [1, 2, 3, 5, 7, 10], "par_spread_bp": [78.0, 91.0, 108.0, 137.0, 158.0, 181.0]})
    quotes = st.data_editor(default_quotes, num_rows="dynamic", width="stretch", hide_index=True, key="fic3_cds_quotes")
    try:
        calibration = calibrate_cds_hazard_curve(
            quotes["tenor_years"], quotes["par_spread_bp"], recovery, zero_rate_pct / 100.0, frequency
        )
    except Exception as exc:
        st.error(f"CDS calibration error: {exc}")
        return
    forward = cds_forward_default_table(calibration)
    maximum_error = calibration["calibration_residual_bp"].abs().max()
    kpis = st.columns(5)
    kpis[0].metric("5Y cumulative PD", f"{np.interp(5.0, calibration['tenor_years'], calibration['cumulative_default_probability_pct']):.2f}%")
    kpis[1].metric("10Y survival", f"{np.interp(10.0, calibration['tenor_years'], calibration['survival_probability_pct']):.2f}%")
    kpis[2].metric("Terminal hazard", f"{calibration['hazard_rate_pct'].iloc[-1]:.2f}%")
    kpis[3].metric("Max calibration error", f"{maximum_error:.4f} bp")
    kpis[4].metric("Calibration", "PASS" if maximum_error < 0.05 else "REVIEW")
    chart = go.Figure()
    chart.add_trace(go.Scatter(x=calibration["tenor_years"], y=calibration["market_spread_bp"], name="Market CDS", mode="lines+markers"))
    chart.add_trace(go.Scatter(x=calibration["tenor_years"], y=calibration["model_spread_bp"], name="Model CDS", mode="lines+markers", line={"dash": "dot"}))
    chart.update_layout(template="plotly_dark", height=420, title="Par CDS fit", xaxis_title="Years", yaxis_title="bp", hovermode="x unified")
    st.plotly_chart(chart, width="stretch")
    left, right = st.columns([1.25, 1.0])
    with left:
        st.markdown("#### Calibrated credit term structure")
        st.dataframe(calibration, width="stretch", hide_index=True)
    with right:
        st.markdown("#### Forward default profile")
        st.dataframe(forward, width="stretch", hide_index=True)
    st.markdown("#### Cash bond / CDS basis")
    basis_inputs = st.columns(4)
    bond_spread = basis_inputs[0].number_input("Bond OAS (bp)", -500.0, 5000.0, 165.0, 1.0, key="fic3_basis_bond")
    curve_cds = float(np.interp(float(basis_tenor), calibration["tenor_years"], calibration["model_spread_bp"]))
    cds_spread = basis_inputs[1].number_input("CDS spread (bp)", -100.0, 5000.0, curve_cds, 1.0, key="fic3_basis_cds")
    bid_ask = basis_inputs[2].number_input("Bond bid/ask (bp)", 0.0, 500.0, 6.0, 0.5, key="fic3_basis_bidask")
    funding_basis = basis_inputs[3].number_input("Funding / repo adjustment (bp)", -500.0, 500.0, 0.0, 0.5, key="fic3_basis_funding")
    basis = bond_cds_basis(bond_spread, cds_spread, bid_ask, funding_basis)
    bcols = st.columns(4)
    bcols[0].metric("Raw basis", _fmt_bp(basis["raw_basis_bp"]))
    bcols[1].metric("Liquidity charge", _fmt_bp(basis["liquidity_charge_bp"]))
    bcols[2].metric("Funding adjustment", _fmt_bp(basis["funding_basis_bp"]))
    bcols[3].metric("Adjusted basis", _fmt_bp(basis["liquidity_funding_adjusted_basis_bp"]))
    st.markdown("#### Standard-coupon CDS economics")
    contract_inputs = st.columns(4)
    contract_notional = contract_inputs[0].number_input("CDS notional", 1.0, 10_000_000_000.0, 10_000_000.0, 100_000.0, key="fic5_cds_notional")
    standard_coupon = contract_inputs[1].selectbox("Standard coupon (bp)", [100.0, 500.0], key="fic5_cds_coupon")
    protection_side = contract_inputs[2].selectbox("Protection side", ["Buy protection", "Sell protection"], key="fic5_cds_side")
    contract_maturity = contract_inputs[3].selectbox("Contract maturity", calibration["tenor_years"].tolist(), index=min(3, len(calibration) - 1), key="fic5_cds_maturity")
    contract = cds_standard_coupon_metrics(calibration, contract_maturity, standard_coupon, contract_notional, recovery, zero_rate_pct / 100.0, frequency, protection_side)
    c = st.columns(6)
    c[0].metric("Par spread", f"{contract['par_spread_bp']:.1f} bp")
    c[1].metric("Clean upfront", f"{contract['clean_upfront_pct']:.3f}%")
    c[2].metric("MTM", _fmt_money(contract["mark_to_market"]))
    c[3].metric("CS01", _fmt_money(contract["cs01"]))
    c[4].metric("Jump-to-default", _fmt_money(contract["jump_to_default"]))
    c[5].metric("Cumulative PD", f"{contract['cumulative_default_probability_pct']:.2f}%")
    scenario_chart = go.Figure(go.Bar(x=contract["scenario"]["spread_shock_bp"], y=contract["scenario"]["approx_mtm_change"], marker_color=np.where(contract["scenario"]["approx_mtm_change"] >= 0, "#58e6ad", "#ff7272")))
    scenario_chart.update_layout(template="plotly_dark", height=330, title="Approximate CDS MTM sensitivity", xaxis_title="Spread shock (bp)", yaxis_title="P&L")
    st.plotly_chart(scenario_chart, width="stretch")
    _download_csv_button(calibration, "cds_hazard_curve.csv", "fic3_cds_download")
    st.markdown("<div class='fic2-method'>Screening implementation: piecewise-constant hazard, quarterly premium, midpoint accrual-on-default and risky-annuity upfront approximation. It is not a certified ISDA Standard Model and does not infer restructuring clauses, calendars, step-in dates, accrued settlement or executable quotes.</div>", unsafe_allow_html=True)


def _fic_render_migration_var_v3() -> None:
    _fic_section("Rating Migration & Credit VaR")
    st.caption("Correlated one-factor migration simulation with mark-to-spread revaluation, default LGD and tail-risk attribution.")
    portfolio = normalize_portfolio(_portfolio_state())
    if portfolio.empty or portfolio["market_value"].fillna(0).abs().sum() == 0:
        st.info("Load holdings in Portfolio Analytics first. Use the explicit demo button there if you want a labelled example.")
    inputs = st.columns(5)
    initial_rating = inputs[0].selectbox("Distribution from", RATING_STATES[:-1], index=3, key="fic3_migration_rating")
    years = inputs[1].selectbox("Horizon (years)", [1, 2, 3, 5], key="fic3_migration_years")
    confidence = inputs[2].selectbox("VaR confidence", [0.95, 0.975, 0.99, 0.995], index=2, key="fic3_migration_conf")
    correlation = inputs[3].slider("Asset correlation", 0.0, 0.75, 0.20, 0.05, key="fic3_migration_corr")
    simulations = inputs[4].selectbox("Simulations", [2000, 5000, 10000, 25000], index=2, key="fic3_migration_sims")
    with st.expander("Transition matrix — editable illustrative input", expanded=False):
        matrix_pct = st.data_editor(ILLUSTRATIVE_TRANSITION_MATRIX, width="stretch", key="fic3_transition_matrix")
        st.warning("ILLUSTRATIVE MATRIX — replace with a licensed, governed and dated agency/internal matrix before production use.")
    try:
        matrix = validate_transition_matrix(matrix_pct)
        distribution = migration_distribution(initial_rating, matrix, years)
    except Exception as exc:
        st.error(f"Transition matrix error: {exc}")
        return
    distribution_table = distribution.mul(100).rename("probability_pct").reset_index().rename(columns={"index": "terminal_rating"})
    st.markdown(f"#### {years}Y migration distribution from {initial_rating}")
    st.dataframe(distribution_table, width="stretch", hide_index=True)
    if portfolio.empty or portfolio["market_value"].fillna(0).abs().sum() == 0:
        return
    try:
        result = credit_migration_var(portfolio, matrix, simulations, confidence, correlation, seed=42)
    except Exception as exc:
        st.error(f"Credit migration simulation error: {exc}")
        return
    if not result.get("available"):
        st.warning(result.get("reason", "Credit VaR unavailable"))
        return
    kpis = st.columns(6)
    kpis[0].metric("Credit VaR", _fmt_money(result["credit_var"]))
    kpis[1].metric("Expected Shortfall", _fmt_money(result["expected_shortfall"]))
    kpis[2].metric("Expected default loss", _fmt_money(result["expected_default_loss"]))
    kpis[3].metric("Unexpected loss", _fmt_money(result["unexpected_loss"]))
    kpis[4].metric("Correlation", f"{100 * result['asset_correlation']:.0f}%")
    kpis[5].metric("Scenarios", f"{result['simulations']:,}")
    histogram = go.Figure(go.Histogram(x=result["loss_distribution"], nbinsx=80, marker_color="#5be7ff"))
    histogram.add_vline(x=result["credit_var"], line_color="#f2c96d", annotation_text="VaR")
    histogram.add_vline(x=result["expected_shortfall"], line_color="#ff6b7d", annotation_text="ES")
    histogram.update_layout(template="plotly_dark", height=400, title="Simulated one-year credit loss distribution", xaxis_title="Loss")
    st.plotly_chart(histogram, width="stretch")
    st.dataframe(result["position_expected_loss"], width="stretch", hide_index=True)
    st.markdown("<div class='fic2-method'>CreditMetrics-style screening model. Results depend materially on the transition matrix, rating spread levels, recovery and single-factor dependence. Validate against the desk's approved migration and valuation engine.</div>", unsafe_allow_html=True)


def _fic_render_irrbb_v3() -> None:
    _fic_section("Basel IRRBB — Economic Value of Equity")
    st.caption("Six supervisory curve shocks with currency-specific calibration and position-level duration/convexity attribution.")
    portfolio = normalize_portfolio(_portfolio_state())
    capital = st.number_input("Tier 1 capital", min_value=0.0, value=100_000_000.0, step=1_000_000.0, key="fic3_irrbb_capital")
    if portfolio.empty or portfolio["market_value"].fillna(0).abs().sum() == 0:
        st.info("Populate Portfolio Analytics first; currency, maturity, market value, duration and convexity are required.")
        return
    result = irrbb_eve_scenarios(portfolio, capital if capital > 0 else None)
    if not result.get("available"):
        st.warning(result.get("reason", "IRRBB unavailable"))
        return
    worst_ratio = result["worst_loss_pct_tier1"]
    kpis = st.columns(4)
    kpis[0].metric("Worst scenario", result["worst_scenario"])
    kpis[1].metric("Worst ΔEVE", _fmt_money(result["worst_delta_eve"]))
    kpis[2].metric("Loss / Tier 1", f"{worst_ratio:.2f}%" if np.isfinite(worst_ratio) else "N/A")
    kpis[3].metric("Supervisory screen", "REVIEW" if np.isfinite(worst_ratio) and worst_ratio > 15 else "WITHIN 15% SCREEN")
    figure = go.Figure(go.Bar(x=result["scenarios"]["scenario"], y=result["scenarios"]["delta_eve"], marker_color=np.where(result["scenarios"]["delta_eve"] < 0, "#ff6b7d", "#58e6ad")))
    figure.update_layout(template="plotly_dark", height=420, title="ΔEVE by supervisory shock", yaxis_title="Currency value")
    st.plotly_chart(figure, width="stretch")
    left, right = st.columns([0.8, 1.2])
    with left:
        st.dataframe(result["scenarios"], width="stretch", hide_index=True)
    with right:
        scenario_filter = st.selectbox("Position attribution", BASEL_IRRBB_SCENARIOS, key="fic3_irrbb_attribution")
        st.dataframe(result["positions"].query("scenario == @scenario_filter"), width="stretch", hide_index=True)
    st.markdown(f"<div class='fic2-method'>{result['scope_note']} The 15% of Tier 1 indicator is a supervisory outlier screen, not an internal risk appetite limit.</div>", unsafe_allow_html=True)


def _fic_render_liquidity_v3() -> None:
    _fic_section("Liquidity, TRACE & Exit Capacity")
    tabs = st.tabs(["Trade diagnostics", "Liquidation cost", "Data boundary"])
    with tabs[0]:
        uploaded = st.file_uploader("Upload TRACE / transaction file (CSV, XLSX, Parquet)", type=["csv", "xlsx", "xls", "parquet"], key="fic3_trace_upload")
        if uploaded is None:
            st.info("No trade file loaded. Required fields: timestamp/date, price and quantity/volume. No transactions are fabricated.")
        else:
            result = parse_uploaded_table(uploaded)
            if not result.ok:
                _show_result_status(result, compact=False)
            else:
                metrics = trace_liquidity_metrics(result.frame)
                if metrics.get("available"):
                    kpis = st.columns(6)
                    kpis[0].metric("Trades", f"{metrics['trade_count']:,}")
                    kpis[1].metric("VWAP", f"{metrics['vwap']:.4f}")
                    kpis[2].metric("Active days", f"{metrics['active_days']:,}")
                    kpis[3].metric("Zero-trade days", f"{100 * metrics['zero_trading_day_ratio']:.1f}%")
                    kpis[4].metric("Roll spread", _fmt_bp(metrics["roll_spread_bp"]))
                    kpis[5].metric("Days since trade", str(metrics["days_since_last_trade"]))
                    metric_table = pd.DataFrame([{"metric": key, "value": value} for key, value in metrics.items() if key not in {"available", "trades", "daily"}])
                    left, right = st.columns([1.15, 0.85])
                    with left:
                        daily = metrics["daily"]
                        st.plotly_chart(_line_chart(daily.rename(columns={"timestamp": "date"}), ["volume"], "Reported daily volume", "Par / quantity"), width="stretch")
                    with right:
                        st.dataframe(metric_table, width="stretch", hide_index=True)
                    st.dataframe(metrics["trades"].tail(1000), width="stretch", hide_index=True)
                    _download_csv_button(metrics["daily"], "trace_liquidity_daily.csv", "fic3_trace_download")
                else:
                    st.warning(metrics.get("reason", "No valid trades"))
    with tabs[1]:
        st.markdown("#### Capacity-aware liquidation curve")
        inputs = st.columns(5)
        position = inputs[0].number_input("Position market value", 0.0, value=10_000_000.0, step=100_000.0, key="fic3_liq_position")
        adv = inputs[1].number_input("Average daily volume", 1.0, value=5_000_000.0, step=100_000.0, key="fic3_liq_adv")
        bid_ask = inputs[2].number_input("Bid/ask (bp)", 0.0, 1000.0, 8.0, 0.5, key="fic3_liq_bidask")
        volatility = inputs[3].number_input("Spread volatility (bp)", 0.0, 1000.0, 45.0, 1.0, key="fic3_liq_vol")
        participation = inputs[4].slider("Max participation", 0.01, 1.0, 0.20, 0.01, key="fic3_liq_participation")
        curve = liquidation_cost_curve(position, adv, bid_ask, volatility, max_participation=participation)
        feasible = curve[curve["feasible"]]
        kpis = st.columns(3)
        kpis[0].metric("Minimum exit days", f"{curve['minimum_exit_days'].iloc[0]:.1f}")
        kpis[1].metric("First feasible horizon", f"{int(feasible['horizon_days'].iloc[0])}d" if not feasible.empty else ">20d")
        kpis[2].metric("First feasible cost", _fmt_money(feasible["estimated_cost"].iloc[0]) if not feasible.empty else "N/A")
        st.dataframe(curve, width="stretch", hide_index=True)
        figure = go.Figure(go.Scatter(x=curve["horizon_days"], y=curve["total_cost_bp"], mode="lines+markers", marker={"color": np.where(curve["feasible"], "#58e6ad", "#ff6b7d")}))
        figure.update_layout(template="plotly_dark", height=370, title="Estimated liquidation cost by horizon", xaxis_title="Days", yaxis_title="bp")
        st.plotly_chart(figure, width="stretch")
        st.caption("Cost = half bid/ask + square-root market impact. Calibrate ADV, volatility, participation and multiplier on internal executions before use.")
    with tabs[2]:
        status = trace_provider_status()
        _show_result_status(status, compact=False)
        st.dataframe(pd.DataFrame(status.monitor_rows()), width="stretch", hide_index=True)
        st.markdown("<div class='fic2-method'>TRACE disseminates reported transaction information; it is not a complete order book. Corrections, cancellations, dissemination caps, identifier mapping and licensed redistribution rules must be handled in production.</div>", unsafe_allow_html=True)


def _fic_render_investment_committee_v3() -> None:
    _fic_section("Investment Committee Decision Workbench")
    st.caption("A transparent, auditable synthesis of valuation, carry, credit, liquidity, stress and data confidence — never a black-box recommendation.")
    identity = st.columns(3)
    issuer = identity[0].text_input("Issuer", "Example Issuer", key="fic3_ic_issuer")
    security = identity[1].text_input("Security", "5Y senior unsecured", key="fic3_ic_security")
    analyst = identity[2].text_input("Analyst / owner", "", key="fic3_ic_analyst")
    inputs = st.columns(6)
    valuation_z = inputs[0].number_input("Valuation z-score", -5.0, 5.0, -0.75, 0.10, key="fic3_ic_value")
    carry_roll = inputs[1].number_input("12M carry + roll (bp)", -500.0, 1000.0, 35.0, 5.0, key="fic3_ic_carry")
    credit = inputs[2].slider("Credit quality", 0, 100, 72, key="fic3_ic_credit")
    liquidity = inputs[3].slider("Liquidity", 0, 100, 65, key="fic3_ic_liquidity")
    stress = inputs[4].number_input("Severe stress loss (%)", 0.0, 100.0, 8.0, 0.5, key="fic3_ic_stress")
    confidence = inputs[5].slider("Data confidence", 0, 100, 85, key="fic3_ic_confidence")
    st.markdown("#### Hard-stop guardrails")
    guards = st.columns(5)
    stops = {
        "Limit breach": guards[0].checkbox("Limit breach", key="fic3_ic_limit"),
        "Stale / missing price": guards[1].checkbox("Stale price", key="fic3_ic_stale"),
        "Legal documentation gap": guards[2].checkbox("Legal gap", key="fic3_ic_legal"),
        "Sanctions / compliance hold": guards[3].checkbox("Compliance hold", key="fic3_ic_compliance"),
        "Unhedgeable concentration": guards[4].checkbox("Concentration", key="fic3_ic_concentration"),
    }
    result = investment_committee_score(valuation_z, carry_roll, credit, liquidity, stress, confidence, stops)
    kpis = st.columns(4)
    kpis[0].metric("Decision score", f"{result['score']:.1f}/100")
    kpis[1].metric("Decision", result["decision"])
    kpis[2].metric("Max position", f"{result['max_position_pct_nav']:.2f}% NAV")
    kpis[3].metric("Hard stops", str(len(result["hard_stop_breaches"])))
    contributions = result["components"].copy()
    figure = go.Figure(go.Bar(x=contributions["dimension"], y=contributions["contribution"], marker_color="#5be7ff"))
    figure.update_layout(template="plotly_dark", height=350, title="Weighted decision contributions", yaxis_title="Score contribution")
    left, right = st.columns([1.0, 1.2])
    with left:
        st.dataframe(contributions, width="stretch", hide_index=True)
    with right:
        st.plotly_chart(figure, width="stretch")
    st.markdown("#### Committee memo")
    narrative = st.columns(2)
    thesis = narrative[0].text_area("Investment thesis", height=120, key="fic3_ic_thesis")
    catalysts = narrative[1].text_area("Catalysts", height=120, key="fic3_ic_catalysts")
    risks = narrative[0].text_area("Principal risks", height=120, key="fic3_ic_risks")
    mitigants = narrative[1].text_area("Mitigants / hedge plan", height=120, key="fic3_ic_mitigants")
    memo = investment_committee_memo(issuer, security, result, thesis, catalysts, risks, mitigants)
    if analyst:
        memo = memo.replace("# Fixed Income Investment Committee Memo", f"# Fixed Income Investment Committee Memo\n\n**Analyst / owner:** {analyst}")
    st.download_button("Download IC memo (.md)", memo, file_name="fixed_income_ic_memo.md", mime="text/markdown", key="fic3_ic_download")
    with st.expander("Memo preview"):
        st.code(memo, language="markdown")
    st.markdown("<div class='fic2-method'>Weights and thresholds are explicit and editable in code. Any hard-stop breach overrides the numerical score. Final authorization remains with the applicable investment, risk, compliance and legal governance.</div>", unsafe_allow_html=True)


def _fic_render_treasury_futures_v4() -> None:
    _fic_section("Treasury Futures — CTD, Basis & Implied Repo")
    st.caption("Delivery-basket economics, financing sensitivity and CTD-adjusted hedge ratios. Exchange conversion factors and cash inputs remain explicit.")
    top = st.columns(6)
    futures_price = top[0].number_input("Futures price", 1.0, 300.0, 110.0, 1.0 / 32.0, key="fic4_fut_price")
    settlement = top[1].date_input("Settlement", value=date.today(), key="fic4_fut_settle")
    delivery = top[2].date_input("Delivery", value=date.today() + timedelta(days=90), key="fic4_fut_delivery")
    repo = top[3].number_input("Term repo (%)", -5.0, 30.0, 4.50, 0.05, key="fic4_fut_repo")
    face = top[4].number_input("Cash face", 0.0, 10_000_000_000.0, 10_000_000.0, 100_000.0, key="fic4_fut_face")
    contract_size = top[5].number_input("Contract face", 1.0, 10_000_000.0, 100_000.0, 10_000.0, key="fic4_fut_contract")
    uploaded = st.file_uploader("Deliverable basket CSV / XLSX", type=["csv", "xlsx", "xls"], key="fic4_fut_upload")
    illustrative = st.checkbox("Load explicit illustrative basket", value=False, key="fic4_fut_demo")
    if uploaded is not None:
        parsed = parse_uploaded_table(uploaded)
        basket = parsed.frame if parsed.ok else pd.DataFrame(columns=TREASURY_FUTURES_BASKET_COLUMNS)
        _show_result_status(parsed)
    elif illustrative:
        st.warning("EXPLICIT ILLUSTRATIVE INPUTS — replace prices, accrued interest, conversion factors and DV01 before use.")
        basket = pd.DataFrame([
            {"security": "Illustrative A", "clean_price": 99.8125, "conversion_factor": 0.9012, "accrued_today": 0.35, "accrued_delivery": 0.82, "interim_coupon_per_100": 0.0, "cash_dv01_per_100k": 72.0},
            {"security": "Illustrative B", "clean_price": 103.1250, "conversion_factor": 0.9325, "accrued_today": 0.58, "accrued_delivery": 0.18, "interim_coupon_per_100": 1.75, "cash_dv01_per_100k": 76.0},
            {"security": "Illustrative C", "clean_price": 96.7500, "conversion_factor": 0.8730, "accrued_today": 0.20, "accrued_delivery": 0.64, "interim_coupon_per_100": 0.0, "cash_dv01_per_100k": 69.0},
        ])
    else:
        basket = pd.DataFrame(columns=TREASURY_FUTURES_BASKET_COLUMNS)
    edited = st.data_editor(basket, num_rows="dynamic", width="stretch", key="fic4_fut_editor")
    st.download_button("Download basket template", pd.DataFrame(columns=TREASURY_FUTURES_BASKET_COLUMNS).to_csv(index=False), "treasury_futures_basket_template.csv", "text/csv", key="fic4_fut_template")
    try:
        result = treasury_futures_delivery_analytics(edited, futures_price, settlement, delivery, repo, face, contract_size)
    except Exception as exc:
        st.error(f"Delivery analytics: {exc}")
        return
    if not result.get("available"):
        st.info(result.get("reason", "Complete the basket to run the CTD screen."))
        return
    k = st.columns(5)
    k[0].metric("CTD candidate", result["ctd_security"])
    k[1].metric("Implied repo", f"{result['ctd_implied_repo_pct']:.3f}%")
    k[2].metric("Net basis", f"{result['ctd_net_basis_32nds']:.3f}/32")
    k[3].metric("Hedge contracts", f"{result['ctd_contracts']:.1f}")
    k[4].metric("Days to delivery", str(result["days_to_delivery"]))
    screen = result["basket"]
    chart = go.Figure(go.Bar(x=screen["security"], y=screen["implied_repo_pct"], marker_color=np.where(screen["ctd_rank"] == 1, "#58e6ad", "#5be7ff")))
    chart.update_layout(template="plotly_dark", height=360, title="Implied repo by deliverable", yaxis_title="% annualised")
    st.plotly_chart(chart, width="stretch")
    st.dataframe(screen, width="stretch", hide_index=True)
    _download_csv_button(screen, "treasury_futures_ctd_screen.csv", "fic4_fut_download")
    st.markdown("<div class='fic2-method'>CTD is ranked by highest implied repo and checked against minimum net basis. Coupon timing, delivery options, wildcard timing, fails and repo specialness require desk conventions or an approved vendor engine before execution.</div>", unsafe_allow_html=True)


def _fic_credit_rv_demo() -> pd.DataFrame:
    rows = []
    ratings = ["A", "A", "BBB", "BBB", "BBB", "BB", "BB", "A", "BBB", "BB", "B", "B"]
    sectors = ["Technology", "Industrial", "Financials", "Utilities", "Consumer", "Energy", "Consumer", "Financials", "Technology", "Industrial", "Energy", "Consumer"]
    for i, (rating, sector) in enumerate(zip(ratings, sectors), 1):
        maturity = [2.1, 3.0, 4.2, 5.0, 6.4, 3.7, 7.1, 8.5, 9.3, 5.6, 4.8, 8.0][i - 1]
        base = {"A": 95, "BBB": 155, "BB": 315, "B": 540}[rating]
        residual = [-12, 14, -18, 24, 3, 36, -22, 18, -4, 28, -35, 45][i - 1]
        rows.append({
            "security": f"ILL-{i:02d}", "issuer": f"Illustrative Issuer {i:02d}", "sector": sector, "rating": rating,
            "maturity_years": maturity, "oas_bp": base + 5 * np.log1p(maturity) + residual, "yield_pct": 4.0 + (base + residual) / 100.0,
            "spread_duration": maturity * 0.82, "bid_ask_bp": 5 + i * 2.0, "daily_volume_mm": max(0.5, 12 - i * 0.7),
            "pd_1y": {"A": 0.001, "BBB": 0.003, "BB": 0.012, "B": 0.035}[rating], "recovery_rate": 0.40,
        })
    return pd.DataFrame(rows)


def _fic_render_credit_relative_value_v4() -> None:
    _fic_section("Credit Relative Value — Fair OAS, Carry & Downside")
    st.caption("Cross-sectional bond screen integrating peer residual, expected loss, funding, liquidity and spread-stress asymmetry.")
    controls = st.columns(4)
    funding = controls[0].number_input("Funding / hedge drag (bp)", -200.0, 1000.0, 35.0, 5.0, key="fic4_rv_funding")
    stress = controls[1].number_input("Spread stress (bp)", 0.0, 2000.0, 100.0, 25.0, key="fic4_rv_stress")
    minimum_liquidity = controls[2].slider("Minimum liquidity score", 0, 100, 25, key="fic4_rv_min_liq")
    max_results = controls[3].slider("Rows displayed", 10, 250, 50, 10, key="fic4_rv_rows")
    uploaded = st.file_uploader("Bond universe CSV / XLSX / Parquet", type=["csv", "xlsx", "xls", "parquet"], key="fic4_rv_upload")
    illustrative = st.checkbox("Load explicit illustrative credit universe", value=False, key="fic4_rv_demo")
    if uploaded is not None:
        parsed = parse_uploaded_table(uploaded)
        universe = parsed.frame if parsed.ok else pd.DataFrame(columns=CREDIT_RV_COLUMNS)
        _show_result_status(parsed)
    elif illustrative:
        st.warning("EXPLICIT ILLUSTRATIVE INPUTS — the universe below is synthetic and exists only to demonstrate the workflow.")
        universe = _fic_credit_rv_demo()
    else:
        universe = pd.DataFrame(columns=CREDIT_RV_COLUMNS)
    edited = st.data_editor(universe, num_rows="dynamic", width="stretch", key="fic4_rv_editor")
    st.download_button("Download universe template", pd.DataFrame(columns=CREDIT_RV_COLUMNS).to_csv(index=False), "credit_relative_value_template.csv", "text/csv", key="fic4_rv_template")
    try:
        result = credit_relative_value_screen(edited, funding, stress)
    except Exception as exc:
        st.error(f"Relative-value model: {exc}")
        return
    if not result.get("available"):
        st.info(result.get("reason", "Upload a valid universe."))
        return
    screen = result["screen"]
    eligible = screen[screen["liquidity_score"] >= minimum_liquidity].head(max_results)
    cheap = int((eligible["screen"] == "CHEAP / REVIEW LONG").sum())
    rich = int((eligible["screen"] == "RICH / REVIEW SHORT").sum())
    k = st.columns(6)
    k[0].metric("Securities", str(result["observations"]))
    k[1].metric("Model R²", f"{result['model_r2']:.2%}" if np.isfinite(result["model_r2"]) else "N/A")
    k[2].metric("RMSE", f"{result['model_rmse_bp']:.1f} bp")
    k[3].metric("Cheap reviews", str(cheap))
    k[4].metric("Rich reviews", str(rich))
    k[5].metric("Median excess carry", f"{eligible['excess_carry_bp'].median():.0f} bp" if not eligible.empty else "N/A")
    left, right = st.columns([1.25, 0.75])
    with left:
        scatter = go.Figure()
        for label, group in eligible.groupby("rating"):
            scatter.add_trace(go.Scatter(x=group["maturity_years"], y=group["oas_bp"], mode="markers", name=str(label), text=group["security"], marker={"size": np.clip(group["liquidity_score"] / 5.0, 7, 20), "color": group["opportunity_score"], "colorscale": "Turbo", "cmin": 0, "cmax": 100}))
        scatter.update_layout(template="plotly_dark", height=430, title="OAS term structure · size = liquidity · colour = opportunity", xaxis_title="Maturity (years)", yaxis_title="OAS (bp)")
        st.plotly_chart(scatter, width="stretch")
    with right:
        score_chart = go.Figure(go.Bar(x=eligible.head(15)["opportunity_score"], y=eligible.head(15)["security"], orientation="h", marker_color="#5be7ff"))
        score_chart.update_layout(template="plotly_dark", height=430, title="Top review queue", xaxis_title="Score", yaxis={"autorange": "reversed"})
        st.plotly_chart(score_chart, width="stretch")
    st.dataframe(eligible, width="stretch", hide_index=True)
    _download_csv_button(screen, "credit_relative_value_screen.csv", "fic4_rv_download")
    st.markdown("<div class='fic2-method'>The fair spread is a transparent cross-sectional screening regression, not a trade recommendation. Callable structures require OAS from an approved option model; PD, recovery, liquidity, funding and execution inputs must be validated independently.</div>", unsafe_allow_html=True)


def _fic_render_pnl_tail_risk_v4() -> None:
    _fic_section("P&L Attribution, Concentration & Liquidity-Horizon ES")
    portfolio = normalize_portfolio(_portfolio_state())
    tabs = st.tabs(["P&L explain", "Risk budget", "Tail risk"])
    with tabs[0]:
        horizon = st.selectbox("Attribution horizon", [1, 5, 20, 63, 252], index=0, key="fic4_pnl_horizon")
        if portfolio.empty or portfolio["market_value"].fillna(0.0).abs().sum() == 0:
            st.info("Populate Portfolio Analytics first, then return here for position-level attribution.")
        else:
            attribution_input = portfolio.copy()
            for column in PNL_ATTRIBUTION_COLUMNS:
                attribution_input[column] = np.nan if column == "realized_pnl" else 0.0
            edited = st.data_editor(attribution_input, width="stretch", key="fic4_pnl_editor")
            result = fixed_income_pnl_attribution(edited, horizon)
            totals = result["totals"]
            k = st.columns(5)
            k[0].metric("Explained P&L", _fmt_money(totals["explained_pnl"]))
            k[1].metric("Carry", _fmt_money(totals["carry_pnl"]))
            k[2].metric("Rates + roll", _fmt_money(totals["rates_pnl"] + totals["roll_down_pnl"]))
            k[3].metric("Spread", _fmt_money(totals["spread_pnl"]))
            k[4].metric("Unexplained", _fmt_money(totals["unexplained_pnl"]) if result["realized_available"] else "N/A")
            components = pd.DataFrame({"component": ["Carry", "Rates", "Spread", "Roll-down", "Convexity", "FX"], "pnl": [totals[x] for x in ["carry_pnl", "rates_pnl", "spread_pnl", "roll_down_pnl", "convexity_pnl", "fx_pnl"]]})
            waterfall = go.Figure(go.Waterfall(x=components["component"], y=components["pnl"], connector={"line": {"color": "rgba(200,220,240,.25)"}}, increasing={"marker": {"color": "#58e6ad"}}, decreasing={"marker": {"color": "#ff7272"}}))
            waterfall.update_layout(template="plotly_dark", height=390, title="Explained P&L waterfall")
            st.plotly_chart(waterfall, width="stretch")
            st.dataframe(result["positions"], width="stretch", hide_index=True)
            _download_csv_button(result["positions"], "fixed_income_pnl_attribution.csv", "fic4_pnl_download")
    with tabs[1]:
        issuer_limit = st.slider("Issuer gross-weight limit (%)", 1.0, 50.0, 10.0, 0.5, key="fic4_conc_limit")
        concentration = portfolio_concentration_dashboard(portfolio, issuer_limit)
        if not concentration.get("available"):
            st.info(concentration.get("reason", "Populate the portfolio first."))
        else:
            k = st.columns(5)
            k[0].metric("Gross exposure", _fmt_money(concentration["gross_market_value"]))
            k[1].metric("Effective issuers", f"{concentration['effective_issuers']:.1f}")
            k[2].metric("Issuer HHI", f"{concentration['issuer_hhi']:.3f}")
            k[3].metric("Top issuer", f"{concentration['top_issuer_pct']:.1f}%")
            k[4].metric("Top 5", f"{concentration['top5_pct']:.1f}%")
            left, right = st.columns(2)
            with left:
                st.markdown("#### Issuer concentration")
                st.dataframe(concentration["tables"]["issuer"], width="stretch", hide_index=True)
            with right:
                st.markdown("#### Sensitivity concentration")
                st.dataframe(concentration["risk_concentration"], width="stretch", hide_index=True)
                st.markdown("#### Limit breaches")
                st.dataframe(concentration["limit_breaches"], width="stretch", hide_index=True)
    with tabs[2]:
        confidence = st.selectbox("ES confidence", [0.95, 0.975, 0.99], index=1, key="fic4_lhes_conf")
        horizons = st.columns(3)
        rate_lh = horizons[0].selectbox("Rates liquidity horizon", [10, 20, 40, 60, 120], index=1, key="fic4_lhes_rate")
        credit_lh = horizons[1].selectbox("Credit liquidity horizon", [10, 20, 40, 60, 120], index=3, key="fic4_lhes_credit")
        fx_lh = horizons[2].selectbox("FX liquidity horizon", [10, 20, 40, 60, 120], index=0, key="fic4_lhes_fx")
        if portfolio.empty or portfolio["market_value"].fillna(0.0).abs().sum() == 0:
            st.info("Populate Portfolio Analytics first.")
        else:
            start = _start_date_for_years(10)
            rates, credit = _result_or_demo(_cached_us_curve(start), "curve"), _result_or_demo(_cached_credit(start), "credit")
            if not rates.ok or not credit.ok:
                st.info("Rates and credit histories are required. Use explicit demo mode only if appropriate.")
            else:
                rate_frame = normalize_curve_history(rates.frame).set_index("date")
                credit_frame = credit.frame.copy().set_index("date")
                rate_change = pd.to_numeric(rate_frame.get("10Y"), errors="coerce").diff() * 100.0
                spread_column = "US IG OAS" if "US IG OAS" in credit_frame.columns else next((c for c in CREDIT_OAS_SERIES if c in credit_frame.columns), None)
                spread_change = pd.to_numeric(credit_frame[spread_column], errors="coerce").diff() if spread_column else None
                factor_history = factor_pnl_components(portfolio, rate_change, spread_change)
                risk = liquidity_adjusted_expected_shortfall(factor_history, {"Rates": rate_lh, "Credit spread": credit_lh, "FX": fx_lh}, confidence)
                if not risk.get("available"):
                    st.warning(risk.get("reason", "Tail-risk estimate unavailable"))
                else:
                    k = st.columns(4)
                    k[0].metric("10D base ES", _fmt_money(risk["base_es"]))
                    k[1].metric("Liquidity-adjusted ES", _fmt_money(risk["liquidity_adjusted_es"]))
                    k[2].metric("Liquidity uplift", f"{risk['uplift_pct']:.1f}%")
                    k[3].metric("Confidence", f"{100 * risk['confidence']:.1f}%")
                    st.dataframe(risk["components"], width="stretch", hide_index=True)
                    st.markdown("<div class='fic2-method'>Historical factor P&L is aggregated with a Basel-style liquidity-horizon square-root rule. This is a risk-management screen, not an IMA capital calculation: modellability, stress scaling, NMRF and regulatory correlation constraints are outside scope.</div>", unsafe_allow_html=True)


def _fic_render_signal_validation_v4() -> None:
    _fic_section("Signal Validation — Walk-Forward, Costs & Robustness")
    _, result = _select_curve_result()
    _show_result_status(result)
    if not result.ok:
        return
    frame = normalize_curve_history(result.frame)
    tenors = [c for c in frame.columns if c != "date"]
    controls = st.columns(7)
    short = controls[0].selectbox("Short tenor", tenors, index=tenors.index("2Y") if "2Y" in tenors else 0, key="fic4_sig_short")
    long = controls[1].selectbox("Long tenor", tenors, index=tenors.index("10Y") if "10Y" in tenors else len(tenors) - 1, key="fic4_sig_long")
    window = controls[2].selectbox("Lookback", [63, 126, 252, 504], index=2, key="fic4_sig_window")
    entry = controls[3].selectbox("Entry z", [1.0, 1.25, 1.5, 2.0, 2.5], index=2, key="fic4_sig_entry")
    exit_z = controls[4].selectbox("Exit z", [0.0, 0.25, 0.5, 0.75], index=1, key="fic4_sig_exit")
    cost = controls[5].number_input("Turn cost (bp)", 0.0, 50.0, 1.0, 0.25, key="fic4_sig_cost")
    test_size = controls[6].selectbox("Test fold", [63, 126, 252], index=1, key="fic4_sig_fold")
    spread = (pd.to_numeric(frame[long], errors="coerce") - pd.to_numeric(frame[short], errors="coerce")) * 100.0
    spread.index = pd.to_datetime(frame["date"])
    minimum_train = min(max(504, 2 * window), max(504, len(spread) - test_size))
    validation = walk_forward_signal_validation(spread, entry, exit_z, 3.0, window, cost, minimum_train, test_size)
    if not validation.get("available"):
        st.warning(validation.get("reason", "Walk-forward validation unavailable"))
        return
    metrics = validation["metrics"]
    k = st.columns(7)
    k[0].metric("OOS Sharpe", _fmt_num(metrics["oos_sharpe"]))
    k[1].metric("NW t-stat", _fmt_num(metrics["newey_west_tstat"]))
    k[2].metric("PSR > 0", f"{metrics['probabilistic_sharpe']:.1%}" if np.isfinite(metrics["probabilistic_sharpe"]) else "N/A")
    k[3].metric("Positive folds", f"{metrics['positive_fold_ratio']:.0%}")
    k[4].metric("Annual P&L", f"{metrics['annualized_pnl_bp']:.1f} bp")
    k[5].metric("Max drawdown", f"{metrics['max_drawdown_bp']:.1f} bp")
    k[6].metric("Turnover", f"{metrics['turnover']:.0f}")
    oos = validation["oos"].copy()
    oos["oos_equity"] = oos["pnl"].cumsum()
    chart = go.Figure()
    chart.add_trace(go.Scatter(x=oos.index, y=oos["oos_equity"], mode="lines", name="OOS cumulative P&L"))
    chart.update_layout(template="plotly_dark", height=390, title="Strict out-of-sample cumulative P&L", yaxis_title="bp")
    st.plotly_chart(chart, width="stretch")
    left, right = st.columns([1.0, 1.15])
    with left:
        st.markdown("#### Fold diagnostics")
        st.dataframe(validation["folds"], width="stretch", hide_index=True)
    with right:
        robustness = []
        for candidate_window in [63, 126, 252, 504]:
            for candidate_entry in [1.0, 1.5, 2.0, 2.5]:
                candidate = backtest_zscore_strategy(spread, candidate_entry, exit_z, 3.0, candidate_window, cost)
                robustness.append({"window": candidate_window, "entry_z": candidate_entry, "sharpe": candidate.get("metrics", {}).get("sharpe")})
        robustness_frame = pd.DataFrame(robustness)
        pivot = robustness_frame.pivot(index="window", columns="entry_z", values="sharpe")
        heatmap = go.Figure(go.Heatmap(z=pivot.to_numpy(), x=[str(x) for x in pivot.columns], y=[str(x) for x in pivot.index], zmid=0, colorscale="RdBu", colorbar_title="Sharpe"))
        heatmap.update_layout(template="plotly_dark", height=330, title="Parameter stability", xaxis_title="Entry z", yaxis_title="Lookback")
        st.plotly_chart(heatmap, width="stretch")
    _download_csv_button(oos.reset_index(), "fixed_income_walk_forward_oos.csv", "fic4_sig_download")
    st.markdown("<div class='fic2-method'>All reported headline metrics are from sequential, non-overlapping test folds. Newey–West inference, probabilistic Sharpe, transaction costs and parameter stability reduce false confidence; they do not remove selection bias, publication lags, financing or CTD-switch risk.</div>", unsafe_allow_html=True)


def _fic_render_structural_credit_v5() -> None:
    _fic_section("Issuer Structural Credit — Merton Distance-to-Default")
    st.caption("Market-implied structural default screen linking equity value, equity volatility and debt through the equity-as-a-call framework.")
    inputs = st.columns(6)
    equity_bn = inputs[0].number_input("Equity value ($bn)", 0.001, 10_000.0, 50.0, 1.0, key="fic5_merton_equity")
    equity_vol_pct = inputs[1].number_input("Equity volatility (%)", 0.1, 500.0, 35.0, 1.0, key="fic5_merton_vol")
    debt_bn = inputs[2].number_input("Default point / debt ($bn)", 0.001, 10_000.0, 35.0, 1.0, key="fic5_merton_debt")
    risk_free_pct = inputs[3].number_input("Risk-free rate (%)", -5.0, 30.0, 4.0, 0.25, key="fic5_merton_rf")
    asset_drift_pct = inputs[4].number_input("Asset drift (%)", -50.0, 100.0, 6.0, 0.5, key="fic5_merton_drift")
    horizon = inputs[5].selectbox("Horizon", [0.25, 0.5, 1.0, 2.0, 3.0], index=2, key="fic5_merton_horizon")
    try:
        model = merton_distance_to_default(equity_bn, equity_vol_pct / 100.0, debt_bn, risk_free_pct / 100.0, horizon, asset_drift_pct / 100.0)
    except Exception as exc:
        st.error(f"Structural model: {exc}")
        return
    market = st.columns(2)
    observed_spread = market[0].number_input("Observed credit spread (bp)", 0.0, 10_000.0, 250.0, 10.0, key="fic5_merton_spread")
    recovery = market[1].slider("Recovery assumption", 0.0, 0.90, 0.40, 0.05, key="fic5_merton_recovery")
    spread_hazard = hazard_rate_from_spread(observed_spread, recovery)
    spread_pd = cumulative_default_probability(spread_hazard, horizon)
    dd = float(model["physical_distance_to_default"])
    state = "DISTRESSED" if dd < 1.0 else "VULNERABLE" if dd < 2.0 else "WATCH" if dd < 3.0 else "RESILIENT"
    k = st.columns(7)
    k[0].metric("Structural state", state)
    k[1].metric("Physical DD", f"{dd:.2f}σ")
    k[2].metric("Physical PD", f"{100 * model['physical_pd']:.2f}%")
    k[3].metric("Risk-neutral PD", f"{100 * model['risk_neutral_pd']:.2f}%")
    k[4].metric("Spread-implied PD", f"{100 * spread_pd:.2f}%")
    k[5].metric("Asset volatility", f"{100 * model['asset_volatility']:.1f}%")
    k[6].metric("Debt / assets", f"{100 * model['debt_to_assets']:.1f}%")
    sensitivity_rows = []
    for debt_multiplier in [0.75, 1.0, 1.25, 1.50]:
        for vol_multiplier in [0.75, 1.0, 1.25, 1.50, 2.0]:
            stressed = merton_distance_to_default(equity_bn, equity_vol_pct / 100.0 * vol_multiplier, debt_bn * debt_multiplier, risk_free_pct / 100.0, horizon, asset_drift_pct / 100.0)
            sensitivity_rows.append({"debt_multiplier": debt_multiplier, "vol_multiplier": vol_multiplier, "physical_pd_pct": 100 * stressed["physical_pd"], "distance_to_default": stressed["physical_distance_to_default"]})
    sensitivity = pd.DataFrame(sensitivity_rows)
    pivot = sensitivity.pivot(index="debt_multiplier", columns="vol_multiplier", values="physical_pd_pct")
    heatmap = go.Figure(go.Heatmap(z=pivot.to_numpy(), x=[f"{x:.2f}×" for x in pivot.columns], y=[f"{x:.2f}×" for x in pivot.index], colorscale="YlOrRd", colorbar_title="PD %"))
    heatmap.update_layout(template="plotly_dark", height=390, title="PD sensitivity to leverage and equity volatility", xaxis_title="Equity-vol multiplier", yaxis_title="Debt multiplier")
    left, right = st.columns([1.2, 0.8])
    with left:
        st.plotly_chart(heatmap, width="stretch")
    with right:
        comparison = pd.DataFrame([
            {"measure": "Physical structural PD", "pd_pct": 100 * model["physical_pd"]},
            {"measure": "Risk-neutral structural PD", "pd_pct": 100 * model["risk_neutral_pd"]},
            {"measure": "Spread / (1-R) implied PD", "pd_pct": 100 * spread_pd},
        ])
        st.dataframe(comparison, width="stretch", hide_index=True)
        st.dataframe(pd.DataFrame([model]), width="stretch", hide_index=True)
    st.markdown("<div class='fic2-method'>Merton assumes a single zero-coupon debt claim, lognormal assets, continuous trading and a fixed default barrier. Treat DD as an equity-based cross-check—not a calibrated bond spread or rating—and compare it with accounting, covenant and market evidence.</div>", unsafe_allow_html=True)


def _fic_render_credit_carry_v5() -> None:
    _fic_section("Credit Carry, Expected Loss & Spread Breakeven")
    st.caption("Forward-looking expected return decomposed into carry, funding, default loss, roll-down, rates, convexity and spread scenarios.")
    first = st.columns(6)
    market_value = first[0].number_input("Market value", 1.0, 100_000_000_000.0, 10_000_000.0, 100_000.0, key="fic5_carry_mv")
    yield_pct = first[1].number_input("Yield (%)", -10.0, 100.0, 6.50, 0.10, key="fic5_carry_yield")
    funding_pct = first[2].number_input("Funding / hedge (%)", -10.0, 100.0, 4.50, 0.10, key="fic5_carry_funding")
    oas_bp = first[3].number_input("OAS (bp)", -1000.0, 10_000.0, 250.0, 10.0, key="fic5_carry_oas")
    spread_duration = first[4].number_input("Spread duration", 0.0, 50.0, 4.5, 0.25, key="fic5_carry_sd")
    rate_duration = first[5].number_input("Rate duration", 0.0, 50.0, 4.8, 0.25, key="fic5_carry_rd")
    second = st.columns(6)
    convexity = second[0].number_input("Convexity", -500.0, 2000.0, 30.0, 1.0, key="fic5_carry_convexity")
    horizon = second[1].selectbox("Horizon", [1/12, 0.25, 0.5, 1.0, 2.0], index=3, format_func=lambda x: f"{x * 12:.0f}M" if x < 1 else f"{x:.0f}Y", key="fic5_carry_horizon")
    pd_pct = second[2].number_input("Horizon PD (%)", 0.0, 100.0, 2.0, 0.25, key="fic5_carry_pd")
    recovery = second[3].slider("Recovery", 0.0, 0.90, 0.40, 0.05, key="fic5_carry_recovery")
    roll_down = second[4].number_input("Roll-down yield move (bp)", -500.0, 500.0, -15.0, 5.0, key="fic5_carry_roll")
    rate_change = second[5].number_input("Expected rate move (bp)", -1000.0, 1000.0, 0.0, 10.0, key="fic5_carry_rates")
    try:
        result = credit_carry_breakeven(market_value, yield_pct, funding_pct, oas_bp, spread_duration, rate_duration, convexity, horizon, pd_pct / 100.0, recovery, roll_down, rate_change)
    except Exception as exc:
        st.error(f"Carry engine: {exc}")
        return
    k = st.columns(7)
    k[0].metric("Expected P&L", _fmt_money(result["expected_pnl_before_spread_move"]))
    k[1].metric("Expected return", f"{result['expected_return_before_spread_move_pct']:.2f}%")
    k[2].metric("Gross carry", _fmt_money(result["gross_carry"]))
    k[3].metric("Expected loss", _fmt_money(result["expected_default_loss"]))
    k[4].metric("Spread breakeven", _fmt_bp(result["spread_breakeven_widening_bp"]))
    k[5].metric("CS01", _fmt_money(result["cs01"]))
    ratio = result["carry_to_expected_loss"]
    k[6].metric("Carry / EL", f"{ratio:.2f}×" if np.isfinite(ratio) else "∞")
    scenario = result["scenario"]
    chart = go.Figure(go.Bar(x=scenario["spread_change_bp"], y=scenario["expected_total_pnl"], marker_color=np.where(scenario["expected_total_pnl"] >= 0, "#58e6ad", "#ff7272")))
    chart.add_vline(x=result["spread_breakeven_widening_bp"], line_color="#f2c96d", line_dash="dash", annotation_text="Breakeven")
    chart.update_layout(template="plotly_dark", height=410, title="Expected P&L under spread shocks", xaxis_title="Spread change (bp)", yaxis_title="P&L")
    st.plotly_chart(chart, width="stretch")
    components = pd.DataFrame({"component": ["Gross carry", "Funding", "Expected default loss", "Roll-down", "Rates", "Convexity"], "pnl": [result["gross_carry"], -result["funding_cost"], -result["expected_default_loss"], result["roll_down_pnl"], result["rates_pnl"], result["convexity_pnl"]]})
    left, right = st.columns([0.7, 1.3])
    with left:
        st.dataframe(components, width="stretch", hide_index=True)
    with right:
        st.dataframe(scenario, width="stretch", hide_index=True)
    _download_csv_button(scenario, "credit_carry_breakeven_scenarios.csv", "fic5_carry_download")
    st.markdown("<div class='fic2-method'>Expected loss is PD × LGD × exposure. Carry is not alpha: liquidity, downgrade migration, optionality, taxes, coupon timing and realised financing can dominate the screen. Use instrument-level OAS and effective spread duration for callable bonds.</div>", unsafe_allow_html=True)


def _fic_render_recovery_covenants_v5() -> None:
    _fic_section("Capital Structure, Recovery Waterfall & Covenants")
    st.caption("Scenario recovery by contractual priority, pari-passu allocation, workout costs and stressed covenant headroom.")
    tabs = st.tabs(["Recovery waterfall", "Covenant headroom"])
    with tabs[0]:
        illustrative = st.checkbox("Load explicit illustrative capital structure", value=False, key="fic5_recovery_demo")
        template = pd.DataFrame(columns=["security", "class", "priority", "claim"])
        if illustrative:
            st.warning("EXPLICIT ILLUSTRATIVE INPUTS — legal priority, guarantees, collateral and intercreditor terms must be reviewed separately.")
            template = pd.DataFrame([
                {"security": "Revolver", "class": "Super senior secured", "priority": 1, "claim": 150.0},
                {"security": "Term Loan", "class": "First lien", "priority": 2, "claim": 450.0},
                {"security": "Senior Notes", "class": "Senior unsecured", "priority": 3, "claim": 300.0},
                {"security": "Sub Notes", "class": "Subordinated", "priority": 4, "claim": 150.0},
            ])
        capital = st.data_editor(template, num_rows="dynamic", width="stretch", key="fic5_recovery_editor")
        controls = st.columns(4)
        base_ev = controls[0].number_input("Base enterprise value", 0.0, 1_000_000.0, 900.0, 25.0, key="fic5_recovery_ev")
        downside_1 = controls[1].slider("Downside scenario", 0.0, 1.0, 0.70, 0.05, key="fic5_recovery_down1")
        downside_2 = controls[2].slider("Severe scenario", 0.0, 1.0, 0.40, 0.05, key="fic5_recovery_down2")
        workout_cost = controls[3].slider("Workout cost (%)", 0.0, 50.0, 7.5, 0.5, key="fic5_recovery_cost")
        result = recovery_waterfall(capital, [base_ev, base_ev * downside_1, base_ev * downside_2], workout_cost)
        st.download_button("Download capital-structure template", pd.DataFrame(columns=["security", "class", "priority", "claim"]).to_csv(index=False), "credit_capital_structure_template.csv", "text/csv", key="fic5_recovery_template")
        if not result.get("available"):
            st.info(result.get("reason", "Complete the capital structure."))
        else:
            summary = result["summary"]
            selected = st.selectbox("Waterfall scenario", summary["scenario"].tolist(), key="fic5_recovery_scenario")
            detail = result["detail"].query("scenario == @selected")
            selected_summary = summary.query("scenario == @selected").iloc[0]
            k = st.columns(5)
            k[0].metric("Distributable EV", _fmt_money(selected_summary["distributable_value"]))
            k[1].metric("Total claims", _fmt_money(selected_summary["total_claims"]))
            k[2].metric("Debt recovery", f"{selected_summary['debt_recovery_pct']:.1f}%")
            k[3].metric("Workout cost", _fmt_money(selected_summary["workout_cost"]))
            k[4].metric("Equity residual", _fmt_money(selected_summary["equity_residual"]))
            chart = go.Figure()
            chart.add_trace(go.Bar(x=detail["security"], y=detail["recovery_amount"], name="Recovery", marker_color="#58e6ad"))
            chart.add_trace(go.Bar(x=detail["security"], y=detail["loss_amount"], name="Loss", marker_color="#ff7272"))
            chart.update_layout(template="plotly_dark", barmode="stack", height=400, title="Claim recovery waterfall", yaxis_title="Claim units")
            st.plotly_chart(chart, width="stretch")
            st.dataframe(result["summary"], width="stretch", hide_index=True)
            st.dataframe(result["detail"], width="stretch", hide_index=True)
            _download_csv_button(result["detail"], "credit_recovery_waterfall.csv", "fic5_recovery_download")
    with tabs[1]:
        covenant_demo = st.checkbox("Load explicit illustrative covenant set", value=False, key="fic5_covenant_demo")
        covenants = pd.DataFrame(columns=["covenant", "test_type", "current", "limit", "stress_change"])
        if covenant_demo:
            covenants = pd.DataFrame([
                {"covenant": "Net leverage", "test_type": "Maximum", "current": 4.2, "limit": 5.5, "stress_change": 1.0},
                {"covenant": "Interest coverage", "test_type": "Minimum", "current": 2.4, "limit": 1.75, "stress_change": -0.8},
                {"covenant": "Minimum liquidity", "test_type": "Minimum", "current": 180.0, "limit": 100.0, "stress_change": -95.0},
            ])
        edited = st.data_editor(covenants, num_rows="dynamic", width="stretch", key="fic5_covenant_editor")
        covenant_result = covenant_headroom_analysis(edited)
        st.download_button("Download covenant template", pd.DataFrame(columns=["covenant", "test_type", "current", "limit", "stress_change"]).to_csv(index=False), "credit_covenant_template.csv", "text/csv", key="fic5_covenant_template")
        if not covenant_result.get("available"):
            st.info(covenant_result.get("reason", "Complete covenant inputs."))
        else:
            k = st.columns(3)
            k[0].metric("Stressed breaches", str(covenant_result["breaches"]))
            k[1].metric("Tight tests", str(covenant_result["tight_tests"]))
            k[2].metric("Minimum headroom", f"{covenant_result['minimum_headroom_pct']:.1f}%")
            st.dataframe(covenant_result["table"], width="stretch", hide_index=True)
    st.markdown("<div class='fic2-method'>The waterfall applies a simplified absolute-priority rule and pari-passu allocation. Guarantees, structural subordination, collateral leakage, DIP financing, avoidance actions, jurisdiction, intercreditor rights and plan negotiations require legal analysis.</div>", unsafe_allow_html=True)


def _fic_watchlist_demo_v5() -> pd.DataFrame:
    return pd.DataFrame([
        {"issuer": "Illustrative Stable", "rating": "A", "oas_bp": 95, "oas_z": -0.4, "spread_change_1m_bp": -8, "equity_drawdown_pct": -4, "net_leverage": 1.8, "interest_coverage": 8.0, "liquidity_score": 85, "maturity_12m_pct": 5, "pd_1y": 0.002, "covenant_headroom_pct": 40},
        {"issuer": "Illustrative Monitor", "rating": "BBB", "oas_bp": 190, "oas_z": 1.1, "spread_change_1m_bp": 35, "equity_drawdown_pct": -18, "net_leverage": 4.0, "interest_coverage": 2.5, "liquidity_score": 55, "maturity_12m_pct": 22, "pd_1y": 0.015, "covenant_headroom_pct": 18},
        {"issuer": "Illustrative Watch", "rating": "BB", "oas_bp": 470, "oas_z": 2.3, "spread_change_1m_bp": 115, "equity_drawdown_pct": -35, "net_leverage": 5.8, "interest_coverage": 1.6, "liquidity_score": 28, "maturity_12m_pct": 38, "pd_1y": 0.065, "covenant_headroom_pct": 4},
        {"issuer": "Illustrative Critical", "rating": "B", "oas_bp": 900, "oas_z": 3.2, "spread_change_1m_bp": 220, "equity_drawdown_pct": -52, "net_leverage": 7.5, "interest_coverage": 0.9, "liquidity_score": 12, "maturity_12m_pct": 55, "pd_1y": 0.14, "covenant_headroom_pct": -8},
    ])


def _fic_render_watchlist_v5() -> None:
    _fic_section("Credit Watchlist & Early-Warning System")
    st.caption("Multi-signal surveillance across market, equity, fundamentals, liquidity, refinancing, covenants and default risk.")
    uploaded = st.file_uploader("Issuer watchlist CSV / XLSX / Parquet", type=["csv", "xlsx", "xls", "parquet"], key="fic5_watch_upload")
    illustrative = st.checkbox("Load explicit illustrative watchlist", value=False, key="fic5_watch_demo")
    if uploaded is not None:
        parsed = parse_uploaded_table(uploaded)
        universe = parsed.frame if parsed.ok else pd.DataFrame(columns=WATCHLIST_COLUMNS)
        _show_result_status(parsed)
    elif illustrative:
        st.warning("EXPLICIT ILLUSTRATIVE INPUTS — no issuer or signal below represents market data.")
        universe = _fic_watchlist_demo_v5()
    else:
        universe = pd.DataFrame(columns=WATCHLIST_COLUMNS)
    edited = st.data_editor(universe, num_rows="dynamic", width="stretch", key="fic5_watch_editor")
    st.download_button("Download watchlist template", pd.DataFrame(columns=WATCHLIST_COLUMNS).to_csv(index=False), "credit_watchlist_template.csv", "text/csv", key="fic5_watch_template")
    result = credit_watchlist_score(edited)
    if not result.get("available"):
        st.info(result.get("reason", "Complete the watchlist."))
        return
    watch = result["watchlist"]
    k = st.columns(5)
    k[0].metric("Issuers", str(len(watch)))
    k[1].metric("Critical", str(result["critical"]))
    k[2].metric("Watch", str(result["watch"]))
    k[3].metric("Median score", f"{result['median_score']:.1f}")
    k[4].metric("Hard flags", str(int(watch["hard_flags"].ne("").sum())))
    left, right = st.columns([0.8, 1.2])
    with left:
        chart = go.Figure(go.Bar(x=watch["watch_score"], y=watch["issuer"], orientation="h", marker_color=np.where(watch["status"] == "CRITICAL", "#ff7272", np.where(watch["status"] == "WATCH", "#f2c96d", "#5be7ff"))))
        chart.update_layout(template="plotly_dark", height=max(360, 38 * len(watch)), title="Early-warning ranking", xaxis_title="Risk score", yaxis={"autorange": "reversed"})
        st.plotly_chart(chart, width="stretch")
    with right:
        components = ["market_component", "equity_component", "fundamental_component", "liquidity_component", "refinancing_component", "default_component"]
        heatmap = go.Figure(go.Heatmap(z=watch[components].to_numpy(), x=[x.replace("_component", "").title() for x in components], y=watch["issuer"], zmin=0, zmax=100, colorscale="YlOrRd", colorbar_title="Risk"))
        heatmap.update_layout(template="plotly_dark", height=max(360, 38 * len(watch)), title="Risk-driver heatmap")
        st.plotly_chart(heatmap, width="stretch")
    st.dataframe(watch, width="stretch", hide_index=True)
    _download_csv_button(watch, "credit_early_warning_watchlist.csv", "fic5_watch_download")
    st.markdown("<div class='fic2-method'>The score is a prioritisation queue, not a rating or trade instruction. Freeze weights under governance, retain point-in-time inputs, track overrides and require analyst review for every hard flag.</div>", unsafe_allow_html=True)



# ============================================================================
# INSTITUTIONAL CREDIT RESEARCH OPERATING SYSTEM — V6
# ============================================================================

def _fic6_robust_z(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    median = values.median()
    mad = (values - median).abs().median()
    scale = 1.4826 * mad
    if not np.isfinite(scale) or scale <= 1e-12:
        scale = values.std(ddof=1)
    if not np.isfinite(scale) or scale <= 1e-12:
        return pd.Series(0.0, index=values.index)
    return (values - median) / scale


def credit_research_peer_screen(frame: pd.DataFrame) -> dict[str, Any]:
    """Robust issuer/security relative-value screen with transparent components."""
    if frame is None or frame.empty:
        return {"available": False, "reason": "Peer universe is empty", "frame": pd.DataFrame()}
    df = frame.copy()
    required_text = {"issuer": "Unknown", "security": "Unspecified", "rating": "NR", "sector": "Other"}
    for column, default in required_text.items():
        if column not in df:
            df[column] = default
        df[column] = df[column].fillna(default).astype(str)
    defaults = {
        "oas_bp": np.nan, "ytw_pct": np.nan, "duration": 5.0, "leverage": np.nan,
        "interest_coverage": np.nan, "liquidity_score": 50.0, "momentum_1m_bp": 0.0,
        "default_probability_pct": 1.0, "recovery_pct": 40.0,
    }
    for column, default in defaults.items():
        if column not in df:
            df[column] = default
        df[column] = pd.to_numeric(df[column], errors="coerce")
        if np.isfinite(default):
            df[column] = df[column].fillna(default)
    df = df.dropna(subset=["oas_bp"]).reset_index(drop=True)
    if df.empty:
        return {"available": False, "reason": "No valid OAS observations", "frame": df}

    df["expected_loss_bp"] = (
        df["default_probability_pct"].clip(lower=0) / 100.0
        * (1.0 - df["recovery_pct"].clip(0, 100) / 100.0)
        * 10000.0
    )
    df["liquidity_premium_bp"] = (100.0 - df["liquidity_score"].clip(0, 100)) * 0.70
    df["excess_compensation_bp"] = df["oas_bp"] - df["expected_loss_bp"] - df["liquidity_premium_bp"]
    df["curve_fair_oas_bp"] = np.nan

    for _, index in df.groupby(["sector", "rating"], dropna=False).groups.items():
        block = df.loc[index]
        x = block["duration"].to_numpy(dtype=float)
        y = block["oas_bp"].to_numpy(dtype=float)
        valid = np.isfinite(x) & np.isfinite(y)
        if valid.sum() >= 3 and np.unique(x[valid]).size >= 2:
            degree = 2 if valid.sum() >= 5 and np.unique(x[valid]).size >= 3 else 1
            coefficients = np.polyfit(x[valid], y[valid], degree)
            df.loc[index, "curve_fair_oas_bp"] = np.polyval(coefficients, x)
        else:
            df.loc[index, "curve_fair_oas_bp"] = float(np.nanmedian(y[valid])) if valid.any() else np.nan

    overall_fair = float(df["oas_bp"].median())
    df["curve_fair_oas_bp"] = df["curve_fair_oas_bp"].fillna(overall_fair)
    df["curve_residual_bp"] = df["oas_bp"] - df["curve_fair_oas_bp"]
    df["rv_z"] = _fic6_robust_z(df["curve_residual_bp"])
    df["excess_comp_z"] = _fic6_robust_z(df["excess_compensation_bp"])
    df["leverage_z"] = _fic6_robust_z(df["leverage"])
    df["coverage_z"] = _fic6_robust_z(df["interest_coverage"])
    df["liquidity_z"] = _fic6_robust_z(df["liquidity_score"])
    df["momentum_z"] = _fic6_robust_z(df["momentum_1m_bp"])
    raw = (
        50.0 + 9.0 * df["rv_z"].clip(-3, 3)
        + 7.0 * df["excess_comp_z"].clip(-3, 3)
        - 6.0 * df["leverage_z"].clip(-3, 3)
        + 5.0 * df["coverage_z"].clip(-3, 3)
        + 4.0 * df["liquidity_z"].clip(-3, 3)
        - 3.0 * df["momentum_z"].clip(-3, 3)
    )
    df["research_score"] = raw.clip(0, 100)
    df["signal"] = np.select(
        [df["research_score"] >= 70, df["research_score"] >= 58, df["research_score"] <= 35],
        ["HIGH-CONVICTION CHEAP", "CHEAP / INVESTIGATE", "RICH / DETERIORATING"],
        default="NEUTRAL / MONITOR",
    )
    df = df.sort_values(["research_score", "excess_compensation_bp"], ascending=False).reset_index(drop=True)
    df["rank"] = np.arange(1, len(df) + 1)
    return {
        "available": True,
        "frame": df,
        "median_oas_bp": float(df["oas_bp"].median()),
        "median_excess_compensation_bp": float(df["excess_compensation_bp"].median()),
    }


def credit_research_scenario_engine(
    scenarios: pd.DataFrame,
    rate_duration: float,
    spread_duration: float,
    convexity: float,
    notional: float,
    liquidity_cost_bp: float = 0.0,
) -> dict[str, Any]:
    """Probability-weighted total-return decomposition for a cash credit position."""
    if scenarios is None or scenarios.empty:
        return {"available": False, "reason": "Scenario table is empty", "frame": pd.DataFrame()}
    df = scenarios.copy()
    if "scenario" not in df:
        df["scenario"] = [f"Scenario {i + 1}" for i in range(len(df))]
    defaults = {
        "probability_pct": 0.0, "rate_shock_bp": 0.0, "spread_shock_bp": 0.0,
        "default_rate_pct": 0.0, "recovery_pct": 40.0, "carry_roll_bp": 0.0,
    }
    for column, default in defaults.items():
        if column not in df:
            df[column] = default
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(default)
    probability = df["probability_pct"].clip(lower=0)
    if probability.sum() <= 0:
        probability = pd.Series(1.0, index=df.index)
    df["probability"] = probability / probability.sum()
    dy = df["rate_shock_bp"] / 10000.0
    df["rate_return_pct"] = (-float(rate_duration) * dy + 0.5 * float(convexity) * dy.pow(2)) * 100.0
    df["spread_return_pct"] = -float(spread_duration) * df["spread_shock_bp"] / 100.0
    df["carry_roll_return_pct"] = df["carry_roll_bp"] / 100.0
    df["default_loss_pct"] = -df["default_rate_pct"].clip(lower=0) * (1.0 - df["recovery_pct"].clip(0, 100) / 100.0)
    df["liquidity_drag_pct"] = -float(liquidity_cost_bp) / 100.0
    components = ["rate_return_pct", "spread_return_pct", "carry_roll_return_pct", "default_loss_pct", "liquidity_drag_pct"]
    df["total_return_pct"] = df[components].sum(axis=1)
    df["pnl"] = float(notional) * df["total_return_pct"] / 100.0
    weighted = {column: float((df[column] * df["probability"]).sum()) for column in components}
    expected_return = float((df["total_return_pct"] * df["probability"]).sum())
    downside = df.loc[df["total_return_pct"] < 0]
    downside_return = (
        float((downside["total_return_pct"] * downside["probability"]).sum() / downside["probability"].sum())
        if not downside.empty and downside["probability"].sum() > 0 else 0.0
    )
    return {
        "available": True,
        "frame": df,
        "expected_return_pct": expected_return,
        "expected_pnl": float(notional) * expected_return / 100.0,
        "worst_return_pct": float(df["total_return_pct"].min()),
        "worst_pnl": float(df["pnl"].min()),
        "downside_return_pct": downside_return,
        "probability_of_loss": float(df.loc[df["total_return_pct"] < 0, "probability"].sum()),
        "weighted_components": weighted,
    }


def credit_research_evidence_score(frame: pd.DataFrame) -> dict[str, Any]:
    """Weighted evidence ledger with freshness, reliability and direction."""
    if frame is None or frame.empty:
        return {"score": 50.0, "coverage": 0.0, "stale_ratio": 1.0, "frame": pd.DataFrame(), "by_category": pd.DataFrame()}
    df = frame.copy()
    for column, default in {"category": "Other", "claim": "", "source": "", "status": "OPEN"}.items():
        if column not in df:
            df[column] = default
        df[column] = df[column].fillna(default).astype(str)
    direction_map = {"BULL": 1.0, "POSITIVE": 1.0, "NEUTRAL": 0.0, "MIXED": 0.0, "BEAR": -1.0, "NEGATIVE": -1.0}
    if "direction" not in df:
        df["direction"] = "NEUTRAL"
    df["direction_value"] = df["direction"].astype(str).str.upper().map(direction_map).fillna(0.0)
    for column, default in {"confidence": 50.0, "reliability": 50.0, "materiality": 3.0, "age_days": 0.0}.items():
        if column not in df:
            df[column] = default
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(default)
    df["freshness_weight"] = np.exp(-df["age_days"].clip(lower=0) / 365.0)
    df["evidence_weight"] = (
        df["confidence"].clip(0, 100) / 100.0
        * df["reliability"].clip(0, 100) / 100.0
        * df["materiality"].clip(1, 5)
        * df["freshness_weight"]
    )
    df["weighted_signal"] = df["direction_value"] * df["evidence_weight"]
    denominator = float(df["evidence_weight"].sum())
    directional = float(df["weighted_signal"].sum() / denominator) if denominator > 0 else 0.0
    score = float(np.clip(50.0 + 50.0 * directional, 0.0, 100.0))
    categories = {"Fundamentals", "Valuation", "Liquidity", "Catalyst", "Documentation", "Macro"}
    coverage = len(categories.intersection(set(df["category"]))) / len(categories)
    stale_ratio = float((df["age_days"] > 180).mean())
    grouped = df.groupby("category", dropna=False).agg(
        evidence_weight=("evidence_weight", "sum"),
        weighted_signal=("weighted_signal", "sum"),
        items=("claim", "count"),
        avg_confidence=("confidence", "mean"),
    ).reset_index()
    grouped["category_score"] = np.where(
        grouped["evidence_weight"] > 0,
        50.0 + 50.0 * grouped["weighted_signal"] / grouped["evidence_weight"],
        50.0,
    ).clip(0, 100)
    return {"score": score, "coverage": coverage, "stale_ratio": stale_ratio, "frame": df, "by_category": grouped}


def _fic6_default_peers(issuer: str, sector: str = "Technology", rating: str = "BBB", oas_bp: float = 138.0, ytw_pct: float = 5.15, duration: float = 4.4, default_probability_pct: float = 0.75, recovery_pct: float = 40.0) -> pd.DataFrame:
    return pd.DataFrame([
        {"issuer": issuer or "Target Co", "security": "Senior 5Y", "rating": rating, "sector": sector, "oas_bp": float(oas_bp), "ytw_pct": float(ytw_pct), "duration": float(duration), "leverage": 2.2, "interest_coverage": 7.1, "liquidity_score": 78, "momentum_1m_bp": 6, "default_probability_pct": float(default_probability_pct), "recovery_pct": float(recovery_pct)},
        {"issuer": "Peer Alpha", "security": "Senior 2029", "rating": "BBB", "sector": sector, "oas_bp": 119, "ytw_pct": 4.91, "duration": 4.0, "leverage": 1.8, "interest_coverage": 8.5, "liquidity_score": 86, "momentum_1m_bp": -2, "default_probability_pct": 0.55, "recovery_pct": 40},
        {"issuer": "Peer Beta", "security": "Senior 2031", "rating": "BBB", "sector": sector, "oas_bp": 154, "ytw_pct": 5.33, "duration": 5.7, "leverage": 2.7, "interest_coverage": 5.8, "liquidity_score": 68, "momentum_1m_bp": 12, "default_probability_pct": 1.05, "recovery_pct": 40},
        {"issuer": "Peer Gamma", "security": "Senior 2030", "rating": "BBB", "sector": sector, "oas_bp": 126, "ytw_pct": 5.02, "duration": 4.9, "leverage": 2.0, "interest_coverage": 7.8, "liquidity_score": 82, "momentum_1m_bp": 1, "default_probability_pct": 0.65, "recovery_pct": 40},
        {"issuer": "Peer Delta", "security": "Senior 2033", "rating": "BBB", "sector": sector, "oas_bp": 171, "ytw_pct": 5.52, "duration": 6.4, "leverage": 3.1, "interest_coverage": 4.6, "liquidity_score": 61, "momentum_1m_bp": 18, "default_probability_pct": 1.35, "recovery_pct": 35},
        {"issuer": "Peer Epsilon", "security": "Senior 2028", "rating": "A", "sector": sector, "oas_bp": 84, "ytw_pct": 4.54, "duration": 3.2, "leverage": 1.3, "interest_coverage": 12.0, "liquidity_score": 91, "momentum_1m_bp": -4, "default_probability_pct": 0.25, "recovery_pct": 45},
        {"issuer": "Peer Zeta", "security": "Senior 2032", "rating": "BBB", "sector": sector, "oas_bp": 147, "ytw_pct": 5.25, "duration": 5.9, "leverage": 2.5, "interest_coverage": 6.2, "liquidity_score": 73, "momentum_1m_bp": 4, "default_probability_pct": 0.90, "recovery_pct": 40},
        {"issuer": "Peer Eta", "security": "Senior 2034", "rating": "BB", "sector": sector, "oas_bp": 286, "ytw_pct": 6.67, "duration": 6.8, "leverage": 4.1, "interest_coverage": 3.2, "liquidity_score": 55, "momentum_1m_bp": 24, "default_probability_pct": 3.20, "recovery_pct": 35},
    ])


def _fic6_reference_map() -> pd.DataFrame:
    return pd.DataFrame([
        {"domain": "Term structure", "institutional_reference": "NY Fed ACM term-premium model", "implementation_boundary": "Public ACM estimates are a macro cross-check; not an executable curve", "url": "https://www.newyorkfed.org/research/data_indicators/term-premia-tabs"},
        {"domain": "CDS conventions", "institutional_reference": "ISDA CDS Standard Model", "implementation_boundary": "This terminal remains screening-only until certified ISDA tie-out", "url": "https://www.cdsmodel.com/"},
        {"domain": "Rates / CSRBB", "institutional_reference": "Basel IRRBB / CSRBB framework", "implementation_boundary": "EVE, NII, basis and option risk require governed behavioural assumptions", "url": "https://www.bis.org/basel_framework/chapter/SRP/31.htm"},
        {"domain": "Liquidity", "institutional_reference": "FINRA TRACE", "implementation_boundary": "Trades are observations, not quotes; licensing and corrections remain explicit", "url": "https://www.finra.org/filing-reporting/trace"},
        {"domain": "Portfolio analytics", "institutional_reference": "LSEG Yield Book", "implementation_boundary": "Security master, curves, option models and large-scale production are provider capabilities", "url": "https://www.lseg.com/en/data-analytics/financial-data/analytics/fixed-income-analytics-yield-book"},
        {"domain": "Factor risk / optimization", "institutional_reference": "MSCI Fixed Income Analytics", "implementation_boundary": "Issuer curves, covariance, optimization and attribution require validated data/models", "url": "https://www.msci.com/data-and-analytics/fixed-income-offerings/fixed-income-analytics"},
        {"domain": "Spread decomposition", "institutional_reference": "Federal Reserve research on default vs liquidity components", "implementation_boundary": "Expected loss, liquidity and excess premium are shown separately", "url": "https://www.federalreserve.gov/econres/feds/effects-of-liquidity-on-the-nondefault-component-of-corporate-yield-spreads-evidence-from-intraday-transactions-data.htm"},
    ])


def _fic6_research_memo(
    issuer: str,
    security: str,
    analyst: str,
    decision: str,
    decision_score: float,
    scenario_result: Mapping[str, Any],
    selected_peer: Mapping[str, Any],
    evidence_result: Mapping[str, Any],
    thesis: str,
    catalysts: str,
    risks: str,
    invalidation: str,
) -> str:
    return f"""# Institutional Credit Research Pack

**Issuer:** {issuer}
**Security:** {security}
**Analyst / owner:** {analyst or "Unassigned"}
**Generated:** {datetime.now(timezone.utc).isoformat()}
**Decision:** {decision}
**Integrated score:** {decision_score:.1f}/100

## Market and relative value
- OAS: {_fmt_num(selected_peer.get("oas_bp"))} bp
- Peer-curve residual: {_fmt_num(selected_peer.get("curve_residual_bp"))} bp
- Expected-loss-adjusted compensation: {_fmt_num(selected_peer.get("excess_compensation_bp"))} bp
- Peer rank: {selected_peer.get("rank", "N/A")}

## Scenario distribution
- Probability-weighted return: {_fmt_num(scenario_result.get("expected_return_pct"))}%
- Probability of loss: {float(scenario_result.get("probability_of_loss", 0.0)):.1%}
- Worst scenario return: {_fmt_num(scenario_result.get("worst_return_pct"))}%
- Conditional downside: {_fmt_num(scenario_result.get("downside_return_pct"))}%

## Evidence governance
- Evidence score: {float(evidence_result.get("score", 50.0)):.1f}/100
- Category coverage: {float(evidence_result.get("coverage", 0.0)):.0%}
- Stale evidence ratio: {float(evidence_result.get("stale_ratio", 1.0)):.0%}

## Thesis
{thesis or "Not documented."}

## Catalysts
{catalysts or "Not documented."}

## Principal risks
{risks or "Not documented."}

## Invalidation / exit conditions
{invalidation or "Not documented."}

## Governance boundary
This pack is a research and decision-support artifact. Validate security terms, executable price,
market-data lineage, legal documentation, compliance, position limits, liquidity and independent
model approval before authorizing risk.
"""


def _fic_render_credit_research_360_v6() -> None:
    _fic_section("Credit Research 360 — Integrated Decision System")
    st.caption("Issuer research, relative value, scenario distribution, evidence governance and risk sizing in one auditable workflow.")

    identity = st.columns([1.25, 1.35, 1.0, 0.75, 0.85])
    issuer = identity[0].text_input("Issuer", "Target Co", key="fic6_issuer")
    security = identity[1].text_input("Security", "Senior unsecured 5Y", key="fic6_security")
    sector = identity[2].selectbox("Sector", ["Technology", "Industrials", "Financials", "Utilities", "Energy", "Consumer", "Healthcare", "Telecom", "Real Estate", "Other"], key="fic6_sector")
    rating = identity[3].selectbox("Rating", ["AAA", "AA", "A", "BBB", "BB", "B", "CCC", "NR"], index=3, key="fic6_rating")
    analyst = identity[4].text_input("Owner", "", key="fic6_owner")

    market = st.columns(6)
    price = market[0].number_input("Clean price", min_value=1.0, max_value=200.0, value=99.25, step=0.125, key="fic6_price")
    ytw = market[1].number_input("Yield to worst (%)", min_value=-5.0, max_value=40.0, value=5.15, step=0.05, key="fic6_ytw")
    oas = market[2].number_input("OAS (bp)", min_value=-500.0, max_value=5000.0, value=138.0, step=1.0, key="fic6_oas")
    fair_oas = market[3].number_input("Analyst fair OAS (bp)", min_value=-500.0, max_value=5000.0, value=120.0, step=1.0, key="fic6_fair_oas")
    rate_duration = market[4].number_input("Rate duration", min_value=0.0, max_value=30.0, value=4.2, step=0.1, key="fic6_rate_duration")
    spread_duration = market[5].number_input("Spread duration", min_value=0.0, max_value=30.0, value=4.4, step=0.1, key="fic6_spread_duration")

    risk_inputs = st.columns(7)
    convexity = risk_inputs[0].number_input("Convexity", min_value=-100.0, max_value=500.0, value=24.0, step=1.0, key="fic6_convexity")
    carry_roll = risk_inputs[1].number_input("12M carry + roll (bp)", min_value=-1000.0, max_value=3000.0, value=82.0, step=5.0, key="fic6_carry")
    notional = risk_inputs[2].number_input("Position notional", min_value=0.0, value=5_000_000.0, step=250_000.0, key="fic6_notional")
    base_pd = risk_inputs[3].number_input("12M PD (%)", min_value=0.0, max_value=100.0, value=0.75, step=0.05, key="fic6_pd")
    recovery = risk_inputs[4].number_input("Recovery (%)", min_value=0.0, max_value=100.0, value=40.0, step=1.0, key="fic6_recovery")
    liquidity_cost = risk_inputs[5].number_input("Round-trip liquidity (bp)", min_value=0.0, max_value=1000.0, value=18.0, step=1.0, key="fic6_liquidity")
    risk_budget = risk_inputs[6].number_input("Stress-loss budget", min_value=0.0, value=500_000.0, step=25_000.0, key="fic6_risk_budget")

    curve_result = _result_or_demo(_cached_us_curve(_start_date_for_years(5)), "curve")
    credit_result = _result_or_demo(_cached_credit(_start_date_for_years(5)), "credit")
    rates_regime = _fic_rates_regime(curve_result.frame) if curve_result.ok else {"label": "UNAVAILABLE", "score": 50.0, "drivers": []}
    credit_regime = _fic_credit_regime_v2(credit_result.frame) if credit_result.ok else {"label": "UNAVAILABLE", "score": 50.0, "drivers": []}
    regime_cards = st.columns(4)
    regime_cards[0].markdown(_fic_html_card("Rates regime", str(rates_regime["label"]), " · ".join(rates_regime.get("drivers", [])[:2]), "warn" if rates_regime["score"] > 65 else "good"), unsafe_allow_html=True)
    regime_cards[1].markdown(_fic_html_card("Credit regime", str(credit_regime["label"]), " · ".join(credit_regime.get("drivers", [])[:2]), "warn" if credit_regime["score"] > 65 else "good"), unsafe_allow_html=True)
    regime_cards[2].markdown(_fic_html_card("Valuation gap", f"{oas - fair_oas:+.0f} bp", "Observed OAS minus analyst fair OAS", "good" if oas > fair_oas else "warn"), unsafe_allow_html=True)
    breakeven = (carry_roll - base_pd / 100.0 * (1.0 - recovery / 100.0) * 10000.0 - liquidity_cost) / max(spread_duration, 0.01)
    regime_cards[3].markdown(_fic_html_card("Spread breakeven", f"{breakeven:.0f} bp", "Widening that consumes carry after expected loss and liquidity", "good" if breakeven > 0 else "bad"), unsafe_allow_html=True)

    tabs = st.tabs(["Decision cockpit", "Scenario & sizing", "Peer relative value", "Evidence & thesis", "Research pack"])

    default_scenarios = pd.DataFrame([
        {"scenario": "Bull / soft landing", "probability_pct": 20.0, "rate_shock_bp": -35.0, "spread_shock_bp": -45.0, "default_rate_pct": 0.15, "recovery_pct": recovery, "carry_roll_bp": carry_roll},
        {"scenario": "Base / carry", "probability_pct": 45.0, "rate_shock_bp": 0.0, "spread_shock_bp": 0.0, "default_rate_pct": base_pd, "recovery_pct": recovery, "carry_roll_bp": carry_roll},
        {"scenario": "Bear / slowdown", "probability_pct": 25.0, "rate_shock_bp": -50.0, "spread_shock_bp": 125.0, "default_rate_pct": max(2.0, base_pd * 2.5), "recovery_pct": max(20.0, recovery - 5.0), "carry_roll_bp": carry_roll * 0.70},
        {"scenario": "Severe recession", "probability_pct": 10.0, "rate_shock_bp": -125.0, "spread_shock_bp": 350.0, "default_rate_pct": max(7.0, base_pd * 6.0), "recovery_pct": max(10.0, recovery - 15.0), "carry_roll_bp": carry_roll * 0.35},
    ])
    with tabs[1]:
        st.markdown("#### Probability-weighted scenario distribution")
        scenario_input = st.data_editor(default_scenarios, width="stretch", hide_index=True, num_rows="dynamic", key="fic6_scenarios")
        scenario_result = credit_research_scenario_engine(scenario_input, rate_duration, spread_duration, convexity, notional, liquidity_cost)
        if not scenario_result["available"]:
            st.warning(scenario_result["reason"])
        else:
            sm = st.columns(6)
            sm[0].metric("Expected return", f"{scenario_result['expected_return_pct']:.2f}%")
            sm[1].metric("Expected P&L", f"{scenario_result['expected_pnl']:,.0f}")
            sm[2].metric("Probability of loss", f"{scenario_result['probability_of_loss']:.0%}")
            sm[3].metric("Conditional downside", f"{scenario_result['downside_return_pct']:.2f}%")
            sm[4].metric("Worst return", f"{scenario_result['worst_return_pct']:.2f}%")
            stress_unit = abs(scenario_result["worst_return_pct"]) / 100.0
            max_notional = risk_budget / stress_unit if stress_unit > 1e-9 else np.inf
            sm[5].metric("Risk-budget notional", f"{max_notional:,.0f}" if np.isfinite(max_notional) else "Unbounded")

            scenario_frame = scenario_result["frame"]
            left, right = st.columns([1.05, 1.0])
            with left:
                colors = ["#58e6ad" if x >= 0 else "#ff7272" for x in scenario_frame["total_return_pct"]]
                fig = go.Figure(go.Bar(x=scenario_frame["scenario"], y=scenario_frame["total_return_pct"], marker_color=colors, customdata=scenario_frame[["probability_pct", "pnl"]], hovertemplate="%{x}<br>Return %{y:.2f}%<br>Probability %{customdata[0]:.1f}%<br>P&L %{customdata[1]:,.0f}<extra></extra>"))
                fig.update_layout(template="plotly_dark", height=390, title="Scenario total return", yaxis_title="Return (%)", margin=dict(l=30, r=20, t=55, b=80))
                st.plotly_chart(fig, width="stretch")
            with right:
                rate_grid = np.array([-125, -75, -25, 0, 25, 75, 125], dtype=float)
                spread_grid = np.array([-100, -50, 0, 50, 100, 200, 350], dtype=float)
                z = np.zeros((len(rate_grid), len(spread_grid)))
                for i, r_shock in enumerate(rate_grid):
                    for j, s_shock in enumerate(spread_grid):
                        dy = r_shock / 10000.0
                        z[i, j] = (-rate_duration * dy + 0.5 * convexity * dy * dy) * 100.0 - spread_duration * s_shock / 100.0 + carry_roll / 100.0 - liquidity_cost / 100.0
                heat = go.Figure(go.Heatmap(z=z, x=spread_grid, y=rate_grid, colorscale="RdYlGn", zmid=0, colorbar_title="Return %", hovertemplate="Spread %{x:.0f} bp<br>Rates %{y:.0f} bp<br>Return %{z:.2f}%<extra></extra>"))
                heat.update_layout(template="plotly_dark", height=390, title="Rate × spread shock surface", xaxis_title="Spread shock (bp)", yaxis_title="Rate shock (bp)", margin=dict(l=50, r=20, t=55, b=45))
                st.plotly_chart(heat, width="stretch")
            scenario_display_columns = ["scenario", "probability_pct", "rate_shock_bp", "spread_shock_bp", "default_rate_pct", "recovery_pct", "carry_roll_bp", "total_return_pct", "pnl"]
            st.dataframe(scenario_frame[[c for c in scenario_display_columns if c in scenario_frame]], width="stretch", hide_index=True)
            _download_csv_button(scenario_frame, "credit_research_scenarios.csv", "fic6_scenario_download")

    with tabs[2]:
        st.markdown("#### Issuer curve, peer residual and compensation decomposition")
        upload = st.file_uploader("Optional peer universe CSV", type=["csv"], key="fic6_peer_upload")
        peer_seed = _fic6_default_peers(issuer, sector, rating, oas, ytw, spread_duration, base_pd, recovery)
        if upload is not None:
            try:
                peer_seed = pd.read_csv(upload)
            except Exception as exc:
                st.error(f"Peer file could not be read: {exc}")
        peer_input = st.data_editor(peer_seed, width="stretch", hide_index=True, num_rows="dynamic", key="fic6_peers")
        peer_result = credit_research_peer_screen(peer_input)
        if not peer_result["available"]:
            st.warning(peer_result["reason"])
            peer_frame = pd.DataFrame()
            selected_peer = {}
        else:
            peer_frame = peer_result["frame"]
            exact = peer_frame[peer_frame["issuer"].str.casefold() == str(issuer).casefold()]
            selected_peer = (exact.iloc[0] if not exact.empty else peer_frame.iloc[0]).to_dict()
            pm = st.columns(5)
            pm[0].metric("Peer rank", f"{int(selected_peer['rank'])}/{len(peer_frame)}")
            pm[1].metric("Curve residual", f"{selected_peer['curve_residual_bp']:+.0f} bp")
            pm[2].metric("Expected loss", f"{selected_peer['expected_loss_bp']:.0f} bp")
            pm[3].metric("Excess compensation", f"{selected_peer['excess_compensation_bp']:+.0f} bp")
            pm[4].metric("RV score", f"{selected_peer['research_score']:.0f}/100")

            left, right = st.columns(2)
            with left:
                scatter = go.Figure(go.Scatter(
                    x=peer_frame["leverage"], y=peer_frame["oas_bp"], mode="markers+text",
                    text=peer_frame["issuer"], textposition="top center",
                    marker=dict(size=np.clip(peer_frame["duration"] * 3.0, 9, 28), color=peer_frame["research_score"], colorscale="Turbo", cmin=0, cmax=100, showscale=True, colorbar_title="RV score", line=dict(width=1, color="rgba(255,255,255,.45)")),
                    customdata=peer_frame[["rating", "curve_residual_bp", "excess_compensation_bp"]],
                    hovertemplate="%{text}<br>Leverage %{x:.2f}x<br>OAS %{y:.0f} bp<br>Rating %{customdata[0]}<br>Curve residual %{customdata[1]:+.0f} bp<br>Excess comp %{customdata[2]:+.0f} bp<extra></extra>",
                ))
                scatter.update_layout(template="plotly_dark", height=430, title="OAS vs leverage · size = duration", xaxis_title="Net leverage (x)", yaxis_title="OAS (bp)")
                st.plotly_chart(scatter, width="stretch")
            with right:
                ordered = peer_frame.sort_values("curve_residual_bp")
                bar_colors = ["#58e6ad" if x > 0 else "#ff7272" for x in ordered["curve_residual_bp"]]
                residual = go.Figure(go.Bar(x=ordered["curve_residual_bp"], y=ordered["issuer"], orientation="h", marker_color=bar_colors))
                residual.add_vline(x=0, line_color="rgba(255,255,255,.4)")
                residual.update_layout(template="plotly_dark", height=430, title="Issuer-curve residual · positive = cheap", xaxis_title="Residual (bp)", margin=dict(l=90, r=20, t=55, b=40))
                st.plotly_chart(residual, width="stretch")
            display_columns = ["rank", "issuer", "security", "rating", "oas_bp", "ytw_pct", "duration", "expected_loss_bp", "liquidity_premium_bp", "excess_compensation_bp", "curve_fair_oas_bp", "curve_residual_bp", "research_score", "signal"]
            st.dataframe(peer_frame[[c for c in display_columns if c in peer_frame]], width="stretch", hide_index=True)
            _download_csv_button(peer_frame, "credit_peer_relative_value.csv", "fic6_peer_download")

    with tabs[3]:
        st.markdown("#### Fundamental scorecard and evidence ledger")
        fundamental_seed = pd.DataFrame([
            {"dimension": "Business resilience", "score": 72, "weight_pct": 15, "trend": "STABLE", "evidence": "Diversification, pricing power, cyclicality"},
            {"dimension": "Leverage / deleveraging", "score": 68, "weight_pct": 18, "trend": "IMPROVING", "evidence": "Net leverage path and debt paydown"},
            {"dimension": "Interest coverage", "score": 78, "weight_pct": 12, "trend": "STABLE", "evidence": "EBITDA / cash interest and fixed-charge coverage"},
            {"dimension": "Free cash flow", "score": 74, "weight_pct": 15, "trend": "IMPROVING", "evidence": "FCF conversion after capex and working capital"},
            {"dimension": "Liquidity / maturity wall", "score": 70, "weight_pct": 15, "trend": "STABLE", "evidence": "Cash, revolver, covenants and refinancing schedule"},
            {"dimension": "Asset protection / recovery", "score": 58, "weight_pct": 10, "trend": "STABLE", "evidence": "Collateral, seniority, guarantees and structural subordination"},
            {"dimension": "Management / governance", "score": 66, "weight_pct": 8, "trend": "MIXED", "evidence": "Financial policy, M&A and shareholder distributions"},
            {"dimension": "Event / documentation risk", "score": 62, "weight_pct": 7, "trend": "MIXED", "evidence": "Covenants, portability, restricted payments and change of control"},
        ])
        fundamentals = st.data_editor(fundamental_seed, width="stretch", hide_index=True, num_rows="dynamic", key="fic6_fundamentals")
        if fundamentals.empty:
            fundamentals = fundamental_seed.copy()
        fscore = pd.to_numeric(fundamentals.get("score"), errors="coerce").fillna(50).clip(0, 100)
        fweight = pd.to_numeric(fundamentals.get("weight_pct"), errors="coerce").fillna(0).clip(lower=0)
        fundamental_score = float((fscore * fweight).sum() / fweight.sum()) if fweight.sum() > 0 else 50.0

        evidence_seed = pd.DataFrame([
            {"category": "Fundamentals", "claim": "Leverage declines over the next four quarters", "source": "Company filings / model", "direction": "BULL", "confidence": 75, "reliability": 85, "materiality": 5, "age_days": 25, "status": "OPEN"},
            {"category": "Valuation", "claim": "Bond screens wide to the fitted issuer/peer curve", "source": "Peer RV screen", "direction": "BULL", "confidence": 70, "reliability": 75, "materiality": 4, "age_days": 1, "status": "OPEN"},
            {"category": "Liquidity", "claim": "Executable depth is adequate for proposed size", "source": "TRACE / dealer runs", "direction": "NEUTRAL", "confidence": 55, "reliability": 60, "materiality": 4, "age_days": 3, "status": "VERIFY"},
            {"category": "Catalyst", "claim": "Refinancing removes near-term maturity concentration", "source": "Treasury plan", "direction": "BULL", "confidence": 60, "reliability": 65, "materiality": 4, "age_days": 40, "status": "OPEN"},
            {"category": "Documentation", "claim": "Structural subordination limits recovery", "source": "Indenture / org chart", "direction": "BEAR", "confidence": 80, "reliability": 90, "materiality": 5, "age_days": 90, "status": "OPEN"},
            {"category": "Macro", "claim": "Sector earnings remain sensitive to a hard landing", "source": "Macro scenario", "direction": "BEAR", "confidence": 65, "reliability": 70, "materiality": 4, "age_days": 12, "status": "OPEN"},
        ])
        evidence_input = st.data_editor(evidence_seed, width="stretch", hide_index=True, num_rows="dynamic", key="fic6_evidence")
        evidence_result = credit_research_evidence_score(evidence_input)
        em = st.columns(4)
        em[0].metric("Fundamental score", f"{fundamental_score:.0f}/100")
        em[1].metric("Evidence score", f"{evidence_result['score']:.0f}/100")
        em[2].metric("Category coverage", f"{evidence_result['coverage']:.0%}")
        em[3].metric("Stale evidence", f"{evidence_result['stale_ratio']:.0%}")

        left, right = st.columns(2)
        with left:
            radar = go.Figure(go.Scatterpolar(r=fscore.tolist() + [float(fscore.iloc[0])], theta=fundamentals["dimension"].astype(str).tolist() + [str(fundamentals["dimension"].iloc[0])], fill="toself", line_color="#5be7ff", fillcolor="rgba(91,231,255,.15)", name="Score"))
            radar.update_layout(template="plotly_dark", height=430, title="Fundamental resilience map", polar=dict(radialaxis=dict(range=[0, 100], showticklabels=True)))
            st.plotly_chart(radar, width="stretch")
        with right:
            grouped = evidence_result["by_category"]
            ev = go.Figure(go.Bar(x=grouped["category"], y=grouped["category_score"], marker_color=["#58e6ad" if x >= 55 else "#ff7272" if x < 45 else "#f2c96d" for x in grouped["category_score"]]))
            ev.add_hline(y=50, line_dash="dot", line_color="rgba(255,255,255,.45)")
            ev.update_layout(template="plotly_dark", height=430, title="Evidence score by category", yaxis=dict(range=[0, 100]), yaxis_title="Score")
            st.plotly_chart(ev, width="stretch")

        st.markdown("#### Thesis, catalysts and invalidation")
        narrative = st.columns(2)
        thesis = narrative[0].text_area("Core thesis", height=130, key="fic6_thesis")
        catalysts_text = narrative[1].text_area("Catalysts / path to fair value", height=130, key="fic6_catalysts")
        risks_text = narrative[0].text_area("Principal risks / variant perception", height=130, key="fic6_risks")
        invalidation = narrative[1].text_area("Invalidation and exit rules", height=130, key="fic6_invalidation")
        event_seed = pd.DataFrame([
            {"event": "Earnings / guidance", "horizon": "0-3M", "probability_pct": 80, "spread_impact_bp": -15, "owner": analyst, "mitigant": "Size below stress budget"},
            {"event": "Refinancing", "horizon": "3-9M", "probability_pct": 60, "spread_impact_bp": -25, "owner": analyst, "mitigant": "Track tender and secured capacity"},
            {"event": "Downside covenant / M&A event", "horizon": "0-12M", "probability_pct": 20, "spread_impact_bp": 90, "owner": analyst, "mitigant": "Documentation review / hedge"},
        ])
        event_ledger = st.data_editor(event_seed, width="stretch", hide_index=True, num_rows="dynamic", key="fic6_events")
        _download_csv_button(evidence_result["frame"], "credit_research_evidence_ledger.csv", "fic6_evidence_download")

    if not scenario_result.get("available"):
        scenario_result = {"expected_return_pct": 0.0, "worst_return_pct": 0.0, "probability_of_loss": 0.0, "downside_return_pct": 0.0, "expected_pnl": 0.0, "worst_pnl": 0.0, "weighted_components": {}}
    if not peer_result.get("available"):
        selected_peer = {"oas_bp": oas, "curve_residual_bp": oas - fair_oas, "excess_compensation_bp": oas - base_pd / 100 * (1 - recovery / 100) * 10000, "research_score": 50.0, "rank": "N/A"}

    valuation_score = float(np.clip(50.0 + (oas - fair_oas) * 0.35 + float(selected_peer.get("curve_residual_bp", 0.0)) * 0.15, 0, 100))
    scenario_score = float(np.clip(55.0 + scenario_result["expected_return_pct"] * 4.0 + scenario_result["worst_return_pct"] * 1.7, 0, 100))
    peer_score = float(selected_peer.get("research_score", 50.0))
    evidence_score = float(evidence_result["score"])
    integrated_score = float(0.24 * valuation_score + 0.22 * fundamental_score + 0.18 * peer_score + 0.18 * scenario_score + 0.18 * evidence_score)
    hard_stop = scenario_result["worst_pnl"] < -risk_budget if risk_budget > 0 else False
    if hard_stop:
        decision = "REDUCE SIZE / HEDGE"
    elif integrated_score >= 72 and scenario_result["expected_return_pct"] > 0:
        decision = "ACCUMULATE — HIGH CONVICTION"
    elif integrated_score >= 60:
        decision = "BUY / ADD ON TERMS"
    elif integrated_score >= 45:
        decision = "HOLD / WATCH"
    else:
        decision = "AVOID / REDUCE"

    with tabs[0]:
        st.markdown("#### Integrated recommendation")
        state = "bad" if hard_stop else "good" if integrated_score >= 60 else "warn"
        decision_cards = st.columns(4)
        decision_cards[0].markdown(_fic_html_card("Decision", decision, "Hard stops override the numerical score", state), unsafe_allow_html=True)
        decision_cards[1].markdown(_fic_html_card("Integrated score", f"{integrated_score:.1f}/100", "Valuation · fundamentals · peers · scenarios · evidence", state), unsafe_allow_html=True)
        decision_cards[2].markdown(_fic_html_card("Expected return", f"{scenario_result['expected_return_pct']:.2f}%", f"Probability of loss {scenario_result['probability_of_loss']:.0%}", "good" if scenario_result["expected_return_pct"] > 0 else "bad"), unsafe_allow_html=True)
        decision_cards[3].markdown(_fic_html_card("Stress budget", "BREACH" if hard_stop else "PASS", f"Worst P&L {scenario_result['worst_pnl']:,.0f} vs budget {risk_budget:,.0f}", "bad" if hard_stop else "good"), unsafe_allow_html=True)

        components = pd.DataFrame({
            "dimension": ["Valuation", "Fundamentals", "Peer RV", "Scenario distribution", "Evidence quality"],
            "score": [valuation_score, fundamental_score, peer_score, scenario_score, evidence_score],
            "weight_pct": [24, 22, 18, 18, 18],
        })
        components["weighted_contribution"] = components["score"] * components["weight_pct"] / 100.0
        left, right = st.columns([1.0, 1.15])
        with left:
            st.dataframe(components, width="stretch", hide_index=True)
            st.markdown("#### Decision protocol")
            protocol = pd.DataFrame([
                {"gate": "Market data and security terms", "state": "VERIFY", "owner": "Trading / operations"},
                {"gate": "Fundamental thesis and variant perception", "state": "DOCUMENTED" if thesis else "OPEN", "owner": analyst or "Research"},
                {"gate": "Scenario loss within budget", "state": "FAIL" if hard_stop else "PASS", "owner": "Risk"},
                {"gate": "Liquidity and executable size", "state": "VERIFY", "owner": "Trading"},
                {"gate": "Legal / covenant / compliance review", "state": "VERIFY", "owner": "Legal / compliance"},
                {"gate": "Independent challenge", "state": "OPEN", "owner": "Investment committee"},
            ])
            st.dataframe(protocol, width="stretch", hide_index=True)
        with right:
            contribution = go.Figure(go.Bar(x=components["dimension"], y=components["weighted_contribution"], marker_color=["#5be7ff", "#4b7dff", "#58e6ad", "#f2c96d", "#b084ff"]))
            contribution.update_layout(template="plotly_dark", height=330, title="Decision-score contributions", yaxis_title="Weighted points")
            st.plotly_chart(contribution, width="stretch")
            wc = scenario_result.get("weighted_components", {})
            labels = ["Carry + roll", "Rates", "Spread", "Default", "Liquidity"]
            values = [wc.get("carry_roll_return_pct", 0.0), wc.get("rate_return_pct", 0.0), wc.get("spread_return_pct", 0.0), wc.get("default_loss_pct", 0.0), wc.get("liquidity_drag_pct", 0.0)]
            waterfall = go.Figure(go.Waterfall(x=labels, y=values, measure=["relative"] * len(labels), connector={"line": {"color": "rgba(255,255,255,.25)"}}, increasing={"marker": {"color": "#58e6ad"}}, decreasing={"marker": {"color": "#ff7272"}}))
            waterfall.update_layout(template="plotly_dark", height=330, title="Expected-return decomposition", yaxis_title="Return contribution (%)")
            st.plotly_chart(waterfall, width="stretch")
        st.markdown("<div class='fic2-method'>The recommendation is deliberately transparent. It combines market compensation, issuer fundamentals, fitted peer residuals, probability-weighted losses and evidence quality. It is not a rating, executable quote or authorization to trade.</div>", unsafe_allow_html=True)

    with tabs[4]:
        st.markdown("#### Committee-ready research pack")
        memo = _fic6_research_memo(issuer, security, analyst, decision, integrated_score, scenario_result, selected_peer, evidence_result, thesis, catalysts_text, risks_text, invalidation)
        pack = {
            "metadata": {"issuer": issuer, "security": security, "sector": sector, "rating": rating, "analyst": analyst, "generated_at": datetime.now(timezone.utc).isoformat(), "module_version": MODULE_VERSION},
            "decision": {"label": decision, "integrated_score": integrated_score, "hard_stop": hard_stop, "valuation_score": valuation_score, "fundamental_score": fundamental_score, "peer_score": peer_score, "scenario_score": scenario_score, "evidence_score": evidence_score},
            "market": {"price": price, "ytw_pct": ytw, "oas_bp": oas, "fair_oas_bp": fair_oas, "rate_duration": rate_duration, "spread_duration": spread_duration, "convexity": convexity, "carry_roll_bp": carry_roll, "pd_pct": base_pd, "recovery_pct": recovery, "liquidity_cost_bp": liquidity_cost},
            "scenario_summary": {k: v for k, v in scenario_result.items() if k not in {"frame", "weighted_components"}},
            "selected_peer": {k: (v.item() if hasattr(v, "item") else v) for k, v in selected_peer.items()},
            "evidence_summary": {"score": evidence_result["score"], "coverage": evidence_result["coverage"], "stale_ratio": evidence_result["stale_ratio"]},
        }
        actions = st.columns(3)
        actions[0].download_button("Download IC memo (.md)", memo, file_name="credit_research_pack.md", mime="text/markdown", key="fic6_memo_download")
        actions[1].download_button("Download decision record (.json)", json.dumps(pack, indent=2, default=str), file_name="credit_decision_record.json", mime="application/json", key="fic6_json_download")
        actions[2].download_button("Download catalyst ledger (.csv)", event_ledger.to_csv(index=False), file_name="credit_catalyst_ledger.csv", mime="text/csv", key="fic6_event_download")
        with st.expander("Research pack preview", expanded=True):
            st.markdown(memo)
        with st.expander("Institutional reference architecture"):
            st.dataframe(_fic6_reference_map(), width="stretch", hide_index=True)
            st.caption("References define target capabilities and production boundaries. Public data and screening analytics remain visibly distinct from licensed pricing, security-master, legal and certified risk engines.")



# ============================================================================
# V7 DECISION INTELLIGENCE: ISSUER, PORTFOLIO CONSTRUCTION, PIT GOVERNANCE
# ============================================================================

_FIC7_FUNDAMENTAL_TAGS: dict[str, tuple[list[str], str]] = {
    "revenue": (["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"], "flow"),
    "operating_income": (["OperatingIncomeLoss"], "flow"),
    "depreciation_amortization": (["DepreciationDepletionAndAmortization", "DepreciationDepletionAndAmortizationPropertyPlantAndEquipment"], "flow"),
    "operating_cash_flow": (["NetCashProvidedByUsedInOperatingActivities"], "flow"),
    "capex": (["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsForAdditionsToPropertyPlantAndEquipment"], "flow"),
    "total_debt": (["LongTermDebtAndFinanceLeaseObligationsCurrent", "LongTermDebtCurrent", "ShortTermBorrowings"], "instant_current_debt"),
    "long_term_debt": (["LongTermDebtAndFinanceLeaseObligationsNoncurrent", "LongTermDebtNoncurrent"], "instant"),
    "cash": (["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"], "instant"),
    "interest_expense": (["InterestExpenseNonOperating", "InterestExpenseDebt", "InterestAndDebtExpense"], "flow"),
    "current_assets": (["AssetsCurrent"], "instant"),
    "current_liabilities": (["LiabilitiesCurrent"], "instant"),
}


def _fic7_sec_metric_series(frame: pd.DataFrame, tags: Sequence[str], metric_kind: str) -> pd.DataFrame:
    columns = ["end", "value", "filed", "tag", "accn"]
    if frame is None or frame.empty or "tag" not in frame.columns:
        return pd.DataFrame(columns=columns)
    work = frame.loc[frame["tag"].isin(list(tags))].copy()
    if work.empty:
        return pd.DataFrame(columns=columns)
    if "unit" in work.columns:
        work = work.loc[work["unit"].astype(str).str.upper().eq("USD")]
    work["end"] = pd.to_datetime(work.get("end"), errors="coerce")
    work["start"] = pd.to_datetime(work.get("start"), errors="coerce")
    work["filed"] = pd.to_datetime(work.get("filed"), errors="coerce")
    work["value"] = pd.to_numeric(work.get("value"), errors="coerce")
    work = work.dropna(subset=["end", "value"])
    if "flow" in metric_kind:
        days = (work["end"] - work["start"]).dt.days
        work = work.loc[days.between(250, 400, inclusive="both")]
    if "form" in work.columns:
        work = work.loc[work["form"].astype(str).isin(["10-K", "20-F", "40-F"])]
    priority = {tag: i for i, tag in enumerate(tags)}
    work["_priority"] = work["tag"].map(priority).fillna(len(priority))
    work = work.sort_values(["end", "_priority", "filed"], ascending=[True, True, False])
    work = work.drop_duplicates("end", keep="first")
    return work.reindex(columns=columns).reset_index(drop=True)


def issuer_fundamental_history(companyfacts: pd.DataFrame) -> pd.DataFrame:
    """Build annual issuer credit fundamentals with filing-date provenance."""
    merged: pd.DataFrame | None = None
    for metric, (tags, kind) in _FIC7_FUNDAMENTAL_TAGS.items():
        series = _fic7_sec_metric_series(companyfacts, tags, kind)
        series = series.rename(
            columns={
                "value": metric,
                "filed": f"{metric}_filed",
                "tag": f"{metric}_tag",
                "accn": f"{metric}_accn",
            }
        )
        merged = series if merged is None else merged.merge(series, on="end", how="outer")
    if merged is None or merged.empty:
        return pd.DataFrame()
    merged = merged.sort_values("end").reset_index(drop=True)
    current_debt = pd.to_numeric(merged.get("total_debt"), errors="coerce").fillna(0.0)
    long_debt = pd.to_numeric(merged.get("long_term_debt"), errors="coerce").fillna(0.0)
    merged["total_debt"] = current_debt + long_debt
    merged["ebitda_proxy"] = pd.to_numeric(merged.get("operating_income"), errors="coerce") + pd.to_numeric(
        merged.get("depreciation_amortization"), errors="coerce"
    )
    merged["fcf_proxy"] = pd.to_numeric(merged.get("operating_cash_flow"), errors="coerce") - pd.to_numeric(
        merged.get("capex"), errors="coerce"
    ).abs()
    merged["net_debt"] = merged["total_debt"] - pd.to_numeric(merged.get("cash"), errors="coerce")
    ebitda = merged["ebitda_proxy"].replace(0.0, np.nan)
    interest = pd.to_numeric(merged.get("interest_expense"), errors="coerce").abs().replace(0.0, np.nan)
    merged["net_leverage"] = merged["net_debt"] / ebitda
    merged["gross_leverage"] = merged["total_debt"] / ebitda
    merged["interest_coverage"] = ebitda / interest
    merged["current_ratio"] = pd.to_numeric(merged.get("current_assets"), errors="coerce") / pd.to_numeric(
        merged.get("current_liabilities"), errors="coerce"
    ).replace(0.0, np.nan)
    merged["fcf_to_debt"] = merged["fcf_proxy"] / merged["total_debt"].replace(0.0, np.nan)
    filed_cols = [col for col in merged.columns if col.endswith("_filed")]
    merged["information_available_date"] = merged[filed_cols].max(axis=1) if filed_cols else pd.NaT
    return merged


def refinancing_schedule_analytics(
    schedule: pd.DataFrame,
    cash: float = 0.0,
    revolver: float = 0.0,
    annual_fcf: float = 0.0,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Compatibility facade backed by the modular refinancing engine."""
    from fixed_income.analytics.refinancing import analyze_refinancing_schedule

    return analyze_refinancing_schedule(schedule, cash, revolver, annual_fcf)

def _fic7_bounded_simplex(values: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> np.ndarray:
    weights = np.clip(np.asarray(values, dtype=float), lower, upper)
    for _ in range(200):
        residual = 1.0 - float(weights.sum())
        if abs(residual) < 1e-10:
            break
        slack = (upper - weights) if residual > 0 else (weights - lower)
        available = float(np.maximum(slack, 0.0).sum())
        if available <= 1e-12:
            break
        weights = weights + residual * np.maximum(slack, 0.0) / available
        weights = np.clip(weights, lower, upper)
    return weights


def _fic7_apply_sector_cap(
    weights: np.ndarray,
    sectors: Sequence[str],
    lower: np.ndarray,
    upper: np.ndarray,
    sector_cap: float,
) -> np.ndarray:
    weights = _fic7_bounded_simplex(weights, lower, upper)
    sector_array = np.asarray(list(sectors), dtype=object)
    for _ in range(80):
        changed = False
        for sector in pd.unique(sector_array):
            idx = np.where(sector_array == sector)[0]
            total = float(weights[idx].sum())
            if total > sector_cap + 1e-10:
                excess = total - sector_cap
                adjustable = np.maximum(weights[idx] - lower[idx], 0.0)
                if adjustable.sum() > 0:
                    weights[idx] -= excess * adjustable / adjustable.sum()
                outside = np.where(sector_array != sector)[0]
                slack = np.maximum(upper[outside] - weights[outside], 0.0)
                if slack.sum() > 0:
                    weights[outside] += excess * slack / slack.sum()
                changed = True
        weights = _fic7_bounded_simplex(weights, lower, upper)
        if not changed:
            break
    return weights


def fixed_income_portfolio_optimizer(
    universe: pd.DataFrame,
    objective: str = "Risk-adjusted",
    risk_aversion: float = 6.0,
    turnover_cost_bp: float = 15.0,
    sector_cap_pct: float = 35.0,
    nav: float = 100_000_000.0,
) -> dict[str, Any]:
    """Compatibility facade backed by the modular constrained optimizer."""
    from fixed_income.analytics.portfolio import optimize_portfolio

    return optimize_portfolio(
        universe,
        objective=objective,
        risk_aversion=risk_aversion,
        turnover_cost_bp=turnover_cost_bp,
        sector_cap_pct=sector_cap_pct,
        nav=nav,
    )

def decision_journal_diagnostics(
    journal: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Compatibility facade backed by the modular decision engine."""
    from fixed_income.research.decision import diagnose_decisions

    return diagnose_decisions(journal)

def point_in_time_leakage_audit(
    observations: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Compatibility facade backed by the modular point-in-time control."""
    from fixed_income.research.decision import audit_point_in_time

    return audit_point_in_time(observations)

def _fic7_money(value: Any) -> str:
    x = _safe_float(value)
    if x is None:
        return "N/A"
    for scale, suffix in [(1e12, "tn"), (1e9, "bn"), (1e6, "mm")]:
        if abs(x) >= scale:
            return f"{x / scale:,.2f} {suffix}"
    return f"{x:,.0f}"


def _fic7_metric(value: Any, digits: int = 2, suffix: str = "") -> str:
    x = _safe_float(value)
    return "N/A" if x is None else f"{x:,.{digits}f}{suffix}"


def _fic7_issuer_score(latest: pd.Series) -> tuple[float, str]:
    leverage = _safe_float(latest.get("net_leverage"), 5.0)
    coverage = _safe_float(latest.get("interest_coverage"), 0.0)
    liquidity = _safe_float(latest.get("current_ratio"), 0.0)
    fcf = _safe_float(latest.get("fcf_to_debt"), -0.2)
    score = 50.0
    score += np.clip((4.0 - leverage) * 8.0, -24.0, 24.0)
    score += np.clip((coverage - 2.0) * 4.0, -16.0, 20.0)
    score += np.clip((liquidity - 1.0) * 12.0, -12.0, 12.0)
    score += np.clip(fcf * 50.0, -10.0, 15.0)
    score = float(np.clip(score, 0.0, 100.0))
    label = "Strong" if score >= 70 else "Balanced" if score >= 50 else "Fragile"
    return score, label


def _fic7_workspace_header(title: str, subtitle: str, boundary: str) -> None:
    _fic_section(title)
    st.caption(subtitle)
    st.caption("Control boundary · " + boundary)


def _fic7_date(value: Any) -> str:
    stamp = pd.to_datetime(value, errors="coerce")
    return "N/A" if pd.isna(stamp) else stamp.date().isoformat()


def _fic_render_issuer_research_pro_v7() -> None:
    _fic7_workspace_header(
        "Issuer Research Pro",
        "SEC filing history, refinancing wall, rate/spread shocks, covenant headroom and exportable evidence.",
        "Observed SEC facts and analyst-supplied capital-structure assumptions remain visibly separated.",
    )
    left, right = st.columns([1.0, 2.2], vertical_alignment="bottom")
    default_ticker = str(st.session_state.get("fic7_issuer_ticker", st.session_state.get("ticker", "NVDA")) or "NVDA")
    ticker = left.text_input("US issuer ticker", value=default_ticker, key="fic7_issuer_ticker").strip().upper()
    right.caption("Source: SEC CompanyFacts. Configure SEC_USER_AGENT with a monitored contact address for production use.")
    result = _cached_sec_companyfacts(ticker) if ticker else DataResult(errors=["Ticker is required."])
    if result.errors:
        st.error("SEC adapter: " + " | ".join(result.errors))
    if result.warnings:
        st.warning(" | ".join(result.warnings))
    if "contact@example.com" in sec_user_agent():
        st.warning("Production control: replace the default SEC_USER_AGENT contact before operational deployment.")
    history = issuer_fundamental_history(result.frame) if result.ok else pd.DataFrame()
    overview, maturity, covenants, evidence = st.tabs(
        ["Fundamental trajectory", "Maturity & refinancing", "Covenants", "Evidence export"]
    )
    with overview:
        if history.empty:
            st.info("No annual filing history is available for this ticker. No synthetic fundamentals were substituted.")
        else:
            latest = history.dropna(subset=["end"]).iloc[-1]
            score, score_label = _fic7_issuer_score(latest)
            cols = st.columns(6)
            cols[0].metric("Credit score", f"{score:.0f}/100", score_label)
            cols[1].metric("Net leverage", _fic7_metric(latest.get("net_leverage"), 2, "x"))
            cols[2].metric("Interest coverage", _fic7_metric(latest.get("interest_coverage"), 2, "x"))
            cols[3].metric("Current ratio", _fic7_metric(latest.get("current_ratio"), 2, "x"))
            cols[4].metric("FCF / debt", _fmt_pct(_safe_float(latest.get("fcf_to_debt"), np.nan), 1))
            cols[5].metric("Available from", _fic7_date(latest.get("information_available_date")))
            chart = go.Figure()
            chart.add_trace(go.Scatter(x=history["end"], y=history["net_leverage"], name="Net leverage", mode="lines+markers"))
            chart.add_trace(go.Scatter(x=history["end"], y=history["interest_coverage"], name="Interest coverage", mode="lines+markers", yaxis="y2"))
            chart.update_layout(
                template="plotly_dark", height=390, margin=dict(l=20, r=20, t=35, b=20),
                yaxis=dict(title="Net leverage (x)"),
                yaxis2=dict(title="Coverage (x)", overlaying="y", side="right"),
                legend=dict(orientation="h", y=1.12),
            )
            st.plotly_chart(chart, use_container_width=True, key="fic7_issuer_trajectory")
            view_cols = [
                "end", "information_available_date", "revenue", "ebitda_proxy", "fcf_proxy",
                "total_debt", "cash", "net_debt", "net_leverage", "interest_coverage",
                "current_ratio", "fcf_to_debt",
            ]
            st.dataframe(history[[c for c in view_cols if c in history.columns]].sort_values("end", ascending=False), use_container_width=True, hide_index=True)
    with maturity:
        latest_debt = float(history.iloc[-1].get("total_debt", 0.0)) if not history.empty and pd.notna(history.iloc[-1].get("total_debt")) else 0.0
        latest_cash = float(history.iloc[-1].get("cash", 0.0)) if not history.empty and pd.notna(history.iloc[-1].get("cash")) else 0.0
        latest_fcf = float(history.iloc[-1].get("fcf_proxy", 0.0)) if not history.empty and pd.notna(history.iloc[-1].get("fcf_proxy")) else 0.0
        schedule_key = "fic7_maturity_schedule"
        if schedule_key not in st.session_state:
            st.session_state[schedule_key] = pd.DataFrame(
                {
                    "year": list(range(pd.Timestamp.today().year + 1, pd.Timestamp.today().year + 7)),
                    "debt_due": [0.0] * 6,
                    "coupon_pct": [0.0] * 6,
                    "benchmark_pct": [0.0] * 6,
                    "current_spread_bp": [0.0] * 6,
                    "refi_spread_bp": [0.0] * 6,
                    "secured_pct": [0.0] * 6,
                }
            )
        b1, b2, b3 = st.columns([1.1, 1.1, 2.0])
        if b1.button("Load illustrative wall", key="fic7_load_wall"):
            proportions = np.array([0.10, 0.14, 0.18, 0.20, 0.20, 0.18])
            base = max(latest_debt, 1_000_000_000.0)
            st.session_state[schedule_key] = pd.DataFrame(
                {
                    "year": list(range(pd.Timestamp.today().year + 1, pd.Timestamp.today().year + 7)),
                    "debt_due": base * proportions,
                    "coupon_pct": [3.2, 3.6, 4.0, 4.3, 4.6, 4.8],
                    "benchmark_pct": [3.8, 3.7, 3.6, 3.5, 3.4, 3.4],
                    "current_spread_bp": [90, 100, 110, 120, 130, 140],
                    "refi_spread_bp": [120, 130, 145, 155, 165, 175],
                    "secured_pct": [0, 0, 20, 20, 30, 30],
                }
            )
            st.rerun()
        if b2.button("Reset blank", key="fic7_reset_wall"):
            st.session_state.pop(schedule_key, None)
            st.rerun()
        b3.warning("Illustrative wall = analyst scenario, not SEC-observed security-level maturities.")
        schedule = st.data_editor(
            st.session_state[schedule_key], use_container_width=True, num_rows="dynamic",
            key="fic7_maturity_editor", hide_index=True,
        )
        inputs = st.columns(3)
        revolver = inputs[0].number_input("Undrawn revolver", min_value=0.0, value=0.0, step=100_000_000.0, key="fic7_revolver")
        cash_input = inputs[1].number_input("Cash available", min_value=0.0, value=max(latest_cash, 0.0), step=100_000_000.0, key="fic7_cash")
        fcf_input = inputs[2].number_input("Annual FCF available", value=latest_fcf, step=100_000_000.0, key="fic7_fcf")
        analyzed, metrics = refinancing_schedule_analytics(schedule, cash_input, revolver, fcf_input)
        mcols = st.columns(5)
        mcols[0].metric("Debt due", _fic7_money(metrics["total_debt_due"]))
        mcols[1].metric("Next 24m", _fic7_money(metrics["next_24m_debt"]))
        mcols[2].metric("24m liquidity cover", _fic7_metric(metrics["liquidity_coverage_24m"], 2, "x"))
        mcols[3].metric("Incremental interest", _fic7_money(metrics["incremental_interest"]))
        mcols[4].metric("Weighted maturity", _fic7_metric(metrics["weighted_maturity_years"], 1, "y"))
        bar = go.Figure()
        bar.add_trace(go.Bar(x=analyzed["year"], y=analyzed["debt_due"], name="Debt due"))
        bar.add_trace(go.Scatter(x=analyzed["year"], y=analyzed["refi_rate_pct"], name="Refi rate", yaxis="y2", mode="lines+markers"))
        bar.update_layout(
            template="plotly_dark", height=380, margin=dict(l=20, r=20, t=35, b=20),
            yaxis=dict(title="Debt due"), yaxis2=dict(title="Refi rate (%)", overlaying="y", side="right"),
            legend=dict(orientation="h", y=1.12),
        )
        st.plotly_chart(bar, use_container_width=True, key="fic7_refi_wall")
        rate_shocks = np.array([-100, -50, 0, 50, 100, 150], dtype=float)
        spread_shocks = np.array([-50, 0, 50, 100, 150, 250], dtype=float)
        debt_24m = metrics["next_24m_debt"]
        heat = np.outer(spread_shocks + 0.0, np.ones(len(rate_shocks))) + np.outer(np.ones(len(spread_shocks)), rate_shocks)
        heat = debt_24m * heat / 10000.0
        heatmap = go.Figure(go.Heatmap(
            z=heat, x=[f"{x:+.0f}" for x in rate_shocks], y=[f"{x:+.0f}" for x in spread_shocks],
            colorbar=dict(title="Annual cost"), colorscale="RdYlGn_r",
            hovertemplate="Rate shock %{x} bp<br>Spread shock %{y} bp<br>Annual cost %{z:,.0f}<extra></extra>",
        ))
        heatmap.update_layout(template="plotly_dark", height=360, xaxis_title="Benchmark shock (bp)", yaxis_title="Refi spread shock (bp)", margin=dict(l=20, r=20, t=35, b=20))
        st.plotly_chart(heatmap, use_container_width=True, key="fic7_refi_heatmap")
        st.dataframe(analyzed, use_container_width=True, hide_index=True)
    with covenants:
        default_cov = pd.DataFrame(
            {
                "covenant": ["Net leverage", "Interest coverage", "Secured leverage"],
                "test_type": ["max", "min", "max"],
                "current": [3.0, 5.0, 1.2],
                "limit": [4.5, 2.5, 2.5],
                "stress_change": [0.8, -1.2, 0.5],
            }
        )
        st.warning("Covenant terms are analyst inputs. Validate definitions, baskets, cure rights and EBITDA add-backs against legal documents.")
        cov_input = st.data_editor(default_cov, use_container_width=True, num_rows="dynamic", key="fic7_covenant_editor", hide_index=True)
        try:
            cov_result = covenant_headroom_analysis(cov_input)
            st.dataframe(cov_result, use_container_width=True, hide_index=True)
        except Exception as exc:
            st.error(f"Covenant validation: {exc}")
    with evidence:
        if history.empty:
            st.info("Load a valid SEC issuer to generate a research evidence pack.")
        else:
            provenance_cols = ["end", "information_available_date"] + [
                col for col in history.columns if col.endswith("_tag") or col.endswith("_accn")
            ]
            st.dataframe(history[[c for c in provenance_cols if c in history.columns]].sort_values("end", ascending=False), use_container_width=True, hide_index=True)
            st.download_button(
                "Download fundamental history CSV", history.to_csv(index=False).encode("utf-8"),
                file_name=f"{ticker}_issuer_fundamentals.csv", mime="text/csv", key="fic7_download_fundamentals",
            )
            if result.monitor_rows():
                lineage = pd.DataFrame(result.monitor_rows())
                st.dataframe(lineage, use_container_width=True, hide_index=True)
                st.download_button(
                    "Download lineage CSV", lineage.to_csv(index=False).encode("utf-8"),
                    file_name=f"{ticker}_sec_lineage.csv", mime="text/csv", key="fic7_download_lineage",
                )


def _fic7_default_universe() -> pd.DataFrame:
    return pd.DataFrame(
        [
            ["UST-5Y", "US Treasury", "Sovereign", "AA+", 4.25, 3.5, 14, 0, 24, 4.5, 0.0, 1, 98],
            ["IG-TECH-A", "Alpha Tech", "Technology", "A", 5.45, 4.7, 14, 0, 22, 5.2, 5.0, 18, 82],
            ["IG-BANK-A", "Atlas Bank", "Financials", "A-", 5.85, 5.2, 14, 0, 22, 4.2, 4.0, 28, 78],
            ["IG-UTIL-BBB", "Grid Utility", "Utilities", "BBB", 6.15, 5.8, 14, 0, 20, 7.0, 6.8, 42, 70],
            ["IG-HC-BBB", "Health Core", "Healthcare", "BBB+", 5.75, 5.0, 14, 0, 20, 6.1, 5.8, 30, 76],
            ["HY-TEL-BB", "Metro Telecom", "Communications", "BB", 8.20, 8.8, 10, 0, 14, 4.8, 4.6, 145, 52],
            ["HY-IND-B", "Prime Industrial", "Industrials", "B+", 9.60, 11.5, 10, 0, 12, 3.7, 3.5, 265, 44],
            ["CASH", "Cash", "Liquidity", "NR", 3.90, 0.4, 10, 2, 30, 0.1, 0.0, 0, 100],
        ],
        columns=[
            "identifier", "issuer", "sector", "rating", "expected_return_pct", "volatility_pct",
            "current_weight_pct", "min_weight_pct", "max_weight_pct", "duration",
            "spread_duration", "expected_loss_bp", "liquidity_score",
        ],
    )


def _fic_render_portfolio_construction_v7() -> None:
    _fic7_workspace_header(
        "Portfolio Construction Lab",
        "Constraint-aware credit allocation, transparent factor covariance, turnover economics and trade list.",
        "Expected returns, volatility and loss estimates are analyst inputs; the optimizer is a decision aid, not an execution instruction.",
    )
    st.warning("EXPLICIT ILLUSTRATIVE INPUTS are loaded by default. Replace them with approved house forecasts before use.")
    uploaded = st.file_uploader("Upload universe CSV", type=["csv"], key="fic7_optimizer_upload")
    if uploaded is not None:
        try:
            base = pd.read_csv(uploaded)
        except Exception as exc:
            st.error(f"CSV import failed: {exc}")
            base = _fic7_default_universe()
    else:
        base = st.session_state.get("fic7_optimizer_universe", _fic7_default_universe())
    universe = st.data_editor(base, use_container_width=True, num_rows="dynamic", key="fic7_optimizer_editor", hide_index=True, height=360)
    st.session_state["fic7_optimizer_universe"] = universe
    c1, c2, c3, c4, c5 = st.columns(5)
    objective = c1.selectbox("Objective", ["Risk-adjusted", "Equal risk", "Carry / quality blend"], key="fic7_optimizer_objective")
    risk_aversion = c2.slider("Risk aversion", 1.0, 20.0, 6.0, 0.5, key="fic7_risk_aversion")
    turnover_cost = c3.number_input("Turnover cost (bp)", min_value=0.0, value=15.0, step=1.0, key="fic7_turnover_cost")
    sector_cap = c4.slider("Sector cap (%)", 10.0, 100.0, 35.0, 1.0, key="fic7_sector_cap")
    nav = c5.number_input("Portfolio NAV", min_value=1_000_000.0, value=100_000_000.0, step=5_000_000.0, key="fic7_nav")
    result = fixed_income_portfolio_optimizer(universe, objective, risk_aversion, turnover_cost, sector_cap, nav)
    if result.get("errors"):
        st.error(" | ".join(result["errors"]))
        return
    metrics = result["metrics"]
    cards = st.columns(8)
    labels = [
        ("Expected return", _fmt_pct(metrics["expected_return_pct"] / 100.0, 2)),
        ("Volatility", _fmt_pct(metrics["volatility_pct"] / 100.0, 2)),
        ("Return / risk", _fic7_metric(metrics["return_to_risk"], 2, "x")),
        ("Duration", _fmt_num(metrics["duration"], 2)),
        ("Spread duration", _fmt_num(metrics["spread_duration"], 2)),
        ("Expected loss", _fmt_num(metrics["expected_loss_bp"], 0) + " bp"),
        ("Turnover", _fmt_pct(metrics["turnover_pct"] / 100.0, 1)),
        ("Est. cost", _fic7_money(metrics["estimated_cost"])),
    ]
    for card, (label, value) in zip(cards, labels):
        card.metric(label, value)
    allocation, risk, audit = st.tabs(["Allocation & trades", "Risk structure", "Constraint audit"])
    assets = result["assets"]
    with allocation:
        fig = go.Figure()
        fig.add_trace(go.Bar(x=assets["identifier"], y=assets["current_weight_pct"], name="Current"))
        fig.add_trace(go.Bar(x=assets["identifier"], y=assets["optimized_weight_pct"], name="Optimized"))
        fig.update_layout(template="plotly_dark", height=390, barmode="group", yaxis_title="Weight (%)", margin=dict(l=20, r=20, t=35, b=20), legend=dict(orientation="h", y=1.12))
        st.plotly_chart(fig, use_container_width=True, key="fic7_optimizer_alloc")
        trade_cols = [
            "identifier", "issuer", "sector", "rating", "current_weight_pct", "optimized_weight_pct",
            "trade_weight_pct", "trade_amount", "expected_return_pct", "expected_loss_bp",
            "risk_contribution_pct", "active_return_contribution_bp",
        ]
        st.dataframe(assets[trade_cols].sort_values("trade_amount", ascending=False), use_container_width=True, hide_index=True)
        d1, d2 = st.columns(2)
        d1.download_button(
            "Download trade list CSV", assets.to_csv(index=False).encode("utf-8"),
            file_name="fixed_income_optimized_trades.csv", mime="text/csv", key="fic7_download_trades",
        )
        d2.download_button(
            "Download input template CSV", _fic7_default_universe().to_csv(index=False).encode("utf-8"),
            file_name="fixed_income_optimizer_template.csv", mime="text/csv", key="fic7_download_optimizer_template",
        )
    with risk:
        r1, r2 = st.columns([1.15, 1.0])
        risk_fig = go.Figure(go.Bar(
            x=assets["identifier"], y=assets["risk_contribution_pct"],
            marker_color=np.where(assets["risk_contribution_pct"] >= 0, "#38bdf8", "#fb7185"),
        ))
        risk_fig.update_layout(template="plotly_dark", height=390, yaxis_title="Contribution to variance (%)", margin=dict(l=20, r=20, t=35, b=20))
        r1.plotly_chart(risk_fig, use_container_width=True, key="fic7_risk_contrib")
        corr = result["correlation"]
        corr_fig = go.Figure(go.Heatmap(z=corr.values, x=corr.columns, y=corr.index, zmin=0, zmax=1, colorscale="Blues"))
        corr_fig.update_layout(template="plotly_dark", height=390, margin=dict(l=20, r=20, t=35, b=20))
        r2.plotly_chart(corr_fig, use_container_width=True, key="fic7_corr")
        st.caption("Covariance = input volatilities × transparent correlation kernel: 15% market + 25% same-sector + 20% duration proximity + diagonal idiosyncratic risk.")
    with audit:
        sectors = result["sectors"]
        st.dataframe(sectors, use_container_width=True, hide_index=True)
        if (sectors["headroom_pct"] < -1e-6).any():
            st.error("A sector limit is breached.")
        else:
            st.success("Individual bounds, fully-invested constraint and sector cap are satisfied.")
        st.json(
            {
                "objective": objective,
                "risk_aversion": risk_aversion,
                "turnover_cost_bp": turnover_cost,
                "sector_cap_pct": sector_cap,
                "long_only": True,
                "fully_invested": True,
                "covariance_model": "market + sector + duration-kernel + idiosyncratic",
            }
        )


def _fic7_blank_journal() -> pd.DataFrame:
    today = pd.Timestamp.today().normalize()
    return pd.DataFrame(
        {
            "decision_date": [pd.NaT] * 3,
            "review_date": [pd.NaT] * 3,
            "issuer": ["", "", ""],
            "instrument": ["", "", ""],
            "decision": ["HOLD", "HOLD", "HOLD"],
            "conviction_pct": [50.0, 50.0, 50.0],
            "entry_spread_bp": [np.nan, np.nan, np.nan],
            "exit_spread_bp": [np.nan, np.nan, np.nan],
            "status": ["OPEN", "OPEN", "OPEN"],
            "thesis": ["", "", ""],
            "invalidation_trigger": ["", "", ""],
        }
    )


def _fic7_blank_pit() -> pd.DataFrame:
    today = pd.Timestamp.today().normalize()
    return pd.DataFrame(
        {
            "series": ["", "", ""],
            "observation_date": [pd.NaT] * 3,
            "available_date": [pd.NaT] * 3,
            "decision_date": [pd.NaT] * 3,
            "value": [np.nan, np.nan, np.nan],
            "source": ["", "", ""],
        }
    )


def _fic_render_decision_journal_v7() -> None:
    _fic7_workspace_header(
        "Decision Journal & PIT Audit",
        "Close the research loop with dated decisions, ex-post spread alpha, calibration and data-leakage controls.",
        "Session data stays in the active browser session unless explicitly downloaded; no server-side persistence is implied.",
    )
    journal_tab, pit_tab, protocol_tab = st.tabs(["Decision journal", "Point-in-time audit", "Governance protocol"])
    with journal_tab:
        upload = st.file_uploader("Import journal CSV or JSON", type=["csv", "json"], key="fic7_journal_upload")
        if upload is not None:
            try:
                raw = upload.getvalue()
                imported = pd.read_csv(BytesIO(raw)) if upload.name.lower().endswith(".csv") else pd.DataFrame(json.loads(raw.decode("utf-8")))
                st.session_state["fic7_journal_data"] = imported
            except Exception as exc:
                st.error(f"Journal import failed: {exc}")
        if st.button("Reset to blank journal", key="fic7_reset_journal"):
            st.session_state["fic7_journal_data"] = _fic7_blank_journal()
            st.rerun()
        journal_base = st.session_state.get("fic7_journal_data", _fic7_blank_journal())
        journal = st.data_editor(journal_base, use_container_width=True, num_rows="dynamic", hide_index=True, key="fic7_journal_editor", height=340)
        st.session_state["fic7_journal_data"] = journal
        analyzed, metrics = decision_journal_diagnostics(journal)
        cols = st.columns(6)
        cols[0].metric("Dated decisions", _fmt_num(metrics["decisions"], 0))
        cols[1].metric("Closed", _fmt_num(metrics["closed_decisions"], 0))
        cols[2].metric("Hit rate", _fmt_pct(metrics["hit_rate_pct"] / 100.0, 1))
        cols[3].metric("Average alpha", _fic7_metric(metrics["average_alpha_bp"], 1, " bp"))
        cols[4].metric("Brier score", _fmt_num(metrics["brier_score"], 3))
        cols[5].metric("Overdue reviews", _fmt_num(metrics["overdue_reviews"], 0))
        closed = analyzed.loc[analyzed["spread_alpha_bp"].notna()]
        if not closed.empty:
            alpha_fig = go.Figure(go.Bar(
                x=closed["issuer"].fillna("") + " · " + closed["instrument"].fillna(""),
                y=closed["spread_alpha_bp"],
                marker_color=np.where(closed["spread_alpha_bp"] >= 0, "#34d399", "#fb7185"),
            ))
            alpha_fig.update_layout(template="plotly_dark", height=360, yaxis_title="Direction-adjusted spread alpha (bp)", margin=dict(l=20, r=20, t=35, b=20))
            st.plotly_chart(alpha_fig, use_container_width=True, key="fic7_journal_alpha")
        else:
            st.info("Enter exit spreads to activate hit-rate, alpha and calibration diagnostics.")
        st.dataframe(analyzed, use_container_width=True, hide_index=True)
        j1, j2 = st.columns(2)
        j1.download_button("Download journal CSV", analyzed.to_csv(index=False).encode("utf-8"), "credit_decision_journal.csv", "text/csv", key="fic7_journal_csv")
        j2.download_button("Download journal JSON", analyzed.to_json(orient="records", date_format="iso").encode("utf-8"), "credit_decision_journal.json", "application/json", key="fic7_journal_json")
    with pit_tab:
        pit_upload = st.file_uploader("Import point-in-time observations CSV", type=["csv"], key="fic7_pit_upload")
        if pit_upload is not None:
            try:
                st.session_state["fic7_pit_data"] = pd.read_csv(pit_upload)
            except Exception as exc:
                st.error(f"PIT import failed: {exc}")
        pit_base = st.session_state.get("fic7_pit_data", _fic7_blank_pit())
        pit_input = st.data_editor(pit_base, use_container_width=True, num_rows="dynamic", hide_index=True, key="fic7_pit_editor", height=340)
        st.session_state["fic7_pit_data"] = pit_input
        audited, pit_metrics = point_in_time_leakage_audit(pit_input)
        pcols = st.columns(5)
        pcols[0].metric("Rows", _fmt_num(pit_metrics["rows"], 0))
        pcols[1].metric("Availability coverage", _fmt_pct(pit_metrics["availability_coverage_pct"] / 100.0, 1))
        pcols[2].metric("Leakage rate", _fmt_pct(pit_metrics["leakage_rate_pct"] / 100.0, 1))
        pcols[3].metric("Median publication lag", _fic7_metric(pit_metrics["median_lag_days"], 0, "d"))
        pcols[4].metric("Revision rows", _fmt_num(pit_metrics["revision_rows"], 0))
        if audited["leakage_flag"].any():
            st.error("Potential look-ahead leakage detected. Review flagged rows before model or committee use.")
        elif audited["available_date"].notna().any():
            st.success("No availability-after-decision or observation-after-decision flag in supplied rows.")
        else:
            st.info("Add or import dated observations to run the point-in-time audit.")
        st.dataframe(audited, use_container_width=True, hide_index=True)
        st.download_button("Download PIT audit CSV", audited.to_csv(index=False).encode("utf-8"), "point_in_time_audit.csv", "text/csv", key="fic7_pit_csv")
    with protocol_tab:
        st.markdown(
            """
            **Minimum institutional protocol**

            1. Freeze the decision timestamp and retain the exact feature snapshot available at that time.
            2. Store publication timestamps, vintage identifiers and transformations alongside every signal.
            3. Record thesis, catalyst, sizing logic, invalidation trigger and scheduled review before execution.
            4. Measure ex-post outcomes directionally and include transaction costs, liquidity and censored exits.
            5. Separate model development, independent validation, limit approval and production monitoring.
            """
        )
        st.dataframe(
            pd.DataFrame(
                [
                    ["Input availability", "available_date <= decision_date", "Every decision", "Research owner"],
                    ["Revision control", "Vintage or accession retained", "Every refresh", "Data owner"],
                    ["Thesis review", "Trigger + review date", "At least monthly", "Analyst / PM"],
                    ["Calibration", "Hit rate + Brier + alpha", "Quarterly", "Independent risk"],
                    ["Model change", "Versioned evidence + challenger", "Before production", "Model governance"],
                ],
                columns=["Control", "Test", "Frequency", "Owner"],
            ),
            use_container_width=True,
            hide_index=True,
        )



def _fic_render_governance_v2() -> None:
    _fic_section("Model Governance & Production Boundary")
    controls=pd.DataFrame([
        {"control":"Observed / proxy / demo separation","status":"IMPLEMENTED","production_requirement":"Persist lineage and entitlement metadata"},
        {"control":"Par / zero / forward semantics","status":"IMPLEMENTED","production_requirement":"Instrument convention and calendar library"},
        {"control":"Curve calibration quality","status":"IMPLEMENTED","production_requirement":"Daily residual thresholds and alerting"},
        {"control":"Bond price / yield reversibility","status":"IMPLEMENTED","production_requirement":"Security master and corporate-action handling"},
        {"control":"DV01 / convexity finite differences","status":"IMPLEMENTED","production_requirement":"Vendor cross-check"},
        {"control":"CDS survival calibration","status":"IMPLEMENTED — SCREENING","production_requirement":"Certified ISDA engine and conventions"},
        {"control":"Rating migration / Credit VaR","status":"IMPLEMENTED — SCREENING","production_requirement":"Approved transition matrices and valuation maps"},
        {"control":"Basel IRRBB EVE shocks","status":"IMPLEMENTED — EVE","production_requirement":"Contractual/behavioural cash flows and NII engine"},
        {"control":"Portfolio factor aggregation","status":"IMPLEMENTED","production_requirement":"Instrument-level KRD and CS01 vectors"},
        {"control":"Stress loss attribution","status":"IMPLEMENTED","production_requirement":"Historical scenario factor maps"},
        {"control":"TRACE / liquidity diagnostics","status":"IMPLEMENTED ON UPLOAD","production_requirement":"FINRA entitlement, corrections and identifier mapping"},
        {"control":"Investment committee scorecard","status":"IMPLEMENTED — TRANSPARENT","production_requirement":"Desk-approved weights, limits and workflow"},
        {"control":"Futures CTD / basis","status":"IMPLEMENTED ON EXPLICIT INPUT","production_requirement":"Exchange basket, conversion factors, delivery options and executable repo"},
        {"control":"Credit relative value","status":"IMPLEMENTED — SCREENING","production_requirement":"Approved OAS, security master, option model and executable liquidity"},
        {"control":"Structural distance-to-default","status":"IMPLEMENTED — CROSS-CHECK","production_requirement":"Point-in-time equity, debt/default barrier, volatility and model validation"},
        {"control":"Standard-coupon CDS economics","status":"IMPLEMENTED — SCREENING","production_requirement":"Certified ISDA engine, calendars, step-in/accrued settlement and RFR curve"},
        {"control":"Credit carry / breakeven","status":"IMPLEMENTED","production_requirement":"Effective OAS duration, callable model, executable funding and governed PD/LGD"},
        {"control":"Recovery waterfall / covenants","status":"IMPLEMENTED — SCENARIO","production_requirement":"Legal priority, collateral, guarantees, intercreditor and jurisdictional review"},
        {"control":"Issuer early-warning system","status":"IMPLEMENTED — TRANSPARENT","production_requirement":"Point-in-time data, frozen weights, overrides and analyst workflow"},
        {"control":"P&L explain / residual","status":"IMPLEMENTED","production_requirement":"Official books-and-records P&L and position-level market moves"},
        {"control":"Liquidity-horizon ES","status":"IMPLEMENTED — SCREENING","production_requirement":"IMA modellability, stressed calibration, NMRF and approved correlation treatment"},
        {"control":"Walk-forward signal validation","status":"IMPLEMENTED","production_requirement":"Independent research review, frozen specification and live shadow period"},
    ])
    st.dataframe(controls,width="stretch",hide_index=True)
    st.markdown("#### Capability map")
    st.dataframe(licensed_provider_registry(),width="stretch",hide_index=True)
    st.markdown("#### Core risk equations")
    st.latex(r"P=\sum_{t=1}^{n}CF_tD(0,t)")
    st.latex(r"\Delta P\approx-DV01\,\Delta y_{bp}-CS01\,\Delta s_{bp}+\frac{1}{2}P C(\Delta y)^2")
    st.latex(r"\lambda\approx\frac{s}{1-R},\qquad PD(0,T)=1-e^{-\lambda T}")
    st.latex(r"s_{CDS}\times RPV01=(1-R)\sum_iD_i\,[Q_{i-1}-Q_i]")
    st.latex(r"Credit\ VaR_{\alpha}=q_{\alpha}(L),\qquad ES_{\alpha}=E[L\mid L\geq VaR_{\alpha}]")
    st.markdown("<div class='fic2-method'>A screen becomes institutional only when market-data lineage, security conventions, model limitations, position-level sensitivities and execution constraints are explicit. This workstation keeps the public-data layer useful without disguising provider gaps.</div>",unsafe_allow_html=True)


DESK_PAGES_V2: dict[str, list[str]] = {
    "OVERVIEW": ["Command Center", "Market Monitor", "Data Monitor"],
    "RATES": ["Curve Monitor", "Curve Construction Pro", "Relative Value & Trade Builder", "Treasury Futures & CTD", "Inflation & Real Rates", "Futures & Volatility", "Auctions & Supply"],
    "CREDIT": ["Credit Monitor", "Credit Relative Value", "CDS Curve & Basis", "Issuer Research Pro", "Issuer Credit", "Structural Credit", "Single Security Analytics", "Credit Carry & Breakeven", "Recovery & Covenants", "Liquidity & TRACE Pro", "Watchlist & Early Warning"],
    "PORTFOLIO": ["Portfolio Construction Lab", "Portfolio Analytics", "Factor Risk", "P&L Attribution & Tail Risk", "Migration & Credit VaR", "Stress & Scenario Lab", "Basel IRRBB", "Hedge Optimizer"],
    "RESEARCH": ["Credit Research 360", "Decision Journal & PIT Audit", "Strategy Lab Pro", "Signal Validation", "Econometric Diagnostics", "Investment Committee", "Model Governance"],
}

PAGE_RENDERERS_V2: dict[str, Callable[..., None]] = {
    "Command Center": _fic_render_command_center_v2,
    "Market Monitor": _fic_render_market_monitor_v2,
    "Data Monitor": _render_data_monitor,
    "Curve Monitor": _fic_render_curve_monitor_v2,
    "Curve Construction Pro": _fic_render_curve_construction_v2,
    "Relative Value & Trade Builder": _fic_render_relative_value_v2,
    "Treasury Futures & CTD": _fic_render_treasury_futures_v4,
    "Inflation & Real Rates": _fic_render_inflation_v2,
    "Futures & Volatility": _fic_render_futures_v2,
    "Auctions & Supply": _fic_render_auctions_v2,
    "Credit Monitor": _fic_render_credit_monitor_v2,
    "Credit Relative Value": _fic_render_credit_relative_value_v4,
    "CDS Curve & Basis": _fic_render_cds_curve_v3,
    "Issuer Research Pro": _fic_render_issuer_research_pro_v7,
    "Structural Credit": _fic_render_structural_credit_v5,
    "Single Security Analytics": _render_bond_analytics,
    "Credit Carry & Breakeven": _fic_render_credit_carry_v5,
    "Recovery & Covenants": _fic_render_recovery_covenants_v5,
    "Liquidity & TRACE Pro": _fic_render_liquidity_v3,
    "Watchlist & Early Warning": _fic_render_watchlist_v5,
    "Portfolio Construction Lab": _fic_render_portfolio_construction_v7,
    "Portfolio Analytics": _render_portfolio_analytics,
    "Factor Risk": _fic_render_factor_risk_v2,
    "P&L Attribution & Tail Risk": _fic_render_pnl_tail_risk_v4,
    "Migration & Credit VaR": _fic_render_migration_var_v3,
    "Stress & Scenario Lab": _fic_render_stress_v2,
    "Basel IRRBB": _fic_render_irrbb_v3,
    "Hedge Optimizer": _fic_render_hedge_optimizer_v2,
    "Credit Research 360": _fic_render_credit_research_360_v6,
    "Decision Journal & PIT Audit": _fic_render_decision_journal_v7,
    "Strategy Lab Pro": _fic_render_strategy_v2,
    "Signal Validation": _fic_render_signal_validation_v4,
    "Econometric Diagnostics": _render_econometric_diagnostics,
    "Investment Committee": _fic_render_investment_committee_v3,
    "Model Governance": _fic_render_governance_v2,
}


def _fic_render_context_rail(desk: str, page: str, data_mode: str) -> None:
    boundaries = {
        "OVERVIEW": ("Regime + dislocation", "Cross-market", "Escalate stale inputs"),
        "RATES": ("Curve + carry + basis", "DV01 / KRD / convexity", "Validate conventions"),
        "CREDIT": ("OAS + default + liquidity", "CS01 / JTD / migration", "Check documentation"),
        "PORTFOLIO": ("Attribution + tail risk", "Limits / concentration", "Hedge residual risk"),
        "RESEARCH": ("Evidence + robustness", "OOS / costs / governance", "Independent approval"),
    }
    signal, risk, action = boundaries.get(desk, boundaries["OVERVIEW"])
    state = "OBSERVED / LICENSED INPUT" if data_mode == "Live public data" else "EXPLICIT DEMO"
    st.markdown(
        f"""
        <div class='fic2-rail'>
            <div><div class='fic2-rail-k'>Workspace</div><div class='fic2-rail-v'>{page}</div></div>
            <div><div class='fic2-rail-k'>Decision lens</div><div class='fic2-rail-v'>{signal}</div></div>
            <div><div class='fic2-rail-k'>Risk lens</div><div class='fic2-rail-v'>{risk}</div></div>
            <div><div class='fic2-rail-k'>Control</div><div class='fic2-rail-v'>{action} · {state}</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_fixed_income_credit_analytics(
    ticker: str | None = None,
    price_data: pd.DataFrame | None = None,
    analysis: dict | None = None,
) -> None:
    """Institutional V8.0 public entry point — modular research and decision workstation."""
    # Synchronize the terminal context without forcing a rerun.
    st.session_state["asset_class"] = "Rates"
    st.session_state["mode_input"] = "Fixed Income & Credit Analytics"
    st.session_state["terminal_selected_mode"] = "Fixed Income & Credit Analytics"
    st.session_state["fic_active_symbol"] = "^TNX"

    _fic_v2_css()
    st.markdown(
        f"""
        <div class="fic2-hero">
            <div class="fic2-kicker">RATES · CREDIT · PORTFOLIO RISK · RESEARCH GOVERNANCE</div>
            <div class="fic2-title">Fixed Income & Credit Analytics</div>
            <div class="fic2-sub">Integrated institutional workstation for curves, carry/roll, Treasury futures CTD, cash/CDS relative value, issuer fundamentals, Merton structural risk, standard-coupon CDS, recovery waterfalls, TRACE liquidity, portfolio tail risk, automated issuer research, refinancing walls, constrained portfolio construction, point-in-time validation, modular engines, validated units and evidence-governed decisions. Version {MODULE_VERSION}.</div>
        </div>
        <div class="fic2-statusbar">
            <div class="fic2-status"><div class="fic2-status-k">Market stack</div><div class="fic2-status-v">CURVES · FUTURES · CASH · CDS</div></div>
            <div class="fic2-status"><div class="fic2-status-k">Risk stack</div><div class="fic2-status-v">DV01 · CS01 · JTD · ES · EVE</div></div>
            <div class="fic2-status"><div class="fic2-status-k">Decision stack</div><div class="fic2-status-v">VALUE · CARRY · LIQUIDITY · STRESS</div></div>
            <div class="fic2-status"><div class="fic2-status-k">Data / model boundary</div><div class="fic2-status-v fic2-good">VISIBLE · AUDITABLE</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    nav1, nav2, nav3 = st.columns([1.0, 1.0, 1.55], vertical_alignment="bottom")
    data_mode = nav1.selectbox("Data state", ["Live public data", "Explicit demo data"], key="fic_data_mode")
    desk = nav2.selectbox("Desk", list(DESK_PAGES_V2), key="fic2_desk")
    pages = DESK_PAGES_V2[desk]
    previous_page = st.session_state.get("fic2_page")
    default_index = pages.index(previous_page) if previous_page in pages else 0
    page = nav3.selectbox("Workspace", pages, index=default_index, key="fic2_page")

    if data_mode == "Explicit demo data":
        st.warning("EXPLICIT DEMO DATA — generated observations are clearly separated from observed public data.")

    _fic_render_context_rail(desk, page, data_mode)

    renderer = PAGE_RENDERERS_V2.get(page)
    if page == "Issuer Credit":
        _render_issuer_credit(ticker)
    elif renderer is not None:
        renderer()
    else:
        st.error(f"Unknown Fixed Income workspace: {page}")


__all__ = ["render_fixed_income_credit_analytics"]
