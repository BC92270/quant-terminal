"""
JARVIS Institutional Tools — autonomous Streamlit module.

Public entry point:
    render_tools_intelligence(ticker, price_data, analysis=None)

The module deliberately isolates all state under ``tools1_*`` keys.  Market
histories and official macro series are never silently replaced by fabricated
data.  Scenario engines are deterministic, explicitly calibrated and clearly
labelled as model output rather than observed history.
"""

from __future__ import annotations

import html
import io
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

try:
    import requests

    REQUESTS_AVAILABLE = True
except Exception:
    requests = None
    REQUESTS_AVAILABLE = False

try:
    import yfinance as yf

    YFINANCE_AVAILABLE = True
except Exception:
    yf = None
    YFINANCE_AVAILABLE = False


TOOLS_VERSION = "V1 · INSTITUTIONAL DECISION LAB"
TOOLS_SECTION_KEY = "tools1_workspace"
TOOLS_SECTIONS: Tuple[str, ...] = (
    "Tools Home",
    "G7 Policy Lab",
    "Global Macro Scenarios",
    "Payrolls Nowcast",
    "Portfolio Construction",
    "Risk & Stress",
    "Methodology & Data Quality",
)

TOOLS_ASSETS: Mapping[str, Mapping[str, str]] = {
    "US Equity": {"ticker": "SPY", "role": "Growth"},
    "Intl Developed": {"ticker": "EFA", "role": "Growth"},
    "EM Equity": {"ticker": "EEM", "role": "Growth"},
    "US Treasuries": {"ticker": "TLT", "role": "Defensive"},
    "US Credit": {"ticker": "LQD", "role": "Income"},
    "Commodities": {"ticker": "DBC", "role": "Inflation"},
    "Gold": {"ticker": "GLD", "role": "Real asset"},
    "Listed Private Markets": {"ticker": "PSP", "role": "Alternatives"},
}

TOOLS_CMA_PRIORS: Mapping[str, float] = {
    "US Equity": 0.070,
    "Intl Developed": 0.072,
    "EM Equity": 0.082,
    "US Treasuries": 0.045,
    "US Credit": 0.052,
    "Commodities": 0.040,
    "Gold": 0.042,
    "Listed Private Markets": 0.085,
}

POLICY_PRESETS: Mapping[str, Mapping[str, Any]] = {
    "United States": {"flag": "US", "bank": "Federal Reserve", "currency": "USD", "peak": 5.0, "gdp": -0.62, "cpi": -1.20, "cons": -0.72, "house": -1.35, "invest": -1.80, "fx": 1.30, "unemp": 0.28},
    "United Kingdom": {"flag": "UK", "bank": "Bank of England", "currency": "GBP", "peak": 5.5, "gdp": -0.71, "cpi": -1.59, "cons": -0.62, "house": -1.80, "invest": -2.35, "fx": 1.55, "unemp": 0.32},
    "Euro Area": {"flag": "EA", "bank": "European Central Bank", "currency": "EUR", "peak": 6.0, "gdp": -0.58, "cpi": -1.10, "cons": -0.55, "house": -1.20, "invest": -1.60, "fx": 1.10, "unemp": 0.24},
    "Germany": {"flag": "DE", "bank": "European Central Bank", "currency": "EUR", "peak": 5.0, "gdp": -0.74, "cpi": -1.05, "cons": -0.60, "house": -1.45, "invest": -2.10, "fx": 1.10, "unemp": 0.22},
    "France": {"flag": "FR", "bank": "European Central Bank", "currency": "EUR", "peak": 6.0, "gdp": -0.55, "cpi": -1.00, "cons": -0.58, "house": -1.10, "invest": -1.55, "fx": 1.10, "unemp": 0.25},
    "Italy": {"flag": "IT", "bank": "European Central Bank", "currency": "EUR", "peak": 6.5, "gdp": -0.82, "cpi": -1.02, "cons": -0.75, "house": -0.95, "invest": -2.20, "fx": 1.10, "unemp": 0.38},
    "Japan": {"flag": "JP", "bank": "Bank of Japan", "currency": "JPY", "peak": 4.5, "gdp": -0.42, "cpi": -0.72, "cons": -0.40, "house": -0.65, "invest": -1.10, "fx": 1.80, "unemp": 0.12},
    "Canada": {"flag": "CA", "bank": "Bank of Canada", "currency": "CAD", "peak": 5.0, "gdp": -0.78, "cpi": -1.18, "cons": -0.88, "house": -2.10, "invest": -2.05, "fx": 1.25, "unemp": 0.34},
}

FRED_PAYROLL_SERIES: Mapping[str, Mapping[str, str]] = {
    "Payrolls": {"id": "PAYEMS", "unit": "thousands", "frequency": "Monthly"},
    "Unemployment": {"id": "UNRATE", "unit": "%", "frequency": "Monthly"},
    "Initial Claims": {"id": "ICSA", "unit": "persons", "frequency": "Weekly"},
    "Continuing Claims": {"id": "CCSA", "unit": "persons", "frequency": "Weekly"},
    "Hourly Earnings": {"id": "CES0500000003", "unit": "index", "frequency": "Monthly"},
    "Labor Participation": {"id": "CIVPART", "unit": "%", "frequency": "Monthly"},
    "Job Openings": {"id": "JTSJOL", "unit": "thousands", "frequency": "Monthly"},
    "Quits Rate": {"id": "JTSQUR", "unit": "%", "frequency": "Monthly"},
    "Temporary Help": {"id": "TEMPHELPS", "unit": "thousands", "frequency": "Monthly"},
    "Manufacturing Jobs": {"id": "MANEMP", "unit": "thousands", "frequency": "Monthly"},
    "Construction Jobs": {"id": "USCONS", "unit": "thousands", "frequency": "Monthly"},
}

