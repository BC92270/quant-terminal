# asset_class_router.py
# ============================================================
# MULTI-ASSET COMMAND CENTER V2 — Quant Terminal
# ============================================================
# Objectif V2 :
# - Remplacer la page 4 cartes statique par un Global Command Center.
# - Garder les fonctions V1 déjà utilisées par app.py.
# - Ajouter une recherche centrale multi-asset avec inférence Equity / FX / Commodities / Rates.
# - Ajouter Market Tape, Cross-Asset Regime, Latest News et Quick Launch.
# - Ajouter un contrôle sidebar optionnel pour choisir l'asset class sans casser app.py.
# - Aucun changement dans les moteurs Monte Carlo / Risk / Backtest / Decision.
# ============================================================

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except Exception:  # pragma: no cover
    yf = None
    YFINANCE_AVAILABLE = False


# ============================================================
# ASSET CLASS REGISTRY
# ============================================================

ASSET_CLASS_REGISTRY: dict[str, dict[str, Any]] = {
    "Equity": {
        "label": "EQUITY",
        "subtitle": "Stocks · ETFs · single-name research",
        "default_symbol": "NVDA",
        "default_period": "1y",
        "default_interval": "1d",
        "description": "Fundamentals, valuation, options, execution plan, risk, backtest, ML research.",
        "presets": ["NVDA", "AAPL", "MSFT", "TSLA", "AMD", "AVGO", "SPY", "QQQ", "IWM"],
        "mode_options": [
            "Correlation Matrix",
            "Trading Plan",
            "Backtest Lab",
            "Risk Monitor",
            "Momentum / Trend",
            "Monte Carlo Advanced",
            "Company Intelligence",
            "Decision Engine",
            "ML Research Lab",
            "Options / Futures",
        ],
    },
    "FX": {
        "label": "FX",
        "subtitle": "Majors · crosses · dollar regime",
        "default_symbol": "EURUSD=X",
        "default_period": "2y",
        "default_interval": "1d",
        "description": "Pairs, trend, volatility, macro proxies, cross-correlation, risk and backtest.",
        "presets": [
            "EURUSD=X",
            "GBPUSD=X",
            "USDJPY=X",
            "USDCHF=X",
            "AUDUSD=X",
            "USDCAD=X",
            "EURJPY=X",
            "DX-Y.NYB",
        ],
        "mode_options": [
            "FX Dashboard",
            "Correlation Matrix",
            "Trading Plan",
            "Backtest Lab",
            "Risk Monitor",
            "Momentum / Trend",
            "Monte Carlo Advanced",
            "Decision Engine Lite",
        ],
    },
    "Commodities": {
        "label": "COMMODITIES",
        "subtitle": "Energy · metals · agricultural futures",
        "default_symbol": "GC=F",
        "default_period": "2y",
        "default_interval": "1d",
        "description": "Futures proxies, volatility, term-structure roadmap, execution risk, backtest.",
        "presets": [
            "GC=F",
            "SI=F",
            "CL=F",
            "BZ=F",
            "NG=F",
            "HG=F",
            "ZC=F",
            "ZS=F",
        ],
        "mode_options": [
            "Commodity Dashboard",
            "Correlation Matrix",
            "Trading Plan",
            "Backtest Lab",
            "Risk Monitor",
            "Momentum / Trend",
            "Monte Carlo Advanced",
            "Options / Futures",
        ],
    },
    "Rates": {
        "label": "FIXED INCOME",
        "subtitle": "Sovereign curves · credit · bonds · portfolio risk",
        "default_symbol": "^TNX",
        "default_period": "5y",
        "default_interval": "1d",
        "description": (
            "Yield curves, sovereign rates, credit spreads, bond pricing, "
            "duration, DV01, CS01, relative value, portfolio risk and stress tests."
        ),
        "presets": [
            "^IRX",
            "^FVX",
            "^TNX",
            "^TYX",

            "SHY",
            "IEF",
            "TLT",
            "TIP",

            "LQD",
            "HYG",
            "JNK",
            "VCIT",
            "VCSH",
            "EMB",

            "ZT=F",
            "ZF=F",
            "ZN=F",
            "ZB=F",
            "UB=F",
        ],
        "mode_options": [
            "Fixed Income & Credit Analytics",
            "Rates Dashboard",
            "Correlation Matrix",
            "Backtest Lab",
            "Risk Monitor",
            "Momentum / Trend",
            "Monte Carlo Advanced",
        ],
    },
}

# ============================================================
# PORTFOLIO LAB — GLOBAL MULTI-ASSET MODE
# ============================================================
PORTFOLIO_LAB_MODE = "Portfolio Lab"

# Portfolio Lab est un book multi-actifs autonome.
# Il doit rester accessible quel que soit l'univers sélectionné :
# Equity, FX, Commodities ou Rates.
for _asset_profile in ASSET_CLASS_REGISTRY.values():
    _mode_options = _asset_profile.setdefault("mode_options", [])

    if PORTFOLIO_LAB_MODE not in _mode_options:
        try:
            _insert_index = _mode_options.index("Correlation Matrix") + 1
        except ValueError:
            _insert_index = 0

        _mode_options.insert(_insert_index, PORTFOLIO_LAB_MODE)

MARKET_TAPE_UNIVERSES: dict[str, list[str]] = {
    "Global": [
        "ES=F", "NQ=F", "YM=F", "RTY=F", "^VIX", "DX-Y.NYB",
        "^IRX", "^FVX", "^TNX", "^TYX", "CL=F", "BZ=F", "GC=F", "SI=F",
        "EURUSD=X", "USDJPY=X", "GBPUSD=X",
    ],
    "Equity": ["ES=F", "NQ=F", "YM=F", "RTY=F", "SPY", "QQQ", "IWM", "SMH", "XLF", "XLE", "XLK", "^VIX"],
    "FX": ["DX-Y.NYB", "EURUSD=X", "GBPUSD=X", "USDJPY=X", "USDCHF=X", "AUDUSD=X", "USDCAD=X", "EURJPY=X"],
    "Commodities": ["CL=F", "BZ=F", "NG=F", "GC=F", "SI=F", "HG=F", "ZC=F", "ZS=F"],
    "Rates": ["^IRX", "^FVX", "^TNX", "^TYX", "SHY", "IEF", "TLT", "ZT=F", "ZN=F", "ZB=F"],
}

SYMBOL_LABELS: dict[str, str] = {
    "ES=F": "S&P Fut",
    "NQ=F": "Nasdaq Fut",
    "YM=F": "Dow Fut",
    "RTY=F": "Russell Fut",
    "^VIX": "VIX",
    "DX-Y.NYB": "DXY",
    "^IRX": "3M Yield",
    "^FVX": "5Y Yield",
    "^TNX": "10Y Yield",
    "^TYX": "30Y Yield",
    "CL=F": "WTI",
    "BZ=F": "Brent",
    "NG=F": "Nat Gas",
    "GC=F": "Gold",
    "SI=F": "Silver",
    "HG=F": "Copper",
    "EURUSD=X": "EUR/USD",
    "GBPUSD=X": "GBP/USD",
    "USDJPY=X": "USD/JPY",
    "USDCHF=X": "USD/CHF",
    "AUDUSD=X": "AUD/USD",
    "USDCAD=X": "USD/CAD",
    "EURJPY=X": "EUR/JPY",
}

COMMODITY_FUTURES = {"CL=F", "BZ=F", "NG=F", "GC=F", "SI=F", "HG=F", "ZC=F", "ZS=F", "ZW=F", "KC=F", "CC=F"}
RATES_SYMBOLS = {
    # Sovereign yield proxies
    "^IRX",
    "^FVX",
    "^TNX",
    "^TYX",

    # Treasury / inflation ETFs
    "SHY",
    "IEF",
    "TLT",
    "TIP",

    # Credit ETFs
    "LQD",
    "HYG",
    "JNK",
    "VCIT",
    "VCSH",
    "EMB",

    # Treasury futures
    "ZT=F",
    "ZF=F",
    "ZN=F",
    "ZB=F",
    "UB=F",
}
FX_COMPACT = {"EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD", "EURJPY", "EURGBP", "EURCHF", "GBPJPY"}
FX_YAHOO = {f"{x}=X" for x in FX_COMPACT} | {"DX-Y.NYB"}


# ============================================================
# BASIC HELPERS
# ============================================================

def _safe_float(value: Any, default: float | None = None) -> float | None:
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


def _fmt_num(value: Any, digits: int = 2) -> str:
    x = _safe_float(value)
    if x is None:
        return "N/A"
    return f"{x:,.{digits}f}"


def _fmt_pct(value: Any, digits: int = 2) -> str:
    x = _safe_float(value)
    if x is None:
        return "N/A"
    return f"{x:+.{digits}%}"


def _fmt_compact_num(value: Any) -> str:
    x = _safe_float(value)
    if x is None:
        return "N/A"
    ax = abs(x)
    if ax >= 1_000_000_000:
        return f"{x / 1_000_000_000:.2f}B"
    if ax >= 1_000_000:
        return f"{x / 1_000_000:.2f}M"
    if ax >= 1_000:
        return f"{x / 1_000:.2f}K"
    return f"{x:.2f}"


def get_asset_profile(asset_class: str | None) -> dict[str, Any]:
    asset_class = str(asset_class or "Equity")
    return ASSET_CLASS_REGISTRY.get(asset_class, ASSET_CLASS_REGISTRY["Equity"])


def get_asset_classes() -> list[str]:
    return list(ASSET_CLASS_REGISTRY.keys())


def get_all_mode_options() -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for profile in ASSET_CLASS_REGISTRY.values():
        for mode in profile.get("mode_options", []):
            if mode not in seen:
                seen.add(mode)
                out.append(mode)
    return out


def infer_asset_class_from_symbol(raw_symbol: str, fallback: str = "Equity") -> str:
    symbol = str(raw_symbol or "").strip().upper()
    if not symbol:
        return fallback if fallback in ASSET_CLASS_REGISTRY else "Equity"

    compact = symbol.replace("/", "").replace("-", "").replace(" ", "")

    if symbol in FX_YAHOO or compact in FX_COMPACT:
        return "FX"
    if symbol in COMMODITY_FUTURES:
        return "Commodities"
    if symbol in RATES_SYMBOLS:
        return "Rates"
    if symbol.startswith("^") and symbol in RATES_SYMBOLS:
        return "Rates"

    return "Equity"


def normalize_market_symbol(asset_class: str, raw_symbol: str) -> str:
    """
    Normalisation prudente Yahoo Finance.
    - FX : EURUSD -> EURUSD=X.
    - Equity / Commo / Rates : conserve les suffixes Yahoo existants.
    """
    symbol = str(raw_symbol or "").strip().upper()
    asset_class = str(asset_class or "Equity")

    if not symbol:
        return get_asset_profile(asset_class)["default_symbol"]

    compact = symbol.replace("/", "").replace("-", "").replace(" ", "")

    if asset_class == "FX" and compact in FX_COMPACT and not symbol.endswith("=X"):
        return f"{compact}=X"

    return symbol


def default_mode_for_asset(asset_class: str) -> str:
    profile = get_asset_profile(asset_class)
    modes = profile.get("mode_options", [])
    return str(modes[0]) if modes else "Correlation Matrix"


def resolve_asset_symbol_and_mode(
    selected_asset_class: str | None,
    raw_symbol: str,
    requested_mode: str | None = None,
) -> tuple[str, str, str]:
    """
    Résout l'asset class, le ticker Yahoo normalisé et un mode compatible.
    Cette fonction permet à l'omnibox de piloter directement FX / Commo / Rates.
    """
    selected = str(selected_asset_class or "Auto")

    if selected == "Auto":
        asset_class = infer_asset_class_from_symbol(raw_symbol, fallback="Equity")
    elif selected in ASSET_CLASS_REGISTRY:
        # Si l'utilisateur tape explicitement un symbole FX/Commo/Rates dans la barre principale,
        # on l'autorise à surclasser Equity automatiquement.
        inferred = infer_asset_class_from_symbol(raw_symbol, fallback=selected)
        if selected == "Equity" and inferred != "Equity":
            asset_class = inferred
        else:
            asset_class = selected
    else:
        asset_class = infer_asset_class_from_symbol(raw_symbol, fallback="Equity")

    symbol = normalize_market_symbol(asset_class, raw_symbol)
    profile = get_asset_profile(asset_class)
    modes = profile.get("mode_options", [])

    if requested_mode in modes:
        mode = str(requested_mode)
    else:
        mode = default_mode_for_asset(asset_class)

    return asset_class, symbol, mode


def _select_index(options: list[str], value: str | None, default: int = 0) -> int:
    try:
        return options.index(str(value))
    except Exception:
        return default


def _launch_workspace(asset_class: str, symbol: str, period: str, interval: str, mode: str) -> None:
    asset_class, symbol, mode = resolve_asset_symbol_and_mode(asset_class, symbol, mode)
    profile = get_asset_profile(asset_class)

    st.session_state["asset_class"] = asset_class
    st.session_state["asset_class_selected"] = True
    st.session_state["ticker"] = symbol
    st.session_state["mode_input"] = mode
    st.session_state["terminal_command_mode"] = mode
    st.session_state["last_params"] = {
        "ticker": symbol,
        "period": period or profile["default_period"],
        "interval": interval or profile["default_interval"],
        "asset_class": asset_class,
    }
    st.rerun()


# ============================================================
# DATA LOADING — MARKET TAPE / NEWS
# ============================================================

@st.cache_data(ttl=300, show_spinner=False)
def _download_one_symbol_snapshot(symbol: str, period: str = "5d") -> dict[str, Any]:
    symbol = str(symbol or "").upper().strip()
    empty = {
        "Symbol": symbol,
        "Name": SYMBOL_LABELS.get(symbol, symbol),
        "Last": np.nan,
        "Change %": np.nan,
        "Volume": np.nan,
        "Status": "WAIT",
    }

    if not symbol or not YFINANCE_AVAILABLE:
        return empty

    try:
        raw = yf.download(
            symbol,
            period=period,
            interval="1d",
            progress=False,
            auto_adjust=False,
            threads=False,
        )

        if raw is None or raw.empty:
            return empty

        df = raw.copy().reset_index()

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = ["_".join([str(x) for x in col if str(x) not in ["", "None"]]).strip("_").lower() for col in df.columns]
        else:
            df.columns = [str(c).lower().replace(" ", "_") for c in df.columns]

        close_candidates = ["close", f"close_{symbol.lower()}", "adj_close", f"adj_close_{symbol.lower()}"]
        close_col = None
        for col in close_candidates:
            if col in df.columns:
                close_col = col
                break
        if close_col is None:
            close_like = [c for c in df.columns if "close" in str(c).lower()]
            close_col = close_like[0] if close_like else None
        if close_col is None:
            return empty

        close = pd.to_numeric(df[close_col], errors="coerce").dropna()
        if close.empty:
            return empty

        last = float(close.iloc[-1])
        prev = float(close.iloc[-2]) if len(close) >= 2 else np.nan
        change = last / prev - 1 if prev and np.isfinite(prev) and prev != 0 else np.nan

        volume = np.nan
        vol_like = [c for c in df.columns if "volume" in str(c).lower()]
        if vol_like:
            volume_series = pd.to_numeric(df[vol_like[0]], errors="coerce").dropna()
            if not volume_series.empty:
                volume = float(volume_series.iloc[-1])

        return {
            "Symbol": symbol,
            "Name": SYMBOL_LABELS.get(symbol, symbol),
            "Last": last,
            "Change %": change,
            "Volume": volume,
            "Status": "OK",
        }
    except Exception:
        return empty


@st.cache_data(ttl=300, show_spinner=False)
def load_market_tape_snapshot(symbols: tuple[str, ...]) -> pd.DataFrame:
    rows = [_download_one_symbol_snapshot(sym) for sym in symbols]
    if not rows:
        return pd.DataFrame(columns=["Symbol", "Name", "Last", "Change %", "Volume", "Status"])
    return pd.DataFrame(rows)


@st.cache_data(ttl=900, show_spinner=False)
def load_latest_news_snapshot(symbols: tuple[str, ...] = ("SPY", "QQQ", "TLT", "CL=F", "GC=F", "EURUSD=X"), limit: int = 8) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    if not YFINANCE_AVAILABLE:
        return pd.DataFrame()

    for symbol in symbols:
        try:
            news_items = yf.Ticker(symbol).news or []
        except Exception:
            news_items = []

        for item in news_items[:4]:
            if not isinstance(item, dict):
                continue

            content = item.get("content") if isinstance(item.get("content"), dict) else {}
            title = item.get("title") or content.get("title") or ""
            publisher = item.get("publisher") or item.get("provider") or ""
            if isinstance(content.get("provider"), dict):
                publisher = content.get("provider", {}).get("displayName") or content.get("provider", {}).get("name") or publisher

            ts = item.get("providerPublishTime") or item.get("pubDate") or content.get("pubDate") or content.get("displayTime")
            published = "N/A"
            try:
                if isinstance(ts, (int, float)):
                    published = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
                elif ts:
                    published = pd.to_datetime(ts).strftime("%Y-%m-%d %H:%M")
            except Exception:
                published = "N/A"

            if title:
                rows.append({
                    "Symbol": symbol,
                    "Published": published,
                    "Source": publisher or "N/A",
                    "Headline": str(title),
                })

            if len(rows) >= limit:
                break

        if len(rows) >= limit:
            break

    return pd.DataFrame(rows)


# ============================================================
# CSS / UI HELPERS
# ============================================================