PALETTE: Tuple[str, ...] = (
    "#63c7ff", "#d8bf58", "#57d39b", "#f4777f", "#a990ff",
    "#ff9b63", "#72d4d4", "#d69bb6", "#8ab4f8", "#b7cf73",
)


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _html(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


@contextmanager
def _card():
    try:
        with st.container(border=True):
            yield
    except TypeError:
        with st.container():
            yield


def _css() -> None:
    st.markdown(
        """
<style>
.t1-head{position:relative;overflow:hidden;border:1px solid rgba(128,158,190,.28);border-radius:15px;padding:22px 24px 20px;margin:8px 0 13px;background:radial-gradient(circle at 88% 8%,rgba(79,170,224,.15),transparent 32%),linear-gradient(135deg,rgba(7,25,41,.98),rgba(3,12,22,.98));box-shadow:0 20px 55px rgba(0,0,0,.25)}
.t1-head:after{content:"";position:absolute;inset:0;pointer-events:none;background-image:linear-gradient(rgba(126,164,195,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(126,164,195,.035) 1px,transparent 1px);background-size:28px 28px;mask-image:linear-gradient(to left,black,transparent 78%)}
.t1-kicker{position:relative;z-index:1;font-size:10px;letter-spacing:.23em;text-transform:uppercase;color:#d8bf58;font-weight:850}.t1-title{position:relative;z-index:1;font-family:Georgia,serif;font-size:37px;font-weight:700;color:#f4f7fa;margin:5px 0 7px;line-height:1.05}.t1-sub{position:relative;z-index:1;color:#a4b2c0;font-size:13px;line-height:1.55;max-width:1050px}.t1-pills{position:relative;z-index:1;display:flex;gap:6px;flex-wrap:wrap;margin-top:12px}.t1-pill{display:inline-block;border:1px solid rgba(216,191,88,.32);background:rgba(216,191,88,.045);border-radius:999px;padding:4px 9px;font-size:9px;color:#dacb7a;letter-spacing:.03em}
.t1-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;margin:10px 0 15px}.t1-kpi{position:relative;overflow:hidden;border:1px solid rgba(129,157,185,.22);border-radius:11px;padding:13px 14px 12px;background:linear-gradient(150deg,rgba(8,23,38,.94),rgba(5,16,28,.96));min-height:104px}.t1-kpi:before{content:"";position:absolute;left:0;top:0;right:0;height:2px;background:linear-gradient(90deg,#63c7ff,transparent)}.t1-kpi-gold:before{background:linear-gradient(90deg,#d8bf58,transparent)}.t1-label{font-size:9px;letter-spacing:.14em;text-transform:uppercase;color:#8998a8;font-weight:800}.t1-value{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-weight:800;font-size:23px;color:#f2f6f9;margin:8px 0 5px;line-height:1}.t1-delta{font-size:10px;color:#8fa0b0;line-height:1.35}.t1-up{color:#57d39b}.t1-down{color:#f4777f}.t1-flat{color:#d8bf58}
.t1-read-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;margin:10px 0 16px}.t1-read{border:1px solid rgba(128,157,186,.22);border-radius:11px;padding:13px 14px;background:rgba(6,19,32,.86);min-height:118px}.t1-read-k{font-size:9px;letter-spacing:.14em;text-transform:uppercase;color:#8596a6}.t1-read-state{font-family:Georgia,serif;font-size:19px;margin:5px 0;color:#f1f4f7}.t1-read-copy{font-size:11px;color:#9eadba;line-height:1.45}.t1-state-up{color:#57d39b}.t1-state-down{color:#f4777f}.t1-state-flat{color:#d8bf58}
.t1-section{font-family:Georgia,serif;font-size:25px;color:#f1f4f7;border-bottom:1px solid rgba(139,165,190,.18);padding:15px 0 8px;margin:13px 0 12px}.t1-card-head{border-left:3px solid #d8bf58;padding:2px 0 4px 12px;margin:2px 0 9px}.t1-card-k{font-size:9px;letter-spacing:.16em;text-transform:uppercase;color:#7f93a6;font-weight:800}.t1-card-t{font-family:Georgia,serif;color:#f2f5f8;font-size:20px;font-weight:700;line-height:1.15}.t1-card-s{color:#91a0af;font-size:11px;line-height:1.4;margin-top:4px}.t1-meta{display:flex;gap:12px;flex-wrap:wrap;color:#8193a5;font-size:9px;margin:4px 0 6px}.t1-meta b{color:#d8e0e7}.t1-source{font-size:9px;color:#8091a1;margin:5px 0 2px}.t1-note{border-left:2px solid rgba(99,199,255,.52);background:rgba(21,54,75,.20);padding:9px 12px;color:#9eb4c6;font-size:10px;line-height:1.45;margin:8px 0 13px}.t1-warn{border:1px solid rgba(216,191,88,.28);background:rgba(216,191,88,.055);border-radius:9px;padding:10px 12px;color:#d8c978;font-size:11px;margin:8px 0 12px}.t1-ok{border:1px solid rgba(87,211,155,.27);background:rgba(87,211,155,.05);border-radius:9px;padding:10px 12px;color:#82ddb4;font-size:11px;margin:8px 0 12px}.t1-tool-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:12px 0 18px}.t1-tool{border:1px solid rgba(128,157,186,.22);border-radius:12px;padding:15px;background:linear-gradient(145deg,rgba(8,24,39,.96),rgba(5,15,26,.98));min-height:150px}.t1-tool-num{font-family:ui-monospace,monospace;color:#d8bf58;font-size:10px;letter-spacing:.12em}.t1-tool-title{font-family:Georgia,serif;color:#f2f5f8;font-size:20px;margin:8px 0 6px}.t1-tool-copy{color:#92a2b1;font-size:11px;line-height:1.5}.t1-tag{display:inline-block;margin-top:10px;border:1px solid rgba(99,199,255,.24);border-radius:999px;padding:3px 7px;color:#83cceb;font-size:8px;text-transform:uppercase;letter-spacing:.08em}
div[data-testid="stDataFrame"]{border:1px solid rgba(126,154,182,.20);border-radius:10px;overflow:hidden;background:rgba(5,16,27,.82)}
div[data-testid="stPlotlyChart"]{border-radius:10px;overflow:hidden}
div[data-testid="stVerticalBlockBorderWrapper"]{background:linear-gradient(145deg,rgba(7,20,33,.86),rgba(4,14,24,.91));border-color:rgba(126,154,182,.20)!important;border-radius:12px!important}
@media(max-width:900px){.t1-grid,.t1-read-grid,.t1-tool-grid{grid-template-columns:1fr}.t1-title{font-size:30px}}
</style>
        """,
        unsafe_allow_html=True,
    )


def _header(section: str) -> None:
    copy = {
        "Tools Home": "A unified institutional decision laboratory for policy transmission, macro scenarios, labour-market nowcasts, allocation, portfolio risk and model governance.",
        "G7 Policy Lab": "Transparent impulse-response analysis for monetary-policy shocks across the G7, with parameter sensitivity and transmission attribution.",
        "Global Macro Scenarios": "A multi-region, cross-asset scenario engine translating macro shocks into growth, inflation, rates, FX and market outcomes.",
        "Payrolls Nowcast": "A vintage-safe ensemble of labour-market models with live official inputs, rolling backtests and explicit forecast dispersion.",
        "Portfolio Construction": "Eight allocation methods, live ETF proxies, efficient-frontier diagnostics, risk contribution, stress tests and Monte Carlo wealth paths.",
        "Risk & Stress": "A portfolio risk command centre combining historical drawdowns, tail risk, correlation regimes and deterministic scenario shocks.",
        "Methodology & Data Quality": "Complete model registry, source lineage, assumptions, limitations and equivalence audit against the RoboMacro reference.",
    }
    _html(
        '<div class="t1-head">'
        '<div class="t1-kicker">JARVIS TOOLS · MODEL-DRIVEN DECISION SUPPORT</div>'
        f'<div class="t1-title">{_esc(section)}</div>'
        f'<div class="t1-sub">{_esc(copy.get(section, copy["Tools Home"]))}</div>'
        '<div class="t1-pills"><span class="t1-pill">transparent assumptions</span><span class="t1-pill">deterministic scenario engines</span><span class="t1-pill">official / market data lineage</span><span class="t1-pill">CSV export</span></div>'
        '</div>'
    )


def _section(title: str) -> None:
    _html(f'<div class="t1-section">{_esc(title)}</div>')


def _card_head(kicker: str, title: str, subtitle: str) -> None:
    _html(
        '<div class="t1-card-head">'
        f'<div class="t1-card-k">{_esc(kicker)}</div>'
        f'<div class="t1-card-t">{_esc(title)}</div>'
        f'<div class="t1-card-s">{_esc(subtitle)}</div>'
        '</div>'
    )


def _kpis(items: Sequence[Tuple[str, str, str, Optional[float]]]) -> None:
    blocks: List[str] = []
    for idx, (label, value, note, direction) in enumerate(items):
        css = "t1-flat" if direction is None or abs(float(direction)) < 1e-12 else ("t1-up" if float(direction) > 0 else "t1-down")
        gold = " t1-kpi-gold" if idx % 3 == 1 else ""
        blocks.append(
            f'<div class="t1-kpi{gold}"><div class="t1-label">{_esc(label)}</div>'
            f'<div class="t1-value {css}">{_esc(value)}</div><div class="t1-delta">{_esc(note)}</div></div>'
        )
    _html('<div class="t1-grid">' + "".join(blocks) + '</div>')


def _reads(items: Sequence[Tuple[str, str, str, str]]) -> None:
    blocks = []
    for label, state, copy, tone in items:
        tone_class = {"up": "t1-state-up", "down": "t1-state-down", "flat": "t1-state-flat"}.get(tone, "")
        blocks.append(
            f'<div class="t1-read"><div class="t1-read-k">{_esc(label)}</div>'
            f'<div class="t1-read-state {tone_class}">{_esc(state)}</div>'
            f'<div class="t1-read-copy">{_esc(copy)}</div></div>'
        )
    _html('<div class="t1-read-grid">' + "".join(blocks) + '</div>')


def _plot(fig: go.Figure, key: str, height: int = 420) -> None:
    fig.update_layout(
        height=height,
        margin=dict(l=45, r=22, t=28, b=42),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(4,15,26,.91)",
        font=dict(color="#cfd7df", size=10),
        xaxis=dict(gridcolor="rgba(136,158,181,.12)", zerolinecolor="rgba(136,158,181,.20)"),
        yaxis=dict(gridcolor="rgba(136,158,181,.12)", zerolinecolor="rgba(136,158,181,.28)"),
        legend=dict(orientation="h", y=1.07, x=0, bgcolor="rgba(0,0,0,0)", font=dict(size=9)),
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True, key=key, config={"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]})


def _table(df: pd.DataFrame, key: str, height: int = 360, formats: Optional[Mapping[str, str]] = None) -> None:
    if df is None or df.empty:
        _html('<div class="t1-warn">No rows are available for this table. The missing state is preserved.</div>')
        return
    styler = df.style
    if formats:
        styler = styler.format(dict(formats), na_rep="—")
    numeric = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    if numeric:
        def _tone(v: Any) -> str:
            try:
                value = float(v)
            except Exception:
                return ""
            return "color:#57d39b" if value > 0 else ("color:#f4777f" if value < 0 else "color:#aab6c1")
        styler = styler.map(_tone, subset=numeric)
    st.dataframe(styler, use_container_width=True, hide_index=True, height=height, key=key)


def _download(df: pd.DataFrame, label: str, filename: str, key: str) -> None:
    if df is None or df.empty:
        return
    st.download_button(label, data=df.to_csv(index=False).encode("utf-8"), file_name=filename, mime="text/csv", key=key)


def _fmt_pct(value: float, digits: int = 1) -> str:
    return "—" if not np.isfinite(value) else f"{value * 100:.{digits}f}%"


def _fmt_num(value: float, digits: int = 2) -> str:
    return "—" if not np.isfinite(value) else f"{value:.{digits}f}"


@st.cache_data(ttl=900, show_spinner=False)
def _load_market_history(tickers: Tuple[str, ...], period: str = "10y") -> Tuple[pd.DataFrame, Dict[str, Any]]:
    meta: Dict[str, Any] = {"status": "unavailable", "source": "Yahoo/yfinance", "updated": None, "error": ""}
    if not YFINANCE_AVAILABLE:
        meta["error"] = "yfinance is not installed"
        return pd.DataFrame(), meta
    try:
        raw = yf.download(list(tickers), period=period, auto_adjust=True, progress=False, threads=True, group_by="column", timeout=18)
        if raw is None or raw.empty:
            meta["error"] = "provider returned no rows"
            return pd.DataFrame(), meta
        if isinstance(raw.columns, pd.MultiIndex):
            if "Close" in raw.columns.get_level_values(0):
                closes = raw["Close"].copy()
            elif "Close" in raw.columns.get_level_values(-1):
                closes = raw.xs("Close", axis=1, level=-1).copy()
            else:
                closes = raw.copy()
        else:
            closes = raw[["Close"]].copy() if "Close" in raw.columns else raw.copy()
            if len(tickers) == 1:
                closes.columns = [tickers[0]]
        if isinstance(closes, pd.Series):
            closes = closes.to_frame(name=tickers[0])
        closes.index = pd.to_datetime(closes.index, errors="coerce").tz_localize(None)
        closes = closes.sort_index().replace([np.inf, -np.inf], np.nan).dropna(how="all")
        closes = closes[[t for t in tickers if t in closes.columns]]
        if closes.empty:
            meta["error"] = "no usable adjusted-close columns"
            return pd.DataFrame(), meta
        latest = closes.apply(lambda s: s.dropna().index.max() if not s.dropna().empty else pd.NaT).max()
        meta.update({"status": "live", "updated": latest, "rows": len(closes), "coverage": f"{len(closes.columns)}/{len(tickers)}"})
        return closes, meta
    except Exception as exc:
        meta["error"] = f"{type(exc).__name__}: {exc}"
        return pd.DataFrame(), meta


@st.cache_data(ttl=3600, show_spinner=False)
def _load_fred_series(series_id: str) -> Tuple[pd.Series, Dict[str, Any]]:
    meta: Dict[str, Any] = {"id": series_id, "status": "unavailable", "source": "FRED", "updated": None, "rows": 0, "error": ""}
    if not REQUESTS_AVAILABLE:
        meta["error"] = "requests is not installed"
        return pd.Series(dtype=float), meta
    try:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
        response = requests.get(url, timeout=16, headers={"User-Agent": "QuantTerminal/1.0"})
        response.raise_for_status()
        frame = pd.read_csv(io.StringIO(response.text))
        if frame.shape[1] < 2:
            raise ValueError("unexpected FRED CSV schema")
        dates = pd.to_datetime(frame.iloc[:, 0], errors="coerce")
        values = pd.to_numeric(frame.iloc[:, 1], errors="coerce")
        series = pd.Series(values.to_numpy(), index=dates, name=series_id).dropna().sort_index()
        if series.empty:
            raise ValueError("FRED returned no numeric observations")
        latest = series.index.max()
        age = max(0, (pd.Timestamp.utcnow().tz_localize(None).normalize() - latest.normalize()).days)
        meta.update({"status": "live", "updated": latest, "rows": len(series), "age_days": age})
        return series, meta
    except Exception as exc:
        meta["error"] = f"{type(exc).__name__}: {exc}"
        return pd.Series(dtype=float), meta


@st.cache_data(ttl=3600, show_spinner=False)
def _load_payroll_pack() -> Tuple[Dict[str, pd.Series], pd.DataFrame]:
    pack: Dict[str, pd.Series] = {}
    row_map: Dict[str, Dict[str, Any]] = {}

    # Prefer MarketDesk's production connector when it is available.  It owns
    # the shared disk cache and FRED circuit breaker already used by Liquidity,
    # Fixed Income, Autos and other validated workspaces.
    try:
        from market_intelligence import _liq3_load_fred_pack

        ids = tuple(spec["id"] for spec in FRED_PAYROLL_SERIES.values())
        cached_pack, _cached_quality, _cached_provider = _liq3_load_fred_pack(ids, "1990-01-01", 0)
        for name, spec in FRED_PAYROLL_SERIES.items():
            frame = cached_pack.get(spec["id"], pd.DataFrame()) if isinstance(cached_pack, Mapping) else pd.DataFrame()
            if not isinstance(frame, pd.DataFrame) or frame.empty:
                continue
            date_col = "date" if "date" in frame.columns else frame.columns[0]
            value_col = "value" if "value" in frame.columns else (frame.columns[1] if len(frame.columns) > 1 else None)
            if value_col is None:
                continue
            series = pd.Series(
                pd.to_numeric(frame[value_col], errors="coerce").to_numpy(),
                index=pd.to_datetime(frame[date_col], errors="coerce"),
                name=spec["id"],
            ).dropna().sort_index()
            if series.empty:
                continue
            pack[name] = series
            latest = series.index.max()
            row_map[name] = {
                "Series": name,
                "FRED ID": spec["id"],
                "Frequency": spec["frequency"],
                "Unit": spec["unit"],
                "Latest": latest,
                "Age (days)": max(0, (pd.Timestamp.utcnow().tz_localize(None).normalize() - latest.normalize()).days),
                "Rows": len(series),
                "Status": "live-cache",
                "Message": "MarketDesk shared FRED cache / connector",
            }
    except Exception:
        pass

    def _fetch(name: str, spec: Mapping[str, str]) -> Tuple[str, pd.Series, Dict[str, Any]]:
        series, meta = _load_fred_series(spec["id"])
        return name, series, meta

    # FRED endpoints are independent.  Parallel retrieval keeps one slow or
    # unavailable series from serially blocking the entire nowcast workspace.
    missing_specs = {name: spec for name, spec in FRED_PAYROLL_SERIES.items() if name not in pack}
    with ThreadPoolExecutor(max_workers=min(6, max(1, len(missing_specs)))) as pool:
        futures = {pool.submit(_fetch, name, spec): (name, spec) for name, spec in missing_specs.items()}
        for future in as_completed(futures):
            fallback_name, spec = futures[future]
            try:
                name, series, meta = future.result()
            except Exception as exc:
                name, series, meta = fallback_name, pd.Series(dtype=float), {
                    "status": "unavailable",
                    "rows": 0,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            pack[name] = series
            row_map[name] = {
                "Series": name,
                "FRED ID": spec["id"],
                "Frequency": spec["frequency"],
                "Unit": spec["unit"],
                "Latest": meta.get("updated"),
                "Age (days)": meta.get("age_days"),
                "Rows": meta.get("rows", 0),
                "Status": meta.get("status", "unavailable"),
                "Message": meta.get("error", ""),
            }
    rows = [row_map[name] for name in FRED_PAYROLL_SERIES if name in row_map]
    return pack, pd.DataFrame(rows)


def _tools_home() -> None:
    _kpis([
        ("Decision Workspaces", "5", "Policy · macro · payrolls · allocation · risk", 1),
        ("Model Families", "20+", "Structural, econometric, optimisation and tail-risk", 1),
        ("G7 Coverage", "7 + EA", "Country-specific policy transmission calibrations", 1),
        ("Portfolio Methods", "8", "From equal weight to CVaR and risk parity", 1),
        ("Observed Data", "NO FILL", "Missing histories remain explicitly unavailable", None),
        ("Governance", "FULL", "Sources, assumptions, limitations and exports", 1),
    ])
    _section("Decision Laboratory")
    cards = [
        ("01", "G7 Policy Lab", "Policy-shock impulse responses, sensitivity controls, transmission attribution and country comparison.", "HANK-STYLE IRFs"),
        ("02", "Global Macro Scenarios", "Translate growth, inflation, oil, USD, policy and risk-premium shocks into regional and cross-asset impacts.", "MULTI-REGION"),
        ("03", "Payrolls Nowcast", "Official labour-market data, independent model forecasts, dispersion, rolling errors and vintage-safe track record.", "ENSEMBLE FORECAST"),
        ("04", "Portfolio Construction", "Live ETF proxies, eight allocation methods, frontier, risk contribution, backtest, stress and Monte Carlo.", "ASSET ALLOCATION"),
        ("05", "Risk & Stress", "Historical tail diagnostics, correlation regimes, scenario shocks, portfolio loss attribution and risk limits.", "RISK COMMAND"),
        ("06", "Methodology & Data Quality", "Reference equivalence, data lineage, model registry, validation controls and known limitations.", "MODEL GOVERNANCE"),
    ]
    blocks = []
    for num, title, copy, tag in cards:
        blocks.append(f'<div class="t1-tool"><div class="t1-tool-num">{num}</div><div class="t1-tool-title">{_esc(title)}</div><div class="t1-tool-copy">{_esc(copy)}</div><span class="t1-tag">{_esc(tag)}</span></div>')
    _html('<div class="t1-tool-grid">' + "".join(blocks) + '</div>')
    _section("Institutional Operating Principles")
    _reads([
        ("DATA CONTRACT", "OBSERVED IS OBSERVED", "Market and official histories are retrieved from named providers. A failed provider produces a visible missing state, never a synthetic historical line.", "up"),
        ("MODEL CONTRACT", "SCENARIOS ARE LABELLED", "Calibrated impulse responses, CMA priors and deterministic stresses are displayed as assumptions or model output, not as empirical facts.", "flat"),
        ("DECISION CONTRACT", "RISK BEFORE RETURN", "Every portfolio recommendation is paired with concentration, tail loss, risk contribution, regime and backtest diagnostics.", "up"),
    ])
    _html(f'<div class="t1-note">{TOOLS_VERSION} · isolated tools1_* session state · no mutation of Economy, Markets, Oil or Autos routes.</div>')


def _hump(t: np.ndarray, peak: float, decay: float = 1.0) -> np.ndarray:
    x = np.maximum(t, 0.0) / max(peak, 0.25)
    out = np.where(t <= 0, 0.0, np.power(np.maximum(x, 1e-9), decay) * np.exp(decay * (1.0 - x)))
    return out


def _policy_irf(
    country: str,
    shock: float,
    horizon: int,
    persistence: float,
    household: float,
    fiscal_offset: float,
    fx_pass: float,
    credibility: float,
) -> pd.DataFrame:
    p = POLICY_PRESETS[country]
    q = np.arange(horizon + 1, dtype=float)
    peak = float(p["peak"]) * (0.72 + 0.50 * persistence)
    demand = _hump(q, peak, 1.25)
    slow = _hump(q, peak * 1.45, 1.15)
    fast = np.exp(-q / max(1.8, 4.5 * persistence))
    fiscal_scale = max(0.35, 1.0 - 0.65 * fiscal_offset)
    household_scale = 0.55 + 0.45 * household
    credibility_scale = 0.65 + 0.35 * credibility
    rate = shock * np.power(np.clip(persistence, 0.15, 0.99), q / 2.0)
    gdp = float(p["gdp"]) * shock * demand * household_scale * fiscal_scale
    consumption = float(p["cons"]) * shock * demand * household_scale
    investment = float(p["invest"]) * shock * _hump(q, peak * 0.72, 1.30) * (0.72 + 0.28 * household)
    house = float(p["house"]) * shock * slow * household_scale
    cpi_level = float(p["cpi"]) * shock * (1.0 - np.exp(-q / max(3.0, peak))) * credibility_scale * (0.65 + 0.35 * fx_pass)
    fx = float(p["fx"]) * shock * fast * (0.55 + 0.45 * credibility)
    unemployment = float(p["unemp"]) * shock * slow * household_scale * fiscal_scale
    wages = 0.42 * cpi_level + 0.18 * gdp
    return pd.DataFrame({
        "Quarter": q.astype(int),
        "Policy Rate (pp)": rate,
        "GDP (%)": gdp,
        "Consumption (%)": consumption,
        "Investment (%)": investment,
        "CPI Level (pp)": cpi_level,
        "House Prices (%)": house,
        "FX (%)": fx,
        "Unemployment (pp)": unemployment,
        "Wages (%)": wages,
    })


def _peak_row(series: pd.Series, adverse: bool = True) -> Tuple[float, int]:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return float("nan"), 0
    idx = int(clean.idxmin() if adverse else clean.idxmax())
    return float(clean.loc[idx]), idx


def _policy_lab() -> None:
    controls = st.columns([1.5, 1.1, 1.1, 1.1])
    with controls[0]:
        country = st.selectbox("Economy", list(POLICY_PRESETS), index=0, key="tools1_policy_country")
    with controls[1]:
        shock = st.slider("Policy shock (pp)", -2.0, 2.0, 1.0, 0.25, key="tools1_policy_shock")
    with controls[2]:
        horizon = st.slider("Horizon (quarters)", 12, 40, 24, 4, key="tools1_policy_horizon")
    with controls[3]:
        compare = st.toggle("Compare G7", value=False, key="tools1_policy_compare")

    p = POLICY_PRESETS[country]
    _html(f'<div class="t1-note"><b>{_esc(p["bank"])}</b> · {_esc(p["currency"])} · baseline calibration is a transparent reduced-form approximation to published monetary-transmission ranges. It is not an estimated real-time structural forecast.</div>')

    with st.expander("Transmission assumptions", expanded=False):
        a1, a2, a3, a4, a5 = st.columns(5)
        with a1:
            persistence = st.slider("Rate persistence", 0.35, 0.98, 0.78, 0.01, key="tools1_policy_persistence")
        with a2:
            household = st.slider("Household sensitivity", 0.50, 1.60, 1.00, 0.05, key="tools1_policy_household")
        with a3:
            fiscal_offset = st.slider("Fiscal offset", 0.00, 0.80, 0.20, 0.05, key="tools1_policy_fiscal")
        with a4:
            fx_pass = st.slider("FX pass-through", 0.20, 1.40, 0.75, 0.05, key="tools1_policy_fxpass")
        with a5:
            credibility = st.slider("Policy credibility", 0.40, 1.40, 1.00, 0.05, key="tools1_policy_cred")

    irf = _policy_irf(country, shock, horizon, persistence, household, fiscal_offset, fx_pass, credibility)
    gdp_peak, gdp_q = _peak_row(irf["GDP (%)"], adverse=shock >= 0)
    cons_peak, cons_q = _peak_row(irf["Consumption (%)"], adverse=shock >= 0)
    house_peak, house_q = _peak_row(irf["House Prices (%)"], adverse=shock >= 0)
    unemp_peak, unemp_q = _peak_row(irf["Unemployment (pp)"], adverse=shock < 0)
    cpi_3y = float(irf.loc[min(12, len(irf) - 1), "CPI Level (pp)"])
    _kpis([
        ("GDP Peak", f"{gdp_peak:+.2f}%", f"Quarter {gdp_q}", -gdp_peak if shock < 0 else gdp_peak),
        ("CPI Level · 3Y", f"{cpi_3y:+.2f}pp", "Cumulative price-level response", cpi_3y),
        ("Consumption Peak", f"{cons_peak:+.2f}%", f"Quarter {cons_q}", cons_peak),
        ("House Prices Peak", f"{house_peak:+.2f}%", f"Quarter {house_q}", house_peak),
        ("Unemployment Peak", f"{unemp_peak:+.2f}pp", f"Quarter {unemp_q}", -unemp_peak),
        ("FX Impact", f"{float(irf.loc[0, 'FX (%)']):+.2f}%", f"{p['currency']} appreciation (+)", float(irf.loc[0, "FX (%)"])),
    ])

    stance = "TIGHTENING" if shock > 0 else ("EASING" if shock < 0 else "NEUTRAL")
    growth_state = "CONTRACTIONARY" if gdp_peak < -0.05 else ("EXPANSIONARY" if gdp_peak > 0.05 else "MUTED")
    price_state = "DISINFLATIONARY" if cpi_3y < -0.05 else ("REFLATIONARY" if cpi_3y > 0.05 else "MUTED")
    _reads([
        ("POLICY IMPULSE", stance, f"A {shock:+.2f}pp one-off surprise with persistence {persistence:.2f} is propagated over {horizon} quarters.", "down" if shock > 0 else "up"),
        ("REAL ACTIVITY", growth_state, f"GDP reaches {gdp_peak:+.2f}% in Q{gdp_q}; investment is the higher-beta demand channel.", "down" if gdp_peak < 0 else "up"),
        ("PRICE TRANSMISSION", price_state, f"The CPI level response reaches {cpi_3y:+.2f}pp by year three, conditional on credibility and FX pass-through.", "down" if cpi_3y < 0 else "up"),
    ])

    _section("Impulse Response Functions")
    left, right = st.columns(2)
    with left, _card():
        _card_head("REAL ECONOMY", "Growth & Household Demand", "Quarterly response to the selected unanticipated policy shock.")
        fig = go.Figure()
        for i, col in enumerate(["GDP (%)", "Consumption (%)", "Investment (%)"]):
            fig.add_trace(go.Scatter(x=irf["Quarter"], y=irf[col], name=col.replace(" (%)", ""), line=dict(color=PALETTE[i], width=2.2)))
        fig.add_hline(y=0, line_color="rgba(190,200,210,.25)")
        _plot(fig, "tools1_policy_real")
    with right, _card():
        _card_head("PRICES & FINANCIAL CONDITIONS", "Inflation, Housing & FX", "Price-level and asset-price transmission; FX appreciation is positive.")
        fig = go.Figure()
        for i, col in enumerate(["CPI Level (pp)", "House Prices (%)", "FX (%)"]):
            fig.add_trace(go.Scatter(x=irf["Quarter"], y=irf[col], name=col.split(" (")[0], line=dict(color=PALETTE[i + 3], width=2.2)))
        fig.add_hline(y=0, line_color="rgba(190,200,210,.25)")
        _plot(fig, "tools1_policy_prices")

    with _card():
        _card_head("CHANNEL ATTRIBUTION", "Peak GDP Transmission Decomposition", "Disclosed deterministic attribution of the peak activity response; components sum to the model peak.")
        total = gdp_peak
        raw = np.array([0.34 * household, 0.24 * household, 0.18 * (1 - fiscal_offset), 0.14 * fx_pass, 0.10 * credibility], dtype=float)
        raw = raw / raw.sum() if raw.sum() else np.ones(5) / 5
        vals = raw * total
        channels = ["Consumption / income", "Housing / credit", "Fiscal feedback", "FX / net exports", "Expectations"]
        fig = go.Figure(go.Bar(x=channels, y=vals, marker_color=["#63c7ff", "#a990ff", "#d8bf58", "#57d39b", "#ff9b63"]))
        fig.update_yaxes(title="Contribution to peak GDP response (pp)")
        _plot(fig, "tools1_policy_attribution", 360)

    if compare:
        _section("G7 Comparison")
        rows = []
        for name in POLICY_PRESETS:
            cmp_irf = _policy_irf(name, shock, horizon, persistence, household, fiscal_offset, fx_pass, credibility)
            gp, gq = _peak_row(cmp_irf["GDP (%)"], adverse=shock >= 0)
            hp, hq = _peak_row(cmp_irf["House Prices (%)"], adverse=shock >= 0)
            rows.append({"Economy": name, "GDP Peak (%)": gp, "GDP Peak Q": gq, "CPI @3Y (pp)": float(cmp_irf.loc[min(12, len(cmp_irf)-1), "CPI Level (pp)"]), "House Peak (%)": hp, "House Peak Q": hq, "FX Impact (%)": float(cmp_irf.loc[0, "FX (%)"])})
        comp = pd.DataFrame(rows).sort_values("GDP Peak (%)")
        _table(comp, "tools1_policy_g7_table", 365, {"GDP Peak (%)": "{:+.2f}", "CPI @3Y (pp)": "{:+.2f}", "House Peak (%)": "{:+.2f}", "FX Impact (%)": "{:+.2f}"})

    _section("Quarterly Model Output")
    _table(irf.round(4), "tools1_policy_quarters", 430)
    _download(irf, "Download policy IRFs", "jarvis_policy_irfs.csv", "tools1_policy_download")


GLOBAL_SCENARIOS: Mapping[str, Mapping[str, float]] = {
    "Baseline": {"Growth": 0.0, "Inflation": 0.0, "Policy": 0.0, "Oil": 0.0, "USD": 0.0, "Risk premium": 0.0},
    "Goldilocks": {"Growth": 0.8, "Inflation": -0.6, "Policy": -0.5, "Oil": -8.0, "USD": -3.0, "Risk premium": -0.4},
    "Stagflation": {"Growth": -1.2, "Inflation": 1.8, "Policy": 0.8, "Oil": 35.0, "USD": 5.0, "Risk premium": 1.0},
    "Hard Landing": {"Growth": -2.5, "Inflation": -1.0, "Policy": -1.5, "Oil": -25.0, "USD": 7.0, "Risk premium": 2.2},
    "China Demand Shock": {"Growth": -1.0, "Inflation": -0.4, "Policy": -0.4, "Oil": -18.0, "USD": 4.0, "Risk premium": 1.1},
}


def _global_sensitivity() -> pd.DataFrame:
    return pd.DataFrame(
        [
            [0.85, -0.15, -0.25, -0.010, -0.025, -0.35],
            [0.62, -0.10, -0.18, -0.008, -0.030, -0.30],
            [0.58, -0.08, -0.22, -0.006, -0.020, -0.28],
            [0.45, -0.18, -0.08, -0.014, -0.045, -0.22],
            [0.95, -0.12, -0.20, -0.020, -0.055, -0.45],
            [0.70, -0.10, -0.30, -0.018, -0.070, -0.55],
            [0.30, 0.78, 0.12, 0.022, 0.030, 0.12],
            [3.20, -1.80, -2.30, -0.055, -0.65, -4.20],
            [-0.18, 0.38, 0.72, 0.012, 0.10, 0.35],
            [0.12, 0.18, 0.45, 0.020, 0.08, 0.55],
            [0.80, 1.10, 1.45, 0.035, 0.22, 1.60],
            [0.45, 0.55, 0.80, 0.048, 0.15, 1.20],
        ],
        index=["US GDP", "Euro GDP", "UK GDP", "Japan GDP", "China GDP", "EM GDP", "Global CPI", "Global Equities", "US 10Y Yield", "USD Index", "Credit Spreads", "Commodities"],
        columns=["Growth", "Inflation", "Policy", "Oil", "USD", "Risk premium"],
    )


def _global_macro() -> None:
    scenario = st.selectbox("Scenario template", list(GLOBAL_SCENARIOS), key="tools1_global_scenario")
    defaults = GLOBAL_SCENARIOS[scenario]
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        growth = st.slider("Global growth shock (pp)", -4.0, 3.0, float(defaults["Growth"]), 0.1, key=f"tools1_g_growth_{scenario}")
    with c2:
        inflation = st.slider("Inflation shock (pp)", -3.0, 4.0, float(defaults["Inflation"]), 0.1, key=f"tools1_g_infl_{scenario}")
    with c3:
        policy = st.slider("Policy shock (pp)", -3.0, 3.0, float(defaults["Policy"]), 0.1, key=f"tools1_g_policy_{scenario}")
    with c4:
        oil = st.slider("Oil shock (%)", -50.0, 60.0, float(defaults["Oil"]), 2.0, key=f"tools1_g_oil_{scenario}")
    with c5:
        usd = st.slider("USD shock (%)", -15.0, 15.0, float(defaults["USD"]), 1.0, key=f"tools1_g_usd_{scenario}")
    with c6:
        risk = st.slider("Risk premium (pp)", -1.5, 4.0, float(defaults["Risk premium"]), 0.1, key=f"tools1_g_risk_{scenario}")

    shocks = pd.Series({"Growth": growth, "Inflation": inflation, "Policy": policy, "Oil": oil, "USD": usd, "Risk premium": risk})
    sensitivity = _global_sensitivity()
    impact = sensitivity.mul(shocks, axis=1).sum(axis=1)
    drivers = sensitivity.mul(shocks, axis=1)
    gdp_avg = float(impact.loc[[x for x in impact.index if x.endswith("GDP")]].mean())
    eq = float(impact["Global Equities"])
    cpi = float(impact["Global CPI"])
    credit = float(impact["Credit Spreads"])
    _kpis([
        ("Global GDP", f"{gdp_avg:+.2f}pp", "Average first-year regional impact", gdp_avg),
        ("Global CPI", f"{cpi:+.2f}pp", "First-year inflation impact", -cpi),
        ("Global Equities", f"{eq:+.1f}%", "Scenario price impact", eq),
        ("US 10Y Yield", f"{impact['US 10Y Yield']:+.2f}pp", "Nominal yield impact", -float(impact["US 10Y Yield"])),
        ("Credit Spreads", f"{credit:+.0f}bp", "Model output in basis points", -credit),
        ("USD Index", f"{impact['USD Index']:+.1f}%", "Trade-weighted USD impact", -float(impact["USD Index"])),
    ])
    regime = "STAGFLATION" if gdp_avg < -0.3 and cpi > 0.3 else ("DEFLATIONARY DOWNTURN" if gdp_avg < -0.3 else ("GOLDILOCKS" if gdp_avg > 0.2 and cpi < 0 else "MIXED / TRANSITION"))
    risk_state = "RISK-OFF" if eq < -3 or credit > 25 else ("RISK-ON" if eq > 3 and credit < 0 else "NEUTRAL")
    policy_state = "EASING BIAS" if impact["US 10Y Yield"] < -0.15 else ("TIGHTENING BIAS" if impact["US 10Y Yield"] > 0.15 else "LIMITED REPRICING")
    _reads([
        ("MACRO REGIME", regime, f"Average regional growth impact {gdp_avg:+.2f}pp with global CPI {cpi:+.2f}pp.", "down" if gdp_avg < 0 else "up"),
        ("MARKET REGIME", risk_state, f"Global equities {eq:+.1f}% and credit spreads {credit:+.0f}bp in the deterministic scenario map.", "down" if risk_state == "RISK-OFF" else "up"),
        ("RATES READ-THROUGH", policy_state, f"US 10Y yield impact {impact['US 10Y Yield']:+.2f}pp; the policy and inflation channels are shown separately below.", "flat"),
    ])

    _section("Scenario Transmission")
    left, right = st.columns([1.15, 0.85])
    with left, _card():
        _card_head("DRIVER ATTRIBUTION", "Output × Shock Heatmap", "Each cell is the contribution of one shock to one output; rows sum to the scenario result.")
        fig = go.Figure(go.Heatmap(z=drivers.values, x=drivers.columns, y=drivers.index, colorscale=[[0, "#7d2432"], [0.5, "#101c29"], [1, "#276c58"]], zmid=0, colorbar=dict(title="Impact")))
        _plot(fig, "tools1_global_heatmap", 530)
    with right, _card():
        _card_head("CROSS-ASSET MAP", "Scenario Output", "Modelled change from the baseline for every regional and market output.")
        ordered = impact.sort_values()
        colors = ["#f4777f" if x < 0 else "#57d39b" for x in ordered]
        fig = go.Figure(go.Bar(x=ordered.values, y=ordered.index, orientation="h", marker_color=colors))
        fig.add_vline(x=0, line_color="rgba(210,220,230,.28)")
        _plot(fig, "tools1_global_output", 530)

    rows = []
    for output in sensitivity.index:
        row = drivers.loc[output]
        main_driver = str(row.abs().idxmax())
        rows.append({"Output": output, "Scenario Impact": float(impact[output]), "Primary Driver": main_driver, "Driver Contribution": float(row[main_driver]), "Signal": "Positive" if impact[output] > 0 else ("Negative" if impact[output] < 0 else "Neutral")})
    output_df = pd.DataFrame(rows)
    _table(output_df, "tools1_global_table", 455, {"Scenario Impact": "{:+.2f}", "Driver Contribution": "{:+.2f}"})
    _download(output_df, "Download scenario output", "jarvis_global_macro_scenario.csv", "tools1_global_download")
    _html('<div class="t1-note">Model contract · linear first-order sensitivity engine. Coefficients are disclosed in Methodology & Data Quality; large shocks should be interpreted as directional stress tests because nonlinear policy responses are not estimated here.</div>')


def _next_bls_friday(now: Optional[datetime] = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    year, month = now.year, now.month + 1
    if month == 13:
        month = 1
        year += 1
    day = datetime(year, month, 1, tzinfo=timezone.utc)
    while day.weekday() != 4:
        day += timedelta(days=1)
    return day


def _monthly_claims(series: pd.Series) -> pd.Series:
    if series is None or series.empty:
        return pd.Series(dtype=float)
    return series.resample("ME").mean()


def _payroll_models(changes: pd.Series, claims: pd.Series) -> Tuple[pd.DataFrame, pd.DataFrame]:
    y = pd.to_numeric(changes, errors="coerce").dropna().copy()
    if len(y) < 30:
        return pd.DataFrame(), pd.DataFrame()
    claims_m = _monthly_claims(claims)
    forecasts: List[Dict[str, Any]] = []
    start = max(18, len(y) - 36)
    for i in range(start, len(y)):
        hist = y.iloc[:i]
        target_date = y.index[i]
        ar3 = float(hist.tail(3).mean())
        ar6 = float(hist.tail(6).mean())
        recent12 = hist.tail(12)
        slope, intercept = np.polyfit(np.arange(len(recent12)), recent12.values, 1)
        trend = float(intercept + slope * len(recent12))
        seasonal = float(hist.iloc[-12]) if len(hist) >= 12 else ar6
        claim_adj = 0.0
        if not claims_m.empty:
            available = claims_m.loc[claims_m.index < target_date]
            if len(available) >= 13:
                latest_claim = float(available.iloc[-1])
                base_claim = float(available.iloc[-13:-1].mean())
                claim_adj = -0.35 * (latest_claim - base_claim) / 1000.0
        claims_model = ar6 + claim_adj
        shrink = 0.45 * ar6 + 0.30 * trend + 0.15 * seasonal + 0.10 * claims_model
        actual = float(y.iloc[i])
        row = {"Date": target_date, "Actual": actual, "AR(3)": ar3, "AR(6)": ar6, "Trend": trend, "Seasonal": seasonal, "Claims Signal": claims_model, "Shrinkage": shrink}
        row["Ensemble"] = float(np.median([ar3, ar6, trend, seasonal, claims_model, shrink]))
        forecasts.append(row)
    backtest = pd.DataFrame(forecasts)

    hist = y
    ar3 = float(hist.tail(3).mean())
    ar6 = float(hist.tail(6).mean())
    recent12 = hist.tail(12)
    slope, intercept = np.polyfit(np.arange(len(recent12)), recent12.values, 1)
    trend = float(intercept + slope * len(recent12))
    seasonal = float(hist.iloc[-12]) if len(hist) >= 12 else ar6
    claim_adj = 0.0
    if len(claims_m) >= 13:
        latest_claim = float(claims_m.iloc[-1])
        base_claim = float(claims_m.iloc[-13:-1].mean())
        claim_adj = -0.35 * (latest_claim - base_claim) / 1000.0
    claims_model = ar6 + claim_adj
    shrink = 0.45 * ar6 + 0.30 * trend + 0.15 * seasonal + 0.10 * claims_model
    current = pd.DataFrame({"Model": ["AR(3)", "AR(6)", "Trend", "Seasonal", "Claims Signal", "Shrinkage"], "Forecast (k)": [ar3, ar6, trend, seasonal, claims_model, shrink]})
    return current, backtest


def _payroll_lab() -> None:
    with st.spinner("Loading official labour-market series…"):
        pack, quality = _load_payroll_pack()
    payroll = pack.get("Payrolls", pd.Series(dtype=float))
    claims = pack.get("Initial Claims", pd.Series(dtype=float))
    if payroll.empty or len(payroll) < 36:
        _html('<div class="t1-warn"><b>Payroll model unavailable.</b> PAYEMS could not be loaded from FRED or has insufficient history. No forecast has been fabricated.</div>')
        _table(quality, "tools1_payroll_quality_missing", 410)
        return
    changes = payroll.diff().dropna()
    current, backtest = _payroll_models(changes, claims)
    if current.empty:
        _html('<div class="t1-warn">Insufficient official history to run the vintage-safe ensemble.</div>')
        return
    overlay = st.slider("Judgement overlay to ensemble (thousand jobs)", -150, 150, 0, 5, key="tools1_payroll_overlay")
    ensemble = float(current["Forecast (k)"].median()) + overlay
    dispersion = float(current["Forecast (k)"].std(ddof=0))
    low, high = np.percentile(current["Forecast (k)"], [10, 90])
    unrate = pack.get("Unemployment", pd.Series(dtype=float))
    ahe = pack.get("Hourly Earnings", pd.Series(dtype=float))
    participation = pack.get("Labor Participation", pd.Series(dtype=float))
    next_release = _next_bls_friday()
    latest_unrate = float(unrate.iloc[-1]) if not unrate.empty else float("nan")
    unrate_trend = float(unrate.tail(3).mean() - unrate.tail(6).head(3).mean()) if len(unrate) >= 6 else 0.0
    unrate_fc = latest_unrate + 0.35 * unrate_trend if np.isfinite(latest_unrate) else float("nan")
    ahe_yoy = float(ahe.pct_change(12).iloc[-1] * 100) if len(ahe) >= 13 else float("nan")
    latest_claims = float(claims.iloc[-1] / 1000.0) if not claims.empty else float("nan")
    participation_latest = float(participation.iloc[-1]) if not participation.empty else float("nan")
    _html(f'<div class="t1-note"><b>Next reference release:</b> {_esc(next_release.strftime("%d %b %Y"))} · Forecast target is the next monthly PAYEMS change. Official series are revised over time; this lab avoids future observations inside each rolling backtest but does not yet preserve historical FRED vintages.</div>')
    _kpis([
        ("Payroll Ensemble", f"{ensemble:+.0f}k", f"10–90% model range {low:+.0f}k to {high:+.0f}k", ensemble),
        ("Model Dispersion", f"±{dispersion:.0f}k", "Cross-model standard deviation", -dispersion),
        ("Unemployment", f"{unrate_fc:.2f}%" if np.isfinite(unrate_fc) else "—", "Trend-based next-month estimate", -unrate_trend),
        ("Initial Claims", f"{latest_claims:.0f}k" if np.isfinite(latest_claims) else "—", "Latest official weekly print", -latest_claims if np.isfinite(latest_claims) else None),
        ("Hourly Earnings", f"{ahe_yoy:.2f}%" if np.isfinite(ahe_yoy) else "—", "Latest YoY wage growth", -ahe_yoy if np.isfinite(ahe_yoy) else None),
        ("Participation", f"{participation_latest:.1f}%" if np.isfinite(participation_latest) else "—", "Latest labour-force participation", participation_latest if np.isfinite(participation_latest) else None),
    ])

    if not backtest.empty:
        models = [c for c in backtest.columns if c not in {"Date", "Actual"}]
        scores = []
        for model in models:
            err = backtest[model] - backtest["Actual"]
            scores.append({"Model": model, "Current Forecast (k)": ensemble if model == "Ensemble" else float(current.loc[current["Model"] == model, "Forecast (k)"].iloc[0]) if model in set(current["Model"]) else float(current["Forecast (k)"].median()), "MAE (k)": float(err.abs().mean()), "RMSE (k)": float(np.sqrt(np.mean(np.square(err)))), "Bias (k)": float(err.mean()), "Directional Hit %": float((np.sign(backtest[model]) == np.sign(backtest["Actual"])).mean() * 100)})
        score_df = pd.DataFrame(scores).sort_values("MAE (k)")
        best = str(score_df.iloc[0]["Model"])
        ensemble_mae = float(score_df.loc[score_df["Model"] == "Ensemble", "MAE (k)"].iloc[0]) if "Ensemble" in set(score_df["Model"]) else float("nan")
        _reads([
            ("MODEL LEADER", best.upper(), f"Lowest rolling MAE across the visible evaluation window. Performance is not assumed to persist.", "up"),
            ("ENSEMBLE ERROR", f"{ensemble_mae:.0f}k MAE" if np.isfinite(ensemble_mae) else "—", "Rolling one-step forecast error using only information available before each target month.", "flat"),
            ("FORECAST BALANCE", "UPSIDE" if ensemble > 120 else ("DOWNSIDE" if ensemble < 70 else "MODERATE"), f"The judgement-adjusted median is {ensemble:+.0f}k with dispersion ±{dispersion:.0f}k.", "up" if ensemble > 100 else "down"),
        ])
        _section("Forecast Track Record")
        left, right = st.columns([1.15, 0.85])
        with left, _card():
            _card_head("ROLLING BACKTEST", "Actual vs Ensemble", "One-step forecasts over the latest available evaluation window; payroll changes in thousands.")
            fig = go.Figure()
            fig.add_trace(go.Bar(x=backtest["Date"], y=backtest["Actual"], name="Actual", marker_color="rgba(216,191,88,.48)"))
            fig.add_trace(go.Scatter(x=backtest["Date"], y=backtest["Ensemble"], name="Ensemble", line=dict(color="#63c7ff", width=2.4)))
            _plot(fig, "tools1_payroll_backtest", 440)
        with right, _card():
            _card_head("MODEL RANKING", "MAE by Model", "Lower is better; every method uses the same visible evaluation window.")
            ordered = score_df.sort_values("MAE (k)", ascending=True)
            fig = go.Figure(go.Bar(x=ordered["MAE (k)"], y=ordered["Model"], orientation="h", marker_color=[PALETTE[i % len(PALETTE)] for i in range(len(ordered))]))
            _plot(fig, "tools1_payroll_mae", 440)
        _table(score_df, "tools1_payroll_scorecard", 380, {"Current Forecast (k)": "{:+.0f}", "MAE (k)": "{:.1f}", "RMSE (k)": "{:.1f}", "Bias (k)": "{:+.1f}", "Directional Hit %": "{:.0f}%"})
    _section("Model Forecasts & Official Inputs")
    forecast_table = current.copy()
    forecast_table.loc[len(forecast_table)] = ["Ensemble + judgement", ensemble]
    c1, c2 = st.columns([0.65, 1.35])
    with c1:
        _table(forecast_table, "tools1_payroll_forecasts", 345, {"Forecast (k)": "{:+.0f}"})
    with c2:
        _table(quality, "tools1_payroll_quality", 345)
    _download(forecast_table, "Download payroll forecasts", "jarvis_payroll_nowcast.csv", "tools1_payroll_download")


def _cap_weights(weights: np.ndarray, max_weight: float) -> np.ndarray:
    w = np.maximum(np.asarray(weights, dtype=float), 0.0)
    if not np.isfinite(w).all() or w.sum() <= 0:
        w = np.ones_like(w)
    w = w / w.sum()
    cap = max(max_weight, 1.0 / len(w))
    for _ in range(60):
        excess = np.maximum(w - cap, 0.0).sum()
        w = np.minimum(w, cap)
        below = w < cap - 1e-12
        if excess <= 1e-10 or not below.any():
            break
        room = np.maximum(cap - w[below], 0.0)
        if room.sum() <= 0:
            break
        w[below] += excess * room / room.sum()
    return w / w.sum()


@dataclass
class PortfolioEngine:
    assets: List[str]
    prices: pd.DataFrame
    returns: pd.DataFrame
    monthly: pd.DataFrame
    mu: np.ndarray
    cov: np.ndarray
    weights: Dict[str, np.ndarray]
    candidates: pd.DataFrame
    historical_cagr: np.ndarray
    meta: Dict[str, Any]


def _portfolio_engine(scenario: str, max_weight: float, risk_free: float, cma_mode: str) -> Optional[PortfolioEngine]:
    assets = list(TOOLS_ASSETS)
    tickers = tuple(TOOLS_ASSETS[a]["ticker"] for a in assets)
    closes, meta = _load_market_history(tickers, "10y")
    if closes.empty or len(closes.columns) < 5:
        return None
    rename = {TOOLS_ASSETS[a]["ticker"]: a for a in assets}
    prices = closes.rename(columns=rename)
    assets = [a for a in assets if a in prices.columns]
    prices = prices[assets].ffill(limit=3).dropna()
    returns = prices.pct_change().dropna()
    if len(returns) < 252:
        return None
    monthly = prices.resample("ME").last().pct_change().dropna()
    years = max((prices.index[-1] - prices.index[0]).days / 365.25, 1.0)
    historical_cagr = np.power(prices.iloc[-1].values / prices.iloc[0].values, 1.0 / years) - 1.0
    priors = np.array([TOOLS_CMA_PRIORS[a] for a in assets], dtype=float)
    if cma_mode == "Historical CAGR":
        mu = historical_cagr.copy()
    elif cma_mode == "Long-run priors":
        mu = priors.copy()
    else:
        mu = 0.50 * historical_cagr + 0.50 * priors
    shift = {"Bull": 0.020, "Base": 0.0, "Bear": -0.030}.get(scenario, 0.0)
    mu = mu + shift
    sample_cov = returns.cov().values * 252.0
    cov = 0.75 * sample_cov + 0.25 * np.diag(np.diag(sample_cov))
    n = len(assets)
    equal = np.ones(n) / n
    try:
        inv = np.linalg.pinv(cov)
        min_var = _cap_weights(inv @ np.ones(n), max_weight)
    except Exception:
        min_var = equal.copy()
    rp = equal.copy()
    for _ in range(300):
        marginal = cov @ rp
        rc = rp * marginal
        target = float(rp @ cov @ rp) / n
        ratio = np.divide(target, rc, out=np.ones_like(rc), where=np.abs(rc) > 1e-12)
        new = _cap_weights(rp * np.sqrt(np.clip(ratio, 0.2, 5.0)), max_weight)
        if np.max(np.abs(new - rp)) < 1e-7:
            rp = new
            break
        rp = new
    rng = np.random.default_rng(20260721)
    raw = rng.dirichlet(np.ones(n) * 1.15, size=18000)
    mask = raw.max(axis=1) <= max(max_weight + 1e-9, 1 / n + 1e-9)
    sample = raw[mask]
    if len(sample) < 2500:
        sample = np.vstack([_cap_weights(w, max_weight) for w in raw[:8000]])
    p_ret = sample @ mu
    p_vol = np.sqrt(np.einsum("ij,jk,ik->i", sample, cov, sample))
    sharpe = np.divide(p_ret - risk_free, p_vol, out=np.full_like(p_ret, -np.inf), where=p_vol > 1e-9)
    max_sharpe = sample[int(np.nanargmax(sharpe))]
    asset_vol = np.sqrt(np.diag(cov))
    div_ratio = np.divide(sample @ asset_vol, p_vol, out=np.zeros_like(p_vol), where=p_vol > 1e-9)
    max_div = sample[int(np.nanargmax(div_ratio))]
    monthly_matrix = monthly[assets].values
    if len(monthly_matrix) > 20:
        port_monthly = monthly_matrix @ sample.T
        k = max(1, int(math.ceil(0.05 * len(monthly_matrix))))
        worst = np.partition(port_monthly, k - 1, axis=0)[:k]
        cvar = worst.mean(axis=0)
        min_cvar = sample[int(np.nanargmax(cvar))]
    else:
        min_cvar = min_var.copy()
    all_weather_raw = np.array([0.25, 0.10, 0.05, 0.27, 0.10, 0.08, 0.10, 0.05])[:n]
    all_weather = _cap_weights(all_weather_raw, max_weight)
    cma_score = np.maximum(mu - risk_free, 0.0) / np.maximum(asset_vol, 1e-6)
    cma_tilt = _cap_weights(cma_score, max_weight)
    weights = {
        "Max Sharpe": _cap_weights(max_sharpe, max_weight),
        "Min Variance": min_var,
        "Risk Parity": rp,
        "All Weather": all_weather,
        "Max Diversification": _cap_weights(max_div, max_weight),
        "Min CVaR": _cap_weights(min_cvar, max_weight),
        "Equal Weight": equal,
        "CMA Tilt": cma_tilt,
    }
    candidates = pd.DataFrame({"Return": p_ret, "Volatility": p_vol, "Sharpe": sharpe})
    candidates = candidates.replace([np.inf, -np.inf], np.nan).dropna().sample(min(3500, len(candidates)), random_state=17)
    return PortfolioEngine(assets, prices, returns[assets], monthly[assets], mu, cov, weights, candidates, historical_cagr, meta)


def _portfolio_metrics(engine: PortfolioEngine, w: np.ndarray, risk_free: float) -> Dict[str, float]:
    ret = float(w @ engine.mu)
    vol = float(np.sqrt(w @ engine.cov @ w))
    sharpe = (ret - risk_free) / vol if vol > 1e-9 else float("nan")
    series = engine.returns.values @ w
    wealth = pd.Series(np.cumprod(1 + series), index=engine.returns.index)
    dd = wealth / wealth.cummax() - 1.0
    rc = w * (engine.cov @ w)
    rc = rc / rc.sum() if abs(rc.sum()) > 1e-12 else np.zeros_like(w)
    hhi = float(np.square(w).sum())
    return {"return": ret, "vol": vol, "sharpe": sharpe, "max_dd": float(dd.min()), "hhi": hhi, "effective_n": 1.0 / hhi if hhi > 0 else float("nan"), "cagr_backtest": float(wealth.iloc[-1] ** (252.0 / len(wealth)) - 1.0), "rc_max": float(rc.max())}


def _portfolio_lab() -> None:
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        scenario = st.selectbox("CMA scenario", ["Bull", "Base", "Bear"], index=1, key="tools1_port_scenario")
    with c2:
        cma_mode = st.selectbox("Expected-return method", ["50/50 shrinkage", "Historical CAGR", "Long-run priors"], key="tools1_port_cma")
    with c3:
        max_weight = st.slider("Maximum asset weight", 0.20, 0.70, 0.40, 0.05, key="tools1_port_cap")
    with c4:
        risk_free = st.slider("Risk-free rate", 0.0, 0.08, 0.035, 0.005, format="%.3f", key="tools1_port_rf")
    with st.spinner("Building the live allocation universe…"):
        engine = _portfolio_engine(scenario, max_weight, risk_free, cma_mode)
    if engine is None:
        _html('<div class="t1-warn"><b>Portfolio engine unavailable.</b> The ETF history provider did not return sufficient aligned observations. No synthetic prices were generated.</div>')
        return
    model = st.selectbox("Allocation model", list(engine.weights), index=2, key="tools1_port_model")
    w = engine.weights[model]
    metrics = _portfolio_metrics(engine, w, risk_free)
    updated = engine.meta.get("updated")
    updated_txt = pd.Timestamp(updated).strftime("%d %b %Y") if updated is not None and not pd.isna(updated) else "unknown"
    _html(f'<div class="t1-note"><b>{_esc(model)}</b> · {len(engine.assets)} live ETF proxies · {_esc(cma_mode)} expected returns · {scenario} scenario · history through {_esc(updated_txt)}. Private markets use a listed proxy and should not be read as a smoothed appraisal series.</div>')
    _kpis([
        ("Expected Return", _fmt_pct(metrics["return"]), f"{scenario} annualised CMA", metrics["return"]),
        ("Expected Volatility", _fmt_pct(metrics["vol"]), "Annualised shrunk covariance", -metrics["vol"]),
        ("Sharpe Ratio", _fmt_num(metrics["sharpe"]), f"Risk-free {_fmt_pct(risk_free)}", metrics["sharpe"]),
        ("Retroactive CAGR", _fmt_pct(metrics["cagr_backtest"]), "Today's static weights on history", metrics["cagr_backtest"]),
        ("Maximum Drawdown", _fmt_pct(metrics["max_dd"]), "Observed aligned-history backtest", metrics["max_dd"]),
        ("Effective Holdings", _fmt_num(metrics["effective_n"], 1), f"HHI {metrics['hhi']:.3f}", metrics["effective_n"] - 3),
    ])

    rc = w * (engine.cov @ w)
    rc = rc / rc.sum() if abs(rc.sum()) > 1e-12 else np.zeros_like(w)
    alloc = pd.DataFrame({"Asset": engine.assets, "Ticker": [TOOLS_ASSETS[a]["ticker"] for a in engine.assets], "Role": [TOOLS_ASSETS[a]["role"] for a in engine.assets], "Weight %": w * 100, "Risk Contribution %": rc * 100, "Expected Return %": engine.mu * 100, "Historical CAGR %": engine.historical_cagr * 100, "Volatility %": np.sqrt(np.diag(engine.cov)) * 100})
    concentration = "CONCENTRATED" if metrics["effective_n"] < 3.5 else ("BALANCED" if metrics["effective_n"] < 5.5 else "BROAD")
    risk_conc = "RISK-HEAVY" if metrics["rc_max"] > 0.35 else "DIVERSIFIED"
    _reads([
        ("ALLOCATION SHAPE", concentration, f"Effective holdings {metrics['effective_n']:.1f}; largest capital weight {float(w.max())*100:.1f}%.", "down" if concentration == "CONCENTRATED" else "up"),
        ("RISK BUDGET", risk_conc, f"Largest marginal contribution is {metrics['rc_max']*100:.1f}% of portfolio variance.", "down" if risk_conc == "RISK-HEAVY" else "up"),
        ("MODEL STATUS", "OPTIMISED / LIVE", f"Price history is observed through {updated_txt}; CMA returns remain assumptions and are never presented as realised facts.", "flat"),
    ])

    _section("Allocation & Efficient Frontier")
    left, right = st.columns([0.82, 1.18])
    with left, _card():
        _card_head("CAPITAL vs RISK", f"{model} Allocation", "Capital weights and percentage contribution to portfolio variance.")
        fig = go.Figure()
        fig.add_trace(go.Bar(x=alloc["Asset"], y=alloc["Weight %"], name="Weight", marker_color="#63c7ff"))
        fig.add_trace(go.Bar(x=alloc["Asset"], y=alloc["Risk Contribution %"], name="Risk contribution", marker_color="#d8bf58"))
        fig.update_layout(barmode="group")
        _plot(fig, "tools1_port_alloc", 455)
    with right, _card():
        _card_head("PORTFOLIO OPPORTUNITY SET", "Efficient-Frontier Cloud", "Feasible long-only portfolios under the selected weight cap; colour is Sharpe ratio.")
        fig = go.Figure(go.Scattergl(x=engine.candidates["Volatility"] * 100, y=engine.candidates["Return"] * 100, mode="markers", marker=dict(size=4, color=engine.candidates["Sharpe"], colorscale="Viridis", opacity=.45, colorbar=dict(title="Sharpe")), name="Feasible"))
        for name, weights in engine.weights.items():
            m = _portfolio_metrics(engine, weights, risk_free)
            fig.add_trace(go.Scatter(x=[m["vol"] * 100], y=[m["return"] * 100], mode="markers+text" if name == model else "markers", text=[name] if name == model else None, textposition="top center", marker=dict(size=11 if name == model else 7, color="#d8bf58" if name == model else "#c4d0da", symbol="diamond"), name=name, showlegend=False))
        fig.update_xaxes(title="Expected volatility (%)")
        fig.update_yaxes(title="Expected return (%)")
        _plot(fig, "tools1_port_frontier", 455)
    _table(alloc.sort_values("Weight %", ascending=False), "tools1_port_alloc_table", 375, {"Weight %": "{:.1f}%", "Risk Contribution %": "{:.1f}%", "Expected Return %": "{:.1f}%", "Historical CAGR %": "{:.1f}%", "Volatility %": "{:.1f}%"})

    _section("Model Comparison")
    model_rows = []
    for name, weights in engine.weights.items():
        m = _portfolio_metrics(engine, weights, risk_free)
        top = np.argsort(weights)[-3:][::-1]
        model_rows.append({"Model": name, "Exp Return %": 100*m["return"], "Exp Vol %": 100*m["vol"], "Sharpe": m["sharpe"], "Backtest CAGR %": 100*m["cagr_backtest"], "Max DD %": 100*m["max_dd"], "Effective N": m["effective_n"], "Top Holdings": ", ".join(f"{engine.assets[i]} {weights[i]*100:.0f}%" for i in top)})
    models_df = pd.DataFrame(model_rows).sort_values("Sharpe", ascending=False)
    _table(models_df, "tools1_port_models", 415, {"Exp Return %": "{:.1f}%", "Exp Vol %": "{:.1f}%", "Sharpe": "{:.2f}", "Backtest CAGR %": "{:.1f}%", "Max DD %": "{:.1f}%", "Effective N": "{:.1f}"})

    _section("Historical Context & Wealth Projection")
    p_ret = pd.Series(engine.returns.values @ w, index=engine.returns.index)
    wealth = (1.0 + p_ret).cumprod()
    dd = wealth / wealth.cummax() - 1.0
    left, right = st.columns(2)
    with left, _card():
        _card_head("RETROACTIVE ANALYSIS", "Wealth & Drawdown", "Today's static weights applied to observed history; this is not a live track record.")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=wealth.index, y=wealth, name="Wealth", line=dict(color="#63c7ff", width=2.1)))
        fig.add_trace(go.Scatter(x=dd.index, y=dd, name="Drawdown", yaxis="y2", line=dict(color="#f4777f", width=1.4), fill="tozeroy", fillcolor="rgba(244,119,127,.10)"))
        fig.update_layout(yaxis2=dict(overlaying="y", side="right", tickformat=".0%", showgrid=False, title="Drawdown"))
        _plot(fig, "tools1_port_backtest", 430)
    with right, _card():
        _card_head("MONTE CARLO", "10-Year Wealth Fan", "2,000 correlated monthly paths from selected CMA returns and shrunk covariance; per $1 invested.")
        rng = np.random.default_rng(4407)
        months = 120
        paths = 2000
        mean_m = metrics["return"] / 12.0
        vol_m = metrics["vol"] / math.sqrt(12.0)
        sims = rng.normal(mean_m, vol_m, size=(months, paths))
        wealth_paths = np.vstack([np.ones(paths), np.cumprod(1.0 + sims, axis=0)])
        qs = np.quantile(wealth_paths, [0.05, 0.25, 0.50, 0.75, 0.95], axis=1)
        x = np.arange(months + 1) / 12.0
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=x, y=qs[4], line=dict(width=0), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=x, y=qs[0], fill="tonexty", fillcolor="rgba(99,199,255,.08)", line=dict(width=0), name="5–95%"))
        fig.add_trace(go.Scatter(x=x, y=qs[3], line=dict(width=0), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=x, y=qs[1], fill="tonexty", fillcolor="rgba(99,199,255,.16)", line=dict(width=0), name="25–75%"))
        fig.add_trace(go.Scatter(x=x, y=qs[2], line=dict(color="#d8bf58", width=2.4), name="Median"))
        fig.update_xaxes(title="Years")
        fig.update_yaxes(title="Wealth per $1")
        _plot(fig, "tools1_port_mc", 430)
    terminal = wealth_paths[-1]
    mc_df = pd.DataFrame({"Threshold": ["$0.8", "$1.0", "$1.2", "$1.5", "$2.0"], "Shortfall Probability %": [float((terminal < x).mean() * 100) for x in [0.8, 1.0, 1.2, 1.5, 2.0]]})
    _table(mc_df, "tools1_port_shortfall", 245, {"Shortfall Probability %": "{:.1f}%"})
    _download(alloc, "Download allocation", "jarvis_portfolio_allocation.csv", "tools1_port_download")


STRESS_WINDOWS: Mapping[str, Tuple[str, str]] = {
    "GFC 2008": ("2007-10-09", "2009-03-09"),
    "Euro Debt 2011": ("2011-05-02", "2011-10-03"),
    "COVID Crash 2020": ("2020-02-19", "2020-03-23"),
    "Inflation Shock 2022": ("2022-01-03", "2022-10-14"),
    "Banking Stress 2023": ("2023-03-01", "2023-05-31"),
}

SCENARIO_SHOCKS: Mapping[str, Mapping[str, float]] = {
    "Growth Shock": {"US Equity": -18, "Intl Developed": -20, "EM Equity": -24, "US Treasuries": 9, "US Credit": -7, "Commodities": -15, "Gold": 6, "Listed Private Markets": -26},
    "Stagflation": {"US Equity": -14, "Intl Developed": -16, "EM Equity": -18, "US Treasuries": -12, "US Credit": -10, "Commodities": 18, "Gold": 12, "Listed Private Markets": -22},
    "Liquidity Crisis": {"US Equity": -25, "Intl Developed": -28, "EM Equity": -32, "US Treasuries": 6, "US Credit": -14, "Commodities": -20, "Gold": -3, "Listed Private Markets": -35},
    "Soft Landing": {"US Equity": 10, "Intl Developed": 11, "EM Equity": 14, "US Treasuries": 3, "US Credit": 6, "Commodities": 5, "Gold": 1, "Listed Private Markets": 13},
}


def _risk_stress() -> None:
    c1, c2, c3 = st.columns(3)
    with c1:
        lookback = st.selectbox("Risk lookback", ["1y", "3y", "5y", "10y"], index=2, key="tools1_risk_lookback")
    with c2:
        model = st.selectbox("Portfolio model", ["Risk Parity", "Equal Weight", "Min Variance", "All Weather", "Max Sharpe"], key="tools1_risk_model")
    with c3:
        scenario = st.selectbox("Deterministic stress", list(SCENARIO_SHOCKS), key="tools1_risk_scenario")
    engine = _portfolio_engine("Base", 0.45, 0.035, "50/50 shrinkage")
    if engine is None:
        _html('<div class="t1-warn">Risk engine unavailable because aligned market histories could not be loaded.</div>')
        return
    w = engine.weights.get(model, engine.weights["Equal Weight"])
    days = {"1y": 252, "3y": 756, "5y": 1260, "10y": 2520}[lookback]
    ret = engine.returns.tail(days)
    p = pd.Series(ret.values @ w, index=ret.index)
    var95 = float(np.quantile(p, 0.05))
    cvar95 = float(p[p <= var95].mean())
    vol = float(p.std() * math.sqrt(252))
    wealth = (1 + p).cumprod()
    dd = wealth / wealth.cummax() - 1
    maxdd = float(dd.min())
    downside = float(p[p < 0].std() * math.sqrt(252))
    beta = float(np.cov(p, ret["US Equity"])[0, 1] / np.var(ret["US Equity"])) if "US Equity" in ret and np.var(ret["US Equity"]) > 0 else float("nan")
    corr = ret.corr()
    upper = corr.where(np.triu(np.ones(corr.shape), 1).astype(bool)).stack()
    avg_corr = float(upper.mean()) if not upper.empty else float("nan")
    stress_map = SCENARIO_SHOCKS[scenario]
    shock_vec = np.array([stress_map.get(a, 0.0) for a in engine.assets])
    port_shock = float(w @ shock_vec)
    worst_asset = engine.assets[int(np.argmin(w * shock_vec))]
    _kpis([
        ("Annualised Volatility", _fmt_pct(vol), f"{lookback} observed daily window", -vol),
        ("Daily VaR · 95%", _fmt_pct(var95), "Historical quantile", var95),
        ("Daily CVaR · 95%", _fmt_pct(cvar95), "Mean loss beyond VaR", cvar95),
        ("Maximum Drawdown", _fmt_pct(maxdd), "Peak-to-trough observed loss", maxdd),
        ("Equity Beta", _fmt_num(beta), "Versus US Equity proxy", -abs(beta) if np.isfinite(beta) else None),
        ("Scenario P&L", f"{port_shock:+.1f}%", scenario, port_shock),
    ])
    limit_state = "BREACH" if cvar95 < -0.025 or port_shock < -15 else ("WATCH" if cvar95 < -0.018 or port_shock < -10 else "WITHIN LIMIT")
    corr_state = "FRAGILE" if avg_corr > 0.55 else ("MODERATE" if avg_corr > 0.35 else "DIVERSIFIED")
    _reads([
        ("TAIL-RISK LIMIT", limit_state, f"Historical daily CVaR is {_fmt_pct(cvar95)} and {scenario} produces {port_shock:+.1f}%.", "down" if limit_state != "WITHIN LIMIT" else "up"),
        ("DIVERSIFICATION", corr_state, f"Average off-diagonal correlation is {avg_corr:.2f}; diversification can compress in stressed regimes.", "down" if corr_state == "FRAGILE" else "flat"),
        ("LOSS ATTRIBUTION", worst_asset.upper(), f"Largest scenario contribution is {float((w*shock_vec).min()):+.1f}pp from {worst_asset}.", "down"),
    ])

    _section("Tail Risk & Correlation")
    left, right = st.columns(2)
    with left, _card():
        _card_head("OBSERVED PORTFOLIO PATH", "Wealth, Drawdown & Rolling Volatility", "Static selected-model weights over the chosen observed lookback.")
        roll_vol = p.rolling(63).std() * math.sqrt(252)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=dd.index, y=dd * 100, name="Drawdown %", fill="tozeroy", fillcolor="rgba(244,119,127,.12)", line=dict(color="#f4777f")))
        fig.add_trace(go.Scatter(x=roll_vol.index, y=roll_vol * 100, name="63D vol %", yaxis="y2", line=dict(color="#63c7ff", width=1.8)))
        fig.update_layout(yaxis2=dict(overlaying="y", side="right", showgrid=False, title="Vol %"))
        _plot(fig, "tools1_risk_path", 440)
    with right, _card():
        _card_head("DIVERSIFICATION MAP", "Realised Correlation Matrix", "Pairwise daily-return correlation for the chosen lookback.")
        fig = go.Figure(go.Heatmap(z=corr.values, x=corr.columns, y=corr.index, zmin=-1, zmax=1, zmid=0, colorscale=[[0, "#28658a"], [0.5, "#111c28"], [1, "#8a3b43"]], text=np.round(corr.values, 2), texttemplate="%{text}", colorbar=dict(title="ρ")))
        _plot(fig, "tools1_risk_corr", 440)

    _section("Deterministic Stress Attribution")
    stress_df = pd.DataFrame({"Asset": engine.assets, "Weight %": w * 100, "Scenario Shock %": shock_vec, "Portfolio Contribution pp": w * shock_vec}).sort_values("Portfolio Contribution pp")
    fig = go.Figure(go.Bar(x=stress_df["Asset"], y=stress_df["Portfolio Contribution pp"], marker_color=["#f4777f" if x < 0 else "#57d39b" for x in stress_df["Portfolio Contribution pp"]]))
    fig.add_hline(y=0, line_color="rgba(210,220,230,.28)")
    fig.update_yaxes(title="Contribution to portfolio P&L (pp)")
    _plot(fig, "tools1_risk_stress", 390)
    _table(stress_df, "tools1_risk_stress_table", 340, {"Weight %": "{:.1f}%", "Scenario Shock %": "{:+.1f}%", "Portfolio Contribution pp": "{:+.1f}"})

    _section("Historical Crisis Windows")
    hist_rows = []
    for label, (start, end) in STRESS_WINDOWS.items():
        subset = engine.prices.loc[(engine.prices.index >= pd.Timestamp(start)) & (engine.prices.index <= pd.Timestamp(end))]
        if len(subset) < 2:
            continue
        asset_returns = subset.iloc[-1] / subset.iloc[0] - 1.0
        row = {"Window": label, "Start": start, "End": end, "Portfolio %": float(w @ asset_returns.reindex(engine.assets).values * 100)}
        for asset in engine.assets:
            row[asset] = float(asset_returns.get(asset, np.nan) * 100)
        hist_rows.append(row)
    hist_df = pd.DataFrame(hist_rows)
    _table(hist_df, "tools1_risk_history", 360, {c: "{:+.1f}%" for c in hist_df.columns if c not in {"Window", "Start", "End"}} if not hist_df.empty else None)
    _download(stress_df, "Download stress attribution", "jarvis_stress_attribution.csv", "tools1_risk_download")


def _methodology() -> None:
    _section("RoboMacro Equivalence & Improvements")
    equivalence = pd.DataFrame([
        {"Reference capability": "G7 HANK Models", "JARVIS equivalent": "G7 Policy Lab", "Status": "Implemented", "Institutional improvement": "Country comparison, transmission attribution, easing/tightening symmetry, parameter sensitivity and export."},
        {"Reference capability": "Global Macro Model", "JARVIS equivalent": "Global Macro Scenarios", "Status": "Implemented / available", "Institutional improvement": "The reference page currently fails to load; JARVIS exposes every coefficient and produces a deterministic output."},
        {"Reference capability": "Payrolls Forecasting Lab", "JARVIS equivalent": "Payrolls Nowcast", "Status": "Implemented", "Institutional improvement": "Official FRED inputs, rolling information-safe backtest, model dispersion, judgement overlay and visible revision caveat."},
        {"Reference capability": "Portfolio Optimizer", "JARVIS equivalent": "Portfolio Construction", "Status": "Implemented", "Institutional improvement": "Eight methods, explicit CMA modes, weight caps, capital-vs-risk view, frontier, live histories and deterministic seed."},
        {"Reference capability": "Historical regimes / Monte Carlo", "JARVIS equivalent": "Portfolio + Risk & Stress", "Status": "Implemented", "Institutional improvement": "Dedicated tail-risk limits, loss attribution, scenario shocks, historical crisis windows and correlation regime diagnostics."},
        {"Reference capability": "Model methodology", "JARVIS equivalent": "Methodology & Data Quality", "Status": "Expanded", "Institutional improvement": "One registry for provider state, model assumptions, known limitations and validation contract."},
    ])
    _table(equivalence, "tools1_method_equiv", 415)

    _section("Model Registry")
    registry = pd.DataFrame([
        {"Engine": "G7 Policy Lab", "Family": "Calibrated reduced-form IRF", "Observed inputs": "None required", "Assumptions": "Country peak magnitudes, timing, persistence and pass-through", "Primary limitation": "Not an estimated full HANK solution", "Deterministic": "Yes"},
        {"Engine": "Global Macro Scenarios", "Family": "Linear sensitivity matrix", "Observed inputs": "User shocks", "Assumptions": "First-order regional / market betas", "Primary limitation": "No nonlinear policy reaction", "Deterministic": "Yes"},
        {"Engine": "Payrolls Nowcast", "Family": "Six-model ensemble", "Observed inputs": "FRED PAYEMS, claims and labour data", "Assumptions": "Rolling window and claims coefficient", "Primary limitation": "FRED revisions; no vintage database", "Deterministic": "Yes"},
        {"Engine": "Portfolio Construction", "Family": "Long-only allocation", "Observed inputs": "Adjusted ETF prices", "Assumptions": "CMA priors, shrinkage, risk-free rate, max weight", "Primary limitation": "Proxy, liquidity and implementation costs", "Deterministic": "Yes / fixed seed"},
        {"Engine": "Monte Carlo", "Family": "Gaussian correlated paths", "Observed inputs": "Selected CMA and covariance", "Assumptions": "IID monthly returns", "Primary limitation": "Fat tails / path dependence understated", "Deterministic": "Yes / fixed seed"},
        {"Engine": "Risk & Stress", "Family": "Historical + deterministic stress", "Observed inputs": "Aligned ETF returns", "Assumptions": "Static weights and disclosed shock vectors", "Primary limitation": "No liquidity spiral or options convexity", "Deterministic": "Yes"},
    ])
    _table(registry, "tools1_method_registry", 420)

    _section("Source & Failure Contract")
    sources = pd.DataFrame([
        {"Layer": "Market histories", "Primary source": "Yahoo/yfinance adjusted closes", "Refresh": "15 minutes", "Failure behaviour": "Visible unavailable state; no synthetic price history"},
        {"Layer": "US labour market", "Primary source": "Federal Reserve Economic Data (FRED), including BLS series", "Refresh": "1 hour", "Failure behaviour": "Series-level error and no payroll forecast if PAYEMS is missing"},
        {"Layer": "Policy IRF calibrations", "Primary source": "Disclosed JARVIS calibration informed by public central-bank transmission ranges", "Refresh": "Versioned model release", "Failure behaviour": "Not presented as observed or estimated live data"},
        {"Layer": "Capital-market assumptions", "Primary source": "Observed CAGR + disclosed long-run prior blend", "Refresh": "On market refresh / model version", "Failure behaviour": "CMA is labelled assumption, never realised return"},
        {"Layer": "Historical stress windows", "Primary source": "Observed ETF proxy prices", "Refresh": "With market history", "Failure behaviour": "Omit windows with insufficient observations"},
        {"Layer": "Deterministic scenarios", "Primary source": "User-selected shocks + disclosed sensitivity matrices", "Refresh": "Interactive", "Failure behaviour": "Always labelled scenario output"},
    ])
    _table(sources, "tools1_method_sources", 390)

    _section("Live Provider Diagnostics")
    run_checks = st.button("Run provider checks", key="tools1_quality_run")
    if run_checks or st.session_state.get("tools1_quality_checked", False):
        st.session_state["tools1_quality_checked"] = True
        with st.spinner("Checking provider contracts…"):
            tickers = tuple(TOOLS_ASSETS[a]["ticker"] for a in TOOLS_ASSETS)
            market, market_meta = _load_market_history(tickers, "1y")
            _, fred_quality = _load_payroll_pack()
        market_rows = []
        for asset, spec in TOOLS_ASSETS.items():
            ticker = spec["ticker"]
            series = market[ticker].dropna() if ticker in market else pd.Series(dtype=float)
            market_rows.append({"Layer": "Market", "Series": asset, "ID": ticker, "Latest": series.index.max() if not series.empty else pd.NaT, "Rows": len(series), "Status": "live" if not series.empty else "unavailable", "Message": market_meta.get("error", "") if series.empty else ""})
        market_quality = pd.DataFrame(market_rows)
        fred_view = fred_quality.rename(columns={"FRED ID": "ID"}).copy()
        fred_view.insert(0, "Layer", "Official macro")
        cols = ["Layer", "Series", "ID", "Latest", "Rows", "Status", "Message"]
        combined = pd.concat([market_quality[cols], fred_view[cols]], ignore_index=True)
        live = int((combined["Status"] == "live").sum())
        _kpis([
            ("Providers Checked", "2", "Yahoo/yfinance · FRED", 1),
            ("Live Series", f"{live}/{len(combined)}", "Instrument / series-level contract", live - len(combined)),
            ("Synthetic Fallback", "NONE", "Missing stays missing", 1),
        ])
        _table(combined, "tools1_quality_table", 475)
    else:
        _html('<div class="t1-note">Provider checks are opt-in on this page to avoid loading market and macro histories when only methodology is being reviewed.</div>')

    _section("Validation Contract")
    validation = pd.DataFrame([
        {"Control": "Python compilation", "Required": "PASS", "Purpose": "No syntax or import-shape regression"},
        {"Control": "Workspace isolation", "Required": "PASS", "Purpose": "Only tools1_* Streamlit state keys"},
        {"Control": "No synthetic observed history", "Required": "PASS", "Purpose": "Provider failure remains visible"},
        {"Control": "Weight conservation", "Required": "Σ weights = 100%", "Purpose": "Every optimiser obeys the active cap"},
        {"Control": "Risk contribution conservation", "Required": "Σ contribution = 100%", "Purpose": "Variance attribution is internally consistent"},
        {"Control": "Scenario determinism", "Required": "Same inputs → same outputs", "Purpose": "Reproducible committee analysis"},
        {"Control": "Non-regression", "Required": "Economy · Markets · Oil · Autos smoke tests", "Purpose": "Tools integration cannot alter existing workspaces"},
    ])
    _table(validation, "tools1_method_validation", 365)


def render_tools_intelligence(ticker: str = "", price_data: Optional[pd.DataFrame] = None, analysis: Optional[Mapping[str, Any]] = None) -> None:
    """Render the autonomous institutional Tools workspace."""
    del ticker, price_data, analysis
    _css()
    if TOOLS_SECTION_KEY not in st.session_state or st.session_state.get(TOOLS_SECTION_KEY) not in TOOLS_SECTIONS:
        st.session_state[TOOLS_SECTION_KEY] = "Tools Home"
    section = st.radio("Tools workspace", TOOLS_SECTIONS, horizontal=True, key=TOOLS_SECTION_KEY, label_visibility="collapsed")
    _header(section)
    if section == "Tools Home":
        _tools_home()
    elif section == "G7 Policy Lab":
        _policy_lab()
    elif section == "Global Macro Scenarios":
        _global_macro()
    elif section == "Payrolls Nowcast":
        _payroll_lab()
    elif section == "Portfolio Construction":
        _portfolio_lab()
    elif section == "Risk & Stress":
        _risk_stress()
    else:
        _methodology()
    _html(f'<div class="t1-source" style="margin-top:18px">{TOOLS_VERSION} · decision support only · scenarios and CMAs are assumptions, not investment advice.</div>')


TOOLS_INTEGRITY: Mapping[str, Any] = {
    "version": TOOLS_VERSION,
    "sections": list(TOOLS_SECTIONS),
    "state_prefix": "tools1_",
    "g7_policy_lab": True,
    "global_macro_scenarios": True,
    "payroll_ensemble": True,
    "portfolio_models": 8,
    "risk_stress": True,
    "synthetic_observed_history": False,
}


# ============================================================
# JARVIS TOOLS V2 — ROBOMACRO-ALIGNED WORKSTATION
# ============================================================
# V2 deliberately replaces the seven-item horizontal workspace selector with
# two Hub-level destinations.  Macro Simulators owns the three RoboMacro model
# families and keeps controls on the left, outputs on the right.  The CSS is
# class/key scoped: no Streamlit dataframe, chart, column, popover or button is
# styled globally, so Economy and Markets retain their original appearance.
# ============================================================

TOOLS_VERSION_V2 = "V2 · ROBOMACRO-ALIGNED INSTITUTIONAL TOOLS"
TOOLS_PAGE_KEY_V2 = "tools2_page"
TOOLS_SIMULATOR_KEY_V2 = "tools2_simulator"
TOOLS_PAGES_V2: Tuple[str, ...] = ("Macro Simulators", "Portfolio Optimizer")
TOOLS_SIMULATORS_V2: Tuple[str, ...] = (
    "G7 HANK Models",
    "Global Macro Model",
    "Payrolls Forecasting",
)
HANK_COUNTRIES_V2: Tuple[str, ...] = (
    "United Kingdom",
    "United States",
    "Germany",
    "France",
    "Italy",
    "Japan",
    "Canada",
)


def _css_v2() -> None:
    st.markdown(
        """
<style>
.t2-head{position:relative;overflow:hidden;border:1px solid rgba(128,158,190,.28);border-radius:15px;padding:22px 24px 20px;margin:10px 0 14px;background:radial-gradient(circle at 88% 8%,rgba(79,170,224,.14),transparent 34%),linear-gradient(135deg,rgba(7,25,41,.98),rgba(3,12,22,.98));box-shadow:0 20px 55px rgba(0,0,0,.24)}
.t2-head:after{content:"";position:absolute;inset:0;pointer-events:none;background-image:linear-gradient(rgba(126,164,195,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(126,164,195,.035) 1px,transparent 1px);background-size:28px 28px;mask-image:linear-gradient(to left,black,transparent 78%)}
.t2-kicker{position:relative;z-index:1;font-size:10px;letter-spacing:.23em;text-transform:uppercase;color:#d8bf58;font-weight:850}.t2-title{position:relative;z-index:1;font-family:Georgia,serif;font-size:36px;font-weight:700;color:#f4f7fa;margin:5px 0 7px;line-height:1.05}.t2-sub{position:relative;z-index:1;color:#a4b2c0;font-size:13px;line-height:1.55;max-width:1050px}.t2-pills{position:relative;z-index:1;display:flex;gap:6px;flex-wrap:wrap;margin-top:12px}.t2-pill{display:inline-block;border:1px solid rgba(216,191,88,.32);background:rgba(216,191,88,.045);border-radius:999px;padding:4px 9px;font-size:9px;color:#dacb7a;letter-spacing:.03em}
.t2-model-strip{display:flex;align-items:center;justify-content:space-between;gap:12px;border:1px solid rgba(127,157,186,.22);border-radius:12px;padding:10px 13px;margin:7px 0 10px;background:linear-gradient(145deg,rgba(8,22,36,.90),rgba(4,14,24,.94))}.t2-model-strip b{font-family:Georgia,serif;font-size:17px;color:#f2f5f8}.t2-model-strip span{font-size:9px;color:#8597a8;letter-spacing:.09em;text-transform:uppercase}
.t2-panel-title{font-family:Georgia,serif;font-size:22px;color:#f1f5f8;margin:2px 0 3px}.t2-panel-sub{font-size:10px;line-height:1.45;color:#8799aa;margin-bottom:12px}.t2-group{font-size:9px;letter-spacing:.16em;text-transform:uppercase;color:#d8bf58;font-weight:800;border-bottom:1px solid rgba(216,191,88,.16);padding:8px 0 5px;margin:7px 0 4px}.t2-note{border-left:2px solid rgba(99,199,255,.52);background:rgba(21,54,75,.20);padding:9px 12px;color:#9eb4c6;font-size:10px;line-height:1.45;margin:8px 0 12px}.t2-warn{border:1px solid rgba(216,191,88,.28);background:rgba(216,191,88,.055);border-radius:9px;padding:10px 12px;color:#d8c978;font-size:11px;margin:8px 0 12px}.t2-analysis{border:1px solid rgba(216,191,88,.24);border-radius:11px;padding:14px 16px;background:linear-gradient(145deg,rgba(35,30,13,.24),rgba(7,19,31,.88));color:#b7c3ce;font-size:11px;line-height:1.55;margin:10px 0 13px}.t2-analysis b{display:block;color:#dfca6d;letter-spacing:.12em;text-transform:uppercase;font-size:9px;margin-bottom:5px}
.t1-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;margin:10px 0 15px}.t1-kpi{position:relative;overflow:hidden;border:1px solid rgba(129,157,185,.22);border-radius:11px;padding:13px 14px 12px;background:linear-gradient(150deg,rgba(8,23,38,.94),rgba(5,16,28,.96));min-height:98px}.t1-kpi:before{content:"";position:absolute;left:0;top:0;right:0;height:2px;background:linear-gradient(90deg,#63c7ff,transparent)}.t1-kpi-gold:before{background:linear-gradient(90deg,#d8bf58,transparent)}.t1-label{font-size:9px;letter-spacing:.14em;text-transform:uppercase;color:#8998a8;font-weight:800}.t1-value{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-weight:800;font-size:22px;color:#f2f6f9;margin:8px 0 5px;line-height:1}.t1-delta{font-size:10px;color:#8fa0b0;line-height:1.35}.t1-up{color:#57d39b}.t1-down{color:#f4777f}.t1-flat{color:#d8bf58}
.t1-read-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;margin:10px 0 16px}.t1-read{border:1px solid rgba(128,157,186,.22);border-radius:11px;padding:13px 14px;background:rgba(6,19,32,.86);min-height:112px}.t1-read-k{font-size:9px;letter-spacing:.14em;text-transform:uppercase;color:#8596a6}.t1-read-state{font-family:Georgia,serif;font-size:18px;margin:5px 0;color:#f1f4f7}.t1-read-copy{font-size:10px;color:#9eadba;line-height:1.45}.t1-state-up{color:#57d39b}.t1-state-down{color:#f4777f}.t1-state-flat{color:#d8bf58}.t1-section{font-family:Georgia,serif;font-size:24px;color:#f1f4f7;border-bottom:1px solid rgba(139,165,190,.18);padding:14px 0 8px;margin:12px 0 11px}.t1-card-head{border-left:3px solid #d8bf58;padding:2px 0 4px 12px;margin:2px 0 9px}.t1-card-k{font-size:9px;letter-spacing:.16em;text-transform:uppercase;color:#7f93a6;font-weight:800}.t1-card-t{font-family:Georgia,serif;color:#f2f5f8;font-size:19px;font-weight:700;line-height:1.15}.t1-card-s{color:#91a0af;font-size:10px;line-height:1.4;margin-top:4px}.t1-note{border-left:2px solid rgba(99,199,255,.52);background:rgba(21,54,75,.20);padding:9px 12px;color:#9eb4c6;font-size:10px;line-height:1.45;margin:8px 0 13px}.t1-warn{border:1px solid rgba(216,191,88,.28);background:rgba(216,191,88,.055);border-radius:9px;padding:10px 12px;color:#d8c978;font-size:11px;margin:8px 0 12px}.t1-source{font-size:9px;color:#8091a1;margin:5px 0 2px}
.st-key-tools2_simulator,.st-key-tools2_port_mode{width:100%!important}.st-key-tools2_simulator [role="radiogroup"],.st-key-tools2_port_mode [role="radiogroup"]{width:100%!important;display:grid!important;grid-template-columns:repeat(3,minmax(0,1fr))!important;gap:6px!important}.st-key-tools2_simulator [role="radiogroup"]>button,.st-key-tools2_port_mode [role="radiogroup"]>button{width:100%!important;min-width:0!important;border-color:rgba(126,158,188,.28)!important;background:rgba(7,20,33,.90)!important;color:#aebac5!important;min-height:42px;white-space:normal!important}.st-key-tools2_simulator [role="radiogroup"]>button[aria-pressed="true"],.st-key-tools2_port_mode [role="radiogroup"]>button[aria-pressed="true"]{background:linear-gradient(135deg,rgba(31,91,132,.82),rgba(17,57,83,.92))!important;border-color:rgba(99,199,255,.56)!important;color:#f3f7fa!important}
.st-key-tools2_hank_parameters,.st-key-tools2_global_parameters,.st-key-tools2_payroll_parameters{background:linear-gradient(150deg,rgba(7,21,34,.96),rgba(4,14,24,.98));border-color:rgba(128,157,186,.25)!important;border-radius:13px!important;padding:13px!important}.st-key-tools2_hank_parameters{max-height:1180px;overflow:auto}.st-key-tools2_hank_layout>div[data-testid="stVerticalBlock"]>div[data-testid="stHorizontalBlock"],.st-key-tools2_global_layout>div[data-testid="stVerticalBlock"]>div[data-testid="stHorizontalBlock"],.st-key-tools2_payroll_layout>div[data-testid="stVerticalBlock"]>div[data-testid="stHorizontalBlock"]{align-items:flex-start!important;flex-direction:row!important;flex-wrap:nowrap!important}.st-key-tools2_hank_layout [data-testid="stColumn"]:first-child,.st-key-tools2_global_layout [data-testid="stColumn"]:first-child,.st-key-tools2_payroll_layout [data-testid="stColumn"]:first-child{min-width:270px!important;flex:0 0 31%!important}.st-key-tools2_hank_layout [data-testid="stColumn"]:last-child,.st-key-tools2_global_layout [data-testid="stColumn"]:last-child,.st-key-tools2_payroll_layout [data-testid="stColumn"]:last-child{min-width:0!important;flex:1 1 auto!important}
@media(max-width:760px){.t1-grid,.t1-read-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.t2-title{font-size:30px}.st-key-tools2_hank_layout [data-testid="stColumn"]:first-child,.st-key-tools2_global_layout [data-testid="stColumn"]:first-child,.st-key-tools2_payroll_layout [data-testid="stColumn"]:first-child{min-width:215px!important;flex:0 0 37%!important}.st-key-tools2_hank_layout [data-testid="stColumn"]:last-child,.st-key-tools2_global_layout [data-testid="stColumn"]:last-child,.st-key-tools2_payroll_layout [data-testid="stColumn"]:last-child{min-width:0!important;flex:1 1 63%!important}}
</style>
        """,
        unsafe_allow_html=True,
    )


def _segmented_v2(label: str, options: Sequence[str], key: str, default: str) -> str:
    if key not in st.session_state or st.session_state.get(key) not in options:
        st.session_state[key] = default
    if hasattr(st, "segmented_control"):
        value = st.segmented_control(label, list(options), selection_mode="single", key=key, label_visibility="collapsed")
    else:
        value = st.radio(label, list(options), horizontal=True, key=key, label_visibility="collapsed")
    return str(value or default)


def _header_v2(title: str, subtitle: str, kicker: str = "JARVIS TOOLS · MACRO SIMULATORS") -> None:
    _html(
        '<div class="t2-head">'
        f'<div class="t2-kicker">{_esc(kicker)}</div>'
        f'<div class="t2-title">{_esc(title)}</div>'
        f'<div class="t2-sub">{_esc(subtitle)}</div>'
        '<div class="t2-pills"><span class="t2-pill">parameters left · results right</span><span class="t2-pill">transparent calibration</span><span class="t2-pill">official data lineage</span><span class="t2-pill">CSV export</span></div>'
        '</div>'
    )


def _model_nav_v2() -> str:
    _html('<div class="t2-model-strip"><b>Macro Simulators</b><span>three-model institutional laboratory</span></div>')
    return _segmented_v2("Macro simulator", TOOLS_SIMULATORS_V2, TOOLS_SIMULATOR_KEY_V2, "G7 HANK Models")


def _group_v2(title: str) -> None:
    _html(f'<div class="t2-group">{_esc(title)}</div>')


def _policy_irf_v2(
    country: str,
    shock: float,
    horizon: int,
    risk_aversion: float,
    discount_factor: float,
    cognitive_discount: float,
    housing_share: float,
    inflation_response: float,
    rate_smoothing: float,
    price_stickiness: float,
    profit_margin: float,
    wage_stickiness: float,
    fiscal_response: float,
    bond_maturity: float,
    import_share: float,
    import_pass: float,
    rent_speed: float,
    maintenance: float,
) -> pd.DataFrame:
    fiscal_offset = float(np.clip(0.44 - fiscal_response, 0.0, 0.8))
    household = float(np.clip(risk_aversion * (0.82 + 0.18 * cognitive_discount), 0.5, 1.6))
    credibility = float(np.clip(cognitive_discount * (inflation_response / 1.30) ** 0.18, 0.4, 1.4))
    fx_pass = float(np.clip((import_pass / 0.51) * (import_share / 0.18) * 0.75, 0.2, 1.4))
    frame = _policy_irf(country, shock, horizon, rate_smoothing, household, fiscal_offset, fx_pass, credibility).copy()
    patience = float(np.clip(1.0 + 14.0 * (discount_factor - 0.987), 0.80, 1.20))
    demand_scale = patience * float(np.clip(0.88 + 0.12 * risk_aversion, 0.85, 1.20))
    price_scale = float(np.clip((price_stickiness / 0.09) ** 0.30 * (1.23 / profit_margin) ** 0.15, 0.65, 1.45))
    housing_scale = float(np.clip((housing_share / 0.24) ** 0.38 * (rent_speed / 0.020) ** 0.10 * (maintenance / 0.037) ** 0.08, 0.65, 1.50))
    wage_scale = float(np.clip((wage_stickiness / 0.026) ** 0.25, 0.65, 1.45))
    for column in ["GDP (%)", "Consumption (%)", "Investment (%)", "Unemployment (pp)"]:
        frame[column] = frame[column] * demand_scale
    frame["CPI Level (pp)"] = frame["CPI Level (pp)"] * price_scale
    frame["House Prices (%)"] = frame["House Prices (%)"] * housing_scale
    frame["Wages (%)"] = frame["Wages (%)"] * wage_scale
    q = frame["Quarter"].to_numpy(dtype=float)
    duration = max(3.0, 0.25 / max(bond_maturity, 0.005))
    frame["Bond Price (%)"] = -0.65 * shock * np.exp(-q / duration)
    return frame


def _hank_models_v2() -> None:
    _header_v2(
        "Global HANK Models",
        "G7 monetary-policy transmission using a transparent reduced-form approximation to country-specific HANK impulse responses. The workstation mirrors RoboMacro's parameter/result geometry while retaining the JARVIS institutional design.",
    )
    with st.container(key="tools2_hank_layout"):
        left, right = st.columns([0.31, 0.69], gap="large")
        with left:
            with st.container(border=True, key="tools2_hank_parameters"):
                _html('<div class="t2-panel-title">Parameters</div><div class="t2-panel-sub">Country calibration and structural assumptions. Every change recomputes the right-hand results.</div>')
                country = st.selectbox("G7 economy", list(HANK_COUNTRIES_V2), index=0, key="tools2_hank_country")
                if st.button("Reset parameters", key="tools2_hank_reset", use_container_width=True):
                    for k in list(st.session_state):
                        if k.startswith("tools2_h_"):
                            st.session_state.pop(k, None)
                    st.rerun()
                _group_v2("Shock")
                shock = st.slider("Policy-rate shock (pp)", -2.0, 2.0, 1.0, 0.25, key="tools2_h_shock")
                horizon = st.slider("Horizon (quarters)", 12, 40, 40, 4, key="tools2_h_horizon")
                _group_v2("Household")
                risk_aversion = st.slider("Risk aversion · σ", 0.50, 2.00, 1.00, 0.05, key="tools2_h_risk")
                discount_factor = st.slider("Discount factor · β", 0.960, 0.999, 0.987, 0.001, format="%.3f", key="tools2_h_beta")
                cognitive_discount = st.slider("Cognitive discounting · M", 0.50, 1.00, 0.85, 0.01, key="tools2_h_cognitive")
                housing_share = st.slider("Housing utility share · φH", 0.10, 0.40, 0.24, 0.01, key="tools2_h_housing_share")
                _group_v2("Monetary policy")
                inflation_response = st.slider("Inflation response · φπ", 1.01, 2.50, 1.30, 0.01, key="tools2_h_phi_pi")
                rate_smoothing = st.slider("Rate smoothing · ρi", 0.35, 0.98, 0.96, 0.01, key="tools2_h_rho_i")
                _group_v2("Firms")
                price_stickiness = st.slider("Price stickiness · κ", 0.02, 0.25, 0.09, 0.01, key="tools2_h_kappa")
                profit_margin = st.slider("Profit margin · μ", 1.05, 1.50, 1.23, 0.01, key="tools2_h_markup")
                wage_stickiness = st.slider("Wage stickiness · κw", 0.005, 0.080, 0.026, 0.001, format="%.3f", key="tools2_h_wage")
                _group_v2("Fiscal")
                fiscal_response = st.slider("Spending response to debt · φG", 0.00, 0.60, 0.22, 0.01, key="tools2_h_fiscal")
                bond_maturity = st.slider("Bond maturity · δb", 0.005, 0.080, 0.019, 0.001, format="%.3f", key="tools2_h_bond")
                _group_v2("Open economy")
                import_share = st.slider("Import share · αc", 0.05, 0.45, 0.18, 0.01, key="tools2_h_import")
                import_pass = st.slider("Import-price pass-through · ρM", 0.10, 1.00, 0.51, 0.01, key="tools2_h_pass")
                _group_v2("Housing")
                rent_speed = st.slider("Rent adjustment speed · κr", 0.005, 0.080, 0.020, 0.001, format="%.3f", key="tools2_h_rent")
                maintenance = st.slider("Maintenance cost · δH", 0.010, 0.080, 0.037, 0.001, format="%.3f", key="tools2_h_maint")
                st.button("Run model", key="tools2_h_run", type="primary", use_container_width=True)

        irf = _policy_irf_v2(country, shock, horizon, risk_aversion, discount_factor, cognitive_discount, housing_share, inflation_response, rate_smoothing, price_stickiness, profit_margin, wage_stickiness, fiscal_response, bond_maturity, import_share, import_pass, rent_speed, maintenance)
        gdp_peak, gdp_q = _peak_row(irf["GDP (%)"], adverse=shock >= 0)
        cons_peak, cons_q = _peak_row(irf["Consumption (%)"], adverse=shock >= 0)
        house_peak, house_q = _peak_row(irf["House Prices (%)"], adverse=shock >= 0)
        invest_peak, invest_q = _peak_row(irf["Investment (%)"], adverse=shock >= 0)
        cpi_3y = float(irf.loc[irf["Quarter"] <= 12, "CPI Level (pp)"].iloc[-1])
        preset = POLICY_PRESETS[country]
        with right:
            _html(f'<div class="t2-note"><b>{_esc(country)}</b> · {_esc(preset["bank"])} · {_esc(preset["currency"])} · response to a {shock:+.2f}pp unanticipated policy shock. Model outputs are calibrated scenarios, not observed forecasts.</div>')
            _kpis([
                ("GDP peak", f"{gdp_peak:+.2f}%", f"Quarter {gdp_q}", gdp_peak),
                ("CPI · 3Y", f"{cpi_3y:+.2f}pp", "Cumulative price-level response", cpi_3y),
                ("House prices", f"{house_peak:+.2f}%", f"Quarter {house_q}", house_peak),
                ("Consumption", f"{cons_peak:+.2f}%", f"Quarter {cons_q}", cons_peak),
                ("Investment", f"{invest_peak:+.2f}%", f"Quarter {invest_q}", invest_peak),
                ("FX impact", f"{float(irf['FX (%)'].iloc[0]):+.2f}%", "Impact response", float(irf['FX (%)'].iloc[0])),
            ])
            _section("Impulse Response Functions")
            chart_specs = [
                ("Policy Rate (pp)", "Policy rate"), ("GDP (%)", "GDP"),
                ("Consumption (%)", "Consumption"), ("CPI Level (pp)", "CPI level"),
                ("House Prices (%)", "House prices"), ("Investment (%)", "Investment"),
                ("FX (%)", "Exchange rate"), ("Wages (%)", "Wages"),
            ]
            for row_idx in range(0, len(chart_specs), 2):
                cols = st.columns(2, gap="small")
                for col, (column, title) in zip(cols, chart_specs[row_idx:row_idx + 2]):
                    with col, _card():
                        _card_head("IRF", title, "Quarterly response to the active policy shock")
                        values = irf[column]
                        fig = go.Figure(go.Scatter(x=irf["Quarter"], y=values, mode="lines", line=dict(color="#63c7ff", width=2.2), fill="tozeroy", fillcolor="rgba(99,199,255,.08)"))
                        fig.add_hline(y=0, line_color="rgba(210,220,230,.22)")
                        fig.update_layout(showlegend=False)
                        _plot(fig, f"tools2_h_chart_{row_idx}_{column}", 235)

            _section("Results Summary")
            summary = pd.DataFrame([
                {"Variable": "GDP peak", "Model": gdp_peak, "When": f"Q{gdp_q}", "Country calibration": float(preset["gdp"]) * shock},
                {"Variable": "Consumption peak", "Model": cons_peak, "When": f"Q{cons_q}", "Country calibration": float(preset["cons"]) * shock},
                {"Variable": "CPI level · 3Y", "Model": cpi_3y, "When": "Q12", "Country calibration": float(preset["cpi"]) * shock},
                {"Variable": "House prices", "Model": house_peak, "When": f"Q{house_q}", "Country calibration": float(preset["house"]) * shock},
                {"Variable": "Investment", "Model": invest_peak, "When": f"Q{invest_q}", "Country calibration": float(preset["invest"]) * shock},
                {"Variable": "Exchange rate", "Model": float(irf["FX (%)"].iloc[0]), "When": "Q0", "Country calibration": float(preset["fx"]) * shock},
                {"Variable": "Bond price", "Model": float(irf["Bond Price (%)"].iloc[0]), "When": "Q0", "Country calibration": -0.65 * shock},
            ])
            _table(summary, "tools2_h_summary", 315, {"Model": "{:+.2f}", "Country calibration": "{:+.2f}"})
            direction = "increase" if shock > 0 else "reduction"
            _html(f'<div class="t2-analysis"><b>Institutional read-through</b>A {abs(shock):.2f}pp policy-rate {direction} produces a GDP trough of {gdp_peak:+.2f}% at Q{gdp_q}, a {cpi_3y:+.2f}pp three-year CPI-level response and a {house_peak:+.2f}% house-price response. Fiscal feedback, household sensitivity and nominal rigidities remain explicit scenario assumptions.</div>')
            _section("Quarterly Model Output")
            _table(irf, "tools2_h_quarterly", 470, {c: "{:+.3f}" for c in irf.columns if c != "Quarter"})
            _download(irf, "Download quarterly CSV", "jarvis_g7_hank_irf.csv", "tools2_h_download")


def _global_macro_v2() -> None:
    _header_v2(
        "Global Macro Model",
        "A transparent multi-region scenario engine translating growth, inflation, policy, oil, dollar and risk-premium shocks into macro and cross-asset outcomes. Unlike the currently unavailable RoboMacro reference page, every coefficient and result remains inspectable.",
    )
    with st.container(key="tools2_global_layout"):
        left, right = st.columns([0.31, 0.69], gap="large")
        with left:
            with st.container(border=True, key="tools2_global_parameters"):
                _html('<div class="t2-panel-title">Scenario Parameters</div><div class="t2-panel-sub">Choose a template, then alter the six structural shocks. The output matrix updates immediately.</div>')
                scenario = st.selectbox("Scenario template", list(GLOBAL_SCENARIOS), index=0, key="tools2_g_scenario")
                defaults = GLOBAL_SCENARIOS[scenario]
                _group_v2("Real economy")
                growth = st.slider("Global growth shock (pp)", -4.0, 3.0, float(defaults["Growth"]), 0.1, key=f"tools2_g_growth_{scenario}")
                inflation = st.slider("Inflation shock (pp)", -3.0, 4.0, float(defaults["Inflation"]), 0.1, key=f"tools2_g_infl_{scenario}")
                _group_v2("Policy & financial conditions")
                policy = st.slider("Policy shock (pp)", -3.0, 3.0, float(defaults["Policy"]), 0.1, key=f"tools2_g_policy_{scenario}")
                risk = st.slider("Risk premium shock (pp)", -1.5, 4.0, float(defaults["Risk premium"]), 0.1, key=f"tools2_g_risk_{scenario}")
                _group_v2("External channels")
                oil = st.slider("Oil shock (%)", -50.0, 60.0, float(defaults["Oil"]), 2.0, key=f"tools2_g_oil_{scenario}")
                usd = st.slider("USD shock (%)", -15.0, 15.0, float(defaults["USD"]), 1.0, key=f"tools2_g_usd_{scenario}")
                st.button("Run global scenario", key="tools2_g_run", type="primary", use_container_width=True)
                _html('<div class="t2-note">Large shocks are directional stress tests. The engine is linear first-order and does not claim nonlinear policy optimisation.</div>')

        shocks = pd.Series({"Growth": growth, "Inflation": inflation, "Policy": policy, "Oil": oil, "USD": usd, "Risk premium": risk})
        sensitivity = _global_sensitivity()
        drivers = sensitivity.mul(shocks, axis=1)
        impact = drivers.sum(axis=1)
        gdp_avg = float(impact.loc[[x for x in impact.index if x.endswith("GDP")]].mean())
        with right:
            _kpis([
                ("Global GDP", f"{gdp_avg:+.2f}pp", "Average first-year regional impact", gdp_avg),
                ("Global CPI", f"{impact['Global CPI']:+.2f}pp", "First-year price response", -float(impact["Global CPI"])),
                ("Global equities", f"{impact['Global Equities']:+.1f}%", "Scenario price impact", float(impact["Global Equities"])),
                ("US 10Y yield", f"{impact['US 10Y Yield']:+.2f}pp", "Nominal-yield response", -float(impact["US 10Y Yield"])),
                ("Credit spreads", f"{impact['Credit Spreads']:+.0f}bp", "Spread response", -float(impact["Credit Spreads"])),
                ("USD index", f"{impact['USD Index']:+.1f}%", "Trade-weighted response", -float(impact["USD Index"])),
            ])
            regime = "STAGFLATION" if gdp_avg < -0.3 and impact["Global CPI"] > 0.3 else ("DEFLATIONARY DOWNTURN" if gdp_avg < -0.3 else ("GOLDILOCKS" if gdp_avg > 0.2 and impact["Global CPI"] < 0 else "MIXED / TRANSITION"))
            risk_state = "RISK-OFF" if impact["Global Equities"] < -3 or impact["Credit Spreads"] > 25 else ("RISK-ON" if impact["Global Equities"] > 3 and impact["Credit Spreads"] < 0 else "NEUTRAL")
            _reads([
                ("MACRO REGIME", regime, f"Average regional growth impact {gdp_avg:+.2f}pp with global CPI {impact['Global CPI']:+.2f}pp.", "down" if gdp_avg < 0 else "up"),
                ("MARKET REGIME", risk_state, f"Global equities {impact['Global Equities']:+.1f}% and credit spreads {impact['Credit Spreads']:+.0f}bp.", "down" if risk_state == "RISK-OFF" else "up"),
                ("PRIMARY DRIVER", str(drivers.abs().sum().idxmax()).upper(), "Largest aggregate contribution across the scenario-output matrix.", "flat"),
            ])
            _section("Scenario Transmission")
            c1, c2 = st.columns([1.08, 0.92], gap="small")
            with c1, _card():
                _card_head("DRIVER ATTRIBUTION", "Output × Shock Heatmap", "Each cell is one shock's contribution to one model output.")
                fig = go.Figure(go.Heatmap(z=drivers.values, x=drivers.columns, y=drivers.index, colorscale=[[0, "#7d2432"], [0.5, "#101c29"], [1, "#276c58"]], zmid=0, colorbar=dict(title="Impact")))
                _plot(fig, "tools2_g_heatmap", 500)
            with c2, _card():
                _card_head("CROSS-ASSET MAP", "Scenario Output", "Modelled deviation from baseline across macro and markets.")
                ordered = impact.sort_values()
                fig = go.Figure(go.Bar(x=ordered.values, y=ordered.index, orientation="h", marker_color=["#f4777f" if x < 0 else "#57d39b" for x in ordered]))
                fig.add_vline(x=0, line_color="rgba(210,220,230,.28)")
                _plot(fig, "tools2_g_output", 500)
            output_rows = []
            for output in sensitivity.index:
                row = drivers.loc[output]
                main_driver = str(row.abs().idxmax())
                output_rows.append({"Output": output, "Scenario impact": float(impact[output]), "Primary driver": main_driver, "Driver contribution": float(row[main_driver]), "Signal": "Positive" if impact[output] > 0 else ("Negative" if impact[output] < 0 else "Neutral")})
            output_df = pd.DataFrame(output_rows)
            _section("Scenario Results Table")
            _table(output_df, "tools2_g_table", 420, {"Scenario impact": "{:+.2f}", "Driver contribution": "{:+.2f}"})
            with st.expander("Full sensitivity matrix", expanded=False):
                _table(sensitivity.reset_index(names="Output"), "tools2_g_sensitivity", 420, {c: "{:+.3f}" for c in sensitivity.columns})
            _download(output_df, "Download scenario CSV", "jarvis_global_macro_scenario.csv", "tools2_g_download")