def inject_command_center_css() -> None:
    st.markdown(
        """
        <style>
        .cc-shell {
            border: 1px solid rgba(90, 205, 255, 0.22);
            background:
                radial-gradient(circle at 50% 0%, rgba(50, 170, 255, 0.14), transparent 32%),
                linear-gradient(180deg, rgba(5, 15, 30, 0.96), rgba(2, 7, 19, 0.98));
            border-radius: 24px;
            padding: 24px 28px;
            margin-bottom: 18px;
            box-shadow: 0 0 55px rgba(40, 160, 255, 0.10);
        }
        .cc-kicker {
            color: #55e8ff;
            font-weight: 950;
            letter-spacing: 0.24em;
            font-size: 0.72rem;
            text-transform: uppercase;
            margin-bottom: 8px;
        }
        .cc-title {
            color: #f8fbff;
            font-size: 2.25rem;
            font-weight: 950;
            line-height: 1.05;
            margin-bottom: 8px;
        }
        .cc-sub {
            color: rgba(220, 235, 250, 0.76);
            font-size: 0.97rem;
            max-width: 1120px;
            line-height: 1.45;
        }
        .cc-panel {
            border: 1px solid rgba(90, 205, 255, 0.18);
            background: rgba(7, 20, 38, 0.66);
            border-radius: 18px;
            padding: 16px 16px;
            min-height: 168px;
            box-shadow: inset 0 0 30px rgba(80, 180, 255, 0.035);
        }
        .cc-panel-title {
            color: #55e8ff;
            font-size: 0.78rem;
            font-weight: 950;
            letter-spacing: 0.20em;
            text-transform: uppercase;
            margin-bottom: 11px;
        }
        .cc-tape-card {
            border: 1px solid rgba(90, 205, 255, 0.18);
            background: rgba(3, 12, 26, 0.72);
            border-radius: 14px;
            padding: 11px 12px;
            min-height: 92px;
        }
        .cc-tape-name {
            color: rgba(230, 244, 255, 0.72);
            font-size: 0.72rem;
            font-weight: 850;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-bottom: 7px;
        }
        .cc-tape-value {
            color: #f8fbff;
            font-size: 1.05rem;
            font-weight: 900;
            margin-bottom: 5px;
        }
        .cc-tape-delta-pos { color: #62ffbf; font-weight: 850; }
        .cc-tape-delta-neg { color: #ff7b7b; font-weight: 850; }
        .cc-tape-delta-flat { color: rgba(235,245,255,0.62); font-weight: 850; }
        .cc-mini-note {
            color: rgba(220, 235, 250, 0.60);
            font-size: 0.75rem;
            line-height: 1.35;
        }
        .cc-news-row {
            border-bottom: 1px solid rgba(90, 205, 255, 0.10);
            padding: 9px 0;
        }
        .cc-news-headline {
            color: rgba(245, 249, 255, 0.94);
            font-size: 0.86rem;
            font-weight: 760;
            line-height: 1.25;
        }
        .cc-news-meta {
            color: rgba(180, 205, 225, 0.58);
            font-size: 0.72rem;
            margin-top: 3px;
        }
        .cc-regime-value {
            color: #f8fbff;
            font-size: 1.10rem;
            font-weight: 900;
        }
        .cc-regime-label {
            color: rgba(220, 235, 250, 0.70);
            font-size: 0.76rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            font-weight: 850;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_tape_cards(df: pd.DataFrame, max_cards: int = 8) -> None:
    if df is None or df.empty:
        st.info("Market tape indisponible.")
        return

    show = df.head(max_cards).copy()
    cols = st.columns(min(max_cards, len(show)))

    for col, (_, row) in zip(cols, show.iterrows()):
        change = _safe_float(row.get("Change %"))
        delta_class = "cc-tape-delta-flat"
        if change is not None and change > 0:
            delta_class = "cc-tape-delta-pos"
        elif change is not None and change < 0:
            delta_class = "cc-tape-delta-neg"

        with col:
            st.markdown(
                f"""
                <div class="cc-tape-card">
                    <div class="cc-tape-name">{row.get('Name', row.get('Symbol', 'N/A'))}</div>
                    <div class="cc-tape-value">{_fmt_num(row.get('Last'))}</div>
                    <div class="{delta_class}">{_fmt_pct(row.get('Change %'))}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def _render_news_panel(news_df: pd.DataFrame) -> None:
    st.markdown("<div class='cc-panel-title'>LATEST NEWS</div>", unsafe_allow_html=True)

    if news_df is None or news_df.empty:
        st.caption(
            "News feed indisponible via yfinance dans cette session. "
            "Prévu pour branchement FMP/Finnhub/NewsAPI ensuite."
        )
        return

    for _, row in news_df.head(8).iterrows():
        headline = str(row.get("Headline", ""))[:220]
        source = str(row.get("Source", "N/A"))
        published = str(row.get("Published", "N/A"))
        symbol = str(row.get("Symbol", ""))
        st.markdown(
            f"""
            <div class="cc-news-row">
                <div class="cc-news-headline">{headline}</div>
                <div class="cc-news-meta">{symbol} · {source} · {published}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ============================================================
# REGIME ENGINE — LIGHT PROXY
# ============================================================

def _read_change(df: pd.DataFrame, symbol: str) -> float | None:
    try:
        row = df.loc[df["Symbol"] == symbol]
        if row.empty:
            return None
        return _safe_float(row.iloc[0].get("Change %"))
    except Exception:
        return None


def build_cross_asset_regime(tape_df: pd.DataFrame) -> dict[str, Any]:
    if tape_df is None or tape_df.empty:
        return {
            "risk": "STANDBY",
            "vol": "STANDBY",
            "dollar": "STANDBY",
            "rates": "STANDBY",
            "commodities": "STANDBY",
            "read": "Données insuffisantes pour construire le régime.",
        }

    es = _read_change(tape_df, "ES=F") or 0.0
    nq = _read_change(tape_df, "NQ=F") or 0.0
    rty = _read_change(tape_df, "RTY=F") or 0.0
    vix = _read_change(tape_df, "^VIX") or 0.0
    dxy = _read_change(tape_df, "DX-Y.NYB") or 0.0
    tnx = _read_change(tape_df, "^TNX") or 0.0
    fv = _read_change(tape_df, "^FVX") or 0.0
    oil = _read_change(tape_df, "CL=F") or 0.0
    gold = _read_change(tape_df, "GC=F") or 0.0
    copper = _read_change(tape_df, "HG=F") or 0.0

    risk_score = 50 + (es + nq + rty) * 850 - vix * 450
    if risk_score >= 65:
        risk = "CONSTRUCTIVE"
    elif risk_score <= 38:
        risk = "DEFENSIVE"
    else:
        risk = "BALANCED"

    vol = "RISING" if vix > 0.03 else "FALLING" if vix < -0.03 else "NORMAL"
    dollar = "STRONG" if dxy > 0.0025 else "WEAK" if dxy < -0.0025 else "NEUTRAL"

    rates_pressure_raw = 0.55 * tnx + 0.45 * fv
    rates = "HIGHER" if rates_pressure_raw > 0.003 else "LOWER" if rates_pressure_raw < -0.003 else "STABLE"

    commo_score = np.nanmean([oil, gold, copper]) if any(np.isfinite(x) for x in [oil, gold, copper]) else 0.0
    commodities = "BID" if commo_score > 0.004 else "OFFERED" if commo_score < -0.004 else "MIXED"

    read = (
        f"Risk {risk.lower()}, volatility {vol.lower()}, dollar {dollar.lower()}, "
        f"rates {rates.lower()}, commodities {commodities.lower()}."
    )

    return {
        "risk": risk,
        "vol": vol,
        "dollar": dollar,
        "rates": rates,
        "commodities": commodities,
        "read": read,
    }


def _render_regime_panel(regime: dict[str, Any]) -> None:
    st.markdown("<div class='cc-panel-title'>CROSS-ASSET REGIME</div>", unsafe_allow_html=True)

    rows = [
        ("Risk appetite", regime.get("risk", "N/A")),
        ("Volatility", regime.get("vol", "N/A")),
        ("Dollar", regime.get("dollar", "N/A")),
        ("Rates pressure", regime.get("rates", "N/A")),
        ("Commodities", regime.get("commodities", "N/A")),
    ]

    for label, value in rows:
        c1, c2 = st.columns([1.25, 1])
        with c1:
            st.markdown(f"<div class='cc-regime-label'>{label}</div>", unsafe_allow_html=True)
        with c2:
            st.markdown(f"<div class='cc-regime-value'>{value}</div>", unsafe_allow_html=True)

    st.caption(str(regime.get("read", "")))


# ============================================================
# GLOBAL COMMAND CENTER
# ============================================================

def render_global_command_center() -> None:
    """
    Page d'accueil post-JARVIS.
    Remplace la page statique de sélection par un vrai cockpit multi-asset.
    """
    inject_command_center_css()

    st.markdown(
        """
        <div class="cc-shell">
            <div class="cc-kicker">GLOBAL COMMAND CENTER</div>
            <div class="cc-title">Quant Terminal Multi-Asset Workspace</div>
            <div class="cc-sub">
                Recherche centrale, Market Tape, régime cross-asset, news et quick launch. 
                Tape un symbole directement : NVDA, EURUSD, USDJPY, CL=F, GC=F, ^TNX, TLT, ZN=F. 
                Le terminal infère la classe d'actif et charge les modules compatibles.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    current_asset = st.session_state.get("asset_class", "Equity")
    current_profile = get_asset_profile(current_asset)

    with st.form("global_command_center_form_v2"):
        c1, c2, c3, c4, c5, c6 = st.columns([1.05, 2.0, 1.15, 0.85, 0.85, 0.95])

        with c1:
            asset_choice = st.selectbox(
                "Asset Class",
                ["Auto"] + get_asset_classes(),
                index=0,
                key="gcc_asset_choice_v2",
            )

        with c2:
            raw_symbol = st.text_input(
                "Search / Command",
                value=st.session_state.get("ticker") or current_profile["default_symbol"],
                placeholder="NVDA, EURUSD, CL=F, ^TNX, TLT...",
                key="gcc_symbol_input_v2",
            )

        inferred_asset = infer_asset_class_from_symbol(raw_symbol, fallback=current_asset)
        effective_asset = inferred_asset if asset_choice == "Auto" else asset_choice
        effective_profile = get_asset_profile(effective_asset)

        with c3:
            mode_choice = st.selectbox(
                "Mode",
                effective_profile["mode_options"],
                index=0,
                key=f"gcc_mode_choice_v2_{effective_asset}",
            )

        with c4:
            period_choice = st.selectbox(
                "Period",
                ["3mo", "6mo", "1y", "2y", "5y", "10y"],
                index=_select_index(["3mo", "6mo", "1y", "2y", "5y", "10y"], effective_profile["default_period"], 2),
                key=f"gcc_period_choice_v2_{effective_asset}",
            )

        with c5:
            interval_choice = st.selectbox(
                "Interval",
                ["1d", "1wk", "1mo"],
                index=0,
                key=f"gcc_interval_choice_v2_{effective_asset}",
            )

        with c6:
            st.write("")
            launch = st.form_submit_button("LAUNCH", use_container_width=True)

        if launch:
            resolved_asset, resolved_symbol, resolved_mode = resolve_asset_symbol_and_mode(
                effective_asset,
                raw_symbol,
                mode_choice,
            )
            _launch_workspace(resolved_asset, resolved_symbol, period_choice, interval_choice, resolved_mode)

    st.caption(
        f"Inference preview : {infer_asset_class_from_symbol(raw_symbol, fallback=current_asset)} · "
        f"normalized symbol : {normalize_market_symbol(infer_asset_class_from_symbol(raw_symbol, fallback=current_asset), raw_symbol)}"
    )

    # Quick launch compact.
    qcols = st.columns(4)
    for col, asset_class in zip(qcols, get_asset_classes()):
        profile = get_asset_profile(asset_class)
        with col:
            if st.button(f"OPEN {profile['label']}", key=f"gcc_quick_open_{asset_class}", use_container_width=True):
                _launch_workspace(
                    asset_class=asset_class,
                    symbol=profile["default_symbol"],
                    period=profile["default_period"],
                    interval=profile["default_interval"],
                    mode=default_mode_for_asset(asset_class),
                )

    tape_df = load_market_tape_snapshot(tuple(MARKET_TAPE_UNIVERSES["Global"]))
    regime = build_cross_asset_regime(tape_df)
    news_df = load_latest_news_snapshot()

    st.markdown("---")

    st.markdown("<div class='cc-panel-title'>GLOBAL MARKET TAPE</div>", unsafe_allow_html=True)
    _render_tape_cards(tape_df, max_cards=8)

    left, right = st.columns([1.15, 1])

    with left:
        with st.container():
            st.markdown("<div class='cc-panel'>", unsafe_allow_html=True)
            _render_regime_panel(regime)
            st.markdown("</div>", unsafe_allow_html=True)

    with right:
        with st.container():
            st.markdown("<div class='cc-panel'>", unsafe_allow_html=True)
            _render_news_panel(news_df)
            st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")

    tab_names = ["Global", "Equity", "FX", "Commodities", "Rates"]
    tabs = st.tabs(tab_names)

    for tab, name in zip(tabs, tab_names):
        with tab:
            symbols = tuple(MARKET_TAPE_UNIVERSES.get(name, MARKET_TAPE_UNIVERSES["Global"]))
            df = load_market_tape_snapshot(symbols)

            if df.empty:
                st.info(f"{name} tape indisponible.")
            else:
                display = df.copy()
                display["Last"] = display["Last"].map(lambda x: _fmt_num(x))
                display["Change %"] = display["Change %"].map(lambda x: _fmt_pct(x))
                display["Volume"] = display["Volume"].map(lambda x: _fmt_compact_num(x))
                st.dataframe(display, use_container_width=True, hide_index=True)


def render_asset_class_home() -> None:
    """
    Backward-compatible entry point appelé par app.py.
    V2 : affiche le Global Command Center au lieu des 4 cartes statiques.
    """
    render_global_command_center()


# ============================================================
# SIDEBAR CONTROL — OPTIONAL
# ============================================================

def render_asset_control_sidebar() -> None:
    """
    Bloc optionnel à placer en haut de la sidebar.
    Permet de changer la classe d'actif sans revenir à la page d'accueil.
    """
    st.markdown("### Workspace")

    asset_classes = get_asset_classes()
    current_asset = st.session_state.get("asset_class", "Equity")
    current_asset = current_asset if current_asset in asset_classes else "Equity"

    selected_asset = st.selectbox(
        "Asset class",
        asset_classes,
        index=_select_index(asset_classes, current_asset, 0),
        key="sidebar_asset_class_selector_v2",
    )

    profile = get_asset_profile(selected_asset)
    current_ticker = st.session_state.get("ticker") or profile["default_symbol"]

    preset_options = profile["presets"]
    preset_default = current_ticker if current_ticker in preset_options else profile["default_symbol"]

    selected_symbol = st.selectbox(
        "Universe preset",
        preset_options,
        index=_select_index(preset_options, preset_default, 0),
        key=f"sidebar_symbol_preset_v2_{selected_asset}",
    )

    mode_options = profile["mode_options"]
    current_mode = st.session_state.get("mode_input") or default_mode_for_asset(selected_asset)
    selected_mode = st.selectbox(
        "Default mode",
        mode_options,
        index=_select_index(mode_options, current_mode, 0),
        key=f"sidebar_mode_selector_v2_{selected_asset}",
    )

    if st.button("Set workspace", use_container_width=True, key="sidebar_set_workspace_v2"):
        st.session_state["asset_class"] = selected_asset
        st.session_state["asset_class_selected"] = True
        st.session_state["ticker"] = selected_symbol
        st.session_state["mode_input"] = selected_mode
        st.session_state["terminal_command_mode"] = selected_mode
        st.rerun()


# ============================================================
# QUICK DASHBOARDS — COMPATIBILITY WITH APP.PY
# ============================================================

def _safe_price_frame(price_data: pd.DataFrame) -> pd.DataFrame:
    if price_data is None or price_data.empty:
        return pd.DataFrame()

    df = price_data.copy()
    df.columns = [str(c).lower() for c in df.columns]

    if "date" not in df.columns:
        df = df.reset_index().rename(columns={"index": "date"})

    if "close" not in df.columns:
        return pd.DataFrame()

    df["date"] = pd.to_datetime(df["date"], errors="coerce")

    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)


def render_generic_asset_dashboard(asset_class: str, ticker: str, price_data: pd.DataFrame, analysis: dict | None = None) -> None:
    profile = get_asset_profile(asset_class)
    df = _safe_price_frame(price_data)

    st.subheader(f"{profile['label']} Dashboard — {ticker}")
    st.caption(
        "Vue multi-asset générique : prix, rendements, volatilité, drawdown, régime simple et modules compatibles. "
        "Les couches spécifiques FX / commodities / rates seront ajoutées progressivement."
    )

    if df.empty:
        st.warning("Données prix indisponibles ou insuffisantes.")
        return

    close = df["close"].astype(float)
    returns = close.pct_change().dropna()

    last_price = float(close.iloc[-1])
    ret_20 = close.iloc[-1] / close.iloc[-21] - 1 if len(close) > 21 else None
    ret_60 = close.iloc[-1] / close.iloc[-61] - 1 if len(close) > 61 else None
    vol_20 = returns.tail(20).std() * (252 ** 0.5) if len(returns) >= 20 else None
    dd = close / close.cummax() - 1

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Last", _fmt_num(last_price))
    c2.metric("20D return", _fmt_pct(ret_20))
    c3.metric("60D return", _fmt_pct(ret_60))
    c4.metric("20D vol ann.", _fmt_pct(vol_20))
    c5.metric("Max drawdown", _fmt_pct(float(dd.min())))

    fig = go.Figure()

    if all(col in df.columns for col in ["open", "high", "low", "close"]):
        fig.add_trace(
            go.Candlestick(
                x=df["date"],
                open=df["open"],
                high=df["high"],
                low=df["low"],
                close=df["close"],
                name=ticker,
            )
        )
    else:
        fig.add_trace(go.Scatter(x=df["date"], y=df["close"], mode="lines", name=ticker))

    fig.update_layout(
        height=470,
        margin=dict(l=10, r=10, t=35, b=10),
        template="plotly_dark",
        title=f"{asset_class} price history — {ticker}",
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
    )

    st.plotly_chart(fig, use_container_width=True)

    with st.expander("Module availability for this asset class", expanded=True):
        module_rows = []

        for mode in profile["mode_options"]:
            comment = "Compatible avec cette classe d'actif."
            if asset_class == "Rates" and ticker.startswith("^") and mode == "Backtest Lab":
                comment = "Prudent : yield non directement tradable. Préférer SHY/IEF/TLT/ZN=F pour backtest exécutable."
            if asset_class != "Equity" and mode in {"Decision Engine Lite", "Options / Futures"}:
                comment = "Lecture proxy / partielle selon disponibilité données publiques."

            module_rows.append(
                {
                    "Module": mode,
                    "Status": "Available",
                    "Comment": comment,
                }
            )

        st.dataframe(pd.DataFrame(module_rows), use_container_width=True, hide_index=True)


def render_fx_dashboard(ticker: str, price_data: pd.DataFrame, analysis: dict | None = None) -> None:
    render_generic_asset_dashboard("FX", ticker, price_data, analysis)


def render_commodity_dashboard(ticker: str, price_data: pd.DataFrame, analysis: dict | None = None) -> None:
    render_generic_asset_dashboard("Commodities", ticker, price_data, analysis)


def render_rates_dashboard(ticker: str, price_data: pd.DataFrame, analysis: dict | None = None) -> None:
    render_generic_asset_dashboard("Rates", ticker, price_data, analysis)

# ============================================================
# MULTI-ASSET COMMAND CENTER V3 — INSTITUTIONAL COCKPIT OVERRIDE
# ============================================================
# Coller ce bloc à la fin de asset_class_router.py.
# Il surcharge uniquement les fonctions UI V2 sans modifier les moteurs métier.
# Objectifs :
# - remplir l'écran avec un vrai cockpit cross-asset ;
# - supprimer l'effet page vide après les premiers blocs ;
# - ajouter market pulse, movers, risk radar, boards par asset class ;
# - rendre le Launch compatible avec un auto-run côté app.py via auto_run_requested.
# ============================================================

from html import escape as _cc_escape


def _direction_label(change: Any) -> str:
    x = _safe_float(change)
    if x is None:
        return "WAIT"
    if x >= 0.01:
        return "STRONG BID"
    if x >= 0.0025:
        return "BID"
    if x <= -0.01:
        return "STRONG OFFER"
    if x <= -0.0025:
        return "OFFER"
    return "FLAT"


def _status_from_value(value: Any) -> str:
    return "OK" if _safe_float(value) is not None else "WAIT"


def _value_for_symbol(row: pd.Series) -> str:
    symbol = str(row.get("Symbol", ""))
    last = _safe_float(row.get("Last"))
    if last is None:
        return "N/A"
    if symbol in {"^IRX", "^FVX", "^TNX", "^TYX"}:
        return f"{last:.2f}"
    if symbol.endswith("=X") and last < 10:
        return f"{last:.4f}"
    return _fmt_num(last)


def _prepare_tape_display(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out["Last"] = out.apply(_value_for_symbol, axis=1)
    out["Change %"] = out["Change %"].map(lambda x: _fmt_pct(x))
    out["Volume"] = out["Volume"].map(lambda x: _fmt_compact_num(x))
    out["Direction"] = df["Change %"].map(_direction_label)
    out["Status"] = df["Last"].map(_status_from_value)
    return out[["Symbol", "Name", "Last", "Change %", "Direction", "Volume", "Status"]]


def _asset_bucket(symbol: str) -> str:
    symbol = str(symbol or "").upper().strip()
    if symbol in {"ES=F", "NQ=F", "YM=F", "RTY=F", "SPY", "QQQ", "IWM", "SMH", "XLF", "XLE", "XLK"}:
        return "Equity"
    if symbol in {"^VIX"}:
        return "Volatility"
    if symbol in FX_YAHOO:
        return "FX"
    if symbol in COMMODITY_FUTURES:
        return "Commodities"
    if symbol in RATES_SYMBOLS:
        return "Rates"
    return "Other"


def build_market_overview_v3(tape_df: pd.DataFrame) -> pd.DataFrame:
    if tape_df is None or tape_df.empty:
        return pd.DataFrame()
    work = tape_df.copy()
    work["Bucket"] = work["Symbol"].map(_asset_bucket)
    work["_change"] = pd.to_numeric(work["Change %"], errors="coerce")
    rows = []
    for bucket in ["Equity", "Volatility", "FX", "Rates", "Commodities"]:
        sub = work.loc[work["Bucket"] == bucket].dropna(subset=["_change"])
        if sub.empty:
            rows.append({"Bloc": bucket, "Avg move": "N/A", "Breadth": "N/A", "Leader": "N/A", "Lag": "N/A", "Regime": "WAIT"})
            continue
        avg_move = float(sub["_change"].mean())
        breadth = float((sub["_change"] > 0).mean())
        leader = sub.sort_values("_change", ascending=False).iloc[0]
        lag = sub.sort_values("_change", ascending=True).iloc[0]
        if avg_move > 0.004 and breadth >= 0.60:
            regime = "BID"
        elif avg_move < -0.004 and breadth <= 0.40:
            regime = "OFFERED"
        else:
            regime = "MIXED"
        rows.append({
            "Bloc": bucket,
            "Avg move": _fmt_pct(avg_move),
            "Breadth": f"{breadth:.0%}",
            "Leader": f"{leader.get('Symbol')} {_fmt_pct(leader.get('Change %'))}",
            "Lag": f"{lag.get('Symbol')} {_fmt_pct(lag.get('Change %'))}",
            "Regime": regime,
        })
    return pd.DataFrame(rows)


def build_movers_v3(tape_df: pd.DataFrame, n: int = 5) -> tuple[pd.DataFrame, pd.DataFrame]:
    if tape_df is None or tape_df.empty:
        return pd.DataFrame(), pd.DataFrame()
    work = tape_df.copy()
    work["_change"] = pd.to_numeric(work["Change %"], errors="coerce")
    work = work.dropna(subset=["_change"])
    if work.empty:
        return pd.DataFrame(), pd.DataFrame()
    keep = ["Symbol", "Name", "Last", "Change %", "Volume", "Status"]
    gainers = work.sort_values("_change", ascending=False).head(n)[keep].copy()
    losers = work.sort_values("_change", ascending=True).head(n)[keep].copy()
    for frame in [gainers, losers]:
        frame["Last"] = frame.apply(_value_for_symbol, axis=1)
        frame["Change %"] = frame["Change %"].map(lambda x: _fmt_pct(x))
        frame["Volume"] = frame["Volume"].map(lambda x: _fmt_compact_num(x))
    return gainers, losers


def build_curve_snapshot_v3(tape_df: pd.DataFrame) -> pd.DataFrame:
    if tape_df is None or tape_df.empty:
        return pd.DataFrame()
    rows = []
    def last(symbol: str) -> float | None:
        try:
            sub = tape_df.loc[tape_df["Symbol"] == symbol]
            if sub.empty:
                return None
            return _safe_float(sub.iloc[0].get("Last"))
        except Exception:
            return None
    irx, fvx, tnx, tyx = last("^IRX"), last("^FVX"), last("^TNX"), last("^TYX")
    spreads = [
        ("5Y - 3M", None if fvx is None or irx is None else fvx - irx),
        ("10Y - 3M", None if tnx is None or irx is None else tnx - irx),
        ("30Y - 10Y", None if tyx is None or tnx is None else tyx - tnx),
    ]
    for label, value in spreads:
        if value is None:
            regime = "WAIT"
            display = "N/A"
        else:
            display = f"{value:.2f}"
            regime = "STEEP" if value > 0.75 else "FLAT" if value > 0.10 else "INVERTED"
        rows.append({"Curve spread": label, "Value": display, "Regime": regime})
    return pd.DataFrame(rows)


def build_fx_board_v3() -> pd.DataFrame:
    symbols = tuple(MARKET_TAPE_UNIVERSES.get("FX", []))
    df = load_market_tape_snapshot(symbols)
    if df.empty:
        return pd.DataFrame()
    out = _prepare_tape_display(df)
    return out[["Symbol", "Name", "Last", "Change %", "Direction", "Status"]]


def build_commodity_board_v3() -> pd.DataFrame:
    symbols = tuple(MARKET_TAPE_UNIVERSES.get("Commodities", []))
    df = load_market_tape_snapshot(symbols)
    if df.empty:
        return pd.DataFrame()
    out = _prepare_tape_display(df)
    return out[["Symbol", "Name", "Last", "Change %", "Direction", "Status"]]


def _render_panel_header_v3(title: str, subtitle: str | None = None) -> None:
    sub = f"<div class='cc-v3-panel-sub'>{_cc_escape(subtitle)}</div>" if subtitle else ""
    st.markdown(
        f"""
        <div class="cc-v3-panel-head">
            <div class="cc-v3-panel-title">{_cc_escape(title)}</div>
            {sub}
        </div>
        """,
        unsafe_allow_html=True,
    )


def inject_command_center_css() -> None:
    """
    Override V3 du thème command center.
    """
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.35rem !important; }
        .cc-v3-hero {
            border: 1px solid rgba(86, 214, 255, 0.22);
            background:
                radial-gradient(circle at 12% 0%, rgba(65, 210, 255, 0.18), transparent 28%),
                radial-gradient(circle at 88% 8%, rgba(70, 110, 255, 0.14), transparent 28%),
                linear-gradient(180deg, rgba(3, 12, 28, .98), rgba(2, 7, 18, .98));
            border-radius: 24px;
            padding: 22px 26px 18px 26px;
            margin-bottom: 12px;
            box-shadow: 0 0 45px rgba(34, 168, 255, .10);
        }
        .cc-v3-kicker { color:#55e8ff; font-weight:950; letter-spacing:.25em; font-size:.72rem; text-transform:uppercase; }
        .cc-v3-title { color:#f8fbff; font-size:2.15rem; font-weight:950; line-height:1.05; margin-top:6px; }
        .cc-v3-sub { color:rgba(222,235,248,.72); font-size:.92rem; max-width:1180px; line-height:1.38; margin-top:8px; }
        .cc-v3-strip {
            display:grid; grid-template-columns: repeat(6, 1fr); gap:10px; margin:10px 0 14px 0;
        }
        .cc-v3-strip-card {
            border:1px solid rgba(90,205,255,.18); border-radius:16px; padding:12px 12px;
            background:rgba(4,14,29,.74); min-height:76px;
        }
        .cc-v3-strip-label { color:rgba(220,235,250,.60); font-size:.67rem; font-weight:850; letter-spacing:.12em; text-transform:uppercase; }
        .cc-v3-strip-value { color:#f8fbff; font-size:1.04rem; font-weight:900; margin-top:6px; }
        .cc-v3-strip-meta { color:rgba(85,232,255,.78); font-size:.70rem; font-weight:800; margin-top:2px; }
        .cc-v3-panel {
            border:1px solid rgba(90,205,255,.18); border-radius:18px;
            background:linear-gradient(180deg, rgba(6,19,40,.80), rgba(3,10,24,.82));
            padding:14px 14px 15px 14px; min-height:214px;
            box-shadow: inset 0 0 30px rgba(80,180,255,.035);
        }
        .cc-v3-panel-head { margin-bottom:9px; }
        .cc-v3-panel-title { color:#55e8ff; font-size:.76rem; font-weight:950; letter-spacing:.20em; text-transform:uppercase; }
        .cc-v3-panel-sub { color:rgba(220,235,250,.52); font-size:.72rem; margin-top:3px; }
        .cc-v3-tape-card {
            border:1px solid rgba(90,205,255,.14); background:rgba(2,10,23,.72);
            border-radius:14px; padding:10px 11px; min-height:84px;
        }
        .cc-v3-tape-name { color:rgba(230,244,255,.70); font-size:.69rem; font-weight:850; letter-spacing:.08em; text-transform:uppercase; margin-bottom:5px; }
        .cc-v3-tape-value { color:#f8fbff; font-size:.98rem; font-weight:900; }
        .cc-v3-pos { color:#62ffbf; font-weight:850; }
        .cc-v3-neg { color:#ff7b7b; font-weight:850; }
        .cc-v3-flat { color:rgba(235,245,255,.62); font-weight:850; }
        .cc-v3-news-item { border-bottom:1px solid rgba(90,205,255,.10); padding:7px 0 9px 0; }
        .cc-v3-news-title { color:rgba(245,249,255,.94); font-size:.82rem; font-weight:760; line-height:1.25; }
        .cc-v3-news-meta { color:rgba(180,205,225,.58); font-size:.69rem; margin-top:3px; }
        .cc-v3-module-grid { display:grid; grid-template-columns: repeat(4, 1fr); gap:9px; }
        .cc-v3-module {
            border:1px solid rgba(90,205,255,.14); border-radius:13px; padding:10px 11px;
            background:rgba(2,10,23,.66);
        }
        .cc-v3-module-name { color:#f8fbff; font-size:.82rem; font-weight:900; }
        .cc-v3-module-meta { color:rgba(220,235,250,.56); font-size:.68rem; margin-top:4px; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_compact_tape_v3(df: pd.DataFrame, max_cards: int = 12) -> None:
    if df is None or df.empty:
        st.info("Market tape indisponible.")
        return
    show = df.head(max_cards).copy()
    rows = [show.iloc[i:i+6] for i in range(0, len(show), 6)]
    for row_block in rows:
        cols = st.columns(len(row_block))
        for col, (_, row) in zip(cols, row_block.iterrows()):
            change = _safe_float(row.get("Change %"))
            css = "cc-v3-flat"
            if change is not None and change > 0:
                css = "cc-v3-pos"
            elif change is not None and change < 0:
                css = "cc-v3-neg"
            with col:
                st.markdown(
                    f"""
                    <div class="cc-v3-tape-card">
                        <div class="cc-v3-tape-name">{_cc_escape(str(row.get('Name', row.get('Symbol', 'N/A'))))}</div>
                        <div class="cc-v3-tape-value">{_cc_escape(_value_for_symbol(row))}</div>
                        <div class="{css}">{_cc_escape(_fmt_pct(row.get('Change %')))}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


def _render_news_panel_v3(news_df: pd.DataFrame) -> None:
    _render_panel_header_v3("Latest News", "Global macro / watchlist feed via public sources")
    if news_df is None or news_df.empty:
        st.caption("News feed indisponible via yfinance dans cette session. Branchement FMP/Finnhub/NewsAPI prévu ensuite.")
        return
    for _, row in news_df.head(7).iterrows():
        headline = _cc_escape(str(row.get("Headline", ""))[:190])
        source = _cc_escape(str(row.get("Source", "N/A")))
        published = _cc_escape(str(row.get("Published", "N/A")))
        symbol = _cc_escape(str(row.get("Symbol", "")))
        st.markdown(
            f"""
            <div class="cc-v3-news-item">
                <div class="cc-v3-news-title">{headline}</div>
                <div class="cc-v3-news-meta">{symbol} · {source} · {published}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _render_regime_panel_v3(regime: dict[str, Any], overview: pd.DataFrame) -> None:
    _render_panel_header_v3("Cross-Asset Regime", "Risk, vol, dollar, rates and commodity pressure")
    c1, c2, c3, c4, c5 = st.columns(5)
    items = [
        ("Risk", regime.get("risk", "N/A")),
        ("Vol", regime.get("vol", "N/A")),
        ("Dollar", regime.get("dollar", "N/A")),
        ("Rates", regime.get("rates", "N/A")),
        ("Commo", regime.get("commodities", "N/A")),
    ]
    for col, (label, value) in zip([c1, c2, c3, c4, c5], items):
        col.metric(label, value)
    st.caption(str(regime.get("read", "")))
    if overview is not None and not overview.empty:
        st.dataframe(overview, use_container_width=True, hide_index=True)


def _render_quick_modules_v3(asset_class: str) -> None:
    profile = get_asset_profile(asset_class)
    _render_panel_header_v3("Module Launchpad", f"Modules compatibles : {profile['label']}")
    modes = profile.get("mode_options", [])
    safe_modes = modes[:8]
    html = ['<div class="cc-v3-module-grid">']
    for mode in safe_modes:
        meta = "Core analytics"
        if "Backtest" in mode:
            meta = "Strategy validation"
        elif "Risk" in mode:
            meta = "Pre-trade risk"
        elif "Monte" in mode:
            meta = "Scenario engine"
        elif "Correlation" in mode:
            meta = "Cross-asset map"
        elif "Dashboard" in mode:
            meta = "Asset overview"
        html.append(
            f'<div class="cc-v3-module"><div class="cc-v3-module-name">{_cc_escape(mode)}</div><div class="cc-v3-module-meta">{_cc_escape(meta)}</div></div>'
        )
    html.append('</div>')
    st.markdown("".join(html), unsafe_allow_html=True)


def render_global_command_center() -> None:
    """
    V3 : vrai cockpit post-JARVIS.
    Le lancement prépare le workspace et demande à app.py de déclencher l'analyse automatiquement.
    """
    inject_command_center_css()

    current_asset = st.session_state.get("asset_class", "Equity")
    current_profile = get_asset_profile(current_asset)

    st.markdown(
        """
        <div class="cc-v3-hero">
            <div class="cc-v3-kicker">GLOBAL COMMAND CENTER</div>
            <div class="cc-v3-title">Institutional Multi-Asset Cockpit</div>
            <div class="cc-v3-sub">
                Recherche centrale, market tape, régime cross-asset, courbe des taux, FX board, commodities board, news et quick launch.
                Tape directement NVDA, EURUSD, USDJPY, CL=F, GC=F, ^TNX, TLT ou ZN=F : le terminal infère l'univers et prépare les modules compatibles.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form("global_command_center_form_v3"):
        c1, c2, c3, c4, c5, c6 = st.columns([1.0, 2.25, 1.25, 0.85, 0.85, 1.0], vertical_alignment="bottom")
        with c1:
            asset_choice = st.selectbox("Asset Class", ["Auto"] + get_asset_classes(), index=0, key="gcc_asset_choice_v3")
        with c2:
            raw_symbol = st.text_input(
                "Search / Command",
                value=st.session_state.get("ticker") or current_profile["default_symbol"],
                placeholder="NVDA, EURUSD, CL=F, ^TNX, TLT...",
                key="gcc_symbol_input_v3",
            )
        inferred_asset = infer_asset_class_from_symbol(raw_symbol, fallback=current_asset)
        effective_asset = inferred_asset if asset_choice == "Auto" else asset_choice
        effective_profile = get_asset_profile(effective_asset)
        with c3:
            mode_choice = st.selectbox("Mode", effective_profile["mode_options"], index=0, key=f"gcc_mode_choice_v3_{effective_asset}")
        with c4:
            period_choice = st.selectbox("Period", ["3mo", "6mo", "1y", "2y", "5y", "10y"], index=_select_index(["3mo", "6mo", "1y", "2y", "5y", "10y"], effective_profile["default_period"], 2), key=f"gcc_period_choice_v3_{effective_asset}")
        with c5:
            interval_choice = st.selectbox("Interval", ["1d", "1wk", "1mo"], index=0, key=f"gcc_interval_choice_v3_{effective_asset}")
        with c6:
            launch = st.form_submit_button("LAUNCH", use_container_width=True)
        if launch:
            resolved_asset, resolved_symbol, resolved_mode = resolve_asset_symbol_and_mode(effective_asset, raw_symbol, mode_choice)
            _launch_workspace(resolved_asset, resolved_symbol, period_choice, interval_choice, resolved_mode)

    resolved_preview_asset, resolved_preview_symbol, resolved_preview_mode = resolve_asset_symbol_and_mode(effective_asset, raw_symbol, mode_choice)
    st.caption(f"Inference preview : {resolved_preview_asset} · normalized symbol : {resolved_preview_symbol} · mode : {resolved_preview_mode}")

    tape_df = load_market_tape_snapshot(tuple(MARKET_TAPE_UNIVERSES["Global"]))
    regime = build_cross_asset_regime(tape_df)
    overview = build_market_overview_v3(tape_df)
    news_df = load_latest_news_snapshot(limit=10)
    gainers, losers = build_movers_v3(tape_df, n=5)
    curve_df = build_curve_snapshot_v3(tape_df)

    if tape_df is not None and not tape_df.empty:
        lookup = {row.get("Symbol"): row for _, row in tape_df.iterrows()}
        strip_items = [
            ("S&P FUT", lookup.get("ES=F")),
            ("NASDAQ FUT", lookup.get("NQ=F")),
            ("VIX", lookup.get("^VIX")),
            ("DXY", lookup.get("DX-Y.NYB")),
            ("10Y", lookup.get("^TNX")),
            ("WTI", lookup.get("CL=F")),
        ]
        html = ['<div class="cc-v3-strip">']
        for label, row in strip_items:
            if row is None:
                value, meta = "N/A", "WAIT"
            else:
                value, meta = _value_for_symbol(row), _fmt_pct(row.get("Change %"))
            html.append(f'<div class="cc-v3-strip-card"><div class="cc-v3-strip-label">{_cc_escape(label)}</div><div class="cc-v3-strip-value">{_cc_escape(value)}</div><div class="cc-v3-strip-meta">{_cc_escape(meta)}</div></div>')
        html.append('</div>')
        st.markdown("".join(html), unsafe_allow_html=True)

    st.markdown("---")
    _render_panel_header_v3("Global Market Tape", "Cross-asset instruments and public proxies")
    _render_compact_tape_v3(tape_df, max_cards=12)

    st.markdown("---")
    left, mid, right = st.columns([1.20, 1.0, 1.10])
    with left:
        st.markdown('<div class="cc-v3-panel">', unsafe_allow_html=True)
        _render_regime_panel_v3(regime, overview)
        st.markdown('</div>', unsafe_allow_html=True)
    with mid:
        st.markdown('<div class="cc-v3-panel">', unsafe_allow_html=True)
        _render_panel_header_v3("Rates / Curve", "Yield proxies and curve state")
        if curve_df.empty:
            st.caption("Curve snapshot indisponible.")
        else:
            st.dataframe(curve_df, use_container_width=True, hide_index=True)
        st.markdown("<br>", unsafe_allow_html=True)
        _render_panel_header_v3("Top Movers", "Current global tape")
        mtab1, mtab2 = st.tabs(["Gainers", "Losers"])
        with mtab1:
            st.dataframe(gainers, use_container_width=True, hide_index=True)
        with mtab2:
            st.dataframe(losers, use_container_width=True, hide_index=True)
        st.markdown('</div>', unsafe_allow_html=True)
    with right:
        st.markdown('<div class="cc-v3-panel">', unsafe_allow_html=True)
        _render_news_panel_v3(news_df)
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("---")
    b1, b2, b3 = st.columns([1, 1, 1])
    with b1:
        st.markdown('<div class="cc-v3-panel">', unsafe_allow_html=True)
        _render_panel_header_v3("FX Board", "Majors and dollar regime")
        fx_board = build_fx_board_v3()
        st.dataframe(fx_board, use_container_width=True, hide_index=True)
        st.markdown('</div>', unsafe_allow_html=True)
    with b2:
        st.markdown('<div class="cc-v3-panel">', unsafe_allow_html=True)
        _render_panel_header_v3("Commodities Board", "Energy, metals and agricultural proxies")
        commo_board = build_commodity_board_v3()
        st.dataframe(commo_board, use_container_width=True, hide_index=True)
        st.markdown('</div>', unsafe_allow_html=True)
    with b3:
        st.markdown('<div class="cc-v3-panel">', unsafe_allow_html=True)
        _render_quick_modules_v3(resolved_preview_asset)
        st.markdown("<br>", unsafe_allow_html=True)
        qcols = st.columns(2)
        for idx, asset_class in enumerate(get_asset_classes()):
            profile = get_asset_profile(asset_class)
            with qcols[idx % 2]:
                if st.button(f"OPEN {profile['label']}", key=f"gcc_quick_open_v3_{asset_class}", use_container_width=True):
                    _launch_workspace(asset_class, profile["default_symbol"], profile["default_period"], profile["default_interval"], default_mode_for_asset(asset_class))
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("---")
    tab_names = ["Global", "Equity", "FX", "Commodities", "Rates"]
    tabs = st.tabs(tab_names)
    for tab, name in zip(tabs, tab_names):
        with tab:
            symbols = tuple(MARKET_TAPE_UNIVERSES.get(name, MARKET_TAPE_UNIVERSES["Global"]))
            df = load_market_tape_snapshot(symbols)
            display = _prepare_tape_display(df)
            if display.empty:
                st.info(f"{name} tape indisponible.")
            else:
                st.dataframe(display, use_container_width=True, hide_index=True)


def render_asset_class_home() -> None:
    """Entrée backward-compatible appelée par app.py."""
    render_global_command_center()


def _launch_workspace(asset_class: str, symbol: str, period: str, interval: str, mode: str) -> None:
    """
    Override V3 : prépare le workspace et demande à app.py d'auto-lancer l'analyse.
    Nécessite le petit patch app.py fourni séparément.
    """
    asset_class, symbol, mode = resolve_asset_symbol_and_mode(asset_class, symbol, mode)
    profile = get_asset_profile(asset_class)
    # Standard ticker workspaces close autonomous Command Center views.
    st.session_state["quant_ai_open"] = False
    st.session_state["market_psychology_lab_open"] = False
    st.session_state["worldmonitor_v211_open"] = False

    st.session_state["asset_class"] = asset_class
    st.session_state["asset_class_selected"] = True
    st.session_state["ticker"] = symbol
    st.session_state["mode_input"] = mode
    st.session_state["terminal_command_mode"] = mode
    st.session_state["auto_run_requested"] = True
    st.session_state["last_params"] = {
        "ticker": symbol,
        "period": period or profile["default_period"],
        "interval": interval or profile["default_interval"],
        "asset_class": asset_class,
    }

    # Persist only non-sensitive navigation state so the selected workspace
    # survives Streamlit session loss and a full browser refresh.
    st.query_params["workspace"] = "terminal"
    st.query_params["asset"] = asset_class
    st.query_params["symbol"] = symbol
    st.query_params["period"] = period or profile["default_period"]
    st.query_params["interval"] = interval or profile["default_interval"]
    st.query_params["mode"] = mode
    st.rerun()


def render_asset_control_sidebar() -> None:
    """Sidebar V3 : contrôle actif + retour Command Center."""
    st.markdown("### Workspace")

    if st.button("Global Command Center", use_container_width=True, key="sidebar_back_to_gcc_v3"):
        st.session_state["quant_ai_open"] = False
        st.session_state["market_psychology_lab_open"] = False
        st.session_state["worldmonitor_v211_open"] = False
        st.session_state["asset_class_selected"] = False
        st.query_params.clear()
        st.rerun()
    
    if st.button("WorldMonitor", use_container_width=True, key="sidebar_open_worldmonitor_v211"):
        st.session_state["worldmonitor_v211_open"] = True
        st.session_state["market_psychology_lab_open"] = False
        st.session_state["quant_ai_open"] = False
        st.session_state["asset_class_selected"] = True
        st.rerun()

    if st.button(
        "Market Psychology Lab",
        use_container_width=True,
        key="sidebar_open_market_psychology_lab_v1",
    ):
        st.session_state["market_psychology_lab_open"] = True
        st.session_state["worldmonitor_v211_open"] = False
        st.session_state["quant_ai_open"] = False
        st.session_state["asset_class_selected"] = True
        st.rerun()

    if st.button(
        "Quant AI · CIO",
        use_container_width=True,
        key="sidebar_open_quant_ai_v1",
    ):
        st.session_state["quant_ai_open"] = True
        st.session_state["market_psychology_lab_open"] = False
        st.session_state["worldmonitor_v211_open"] = False
        st.session_state["asset_class_selected"] = True
        st.rerun()

    asset_classes = get_asset_classes()
    current_asset = st.session_state.get("asset_class", "Equity")
    current_asset = current_asset if current_asset in asset_classes else "Equity"

    selected_asset = st.selectbox(
        "Asset class",
        asset_classes,
        index=_select_index(asset_classes, current_asset, 0),
        key="sidebar_asset_class_selector_v3",
    )

    profile = get_asset_profile(selected_asset)
    current_ticker = st.session_state.get("ticker") or profile["default_symbol"]
    preset_options = profile["presets"]
    preset_default = current_ticker if current_ticker in preset_options else profile["default_symbol"]

    selected_symbol = st.selectbox(
        "Universe preset",
        preset_options,
        index=_select_index(preset_options, preset_default, 0),
        key=f"sidebar_symbol_preset_v3_{selected_asset}",
    )

    mode_options = profile["mode_options"]
    current_mode = st.session_state.get("mode_input") or default_mode_for_asset(selected_asset)
    selected_mode = st.selectbox(
        "Default mode",
        mode_options,
        index=_select_index(mode_options, current_mode, 0),
        key=f"sidebar_mode_selector_v3_{selected_asset}",
    )

    cols = st.columns(2)
    with cols[0]:
        if st.button("Set", use_container_width=True, key="sidebar_set_workspace_v3"):
            st.session_state["asset_class"] = selected_asset
            st.session_state["asset_class_selected"] = True
            st.session_state["ticker"] = selected_symbol
            st.session_state["mode_input"] = selected_mode
            st.session_state["terminal_command_mode"] = selected_mode
            st.rerun()
    with cols[1]:
        if st.button("Set + Run", use_container_width=True, key="sidebar_set_run_workspace_v3"):
            _launch_workspace(selected_asset, selected_symbol, profile["default_period"], profile["default_interval"], selected_mode)


# ============================================================
# END MULTI-ASSET COMMAND CENTER V3 OVERRIDE
# ============================================================

# ============================================================
# MULTI-ASSET COMMAND CENTER V4 — LIVE CURVES / DATABENTO BRIDGE
# ============================================================
# Objectif V4 :
# - Ajouter de vraies courbes intraday/live au cockpit et aux dashboards FX/Commo/Rates.
# - Utiliser Databento si DATABENTO_API_KEY est disponible.
# - Fallback automatique yfinance si Databento n'est pas installé, pas configuré, ou pas couvert.
# - Ne pas modifier les moteurs Backtest / Risk / Monte Carlo / Decision.
# ============================================================

import os
from datetime import datetime, timedelta, timezone


# ------------------------------------------------------------
# Provider registry
# ------------------------------------------------------------
# Databento couvre très bien futures / options / equities selon datasets.
# Spot FX n'est pas traité comme spot ici : on mappe vers les futures CME 6E/6J/6B/etc.
# Cela donne une vraie courbe tradable/proxy lorsque l'utilisateur regarde EURUSD=X.

DATABENTO_PROXY_MAP: dict[str, dict[str, Any]] = {
    # Equity index futures — CME Globex MDP3 parent symbology
    "ES=F": {"dataset": "GLBX.MDP3", "symbol": "ES.FUT", "stype_in": "parent", "schema": "ohlcv-1m", "label": "S&P 500 E-mini", "proxy_note": "CME parent future"},
    "NQ=F": {"dataset": "GLBX.MDP3", "symbol": "NQ.FUT", "stype_in": "parent", "schema": "ohlcv-1m", "label": "Nasdaq 100 E-mini", "proxy_note": "CME parent future"},
    "YM=F": {"dataset": "GLBX.MDP3", "symbol": "YM.FUT", "stype_in": "parent", "schema": "ohlcv-1m", "label": "Dow E-mini", "proxy_note": "CBOT parent future"},
    "RTY=F": {"dataset": "GLBX.MDP3", "symbol": "RTY.FUT", "stype_in": "parent", "schema": "ohlcv-1m", "label": "Russell 2000 E-mini", "proxy_note": "CME parent future"},

    # FX via CME currency futures proxies
    "EURUSD=X": {"dataset": "GLBX.MDP3", "symbol": "6E.FUT", "stype_in": "parent", "schema": "ohlcv-1m", "label": "EUR/USD via 6E", "proxy_note": "CME Euro FX future proxy, not spot FX"},
    "GBPUSD=X": {"dataset": "GLBX.MDP3", "symbol": "6B.FUT", "stype_in": "parent", "schema": "ohlcv-1m", "label": "GBP/USD via 6B", "proxy_note": "CME British Pound future proxy, not spot FX"},
    "USDJPY=X": {"dataset": "GLBX.MDP3", "symbol": "6J.FUT", "stype_in": "parent", "schema": "ohlcv-1m", "label": "JPY futures via 6J", "proxy_note": "CME Japanese Yen future proxy; quote convention differs from USDJPY spot"},
    "USDCHF=X": {"dataset": "GLBX.MDP3", "symbol": "6S.FUT", "stype_in": "parent", "schema": "ohlcv-1m", "label": "CHF futures via 6S", "proxy_note": "CME Swiss Franc future proxy; quote convention differs from USDCHF spot"},
    "AUDUSD=X": {"dataset": "GLBX.MDP3", "symbol": "6A.FUT", "stype_in": "parent", "schema": "ohlcv-1m", "label": "AUD/USD via 6A", "proxy_note": "CME Australian Dollar future proxy, not spot FX"},
    "USDCAD=X": {"dataset": "GLBX.MDP3", "symbol": "6C.FUT", "stype_in": "parent", "schema": "ohlcv-1m", "label": "CAD futures via 6C", "proxy_note": "CME Canadian Dollar future proxy; quote convention differs from USDCAD spot"},

    # Rates futures
    "ZT=F": {"dataset": "GLBX.MDP3", "symbol": "ZT.FUT", "stype_in": "parent", "schema": "ohlcv-1m", "label": "2Y Note future", "proxy_note": "CBOT parent future"},
    "ZF=F": {"dataset": "GLBX.MDP3", "symbol": "ZF.FUT", "stype_in": "parent", "schema": "ohlcv-1m", "label": "5Y Note future", "proxy_note": "CBOT parent future"},
    "ZN=F": {"dataset": "GLBX.MDP3", "symbol": "ZN.FUT", "stype_in": "parent", "schema": "ohlcv-1m", "label": "10Y Note future", "proxy_note": "CBOT parent future"},
    "ZB=F": {"dataset": "GLBX.MDP3", "symbol": "ZB.FUT", "stype_in": "parent", "schema": "ohlcv-1m", "label": "30Y Bond future", "proxy_note": "CBOT parent future"},

    # Commodities futures
    "CL=F": {"dataset": "GLBX.MDP3", "symbol": "CL.FUT", "stype_in": "parent", "schema": "ohlcv-1m", "label": "WTI Crude", "proxy_note": "NYMEX parent future"},
    "NG=F": {"dataset": "GLBX.MDP3", "symbol": "NG.FUT", "stype_in": "parent", "schema": "ohlcv-1m", "label": "Natural Gas", "proxy_note": "NYMEX parent future"},
    "GC=F": {"dataset": "GLBX.MDP3", "symbol": "GC.FUT", "stype_in": "parent", "schema": "ohlcv-1m", "label": "Gold", "proxy_note": "COMEX parent future"},
    "SI=F": {"dataset": "GLBX.MDP3", "symbol": "SI.FUT", "stype_in": "parent", "schema": "ohlcv-1m", "label": "Silver", "proxy_note": "COMEX parent future"},
    "HG=F": {"dataset": "GLBX.MDP3", "symbol": "HG.FUT", "stype_in": "parent", "schema": "ohlcv-1m", "label": "Copper", "proxy_note": "COMEX parent future"},
    "ZC=F": {"dataset": "GLBX.MDP3", "symbol": "ZC.FUT", "stype_in": "parent", "schema": "ohlcv-1m", "label": "Corn", "proxy_note": "CBOT parent future"},
    "ZS=F": {"dataset": "GLBX.MDP3", "symbol": "ZS.FUT", "stype_in": "parent", "schema": "ohlcv-1m", "label": "Soybeans", "proxy_note": "CBOT parent future"},
}


LIVE_CHART_DEFAULTS = {
    "Equity": ["ES=F", "NQ=F", "NVDA", "QQQ"],
    "FX": ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "DX-Y.NYB"],
    "Commodities": ["CL=F", "GC=F", "NG=F", "HG=F"],
    "Rates": ["ZN=F", "ZB=F", "TLT", "^TNX"],
    "Global": ["ES=F", "NQ=F", "EURUSD=X", "CL=F"],
}


def _get_databento_key_v4() -> str:
    try:
        key = st.secrets.get("DATABENTO_API_KEY", "")
    except Exception:
        key = ""
    if not key:
        key = os.getenv("DATABENTO_API_KEY", "")
    return str(key or "").strip()


def databento_configured_v4() -> bool:
    return bool(_get_databento_key_v4())


def _normalize_live_symbol_v4(symbol: str) -> str:
    symbol = str(symbol or "").strip().upper()
    # Keep Yahoo-style FX aliases consistent with the router.
    compact = symbol.replace("/", "").replace("-", "")
    if compact in {"EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD"}:
        return f"{compact}=X"
    return symbol


def _standardize_ohlcv_frame_v4(df: pd.DataFrame, source: str, symbol: str, provider_symbol: str | None = None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    work = df.copy()

    if isinstance(work.index, pd.DatetimeIndex):
        work = work.reset_index()

    work.columns = [str(c).lower().replace(" ", "_") for c in work.columns]

    # Databento usually returns ts_event as index/column. yfinance returns datetime/date.
    date_col = None
    for candidate in ["ts_event", "datetime", "date", "index"]:
        if candidate in work.columns:
            date_col = candidate
            break

    if date_col is None:
        # Fallback: first datetime-like column.
        for col in work.columns:
            if "time" in col or "date" in col or "ts_" in col:
                date_col = col
                break

    if date_col is None or "close" not in work.columns:
        return pd.DataFrame()

    rename_map = {date_col: "date"}
    for col in ["open", "high", "low", "close", "volume"]:
        if col in work.columns:
            rename_map[col] = col

    work = work.rename(columns=rename_map)
    keep_cols = [c for c in ["date", "open", "high", "low", "close", "volume"] if c in work.columns]
    work = work[keep_cols].copy()

    work["date"] = pd.to_datetime(work["date"], errors="coerce", utc=True)

    for col in ["open", "high", "low", "close", "volume"]:
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce")

    if "volume" not in work.columns:
        work["volume"] = np.nan

    work = work.dropna(subset=["date", "close"]).sort_values("date").drop_duplicates("date")
    if work.empty:
        return pd.DataFrame()

    # Some feeds may provide only close; synthesize OHLC for line fallback.
    for col in ["open", "high", "low"]:
        if col not in work.columns:
            work[col] = work["close"]
        else:
            work[col] = work[col].fillna(work["close"])

    work["source"] = source
    work["symbol"] = symbol
    work["provider_symbol"] = provider_symbol or symbol
    return work.reset_index(drop=True)


@st.cache_data(ttl=20, show_spinner=False)
def fetch_databento_ohlcv_v4(symbol: str, lookback_minutes: int = 390, schema: str = "ohlcv-1m") -> pd.DataFrame:
    """
    Databento historical intraday pull used as a live-ish curve.
    Streamlit is pull-based; true streaming should later run in a background service.
    """
    symbol = _normalize_live_symbol_v4(symbol)
    cfg = DATABENTO_PROXY_MAP.get(symbol)
    key = _get_databento_key_v4()

    if not cfg or not key:
        return pd.DataFrame()

    try:
        import databento as db  # local import so app still works without package
    except Exception:
        return pd.DataFrame()

    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(minutes=int(max(30, min(lookback_minutes, 1440))))

    try:
        client = db.Historical(key)
        store = client.timeseries.get_range(
            dataset=cfg["dataset"],
            start=start_dt.isoformat(),
            end=end_dt.isoformat(),
            symbols=cfg["symbol"],
            stype_in=cfg.get("stype_in", "raw_symbol"),
            schema=cfg.get("schema", schema),
        )
        df = store.to_df()
        return _standardize_ohlcv_frame_v4(
            df=df,
            source="Databento",
            symbol=symbol,
            provider_symbol=cfg.get("symbol"),
        )
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=20, show_spinner=False)
def fetch_yfinance_intraday_v4(symbol: str, period: str = "1d", interval: str = "1m") -> pd.DataFrame:
    symbol = _normalize_live_symbol_v4(symbol)

    if not YFINANCE_AVAILABLE:
        return pd.DataFrame()

    try:
        data = yf.download(symbol, period=period, interval=interval, progress=False, auto_adjust=False)
        if data is None or data.empty:
            # Fallback when 1m data is unavailable.
            data = yf.download(symbol, period="5d", interval="5m", progress=False, auto_adjust=False)
        if data is None or data.empty:
            return pd.DataFrame()

        data = data.reset_index()
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = [str(c[0]).lower() for c in data.columns]
        return _standardize_ohlcv_frame_v4(data, source="yfinance", symbol=symbol, provider_symbol=symbol)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=20, show_spinner=False)
def get_live_curve_v4(symbol: str, asset_class: str = "Global", provider: str = "auto", lookback_minutes: int = 390) -> tuple[pd.DataFrame, dict[str, Any]]:
    symbol = _normalize_live_symbol_v4(symbol)
    provider = str(provider or "auto").lower()

    df = pd.DataFrame()
    used_provider = "None"

    if provider in {"auto", "databento"}:
        df = fetch_databento_ohlcv_v4(symbol, lookback_minutes=lookback_minutes)
        if not df.empty:
            used_provider = "Databento"

    if df.empty and provider in {"auto", "yfinance"}:
        df = fetch_yfinance_intraday_v4(symbol)
        if not df.empty:
            used_provider = "yfinance"

    cfg = DATABENTO_PROXY_MAP.get(symbol, {})
    meta = {
        "symbol": symbol,
        "asset_class": asset_class,
        "provider": used_provider,
        "databento_configured": databento_configured_v4(),
        "databento_mapped": symbol in DATABENTO_PROXY_MAP,
        "provider_symbol": cfg.get("symbol", symbol),
        "proxy_note": cfg.get("proxy_note", ""),
        "label": cfg.get("label", symbol),
    }
    return df, meta


def build_live_curve_metrics_v4(df: pd.DataFrame) -> dict[str, Any]:
    if df is None or df.empty or "close" not in df.columns:
        return {"last": None, "change": None, "range": None, "volume": None}

    close = pd.to_numeric(df["close"], errors="coerce").dropna()
    if close.empty:
        return {"last": None, "change": None, "range": None, "volume": None}

    first = safe_float(close.iloc[0])
    last = safe_float(close.iloc[-1])
    change = last / first - 1 if first not in [None, 0] and last is not None else None

    high = pd.to_numeric(df.get("high", close), errors="coerce").max()
    low = pd.to_numeric(df.get("low", close), errors="coerce").min()
    price_range = high / low - 1 if safe_float(low) not in [None, 0] else None
    volume = safe_float(pd.to_numeric(df.get("volume", pd.Series(dtype=float)), errors="coerce").sum())

    return {
        "last": last,
        "change": change,
        "range": price_range,
        "volume": volume,
        "bars": int(len(df)),
    }


def render_live_curve_panel_v4(
    symbol: str,
    asset_class: str = "Global",
    title: str | None = None,
    provider: str = "auto",
    lookback_minutes: int = 390,
    height: int = 420,
    compact: bool = False,
) -> None:
    symbol = _normalize_live_symbol_v4(symbol)
    df, meta = get_live_curve_v4(symbol, asset_class=asset_class, provider=provider, lookback_minutes=lookback_minutes)
    metrics = build_live_curve_metrics_v4(df)

    header = title or f"Live curve — {symbol}"
    st.markdown(f"#### {header}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Last", _fmt_num(metrics.get("last")))
    c2.metric("Intraday", _fmt_pct(metrics.get("change")))
    c3.metric("Range", _fmt_pct(metrics.get("range")))
    c4.metric("Bars", str(metrics.get("bars", 0)))

    if df.empty:
        st.info(
            "Courbe live indisponible pour ce symbole. "
            "Vérifie DATABENTO_API_KEY, le package databento, la couverture du dataset, ou utilise le fallback yfinance."
        )
        return

    fig = go.Figure()
    if not compact and all(col in df.columns for col in ["open", "high", "low", "close"]):
        fig.add_trace(
            go.Candlestick(
                x=df["date"],
                open=df["open"],
                high=df["high"],
                low=df["low"],
                close=df["close"],
                name=symbol,
            )
        )
    else:
        fig.add_trace(go.Scatter(x=df["date"], y=df["close"], mode="lines", name=symbol))

    # VWAP-style line if volume exists.
    try:
        vol = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
        typical = pd.to_numeric(df[["high", "low", "close"]].mean(axis=1), errors="coerce")
        if vol.sum() > 0:
            vwap = (typical * vol).cumsum() / vol.replace(0, np.nan).cumsum()
            fig.add_trace(go.Scatter(x=df["date"], y=vwap, mode="lines", name="VWAP proxy"))
    except Exception:
        pass

    fig.update_layout(
        height=height,
        template="plotly_dark",
        hovermode="x unified",
        margin=dict(l=10, r=10, t=40, b=10),
        title=f"{symbol} · {meta.get('provider')} · {meta.get('provider_symbol')}",
        xaxis_rangeslider_visible=False,
    )
    st.plotly_chart(fig, use_container_width=True)

    source_note = f"Source: {meta.get('provider')}"
    if meta.get("proxy_note"):
        source_note += f" · {meta.get('proxy_note')}"
    if meta.get("provider") != "Databento" and meta.get("databento_mapped") and not meta.get("databento_configured"):
        source_note += " · Databento non configuré: fallback public."
    st.caption(source_note)


def _render_micro_curve_cards_v4(symbols: list[str], asset_class: str = "Global", max_items: int = 4) -> None:
    shown = [s for s in symbols if s][:max_items]
    if not shown:
        return

    _render_panel_header_v3("Live Curves", "Intraday charts · Databento when mapped, yfinance fallback otherwise")
    cols = st.columns(len(shown))
    for col, symbol in zip(cols, shown):
        with col:
            df, meta = get_live_curve_v4(symbol, asset_class=asset_class, lookback_minutes=240)
            metrics = build_live_curve_metrics_v4(df)
            st.metric(symbol, _fmt_num(metrics.get("last")), delta=_fmt_pct(metrics.get("change")))
            if df.empty:
                st.caption("No curve")
                continue
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df["date"], y=df["close"], mode="lines", name=symbol))
            fig.update_layout(
                height=165,
                template="plotly_dark",
                margin=dict(l=0, r=0, t=0, b=0),
                xaxis=dict(visible=False),
                yaxis=dict(visible=False),
                showlegend=False,
            )
            st.plotly_chart(fig, use_container_width=True)
            st.caption(str(meta.get("provider", "N/A")))


# ------------------------------------------------------------
# Dashboard override with actual live curve tabs
# ------------------------------------------------------------

def render_generic_asset_dashboard(asset_class: str, ticker: str, price_data: pd.DataFrame, analysis: dict | None = None) -> None:
    profile = get_asset_profile(asset_class)
    df = _safe_price_frame(price_data)

    st.subheader(f"{profile['label']} Dashboard — {ticker}")
    st.caption(
        "Vue multi-asset : courbe live/intraday, historique, rendements, volatilité, drawdown, régime simple et modules compatibles."
    )

    if df.empty:
        st.warning("Données prix historiques indisponibles ou insuffisantes.")
        # Even if historical app data failed, try a live/public curve.
        render_live_curve_panel_v4(ticker, asset_class=asset_class, height=430)
        return

    close = df["close"].astype(float)
    returns = close.pct_change().dropna()

    last_price = float(close.iloc[-1])
    ret_20 = close.iloc[-1] / close.iloc[-21] - 1 if len(close) > 21 else None
    ret_60 = close.iloc[-1] / close.iloc[-61] - 1 if len(close) > 61 else None
    vol_20 = returns.tail(20).std() * (252 ** 0.5) if len(returns) >= 20 else None
    dd = close / close.cummax() - 1

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Last", _fmt_num(last_price))
    c2.metric("20D return", _fmt_pct(ret_20))
    c3.metric("60D return", _fmt_pct(ret_60))
    c4.metric("20D vol ann.", _fmt_pct(vol_20))
    c5.metric("Max drawdown", _fmt_pct(float(dd.min())))

    live_tab, hist_tab, data_tab = st.tabs(["Live / Intraday curve", "Historical structure", "Data / modules"])

    with live_tab:
        render_live_curve_panel_v4(ticker, asset_class=asset_class, height=500)

    with hist_tab:
        fig = go.Figure()
        if all(col in df.columns for col in ["open", "high", "low", "close"]):
            fig.add_trace(
                go.Candlestick(
                    x=df["date"], open=df["open"], high=df["high"], low=df["low"], close=df["close"], name=ticker
                )
            )
        else:
            fig.add_trace(go.Scatter(x=df["date"], y=df["close"], mode="lines", name=ticker))
        fig.add_trace(go.Scatter(x=df["date"], y=close.rolling(20).mean(), mode="lines", name="SMA 20"))
        fig.add_trace(go.Scatter(x=df["date"], y=close.rolling(60).mean(), mode="lines", name="SMA 60"))
        fig.update_layout(
            height=520,
            margin=dict(l=10, r=10, t=35, b=10),
            template="plotly_dark",
            title=f"{asset_class} historical structure — {ticker}",
            xaxis_rangeslider_visible=False,
            hovermode="x unified",
        )
        st.plotly_chart(fig, use_container_width=True)

        perf_rows = []
        for label, n in [("5D", 5), ("20D", 20), ("60D", 60), ("120D", 120), ("252D", 252)]:
            value = close.iloc[-1] / close.iloc[-n] - 1 if len(close) > n else None
            perf_rows.append({"Window": label, "Return": _fmt_pct(value)})
        st.dataframe(pd.DataFrame(perf_rows), use_container_width=True, hide_index=True)

    with data_tab:
        provider_rows = [
            {"Provider": "Databento", "Status": "Configured" if databento_configured_v4() else "Missing key", "Use": "Preferred for futures / intraday proxies"},
            {"Provider": "yfinance", "Status": "Available" if YFINANCE_AVAILABLE else "Unavailable", "Use": "Fallback public quotes / charts"},
        ]
        st.dataframe(pd.DataFrame(provider_rows), use_container_width=True, hide_index=True)

        module_rows = []
        for mode in profile["mode_options"]:
            comment = "Compatible avec cette classe d'actif."
            if mode == "Decision Engine Lite":
                comment = "Lecture proxy / partielle selon disponibilité données publiques."
            module_rows.append({"Module": mode, "Status": "Available", "Comment": comment})
        st.dataframe(pd.DataFrame(module_rows), use_container_width=True, hide_index=True)


def render_fx_dashboard(ticker: str, price_data: pd.DataFrame, analysis: dict | None = None) -> None:
    render_generic_asset_dashboard("FX", ticker, price_data, analysis)


def render_commodity_dashboard(ticker: str, price_data: pd.DataFrame, analysis: dict | None = None) -> None:
    render_generic_asset_dashboard("Commodities", ticker, price_data, analysis)


def render_rates_dashboard(ticker: str, price_data: pd.DataFrame, analysis: dict | None = None) -> None:
    render_generic_asset_dashboard("Rates", ticker, price_data, analysis)


# ------------------------------------------------------------
# Global Command Center override with live curves
# ------------------------------------------------------------

def render_global_command_center() -> None:
    """
    V4 : cockpit post-JARVIS avec courbes live/intraday.
    """
    inject_command_center_css()

    current_asset = st.session_state.get("asset_class", "Equity")
    current_profile = get_asset_profile(current_asset)

    st.markdown(
        """
        <div class="cc-v3-hero">
            <div class="cc-v3-kicker">GLOBAL COMMAND CENTER</div>
            <div class="cc-v3-title">Institutional Multi-Asset Cockpit</div>
            <div class="cc-v3-sub">
                Recherche centrale, market tape, régime cross-asset, courbes live/intraday, FX board, commodities board, news et quick launch.
                Databento est utilisé en priorité sur futures/proxies mappés ; fallback public si nécessaire.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form("global_command_center_form_v4"):
        c1, c2, c3, c4, c5, c6 = st.columns([1.0, 2.25, 1.25, 0.85, 0.85, 1.0], vertical_alignment="bottom")
        with c1:
            asset_choice = st.selectbox("Asset Class", ["Auto"] + get_asset_classes(), index=0, key="gcc_asset_choice_v4")
        with c2:
            raw_symbol = st.text_input(
                "Search / Command",
                value=st.session_state.get("ticker") or current_profile["default_symbol"],
                placeholder="NVDA, EURUSD, CL=F, ^TNX, TLT...",
                key="gcc_symbol_input_v4",
            )
        inferred_asset = infer_asset_class_from_symbol(raw_symbol, fallback=current_asset)
        effective_asset = inferred_asset if asset_choice == "Auto" else asset_choice
        effective_profile = get_asset_profile(effective_asset)
        with c3:
            mode_choice = st.selectbox("Mode", effective_profile["mode_options"], index=0, key=f"gcc_mode_choice_v4_{effective_asset}")
        with c4:
            period_choice = st.selectbox("Period", ["3mo", "6mo", "1y", "2y", "5y", "10y"], index=_select_index(["3mo", "6mo", "1y", "2y", "5y", "10y"], effective_profile["default_period"], 2), key=f"gcc_period_choice_v4_{effective_asset}")
        with c5:
            interval_choice = st.selectbox("Interval", ["1d", "1wk", "1mo"], index=0, key=f"gcc_interval_choice_v4_{effective_asset}")
        with c6:
            launch = st.form_submit_button("LAUNCH", use_container_width=True)
        if launch:
            resolved_asset, resolved_symbol, resolved_mode = resolve_asset_symbol_and_mode(effective_asset, raw_symbol, mode_choice)
            _launch_workspace(resolved_asset, resolved_symbol, period_choice, interval_choice, resolved_mode)

    resolved_preview_asset, resolved_preview_symbol, resolved_preview_mode = resolve_asset_symbol_and_mode(effective_asset, raw_symbol, mode_choice)
    st.caption(f"Inference preview : {resolved_preview_asset} · normalized symbol : {resolved_preview_symbol} · mode : {resolved_preview_mode}")

    # ============================================================
    # WORLDMONITOR / MACRO — DIRECT COMMAND CENTER ACCESS
    # ============================================================
    gem_cols = st.columns([1.25, 1.25, 4.5], vertical_alignment="center")

    with gem_cols[1]:
        if st.button(
            "WORLDMONITOR ",
            use_container_width=True,
            key="gcc_open_worldmonitor_v211",
        ):
            st.session_state["worldmonitor_v211_open"] = True
            st.session_state["asset_class_selected"] = True
            st.rerun()

    with gem_cols[2]:
        st.caption(
            "Direct geopolitical monitor · macro regime · central banks · no ticker dependency."
        )

    tape_df = load_market_tape_snapshot(tuple(MARKET_TAPE_UNIVERSES["Global"]))
    regime = build_cross_asset_regime(tape_df)
    overview = build_market_overview_v3(tape_df)
    news_df = load_latest_news_snapshot(limit=10)
    gainers, losers = build_movers_v3(tape_df, n=5)
    curve_df = build_curve_snapshot_v3(tape_df)

    if tape_df is not None and not tape_df.empty:
        lookup = {row.get("Symbol"): row for _, row in tape_df.iterrows()}
        strip_items = [
            ("S&P FUT", lookup.get("ES=F")),
            ("NASDAQ FUT", lookup.get("NQ=F")),
            ("VIX", lookup.get("^VIX")),
            ("DXY", lookup.get("DX-Y.NYB")),
            ("10Y", lookup.get("^TNX")),
            ("WTI", lookup.get("CL=F")),
        ]
        html = ['<div class="cc-v3-strip">']
        for label, row in strip_items:
            if row is None:
                value, meta = "N/A", "WAIT"
            else:
                value, meta = _value_for_symbol(row), _fmt_pct(row.get("Change %"))
            html.append(f'<div class="cc-v3-strip-card"><div class="cc-v3-strip-label">{_cc_escape(label)}</div><div class="cc-v3-strip-value">{_cc_escape(value)}</div><div class="cc-v3-strip-meta">{_cc_escape(meta)}</div></div>')
        html.append('</div>')
        st.markdown("".join(html), unsafe_allow_html=True)

    st.markdown("---")
    chart_symbols = LIVE_CHART_DEFAULTS.get(resolved_preview_asset, LIVE_CHART_DEFAULTS["Global"])
    _render_micro_curve_cards_v4(chart_symbols, asset_class=resolved_preview_asset, max_items=4)

    st.markdown("---")
    _render_panel_header_v3("Global Market Tape", "Cross-asset instruments and public proxies")
    _render_compact_tape_v3(tape_df, max_cards=12)

    st.markdown("---")
    left, mid, right = st.columns([1.20, 1.0, 1.10])
    with left:
        st.markdown('<div class="cc-v3-panel">', unsafe_allow_html=True)
        _render_regime_panel_v3(regime, overview)
        st.markdown('</div>', unsafe_allow_html=True)
    with mid:
        st.markdown('<div class="cc-v3-panel">', unsafe_allow_html=True)
        _render_panel_header_v3("Rates / Curve", "Yield proxies and curve state")
        if curve_df.empty:
            st.caption("Curve snapshot indisponible.")
        else:
            st.dataframe(curve_df, use_container_width=True, hide_index=True)
        st.markdown("<br>", unsafe_allow_html=True)
        _render_panel_header_v3("Top Movers", "Current global tape")
        mtab1, mtab2 = st.tabs(["Gainers", "Losers"])
        with mtab1:
            st.dataframe(gainers, use_container_width=True, hide_index=True)
        with mtab2:
            st.dataframe(losers, use_container_width=True, hide_index=True)
        st.markdown('</div>', unsafe_allow_html=True)
    with right:
        st.markdown('<div class="cc-v3-panel">', unsafe_allow_html=True)
        _render_news_panel_v3(news_df)
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("---")
    b1, b2, b3 = st.columns([1, 1, 1])
    with b1:
        st.markdown('<div class="cc-v3-panel">', unsafe_allow_html=True)
        _render_panel_header_v3("FX Board", "Majors and dollar regime")
        fx_board = build_fx_board_v3()
        st.dataframe(fx_board, use_container_width=True, hide_index=True)
        st.markdown('</div>', unsafe_allow_html=True)
    with b2:
        st.markdown('<div class="cc-v3-panel">', unsafe_allow_html=True)
        _render_panel_header_v3("Commodities Board", "Energy, metals and agricultural proxies")
        commo_board = build_commodity_board_v3()
        st.dataframe(commo_board, use_container_width=True, hide_index=True)
        st.markdown('</div>', unsafe_allow_html=True)
    with b3:
        st.markdown('<div class="cc-v3-panel">', unsafe_allow_html=True)
        _render_quick_modules_v3(resolved_preview_asset)
        st.markdown("<br>", unsafe_allow_html=True)
        qcols = st.columns(2)
        for idx, asset_class in enumerate(get_asset_classes()):
            profile = get_asset_profile(asset_class)
            with qcols[idx % 2]:
                if st.button(f"OPEN {profile['label']}", key=f"gcc_quick_open_v4_{asset_class}", use_container_width=True):
                    _launch_workspace(asset_class, profile["default_symbol"], profile["default_period"], profile["default_interval"], default_mode_for_asset(asset_class))
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("---")
    tab_names = ["Global", "Equity", "FX", "Commodities", "Rates"]
    tabs = st.tabs(tab_names)
    for tab, name in zip(tabs, tab_names):
        with tab:
            symbols = tuple(MARKET_TAPE_UNIVERSES.get(name, MARKET_TAPE_UNIVERSES["Global"]))
            df = load_market_tape_snapshot(symbols)
            display = _prepare_tape_display(df)
            if display.empty:
                st.info(f"{name} tape indisponible.")
            else:
                st.dataframe(display, use_container_width=True, hide_index=True)


def render_asset_class_home() -> None:
    """Entrée backward-compatible appelée par app.py."""
    render_global_command_center()


# ============================================================
# END MULTI-ASSET COMMAND CENTER V4 LIVE CURVES PATCH
# ============================================================

# ============================================================
# MULTI-ASSET COMMAND CENTER V5 — CLEAN LIVE CURVES OVERRIDE
# ============================================================
# Où coller :
# - À la TOUTE FIN de asset_class_router.py, après :
#   # END MULTI-ASSET COMMAND CENTER V4 LIVE CURVES PATCH
#
# Objectif :
# - Corriger les courbes absentes / moches du V4.
# - Brancher réellement Twelve Data dans la chaîne provider.
# - Priorité provider :
#       1) Databento pour futures/proxies mappés
#       2) Twelve Data pour FX spot / equities / ETF / indices / crypto / XAU/XAG
#       3) yfinance fallback
# - Améliorer le rendu visuel :
#       * sparkline propre
#       * line + area fill
#       * dernier prix
#       * range intraday
#       * provider visible
#       * diagnostic clair si aucune donnée
# - Ne touche pas aux moteurs Backtest / Risk / Monte Carlo / Decision.
# ============================================================


# ------------------------------------------------------------
# V5 — provider selection helpers
# ------------------------------------------------------------

def _twelve_data_candidate_v5(symbol: str, asset_class: str = "Global") -> bool:
    """
    Détermine si Twelve Data est pertinent pour le symbole.
    On évite de le requêter inutilement sur les futures Yahoo =F
    sauf métaux spot mappés.
    """
    s = _normalize_live_symbol_v4(symbol)
    ac = str(asset_class or "").strip()

    if not twelve_data_enabled():
        return False

    # FX Yahoo/compact.
    if s in FX_YAHOO or s.replace("/", "").replace("-", "").replace("=X", "") in FX_COMPACT:
        return True

    # Gold/silver spot mapping already present in to_twelve_data_symbol().
    if s in {"GC=F", "SI=F", "XAUUSD", "XAGUSD"}:
        return True

    # Crypto Yahoo style.
    if s.endswith("-USD"):
        return True

    # Common equity / ETF symbols, no suffix.
    if (
        ac in {"Equity", "Global", "Auto"}
        and not s.startswith("^")
        and not s.endswith("=F")
        and not s.endswith("=X")
        and "." not in s
        and "-" not in s
    ):
        return True

    # Known indices mapped in to_twelve_data_symbol.
    if s in {"^GSPC", "^IXIC", "^DJI", "^VIX"}:
        return True

    return False


def _standardize_twelve_data_frame_v5(
    df: pd.DataFrame,
    symbol: str,
    asset_class: str = "Global",
    provider_symbol: str | None = None,
) -> pd.DataFrame:
    """
    Convertit le DataFrame Twelve Data vers le format live curve V4/V5.
    """
    if df is None or df.empty:
        return pd.DataFrame()

    work = df.copy()
    work.columns = [str(c).lower().strip() for c in work.columns]

    if "datetime" in work.columns and "date" not in work.columns:
        work = work.rename(columns={"datetime": "date"})

    if "date" not in work.columns or "close" not in work.columns:
        return pd.DataFrame()

    work["date"] = pd.to_datetime(work["date"], errors="coerce", utc=True)

    for col in ["open", "high", "low", "close", "volume"]:
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce")

    if "volume" not in work.columns:
        work["volume"] = np.nan

    work = work.dropna(subset=["date", "close"]).sort_values("date").drop_duplicates("date")

    if work.empty:
        return pd.DataFrame()

    for col in ["open", "high", "low"]:
        if col not in work.columns:
            work[col] = work["close"]
        else:
            work[col] = work[col].fillna(work["close"])

    work["source"] = "Twelve Data"
    work["symbol"] = _normalize_live_symbol_v4(symbol)
    work["provider_symbol"] = provider_symbol or to_twelve_data_symbol(symbol, asset_class)

    keep = ["date", "open", "high", "low", "close", "volume", "source", "symbol", "provider_symbol"]
    return work[[c for c in keep if c in work.columns]].reset_index(drop=True)


@st.cache_data(ttl=20, show_spinner=False)
def fetch_twelve_data_intraday_v5(
    symbol: str,
    asset_class: str = "Global",
    interval: str = "1min",
    outputsize: int = 240,
) -> pd.DataFrame:
    """
    Fetch Twelve Data intraday and standardize it for V5 charts.
    """
    if not _twelve_data_candidate_v5(symbol, asset_class):
        return pd.DataFrame()

    try:
        df, meta = get_twelve_data_intraday_frame(
            symbol=symbol,
            asset_class=asset_class,
            interval=interval,
            outputsize=outputsize,
        )
        if df is None or df.empty:
            return pd.DataFrame()

        return _standardize_twelve_data_frame_v5(
            df=df,
            symbol=symbol,
            asset_class=asset_class,
            provider_symbol=meta.get("td_symbol") or to_twelve_data_symbol(symbol, asset_class),
        )
    except Exception:
        return pd.DataFrame()


def _provider_order_v5(symbol: str, asset_class: str = "Global", provider: str = "auto") -> list[str]:
    """
    Ordre dynamique pour éviter de demander Twelve Data sur des futures
    et éviter d'utiliser yfinance sur du FX quand Twelve Data est disponible.
    """
    provider = str(provider or "auto").lower()
    s = _normalize_live_symbol_v4(symbol)

    if provider in {"databento", "twelvedata", "twelve", "yfinance"}:
        return [provider]

    # Futures mappés : Databento d'abord.
    if s in DATABENTO_PROXY_MAP:
        if _twelve_data_candidate_v5(s, asset_class) and asset_class == "FX":
            # Pour FX, on préfère spot Twelve Data à un proxy future
            # si la clé TD est configurée. Databento reste disponible ensuite.
            return ["twelvedata", "databento", "yfinance"]
        return ["databento", "yfinance", "twelvedata"]

    # FX / equity / ETF / crypto : Twelve Data d'abord.
    if _twelve_data_candidate_v5(s, asset_class):
        return ["twelvedata", "yfinance"]

    return ["yfinance"]


@st.cache_data(ttl=20, show_spinner=False)
def get_live_curve_v4(
    symbol: str,
    asset_class: str = "Global",
    provider: str = "auto",
    lookback_minutes: int = 390,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Override V5 gardant le nom V4 pour compatibilité.
    """
    s = _normalize_live_symbol_v4(symbol)
    order = _provider_order_v5(s, asset_class, provider)

    errors: list[str] = []
    df = pd.DataFrame()
    used_provider = "None"

    for p in order:
        try:
            if p == "databento":
                df = fetch_databento_ohlcv_v4(s, lookback_minutes=lookback_minutes)
                if not df.empty:
                    used_provider = "Databento"
                    break

            elif p in {"twelvedata", "twelve"}:
                # outputsize roughly aligned with lookback minutes.
                df = fetch_twelve_data_intraday_v5(
                    s,
                    asset_class=asset_class,
                    interval="1min",
                    outputsize=int(max(60, min(500, lookback_minutes))),
                )
                if not df.empty:
                    used_provider = "Twelve Data"
                    break

            elif p == "yfinance":
                df = fetch_yfinance_intraday_v4(s)
                if not df.empty:
                    used_provider = "yfinance"
                    break

        except Exception as exc:
            errors.append(f"{p}: {exc}")

    cfg = DATABENTO_PROXY_MAP.get(s, {})
    td_symbol = None
    try:
        td_symbol = to_twelve_data_symbol(s, asset_class)
    except Exception:
        td_symbol = None

    provider_symbol = s
    if not df.empty and "provider_symbol" in df.columns:
        try:
            provider_symbol = str(df["provider_symbol"].dropna().iloc[-1])
        except Exception:
            provider_symbol = cfg.get("symbol", td_symbol or s)
    elif used_provider == "Databento":
        provider_symbol = cfg.get("symbol", s)
    elif used_provider == "Twelve Data":
        provider_symbol = td_symbol or s

    meta = {
        "symbol": s,
        "asset_class": asset_class,
        "provider": used_provider,
        "provider_order": " > ".join(order),
        "provider_symbol": provider_symbol,
        "databento_configured": databento_configured_v4(),
        "databento_mapped": s in DATABENTO_PROXY_MAP,
        "twelve_data_configured": twelve_data_enabled(),
        "twelve_data_candidate": _twelve_data_candidate_v5(s, asset_class),
        "twelve_data_symbol": td_symbol,
        "proxy_note": cfg.get("proxy_note", ""),
        "label": cfg.get("label", s),
        "errors": "; ".join(errors[-3:]),
    }
    return df, meta


# ------------------------------------------------------------
# V5 — chart cosmetics
# ------------------------------------------------------------

def _curve_color_v5(change: Any) -> tuple[str, str]:
    """
    Retourne line_color, fill_color.
    """
    x = _safe_float(change)
    if x is None:
        return "rgba(120, 170, 255, 0.95)", "rgba(120, 170, 255, 0.10)"
    if x >= 0:
        return "rgba(60, 240, 180, 0.95)", "rgba(60, 240, 180, 0.10)"
    return "rgba(255, 95, 115, 0.95)", "rgba(255, 95, 115, 0.10)"


def _downsample_for_plot_v5(df: pd.DataFrame, max_points: int = 260) -> pd.DataFrame:
    if df is None or df.empty or len(df) <= max_points:
        return df
    step = int(np.ceil(len(df) / max_points))
    return df.iloc[::step].copy()


def _format_price_by_symbol_v5(symbol: str, value: Any) -> str:
    x = _safe_float(value)
    if x is None:
        return "N/A"

    s = _normalize_live_symbol_v4(symbol)

    if s.endswith("=X") or s in FX_YAHOO:
        return f"{x:,.5f}"

    if s in {"^IRX", "^FVX", "^TNX", "^TYX"}:
        return f"{x:,.3f}"

    if x < 10:
        return f"{x:,.4f}"

    return f"{x:,.2f}"


def _make_live_curve_figure_v5(
    df: pd.DataFrame,
    symbol: str,
    title: str | None = None,
    height: int = 260,
    compact: bool = False,
    show_volume: bool = False,
) -> go.Figure:
    metrics = build_live_curve_metrics_v4(df)
    line_color, fill_color = _curve_color_v5(metrics.get("change"))
    plot_df = _downsample_for_plot_v5(df, max_points=260 if compact else 650)

    fig = go.Figure()

    if plot_df is None or plot_df.empty:
        fig.update_layout(
            template="plotly_dark",
            height=height,
            margin=dict(l=4, r=4, t=22, b=4),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        return fig

    fig.add_trace(
        go.Scatter(
            x=plot_df["date"],
            y=plot_df["close"],
            mode="lines",
            name=symbol,
            line=dict(width=2.2 if not compact else 1.65, color=line_color),
            fill="tozeroy" if compact else "tonexty",
            fillcolor=fill_color,
            hovertemplate="%{x}<br>Close: %{y:.5f}<extra></extra>",
        )
    )

    # Add EMA/VWAP only on non-compact panel.
    if not compact:
        try:
            ema = pd.to_numeric(plot_df["close"], errors="coerce").ewm(span=21, adjust=False).mean()
            fig.add_trace(
                go.Scatter(
                    x=plot_df["date"],
                    y=ema,
                    mode="lines",
                    name="EMA 21",
                    line=dict(width=1.2, color="rgba(210, 220, 255, 0.55)", dash="dot"),
                    hovertemplate="%{x}<br>EMA21: %{y:.5f}<extra></extra>",
                )
            )
        except Exception:
            pass

        try:
            last = _safe_float(plot_df["close"].iloc[-1])
            if last is not None:
                fig.add_hline(
                    y=last,
                    line_width=1,
                    line_dash="dot",
                    line_color="rgba(255,255,255,0.35)",
                    annotation_text=f"Last {last:.5f}" if last < 10 else f"Last {last:.2f}",
                    annotation_position="top right",
                )
        except Exception:
            pass

    fig.update_layout(
        height=height,
        template="plotly_dark",
        hovermode="x unified",
        margin=dict(l=6 if compact else 10, r=6 if compact else 10, t=24 if compact else 46, b=4 if compact else 18),
        title=None if compact else title,
        showlegend=False if compact else True,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(4, 12, 26, 0.15)",
        xaxis=dict(
            visible=not compact,
            showgrid=False,
            rangeslider=dict(visible=False),
        ),
        yaxis=dict(
            visible=not compact,
            showgrid=not compact,
            gridcolor="rgba(120, 170, 255, 0.10)",
            zeroline=False,
        ),
    )
    return fig


def _render_provider_diagnostic_v5(meta: dict[str, Any]) -> None:
    rows = [
        {"Item": "Provider used", "Value": meta.get("provider", "None")},
        {"Item": "Provider order", "Value": meta.get("provider_order", "N/A")},
        {"Item": "Provider symbol", "Value": meta.get("provider_symbol", "N/A")},
        {"Item": "Databento configured", "Value": str(meta.get("databento_configured"))},
        {"Item": "Databento mapped", "Value": str(meta.get("databento_mapped"))},
        {"Item": "Twelve Data configured", "Value": str(meta.get("twelve_data_configured"))},
        {"Item": "Twelve Data candidate", "Value": str(meta.get("twelve_data_candidate"))},
        {"Item": "Twelve Data symbol", "Value": str(meta.get("twelve_data_symbol"))},
        {"Item": "Proxy note", "Value": str(meta.get("proxy_note", ""))},
        {"Item": "Errors", "Value": str(meta.get("errors", ""))},
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_live_curve_panel_v4(
    symbol: str,
    asset_class: str = "Global",
    title: str | None = None,
    provider: str = "auto",
    lookback_minutes: int = 390,
    height: int = 500,
    compact: bool = False,
) -> None:
    """
    Override V5 du panneau live.
    """
    s = _normalize_live_symbol_v4(symbol)
    df, meta = get_live_curve_v4(
        s,
        asset_class=asset_class,
        provider=provider,
        lookback_minutes=lookback_minutes,
    )
    metrics = build_live_curve_metrics_v4(df)

    header = title or f"Live / Intraday — {s}"
    st.markdown(f"#### {header}")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Last", _format_price_by_symbol_v5(s, metrics.get("last")))
    c2.metric("Intraday", _fmt_pct(metrics.get("change")))
    c3.metric("Range", _fmt_pct(metrics.get("range")))
    c4.metric("Bars", str(metrics.get("bars", 0)))
    c5.metric("Provider", str(meta.get("provider", "None")))

    if df.empty:
        st.warning(
            f"Aucune courbe disponible pour {s}. "
            f"Provider order: {meta.get('provider_order', 'N/A')}. "
            "Vérifie les clés API, les quotas et la couverture du symbole."
        )
        with st.expander("Provider diagnostic", expanded=False):
            _render_provider_diagnostic_v5(meta)
        return

    chart_title = f"{s} · {meta.get('provider')} · {meta.get('provider_symbol')}"
    fig = _make_live_curve_figure_v5(
        df=df,
        symbol=s,
        title=chart_title,
        height=height,
        compact=compact,
    )
    st.plotly_chart(fig, use_container_width=True)

    note = f"Source: {meta.get('provider')} · Symbol: {meta.get('provider_symbol')}"
    if meta.get("proxy_note"):
        note += f" · {meta.get('proxy_note')}"
    st.caption(note)

    with st.expander("Provider diagnostic", expanded=False):
        _render_provider_diagnostic_v5(meta)


def _render_micro_curve_cards_v4(symbols: list[str], asset_class: str = "Global", max_items: int = 4) -> None:
    """
    Override V5 des mini-courbes du Global Command Center.
    """
    shown = [s for s in symbols if s][:max_items]
    if not shown:
        return

    _render_panel_header_v3(
        "Live Curves",
        "Intraday curves · Databento / Twelve Data / yfinance fallback"
    )

    cols = st.columns(len(shown))

    for col, symbol in zip(cols, shown):
        with col:
            s = _normalize_live_symbol_v4(symbol)
            df, meta = get_live_curve_v4(
                s,
                asset_class=asset_class,
                provider="auto",
                lookback_minutes=240,
            )
            metrics = build_live_curve_metrics_v4(df)
            line_color, _ = _curve_color_v5(metrics.get("change"))

            st.markdown(
                f"""
                <div style="
                    border:1px solid rgba(90,205,255,.15);
                    background:rgba(4,14,29,.72);
                    border-radius:14px;
                    padding:10px 11px;
                    margin-bottom:6px;">
                    <div style="color:rgba(230,244,255,.70);font-size:.68rem;font-weight:850;letter-spacing:.10em;text-transform:uppercase;">
                        {s}
                    </div>
                    <div style="color:#f8fbff;font-size:1.02rem;font-weight:900;margin-top:4px;">
                        {_format_price_by_symbol_v5(s, metrics.get("last"))}
                    </div>
                    <div style="color:{line_color};font-size:.72rem;font-weight:850;margin-top:2px;">
                        {_fmt_pct(metrics.get("change"))} · {meta.get("provider", "None")}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            if df.empty:
                st.caption("No curve · check provider diagnostic in full dashboard")
                continue

            fig = _make_live_curve_figure_v5(
                df=df,
                symbol=s,
                title=None,
                height=165,
                compact=True,
            )
            st.plotly_chart(fig, use_container_width=True)


# ------------------------------------------------------------
# V5 — dashboard override with cleaner tabs and visible provider state
# ------------------------------------------------------------

def render_generic_asset_dashboard(
    asset_class: str,
    ticker: str,
    price_data: pd.DataFrame,
    analysis: dict | None = None,
) -> None:
    profile = get_asset_profile(asset_class)
    df = _safe_price_frame(price_data)

    st.subheader(f"{profile['label']} Dashboard — {ticker}")
    st.caption(
        "Vue multi-asset : live/intraday propre, structure historique, contrôle provider et modules compatibles."
    )

    if df.empty:
        st.warning("Données historiques indisponibles. Tentative live provider uniquement.")
        render_live_curve_panel_v4(ticker, asset_class=asset_class, height=520)
        return

    close = pd.to_numeric(df["close"], errors="coerce").dropna()
    returns = close.pct_change().dropna()

    last_price = _safe_float(close.iloc[-1]) if not close.empty else None
    ret_20 = close.iloc[-1] / close.iloc[-21] - 1 if len(close) > 21 else None
    ret_60 = close.iloc[-1] / close.iloc[-61] - 1 if len(close) > 61 else None
    vol_20 = returns.tail(20).std() * (252 ** 0.5) if len(returns) >= 20 else None
    dd = close / close.cummax() - 1 if not close.empty else pd.Series(dtype=float)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Hist Last", _format_price_by_symbol_v5(ticker, last_price))
    c2.metric("20D return", _fmt_pct(ret_20))
    c3.metric("60D return", _fmt_pct(ret_60))
    c4.metric("20D vol ann.", _fmt_pct(vol_20))
    c5.metric("Max drawdown", _fmt_pct(float(dd.min())) if not dd.empty else "N/A")

    live_tab, hist_tab, data_tab = st.tabs([
        "Live / Intraday",
        "Historical structure",
        "Data / modules",
    ])

    with live_tab:
        render_live_curve_panel_v4(
            ticker,
            asset_class=asset_class,
            height=540,
            provider="auto",
            lookback_minutes=390,
        )

    with hist_tab:
        fig = go.Figure()

        if all(col in df.columns for col in ["open", "high", "low", "close"]):
            fig.add_trace(
                go.Candlestick(
                    x=df["date"],
                    open=df["open"],
                    high=df["high"],
                    low=df["low"],
                    close=df["close"],
                    name=ticker,
                )
            )
        else:
            fig.add_trace(
                go.Scatter(
                    x=df["date"],
                    y=df["close"],
                    mode="lines",
                    name=ticker,
                    line=dict(width=2.0, color="rgba(120,170,255,.95)"),
                )
            )

        try:
            fig.add_trace(go.Scatter(x=df["date"], y=close.rolling(20).mean(), mode="lines", name="SMA 20"))
            fig.add_trace(go.Scatter(x=df["date"], y=close.rolling(60).mean(), mode="lines", name="SMA 60"))
        except Exception:
            pass

        fig.update_layout(
            height=540,
            margin=dict(l=10, r=10, t=42, b=10),
            template="plotly_dark",
            title=f"{asset_class} historical structure — {ticker}",
            xaxis_rangeslider_visible=False,
            hovermode="x unified",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(4,12,26,0.15)",
        )
        st.plotly_chart(fig, use_container_width=True)

        perf_rows = []
        for label, n in [("5D", 5), ("20D", 20), ("60D", 60), ("120D", 120), ("252D", 252)]:
            value = close.iloc[-1] / close.iloc[-n] - 1 if len(close) > n else None
            perf_rows.append({"Window": label, "Return": _fmt_pct(value)})
        st.dataframe(pd.DataFrame(perf_rows), use_container_width=True, hide_index=True)

    with data_tab:
        provider_rows = [
            {
                "Provider": "Databento",
                "Status": "Configured" if databento_configured_v4() else "Missing key",
                "Use": "Futures / CME proxies / institutional intraday",
            },
            {
                "Provider": "Twelve Data",
                "Status": "Configured" if twelve_data_enabled() else "Missing key",
                "Use": "FX spot / equities / ETFs / indices / crypto",
            },
            {
                "Provider": "yfinance",
                "Status": "Available" if YFINANCE_AVAILABLE else "Unavailable",
                "Use": "Public fallback only",
            },
        ]
        st.dataframe(pd.DataFrame(provider_rows), use_container_width=True, hide_index=True)

        module_rows = []
        for mode in profile["mode_options"]:
            comment = "Compatible avec cette classe d'actif."
            if asset_class == "Rates" and ticker.startswith("^") and mode == "Backtest Lab":
                comment = "Prudent : yield non tradable. Préférer SHY/IEF/TLT/ZN=F."
            elif mode == "Decision Engine Lite":
                comment = "Lecture proxy / partielle selon disponibilité provider."
            module_rows.append({"Module": mode, "Status": "Available", "Comment": comment})

        st.dataframe(pd.DataFrame(module_rows), use_container_width=True, hide_index=True)


def render_fx_dashboard(ticker: str, price_data: pd.DataFrame, analysis: dict | None = None) -> None:
    render_generic_asset_dashboard("FX", ticker, price_data, analysis)


def render_commodity_dashboard(ticker: str, price_data: pd.DataFrame, analysis: dict | None = None) -> None:
    render_generic_asset_dashboard("Commodities", ticker, price_data, analysis)


def render_rates_dashboard(ticker: str, price_data: pd.DataFrame, analysis: dict | None = None) -> None:
    render_generic_asset_dashboard("Rates", ticker, price_data, analysis)


# ------------------------------------------------------------
# V5 — defaults adjusted to avoid ugly/empty curves
# ------------------------------------------------------------

LIVE_CHART_DEFAULTS = {
    "Equity": ["NVDA", "QQQ", "SPY", "AAPL"],
    "FX": ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X"],
    "Commodities": ["CL=F", "GC=F", "SI=F", "HG=F"],
    "Rates": ["TLT", "IEF", "ZN=F", "^TNX"],
    "Global": ["SPY", "QQQ", "EURUSD=X", "GC=F"],
}


# ============================================================
# END MULTI-ASSET COMMAND CENTER V5 LIVE CURVES OVERRIDE
# ============================================================


# ============================================================
# HOTFIX V5 — MISSING TWELVE DATA HELPERS + SAFE_FLOAT ALIAS
# ============================================================
# Où coller :
# - Tout à la FIN de asset_class_router.py
# - Après : # END MULTI-ASSET COMMAND CENTER V5 LIVE CURVES OVERRIDE
#
# Pourquoi :
# - Le bloc V5 appelle twelve_data_enabled(), to_twelve_data_symbol()
#   et get_twelve_data_intraday_frame(), mais ces helpers ne sont pas
#   présents dans ton fichier actuel.
# - Le bloc V4 contient encore des appels à safe_float(), alors que ton
#   helper réel s'appelle _safe_float().
# ============================================================


# ------------------------------------------------------------
# Compatibility alias
# ------------------------------------------------------------

def safe_float(value, default=None):
    return _safe_float(value, default)


# ------------------------------------------------------------
# Twelve Data helpers
# ------------------------------------------------------------

def get_twelve_data_api_key() -> str:
    """
    Lit la clé Twelve Data depuis :
    1) .streamlit/secrets.toml
    2) variable d'environnement TWELVE_DATA_API_KEY
    """
    import os

    key = ""

    try:
        key = st.secrets.get("TWELVE_DATA_API_KEY", "")
    except Exception:
        key = ""

    if not key:
        key = os.getenv("TWELVE_DATA_API_KEY", "")

    return str(key or "").strip()


def twelve_data_enabled() -> bool:
    return bool(get_twelve_data_api_key())


def to_twelve_data_symbol(symbol: str, asset_class: str | None = None) -> str:
    """
    Convertit les symboles Yahoo / internes vers le format Twelve Data.
    """
    raw = str(symbol or "").strip().upper()

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
        "EURUSD": "EUR/USD",
        "GBPUSD": "GBP/USD",
        "USDJPY": "USD/JPY",
        "USDCHF": "USD/CHF",
        "AUDUSD": "AUD/USD",
        "USDCAD": "USD/CAD",
        "NZDUSD": "NZD/USD",
        "EURJPY": "EUR/JPY",
        "EURGBP": "EUR/GBP",
        "GBPJPY": "GBP/JPY",
    }

    commodity_map = {
        "GC=F": "XAU/USD",
        "SI=F": "XAG/USD",
        "XAUUSD": "XAU/USD",
        "XAGUSD": "XAG/USD",
    }

    index_map = {
        "^GSPC": "SPX",
        "^IXIC": "IXIC",
        "^DJI": "DJI",
        "^VIX": "VIX",
    }

    if raw in fx_map:
        return fx_map[raw]

    compact = raw.replace("/", "").replace("-", "").replace("=X", "")
    if compact in fx_map:
        return fx_map[compact]

    if raw in commodity_map:
        return commodity_map[raw]

    if raw in index_map:
        return index_map[raw]

    # Yahoo FX générique : ABCDEF=X -> ABC/DEF
    if raw.endswith("=X"):
        clean = raw.replace("=X", "")
        if len(clean) == 6:
            return f"{clean[:3]}/{clean[3:]}"

    # Crypto Yahoo : BTC-USD -> BTC/USD
    if raw.endswith("-USD") and len(raw) <= 10:
        return raw.replace("-", "/")

    return raw


@st.cache_data(ttl=20, show_spinner=False)
def get_twelve_data_intraday_frame(
    symbol: str,
    asset_class: str | None = None,
    interval: str = "1min",
    outputsize: int = 240,
) -> tuple[pd.DataFrame, dict]:
    """
    Pull intraday Twelve Data en OHLCV.
    Retour :
    - DataFrame colonnes: date, open, high, low, close, volume
    - meta: provider/status/message/td_symbol
    """
    import requests

    key = get_twelve_data_api_key()

    if not key:
        return pd.DataFrame(), {
            "provider": "Twelve Data",
            "status": "disabled",
            "message": "TWELVE_DATA_API_KEY absente.",
            "td_symbol": None,
        }

    td_symbol = to_twelve_data_symbol(symbol, asset_class)

    if not td_symbol:
        return pd.DataFrame(), {
            "provider": "Twelve Data",
            "status": "invalid_symbol",
            "message": "Symbole Twelve Data vide.",
            "td_symbol": None,
        }

    params = {
        "symbol": td_symbol,
        "interval": interval,
        "outputsize": int(outputsize),
        "apikey": key,
        "format": "JSON",
        "timezone": "UTC",
    }

    try:
        response = requests.get(
            "https://api.twelvedata.com/time_series",
            params=params,
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return pd.DataFrame(), {
            "provider": "Twelve Data",
            "status": "request_error",
            "message": str(exc),
            "td_symbol": td_symbol,
        }

    if not isinstance(payload, dict):
        return pd.DataFrame(), {
            "provider": "Twelve Data",
            "status": "bad_payload",
            "message": "Réponse API non-dictionnaire.",
            "td_symbol": td_symbol,
        }

    if payload.get("status") == "error" or "values" not in payload:
        return pd.DataFrame(), {
            "provider": "Twelve Data",
            "status": "api_error",
            "message": str(payload.get("message") or payload)[:500],
            "td_symbol": td_symbol,
        }

    values = payload.get("values") or []

    if not isinstance(values, list) or not values:
        return pd.DataFrame(), {
            "provider": "Twelve Data",
            "status": "empty",
            "message": "Aucune valeur retournée.",
            "td_symbol": td_symbol,
        }

    df = pd.DataFrame(values)

    if "datetime" in df.columns and "date" not in df.columns:
        df = df.rename(columns={"datetime": "date"})

    if "date" not in df.columns or "close" not in df.columns:
        return pd.DataFrame(), {
            "provider": "Twelve Data",
            "status": "missing_columns",
            "message": f"Colonnes retournées : {list(df.columns)}",
            "td_symbol": td_symbol,
        }

    df["date"] = pd.to_datetime(df["date"], errors="coerce", utc=True)

    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "volume" not in df.columns:
        df["volume"] = np.nan

    for col in ["open", "high", "low"]:
        if col not in df.columns:
            df[col] = df["close"]
        else:
            df[col] = df[col].fillna(df["close"])

    df = (
        df.dropna(subset=["date", "close"])
        .sort_values("date")
        .drop_duplicates("date")
        .reset_index(drop=True)
    )

    keep = [c for c in ["date", "open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[keep].copy()

    return df, {
        "provider": "Twelve Data",
        "status": "ok" if not df.empty else "empty_after_clean",
        "message": "",
        "td_symbol": td_symbol,
        "interval": interval,
        "rows": len(df),
    }


# ============================================================
# END HOTFIX V5 — MISSING TWELVE DATA HELPERS
# ============================================================


# ============================================================
# COMMAND CENTER V6 — REMOVE EMPTY BLUE PANELS + CLEAN SPARKLINES
# ============================================================
# Où coller :
# - Tout à la FIN de asset_class_router.py
# - Après tous les blocs V5 / hotfix.
#
# Objectif :
# - Supprimer les grands rectangles bleu foncé vides.
# - Remplacer les mini-courbes Plotly "undefined" par des sparklines SVG robustes.
# - Garder Databento / Twelve Data / yfinance sans toucher aux moteurs métier.
# ============================================================


def _sparkline_svg_v6(df: pd.DataFrame, change: Any = None, width: int = 360, height: int = 86) -> str:
    """
    Génère une mini-courbe SVG autonome.
    Avantage : pas de Plotly dans les petites cards, donc plus de rendu 'undefined'
    ni de zone vide difficile à contrôler.
    """
    try:
        if df is None or df.empty or "close" not in df.columns:
            return ""

        close = pd.to_numeric(df["close"], errors="coerce").dropna()
        if len(close) < 2:
            return ""

        # Downsample léger.
        if len(close) > 120:
            step = int(np.ceil(len(close) / 120))
            close = close.iloc[::step]

        values = close.to_numpy(dtype=float)
        if not np.isfinite(values).all():
            values = values[np.isfinite(values)]
        if len(values) < 2:
            return ""

        ymin = float(np.min(values))
        ymax = float(np.max(values))
        if ymax == ymin:
            ymax = ymin + 1e-9

        pad_x = 8
        pad_y = 8

        xs = np.linspace(pad_x, width - pad_x, len(values))
        ys = height - pad_y - ((values - ymin) / (ymax - ymin)) * (height - 2 * pad_y)

        points = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))

        x_change = _safe_float(change)
        stroke = "#3cf0b4" if (x_change is None or x_change >= 0) else "#ff5f73"
        fill = "rgba(60,240,180,0.10)" if (x_change is None or x_change >= 0) else "rgba(255,95,115,0.10)"

        baseline = height - pad_y
        area_points = f"{pad_x},{baseline} {points} {width - pad_x},{baseline}"

        return f"""
        <svg viewBox="0 0 {width} {height}" width="100%" height="{height}" preserveAspectRatio="none"
             style="display:block;background:rgba(2,10,23,.35);border-radius:10px;">
            <polyline points="{area_points}" fill="{fill}" stroke="none"></polyline>
            <polyline points="{points}" fill="none" stroke="{stroke}" stroke-width="2.2"
                      stroke-linecap="round" stroke-linejoin="round"></polyline>
        </svg>
        """
    except Exception:
        return ""


def _render_metric_card_v6(label: str, value: str, delta: str | None = None) -> None:
    delta = delta or ""
    delta_color = "#3cf0b4"
    if str(delta).strip().startswith("-"):
        delta_color = "#ff5f73"

    st.markdown(
        f"""
        <div style="
            border:1px solid rgba(90,205,255,.14);
            background:rgba(4,14,29,.70);
            border-radius:14px;
            padding:11px 12px;
            min-height:78px;">
            <div style="color:rgba(230,244,255,.62);font-size:.67rem;font-weight:850;letter-spacing:.10em;text-transform:uppercase;">
                {_cc_escape(str(label))}
            </div>
            <div style="color:#f8fbff;font-size:1.02rem;font-weight:900;margin-top:6px;">
                {_cc_escape(str(value))}
            </div>
            <div style="color:{delta_color};font-size:.72rem;font-weight:850;margin-top:3px;">
                {_cc_escape(str(delta))}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_micro_curve_cards_v4(symbols: list[str], asset_class: str = "Global", max_items: int = 4) -> None:
    """
    Override V6 : mini-courbes sans Plotly.
    Corrige :
    - texte 'undefined'
    - rectangles remplis sans vraie courbe
    - rendu trop lourd dans le cockpit
    """
    shown = [str(s).strip() for s in symbols if str(s).strip()][:max_items]
    if not shown:
        return

    _render_panel_header_v3(
        "Live Curves",
        "Intraday curves · Databento / Twelve Data / yfinance fallback"
    )

    cols = st.columns(len(shown))

    for col, symbol in zip(cols, shown):
        with col:
            s = _normalize_live_symbol_v4(symbol)
            df, meta = get_live_curve_v4(
                s,
                asset_class=asset_class,
                provider="auto",
                lookback_minutes=240,
            )
            metrics = build_live_curve_metrics_v4(df)

            provider = str(meta.get("provider", "None"))
            value = _format_price_by_symbol_v5(s, metrics.get("last"))
            delta = f"{_fmt_pct(metrics.get('change'))} · {provider}"

            st.markdown(
                f"""
                <div style="
                    border:1px solid rgba(90,205,255,.16);
                    background:linear-gradient(180deg,rgba(4,14,29,.82),rgba(2,8,20,.86));
                    border-radius:14px;
                    padding:10px 11px 12px 11px;
                    min-height:170px;">
                    <div style="color:rgba(230,244,255,.70);font-size:.68rem;font-weight:850;letter-spacing:.10em;text-transform:uppercase;">
                        {_cc_escape(s)}
                    </div>
                    <div style="color:#f8fbff;font-size:1.05rem;font-weight:900;margin-top:4px;">
                        {_cc_escape(value)}
                    </div>
                    <div style="color:{'#3cf0b4' if not str(delta).startswith('-') else '#ff5f73'};font-size:.72rem;font-weight:850;margin-top:2px;margin-bottom:8px;">
                        {_cc_escape(delta)}
                    </div>
                    {_sparkline_svg_v6(df, metrics.get("change")) if not df.empty else '<div style="height:86px;border-radius:10px;background:rgba(2,10,23,.42);display:flex;align-items:center;justify-content:center;color:rgba(230,244,255,.45);font-size:.72rem;">No curve</div>'}
                </div>
                """,
                unsafe_allow_html=True,
            )


def _render_simple_panel_header_v6(title: str, subtitle: str | None = None) -> None:
    st.markdown(
        f"""
        <div style="margin-bottom:8px;">
            <div style="color:#55e8ff;font-size:.76rem;font-weight:950;letter-spacing:.20em;text-transform:uppercase;">
                {_cc_escape(title)}
            </div>
            <div style="color:rgba(220,235,250,.52);font-size:.72rem;margin-top:3px;">
                {_cc_escape(subtitle or '')}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_command_center_section_v6(title: str, subtitle: str | None = None) -> None:
    st.markdown("---")
    _render_simple_panel_header_v6(title, subtitle)


def render_global_command_center() -> None:
    """
    Override V6 : même cockpit, mais sans faux wrappers HTML vides.
    Les anciens rectangles bleu foncé venaient de st.markdown('<div class="cc-v3-panel">')
    utilisé comme conteneur autour de widgets Streamlit. Streamlit ne permet pas
    d'ouvrir un div HTML dans un appel puis d'y placer des widgets dans les appels suivants.
    """
    inject_command_center_css()

    current_asset = st.session_state.get("asset_class", "Equity")
    current_profile = get_asset_profile(current_asset)

    st.markdown(
        """
        <div class="cc-v3-hero">
            <div class="cc-v3-kicker">GLOBAL COMMAND CENTER</div>
            <div class="cc-v3-title">Institutional Multi-Asset Cockpit</div>
            <div class="cc-v3-sub">
                Recherche centrale, market tape, régime cross-asset, courbes live/intraday, FX board, commodities board, news et quick launch.
                Databento est utilisé en priorité sur futures/proxies mappés ; Twelve Data pour FX spot / equities / ETF ; yfinance en fallback.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form("global_command_center_form_v6"):
        c1, c2, c3, c4, c5, c6 = st.columns(
            [1.0, 2.25, 1.25, 0.85, 0.85, 1.0],
            vertical_alignment="bottom",
        )
        with c1:
            asset_choice = st.selectbox(
                "Asset Class",
                ["Auto"] + get_asset_classes(),
                index=0,
                key="gcc_asset_choice_v6",
            )
        with c2:
            raw_symbol = st.text_input(
                "Search / Command",
                value=st.session_state.get("ticker") or current_profile["default_symbol"],
                placeholder="NVDA, EURUSD, CL=F, ^TNX, TLT...",
                key="gcc_symbol_input_v6",
            )

        inferred_asset = infer_asset_class_from_symbol(raw_symbol, fallback=current_asset)
        effective_asset = inferred_asset if asset_choice == "Auto" else asset_choice
        effective_profile = get_asset_profile(effective_asset)

        with c3:
            mode_choice = st.selectbox(
                "Mode",
                effective_profile["mode_options"],
                index=0,
                key=f"gcc_mode_choice_v6_{effective_asset}",
            )
        with c4:
            period_choice = st.selectbox(
                "Period",
                ["3mo", "6mo", "1y", "2y", "5y", "10y"],
                index=_select_index(
                    ["3mo", "6mo", "1y", "2y", "5y", "10y"],
                    effective_profile["default_period"],
                    2,
                ),
                key=f"gcc_period_choice_v6_{effective_asset}",
            )
        with c5:
            interval_choice = st.selectbox(
                "Interval",
                ["1d", "1wk", "1mo"],
                index=0,
                key=f"gcc_interval_choice_v6_{effective_asset}",
            )
        with c6:
            launch = st.form_submit_button("LAUNCH", use_container_width=True)

        if launch:
            resolved_asset, resolved_symbol, resolved_mode = resolve_asset_symbol_and_mode(
                effective_asset,
                raw_symbol,
                mode_choice,
            )
            _launch_workspace(resolved_asset, resolved_symbol, period_choice, interval_choice, resolved_mode)

    resolved_preview_asset, resolved_preview_symbol, resolved_preview_mode = resolve_asset_symbol_and_mode(
        effective_asset,
        raw_symbol,
        mode_choice,
    )
    st.caption(
        f"Inference preview : {resolved_preview_asset} · normalized symbol : "
        f"{resolved_preview_symbol} · mode : {resolved_preview_mode}"
    )

    tape_df = load_market_tape_snapshot(tuple(MARKET_TAPE_UNIVERSES["Global"]))
    regime = build_cross_asset_regime(tape_df)
    overview = build_market_overview_v3(tape_df)
    news_df = load_latest_news_snapshot(limit=10)
    gainers, losers = build_movers_v3(tape_df, n=5)
    curve_df = build_curve_snapshot_v3(tape_df)

    # Top strip
    if tape_df is not None and not tape_df.empty:
        lookup = {row.get("Symbol"): row for _, row in tape_df.iterrows()}
        strip_items = [
            ("S&P FUT", lookup.get("ES=F")),
            ("NASDAQ FUT", lookup.get("NQ=F")),
            ("VIX", lookup.get("^VIX")),
            ("DXY", lookup.get("DX-Y.NYB")),
            ("10Y", lookup.get("^TNX")),
            ("WTI", lookup.get("CL=F")),
        ]
        html = ['<div class="cc-v3-strip">']
        for label, row in strip_items:
            if row is None:
                value, meta = "N/A", "WAIT"
            else:
                value, meta = _value_for_symbol(row), _fmt_pct(row.get("Change %"))
            html.append(
                f'<div class="cc-v3-strip-card">'
                f'<div class="cc-v3-strip-label">{_cc_escape(label)}</div>'
                f'<div class="cc-v3-strip-value">{_cc_escape(value)}</div>'
                f'<div class="cc-v3-strip-meta">{_cc_escape(meta)}</div>'
                f'</div>'
            )
        html.append('</div>')
        st.markdown("".join(html), unsafe_allow_html=True)

    _render_command_center_section_v6(
        "Live Curves",
        "Intraday curves · compact SVG sparklines · provider aware",
    )
    chart_symbols = LIVE_CHART_DEFAULTS.get(resolved_preview_asset, LIVE_CHART_DEFAULTS["Global"])
    _render_micro_curve_cards_v4(chart_symbols, asset_class=resolved_preview_asset, max_items=4)

    _render_command_center_section_v6(
        "Global Market Tape",
        "Cross-asset instruments and public proxies",
    )
    _render_compact_tape_v3(tape_df, max_cards=12)

    _render_command_center_section_v6(
        "Macro Monitor",
        "Regime, curve, movers and news",
    )

    left, mid, right = st.columns([1.20, 1.0, 1.10])

    with left:
        _render_regime_panel_v3(regime, overview)

    with mid:
        _render_simple_panel_header_v6("Rates / Curve", "Yield proxies and curve state")
        if curve_df.empty:
            st.caption("Curve snapshot indisponible.")
        else:
            st.dataframe(curve_df, use_container_width=True, hide_index=True)

        _render_simple_panel_header_v6("Top Movers", "Current global tape")
        mtab1, mtab2 = st.tabs(["Gainers", "Losers"])
        with mtab1:
            st.dataframe(gainers, use_container_width=True, hide_index=True)
        with mtab2:
            st.dataframe(losers, use_container_width=True, hide_index=True)

    with right:
        _render_news_panel_v3(news_df)

    _render_command_center_section_v6(
        "Asset Boards",
        "FX, commodities and module launchpad",
    )

    b1, b2, b3 = st.columns([1, 1, 1])

    with b1:
        _render_simple_panel_header_v6("FX Board", "Majors and dollar regime")
        fx_board = build_fx_board_v3()
        st.dataframe(fx_board, use_container_width=True, hide_index=True)

    with b2:
        _render_simple_panel_header_v6("Commodities Board", "Energy, metals and agricultural proxies")
        commo_board = build_commodity_board_v3()
        st.dataframe(commo_board, use_container_width=True, hide_index=True)

    with b3:
        _render_quick_modules_v3(resolved_preview_asset)
        qcols = st.columns(2)
        for idx, asset_class in enumerate(get_asset_classes()):
            profile = get_asset_profile(asset_class)
            with qcols[idx % 2]:
                if st.button(
                    f"OPEN {profile['label']}",
                    key=f"gcc_quick_open_v6_{asset_class}",
                    use_container_width=True,
                ):
                    _launch_workspace(
                        asset_class,
                        profile["default_symbol"],
                        profile["default_period"],
                        profile["default_interval"],
                        default_mode_for_asset(asset_class),
                    )

    _render_command_center_section_v6(
        "Full Tape",
        "Global / Equity / FX / Commodities / Rates",
    )

    tab_names = ["Global", "Equity", "FX", "Commodities", "Rates"]
    tabs = st.tabs(tab_names)

    for tab, name in zip(tabs, tab_names):
        with tab:
            symbols = tuple(MARKET_TAPE_UNIVERSES.get(name, MARKET_TAPE_UNIVERSES["Global"]))
            df = load_market_tape_snapshot(symbols)
            display = _prepare_tape_display(df)
            if display.empty:
                st.info(f"{name} tape indisponible.")
            else:
                st.dataframe(display, use_container_width=True, hide_index=True)


def render_asset_class_home() -> None:
    render_global_command_center()


# ============================================================
# END COMMAND CENTER V6 — REMOVE EMPTY BLUE PANELS
# ============================================================



# ============================================================
# COMMAND CENTER V7 — LIVE REFRESH + CLEAN MINI CHARTS
# ============================================================
# Où coller :
# - Tout à la FIN de asset_class_router.py
# - Après le patch V6.
#
# Ce que ça corrige :
# 1) Les mini-courbes ne sont plus injectées en HTML brut.
#    Donc plus de texte "</div>" visible.
# 2) Le double titre "LIVE CURVES" disparaît.
# 3) Ajout d'un auto-refresh Streamlit si le package streamlit-autorefresh est installé.
# 4) Market tape réduit à un cache court.
#
# Installation recommandée pour auto-refresh réel côté UI :
#     pip install streamlit-autorefresh
#
# Important :
# - Ce patch donne du "near-live" pull-based.
# - Le vrai streaming tick-by-tick demandera un collecteur séparé Databento Live / Twelve WebSocket.
# ============================================================

import time


# ------------------------------------------------------------
# V7 — live refresh controller
# ------------------------------------------------------------

LIVE_REFRESH_SECONDS_V7 = 15


def _live_refresh_token_v7(interval_sec: int = LIVE_REFRESH_SECONDS_V7) -> int:
    interval_sec = int(max(5, interval_sec or LIVE_REFRESH_SECONDS_V7))
    return int(time.time() // interval_sec)


def _maybe_autorefresh_v7(enabled: bool = True, interval_sec: int = LIVE_REFRESH_SECONDS_V7) -> int:
    """
    Déclenche un rerun automatique si streamlit-autorefresh est installé.
    Sinon, renvoie seulement un token temporel qui se mettra à jour au prochain rerun manuel.
    """
    interval_sec = int(max(5, interval_sec or LIVE_REFRESH_SECONDS_V7))
    token = _live_refresh_token_v7(interval_sec)

    st.session_state["_live_refresh_token_v7"] = token
    st.session_state["_live_refresh_seconds_v7"] = interval_sec

    if not enabled:
        return token

    try:
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(
            interval=interval_sec * 1000,
            key="quant_terminal_live_autorefresh_v7",
        )
    except Exception:
        # Pas d'erreur bloquante : l'app doit rester utilisable.
        st.session_state["_live_autorefresh_missing_v7"] = True

    return token


# ------------------------------------------------------------
# V7 — shorter-cache market tape override
# ------------------------------------------------------------

@st.cache_data(ttl=15, show_spinner=False)
def _download_one_symbol_snapshot(symbol: str, period: str = "1d") -> dict[str, Any]:
    """
    Override V7 : snapshot plus proche du live.
    Priorité :
    - yfinance intraday 1m pour éviter les prix daily trop statiques
    - fallback daily 5d si 1m indisponible
    """
    symbol = str(symbol or "").upper().strip()
    empty = {
        "Symbol": symbol,
        "Name": SYMBOL_LABELS.get(symbol, symbol),
        "Last": np.nan,
        "Change %": np.nan,
        "Volume": np.nan,
        "Status": "WAIT",
    }

    if not symbol or not YFINANCE_AVAILABLE:
        return empty

    try:
        raw = yf.download(
            symbol,
            period="1d",
            interval="1m",
            progress=False,
            auto_adjust=False,
            threads=False,
        )

        if raw is None or raw.empty:
            raw = yf.download(
                symbol,
                period="5d",
                interval="5m",
                progress=False,
                auto_adjust=False,
                threads=False,
            )

        if raw is None or raw.empty:
            raw = yf.download(
                symbol,
                period="5d",
                interval="1d",
                progress=False,
                auto_adjust=False,
                threads=False,
            )

        if raw is None or raw.empty:
            return empty

        df = raw.copy().reset_index()

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [
                "_".join([str(x) for x in col if str(x) not in ["", "None"]])
                .strip("_")
                .lower()
                for col in df.columns
            ]
        else:
            df.columns = [str(c).lower().replace(" ", "_") for c in df.columns]

        close_like = [c for c in df.columns if "close" in str(c).lower()]
        if not close_like:
            return empty

        close = pd.to_numeric(df[close_like[0]], errors="coerce").dropna()
        if close.empty:
            return empty

        last = float(close.iloc[-1])
        first = float(close.iloc[0])
        change = last / first - 1 if first and np.isfinite(first) and first != 0 else np.nan

        volume = np.nan
        vol_like = [c for c in df.columns if "volume" in str(c).lower()]
        if vol_like:
            volume_series = pd.to_numeric(df[vol_like[0]], errors="coerce").dropna()
            if not volume_series.empty:
                volume = float(volume_series.iloc[-1])

        return {
            "Symbol": symbol,
            "Name": SYMBOL_LABELS.get(symbol, symbol),
            "Last": last,
            "Change %": change,
            "Volume": volume,
            "Status": "LIVE" if len(close) > 2 else "OK",
        }
    except Exception:
        return empty


@st.cache_data(ttl=15, show_spinner=False)
def load_market_tape_snapshot(symbols: tuple[str, ...]) -> pd.DataFrame:
    rows = [_download_one_symbol_snapshot(sym) for sym in symbols]
    if not rows:
        return pd.DataFrame(columns=["Symbol", "Name", "Last", "Change %", "Volume", "Status"])
    return pd.DataFrame(rows)


# ------------------------------------------------------------
# V7 — direct Twelve Data pull, cache-busted by refresh token
# ------------------------------------------------------------

@st.cache_data(ttl=10, show_spinner=False)
def fetch_twelve_data_intraday_v7(
    symbol: str,
    asset_class: str = "Global",
    interval: str = "1min",
    outputsize: int = 240,
    refresh_token: int | None = None,
) -> pd.DataFrame:
    """
    Twelve Data pull avec refresh_token dans la clé de cache.
    Le token force une actualisation toutes les X secondes si l'UI rerun.
    """
    try:
        df, meta = get_twelve_data_intraday_frame(
            symbol=symbol,
            asset_class=asset_class,
            interval=interval,
            outputsize=outputsize,
        )
        if df is None or df.empty:
            return pd.DataFrame()

        return _standardize_twelve_data_frame_v5(
            df=df,
            symbol=symbol,
            asset_class=asset_class,
            provider_symbol=meta.get("td_symbol") or to_twelve_data_symbol(symbol, asset_class),
        )
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=10, show_spinner=False)
def fetch_databento_ohlcv_v7(
    symbol: str,
    lookback_minutes: int = 390,
    schema: str = "ohlcv-1m",
    refresh_token: int | None = None,
) -> pd.DataFrame:
    """
    Databento pull avec refresh_token.
    Ce n'est pas encore un stream db.Live : c'est un pull historical intraday court.
    """
    try:
        return fetch_databento_ohlcv_v4(
            symbol=symbol,
            lookback_minutes=lookback_minutes,
            schema=schema,
        )
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=10, show_spinner=False)
def fetch_yfinance_intraday_v7(
    symbol: str,
    period: str = "1d",
    interval: str = "1m",
    refresh_token: int | None = None,
) -> pd.DataFrame:
    try:
        return fetch_yfinance_intraday_v4(symbol=symbol, period=period, interval=interval)
    except Exception:
        return pd.DataFrame()


def get_live_curve_v7(
    symbol: str,
    asset_class: str = "Global",
    provider: str = "auto",
    lookback_minutes: int = 390,
    refresh_token: int | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    s = _normalize_live_symbol_v4(symbol)
    refresh_token = refresh_token if refresh_token is not None else st.session_state.get("_live_refresh_token_v7", 0)

    try:
        order = _provider_order_v5(s, asset_class, provider)
    except Exception:
        order = ["yfinance"]

    errors: list[str] = []
    df = pd.DataFrame()
    used_provider = "None"

    for p in order:
        try:
            if p == "databento":
                df = fetch_databento_ohlcv_v7(
                    s,
                    lookback_minutes=lookback_minutes,
                    refresh_token=refresh_token,
                )
                if df is not None and not df.empty:
                    used_provider = "Databento"
                    break

            elif p in {"twelvedata", "twelve"}:
                df = fetch_twelve_data_intraday_v7(
                    s,
                    asset_class=asset_class,
                    interval="1min",
                    outputsize=int(max(60, min(500, lookback_minutes))),
                    refresh_token=refresh_token,
                )
                if df is not None and not df.empty:
                    used_provider = "Twelve Data"
                    break

            elif p == "yfinance":
                df = fetch_yfinance_intraday_v7(
                    s,
                    refresh_token=refresh_token,
                )
                if df is not None and not df.empty:
                    used_provider = "yfinance"
                    break

        except Exception as exc:
            errors.append(f"{p}: {exc}")

    cfg = DATABENTO_PROXY_MAP.get(s, {})

    try:
        td_symbol = to_twelve_data_symbol(s, asset_class)
    except Exception:
        td_symbol = None

    provider_symbol = s
    if df is not None and not df.empty and "provider_symbol" in df.columns:
        try:
            provider_symbol = str(df["provider_symbol"].dropna().iloc[-1])
        except Exception:
            provider_symbol = cfg.get("symbol", td_symbol or s)
    elif used_provider == "Databento":
        provider_symbol = cfg.get("symbol", s)
    elif used_provider == "Twelve Data":
        provider_symbol = td_symbol or s

    meta = {
        "symbol": s,
        "asset_class": asset_class,
        "provider": used_provider,
        "provider_order": " > ".join(order),
        "provider_symbol": provider_symbol,
        "databento_configured": databento_configured_v4(),
        "databento_mapped": s in DATABENTO_PROXY_MAP,
        "twelve_data_configured": twelve_data_enabled() if "twelve_data_enabled" in globals() else False,
        "twelve_data_candidate": _twelve_data_candidate_v5(s, asset_class) if "_twelve_data_candidate_v5" in globals() else False,
        "twelve_data_symbol": td_symbol,
        "proxy_note": cfg.get("proxy_note", ""),
        "label": cfg.get("label", s),
        "errors": "; ".join(errors[-3:]),
        "refresh_token": refresh_token,
        "last_refresh_utc": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
    }

    return df if df is not None else pd.DataFrame(), meta


# Keep compatibility name. Existing dashboards now use the V7 live curve.
def get_live_curve_v4(
    symbol: str,
    asset_class: str = "Global",
    provider: str = "auto",
    lookback_minutes: int = 390,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    return get_live_curve_v7(
        symbol=symbol,
        asset_class=asset_class,
        provider=provider,
        lookback_minutes=lookback_minutes,
        refresh_token=st.session_state.get("_live_refresh_token_v7", 0),
    )


# ------------------------------------------------------------
# V7 — clean mini-cards, no raw closing tags, no duplicate title
# ------------------------------------------------------------

def _render_micro_curve_cards_v4(symbols: list[str], asset_class: str = "Global", max_items: int = 4) -> None:
    """
    Override V7.
    Ne rend PAS de titre interne. Le titre est rendu par render_global_command_center().
    Ne met PAS de SVG/HTML complexe dans un div parent.
    """
    shown = [str(s).strip() for s in symbols if str(s).strip()][:max_items]
    if not shown:
        return

    refresh_token = st.session_state.get("_live_refresh_token_v7", 0)

    cols = st.columns(len(shown))

    for col, symbol in zip(cols, shown):
        with col:
            s = _normalize_live_symbol_v4(symbol)
            df, meta = get_live_curve_v7(
                s,
                asset_class=asset_class,
                provider="auto",
                lookback_minutes=240,
                refresh_token=refresh_token,
            )
            metrics = build_live_curve_metrics_v4(df)

            provider = str(meta.get("provider", "None"))
            value = _format_price_by_symbol_v5(s, metrics.get("last"))
            delta = _fmt_pct(metrics.get("change"))
            delta_color = "#3cf0b4" if not str(delta).startswith("-") else "#ff5f73"

            st.markdown(
                f"""
                <div style="
                    border:1px solid rgba(90,205,255,.16);
                    background:linear-gradient(180deg,rgba(4,14,29,.82),rgba(2,8,20,.86));
                    border-radius:14px;
                    padding:10px 11px;
                    margin-bottom:7px;">
                    <div style="color:rgba(230,244,255,.70);font-size:.68rem;font-weight:850;letter-spacing:.10em;text-transform:uppercase;">
                        {_cc_escape(s)}
                    </div>
                    <div style="color:#f8fbff;font-size:1.05rem;font-weight:900;margin-top:4px;">
                        {_cc_escape(value)}
                    </div>
                    <div style="color:{delta_color};font-size:.72rem;font-weight:850;margin-top:2px;">
                        {_cc_escape(delta)} · {_cc_escape(provider)}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            if df is None or df.empty:
                st.caption("No curve")
                continue

            plot_df = _downsample_for_plot_v5(df, max_points=160)
            fig = go.Figure()
            line_color, fill_color = _curve_color_v5(metrics.get("change"))
            fig.add_trace(
                go.Scatter(
                    x=plot_df["date"],
                    y=plot_df["close"],
                    mode="lines",
                    line=dict(width=1.8, color=line_color),
                    fill="tozeroy",
                    fillcolor=fill_color,
                    hovertemplate="%{x}<br>%{y}<extra></extra>",
                    name=s,
                )
            )
            fig.update_layout(
                height=132,
                template="plotly_dark",
                margin=dict(l=0, r=0, t=0, b=0),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(4,12,26,0.18)",
                showlegend=False,
                xaxis=dict(visible=False, showgrid=False),
                yaxis=dict(visible=False, showgrid=False, zeroline=False),
            )
            st.plotly_chart(
                fig,
                use_container_width=True,
                config={"displayModeBar": False, "responsive": True},
            )
            st.caption(f"Updated {meta.get('last_refresh_utc', '')}")


# ------------------------------------------------------------
# V7 — inject refresh controls before the command center
# ------------------------------------------------------------

def render_asset_class_home() -> None:
    """
    Entrée app.py. Ajoute le contrôle live avant le cockpit.
    """
    c1, c2, c3 = st.columns([1.1, 0.7, 2.2], vertical_alignment="bottom")

    with c1:
        auto_refresh = st.toggle(
            "Live auto-refresh",
            value=True,
            key="live_auto_refresh_v7",
        )

    with c2:
        refresh_seconds = st.selectbox(
            "Refresh",
            [5, 10, 15, 30, 60],
            index=2,
            key="live_refresh_seconds_select_v7",
        )

    token = _maybe_autorefresh_v7(
        enabled=auto_refresh,
        interval_sec=int(refresh_seconds),
    )

    with c3:
        missing = st.session_state.get("_live_autorefresh_missing_v7", False)
        if missing and auto_refresh:
            st.caption(
                "Auto-refresh UI non actif : installe `streamlit-autorefresh`. "
                "Les données se mettront à jour au prochain rerun manuel."
            )
        else:
            st.caption(
                f"Live pull mode · refresh={refresh_seconds}s · token={token} · "
                f"{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}"
            )

    render_global_command_center()


# ============================================================
# END COMMAND CENTER V7 — LIVE REFRESH + CLEAN MINI CHARTS
# ============================================================


# ============================================================
# COMMAND CENTER V8 — VISUAL POLISH + HONEST LIVE STATE
# ============================================================
# Où coller :
# - Tout à la FIN de asset_class_router.py
# - Après le patch V7.
#
# Objectifs :
# - Nettoyer le rendu : plus de gros blocs vides, moins de hauteur morte.
# - Corriger les cartes macro qui coupent les mots DEFENSIVE/RISING/etc.
# - Rendre les courbes moins "rectangles rouges" : ligne propre, zone très légère.
# - Mettre l'état live au clair : LIVE PULL / AUTO-REFRESH ACTIVE / MANUAL REFRESH.
# - Garder les fonctions existantes et ne pas toucher aux moteurs métier.
# ============================================================


# ------------------------------------------------------------
# V8 — compact section / cards
# ------------------------------------------------------------

def _section_v8(title: str, subtitle: str | None = None) -> None:
    st.markdown(
        f"""
        <div style="
            border-top:1px solid rgba(90,205,255,.18);
            margin:22px 0 10px 0;
            padding-top:13px;">
            <div style="color:#55e8ff;font-size:.76rem;font-weight:950;letter-spacing:.22em;text-transform:uppercase;">
                {_cc_escape(str(title))}
            </div>
            <div style="color:rgba(220,235,250,.54);font-size:.73rem;margin-top:3px;">
                {_cc_escape(str(subtitle or ""))}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _status_pill_v8(label: str, value: str, tone: str = "neutral") -> None:
    if tone == "good":
        color = "#3cf0b4"
        bg = "rgba(60,240,180,.09)"
    elif tone == "bad":
        color = "#ff5f73"
        bg = "rgba(255,95,115,.09)"
    elif tone == "warn":
        color = "#ffd166"
        bg = "rgba(255,209,102,.09)"
    else:
        color = "#55e8ff"
        bg = "rgba(85,232,255,.08)"

    st.markdown(
        f"""
        <div style="
            border:1px solid rgba(90,205,255,.14);
            background:{bg};
            border-radius:12px;
            padding:8px 10px;">
            <div style="color:rgba(230,244,255,.58);font-size:.63rem;font-weight:850;letter-spacing:.10em;text-transform:uppercase;">
                {_cc_escape(label)}
            </div>
            <div style="color:{color};font-size:.82rem;font-weight:900;margin-top:2px;white-space:nowrap;">
                {_cc_escape(value)}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ------------------------------------------------------------
# V8 — regime cards without broken words
# ------------------------------------------------------------

def _render_regime_panel_v3(regime: dict[str, Any], overview: pd.DataFrame) -> None:
    _section_v8("Cross-Asset Regime", "Risk, volatility, dollar, rates and commodities")

    items = [
        ("Risk", regime.get("risk", "N/A")),
        ("Vol", regime.get("vol", "N/A")),
        ("Dollar", regime.get("dollar", "N/A")),
        ("Rates", regime.get("rates", "N/A")),
        ("Commo", regime.get("commodities", "N/A")),
    ]

    cols = st.columns(5)
    for col, (label, value) in zip(cols, items):
        v = str(value)
        tone = "neutral"
        if v in {"CONSTRUCTIVE", "FALLING", "WEAK", "LOWER", "BID"}:
            tone = "good"
        elif v in {"DEFENSIVE", "RISING", "STRONG", "HIGHER", "OFFERED"}:
            tone = "bad"
        elif v in {"BALANCED", "NORMAL", "NEUTRAL", "STABLE", "MIXED"}:
            tone = "warn"

        with col:
            _status_pill_v8(label, v, tone=tone)

    st.caption(str(regime.get("read", "")))

    if overview is not None and not overview.empty:
        st.dataframe(overview, use_container_width=True, hide_index=True)


# ------------------------------------------------------------
# V8 — cleaner micro live charts
# ------------------------------------------------------------

def _make_micro_chart_v8(df: pd.DataFrame, symbol: str, change: Any, height: int = 150) -> go.Figure:
    plot_df = _downsample_for_plot_v5(df, max_points=180)
    line_color, fill_color = _curve_color_v5(change)

    fig = go.Figure()

    if plot_df is not None and not plot_df.empty:
        fig.add_trace(
            go.Scatter(
                x=plot_df["date"],
                y=plot_df["close"],
                mode="lines",
                line=dict(width=2.0, color=line_color),
                fill="tonexty",
                fillcolor=fill_color.replace("0.10", "0.045") if isinstance(fill_color, str) else fill_color,
                hovertemplate="%{x}<br>%{y}<extra></extra>",
                name=symbol,
            )
        )

        try:
            last = _safe_float(plot_df["close"].iloc[-1])
            if last is not None:
                fig.add_hline(
                    y=last,
                    line_width=1,
                    line_dash="dot",
                    line_color="rgba(255,255,255,.22)",
                )
        except Exception:
            pass

    fig.update_layout(
        height=height,
        template="plotly_dark",
        margin=dict(l=2, r=2, t=4, b=2),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(2,10,23,.25)",
        showlegend=False,
        hovermode="x unified",
        xaxis=dict(visible=False, showgrid=False, zeroline=False),
        yaxis=dict(visible=False, showgrid=False, zeroline=False),
    )
    return fig


def _render_micro_curve_cards_v4(symbols: list[str], asset_class: str = "Global", max_items: int = 4) -> None:
    shown = [str(s).strip() for s in symbols if str(s).strip()][:max_items]
    if not shown:
        return

    refresh_token = st.session_state.get("_live_refresh_token_v7", 0)
    cols = st.columns(len(shown))

    for col, symbol in zip(cols, shown):
        with col:
            s = _normalize_live_symbol_v4(symbol)
            df, meta = get_live_curve_v7(
                s,
                asset_class=asset_class,
                provider="auto",
                lookback_minutes=240,
                refresh_token=refresh_token,
            )
            metrics = build_live_curve_metrics_v4(df)

            provider = str(meta.get("provider", "None"))
            value = _format_price_by_symbol_v5(s, metrics.get("last"))
            delta = _fmt_pct(metrics.get("change"))
            delta_color = "#3cf0b4" if not str(delta).startswith("-") else "#ff5f73"

            st.markdown(
                f"""
                <div style="
                    border:1px solid rgba(90,205,255,.16);
                    background:linear-gradient(180deg,rgba(4,14,29,.82),rgba(2,8,20,.86));
                    border-radius:14px;
                    padding:10px 11px 9px 11px;
                    margin-bottom:6px;">
                    <div style="color:rgba(230,244,255,.70);font-size:.68rem;font-weight:850;letter-spacing:.10em;text-transform:uppercase;">
                        {_cc_escape(s)}
                    </div>
                    <div style="display:flex;align-items:baseline;gap:8px;margin-top:4px;">
                        <div style="color:#f8fbff;font-size:1.05rem;font-weight:900;">
                            {_cc_escape(value)}
                        </div>
                        <div style="color:{delta_color};font-size:.70rem;font-weight:850;">
                            {_cc_escape(delta)}
                        </div>
                    </div>
                    <div style="color:rgba(220,235,250,.52);font-size:.66rem;font-weight:760;margin-top:2px;">
                        {_cc_escape(provider)}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            if df is None or df.empty:
                st.caption("No curve")
                continue

            fig = _make_micro_chart_v8(df, s, metrics.get("change"), height=145)
            st.plotly_chart(
                fig,
                use_container_width=True,
                config={"displayModeBar": False, "responsive": True},
            )

            st.caption(f"{meta.get('last_refresh_utc', '')}")


# ------------------------------------------------------------
# V8 — top live state
# ------------------------------------------------------------

def _render_live_state_bar_v8(auto_refresh: bool, refresh_seconds: int, token: int) -> None:
    auto_ok = not st.session_state.get("_live_autorefresh_missing_v7", False)

    provider_bits = []
    provider_bits.append("Databento OK" if databento_configured_v4() else "Databento missing")
    try:
        provider_bits.append("Twelve OK" if twelve_data_enabled() else "Twelve missing")
    except Exception:
        provider_bits.append("Twelve missing")
    provider_bits.append("yfinance OK" if YFINANCE_AVAILABLE else "yfinance missing")

    tone = "good" if auto_refresh and auto_ok else "warn"
    mode = "AUTO-REFRESH ACTIVE" if auto_refresh and auto_ok else "MANUAL / PULL ONLY"

    cols = st.columns([1.2, 1.0, 2.4], vertical_alignment="center")
    with cols[0]:
        _status_pill_v8("Live mode", mode, tone=tone)
    with cols[1]:
        _status_pill_v8("Refresh", f"{refresh_seconds}s · token {token}", tone="neutral")
    with cols[2]:
        st.caption(" · ".join(provider_bits))


# ------------------------------------------------------------
# V8 — command center override
# ------------------------------------------------------------

def render_asset_class_home() -> None:
    c1, c2 = st.columns([0.9, 0.9], vertical_alignment="bottom")

    with c1:
        auto_refresh = st.toggle(
            "Live auto-refresh",
            value=True,
            key="live_auto_refresh_v8",
        )

    with c2:
        refresh_seconds = st.selectbox(
            "Refresh",
            [5, 10, 15, 30, 60],
            index=1,
            key="live_refresh_seconds_select_v8",
        )

    token = _maybe_autorefresh_v7(
        enabled=auto_refresh,
        interval_sec=int(refresh_seconds),
    )

    _render_live_state_bar_v8(auto_refresh, int(refresh_seconds), token)
    render_global_command_center()


def render_global_command_center() -> None:
    inject_command_center_css()

    current_asset = st.session_state.get("asset_class", "Equity")
    current_profile = get_asset_profile(current_asset)

    st.markdown(
        """
        <div class="cc-v3-hero">
            <div class="cc-v3-kicker">GLOBAL COMMAND CENTER</div>
            <div class="cc-v3-title">Institutional Multi-Asset Cockpit</div>
            <div class="cc-v3-sub">
                Multi-asset monitoring, near-live pull, regime detection, market tape, news and launchpad.
                For true tick-by-tick live, use an external Databento/Twelve collector writing to a local cache.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form("global_command_center_form_v8"):
        c1, c2, c3, c4, c5, c6 = st.columns(
            [1.0, 2.25, 1.25, 0.85, 0.85, 1.0],
            vertical_alignment="bottom",
        )
        with c1:
            asset_choice = st.selectbox(
                "Asset Class",
                ["Auto"] + get_asset_classes(),
                index=0,
                key="gcc_asset_choice_v8",
            )
        with c2:
            raw_symbol = st.text_input(
                "Search / Command",
                value=st.session_state.get("ticker") or current_profile["default_symbol"],
                placeholder="NVDA, EURUSD, CL=F, ^TNX, TLT...",
                key="gcc_symbol_input_v8",
            )

        inferred_asset = infer_asset_class_from_symbol(raw_symbol, fallback=current_asset)
        effective_asset = inferred_asset if asset_choice == "Auto" else asset_choice
        effective_profile = get_asset_profile(effective_asset)

        with c3:
            mode_choice = st.selectbox(
                "Mode",
                effective_profile["mode_options"],
                index=0,
                key=f"gcc_mode_choice_v8_{effective_asset}",
            )
        with c4:
            period_choice = st.selectbox(
                "Period",
                ["3mo", "6mo", "1y", "2y", "5y", "10y"],
                index=_select_index(
                    ["3mo", "6mo", "1y", "2y", "5y", "10y"],
                    effective_profile["default_period"],
                    2,
                ),
                key=f"gcc_period_choice_v8_{effective_asset}",
            )
        with c5:
            interval_choice = st.selectbox(
                "Interval",
                ["1d", "1wk", "1mo"],
                index=0,
                key=f"gcc_interval_choice_v8_{effective_asset}",
            )
        with c6:
            launch = st.form_submit_button("LAUNCH", use_container_width=True)

        if launch:
            resolved_asset, resolved_symbol, resolved_mode = resolve_asset_symbol_and_mode(
                effective_asset,
                raw_symbol,
                mode_choice,
            )
            _launch_workspace(resolved_asset, resolved_symbol, period_choice, interval_choice, resolved_mode)

    resolved_preview_asset, resolved_preview_symbol, resolved_preview_mode = resolve_asset_symbol_and_mode(
        effective_asset,
        raw_symbol,
        mode_choice,
    )
    st.caption(
        f"Inference: {resolved_preview_asset} · {resolved_preview_symbol} · {resolved_preview_mode}"
    )

    tape_df = load_market_tape_snapshot(tuple(MARKET_TAPE_UNIVERSES["Global"]))
    regime = build_cross_asset_regime(tape_df)
    overview = build_market_overview_v3(tape_df)
    news_df = load_latest_news_snapshot(limit=8)
    gainers, losers = build_movers_v3(tape_df, n=5)
    curve_df = build_curve_snapshot_v3(tape_df)

    # Top strip
    if tape_df is not None and not tape_df.empty:
        lookup = {row.get("Symbol"): row for _, row in tape_df.iterrows()}
        strip_items = [
            ("S&P FUT", lookup.get("ES=F")),
            ("NASDAQ FUT", lookup.get("NQ=F")),
            ("VIX", lookup.get("^VIX")),
            ("DXY", lookup.get("DX-Y.NYB")),
            ("10Y", lookup.get("^TNX")),
            ("WTI", lookup.get("CL=F")),
        ]
        html = ['<div class="cc-v3-strip">']
        for label, row in strip_items:
            value, meta = ("N/A", "WAIT") if row is None else (_value_for_symbol(row), _fmt_pct(row.get("Change %")))
            html.append(
                f'<div class="cc-v3-strip-card">'
                f'<div class="cc-v3-strip-label">{_cc_escape(label)}</div>'
                f'<div class="cc-v3-strip-value">{_cc_escape(value)}</div>'
                f'<div class="cc-v3-strip-meta">{_cc_escape(meta)}</div>'
                f'</div>'
            )
        html.append('</div>')
        st.markdown("".join(html), unsafe_allow_html=True)

    _section_v8("Live Curves", "Provider-aware intraday charts")
    chart_symbols = LIVE_CHART_DEFAULTS.get(resolved_preview_asset, LIVE_CHART_DEFAULTS["Global"])
    _render_micro_curve_cards_v4(chart_symbols, asset_class=resolved_preview_asset, max_items=4)

    _section_v8("Global Market Tape", "Cross-asset instruments and public proxies")
    _render_compact_tape_v3(tape_df, max_cards=12)

    _section_v8("Macro Monitor", "Regime, curve, movers and news")
    left, mid, right = st.columns([1.20, 1.0, 1.10])

    with left:
        _render_regime_panel_v3(regime, overview)

    with mid:
        _section_v8("Rates / Curve", "Yield proxies and curve state")
        if curve_df.empty:
            st.caption("Curve snapshot indisponible.")
        else:
            st.dataframe(curve_df, use_container_width=True, hide_index=True)

        _section_v8("Top Movers", "Current global tape")
        mtab1, mtab2 = st.tabs(["Gainers", "Losers"])
        with mtab1:
            st.dataframe(gainers, use_container_width=True, hide_index=True)
        with mtab2:
            st.dataframe(losers, use_container_width=True, hide_index=True)

    with right:
        _render_news_panel_v3(news_df)

    _section_v8("Asset Boards", "FX, commodities and module launchpad")
    b1, b2, b3 = st.columns([1, 1, 1])

    with b1:
        _section_v8("FX Board", "Majors and dollar regime")
        st.dataframe(build_fx_board_v3(), use_container_width=True, hide_index=True)

    with b2:
        _section_v8("Commodities Board", "Energy, metals and agricultural proxies")
        st.dataframe(build_commodity_board_v3(), use_container_width=True, hide_index=True)

    with b3:
        _render_quick_modules_v3(resolved_preview_asset)
        qcols = st.columns(2)
        for idx, asset_class in enumerate(get_asset_classes()):
            profile = get_asset_profile(asset_class)
            with qcols[idx % 2]:
                if st.button(
                    f"OPEN {profile['label']}",
                    key=f"gcc_quick_open_v8_{asset_class}",
                    use_container_width=True,
                ):
                    _launch_workspace(
                        asset_class,
                        profile["default_symbol"],
                        profile["default_period"],
                        profile["default_interval"],
                        default_mode_for_asset(asset_class),
                    )

    with st.expander("Full Tape — Global / Equity / FX / Commodities / Rates", expanded=False):
        tab_names = ["Global", "Equity", "FX", "Commodities", "Rates"]
        tabs = st.tabs(tab_names)
        for tab, name in zip(tabs, tab_names):
            with tab:
                symbols = tuple(MARKET_TAPE_UNIVERSES.get(name, MARKET_TAPE_UNIVERSES["Global"]))
                df = load_market_tape_snapshot(symbols)
                display = _prepare_tape_display(df)
                if display.empty:
                    st.info(f"{name} tape indisponible.")
                else:
                    st.dataframe(display, use_container_width=True, hide_index=True)


# ============================================================
# END COMMAND CENTER V8 — VISUAL POLISH + HONEST LIVE STATE
# ============================================================



# ============================================================
# COMMAND CENTER V9 — BETTER LIVE CHARTS / REBASED RETURNS
# ============================================================
# Où coller :
# - Tout à la FIN de asset_class_router.py
# - Après le patch V8.
#
# Objectif :
# - Corriger les courbes visuellement mauvaises / plates.
# - Les mini-courbes affichent maintenant le mouvement intraday en %
#   rebased à 0, pas le prix brut compressé.
# - Le full live panel affiche :
#       1) price chart propre
#       2) intraday % move chart
#       3) diagnostics provider
# - Aucune modification des moteurs métier.
# ============================================================


def _rebased_live_frame_v9(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or "date" not in df.columns or "close" not in df.columns:
        return pd.DataFrame()

    work = df.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work["close"] = pd.to_numeric(work["close"], errors="coerce")
    work = work.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)

    if len(work) < 2:
        return pd.DataFrame()

    first = _safe_float(work["close"].iloc[0])
    if first in [None, 0]:
        return pd.DataFrame()

    work["ret_pct"] = (work["close"] / first - 1.0) * 100.0
    work["bar_id"] = np.arange(len(work))
    return work


def _padded_range_v9(values, min_pad: float = 0.04) -> tuple[float, float]:
    arr = pd.to_numeric(pd.Series(values), errors="coerce").dropna().to_numpy(dtype=float)
    if len(arr) == 0:
        return -1.0, 1.0

    lo = float(np.nanmin(arr))
    hi = float(np.nanmax(arr))

    if lo == hi:
        pad = max(abs(lo) * 0.05, min_pad)
        return lo - pad, hi + pad

    pad = max((hi - lo) * 0.16, min_pad)
    return lo - pad, hi + pad


def _make_rebased_micro_chart_v9(df: pd.DataFrame, symbol: str, height: int = 155) -> go.Figure:
    work = _rebased_live_frame_v9(df)
    fig = go.Figure()

    if work.empty:
        fig.update_layout(
            height=height,
            template="plotly_dark",
            margin=dict(l=0, r=0, t=0, b=0),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(2,10,23,.22)",
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
        )
        return fig

    y = work["ret_pct"]
    y0, y1 = _padded_range_v9(y, min_pad=0.03)
    last_ret = _safe_float(y.iloc[-1])
    line_color, _ = _curve_color_v5((last_ret or 0) / 100.0)

    fig.add_hline(y=0, line_width=1, line_dash="dot", line_color="rgba(255,255,255,.22)")

    fig.add_trace(
        go.Scatter(
            x=work["date"],
            y=y,
            mode="lines",
            line=dict(width=2.15, color=line_color),
            name=symbol,
            hovertemplate="%{x}<br>%{y:.3f}%<extra></extra>",
        )
    )

    try:
        fig.add_trace(
            go.Scatter(
                x=[work["date"].iloc[-1]],
                y=[work["ret_pct"].iloc[-1]],
                mode="markers",
                marker=dict(size=5, color=line_color),
                showlegend=False,
                hoverinfo="skip",
            )
        )
    except Exception:
        pass

    fig.update_layout(
        height=height,
        template="plotly_dark",
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(2,10,23,.25)",
        showlegend=False,
        hovermode="x unified",
        xaxis=dict(visible=False, showgrid=False, zeroline=False),
        yaxis=dict(visible=False, showgrid=False, zeroline=False, range=[y0, y1]),
    )
    return fig


def _make_price_chart_v9(df: pd.DataFrame, symbol: str, height: int = 520) -> go.Figure:
    work = df.copy() if df is not None else pd.DataFrame()
    fig = go.Figure()

    if work.empty or "date" not in work.columns or "close" not in work.columns:
        fig.update_layout(template="plotly_dark", height=height)
        return fig

    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    for col in ["open", "high", "low", "close"]:
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce")

    work = work.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)

    if work.empty:
        fig.update_layout(template="plotly_dark", height=height)
        return fig

    close = pd.to_numeric(work["close"], errors="coerce").dropna()
    y0, y1 = _padded_range_v9(close, min_pad=0.001)

    if all(c in work.columns for c in ["open", "high", "low", "close"]):
        fig.add_trace(
            go.Candlestick(
                x=work["date"],
                open=work["open"],
                high=work["high"],
                low=work["low"],
                close=work["close"],
                name=symbol,
            )
        )
    else:
        fig.add_trace(go.Scatter(x=work["date"], y=work["close"], mode="lines", line=dict(width=2.1), name=symbol))

    try:
        ema = close.ewm(span=21, adjust=False).mean()
        fig.add_trace(go.Scatter(x=work.loc[close.index, "date"], y=ema, mode="lines", line=dict(width=1.15, dash="dot"), name="EMA 21"))
    except Exception:
        pass

    fig.update_layout(
        height=height,
        template="plotly_dark",
        hovermode="x unified",
        margin=dict(l=10, r=10, t=42, b=10),
        title=f"{symbol} · live price",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(4,12,26,0.18)",
        xaxis_rangeslider_visible=False,
        yaxis=dict(range=[y0, y1], gridcolor="rgba(120,170,255,.10)", zeroline=False),
    )
    return fig


def _make_return_chart_v9(df: pd.DataFrame, symbol: str, height: int = 460) -> go.Figure:
    work = _rebased_live_frame_v9(df)
    fig = go.Figure()

    if work.empty:
        fig.update_layout(template="plotly_dark", height=height)
        return fig

    y = work["ret_pct"]
    y0, y1 = _padded_range_v9(y, min_pad=0.05)
    last_ret = _safe_float(y.iloc[-1])
    line_color, _ = _curve_color_v5((last_ret or 0) / 100.0)

    fig.add_hline(y=0, line_width=1, line_dash="dot", line_color="rgba(255,255,255,.35)")
    fig.add_trace(
        go.Scatter(
            x=work["date"],
            y=work["ret_pct"],
            mode="lines",
            line=dict(width=2.4, color=line_color),
            name="% move",
            hovertemplate="%{x}<br>%{y:.3f}%<extra></extra>",
        )
    )

    fig.update_layout(
        height=height,
        template="plotly_dark",
        hovermode="x unified",
        margin=dict(l=10, r=10, t=42, b=10),
        title=f"{symbol} · intraday % move",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(4,12,26,0.18)",
        yaxis=dict(title="% from first bar", range=[y0, y1], gridcolor="rgba(120,170,255,.10)", zeroline=False),
        xaxis=dict(showgrid=False),
    )
    return fig


def _render_micro_curve_cards_v4(symbols: list[str], asset_class: str = "Global", max_items: int = 4) -> None:
    shown = [str(s).strip() for s in symbols if str(s).strip()][:max_items]
    if not shown:
        return

    refresh_token = st.session_state.get("_live_refresh_token_v7", 0)
    cols = st.columns(len(shown))

    for col, symbol in zip(cols, shown):
        with col:
            s = _normalize_live_symbol_v4(symbol)
            df, meta = get_live_curve_v7(s, asset_class=asset_class, provider="auto", lookback_minutes=240, refresh_token=refresh_token)
            metrics = build_live_curve_metrics_v4(df)

            provider = str(meta.get("provider", "None"))
            value = _format_price_by_symbol_v5(s, metrics.get("last"))
            delta = _fmt_pct(metrics.get("change"))
            delta_color = "#3cf0b4" if not str(delta).startswith("-") else "#ff5f73"

            st.markdown(
                f"""
                <div style="
                    border:1px solid rgba(90,205,255,.16);
                    background:linear-gradient(180deg,rgba(4,14,29,.82),rgba(2,8,20,.86));
                    border-radius:14px;
                    padding:10px 11px 9px 11px;
                    margin-bottom:6px;">
                    <div style="color:rgba(230,244,255,.70);font-size:.68rem;font-weight:850;letter-spacing:.10em;text-transform:uppercase;">
                        {_cc_escape(s)}
                    </div>
                    <div style="display:flex;align-items:baseline;gap:8px;margin-top:4px;">
                        <div style="color:#f8fbff;font-size:1.05rem;font-weight:900;">
                            {_cc_escape(value)}
                        </div>
                        <div style="color:{delta_color};font-size:.70rem;font-weight:850;">
                            {_cc_escape(delta)}
                        </div>
                    </div>
                    <div style="color:rgba(220,235,250,.52);font-size:.66rem;font-weight:760;margin-top:2px;">
                        {_cc_escape(provider)} · % intraday
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            if df is None or df.empty:
                st.caption("No curve")
                continue

            fig = _make_rebased_micro_chart_v9(df, s, height=150)
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False, "responsive": True})
            st.caption(f"{meta.get('last_refresh_utc', '')}")


def render_live_curve_panel_v4(
    symbol: str,
    asset_class: str = "Global",
    title: str | None = None,
    provider: str = "auto",
    lookback_minutes: int = 390,
    height: int = 520,
    compact: bool = False,
) -> None:
    s = _normalize_live_symbol_v4(symbol)
    df, meta = get_live_curve_v7(
        s,
        asset_class=asset_class,
        provider=provider,
        lookback_minutes=lookback_minutes,
        refresh_token=st.session_state.get("_live_refresh_token_v7", 0),
    )
    metrics = build_live_curve_metrics_v4(df)

    st.markdown(f"#### {title or f'Live / Intraday — {s}'}")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Last", _format_price_by_symbol_v5(s, metrics.get("last")))
    c2.metric("Intraday", _fmt_pct(metrics.get("change")))
    c3.metric("Range", _fmt_pct(metrics.get("range")))
    c4.metric("Bars", str(metrics.get("bars", 0)))
    c5.metric("Provider", str(meta.get("provider", "None")))

    if df is None or df.empty:
        st.warning(f"Aucune courbe disponible pour {s}. Provider order: {meta.get('provider_order', 'N/A')}.")
        with st.expander("Provider diagnostic", expanded=False):
            _render_provider_diagnostic_v5(meta)
        return

    tab_price, tab_move, tab_diag = st.tabs(["Price", "% move", "Provider diagnostic"])

    with tab_price:
        st.plotly_chart(_make_price_chart_v9(df, s, height=height), use_container_width=True, config={"displayModeBar": True, "responsive": True})

    with tab_move:
        st.plotly_chart(_make_return_chart_v9(df, s, height=max(420, height - 80)), use_container_width=True, config={"displayModeBar": True, "responsive": True})

    with tab_diag:
        _render_provider_diagnostic_v5(meta)

    note = f"Source: {meta.get('provider')} · Symbol: {meta.get('provider_symbol')} · Updated: {meta.get('last_refresh_utc', '')}"
    if meta.get("proxy_note"):
        note += f" · {meta.get('proxy_note')}"
    st.caption(note)


# ============================================================
# END COMMAND CENTER V9 — BETTER LIVE CHARTS
# ============================================================


# ============================================================
# COMMAND CENTER V10 — READ TRUE LIVE CACHE FIRST
# ============================================================
# Où coller :
# - Tout à la FIN de asset_class_router.py
# - Après V9.
#
# Pré-requis :
# - market_live_cache.py à la racine du projet
# - twelvedata_ws_collector.py lancé dans un terminal séparé
#
# Effet :
# - Les courbes utilisent d'abord le cache SQLite live écrit par le collector.
# - Si aucun cache live n'est trouvé, fallback vers le mode pull V9/V8.
# ============================================================

try:
    _get_live_curve_v7_pull_fallback = get_live_curve_v7
except Exception:
    _get_live_curve_v7_pull_fallback = None


def _live_cache_symbol_aliases_v10(symbol: str) -> list[str]:
    s = _normalize_live_symbol_v4(symbol)
    aliases = [s]
    fx_alias = {
        "EUR/USD": "EURUSD=X", "GBP/USD": "GBPUSD=X", "USD/JPY": "USDJPY=X", "USD/CHF": "USDCHF=X",
        "AUD/USD": "AUDUSD=X", "USD/CAD": "USDCAD=X", "NZD/USD": "NZDUSD=X", "EUR/JPY": "EURJPY=X",
        "EUR/GBP": "EURGBP=X", "GBP/JPY": "GBPJPY=X",
    }
    inverse = {v: k for k, v in fx_alias.items()}
    if s in inverse:
        aliases.append(inverse[s])
    if s in fx_alias:
        aliases.append(fx_alias[s])
    if s == "GC=F":
        aliases.append("XAU/USD")
    if s == "SI=F":
        aliases.append("XAG/USD")
    return list(dict.fromkeys([x.upper() for x in aliases if x]))


def fetch_live_cache_bars_v10(symbol: str, lookback_minutes: int = 60, preferred_timeframes: tuple[str, ...] = ("1s", "5s", "1m")) -> tuple[pd.DataFrame, dict[str, Any]]:
    try:
        from market_live_cache import read_live_bars
    except Exception as exc:
        return pd.DataFrame(), {"provider": "Live Cache", "status": "missing_module", "errors": str(exc)}

    aliases = _live_cache_symbol_aliases_v10(symbol)
    last_error = ""
    for alias in aliases:
        for tf in preferred_timeframes:
            try:
                df = read_live_bars(alias, timeframe=tf, lookback_minutes=lookback_minutes)
            except Exception as exc:
                last_error = str(exc)
                continue
            if df is not None and not df.empty:
                out = df.copy()
                provider = str(out["provider"].dropna().iloc[-1]) if "provider" in out.columns and not out["provider"].dropna().empty else "Live Cache"
                provider_symbol = str(out["provider_symbol"].dropna().iloc[-1]) if "provider_symbol" in out.columns and not out["provider_symbol"].dropna().empty else alias
                out["source"] = provider
                out["symbol"] = _normalize_live_symbol_v4(symbol)
                out["provider_symbol"] = provider_symbol
                return out, {
                    "symbol": _normalize_live_symbol_v4(symbol),
                    "asset_class": "Live",
                    "provider": f"{provider} Live Cache",
                    "provider_order": "SQLite live cache > pull fallback",
                    "provider_symbol": provider_symbol,
                    "timeframe": tf,
                    "live_cache_alias": alias,
                    "live_cache_rows": len(out),
                    "databento_configured": databento_configured_v4() if "databento_configured_v4" in globals() else False,
                    "databento_mapped": _normalize_live_symbol_v4(symbol) in DATABENTO_PROXY_MAP if "DATABENTO_PROXY_MAP" in globals() else False,
                    "twelve_data_configured": twelve_data_enabled() if "twelve_data_enabled" in globals() else False,
                    "twelve_data_candidate": _twelve_data_candidate_v5(symbol, "Global") if "_twelve_data_candidate_v5" in globals() else False,
                    "twelve_data_symbol": provider_symbol,
                    "proxy_note": "true WebSocket collector cache",
                    "label": _normalize_live_symbol_v4(symbol),
                    "errors": "",
                    "last_refresh_utc": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                }
    return pd.DataFrame(), {
        "symbol": _normalize_live_symbol_v4(symbol),
        "provider": "Live Cache",
        "provider_order": "SQLite live cache > pull fallback",
        "provider_symbol": aliases[0] if aliases else symbol,
        "errors": last_error,
    }


def get_live_curve_v7(symbol: str, asset_class: str = "Global", provider: str = "auto", lookback_minutes: int = 390, refresh_token: int | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Override V10:
    1) Try true live cache from collectors.
    2) If empty, fallback to the previous pull-based implementation.
    """
    s = _normalize_live_symbol_v4(symbol)
    cache_df, cache_meta = fetch_live_cache_bars_v10(s, lookback_minutes=max(10, int(lookback_minutes or 60)), preferred_timeframes=("1s", "5s", "1m"))
    if cache_df is not None and not cache_df.empty:
        cache_meta["asset_class"] = asset_class
        return cache_df, cache_meta
    if _get_live_curve_v7_pull_fallback is not None:
        df, meta = _get_live_curve_v7_pull_fallback(symbol=s, asset_class=asset_class, provider=provider, lookback_minutes=lookback_minutes, refresh_token=refresh_token)
        meta = dict(meta or {})
        meta["live_cache_status"] = "empty"
        return df, meta
    return pd.DataFrame(), cache_meta


def get_live_curve_v4(symbol: str, asset_class: str = "Global", provider: str = "auto", lookback_minutes: int = 390) -> tuple[pd.DataFrame, dict[str, Any]]:
    return get_live_curve_v7(symbol=symbol, asset_class=asset_class, provider=provider, lookback_minutes=lookback_minutes, refresh_token=st.session_state.get("_live_refresh_token_v7", 0))


def render_live_cache_status_v10() -> None:
    try:
        from market_live_cache import read_live_status
        status = read_live_status()
    except Exception as exc:
        st.caption(f"Live cache status unavailable: {exc}")
        return
    if status is None or status.empty:
        st.caption("Live cache: no collector status yet.")
        return
    with st.expander("Live collector status", expanded=False):
        st.dataframe(status, use_container_width=True, hide_index=True)

try:
    _render_live_state_bar_v8_previous = _render_live_state_bar_v8
except Exception:
    _render_live_state_bar_v8_previous = None


def _render_live_state_bar_v8(auto_refresh: bool, refresh_seconds: int, token: int) -> None:
    if _render_live_state_bar_v8_previous is not None:
        _render_live_state_bar_v8_previous(auto_refresh, refresh_seconds, token)
    render_live_cache_status_v10()

# ============================================================
# END COMMAND CENTER V10 — READ TRUE LIVE CACHE FIRST
# ============================================================


# ============================================================
# COMMAND CENTER V11 — DISABLE TRUE LIVE CACHE / RETURN TO 5S PULL
# ============================================================
# Où coller :
# - Tout à la FIN de asset_class_router.py
# - Après le patch V10 si tu l'as déjà collé.
#
# Objectif :
# - On abandonne le live WebSocket direct pour l'instant.
# - On revient au mode stable :
#       Twelve Data REST / yfinance pull
#       + auto-refresh Streamlit toutes les 5s
# - Le cache SQLite live n'est plus utilisé en priorité.
# - Le collector Twelve WebSocket peut être arrêté.
# ============================================================


# ------------------------------------------------------------
# V11 — disable live cache priority
# ------------------------------------------------------------

LIVE_CACHE_ENABLED_V11 = False


def get_live_curve_v7(
    symbol: str,
    asset_class: str = "Global",
    provider: str = "auto",
    lookback_minutes: int = 390,
    refresh_token: int | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    V11:
    Retour au mode pull stable.
    On ignore volontairement le cache SQLite live.
    """
    s = _normalize_live_symbol_v4(symbol)
    refresh_token = refresh_token if refresh_token is not None else st.session_state.get("_live_refresh_token_v7", 0)

    try:
        order = _provider_order_v5(s, asset_class, provider)
    except Exception:
        order = ["yfinance"]

    # Databento désactivé volontairement si non utilisé dans le projet.
    order = [p for p in order if p != "databento"]

    errors: list[str] = []
    df = pd.DataFrame()
    used_provider = "None"

    for p in order:
        try:
            if p in {"twelvedata", "twelve"}:
                df = fetch_twelve_data_intraday_v7(
                    s,
                    asset_class=asset_class,
                    interval="1min",
                    outputsize=int(max(60, min(500, lookback_minutes))),
                    refresh_token=refresh_token,
                )
                if df is not None and not df.empty:
                    used_provider = "Twelve Data REST"
                    break

            elif p == "yfinance":
                df = fetch_yfinance_intraday_v7(
                    s,
                    refresh_token=refresh_token,
                )
                if df is not None and not df.empty:
                    used_provider = "yfinance"
                    break

        except Exception as exc:
            errors.append(f"{p}: {exc}")

    try:
        td_symbol = to_twelve_data_symbol(s, asset_class)
    except Exception:
        td_symbol = None

    provider_symbol = s
    if df is not None and not df.empty and "provider_symbol" in df.columns:
        try:
            provider_symbol = str(df["provider_symbol"].dropna().iloc[-1])
        except Exception:
            provider_symbol = td_symbol or s
    elif used_provider.startswith("Twelve"):
        provider_symbol = td_symbol or s

    meta = {
        "symbol": s,
        "asset_class": asset_class,
        "provider": used_provider,
        "provider_order": " > ".join(order),
        "provider_symbol": provider_symbol,
        "databento_configured": False,
        "databento_mapped": False,
        "twelve_data_configured": twelve_data_enabled() if "twelve_data_enabled" in globals() else False,
        "twelve_data_candidate": _twelve_data_candidate_v5(s, asset_class) if "_twelve_data_candidate_v5" in globals() else False,
        "twelve_data_symbol": td_symbol,
        "proxy_note": "5s near-live pull mode; live cache disabled",
        "label": s,
        "errors": "; ".join(errors[-3:]),
        "refresh_token": refresh_token,
        "last_refresh_utc": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "live_cache_status": "disabled",
    }

    return df if df is not None else pd.DataFrame(), meta


def get_live_curve_v4(
    symbol: str,
    asset_class: str = "Global",
    provider: str = "auto",
    lookback_minutes: int = 390,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    return get_live_curve_v7(
        symbol=symbol,
        asset_class=asset_class,
        provider=provider,
        lookback_minutes=lookback_minutes,
        refresh_token=st.session_state.get("_live_refresh_token_v7", 0),
    )


# ------------------------------------------------------------
# V11 — honest status bar
# ------------------------------------------------------------

def _render_live_state_bar_v8(auto_refresh: bool, refresh_seconds: int, token: int) -> None:
    auto_ok = not st.session_state.get("_live_autorefresh_missing_v7", False)

    tone = "good" if auto_refresh and auto_ok else "warn"
    mode = "5S NEAR-LIVE ACTIVE" if auto_refresh and auto_ok else "MANUAL PULL"

    try:
        twelve_ok = twelve_data_enabled()
    except Exception:
        twelve_ok = False

    cols = st.columns([1.2, 1.0, 2.4], vertical_alignment="center")

    with cols[0]:
        _status_pill_v8("Live mode", mode, tone=tone)

    with cols[1]:
        _status_pill_v8("Refresh", f"{refresh_seconds}s · token {token}", tone="neutral")

    with cols[2]:
        provider_text = (
            f"Primary: Twelve REST {'OK' if twelve_ok else 'missing'} · "
            f"Fallback: yfinance {'OK' if YFINANCE_AVAILABLE else 'missing'} · "
            f"WebSocket cache disabled · Databento disabled"
        )
        st.caption(provider_text)


# ============================================================
# END COMMAND CENTER V11 — DISABLE TRUE LIVE CACHE
# ============================================================



# ============================================================
# COMMAND CENTER V12 — INSTITUTIONAL READ / DATA QUALITY / PRESSURE MAP
# ============================================================
# Où coller :
# - Tout à la FIN de asset_class_router.py
# - Après V11.
#
# Choix de prudence :
# - Patch d'override uniquement : aucune modification des moteurs Backtest / Risk / Monte Carlo / Decision.
# - On garde la décision actuelle : Twelve Data REST + auto-refresh 5s + yfinance fallback.
# - Databento et WebSocket cache restent volontairement désactivés.
#
# Ce que V12 ajoute :
# - Data Quality Bar institutionnelle.
# - Market Read synthétique.
# - Cross-Asset Regime quantifié.
# - Cross-Asset Pressure Map.
# - Live cards enrichies : range, realised vol proxy, intraday drawdown, provider.
# - Event Monitor plus lisible que Latest News brut.
# - Module Launchpad groupé par workflow : Research / Trading / Risk / Validation.
# ============================================================


# ------------------------------------------------------------
# V12 — Safe utilities
# ------------------------------------------------------------

def _safe_series_v12(values) -> pd.Series:
    try:
        return pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    except Exception:
        return pd.Series(dtype=float)


def _pct_to_score_v12(value: Any, scale: float = 0.012, invert: bool = False) -> int:
    """
    Convertit un mouvement en score 0-100.
    scale=1.2% signifie qu'un move de +1.2% donne environ 100.
    """
    x = _safe_float(value, 0.0) or 0.0
    if invert:
        x = -x
    raw = 50.0 + 50.0 * (x / max(scale, 1e-9))
    return int(max(0, min(100, round(raw))))


def _score_label_v12(score: Any) -> str:
    s = _safe_float(score)
    if s is None:
        return "WAIT"
    if s >= 72:
        return "HIGH"
    if s >= 56:
        return "MEDIUM+"
    if s >= 44:
        return "NEUTRAL"
    if s >= 28:
        return "MEDIUM-"
    return "LOW"


def _score_tone_v12(score: Any) -> str:
    s = _safe_float(score, 50) or 50
    if s >= 68:
        return "good"
    if s <= 32:
        return "bad"
    if 44 <= s <= 56:
        return "neutral"
    return "warn"


def _move_importance_v12(change: Any) -> str:
    x = abs(_safe_float(change, 0.0) or 0.0)
    if x >= 0.015:
        return "HIGH"
    if x >= 0.006:
        return "MEDIUM"
    if x >= 0.002:
        return "LOW"
    return "NOISE"


def _trend_word_v12(change: Any, pos: str = "BID", neg: str = "OFFER") -> str:
    x = _safe_float(change, 0.0) or 0.0
    if x >= 0.004:
        return pos
    if x <= -0.004:
        return neg
    return "FLAT"


def _format_signed_pct_v12(value: Any, digits: int = 2) -> str:
    return _fmt_pct(value, digits=digits)


def _latest_update_from_meta_v12(meta: dict[str, Any] | None) -> str:
    if not isinstance(meta, dict):
        return "N/A"
    return str(meta.get("last_refresh_utc") or "N/A")


def _extract_change_v12(tape_df: pd.DataFrame, symbol: str) -> float | None:
    try:
        sub = tape_df.loc[tape_df["Symbol"] == symbol]
        if sub.empty:
            return None
        return _safe_float(sub.iloc[0].get("Change %"))
    except Exception:
        return None


def _extract_last_v12(tape_df: pd.DataFrame, symbol: str) -> float | None:
    try:
        sub = tape_df.loc[tape_df["Symbol"] == symbol]
        if sub.empty:
            return None
        return _safe_float(sub.iloc[0].get("Last"))
    except Exception:
        return None


# ------------------------------------------------------------
# V12 — Data quality / provider state
# ------------------------------------------------------------

def build_data_quality_v12(auto_refresh: bool | None = None, refresh_seconds: int | None = None) -> dict[str, Any]:
    try:
        twelve_ok = bool(twelve_data_enabled())
    except Exception:
        twelve_ok = False

    try:
        yfinance_ok = bool(YFINANCE_AVAILABLE)
    except Exception:
        yfinance_ok = False

    try:
        missing_autorefresh = bool(st.session_state.get("_live_autorefresh_missing_v7", False))
    except Exception:
        missing_autorefresh = True

    auto_refresh = bool(st.session_state.get("live_auto_refresh_v8", True) if auto_refresh is None else auto_refresh)
    refresh_seconds = int(st.session_state.get("_live_refresh_seconds_v7", 5) if refresh_seconds is None else refresh_seconds)

    operational = twelve_ok or yfinance_ok
    if twelve_ok and auto_refresh and not missing_autorefresh:
        status = "OPERATIONAL"
        status_tone = "good"
    elif operational:
        status = "DEGRADED"
        status_tone = "warn"
    else:
        status = "NO DATA"
        status_tone = "bad"

    return {
        "status": status,
        "tone": status_tone,
        "primary": "Twelve REST" if twelve_ok else "yfinance fallback" if yfinance_ok else "None",
        "refresh": f"{refresh_seconds}s",
        "coverage": "Equity / FX / ETF / indices / selected spot proxies",
        "latency": "Near-live pull",
        "fallback": "yfinance OK" if yfinance_ok else "yfinance missing",
        "websocket": "disabled",
        "databento": "disabled",
        "auto_refresh": "active" if auto_refresh and not missing_autorefresh else "manual/degraded",
    }


def _render_data_quality_bar_v12(auto_refresh: bool, refresh_seconds: int, token: int) -> None:
    dq = build_data_quality_v12(auto_refresh=auto_refresh, refresh_seconds=refresh_seconds)

    cols = st.columns([1.05, 1.0, 1.0, 1.35, 2.1])
    with cols[0]:
        _status_pill_v8("Data status", str(dq["status"]), tone=str(dq["tone"]))
    with cols[1]:
        _status_pill_v8("Provider", str(dq["primary"]), tone="neutral")
    with cols[2]:
        _status_pill_v8("Refresh", f"{dq['refresh']} · {token}", tone="neutral")
    with cols[3]:
        _status_pill_v8("Mode", "5S NEAR-LIVE" if auto_refresh else "MANUAL PULL", tone="good" if auto_refresh else "warn")
    with cols[4]:
        st.caption(
            f"Coverage: {dq['coverage']} · Fallback: {dq['fallback']} · "
            f"WebSocket cache {dq['websocket']} · Databento {dq['databento']}"
        )


def _render_live_state_bar_v8(auto_refresh: bool, refresh_seconds: int, token: int) -> None:
    """
    Override V12.
    Remplace le status technique V11 par une Data Quality Bar.
    """
    _render_data_quality_bar_v12(auto_refresh, refresh_seconds, token)


# ------------------------------------------------------------
# V12 — Regime scoring / market read
# ------------------------------------------------------------

def build_regime_scores_v12(tape_df: pd.DataFrame, regime: dict[str, Any] | None = None) -> dict[str, Any]:
    if tape_df is None or tape_df.empty:
        return {
            "risk_score": 50,
            "vol_pressure": 50,
            "dollar_pressure": 50,
            "rates_pressure": 50,
            "commodities_pressure": 50,
            "confidence": 0,
            "main_drivers": "WAIT",
        }

    es = _extract_change_v12(tape_df, "ES=F") or 0.0
    nq = _extract_change_v12(tape_df, "NQ=F") or 0.0
    rty = _extract_change_v12(tape_df, "RTY=F") or 0.0
    vix = _extract_change_v12(tape_df, "^VIX") or 0.0
    dxy = _extract_change_v12(tape_df, "DX-Y.NYB") or 0.0
    tnx = _extract_change_v12(tape_df, "^TNX") or 0.0
    fvx = _extract_change_v12(tape_df, "^FVX") or 0.0
    oil = _extract_change_v12(tape_df, "CL=F") or 0.0
    gold = _extract_change_v12(tape_df, "GC=F") or 0.0
    copper = _extract_change_v12(tape_df, "HG=F") or 0.0

    equity_pressure = np.nanmean([es, nq, rty])
    rates_raw = np.nanmean([tnx, fvx])
    commo_raw = np.nanmean([oil, gold, copper])

    # Risk score: equities up is positive; vol/rates/dollar up are risk-negative.
    risk_score = int(max(0, min(100, round(
        50
        + 900 * equity_pressure
        - 280 * max(vix, 0)
        - 900 * max(dxy, 0)
        - 700 * max(rates_raw, 0)
    ))))

    vol_pressure = _pct_to_score_v12(vix, scale=0.10)
    dollar_pressure = _pct_to_score_v12(dxy, scale=0.012)
    rates_pressure = _pct_to_score_v12(rates_raw, scale=0.012)
    commodities_pressure = _pct_to_score_v12(commo_raw, scale=0.018)

    drivers = [
        ("VIX", abs(vix)),
        ("DXY", abs(dxy)),
        ("Rates", abs(rates_raw)),
        ("Equity", abs(equity_pressure)),
        ("Commodities", abs(commo_raw)),
    ]
    drivers = sorted(drivers, key=lambda x: x[1], reverse=True)
    main_drivers = " / ".join([d[0] for d in drivers[:3] if d[1] > 0]) or "N/A"

    confidence = int(max(0, min(100, round(
        35
        + 650 * abs(equity_pressure)
        + 120 * abs(vix)
        + 900 * abs(dxy)
        + 700 * abs(rates_raw)
    ))))

    return {
        "risk_score": risk_score,
        "vol_pressure": vol_pressure,
        "dollar_pressure": dollar_pressure,
        "rates_pressure": rates_pressure,
        "commodities_pressure": commodities_pressure,
        "confidence": confidence,
        "main_drivers": main_drivers,
    }


def build_market_read_v12(tape_df: pd.DataFrame, regime: dict[str, Any] | None = None) -> dict[str, Any]:
    regime = regime or {}
    scores = build_regime_scores_v12(tape_df, regime)

    if tape_df is None or tape_df.empty:
        return {
            "headline": "Market read unavailable.",
            "detail": "Insufficient market tape.",
            "bias": "WAIT",
            "confidence": 0,
            "drivers": "N/A",
        }

    es = _extract_change_v12(tape_df, "ES=F") or 0.0
    nq = _extract_change_v12(tape_df, "NQ=F") or 0.0
    vix = _extract_change_v12(tape_df, "^VIX") or 0.0
    dxy = _extract_change_v12(tape_df, "DX-Y.NYB") or 0.0
    tnx = _extract_change_v12(tape_df, "^TNX") or 0.0
    oil = _extract_change_v12(tape_df, "CL=F") or 0.0

    risk = str(regime.get("risk", "BALANCED"))
    vol = str(regime.get("vol", "NORMAL"))
    dollar = str(regime.get("dollar", "NEUTRAL"))
    rates = str(regime.get("rates", "STABLE"))
    commo = str(regime.get("commodities", "MIXED"))

    if risk == "DEFENSIVE":
        bias = "RISK-OFF"
    elif risk == "CONSTRUCTIVE":
        bias = "RISK-ON"
    else:
        bias = "BALANCED"

    bits = []
    if es < 0 and nq < 0:
        bits.append("equity futures offered")
    elif es > 0 and nq > 0:
        bits.append("equity futures bid")
    if vix > 0:
        bits.append("volatility bid")
    if dxy > 0:
        bits.append("dollar stronger")
    if tnx > 0:
        bits.append("rates higher")
    if oil > 0:
        bits.append("oil bid")
    elif oil < 0:
        bits.append("oil offered")

    headline = f"{bias}: {', '.join(bits[:4]) if bits else 'mixed cross-asset tape'}."
    detail = f"Regime {risk}; vol {vol}; dollar {dollar}; rates {rates}; commodities {commo}."

    return {
        "headline": headline,
        "detail": detail,
        "bias": bias,
        "confidence": scores["confidence"],
        "drivers": scores["main_drivers"],
        "scores": scores,
    }


def _render_market_read_v12(tape_df: pd.DataFrame, regime: dict[str, Any]) -> None:
    read = build_market_read_v12(tape_df, regime)
    scores = read.get("scores", {}) if isinstance(read.get("scores"), dict) else {}

    st.markdown(
        f"""
        <div style="
            border:1px solid rgba(90,205,255,.18);
            background:linear-gradient(180deg,rgba(5,18,38,.86),rgba(2,9,22,.88));
            border-radius:18px;
            padding:14px 15px;
            margin:8px 0 14px 0;">
            <div style="color:#55e8ff;font-size:.72rem;font-weight:950;letter-spacing:.18em;text-transform:uppercase;">
                MARKET READ
            </div>
            <div style="color:#f8fbff;font-size:1.02rem;font-weight:900;margin-top:7px;">
                {_cc_escape(str(read.get("headline", "")))}
            </div>
            <div style="color:rgba(220,235,250,.68);font-size:.78rem;margin-top:5px;">
                {_cc_escape(str(read.get("detail", "")))} · Drivers: {_cc_escape(str(read.get("drivers", "N/A")))}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    cols = st.columns(6)
    cards = [
        ("Bias", str(read.get("bias", "N/A")), "good" if read.get("bias") == "RISK-ON" else "bad" if read.get("bias") == "RISK-OFF" else "warn"),
        ("Confidence", f"{int(read.get('confidence', 0))}/100", _score_tone_v12(read.get("confidence", 0))),
        ("Risk score", f"{int(scores.get('risk_score', 50))}/100", _score_tone_v12(scores.get("risk_score", 50))),
        ("Vol pressure", f"{int(scores.get('vol_pressure', 50))}/100", _score_tone_v12(100 - int(scores.get("vol_pressure", 50)))),
        ("Dollar", f"{int(scores.get('dollar_pressure', 50))}/100", _score_tone_v12(100 - int(scores.get("dollar_pressure", 50)))),
        ("Rates", f"{int(scores.get('rates_pressure', 50))}/100", _score_tone_v12(100 - int(scores.get("rates_pressure", 50)))),
    ]
    for col, (label, value, tone) in zip(cols, cards):
        with col:
            _status_pill_v8(label, value, tone=tone)


def _render_regime_panel_v3(regime: dict[str, Any], overview: pd.DataFrame) -> None:
    """
    Override V12 : regime panel with scores and no broken labels.
    """
    _section_v8("Cross-Asset Regime", "Risk, volatility, dollar, rates and commodities")

    # Try to rebuild scores from overview is impossible; use labels only here.
    items = [
        ("Risk", regime.get("risk", "N/A")),
        ("Vol", regime.get("vol", "N/A")),
        ("Dollar", regime.get("dollar", "N/A")),
        ("Rates", regime.get("rates", "N/A")),
        ("Commo", regime.get("commodities", "N/A")),
    ]

    cols = st.columns(5)
    for col, (label, value) in zip(cols, items):
        v = str(value)
        tone = "neutral"
        if v in {"CONSTRUCTIVE", "FALLING", "WEAK", "LOWER", "BID"}:
            tone = "good"
        elif v in {"DEFENSIVE", "RISING", "STRONG", "HIGHER", "OFFERED"}:
            tone = "bad"
        elif v in {"BALANCED", "NORMAL", "NEUTRAL", "STABLE", "MIXED"}:
            tone = "warn"
        with col:
            _status_pill_v8(label, v, tone=tone)

    st.caption(str(regime.get("read", "")))

    if overview is not None and not overview.empty:
        st.dataframe(overview, use_container_width=True, hide_index=True)


# ------------------------------------------------------------
# V12 — Cross-Asset Pressure Map
# ------------------------------------------------------------

def build_pressure_map_v12(tape_df: pd.DataFrame) -> pd.DataFrame:
    if tape_df is None or tape_df.empty:
        return pd.DataFrame(columns=["Bloc", "Direction", "Strength", "Driver", "Avg move", "Breadth"])

    work = tape_df.copy()
    work["Bucket"] = work["Symbol"].map(_asset_bucket)
    work["_change"] = pd.to_numeric(work["Change %"], errors="coerce")

    rows = []
    for bucket in ["Equity", "Volatility", "FX", "Rates", "Commodities"]:
        sub = work.loc[work["Bucket"] == bucket].dropna(subset=["_change"])
        if sub.empty:
            rows.append({
                "Bloc": bucket,
                "Direction": "WAIT",
                "Strength": "WAIT",
                "Driver": "N/A",
                "Avg move": "N/A",
                "Breadth": "N/A",
            })
            continue

        avg = float(sub["_change"].mean())
        breadth = float((sub["_change"] > 0).mean())
        driver = sub.iloc[sub["_change"].abs().argmax()]
        direction = _trend_word_v12(avg, pos="BID", neg="OFFER")
        if bucket == "Volatility":
            direction = "VOL BID" if avg > 0.004 else "VOL OFFER" if avg < -0.004 else "FLAT"
        elif bucket == "Rates":
            direction = "HIGHER" if avg > 0.003 else "LOWER" if avg < -0.003 else "FLAT"
        elif bucket == "FX":
            direction = "USD BID" if (_extract_change_v12(tape_df, "DX-Y.NYB") or 0.0) > 0.0025 else "USD OFFER" if (_extract_change_v12(tape_df, "DX-Y.NYB") or 0.0) < -0.0025 else "MIXED"

        rows.append({
            "Bloc": bucket,
            "Direction": direction,
            "Strength": _move_importance_v12(avg),
            "Driver": f"{driver.get('Symbol')} {_fmt_pct(driver.get('Change %'))}",
            "Avg move": _fmt_pct(avg),
            "Breadth": f"{breadth:.0%}",
        })

    return pd.DataFrame(rows)


def _render_pressure_map_v12(tape_df: pd.DataFrame) -> None:
    _section_v8("Cross-Asset Pressure Map", "Direction, strength and dominant driver by bloc")
    pressure = build_pressure_map_v12(tape_df)
    if pressure.empty:
        st.caption("Pressure map unavailable.")
        return
    st.dataframe(pressure, use_container_width=True, hide_index=True)


def _prepare_tape_display(df: pd.DataFrame) -> pd.DataFrame:
    """
    Override V12 : market tape includes direction and importance.
    """
    if df is None or df.empty:
        return pd.DataFrame()

    out = df.copy()
    out["Last"] = out.apply(_value_for_symbol, axis=1)
    out["Change % raw"] = pd.to_numeric(df["Change %"], errors="coerce")
    out["Change %"] = df["Change %"].map(lambda x: _fmt_pct(x))
    out["Direction"] = df["Change %"].map(_direction_label)
    out["Importance"] = df["Change %"].map(_move_importance_v12)
    out["Volume"] = df["Volume"].map(lambda x: _fmt_compact_num(x))
    out["Status"] = df["Last"].map(_status_from_value)

    cols = ["Symbol", "Name", "Last", "Change %", "Direction", "Importance", "Volume", "Status"]
    return out[cols]


# ------------------------------------------------------------
# V12 — Better live card metrics
# ------------------------------------------------------------

def build_live_card_metrics_v12(df: pd.DataFrame) -> dict[str, Any]:
    base = build_live_curve_metrics_v4(df)
    if df is None or df.empty or "close" not in df.columns:
        base.update({"rv_proxy": None, "intraday_dd": None, "fresh_bars": 0})
        return base

    close = pd.to_numeric(df["close"], errors="coerce").dropna()
    if len(close) < 3:
        base.update({"rv_proxy": None, "intraday_dd": None, "fresh_bars": len(close)})
        return base

    ret = close.pct_change().dropna()
    rv = None
    if len(ret) >= 2:
        # 1-minute bars approximate annualisation. If bars are not exactly 1m, this remains a proxy.
        rv = float(ret.std() * np.sqrt(252 * 390))

    dd = close / close.cummax() - 1
    base.update({
        "rv_proxy": rv,
        "intraday_dd": float(dd.min()) if not dd.empty else None,
        "fresh_bars": len(close),
    })
    return base


def _render_micro_curve_cards_v4(symbols: list[str], asset_class: str = "Global", max_items: int = 4) -> None:
    """
    Override V12 : richer institutional live cards.
    """
    shown = [str(s).strip() for s in symbols if str(s).strip()][:max_items]
    if not shown:
        return

    refresh_token = st.session_state.get("_live_refresh_token_v7", 0)
    cols = st.columns(len(shown))

    for col, symbol in zip(cols, shown):
        with col:
            s = _normalize_live_symbol_v4(symbol)
            df, meta = get_live_curve_v7(
                s,
                asset_class=asset_class,
                provider="auto",
                lookback_minutes=240,
                refresh_token=refresh_token,
            )
            metrics = build_live_card_metrics_v12(df)

            provider = str(meta.get("provider", "None"))
            value = _format_price_by_symbol_v5(s, metrics.get("last"))
            delta = _fmt_pct(metrics.get("change"))
            delta_color = "#3cf0b4" if not str(delta).startswith("-") else "#ff5f73"

            st.markdown(
                f"""
                <div style="
                    border:1px solid rgba(90,205,255,.16);
                    background:linear-gradient(180deg,rgba(4,14,29,.84),rgba(2,8,20,.88));
                    border-radius:14px;
                    padding:10px 11px 9px 11px;
                    margin-bottom:6px;">
                    <div style="display:flex;justify-content:space-between;align-items:center;">
                        <div style="color:rgba(230,244,255,.70);font-size:.68rem;font-weight:850;letter-spacing:.10em;text-transform:uppercase;">
                            {_cc_escape(s)}
                        </div>
                        <div style="color:rgba(220,235,250,.48);font-size:.62rem;font-weight:780;">
                            {_cc_escape(provider)}
                        </div>
                    </div>
                    <div style="display:flex;align-items:baseline;gap:8px;margin-top:4px;">
                        <div style="color:#f8fbff;font-size:1.05rem;font-weight:900;">
                            {_cc_escape(value)}
                        </div>
                        <div style="color:{delta_color};font-size:.70rem;font-weight:850;">
                            {_cc_escape(delta)}
                        </div>
                    </div>
                    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:4px;margin-top:8px;">
                        <div style="color:rgba(220,235,250,.55);font-size:.61rem;">Range<br><b style="color:#f8fbff;">{_cc_escape(_fmt_pct(metrics.get("range")))}</b></div>
                        <div style="color:rgba(220,235,250,.55);font-size:.61rem;">RV proxy<br><b style="color:#f8fbff;">{_cc_escape(_fmt_pct(metrics.get("rv_proxy")))}</b></div>
                        <div style="color:rgba(220,235,250,.55);font-size:.61rem;">I-DD<br><b style="color:#f8fbff;">{_cc_escape(_fmt_pct(metrics.get("intraday_dd")))}</b></div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            if df is None or df.empty:
                st.caption("No curve")
                continue

            fig = _make_rebased_micro_chart_v9(df, s, height=142)
            st.plotly_chart(
                fig,
                use_container_width=True,
                config={"displayModeBar": False, "responsive": True},
            )

            st.caption(f"{_latest_update_from_meta_v12(meta)}")


# ------------------------------------------------------------
# V12 — Event monitor / module launchpad
# ------------------------------------------------------------

def _classify_event_v12(headline: str, symbol: str = "") -> tuple[str, str]:
    text = f"{headline} {symbol}".lower()
    if any(k in text for k in ["fed", "fomc", "rate", "treasury", "yield", "inflation", "cpi", "jobs", "payroll"]):
        return "Macro/Rates", "HIGH"
    if any(k in text for k in ["oil", "crude", "brent", "gold", "copper", "commodity"]):
        return "Commodities", "MEDIUM"
    if any(k in text for k in ["earnings", "guidance", "revenue", "eps"]):
        return "Earnings", "HIGH"
    if any(k in text for k in ["etf", "s&p", "nasdaq", "dow", "wall street"]):
        return "Equity Index", "MEDIUM"
    if symbol:
        return "Watchlist", "MEDIUM"
    return "General", "LOW"


def _render_news_panel_v3(news_df: pd.DataFrame) -> None:
    """
    Override V12 : Event Monitor instead of raw Latest News.
    """
    _section_v8("Event Monitor", "Classified public feed / watchlist headlines")
    if news_df is None or news_df.empty:
        st.caption("Event feed unavailable via yfinance. FMP/Finnhub can be connected later.")
        return

    for _, row in news_df.head(8).iterrows():
        headline = str(row.get("Headline", ""))[:190]
        source = str(row.get("Source", "N/A"))
        published = str(row.get("Published", "N/A"))
        symbol = str(row.get("Symbol", ""))
        bucket, impact = _classify_event_v12(headline, symbol)

        tone_color = "#ff5f73" if impact == "HIGH" else "#ffd166" if impact == "MEDIUM" else "rgba(220,235,250,.60)"
        st.markdown(
            f"""
            <div style="border-bottom:1px solid rgba(90,205,255,.10);padding:8px 0 9px 0;">
                <div style="display:flex;gap:7px;align-items:center;margin-bottom:3px;">
                    <span style="color:#55e8ff;font-size:.62rem;font-weight:900;letter-spacing:.12em;text-transform:uppercase;">{_cc_escape(bucket)}</span>
                    <span style="color:{tone_color};font-size:.62rem;font-weight:900;">{_cc_escape(impact)}</span>
                </div>
                <div style="color:rgba(245,249,255,.94);font-size:.82rem;font-weight:760;line-height:1.25;">{_cc_escape(headline)}</div>
                <div style="color:rgba(180,205,225,.58);font-size:.69rem;margin-top:3px;">{_cc_escape(symbol)} · {_cc_escape(source)} · {_cc_escape(published)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _render_quick_modules_v3(asset_class: str) -> None:
    """
    Override V12 : workflow-based module launchpad.
    """
    profile = get_asset_profile(asset_class)
    _section_v8("Module Launchpad", f"Workflow view · {profile['label']}")

    modes = list(profile.get("mode_options", []))

    groups = {
        "Research": ["Company Intelligence", "Correlation Matrix", "FX Dashboard", "Commodity Dashboard", "Rates Dashboard"],
        "Trading": ["Trading Plan", "Momentum / Trend", "Options / Futures", "Decision Engine", "Decision Engine Lite"],
        "Risk": ["Risk Monitor", "Monte Carlo Advanced"],
        "Validation": ["Backtest Lab", "ML Research Lab"],
    }

    html = ['<div style="display:grid;grid-template-columns:repeat(2,1fr);gap:9px;">']
    for group, candidates in groups.items():
        available = [m for m in candidates if m in modes]
        if not available:
            continue
        html.append(
            f"""
            <div style="border:1px solid rgba(90,205,255,.14);border-radius:13px;padding:10px 11px;background:rgba(2,10,23,.66);">
                <div style="color:#55e8ff;font-size:.67rem;font-weight:950;letter-spacing:.14em;text-transform:uppercase;margin-bottom:7px;">{_cc_escape(group)}</div>
            """
        )
        for mode in available[:4]:
            html.append(
                f"""
                <div style="color:#f8fbff;font-size:.75rem;font-weight:850;margin:4px 0;">
                    {_cc_escape(mode)}
                </div>
                """
            )
        html.append("</div>")
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)


# ------------------------------------------------------------
# V12 — Specialized asset boards
# ------------------------------------------------------------

def build_rates_board_v12() -> pd.DataFrame:
    symbols = tuple(MARKET_TAPE_UNIVERSES.get("Rates", []))
    df = load_market_tape_snapshot(symbols)
    if df.empty:
        return pd.DataFrame()
    out = _prepare_tape_display(df)
    return out[["Symbol", "Name", "Last", "Change %", "Direction", "Importance", "Status"]]


def build_fx_summary_v12() -> pd.DataFrame:
    df = build_fx_board_v3()
    if df is None or df.empty:
        return pd.DataFrame()
    return df


def build_commodity_summary_v12() -> pd.DataFrame:
    df = build_commodity_board_v3()
    if df is None or df.empty:
        return pd.DataFrame()
    return df


# ------------------------------------------------------------
# V12 — Global Command Center override
# ------------------------------------------------------------

def render_global_command_center() -> None:
    """
    V12 : institutional cockpit.
    """
    inject_command_center_css()

    current_asset = st.session_state.get("asset_class", "Equity")
    current_profile = get_asset_profile(current_asset)

    st.markdown(
        """
        <div class="cc-v3-hero">
            <div class="cc-v3-kicker">GLOBAL COMMAND CENTER · V12</div>
            <div class="cc-v3-title">Institutional Multi-Asset Cockpit</div>
            <div class="cc-v3-sub">
                Multi-asset monitoring, 5-second near-live pull, data quality control, market read,
                pressure map, regime scoring, event monitor and module workflow launchpad.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form("global_command_center_form_v12"):
        c1, c2, c3, c4, c5, c6 = st.columns([1.0, 2.25, 1.25, 0.85, 0.85, 1.0])
        with c1:
            asset_choice = st.selectbox("Asset Class", ["Auto"] + get_asset_classes(), index=0, key="gcc_asset_choice_v12")
        with c2:
            raw_symbol = st.text_input(
                "Search / Command",
                value=st.session_state.get("ticker") or current_profile["default_symbol"],
                placeholder="NVDA, EURUSD, CL=F, ^TNX, TLT...",
                key="gcc_symbol_input_v12",
            )

        inferred_asset = infer_asset_class_from_symbol(raw_symbol, fallback=current_asset)
        effective_asset = inferred_asset if asset_choice == "Auto" else asset_choice
        effective_profile = get_asset_profile(effective_asset)

        with c3:
            mode_choice = st.selectbox("Mode", effective_profile["mode_options"], index=0, key=f"gcc_mode_choice_v12_{effective_asset}")
        with c4:
            period_choice = st.selectbox(
                "Period",
                ["3mo", "6mo", "1y", "2y", "5y", "10y"],
                index=_select_index(["3mo", "6mo", "1y", "2y", "5y", "10y"], effective_profile["default_period"], 2),
                key=f"gcc_period_choice_v12_{effective_asset}",
            )
        with c5:
            interval_choice = st.selectbox("Interval", ["1d", "1wk", "1mo"], index=0, key=f"gcc_interval_choice_v12_{effective_asset}")
        with c6:
            launch = st.form_submit_button("LAUNCH", use_container_width=True)

        if launch:
            resolved_asset, resolved_symbol, resolved_mode = resolve_asset_symbol_and_mode(effective_asset, raw_symbol, mode_choice)
            _launch_workspace(resolved_asset, resolved_symbol, period_choice, interval_choice, resolved_mode)

    resolved_preview_asset, resolved_preview_symbol, resolved_preview_mode = resolve_asset_symbol_and_mode(
        effective_asset,
        raw_symbol,
        mode_choice,
    )
    st.caption(f"Inference: {resolved_preview_asset} · {resolved_preview_symbol} · {resolved_preview_mode}")

    tape_df = load_market_tape_snapshot(tuple(MARKET_TAPE_UNIVERSES["Global"]))
    regime = build_cross_asset_regime(tape_df)
    overview = build_market_overview_v3(tape_df)
    news_df = load_latest_news_snapshot(limit=10)
    gainers, losers = build_movers_v3(tape_df, n=5)
    curve_df = build_curve_snapshot_v3(tape_df)

    # Top strip.
    if tape_df is not None and not tape_df.empty:
        lookup = {row.get("Symbol"): row for _, row in tape_df.iterrows()}
        strip_items = [
            ("S&P FUT", lookup.get("ES=F")),
            ("NASDAQ FUT", lookup.get("NQ=F")),
            ("VIX", lookup.get("^VIX")),
            ("DXY", lookup.get("DX-Y.NYB")),
            ("10Y", lookup.get("^TNX")),
            ("WTI", lookup.get("CL=F")),
        ]
        html = ['<div class="cc-v3-strip">']
        for label, row in strip_items:
            value, meta = ("N/A", "WAIT") if row is None else (_value_for_symbol(row), _fmt_pct(row.get("Change %")))
            html.append(
                f'<div class="cc-v3-strip-card">'
                f'<div class="cc-v3-strip-label">{_cc_escape(label)}</div>'
                f'<div class="cc-v3-strip-value">{_cc_escape(value)}</div>'
                f'<div class="cc-v3-strip-meta">{_cc_escape(meta)}</div>'
                f'</div>'
            )
        html.append('</div>')
        st.markdown("".join(html), unsafe_allow_html=True)

    _render_market_read_v12(tape_df, regime)

    _section_v8("Live Curves", "Provider-aware intraday % move · range · realised-vol proxy · intraday drawdown")
    chart_symbols = LIVE_CHART_DEFAULTS.get(resolved_preview_asset, LIVE_CHART_DEFAULTS["Global"])
    _render_micro_curve_cards_v4(chart_symbols, asset_class=resolved_preview_asset, max_items=4)

    _section_v8("Global Market Tape", "Cross-asset instruments, direction and movement importance")
    _render_compact_tape_v3(tape_df, max_cards=12)

    _render_pressure_map_v12(tape_df)

    _section_v8("Macro Monitor", "Regime, curve, movers and event monitor")
    left, mid, right = st.columns([1.20, 1.0, 1.10])

    with left:
        _render_regime_panel_v3(regime, overview)

    with mid:
        _section_v8("Rates / Curve", "Yield proxies and curve state")
        if curve_df.empty:
            st.caption("Curve snapshot unavailable.")
        else:
            st.dataframe(curve_df, use_container_width=True, hide_index=True)

        _section_v8("Top Movers", "Extreme cross-asset movers")
        mtab1, mtab2 = st.tabs(["Gainers", "Losers"])
        with mtab1:
            st.dataframe(gainers, use_container_width=True, hide_index=True)
        with mtab2:
            st.dataframe(losers, use_container_width=True, hide_index=True)

    with right:
        _render_news_panel_v3(news_df)

    _section_v8("Asset Boards", "FX, rates, commodities and workflow launchpad")
    b1, b2, b3, b4 = st.columns([1, 1, 1, 1])

    with b1:
        _section_v8("FX Board", "Majors and dollar regime")
        fx_board = build_fx_summary_v12()
        if fx_board.empty:
            st.caption("FX board unavailable.")
        else:
            st.dataframe(fx_board, use_container_width=True, hide_index=True)

    with b2:
        _section_v8("Rates Board", "Duration and curve proxies")
        rates_board = build_rates_board_v12()
        if rates_board.empty:
            st.caption("Rates board unavailable.")
        else:
            st.dataframe(rates_board, use_container_width=True, hide_index=True)

    with b3:
        _section_v8("Commodities Board", "Energy, metals and agricultural proxies")
        commo_board = build_commodity_summary_v12()
        if commo_board.empty:
            st.caption("Commodities board unavailable.")
        else:
            st.dataframe(commo_board, use_container_width=True, hide_index=True)

    with b4:
        _render_quick_modules_v3(resolved_preview_asset)
        st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
        qcols = st.columns(2)
        for idx, asset_class in enumerate(get_asset_classes()):
            profile = get_asset_profile(asset_class)
            with qcols[idx % 2]:
                if st.button(
                    f"OPEN {profile['label']}",
                    key=f"gcc_quick_open_v12_{asset_class}",
                    use_container_width=True,
                ):
                    _launch_workspace(
                        asset_class,
                        profile["default_symbol"],
                        profile["default_period"],
                        profile["default_interval"],
                        default_mode_for_asset(asset_class),
                    )

    with st.expander("Full Tape — Global / Equity / FX / Commodities / Rates", expanded=False):
        tab_names = ["Global", "Equity", "FX", "Commodities", "Rates"]
        tabs = st.tabs(tab_names)
        for tab, name in zip(tabs, tab_names):
            with tab:
                symbols = tuple(MARKET_TAPE_UNIVERSES.get(name, MARKET_TAPE_UNIVERSES["Global"]))
                df = load_market_tape_snapshot(symbols)
                display = _prepare_tape_display(df)
                if display.empty:
                    st.info(f"{name} tape unavailable.")
                else:
                    st.dataframe(display, use_container_width=True, hide_index=True)


def render_asset_class_home() -> None:
    """
    V12 entry point.
    Keeps stable 5-second near-live pull mode.
    """
    c1, c2 = st.columns([0.9, 0.9])

    with c1:
        auto_refresh = st.toggle(
            "Live auto-refresh",
            value=True,
            key="live_auto_refresh_v12",
        )

    with c2:
        refresh_seconds = st.selectbox(
            "Refresh",
            [5, 10, 15, 30, 60],
            index=0,
            key="live_refresh_seconds_select_v12",
        )

    token = _maybe_autorefresh_v7(
        enabled=auto_refresh,
        interval_sec=int(refresh_seconds),
    )

    _render_live_state_bar_v8(auto_refresh, int(refresh_seconds), token)
    render_global_command_center()


# ============================================================
# END COMMAND CENTER V12
# ============================================================



# ============================================================
# COMMAND CENTER V12.1 — SAFE MODULE LAUNCHPAD + SCORE POLISH
# ============================================================
# Où coller :
# - Tout à la FIN de asset_class_router.py
# - Après le patch V12.
#
# Pourquoi :
# - Le PDF montre que le Module Launchpad rend du HTML brut sur les pages 2-3.
#   Donc on supprime le rendu HTML complexe à cet endroit.
# - Cette version utilise des composants Streamlit natifs : st.container,
#   st.columns, st.button, st.caption. Plus robuste, moins joli en CSS,
#   mais beaucoup plus sûr.
# - On corrige aussi le Risk Score trop binaire qui pouvait tomber à 0/100.
#
# Ne touche pas :
# - Backtest Lab
# - Risk Monitor
# - Monte Carlo
# - ML Research Lab
# - Decision Engine
# - Data providers
# ============================================================


# ------------------------------------------------------------
# V12.1 — less binary regime scoring
# ------------------------------------------------------------

def compute_regime_scores_v12(regime: dict[str, Any], tape_df: pd.DataFrame) -> dict[str, Any]:
    """
    Override V12.1.
    Score plus institutionnel : on évite les extrêmes 0/100 sauf vraie absence totale de signal.
    """
    tape_df = tape_df if tape_df is not None else pd.DataFrame()

    def get_change(symbol: str) -> float | None:
        if tape_df.empty or "Symbol" not in tape_df.columns:
            return None
        row = tape_df[tape_df["Symbol"] == symbol]
        if row.empty:
            return None
        return _v12_safe_float(row.iloc[0].get("Change %"))

    es = get_change("ES=F")
    nq = get_change("NQ=F")
    vix = get_change("^VIX")
    dxy = get_change("DX-Y.NYB")
    tnx = get_change("^TNX")
    wti = get_change("CL=F")

    equity_avg = np.nanmean([x for x in [es, nq] if x is not None]) if any(x is not None for x in [es, nq]) else 0.0

    # Risk score:
    # 50 baseline, penalize equity weakness, VIX bid, USD bid, rates up.
    risk_score = 50.0
    risk_score += max(min((equity_avg or 0.0) * 1200.0, 22.0), -22.0)
    risk_score -= max((vix or 0.0) * 120.0, 0.0)
    risk_score -= max((dxy or 0.0) * 900.0, 0.0)
    risk_score -= max((tnx or 0.0) * 350.0, 0.0)
    risk_score += max((wti or 0.0) * 100.0, -4.0)

    # Clamp not to 0/100 unless extremely strong.
    risk_score = max(8.0, min(92.0, risk_score))

    vol_pressure = 50.0 + max(min((vix or 0.0) * 450.0, 45.0), -25.0)
    dollar_pressure = 50.0 + max(min((dxy or 0.0) * 1800.0, 42.0), -42.0)
    rates_pressure = 50.0 + max(min((tnx or 0.0) * 1200.0, 42.0), -42.0)
    commo_pressure = 50.0 + max(min((wti or 0.0) * 900.0, 35.0), -35.0)

    vol_pressure = max(5.0, min(95.0, vol_pressure))
    dollar_pressure = max(5.0, min(95.0, dollar_pressure))
    rates_pressure = max(5.0, min(95.0, rates_pressure))
    commo_pressure = max(5.0, min(95.0, commo_pressure))

    if risk_score < 35:
        bias = "RISK-OFF"
    elif risk_score > 65:
        bias = "RISK-ON"
    else:
        bias = "BALANCED"

    confidence = int(
        min(
            92,
            max(
                45,
                abs(risk_score - 50) * 1.15
                + abs(vol_pressure - 50) * 0.35
                + abs(dollar_pressure - 50) * 0.25
                + abs(rates_pressure - 50) * 0.25
                + 35,
            ),
        )
    )

    return {
        "risk_score": int(round(risk_score)),
        "vol_pressure": int(round(vol_pressure)),
        "dollar_pressure": int(round(dollar_pressure)),
        "rates_pressure": int(round(rates_pressure)),
        "commodities_pressure": int(round(commo_pressure)),
        "bias": bias,
        "confidence": confidence,
        "drivers": _dominant_drivers_v12({
            "VIX": vol_pressure,
            "DXY": dollar_pressure,
            "Rates": rates_pressure,
            "Commodities": commo_pressure,
        }),
    }


# ------------------------------------------------------------
# V12.1 — pure Streamlit workflow launchpad
# ------------------------------------------------------------

def _available_modes_for_workflow_v121(asset_class: str) -> dict[str, list[str]]:
    profile = get_asset_profile(asset_class)
    modes = list(profile.get("mode_options", []))

    groups = {
        "Research": [
            "Company Intelligence",
            "Correlation Matrix",
            "FX Dashboard",
            "Commodity Dashboard",
            "Rates Dashboard",
        ],
        "Trading": [
            "Trading Plan",
            "Momentum / Trend",
            "Options / Futures",
            "Decision Engine",
            "Decision Engine Lite",
        ],
        "Risk": [
            "Risk Monitor",
            "Monte Carlo Advanced",
        ],
        "Validation": [
            "Backtest Lab",
            "ML Research Lab",
        ],
    }

    out: dict[str, list[str]] = {}
    for group, candidates in groups.items():
        available = [m for m in candidates if m in modes]
        if available:
            out[group] = available
    return out


def _workflow_default_symbol_v121(asset_class: str) -> str:
    try:
        return get_asset_profile(asset_class)["default_symbol"]
    except Exception:
        return st.session_state.get("ticker", "NVDA")


def _workflow_launch_button_v121(asset_class: str, mode: str, key_suffix: str) -> None:
    profile = get_asset_profile(asset_class)
    symbol = st.session_state.get("ticker") or profile["default_symbol"]

    if st.button(mode, key=f"workflow_launch_v121_{asset_class}_{key_suffix}_{mode}", use_container_width=True):
        _launch_workspace(
            asset_class,
            symbol,
            profile.get("default_period", "1y"),
            profile.get("default_interval", "1d"),
            mode,
        )


def _render_quick_modules_v3(asset_class: str) -> None:
    """
    Override V12.1.
    N'utilise plus de HTML complexe pour éviter l'affichage de balises brutes.
    """
    profile = get_asset_profile(asset_class)
    _section_v8("Module Launchpad", f"Workflow view · {profile['label']}")

    workflows = _available_modes_for_workflow_v121(asset_class)

    if not workflows:
        st.info("Aucun module disponible pour cette classe d'actif.")
        return

    # Two-column workflow grid, native Streamlit.
    workflow_items = list(workflows.items())
    cols = st.columns(2)

    for idx, (group, modes) in enumerate(workflow_items):
        with cols[idx % 2]:
            with st.container(border=True):
                st.markdown(f"**{group.upper()}**")
                for mode in modes[:5]:
                    _workflow_launch_button_v121(asset_class, mode, f"{idx}")

    st.caption(
        "Launchpad natif Streamlit · rendu robuste · aucun HTML brut."
    )


# ------------------------------------------------------------
# V12.1 — safer asset board section
# ------------------------------------------------------------

def render_global_command_center() -> None:
    """
    Override V12.1.
    Identique à V12 dans l'esprit, mais la partie Module Launchpad est native Streamlit.
    """
    inject_command_center_css()

    current_asset = st.session_state.get("asset_class", "Equity")
    current_profile = get_asset_profile(current_asset)

    st.markdown(
        """
        <div class="cc-v3-hero">
            <div class="cc-v3-kicker">GLOBAL COMMAND CENTER · V12.1</div>
            <div class="cc-v3-title">Institutional Multi-Asset Cockpit</div>
            <div class="cc-v3-sub">
                Multi-asset monitoring, 5-second near-live pull, data quality control, market read,
                pressure map, regime scoring, event monitor and native workflow launchpad.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form("global_command_center_form_v121"):
        c1, c2, c3, c4, c5, c6 = st.columns(
            [1.0, 2.25, 1.25, 0.85, 0.85, 1.0],
            vertical_alignment="bottom",
        )
        with c1:
            asset_choice = st.selectbox(
                "Asset Class",
                ["Auto"] + get_asset_classes(),
                index=0,
                key="gcc_asset_choice_v121",
            )
        with c2:
            raw_symbol = st.text_input(
                "Search / Command",
                value=st.session_state.get("ticker") or current_profile["default_symbol"],
                placeholder="NVDA, EURUSD, CL=F, ^TNX, TLT...",
                key="gcc_symbol_input_v121",
            )

        inferred_asset = infer_asset_class_from_symbol(raw_symbol, fallback=current_asset)
        effective_asset = inferred_asset if asset_choice == "Auto" else asset_choice
        effective_profile = get_asset_profile(effective_asset)

        with c3:
            mode_choice = st.selectbox(
                "Mode",
                effective_profile["mode_options"],
                index=0,
                key=f"gcc_mode_choice_v121_{effective_asset}",
            )
        with c4:
            period_choice = st.selectbox(
                "Period",
                ["3mo", "6mo", "1y", "2y", "5y", "10y"],
                index=_select_index(
                    ["3mo", "6mo", "1y", "2y", "5y", "10y"],
                    effective_profile["default_period"],
                    2,
                ),
                key=f"gcc_period_choice_v121_{effective_asset}",
            )
        with c5:
            interval_choice = st.selectbox(
                "Interval",
                ["1d", "1wk", "1mo"],
                index=0,
                key=f"gcc_interval_choice_v121_{effective_asset}",
            )
        with c6:
            launch = st.form_submit_button("LAUNCH", use_container_width=True)

        if launch:
            resolved_asset, resolved_symbol, resolved_mode = resolve_asset_symbol_and_mode(
                effective_asset,
                raw_symbol,
                mode_choice,
            )
            _launch_workspace(resolved_asset, resolved_symbol, period_choice, interval_choice, resolved_mode)

    resolved_preview_asset, resolved_preview_symbol, resolved_preview_mode = resolve_asset_symbol_and_mode(
        effective_asset,
        raw_symbol,
        mode_choice,
    )
    st.caption(
        f"Inference: {resolved_preview_asset} · {resolved_preview_symbol} · {resolved_preview_mode}"
    )

    tape_df = load_market_tape_snapshot(tuple(MARKET_TAPE_UNIVERSES["Global"]))
    regime = build_cross_asset_regime(tape_df)
    overview = build_market_overview_v3(tape_df)
    scores = compute_regime_scores_v12(regime, tape_df)
    news_df = load_latest_news_snapshot(limit=8)
    gainers, losers = build_movers_v3(tape_df, n=5)
    curve_df = build_curve_snapshot_v3(tape_df)

    if tape_df is not None and not tape_df.empty:
        lookup = {row.get("Symbol"): row for _, row in tape_df.iterrows()}
        strip_items = [
            ("S&P FUT", lookup.get("ES=F")),
            ("NASDAQ FUT", lookup.get("NQ=F")),
            ("VIX", lookup.get("^VIX")),
            ("DXY", lookup.get("DX-Y.NYB")),
            ("10Y", lookup.get("^TNX")),
            ("WTI", lookup.get("CL=F")),
        ]
        html = ['<div class="cc-v3-strip">']
        for label, row in strip_items:
            value, meta = ("N/A", "WAIT") if row is None else (_value_for_symbol(row), _fmt_pct(row.get("Change %")))
            html.append(
                f'<div class="cc-v3-strip-card">'
                f'<div class="cc-v3-strip-label">{_cc_escape(label)}</div>'
                f'<div class="cc-v3-strip-value">{_cc_escape(value)}</div>'
                f'<div class="cc-v3-strip-meta">{_cc_escape(meta)}</div>'
                f'</div>'
            )
        html.append('</div>')
        st.markdown("".join(html), unsafe_allow_html=True)

    _render_market_read_v12(regime, scores)

    _section_v8("Live Curves", "Provider-aware intraday % move · range · realised-vol proxy · intraday drawdown")
    chart_symbols = LIVE_CHART_DEFAULTS.get(resolved_preview_asset, LIVE_CHART_DEFAULTS["Global"])
    _render_micro_curve_cards_v4(chart_symbols, asset_class=resolved_preview_asset, max_items=4)

    _section_v8("Global Market Tape", "Cross-asset instruments, direction and movement importance")
    _render_compact_tape_v3(tape_df, max_cards=12)

    _render_pressure_map_v12(tape_df)

    _section_v8("Macro Monitor", "Regime, curve, movers and event monitor")
    left, mid, right = st.columns([1.15, 0.95, 1.20])

    with left:
        _render_regime_panel_v3(regime, overview)

    with mid:
        _section_v8("Rates / Curve", "Yield proxies and curve state")
        if curve_df.empty:
            st.caption("Curve snapshot indisponible.")
        else:
            st.dataframe(curve_df, use_container_width=True, hide_index=True)

        _section_v8("Top Movers", "Extreme cross-asset movers")
        mtab1, mtab2 = st.tabs(["Gainers", "Losers"])
        with mtab1:
            st.dataframe(_prepare_tape_display(gainers), use_container_width=True, hide_index=True)
        with mtab2:
            st.dataframe(_prepare_tape_display(losers), use_container_width=True, hide_index=True)

    with right:
        _render_news_panel_v3(news_df)

    _section_v8("Asset Boards", "FX, rates, commodities and workflow launchpad")
    b1, b2, b3, b4 = st.columns([1, 1, 1, 1.18])

    with b1:
        _section_v8("FX Board", "Majors and dollar regime")
        st.dataframe(build_fx_board_v3(), use_container_width=True, hide_index=True)

    with b2:
        _section_v8("Rates Board", "Duration and curve proxies")
        st.dataframe(build_rates_board_v12(), use_container_width=True, hide_index=True)

    with b3:
        _section_v8("Commodities Board", "Energy, metals and agricultural proxies")
        st.dataframe(build_commodity_board_v3(), use_container_width=True, hide_index=True)

    with b4:
        _render_quick_modules_v3(resolved_preview_asset)
        st.divider()
        qcols = st.columns(2)
        for idx, asset_class in enumerate(get_asset_classes()):
            profile = get_asset_profile(asset_class)
            with qcols[idx % 2]:
                if st.button(
                    f"OPEN {profile['label']}",
                    key=f"gcc_quick_open_v121_{asset_class}",
                    use_container_width=True,
                ):
                    _launch_workspace(
                        asset_class,
                        profile["default_symbol"],
                        profile["default_period"],
                        profile["default_interval"],
                        default_mode_for_asset(asset_class),
                    )

    with st.expander("Full Tape — Global / Equity / FX / Commodities / Rates", expanded=False):
        tab_names = ["Global", "Equity", "FX", "Commodities", "Rates"]
        tabs = st.tabs(tab_names)
        for tab, name in zip(tabs, tab_names):
            with tab:
                symbols = tuple(MARKET_TAPE_UNIVERSES.get(name, MARKET_TAPE_UNIVERSES["Global"]))
                df = load_market_tape_snapshot(symbols)
                display = _prepare_tape_display(df)
                if display.empty:
                    st.info(f"{name} tape indisponible.")
                else:
                    st.dataframe(display, use_container_width=True, hide_index=True)


def render_asset_class_home() -> None:
    c1, c2 = st.columns([0.9, 0.9], vertical_alignment="bottom")

    with c1:
        auto_refresh = st.toggle(
            "Live auto-refresh",
            value=True,
            key="live_auto_refresh_v121",
        )

    with c2:
        refresh_seconds = st.selectbox(
            "Refresh",
            [5, 10, 15, 30, 60],
            index=0,
            key="live_refresh_seconds_select_v121",
        )

    token = _maybe_autorefresh_v7(
        enabled=auto_refresh,
        interval_sec=int(refresh_seconds),
    )

    _render_live_state_bar_v8(auto_refresh, int(refresh_seconds), token)
    render_global_command_center()


# ============================================================
# END COMMAND CENTER V12.1 — SAFE MODULE LAUNCHPAD
# ============================================================



# ============================================================
# COMMAND CENTER V12.2 — HOTFIX MISSING V12 HELPERS
# ============================================================
# Où coller :
# - Tout à la FIN de asset_class_router.py
# - Après le patch V12.1.
#
# Problème corrigé :
# - NameError: name '_v12_safe_float' is not defined
# - Ajoute aussi un fallback prudent pour _dominant_drivers_v12 si absent.
#
# Cause :
# - compute_regime_scores_v12() appelle _v12_safe_float()
# - mais le helper n'existe pas dans ton fichier actuel ou a été écrasé
#   par l'empilement V12 / V12.1.
# ============================================================


def _v12_safe_float(value, default=None):
    """
    Conversion float robuste pour les scores V12.
    Compatible avec None, NaN, chaînes vides et valeurs pandas/numpy.
    """
    try:
        if value is None:
            return default

        if isinstance(value, str) and not value.strip():
            return default

        x = float(value)

        # NaN check sans dépendre uniquement de pandas.
        if x != x:
            return default

        try:
            if "np" in globals() and not np.isfinite(x):
                return default
        except Exception:
            pass

        return x
    except Exception:
        return default


def _dominant_drivers_v12(score_map):
    """
    Fallback prudent.
    Retourne les 3 drivers les plus éloignés d'un niveau neutre 50.
    """
    try:
        if not isinstance(score_map, dict) or not score_map:
            return "N/A"

        rows = []
        for name, value in score_map.items():
            x = _v12_safe_float(value)
            if x is None:
                continue
            rows.append((str(name), abs(x - 50.0), x))

        if not rows:
            return "N/A"

        rows = sorted(rows, key=lambda r: r[1], reverse=True)
        strong = [name for name, dist, _ in rows if dist >= 8.0]

        if strong:
            return " / ".join(strong[:3])

        return " / ".join([name for name, _, _ in rows[:3]])

    except Exception:
        return "N/A"


# ============================================================
# END COMMAND CENTER V12.2 — HOTFIX MISSING V12 HELPERS
# ============================================================



# ============================================================
# COMMAND CENTER V12.3 — HOTFIX MARKET READ ARGUMENT ORDER
# ============================================================
# Où coller :
# - Tout à la FIN de asset_class_router.py
# - Après V12.2.
#
# Problème corrigé :
# - AttributeError: 'dict' object has no attribute 'empty'
#
# Cause :
# - _render_market_read_v12(regime, scores) appelait encore
#   build_market_read_v12(tape_df, regime)
# - donc build_regime_scores_v12 recevait un dict à la place d'un DataFrame.
#
# Solution :
# - Redéfinir build_market_read_v12() de manière robuste.
# - Redéfinir _render_market_read_v12() pour accepter :
#       1) _render_market_read_v12(regime, scores)
#       2) _render_market_read_v12(tape_df, regime)
#       3) _render_market_read_v12(tape_df, regime, scores)
# ============================================================


def _v123_is_dataframe(obj) -> bool:
    try:
        return isinstance(obj, pd.DataFrame)
    except Exception:
        return hasattr(obj, "empty") and hasattr(obj, "columns")


def _v123_clean_regime(regime) -> dict:
    return regime if isinstance(regime, dict) else {}


def _v123_clean_scores(scores) -> dict:
    return scores if isinstance(scores, dict) else {}


def _v123_score(scores: dict, key: str, default=50):
    try:
        return scores.get(key, default)
    except Exception:
        return default


def build_market_read_v12(tape_df=None, regime=None, scores=None) -> dict:
    """
    Version robuste V12.3.

    Supporte les appels historiques :
    - build_market_read_v12(tape_df, regime)
    - build_market_read_v12(regime, scores)
    - build_market_read_v12(tape_df, regime, scores)
    """

    # Cas bug actuel : build_market_read_v12(regime_dict, scores_dict)
    if isinstance(tape_df, dict) and isinstance(regime, dict) and scores is None:
        maybe_regime = tape_df
        maybe_scores = regime

        if any(k in maybe_scores for k in ["risk_score", "vol_pressure", "bias", "confidence"]):
            tape_df = pd.DataFrame()
            regime = maybe_regime
            scores = maybe_scores

    # Cas défensif : premier argument dict seul.
    if isinstance(tape_df, dict) and regime is None:
        regime = tape_df
        tape_df = pd.DataFrame()

    if not _v123_is_dataframe(tape_df):
        tape_df = pd.DataFrame()

    regime = _v123_clean_regime(regime)

    if scores is None or not isinstance(scores, dict):
        try:
            scores = compute_regime_scores_v12(regime, tape_df)
        except Exception:
            scores = {}

    scores = _v123_clean_scores(scores)

    bias = str(scores.get("bias", "BALANCED"))
    confidence = int(_v12_safe_float(scores.get("confidence"), 50) or 50)

    risk = str(regime.get("risk", "N/A"))
    vol = str(regime.get("vol", "N/A"))
    dollar = str(regime.get("dollar", "N/A"))
    rates = str(regime.get("rates", "N/A"))
    commodities = str(regime.get("commodities", "N/A"))

    drivers = str(scores.get("drivers") or "N/A")

    if bias == "RISK-OFF":
        headline = "RISK-OFF: equity futures offered, volatility bid, dollar stronger, rates higher."
    elif bias == "RISK-ON":
        headline = "RISK-ON: equities bid, volatility softer, macro pressure contained."
    else:
        headline = "BALANCED: cross-asset signals are mixed; no dominant directional regime."

    detail = (
        f"Regime {risk}; vol {vol}; dollar {dollar}; rates {rates}; "
        f"commodities {commodities}. · Drivers: {drivers}"
    )

    return {
        "bias": bias,
        "confidence": confidence,
        "headline": headline,
        "detail": detail,
        "risk_score": int(_v12_safe_float(scores.get("risk_score"), 50) or 50),
        "vol_pressure": int(_v12_safe_float(scores.get("vol_pressure"), 50) or 50),
        "dollar_pressure": int(_v12_safe_float(scores.get("dollar_pressure"), 50) or 50),
        "rates_pressure": int(_v12_safe_float(scores.get("rates_pressure"), 50) or 50),
    }


def _render_market_read_v12(arg1=None, arg2=None, arg3=None) -> None:
    """
    Version robuste V12.3.

    Accepte :
    - _render_market_read_v12(regime, scores)
    - _render_market_read_v12(tape_df, regime)
    - _render_market_read_v12(tape_df, regime, scores)
    """

    tape_df = pd.DataFrame()
    regime = {}
    scores = None

    if _v123_is_dataframe(arg1):
        tape_df = arg1
        regime = _v123_clean_regime(arg2)
        scores = _v123_clean_scores(arg3) if isinstance(arg3, dict) else None

    elif isinstance(arg1, dict) and isinstance(arg2, dict):
        # Appel V12.1 actuel : _render_market_read_v12(regime, scores)
        regime = arg1
        scores = arg2

    elif isinstance(arg1, dict):
        regime = arg1
        scores = None

    read = build_market_read_v12(tape_df, regime, scores)

    _section_v8("Market Read", read.get("headline", "Market read unavailable."))

    st.caption(read.get("detail", ""))

    c1, c2, c3, c4, c5, c6 = st.columns(6)

    bias = str(read.get("bias", "BALANCED"))
    bias_tone = "bad" if bias == "RISK-OFF" else "good" if bias == "RISK-ON" else "warn"

    with c1:
        _status_pill_v8("Bias", bias, tone=bias_tone)
    with c2:
        _status_pill_v8("Confidence", f"{read.get('confidence', 50)}/100", tone="neutral")
    with c3:
        _status_pill_v8("Risk Score", f"{read.get('risk_score', 50)}/100", tone=bias_tone)
    with c4:
        _status_pill_v8("Vol Pressure", f"{read.get('vol_pressure', 50)}/100", tone="bad")
    with c5:
        _status_pill_v8("Dollar", f"{read.get('dollar_pressure', 50)}/100", tone="warn")
    with c6:
        _status_pill_v8("Rates", f"{read.get('rates_pressure', 50)}/100", tone="warn")


# ============================================================
# END COMMAND CENTER V12.3 — HOTFIX MARKET READ ARGUMENT ORDER
# ============================================================



# ============================================================
# COMMAND CENTER V13 — INSTITUTIONAL TABLES + NO LAUNCHPAD
# ============================================================
# Où coller :
# - Tout à la FIN de asset_class_router.py
# - Après V12.3.
#
# Objectifs :
# - Supprimer entièrement le Module Launchpad et les boutons OPEN.
# - Remplacer les tableaux noirs par des tableaux HTML auto-contenus
#   dans le même style visuel que le cockpit.
# - Ajouter un code couleur rouge/vert sur les mouvements.
# - Ajouter sous les live curves un tableau classique de niveaux :
#   Open / High / Low / Last / Move / Range / Intraday DD / Bars / Provider.
#
# Ne touche pas :
# - Backtest Lab
# - Risk Monitor
# - Monte Carlo
# - Decision Engine
# - Providers
# - app.py
# ============================================================

import html as _html_v13


# ------------------------------------------------------------
# V13 — formatting helpers
# ------------------------------------------------------------

def _v13_float(value, default=None):
    try:
        if value is None:
            return default
        if isinstance(value, str):
            clean = value.strip().replace(",", "")
            if not clean:
                return default
            if clean.endswith("%"):
                return float(clean.replace("%", "")) / 100.0
            return float(clean)
        x = float(value)
        if x != x:
            return default
        try:
            if "np" in globals() and not np.isfinite(x):
                return default
        except Exception:
            pass
        return x
    except Exception:
        return default


def _v13_escape(value) -> str:
    try:
        return _html_v13.escape(str(value))
    except Exception:
        return ""


def _v13_pct_value(value, default=None):
    return _v13_float(value, default)


def _v13_fmt_price(value, symbol: str = "") -> str:
    x = _v13_float(value)
    if x is None:
        return "N/A"
    s = str(symbol or "").upper()
    if s.endswith("=X") or "/" in s:
        return f"{x:,.5f}"
    if x < 10:
        return f"{x:,.4f}"
    return f"{x:,.2f}"


def _v13_fmt_pct(value) -> str:
    x = _v13_pct_value(value)
    if x is None:
        return "N/A"
    return f"{x:+.2%}"


def _v13_color_from_value(value) -> str:
    x = _v13_pct_value(value)
    if x is None:
        return "rgba(225,235,245,.78)"
    if x > 0:
        return "#3cf0b4"
    if x < 0:
        return "#ff5f73"
    return "rgba(225,235,245,.78)"


def _v13_bg_from_value(value) -> str:
    x = _v13_pct_value(value)
    if x is None:
        return "rgba(120,170,255,.045)"
    if x > 0:
        return "rgba(60,240,180,.095)"
    if x < 0:
        return "rgba(255,95,115,.095)"
    return "rgba(120,170,255,.045)"


def _v13_arrow(value) -> str:
    x = _v13_pct_value(value)
    if x is None:
        return "•"
    if x > 0:
        return "▲"
    if x < 0:
        return "▼"
    return "→"


def _v13_is_change_col(col: str) -> bool:
    c = str(col).lower()
    return any(k in c for k in ["change", "move", "return", "ret", "drawdown", "i-dd", "range"])


def _v13_get_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    if df is None or df.empty:
        return None
    lower = {str(c).lower(): c for c in df.columns}
    for cand in candidates:
        key = str(cand).lower()
        if key in lower:
            return lower[key]
    return None


# ------------------------------------------------------------
# V13 — self-contained institutional HTML table
# ------------------------------------------------------------

def _v13_html_table(
    df: pd.DataFrame,
    title: str | None = None,
    subtitle: str | None = None,
    max_rows: int | None = None,
    compact: bool = True,
    key_change_cols: list[str] | None = None,
) -> str:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        body = """
        <div style="border:1px solid rgba(90,205,255,.14);border-radius:14px;
                    background:rgba(4,14,29,.72);padding:12px;color:rgba(230,244,255,.55);
                    font-size:.74rem;">
            No data
        </div>
        """
        return body

    work = df.copy()
    if max_rows is not None:
        work = work.head(max_rows)

    key_change_cols = key_change_cols or []
    row_pad = "7px 8px" if compact else "9px 10px"
    font_size = ".70rem" if compact else ".76rem"

    parts = [
        """
        <div style="
            border:1px solid rgba(90,205,255,.18);
            background:linear-gradient(180deg,rgba(4,14,29,.86),rgba(2,8,20,.90));
            border-radius:15px;
            padding:10px 11px;
            box-shadow:0 0 0 1px rgba(255,255,255,.015) inset;
            overflow:auto;
            width:100%;">
        """
    ]

    if title:
        parts.append(
            f"""
            <div style="color:#55e8ff;font-size:.70rem;font-weight:950;
                        letter-spacing:.16em;text-transform:uppercase;margin-bottom:2px;">
                {_v13_escape(title)}
            </div>
            """
        )

    if subtitle:
        parts.append(
            f"""
            <div style="color:rgba(220,235,250,.52);font-size:.68rem;margin-bottom:8px;">
                {_v13_escape(subtitle)}
            </div>
            """
        )

    parts.append(
        f"""
        <table style="width:100%;border-collapse:collapse;font-size:{font_size};
                      color:rgba(235,245,255,.88);font-family:Inter,Arial,sans-serif;">
        <thead>
        <tr>
        """
    )

    for col in work.columns:
        parts.append(
            f"""
            <th style="text-align:left;padding:{row_pad};border-bottom:1px solid rgba(90,205,255,.18);
                       color:rgba(155,210,235,.80);font-weight:850;letter-spacing:.08em;
                       text-transform:uppercase;white-space:nowrap;">
                {_v13_escape(col)}
            </th>
            """
        )

    parts.append("</tr></thead><tbody>")

    for _, row in work.iterrows():
        parts.append("<tr>")
        row_change = None
        for col in work.columns:
            if _v13_is_change_col(col):
                row_change = row.get(col)
                break

        for col in work.columns:
            val = row.get(col)
            display = val

            # Reformat common numeric columns.
            if str(col).lower() in ["last", "price", "open", "high", "low", "close", "value"]:
                symbol = str(row.get("Symbol", row.get("symbol", "")))
                display = _v13_fmt_price(val, symbol)

            elif _v13_is_change_col(col):
                display = _v13_fmt_pct(val)
                if display != "N/A":
                    display = f"{_v13_arrow(val)} {display}"

            elif str(col).lower() in ["volume"]:
                x = _v13_float(val)
                display = "N/A" if x is None else f"{x:,.0f}"

            text_color = "rgba(235,245,255,.88)"
            bg = "transparent"
            fw = "650"

            if _v13_is_change_col(col):
                text_color = _v13_color_from_value(val)
                bg = _v13_bg_from_value(val)
                fw = "900"

            # Direction/Signal columns inherit row change color.
            if str(col).lower() in ["direction", "signal", "bias", "regime"]:
                text_color = _v13_color_from_value(row_change)
                fw = "900"

            parts.append(
                f"""
                <td style="padding:{row_pad};border-bottom:1px solid rgba(90,205,255,.075);
                           color:{text_color};background:{bg};font-weight:{fw};white-space:nowrap;">
                    {_v13_escape(display)}
                </td>
                """
            )

        parts.append("</tr>")

    parts.append("</tbody></table></div>")
    return "".join(parts)


def _render_table_v13(
    df: pd.DataFrame,
    title: str | None = None,
    subtitle: str | None = None,
    max_rows: int | None = None,
    compact: bool = True,
) -> None:
    st.markdown(
        _v13_html_table(
            df=df,
            title=title,
            subtitle=subtitle,
            max_rows=max_rows,
            compact=compact,
        ),
        unsafe_allow_html=True,
    )


# ------------------------------------------------------------
# V13 — market data table builders
# ------------------------------------------------------------

def _tape_to_table_v13(tape_df: pd.DataFrame, max_rows: int | None = None) -> pd.DataFrame:
    if tape_df is None or not isinstance(tape_df, pd.DataFrame) or tape_df.empty:
        return pd.DataFrame()

    work = tape_df.copy()

    symbol_col = _v13_get_col(work, ["Symbol"])
    name_col = _v13_get_col(work, ["Name"])
    last_col = _v13_get_col(work, ["Last", "Price", "Close"])
    chg_col = _v13_get_col(work, ["Change %", "Change", "Move"])

    out = pd.DataFrame()
    if symbol_col:
        out["Symbol"] = work[symbol_col].astype(str)
    if name_col:
        out["Name"] = work[name_col].astype(str)
    if last_col:
        out["Last"] = pd.to_numeric(work[last_col], errors="coerce")
    if chg_col:
        out["Change %"] = work[chg_col].apply(_v13_pct_value)
        out["Direction"] = out["Change %"].apply(lambda x: "BID" if _v13_float(x, 0) > 0 else "OFFER" if _v13_float(x, 0) < 0 else "FLAT")

    if "Volume" in work.columns:
        out["Volume"] = pd.to_numeric(work["Volume"], errors="coerce")

    if "Status" in work.columns:
        out["Status"] = work["Status"].astype(str)

    if max_rows:
        out = out.head(max_rows)

    return out


def _board_to_table_v13(df: pd.DataFrame, max_rows: int | None = None) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()

    work = df.copy()
    cols = list(work.columns)

    # Keep only useful columns if present.
    wanted = []
    for cand in ["Symbol", "Name", "Last", "Change %", "Direction", "Signal", "Regime", "Status"]:
        if cand in cols:
            wanted.append(cand)

    if not wanted:
        wanted = cols[:6]

    out = work[wanted].copy()

    # Normalize common values for color logic.
    if "Change %" in out.columns:
        out["Change %"] = out["Change %"].apply(_v13_pct_value)

    if "Direction" not in out.columns and "Change %" in out.columns:
        out["Direction"] = out["Change %"].apply(lambda x: "BID" if _v13_float(x, 0) > 0 else "OFFER" if _v13_float(x, 0) < 0 else "FLAT")

    if max_rows:
        out = out.head(max_rows)

    return out


def _render_compact_tape_v3(tape_df: pd.DataFrame, max_cards: int = 12) -> None:
    """
    Override V13.
    Remplace les cards par un tableau institutionnel avec code couleur.
    """
    table = _tape_to_table_v13(tape_df, max_rows=max_cards)
    _render_table_v13(
        table,
        title="Market Tape",
        subtitle="Classic price table · green/red move coding",
        compact=False,
    )


# ------------------------------------------------------------
# V13 — live curves with price-level tables
# ------------------------------------------------------------

def _live_levels_table_v13(df: pd.DataFrame, symbol: str, meta: dict[str, Any] | None = None) -> pd.DataFrame:
    meta = meta or {}

    if df is None or not isinstance(df, pd.DataFrame) or df.empty or "close" not in df.columns:
        return pd.DataFrame([{
            "Symbol": symbol,
            "Provider": meta.get("provider", "None"),
            "Open": None,
            "High": None,
            "Low": None,
            "Last": None,
            "Change %": None,
            "Range %": None,
            "I-DD %": None,
            "Bars": 0,
        }])

    work = df.copy()
    for col in ["open", "high", "low", "close"]:
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce")

    close = work["close"].dropna()
    if close.empty:
        return pd.DataFrame()

    open_px = _v13_float(work["open"].dropna().iloc[0] if "open" in work.columns and not work["open"].dropna().empty else close.iloc[0])
    high_px = _v13_float(work["high"].max() if "high" in work.columns else close.max())
    low_px = _v13_float(work["low"].min() if "low" in work.columns else close.min())
    last_px = _v13_float(close.iloc[-1])

    change = (last_px / open_px - 1.0) if open_px not in [None, 0] and last_px is not None else None
    range_pct = (high_px / low_px - 1.0) if high_px is not None and low_px not in [None, 0] else None

    try:
        running_max = close.cummax()
        idd = float((close / running_max - 1.0).min())
    except Exception:
        idd = None

    return pd.DataFrame([{
        "Symbol": symbol,
        "Provider": meta.get("provider", "None"),
        "Open": open_px,
        "High": high_px,
        "Low": low_px,
        "Last": last_px,
        "Change %": change,
        "Range %": range_pct,
        "I-DD %": idd,
        "Bars": int(len(work)),
    }])


def _render_micro_curve_cards_v4(symbols: list[str], asset_class: str = "Global", max_items: int = 4) -> None:
    """
    Override V13.
    Courbes + tableau classique des niveaux de prix.
    """
    shown = [str(s).strip() for s in symbols if str(s).strip()][:max_items]
    if not shown:
        return

    refresh_token = st.session_state.get("_live_refresh_token_v7", 0)
    cols = st.columns(len(shown))

    for col, symbol in zip(cols, shown):
        with col:
            s = _normalize_live_symbol_v4(symbol)
            df, meta = get_live_curve_v7(
                s,
                asset_class=asset_class,
                provider="auto",
                lookback_minutes=240,
                refresh_token=refresh_token,
            )
            metrics = build_live_curve_metrics_v4(df)

            # Header compact, no extra launchpad/HTML fragments.
            table = _live_levels_table_v13(df, s, meta)

            if df is None or df.empty:
                _render_table_v13(table, compact=True)
                st.caption("No intraday curve")
                continue

            fig = _make_rebased_micro_chart_v9(df, s, height=145)
            st.plotly_chart(
                fig,
                use_container_width=True,
                config={"displayModeBar": False, "responsive": True},
            )

            _render_table_v13(
                table,
                title=s,
                subtitle=f"{meta.get('provider', 'Provider')} · updated {meta.get('last_refresh_utc', '')}",
                compact=True,
            )


# ------------------------------------------------------------
# V13 — styled pressure map
# ------------------------------------------------------------

def _change_for_symbol_v13(tape_df: pd.DataFrame, symbol: str):
    try:
        if tape_df is None or tape_df.empty or "Symbol" not in tape_df.columns:
            return None
        row = tape_df[tape_df["Symbol"] == symbol]
        if row.empty:
            return None
        return _v13_pct_value(row.iloc[0].get("Change %"))
    except Exception:
        return None


def _name_for_symbol_v13(symbol: str) -> str:
    try:
        return SYMBOL_LABELS.get(symbol, symbol)
    except Exception:
        return symbol


def build_pressure_map_table_v13(tape_df: pd.DataFrame) -> pd.DataFrame:
    rows = []

    def avg(symbols):
        vals = [_change_for_symbol_v13(tape_df, s) for s in symbols]
        vals = [v for v in vals if v is not None]
        if not vals:
            return None
        return float(np.nanmean(vals))

    equity = avg(["ES=F", "NQ=F", "YM=F", "RTY=F"])
    vol = _change_for_symbol_v13(tape_df, "^VIX")
    fx = _change_for_symbol_v13(tape_df, "DX-Y.NYB")
    rates = avg(["^FVX", "^TNX", "^TYX"])
    commo = avg(["CL=F", "BZ=F", "GC=F", "SI=F"])

    blocs = [
        ("Equity", equity, "ES / NQ / YM / RTY"),
        ("Volatility", vol, "VIX"),
        ("FX", fx, "DXY"),
        ("Rates", rates, "5Y / 10Y / 30Y"),
        ("Commodities", commo, "Oil / Metals basket"),
    ]

    for bloc, move, driver in blocs:
        x = _v13_float(move)
        if x is None:
            direction = "WAIT"
            strength = "N/A"
        else:
            # For VIX/rates/USD, positive is pressure/risk-off, but still color by sign.
            direction = "BID" if x > 0 else "OFFER" if x < 0 else "FLAT"
            ax = abs(x)
            strength = "HIGH" if ax >= 0.01 else "MEDIUM" if ax >= 0.0035 else "LOW"

        rows.append({
            "Bloc": bloc,
            "Direction": direction,
            "Strength": strength,
            "Driver": driver,
            "Avg move": move,
        })

    return pd.DataFrame(rows)


def _render_pressure_map_v12(tape_df: pd.DataFrame) -> None:
    _section_v8("Cross-Asset Pressure Map", "Direction, strength and dominant driver by bloc")
    table = build_pressure_map_table_v13(tape_df)
    _render_table_v13(table, compact=False)


# ------------------------------------------------------------
# V13 — full command center without Module Launchpad
# ------------------------------------------------------------

def render_global_command_center() -> None:
    inject_command_center_css()

    current_asset = st.session_state.get("asset_class", "Equity")
    current_profile = get_asset_profile(current_asset)

    st.markdown(
        """
        <div class="cc-v3-hero">
            <div class="cc-v3-kicker">GLOBAL COMMAND CENTER · V13</div>
            <div class="cc-v3-title">Institutional Multi-Asset Cockpit</div>
            <div class="cc-v3-sub">
                Multi-asset monitoring, 5-second near-live pull, market read, pressure map,
                classic price tables, coloured market moves and event monitor.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form("global_command_center_form_v13"):
        c1, c2, c3, c4, c5, c6 = st.columns(
            [1.0, 2.25, 1.25, 0.85, 0.85, 1.0],
            vertical_alignment="bottom",
        )

        # ============================================================
        # WORLDMONITOR — DIRECT COMMAND CENTER ACCESS
        # ============================================================
        gem_cols = st.columns([1.35, 1.35, 4.30], vertical_alignment="center")

        with gem_cols[2]:
            st.caption(
                "Direct geopolitical monitor · macro regime · central banks · no ticker dependency."
            )
        with c1:
            asset_choice = st.selectbox(
                "Asset Class",
                ["Auto"] + get_asset_classes(),
                index=0,
                key="gcc_asset_choice_v13",
            )
        with c2:
            raw_symbol = st.text_input(
                "Search / Command",
                value=st.session_state.get("ticker") or current_profile["default_symbol"],
                placeholder="NVDA, EURUSD, CL=F, ^TNX, TLT...",
                key="gcc_symbol_input_v13",
            )

        inferred_asset = infer_asset_class_from_symbol(raw_symbol, fallback=current_asset)
        effective_asset = inferred_asset if asset_choice == "Auto" else asset_choice
        effective_profile = get_asset_profile(effective_asset)

        with c3:
            mode_choice = st.selectbox(
                "Mode",
                effective_profile["mode_options"],
                index=0,
                key=f"gcc_mode_choice_v13_{effective_asset}",
            )
        with c4:
            period_choice = st.selectbox(
                "Period",
                ["3mo", "6mo", "1y", "2y", "5y", "10y"],
                index=_select_index(
                    ["3mo", "6mo", "1y", "2y", "5y", "10y"],
                    effective_profile["default_period"],
                    2,
                ),
                key=f"gcc_period_choice_v13_{effective_asset}",
            )
        with c5:
            interval_choice = st.selectbox(
                "Interval",
                ["1d", "1wk", "1mo"],
                index=0,
                key=f"gcc_interval_choice_v13_{effective_asset}",
            )
        with c6:
            launch = st.form_submit_button("LAUNCH", use_container_width=True)

        if launch:
            resolved_asset, resolved_symbol, resolved_mode = resolve_asset_symbol_and_mode(
                effective_asset,
                raw_symbol,
                mode_choice,
            )
            _launch_workspace(resolved_asset, resolved_symbol, period_choice, interval_choice, resolved_mode)

    resolved_preview_asset, resolved_preview_symbol, resolved_preview_mode = resolve_asset_symbol_and_mode(
        effective_asset,
        raw_symbol,
        mode_choice,
    )
    st.caption(
        f"Inference: {resolved_preview_asset} · {resolved_preview_symbol} · {resolved_preview_mode}"
    )

    tape_df = load_market_tape_snapshot(tuple(MARKET_TAPE_UNIVERSES["Global"]))
    regime = build_cross_asset_regime(tape_df)
    scores = compute_regime_scores_v12(regime, tape_df)
    news_df = load_latest_news_snapshot(limit=8)
    gainers, losers = build_movers_v3(tape_df, n=5)
    curve_df = build_curve_snapshot_v3(tape_df)

    # Top strip remains cards because it is readable and compact.
    if tape_df is not None and not tape_df.empty:
        lookup = {row.get("Symbol"): row for _, row in tape_df.iterrows()}
        strip_items = [
            ("S&P FUT", lookup.get("ES=F")),
            ("NASDAQ FUT", lookup.get("NQ=F")),
            ("VIX", lookup.get("^VIX")),
            ("DXY", lookup.get("DX-Y.NYB")),
            ("10Y", lookup.get("^TNX")),
            ("WTI", lookup.get("CL=F")),
        ]
        html = ['<div class="cc-v3-strip">']
        for label, row in strip_items:
            value, meta = ("N/A", "WAIT") if row is None else (_value_for_symbol(row), _fmt_pct(row.get("Change %")))
            html.append(
                f'<div class="cc-v3-strip-card">'
                f'<div class="cc-v3-strip-label">{_cc_escape(label)}</div>'
                f'<div class="cc-v3-strip-value">{_cc_escape(value)}</div>'
                f'<div class="cc-v3-strip-meta" style="color:{_v13_color_from_value(row.get("Change %") if row is not None else None)}">{_cc_escape(meta)}</div>'
                f'</div>'
            )
        html.append('</div>')
        st.markdown("".join(html), unsafe_allow_html=True)

    _render_market_read_v12(regime, scores)

    _section_v8("Live Curves", "Intraday chart + classic price-level table")
    chart_symbols = LIVE_CHART_DEFAULTS.get(resolved_preview_asset, LIVE_CHART_DEFAULTS["Global"])
    _render_micro_curve_cards_v4(chart_symbols, asset_class=resolved_preview_asset, max_items=4)

    _section_v8("Global Market Tape", "Classic price table · green/red move coding")
    _render_compact_tape_v3(tape_df, max_cards=16)

    _render_pressure_map_v12(tape_df)

    _section_v8("Macro Monitor", "Regime, curve, movers and event monitor")
    left, mid, right = st.columns([1.10, 0.95, 1.25])

    with left:
        _render_regime_panel_v3(regime, pd.DataFrame())

    with mid:
        _section_v8("Rates / Curve", "Yield proxies and curve state")
        _render_table_v13(curve_df, compact=True)

        _section_v8("Top Movers", "Extreme cross-asset movers")
        mtab1, mtab2 = st.tabs(["Gainers", "Losers"])
        with mtab1:
            _render_table_v13(_tape_to_table_v13(gainers, max_rows=5), compact=True)
        with mtab2:
            _render_table_v13(_tape_to_table_v13(losers, max_rows=5), compact=True)

    with right:
        _render_news_panel_v3(news_df)

    _section_v8("Asset Boards", "FX, rates and commodities")
    b1, b2, b3 = st.columns(3)

    with b1:
        _section_v8("FX Board", "Majors and dollar regime")
        _render_table_v13(_board_to_table_v13(build_fx_board_v3(), max_rows=10), compact=True)

    with b2:
        _section_v8("Rates Board", "Duration and curve proxies")
        _render_table_v13(_board_to_table_v13(build_rates_board_v12(), max_rows=10), compact=True)

    with b3:
        _section_v8("Commodities Board", "Energy, metals and agricultural proxies")
        _render_table_v13(_board_to_table_v13(build_commodity_board_v3(), max_rows=10), compact=True)

    with st.expander("Full Tape — Global / Equity / FX / Commodities / Rates", expanded=False):
        tab_names = ["Global", "Equity", "FX", "Commodities", "Rates"]
        tabs = st.tabs(tab_names)
        for tab, name in zip(tabs, tab_names):
            with tab:
                symbols = tuple(MARKET_TAPE_UNIVERSES.get(name, MARKET_TAPE_UNIVERSES["Global"]))
                df = load_market_tape_snapshot(symbols)
                _render_table_v13(_tape_to_table_v13(df), compact=False)


def render_asset_class_home() -> None:
    c1, c2 = st.columns([0.9, 0.9], vertical_alignment="bottom")

    with c1:
        auto_refresh = st.toggle(
            "Live auto-refresh",
            value=True,
            key="live_auto_refresh_v13",
        )

    with c2:
        refresh_seconds = st.selectbox(
            "Refresh",
            [5, 10, 15, 30, 60],
            index=0,
            key="live_refresh_seconds_select_v13",
        )

    token = _maybe_autorefresh_v7(
        enabled=auto_refresh,
        interval_sec=int(refresh_seconds),
    )

    _render_live_state_bar_v8(auto_refresh, int(refresh_seconds), token)
    render_global_command_center()


# ============================================================
# END COMMAND CENTER V13 — INSTITUTIONAL TABLES + NO LAUNCHPAD
# ============================================================



# ============================================================
# COMMAND CENTER V13.1 — HOTFIX TABLE HTML RENDERING
# ============================================================
# Où coller :
# - Tout à la FIN de asset_class_router.py
# - Après V13.
#
# Problème corrigé :
# - Le PDF montre que les tableaux V13 affichent le HTML brut :
#   <div style=...>, <th style=...>, <td style=...>
#
# Cause probable :
# - st.markdown() interprète certains blocs HTML indentés comme du texte/code.
#
# Solution prudente :
# - On garde toute la logique V13.
# - On remplace seulement _render_table_v13().
# - Les tableaux passent par components.html(), donc le HTML est rendu dans
#   une iframe propre au lieu d'être interprété comme Markdown.
#
# Ne touche pas :
# - Providers
# - Live 5s
# - Backtest / Risk / Monte Carlo / ML
# - render_global_command_center()
# ============================================================

try:
    import streamlit.components.v1 as _components_v131
except Exception:
    _components_v131 = None


def _v131_table_height(df, compact: bool = True, title: str | None = None, subtitle: str | None = None) -> int:
    try:
        rows = 0 if df is None or not isinstance(df, pd.DataFrame) else len(df)
    except Exception:
        rows = 0

    row_h = 30 if compact else 36
    base = 56
    if title:
        base += 22
    if subtitle:
        base += 20

    height = base + row_h * max(1, min(rows, 18))
    return int(max(115, min(height, 560)))


def _render_table_v13(
    df: pd.DataFrame,
    title: str | None = None,
    subtitle: str | None = None,
    max_rows: int | None = None,
    compact: bool = True,
) -> None:
    """
    Override V13.1.
    Rendu HTML fiable via Streamlit components.
    Évite l'affichage brut des balises HTML dans le dashboard/PDF.
    """
    try:
        html_table = _v13_html_table(
            df=df,
            title=title,
            subtitle=subtitle,
            max_rows=max_rows,
            compact=compact,
        )

        html_doc = f"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
    html, body {{
        margin: 0;
        padding: 0;
        background: transparent;
        overflow-x: auto;
        overflow-y: auto;
        font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
    }}
    * {{
        box-sizing: border-box;
    }}
    ::-webkit-scrollbar {{
        height: 6px;
        width: 6px;
    }}
    ::-webkit-scrollbar-track {{
        background: rgba(255,255,255,.03);
    }}
    ::-webkit-scrollbar-thumb {{
        background: rgba(90,205,255,.25);
        border-radius: 99px;
    }}
</style>
</head>
<body>
{html_table}
</body>
</html>
"""

        if _components_v131 is not None:
            _components_v131.html(
                html_doc,
                height=_v131_table_height(df, compact=compact, title=title, subtitle=subtitle),
                scrolling=True,
            )
            return

        # Fallback extrême si components indisponible :
        # rendu dataframe natif, sans HTML brut.
        display_df = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
        st.dataframe(display_df, use_container_width=True, hide_index=True)

    except Exception as exc:
        st.warning(f"Table render fallback: {exc}")
        try:
            display_df = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
            st.dataframe(display_df, use_container_width=True, hide_index=True)
        except Exception:
            st.caption("Table unavailable.")


# ============================================================
# END COMMAND CENTER V13.1 — HOTFIX TABLE HTML RENDERING
# ============================================================


# ============================================================
# COMMAND CENTER V14 — ANALYTICAL READ LAYER
# ============================================================
# Où coller :
# - Tout à la FIN de asset_class_router.py
# - Après V13.1.
#
# Objectif :
# - Garder les tableaux V13/V13.1 validés.
# - Ne pas toucher aux providers, au live 5s, ni aux moteurs métier.
# - Ajouter une vraie couche de lecture analytique :
#     1) Movement Monitor plus utile que Top Movers vide.
#     2) Board Reads FX / Rates / Commodities.
#     3) Résumés directionnels : USD, duration, energy/metals, strongest/weakest.
#     4) Layout plus compact : pas de Module Launchpad.
#
# Ne touche pas :
# - Backtest Lab
# - Risk Monitor
# - Monte Carlo
# - Decision Engine
# - ML Research Lab
# - Options / Futures
# - Data providers
# - app.py
# ============================================================


# ------------------------------------------------------------
# V14 — defensive helpers
# ------------------------------------------------------------

def _v14_float(value, default=None):
    try:
        if value is None:
            return default
        if isinstance(value, str):
            text = value.strip().replace(",", "")
            if not text:
                return default
            if text.endswith("%"):
                return float(text.replace("%", "")) / 100.0
            return float(text)
        x = float(value)
        if x != x:
            return default
        try:
            if "np" in globals() and not np.isfinite(x):
                return default
        except Exception:
            pass
        return x
    except Exception:
        return default


def _v14_get_row(tape_df: pd.DataFrame, symbol: str) -> pd.Series | None:
    try:
        if tape_df is None or not isinstance(tape_df, pd.DataFrame) or tape_df.empty:
            return None
        if "Symbol" not in tape_df.columns:
            return None
        rows = tape_df[tape_df["Symbol"].astype(str).str.upper() == str(symbol).upper()]
        if rows.empty:
            return None
        return rows.iloc[0]
    except Exception:
        return None


def _v14_change(tape_df: pd.DataFrame, symbol: str):
    row = _v14_get_row(tape_df, symbol)
    if row is None:
        return None
    return _v14_float(row.get("Change %"))


def _v14_last(tape_df: pd.DataFrame, symbol: str):
    row = _v14_get_row(tape_df, symbol)
    if row is None:
        return None
    return _v14_float(row.get("Last"))


def _v14_name(symbol: str) -> str:
    try:
        return str(SYMBOL_LABELS.get(symbol, symbol))
    except Exception:
        return str(symbol)


def _v14_fmt_pct(value, digits: int = 2) -> str:
    x = _v14_float(value)
    if x is None:
        return "N/A"
    return f"{x:+.{digits}%}"


def _v14_fmt_move(value) -> str:
    x = _v14_float(value)
    if x is None:
        return "N/A"
    arrow = "▲" if x > 0 else "▼" if x < 0 else "→"
    return f"{arrow} {x:+.2%}"


def _v14_direction(value, pos_label: str = "BID", neg_label: str = "OFFER") -> str:
    x = _v14_float(value)
    if x is None:
        return "WAIT"
    if x > 0:
        return pos_label
    if x < 0:
        return neg_label
    return "FLAT"


def _v14_strength(value, symbol: str = "") -> str:
    x = _v14_float(value)
    if x is None:
        return "N/A"

    ax = abs(x)
    s = str(symbol or "").upper()

    # Thresholds adjusted by asset bloc. Change % for rates is relative yield move from Yahoo.
    if s == "^VIX":
        high, medium = 0.08, 0.03
    elif s in {"DX-Y.NYB"} or s.endswith("=X"):
        high, medium = 0.0050, 0.0020
    elif s in {"^IRX", "^FVX", "^TNX", "^TYX"}:
        high, medium = 0.0100, 0.0035
    elif s in {"CL=F", "BZ=F", "NG=F", "GC=F", "SI=F", "HG=F"}:
        high, medium = 0.0150, 0.0060
    else:
        high, medium = 0.0125, 0.0040

    if ax >= high:
        return "HIGH"
    if ax >= medium:
        return "MEDIUM"
    return "LOW"


def _v14_avg(values: list[float | None]):
    vals = [_v14_float(v) for v in values]
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return float(np.nanmean(vals))


def _v14_pick_extreme(tape_df: pd.DataFrame, symbols: list[str], mode: str = "max") -> tuple[str, float | None]:
    rows = []
    for sym in symbols:
        chg = _v14_change(tape_df, sym)
        if chg is not None:
            rows.append((sym, chg))
    if not rows:
        return "N/A", None
    rows = sorted(rows, key=lambda x: x[1], reverse=(mode == "max"))
    return rows[0]


# ------------------------------------------------------------
# V14 — movement monitor
# ------------------------------------------------------------

def _v14_asset_bloc(symbol: str) -> str:
    s = str(symbol or "").upper()
    if s in {"ES=F", "NQ=F", "YM=F", "RTY=F", "SPY", "QQQ", "IWM", "SMH", "XLF", "XLE", "XLK"}:
        return "Equity"
    if s == "^VIX":
        return "Vol"
    if s == "DX-Y.NYB" or s.endswith("=X"):
        return "FX"
    if s in {"^IRX", "^FVX", "^TNX", "^TYX", "SHY", "IEF", "TLT", "ZT=F", "ZN=F", "ZB=F"}:
        return "Rates"
    if s in {"CL=F", "BZ=F", "NG=F", "GC=F", "SI=F", "HG=F", "ZC=F", "ZS=F"}:
        return "Commo"
    return "Other"


def _v14_driver_read(symbol: str, move) -> str:
    s = str(symbol or "").upper()
    x = _v14_float(move)
    if x is None:
        return "WAIT"

    direction = "BID" if x > 0 else "OFFER" if x < 0 else "FLAT"

    if s == "^VIX":
        return f"VOL {direction}"
    if s == "DX-Y.NYB":
        return f"USD {direction}"
    if s.endswith("=X"):
        if s.startswith("USD"):
            return f"USD {direction}"
        return f"{s.replace('=X', '')} {direction}"
    if s in {"^IRX", "^FVX", "^TNX", "^TYX"}:
        return "YIELDS HIGHER" if x > 0 else "YIELDS LOWER" if x < 0 else "RATES FLAT"
    if s in {"SHY", "IEF", "TLT", "ZT=F", "ZN=F", "ZB=F"}:
        return "DURATION BID" if x > 0 else "DURATION OFFER" if x < 0 else "DURATION FLAT"
    if s in {"CL=F", "BZ=F", "NG=F"}:
        return f"ENERGY {direction}"
    if s in {"GC=F", "SI=F", "HG=F"}:
        return f"METALS {direction}"
    if s in {"ES=F", "NQ=F", "YM=F", "RTY=F"}:
        return f"FUTURES {direction}"
    return f"{_v14_asset_bloc(s).upper()} {direction}"


def build_movement_monitor_v14(tape_df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    if tape_df is None or not isinstance(tape_df, pd.DataFrame) or tape_df.empty:
        return pd.DataFrame()

    work = tape_df.copy()
    if "Symbol" not in work.columns:
        return pd.DataFrame()

    work["Move"] = work["Change %"].map(_v14_float)
    work = work.dropna(subset=["Move"]).copy()

    if work.empty:
        return pd.DataFrame()

    work["Abs move"] = work["Move"].abs()
    work["Bloc"] = work["Symbol"].map(_v14_asset_bloc)
    work["Strength"] = work.apply(lambda r: _v14_strength(r.get("Move"), r.get("Symbol")), axis=1)
    work["Signal"] = work.apply(lambda r: _v14_driver_read(r.get("Symbol"), r.get("Move")), axis=1)
    work["Direction"] = work["Move"].map(lambda x: _v14_direction(x))

    out = work.sort_values("Abs move", ascending=False).head(top_n).copy()

    # Use Change % as the colored column expected by V13 table renderer.
    out["Change %"] = out["Move"]

    keep = ["Symbol", "Name", "Bloc", "Last", "Change %", "Direction", "Strength", "Signal"]
    keep = [c for c in keep if c in out.columns]
    return out[keep].reset_index(drop=True)


def _render_movement_monitor_v14(tape_df: pd.DataFrame) -> None:
    _section_v8("Movement Monitor", "Largest current cross-asset moves · sorted by absolute move")
    monitor = build_movement_monitor_v14(tape_df, top_n=10)

    if monitor.empty:
        st.info("Movement monitor indisponible.")
        return

    _render_table_v13(
        monitor,
        title="Current Movers",
        subtitle="Prioritised by absolute move and driver read",
        compact=True,
    )


# ------------------------------------------------------------
# V14 — board reads
# ------------------------------------------------------------

def build_fx_read_v14(tape_df: pd.DataFrame) -> dict[str, Any]:
    fx_symbols = ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "USDCHF=X", "AUDUSD=X", "USDCAD=X", "EURJPY=X"]
    dxy = _v14_change(tape_df, "DX-Y.NYB")
    strongest, strongest_chg = _v14_pick_extreme(tape_df, fx_symbols, "max")
    weakest, weakest_chg = _v14_pick_extreme(tape_df, fx_symbols, "min")

    risk_fx = _v14_avg([_v14_change(tape_df, "AUDUSD=X"), _v14_change(tape_df, "USDCAD=X")])
    safe_haven = _v14_avg([_v14_change(tape_df, "USDJPY=X"), _v14_change(tape_df, "USDCHF=X")])

    if dxy is None:
        regime = "USD UNKNOWN"
        tone = "neutral"
    elif dxy > 0.002:
        regime = "USD BID"
        tone = "bad"
    elif dxy < -0.002:
        regime = "USD OFFER"
        tone = "good"
    else:
        regime = "USD FLAT"
        tone = "warn"

    read = (
        f"{regime}. Strongest pair: {strongest} {_v14_fmt_pct(strongest_chg)}. "
        f"Weakest pair: {weakest} {_v14_fmt_pct(weakest_chg)}."
    )

    return {
        "title": "FX Read",
        "headline": regime,
        "tone": tone,
        "read": read,
        "cards": [
            ("DXY", _v14_fmt_move(dxy), tone),
            ("Strongest", f"{strongest} {_v14_fmt_pct(strongest_chg)}", "good"),
            ("Weakest", f"{weakest} {_v14_fmt_pct(weakest_chg)}", "bad"),
            ("Risk FX", _v14_fmt_move(risk_fx), "neutral"),
            ("Haven proxy", _v14_fmt_move(safe_haven), "neutral"),
        ],
    }


def build_rates_read_v14(tape_df: pd.DataFrame) -> dict[str, Any]:
    y3m = _v14_last(tape_df, "^IRX")
    y5 = _v14_last(tape_df, "^FVX")
    y10 = _v14_last(tape_df, "^TNX")
    y30 = _v14_last(tape_df, "^TYX")

    c3m = _v14_change(tape_df, "^IRX")
    c5 = _v14_change(tape_df, "^FVX")
    c10 = _v14_change(tape_df, "^TNX")
    c30 = _v14_change(tape_df, "^TYX")

    avg_yield_move = _v14_avg([c5, c10, c30])

    spread_10_5 = None
    spread_30_10 = None
    if y10 is not None and y5 is not None:
        spread_10_5 = y10 - y5
    if y30 is not None and y10 is not None:
        spread_30_10 = y30 - y10

    long_vs_intermediate = None
    if c30 is not None and c5 is not None:
        long_vs_intermediate = c30 - c5

    if avg_yield_move is None:
        duration = "DURATION UNKNOWN"
        tone = "neutral"
    elif avg_yield_move > 0.0035:
        duration = "DURATION OFFERED"
        tone = "bad"
    elif avg_yield_move < -0.0035:
        duration = "DURATION BID"
        tone = "good"
    else:
        duration = "DURATION FLAT"
        tone = "warn"

    if long_vs_intermediate is None:
        curve = "Curve read unavailable"
    elif long_vs_intermediate > 0.002:
        curve = "Bear steepening proxy" if avg_yield_move and avg_yield_move > 0 else "Bull steepening proxy"
    elif long_vs_intermediate < -0.002:
        curve = "Bear flattening proxy" if avg_yield_move and avg_yield_move > 0 else "Bull flattening proxy"
    else:
        curve = "Parallel-ish move"

    read = f"{duration}. {curve}. 10Y-5Y proxy: {_v14_float(spread_10_5, 0):+.2f}; 30Y-10Y proxy: {_v14_float(spread_30_10, 0):+.2f}."

    return {
        "title": "Rates Read",
        "headline": duration,
        "tone": tone,
        "read": read,
        "cards": [
            ("5Y move", _v14_fmt_move(c5), tone),
            ("10Y move", _v14_fmt_move(c10), tone),
            ("30Y move", _v14_fmt_move(c30), tone),
            ("10Y-5Y", "N/A" if spread_10_5 is None else f"{spread_10_5:+.2f}", "neutral"),
            ("Curve", curve, "neutral"),
        ],
    }


def build_commodities_read_v14(tape_df: pd.DataFrame) -> dict[str, Any]:
    energy_symbols = ["CL=F", "BZ=F", "NG=F"]
    metals_symbols = ["GC=F", "SI=F", "HG=F"]
    agri_symbols = ["ZC=F", "ZS=F"]

    energy = _v14_avg([_v14_change(tape_df, s) for s in energy_symbols])
    metals = _v14_avg([_v14_change(tape_df, s) for s in metals_symbols])
    agri = _v14_avg([_v14_change(tape_df, s) for s in agri_symbols])

    all_symbols = energy_symbols + metals_symbols + agri_symbols
    strongest, strongest_chg = _v14_pick_extreme(tape_df, all_symbols, "max")
    weakest, weakest_chg = _v14_pick_extreme(tape_df, all_symbols, "min")

    if energy is not None and energy > 0.006:
        headline = "ENERGY BID"
        tone = "good"
    elif metals is not None and metals > 0.006:
        headline = "METALS BID"
        tone = "good"
    elif energy is not None and energy < -0.006 and metals is not None and metals < -0.006:
        headline = "COMMODITIES OFFERED"
        tone = "bad"
    else:
        headline = "COMMODITIES MIXED"
        tone = "warn"

    read = (
        f"{headline}. Energy basket {_v14_fmt_pct(energy)}; metals basket {_v14_fmt_pct(metals)}; "
        f"strongest {strongest} {_v14_fmt_pct(strongest_chg)}, weakest {weakest} {_v14_fmt_pct(weakest_chg)}."
    )

    return {
        "title": "Commodities Read",
        "headline": headline,
        "tone": tone,
        "read": read,
        "cards": [
            ("Energy", _v14_fmt_move(energy), "good" if _v14_float(energy, 0) > 0 else "bad"),
            ("Metals", _v14_fmt_move(metals), "good" if _v14_float(metals, 0) > 0 else "bad"),
            ("Agri", _v14_fmt_move(agri), "neutral"),
            ("Strongest", f"{strongest} {_v14_fmt_pct(strongest_chg)}", "good"),
            ("Weakest", f"{weakest} {_v14_fmt_pct(weakest_chg)}", "bad"),
        ],
    }


def _render_board_read_v14(read: dict[str, Any]) -> None:
    if not isinstance(read, dict):
        return

    title = str(read.get("title", "Board Read"))
    headline = str(read.get("headline", "N/A"))
    tone = str(read.get("tone", "neutral"))
    text = str(read.get("read", ""))

    _section_v8(title, text)

    cards = read.get("cards", [])
    if not isinstance(cards, list) or not cards:
        return

    cols = st.columns(min(len(cards), 5))
    for col, card in zip(cols, cards[:5]):
        try:
            label, value, card_tone = card
        except Exception:
            continue
        with col:
            _status_pill_v8(str(label), str(value), tone=str(card_tone or tone))


# ------------------------------------------------------------
# V14 — board renderers with summaries
# ------------------------------------------------------------

def _render_fx_board_v14(tape_df: pd.DataFrame) -> None:
    _render_board_read_v14(build_fx_read_v14(tape_df))
    _render_table_v13(
        _board_to_table_v13(build_fx_board_v3(), max_rows=10),
        title="FX Board",
        subtitle="Majors and dollar regime",
        compact=True,
    )


def _render_rates_board_v14(tape_df: pd.DataFrame) -> None:
    _render_board_read_v14(build_rates_read_v14(tape_df))
    _render_table_v13(
        _board_to_table_v13(build_rates_board_v12(), max_rows=10),
        title="Rates Board",
        subtitle="Duration and curve proxies",
        compact=True,
    )


def _render_commodities_board_v14(tape_df: pd.DataFrame) -> None:
    _render_board_read_v14(build_commodities_read_v14(tape_df))
    _render_table_v13(
        _board_to_table_v13(build_commodity_board_v3(), max_rows=10),
        title="Commodities Board",
        subtitle="Energy, metals and agricultural proxies",
        compact=True,
    )


# ------------------------------------------------------------
# V14 — full command center override
# ------------------------------------------------------------

def render_global_command_center() -> None:
    inject_command_center_css()

    current_asset = st.session_state.get("asset_class", "Equity")
    current_profile = get_asset_profile(current_asset)

    st.markdown(
        """
        <div class="cc-v3-hero">
            <div class="cc-v3-kicker">GLOBAL COMMAND CENTER · V14</div>
            <div class="cc-v3-title">Institutional Multi-Asset Cockpit</div>
            <div class="cc-v3-sub">
                5-second near-live pull, market read, cross-asset pressure, movement monitor,
                analytical FX/Rates/Commodities board reads and classic price tables.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form("global_command_center_form_v14"):
        c1, c2, c3, c4, c5, c6 = st.columns(
            [1.0, 2.25, 1.25, 0.85, 0.85, 1.0],
            vertical_alignment="bottom",
        )
        with c1:
            asset_choice = st.selectbox(
                "Asset Class",
                ["Auto"] + get_asset_classes(),
                index=0,
                key="gcc_asset_choice_v14",
            )
        with c2:
            raw_symbol = st.text_input(
                "Search / Command",
                value=st.session_state.get("ticker") or current_profile["default_symbol"],
                placeholder="NVDA, EURUSD, CL=F, ^TNX, TLT...",
                key="gcc_symbol_input_v14",
            )

        inferred_asset = infer_asset_class_from_symbol(raw_symbol, fallback=current_asset)
        effective_asset = inferred_asset if asset_choice == "Auto" else asset_choice
        effective_profile = get_asset_profile(effective_asset)

        with c3:
            mode_choice = st.selectbox(
                "Mode",
                effective_profile["mode_options"],
                index=0,
                key=f"gcc_mode_choice_v14_{effective_asset}",
            )
        with c4:
            period_choice = st.selectbox(
                "Period",
                ["3mo", "6mo", "1y", "2y", "5y", "10y"],
                index=_select_index(
                    ["3mo", "6mo", "1y", "2y", "5y", "10y"],
                    effective_profile["default_period"],
                    2,
                ),
                key=f"gcc_period_choice_v14_{effective_asset}",
            )
        with c5:
            interval_choice = st.selectbox(
                "Interval",
                ["1d", "1wk", "1mo"],
                index=0,
                key=f"gcc_interval_choice_v14_{effective_asset}",
            )
        with c6:
            launch = st.form_submit_button("LAUNCH", use_container_width=True)

        if launch:
            resolved_asset, resolved_symbol, resolved_mode = resolve_asset_symbol_and_mode(
                effective_asset,
                raw_symbol,
                mode_choice,
            )
            _launch_workspace(resolved_asset, resolved_symbol, period_choice, interval_choice, resolved_mode)

    resolved_preview_asset, resolved_preview_symbol, resolved_preview_mode = resolve_asset_symbol_and_mode(
        effective_asset,
        raw_symbol,
        mode_choice,
    )
    st.caption(f"Inference: {resolved_preview_asset} · {resolved_preview_symbol} · {resolved_preview_mode}")

    # ============================================================
    # WORLDMONITOR / MACRO — DIRECT COMMAND CENTER ACCESS
    # ============================================================
    st.markdown(
        """
        <div style="
            margin-top: 12px;
            margin-bottom: 14px;
            padding: 14px 16px;
            border: 1px solid rgba(90, 205, 255, 0.22);
            border-radius: 16px;
            background: rgba(4, 14, 30, 0.70);
        ">
            <div style="
                color: #55e8ff;
                font-size: 0.72rem;
                font-weight: 950;
                letter-spacing: 0.20em;
                text-transform: uppercase;
                margin-bottom: 5px;
            ">
                WORLDMONITOR / MACRO / BEHAVIORAL / AI LAYER
            </div>
            <div style="
                color: rgba(235,245,255,0.78);
                font-size: 0.82rem;
            ">
                Direct geopolitical monitor · macro regime · central banks · behavioral market state · Quant AI CIO / investment committee.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Four autonomous research workspaces at the same Command Center level.
    # Quant AI is deliberately adjacent to Market Psychology Lab.
    gem_cols = st.columns(
        [1.25, 1.35, 1.55, 1.30, 1.75],
        vertical_alignment="center",
    )

    with gem_cols[0]:
        if st.button(
            "WORLDMONITOR",
            use_container_width=True,
            key="gcc_open_worldmonitor_v211",
        ):
            st.session_state["worldmonitor_v211_open"] = True
            st.session_state["market_psychology_lab_open"] = False
            st.session_state["quant_ai_open"] = False
            st.session_state["asset_class_selected"] = True
            st.rerun()

    with gem_cols[1]:
        if st.button(
            "MACRO / CENTRAL BANKS",
            use_container_width=True,
            key="gcc_open_macro_central_banks_v14",
        ):
            st.session_state["quant_ai_open"] = False
            st.session_state["market_psychology_lab_open"] = False
            st.session_state["worldmonitor_v211_open"] = False
            _launch_macro_central_banks_hotfix()

    with gem_cols[2]:
        if st.button(
            "MARKET PSYCHOLOGY LAB",
            use_container_width=True,
            key="gcc_open_market_psychology_lab_v1",
        ):
            st.session_state["market_psychology_lab_open"] = True
            st.session_state["worldmonitor_v211_open"] = False
            st.session_state["quant_ai_open"] = False
            st.session_state["asset_class_selected"] = True
            st.rerun()

    with gem_cols[3]:
        if st.button(
            "QUANT AI · CIO",
            use_container_width=True,
            key="gcc_open_quant_ai_v1",
        ):
            st.session_state["quant_ai_open"] = True
            st.session_state["market_psychology_lab_open"] = False
            st.session_state["worldmonitor_v211_open"] = False
            st.session_state["asset_class_selected"] = True
            st.rerun()

    with gem_cols[4]:
        st.caption(
            "Command Center modules · geopolitics · macro · behavioral state · Quant AI CIO / specialist investment committee."
        )

    # Core data.
    tape_df = load_market_tape_snapshot(tuple(MARKET_TAPE_UNIVERSES["Global"]))
    regime = build_cross_asset_regime(tape_df)
    try:
        scores = compute_regime_scores_v12(regime, tape_df)
    except Exception:
        scores = {"bias": "BALANCED", "confidence": 50, "risk_score": 50}
    news_df = load_latest_news_snapshot(limit=8)
    curve_df = build_curve_snapshot_v3(tape_df)

    # Top strip.
    if tape_df is not None and not tape_df.empty:
        lookup = {row.get("Symbol"): row for _, row in tape_df.iterrows()}
        strip_items = [
            ("S&P FUT", lookup.get("ES=F")),
            ("NASDAQ FUT", lookup.get("NQ=F")),
            ("VIX", lookup.get("^VIX")),
            ("DXY", lookup.get("DX-Y.NYB")),
            ("10Y", lookup.get("^TNX")),
            ("WTI", lookup.get("CL=F")),
        ]

        html = ['<div class="cc-v3-strip">']
        for label, row in strip_items:
            if row is None:
                value = "N/A"
                meta = "WAIT"
                color = "rgba(225,235,245,.70)"
            else:
                change_value = row.get("Change %")
                value = _value_for_symbol(row)
                meta = _fmt_pct(change_value)
                color = _v13_color_from_value(change_value) if "_v13_color_from_value" in globals() else "rgba(225,235,245,.70)"

            html.append(
                f'<div class="cc-v3-strip-card">'
                f'<div class="cc-v3-strip-label">{_cc_escape(label)}</div>'
                f'<div class="cc-v3-strip-value">{_cc_escape(value)}</div>'
                f'<div class="cc-v3-strip-meta" style="color:{color}">{_cc_escape(meta)}</div>'
                f'</div>'
            )
        html.append("</div>")
        st.markdown("".join(html), unsafe_allow_html=True)

    # Analytical stack.
    _render_market_read_v12(regime, scores)

    _section_v8("Live Curves", "Intraday chart + price-level table")
    chart_symbols = LIVE_CHART_DEFAULTS.get(resolved_preview_asset, LIVE_CHART_DEFAULTS["Global"])
    _render_micro_curve_cards_v4(chart_symbols, asset_class=resolved_preview_asset, max_items=4)

    _section_v8("Global Market Tape", "Classic price table · green/red move coding")
    _render_compact_tape_v3(tape_df, max_cards=16)

    _render_pressure_map_v12(tape_df)

    # Replaces old weak Top Movers tabs.
    _render_movement_monitor_v14(tape_df)

    _section_v8("Macro Monitor", "Regime, rates curve and event monitor")
    left, mid, right = st.columns([1.08, 0.92, 1.25])

    with left:
        try:
            _render_regime_panel_v3(regime, pd.DataFrame())
        except Exception as exc:
            st.info(f"Regime panel indisponible : {exc}")

    with mid:
        _section_v8("Rates / Curve", "Yield proxies and curve state")
        _render_table_v13(curve_df, compact=True)

    with right:
        _render_news_panel_v3(news_df)

    _section_v8("Asset Boards", "Analytical board reads + underlying price tables")
    b1, b2, b3 = st.columns(3)

    with b1:
        _render_fx_board_v14(tape_df)

    with b2:
        _render_rates_board_v14(tape_df)

    with b3:
        _render_commodities_board_v14(tape_df)

    with st.expander("Full Tape — Global / Equity / FX / Commodities / Rates", expanded=False):
        tab_names = ["Global", "Equity", "FX", "Commodities", "Rates"]
        tabs = st.tabs(tab_names)
        for tab, name in zip(tabs, tab_names):
            with tab:
                symbols = tuple(MARKET_TAPE_UNIVERSES.get(name, MARKET_TAPE_UNIVERSES["Global"]))
                df = load_market_tape_snapshot(symbols)
                _render_table_v13(_tape_to_table_v13(df), compact=False)


def render_asset_class_home() -> None:
    c1, c2 = st.columns([0.9, 0.9], vertical_alignment="bottom")

    with c1:
        auto_refresh = st.toggle(
            "Live auto-refresh",
            value=True,
            key="live_auto_refresh_v14",
        )

    with c2:
        refresh_seconds = st.selectbox(
            "Refresh",
            [5, 10, 15, 30, 60],
            index=0,
            key="live_refresh_seconds_select_v14",
        )

    token = _maybe_autorefresh_v7(
        enabled=auto_refresh,
        interval_sec=int(refresh_seconds),
    )

    _render_live_state_bar_v8(auto_refresh, int(refresh_seconds), token)
    render_global_command_center()


# ============================================================
# END COMMAND CENTER V14 — ANALYTICAL READ LAYER
# ============================================================


# ============================================================
# COMMAND CENTER HOTFIX — MACRO / CENTRAL BANKS ROUTING LOCK
# ============================================================
# Objectif :
# - Enregistrer Macro / Central Banks comme vrai mode terminal.
# - Empêcher resolve_asset_symbol_and_mode() de le remplacer par Correlation Matrix.
# - Garder le lancement depuis le Command Center stable.
# ============================================================

MACRO_CENTRAL_BANKS_MODE = "Macro / Central Banks"


def _register_macro_central_banks_mode_hotfix() -> None:
    """
    Ajoute Macro / Central Banks dans les mode_options sans casser les anciens modes.
    Append-only et idempotent.
    """
    try:
        for asset_class, profile in ASSET_CLASS_REGISTRY.items():
            modes = profile.get("mode_options", [])

            if MACRO_CENTRAL_BANKS_MODE in modes:
                continue

            if asset_class == "Rates" and "Rates Dashboard" in modes:
                insert_at = modes.index("Rates Dashboard") + 1
            elif "Trading Plan" in modes:
                insert_at = modes.index("Trading Plan") + 1
            elif "Correlation Matrix" in modes:
                insert_at = modes.index("Correlation Matrix") + 1
            else:
                insert_at = 0

            modes.insert(insert_at, MACRO_CENTRAL_BANKS_MODE)
            profile["mode_options"] = modes
    except Exception:
        pass


_register_macro_central_banks_mode_hotfix()


try:
    _previous_resolve_asset_symbol_and_mode_macro_hotfix = resolve_asset_symbol_and_mode
except Exception:
    _previous_resolve_asset_symbol_and_mode_macro_hotfix = None


def resolve_asset_symbol_and_mode(
    selected_asset_class: str | None,
    raw_symbol: str,
    requested_mode: str | None = None,
) -> tuple[str, str, str]:
    """
    Hotfix macro :
    Si le mode demandé est Macro / Central Banks, on le préserve.
    Sans ça, l'ancien resolver peut fallback sur le premier mode compatible :
    Correlation Matrix.
    """
    _register_macro_central_banks_mode_hotfix()

    requested = str(requested_mode or "").strip()

    if requested == MACRO_CENTRAL_BANKS_MODE:
        asset_class = str(selected_asset_class or "Equity")

        if asset_class == "Auto" or asset_class not in ASSET_CLASS_REGISTRY:
            asset_class = "Equity"

        symbol = str(raw_symbol or "SPY").strip().upper() or "SPY"

        return asset_class, symbol, MACRO_CENTRAL_BANKS_MODE

    if callable(_previous_resolve_asset_symbol_and_mode_macro_hotfix):
        return _previous_resolve_asset_symbol_and_mode_macro_hotfix(
            selected_asset_class,
            raw_symbol,
            requested_mode,
        )

    asset_class = str(selected_asset_class or "Equity")
    if asset_class == "Auto" or asset_class not in ASSET_CLASS_REGISTRY:
        asset_class = infer_asset_class_from_symbol(raw_symbol, fallback="Equity")

    symbol = normalize_market_symbol(asset_class, raw_symbol)
    profile = get_asset_profile(asset_class)
    modes = profile.get("mode_options", [])

    mode = requested if requested in modes else default_mode_for_asset(asset_class)

    return asset_class, symbol, mode


def _launch_macro_central_banks_hotfix() -> None:
    """
    Lancement direct depuis le Command Center.
    Ne dépend pas du ticker utilisateur.
    SPY sert seulement de proxy marché pour que app.py dispose de price_data.
    """
    _register_macro_central_banks_mode_hotfix()

    st.session_state["asset_class"] = "Equity"
    st.session_state["asset_class_selected"] = True
    st.session_state["ticker"] = "SPY"

    st.session_state["mode_input"] = MACRO_CENTRAL_BANKS_MODE
    st.session_state["terminal_command_mode"] = MACRO_CENTRAL_BANKS_MODE
    st.session_state["terminal_selected_mode"] = MACRO_CENTRAL_BANKS_MODE

    st.session_state["auto_run_requested"] = True
    st.session_state["last_params"] = {
        "ticker": "SPY",
        "period": "2y",
        "interval": "1d",
        "asset_class": "Equity",
    }

    st.rerun()


# ============================================================
# END COMMAND CENTER HOTFIX — MACRO / CENTRAL BANKS ROUTING LOCK
# ============================================================

# ============================================================
# FIXED INCOME & CREDIT ANALYTICS — GLOBAL MODE REGISTRATION
# ============================================================
# À coller tout à la FIN de asset_class_router.py.
#
# Objectifs :
# - rendre le module visible dans le menu Mode principal ;
# - le rendre accessible depuis n'importe quel univers actif ;
# - enrichir l'univers Rates / Fixed Income ;
# - préserver tous les anciens modes ;
# - patch idempotent : aucun doublon après plusieurs redémarrages.
# ============================================================

FIXED_INCOME_CREDIT_MODE = "Fixed Income & Credit Analytics"


def _register_fixed_income_credit_mode() -> None:
    """
    Enregistre Fixed Income & Credit Analytics dans toutes les listes de modes.

    Le module est autonome et ne dépend pas du ticker Equity actif.
    Il doit donc rester accessible depuis la Command Line principale,
    même lorsque l'univers courant est encore Equity.
    """

    try:
        for asset_class, profile in ASSET_CLASS_REGISTRY.items():
            if not isinstance(profile, dict):
                continue

            modes = list(profile.get("mode_options", []))

            if FIXED_INCOME_CREDIT_MODE not in modes:

                # Placement institutionnel cohérent dans le menu.
                if "Macro / Central Banks" in modes:
                    insert_at = modes.index("Macro / Central Banks") + 1

                elif "Portfolio Lab" in modes:
                    insert_at = modes.index("Portfolio Lab") + 1

                elif "Rates Dashboard" in modes:
                    insert_at = modes.index("Rates Dashboard")

                elif "Correlation Matrix" in modes:
                    insert_at = modes.index("Correlation Matrix") + 1

                else:
                    insert_at = 0

                modes.insert(
                    insert_at,
                    FIXED_INCOME_CREDIT_MODE,
                )

            profile["mode_options"] = modes

    except Exception:
        pass

    # --------------------------------------------------------
    # Enrichissement spécifique de l'univers Rates
    # --------------------------------------------------------

    try:
        rates_profile = ASSET_CLASS_REGISTRY.get("Rates", {})

        if isinstance(rates_profile, dict):

            rates_profile["label"] = "FIXED INCOME"

            rates_profile["subtitle"] = (
                "Sovereign curves · credit · bonds · portfolio risk"
            )

            rates_profile["description"] = (
                "Yield curves, sovereign rates, credit spreads, bond pricing, "
                "duration, DV01, CS01, relative value, portfolio risk and stress tests."
            )

            existing_presets = list(
                rates_profile.get("presets", [])
            )

            required_presets = [
                "^IRX",
                "^FVX",
                "^TNX",
                "^TYX",
                "SHY",
                "IEF",
                "TLT",
                "TIP",
                "LQD",
                "HYG",
                "JNK",
                "VCIT",
                "VCSH",
                "EMB",
                "ZT=F",
                "ZF=F",
                "ZN=F",
                "ZB=F",
                "UB=F",
            ]

            for symbol in required_presets:
                if symbol not in existing_presets:
                    existing_presets.append(symbol)

            rates_profile["presets"] = existing_presets

            # Le module institutionnel devient le premier mode
            # uniquement dans l'univers Fixed Income.
            rates_modes = list(
                rates_profile.get("mode_options", [])
            )

            if FIXED_INCOME_CREDIT_MODE in rates_modes:
                rates_modes.remove(FIXED_INCOME_CREDIT_MODE)

            rates_modes.insert(
                0,
                FIXED_INCOME_CREDIT_MODE,
            )

            rates_profile["mode_options"] = rates_modes

            ASSET_CLASS_REGISTRY["Rates"] = rates_profile

    except Exception:
        pass

    # --------------------------------------------------------
    # Inférence automatique des instruments Fixed Income
    # --------------------------------------------------------

    try:
        RATES_SYMBOLS.update(
            {
                "^IRX",
                "^FVX",
                "^TNX",
                "^TYX",
                "SHY",
                "IEF",
                "TLT",
                "TIP",
                "LQD",
                "HYG",
                "JNK",
                "VCIT",
                "VCSH",
                "EMB",
                "ZT=F",
                "ZF=F",
                "ZN=F",
                "ZB=F",
                "UB=F",
            }
        )

    except Exception:
        pass


_register_fixed_income_credit_mode()


# ============================================================
# END FIXED INCOME & CREDIT ANALYTICS REGISTRATION
# ============================================================


# ============================================================
# INSTITUTIONAL ROUTER — CLEAN PRESENTATION FACADE
# ============================================================
# The historical market-data and analytics engines above remain stable, while
# the client-adaptive navigation experience lives in a focused, testable module.

from institutional_router import render_institutional_router


def render_asset_class_home() -> None:
    """Render the adaptive multi-window institutional navigator."""
    render_institutional_router(
        launch_workspace=_launch_workspace,
        snapshot_loader=load_market_tape_snapshot,
    )