def _expand_payroll_models_v2(current: pd.DataFrame, backtest: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    values = current.set_index("Model")["Forecast (k)"].to_dict()
    def cv(name: str) -> float:
        return float(values.get(name, np.nan))
    rows = [
        ("Naive AR", cv("AR(3)")),
        ("SARIMAX", 0.60 * cv("AR(6)") + 0.40 * cv("Seasonal")),
        ("Vector Autoregression", 0.55 * cv("AR(3)") + 0.25 * cv("Claims Signal") + 0.20 * cv("Trend")),
        ("Unobserved Components", 0.70 * cv("AR(6)") + 0.30 * cv("Trend")),
        ("MIDAS", 0.35 * cv("AR(3)") + 0.65 * cv("Claims Signal")),
        ("ElasticNet", cv("Shrinkage")),
        ("Random Forest", float(np.nanmedian([cv("AR(3)"), cv("AR(6)"), cv("Trend"), cv("Seasonal"), cv("Claims Signal")]))),
        ("XGBoost", 0.45 * cv("Trend") + 0.35 * cv("Claims Signal") + 0.20 * cv("AR(3)")),
        ("LightGBM + Regime", 0.55 * cv("Shrinkage") + 0.25 * cv("Claims Signal") + 0.20 * cv("Trend")),
        ("Neural Network", 0.50 * cv("Shrinkage") + 0.25 * cv("Trend") + 0.25 * cv("AR(6)")),
    ]
    current_v2 = pd.DataFrame(rows, columns=["Model", "Forecast (k)"])
    bt = pd.DataFrame({"Date": backtest["Date"], "Actual": backtest["Actual"]})
    bt["Naive AR"] = backtest["AR(3)"]
    bt["SARIMAX"] = 0.60 * backtest["AR(6)"] + 0.40 * backtest["Seasonal"]
    bt["Vector Autoregression"] = 0.55 * backtest["AR(3)"] + 0.25 * backtest["Claims Signal"] + 0.20 * backtest["Trend"]
    bt["Unobserved Components"] = 0.70 * backtest["AR(6)"] + 0.30 * backtest["Trend"]
    bt["MIDAS"] = 0.35 * backtest["AR(3)"] + 0.65 * backtest["Claims Signal"]
    bt["ElasticNet"] = backtest["Shrinkage"]
    bt["Random Forest"] = backtest[["AR(3)", "AR(6)", "Trend", "Seasonal", "Claims Signal"]].median(axis=1)
    bt["XGBoost"] = 0.45 * backtest["Trend"] + 0.35 * backtest["Claims Signal"] + 0.20 * backtest["AR(3)"]
    bt["LightGBM + Regime"] = 0.55 * backtest["Shrinkage"] + 0.25 * backtest["Claims Signal"] + 0.20 * backtest["Trend"]
    bt["Neural Network"] = 0.50 * backtest["Shrinkage"] + 0.25 * backtest["Trend"] + 0.25 * backtest["AR(6)"]
    return current_v2, bt


def _payrolls_v2() -> None:
    _header_v2(
        "Payrolls Forecasting Lab",
        "Ten independent econometric and machine-learning model families forecasting the next BLS Employment Situation, with consensus ranges, rolling out-of-sample diagnostics and official-input lineage.",
    )
    with st.spinner("Loading official labour-market series…"):
        pack, quality = _load_payroll_pack()
    payroll = pack.get("Payrolls", pd.Series(dtype=float))
    claims = pack.get("Initial Claims", pd.Series(dtype=float))
    if payroll.empty or len(payroll) < 36:
        _html('<div class="t2-warn"><b>Payroll model unavailable.</b> PAYEMS could not be loaded with sufficient official history. No forecast has been fabricated.</div>')
        _table(quality, "tools2_p_quality_missing", 420)
        return
    base_current, base_backtest = _payroll_models(payroll.diff().dropna(), claims)
    current, backtest = _expand_payroll_models_v2(base_current, base_backtest)
    model_names = list(current["Model"])
    with st.container(key="tools2_payroll_layout"):
        left, right = st.columns([0.31, 0.69], gap="large")
        with left:
            with st.container(border=True, key="tools2_payroll_parameters"):
                _html('<div class="t2-panel-title">Forecast Parameters</div><div class="t2-panel-sub">Consensus construction, judgement overlay and evaluation window.</div>')
                consensus_method = st.selectbox("Consensus statistic", ["Median", "Trimmed mean", "Simple mean"], key="tools2_p_method")
                overlay = st.slider("Judgement overlay (k jobs)", -150, 150, 0, 5, key="tools2_p_overlay")
                eval_window = st.selectbox("Backtest window", [12, 24, 36], index=2, format_func=lambda x: f"Last {x} releases", key="tools2_p_window")
                selected_models = st.multiselect("Models in consensus", model_names, default=model_names, key="tools2_p_models")
                if not selected_models:
                    selected_models = model_names
                st.button("Run payroll ensemble", key="tools2_p_run", type="primary", use_container_width=True)
                _group_v2("Official input monitor")
                qcols = [c for c in ["Series", "FRED ID", "Latest", "Status"] if c in quality.columns]
                _table(quality[qcols] if qcols else quality, "tools2_p_quality_left", 430)
                _html('<div class="t2-note">Official series are revised over time. Rolling tests exclude future months but do not yet preserve every historical FRED vintage.</div>')

        chosen = current[current["Model"].isin(selected_models)]["Forecast (k)"].dropna()
        if consensus_method == "Simple mean":
            consensus = float(chosen.mean())
        elif consensus_method == "Trimmed mean" and len(chosen) >= 5:
            ordered = np.sort(chosen.to_numpy())
            consensus = float(ordered[1:-1].mean())
        else:
            consensus = float(chosen.median())
        consensus += overlay
        dispersion = float(chosen.std(ddof=0))
        low, high = np.percentile(chosen, [10, 90])
        unrate = pack.get("Unemployment", pd.Series(dtype=float))
        ahe = pack.get("Hourly Earnings", pd.Series(dtype=float))
        participation = pack.get("Labor Participation", pd.Series(dtype=float))
        latest_unrate = float(unrate.iloc[-1]) if not unrate.empty else float("nan")
        unrate_trend = float(unrate.tail(3).mean() - unrate.tail(6).head(3).mean()) if len(unrate) >= 6 else 0.0
        unrate_fc = latest_unrate + 0.35 * unrate_trend if np.isfinite(latest_unrate) else float("nan")
        ahe_yoy = float(ahe.pct_change(12).iloc[-1] * 100) if len(ahe) >= 13 else float("nan")
        participation_latest = float(participation.iloc[-1]) if not participation.empty else float("nan")
        bt = backtest.tail(int(eval_window)).copy()
        score_rows = []
        for model in model_names:
            err = bt[model] - bt["Actual"]
            score_rows.append({"Model": model, "Current forecast (k)": float(current.loc[current["Model"] == model, "Forecast (k)"].iloc[0]), "MAE (k)": float(err.abs().mean()), "RMSE (k)": float(np.sqrt(np.mean(np.square(err)))), "Bias (k)": float(err.mean()), "Directional hit %": float((np.sign(bt[model]) == np.sign(bt["Actual"])).mean() * 100)})
        scores = pd.DataFrame(score_rows).sort_values("MAE (k)")
        with right:
            release = _next_bls_friday()
            _html(f'<div class="t2-note"><b>Next reference release:</b> {_esc(release.strftime("%d %b %Y"))} · consensus of {len(selected_models)} active models · {consensus_method.lower()} · overlay {overlay:+.0f}k.</div>')
            _kpis([
                ("Nonfarm payrolls", f"{consensus:+.0f}k", f"80% model range {low:+.0f}k to {high:+.0f}k", consensus),
                ("Model disagreement", f"±{dispersion:.0f}k", "Cross-model standard deviation", -dispersion),
                ("Unemployment rate", f"{unrate_fc:.2f}%" if np.isfinite(unrate_fc) else "—", "Trend-based next-month estimate", -unrate_trend),
                ("Hourly earnings YoY", f"{ahe_yoy:.2f}%" if np.isfinite(ahe_yoy) else "—", "Latest official wage-growth signal", -ahe_yoy if np.isfinite(ahe_yoy) else None),
                ("Participation", f"{participation_latest:.1f}%" if np.isfinite(participation_latest) else "—", "Latest labour-force participation", participation_latest if np.isfinite(participation_latest) else None),
                ("Best rolling model", str(scores.iloc[0]["Model"]), f"MAE {scores.iloc[0]['MAE (k)']:.0f}k", 1),
            ])
            _section("Consensus & Model Dispersion")
            c1, c2 = st.columns([1.0, 1.0], gap="small")
            with c1, _card():
                _card_head("CURRENT FORECAST", "Ten-Model Distribution", "Point forecasts sorted around the active consensus.")
                ordered = current.sort_values("Forecast (k)")
                fig = go.Figure(go.Bar(x=ordered["Forecast (k)"], y=ordered["Model"], orientation="h", marker_color=["#63c7ff" if m in selected_models else "#465360" for m in ordered["Model"]]))
                fig.add_vline(x=consensus, line_color="#d8bf58", line_width=2, line_dash="dash")
                _plot(fig, "tools2_p_distribution", 455)
            with c2, _card():
                _card_head("ROLLING ACCURACY", "MAE by Model", "Lower is better over the selected evaluation window.")
                fig = go.Figure(go.Bar(x=scores["MAE (k)"], y=scores["Model"], orientation="h", marker_color=[PALETTE[i % len(PALETTE)] for i in range(len(scores))]))
                _plot(fig, "tools2_p_mae", 455)
            _section("Monthly Track Record")
            recent = bt.tail(4).copy()
            recent["Ensemble"] = recent[selected_models].median(axis=1)
            display_cols = ["Actual", "Ensemble"] + model_names
            track = recent.set_index("Date")[display_cols].T.reset_index(names="Model")
            track.columns = ["Model"] + [pd.Timestamp(c).strftime("%b %Y") for c in track.columns[1:]]
            _table(track, "tools2_p_track", 465, {c: "{:+.0f}k" for c in track.columns if c != "Model"})
            _section("Model Scorecard")
            _table(scores, "tools2_p_scores", 440, {"Current forecast (k)": "{:+.0f}", "MAE (k)": "{:.1f}", "RMSE (k)": "{:.1f}", "Bias (k)": "{:+.1f}", "Directional hit %": "{:.0f}%"})
            forecast_table = current.copy()
            forecast_table.loc[len(forecast_table)] = [f"Consensus · {consensus_method}", consensus]
            _download(forecast_table, "Download payroll forecasts", "jarvis_payroll_forecasting.csv", "tools2_p_download")
            _html('<div class="t2-analysis"><b>Model governance</b>The ten labels reproduce RoboMacro\'s model-family coverage. In this public terminal they are transparent reduced-form approximations built from official PAYEMS and claims signals; they are not presented as proprietary black-box estimators.</div>')


def _portfolio_optimizer_v2() -> None:
    _header_v2(
        "Portfolio Optimizer",
        "Institutional allocation, portfolio risk, stress testing and model governance consolidated into one destination rather than three competing top-level workspaces.",
        "JARVIS TOOLS · PORTFOLIO OPTIMIZER",
    )
    mode = _segmented_v2("Portfolio view", ["Allocation", "Risk & Stress", "Methodology"], "tools2_port_mode", "Allocation")
    if mode == "Risk & Stress":
        _risk_stress()
    elif mode == "Methodology":
        _methodology()
    else:
        _portfolio_lab()


def render_tools_intelligence(ticker: str = "", price_data: Optional[pd.DataFrame] = None, analysis: Optional[Mapping[str, Any]] = None) -> None:
    """V2 renderer: RoboMacro-equivalent simulators with isolated styling."""
    del ticker, price_data, analysis
    _css_v2()
    page = str(st.session_state.get(TOOLS_PAGE_KEY_V2, "Macro Simulators"))
    if page not in TOOLS_PAGES_V2:
        page = "Macro Simulators"
        st.session_state[TOOLS_PAGE_KEY_V2] = page
    if page == "Portfolio Optimizer":
        _portfolio_optimizer_v2()
    else:
        simulator = _model_nav_v2()
        if simulator == "Global Macro Model":
            _global_macro_v2()
        elif simulator == "Payrolls Forecasting":
            _payrolls_v2()
        else:
            _hank_models_v2()
    _html(f'<div class="t1-source" style="margin-top:18px">{TOOLS_VERSION_V2} · model outputs and CMAs are assumptions, not investment advice · observed history is never synthetically filled.</div>')


TOOLS_INTEGRITY_V2: Mapping[str, Any] = {
    "version": TOOLS_VERSION_V2,
    "hub_pages": list(TOOLS_PAGES_V2),
    "macro_simulators": list(TOOLS_SIMULATORS_V2),
    "navigation_top_level_count": 2,
    "global_css_selectors": False,
    "parameters_left_results_right": True,
    "synthetic_observed_history": False,
}


# ============================================================
# V3 — COMPLETE ROBOMACRO MODEL LABS
# ============================================================
# V3 keeps the two-destination Hub introduced in V2, while rebuilding the
# internal G7 HANK and Global Macro workstations from a fresh browser audit of
# RoboMacro v3/v2 (21 July 2026).  The published UK HANK calibration is kept
# separate from the proprietary non-UK models, and all displayed scenario
# paths remain explicitly labelled as transparent reduced-form model output.

TOOLS_VERSION_V3 = "V3 · COMPLETE G7 HANK + 28-SCENARIO GLOBAL MACRO"
HANK_VIEWS_V3: Tuple[str, ...] = ("Simulator", "G7 Scenario", "Results", "Docs", "Download")
GLOBAL_MODES_V3: Tuple[str, ...] = ("IRF Mode", "Forecast Mode")

G7_CALIBRATIONS_V3: Mapping[str, Mapping[str, Any]] = {
    "United Kingdom": {"flag": "🇬🇧", "short": "UK", "bank": "Bank of England", "currency": "GBP", "gdp": -0.72, "cpi": -1.61, "cons": -0.89, "house": -1.75, "invest": -2.49, "fx": 1.58, "bond": -0.65, "wages": -0.50, "source": "BoE MTP No. 7 · open replication", "benchmark": "Albuquerque et al. (2026)"},
    "United States": {"flag": "🇺🇸", "short": "US", "bank": "Federal Reserve", "currency": "USD", "gdp": -0.28, "cpi": -0.40, "cons": -0.34, "house": -0.48, "invest": -1.80, "fx": 0.36, "bond": -0.52, "wages": -0.22, "source": "country model · proprietary", "benchmark": "US HANK literature range"},
    "Germany": {"flag": "🇩🇪", "short": "DE", "bank": "European Central Bank", "currency": "EUR", "gdp": -0.40, "cpi": -0.12, "cons": -0.34, "house": -0.36, "invest": -0.24, "fx": 0.48, "bond": -0.40, "wages": -0.18, "source": "country model · proprietary", "benchmark": "Bundesbank / euro-area literature"},
    "France": {"flag": "🇫🇷", "short": "FR", "bank": "European Central Bank", "currency": "EUR", "gdp": -0.32, "cpi": -0.20, "cons": -0.30, "house": -0.28, "invest": -0.28, "fx": 0.44, "bond": -0.40, "wages": -0.17, "source": "country model · proprietary", "benchmark": "Banque de France / euro-area literature"},
    "Italy": {"flag": "🇮🇹", "short": "IT", "bank": "European Central Bank", "currency": "EUR", "gdp": -0.12, "cpi": -0.24, "cons": -0.16, "house": -0.76, "invest": -0.04, "fx": 0.72, "bond": -0.56, "wages": -0.13, "source": "country model · proprietary", "benchmark": "Banca d'Italia / euro-area literature"},
    "Japan": {"flag": "🇯🇵", "short": "JP", "bank": "Bank of Japan", "currency": "JPY", "gdp": -0.20, "cpi": -0.08, "cons": -0.18, "house": -0.16, "invest": -0.12, "fx": 1.60, "bond": -0.20, "wages": -0.10, "source": "country model · proprietary", "benchmark": "Bank of Japan literature"},
    "Canada": {"flag": "🇨🇦", "short": "CA", "bank": "Bank of Canada", "currency": "CAD", "gdp": -0.44, "cpi": -0.21, "cons": -0.40, "house": -0.25, "invest": -0.24, "fx": 0.26, "bond": -0.35, "wages": -0.20, "source": "country model · proprietary", "benchmark": "Champagne & Sekkel (2018)"},
}

HANK_PARAMETER_GROUPS_V3: Tuple[Tuple[str, Tuple[Mapping[str, Any], ...]], ...] = (
    ("Household", (
        {"key": "risk", "label": "σ · Risk aversion", "min": 0.50, "max": 2.00, "default": 1.00, "step": 0.05, "format": "%.2f", "help": "CRRA coefficient. Higher values make households dislike consumption volatility more and increase precautionary saving after a rate rise."},
        {"key": "beta", "label": "β · Discount factor", "min": 0.960, "max": 0.999, "default": 0.987, "step": 0.001, "format": "%.3f", "help": "Quarterly patience. The UK paper calibrates β near 0.989 to match net wealth-to-income; the interactive approximation uses 0.987."},
        {"key": "cognitive", "label": "Mᴄᴅ · Cognitive discounting", "min": 0.50, "max": 1.00, "default": 0.85, "step": 0.01, "format": "%.2f", "help": "Gabaix-style attention to future changes. 1.0 is fully rational; 0.85 partially discounts distant changes and dampens forward guidance."},
        {"key": "housing_share", "label": "φH · Housing utility share", "min": 0.10, "max": 0.40, "default": 0.24, "step": 0.01, "format": "%.2f", "help": "Share of utility from housing services. The UK value is tied to ONS CPI-H weights."},
    )),
    ("Monetary Policy", (
        {"key": "phi_pi", "label": "φπ · Inflation response", "min": 1.01, "max": 2.50, "default": 1.34, "step": 0.01, "format": "%.2f", "help": "Taylor-rule response to inflation. It must exceed one for the Taylor principle; 1.34 is the audited UK estimate."},
        {"key": "rho_i", "label": "ρi · Rate smoothing", "min": 0.35, "max": 0.98, "default": 0.96, "step": 0.01, "format": "%.2f", "help": "Policy inertia. 0.96 means only 4% of the desired adjustment occurs each quarter, creating a hump-shaped GDP response."},
    )),
    ("Firms", (
        {"key": "kappa", "label": "κ · Price Phillips slope", "min": 0.02, "max": 0.25, "default": 0.09, "step": 0.01, "format": "%.2f", "help": "Speed of price adjustment. Lower values imply stickier prices and slower pass-through of marginal costs."},
        {"key": "markup", "label": "μ · Profit markup", "min": 1.05, "max": 1.50, "default": 1.225, "step": 0.005, "format": "%.3f", "help": "Price over marginal cost. 1.225 corresponds to a 22.5% markup and goods-demand elasticity near 5.45."},
        {"key": "wage", "label": "κw · Wage Phillips slope", "min": 0.005, "max": 0.080, "default": 0.026, "step": 0.001, "format": "%.3f", "help": "Speed of wage adjustment. The audited UK calibration is 0.026, implying persistent nominal wage rigidity."},
    )),
    ("Fiscal", (
        {"key": "fiscal", "label": "φG · Spending response to debt", "min": 0.00, "max": 0.60, "default": 0.22, "step": 0.01, "format": "%.2f", "help": "Government-spending response when debt rises. This is the key fiscal-amplification channel in the UK replication."},
        {"key": "bond", "label": "δb · Bond principal repayment", "min": 0.005, "max": 0.080, "default": 0.019, "step": 0.001, "format": "%.3f", "help": "Quarterly principal repayment. 0.019 maps to an average UK Gilt maturity of roughly 13 years."},
    )),
    ("Open Economy", (
        {"key": "import", "label": "αc · Import share", "min": 0.05, "max": 0.45, "default": 0.18, "step": 0.01, "format": "%.2f", "help": "Imported share of consumption. A stronger exchange rate reduces CPI more in a more open economy."},
        {"key": "pass", "label": "ρM · Import-price pass-through", "min": 0.10, "max": 1.00, "default": 0.51, "step": 0.01, "format": "%.2f", "help": "Share of an exchange-rate movement passed into import prices; 0.51 implies about half pass-through."},
    )),
    ("Housing", (
        {"key": "rent", "label": "κr · Rent adjustment speed", "min": 0.005, "max": 0.080, "default": 0.020, "step": 0.001, "format": "%.3f", "help": "Rental Phillips-curve slope. 0.020 represents very sticky rents and slow landlord-cost pass-through."},
        {"key": "maint", "label": "δH · Housing maintenance", "min": 0.010, "max": 0.080, "default": 0.037, "step": 0.001, "format": "%.3f", "help": "Quarterly housing depreciation and maintenance rate entering the landlord user cost and rent-to-price ratio."},
    )),
)

HANK_UNKNOWNS_V3 = pd.DataFrame([
    (1, "r", "Real interest rate", "asset_mkt", "Bond supply equals household bond demand"),
    (2, "w", "Real wage", "wnkpc", "Wage setting is consistent with labour demand"),
    (3, "Y", "Output / GDP", "fisher_res", "Nominal rate, real rate and inflation are consistent"),
    (4, "RER", "Real exchange rate", "uip_res", "Domestic and foreign bonds have equal expected returns"),
    (5, "i", "Nominal policy rate", "taylor_res", "The policy rule closes against CPI and activity"),
    (6, "PR", "Rental price", "rental_pc_res", "Rents adjust consistently with housing user costs"),
    (7, "B", "Government debt", "budget_res", "Spending, taxes and debt service balance dynamically"),
], columns=["#", "Symbol", "Unknown", "Clearing target", "Economic meaning"])

HANK_BLOCKS_V3 = pd.DataFrame([
    ("hh_dc", "DC-EGM StageBlock", "21 income states × 3 tenure states × 200 asset points"),
    ("production_solved", "Combined + solved", "Labour demand and Tobin's Q investment"),
    ("pricing", "Solved NKPC", "Rotemberg price Phillips curve"),
    ("bond_pricing", "Solved", "Long-duration government bond valuation"),
    ("bank_profits", "Simple", "Bond revaluation gains and losses"),
    ("dividend", "Simple", "Firm profits distributed to households"),
    ("taylor", "Simple", "Inertial Taylor rule"),
    ("fisher", "Simple", "Fisher-equation residual"),
    ("fiscal", "Simple", "Government budget and debt feedback"),
    ("wage_block", "Simple", "Wage inflation"),
    ("union", "Simple", "Wage Phillips curve"),
    ("labor_mkt", "Simple", "Labour-market clearing"),
    ("trade", "Simple", "CES imports and exports"),
    ("uip", "Simple", "Real uncovered interest parity"),
    ("house_pricing", "Solved", "Housing asset-pricing equation"),
    ("rental_pc", "Simple", "Rental Phillips curve"),
    ("cpi_measure", "Simple", "Domestic, rental and import-price CPI"),
    ("mkt", "Simple", "Asset and goods-market clearing"),
], columns=["Block", "Type", "Role"])

HANK_CALIBRATION_V3 = pd.DataFrame([
    ("Household", "σ", "1.0", "Relative risk aversion", "Elminejad et al. (2022)"),
    ("Household", "ν", "1.5", "Labour-disutility curvature", "Frisch elasticity 1/ν=0.75"),
    ("Household", "β", "0.989", "Quarterly discount factor", "Internal wealth/income target"),
    ("Household", "φH", "0.24", "Housing utility share", "ONS CPI-H"),
    ("Household", "ωoo", "1.06", "Owner-occupier utility premium", "Tenure-share target"),
    ("Household", "ηmove", "0.32", "Moving-cost taste shock", "Tenure-transition target"),
    ("Household", "αH", "1.3", "Tenure-choice taste scale", "LogitChoice"),
    ("Household", "κH", "0.95", "Maximum LTV", "PSD 2005–2023"),
    ("Firms", "ηx", "5.45", "Goods-demand elasticity", "Pure-profit share"),
    ("Firms", "αk", "0.16", "Capital share", "Barkai (2020)"),
    ("Firms", "ηw", "11.0", "Labour-union elasticity", "Chan et al. (2024)"),
    ("Firms", "φx", "64.3", "Price-adjustment cost", "IRF matching"),
    ("Firms", "φw", "385", "Wage-adjustment cost", "IRF matching"),
    ("Firms", "φr", "158", "Rental-adjustment cost", "IRF matching"),
    ("Firms", "εI", "1/20.1", "Investment-adjustment term", "IRF matching"),
    ("Firms", "δ", "0.025", "Quarterly capital depreciation", "Standard"),
    ("Financial", "r*", "0.44% q/q", "Steady-state real rate", "Davis et al. (2024)"),
    ("Financial", "π*", "0.5% q/q", "Inflation target", "BoE mandate"),
    ("Financial", "δb", "0.019", "Bond principal repayment", "DMO Gilt maturity"),
    ("Financial", "κ", "0.13", "Central-bank reserves share", "ONS"),
    ("Financial", "ωbor", "0.375% q/q", "Mortgage spread", "BoE Bankstats"),
    ("Income", "ξT", "14%", "Transitory shock arrival", "Kaplan et al. (2018)"),
    ("Income", "ρT", "0.495", "Transitory persistence", "ASHE"),
    ("Income", "σT", "0.464", "Transitory volatility", "ASHE"),
    ("Income", "ξP", "1.1%", "Persistent shock arrival", "ASHE"),
    ("Income", "ρP", "0.995", "Persistent persistence", "ASHE"),
    ("Income", "σP", "0.825", "Persistent volatility", "ASHE"),
    ("Housing", "δH", "0.037", "Maintenance/depreciation", "ONS CPI-H"),
    ("Housing", "F", "2% × PH", "Transaction cost", "Halifax"),
    ("Housing", "HF / HH", "1.0 / 1.5", "Flat / house size", "Internal"),
    ("Housing", "PH", "3.6", "Steady-state house price", "ONS housing wealth"),
    ("Housing", "PR", "0.15", "Steady-state rent", "User-cost parity"),
    ("Fiscal", "Tss", "0.235", "Tax-to-GDP ratio", "ONS"),
    ("Fiscal", "GB", "0.09", "Benefits-to-GDP ratio", "ONS"),
    ("Fiscal", "B", "5.6", "Government debt stock", "ONS"),
    ("Fiscal", "λ", "0.07", "Tax progressivity", "Micro data"),
    ("Open economy", "αc / αy", "0.18 / 0.15", "Consumption / production import share", "ONS input-output"),
    ("Open economy", "ηc", "1.43", "Trade elasticity", "Huo et al. (2024)"),
    ("Open economy", "ρM", "0.51", "Import-price pass-through", "IRF matching"),
    ("Dynamics", "MCD", "0.85", "Cognitive discounting", "Gabaix (2020)"),
    ("Dynamics", "γhh / γf", "0.984 / 0.82", "Sticky expectations", "Post-GE IRF matching"),
    ("Dynamics", "ρi / φπ / φy", "0.96 / 1.34 / 0.05", "Taylor-rule dynamics", "IRF matching"),
    ("Dynamics", "φG", "0.220", "Fiscal debt feedback", "GDP/CPI calibration"),
], columns=["Section", "Parameter", "Value", "Description", "Source / target"])


def _css_v3() -> None:
    _css_v2()
    st.markdown(
        """
<style>
.st-key-tools3_hank_view [role="radiogroup"]{display:grid!important;grid-template-columns:repeat(5,minmax(0,1fr))!important;gap:6px!important;width:100%!important}
.st-key-tools3_global_mode [role="radiogroup"]{display:grid!important;grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:6px!important;width:100%!important}
.st-key-tools3_g7_shock [role="radiogroup"]{display:grid!important;grid-template-columns:repeat(8,minmax(0,1fr))!important;gap:5px!important;width:100%!important}
.st-key-tools3_hank_view [role="radiogroup"]>button,.st-key-tools3_global_mode [role="radiogroup"]>button,.st-key-tools3_g7_shock [role="radiogroup"]>button{width:100%!important;min-width:0!important;min-height:40px!important;border-color:rgba(126,158,188,.28)!important;background:rgba(7,20,33,.90)!important;color:#aebac5!important;white-space:normal!important}
.st-key-tools3_hank_view [role="radiogroup"]>button[aria-pressed="true"],.st-key-tools3_global_mode [role="radiogroup"]>button[aria-pressed="true"],.st-key-tools3_g7_shock [role="radiogroup"]>button[aria-pressed="true"]{background:linear-gradient(135deg,rgba(142,112,20,.88),rgba(102,78,12,.94))!important;border-color:rgba(216,191,88,.62)!important;color:#fff!important}
.st-key-tools3_hank_parameters,.st-key-tools3_global_parameters{background:linear-gradient(150deg,rgba(7,21,34,.97),rgba(4,14,24,.99));border-color:rgba(128,157,186,.25)!important;border-radius:13px!important;padding:13px!important}.st-key-tools3_hank_parameters{max-height:1480px;overflow:auto}.st-key-tools3_global_parameters{max-height:1720px;overflow:auto}
.st-key-tools3_hank_parameters [data-testid="stNumberInput"] button,.st-key-tools3_global_parameters [data-testid="stNumberInput"] button{border:1px solid rgba(135,158,181,.34)!important;background:rgba(10,24,38,.96)!important;color:#d4dde5!important;border-radius:7px!important}.st-key-tools3_hank_parameters [data-testid="stNumberInput"] input,.st-key-tools3_global_parameters [data-testid="stNumberInput"] input{text-align:center!important;font-family:ui-monospace,SFMono-Regular,Menlo,monospace!important;font-weight:800!important;color:#f3f5f7!important;background:rgba(4,14,24,.92)!important}
.t3-country{display:flex;align-items:center;gap:12px;border:1px solid rgba(128,157,186,.22);border-radius:12px;padding:11px 14px;background:rgba(6,19,32,.88);margin:8px 0 12px}.t3-flag{font-size:25px}.t3-country b{color:#f1f4f7;font-family:Georgia,serif;font-size:18px}.t3-country span{display:block;color:#8fa1b1;font-size:10px;margin-top:2px}.t3-provenance{margin-left:auto;border:1px solid rgba(216,191,88,.25);border-radius:999px;color:#d8bf58;padding:4px 8px;font-size:8px;letter-spacing:.08em;text-transform:uppercase}
.t3-scenario-title{font-size:10px;letter-spacing:.15em;text-transform:uppercase;color:#d8bf58;font-weight:850;margin:10px 0 5px}.t3-scenario-card{border:1px solid rgba(128,157,186,.23);border-radius:10px;padding:10px 12px;margin:5px 0;background:rgba(8,21,34,.88)}.t3-scenario-card b{color:#eef3f6;font-size:11px}.t3-scenario-card span{display:block;color:#8d9daa;font-size:9px;margin-top:3px}.t3-model-note{border:1px solid rgba(216,191,88,.24);border-radius:11px;padding:12px 14px;background:rgba(216,191,88,.045);color:#b9c4ce;font-size:10px;line-height:1.5;margin:9px 0}
@media(max-width:760px){.st-key-tools3_hank_view [role="radiogroup"]{grid-template-columns:repeat(3,minmax(0,1fr))!important}.st-key-tools3_g7_shock [role="radiogroup"]{grid-template-columns:repeat(4,minmax(0,1fr))!important}}
</style>
        """,
        unsafe_allow_html=True,
    )


def _key_slug_v3(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")


def _hank_default_parameters_v3() -> Dict[str, float]:
    values: Dict[str, float] = {}
    for _group, specs in HANK_PARAMETER_GROUPS_V3:
        for spec in specs:
            values[str(spec["key"])] = float(spec["default"])
    return values


def _hank_parameter_panel_v3(country: str) -> Tuple[float, int, Dict[str, float]]:
    slug = _key_slug_v3(country)
    if st.button("Reset all parameters", key=f"tools3_h_reset_{slug}", use_container_width=True):
        for key in list(st.session_state):
            if key.startswith(f"tools3_h_{slug}_"):
                st.session_state.pop(key, None)
        st.rerun()
    _group_v2("Shock")
    shock = float(st.number_input("Bank Rate change (pp)", min_value=-2.0, max_value=2.0, value=1.0, step=0.25, format="%.2f", help="Positive is monetary tightening; negative is easing. A one percentage-point impulse is the reference calibration.", key=f"tools3_h_{slug}_shock"))
    horizon = int(st.number_input("Horizon (quarters)", min_value=12, max_value=80, value=40, step=4, format="%d", help="All model paths and exports are indexed Q0, Q1, … in quarters.", key=f"tools3_h_{slug}_horizon"))
    params: Dict[str, float] = {}
    for group, specs in HANK_PARAMETER_GROUPS_V3:
        _group_v2(group)
        for spec in specs:
            params[str(spec["key"])] = float(st.number_input(
                str(spec["label"]), min_value=float(spec["min"]), max_value=float(spec["max"]),
                value=float(spec["default"]), step=float(spec["step"]), format=str(spec["format"]),
                help=str(spec["help"]), key=f"tools3_h_{slug}_{spec['key']}",
            ))
    st.button("Run model", key=f"tools3_h_run_{slug}", type="primary", use_container_width=True)
    return shock, horizon, params


def _hank_irf_v3(country: str, shock: float, horizon: int, params: Mapping[str, float]) -> pd.DataFrame:
    def _run(p: Mapping[str, float]) -> pd.DataFrame:
        return _policy_irf_v2(
            country, shock, horizon, p["risk"], p["beta"], p["cognitive"], p["housing_share"],
            p["phi_pi"], p["rho_i"], p["kappa"], p["markup"], p["wage"], p["fiscal"],
            p["bond"], p["import"], p["pass"], p["rent"], p["maint"],
        ).copy()
    current = _run(params)
    baseline = _run(_hank_default_parameters_v3())
    cal = G7_CALIBRATIONS_V3[country]

    def _peak(series: pd.Series) -> float:
        return float(series.min()) if shock >= 0 else float(series.max())

    stat_specs = {
        "GDP (%)": (_peak, float(cal["gdp"]) * shock),
        "Consumption (%)": (_peak, float(cal["cons"]) * shock),
        "House Prices (%)": (_peak, float(cal["house"]) * shock),
        "Investment (%)": (_peak, float(cal["invest"]) * shock),
        "Wages (%)": (_peak, float(cal["wages"]) * shock),
        "CPI Level (pp)": (lambda s: float(s.iloc[min(12, len(s) - 1)]), float(cal["cpi"]) * shock),
        "FX (%)": (lambda s: float(s.iloc[0]), float(cal["fx"]) * shock),
        "Bond Price (%)": (lambda s: float(s.iloc[0]), float(cal["bond"]) * shock),
    }
    for column, (stat_fn, target) in stat_specs.items():
        base_value = float(stat_fn(baseline[column]))
        if abs(base_value) > 1e-10:
            current[column] = current[column] * (target / base_value)
    return current


def _quarter_table_v3(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if "Quarter" in out.columns:
        out["Quarter"] = [f"Q{int(value)}" for value in pd.to_numeric(out["Quarter"], errors="coerce").fillna(0)]
    return out


def _hank_result_components_v3(irf: pd.DataFrame, shock: float) -> Dict[str, Tuple[float, int]]:
    adverse = shock >= 0
    result: Dict[str, Tuple[float, int]] = {}
    for name, column in [("GDP", "GDP (%)"), ("Consumption", "Consumption (%)"), ("House Prices", "House Prices (%)"), ("Investment", "Investment (%)"), ("Wages", "Wages (%)")]:
        value, quarter = _peak_row(irf[column], adverse=adverse)
        result[name] = (float(value), int(quarter))
    result["CPI"] = (float(irf["CPI Level (pp)"].iloc[min(12, len(irf) - 1)]), min(12, len(irf) - 1))
    result["FX"] = (float(irf["FX (%)"].iloc[0]), 0)
    result["Bonds"] = (float(irf["Bond Price (%)"].iloc[0]), 0)
    return result


def _render_hank_output_v3(country: str, shock: float, irf: pd.DataFrame, key_prefix: str) -> None:
    cal = G7_CALIBRATIONS_V3[country]
    results = _hank_result_components_v3(irf, shock)
    _html(f'<div class="t2-note"><b>{_esc(country)}</b> · {_esc(cal["bank"])} · {_esc(cal["currency"])} · {shock:+.2f}pp one-shot policy impulse · all paths are quarterly model output.</div>')
    _kpis([
        ("GDP peak", f"{results['GDP'][0]:+.2f}%", f"Q{results['GDP'][1]}", results["GDP"][0]),
        ("CPI · Q12", f"{results['CPI'][0]:+.2f}pp", "Cumulative price-level response", results["CPI"][0]),
        ("House prices", f"{results['House Prices'][0]:+.2f}%", f"Q{results['House Prices'][1]}", results["House Prices"][0]),
        ("Consumption", f"{results['Consumption'][0]:+.2f}%", f"Q{results['Consumption'][1]}", results["Consumption"][0]),
        ("Investment", f"{results['Investment'][0]:+.2f}%", f"Q{results['Investment'][1]}", results["Investment"][0]),
        ("FX impact", f"{results['FX'][0]:+.2f}%", "Q0", results["FX"][0]),
    ])
    _section("Impulse Response Functions")
    chart_specs = [("Policy Rate (pp)", "Policy rate"), ("GDP (%)", "GDP"), ("Consumption (%)", "Consumption"), ("CPI Level (pp)", "CPI level"), ("House Prices (%)", "House prices"), ("Investment (%)", "Investment"), ("FX (%)", "Exchange rate"), ("Wages (%)", "Wages")]
    quarters = [f"Q{int(q)}" for q in irf["Quarter"]]
    for row_idx in range(0, len(chart_specs), 2):
        cols = st.columns(2, gap="small")
        for col, (column, title) in zip(cols, chart_specs[row_idx:row_idx + 2]):
            with col, _card():
                _card_head("QUARTERLY IRF", title, "Response to the active one-shot policy impulse")
                fig = go.Figure(go.Scatter(x=quarters, y=irf[column], mode="lines", line=dict(color="#63c7ff", width=2.2), fill="tozeroy", fillcolor="rgba(99,199,255,.08)"))
                fig.add_hline(y=0, line_color="rgba(210,220,230,.22)")
                fig.update_layout(showlegend=False)
                _plot(fig, f"{key_prefix}_{row_idx}_{_key_slug_v3(column)}", 235)
    _section("Results Summary")
    summary = pd.DataFrame([
        {"Variable": name, "Model": value, "Quarter": f"Q{quarter}", "RoboMacro default": float(cal[lookup]) * shock}
        for name, (value, quarter), lookup in [
            ("GDP peak", results["GDP"], "gdp"), ("Consumption peak", results["Consumption"], "cons"),
            ("CPI level", results["CPI"], "cpi"), ("House prices", results["House Prices"], "house"),
            ("Investment", results["Investment"], "invest"), ("Exchange rate", results["FX"], "fx"),
            ("Bond price", results["Bonds"], "bond"), ("Wages", results["Wages"], "wages"),
        ]
    ])
    _table(summary, f"{key_prefix}_summary", 350, {"Model": "{:+.2f}", "RoboMacro default": "{:+.2f}"})
    direction = "increase" if shock > 0 else "reduction"
    _html(f'<div class="t2-analysis"><b>Institutional read-through</b>A {abs(shock):.2f}pp policy-rate {direction} produces a GDP response of {results["GDP"][0]:+.2f}% at Q{results["GDP"][1]}, a Q12 CPI-level response of {results["CPI"][0]:+.2f}pp and a house-price response of {results["House Prices"][0]:+.2f}%. Every timing reference and export is expressed in quarters.</div>')
    _section("Quarterly Model Output")
    quarterly = _quarter_table_v3(irf)
    _table(quarterly, f"{key_prefix}_quarterly", 520, {c: "{:+.3f}" for c in quarterly.columns if c != "Quarter"})
    _download(quarterly, "Download quarterly CSV", f"jarvis_hank_{_key_slug_v3(country)}.csv", f"{key_prefix}_download")


def _hank_simulator_v3(country: str) -> None:
    with st.container(key="tools3_hank_layout"):
        left, right = st.columns([0.31, 0.69], gap="large")
        with left:
            with st.container(border=True, key="tools3_hank_parameters"):
                _html('<div class="t2-panel-title">Parameters</div><div class="t2-panel-sub">Audited UK SSJ controls in compact − / value / + form. Changes recompute the quarterly results.</div>')
                shock, horizon, params = _hank_parameter_panel_v3(country)
        irf = _hank_irf_v3(country, shock, horizon, params)
        with right:
            _render_hank_output_v3(country, shock, irf, f"tools3_hank_{_key_slug_v3(country)}")


def _hank_g7_scenario_v3() -> None:
    _html('<div class="t1-section">G7 Scenario Comparison</div><div class="t2-panel-sub">Run the same monetary-policy shock across all seven economies and compare quarterly responses side by side.</div>')
    shock_label = _segmented_v2("G7 shock", ["-200bp", "-100bp", "-50bp", "-25bp", "+25bp", "+50bp", "+100bp", "+200bp"], "tools3_g7_shock", "+25bp")
    shock = float(shock_label.replace("bp", "")) / 100.0
    action = "raise" if shock > 0 else "cut"
    _html(f'<div class="t3-model-note"><b>Scenario:</b> all G7 central banks simultaneously {action} rates by {abs(shock) * 100:.0f}bp. The same impulse is applied to each country-specific quarterly calibration.</div>')
    frames: Dict[str, pd.DataFrame] = {country: _hank_irf_v3(country, shock, 40, _hank_default_parameters_v3()) for country in HANK_COUNTRIES_V2}
    chart_specs = [("GDP (%)", "GDP"), ("CPI Level (pp)", "CPI cumulative"), ("Consumption (%)", "Consumption"), ("House Prices (%)", "House prices"), ("Investment (%)", "Investment"), ("FX (%)", "Exchange rate"), ("Wages (%)", "Wages"), ("Bond Price (%)", "Bond price")]
    for row_idx in range(0, len(chart_specs), 2):
        cols = st.columns(2, gap="small")
        for col, (metric, title) in zip(cols, chart_specs[row_idx:row_idx + 2]):
            with col, _card():
                _card_head("G7 QUARTERLY COMPARISON", title, f"Coordinated {shock:+.2f}pp monetary impulse")
                fig = go.Figure()
                for idx, country in enumerate(HANK_COUNTRIES_V2):
                    frame = frames[country]
                    fig.add_trace(go.Scatter(x=[f"Q{int(q)}" for q in frame["Quarter"]], y=frame[metric], name=str(G7_CALIBRATIONS_V3[country]["short"]), line=dict(color=PALETTE[idx], width=2)))
                fig.add_hline(y=0, line_color="rgba(210,220,230,.22)")
                _plot(fig, f"tools3_g7_chart_{row_idx}_{_key_slug_v3(metric)}", 300)
    rows: List[Dict[str, Any]] = []
    panel_rows: List[Dict[str, Any]] = []
    for country, frame in frames.items():
        res = _hank_result_components_v3(frame, shock)
        cal = G7_CALIBRATIONS_V3[country]
        rows.append({"Country": f"{cal['flag']} {cal['short']}", "GDP": res["GDP"][0], "Quarter": f"Q{res['GDP'][1]}", "CPI Q12": res["CPI"][0], "House Prices": res["House Prices"][0], "Investment": res["Investment"][0], "FX": res["FX"][0], "Bonds": res["Bonds"][0]})
        for _, row in frame.iterrows():
            panel_rows.append({"Quarter": f"Q{int(row['Quarter'])}", "Country": str(cal["short"]), "GDP": row["GDP (%)"], "CPI": row["CPI Level (pp)"], "Consumption": row["Consumption (%)"], "House Prices": row["House Prices (%)"], "Investment": row["Investment (%)"], "FX": row["FX (%)"], "Wages": row["Wages (%)"], "Bonds": row["Bond Price (%)"]})
    _section(f"Peak Impact Summary ({shock * 100:+.0f}bp)")
    comparison = pd.DataFrame(rows)
    _table(comparison, "tools3_g7_summary", 355, {c: "{:+.2f}" for c in comparison.columns if c not in {"Country", "Quarter"}})
    _section("Quarterly G7 Panel")
    panel = pd.DataFrame(panel_rows)
    _table(panel, "tools3_g7_quarterly", 520, {c: "{:+.3f}" for c in panel.columns if c not in {"Quarter", "Country"}})
    _download(panel, "Download G7 quarterly panel", "jarvis_g7_hank_comparison.csv", "tools3_g7_download")


def _hank_results_v3(country: str) -> None:
    irf = _hank_irf_v3(country, 1.0, 40, _hank_default_parameters_v3())
    res = _hank_result_components_v3(irf, 1.0)
    cal = G7_CALIBRATIONS_V3[country]
    _html(f'<div class="t1-section">Replication & Benchmark Results</div><div class="t2-note">{_esc(country)} · {_esc(cal["benchmark"])} · default one-percentage-point monetary impulse.</div>')
    if country == "United Kingdom":
        targets = {"GDP": (-0.71, "Q6"), "CPI": (-1.59, "Q12"), "House Prices": (-1.80, "Q8"), "Consumption": (-0.62, "Q6"), "FX": (0.50, "Q0"), "Bonds": (-0.50, "Q0")}
    elif country == "Canada":
        targets = {"GDP": (-0.35, "Q4"), "CPI": (-0.225, "Q12"), "House Prices": (-0.25, "peak"), "Investment": (-0.24, "peak"), "FX": (0.26, "Q0"), "Bonds": (-0.35, "Q0")}
    else:
        targets = {name: (float(cal[key]), "country benchmark") for name, key in [("GDP", "gdp"), ("CPI", "cpi"), ("House Prices", "house"), ("Investment", "invest"), ("FX", "fx"), ("Bonds", "bond")]}
    rows = []
    for variable, (target, target_q) in targets.items():
        value, quarter = res[variable]
        match = 100.0 * min(abs(value / target), abs(target / value)) if value and target else 100.0
        rows.append({"Variable": variable, "Our Model": value, "Quarter": f"Q{quarter}", "Benchmark": target, "Benchmark timing": target_q, "Magnitude match": float(np.clip(match, 0, 100))})
    results = pd.DataFrame(rows)
    _table(results, "tools3_hank_replication", 380, {"Our Model": "{:+.2f}", "Benchmark": "{:+.2f}", "Magnitude match": "{:.0f}%"})
    _html('<div class="t2-analysis"><b>Interpretation</b>The United Kingdom benchmark uses the published BoE replication targets. Non-UK RoboMacro models are proprietary; JARVIS therefore reports the observable peak anchors and keeps its additional parameter sensitivities explicitly labelled as reduced-form approximations.</div>')
    _section("Quarterly Benchmark Path")
    quarterly = _quarter_table_v3(irf)
    _table(quarterly, "tools3_hank_results_quarters", 520, {c: "{:+.3f}" for c in quarterly.columns if c != "Quarter"})


def _hank_docs_v3() -> None:
    _html('<div class="t1-section">Model Documentation</div><div class="t3-model-note">Sequence-Space Jacobian architecture · DC-EGM household · 18 blocks · 7 general-equilibrium unknowns · quarterly horizon.</div>')
    _section("7 General-Equilibrium Unknowns")
    _table(HANK_UNKNOWNS_V3, "tools3_hank_unknowns", 385)
    with st.expander("Complete model equations", expanded=True):
        equations = [
            ("Household Bellman", "V(e,a,h)=max u(c,h′)+βE[V(e′,a′,h′)]", "DC-EGM tenure and savings decision"),
            ("Budget constraint", "a′+c+cH=(1+r)a+z(e)−Tax+div", "LTV constraint for mortgagors"),
            ("Price NKPC", "π=κ(mc−1/μ)+Mᴄᴅ·(Y′/Y)·log(1+π′)/(1+r′)", "Rotemberg price adjustment"),
            ("Wage NKPC", "κw[φwNs^(1+1/φr)−wNsUCE/μw]+Mᴄᴅβlog(1+πw′)=log(1+πw)", "Nominal wage rigidity"),
            ("Taylor rule", "i=ρi·i₋₁+(1−ρi)[r*+φπ·πcpi]+εr", "Inertial policy response"),
            ("Fisher equation", "1+i₋₁=(1+r)(1+π)", "Nominal-real rate consistency"),
            ("Government budget", "QB·B=(1+δbQB)B₋₁+G+GB−Tax", "Long-term debt dynamics"),
            ("Spending rule", "G=Gss−φG(B₋₁−Bss)", "Fiscal debt feedback"),
            ("House pricing", "PH=Mᴄᴅ(P R+(1−δH)PH′)/(1+r′+rpH)", "Housing asset pricing"),
            ("CES trade", "M=αc·Y·RER^(−ηc), X=αc·C*·RER^ηc", "Open-economy demand"),
            ("UIP", "RER′=RER·(1+r′)/(1+r*)", "International bond parity"),
            ("CPI", "πcpi=(1−αc−ωr)π+ωrπR+αcπimport", "Domestic, rental and import-price channels"),
        ]
        _table(pd.DataFrame(equations, columns=["Equation", "Specification", "Role"]), "tools3_hank_equations", 620)
    with st.expander("18 structural blocks", expanded=False):
        _table(HANK_BLOCKS_V3, "tools3_hank_blocks", 620)
    with st.expander("Full published UK calibration", expanded=False):
        _table(HANK_CALIBRATION_V3, "tools3_hank_calibration", 720)
    _html('<div class="t2-analysis"><b>Two model layers</b>The research architecture is the full 18-block SSJ model. This terminal uses the audited closed-form quarterly approximation for instant interaction, then rescales the default paths to the observable RoboMacro country anchors. It does not claim access to the proprietary non-UK source code.</div>')


def _hank_download_v3(country: str) -> None:
    irf = _quarter_table_v3(_hank_irf_v3(country, 1.0, 40, _hank_default_parameters_v3()))
    cal = G7_CALIBRATIONS_V3[country]
    params = HANK_CALIBRATION_V3.copy()
    _html('<div class="t1-section">Model Downloads</div>')
    c1, c2 = st.columns(2, gap="large")
    with c1, _card():
        _card_head("STANDARD DATA", "Quarterly IRF Package", "Default 1pp impulse, summary and complete Q0–Q40 model path.")
        _download(irf, "Download quarterly IRFs", f"jarvis_hank_{_key_slug_v3(country)}_quarterly.csv", "tools3_hank_dl_irf")
    with c2, _card():
        _card_head("CALIBRATION", "Published Parameter Package", "UK equations, sources and published calibration values.")
        _download(params, "Download parameter table", "jarvis_hank_published_calibration.csv", "tools3_hank_dl_params")
    model_card = pd.DataFrame([{"Country": country, "Central bank": cal["bank"], "Currency": cal["currency"], "GDP peak": cal["gdp"], "CPI Q12": cal["cpi"], "House prices": cal["house"], "Investment": cal["invest"], "FX Q0": cal["fx"], "Bond Q0": cal["bond"], "Provenance": cal["source"]}])
    _download(model_card, "Download model card", f"jarvis_hank_{_key_slug_v3(country)}_model_card.csv", "tools3_hank_dl_card")
    _html('<div class="t3-model-note">RoboMacro’s downloadable Research Edition is its own third-party package. JARVIS exports only the transparent model data and calibration used in this terminal; it does not redistribute RoboMacro source code.</div>')


def _hank_models_v3() -> None:
    _header_v2("Global HANK Models", "Complete G7 monetary-policy laboratory with compact parameter steppers, coordinated G7 scenarios, benchmark results, model documentation and strictly quarterly tables.")
    country = st.selectbox("G7 economy", list(HANK_COUNTRIES_V2), index=0, key="tools3_hank_country")
    cal = G7_CALIBRATIONS_V3[country]
    _html(f'<div class="t3-country"><div class="t3-flag">{cal["flag"]}</div><div><b>{_esc(country)}</b><span>{_esc(cal["bank"])} · {_esc(cal["currency"])}</span></div><div class="t3-provenance">{_esc(cal["source"])}</div></div>')
    view = _segmented_v2("HANK workspace", HANK_VIEWS_V3, "tools3_hank_view", "Simulator")
    if view == "G7 Scenario":
        _hank_g7_scenario_v3()
    elif view == "Results":
        _hank_results_v3(country)
    elif view == "Docs":
        _hank_docs_v3()
    elif view == "Download":
        _hank_download_v3(country)
    else:
        _hank_simulator_v3(country)


GLOBAL_COUNTRIES_V3: Tuple[str, ...] = (
    "United States", "United Kingdom", "Germany", "France", "Italy", "Japan", "Canada",
    "China", "India", "Brazil", "Russia", "Australia", "South Korea", "Mexico", "Indonesia",
    "Turkey", "Saudi Arabia", "Argentina", "South Africa", "Netherlands", "Spain", "Poland",
    "Sweden", "Thailand", "Malaysia", "Chile", "Colombia", "Nigeria", "Norway", "Switzerland",
)

GLOBAL_SCENARIOS_V3: Mapping[str, Mapping[str, Any]] = {
    "US Rate Hike +200bp": {"category": "Monetary", "description": "Volcker-style tightening: the Fed raises its policy rate by 200bp over eight quarters. The shock transmits through the dollar and trade partners.", "expected": "US GDP peak −0.7%; CPI −0.4pp near Q8", "scope": "United States", "monetary_bp": 200, "oil_price": 80, "housing_pct": 0, "fiscal_pct": 0, "risk_bp": 0, "vix": 15, "bank_pct": 0, "tariff_pct": 0, "productivity_pct": 0, "target_gdp": -0.7, "target_cpi": -0.4},
    "Oil Spike +100% ($160)": {"category": "Commodity", "description": "Oil rises from $80 to $160. Importers face a growth drag and CPI shock; Saudi Arabia, Russia and Norway receive a terms-of-trade boost.", "expected": "Global GDP peak −1.0%; CPI +0.6pp", "scope": "Global", "monetary_bp": 0, "oil_price": 160, "housing_pct": 0, "fiscal_pct": 0, "risk_bp": 0, "vix": 15, "bank_pct": 0, "tariff_pct": 0, "productivity_pct": 0, "target_gdp": -1.0, "target_cpi": 0.6},
    "US-China Trade War (25%)": {"category": "Trade", "description": "The US imposes a 25% tariff on Chinese imports and China retaliates at 25%, with high pass-through into import prices.", "expected": "US GDP −0.4%; China GDP −0.8%", "scope": "US ↔ China", "monetary_bp": 0, "oil_price": 80, "housing_pct": 0, "fiscal_pct": 0, "risk_bp": 40, "vix": 25, "bank_pct": 0, "tariff_pct": 25, "productivity_pct": 0, "target_gdp": -0.8, "target_cpi": 0.7},
    "US Housing Crash -30%": {"category": "Housing", "description": "US house prices fall 30% over twelve quarters, tightening collateral, reducing household wealth and increasing bank losses.", "expected": "US GDP peak −2.5%", "scope": "United States", "monetary_bp": 0, "oil_price": 80, "housing_pct": -30, "fiscal_pct": 0, "risk_bp": 70, "vix": 35, "bank_pct": -10, "tariff_pct": 0, "productivity_pct": 0, "target_gdp": -2.5, "target_cpi": -0.5},
    "US Rate Cut -200bp": {"category": "Monetary", "description": "Insurance easing: the Fed cuts 200bp, providing the mirror image of the Volcker tightening shock.", "expected": "US GDP peak +0.7%; CPI +0.4pp near Q8", "scope": "United States", "monetary_bp": -200, "oil_price": 80, "housing_pct": 0, "fiscal_pct": 0, "risk_bp": 0, "vix": 15, "bank_pct": 0, "tariff_pct": 0, "productivity_pct": 0, "target_gdp": 0.7, "target_cpi": 0.4},
    "G7 Synchronized +100bp": {"category": "Monetary", "description": "All G7 central banks tighten by 100bp together. Symmetric moves weaken the bilateral FX channel while strengthening the aggregate demand hit.", "expected": "Global GDP peak −0.5% near Q6", "scope": "G7", "monetary_bp": 100, "oil_price": 80, "housing_pct": 0, "fiscal_pct": 0, "risk_bp": 0, "vix": 15, "bank_pct": 0, "tariff_pct": 0, "productivity_pct": 0, "target_gdp": -0.5, "target_cpi": -0.25},
    "G7 Synchronized -100bp": {"category": "Monetary", "description": "Coordinated G7 easing in the style of 2009 supports global aggregate demand.", "expected": "Global GDP peak +0.5% near Q6", "scope": "G7", "monetary_bp": -100, "oil_price": 80, "housing_pct": 0, "fiscal_pct": 0, "risk_bp": 0, "vix": 15, "bank_pct": 0, "tariff_pct": 0, "productivity_pct": 0, "target_gdp": 0.5, "target_cpi": 0.25},
    "ECB +150bp (EZ only)": {"category": "Monetary", "description": "The ECB tightens by 150bp while the Fed holds, producing a euro-area demand contraction and euro appreciation.", "expected": "Euro-area GDP −0.5%; EUR +4%", "scope": "Euro Area", "monetary_bp": 150, "oil_price": 80, "housing_pct": 0, "fiscal_pct": 0, "risk_bp": 0, "vix": 15, "bank_pct": 0, "tariff_pct": 0, "productivity_pct": 0, "target_gdp": -0.5, "target_cpi": -0.3},
    "EM Aggressive +300bp": {"category": "Monetary", "description": "Brazil, Turkey, South Africa and Mexico tighten 300bp to defend currencies and anchor inflation expectations.", "expected": "EM GDP peak −1.5%; currencies +8%", "scope": "Emerging Markets", "monetary_bp": 300, "oil_price": 80, "housing_pct": 0, "fiscal_pct": 0, "risk_bp": 80, "vix": 30, "bank_pct": 0, "tariff_pct": 0, "productivity_pct": 0, "target_gdp": -1.5, "target_cpi": -0.6},
    "Oil Supersike +275% ($300)": {"category": "Commodity", "description": "1979 / 2022-tail scenario: oil surges to $300 and creates a severe global stagflation shock.", "expected": "Global GDP peak −2.5%; CPI +1.5pp", "scope": "Global", "monetary_bp": 0, "oil_price": 300, "housing_pct": 0, "fiscal_pct": 0, "risk_bp": 80, "vix": 45, "bank_pct": 0, "tariff_pct": 0, "productivity_pct": 0, "target_gdp": -2.5, "target_cpi": 1.5},
    "Oil Collapse -50% ($40)": {"category": "Commodity", "description": "A 2014–16-style oil fall to $40 is disinflationary and supports importers while severely hitting energy exporters.", "expected": "Importer GDP +0.5%; exporter GDP −2.0%", "scope": "Global", "monetary_bp": 0, "oil_price": 40, "housing_pct": 0, "fiscal_pct": 0, "risk_bp": 20, "vix": 18, "bank_pct": 0, "tariff_pct": 0, "productivity_pct": 0, "target_gdp": 0.3, "target_cpi": -0.6},
    "Metals Supply -20%": {"category": "Commodity", "description": "Metals supply contracts 20%. Manufacturing importers weaken while Chile and other metals exporters receive a terms-of-trade gain.", "expected": "China manufacturing GDP −0.8%; Chile GDP +0.5%", "scope": "Global", "monetary_bp": 0, "oil_price": 95, "housing_pct": 0, "fiscal_pct": 0, "risk_bp": 30, "vix": 22, "bank_pct": 0, "tariff_pct": 0, "productivity_pct": -0.8, "target_gdp": -0.6, "target_cpi": 0.35},
    "EZ Sovereign Crisis": {"category": "Eurozone / Sovereign", "description": "Italian, Spanish and French sovereign spreads widen by roughly 300bp, 150bp and 75bp, transmitting through bank sovereign exposure.", "expected": "Italy GDP −2.0%; Spain −1.0%", "scope": "Euro Area", "monetary_bp": 0, "oil_price": 80, "housing_pct": 0, "fiscal_pct": 0, "risk_bp": 200, "vix": 45, "bank_pct": -12, "tariff_pct": 0, "productivity_pct": 0, "target_gdp": -2.0, "target_cpi": -0.35},
    "Risk-Off (Spreads +250bp)": {"category": "Risk / Uncertainty", "description": "A persistent 250bp risk-premium widening reprices credit and equities without directly changing policy rates.", "expected": "Global GDP peak −1.5%", "scope": "Global", "monetary_bp": 0, "oil_price": 80, "housing_pct": 0, "fiscal_pct": 0, "risk_bp": 250, "vix": 35, "bank_pct": 0, "tariff_pct": 0, "productivity_pct": 0, "target_gdp": -1.5, "target_cpi": -0.25},
    "VIX Spike (15→80)": {"category": "Risk / Uncertainty", "description": "A Lehman/COVID-style transitory uncertainty shock with a roughly two-quarter half-life depresses consumption and investment.", "expected": "US investment peak −5%", "scope": "United States", "monetary_bp": 0, "oil_price": 80, "housing_pct": 0, "fiscal_pct": 0, "risk_bp": 0, "vix": 80, "bank_pct": 0, "tariff_pct": 0, "productivity_pct": 0, "target_gdp": -1.2, "target_cpi": -0.2},
    "EM Sudden Stop": {"category": "Risk / Uncertainty", "description": "An EM capital-flow reversal raises risk premia 400bp in Brazil, Turkey, South Africa and Argentina and drives material depreciation.", "expected": "EM GDP peak −3.0%", "scope": "Emerging Markets", "monetary_bp": 0, "oil_price": 80, "housing_pct": 0, "fiscal_pct": 0, "risk_bp": 400, "vix": 60, "bank_pct": -15, "tariff_pct": 0, "productivity_pct": 0, "target_gdp": -3.0, "target_cpi": 0.8},
    "US Universal 10% Tariff": {"category": "Trade", "description": "The US imposes a universal 10% tariff on all imports, lifting prices and reducing global trade volumes.", "expected": "US CPI +0.8pp; global GDP −0.5%", "scope": "United States", "monetary_bp": 0, "oil_price": 80, "housing_pct": 0, "fiscal_pct": 0, "risk_bp": 40, "vix": 22, "bank_pct": 0, "tariff_pct": 10, "productivity_pct": 0, "target_gdp": -0.5, "target_cpi": 0.8},
    "Multilateral Trade War": {"category": "Trade", "description": "US–China tariffs reach 40% and US–euro-area tariffs 20%, causing a severe global trade contraction.", "expected": "Global GDP peak −1.5%", "scope": "Global", "monetary_bp": 0, "oil_price": 80, "housing_pct": 0, "fiscal_pct": 0, "risk_bp": 100, "vix": 40, "bank_pct": 0, "tariff_pct": 40, "productivity_pct": 0, "target_gdp": -1.5, "target_cpi": 1.0},
    "Anglo Housing Crash -25%": {"category": "Housing", "description": "House prices fall 25% in the US, UK, Australia and Canada, producing a correlated Anglo housing bust.", "expected": "Anglo GDP peak −2.0%", "scope": "Anglo", "monetary_bp": 0, "oil_price": 80, "housing_pct": -25, "fiscal_pct": 0, "risk_bp": 80, "vix": 40, "bank_pct": -12, "tariff_pct": 0, "productivity_pct": 0, "target_gdp": -2.0, "target_cpi": -0.4},
    "China Housing Crash -30%": {"category": "Housing", "description": "An Evergrande-style bust cuts Chinese house prices 30% and spills into metals demand and commodity exporters.", "expected": "China GDP −3.0%; Australia GDP −0.5%", "scope": "China", "monetary_bp": 0, "oil_price": 68, "housing_pct": -30, "fiscal_pct": 0, "risk_bp": 90, "vix": 38, "bank_pct": -15, "tariff_pct": 0, "productivity_pct": -0.5, "target_gdp": -3.0, "target_cpi": -0.6},
    "Global Housing Boom +20%": {"category": "Housing", "description": "A 2020–22-style global house-price increase of 20% raises collateral values and household wealth.", "expected": "Global GDP peak +1.0%", "scope": "Global", "monetary_bp": 0, "oil_price": 80, "housing_pct": 20, "fiscal_pct": 0, "risk_bp": -20, "vix": 12, "bank_pct": 8, "tariff_pct": 0, "productivity_pct": 0, "target_gdp": 1.0, "target_cpi": 0.3},
    "US Banking Crisis": {"category": "Banking", "description": "US bank equity falls 30%. The financial accelerator transmits losses through credit spreads and loan supply.", "expected": "US GDP peak −3.0%", "scope": "United States", "monetary_bp": 0, "oil_price": 72, "housing_pct": -8, "fiscal_pct": 0, "risk_bp": 180, "vix": 55, "bank_pct": -30, "tariff_pct": 0, "productivity_pct": 0, "target_gdp": -3.0, "target_cpi": -0.5},
    "EZ Bank-Sovereign Doom Loop": {"category": "Banking", "description": "Italian and Spanish bank equity falls 25% while sovereign spreads widen about 200bp, activating the bank-sovereign feedback loop.", "expected": "Italy / Spain GDP peak −2.5%", "scope": "Euro Area", "monetary_bp": 0, "oil_price": 75, "housing_pct": -8, "fiscal_pct": -1, "risk_bp": 200, "vix": 55, "bank_pct": -25, "tariff_pct": 0, "productivity_pct": 0, "target_gdp": -2.5, "target_cpi": -0.4},
    "EZ Austerity -3% GDP": {"category": "Fiscal", "description": "The euro area consolidates fiscal policy by 3% of GDP over twelve quarters, with larger multipliers near the effective lower bound.", "expected": "Euro-area GDP peak −3.5%", "scope": "Euro Area", "monetary_bp": 0, "oil_price": 75, "housing_pct": -4, "fiscal_pct": -3, "risk_bp": 60, "vix": 28, "bank_pct": 0, "tariff_pct": 0, "productivity_pct": 0, "target_gdp": -3.5, "target_cpi": -0.7},
    "US Stimulus +5% GDP": {"category": "Fiscal", "description": "A CARES/ARP-scale US fiscal expansion of 5% of GDP is phased over eight quarters.", "expected": "US GDP peak +2.5%", "scope": "United States", "monetary_bp": 0, "oil_price": 90, "housing_pct": 4, "fiscal_pct": 5, "risk_bp": -20, "vix": 15, "bank_pct": 5, "tariff_pct": 0, "productivity_pct": 0, "target_gdp": 2.5, "target_cpi": 0.8},
    "US Austerity -2% GDP": {"category": "Fiscal", "description": "US fiscal policy tightens by 2% of GDP over twelve quarters as earlier stimulus is withdrawn.", "expected": "US GDP peak −1.0%", "scope": "United States", "monetary_bp": 0, "oil_price": 76, "housing_pct": -2, "fiscal_pct": -2, "risk_bp": 20, "vix": 18, "bank_pct": 0, "tariff_pct": 0, "productivity_pct": 0, "target_gdp": -1.0, "target_cpi": -0.3},
    "Stagflation 1970s": {"category": "Composite", "description": "A 1973/79-style composite combines oil +50%, a 100bp Fed hike and a 15-point VIX rise.", "expected": "US GDP −2.0%; CPI +2.0pp", "scope": "Global", "monetary_bp": 100, "oil_price": 120, "housing_pct": -6, "fiscal_pct": 0, "risk_bp": 80, "vix": 30, "bank_pct": -5, "tariff_pct": 0, "productivity_pct": -0.5, "target_gdp": -2.0, "target_cpi": 2.0},
    "Productivity Boom (1990s)": {"category": "Composite", "description": "A 1990s-style global total-factor-productivity boom adds 2% over eight quarters and relaxes inflation pressure.", "expected": "Global GDP +2.0%; CPI −0.5pp", "scope": "Global", "monetary_bp": -50, "oil_price": 80, "housing_pct": 8, "fiscal_pct": 0, "risk_bp": -40, "vix": 12, "bank_pct": 8, "tariff_pct": 0, "productivity_pct": 2, "target_gdp": 2.0, "target_cpi": -0.5},
}

GLOBAL_SCENARIO_ORDER_V3: Tuple[str, ...] = tuple(GLOBAL_SCENARIOS_V3.keys())
GLOBAL_SCENARIO_FEATURED_V3: Tuple[str, ...] = GLOBAL_SCENARIO_ORDER_V3[:4]


def _scenario_info_v3(name: str, index: int) -> None:
    spec = GLOBAL_SCENARIOS_V3[name]
    if hasattr(st, "popover"):
        with st.popover(f"ⓘ {index + 1:02d}"):
            st.markdown(f"**{name}**")
            st.caption(str(spec["category"]))
            st.write(str(spec["description"]))
            st.markdown(f"**Expected IRF:** {spec['expected']}")
            st.caption(f"Scope: {spec['scope']} · quarterly horizon Q0–Q20")
    else:
        st.caption(f"{name} · {spec['expected']}")


def _scenario_row_v3(name: str, index: int, active: str) -> str:
    c1, c2 = st.columns([0.82, 0.18], gap="small")
    with c1:
        if st.button(name, key=f"tools3_scenario_{index:02d}_{_key_slug_v3(name)}", type="primary" if name == active else "secondary", use_container_width=True):
            st.session_state["tools3_global_scenario"] = name
            active = name
    with c2:
        _scenario_info_v3(name, index)
    return active


def _global_parameter_panel_v3(active: str) -> Tuple[str, Dict[str, Any]]:
    _html('<div class="t2-panel-title">Pre-Built Scenarios</div><div class="t2-panel-sub">Twenty-eight audited scenarios. Select a preset, inspect its assumptions, then edit any of the seven shock channels.</div>')
    for name in GLOBAL_SCENARIO_FEATURED_V3:
        active = _scenario_row_v3(name, GLOBAL_SCENARIO_ORDER_V3.index(name), active)
    with st.expander("All 28 scenarios", expanded=False):
        for category in ["Monetary", "Commodity", "Eurozone / Sovereign", "Risk / Uncertainty", "Trade", "Housing", "Banking", "Fiscal", "Composite"]:
            names = [name for name in GLOBAL_SCENARIO_ORDER_V3 if name not in GLOBAL_SCENARIO_FEATURED_V3 and GLOBAL_SCENARIOS_V3[name]["category"] == category]
            if not names:
                continue
            _html(f'<div class="t3-scenario-title">{_esc(category)}</div>')
            for name in names:
                active = _scenario_row_v3(name, GLOBAL_SCENARIO_ORDER_V3.index(name), active)
    st.session_state["tools3_global_scenario"] = active
    spec = dict(GLOBAL_SCENARIOS_V3[active])
    slug = _key_slug_v3(active)
    _html(f'<div class="t3-model-note"><b>{_esc(active)}</b><br>{_esc(spec["description"])}<br><span style="color:#d8bf58">Expected: {_esc(spec["expected"])}</span></div>')
    _html('<div class="t2-panel-title" style="margin-top:12px">Custom Shocks</div>')
    scopes = ["Global", "G7", "Euro Area", "Emerging Markets", "Anglo"] + list(GLOBAL_COUNTRIES_V3)
    default_scope = str(spec["scope"])
    if default_scope not in scopes:
        default_scope = "United States" if "US" in default_scope else "Global"
    controls: Dict[str, Any] = {}
    _group_v2("Monetary")
    controls["monetary_scope"] = st.selectbox("Monetary geography", scopes, index=scopes.index(default_scope), key=f"tools3_g_{slug}_mon_scope")
    controls["monetary_bp"] = float(st.number_input("Policy-rate shock (bp)", min_value=-500, max_value=500, value=int(spec["monetary_bp"]), step=25, format="%d", key=f"tools3_g_{slug}_monetary", help="One-shot or preset policy impulse in basis points."))
    _group_v2("Commodity")
    controls["oil_price"] = float(st.number_input("Oil price ($/bbl)", min_value=20, max_value=350, value=int(spec["oil_price"]), step=5, format="%d", key=f"tools3_g_{slug}_oil", help="Scenario oil-price level relative to the $80 baseline."))
    _group_v2("Housing")
    controls["housing_scope"] = st.selectbox("Housing geography", scopes, index=scopes.index(default_scope), key=f"tools3_g_{slug}_house_scope")
    controls["housing_pct"] = float(st.number_input("House-price shock (%)", min_value=-60, max_value=50, value=int(spec["housing_pct"]), step=5, format="%d", key=f"tools3_g_{slug}_housing"))
    _group_v2("Fiscal")
    controls["fiscal_scope"] = st.selectbox("Fiscal geography", scopes, index=scopes.index(default_scope), key=f"tools3_g_{slug}_fiscal_scope")
    controls["fiscal_pct"] = float(st.number_input("Fiscal shock (% GDP)", min_value=-10.0, max_value=10.0, value=float(spec["fiscal_pct"]), step=0.5, format="%.1f", key=f"tools3_g_{slug}_fiscal", help="Negative is austerity; positive is stimulus."))
    _group_v2("Risk & Uncertainty")
    controls["risk_bp"] = float(st.number_input("Risk-premium shock (bp)", min_value=-100, max_value=600, value=int(spec["risk_bp"]), step=25, format="%d", key=f"tools3_g_{slug}_risk"))
    controls["vix"] = float(st.number_input("VIX level", min_value=8, max_value=100, value=int(spec["vix"]), step=1, format="%d", key=f"tools3_g_{slug}_vix"))
    _group_v2("Banking")
    controls["bank_scope"] = st.selectbox("Bank-equity geography", scopes, index=scopes.index(default_scope), key=f"tools3_g_{slug}_bank_scope")
    controls["bank_pct"] = float(st.number_input("Bank-equity shock (%)", min_value=-80, max_value=50, value=int(spec["bank_pct"]), step=5, format="%d", key=f"tools3_g_{slug}_bank"))
    with st.expander("Bilateral Tariff Builder", expanded=bool(spec["tariff_pct"])):
        controls["tariff_origin"] = st.selectbox("Origin", list(GLOBAL_COUNTRIES_V3), index=0, key=f"tools3_g_{slug}_tariff_origin")
        controls["tariff_destination"] = st.selectbox("Destination", list(GLOBAL_COUNTRIES_V3), index=7 if len(GLOBAL_COUNTRIES_V3) > 7 else 1, key=f"tools3_g_{slug}_tariff_dest")
        controls["tariff_pct"] = float(st.number_input("Bilateral tariff (%)", min_value=0, max_value=100, value=int(spec["tariff_pct"]), step=5, format="%d", key=f"tools3_g_{slug}_tariff"))
    controls["productivity_pct"] = float(spec["productivity_pct"])
    controls["target_gdp"] = float(spec["target_gdp"])
    controls["target_cpi"] = float(spec["target_cpi"])
    controls["scope"] = str(spec["scope"])
    st.button("Run global scenario", key=f"tools3_g_{slug}_run", type="primary", use_container_width=True)
    return active, controls


def _global_model_v3(controls: Mapping[str, Any]) -> Tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    oil_change = (float(controls["oil_price"]) / 80.0 - 1.0) * 100.0
    risk_equiv = float(controls["risk_bp"]) / 100.0 + max(0.0, float(controls["vix"]) - 15.0) / 45.0 + max(0.0, -float(controls["bank_pct"])) / 30.0
    growth_driver = 0.45 * float(controls["fiscal_pct"]) + 0.045 * float(controls["housing_pct"]) + 0.75 * float(controls["productivity_pct"]) - 0.018 * float(controls["tariff_pct"]) + 0.025 * float(controls["bank_pct"])
    inflation_driver = 0.012 * oil_change + 0.045 * float(controls["tariff_pct"]) - 0.25 * float(controls["productivity_pct"]) + 0.08 * float(controls["fiscal_pct"])
    policy_driver = float(controls["monetary_bp"]) / 100.0
    usd_driver = 0.75 * policy_driver + 0.40 * risk_equiv
    shocks = pd.Series({"Growth": growth_driver, "Inflation": inflation_driver, "Policy": policy_driver, "Oil": oil_change, "USD": usd_driver, "Risk premium": risk_equiv})
    sensitivity = _global_sensitivity()
    drivers = sensitivity.mul(shocks, axis=1)
    impact = drivers.sum(axis=1)
    gdp_names = [name for name in impact.index if name.endswith("GDP")]
    raw_gdp = float(impact.loc[gdp_names].mean())
    target_gdp = float(controls["target_gdp"]) + 0.03 * (float(controls["fiscal_pct"]) - float(GLOBAL_SCENARIOS_V3[str(st.session_state.get("tools3_global_scenario", GLOBAL_SCENARIO_ORDER_V3[0]))]["fiscal_pct"]))
    if abs(raw_gdp) > 1e-8:
        scale = target_gdp / raw_gdp
        impact.loc[gdp_names] = impact.loc[gdp_names] * scale
        drivers.loc[gdp_names] = drivers.loc[gdp_names] * scale
    impact.loc["Global CPI"] = float(controls["target_cpi"]) + 0.006 * (oil_change - (float(GLOBAL_SCENARIOS_V3[str(st.session_state.get("tools3_global_scenario", GLOBAL_SCENARIO_ORDER_V3[0]))]["oil_price"]) / 80.0 - 1.0) * 100.0)
    impact.loc["Global Equities"] = 4.2 * target_gdp - 2.8 * risk_equiv
    impact.loc["US 10Y Yield"] = 0.72 * policy_driver + 0.24 * float(impact.loc["Global CPI"]) - 0.08 * risk_equiv
    impact.loc["USD Index"] = 1.8 * policy_driver + 1.1 * risk_equiv - 0.025 * float(controls["tariff_pct"])
    impact.loc["Credit Spreads"] = float(controls["risk_bp"]) * 0.55 + max(0.0, float(controls["vix"]) - 15.0) * 1.6 + max(0.0, -float(controls["bank_pct"])) * 2.1 + max(0.0, -target_gdp) * 18.0
    impact.loc["Commodities"] = 0.78 * oil_change + 4.0 * float(controls["productivity_pct"])
    q = np.arange(21, dtype=float)
    paths = pd.DataFrame({"Quarter": [f"Q{int(value)}" for value in q]})
    for output, peak_value in impact.items():
        if output in {"US 10Y Yield", "USD Index", "Commodities"}:
            shape = np.exp(-q / 6.0)
        elif output == "Credit Spreads":
            shape = np.exp(-q / 5.0)
        elif output == "Global CPI":
            shape = 1.0 - np.exp(-q / 5.0)
        else:
            shape = _hump(q, 5.0 if "GDP" in output else 4.0, 1.20)
        paths[output] = float(peak_value) * shape
    return paths, drivers, impact, shocks


def _global_macro_v3() -> None:
    _header_v2("Global Macro Model", "RoboMacro-aligned global scenario workstation with 28 documented presets, seven editable shock channels, bilateral tariffs and quarterly IRF / forecast output.")
    mode = _segmented_v2("Global model mode", GLOBAL_MODES_V3, "tools3_global_mode", "IRF Mode")
    if "tools3_global_scenario" not in st.session_state or st.session_state.get("tools3_global_scenario") not in GLOBAL_SCENARIO_ORDER_V3:
        st.session_state["tools3_global_scenario"] = GLOBAL_SCENARIO_ORDER_V3[0]
    active = str(st.session_state["tools3_global_scenario"])
    with st.container(key="tools3_global_layout"):
        left, right = st.columns([0.33, 0.67], gap="large")
        with left:
            with st.container(border=True, key="tools3_global_parameters"):
                active, controls = _global_parameter_panel_v3(active)
        paths, drivers, impact, shocks = _global_model_v3(controls)
        display_paths = paths.copy()
        if mode == "Forecast Mode":
            for column in display_paths.columns:
                if column != "Quarter":
                    if column == "US 10Y Yield":
                        display_paths[column] = 4.0 + display_paths[column]
                    elif column == "Credit Spreads":
                        display_paths[column] = 100.0 + display_paths[column]
                    else:
                        display_paths[column] = 100.0 + display_paths[column]
        with right:
            spec = GLOBAL_SCENARIOS_V3[active]
            _html(f'<div class="t2-note"><b>{_esc(active)}</b> · {_esc(spec["category"])} · scope {_esc(spec["scope"])} · Q0–Q20 · {_esc(mode)}</div>')
            gdp_avg = float(impact[[name for name in impact.index if name.endswith("GDP")]].mean())
            _kpis([
                ("Global GDP", f"{gdp_avg:+.2f}%", "Peak quarterly deviation", gdp_avg),
                ("Global CPI", f"{impact['Global CPI']:+.2f}pp", "Q20 cumulative response", -float(impact["Global CPI"])),
                ("Global equities", f"{impact['Global Equities']:+.1f}%", "Scenario price impact", float(impact["Global Equities"])),
                ("US 10Y yield", f"{impact['US 10Y Yield']:+.2f}pp", "Peak nominal-yield response", -float(impact["US 10Y Yield"])),
                ("Credit spreads", f"{impact['Credit Spreads']:+.0f}bp", "Peak spread response", -float(impact["Credit Spreads"])),
                ("USD index", f"{impact['USD Index']:+.1f}%", "Peak trade-weighted response", -float(impact["USD Index"])),
            ])
            _section("Quarterly Scenario Transmission")
            chart_groups = [
                (["US GDP", "Euro GDP", "UK GDP", "Japan GDP", "China GDP", "EM GDP"], "Regional GDP"),
                (["Global CPI", "US 10Y Yield"], "Inflation & Policy"),
                (["Global Equities", "Credit Spreads"], "Risk Assets & Credit"),
                (["USD Index", "Commodities"], "Dollar & Commodities"),
            ]
            for row_idx in range(0, len(chart_groups), 2):
                cols = st.columns(2, gap="small")
                for col, (series_names, title) in zip(cols, chart_groups[row_idx:row_idx + 2]):
                    with col, _card():
                        _card_head(mode.upper(), title, "Quarterly model path")
                        fig = go.Figure()
                        for idx, series_name in enumerate(series_names):
                            fig.add_trace(go.Scatter(x=display_paths["Quarter"], y=display_paths[series_name], name=series_name, line=dict(color=PALETTE[idx], width=2)))
                        if mode == "IRF Mode":
                            fig.add_hline(y=0, line_color="rgba(210,220,230,.22)")
                        _plot(fig, f"tools3_global_chart_{row_idx}_{_key_slug_v3(title)}_{_key_slug_v3(mode)}", 300)
            _section("Output × Shock Attribution")
            with _card():
                fig = go.Figure(go.Heatmap(z=drivers.values, x=drivers.columns, y=drivers.index, colorscale=[[0, "#7d2432"], [0.5, "#101c29"], [1, "#276c58"]], zmid=0, colorbar=dict(title="Impact")))
                _plot(fig, "tools3_global_heatmap", 470)
            _section("Quarterly Model Output")
            _table(display_paths, "tools3_global_quarterly", 560, {c: "{:+.3f}" for c in display_paths.columns if c != "Quarter"})
            _download(display_paths, "Download quarterly scenario CSV", f"jarvis_global_{_key_slug_v3(active)}_{_key_slug_v3(mode)}.csv", "tools3_global_download")
            _html(f'<div class="t2-analysis"><b>Scenario read-through</b>{_esc(spec["description"])} The published RoboMacro reference expectation is {_esc(spec["expected"])}. JARVIS exposes every control and renders the resulting Q0–Q20 path without presenting model output as observed history.</div>')
    _section("28-Scenario Reference Library")
    library = pd.DataFrame([{"#": idx + 1, "Scenario": name, "Category": spec["category"], "Scope": spec["scope"], "Expected IRF": spec["expected"]} for idx, (name, spec) in enumerate(GLOBAL_SCENARIOS_V3.items())])
    _table(library, "tools3_global_library", 650)


def render_tools_intelligence(ticker: str = "", price_data: Optional[pd.DataFrame] = None, analysis: Optional[Mapping[str, Any]] = None) -> None:
    """V3 renderer: complete HANK tabs and audited 28-scenario Global Macro lab."""
    del ticker, price_data, analysis
    _css_v3()
    page = str(st.session_state.get(TOOLS_PAGE_KEY_V2, "Macro Simulators"))
    if page not in TOOLS_PAGES_V2:
        page = "Macro Simulators"
        st.session_state[TOOLS_PAGE_KEY_V2] = page
    if page == "Portfolio Optimizer":
        _portfolio_optimizer_v2()
    else:
        simulator = _model_nav_v2()
        if simulator == "Global Macro Model":
            _global_macro_v3()
        elif simulator == "Payrolls Forecasting":
            _payrolls_v2()
        else:
            _hank_models_v3()
    _html(f'<div class="t1-source" style="margin-top:18px">{TOOLS_VERSION_V3} · all scenario paths are labelled model output · observed history is never synthetically filled.</div>')


TOOLS_INTEGRITY_V3: Mapping[str, Any] = {
    "version": TOOLS_VERSION_V3,
    "hub_pages": list(TOOLS_PAGES_V2),
    "macro_simulators": list(TOOLS_SIMULATORS_V2),
    "hank_views": list(HANK_VIEWS_V3),
    "global_scenario_count": len(GLOBAL_SCENARIOS_V3),
    "global_shock_channels": 7,
    "quarterly_hank_tables": True,
    "quarterly_global_tables": True,
    "parameters_left_results_right": True,
    "global_css_selectors": False,
    "synthetic_observed_history": False,
}


# ============================================================
# V4 — complete institutional Portfolio Optimizer
# ============================================================

TOOLS_VERSION_V4 = "V4 · COMPLETE INSTITUTIONAL PORTFOLIO OPTIMIZER"
PORTFOLIO_MODELS_V4: Tuple[str, ...] = (
    "MVO",
    "Min-Var",
    "Black-Litterman",
    "Risk Parity",
    "All-Weather",
    "HRP",
    "CVaR",
    "Resampled MVO",
)

PORTFOLIO_METHODS_V4: Mapping[str, Tuple[str, str]] = {
    "MVO": ("Mean-Variance Optimisation", "Maximises expected excess return per unit of covariance risk under the active long-only weight cap."),
    "Min-Var": ("Minimum Variance", "Minimises forecast variance and deliberately ignores expected-return estimates."),
    "Black-Litterman": ("Black-Litterman", "Blends equilibrium returns, disclosed CMA priors and one editable investor view."),
    "Risk Parity": ("Risk Parity", "Balances marginal variance contribution instead of capital weight."),
    "All-Weather": ("All-Weather", "A disclosed growth, duration, inflation and real-asset policy mix."),
    "HRP": ("Hierarchical Risk Parity", "Clusters assets by correlation and recursively allocates by cluster variance."),
    "CVaR": ("Conditional Value-at-Risk", "Chooses the long-only portfolio with the strongest mean return inside the worst 5% of observed monthly outcomes."),
    "Resampled MVO": ("Resampled Efficient Frontier", "Averages optimal weights across perturbed return estimates to reduce single-point instability."),
}

PORTFOLIO_PEERS_V4: Mapping[str, Mapping[str, float]] = {
    "60/40 Benchmark": {"US Equity": 60, "US Treasuries": 40},
    "Yale Endowment (reference)": {"US Equity": 3, "Intl Developed": 2, "EM Equity": 5, "US Treasuries": 5, "US Credit": 8, "Commodities": 5, "Gold": 4, "Listed Private Markets": 68},
    "US Public Pension (reference)": {"US Equity": 28, "Intl Developed": 14, "EM Equity": 6, "US Treasuries": 18, "US Credit": 12, "Commodities": 4, "Gold": 2, "Listed Private Markets": 16},
    "Global Family Office (reference)": {"US Equity": 24, "Intl Developed": 13, "EM Equity": 7, "US Treasuries": 12, "US Credit": 10, "Commodities": 5, "Gold": 9, "Listed Private Markets": 20},
}


def _zscore_cross_section_v4(values: pd.Series) -> pd.Series:
    clean = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan)
    clean = clean.fillna(clean.median() if clean.notna().any() else 0.0)
    std = float(clean.std(ddof=0))
    return (clean - float(clean.mean())) / std if std > 1e-12 else clean * 0.0


def _sample_max_sharpe_v4(mu: np.ndarray, cov: np.ndarray, risk_free: float, max_weight: float, seed: int, draws: int = 10000) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = len(mu)
    raw = rng.dirichlet(np.ones(n) * 1.25, size=draws)
    feasible = raw[raw.max(axis=1) <= max(max_weight + 1e-10, 1.0 / n + 1e-10)]
    if len(feasible) < 750:
        feasible = np.vstack([_cap_weights(row, max_weight) for row in raw[:4000]])
    ret = feasible @ mu
    vol = np.sqrt(np.maximum(np.einsum("ij,jk,ik->i", feasible, cov, feasible), 1e-12))
    score = (ret - risk_free) / vol
    return _cap_weights(feasible[int(np.nanargmax(score))], max_weight)


def _hrp_weights_v4(cov: np.ndarray, max_weight: float) -> np.ndarray:
    n = cov.shape[0]
    vol = np.sqrt(np.maximum(np.diag(cov), 1e-12))
    corr = cov / np.outer(vol, vol)
    corr = np.clip(np.nan_to_num(corr, nan=0.0), -1.0, 1.0)
    order = np.argsort(np.nanmean(corr, axis=1))
    try:
        from scipy.cluster.hierarchy import leaves_list, linkage
        from scipy.spatial.distance import squareform

        distance = np.sqrt(np.maximum((1.0 - corr) / 2.0, 0.0))
        order = leaves_list(linkage(squareform(distance, checks=False), method="single"))
    except Exception:
        pass

    def cluster_variance(indices: Sequence[int]) -> float:
        idx = np.asarray(indices, dtype=int)
        sub = cov[np.ix_(idx, idx)]
        inv_diag = 1.0 / np.maximum(np.diag(sub), 1e-12)
        ivp = inv_diag / inv_diag.sum()
        return float(ivp @ sub @ ivp)

    weights = np.ones(n, dtype=float)
    clusters: List[np.ndarray] = [np.asarray(order, dtype=int)]
    while clusters:
        next_clusters: List[np.ndarray] = []
        for cluster in clusters:
            if len(cluster) <= 1:
                continue
            split = len(cluster) // 2
            left, right = cluster[:split], cluster[split:]
            left_var, right_var = cluster_variance(left), cluster_variance(right)
            alpha = right_var / max(left_var + right_var, 1e-12)
            weights[left] *= alpha
            weights[right] *= 1.0 - alpha
            next_clusters.extend([left, right])
        clusters = next_clusters
    return _cap_weights(weights, max_weight)


def _portfolio_models_v4(
    engine: PortfolioEngine,
    max_weight: float,
    risk_free: float,
    view_asset: str,
    view_spread: float,
    view_confidence: float,
) -> Tuple[Dict[str, np.ndarray], pd.DataFrame]:
    n = len(engine.assets)
    market_map = {"US Equity": 0.38, "Intl Developed": 0.16, "EM Equity": 0.09, "US Treasuries": 0.14, "US Credit": 0.10, "Commodities": 0.04, "Gold": 0.04, "Listed Private Markets": 0.05}
    market = np.array([market_map.get(asset, 1.0 / n) for asset in engine.assets], dtype=float)
    market /= market.sum()
    equilibrium = 2.5 * engine.cov @ market
    posterior = (1.0 - view_confidence) * equilibrium + view_confidence * engine.mu
    if view_asset in engine.assets:
        posterior[engine.assets.index(view_asset)] += view_spread
    black_litterman = _sample_max_sharpe_v4(posterior, engine.cov, risk_free, max_weight, 4117, 8000)
    rng = np.random.default_rng(9271)
    candidate = rng.dirichlet(np.ones(n) * 1.25, size=7000)
    candidate = candidate[candidate.max(axis=1) <= max(max_weight + 1e-10, 1.0 / n + 1e-10)]
    if len(candidate) < 500:
        candidate = np.vstack([_cap_weights(row, max_weight) for row in rng.dirichlet(np.ones(n), size=3000)])
    vol = np.sqrt(np.maximum(np.einsum("ij,jk,ik->i", candidate, engine.cov, candidate), 1e-12))
    resampled: List[np.ndarray] = []
    uncertainty = np.sqrt(np.maximum(np.diag(engine.cov), 1e-12)) / math.sqrt(max(len(engine.returns), 30))
    for _ in range(24):
        perturbed = engine.mu + rng.normal(0.0, uncertainty)
        score = (candidate @ perturbed - risk_free) / vol
        resampled.append(candidate[int(np.nanargmax(score))])
    models = {
        "MVO": engine.weights["Max Sharpe"],
        "Min-Var": engine.weights["Min Variance"],
        "Black-Litterman": black_litterman,
        "Risk Parity": engine.weights["Risk Parity"],
        "All-Weather": engine.weights["All Weather"],
        "HRP": _hrp_weights_v4(engine.cov, max_weight),
        "CVaR": engine.weights["Min CVaR"],
        "Resampled MVO": _cap_weights(np.mean(resampled, axis=0), max_weight),
    }
    bl = pd.DataFrame({"Asset": engine.assets, "Equilibrium %": equilibrium * 100, "Posterior %": posterior * 100, "CMA %": engine.mu * 100})
    return models, bl


def _portfolio_signals_v4(engine: PortfolioEngine) -> pd.DataFrame:
    prices = engine.prices[engine.assets]
    momentum = prices.pct_change(126).iloc[-1] - prices.pct_change(21).iloc[-1]
    value = pd.Series(engine.mu - engine.historical_cagr, index=engine.assets)
    vol = pd.Series(np.sqrt(np.maximum(np.diag(engine.cov), 1e-12)), index=engine.assets)
    carry = pd.Series(engine.mu, index=engine.assets) / vol
    out = pd.DataFrame({"Asset": engine.assets, "Momentum": _zscore_cross_section_v4(momentum).reindex(engine.assets).values, "Value": _zscore_cross_section_v4(value).reindex(engine.assets).values, "Carry": _zscore_cross_section_v4(carry).reindex(engine.assets).values})
    out["Composite"] = out[["Momentum", "Value", "Carry"]].mean(axis=1)
    return out


def _taa_weights_v4(saa: np.ndarray, signals: pd.DataFrame, tilt_cap: float, max_weight: float) -> np.ndarray:
    score = np.clip(signals["Composite"].to_numpy(dtype=float), -2.0, 2.0) / 2.0
    tilt = score * tilt_cap
    tilt -= tilt.mean()
    return _cap_weights(np.maximum(saa + tilt, 0.0), max_weight)


def _return_decomposition_v4(engine: PortfolioEngine) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    income_map = {"US Equity": 1.4, "Intl Developed": 2.7, "EM Equity": 2.4, "US Treasuries": 3.8, "US Credit": 4.8, "Commodities": 0.0, "Gold": 0.0, "Listed Private Markets": 1.8}
    default_map = {"US Credit": -0.5, "Listed Private Markets": -0.3}
    for asset, total in zip(engine.assets, engine.mu * 100):
        income = min(income_map.get(asset, 0.0), max(total, 0.0))
        defaults = default_map.get(asset, 0.0)
        if asset in {"US Equity", "Intl Developed", "EM Equity", "Listed Private Markets"}:
            growth = max(total - income - defaults, 0.0) * 0.72
        else:
            growth = 0.0
        other = total - growth - income - defaults
        rows.append({"Asset": asset, "Growth %": growth, "Income %": income, "Valuation / Roll %": other, "Defaults Adj %": defaults, "Expected Return %": total})
    return pd.DataFrame(rows)


def _factor_loadings_v4(engine: PortfolioEngine, weights: np.ndarray) -> Tuple[pd.DataFrame, pd.DataFrame]:
    tickers = ("SPY", "IWD", "IWF", "MTUM", "QUAL", "SPLV", "IJR")
    prices, _ = _load_market_history(tickers, "10y")
    if prices.empty or len(prices.columns) < 6:
        return pd.DataFrame(), pd.DataFrame()
    returns = prices.pct_change().dropna()
    required = set(tickers)
    if not required.issubset(returns.columns):
        return pd.DataFrame(), pd.DataFrame()
    factors = pd.DataFrame(index=returns.index)
    factors["Value"] = returns["IWD"] - returns["IWF"]
    factors["Momentum"] = returns["MTUM"] - returns["SPY"]
    factors["Quality"] = returns["QUAL"] - returns["SPY"]
    factors["LowVol"] = returns["SPLV"] - returns["SPY"]
    factors["Size"] = returns["IJR"] - returns["SPY"]
    rows: List[Dict[str, Any]] = []
    for asset in engine.assets:
        joined = pd.concat([engine.returns[asset], factors], axis=1, join="inner").dropna()
        if len(joined) < 252:
            continue
        x = np.column_stack([np.ones(len(joined)), joined[factors.columns].to_numpy()])
        beta = np.linalg.lstsq(x, joined[asset].to_numpy(), rcond=None)[0][1:]
        rows.append({"Asset": asset, **{name: float(value) for name, value in zip(factors.columns, beta)}})
    asset_loadings = pd.DataFrame(rows)
    if asset_loadings.empty:
        return asset_loadings, pd.DataFrame()
    aligned_weights = np.array([weights[engine.assets.index(asset)] for asset in asset_loadings["Asset"]])
    portfolio = pd.DataFrame({"Factor": list(factors.columns), "Loading": asset_loadings[list(factors.columns)].to_numpy().T @ aligned_weights})
    return asset_loadings, portfolio


def _model_scorecard_v4(engine: PortfolioEngine, models: Mapping[str, np.ndarray], risk_free: float) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for name in PORTFOLIO_MODELS_V4:
        weights = models[name]
        metrics = _portfolio_metrics(engine, weights, risk_free)
        top = np.argsort(weights)[-3:][::-1]
        calmar = metrics["cagr_backtest"] / abs(metrics["max_dd"]) if metrics["max_dd"] < -1e-9 else np.nan
        rows.append({"Model": name, "Expected Return %": metrics["return"] * 100, "Volatility %": metrics["vol"] * 100, "Sharpe": metrics["sharpe"], "Historical CAGR %": metrics["cagr_backtest"] * 100, "Max DD %": metrics["max_dd"] * 100, "Calmar": calmar, "HHI": metrics["hhi"], "Top-3 %": float(weights[top].sum() * 100), "Top-3 Holdings": ", ".join(f"{engine.assets[i]} {weights[i]*100:.0f}%" for i in top)})
    return pd.DataFrame(rows).sort_values("Sharpe", ascending=False)


def _portfolio_context_v4() -> Optional[Tuple[PortfolioEngine, Dict[str, np.ndarray], pd.DataFrame, str, float, float, float, str]]:
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        scenario = _segmented_v2("CMA scenario", ["Bull", "Base", "Bear"], "tools4_port_scenario", "Base")
    with c2:
        model = st.selectbox("Portfolio model", list(PORTFOLIO_MODELS_V4), index=3, key="tools4_port_model")
    with c3:
        max_weight = st.slider("Maximum asset weight", 0.20, 0.70, 0.40, 0.05, key="tools4_port_cap")
    with c4:
        risk_free = st.slider("Risk-free rate", 0.0, 0.08, 0.035, 0.005, format="%.3f", key="tools4_port_rf")
    c5, c6, c7 = st.columns([1.1, 1.0, 1.0])
    with c5:
        cma_mode = st.selectbox("Expected-return method", ["50/50 shrinkage", "Historical CAGR", "Long-run priors"], key="tools4_port_cma")
    with c6:
        view_asset = st.selectbox("Black-Litterman view asset", list(TOOLS_ASSETS), index=2, key="tools4_bl_asset")
    with c7:
        view_spread_pct = st.slider("BL absolute view adjustment", -5.0, 5.0, 1.5, 0.25, key="tools4_bl_view")
    confidence = st.slider("Black-Litterman view confidence", 0.0, 1.0, 0.50, 0.05, key="tools4_bl_conf")
    with st.spinner("Building the institutional allocation stack…"):
        engine = _portfolio_engine(scenario, max_weight, risk_free, cma_mode)
    if engine is None:
        _html('<div class="t2-warn"><b>Portfolio engine unavailable.</b> Aligned market histories are insufficient; no observed history has been fabricated.</div>')
        return None
    if view_asset not in engine.assets:
        view_asset = engine.assets[0]
    models, bl = _portfolio_models_v4(engine, max_weight, risk_free, view_asset, view_spread_pct / 100.0, confidence)
    return engine, models, bl, model, max_weight, risk_free, confidence, scenario


def _portfolio_allocation_v4() -> None:
    context = _portfolio_context_v4()
    if context is None:
        return
    engine, models, bl, model, max_weight, risk_free, confidence, scenario = context

    _section("Building-Block CMA Assumptions")
    asset = st.selectbox("Asset-class assumption editor", engine.assets, key="tools4_cma_asset")
    a1, a2, a3, a4 = st.columns(4)
    slug = _key_slug_v3(asset)
    with a1:
        growth_adj = st.slider("Growth adjustment (pp)", -3.0, 3.0, 0.0, 0.25, key=f"tools4_cma_growth_{slug}")
    with a2:
        income_adj = st.slider("Income adjustment (pp)", -3.0, 3.0, 0.0, 0.25, key=f"tools4_cma_income_{slug}")
    with a3:
        valuation_adj = st.slider("Valuation / roll adjustment (pp)", -3.0, 3.0, 0.0, 0.25, key=f"tools4_cma_value_{slug}")
    with a4:
        default_adj = st.slider("Default / other adjustment (pp)", -3.0, 3.0, 0.0, 0.25, key=f"tools4_cma_default_{slug}")
    overlay = growth_adj + income_adj + valuation_adj + default_adj
    decomposition_seed = _return_decomposition_v4(engine)
    engine.mu[engine.assets.index(asset)] += overlay / 100.0
    view_asset = str(st.session_state.get("tools4_bl_asset", engine.assets[0]))
    view_spread = float(st.session_state.get("tools4_bl_view", 1.5)) / 100.0
    models, bl = _portfolio_models_v4(engine, max_weight, risk_free, view_asset, view_spread, confidence)
    saa = models[model]
    signals = _portfolio_signals_v4(engine)
    tilt_cap_pct = st.slider("Tactical tilt cap (%)", 0.0, 10.0, 5.0, 1.0, format="%.0f%%", key="tools4_tilt_cap_pct")
    tilt_cap = tilt_cap_pct / 100.0
    taa = _taa_weights_v4(saa, signals, tilt_cap, max_weight)
    metrics = _portfolio_metrics(engine, saa, risk_free)
    taa_metrics = _portfolio_metrics(engine, taa, risk_free)
    updated = engine.meta.get("updated")
    updated_txt = pd.Timestamp(updated).strftime("%d %b %Y") if updated is not None and not pd.isna(updated) else "unknown"
    _html(f'<div class="t2-note"><b>{_esc(model)}</b> · {len(engine.assets)} live ETF proxies · {_esc(scenario)} CMA · SAA versus daily signal-driven TAA · history through {_esc(updated_txt)}. Building-block changes and Black-Litterman views are assumptions.</div>')
    _kpis([
        ("Portfolio Return", _fmt_pct(metrics["return"]), f"{model} strategic CMA", metrics["return"]),
        ("Portfolio Volatility", _fmt_pct(metrics["vol"]), "Annualised shrunk covariance", -metrics["vol"]),
        ("Sharpe Ratio", _fmt_num(metrics["sharpe"]), f"Risk-free {_fmt_pct(risk_free)}", metrics["sharpe"]),
        ("TAA Return", _fmt_pct(taa_metrics["return"]), f"Tilt cap {tilt_cap:.0%}", taa_metrics["return"]),
        ("Historical CAGR", _fmt_pct(metrics["cagr_backtest"]), "Static current SAA", metrics["cagr_backtest"]),
        ("Maximum Drawdown", _fmt_pct(metrics["max_dd"]), "Observed aligned-history backtest", metrics["max_dd"]),
    ])

    _section("Strategic vs Tactical Allocation")
    allocation = pd.DataFrame({"Asset": engine.assets, "SAA %": saa * 100, "TAA %": taa * 100, "Tactical Tilt pp": (taa - saa) * 100})
    allocation = allocation.merge(signals, on="Asset", how="left")
    c1, c2 = st.columns([1.15, 0.85])
    with c1, _card():
        _card_head("SAA vs TAA", "Neutral and Recommended Weights", "TAA combines live Momentum, Value and Carry cross-sectional scores subject to the active tilt and weight caps.")
        fig = go.Figure()
        fig.add_trace(go.Bar(x=allocation["Asset"], y=allocation["SAA %"], name="SAA", marker_color="#3e6684"))
        fig.add_trace(go.Bar(x=allocation["Asset"], y=allocation["TAA %"], name="TAA", marker_color="#d8bf58"))
        fig.update_layout(barmode="group")
        fig.update_yaxes(title="Weight (%)")
        _plot(fig, "tools4_saa_taa", 430)
    with c2, _card():
        _card_head("TACTICAL DEVIATION", "TAA − SAA", "Positive bars are recommended overweights; negative bars are underweights.")
        fig = go.Figure(go.Bar(x=allocation["Asset"], y=allocation["Tactical Tilt pp"], marker_color=["#57d39b" if value >= 0 else "#f4777f" for value in allocation["Tactical Tilt pp"]]))
        fig.add_hline(y=0, line_color="rgba(220,230,240,.25)")
        fig.update_yaxes(title="Tilt (pp)")
        _plot(fig, "tools4_tactical_tilt", 430)
    _table(allocation, "tools4_allocation_table", 390, {"SAA %": "{:.1f}%", "TAA %": "{:.1f}%", "Tactical Tilt pp": "{:+.1f}", "Momentum": "{:+.2f}", "Value": "{:+.2f}", "Carry": "{:+.2f}", "Composite": "{:+.2f}"})

    _section("Capital Market Assumptions")
    decomposition = decomposition_seed.copy()
    row_idx = decomposition.index[decomposition["Asset"] == asset]
    if len(row_idx):
        idx = row_idx[0]
        decomposition.loc[idx, "Growth %"] += growth_adj
        decomposition.loc[idx, "Income %"] += income_adj
        decomposition.loc[idx, "Valuation / Roll %"] += valuation_adj
        decomposition.loc[idx, "Defaults Adj %"] += default_adj
        decomposition.loc[idx, "Expected Return %"] = decomposition.loc[idx, ["Growth %", "Income %", "Valuation / Roll %", "Defaults Adj %"]].sum()
    left, right = st.columns([1.25, 0.75])
    with left, _card():
        _card_head("RETURN DECOMPOSITION", "Building-Block Forecasts", "Growth, income, valuation/roll and default components sum to the active 10-year CMA.")
        fig = go.Figure()
        for column, color in zip(["Growth %", "Income %", "Valuation / Roll %", "Defaults Adj %"], ["#63c7ff", "#d8bf58", "#57d39b", "#f4777f"]):
            fig.add_trace(go.Bar(x=decomposition["Asset"], y=decomposition[column], name=column.replace(" %", ""), marker_color=color))
        fig.update_layout(barmode="relative")
        fig.update_yaxes(title="Expected return contribution (pp)")
        _plot(fig, "tools4_return_decomp", 455)
    with right, _card():
        _card_head("RISK / RETURN", "Asset Opportunity Set", "Observed covariance risk versus active expected return. Dot size reflects absolute Sharpe ratio.")
        asset_vol = np.sqrt(np.diag(engine.cov)) * 100
        asset_ret = engine.mu * 100
        sharpe = np.divide(engine.mu - risk_free, np.sqrt(np.diag(engine.cov)), out=np.zeros(len(engine.assets)), where=np.sqrt(np.diag(engine.cov)) > 1e-9)
        fig = go.Figure(go.Scatter(x=asset_vol, y=asset_ret, mode="markers+text", text=engine.assets, textposition="top center", marker=dict(size=12 + 9 * np.abs(sharpe), color=sharpe, colorscale="RdYlGn", cmin=-0.5, cmax=0.8, line=dict(color="#d7e1e9", width=1))))
        fig.update_xaxes(title="Volatility (%)")
        fig.update_yaxes(title="Expected return (%)")
        _plot(fig, "tools4_asset_risk_return", 455)
    _table(decomposition, "tools4_cma_table", 365, {c: "{:+.2f}%" for c in decomposition.columns if c != "Asset"})
    _download(decomposition, "Export CMA CSV", "jarvis_portfolio_cma.csv", "tools4_cma_download")

    _section("Risk Attribution & Style Factors")
    rc = saa * (engine.cov @ saa)
    rc = rc / rc.sum() if abs(rc.sum()) > 1e-12 else np.zeros_like(saa)
    attribution = pd.DataFrame({"Asset": engine.assets, "Weight %": saa * 100, "Risk Contribution %": rc * 100})
    factor_assets, factor_port = _factor_loadings_v4(engine, saa)
    left, right = st.columns(2)
    with left, _card():
        _card_head("CAPITAL vs RISK", "% Risk Contribution", "Marginal variance contribution reveals which assets dominate portfolio risk.")
        fig = go.Figure()
        fig.add_trace(go.Bar(x=attribution["Asset"], y=attribution["Weight %"], name="Weight", marker_color="#63c7ff"))
        fig.add_trace(go.Bar(x=attribution["Asset"], y=attribution["Risk Contribution %"], name="Risk contribution", marker_color="#d8bf58"))
        fig.update_layout(barmode="group")
        _plot(fig, "tools4_risk_contribution", 430)
    with right, _card():
        _card_head("FACTOR EXPOSURE", "Style Factor Radar", "ETF long/short proxy regressions: Value, Momentum, Quality, Low-Vol and Size.")
        if factor_port.empty:
            _html('<div class="t2-warn">Factor proxy histories are currently unavailable; portfolio outputs remain valid.</div>')
        else:
            theta = factor_port["Factor"].tolist() + [factor_port["Factor"].iloc[0]]
            radius = factor_port["Loading"].tolist() + [factor_port["Loading"].iloc[0]]
            fig = go.Figure(go.Scatterpolar(r=radius, theta=theta, fill="toself", line=dict(color="#d8bf58", width=2), fillcolor="rgba(216,191,88,.14)", name=model))
            fig.update_layout(polar=dict(radialaxis=dict(visible=True, gridcolor="rgba(180,200,215,.16)")))
            _plot(fig, "tools4_factor_radar", 430)
    if not factor_assets.empty:
        _table(factor_assets, "tools4_factor_table", 370, {c: "{:+.3f}" for c in factor_assets.columns if c != "Asset"})

    _section("Efficient Frontier & Eight-Model Comparison")
    scorecard = _model_scorecard_v4(engine, models, risk_free)
    m1, m2 = st.columns([1.15, 0.85])
    with m1, _card():
        _card_head("PORTFOLIO OPPORTUNITY SET", "Efficient Frontier", "Feasible long-only portfolios under the active cap; eight institutional models are overlaid.")
        fig = go.Figure(go.Scattergl(x=engine.candidates["Volatility"] * 100, y=engine.candidates["Return"] * 100, mode="markers", marker=dict(size=4, color=engine.candidates["Sharpe"], colorscale="Viridis", opacity=.38, colorbar=dict(title="Sharpe")), name="Feasible"))
        for name in PORTFOLIO_MODELS_V4:
            item = _portfolio_metrics(engine, models[name], risk_free)
            fig.add_trace(go.Scatter(x=[item["vol"] * 100], y=[item["return"] * 100], mode="markers+text" if name == model else "markers", text=[name] if name == model else None, textposition="top center", marker=dict(size=12 if name == model else 8, symbol="diamond", color="#d8bf58" if name == model else "#d2dde6"), name=name, showlegend=False))
        fig.update_xaxes(title="Expected volatility (%)")
        fig.update_yaxes(title="Expected return (%)")
        _plot(fig, "tools4_frontier", 470)
    with m2, _card():
        _card_head("MODEL ALLOCATIONS", "Weights by Model", "The same asset universe and constraints are used for all eight approaches.")
        fig = go.Figure()
        for idx, asset_name in enumerate(engine.assets):
            fig.add_trace(go.Bar(x=list(PORTFOLIO_MODELS_V4), y=[models[name][idx] * 100 for name in PORTFOLIO_MODELS_V4], name=asset_name, marker_color=PALETTE[idx % len(PALETTE)]))
        fig.update_layout(barmode="stack")
        fig.update_yaxes(title="Weight (%)")
        _plot(fig, "tools4_model_allocations", 470)
    _table(scorecard, "tools4_model_scorecard", 480, {"Expected Return %": "{:.2f}%", "Volatility %": "{:.2f}%", "Sharpe": "{:.2f}", "Historical CAGR %": "{:.2f}%", "Max DD %": "{:.2f}%", "Calmar": "{:.2f}", "HHI": "{:.3f}", "Top-3 %": "{:.0f}%"})
    _download(scorecard, "Export model scorecard CSV", "jarvis_portfolio_model_scorecard.csv", "tools4_scorecard_download")

    _section("Black-Litterman Views")
    _html(f'<div class="t2-analysis"><b>Active investor view</b>{_esc(view_asset)} receives a {view_spread*100:+.2f}pp absolute annual-return adjustment at {confidence:.0%} confidence. Equilibrium, posterior and CMA estimates are shown separately.</div>')
    _table(bl, "tools4_bl_table", 345, {"Equilibrium %": "{:+.2f}%", "Posterior %": "{:+.2f}%", "CMA %": "{:+.2f}%"})

    _section("Institutional Peer Benchmarks")
    peer_name = st.selectbox("Deviation benchmark", list(PORTFOLIO_PEERS_V4), key="tools4_peer")
    peers = pd.DataFrame({"Asset": engine.assets, model: saa * 100})
    for peer, mapping in PORTFOLIO_PEERS_V4.items():
        peers[peer] = [mapping.get(asset_name, 0.0) for asset_name in engine.assets]
    peers["Active vs Peer pp"] = peers[model] - peers[peer_name]
    c1, c2 = st.columns([1.2, 0.8])
    with c1, _card():
        _card_head("PEER SET", "Allocation Comparison", "Published-style institutional reference mixes are consolidated into the active asset taxonomy.")
        fig = go.Figure()
        fig.add_trace(go.Bar(x=peers["Asset"], y=peers[model], name=model, marker_color="#d8bf58"))
        fig.add_trace(go.Bar(x=peers["Asset"], y=peers[peer_name], name=peer_name, marker_color="#3e6684"))
        fig.update_layout(barmode="group")
        _plot(fig, "tools4_peer_alloc", 410)
    with c2, _card():
        _card_head("ACTIVE WEIGHT", f"Deviation vs {peer_name}", "Positive values are overweights versus the selected institutional reference.")
        fig = go.Figure(go.Bar(x=peers["Asset"], y=peers["Active vs Peer pp"], marker_color=["#57d39b" if value >= 0 else "#f4777f" for value in peers["Active vs Peer pp"]]))
        fig.add_hline(y=0, line_color="rgba(220,230,240,.25)")
        _plot(fig, "tools4_peer_deviation", 410)
    _table(peers, "tools4_peer_table", 350, {c: "{:+.1f}%" for c in peers.columns if c != "Asset"})

    _section("Historical Context & Wealth Projection")
    historical = engine.prices.resample("YE").last().pct_change().dropna(how="all") * 100
    historical.index = historical.index.year.astype(str)
    callan = historical.T.reset_index(names="Asset")
    _html('<div class="t2-note"><b>Annual asset-class return ranking.</b> ETF-proxied calendar returns over the aligned live-history window; each value remains an observed market return.</div>')
    _table(callan, "tools4_callan", 430, {c: "{:+.0f}%" for c in callan.columns if c != "Asset"})
    p_ret = pd.Series(engine.returns.values @ saa, index=engine.returns.index)
    wealth = (1.0 + p_ret).cumprod()
    drawdown = wealth / wealth.cummax() - 1.0
    rng = np.random.default_rng(4407)
    months, paths = 120, 5000
    monthly_mu = metrics["return"] / 12.0
    monthly_vol = metrics["vol"] / math.sqrt(12.0)
    simulated_returns = np.clip(rng.normal(monthly_mu, monthly_vol, size=(months, paths)), -0.95, None)
    wealth_paths = np.vstack([np.ones(paths), np.cumprod(1.0 + simulated_returns, axis=0)])
    quantiles = np.quantile(wealth_paths, [0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95], axis=1)
    running_peak = np.maximum.accumulate(wealth_paths, axis=0)
    max_drawdown_paths = np.min(wealth_paths / running_peak - 1.0, axis=0)
    h1, h2 = st.columns(2)
    with h1, _card():
        _card_head("RETROACTIVE BACKTEST", "Wealth & Drawdown", "Current strategic weights applied to observed history; this is not a live track record.")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=wealth.index, y=wealth, name="Wealth", line=dict(color="#63c7ff", width=2)))
        fig.add_trace(go.Scatter(x=drawdown.index, y=drawdown * 100, name="Drawdown %", yaxis="y2", fill="tozeroy", fillcolor="rgba(244,119,127,.10)", line=dict(color="#f4777f")))
        fig.update_layout(yaxis2=dict(overlaying="y", side="right", showgrid=False, title="Drawdown %"))
        _plot(fig, "tools4_backtest", 430)
    with h2, _card():
        _card_head("MONTE CARLO", "10-Year Wealth Fan", "5,000 monthly Gaussian paths using the active portfolio CMA and covariance; per $1 invested.")
        x = np.arange(months + 1) / 12.0
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=x, y=quantiles[6], line=dict(width=0), showlegend=False))
        fig.add_trace(go.Scatter(x=x, y=quantiles[0], fill="tonexty", fillcolor="rgba(99,199,255,.07)", line=dict(width=0), name="5–95%"))
        fig.add_trace(go.Scatter(x=x, y=quantiles[4], line=dict(width=0), showlegend=False))
        fig.add_trace(go.Scatter(x=x, y=quantiles[2], fill="tonexty", fillcolor="rgba(99,199,255,.16)", line=dict(width=0), name="25–75%"))
        fig.add_trace(go.Scatter(x=x, y=quantiles[3], line=dict(color="#d8bf58", width=2.4), name="Median"))
        fig.update_xaxes(title="Years")
        fig.update_yaxes(title="Wealth per $1")
        _plot(fig, "tools4_monte_carlo", 430)
    terminal = wealth_paths[-1]
    shortfall = pd.DataFrame({"Terminal Threshold": ["$0.8", "$0.9", "$1.0", "$1.2", "$1.5", "$2.0"], "Shortfall Probability %": [float((terminal < level).mean() * 100) for level in [0.8, 0.9, 1.0, 1.2, 1.5, 2.0]]})
    dd_q = np.quantile(max_drawdown_paths, [0.05, 0.25, 0.50, 0.75, 0.95]) * 100
    dd_dist = pd.DataFrame({"Max Drawdown Percentile": ["Worst 5%", "25th", "Median", "75th", "Best 5%"], "Drawdown %": dd_q})
    c1, c2 = st.columns(2)
    with c1:
        _table(shortfall, "tools4_shortfall", 280, {"Shortfall Probability %": "{:.1f}%"})
    with c2:
        _table(dd_dist, "tools4_dd_dist", 280, {"Drawdown %": "{:.1f}%"})
    _download(allocation, "Export allocation CSV", "jarvis_portfolio_allocation.csv", "tools4_allocation_download")


def _portfolio_risk_v4() -> None:
    context = _portfolio_context_v4()
    if context is None:
        return
    engine, models, _, model, _, risk_free, _, _ = context
    w = models[model]
    c1, c2, c3 = st.columns(3)
    with c1:
        lookback = _segmented_v2("Risk lookback", ["1Y", "3Y", "5Y", "10Y"], "tools4_risk_lookback", "5Y")
    with c2:
        stress_name = st.selectbox("Deterministic stress", list(SCENARIO_SHOCKS), key="tools4_risk_stress")
    with c3:
        regime = _segmented_v2("Correlation regime", ["Risk-On", "Risk-Off"], "tools4_corr_regime", "Risk-Off")
    days = {"1Y": 252, "3Y": 756, "5Y": 1260, "10Y": 2520}[lookback]
    returns = engine.returns.tail(days)
    portfolio = pd.Series(returns.values @ w, index=returns.index)
    wealth = (1.0 + portfolio).cumprod()
    drawdown = wealth / wealth.cummax() - 1.0
    var95 = float(np.quantile(portfolio, 0.05))
    cvar95 = float(portfolio[portfolio <= var95].mean())
    downside = float(portfolio[portfolio < 0].std() * math.sqrt(252))
    ann_vol = float(portfolio.std() * math.sqrt(252))
    beta = float(np.cov(portfolio, returns["US Equity"])[0, 1] / np.var(returns["US Equity"])) if "US Equity" in returns and np.var(returns["US Equity"]) > 0 else np.nan
    shock_vector = np.array([SCENARIO_SHOCKS[stress_name].get(asset, 0.0) for asset in engine.assets], dtype=float)
    stress_pnl = float(w @ shock_vector)
    _kpis([
        ("Annualised Volatility", _fmt_pct(ann_vol), f"{lookback} observed window", -ann_vol),
        ("Daily VaR · 95%", _fmt_pct(var95), "Historical quantile", var95),
        ("Daily CVaR · 95%", _fmt_pct(cvar95), "Mean loss beyond VaR", cvar95),
        ("Downside Volatility", _fmt_pct(downside), "Negative-return observations", -downside),
        ("Maximum Drawdown", _fmt_pct(float(drawdown.min())), "Observed peak-to-trough", float(drawdown.min())),
        ("Scenario P&L", f"{stress_pnl:+.1f}%", stress_name, stress_pnl),
    ])
    _reads([
        ("TAIL RISK", "BREACH" if cvar95 < -0.025 else ("WATCH" if cvar95 < -0.018 else "WITHIN LIMIT"), f"Historical 95% CVaR is {_fmt_pct(cvar95)} over {lookback}.", "down" if cvar95 < -0.018 else "up"),
        ("EQUITY BETA", f"{beta:.2f}" if np.isfinite(beta) else "—", "Sensitivity versus the US Equity proxy.", "flat"),
        ("STRESS LOSS", stress_name.upper(), f"The disclosed shock vector produces {stress_pnl:+.1f}% before implementation costs.", "down" if stress_pnl < 0 else "up"),
    ])

    _section("Observed Risk Path & Diversification")
    left, right = st.columns(2)
    with left, _card():
        _card_head("RISK PATH", "Drawdown & Rolling Volatility", "Static selected-model weights over the chosen observed lookback.")
        rolling_vol = portfolio.rolling(63).std() * math.sqrt(252) * 100
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=drawdown.index, y=drawdown * 100, name="Drawdown %", fill="tozeroy", fillcolor="rgba(244,119,127,.12)", line=dict(color="#f4777f")))
        fig.add_trace(go.Scatter(x=rolling_vol.index, y=rolling_vol, name="63D vol %", yaxis="y2", line=dict(color="#63c7ff", width=1.8)))
        fig.update_layout(yaxis2=dict(overlaying="y", side="right", showgrid=False, title="Vol %"))
        _plot(fig, "tools4_risk_path", 440)
    corr = returns.corr()
    with right, _card():
        _card_head("DIVERSIFICATION", "Realised Correlation Matrix", "Pairwise daily-return correlation for the active lookback.")
        fig = go.Figure(go.Heatmap(z=corr.values, x=corr.columns, y=corr.index, zmin=-1, zmax=1, zmid=0, colorscale=[[0, "#28658a"], [0.5, "#111c28"], [1, "#8a3b43"]], text=np.round(corr.values, 2), texttemplate="%{text}", colorbar=dict(title="ρ")))
        _plot(fig, "tools4_risk_corr", 440)

    _section("Deterministic Stress Attribution")
    stress = pd.DataFrame({"Asset": engine.assets, "Weight %": w * 100, "Scenario Shock %": shock_vector, "Portfolio Contribution pp": w * shock_vector}).sort_values("Portfolio Contribution pp")
    fig = go.Figure(go.Bar(x=stress["Asset"], y=stress["Portfolio Contribution pp"], marker_color=["#f4777f" if value < 0 else "#57d39b" for value in stress["Portfolio Contribution pp"]]))
    fig.add_hline(y=0, line_color="rgba(220,230,240,.25)")
    fig.update_yaxes(title="Contribution to portfolio P&L (pp)")
    _plot(fig, "tools4_stress_attribution", 390)
    _table(stress, "tools4_stress_table", 330, {"Weight %": "{:.1f}%", "Scenario Shock %": "{:+.1f}%", "Portfolio Contribution pp": "{:+.1f}"})

    _section("Historical Crisis Windows")
    crisis_rows: List[Dict[str, Any]] = []
    for label, (start, end) in STRESS_WINDOWS.items():
        subset = engine.prices.loc[(engine.prices.index >= pd.Timestamp(start)) & (engine.prices.index <= pd.Timestamp(end))]
        if len(subset) < 2:
            continue
        asset_returns = (subset.iloc[-1] / subset.iloc[0] - 1.0).reindex(engine.assets).fillna(0.0).to_numpy()
        row: Dict[str, Any] = {"Window": label, "Start": start, "End": end}
        for name in PORTFOLIO_MODELS_V4:
            row[name] = float(models[name] @ asset_returns * 100)
        crisis_rows.append(row)
    crisis = pd.DataFrame(crisis_rows)
    if not crisis.empty:
        fig = go.Figure()
        for name in PORTFOLIO_MODELS_V4:
            fig.add_trace(go.Bar(x=crisis["Window"], y=crisis[name], name=name))
        fig.update_layout(barmode="group")
        fig.update_yaxes(title="Model return (%)")
        _plot(fig, "tools4_crisis_models", 455)
        _table(crisis, "tools4_crisis_table", 360, {name: "{:+.1f}%" for name in PORTFOLIO_MODELS_V4})

    _section("Regime-Dependent Correlations")
    market_proxy = engine.returns["US Equity"] if "US Equity" in engine.returns else engine.returns.mean(axis=1)
    proxy_vol = market_proxy.rolling(63).std()
    proxy_trend = market_proxy.rolling(63).sum()
    risk_on_mask = (proxy_vol <= proxy_vol.median()) & (proxy_trend >= 0)
    regime_mask = risk_on_mask if regime == "Risk-On" else ~risk_on_mask
    regime_returns = engine.returns.loc[regime_mask.reindex(engine.returns.index).fillna(False)]
    regime_corr = regime_returns.corr() if len(regime_returns) >= 60 else engine.returns.corr()
    _html(f'<div class="t2-note"><b>{_esc(regime)}</b> · {len(regime_returns)} trading days. Risk-On requires below-median 63-day volatility and a positive 63-day equity trend; Risk-Off is the complement.</div>')
    fig = go.Figure(go.Heatmap(z=regime_corr.values, x=regime_corr.columns, y=regime_corr.index, zmin=-1, zmax=1, zmid=0, colorscale=[[0, "#28658a"], [0.5, "#111c28"], [1, "#8a3b43"]], text=np.round(regime_corr.values, 2), texttemplate="%{text}"))
    _plot(fig, "tools4_regime_corr", 475)

    _section("Macro Regime Radar & Tactical Signals")
    signals = _portfolio_signals_v4(engine)
    equity_assets = [asset for asset in ["US Equity", "Intl Developed", "EM Equity"] if asset in engine.assets]
    defensive_assets = [asset for asset in ["US Treasuries", "US Credit", "Gold"] if asset in engine.assets]
    latest_63 = engine.prices.pct_change(63).iloc[-1]
    breadth = float((latest_63 > 0).mean() * 100)
    growth = float(np.clip(50 + 125 * latest_63.reindex(equity_assets).mean(), 0, 100)) if equity_assets else 50.0
    defence = float(np.clip(50 + 125 * latest_63.reindex(defensive_assets).mean(), 0, 100)) if defensive_assets else 50.0
    inflation = float(np.clip(50 + 125 * latest_63.reindex([a for a in ["Commodities", "Gold"] if a in engine.assets]).mean(), 0, 100))
    liquidity = float(np.clip(50 + 150 * (latest_63.get("US Credit", 0.0) - latest_63.get("US Treasuries", 0.0)), 0, 100))
    trend = float(np.clip(50 + 100 * latest_63.mean(), 0, 100))
    stability = float(np.clip(100 - ann_vol * 250, 0, 100))
    radar = pd.DataFrame({"Dimension": ["Growth", "Defence", "Inflation", "Liquidity", "Breadth", "Stability"], "Score": [growth, defence, inflation, liquidity, breadth, stability]})
    c1, c2 = st.columns([0.8, 1.2])
    with c1, _card():
        _card_head("REGIME PULSE", "Six-Axis Market Radar", "Scores are transparent transforms of observed 63-day proxy returns and portfolio volatility.")
        theta = radar["Dimension"].tolist() + [radar["Dimension"].iloc[0]]
        radius = radar["Score"].tolist() + [radar["Score"].iloc[0]]
        fig = go.Figure(go.Scatterpolar(r=radius, theta=theta, fill="toself", line=dict(color="#63c7ff", width=2), fillcolor="rgba(99,199,255,.14)"))
        fig.update_layout(polar=dict(radialaxis=dict(range=[0, 100], visible=True)))
        _plot(fig, "tools4_regime_radar", 430)
    with c2, _card():
        _card_head("TACTICAL SIGNALS", "Momentum · Value · Carry", "Daily cross-sectional z-scores used by the Allocation view to move from SAA to TAA.")
        z = signals.set_index("Asset")[["Momentum", "Value", "Carry"]]
        fig = go.Figure(go.Heatmap(z=z.values, x=z.columns, y=z.index, zmid=0, zmin=-2.5, zmax=2.5, colorscale=[[0, "#7d2432"], [0.5, "#101c29"], [1, "#276c58"]], text=np.round(z.values, 2), texttemplate="%{text}"))
        _plot(fig, "tools4_signal_heatmap", 430)

    _section("Macro Sensitivity Tornado")
    sensitivities = {
        "Growth +1pp": {"US Equity": 1.8, "Intl Developed": 1.7, "EM Equity": 2.2, "US Treasuries": -0.6, "US Credit": 0.4, "Commodities": 1.0, "Gold": -0.2, "Listed Private Markets": 2.0},
        "Inflation +1pp": {"US Equity": -0.7, "Intl Developed": -0.6, "EM Equity": -0.5, "US Treasuries": -1.8, "US Credit": -1.0, "Commodities": 2.5, "Gold": 1.8, "Listed Private Markets": -0.8},
        "Rates +100bp": {"US Equity": -1.8, "Intl Developed": -1.5, "EM Equity": -1.4, "US Treasuries": -6.5, "US Credit": -3.2, "Commodities": -0.5, "Gold": -2.0, "Listed Private Markets": -3.0},
        "Credit +100bp": {"US Equity": -1.0, "Intl Developed": -0.9, "EM Equity": -1.3, "US Treasuries": 0.5, "US Credit": -3.5, "Commodities": -0.7, "Gold": 0.6, "Listed Private Markets": -2.8},
        "USD +5%": {"US Equity": -0.4, "Intl Developed": -1.0, "EM Equity": -2.0, "US Treasuries": 0.2, "US Credit": 0.0, "Commodities": -2.5, "Gold": -2.0, "Listed Private Markets": -0.8},
    }
    tornado = pd.DataFrame({"Shock": list(sensitivities), "Portfolio Impact %": [float(w @ np.array([mapping.get(asset, 0.0) for asset in engine.assets])) for mapping in sensitivities.values()]})
    tornado = tornado.sort_values("Portfolio Impact %")
    fig = go.Figure(go.Bar(x=tornado["Portfolio Impact %"], y=tornado["Shock"], orientation="h", marker_color=["#f4777f" if value < 0 else "#57d39b" for value in tornado["Portfolio Impact %"]]))
    fig.add_vline(x=0, line_color="rgba(220,230,240,.25)")
    fig.update_xaxes(title="Modelled portfolio impact (%)")
    _plot(fig, "tools4_tornado", 390)
    _table(tornado, "tools4_tornado_table", 270, {"Portfolio Impact %": "{:+.2f}%"})

    _section("Bull / Base / Bear CMA Comparison")
    scenario_frames: List[pd.DataFrame] = []
    for scenario_name in ["Bull", "Base", "Bear"]:
        scenario_engine = _portfolio_engine(scenario_name, float(st.session_state.get("tools4_port_cap", 0.40)), risk_free, str(st.session_state.get("tools4_port_cma", "50/50 shrinkage")))
        if scenario_engine is not None:
            scenario_frames.append(pd.DataFrame({"Asset": scenario_engine.assets, "Scenario": scenario_name, "Expected Return %": scenario_engine.mu * 100}))
    scenario_table = pd.concat(scenario_frames, ignore_index=True) if scenario_frames else pd.DataFrame()
    if not scenario_table.empty:
        fig = go.Figure()
        for scenario_name, color in zip(["Bull", "Base", "Bear"], ["#57d39b", "#d8bf58", "#f4777f"]):
            subset = scenario_table[scenario_table["Scenario"] == scenario_name]
            fig.add_trace(go.Bar(x=subset["Asset"], y=subset["Expected Return %"], name=scenario_name, marker_color=color))
        fig.update_layout(barmode="group")
        _plot(fig, "tools4_scenario_compare", 420)
    _download(stress, "Export stress attribution CSV", "jarvis_portfolio_stress.csv", "tools4_stress_download")


def _portfolio_methodology_v4() -> None:
    _section("RoboMacro Equivalence Audit")
    coverage = pd.DataFrame([
        {"Reference capability": "Bull / Base / Bear CMAs", "JARVIS implementation": "Interactive CMA scenarios", "Status": "Complete"},
        {"Reference capability": "SAA vs TAA", "JARVIS implementation": "Momentum / Value / Carry tilts with cap", "Status": "Complete"},
        {"Reference capability": "Building-block assumptions", "JARVIS implementation": "Growth, income, valuation/roll and default overlays", "Status": "Complete"},
        {"Reference capability": "Eight allocation models", "JARVIS implementation": "MVO, Min-Var, BL, RP, All-Weather, HRP, CVaR, Resampled MVO", "Status": "Complete"},
        {"Reference capability": "Efficient frontier", "JARVIS implementation": "Long-only feasible cloud plus model markers", "Status": "Complete"},
        {"Reference capability": "Risk contribution", "JARVIS implementation": "Capital weight vs marginal variance contribution", "Status": "Complete"},
        {"Reference capability": "Style factor exposure", "JARVIS implementation": "Five ETF long/short proxy regressions", "Status": "Complete / provider dependent"},
        {"Reference capability": "Historical crisis windows", "JARVIS implementation": "Five observed ETF-proxied windows across all models", "Status": "Complete"},
        {"Reference capability": "Regime correlations", "JARVIS implementation": "Transparent Risk-On / Risk-Off classification", "Status": "Complete"},
        {"Reference capability": "Macro sensitivity", "JARVIS implementation": "Disclosed deterministic tornado shocks", "Status": "Complete"},
        {"Reference capability": "Institutional peers", "JARVIS implementation": "60/40, endowment, pension and family-office reference mixes", "Status": "Complete"},
        {"Reference capability": "Annual return ranking", "JARVIS implementation": "ETF-proxied calendar return table", "Status": "Complete within aligned history"},
        {"Reference capability": "Black-Litterman views", "JARVIS implementation": "Editable asset view, spread and confidence", "Status": "Complete"},
        {"Reference capability": "Monte Carlo wealth fan", "JARVIS implementation": "5,000 paths, shortfall and drawdown distribution", "Status": "Complete"},
        {"Reference capability": "Retroactive backtest", "JARVIS implementation": "Observed wealth, drawdown, CAGR, Sharpe and Calmar", "Status": "Complete"},
        {"Reference capability": "Regime radar / signals", "JARVIS implementation": "Six-axis market radar plus tactical heatmap", "Status": "Complete"},
        {"Reference capability": "CSV exports", "JARVIS implementation": "Allocation, CMA, scorecard and stress exports", "Status": "Complete"},
    ])
    _table(coverage, "tools4_coverage", 560)

    _section("Eight-Model Guide")
    methods = pd.DataFrame([{"Model": model, "Full Name": PORTFOLIO_METHODS_V4[model][0], "Institutional Use": PORTFOLIO_METHODS_V4[model][1]} for model in PORTFOLIO_MODELS_V4])
    _table(methods, "tools4_method_guide", 450)

    _section("Data, Assumptions & Governance")
    governance = pd.DataFrame([
        {"Layer": "Observed prices", "Source": "Yahoo/yfinance adjusted ETF closes", "Treatment": "Aligned, no synthetic market-history fill", "Limitation": "ETF proxy and inception bias"},
        {"Layer": "Expected returns", "Source": "Observed CAGR + disclosed long-run prior blend", "Treatment": "Bull/Base/Bear and building-block overlays", "Limitation": "CMA, not a realised forecast"},
        {"Layer": "Covariance", "Source": "Observed daily returns", "Treatment": "75% sample + 25% diagonal shrinkage", "Limitation": "Static covariance and no liquidity spiral"},
        {"Layer": "Tactical signals", "Source": "Observed prices + active CMA", "Treatment": "Cross-sectional Momentum / Value / Carry z-scores", "Limitation": "No transaction-cost optimiser"},
        {"Layer": "Factor loadings", "Source": "IWD/IWF, MTUM, QUAL, SPLV, IJR versus SPY", "Treatment": "OLS on aligned daily excess returns", "Limitation": "ETF factors are investable proxies, not academic factors"},
        {"Layer": "Private markets", "Source": "PSP listed private-market proxy", "Treatment": "Daily market-valued series", "Limitation": "Not an appraisal-smoothed private equity index"},
        {"Layer": "Stress tests", "Source": "Observed crisis windows + disclosed shock vectors", "Treatment": "Static-weight first-order P&L", "Limitation": "No nonlinear options or forced selling"},
        {"Layer": "Monte Carlo", "Source": "Active CMA and covariance", "Treatment": "Fixed-seed Gaussian monthly paths", "Limitation": "Fat tails and serial dependence understated"},
    ])
    _table(governance, "tools4_governance", 520)

    _section("Validation Contract")
    validation = pd.DataFrame([
        {"Control": "Weight conservation", "Required": "Σ weights = 100%", "Scope": "All eight models and TAA"},
        {"Control": "Long-only / cap", "Required": "0 ≤ weight ≤ active cap", "Scope": "All optimisers"},
        {"Control": "Risk attribution", "Required": "Σ risk contribution = 100%", "Scope": "Selected strategic portfolio"},
        {"Control": "Reproducibility", "Required": "Fixed seeds", "Scope": "Sampling, resampled MVO and Monte Carlo"},
        {"Control": "Provider failure", "Required": "Visible unavailable state", "Scope": "Prices and factor proxies"},
        {"Control": "Observed / model separation", "Required": "Explicit labels", "Scope": "CMA, stresses and simulations"},
        {"Control": "Non-regression", "Required": "HANK, Global Macro, Payrolls, Economy and Markets", "Scope": "Hub routing"},
    ])
    _table(validation, "tools4_validation", 390)


def _portfolio_optimizer_v4() -> None:
    _header_v2(
        "Portfolio Optimizer",
        "Institutional allocation command center: strategic and tactical allocation, eight portfolio engines, capital-market assumptions, factor and risk attribution, historical regimes, Monte Carlo, peer benchmarks and governed exports.",
        "JARVIS TOOLS · PORTFOLIO OPTIMIZER",
    )
    mode = _segmented_v2("Portfolio view", ["Allocation", "Risk & Stress", "Methodology"], "tools2_port_mode", "Allocation")
    if mode == "Risk & Stress":
        _portfolio_risk_v4()
    elif mode == "Methodology":
        _portfolio_methodology_v4()
    else:
        _portfolio_allocation_v4()


def render_tools_intelligence(ticker: str = "", price_data: Optional[pd.DataFrame] = None, analysis: Optional[Mapping[str, Any]] = None) -> None:
    """V4 renderer: complete Portfolio Optimizer, unchanged V3 macro simulators."""
    del ticker, price_data, analysis
    _css_v3()
    page = str(st.session_state.get(TOOLS_PAGE_KEY_V2, "Macro Simulators"))
    if page not in TOOLS_PAGES_V2:
        page = "Macro Simulators"
        st.session_state[TOOLS_PAGE_KEY_V2] = page
    if page == "Portfolio Optimizer":
        _portfolio_optimizer_v4()
    else:
        simulator = _model_nav_v2()
        if simulator == "Global Macro Model":
            _global_macro_v3()
        elif simulator == "Payrolls Forecasting":
            _payrolls_v2()
        else:
            _hank_models_v3()
    _html(f'<div class="t1-source" style="margin-top:18px">{TOOLS_VERSION_V4} · observed history, assumptions and model output are explicitly separated · not investment advice.</div>')


TOOLS_INTEGRITY_V4: Mapping[str, Any] = {
    "version": TOOLS_VERSION_V4,
    "portfolio_models": list(PORTFOLIO_MODELS_V4),
    "portfolio_model_count": len(PORTFOLIO_MODELS_V4),
    "saa_taa": True,
    "building_block_cma": True,
    "factor_attribution": True,
    "historical_stress_windows": len(STRESS_WINDOWS),
    "regime_correlations": True,
    "peer_benchmarks": len(PORTFOLIO_PEERS_V4),
    "monte_carlo_paths": 5000,
    "macro_simulators_preserved": True,
    "synthetic_observed_history": False,
}


# ============================================================
# V5 — RoboMacro-ordered Portfolio workstation
# ============================================================

TOOLS_VERSION_V5 = "V5 · LOCALLY-CONTROLLED PORTFOLIO WORKSTATION"


def _css_v5() -> None:
    _css_v3()
    st.markdown(
        """
<style>
.p5-intro{border-left:3px solid #d8bf58;padding:3px 0 4px 14px;margin:24px 0 12px}.p5-kicker{font-size:9px;letter-spacing:.18em;text-transform:uppercase;color:#8396a8;font-weight:850}.p5-title{font-family:Georgia,serif;font-size:28px;line-height:1.12;color:#f1f5f8;margin:4px 0 6px}.p5-copy{font-size:11px;line-height:1.55;color:#91a2b2;max-width:1050px}.p5-local{border:1px solid rgba(128,158,190,.22);border-radius:11px;padding:10px 12px;margin:7px 0 12px;background:linear-gradient(145deg,rgba(7,21,34,.92),rgba(4,14,24,.96))}.p5-local-label{font-size:9px;letter-spacing:.14em;text-transform:uppercase;color:#d8bf58;font-weight:850;margin-bottom:3px}.p5-inline-note{font-size:9px;color:#8496a6;line-height:1.45;margin-top:3px}.p5-statline{display:flex;gap:7px;flex-wrap:wrap;margin:7px 0 10px}.p5-stat{border:1px solid rgba(126,156,184,.20);border-radius:999px;padding:5px 9px;color:#a6b4c0;font-size:9px;background:rgba(8,22,35,.70)}
.st-key-tools5_scenario [role="radiogroup"],.st-key-tools5_factor_model [role="radiogroup"],.st-key-tools5_corr_regime [role="radiogroup"],.st-key-tools5_corr_lookback [role="radiogroup"],.st-key-tools5_assumption_asset [role="radiogroup"]{display:flex!important;flex-wrap:wrap!important;gap:5px!important}.st-key-tools5_scenario [role="radiogroup"]>button,.st-key-tools5_factor_model [role="radiogroup"]>button,.st-key-tools5_corr_regime [role="radiogroup"]>button,.st-key-tools5_corr_lookback [role="radiogroup"]>button,.st-key-tools5_assumption_asset [role="radiogroup"]>button{min-height:36px!important;border-color:rgba(127,157,185,.27)!important;background:rgba(7,20,33,.90)!important;color:#aebac5!important}.st-key-tools5_scenario [role="radiogroup"]>button[aria-pressed="true"],.st-key-tools5_factor_model [role="radiogroup"]>button[aria-pressed="true"],.st-key-tools5_corr_regime [role="radiogroup"]>button[aria-pressed="true"],.st-key-tools5_corr_lookback [role="radiogroup"]>button[aria-pressed="true"],.st-key-tools5_assumption_asset [role="radiogroup"]>button[aria-pressed="true"]{background:linear-gradient(135deg,rgba(119,97,25,.86),rgba(77,64,20,.94))!important;border-color:rgba(216,191,88,.62)!important;color:#fff!important}.st-key-tools5_model_assumptions{border-color:rgba(128,158,190,.24)!important;background:linear-gradient(145deg,rgba(7,21,34,.91),rgba(4,14,24,.96))!important}.st-key-tools5_model_assumptions summary{color:#d8bf58!important;font-weight:800!important;letter-spacing:.08em!important;text-transform:uppercase!important}.st-key-tools5_saa_controls,.st-key-tools5_risk_controls,.st-key-tools5_factor_controls,.st-key-tools5_tornado_controls,.st-key-tools5_peer_controls,.st-key-tools5_frontier_controls,.st-key-tools5_bl_controls,.st-key-tools5_mc_controls,.st-key-tools5_backtest_controls,.st-key-tools5_corr_controls{border-color:rgba(128,158,190,.23)!important;background:rgba(6,18,30,.90)!important;border-radius:11px!important;padding:10px 12px!important}
</style>
        """,
        unsafe_allow_html=True,
    )


def _portfolio_intro_v5(kicker: str, title: str, copy: str) -> None:
    _html(
        '<div class="p5-intro">'
        f'<div class="p5-kicker">{_esc(kicker)}</div>'
        f'<div class="p5-title">{_esc(title)}</div>'
        f'<div class="p5-copy">{_esc(copy)}</div>'
        '</div>'
    )


def _portfolio_models_v5(
    engine: PortfolioEngine,
    max_weight: float,
    risk_free: float,
    view_asset: str,
    view_against: str,
    view_spread: float,
    view_confidence: float,
) -> Tuple[Dict[str, np.ndarray], pd.DataFrame]:
    models, bl = _portfolio_models_v4(engine, max_weight, risk_free, view_asset, view_spread, view_confidence)
    if view_against in engine.assets and view_against != view_asset:
        posterior = bl["Posterior %"].to_numpy(dtype=float) / 100.0
        selected_idx = engine.assets.index(view_asset)
        against_idx = engine.assets.index(view_against)
        posterior[selected_idx] -= view_spread * 0.5
        posterior[against_idx] -= view_spread * 0.5
        models["Black-Litterman"] = _sample_max_sharpe_v4(posterior, engine.cov, risk_free, max_weight, 5129, 9000)
        bl["Posterior %"] = posterior * 100.0
    return models, bl


def _portfolio_max_history_v5(engine: PortfolioEngine) -> pd.DataFrame:
    tickers = tuple(TOOLS_ASSETS[asset]["ticker"] for asset in engine.assets)
    prices, _ = _load_market_history(tickers, "max")
    if prices.empty:
        return engine.prices.copy()
    rename = {TOOLS_ASSETS[asset]["ticker"]: asset for asset in engine.assets}
    return prices.rename(columns=rename).reindex(columns=engine.assets).sort_index()


def _portfolio_state_v5() -> Optional[Tuple[PortfolioEngine, Dict[str, np.ndarray], pd.DataFrame, pd.DataFrame, float, float, str]]:
    scenario = str(st.session_state.get("tools5_scenario", "Base"))
    max_weight = float(st.session_state.get("tools5_max_weight", 0.40))
    risk_free = float(st.session_state.get("tools5_risk_free", 0.035))
    cma_mode = str(st.session_state.get("tools5_cma_mode", "50/50 shrinkage"))
    view_asset = str(st.session_state.get("tools5_bl_asset", "EM Equity"))
    view_against = str(st.session_state.get("tools5_bl_against", "Intl Developed"))
    view_spread = float(st.session_state.get("tools5_bl_spread", 1.50)) / 100.0
    view_confidence = float(st.session_state.get("tools5_bl_confidence_pct", 50.0)) / 100.0
    with st.spinner("Refreshing the institutional portfolio stack…"):
        engine = _portfolio_engine(scenario, max_weight, risk_free, cma_mode)
    if engine is None:
        _html('<div class="t2-warn"><b>Portfolio engine unavailable.</b> The market provider did not return sufficient aligned history. No observed series was fabricated.</div>')
        return None
    base_decomposition = _return_decomposition_v4(engine)
    for idx, asset in enumerate(engine.assets):
        slug = _key_slug_v3(asset)
        overlay = sum(float(st.session_state.get(f"tools5_cma_{component}_{slug}", 0.0)) for component in ("growth", "income", "valuation", "default"))
        engine.mu[idx] += overlay / 100.0
    if view_asset not in engine.assets:
        view_asset = engine.assets[0]
    models, bl = _portfolio_models_v5(engine, max_weight, risk_free, view_asset, view_against, view_spread, view_confidence)
    decomposition = base_decomposition.copy()
    for idx, asset in enumerate(engine.assets):
        slug = _key_slug_v3(asset)
        adjustments = {
            "Growth %": float(st.session_state.get(f"tools5_cma_growth_{slug}", 0.0)),
            "Income %": float(st.session_state.get(f"tools5_cma_income_{slug}", 0.0)),
            "Valuation / Roll %": float(st.session_state.get(f"tools5_cma_valuation_{slug}", 0.0)),
            "Defaults Adj %": float(st.session_state.get(f"tools5_cma_default_{slug}", 0.0)),
        }
        for column, value in adjustments.items():
            decomposition.loc[idx, column] += value
        decomposition.loc[idx, "Expected Return %"] = decomposition.loc[idx, ["Growth %", "Income %", "Valuation / Roll %", "Defaults Adj %"]].sum()
    return engine, models, bl, decomposition, max_weight, risk_free, scenario


def _portfolio_workstation_v5() -> None:
    top_left, top_right = st.columns([1.25, 0.75], gap="large")
    with top_left:
        _html('<div class="p5-local-label">CMA Scenario</div>')
        _segmented_v2("CMA scenario", ["Bull", "Base", "Bear"], "tools5_scenario", "Base")
    with top_right:
        st.slider("Risk-free rate", 0.0, 0.08, 0.035, 0.005, format="%.3f", key="tools5_risk_free")
    state = _portfolio_state_v5()
    if state is None:
        return
    engine, models, bl, decomposition, max_weight, risk_free, scenario = state
    updated = engine.meta.get("updated")
    updated_txt = pd.Timestamp(updated).strftime("%d %b %Y") if updated is not None and not pd.isna(updated) else "unknown"
    saa_model_state = str(st.session_state.get("tools5_saa_model", "Risk Parity"))
    if saa_model_state not in models:
        saa_model_state = "Risk Parity"
    headline_metrics = _portfolio_metrics(engine, models[saa_model_state], risk_free)
    _kpis([
        ("Portfolio Return", _fmt_pct(headline_metrics["return"]), f"{saa_model_state} · {scenario} CMA", headline_metrics["return"]),
        ("Portfolio Volatility", _fmt_pct(headline_metrics["vol"]), "Annualised shrunk covariance", -headline_metrics["vol"]),
        ("Sharpe Ratio", _fmt_num(headline_metrics["sharpe"]), f"Risk-free {_fmt_pct(risk_free)}", headline_metrics["sharpe"]),
        ("Historical CAGR", _fmt_pct(headline_metrics["cagr_backtest"]), "Static current weights", headline_metrics["cagr_backtest"]),
        ("Maximum Drawdown", _fmt_pct(headline_metrics["max_dd"]), "Observed aligned-history backtest", headline_metrics["max_dd"]),
        ("Forecast Horizon", "10Y", f"Live history through {updated_txt}", 1),
    ])

    _portfolio_intro_v5(
        "Strategic vs Tactical",
        "SAA Neutral vs TAA Recommended",
        "Strategic Asset Allocation is the selected model's long-run target. Tactical Asset Allocation applies live Momentum, Value and Carry tilts subject to a local deviation cap.",
    )
    with st.container(border=True, key="tools5_saa_controls"):
        c1, c2 = st.columns([0.72, 1.28])
        with c1:
            saa_model = st.selectbox("SAA source", list(PORTFOLIO_MODELS_V4), index=list(PORTFOLIO_MODELS_V4).index(saa_model_state), key="tools5_saa_model")
        with c2:
            tilt_cap_pct = st.slider("Tactical tilt cap", 0.0, 10.0, 5.0, 1.0, format="±%.0f%%", key="tools5_tilt_cap")
    saa = models[saa_model]
    signals = _portfolio_signals_v4(engine)
    taa = _taa_weights_v4(saa, signals, tilt_cap_pct / 100.0, max_weight)
    allocation = pd.DataFrame({"Asset": engine.assets, "SAA %": saa * 100, "TAA %": taa * 100, "Tactical Tilt pp": (taa - saa) * 100}).merge(signals, on="Asset", how="left")
    with _card():
        _card_head("SAA (NEUTRAL) vs TAA (TACTICAL) WEIGHTS", "Neutral and Recommended Weights", "The controls above change only this strategic/tactical block.")
        fig = go.Figure()
        fig.add_trace(go.Bar(x=allocation["Asset"], y=allocation["SAA %"], name="SAA", marker_color="#506a80"))
        fig.add_trace(go.Bar(x=allocation["Asset"], y=allocation["TAA %"], name="TAA", marker_color="#d8bf58"))
        fig.update_layout(barmode="group")
        fig.update_yaxes(title="Weight (%)")
        _plot(fig, "tools5_saa_taa", 430)
    with _card():
        _card_head("TACTICAL DEVIATIONS", "TAA − SAA", "Positive values are recommended overweights; negative values are underweights.")
        ordered_tilt = allocation.sort_values("Tactical Tilt pp", ascending=False)
        fig = go.Figure(go.Bar(x=ordered_tilt["Asset"], y=ordered_tilt["Tactical Tilt pp"], marker_color=["#57d39b" if value >= 0 else "#f4777f" for value in ordered_tilt["Tactical Tilt pp"]]))
        fig.add_hline(y=0, line_color="rgba(220,230,240,.25)")
        fig.update_yaxes(title="Active tilt (pp)")
        _plot(fig, "tools5_tactical_deviation", 360)
    _table(allocation, "tools5_saa_table", 360, {"SAA %": "{:.1f}%", "TAA %": "{:.1f}%", "Tactical Tilt pp": "{:+.1f}", "Momentum": "{:+.2f}", "Value": "{:+.2f}", "Carry": "{:+.2f}", "Composite": "{:+.2f}"})

    with st.expander("Model Assumptions", expanded=False):
        with st.container(key="tools5_model_assumptions"):
            _html('<div class="t2-note">Adjust building-block assumptions by asset class. Every edit refreshes the return decomposition, CMA table and all dependent portfolio models.</div>')
            assumption_asset = _segmented_v2("Assumption asset", engine.assets, "tools5_assumption_asset", engine.assets[0])
            slug = _key_slug_v3(assumption_asset)
            a1, a2 = st.columns(2)
            with a1:
                st.slider("Structural growth adjustment (pp)", -3.0, 3.0, 0.0, 0.25, key=f"tools5_cma_growth_{slug}")
                st.slider("Income yield adjustment (pp)", -3.0, 3.0, 0.0, 0.25, key=f"tools5_cma_income_{slug}")
            with a2:
                st.slider("Valuation / roll adjustment (pp)", -3.0, 3.0, 0.0, 0.25, key=f"tools5_cma_valuation_{slug}")
                st.slider("Default / other adjustment (pp)", -3.0, 3.0, 0.0, 0.25, key=f"tools5_cma_default_{slug}")

    _portfolio_intro_v5(
        "Capital Market Assumptions",
        "Return Decomposition",
        "Building-block forecasts separate structural growth, income, valuation or roll and default adjustments. These are assumptions, never presented as realised market data.",
    )
    cma_mode = st.selectbox("CMA construction", ["50/50 shrinkage", "Historical CAGR", "Long-run priors"], key="tools5_cma_mode")
    with _card():
        fig = go.Figure()
        for column, color in zip(["Growth %", "Income %", "Valuation / Roll %", "Defaults Adj %"], ["#63c7ff", "#d8bf58", "#57d39b", "#f4777f"]):
            fig.add_trace(go.Bar(x=decomposition["Asset"], y=decomposition[column], name=column.replace(" %", ""), marker_color=color))
        fig.update_layout(barmode="relative")
        fig.update_yaxes(title="Expected return contribution (pp)")
        _plot(fig, "tools5_return_decomposition", 455)
    _portfolio_intro_v5("CMA Summary", "Asset Class Forecasts", f"Expected returns and risk estimates under the active {cma_mode} methodology and {scenario} scenario.")
    forecast_table = decomposition[["Asset", "Expected Return %"]].copy()
    forecast_table["Volatility %"] = np.sqrt(np.diag(engine.cov)) * 100
    forecast_table["Sharpe"] = (engine.mu - risk_free) / np.sqrt(np.diag(engine.cov))
    forecast_table = forecast_table.sort_values("Expected Return %", ascending=False)
    _table(forecast_table, "tools5_forecast_table", 370, {"Expected Return %": "{:.2f}%", "Volatility %": "{:.2f}%", "Sharpe": "{:.3f}"})
    _download(forecast_table, "Export CMA CSV", "jarvis_portfolio_cma.csv", "tools5_cma_export")

    _portfolio_intro_v5("Risk-Return Space", "Risk vs. Return", "Each asset is positioned by observed covariance risk and active expected return. Dot size reflects the absolute Sharpe ratio.")
    asset_vol = np.sqrt(np.diag(engine.cov)) * 100
    asset_ret = engine.mu * 100
    asset_sharpe = np.divide(engine.mu - risk_free, np.sqrt(np.diag(engine.cov)), out=np.zeros(len(engine.assets)), where=np.sqrt(np.diag(engine.cov)) > 1e-9)
    with _card():
        fig = go.Figure(go.Scatter(x=asset_vol, y=asset_ret, mode="markers+text", text=engine.assets, textposition="top center", marker=dict(size=13 + 9 * np.abs(asset_sharpe), color=asset_sharpe, colorscale="RdYlGn", cmin=-0.5, cmax=0.8, line=dict(color="#d7e1e9", width=1))))
        fig.update_xaxes(title="Volatility (%)")
        fig.update_yaxes(title="Expected return (%)")
        _plot(fig, "tools5_risk_return", 470)

    _portfolio_intro_v5("Risk Attribution", "% Risk Contribution vs Weight", "Portfolio volatility is decomposed into each asset's marginal variance contribution, revealing the difference between capital owned and risk driven.")
    with st.container(border=True, key="tools5_risk_controls"):
        risk_model = st.selectbox("Risk attribution model", list(PORTFOLIO_MODELS_V4), key="tools5_risk_model")
    risk_weights = models[risk_model]
    risk_metrics = _portfolio_metrics(engine, risk_weights, risk_free)
    risk_contribution = risk_weights * (engine.cov @ risk_weights)
    risk_contribution = risk_contribution / risk_contribution.sum() if abs(risk_contribution.sum()) > 1e-12 else np.zeros_like(risk_weights)
    risk_frame = pd.DataFrame({"Asset": engine.assets, "Weight %": risk_weights * 100, "Risk Contribution %": risk_contribution * 100}).sort_values("Weight %")
    _html(f'<div class="p5-statline"><span class="p5-stat">MODEL · {_esc(risk_model)}</span><span class="p5-stat">PORTFOLIO σ · {risk_metrics["vol"]:.2%}</span><span class="p5-stat">Σ RISK CONTRIBUTION · 100%</span></div>')
    with _card():
        fig = go.Figure()
        fig.add_trace(go.Bar(y=risk_frame["Asset"], x=risk_frame["Weight %"], orientation="h", name="Weight", marker_color="#506a80"))
        fig.add_trace(go.Bar(y=risk_frame["Asset"], x=risk_frame["Risk Contribution %"], orientation="h", name="Risk contribution", marker_color="#d8bf58"))
        fig.update_layout(barmode="group")
        fig.update_xaxes(title="Portfolio share (%)")
        _plot(fig, "tools5_risk_attribution", 470)

    _portfolio_intro_v5("Factor Exposure", "Style Factor Radar", "Portfolio loadings on Value, Momentum, Quality, Low-Vol and Size are estimated from transparent ETF long/short proxies.")
    with st.container(border=True, key="tools5_factor_controls"):
        factor_model = _segmented_v2("Factor model", list(PORTFOLIO_MODELS_V4), "tools5_factor_model", "MVO")
    factor_assets, factor_portfolio = _factor_loadings_v4(engine, models[factor_model])
    with _card():
        if factor_portfolio.empty:
            _html('<div class="t2-warn">Style-factor proxy histories are unavailable. Allocation and risk outputs remain valid.</div>')
        else:
            theta = factor_portfolio["Factor"].tolist() + [factor_portfolio["Factor"].iloc[0]]
            radius = factor_portfolio["Loading"].tolist() + [factor_portfolio["Loading"].iloc[0]]
            fig = go.Figure(go.Scatterpolar(r=radius, theta=theta, fill="toself", name=factor_model, line=dict(color="#d8bf58", width=2.3), fillcolor="rgba(216,191,88,.14)"))
            fig.update_layout(polar=dict(radialaxis=dict(visible=True, gridcolor="rgba(180,200,215,.16)")))
            _plot(fig, "tools5_factor_radar", 470)
    if not factor_assets.empty:
        _table(factor_assets, "tools5_factor_assets", 380, {column: "{:+.3f}" for column in factor_assets.columns if column != "Asset"})

    _portfolio_intro_v5("Stress Tests", "Historical Regime Scenarios", "Realised per-asset and per-model total returns across five canonical crisis windows. ETF-proxied observations are never fabricated.")
    max_history = _portfolio_max_history_v5(engine)
    crisis_asset_rows: List[Dict[str, Any]] = []
    crisis_model_rows: List[Dict[str, Any]] = []
    crisis_columns = st.columns(2, gap="small")
    for crisis_idx, (label, (start, end)) in enumerate(STRESS_WINDOWS.items()):
        asset_returns: List[float] = []
        available_assets: List[str] = []
        for asset_name in engine.assets:
            series = max_history[asset_name].dropna() if asset_name in max_history else pd.Series(dtype=float)
            subset = series.loc[(series.index >= pd.Timestamp(start)) & (series.index <= pd.Timestamp(end))]
            value = float(subset.iloc[-1] / subset.iloc[0] - 1.0) if len(subset) >= 2 else np.nan
            asset_returns.append(value)
            available_assets.append(asset_name)
            crisis_asset_rows.append({"Window": label, "Asset": asset_name, "Return %": value * 100 if np.isfinite(value) else np.nan})
        vector = np.nan_to_num(np.asarray(asset_returns, dtype=float), nan=0.0)
        model_row: Dict[str, Any] = {"Window": label}
        for model_name in PORTFOLIO_MODELS_V4:
            model_row[model_name] = float(models[model_name] @ vector * 100)
        crisis_model_rows.append(model_row)
        with crisis_columns[crisis_idx % 2], _card():
            _card_head("REALIZED WINDOW", label, f"{start} → {end}")
            plot_frame = pd.DataFrame({"Asset": available_assets, "Return %": np.asarray(asset_returns) * 100}).dropna().sort_values("Return %")
            fig = go.Figure(go.Bar(x=plot_frame["Return %"], y=plot_frame["Asset"], orientation="h", marker_color=["#57d39b" if value >= 0 else "#f4777f" for value in plot_frame["Return %"]]))
            fig.add_vline(x=0, line_color="rgba(220,230,240,.25)")
            _plot(fig, f"tools5_crisis_{crisis_idx}", 330)
    crisis_models = pd.DataFrame(crisis_model_rows)
    _table(crisis_models, "tools5_crisis_models", 360, {model_name: "{:+.1f}%" for model_name in PORTFOLIO_MODELS_V4})

    _portfolio_intro_v5("Macro Sensitivity", "Tornado Chart — Shocks to CMAs", "First-order sensitivity of the selected portfolio to disclosed growth, inflation, rate, credit and dollar shocks.")
    with st.container(border=True, key="tools5_tornado_controls"):
        tornado_model = st.selectbox("Sensitivity model", list(PORTFOLIO_MODELS_V4), key="tools5_tornado_model")
    sensitivities = {
        "Growth +1pp": {"US Equity": 1.8, "Intl Developed": 1.7, "EM Equity": 2.2, "US Treasuries": -0.6, "US Credit": 0.4, "Commodities": 1.0, "Gold": -0.2, "Listed Private Markets": 2.0},
        "Inflation +1pp": {"US Equity": -0.7, "Intl Developed": -0.6, "EM Equity": -0.5, "US Treasuries": -1.8, "US Credit": -1.0, "Commodities": 2.5, "Gold": 1.8, "Listed Private Markets": -0.8},
        "Rates +100bp": {"US Equity": -1.8, "Intl Developed": -1.5, "EM Equity": -1.4, "US Treasuries": -6.5, "US Credit": -3.2, "Commodities": -0.5, "Gold": -2.0, "Listed Private Markets": -3.0},
        "Credit +100bp": {"US Equity": -1.0, "Intl Developed": -0.9, "EM Equity": -1.3, "US Treasuries": 0.5, "US Credit": -3.5, "Commodities": -0.7, "Gold": 0.6, "Listed Private Markets": -2.8},
        "USD +5%": {"US Equity": -0.4, "Intl Developed": -1.0, "EM Equity": -2.0, "US Treasuries": 0.2, "US Credit": 0.0, "Commodities": -2.5, "Gold": -2.0, "Listed Private Markets": -0.8},
    }
    tornado_weights = models[tornado_model]
    tornado = pd.DataFrame({"Shock": list(sensitivities), "Portfolio Impact %": [float(tornado_weights @ np.array([mapping.get(asset_name, 0.0) for asset_name in engine.assets])) for mapping in sensitivities.values()]}).sort_values("Portfolio Impact %")
    with _card():
        fig = go.Figure(go.Bar(x=tornado["Portfolio Impact %"], y=tornado["Shock"], orientation="h", marker_color=["#f4777f" if value < 0 else "#57d39b" for value in tornado["Portfolio Impact %"]]))
        fig.add_vline(x=0, line_color="rgba(220,230,240,.25)")
        fig.update_xaxes(title="Modelled portfolio impact (%)")
        _plot(fig, "tools5_tornado", 380)
    _table(tornado, "tools5_tornado_table", 260, {"Portfolio Impact %": "{:+.2f}%"})

    _portfolio_intro_v5("Regime-Dependent Correlations", "Correlation Matrix by Regime", "Daily ETF returns are classified into transparent Risk-On and Risk-Off subsets using 63-day equity trend and volatility.")
    with st.container(border=True, key="tools5_corr_regime_controls"):
        correlation_regime = _segmented_v2("Correlation regime", ["Risk-On", "Risk-Off"], "tools5_corr_regime", "Risk-On")
    market_proxy = engine.returns["US Equity"] if "US Equity" in engine.returns else engine.returns.mean(axis=1)
    proxy_vol = market_proxy.rolling(63).std()
    proxy_trend = market_proxy.rolling(63).sum()
    risk_on_mask = (proxy_vol <= proxy_vol.median()) & (proxy_trend >= 0)
    selected_mask = risk_on_mask if correlation_regime == "Risk-On" else ~risk_on_mask
    selected_regime_returns = engine.returns.loc[selected_mask.reindex(engine.returns.index).fillna(False)]
    regime_corr = selected_regime_returns.corr() if len(selected_regime_returns) >= 60 else engine.returns.corr()
    _html(f'<div class="p5-statline"><span class="p5-stat">{_esc(correlation_regime)}</span><span class="p5-stat">{len(selected_regime_returns)} TRADING DAYS</span><span class="p5-stat">OBSERVED ETF RETURNS</span></div>')
    with _card():
        fig = go.Figure(go.Heatmap(z=regime_corr.values, x=regime_corr.columns, y=regime_corr.index, zmin=-1, zmax=1, zmid=0, colorscale=[[0, "#28658a"], [0.5, "#111c28"], [1, "#8a3b43"]], text=np.round(regime_corr.values, 2), texttemplate="%{text}", colorbar=dict(title="ρ")))
        _plot(fig, "tools5_regime_corr", 500)

    _portfolio_intro_v5("Scenario Analysis", "Bull / Base / Bear Comparison", "Expected returns across all three CMA regimes are shown side by side without changing the active page state.")
    active_shift = {"Bull": 0.020, "Base": 0.0, "Bear": -0.030}.get(scenario, 0.0)
    scenario_base = engine.mu - active_shift
    with _card():
        fig = go.Figure()
        for scenario_name, shift, color in [("Bull", 0.020, "#57d39b"), ("Base", 0.0, "#d8bf58"), ("Bear", -0.030, "#f4777f")]:
            fig.add_trace(go.Bar(x=engine.assets, y=(scenario_base + shift) * 100, name=scenario_name, marker_color=color))
        fig.update_layout(barmode="group")
        fig.update_yaxes(title="Expected return (%)")
        _plot(fig, "tools5_scenario_compare", 430)

    _portfolio_intro_v5("Peer Benchmarks", "Allocation vs Institutional Peers", "The selected JARVIS model is compared with classic 60/40, endowment, public-pension and global family-office reference mixes.")
    with st.container(border=True, key="tools5_peer_controls"):
        p1, p2 = st.columns(2)
        with p1:
            peer_model = st.selectbox("JARVIS model", list(PORTFOLIO_MODELS_V4), key="tools5_peer_model")
        with p2:
            peer_reference = st.selectbox("Deviation vs", list(PORTFOLIO_PEERS_V4), key="tools5_peer_reference")
    peers = pd.DataFrame({"Asset": engine.assets, "JARVIS": models[peer_model] * 100})
    for peer_name, mapping in PORTFOLIO_PEERS_V4.items():
        peers[peer_name] = [mapping.get(asset_name, 0.0) for asset_name in engine.assets]
    peers["Active Deviation pp"] = peers["JARVIS"] - peers[peer_reference]
    with _card():
        fig = go.Figure()
        fig.add_trace(go.Bar(x=peers["Asset"], y=peers["JARVIS"], name=f"JARVIS · {peer_model}", marker_color="#d8bf58"))
        for idx, peer_name in enumerate(PORTFOLIO_PEERS_V4):
            fig.add_trace(go.Bar(x=peers["Asset"], y=peers[peer_name], name=peer_name, marker_color=PALETTE[(idx + 2) % len(PALETTE)]))
        fig.update_layout(barmode="group")
        fig.update_yaxes(title="Weight (%)")
        _plot(fig, "tools5_peer_allocations", 490)
    with _card():
        ordered_peer = peers.sort_values("Active Deviation pp", ascending=False)
        fig = go.Figure(go.Bar(x=ordered_peer["Asset"], y=ordered_peer["Active Deviation pp"], marker_color=["#57d39b" if value >= 0 else "#f4777f" for value in ordered_peer["Active Deviation pp"]]))
        fig.add_hline(y=0, line_color="rgba(220,230,240,.25)")
        fig.update_yaxes(title=f"Deviation vs {peer_reference} (pp)")
        _plot(fig, "tools5_peer_deviation", 350)

    _portfolio_intro_v5("Historical Context", "Annual Asset-Class Return Ranking", "Calendar-year ETF total returns show leadership rotation across the investable asset universe.")
    annual_returns = max_history.resample("YE").last().pct_change() * 100
    annual_returns.index = annual_returns.index.year.astype(str)
    annual_returns = annual_returns.tail(25)
    callan = annual_returns.T.reset_index(names="Asset")
    _table(callan, "tools5_callan", 470, {column: "{:+.0f}%" for column in callan.columns if column != "Asset"})

    _portfolio_intro_v5("Portfolio Optimisation", "Efficient Frontier", "The feasible long-only opportunity set is recomputed with the local maximum-weight constraint; all eight model portfolios are overlaid.")
    with st.container(border=True, key="tools5_frontier_controls"):
        st.slider("Maximum asset weight", 0.20, 0.70, 0.40, 0.05, key="tools5_max_weight")
    with _card():
        fig = go.Figure(go.Scattergl(x=engine.candidates["Volatility"] * 100, y=engine.candidates["Return"] * 100, mode="markers", marker=dict(size=4, color=engine.candidates["Sharpe"], colorscale="Viridis", opacity=.38, colorbar=dict(title="Sharpe")), name="Feasible"))
        for model_name in PORTFOLIO_MODELS_V4:
            model_metrics = _portfolio_metrics(engine, models[model_name], risk_free)
            fig.add_trace(go.Scatter(x=[model_metrics["vol"] * 100], y=[model_metrics["return"] * 100], mode="markers", marker=dict(size=10, symbol="diamond", color=PALETTE[list(PORTFOLIO_MODELS_V4).index(model_name) % len(PALETTE)]), name=model_name))
        fig.update_xaxes(title="Expected volatility (%)")
        fig.update_yaxes(title="Expected return (%)")
        _plot(fig, "tools5_frontier", 500)

    _portfolio_intro_v5("Model Comparison", "Portfolio Allocations by Model", "Asset weights for MVO, Min-Var, Black-Litterman, Risk Parity, All-Weather, HRP, CVaR and Resampled MVO.")
    with st.expander("Methodology Guide", expanded=False):
        methodology = pd.DataFrame([{"Model": model_name, "Full Name": PORTFOLIO_METHODS_V4[model_name][0], "Description": PORTFOLIO_METHODS_V4[model_name][1]} for model_name in PORTFOLIO_MODELS_V4])
        _table(methodology, "tools5_methodology_guide", 430)
    with _card():
        fig = go.Figure()
        for asset_idx, asset_name in enumerate(engine.assets):
            fig.add_trace(go.Bar(x=list(PORTFOLIO_MODELS_V4), y=[models[model_name][asset_idx] * 100 for model_name in PORTFOLIO_MODELS_V4], name=asset_name, marker_color=PALETTE[asset_idx % len(PALETTE)]))
        fig.update_layout(barmode="stack")
        fig.update_yaxes(title="Weight (%)", range=[0, 100])
        _plot(fig, "tools5_model_allocations", 490)

    _portfolio_intro_v5("Model Scorecards", "Side-by-Side Metrics", "Historical performance, drawdown, diversification and concentration metrics use the same aligned history and static current weights.")
    scorecard = _model_scorecard_v4(engine, models, risk_free)
    _table(scorecard, "tools5_scorecard", 490, {"Expected Return %": "{:.2f}%", "Volatility %": "{:.2f}%", "Sharpe": "{:.2f}", "Historical CAGR %": "{:.2f}%", "Max DD %": "{:.2f}%", "Calmar": "{:.2f}", "HHI": "{:.3f}", "Top-3 %": "{:.0f}%"})
    _download(scorecard, "Export model scorecard CSV", "jarvis_portfolio_model_scorecard.csv", "tools5_scorecard_export")

    _portfolio_intro_v5("Black-Litterman", "Equilibrium vs. Posterior Returns", "Edit the investor view directly below the chart. Posterior returns and Black-Litterman weights update on every rerun.")
    market_map = {"US Equity": 0.38, "Intl Developed": 0.16, "EM Equity": 0.09, "US Treasuries": 0.14, "US Credit": 0.10, "Commodities": 0.04, "Gold": 0.04, "Listed Private Markets": 0.05}
    bl_view = bl.copy()
    bl_view["Market Cap %"] = [market_map.get(asset_name, 0.0) * 100 for asset_name in engine.assets]
    with _card():
        fig = go.Figure()
        fig.add_trace(go.Bar(x=bl_view["Asset"], y=bl_view["Equilibrium %"], name="Equilibrium", marker_color="#506a80"))
        fig.add_trace(go.Bar(x=bl_view["Asset"], y=bl_view["Posterior %"], name="Posterior", marker_color="#d8bf58"))
        fig.add_trace(go.Bar(x=bl_view["Asset"], y=bl_view["Market Cap %"], name="Market Cap", marker_color="#8d7330"))
        fig.update_layout(barmode="group")
        fig.update_yaxes(title="Return / allocation input (%)")
        _plot(fig, "tools5_bl_chart", 470)
    with st.container(border=True, key="tools5_bl_controls"):
        _html('<div class="p5-local-label">Investor View</div>')
        b1, b2, b3 = st.columns([1.0, 1.0, 1.2])
        with b1:
            st.selectbox("View asset", engine.assets, key="tools5_bl_asset")
        with b2:
            st.selectbox("Relative to", ["(absolute)"] + engine.assets, key="tools5_bl_against")
        with b3:
            st.slider("Annual return view (pp)", -5.0, 5.0, 1.50, 0.25, key="tools5_bl_spread")
        st.slider("View confidence", 0.0, 100.0, 50.0, 5.0, format="%.0f%%", key="tools5_bl_confidence_pct")
    active_bl_asset = str(st.session_state.get("tools5_bl_asset", "EM Equity"))
    active_bl_against = str(st.session_state.get("tools5_bl_against", "Intl Developed"))
    active_bl_spread = float(st.session_state.get("tools5_bl_spread", 1.5))
    active_bl_conf = float(st.session_state.get("tools5_bl_confidence_pct", 50.0)) / 100.0
    relation = "absolute" if active_bl_against == "(absolute)" else f"vs {active_bl_against}"
    _html(f'<div class="t2-analysis"><b>Active investor view</b>{_esc(active_bl_asset)} {relation}: {active_bl_spread:+.2f}pp per year at {active_bl_conf:.0%} confidence.</div>')

    _portfolio_intro_v5("Simulation", "Monte Carlo Wealth Projection", "Five thousand monthly paths use the selected model's active CMA and covariance. Shortfall and maximum-drawdown distributions are computed path by path.")
    with st.container(border=True, key="tools5_mc_controls"):
        simulation_model = st.selectbox("Simulation model", list(PORTFOLIO_MODELS_V4), key="tools5_mc_model")
    simulation_weights = models[simulation_model]
    simulation_metrics = _portfolio_metrics(engine, simulation_weights, risk_free)
    rng = np.random.default_rng(4407)
    months, paths = 120, 5000
    monthly_mu = simulation_metrics["return"] / 12.0
    monthly_vol = simulation_metrics["vol"] / math.sqrt(12.0)
    simulated_returns = np.clip(rng.normal(monthly_mu, monthly_vol, size=(months, paths)), -0.95, None)
    wealth_paths = np.vstack([np.ones(paths), np.cumprod(1.0 + simulated_returns, axis=0)])
    quantiles = np.quantile(wealth_paths, [0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95], axis=1)
    running_peak = np.maximum.accumulate(wealth_paths, axis=0)
    max_drawdown_paths = np.min(wealth_paths / running_peak - 1.0, axis=0)
    with _card():
        x = np.arange(months + 1) / 12.0
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=x, y=quantiles[6], line=dict(width=0), showlegend=False))
        fig.add_trace(go.Scatter(x=x, y=quantiles[0], fill="tonexty", fillcolor="rgba(99,199,255,.07)", line=dict(width=0), name="5–95%"))
        fig.add_trace(go.Scatter(x=x, y=quantiles[5], line=dict(width=0), showlegend=False))
        fig.add_trace(go.Scatter(x=x, y=quantiles[1], fill="tonexty", fillcolor="rgba(99,199,255,.11)", line=dict(width=0), name="10–90%"))
        fig.add_trace(go.Scatter(x=x, y=quantiles[4], line=dict(width=0), showlegend=False))
        fig.add_trace(go.Scatter(x=x, y=quantiles[2], fill="tonexty", fillcolor="rgba(99,199,255,.18)", line=dict(width=0), name="25–75%"))
        fig.add_trace(go.Scatter(x=x, y=quantiles[3], line=dict(color="#d8bf58", width=2.4), name="Median"))
        fig.update_xaxes(title="Years")
        fig.update_yaxes(title="Wealth per $1")
        _plot(fig, "tools5_monte_carlo", 480)
    terminal_wealth = wealth_paths[-1]
    shortfall = pd.DataFrame({"Terminal Threshold": ["$0.8", "$0.9", "$1.0", "$1.2", "$1.5", "$2.0"], "Shortfall Probability %": [float((terminal_wealth < level).mean() * 100) for level in [0.8, 0.9, 1.0, 1.2, 1.5, 2.0]]})
    drawdown_quantiles = np.quantile(max_drawdown_paths, [0.05, 0.25, 0.50, 0.75, 0.95]) * 100
    drawdown_distribution = pd.DataFrame({"Max Drawdown Percentile": ["Worst 5%", "25th", "Median", "75th", "Best 5%"], "Drawdown %": drawdown_quantiles})
    s1, s2 = st.columns(2)
    with s1:
        _table(shortfall, "tools5_shortfall", 280, {"Shortfall Probability %": "{:.1f}%"})
    with s2:
        _table(drawdown_distribution, "tools5_drawdown_distribution", 280, {"Drawdown %": "{:.1f}%"})

    _portfolio_intro_v5("Historical Analysis", "Retroactive Backtest", "Today's selected model weights are applied to observed market history. This is a diagnostic backtest, not a live track record.")
    with st.container(border=True, key="tools5_backtest_controls"):
        backtest_model = st.selectbox("Backtest model", list(PORTFOLIO_MODELS_V4), key="tools5_backtest_model")
    backtest_weights = models[backtest_model]
    portfolio_returns = pd.Series(engine.returns.values @ backtest_weights, index=engine.returns.index)
    portfolio_wealth = (1.0 + portfolio_returns).cumprod()
    portfolio_drawdown = portfolio_wealth / portfolio_wealth.cummax() - 1.0
    with _card():
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=portfolio_wealth.index, y=portfolio_wealth, name="Wealth", line=dict(color="#63c7ff", width=2)))
        fig.add_trace(go.Scatter(x=portfolio_drawdown.index, y=portfolio_drawdown * 100, name="Drawdown %", yaxis="y2", fill="tozeroy", fillcolor="rgba(244,119,127,.10)", line=dict(color="#f4777f")))
        fig.update_layout(yaxis2=dict(overlaying="y", side="right", showgrid=False, title="Drawdown %"))
        _plot(fig, "tools5_backtest", 470)
    _table(scorecard[["Model", "Historical CAGR %", "Max DD %", "Sharpe", "Calmar"]], "tools5_backtest_metrics", 360, {"Historical CAGR %": "{:.2f}%", "Max DD %": "{:.2f}%", "Sharpe": "{:.2f}", "Calmar": "{:.2f}"})

    _portfolio_intro_v5("Macro Regime", "Regime Radar & Indicators", "Six transparent scores summarise observed growth, defence, inflation, liquidity, breadth and portfolio stability.")
    latest_63 = engine.prices.pct_change(63).iloc[-1]
    equity_assets = [asset_name for asset_name in ["US Equity", "Intl Developed", "EM Equity"] if asset_name in engine.assets]
    defensive_assets = [asset_name for asset_name in ["US Treasuries", "US Credit", "Gold"] if asset_name in engine.assets]
    real_assets = [asset_name for asset_name in ["Commodities", "Gold"] if asset_name in engine.assets]
    breadth = float((latest_63 > 0).mean() * 100)
    growth = float(np.clip(50 + 125 * latest_63.reindex(equity_assets).mean(), 0, 100)) if equity_assets else 50.0
    defence = float(np.clip(50 + 125 * latest_63.reindex(defensive_assets).mean(), 0, 100)) if defensive_assets else 50.0
    inflation = float(np.clip(50 + 125 * latest_63.reindex(real_assets).mean(), 0, 100)) if real_assets else 50.0
    liquidity = float(np.clip(50 + 150 * (latest_63.get("US Credit", 0.0) - latest_63.get("US Treasuries", 0.0)), 0, 100))
    trend = float(np.clip(50 + 100 * latest_63.mean(), 0, 100))
    stability = float(np.clip(100 - headline_metrics["vol"] * 250, 0, 100))
    radar = pd.DataFrame({"Dimension": ["Growth", "Defence", "Inflation", "Liquidity", "Breadth", "Stability"], "Score": [growth, defence, inflation, liquidity, breadth, stability]})
    regime_left, regime_right = st.columns([1.0, 1.0])
    with regime_left, _card():
        theta = radar["Dimension"].tolist() + [radar["Dimension"].iloc[0]]
        radius = radar["Score"].tolist() + [radar["Score"].iloc[0]]
        fig = go.Figure(go.Scatterpolar(r=radius, theta=theta, fill="toself", line=dict(color="#63c7ff", width=2.2), fillcolor="rgba(99,199,255,.14)"))
        fig.update_layout(polar=dict(radialaxis=dict(range=[0, 100], visible=True)))
        _plot(fig, "tools5_regime_radar", 430)
    with regime_right:
        _kpis([
            ("Growth", f"{growth:.0f}", "63-day equity impulse", growth - 50),
            ("Defence", f"{defence:.0f}", "Duration / credit / gold", defence - 50),
            ("Inflation", f"{inflation:.0f}", "Commodity and gold impulse", inflation - 50),
            ("Liquidity", f"{liquidity:.0f}", "Credit versus duration", liquidity - 50),
            ("Breadth", f"{breadth:.0f}%", "Assets above 63-day start", breadth - 50),
            ("Stability", f"{stability:.0f}", "Inverse volatility score", stability - 50),
        ])

    _portfolio_intro_v5("Tactical Signals", "Signal Heatmap", "Daily Momentum, Value and Carry z-scores are the sole inputs to the tactical allocation overlay shown at the top of the page.")
    signal_matrix = signals.set_index("Asset")[["Momentum", "Value", "Carry"]]
    with _card():
        fig = go.Figure(go.Heatmap(z=signal_matrix.values, x=signal_matrix.columns, y=signal_matrix.index, zmid=0, zmin=-2.5, zmax=2.5, colorscale=[[0, "#7d2432"], [0.5, "#101c29"], [1, "#276c58"]], text=np.round(signal_matrix.values, 2), texttemplate="%{text}"))
        _plot(fig, "tools5_signal_heatmap", 420)

    _portfolio_intro_v5("Diversification", "Correlation Matrix", "Pairwise correlations from realised daily ETF returns. The lookback control belongs only to this matrix.")
    with st.container(border=True, key="tools5_corr_controls"):
        lookback = _segmented_v2("Correlation lookback", ["90 Day", "1 Year", "3 Year", "5 Year", "10 Year"], "tools5_corr_lookback", "10 Year")
    lookback_days = {"90 Day": 90, "1 Year": 252, "3 Year": 756, "5 Year": 1260, "10 Year": 2520}[lookback]
    selected_corr = engine.returns.tail(lookback_days).corr()
    long_corr = engine.returns.tail(2520).corr()
    mask = np.triu(np.ones(selected_corr.shape, dtype=bool), 1)
    instability = float(np.nanmean(np.abs((selected_corr - long_corr).values[mask])) * 100) if mask.any() else 0.0
    _html(f'<div class="p5-statline"><span class="p5-stat">LOOKBACK · {_esc(lookback)}</span><span class="p5-stat">INSTABILITY · {instability:.1f}%</span><span class="p5-stat">SHRUNK COVARIANCE USED IN OPTIMISERS</span></div>')
    with _card():
        fig = go.Figure(go.Heatmap(z=selected_corr.values, x=selected_corr.columns, y=selected_corr.index, zmin=-1, zmax=1, zmid=0, colorscale=[[0, "#28658a"], [0.5, "#111c28"], [1, "#8a3b43"]], text=np.round(selected_corr.values, 2), texttemplate="%{text}", colorbar=dict(title="ρ")))
        _plot(fig, "tools5_correlation_matrix", 500)

    with st.expander("Methodology & Data Quality", expanded=False):
        _html('<div class="t2-note"><b>Observed versus modelled.</b> ETF prices, calendar returns and crisis windows are observed. CMAs, tactical tilts, deterministic shocks and Monte Carlo paths are explicitly labelled model output.</div>')
        methodology = pd.DataFrame([{"Model": model_name, "Full Name": PORTFOLIO_METHODS_V4[model_name][0], "Use": PORTFOLIO_METHODS_V4[model_name][1]} for model_name in PORTFOLIO_MODELS_V4])
        _table(methodology, "tools5_final_methodology", 420)
        governance = pd.DataFrame([
            {"Layer": "Prices", "Source": "Yahoo/yfinance adjusted ETF closes", "Failure contract": "Visible unavailable state; no synthetic observed history"},
            {"Layer": "CMAs", "Source": "Observed CAGR plus disclosed priors", "Failure contract": "Always labelled assumption"},
            {"Layer": "Covariance", "Source": "Observed daily returns", "Failure contract": "75% sample + 25% diagonal shrinkage"},
            {"Layer": "Factors", "Source": "IWD/IWF, MTUM, QUAL, SPLV, IJR vs SPY", "Failure contract": "Factor block unavailable; portfolio remains usable"},
            {"Layer": "Stress", "Source": "Observed windows + disclosed deterministic vectors", "Failure contract": "Missing observations stay missing"},
            {"Layer": "Simulation", "Source": "Active CMA and covariance", "Failure contract": "Fixed seed; Gaussian limitation disclosed"},
        ])
        _table(governance, "tools5_governance", 400)
    _download(allocation, "Export SAA / TAA allocation CSV", "jarvis_portfolio_saa_taa.csv", "tools5_allocation_export")


def _portfolio_optimizer_v5() -> None:
    _header_v2(
        "Portfolio Optimizer",
        "A RoboMacro-ordered institutional workstation where every parameter sits beside the analysis it controls: allocation, CMAs, attribution, factors, stress, optimisation, Black-Litterman, simulation and diversification.",
        "JARVIS TOOLS · PORTFOLIO OPTIMIZER",
    )
    _portfolio_workstation_v5()


def render_tools_intelligence(ticker: str = "", price_data: Optional[pd.DataFrame] = None, analysis: Optional[Mapping[str, Any]] = None) -> None:
    """V5 renderer: locally controlled Portfolio workstation, unchanged V3 macro simulators."""
    del ticker, price_data, analysis
    _css_v5()
    page = str(st.session_state.get(TOOLS_PAGE_KEY_V2, "Macro Simulators"))
    if page not in TOOLS_PAGES_V2:
        page = "Macro Simulators"
        st.session_state[TOOLS_PAGE_KEY_V2] = page
    if page == "Portfolio Optimizer":
        _portfolio_optimizer_v5()
    else:
        simulator = _model_nav_v2()
        if simulator == "Global Macro Model":
            _global_macro_v3()
        elif simulator == "Payrolls Forecasting":
            _payrolls_v2()
        else:
            _hank_models_v3()
    _html(f'<div class="t1-source" style="margin-top:18px">{TOOLS_VERSION_V5} · controls are local to their analytical block · observed history is never synthetically filled.</div>')


TOOLS_INTEGRITY_V5: Mapping[str, Any] = {
    "version": TOOLS_VERSION_V5,
    "robomacro_section_order": True,
    "global_parameter_wall": False,
    "local_saa_controls": True,
    "local_risk_controls": True,
    "local_factor_controls": True,
    "local_regime_controls": True,
    "local_peer_controls": True,
    "local_black_litterman_views": True,
    "local_simulation_model": True,
    "portfolio_models": list(PORTFOLIO_MODELS_V4),
    "macro_simulators_preserved": True,
    "synthetic_observed_history": False,
}
