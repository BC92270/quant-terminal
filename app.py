import re
import os
import time
import requests
from datetime import datetime, timedelta
from html import escape

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
import xml.etree.ElementTree as ET
# ============================================================
# MONTE CARLO LAB — SAFE IMPORT
# ============================================================
try:
    from mc_lab import render_monte_carlo_advanced_lab
    MC_LAB_IMPORT_ERROR = None
except Exception as exc:
    render_monte_carlo_advanced_lab = None
    MC_LAB_IMPORT_ERROR = exc
from ml_lab.research_lab import render_ml_research_lab_v1
from decision_engine import render_decision_engine_v2
from risk_monitor import render_risk_monitor_v2
from trading_plan import render_trading_plan_v2
from correlation_matrix import render_correlation_intelligence_v1
from options_futures import render_options_futures_v1

# ============================================================
# COMPANY INTELLIGENCE — MODULAR PACKAGE
# ============================================================
try:
    from company_intelligence import (
        analyze_company_intelligence,
        render_company_intelligence_mode,
    )
    COMPANY_INTELLIGENCE_IMPORT_ERROR = None
except Exception as exc:
    analyze_company_intelligence = None
    render_company_intelligence_mode = None
    COMPANY_INTELLIGENCE_IMPORT_ERROR = exc
try:
    from macro_central_bank_lab import render_macro_central_bank_lab
except Exception:
    render_macro_central_bank_lab = None
from ui_theme import inject_global_theme, render_terminal_header
from ui_landing import render_landing_page
try:
    from momentum_trend import render_momentum_trend_terminal
    MOMENTUM_TREND_IMPORT_ERROR = None
except Exception as exc:
    render_momentum_trend_terminal = None
    MOMENTUM_TREND_IMPORT_ERROR = exc

from ui_terminal_standby import (
    apply_terminal_shell_theme,
    render_terminal_header_shell,
    render_sidebar_control_panel,
    render_terminal_command_panel,
)

try:
    from backtest_lab import render_backtest_lab_mode
except Exception:
    render_backtest_lab_mode = None

# ============================================================
# PORTFOLIO LAB — SAFE IMPORT
# ============================================================
try:
    from portfolio_lab import render_portfolio_lab_v1
    PORTFOLIO_LAB_IMPORT_ERROR = None
except Exception as exc:
    render_portfolio_lab_v1 = None
    PORTFOLIO_LAB_IMPORT_ERROR = exc

from asset_class_router import (
    get_asset_profile,
    normalize_market_symbol,
    resolve_asset_symbol_and_mode,
    render_asset_class_home,
    render_asset_control_sidebar,
    render_fx_dashboard,
    render_commodity_dashboard,
    render_rates_dashboard,
)

# ============================================================
# FIXED INCOME & CREDIT ANALYTICS — SAFE IMPORT
# ============================================================

try:
    from fixed_income_credit import (
        render_fixed_income_credit_analytics,
    )
    FIC_IMPORT_ERROR = None

except Exception as exc:
    render_fixed_income_credit_analytics = None
    FIC_IMPORT_ERROR = exc


# ============================================================
# MARKET PSYCHOLOGY LAB — SAFE IMPORT
# ============================================================
# Autonomous experimental behavioral-market workspace.
# It is opened from the Global Command Center and does not mutate
# the existing ticker-mode registry.
MARKET_PSYCHOLOGY_IMPORT_ERROR = None
render_market_psychology_lab = None

try:
    from market_psychology_lab import (
        render_market_psychology_lab,
        render_market_psychology_shell_header,
    )
except Exception as _exc:
    MARKET_PSYCHOLOGY_IMPORT_ERROR = _exc
    render_market_psychology_lab = None


# ============================================================
# QUANT AI CIO — SAFE IMPORT
# ============================================================
QUANT_AI_IMPORT_ERROR = None
render_quant_ai_terminal = None

try:
    from quant_ai_lab import render_quant_ai_terminal
except Exception as _exc:
    QUANT_AI_IMPORT_ERROR = _exc
    render_quant_ai_terminal = None


# ============================================================
# WORLDMONITOR — SAFE IMPORT
# ============================================================
# Important:
# Use a normal import instead of importlib.exec_module.
# The bridge uses @dataclass; dynamic exec without sys.modules registration
# can trigger: 'NoneType' object has no attribute '__dict__'.

WM_V211_IMPORT_ERROR = None
render_worldmonitor_bridge_v211 = None

try:
    import sys as _QT_sys
    from pathlib import Path as _QT_Path

    _qt_root = str(_QT_Path(__file__).resolve().parent)
    if _qt_root not in _QT_sys.path:
        _QT_sys.path.insert(0, _qt_root)

    from worldmonitor_bridge_v211 import render_worldmonitor_bridge_v211

except Exception as _exc:
    WM_V211_IMPORT_ERROR = _exc
    render_worldmonitor_bridge_v211 = None



# ============================================================
# SAFE UI / MODULE IMPORTS
# ============================================================
# Ajoute ce bloc en haut de app.py, après tes imports standards.
# Objectif : ne pas casser l'app si un module visuel est absent.

try:
    from ui_landing import render_landing_page
except Exception:
    render_landing_page = None

try:
    from correlation_matrix import render_correlation_intelligence_v1
except Exception:
    render_correlation_intelligence_v1 = None

try:
    from options_futures import render_options_futures_v1
except Exception:
    render_options_futures_v1 = None



st.set_page_config(
    page_title="Quant Terminal",
    page_icon="📈",
    layout="wide"
)

inject_global_theme()

if "terminal_entered" not in st.session_state:
    st.session_state["terminal_entered"] = False


# ============================================================
# GENERIC HELPERS
# ============================================================

def safe_float(value, default=None):
    try:
        if value is None:
            return default
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def safe_int(value, default=None):
    try:
        if value is None:
            return default
        if pd.isna(value):
            return default
        return int(value)
    except Exception:
        return default


def clamp(value: float, low: float = 0, high: float = 100) -> float:
    return max(low, min(high, value))


def fmt_price(value):
    return "N/A" if value is None or pd.isna(value) else round(float(value), 2)


def fmt_pct(value):
    return "N/A" if value is None or pd.isna(value) else f"{float(value):.2%}"


def fmt_num(value):
    if value is None or pd.isna(value):
        return "N/A"
    return f"{float(value):,.2f}"


def fmt_pp(value):
    if value is None or pd.isna(value):
        return "N/A"
    return f"{float(value) * 100:.2f} pts"


def fmt_large_number(value):
    value = safe_float(value)
    if value is None:
        return "N/A"

    sign = "-" if value < 0 else ""
    value = abs(value)

    if value >= 1_000_000_000_000:
        return f"{sign}{value / 1_000_000_000_000:.2f}T"
    if value >= 1_000_000_000:
        return f"{sign}{value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"{sign}{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{sign}{value / 1_000:.2f}K"
    return f"{sign}{value:.2f}"


def get_first_existing(info: dict, keys: list[str], default=None):
    for key in keys:
        value = info.get(key)
        if value is not None and not pd.isna(value):
            return value
    return default


def extract_statement_value(statement: pd.DataFrame, possible_rows: list[str], column_index: int = 0):
    if statement is None or statement.empty:
        return None

    for row in possible_rows:
        if row in statement.index:
            series = statement.loc[row].dropna()
            if len(series) > column_index:
                return safe_float(series.iloc[column_index])
    return None


def statement_row_series(statement: pd.DataFrame, possible_rows: list[str]) -> pd.Series:
    if statement is None or statement.empty:
        return pd.Series(dtype=float)

    for row in possible_rows:
        if row in statement.index:
            series = statement.loc[row].dropna()
            series = pd.to_numeric(series, errors="coerce").dropna()
            return series
    return pd.Series(dtype=float)


def make_statement_chart_df(statement: pd.DataFrame, row_map: dict[str, list[str]]) -> pd.DataFrame:
    if statement is None or statement.empty:
        return pd.DataFrame()

    rows = []

    for label, possible_rows in row_map.items():
        series = statement_row_series(statement, possible_rows)
        for date, value in series.items():
            rows.append({"Date": pd.to_datetime(date), "Metric": label, "Value": float(value)})

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = df.sort_values("Date")
    return df


# ============================================================
# DATA
# ============================================================

@st.cache_data(ttl=300)
def get_price_history(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    data = yf.download(
        ticker,
        period=period,
        interval=interval,
        progress=False,
        auto_adjust=False
    )

    if data.empty:
        raise ValueError(f"Aucune donnée trouvée pour le ticker : {ticker}")

    data = data.reset_index()

    data.columns = [
        col[0].lower() if isinstance(col, tuple) else str(col).lower()
        for col in data.columns
    ]

    data = data.rename(columns={
        "date": "date",
        "datetime": "date",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "adj close": "adj_close",
        "volume": "volume"
    })

    required_columns = ["date", "open", "high", "low", "close"]

    for col in required_columns:
        if col not in data.columns:
            raise ValueError(f"Colonne manquante dans les données : {col}")

    return data.dropna(subset=["close"])














# ============================================================
# ADDITIONAL FUNDAMENTAL PROVIDERS — ALPHA VANTAGE / SEC
# ============================================================









# ============================================================
# FINNHUB — EPS / REVENUE ESTIMATES + EARNINGS SURPRISE
# ============================================================

def get_finnhub_api_key() -> str:
    try:
        key = st.secrets.get("FINNHUB_API_KEY", "")
    except Exception:
        key = ""

    if not key:
        key = os.getenv("FINNHUB_API_KEY", "")

    return str(key).strip()


def finnhub_enabled() -> bool:
    return bool(get_finnhub_api_key())




def finnhub_get_json(endpoint: str, params: dict | None = None):
    token = get_finnhub_api_key()

    if not token:
        return {}

    request_params = dict(params or {})
    request_params["token"] = token

    try:
        response = requests.get(
            f"https://finnhub.io/api/v1/{endpoint.lstrip('/')}",
            params=request_params,
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()

        if isinstance(data, dict):
            msg = str(data).lower()
            if "error" in msg and len(data) <= 3:
                return {}

        return data

    except Exception:
        return {}













# ============================================================
# QUANT HELPERS
# ============================================================

def calculate_returns(prices: pd.Series) -> pd.Series:
    return prices.pct_change().dropna()


def calculate_volatility(returns: pd.Series) -> float:
    return float(returns.std() * np.sqrt(252))


def calculate_drift(returns: pd.Series) -> float:
    return float(returns.mean() * 252)


def calculate_momentum(prices: pd.Series) -> float:
    if len(prices) < 60:
        return 0.0

    perf_20d = prices.iloc[-1] / prices.iloc[-20] - 1
    perf_60d = prices.iloc[-1] / prices.iloc[-60] - 1

    return float(0.6 * perf_20d + 0.4 * perf_60d)


def calculate_max_drawdown(prices: pd.Series) -> float:
    cumulative_max = prices.cummax()
    drawdown = prices / cumulative_max - 1
    return float(drawdown.min())


def calculate_atr(data: pd.DataFrame, window: int = 14) -> float:
    high = data["high"]
    low = data["low"]
    close = data["close"]

    previous_close = close.shift(1)

    tr_1 = high - low
    tr_2 = (high - previous_close).abs()
    tr_3 = (low - previous_close).abs()

    true_range = pd.concat([tr_1, tr_2, tr_3], axis=1).max(axis=1)
    atr = true_range.rolling(window=window).mean().dropna()

    if atr.empty:
        return float(true_range.mean())

    return float(atr.iloc[-1])


def safe_performance(prices: pd.Series, days: int):
    if len(prices) <= days:
        return None

    return float(prices.iloc[-1] / prices.iloc[-days] - 1)


def calculate_performance_table(prices: pd.Series) -> pd.DataFrame:
    perf_map = {
        "5D": safe_performance(prices, 5),
        "1M": safe_performance(prices, 21),
        "3M": safe_performance(prices, 63),
        "6M": safe_performance(prices, 126),
        "1Y": safe_performance(prices, 252),
    }

    rows = []

    for label, value in perf_map.items():
        rows.append({
            "Horizon": label,
            "Performance": value
        })

    return pd.DataFrame(rows)


def calculate_52w_levels(prices: pd.Series) -> dict:
    lookback = min(len(prices), 252)
    recent = prices.tail(lookback)

    high_52w = float(recent.max())
    low_52w = float(recent.min())
    current = float(prices.iloc[-1])

    distance_high = current / high_52w - 1
    distance_low = current / low_52w - 1

    return {
        "high_52w": high_52w,
        "low_52w": low_52w,
        "distance_high": float(distance_high),
        "distance_low": float(distance_low)
    }


def calculate_sma(prices: pd.Series, window: int) -> float:
    sma = prices.rolling(window=window).mean().dropna()

    if sma.empty:
        return float("nan")

    return float(sma.iloc[-1])


def calculate_rsi(prices: pd.Series, window: int = 14) -> float:
    delta = prices.diff()

    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)

    avg_gain = gains.rolling(window=window).mean()
    avg_loss = losses.rolling(window=window).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.dropna()

    if rsi.empty:
        return float("nan")

    return float(rsi.iloc[-1])


def calculate_trend_metrics(price_data: pd.DataFrame) -> dict:
    close = price_data["close"].dropna()
    price = float(close.iloc[-1])

    sma_20 = calculate_sma(close, 20)
    sma_50 = calculate_sma(close, 50)
    sma_200 = calculate_sma(close, 200)
    rsi_14 = calculate_rsi(close, 14)

    perf_20d = safe_performance(close, 20)
    perf_60d = safe_performance(close, 60)
    perf_120d = safe_performance(close, 120)

    price_vs_sma20 = price / sma_20 - 1 if not np.isnan(sma_20) and sma_20 != 0 else None
    price_vs_sma50 = price / sma_50 - 1 if not np.isnan(sma_50) and sma_50 != 0 else None
    price_vs_sma200 = price / sma_200 - 1 if not np.isnan(sma_200) and sma_200 != 0 else None

    return {
        "sma_20": sma_20,
        "sma_50": sma_50,
        "sma_200": sma_200,
        "rsi_14": rsi_14,
        "perf_20d": perf_20d,
        "perf_60d": perf_60d,
        "perf_120d": perf_120d,
        "price_vs_sma20": price_vs_sma20,
        "price_vs_sma50": price_vs_sma50,
        "price_vs_sma200": price_vs_sma200,
    }


def calculate_trend_score(trend: dict) -> int:
    score = 0

    if trend["price_vs_sma20"] is not None and trend["price_vs_sma20"] > 0:
        score += 20

    if trend["price_vs_sma50"] is not None and trend["price_vs_sma50"] > 0:
        score += 20

    if trend["price_vs_sma200"] is not None and trend["price_vs_sma200"] > 0:
        score += 20

    if trend["perf_20d"] is not None and trend["perf_20d"] > 0:
        score += 15

    if trend["perf_60d"] is not None and trend["perf_60d"] > 0:
        score += 15

    rsi = trend["rsi_14"]

    if not pd.isna(rsi):
        if 50 <= rsi <= 70:
            score += 10
        elif 45 <= rsi < 50:
            score += 5
        elif rsi > 75:
            score -= 5

    return int(max(0, min(100, score)))


def generate_trend_diagnosis(trend: dict) -> str:
    trend_score = calculate_trend_score(trend)
    rsi = trend["rsi_14"]

    if pd.isna(rsi):
        rsi_comment = "RSI indisponible."
    elif rsi >= 70:
        rsi_comment = "RSI élevé : le titre peut être en zone de surachat court terme."
    elif rsi <= 30:
        rsi_comment = "RSI faible : le titre peut être en zone de survente court terme."
    elif rsi >= 55:
        rsi_comment = "RSI constructif : le momentum reste positif."
    elif rsi <= 45:
        rsi_comment = "RSI fragile : le momentum reste faible."
    else:
        rsi_comment = "RSI neutre."

    if trend_score >= 75:
        trend_label = "Tendance haussière confirmée."
    elif trend_score >= 60:
        trend_label = "Tendance positive mais pas totalement confirmée."
    elif trend_score >= 40:
        trend_label = "Tendance neutre ou en transition."
    elif trend_score >= 25:
        trend_label = "Tendance fragile."
    else:
        trend_label = "Tendance baissière ou dégradée."

    return f"{trend_label} {rsi_comment}"



# ============================================================
# MOMENTUM / TREND INTELLIGENCE CENTER V2
# ============================================================

@st.cache_data(ttl=60, show_spinner=False)
def get_live_quote_v2(ticker: str) -> dict:
    """
    Quote live avec fallback prudent.
    Priorité :
    1) Finnhub quote si token disponible
    2) yfinance fast_info
    3) vide => fallback historique dans le moteur
    """
    ticker = str(ticker or "").upper().strip()

    quote = {
        "price": None,
        "previous_close": None,
        "source": "Historical close",
        "timestamp": None,
    }

    if not ticker:
        return quote

    try:
        if finnhub_enabled():
            payload = finnhub_get_json("quote", {"symbol": ticker})
            if isinstance(payload, dict):
                live_price = safe_float(payload.get("c"))
                previous_close = safe_float(payload.get("pc"))
                ts = payload.get("t")

                if live_price is not None and live_price > 0:
                    quote.update({
                        "price": live_price,
                        "previous_close": previous_close,
                        "source": "Finnhub quote",
                        "timestamp": ts,
                    })
                    return quote
    except Exception:
        pass

    try:
        fast = yf.Ticker(ticker).fast_info
        live_price = safe_float(getattr(fast, "last_price", None) or fast.get("last_price"))
        previous_close = safe_float(getattr(fast, "previous_close", None) or fast.get("previous_close"))

        if live_price is not None and live_price > 0:
            quote.update({
                "price": live_price,
                "previous_close": previous_close,
                "source": "yfinance fast_info",
                "timestamp": None,
            })
            return quote
    except Exception:
        pass

    return quote


def calculate_ema_v2(prices: pd.Series, span: int) -> pd.Series:
    prices = pd.to_numeric(prices, errors="coerce")
    return prices.ewm(span=span, adjust=False).mean()


def calculate_rsi_series_v2(prices: pd.Series, window: int = 14) -> pd.Series:
    prices = pd.to_numeric(prices, errors="coerce")
    delta = prices.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    return rsi


def calculate_macd_v2(prices: pd.Series) -> pd.DataFrame:
    prices = pd.to_numeric(prices, errors="coerce")

    ema_12 = calculate_ema_v2(prices, 12)
    ema_26 = calculate_ema_v2(prices, 26)

    macd = ema_12 - ema_26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal

    return pd.DataFrame({
        "macd": macd,
        "macd_signal": signal,
        "macd_hist": hist,
    })


def calculate_atr_series_v2(data: pd.DataFrame, window: int = 14) -> pd.Series:
    high = pd.to_numeric(data["high"], errors="coerce")
    low = pd.to_numeric(data["low"], errors="coerce")
    close = pd.to_numeric(data["close"], errors="coerce")

    previous_close = close.shift(1)

    true_range = pd.concat([
        high - low,
        (high - previous_close).abs(),
        (low - previous_close).abs()
    ], axis=1).max(axis=1)

    return true_range.rolling(window=window).mean()


def calculate_regression_strength_v2(prices: pd.Series, window: int) -> dict:
    prices = pd.to_numeric(prices, errors="coerce").dropna()

    if len(prices) < window + 2:
        return {
            "slope": None,
            "r2": None,
            "annualized_slope": None,
        }

    y = np.log(prices.tail(window).values)
    x = np.arange(len(y))

    try:
        slope, intercept = np.polyfit(x, y, 1)
        fitted = slope * x + intercept

        ss_res = float(np.sum((y - fitted) ** 2))
        ss_tot = float(np.sum((y - np.mean(y)) ** 2))

        r2 = 1 - ss_res / ss_tot if ss_tot != 0 else 0
        annualized_slope = np.exp(slope * 252) - 1

        return {
            "slope": float(slope),
            "r2": float(r2),
            "annualized_slope": float(annualized_slope),
        }
    except Exception:
        return {
            "slope": None,
            "r2": None,
            "annualized_slope": None,
        }


def momentum_label_v2(score: float) -> str:
    score = safe_float(score, 50) or 50

    if score >= 80:
        return "Très fort"
    if score >= 65:
        return "Fort"
    if score >= 50:
        return "Constructif"
    if score >= 35:
        return "Fragile"
    return "Dégradé"


def noise_label_v2(score: float) -> str:
    score = safe_float(score, 50) or 50

    if score >= 75:
        return "Très élevé"
    if score >= 55:
        return "Élevé"
    if score >= 35:
        return "Modéré"
    return "Faible"


def timing_label_v2(score: float) -> str:
    score = safe_float(score, 50) or 50

    if score >= 75:
        return "Bon timing"
    if score >= 60:
        return "Correct"
    if score >= 45:
        return "À confirmer"
    return "Tendu"


def execution_status_v2(
    composite: float,
    trend_score: float,
    momentum_score: float,
    noise_risk: float,
    timing_score: float,
    relative_strength_score: float | None = None,
    breakout_quality_score: float | None = None,
    pullback_quality_score: float | None = None,
    exhaustion_risk_score: float | None = None,
    entry_timing_quality_score: float | None = None,
    volume_zscore: float | None = None,
) -> str:
    """
    Verdict décisionnel plus précis.
    Objectif :
    - éviter un BUY_ZONE trop générique ;
    - distinguer breakout, pullback, trend hold, extension excessive ;
    - utiliser les nouveaux scores avancés déjà calculés.
    """

    composite = safe_float(composite, 50) or 50
    trend_score = safe_float(trend_score, 50) or 50
    momentum_score = safe_float(momentum_score, 50) or 50
    noise_risk = safe_float(noise_risk, 50) or 50
    timing_score = safe_float(timing_score, 50) or 50

    rs_score = safe_float(relative_strength_score, 50) or 50
    breakout_score = safe_float(breakout_quality_score, 50) or 50
    pullback_score = safe_float(pullback_quality_score, 50) or 50
    exhaustion_score = safe_float(exhaustion_risk_score, 50) or 50
    entry_score = safe_float(entry_timing_quality_score, 50) or 50
    volume_z = safe_float(volume_zscore, 0) or 0

    strong_trend = trend_score >= 70
    strong_momentum = momentum_score >= 65
    clean_noise = noise_risk < 65
    noisy = noise_risk >= 70

    if trend_score < 40 and momentum_score < 45:
        return "BREAKDOWN_RISK"

    if exhaustion_score >= 75:
        return "EXHAUSTED_WAIT"

    if strong_trend and strong_momentum and breakout_score >= 70 and timing_score >= 55 and rs_score >= 50:
        if noisy:
            return "BREAKOUT_NOISY"
        if volume_z < -0.8:
            return "BREAKOUT_WEAK_VOLUME"
        return "BREAKOUT_BUY_ZONE"

    if strong_trend and momentum_score >= 55 and pullback_score >= 70 and entry_score >= 65:
        if noise_risk >= 75:
            return "PULLBACK_HIGH_NOISE"
        if exhaustion_score >= 65:
            return "PULLBACK_OK_BUT_EXTENDED"
    return "PULLBACK_BUY_ZONE"

    if strong_trend and strong_momentum and timing_score < 45:
        return "EXTENDED_WAIT"

    if trend_score >= 65 and momentum_score >= 55 and breakout_score < 55 and pullback_score < 60:
        return "TREND_HOLD"

    if trend_score >= 55 and momentum_score >= 50 and noisy:
        return "RANGE_NOISE"

    if composite >= 60:
        return "CONSTRUCTIVE_WAIT"

    return "NO_EDGE"


def execution_narrative_v2(status: str) -> str:
    mapping = {
        "BREAKOUT_BUY_ZONE": (
            "Cassure exploitable : trend confirmé, momentum positif, breakout quality correcte et timing encore acceptable."
        ),
        "BREAKOUT_NOISY": (
            "Cassure présente mais bruit élevée : attendre confirmation ou clôture propre avant entrée agressive."
        ),
        "BREAKOUT_WEAK_VOLUME": (
            "Cassure mécanique présente mais volume faible : signal à confirmer avant de lui donner trop de poids."
        ),
        "PULLBACK_BUY_ZONE": (
            "Repli exploitable dans tendance haussière : structure positive, timing favorable, risque d'extension maîtrisé."
        ),
        "PULLBACK_OK_BUT_EXTENDED": (
            "Repli intéressant mais encore un peu étendu : privilégier entrée progressive ou confirmation supplémentaire."
        ),
        "TREND_HOLD": (
            "Trend haussier encore valide, mais absence de vraie cassure ou de repli optimal : plutôt maintien / surveillance."
        ),
        "EXTENDED_WAIT": (
            "Trend fort mais prix étendu : le risque principal est le mauvais timing d'entrée."
        ),
        "EXHAUSTED_WAIT": (
            "Risque d'essoufflement élevé : éviter de courir après le mouvement, attendre respiration ou reset."
        ),
        "RANGE_NOISE": (
            "Signal directionnel présent mais bruit dominant : éviter de surinterpréter les cassures courtes."
        ),
        "BREAKDOWN_RISK": (
            "Structure technique dégradée : momentum faible et risque de rupture."
        ),
        "CONSTRUCTIVE_WAIT": (
            "Setup constructif mais incomplet : attendre validation prix, volume ou amélioration du timing."
        ),
        "NO_EDGE": (
            "Pas d'avantage technique clair : setup trop mixte."
        ),
        "PULLBACK_HIGH_NOISE": (
            "Repli techniquement exploitable, mais bruit très élevé : privilégier confirmation, sizing réduit ou entrée progressive."
        ),
    }

    return mapping.get(status, "Lecture technique mixte.")

@st.cache_data(ttl=300, show_spinner=False)
def get_benchmark_price_history_v2(
    benchmarks: tuple[str, ...] = ("SPY", "QQQ", "SMH"),
    period: str = "2y",
    interval: str = "1d",
) -> dict:
    """
    Télécharge les benchmarks pour relative strength.
    Retourne un dict benchmark -> DataFrame(date, close).
    Prudent : si un benchmark échoue, on l'ignore.
    """
    output = {}

    for benchmark in benchmarks:
        try:
            data = yf.download(
                benchmark,
                period=period,
                interval=interval,
                progress=False,
                auto_adjust=False
            )

            if data is None or data.empty:
                continue

            data = data.reset_index()

            # Gestion MultiIndex yfinance.
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = [
                    "_".join([str(x) for x in col if str(x) != ""]).strip("_").lower()
                    for col in data.columns
                ]
            else:
                data.columns = [str(c).lower() for c in data.columns]

            date_col = "date" if "date" in data.columns else "datetime" if "datetime" in data.columns else None

            close_candidates = [
                "adj close",
                "adj_close",
                f"adj close_{benchmark.lower()}",
                f"adj_close_{benchmark.lower()}",
                "close",
                f"close_{benchmark.lower()}",
            ]

            close_col = None

            for col in close_candidates:
                if col in data.columns:
                    close_col = col
                    break

            if date_col is None or close_col is None:
                # Fallback : chercher une colonne qui contient close.
                close_like = [c for c in data.columns if "close" in str(c).lower()]
                if not close_like:
                    continue
                close_col = close_like[0]

                date_like = [c for c in data.columns if "date" in str(c).lower()]
                if not date_like:
                    continue
                date_col = date_like[0]

            clean = data[[date_col, close_col]].copy()
            clean.columns = ["date", "close"]
            clean["date"] = pd.to_datetime(clean["date"], errors="coerce")
            clean["close"] = pd.to_numeric(clean["close"], errors="coerce")
            clean = clean.dropna(subset=["date", "close"]).sort_values("date")

            if not clean.empty:
                output[benchmark.upper()] = clean

        except Exception:
            continue

    return output


def benchmark_slug_v2(benchmark: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(benchmark).lower()).strip("_")


def enrich_relative_strength_frame_v2(
    df: pd.DataFrame,
    benchmarks: tuple[str, ...] = ("SPY", "QQQ", "SMH"),
) -> pd.DataFrame:
    """
    Ajoute :
    - rs_spy / rs_qqq / rs_smh : ratio relatif normalisé
    - rs_spy_20d / 60d : surperformance vs benchmark
    - rs_spy_slope_20 : pente annualisée du ratio relatif
    - relative_strength_score : score global 0-100
    """
    if df is None or df.empty or "date" not in df.columns or "close" not in df.columns:
        return df

    work = df.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work["close"] = pd.to_numeric(work["close"], errors="coerce")
    work = work.dropna(subset=["date", "close"]).sort_values("date")

    if work.empty:
        return df

    day_span = int((work["date"].max() - work["date"].min()).days)

    if day_span > 900:
        bench_period = "5y"
    elif day_span > 400:
        bench_period = "2y"
    else:
        bench_period = "1y"

    benchmark_data = get_benchmark_price_history_v2(
        benchmarks=benchmarks,
        period=bench_period,
        interval="1d",
    )

    score_inputs = []

    for benchmark, bench_df in benchmark_data.items():
        if bench_df is None or bench_df.empty:
            continue

        slug = benchmark_slug_v2(benchmark)

        bench = bench_df.copy()
        bench["date"] = pd.to_datetime(bench["date"], errors="coerce")
        bench["bench_close"] = pd.to_numeric(bench["close"], errors="coerce")
        bench = bench.dropna(subset=["date", "bench_close"]).sort_values("date")

        if bench.empty:
            continue

        aligned = pd.merge_asof(
            work[["date"]].sort_values("date"),
            bench[["date", "bench_close"]].sort_values("date"),
            on="date",
            direction="backward"
        )

        bench_close = aligned["bench_close"].reset_index(drop=True)

        first_stock = safe_float(work["close"].dropna().iloc[0])
        first_bench = safe_float(bench_close.dropna().iloc[0]) if not bench_close.dropna().empty else None

        if first_stock in [None, 0] or first_bench in [None, 0]:
            continue

        bench_col = f"bench_{slug}_close"
        rs_col = f"rs_{slug}"
        rs20_col = f"rs_{slug}_20d"
        rs60_col = f"rs_{slug}_60d"
        rsslope_col = f"rs_{slug}_slope_20"

        work[bench_col] = bench_close.values
        work[rs_col] = (work["close"] / first_stock) / (work[bench_col] / first_bench)

        stock_perf_20 = work["close"].pct_change(20)
        stock_perf_60 = work["close"].pct_change(60)
        bench_perf_20 = work[bench_col].pct_change(20)
        bench_perf_60 = work[bench_col].pct_change(60)

        work[rs20_col] = stock_perf_20 - bench_perf_20
        work[rs60_col] = stock_perf_60 - bench_perf_60
        work[rsslope_col] = np.exp((np.log(work[rs_col].replace(0, np.nan)).diff(20) / 20) * 252) - 1

        score_component = (
            50
            + work[rs20_col].apply(lambda x: clamp((safe_float(x, 0) or 0) * 250, -15, 15))
            + work[rs60_col].apply(lambda x: clamp((safe_float(x, 0) or 0) * 180, -15, 15))
            + work[rsslope_col].apply(lambda x: clamp((safe_float(x, 0) or 0) * 15, -10, 10))
            + work[rs_col].apply(lambda x: 7 if safe_float(x) is not None and safe_float(x) > 1 else -5)
        ).clip(0, 100)

        score_inputs.append(score_component)

    if score_inputs:
        score_matrix = pd.concat(score_inputs, axis=1)
        work["relative_strength_score"] = score_matrix.mean(axis=1).clip(0, 100)
    else:
        work["relative_strength_score"] = np.nan

    return work


def add_setup_quality_metrics_v2(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ajoute des métriques décisionnelles :
    - Breakout Quality
    - Pullback Quality
    - Exhaustion Risk
    - Entry Timing Quality

    Les scores sont mécaniques. On ne les branche pas encore fortement au score principal,
    sauf ajustement prudent dans build_momentum_trend_intelligence_v2.
    """
    if df is None or df.empty:
        return df

    work = df.copy()

    for col in [
        "close", "open", "high", "low", "ema_20", "ema_50", "sma_50",
        "rsi_14", "volume_zscore", "ema20_distance_atr",
        "bb_percent_b", "return_zscore_20", "drawdown",
        "noise_20", "signal_to_noise", "relative_strength_score"
    ]:
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce")

    high_low_range = (work["high"] - work["low"]).replace(0, np.nan) if all(c in work.columns for c in ["high", "low"]) else np.nan
    work["close_location"] = ((work["close"] - work["low"]) / high_low_range).clip(0, 1) if all(c in work.columns for c in ["close", "low"]) else np.nan

    work["rolling_high_60"] = work["close"].rolling(60).max()
    work["rolling_low_60"] = work["close"].rolling(60).min()
    work["breakout_60"] = work["close"] / work["rolling_high_60"].shift(1).replace(0, np.nan) - 1
    work["breakdown_60"] = work["close"] / work["rolling_low_60"].shift(1).replace(0, np.nan) - 1

    breakout_20 = pd.to_numeric(work.get("breakout_20", np.nan), errors="coerce").fillna(0)
    breakout_60 = pd.to_numeric(work.get("breakout_60", np.nan), errors="coerce").fillna(0)
    volume_z = pd.to_numeric(work.get("volume_zscore", np.nan), errors="coerce").fillna(0)
    close_location = pd.to_numeric(work.get("close_location", np.nan), errors="coerce").fillna(0.5)
    distance_atr = pd.to_numeric(work.get("ema20_distance_atr", np.nan), errors="coerce").fillna(0)
    rs_score = pd.to_numeric(work.get("relative_strength_score", np.nan), errors="coerce").fillna(50)

    breakout_score = (
        45
        + breakout_20.apply(lambda x: clamp(x * 800, -10, 20))
        + breakout_60.apply(lambda x: clamp(x * 500, -10, 18))
        + volume_z.apply(lambda x: 10 if x >= 1.5 else 6 if x >= 0.5 else -5 if x <= -1.0 else 0)
        + close_location.apply(lambda x: 8 if x >= 0.70 else 3 if x >= 0.55 else -6 if x <= 0.35 else 0)
        + distance_atr.apply(lambda x: 8 if 0 <= x <= 2.2 else -10 if x > 3.0 else -5 if x < -1.0 else 0)
        + (rs_score - 50) * 0.20
    )

    work["breakout_quality_score"] = breakout_score.clip(0, 100)

    drawdown = pd.to_numeric(work.get("drawdown", np.nan), errors="coerce").fillna(0)
    rsi = pd.to_numeric(work.get("rsi_14", np.nan), errors="coerce").fillna(50)
    noise_20 = pd.to_numeric(work.get("noise_20", np.nan), errors="coerce").fillna(0.04)

    above_ema20 = (work["close"] > work["ema_20"]) if "ema_20" in work.columns else False
    above_sma50 = (work["close"] > work["sma_50"]) if "sma_50" in work.columns else False

    pullback_score = (
        45
        + drawdown.apply(lambda x: 20 if -0.12 <= x <= -0.03 else 8 if -0.20 <= x < -0.12 else 4 if x > -0.03 else -15)
        + pd.Series(np.where(above_ema20, 12, -10), index=work.index)
        + pd.Series(np.where(above_sma50, 8, -8), index=work.index)
        + rsi.apply(lambda x: 12 if 45 <= x <= 62 else 4 if 38 <= x < 45 else 2 if 62 < x <= 68 else -10)
        + volume_z.apply(lambda x: 6 if x <= 0.5 else -8 if x >= 1.8 else 0)
        + noise_20.apply(lambda x: 6 if x <= 0.04 else -8 if x >= 0.07 else 0)
    )

    work["pullback_quality_score"] = pullback_score.clip(0, 100)

    bb_percent_b = pd.to_numeric(work.get("bb_percent_b", np.nan), errors="coerce").fillna(0.5)
    return_z = pd.to_numeric(work.get("return_zscore_20", np.nan), errors="coerce").fillna(0)

    exhaustion_score = (
        25
        + rsi.apply(lambda x: 22 if x >= 75 else 14 if x >= 70 else 7 if x >= 66 else 0)
        + distance_atr.apply(lambda x: 24 if x >= 3.0 else 14 if x >= 2.2 else 5 if x >= 1.6 else 0)
        + bb_percent_b.apply(lambda x: 18 if x >= 1.08 else 10 if x >= 1.0 else 0)
        + return_z.apply(lambda x: 14 if x >= 2.0 else 8 if x >= 1.3 else 0)
        + volume_z.apply(lambda x: 10 if x >= 1.8 else 5 if x >= 1.0 else 0)
        + drawdown.apply(lambda x: 7 if x > -0.03 else 0)
    )

    work["exhaustion_risk_score"] = exhaustion_score.clip(0, 100)

    entry_timing_score = (
        50
        + distance_atr.apply(lambda x: 18 if -0.3 <= x <= 1.6 else 6 if 1.6 < x <= 2.3 else -15 if x > 2.8 else -8 if x < -1.2 else 0)
        + noise_20.apply(lambda x: 10 if x <= 0.04 else -8 if x >= 0.07 else 0)
        + rsi.apply(lambda x: 8 if 48 <= x <= 65 else -8 if x >= 73 or x <= 35 else 0)
        + work["exhaustion_risk_score"].apply(lambda x: 10 if x <= 45 else -12 if x >= 70 else 0)
        + (rs_score - 50) * 0.12
    )

    work["entry_timing_quality_score"] = entry_timing_score.clip(0, 100)

    return work


def prepare_momentum_frame_v2(price_data: pd.DataFrame, live_price: float | None = None) -> pd.DataFrame:
    df = price_data.copy()
    df.columns = [str(c).lower() for c in df.columns]

    if "date" not in df.columns:
        df = df.reset_index().rename(columns={"index": "date"})

    df["date"] = pd.to_datetime(df["date"], errors="coerce")

    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)

    if live_price is not None and len(df) > 0:
        live_price = safe_float(live_price)
        if live_price is not None and live_price > 0:
            last_idx = df.index[-1]
            df.loc[last_idx, "close"] = live_price

            if "high" in df.columns:
                df.loc[last_idx, "high"] = max(safe_float(df.loc[last_idx, "high"], live_price) or live_price, live_price)
            if "low" in df.columns:
                df.loc[last_idx, "low"] = min(safe_float(df.loc[last_idx, "low"], live_price) or live_price, live_price)

    close = df["close"]

    df["return"] = close.pct_change()
    df["ema_10"] = calculate_ema_v2(close, 10)
    df["ema_20"] = calculate_ema_v2(close, 20)
    df["ema_50"] = calculate_ema_v2(close, 50)
    df["sma_50"] = close.rolling(50).mean()
    df["sma_200"] = close.rolling(200).mean()

    df["rsi_14"] = calculate_rsi_series_v2(close, 14)

    macd_df = calculate_macd_v2(close)
    df = pd.concat([df, macd_df], axis=1)

    df["atr_14"] = calculate_atr_series_v2(df, 14)
    df["atr_pct"] = df["atr_14"] / df["close"]

    df["vol_20"] = df["return"].rolling(20).std() * np.sqrt(252)
    df["vol_60"] = df["return"].rolling(60).std() * np.sqrt(252)

    df["trend_component"] = df["close"].ewm(span=50, adjust=False).mean()
    df["noise_residual"] = df["close"] / df["trend_component"] - 1
    df["noise_20"] = df["noise_residual"].rolling(20).std()
    df["signal_to_noise"] = df["return"].rolling(20).mean().abs() / df["return"].rolling(20).std().replace(0, np.nan)

    df["bb_mid"] = df["close"].rolling(20).mean()
    df["bb_std"] = df["close"].rolling(20).std()
    df["bb_upper"] = df["bb_mid"] + 2 * df["bb_std"]
    df["bb_lower"] = df["bb_mid"] - 2 * df["bb_std"]

    df["atr_upper"] = df["ema_20"] + 2 * df["atr_14"]
    df["atr_lower"] = df["ema_20"] - 2 * df["atr_14"]

    rolling_high = df["close"].cummax()
    df["drawdown"] = df["close"] / rolling_high - 1

    if "volume" in df.columns:
        vol_mean = df["volume"].rolling(20).mean()
        vol_std = df["volume"].rolling(20).std()
        df["volume_zscore"] = (df["volume"] - vol_mean) / vol_std.replace(0, np.nan)
    else:
        df["volume_zscore"] = np.nan

    # ------------------------------------------------------------
    # Advanced modular metrics — trend / noise / breakout / regime
    # ------------------------------------------------------------

    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"].replace(0, np.nan)
    df["bb_width_zscore"] = (
        df["bb_width"] - df["bb_width"].rolling(60).mean()
    ) / df["bb_width"].rolling(60).std().replace(0, np.nan)

    df["bb_percent_b"] = (
        df["close"] - df["bb_lower"]
    ) / (df["bb_upper"] - df["bb_lower"]).replace(0, np.nan)

    df["ema20_distance_atr"] = (
        df["close"] - df["ema_20"]
    ) / df["atr_14"].replace(0, np.nan)

    df["return_zscore_20"] = (
        df["return"] - df["return"].rolling(20).mean()
    ) / df["return"].rolling(20).std().replace(0, np.nan)

    df["atr_pct_zscore"] = (
        df["atr_pct"] - df["atr_pct"].rolling(60).mean()
    ) / df["atr_pct"].rolling(60).std().replace(0, np.nan)

    df["rolling_high_20"] = df["close"].rolling(20).max()
    df["rolling_low_20"] = df["close"].rolling(20).min()

    df["breakout_20"] = df["close"] / df["rolling_high_20"].shift(1).replace(0, np.nan) - 1
    df["breakdown_20"] = df["close"] / df["rolling_low_20"].shift(1).replace(0, np.nan) - 1

    df["high_52w"] = df["close"].rolling(252, min_periods=60).max()
    df["low_52w"] = df["close"].rolling(252, min_periods=60).min()

    df["distance_high_52w"] = df["close"] / df["high_52w"].replace(0, np.nan) - 1
    df["distance_low_52w"] = df["close"] / df["low_52w"].replace(0, np.nan) - 1

    df["position_52w"] = (
        df["close"] - df["low_52w"]
    ) / (df["high_52w"] - df["low_52w"]).replace(0, np.nan)

    df["trend_slope_20"] = np.log(df["trend_component"].replace(0, np.nan)).diff(20)
    df["trend_slope_20_annualized"] = np.exp((df["trend_slope_20"] / 20) * 252) - 1

    if "volume" in df.columns:
        df["volume_ratio_20"] = df["volume"] / df["volume"].rolling(20).mean().replace(0, np.nan)
    else:
        df["volume_ratio_20"] = np.nan

    return df


def build_multi_timeframe_table_v2(df: pd.DataFrame) -> pd.DataFrame:
    close = df["close"].dropna()
    latest_price = safe_float(close.iloc[-1]) if not close.empty else None

    rows = []

    horizon_map = {
        "5D": 5,
        "20D": 20,
        "60D": 60,
        "120D": 120,
        "200D": 200,
    }

    for label, days in horizon_map.items():
        if latest_price is None or len(close) <= days:
            continue

        perf = close.iloc[-1] / close.iloc[-days] - 1
        reg = calculate_regression_strength_v2(close, min(days, len(close) - 1))

        sub_returns = close.tail(days).pct_change().dropna()
        realized_vol = float(sub_returns.std() * np.sqrt(252)) if not sub_returns.empty else None

        direction_score = 50
        if perf > 0:
            direction_score += min(25, perf * 300)
        else:
            direction_score += max(-25, perf * 300)

        r2_score = 0 if reg.get("r2") is None else clamp(reg["r2"] * 30, 0, 30)
        slope_score = 0

        if reg.get("annualized_slope") is not None:
            slope = reg["annualized_slope"]
            if slope > 0:
                slope_score = min(20, slope * 50)
            else:
                slope_score = max(-20, slope * 50)

        vol_penalty = 0
        if realized_vol is not None:
            if realized_vol > 0.75:
                vol_penalty = 12
            elif realized_vol > 0.50:
                vol_penalty = 7
            elif realized_vol > 0.35:
                vol_penalty = 3

        score = clamp(direction_score + r2_score + slope_score - vol_penalty)

        if score >= 75:
            signal = "Bull confirmé"
        elif score >= 60:
            signal = "Bull constructif"
        elif score >= 45:
            signal = "Neutre / range"
        elif score >= 30:
            signal = "Fragile"
        else:
            signal = "Bearish"

        rows.append({
            "Horizon": label,
            "Performance": perf,
            "Trend slope annualisée": reg.get("annualized_slope"),
            "R² trend": reg.get("r2"),
            "Vol réalisée": realized_vol,
            "Score": round(score, 1),
            "Signal": signal,
        })

    return pd.DataFrame(rows)


def build_momentum_trend_intelligence_v2(ticker: str, price_data: pd.DataFrame) -> dict:
    quote = get_live_quote_v2(ticker)
    live_price = safe_float(quote.get("price"))

    df = prepare_momentum_frame_v2(price_data, live_price=live_price)

    try:
        df = enrich_relative_strength_frame_v2(df, benchmarks=("SPY", "QQQ", "SMH"))
    except Exception:
        df["relative_strength_score"] = np.nan

    try:
        df = add_setup_quality_metrics_v2(df)
    except Exception:
        for col in [
            "breakout_quality_score",
            "pullback_quality_score",
            "exhaustion_risk_score",
            "entry_timing_quality_score",
            "close_location",
            "breakout_60",
            "breakdown_60",
        ]:
            df[col] = np.nan

    if df.empty:
        return {
            "available": False,
            "reason": "Données prix indisponibles.",
        }

    close = df["close"].dropna()
    latest = df.iloc[-1]

    latest_price = safe_float(latest.get("close"))
    previous_close = safe_float(quote.get("previous_close"))

    if previous_close is None and len(close) >= 2:
        previous_close = safe_float(close.iloc[-2])

    daily_change = None
    if latest_price is not None and previous_close not in [None, 0]:
        daily_change = latest_price / previous_close - 1

    ema_20 = safe_float(latest.get("ema_20"))
    ema_50 = safe_float(latest.get("ema_50"))
    sma_50 = safe_float(latest.get("sma_50"))
    sma_200 = safe_float(latest.get("sma_200"))
    rsi = safe_float(latest.get("rsi_14"))
    macd_hist = safe_float(latest.get("macd_hist"))
    atr_pct = safe_float(latest.get("atr_pct"))
    vol_20 = safe_float(latest.get("vol_20"))
    noise_20 = safe_float(latest.get("noise_20"))
    signal_to_noise = safe_float(latest.get("signal_to_noise"))
    drawdown = safe_float(latest.get("drawdown"))
    volume_z = safe_float(latest.get("volume_zscore"))
    relative_strength_score = safe_float(latest.get("relative_strength_score"))
    breakout_quality_score = safe_float(latest.get("breakout_quality_score"))
    pullback_quality_score = safe_float(latest.get("pullback_quality_score"))
    exhaustion_risk_score = safe_float(latest.get("exhaustion_risk_score"))
    entry_timing_quality_score = safe_float(latest.get("entry_timing_quality_score"))

    reg_60 = calculate_regression_strength_v2(close, min(60, len(close) - 1))
    reg_120 = calculate_regression_strength_v2(close, min(120, len(close) - 1))

    perf_5 = safe_performance(close, 5)
    perf_20 = safe_performance(close, 20)
    perf_60 = safe_performance(close, 60)

    price_vs_ema20 = latest_price / ema_20 - 1 if latest_price and ema_20 not in [None, 0] else None
    price_vs_sma50 = latest_price / sma_50 - 1 if latest_price and sma_50 not in [None, 0] else None
    price_vs_sma200 = latest_price / sma_200 - 1 if latest_price and sma_200 not in [None, 0] else None

    # Trend score
    trend_score = 50

    for distance in [price_vs_ema20, price_vs_sma50, price_vs_sma200]:
        if distance is None:
            continue
        if distance > 0:
            trend_score += 10
        else:
            trend_score -= 10

    if reg_60.get("annualized_slope") is not None:
        trend_score += clamp(reg_60["annualized_slope"] * 25, -15, 15)

    if reg_120.get("r2") is not None:
        trend_score += clamp(reg_120["r2"] * 15, 0, 15)

    trend_score = clamp(trend_score)

    # Momentum score
    momentum_score = 50

    for perf, weight in [(perf_5, 120), (perf_20, 180), (perf_60, 120)]:
        if perf is None:
            continue
        momentum_score += clamp(perf * weight, -18, 18)

    if rsi is not None:
        if 52 <= rsi <= 68:
            momentum_score += 10
        elif 45 <= rsi < 52:
            momentum_score += 3
        elif rsi > 75:
            momentum_score -= 8
        elif rsi < 40:
            momentum_score -= 10

    if macd_hist is not None:
        momentum_score += 6 if macd_hist > 0 else -6

    momentum_score = clamp(momentum_score)

    # Noise risk score : plus haut = plus de bruit
    noise_risk = 35

    if vol_20 is not None:
        if vol_20 > 0.80:
            noise_risk += 30
        elif vol_20 > 0.55:
            noise_risk += 20
        elif vol_20 > 0.35:
            noise_risk += 10
        elif vol_20 < 0.22:
            noise_risk -= 5

    if noise_20 is not None:
        if noise_20 > 0.08:
            noise_risk += 25
        elif noise_20 > 0.05:
            noise_risk += 15
        elif noise_20 > 0.03:
            noise_risk += 8

    if signal_to_noise is not None:
        if signal_to_noise >= 0.35:
            noise_risk -= 10
        elif signal_to_noise < 0.12:
            noise_risk += 10

    noise_risk = clamp(noise_risk)

    # Timing score : plus haut = meilleur timing
    timing_score = 60

    if price_vs_ema20 is not None and atr_pct not in [None, 0]:
        extension_atr = price_vs_ema20 / atr_pct

        if -0.5 <= extension_atr <= 1.5:
            timing_score += 15
        elif 1.5 < extension_atr <= 2.5:
            timing_score += 3
        elif extension_atr > 2.5:
            timing_score -= 18
        elif extension_atr < -1.5:
            timing_score -= 10

    if rsi is not None:
        if rsi > 72:
            timing_score -= 15
        elif rsi < 35:
            timing_score -= 10
        elif 48 <= rsi <= 65:
            timing_score += 8

    if drawdown is not None:
        if drawdown > -0.05:
            timing_score += 5
        elif drawdown < -0.20:
            timing_score -= 12

    timing_score = clamp(timing_score)

    composite_score = clamp(
        0.35 * trend_score
        + 0.25 * momentum_score
        + 0.20 * timing_score
        + 0.20 * (100 - noise_risk)
    )

    # Ajustement prudent avec les nouveaux signaux avancés.
    # On ne remplace pas le score principal : on l'affine légèrement.
    if relative_strength_score is not None:
        composite_score += clamp((relative_strength_score - 50) * 0.08, -4, 4)

    if breakout_quality_score is not None and breakout_quality_score >= 75:
        composite_score += 2

    if exhaustion_risk_score is not None:
        if exhaustion_risk_score >= 75:
            composite_score -= 6
            timing_score = clamp(timing_score - 8)
        elif exhaustion_risk_score >= 65:
            composite_score -= 3
            timing_score = clamp(timing_score - 4)

    if entry_timing_quality_score is not None:
        composite_score += clamp((entry_timing_quality_score - 50) * 0.06, -3, 3)

    composite_score = clamp(composite_score)

    status = execution_status_v2(
        composite=composite_score,
        trend_score=trend_score,
        momentum_score=momentum_score,
        noise_risk=noise_risk,
        timing_score=timing_score,
        relative_strength_score=relative_strength_score,
        breakout_quality_score=breakout_quality_score,
        pullback_quality_score=pullback_quality_score,
        exhaustion_risk_score=exhaustion_risk_score,
        entry_timing_quality_score=entry_timing_quality_score,
        volume_zscore=volume_z,
    )

    if trend_score >= 75:
        trend_regime = "Trend haussier confirmé"
    elif trend_score >= 60:
        trend_regime = "Trend constructif"
    elif trend_score >= 45:
        trend_regime = "Range / transition"
    elif trend_score >= 30:
        trend_regime = "Fragile"
    else:
        trend_regime = "Dégradé"

    dashboard_rows = [
        {
            "Dimension": "Trend Regime",
            "Lecture": trend_regime,
            "Score": round(trend_score, 1),
            "Détail": f"Prix vs EMA20 {fmt_pct(price_vs_ema20)} · Prix vs SMA50 {fmt_pct(price_vs_sma50)} · Prix vs SMA200 {fmt_pct(price_vs_sma200)}.",
        },
        {
            "Dimension": "Momentum",
            "Lecture": momentum_label_v2(momentum_score),
            "Score": round(momentum_score, 1),
            "Détail": f"Perf 5D {fmt_pct(perf_5)} · Perf 20D {fmt_pct(perf_20)} · Perf 60D {fmt_pct(perf_60)} · RSI {fmt_num(rsi)}.",
        },
        {
            "Dimension": "Noise Risk",
            "Lecture": noise_label_v2(noise_risk),
            "Score": round(noise_risk, 1),
            "Détail": f"Vol 20D {fmt_pct(vol_20)} · Noise residual {fmt_pct(noise_20)} · Signal/noise {fmt_num(signal_to_noise)}.",
        },
        {
            "Dimension": "Timing",
            "Lecture": timing_label_v2(timing_score),
            "Score": round(timing_score, 1),
            "Détail": f"Extension EMA20 {fmt_pct(price_vs_ema20)} · ATR% {fmt_pct(atr_pct)} · Drawdown {fmt_pct(drawdown)}.",
        },
        {
            "Dimension": "Volume Confirmation",
            "Lecture": "Élevé" if volume_z is not None and volume_z >= 1 else "Normal / indispo",
            "Score": round(clamp(50 + (volume_z or 0) * 12), 1) if volume_z is not None else 50,
            "Détail": f"Volume z-score {fmt_num(volume_z)}.",
        },
        {
            "Dimension": "Relative Strength",
            "Lecture": (
                "Surperformance nette" if relative_strength_score is not None and relative_strength_score >= 70
                else "Constructif" if relative_strength_score is not None and relative_strength_score >= 55
                else "Sous-performance" if relative_strength_score is not None and relative_strength_score < 45
                else "Neutre / indispo"
            ),
            "Score": round(relative_strength_score, 1) if relative_strength_score is not None else 50,
            "Détail": (
                f"Score relatif vs SPY/QQQ/SMH {fmt_num(relative_strength_score)}."
            ),
        },
        {
            "Dimension": "Breakout Quality",
            "Lecture": (
                "Cassure de qualité" if breakout_quality_score is not None and breakout_quality_score >= 75
                else "Correct" if breakout_quality_score is not None and breakout_quality_score >= 55
                else "Faible / à confirmer"
            ),
            "Score": round(breakout_quality_score, 1) if breakout_quality_score is not None else 50,
            "Détail": "Combine breakout 20D/60D, volume, clôture dans la bougie, extension ATR et relative strength.",
        },
        {
            "Dimension": "Pullback Quality",
            "Lecture": (
                "Repli exploitable" if pullback_quality_score is not None and pullback_quality_score >= 70
                else "Correct" if pullback_quality_score is not None and pullback_quality_score >= 55
                else "Repli fragile / pas optimal"
            ),
            "Score": round(pullback_quality_score, 1) if pullback_quality_score is not None else 50,
            "Détail": "Mesure si le repli reste sain : drawdown contrôlé, support EMA/SMA, RSI, volume et bruit.",
        },
        {
            "Dimension": "Exhaustion Risk",
            "Lecture": (
                "Risque élevé" if exhaustion_risk_score is not None and exhaustion_risk_score >= 70
                else "À surveiller" if exhaustion_risk_score is not None and exhaustion_risk_score >= 55
                else "Maîtrisé"
            ),
            "Score": round(exhaustion_risk_score, 1) if exhaustion_risk_score is not None else 50,
            "Détail": "Plus le score est élevé, plus le titre est possiblement étendu : RSI, distance EMA20/ATR, BB%B, return z-score, volume.",
        },
    ]

    return {
        "available": True,
        "quote": quote,
        "frame": df,
        "latest": {
            "price": latest_price,
            "previous_close": previous_close,
            "daily_change": daily_change,
            "trend_score": round(trend_score, 1),
            "momentum_score": round(momentum_score, 1),
            "noise_risk": round(noise_risk, 1),
            "timing_score": round(timing_score, 1),
            "composite_score": round(composite_score, 1),
            "trend_regime": trend_regime,
            "execution_status": status,
            "execution_narrative": execution_narrative_v2(status),
            "rsi_14": rsi,
            "macd_hist": macd_hist,
            "atr_pct": atr_pct,
            "vol_20": vol_20,
            "drawdown": drawdown,
            "price_vs_ema20": price_vs_ema20,
            "price_vs_sma50": price_vs_sma50,
            "price_vs_sma200": price_vs_sma200,
            "signal_to_noise": signal_to_noise,
            "volume_zscore": volume_z,
            "relative_strength_score": relative_strength_score,
            "breakout_quality_score": breakout_quality_score,
            "pullback_quality_score": pullback_quality_score,
            "exhaustion_risk_score": exhaustion_risk_score,
            "entry_timing_quality_score": entry_timing_quality_score,
        },
        "dashboard_table": pd.DataFrame(dashboard_rows),
        "multi_timeframe": build_multi_timeframe_table_v2(df),
    }


def momentum_metric_presets_v2() -> dict:
    return {
        "Clean View": [
            "Close",
            "EMA20",
            "SMA50",
            "Trend Component",
        ],
        "Trend View": [
            "Close",
            "EMA20",
            "EMA50",
            "SMA50",
            "SMA200",
            "Trend Component",
            "Trend Slope 20D",
            "52W Position",
            "Distance 52W High",
        ],
        "Noise View": [
            "Close",
            "Trend Component",
            "Noise Bands",
            "Bollinger Bands",
            "ATR Bands",
            "Realized Vol 20D",
            "Noise Residual",
            "Signal / Noise",
            "ATR Regime Z",
            "BB Width Z",
        ],
        "Momentum View": [
            "Close",
            "RSI",
            "MACD Histogram",
            "Return Z-Score 20D",
            "20D Breakout",
            "Drawdown",
            "Volume Z-Score",
            "Volume Ratio 20D",
        ],
        "Setup Quality": [
            "Close",
            "EMA20",
            "Trend Component",
            "Relative Strength Score",
            "RS 20D vs QQQ",
            "RS 60D vs QQQ",
            "RS 20D vs SMH",
            "Breakout Quality",
            "Pullback Quality",
            "Exhaustion Risk",
            "Entry Timing Quality",
            "Close Location",
            "EMA20 Distance ATR",
            "20D Breakout",
            "60D Breakout",
            "Volume Z-Score",
        ],
        "Full Audit": [
            "Close",
            "Candles",
            "EMA10",
            "EMA20",
            "EMA50",
            "SMA50",
            "SMA200",
            "Trend Component",
            "Noise Bands",
            "Bollinger Bands",
            "ATR Bands",
            "RSI",
            "MACD Histogram",
            "Drawdown",
            "Realized Vol 20D",
            "Noise Residual",
            "Signal / Noise",
            "Volume Z-Score",
            "Volume Ratio 20D",
            "Return Z-Score 20D",
            "ATR Regime Z",
            "BB Width Z",
            "EMA20 Distance ATR",
            "52W Position",
            "Distance 52W High",
            "Distance 52W Low",
            "20D Breakout",
            "20D Breakdown",
            "Trend Slope 20D",
            "Relative Strength Score",
            "RS vs SPY",
            "RS 20D vs SPY",
            "RS 60D vs SPY",
            "RS vs QQQ",
            "RS 20D vs QQQ",
            "RS 60D vs QQQ",
            "RS vs SMH",
            "RS 20D vs SMH",
            "RS 60D vs SMH",
            "Breakout Quality",
            "Pullback Quality",
            "Exhaustion Risk",
            "Entry Timing Quality",
            "Close Location",
            "60D Breakout",
            "60D Breakdown",
        ],
    }


def fmt_metric_value_v2(value, unit: str = "number") -> str:
    value = safe_float(value)

    if value is None or pd.isna(value):
        return "N/A"

    if unit == "price":
        return fmt_price(value)

    if unit == "pct":
        return fmt_pct(value)

    if unit == "score":
        return f"{value:.1f}/100"

    if unit == "x":
        return f"{value:.2f}x"

    return f"{value:.2f}"


def fmt_metric_delta_v2(latest, previous, unit: str = "number") -> str:
    latest = safe_float(latest)
    previous = safe_float(previous)

    if latest is None or previous is None or pd.isna(latest) or pd.isna(previous):
        return "N/A"

    if unit == "price":
        if previous == 0:
            return "N/A"
        return fmt_pct(latest / previous - 1)

    if unit == "pct":
        return fmt_pp(latest - previous)

    return f"{latest - previous:+.2f}"


def metric_state_label_v2(label: str, value) -> str:
    value = safe_float(value)

    if value is None or pd.isna(value):
        return "Indisponible"

    label_l = str(label).lower().strip()

    # -----------------------------
    # Scores décisionnels
    # -----------------------------
    if "relative strength score" in label_l:
        if value >= 75:
            return "Surperformance forte"
        if value >= 60:
            return "Surperformance"
        if value >= 45:
            return "Neutre"
        return "Sous-performance"

    if "breakout quality" in label_l:
        if value >= 75:
            return "Cassure robuste"
        if value >= 60:
            return "Cassure correcte"
        if value >= 45:
            return "À confirmer"
        return "Cassure faible"

    if "pullback quality" in label_l:
        if value >= 75:
            return "Repli de qualité"
        if value >= 60:
            return "Repli exploitable"
        if value >= 45:
            return "Repli moyen"
        return "Repli fragile"

    if "exhaustion risk" in label_l:
        if value >= 75:
            return "Risque d'excès élevé"
        if value >= 60:
            return "Extension à surveiller"
        if value >= 40:
            return "Risque modéré"
        return "Risque faible"

    if "entry timing quality" in label_l:
        if value >= 75:
            return "Timing favorable"
        if value >= 60:
            return "Timing correct"
        if value >= 45:
            return "Timing moyen"
        return "Timing fragile"

    # -----------------------------
    # Relative strength détaillée
    # -----------------------------
    if label_l.startswith("rs 20d") or label_l.startswith("rs 60d"):
        if value >= 0.08:
            return "Surperformance forte"
        if value >= 0.03:
            return "Surperformance"
        if value >= -0.03:
            return "Neutre"
        if value >= -0.08:
            return "Sous-performance"
        return "Sous-performance forte"

    if label_l.startswith("rs vs"):
        if value >= 1.08:
            return "Surperformance forte"
        if value >= 1.03:
            return "Surperformance"
        if value >= 0.97:
            return "Neutre"
        if value >= 0.92:
            return "Sous-performance"
        return "Sous-performance forte"

    # -----------------------------
    # Momentum pur
    # -----------------------------
    if "rsi" in label_l:
        if value >= 75:
            return "Surachat"
        if value >= 60:
            return "Momentum fort"
        if value >= 50:
            return "Momentum positif"
        if value >= 40:
            return "Momentum fragile"
        return "Survente / faiblesse"

    if "macd" in label_l:
        if value > 0.5:
            return "Accélération positive"
        if value > 0:
            return "Momentum positif"
        if value > -0.5:
            return "Neutre"
        return "Décélération"

    if "return z-score" in label_l:
        if value >= 2:
            return "Hausse extrême"
        if value >= 1:
            return "Hausse forte"
        if value <= -2:
            return "Baisse extrême"
        if value <= -1:
            return "Baisse forte"
        return "Lecture neutre"

    # -----------------------------
    # Volume
    # -----------------------------
    if "volume z" in label_l:
        if value >= 1.5:
            return "Volume fort"
        if value >= 0.5:
            return "Volume confirmé"
        if value <= -1.0:
            return "Volume faible"
        return "Volume normal"

    if "volume ratio" in label_l:
        if value >= 1.5:
            return "Volume élevé"
        if value >= 1.1:
            return "Volume correct"
        if value <= 0.75:
            return "Volume faible"
        return "Volume normal"

    # -----------------------------
    # Signal / noise
    # -----------------------------
    if "signal / noise" in label_l:
        if value >= 0.35:
            return "Signal propre"
        if value >= 0.18:
            return "Signal exploitable"
        return "Signal bruité"

    if "noise residual" in label_l:
        abs_value = abs(value)
        if abs_value >= 0.08:
            return "Écart élevé au trend"
        if abs_value >= 0.04:
            return "Écart modéré"
        return "Bruit faible"

    if "noise 20d" in label_l or label_l == "noise 20d":
        if value >= 0.08:
            return "Bruit très élevé"
        if value >= 0.05:
            return "Bruit élevé"
        if value >= 0.03:
            return "Bruit modéré"
        return "Bruit faible"

    if "noise upper" in label_l or "noise lower" in label_l:
        return "Bande de bruit"

    # -----------------------------
    # ATR / volatilité
    # -----------------------------
    if "ema20 distance atr" in label_l:
        if value > 2.5:
            return "Très étendu"
        if value > 1.5:
            return "Étendu"
        if value >= -0.5:
            return "Timing acceptable"
        return "Sous EMA20"

    if "atr regime z" in label_l:
        if value >= 1.5:
            return "Régime ATR élevé"
        if value <= -1.0:
            return "Régime ATR faible"
        return "Régime ATR normal"

    if label_l in ["atr upper", "atr lower"]:
        return "Bande ATR"

    if "atr %" in label_l:
        if value >= 0.06:
            return "Volatilité élevée"
        if value >= 0.035:
            return "Volatilité modérée"
        return "Volatilité faible"

    if "realized vol" in label_l:
        if value >= 0.60:
            return "Volatilité élevée"
        if value >= 0.35:
            return "Volatilité modérée"
        return "Volatilité faible"

    # -----------------------------
    # Bollinger
    # -----------------------------
    if "bb width z" in label_l:
        if value >= 1.5:
            return "Expansion forte"
        if value >= 0.75:
            return "Expansion"
        if value <= -1.0:
            return "Compression"
        return "Régime normal"

    if "bb %b" in label_l:
        if value >= 1.0:
            return "Haut de bande"
        if value <= 0:
            return "Bas de bande"
        if value >= 0.75:
            return "Zone haute"
        if value <= 0.25:
            return "Zone basse"
        return "Zone médiane"

    if "bb upper" in label_l or "bb lower" in label_l:
        return "Bande Bollinger"

    # -----------------------------
    # Range / breakout
    # -----------------------------
    if "close location" in label_l:
        if value >= 0.75:
            return "Clôture forte"
        if value >= 0.55:
            return "Clôture correcte"
        if value <= 0.25:
            return "Clôture faible"
        return "Lecture neutre"

    if "52w position" in label_l:
        if value >= 0.85:
            return "Zone haute 52W"
        if value >= 0.60:
            return "Haut de range"
        if value >= 0.35:
            return "Milieu de range"
        return "Bas de range"

    if "distance 52w high" in label_l:
        if value > -0.05:
            return "Près du high"
        if value > -0.15:
            return "Repli raisonnable"
        return "Éloigné du high"

    if "distance 52w low" in label_l:
        if value >= 0.50:
            return "Très au-dessus du low"
        if value >= 0.20:
            return "Au-dessus du low"
        return "Proche du low"

    if "breakout" in label_l:
        if value > 0:
            return "Breakout actif"
        return "Pas de breakout"

    if "breakdown" in label_l:
        if value < 0:
            return "Breakdown actif"
        return "Pas de breakdown"

    # -----------------------------
    # Drawdown / prix / moyennes
    # -----------------------------
    if "drawdown" in label_l:
        if value > -0.05:
            return "Proche des highs"
        if value > -0.12:
            return "Repli modéré"
        if value > -0.25:
            return "Correction"
        return "Drawdown profond"

    if label_l in [
        "close",
        "candles",
        "ema10",
        "ema20",
        "ema50",
        "sma50",
        "sma200",
        "trend component",
    ]:
        return "Lecture neutre"

    if "trend slope" in label_l:
        if value >= 0.25:
            return "Pente forte"
        if value >= 0.05:
            return "Pente positive"
        if value <= -0.10:
            return "Pente négative"
        return "Pente neutre"

    return "Lecture neutre"


def build_momentum_metric_snapshot_table_v2(
    df: pd.DataFrame,
    selected_metrics: list[str],
    only_changed: bool = True,
) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    work = df.copy()

    if "date" in work.columns:
        work["date"] = pd.to_datetime(work["date"], errors="coerce")

    # Séries dérivées pour les groupes de métriques.
    if all(c in work.columns for c in ["trend_component", "noise_20"]):
        work["_noise_upper_v2"] = work["trend_component"] * (1 + 2 * work["noise_20"])
        work["_noise_lower_v2"] = work["trend_component"] * (1 - 2 * work["noise_20"])

    specs = []

    def add(label: str, col: str, unit: str, lecture: str):
        if col in work.columns:
            specs.append({
                "Metric": label,
                "Column": col,
                "Unit": unit,
                "Lecture": lecture,
            })

    # Métriques directes.
    direct_map = {
        "Close": ("close", "price", "Prix de clôture / prix live injecté."),
        "Candles": ("close", "price", "Prix utilisé par les bougies."),
        "EMA10": ("ema_10", "price", "Tendance très courte."),
        "EMA20": ("ema_20", "price", "Support dynamique court terme."),
        "EMA50": ("ema_50", "price", "Tendance intermédiaire."),
        "SMA50": ("sma_50", "price", "Tendance institutionnelle intermédiaire."),
        "SMA200": ("sma_200", "price", "Tendance longue."),
        "Trend Component": ("trend_component", "price", "Composante de tendance lissée."),
        "RSI": ("rsi_14", "number", "Momentum court terme."),
        "MACD Histogram": ("macd_hist", "number", "Accélération / décélération du momentum."),
        "Drawdown": ("drawdown", "pct", "Distance au plus haut historique de la fenêtre."),
        "Realized Vol 20D": ("vol_20", "pct", "Volatilité annualisée 20 jours."),
        "Noise Residual": ("noise_residual", "pct", "Écart du prix à la composante de tendance."),
        "Signal / Noise": ("signal_to_noise", "number", "Qualité directionnelle du mouvement."),
        "Volume Z-Score": ("volume_zscore", "number", "Anomalie de volume vs moyenne 20 jours."),
        "Volume Ratio 20D": ("volume_ratio_20", "x", "Volume actuel rapporté à la moyenne 20 jours."),
        "Return Z-Score 20D": ("return_zscore_20", "number", "Anomalie du rendement quotidien."),
        "ATR Regime Z": ("atr_pct_zscore", "number", "Régime d'ATR vs historique récent."),
        "BB Width Z": ("bb_width_zscore", "number", "Compression / expansion des bandes de Bollinger."),
        "BB %B": ("bb_percent_b", "number", "Position du prix dans les bandes de Bollinger."),
        "EMA20 Distance ATR": ("ema20_distance_atr", "x", "Distance à l'EMA20 exprimée en ATR."),
        "52W Position": ("position_52w", "pct", "Position du prix dans le range 52 semaines."),
        "Distance 52W High": ("distance_high_52w", "pct", "Distance au plus haut 52 semaines."),
        "Distance 52W Low": ("distance_low_52w", "pct", "Distance au plus bas 52 semaines."),
        "20D Breakout": ("breakout_20", "pct", "Cassure au-dessus du plus haut 20 jours précédent."),
        "20D Breakdown": ("breakdown_20", "pct", "Cassure sous le plus bas 20 jours précédent."),
        "Trend Slope 20D": ("trend_slope_20_annualized", "pct", "Pente annualisée de la composante trend sur 20 jours."),
        "Relative Strength Score": ("relative_strength_score", "score", "Score de sur/sous-performance vs SPY, QQQ et SMH."),
        "RS vs SPY": ("rs_spy", "x", "Ratio relatif normalisé vs SPY."),
        "RS 20D vs SPY": ("rs_spy_20d", "pct", "Surperformance 20 jours vs SPY."),
        "RS 60D vs SPY": ("rs_spy_60d", "pct", "Surperformance 60 jours vs SPY."),
        "RS vs QQQ": ("rs_qqq", "x", "Ratio relatif normalisé vs QQQ."),
        "RS 20D vs QQQ": ("rs_qqq_20d", "pct", "Surperformance 20 jours vs QQQ."),
        "RS 60D vs QQQ": ("rs_qqq_60d", "pct", "Surperformance 60 jours vs QQQ."),
        "RS vs SMH": ("rs_smh", "x", "Ratio relatif normalisé vs SMH."),
        "RS 20D vs SMH": ("rs_smh_20d", "pct", "Surperformance 20 jours vs SMH."),
        "RS 60D vs SMH": ("rs_smh_60d", "pct", "Surperformance 60 jours vs SMH."),
        "Breakout Quality": ("breakout_quality_score", "score", "Qualité mécanique de cassure."),
        "Pullback Quality": ("pullback_quality_score", "score", "Qualité mécanique du repli."),
        "Exhaustion Risk": ("exhaustion_risk_score", "score", "Risque mécanique d'extension excessive."),
        "Entry Timing Quality": ("entry_timing_quality_score", "score", "Qualité mécanique du timing d'entrée."),
        "Close Location": ("close_location", "pct", "Position de clôture dans la bougie."),
        "60D Breakout": ("breakout_60", "pct", "Cassure au-dessus du plus haut 60 jours précédent."),
        "60D Breakdown": ("breakdown_60", "pct", "Cassure sous le plus bas 60 jours précédent."),
    }

    for metric in selected_metrics:
        if metric in direct_map:
            col, unit, lecture = direct_map[metric]
            add(metric, col, unit, lecture)

    # Groupes visuels : on les décompose dans le tableau.
    if "Noise Bands" in selected_metrics:
        add("Noise Upper", "_noise_upper_v2", "price", "Bande haute de bruit autour du trend.")
        add("Noise Lower", "_noise_lower_v2", "price", "Bande basse de bruit autour du trend.")
        add("Noise Residual", "noise_residual", "pct", "Écart du prix à la composante de tendance.")
        add("Noise 20D", "noise_20", "pct", "Écart-type du bruit sur 20 jours.")

    if "Bollinger Bands" in selected_metrics:
        add("BB Upper", "bb_upper", "price", "Bande de Bollinger haute.")
        add("BB Lower", "bb_lower", "price", "Bande de Bollinger basse.")
        add("BB %B", "bb_percent_b", "number", "Position du prix dans les bandes.")
        add("BB Width Z", "bb_width_zscore", "number", "Expansion / compression des bandes.")

    if "ATR Bands" in selected_metrics:
        add("ATR Upper", "atr_upper", "price", "Bande haute basée sur ATR.")
        add("ATR Lower", "atr_lower", "price", "Bande basse basée sur ATR.")
        add("ATR %", "atr_pct", "pct", "ATR rapporté au prix.")
        add("ATR Regime Z", "atr_pct_zscore", "number", "Régime d'ATR vs historique.")

    # Déduplication en gardant l'ordre.
    deduped = []
    seen = set()

    for spec in specs:
        key = (spec["Metric"], spec["Column"])

        if key in seen:
            continue

        seen.add(key)
        deduped.append(spec)

    rows = []

    for spec in deduped:
        col = spec["Column"]

        valid = work[["date", col]].copy() if "date" in work.columns else work[[col]].copy()
        valid[col] = pd.to_numeric(valid[col], errors="coerce")
        valid = valid.dropna(subset=[col])

        if valid.empty:
            continue

        latest_row = valid.iloc[-1]
        latest_value = safe_float(latest_row.get(col))

        previous_value = None
        value_5d = None

        if len(valid) >= 2:
            previous_value = safe_float(valid.iloc[-2].get(col))

        if len(valid) >= 6:
            value_5d = safe_float(valid.iloc[-6].get(col))

        changed = True

        if previous_value is not None and latest_value is not None:
            changed = not np.isclose(latest_value, previous_value, rtol=0.0001, atol=0.0001)

        if only_changed and not changed:
            continue

        rows.append({
            "Metric": spec["Metric"],
            "Dernière valeur": fmt_metric_value_v2(latest_value, spec["Unit"]),
            "Veille": fmt_metric_value_v2(previous_value, spec["Unit"]),
            "Δ 1j": fmt_metric_delta_v2(latest_value, previous_value, spec["Unit"]),
            "Δ 5j": fmt_metric_delta_v2(latest_value, value_5d, spec["Unit"]),
            "Régime": metric_state_label_v2(spec["Metric"], latest_value),
            "Lecture": spec["Lecture"],
        })

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows)


def render_momentum_metric_snapshot_table_v2(
    df: pd.DataFrame,
    selected_metrics: list[str],
    title: str = "Snapshot des métriques sélectionnées",
    only_changed: bool = True,
):
    snapshot = build_momentum_metric_snapshot_table_v2(
        df=df,
        selected_metrics=selected_metrics,
        only_changed=only_changed,
    )

    if snapshot.empty:
        st.caption("Aucune variation significative détectée sur les métriques sélectionnées.")
        return

    st.subheader(title)

    st.dataframe(
        snapshot,
        use_container_width=True,
        hide_index=True
    )


def chart_metrics_for_preset_v2(preset_name: str, selected_metrics: list[str]) -> list[str]:
    """
    Limite volontairement les métriques affichées sur le graphe.
    Le tableau garde toutes les métriques sélectionnées.
    Objectif : éviter les graphes illisibles avec 15-40 séries.
    """

    selected = list(selected_metrics or [])

    chart_policy = {
        "Clean View": [
            "Close",
            "EMA20",
            "SMA50",
            "Trend Component",
        ],
        "Trend View": [
            "Close",
            "EMA20",
            "EMA50",
            "SMA50",
            "SMA200",
            "Trend Component",
        ],
        "Noise View": [
            "Close",
            "Trend Component",
            "Noise Bands",
            "Bollinger Bands",
            "ATR Bands",
            "Noise Residual",
            "Signal / Noise",
        ],
        "Momentum View": [
            "Close",
            "RSI",
            "MACD Histogram",
            "Return Z-Score 20D",
            "Volume Z-Score",
        ],
        "Setup Quality": [
            "Close",
            "EMA20",
            "Trend Component",
            "EMA20 Distance ATR",
            "20D Breakout",
            "Volume Z-Score",
        ],
        "Full Audit": [
            "Close",
            "Candles",
            "EMA20",
            "EMA50",
            "SMA50",
            "SMA200",
            "Trend Component",
            "Noise Bands",
            "Bollinger Bands",
            "ATR Bands",
        ],
    }

    preferred = chart_policy.get(preset_name, selected)
    chart_selected = [m for m in preferred if m in selected]

    if not chart_selected:
        chart_selected = selected[:8]

    return chart_selected


def render_setup_quality_scorecard_v2(df: pd.DataFrame, selected_metrics: list[str]):
    """
    Scorecard compacte pour les scores /100.
    Ces métriques sont souvent illisibles sur le graphe mais très utiles en tableau.
    """

    if df is None or df.empty:
        return

    score_specs = [
        ("Relative Strength Score", "relative_strength_score", "Score relatif vs SPY/QQQ/SMH."),
        ("Breakout Quality", "breakout_quality_score", "Qualité mécanique de cassure."),
        ("Pullback Quality", "pullback_quality_score", "Qualité mécanique du repli."),
        ("Exhaustion Risk", "exhaustion_risk_score", "Risque d'extension excessive."),
        ("Entry Timing Quality", "entry_timing_quality_score", "Qualité mécanique du timing d'entrée."),
    ]

    selected_set = set(selected_metrics or [])

    active_specs = [
        spec for spec in score_specs
        if spec[0] in selected_set and spec[1] in df.columns
    ]

    if not active_specs:
        return

    rows = []

    for label, col, lecture in active_specs:
        valid = df[[col]].copy()
        valid[col] = pd.to_numeric(valid[col], errors="coerce")
        valid = valid.dropna(subset=[col])

        if valid.empty:
            continue

        latest = safe_float(valid.iloc[-1][col])
        previous = safe_float(valid.iloc[-2][col]) if len(valid) >= 2 else None
        value_5d = safe_float(valid.iloc[-6][col]) if len(valid) >= 6 else None

        rows.append({
            "Score": label,
            "Dernière valeur": fmt_metric_value_v2(latest, "score"),
            "Veille": fmt_metric_value_v2(previous, "score"),
            "Δ 1j": fmt_metric_delta_v2(latest, previous, "number"),
            "Δ 5j": fmt_metric_delta_v2(latest, value_5d, "number"),
            "Régime": metric_state_label_v2(label, latest),
            "Lecture": lecture,
        })

    if not rows:
        return

    st.subheader("Scorecard setup — signaux décisionnels")

    st.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True
    )


def build_momentum_data_quality_table_v2(mt: dict) -> pd.DataFrame:
    """
    Diagnostic compact de couverture data pour Momentum / Trend.
    Ne modifie aucun score. Sert uniquement à expliquer les métriques disponibles.
    """
    if not isinstance(mt, dict):
        return pd.DataFrame()

    df = mt.get("frame", pd.DataFrame())
    latest = mt.get("latest", {})
    quote = mt.get("quote", {})

    rows = []

    def add(component: str, status: str, detail: str):
        rows.append({
            "Bloc": component,
            "Statut": status,
            "Détail": detail,
        })

    if df is None or df.empty:
        add("Historique prix", "KO", "Frame prix vide.")
        return pd.DataFrame(rows)

    rows_count = len(df)

    add(
        "Historique prix",
        "OK" if rows_count >= 200 else "Partiel",
        f"{rows_count} lignes disponibles."
    )

    quote_source = quote.get("source", "Historical close")
    live_price = safe_float(latest.get("price"))

    add(
        "Prix live",
        "OK" if quote_source != "Historical close" and live_price is not None else "Fallback",
        f"Source utilisée : {quote_source}."
    )

    required_ohlc = ["open", "high", "low", "close"]

    missing_ohlc = [
        col for col in required_ohlc
        if col not in df.columns or df[col].dropna().empty
    ]

    add(
        "OHLC",
        "OK" if not missing_ohlc else "Partiel",
        "Colonnes OHLC complètes." if not missing_ohlc else f"Manquant : {', '.join(missing_ohlc)}."
    )

    if "volume" in df.columns and not df["volume"].dropna().empty:
        add("Volume", "OK", "Volume disponible : volume z-score et volume ratio utilisables.")
    else:
        add("Volume", "Indisponible", "Volume absent : certains signaux de confirmation seront neutres.")

    rs_cols = [
        "relative_strength_score",
        "rs_spy",
        "rs_qqq",
        "rs_smh",
    ]

    available_rs = [
        col for col in rs_cols
        if col in df.columns and not df[col].dropna().empty
    ]

    add(
        "Relative Strength",
        "OK" if len(available_rs) >= 2 else "Partiel",
        f"{len(available_rs)}/{len(rs_cols)} colonnes RS disponibles."
    )

    setup_cols = [
        "breakout_quality_score",
        "pullback_quality_score",
        "exhaustion_risk_score",
        "entry_timing_quality_score",
    ]

    available_setup = [
        col for col in setup_cols
        if col in df.columns and not df[col].dropna().empty
    ]

    add(
        "Setup Quality",
        "OK" if len(available_setup) == len(setup_cols) else "Partiel",
        f"{len(available_setup)}/{len(setup_cols)} scores setup disponibles."
    )

    noise_cols = [
        "trend_component",
        "noise_residual",
        "noise_20",
        "signal_to_noise",
    ]

    available_noise = [
        col for col in noise_cols
        if col in df.columns and not df[col].dropna().empty
    ]

    add(
        "Trend / Noise",
        "OK" if len(available_noise) == len(noise_cols) else "Partiel",
        f"{len(available_noise)}/{len(noise_cols)} métriques trend/noise disponibles."
    )

    return pd.DataFrame(rows)


def render_momentum_data_quality_v2(mt: dict):
    quality_df = build_momentum_data_quality_table_v2(mt)

    if quality_df.empty:
        return

    with st.expander("Data quality / couverture des signaux", expanded=False):
        st.dataframe(
            quality_df,
            use_container_width=True,
            hide_index=True
        )


def render_momentum_metric_explorer_v2(ticker: str, mt: dict):
    df = mt.get("frame", pd.DataFrame())

    if df.empty:
        st.info("Données prix indisponibles.")
        return

    st.subheader("Explorateur — prix, trend, bruit et timing")

    metric_options = [
        "Close",
        "Candles",
        "EMA10",
        "EMA20",
        "EMA50",
        "SMA50",
        "SMA200",
        "Trend Component",
        "Noise Bands",
        "Bollinger Bands",
        "ATR Bands",
        "RSI",
        "MACD Histogram",
        "Drawdown",
        "Realized Vol 20D",
        "Noise Residual",
        "Signal / Noise",
        "Volume Z-Score",
        "Volume Ratio 20D",
        "Return Z-Score 20D",
        "ATR Regime Z",
        "BB %B",
        "BB Width Z",
        "EMA20 Distance ATR",
        "52W Position",
        "Distance 52W High",
        "Distance 52W Low",
        "20D Breakout",
        "20D Breakdown",
        "Relative Strength Score",
        "RS vs SPY",
        "RS 20D vs SPY",
        "RS 60D vs SPY",
        "RS vs QQQ",
        "RS 20D vs QQQ",
        "RS 60D vs QQQ",
        "RS vs SMH",
        "RS 20D vs SMH",
        "RS 60D vs SMH",
        "Breakout Quality",
        "Pullback Quality",
        "Exhaustion Risk",
        "Entry Timing Quality",
        "Close Location",
        "60D Breakout",
        "60D Breakdown",
        "Trend Slope 20D",
    ]

    presets = momentum_metric_presets_v2()

    preset_name = st.selectbox(
        "Preset d'analyse",
        list(presets.keys()),
        index=0,
        key=f"momentum_metric_preset_v2_{ticker}"
    )

    selected = st.multiselect(
        "Métriques affichées",
        metric_options,
        default=[m for m in presets[preset_name] if m in metric_options],
        key=f"momentum_metric_selector_v2_{ticker}_{preset_name}"
    )

    only_changed_metrics = st.checkbox(
        "Afficher seulement les métriques qui ont changé",
        value=True,
        key=f"momentum_metric_only_changed_v2_{ticker}"
    )

    chart_selected = list(selected)

    table_selected = list(selected)
    chart_selected = chart_metrics_for_preset_v2(preset_name, table_selected)

    hidden_from_chart = [m for m in table_selected if m not in chart_selected]

    if hidden_from_chart:
        st.caption(
            f"Graphique limité à {len(chart_selected)} métrique(s) lisibles. "
            f"{len(hidden_from_chart)} métrique(s) restent disponibles dans le tableau."
        )

    fig = go.Figure()

    price_like = {
        "Close", "Candles", "EMA10", "EMA20", "EMA50", "SMA50", "SMA200",
        "Trend Component", "Noise Bands", "Bollinger Bands", "ATR Bands"
    }

    if "Candles" in chart_selected and all(c in df.columns for c in ["open", "high", "low", "close"]):
        fig.add_trace(go.Candlestick(
            x=df["date"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name=ticker
        ))

    if "Close" in chart_selected:
        fig.add_trace(go.Scatter(x=df["date"], y=df["close"], mode="lines", name="Close"))

    line_map = {
        "EMA10": "ema_10",
        "EMA20": "ema_20",
        "EMA50": "ema_50",
        "SMA50": "sma_50",
        "SMA200": "sma_200",
        "Trend Component": "trend_component",
    }

    for label, col in line_map.items():
        if label in chart_selected and col in df.columns:
            fig.add_trace(go.Scatter(x=df["date"], y=df[col], mode="lines", name=label))

    if "Noise Bands" in chart_selected:
        upper = df["trend_component"] * (1 + 2 * df["noise_20"])
        lower = df["trend_component"] * (1 - 2 * df["noise_20"])
        fig.add_trace(go.Scatter(x=df["date"], y=upper, mode="lines", name="Noise upper"))
        fig.add_trace(go.Scatter(x=df["date"], y=lower, mode="lines", name="Noise lower"))

    if "Bollinger Bands" in chart_selected:
        fig.add_trace(go.Scatter(x=df["date"], y=df["bb_upper"], mode="lines", name="BB upper"))
        fig.add_trace(go.Scatter(x=df["date"], y=df["bb_lower"], mode="lines", name="BB lower"))

    if "ATR Bands" in chart_selected:
        fig.add_trace(go.Scatter(x=df["date"], y=df["atr_upper"], mode="lines", name="ATR upper"))
        fig.add_trace(go.Scatter(x=df["date"], y=df["atr_lower"], mode="lines", name="ATR lower"))

    secondary_series = {
        "RSI": ("rsi_14", "RSI"),
        "MACD Histogram": ("macd_hist", "MACD Hist"),
        "Drawdown": ("drawdown", "Drawdown"),
        "Realized Vol 20D": ("vol_20", "Vol 20D"),
        "Noise Residual": ("noise_residual", "Noise Residual"),
        "Signal / Noise": ("signal_to_noise", "Signal / Noise"),
        "Volume Z-Score": ("volume_zscore", "Volume Z"),
        "Volume Ratio 20D": ("volume_ratio_20", "Volume Ratio"),
        "Return Z-Score 20D": ("return_zscore_20", "Return Z"),
        "ATR Regime Z": ("atr_pct_zscore", "ATR Regime Z"),
        "BB %B": ("bb_percent_b", "BB %B"),
        "BB Width Z": ("bb_width_zscore", "BB Width Z"),
        "EMA20 Distance ATR": ("ema20_distance_atr", "EMA20 Distance ATR"),
        "52W Position": ("position_52w", "52W Position"),
        "Distance 52W High": ("distance_high_52w", "Distance 52W High"),
        "Distance 52W Low": ("distance_low_52w", "Distance 52W Low"),
        "20D Breakout": ("breakout_20", "20D Breakout"),
        "20D Breakdown": ("breakdown_20", "20D Breakdown"),
        "Relative Strength Score": ("relative_strength_score", "Relative Strength"),
        "RS vs SPY": ("rs_spy", "RS vs SPY"),
        "RS 20D vs SPY": ("rs_spy_20d", "RS 20D vs SPY"),
        "RS 60D vs SPY": ("rs_spy_60d", "RS 60D vs SPY"),
        "RS vs QQQ": ("rs_qqq", "RS vs QQQ"),
        "RS 20D vs QQQ": ("rs_qqq_20d", "RS 20D vs QQQ"),
        "RS 60D vs QQQ": ("rs_qqq_60d", "RS 60D vs QQQ"),
        "RS vs SMH": ("rs_smh", "RS vs SMH"),
        "RS 20D vs SMH": ("rs_smh_20d", "RS 20D vs SMH"),
        "RS 60D vs SMH": ("rs_smh_60d", "RS 60D vs SMH"),
        "Breakout Quality": ("breakout_quality_score", "Breakout Quality"),
        "Pullback Quality": ("pullback_quality_score", "Pullback Quality"),
        "Exhaustion Risk": ("exhaustion_risk_score", "Exhaustion Risk"),
        "Entry Timing Quality": ("entry_timing_quality_score", "Entry Timing"),
        "Close Location": ("close_location", "Close Location"),
        "60D Breakout": ("breakout_60", "60D Breakout"),
        "60D Breakdown": ("breakdown_60", "60D Breakdown"),
        "Trend Slope 20D": ("trend_slope_20_annualized", "Trend Slope 20D"),
    }

    secondary_selected = [m for m in chart_selected if m in secondary_series]

    for label in secondary_selected:
        col, display = secondary_series[label]
        if col not in df.columns:
            continue

        fig.add_trace(go.Scatter(
            x=df["date"],
            y=df[col],
            mode="lines",
            name=display,
            yaxis="y2"
        ))

    fig.update_layout(
        height=620,
        title=f"Momentum / Trend Explorer — {ticker}",
        xaxis_title="Date",
        yaxis_title="Prix",
        yaxis2=dict(
            title="Indicateurs secondaires",
            overlaying="y",
            side="right",
            showgrid=False
        ) if secondary_selected else None,
        hovermode="x unified",
        margin=dict(l=20, r=20, t=70, b=40),
    )

    fig.update_xaxes(rangeslider_visible=False)

    st.plotly_chart(fig, use_container_width=True)

    render_setup_quality_scorecard_v2(
        df=df,
        selected_metrics=table_selected,
    )

    render_momentum_metric_snapshot_table_v2(
        df=df,
        selected_metrics=table_selected,
        title="Tableau des métriques sélectionnées — valeurs et variations",
        only_changed=only_changed_metrics,
    )


def render_momentum_trend_center_v2(ticker: str, price_data: pd.DataFrame, analysis: dict):
    st.subheader(f"Momentum / Trend Intelligence Center — {ticker}")

    mt = analysis.get("momentum_v2") if isinstance(analysis, dict) else None

    required_advanced_cols = [
        "relative_strength_score",
        "breakout_quality_score",
        "pullback_quality_score",
        "exhaustion_risk_score",
        "entry_timing_quality_score",
    ]

    frame = mt.get("frame", pd.DataFrame()) if isinstance(mt, dict) else pd.DataFrame()

    needs_rebuild = (
        not isinstance(mt, dict)
        or not mt.get("available")
        or frame.empty
        or any(col not in frame.columns for col in required_advanced_cols)
    )

    if needs_rebuild:
        mt = build_momentum_trend_intelligence_v2(ticker, price_data)

    if not mt.get("available"):
        st.warning(mt.get("reason", "Momentum V2 indisponible."))
        return

    latest = mt.get("latest", {})
    quote = mt.get("quote", {})

    c1, c2, c3, c4, c5, c6 = st.columns(6)

    c1.metric(
        "Prix live",
        fmt_price(latest.get("price")),
        delta=fmt_pct(latest.get("daily_change"))
    )
    c2.metric("Setup Score", f"{latest.get('composite_score', 0):.0f}/100")
    c3.metric("Trend", f"{latest.get('trend_score', 0):.0f}/100")
    c4.metric("Momentum", f"{latest.get('momentum_score', 0):.0f}/100")
    c5.metric("Noise Risk", f"{latest.get('noise_risk', 0):.0f}/100")
    c6.metric("Timing", f"{latest.get('timing_score', 0):.0f}/100")

    status = latest.get("execution_status", "N/A")
    narrative = latest.get("execution_narrative", "")

    success_statuses = [
        "BREAKOUT_BUY_ZONE",
        "PULLBACK_BUY_ZONE",
    ]

    warning_statuses = [
        "BREAKOUT_NOISY",
        "BREAKOUT_WEAK_VOLUME",
        "PULLBACK_OK_BUT_EXTENDED",
        "TREND_HOLD",
        "EXTENDED_WAIT",
        "EXHAUSTED_WAIT",
        "RANGE_NOISE",
        "CONSTRUCTIVE_WAIT",
        "PULLBACK_HIGH_NOISE",
    ]

    if status in success_statuses:
        st.success(f"{status} — {narrative}")
    elif status in warning_statuses:
        st.warning(f"{status} — {narrative}")
    else:
        st.info(f"{status} — {narrative}")

    st.caption(
        f"Source prix : {quote.get('source', 'Historical close')} · "
        f"Prix vs EMA20 {fmt_pct(latest.get('price_vs_ema20'))} · "
        f"ATR% {fmt_pct(latest.get('atr_pct'))} · "
        f"Vol 20D {fmt_pct(latest.get('vol_20'))} · "
        f"Signal/noise {fmt_num(latest.get('signal_to_noise'))}"
    )

    render_momentum_data_quality_v2(mt)

    momentum_view = st.radio(
        "Vue Momentum / Trend",
        ["Executive Tape", "Metric Explorer", "Trend / Noise Separation", "Multi-Timeframe", "Raw Audit"],
        horizontal=True,
        key=f"momentum_view_v2_{ticker}"
    )

    if momentum_view == "Executive Tape":
        st.subheader("Lecture décisionnelle")

        st.dataframe(
            mt.get("dashboard_table", pd.DataFrame()),
            use_container_width=True,
            hide_index=True
        )

        executive_snapshot_metrics = [
            "Close",
            "EMA20",
            "SMA50",
            "SMA200",
            "RSI",
            "MACD Histogram",
            "Drawdown",
            "Realized Vol 20D",
            "Signal / Noise",
            "Volume Z-Score",
            "EMA20 Distance ATR",
            "52W Position",
            "20D Breakout",
            "Relative Strength Score",
            "Breakout Quality",
            "Pullback Quality",
            "Exhaustion Risk",
            "Entry Timing Quality",
        ]

        render_momentum_metric_snapshot_table_v2(
            df=mt.get("frame", pd.DataFrame()),
            selected_metrics=executive_snapshot_metrics,
            title="Snapshot exécutif — métriques clés",
            only_changed=False,
        )

    elif momentum_view == "Metric Explorer":
        render_momentum_metric_explorer_v2(ticker, mt)

    elif momentum_view == "Trend / Noise Separation":
        df = mt.get("frame", pd.DataFrame())

        if df.empty:
            st.info("Données indisponibles.")
        else:
            fig = go.Figure()

            fig.add_trace(go.Scatter(
                x=df["date"],
                y=df["close"],
                mode="lines",
                name="Prix"
            ))

            fig.add_trace(go.Scatter(
                x=df["date"],
                y=df["trend_component"],
                mode="lines",
                name="Trend component"
            ))

            upper = df["trend_component"] * (1 + 2 * df["noise_20"])
            lower = df["trend_component"] * (1 - 2 * df["noise_20"])

            fig.add_trace(go.Scatter(
                x=df["date"],
                y=upper,
                mode="lines",
                name="Bande bruit haute"
            ))

            fig.add_trace(go.Scatter(
                x=df["date"],
                y=lower,
                mode="lines",
                name="Bande bruit basse"
            ))

            fig.update_layout(
                height=560,
                title=f"Trend / Noise Separation — {ticker}",
                xaxis_title="Date",
                yaxis_title="Prix",
                hovermode="x unified",
                margin=dict(l=20, r=20, t=70, b=40)
            )

            st.plotly_chart(fig, use_container_width=True)

            noise_df = df[[
                "date", "close", "trend_component", "noise_residual",
                "noise_20", "signal_to_noise", "vol_20", "atr_pct"
            ]].tail(30).copy()

            noise_df["date"] = pd.to_datetime(noise_df["date"], errors="coerce").dt.strftime("%Y-%m-%d")

            for col in ["noise_residual", "noise_20", "vol_20", "atr_pct"]:
                noise_df[col] = noise_df[col].apply(fmt_pct)

            noise_df["signal_to_noise"] = noise_df["signal_to_noise"].apply(fmt_num)

            st.dataframe(noise_df, use_container_width=True, hide_index=True)

    elif momentum_view == "Multi-Timeframe":
        mtf = mt.get("multi_timeframe", pd.DataFrame())

        if mtf.empty:
            st.info("Historique insuffisant pour le multi-timeframe.")
        else:
            display = mtf.copy()

            for col in ["Performance", "Trend slope annualisée", "R² trend", "Vol réalisée"]:
                if col in display.columns:
                    if col == "R² trend":
                        display[col] = display[col].apply(fmt_num)
                    else:
                        display[col] = display[col].apply(fmt_pct)

            st.dataframe(display, use_container_width=True, hide_index=True)

            chart_df = mtf.copy()
            fig = go.Figure()

            fig.add_trace(go.Bar(
                x=chart_df["Horizon"],
                y=chart_df["Score"],
                text=chart_df["Score"],
                textposition="auto",
                name="MTF Score"
            ))

            fig.add_hline(y=50, line_dash="dot", annotation_text="Neutre")
            fig.add_hline(y=70, line_dash="dash", annotation_text="Trend fort")

            fig.update_layout(
                height=420,
                title="Multi-Timeframe Trend Score",
                xaxis_title="Horizon",
                yaxis_title="Score",
                yaxis=dict(range=[0, 100]),
                margin=dict(l=20, r=20, t=70, b=40)
            )

            st.plotly_chart(fig, use_container_width=True)

    elif momentum_view == "Raw Audit":
        df = mt.get("frame", pd.DataFrame()).copy()

        if df.empty:
            st.info("Données indisponibles.")
        else:
            keep_cols = [
                "date", "open", "high", "low", "close", "volume",
                "ema_10", "ema_20", "ema_50", "sma_50", "sma_200",
                "rsi_14", "macd", "macd_signal", "macd_hist",
                "atr_14", "atr_pct", "atr_pct_zscore",
                "vol_20", "vol_60",
                "trend_component", "trend_slope_20_annualized",
                "noise_residual", "noise_20", "signal_to_noise",
                "bb_percent_b", "bb_width", "bb_width_zscore",
                "ema20_distance_atr",
                "drawdown",
                "volume_zscore", "volume_ratio_20",
                "return_zscore_20",
                "position_52w", "distance_high_52w", "distance_low_52w",
                "breakout_20", "breakdown_20",
                "relative_strength_score",
                "rs_spy", "rs_spy_20d", "rs_spy_60d", "rs_spy_slope_20",
                "rs_qqq", "rs_qqq_20d", "rs_qqq_60d", "rs_qqq_slope_20",
                "rs_smh", "rs_smh_20d", "rs_smh_60d", "rs_smh_slope_20",
                "close_location",
                "breakout_60", "breakdown_60",
                "breakout_quality_score",
                "pullback_quality_score",
                "exhaustion_risk_score",
                "entry_timing_quality_score",
            ]

            keep_cols = [c for c in keep_cols if c in df.columns]

            raw = df[keep_cols].tail(80).copy()
            raw["date"] = pd.to_datetime(raw["date"], errors="coerce").dt.strftime("%Y-%m-%d")

            st.dataframe(raw, use_container_width=True, hide_index=True)




# ============================================================
# ============================================================
# MONTE CARLO HELPERS
# ============================================================

def get_monte_carlo_assumptions(
    drift: float,
    volatility: float,
    scenario: str
) -> tuple[float, float, str]:
    if scenario == "Historique":
        return drift, volatility, "Drift historique et volatilité historique."

    if scenario == "Conservateur":
        return drift * 0.50, volatility, "Drift historique réduit de 50 %, volatilité inchangée."

    if scenario == "Neutre":
        return 0.0, volatility, "Drift neutralisé à 0 %, volatilité historique conservée."

    if scenario == "Stress volatilité":
        return drift * 0.50, volatility * 1.25, "Drift réduit de 50 % et volatilité augmentée de 25 %."

    return drift, volatility, "Hypothèse historique par défaut."


def monte_carlo_simulation(
    start_price: float,
    drift: float,
    volatility: float,
    days: int = 30,
    simulations: int = 1000
) -> np.ndarray:
    dt = 1 / 252

    paths = np.zeros((days, simulations))
    paths[0] = start_price

    for t in range(1, days):
        random_shocks = np.random.normal(0, 1, simulations)

        paths[t] = paths[t - 1] * np.exp(
            (drift - 0.5 * volatility ** 2) * dt
            + volatility * np.sqrt(dt) * random_shocks
        )

    return paths


def calculate_mc_quality_score(row: pd.Series) -> int:
    prob_positive = row["Prob finir positif"]
    prob_loss_5 = row["Prob perte > 5%"]
    prob_stop = row["Prob toucher stop court"]
    prob_target = row["Prob toucher Target 1"]
    expected_return = row["Expected Return"]

    asymmetry = prob_target - prob_stop

    score = 50
    score += asymmetry * 130
    score += expected_return * 180
    score += (prob_positive - 0.50) * 60
    score -= max(0, prob_stop - 0.35) * 90
    score -= prob_loss_5 * 45

    return int(max(0, min(100, round(score))))


def calculate_monte_carlo_advanced_metrics(
    price: float,
    drift: float,
    volatility: float,
    plan: dict,
    horizons=(7, 30, 90),
    simulations: int = 1000
) -> tuple[pd.DataFrame, dict]:
    rows = []
    paths_by_horizon = {}

    for horizon in horizons:
        paths = monte_carlo_simulation(
            start_price=price,
            drift=drift,
            volatility=volatility,
            days=horizon,
            simulations=simulations
        )

        paths_by_horizon[horizon] = paths

        final_prices = paths[-1, :]
        min_prices = paths.min(axis=0)
        max_prices = paths.max(axis=0)
        returns = final_prices / price - 1

        row = {
            "Horizon": f"{horizon}D",
            "P5": float(np.percentile(final_prices, 5)),
            "P25": float(np.percentile(final_prices, 25)),
            "P50": float(np.percentile(final_prices, 50)),
            "P75": float(np.percentile(final_prices, 75)),
            "P95": float(np.percentile(final_prices, 95)),
            "Prob finir positif": float(np.mean(final_prices > price)),
            "Prob perte > 5%": float(np.mean(returns <= -0.05)),
            "Prob toucher stop court": float(np.mean(min_prices <= plan["stop_short"])),
            "Prob toucher stop structurel": float(np.mean(min_prices <= plan["stop_structural"])),
            "Prob toucher Target 1": float(np.mean(max_prices >= plan["target_1"])),
            "Prob toucher Target 2": float(np.mean(max_prices >= plan["target_2"])),
            "Expected Return": float(np.mean(returns)),
            "Median Return": float(np.median(returns)),
        }

        row["Asymétrie T1/Stop"] = row["Prob toucher Target 1"] - row["Prob toucher stop court"]
        row["MC Score"] = calculate_mc_quality_score(pd.Series(row))

        rows.append(row)

    return pd.DataFrame(rows), paths_by_horizon


def rebuild_monte_carlo(
    analysis: dict,
    simulations: int,
    scenario: str
) -> dict:
    effective_drift, effective_volatility, mc_assumption_text = get_monte_carlo_assumptions(
        drift=analysis["drift"],
        volatility=analysis["volatility"],
        scenario=scenario
    )

    mc_paths = monte_carlo_simulation(
        start_price=analysis["latest_price"],
        drift=effective_drift,
        volatility=effective_volatility,
        days=30,
        simulations=simulations
    )

    mc_summary = {
        "p05": float(np.percentile(mc_paths[-1], 5)),
        "p25": float(np.percentile(mc_paths[-1], 25)),
        "p50": float(np.percentile(mc_paths[-1], 50)),
        "p75": float(np.percentile(mc_paths[-1], 75)),
        "p95": float(np.percentile(mc_paths[-1], 95)),
    }

    mc_advanced_table, mc_advanced_paths = calculate_monte_carlo_advanced_metrics(
        price=analysis["latest_price"],
        drift=effective_drift,
        volatility=effective_volatility,
        plan=analysis["trading_plan"],
        horizons=(7, 30, 90),
        simulations=simulations
    )

    analysis["effective_drift"] = effective_drift
    analysis["effective_volatility"] = effective_volatility
    analysis["mc_scenario"] = scenario
    analysis["mc_assumption_text"] = mc_assumption_text
    analysis["mc_simulations"] = simulations
    analysis["monte_carlo"] = mc_summary
    analysis["monte_carlo_paths"] = mc_paths
    analysis["mc_advanced_table"] = mc_advanced_table
    analysis["mc_advanced_paths"] = mc_advanced_paths

    return analysis


def compute_path_percentiles(paths: np.ndarray) -> dict:
    return {
        "p05": np.percentile(paths, 5, axis=1),
        "p50": np.percentile(paths, 50, axis=1),
        "p95": np.percentile(paths, 95, axis=1),
    }


def build_scenario_comparison(
    analysis: dict,
    horizon: int,
    simulations: int = 1000
) -> pd.DataFrame:
    scenarios = ["Historique", "Conservateur", "Neutre", "Stress volatilité"]
    rows = []

    for scenario in scenarios:
        effective_drift, effective_volatility, _ = get_monte_carlo_assumptions(
            drift=analysis["drift"],
            volatility=analysis["volatility"],
            scenario=scenario
        )

        mc_table, _ = calculate_monte_carlo_advanced_metrics(
            price=analysis["latest_price"],
            drift=effective_drift,
            volatility=effective_volatility,
            plan=analysis["trading_plan"],
            horizons=(horizon,),
            simulations=simulations
        )

        row = mc_table.iloc[0]

        rows.append({
            "Scénario": scenario,
            "Drift utilisé": effective_drift,
            "Volatilité utilisée": effective_volatility,
            "Prob. positif": row["Prob finir positif"],
            "Prob. stop court": row["Prob toucher stop court"],
            "Prob. Target 1": row["Prob toucher Target 1"],
            "Asymétrie T1/Stop": row["Asymétrie T1/Stop"],
            "Espérance": row["Expected Return"],
            "MC Score": row["MC Score"],
            "P5": row["P5"],
            "P50": row["P50"],
            "P95": row["P95"],
        })

    return pd.DataFrame(rows)


# ============================================================
# SIGNAL / PLAN
# ============================================================

def generate_signal(
    momentum: float,
    volatility: float,
    risk_reward: float,
    max_drawdown: float
):
    score = 0

    if momentum > 0.05:
        score += 30
    elif momentum > 0:
        score += 15
    else:
        score -= 10

    if volatility < 0.35:
        score += 20
    elif volatility < 0.60:
        score += 5
    else:
        score -= 15

    if risk_reward >= 2:
        score += 25
    elif risk_reward >= 1.5:
        score += 10
    else:
        score -= 10

    if max_drawdown > -0.20:
        score += 15
    elif max_drawdown > -0.35:
        score += 5
    else:
        score -= 10

    if score >= 60:
        signal = "BUY_ZONE"
    elif score >= 30:
        signal = "WATCH"
    elif score >= 0:
        signal = "NEUTRAL"
    else:
        signal = "AVOID"

    return score, signal


def calculate_basic_trade_levels(
    price: float,
    volatility: float,
    momentum: float
) -> dict:
    daily_vol = volatility / np.sqrt(252)

    if momentum > 0:
        entry_price = price * 0.98
        stop_loss = price * (1 - 2.5 * daily_vol)
        take_profit = price * (1 + 5 * daily_vol)
    else:
        entry_price = price * 0.95
        stop_loss = price * (1 - 2.0 * daily_vol)
        take_profit = price * (1 + 3.0 * daily_vol)

    downside = entry_price - stop_loss
    upside = take_profit - entry_price

    risk_reward = upside / downside if downside > 0 else 0

    return {
        "entry_price": float(entry_price),
        "stop_loss": float(stop_loss),
        "take_profit": float(take_profit),
        "risk_reward": float(risk_reward)
    }


def calculate_trading_plan(
    price: float,
    atr: float,
    momentum: float,
    volatility: float
) -> dict:
    if atr <= 0:
        atr = price * 0.02

    if momentum > 0:
        entry_aggressive = price - 0.50 * atr
        entry_prudent = price - 1.00 * atr
        stop_short = price - 1.50 * atr
        stop_structural = price - 2.50 * atr
        target_1 = price + 1.50 * atr
        target_2 = price + 3.00 * atr
    else:
        entry_aggressive = price - 0.75 * atr
        entry_prudent = price - 1.50 * atr
        stop_short = price - 2.00 * atr
        stop_structural = price - 3.00 * atr
        target_1 = price + 1.25 * atr
        target_2 = price + 2.50 * atr

    rr_aggressive = (
        (target_2 - entry_aggressive) / (entry_aggressive - stop_short)
        if entry_aggressive > stop_short else 0
    )

    rr_prudent = (
        (target_2 - entry_prudent) / (entry_prudent - stop_structural)
        if entry_prudent > stop_structural else 0
    )

    if volatility > 0.60:
        risk_regime = "Risque élevé"
    elif volatility > 0.35:
        risk_regime = "Risque modéré"
    else:
        risk_regime = "Risque contenu"

    return {
        "entry_aggressive": float(entry_aggressive),
        "entry_prudent": float(entry_prudent),
        "stop_short": float(stop_short),
        "stop_structural": float(stop_structural),
        "target_1": float(target_1),
        "target_2": float(target_2),
        "rr_aggressive": float(rr_aggressive),
        "rr_prudent": float(rr_prudent),
        "risk_regime": risk_regime
    }


def generate_commentary(
    signal: str,
    momentum: float,
    volatility: float,
    max_drawdown: float,
    risk_reward: float
) -> str:
    comments = []

    if signal == "BUY_ZONE":
        comments.append("Le modèle détecte une configuration quantitative favorable.")
    elif signal == "WATCH":
        comments.append("Le titre mérite surveillance, mais le signal n'est pas encore pleinement confirmé.")
    elif signal == "NEUTRAL":
        comments.append("Le signal est neutre : le modèle ne détecte pas d'avantage clair.")
    else:
        comments.append("Le modèle recommande d'éviter pour l'instant selon les critères quantitatifs.")

    if momentum > 0.05:
        comments.append("Le momentum récent est positif.")
    elif momentum > 0:
        comments.append("Le momentum est légèrement positif.")
    else:
        comments.append("Le momentum est faible ou négatif.")

    if volatility > 0.60:
        comments.append("La volatilité est très élevée : la taille de position devrait être réduite.")
    elif volatility > 0.35:
        comments.append("La volatilité est significative : le risque doit être surveillé.")
    else:
        comments.append("La volatilité est relativement contenue.")

    if max_drawdown < -0.35:
        comments.append("Le drawdown historique est important, ce qui signale un risque structurel élevé.")
    elif max_drawdown < -0.20:
        comments.append("Le drawdown est notable, mais pas extrême.")
    else:
        comments.append("Le drawdown reste relativement modéré.")

    if risk_reward >= 2:
        comments.append("Le ratio risk/reward est attractif selon les niveaux théoriques.")
    elif risk_reward >= 1.5:
        comments.append("Le ratio risk/reward est acceptable mais pas exceptionnel.")
    else:
        comments.append("Le ratio risk/reward est faible.")

    return " ".join(comments)


def generate_mc_verdict(row: pd.Series) -> dict:
    prob_positive = row["Prob finir positif"]
    prob_stop = row["Prob toucher stop court"]
    prob_target = row["Prob toucher Target 1"]
    expected_return = row["Expected Return"]
    mc_score = row["MC Score"]

    if expected_return < 0 or prob_target <= prob_stop:
        return {
            "label": "Défavorable",
            "status": "error",
            "message": (
                "Rendement espéré négatif ou probabilité de toucher le stop court supérieure "
                "ou égale à celle d'atteindre Target 1."
            )
        }

    if mc_score >= 75:
        return {
            "label": "Strong favorable",
            "status": "success",
            "message": (
                "Asymétrie positive nette, rendement espéré solide et probabilité de stop contenue."
            )
        }

    if prob_target > prob_stop and expected_return > 0 and 0.35 <= prob_stop <= 0.50:
        return {
            "label": "Favorable mais risqué",
            "status": "warning",
            "message": (
                "Target 1 reste plus probable que le stop court, mais la probabilité de toucher "
                "le stop reste élevée."
            )
        }

    if prob_target > prob_stop and expected_return > 0 and prob_positive >= 0.55:
        return {
            "label": "Favorable",
            "status": "success",
            "message": (
                "La probabilité d'atteindre Target 1 est supérieure à celle de toucher le stop court, "
                "avec un rendement espéré positif."
            )
        }

    return {
        "label": "Fragile",
        "status": "warning",
        "message": (
            "Rendement espéré positif mais avantage statistique faible ou insuffisamment asymétrique."
        )
    }


def generate_scenario_commentary(analysis: dict, verdict: dict) -> str:
    scenario = analysis["mc_scenario"]

    if scenario == "Neutre" and verdict["label"] in ["Défavorable", "Fragile"]:
        return (
            "Lecture importante : le scénario neutre retire l'effet de tendance historique. "
            "Si le verdict devient fragile ou défavorable ici, cela signifie que le trade dépend fortement "
            "de la continuation du momentum."
        )

    if scenario == "Historique":
        return (
            "Attention : le scénario historique prolonge le drift récent. Il peut devenir trop optimiste "
            "sur les titres ayant fortement monté."
        )

    if scenario == "Stress volatilité":
        return (
            "Le scénario stress augmente la volatilité et réduit le drift. Il sert à tester la robustesse "
            "du plan face à une dégradation de régime."
        )

    if scenario == "Conservateur":
        return (
            "Le scénario conservateur réduit le drift historique de moitié. C'est généralement un compromis "
            "entre extrapolation de tendance et prudence."
        )

    return ""


# ============================================================
# DECISION ENGINE
# ============================================================

def calculate_distance_metrics(analysis: dict) -> dict:
    price = analysis["latest_price"]
    plan = analysis["trading_plan"]

    stop_short_distance = plan["stop_short"] / price - 1
    stop_structural_distance = plan["stop_structural"] / price - 1
    target_1_distance = plan["target_1"] / price - 1
    target_2_distance = plan["target_2"] / price - 1

    rr_to_target_1 = (
        abs(target_1_distance) / abs(stop_short_distance)
        if stop_short_distance != 0 else 0
    )

    rr_to_target_2 = (
        abs(target_2_distance) / abs(stop_short_distance)
        if stop_short_distance != 0 else 0
    )

    return {
        "stop_short_distance": float(stop_short_distance),
        "stop_structural_distance": float(stop_structural_distance),
        "target_1_distance": float(target_1_distance),
        "target_2_distance": float(target_2_distance),
        "rr_to_target_1": float(rr_to_target_1),
        "rr_to_target_2": float(rr_to_target_2),
    }


def generate_final_decision(analysis: dict, mc_row: pd.Series) -> dict:
    quant_score = analysis["global_score"]
    trend_score = analysis["trend_score"]
    mc_score = mc_row["MC Score"]

    company_analysis = analysis.get("company_analysis", {})
    company_scores = company_analysis.get("scores", {})
    company_score = company_scores.get("company_score", 50)
    valuation_score = company_scores.get("valuation_score", 50)
    analyst_score = company_scores.get("analyst_score", 50)

    volatility = analysis["volatility"]
    max_drawdown = analysis["max_drawdown"]
    prob_stop = mc_row["Prob toucher stop court"]
    prob_target = mc_row["Prob toucher Target 1"]
    expected_return = mc_row["Expected Return"]

    composite_score = (
        0.25 * quant_score
        + 0.20 * trend_score
        + 0.30 * mc_score
        + 0.15 * company_score
        + 0.10 * analyst_score
    )

    if volatility > 0.60:
        composite_score -= 8

    if prob_stop > 0.50:
        composite_score -= 8

    if max_drawdown < -0.35:
        composite_score -= 6

    if expected_return < 0:
        composite_score -= 10

    if valuation_score < 35:
        composite_score -= 4

    composite_score = int(max(0, min(100, round(composite_score))))

    quality_pullback = company_score >= 70 and trend_score >= 70 and valuation_score < 45

    if composite_score >= 75 and mc_score >= 70 and prob_stop < 0.40 and valuation_score >= 45:
        label = "BUY_CONFIRMED"
        status = "success"
        sizing = "Taille normale théorique"
        action = "Setup quantitatif confirmé. Le profil momentum, tendance, Monte Carlo et entreprise est cohérent."
    elif quality_pullback and composite_score >= 65 and prob_target > prob_stop:
        label = "BUY_QUALITY_PULLBACK"
        status = "warning"
        sizing = "Taille réduite / entrée sur repli"
        action = "Entreprise solide et tendance favorable, mais valorisation exigeante ou risque de stop élevé : privilégier un pullback."
    elif composite_score >= 60 and prob_target > prob_stop and expected_return > 0:
        label = "BUY_RISKY"
        status = "warning"
        sizing = "Taille réduite"
        action = "Setup intéressant mais risqué. L'entrée doit rester prudente et le stop doit être respecté."
    elif composite_score >= 45:
        label = "WATCH"
        status = "warning"
        sizing = "Très petite taille ou attente"
        action = "Avantage statistique incomplet. Meilleur usage : surveillance ou attente d'un meilleur prix."
    elif company_score < 35:
        label = "FUNDAMENTAL_WEAKNESS"
        status = "error"
        sizing = "Éviter ou spéculatif uniquement"
        action = "Profil entreprise fragile : le signal technique ne suffit pas à valider un setup robuste."
    elif composite_score >= 30:
        label = "DEFENSIVE_WAIT"
        status = "error"
        sizing = "Pas d'entrée immédiate"
        action = "Profil défensif. Le risque domine ou le signal n'est pas assez confirmé."
    else:
        label = "AVOID"
        status = "error"
        sizing = "Éviter"
        action = "Configuration trop fragile selon le moteur quantitatif."

    return {
        "label": label,
        "status": status,
        "sizing": sizing,
        "action": action,
        "composite_score": composite_score,
        "quant_score": quant_score,
        "trend_score": trend_score,
        "mc_score": mc_score,
        "company_score": company_score,
        "valuation_score": valuation_score,
        "analyst_score": analyst_score,
    }


def generate_decision_explanation(analysis: dict, mc_row: pd.Series, decision: dict) -> str:
    parts = []

    if analysis["signal"] == "BUY_ZONE":
        parts.append("Le score quantitatif brut est favorable.")
    elif analysis["signal"] == "WATCH":
        parts.append("Le score quantitatif brut est surveillable mais pas pleinement confirmé.")
    else:
        parts.append("Le score quantitatif brut n'est pas suffisamment favorable.")

    if analysis["trend_score"] >= 70:
        parts.append("La tendance technique soutient clairement le scénario.")
    elif analysis["trend_score"] >= 45:
        parts.append("La tendance est correcte mais pas dominante.")
    else:
        parts.append("La tendance est fragile ou insuffisamment confirmée.")

    if mc_row["MC Score"] >= 70:
        parts.append("Le Monte Carlo confirme une asymétrie favorable.")
    elif mc_row["MC Score"] >= 50:
        parts.append("Le Monte Carlo reste exploitable mais le risque de stop est significatif.")
    else:
        parts.append("Le Monte Carlo ne valide pas suffisamment le setup.")

    company_analysis = analysis.get("company_analysis", {})
    company_scores = company_analysis.get("scores", {})

    if company_scores:
        company_score = company_scores.get("company_score", 50)
        valuation_score = company_scores.get("valuation_score", 50)

        if company_score >= 75:
            parts.append("La qualité entreprise renforce le dossier.")
        elif company_score >= 55:
            parts.append("Le profil entreprise est correct mais pas décisif.")
        else:
            parts.append("Le profil entreprise ne renforce pas suffisamment le signal.")

        if valuation_score < 45:
            parts.append("La valorisation est exigeante : le moteur préfère une entrée sur repli.")

    if mc_row["Prob toucher stop court"] >= 0.45:
        parts.append("La probabilité de toucher le stop court impose une taille de position prudente.")

    if decision["label"] in ["BUY_RISKY", "BUY_QUALITY_PULLBACK"]:
        parts.append("Le signal reste classé risqué car le potentiel est présent mais la probabilité de stop ou la valorisation reste contraignante.")

    return " ".join(parts)


def calculate_entry_zone(analysis: dict, decision: dict) -> dict:
    price = analysis["latest_price"]
    atr = analysis["atr"]
    plan = analysis["trading_plan"]

    if decision["label"] == "BUY_CONFIRMED":
        zone_low = price - 0.65 * atr
        zone_high = price - 0.15 * atr
        zone_type = "Zone active"
        message = "Le setup est confirmé : une entrée proche du prix actuel reste acceptable, avec contrôle du risque."
    elif decision["label"] in ["BUY_RISKY", "BUY_QUALITY_PULLBACK"]:
        zone_low = plan["entry_prudent"]
        zone_high = plan["entry_aggressive"]
        zone_type = "Zone prudente"
        message = "Le setup est exploitable mais risqué : l'entrée prudente est préférable pour améliorer le ratio risque/rendement."
    elif decision["label"] == "WATCH":
        zone_low = price - 1.50 * atr
        zone_high = price - 0.75 * atr
        zone_type = "Zone d'attente"
        message = "Le setup manque de confirmation : attendre un repli plus marqué ou une amélioration du Monte Carlo."
    else:
        zone_low = price - 2.00 * atr
        zone_high = price - 1.25 * atr
        zone_type = "Pas de zone exploitable"
        message = "Le moteur ne valide pas d'entrée immédiate. La zone affichée sert uniquement de repère théorique."

    if zone_low > zone_high:
        zone_low, zone_high = zone_high, zone_low

    if price > zone_high:
        distance_to_zone = zone_high / price - 1
        price_position = "Au-dessus de la zone"
    elif price < zone_low:
        distance_to_zone = zone_low / price - 1
        price_position = "Sous la zone"
    else:
        distance_to_zone = 0.0
        price_position = "Dans la zone"

    return {
        "zone_low": float(zone_low),
        "zone_high": float(zone_high),
        "zone_type": zone_type,
        "message": message,
        "distance_to_zone": float(distance_to_zone),
        "price_position": price_position
    }


def get_buy_confirmed_conditions(decision: dict, mc_row: pd.Series) -> pd.DataFrame:
    rows = [
        {
            "Critère": "Score composite",
            "Actuel": decision["composite_score"],
            "Seuil BUY_CONFIRMED": "≥ 75",
            "Statut": "OK" if decision["composite_score"] >= 75 else "À améliorer",
            "Action": "Conserver" if decision["composite_score"] >= 75 else "Améliorer MC Score, fondamentaux ou réduire risque"
        },
        {
            "Critère": "MC Score",
            "Actuel": decision["mc_score"],
            "Seuil BUY_CONFIRMED": "≥ 70",
            "Statut": "OK" if decision["mc_score"] >= 70 else "À améliorer",
            "Action": "Conserver" if decision["mc_score"] >= 70 else "Attendre meilleur prix ou meilleure asymétrie"
        },
        {
            "Critère": "Probabilité stop court",
            "Actuel": f"{mc_row['Prob toucher stop court']:.2%}",
            "Seuil BUY_CONFIRMED": "< 40%",
            "Statut": "OK" if mc_row["Prob toucher stop court"] < 0.40 else "À réduire",
            "Action": "Conserver" if mc_row["Prob toucher stop court"] < 0.40 else "Attendre pullback / élargir invalidation / réduire taille"
        },
        {
            "Critère": "Company Score",
            "Actuel": decision.get("company_score", 50),
            "Seuil BUY_CONFIRMED": "≥ 60 souhaitable",
            "Statut": "OK" if decision.get("company_score", 50) >= 60 else "À améliorer",
            "Action": "Conserver" if decision.get("company_score", 50) >= 60 else "Fondamentaux insuffisants"
        },
        {
            "Critère": "Valuation Score",
            "Actuel": decision.get("valuation_score", 50),
            "Seuil BUY_CONFIRMED": "≥ 45 souhaitable",
            "Statut": "OK" if decision.get("valuation_score", 50) >= 45 else "Valorisation tendue",
            "Action": "Conserver" if decision.get("valuation_score", 50) >= 45 else "Privilégier pullback"
        },
        {
            "Critère": "Espérance Monte Carlo",
            "Actuel": f"{mc_row['Expected Return']:.2%}",
            "Seuil BUY_CONFIRMED": "> 0%",
            "Statut": "OK" if mc_row["Expected Return"] > 0 else "Négatif",
            "Action": "Conserver" if mc_row["Expected Return"] > 0 else "Ne pas exécuter tant que l'espérance reste négative"
        },
        {
            "Critère": "Asymétrie Target 1 / Stop",
            "Actuel": f"{mc_row['Asymétrie T1/Stop'] * 100:.2f} pts",
            "Seuil BUY_CONFIRMED": "> 0 pt",
            "Statut": "OK" if mc_row["Asymétrie T1/Stop"] > 0 else "Insuffisant",
            "Action": "Conserver" if mc_row["Asymétrie T1/Stop"] > 0 else "Attendre amélioration Target/Stop"
        },
        {
            "Critère": "Trend Score",
            "Actuel": decision["trend_score"],
            "Seuil BUY_CONFIRMED": "≥ 60 souhaitable",
            "Statut": "OK" if decision["trend_score"] >= 60 else "À améliorer",
            "Action": "Conserver" if decision["trend_score"] >= 60 else "Attendre confirmation tendance"
        },
    ]

    return pd.DataFrame(rows)


def get_action_matrix(decision: dict, distances: dict, mc_row: pd.Series, entry_zone: dict) -> pd.DataFrame:
    rows = [
        {
            "Bloc": "Signal final",
            "Lecture": decision["label"],
            "Interprétation": decision["action"]
        },
        {
            "Bloc": "Sizing mécanique",
            "Lecture": decision["sizing"],
            "Interprétation": "Ajustement théorique selon risque Monte Carlo, score composite et probabilité de stop."
        },
        {
            "Bloc": "Zone d'entrée",
            "Lecture": entry_zone["zone_type"],
            "Interprétation": entry_zone["message"]
        },
        {
            "Bloc": "Position du prix",
            "Lecture": entry_zone["price_position"],
            "Interprétation": "Permet de savoir s'il faut exécuter maintenant ou attendre un pullback."
        },
        {
            "Bloc": "Distance stop court",
            "Lecture": f"{distances['stop_short_distance']:.2%}",
            "Interprétation": "Distance entre prix actuel et invalidation court terme."
        },
        {
            "Bloc": "Distance Target 1",
            "Lecture": f"{distances['target_1_distance']:.2%}",
            "Interprétation": "Premier objectif théorique du plan."
        },
        {
            "Bloc": "Asymétrie MC",
            "Lecture": f"{(mc_row['Asymétrie T1/Stop'] * 100):.2f} pts",
            "Interprétation": "Écart entre probabilité Target 1 et probabilité stop court."
        },
        {
            "Bloc": "Espérance MC",
            "Lecture": f"{mc_row['Expected Return']:.2%}",
            "Interprétation": "Rendement moyen simulé sur l'horizon sélectionné."
        },
    ]

    return pd.DataFrame(rows)


def get_execution_checklist(decision: dict, mc_row: pd.Series, entry_zone: dict, analysis: dict) -> pd.DataFrame:
    price = analysis["latest_price"]

    price_ok = entry_zone["zone_low"] <= price <= entry_zone["zone_high"]
    stop_ok = mc_row["Prob toucher stop court"] < 0.45
    mc_ok = mc_row["MC Score"] >= 60
    expected_ok = mc_row["Expected Return"] > 0
    signal_ok = decision["label"] in ["BUY_CONFIRMED", "BUY_RISKY", "BUY_QUALITY_PULLBACK"]

    rows = [
        {
            "Étape": "1. Signal",
            "Condition": "Signal final exploitable",
            "Lecture actuelle": decision["label"],
            "Statut": "OK" if signal_ok else "Attendre",
            "Action": "Continuer le process" if signal_ok else "Ne pas exécuter"
        },
        {
            "Étape": "2. Prix",
            "Condition": "Prix dans ou proche de la zone d'entrée",
            "Lecture actuelle": (
                f"Prix {price:.2f} | Zone {entry_zone['zone_low']:.2f} → {entry_zone['zone_high']:.2f}"
            ),
            "Statut": "OK" if price_ok else "Attendre pullback",
            "Action": "Exécution possible" if price_ok else "Ne pas acheter au marché ; attendre retour dans la zone"
        },
        {
            "Étape": "3. Monte Carlo",
            "Condition": "MC Score ≥ 60 souhaitable",
            "Lecture actuelle": f"{mc_row['MC Score']}/100",
            "Statut": "OK" if mc_ok else "Fragile",
            "Action": "Valider avec prudence" if mc_ok else "Attendre amélioration du profil simulé"
        },
        {
            "Étape": "4. Stop",
            "Condition": "Probabilité stop court < 45% souhaitable",
            "Lecture actuelle": f"{mc_row['Prob toucher stop court']:.2%}",
            "Statut": "OK" if stop_ok else "Risque élevé",
            "Action": "Risque acceptable" if stop_ok else "Réduire taille ou attendre un meilleur point d'entrée"
        },
        {
            "Étape": "5. Entreprise",
            "Condition": "Company Score ≥ 55 souhaitable",
            "Lecture actuelle": f"{decision.get('company_score', 50)}/100",
            "Statut": "OK" if decision.get("company_score", 50) >= 55 else "Fragile",
            "Action": "Conserver" if decision.get("company_score", 50) >= 55 else "Ne pas renforcer sans amélioration fondamentale"
        },
        {
            "Étape": "6. Espérance",
            "Condition": "Espérance Monte Carlo positive",
            "Lecture actuelle": f"{mc_row['Expected Return']:.2%}",
            "Statut": "OK" if expected_ok else "Négatif",
            "Action": "Conserver" if expected_ok else "Ne pas exécuter"
        },
    ]

    return pd.DataFrame(rows)


def get_invalidation_revalidation_table(decision: dict, mc_row: pd.Series, analysis: dict) -> pd.DataFrame:
    plan = analysis["trading_plan"]

    rows = [
        {
            "Bloc": "Invalidation rapide",
            "Niveau / condition": f"Clôture sous stop court : {plan['stop_short']:.2f}",
            "Lecture": "Le setup court terme est invalidé."
        },
        {
            "Bloc": "Invalidation structurelle",
            "Niveau / condition": f"Clôture sous stop structurel : {plan['stop_structural']:.2f}",
            "Lecture": "Le scénario quantitatif devient trop dégradé."
        },
        {
            "Bloc": "Invalidation statistique",
            "Niveau / condition": "MC Score < 50 ou espérance MC négative",
            "Lecture": "Le moteur ne valide plus l'asymétrie."
        },
        {
            "Bloc": "Invalidation fondamentale",
            "Niveau / condition": "Company Score < 45 ou forte dégradation croissance / marges",
            "Lecture": "Le support entreprise devient insuffisant pour renforcer le signal."
        },
        {
            "Bloc": "Revalidation",
            "Niveau / condition": "MC Score > 65, stop court < 45%, prix dans la zone d'entrée",
            "Lecture": "Le setup redevient exploitable avec meilleur contrôle du risque."
        },
        {
            "Bloc": "Passage BUY_CONFIRMED",
            "Niveau / condition": "Score composite ≥ 75, MC Score ≥ 70, stop court < 40%, valorisation non excessive",
            "Lecture": "Le setup passe d'intéressant mais risqué à confirmé."
        },
    ]

    return pd.DataFrame(rows)


def get_final_mechanical_plan(decision: dict, entry_zone: dict, mc_row: pd.Series, analysis: dict) -> pd.DataFrame:
    plan = analysis["trading_plan"]

    if decision["label"] in ["BUY_CONFIRMED", "BUY_RISKY", "BUY_QUALITY_PULLBACK"]:
        action = "Entrée autorisée sous conditions"
    elif decision["label"] == "WATCH":
        action = "Surveillance active"
    else:
        action = "Pas d'entrée immédiate"

    rows = [
        {
            "Élément": "Action",
            "Valeur": action,
            "Lecture": decision["action"]
        },
        {
            "Élément": "Zone d'entrée optimale",
            "Valeur": f"{entry_zone['zone_low']:.2f} → {entry_zone['zone_high']:.2f}",
            "Lecture": entry_zone["message"]
        },
        {
            "Élément": "Position du prix",
            "Valeur": entry_zone["price_position"],
            "Lecture": "Indique si le prix actuel permet une exécution immédiate ou nécessite attente."
        },
        {
            "Élément": "Stop court terme",
            "Valeur": f"{plan['stop_short']:.2f}",
            "Lecture": "Niveau d'invalidation rapide."
        },
        {
            "Élément": "Stop structurel",
            "Valeur": f"{plan['stop_structural']:.2f}",
            "Lecture": "Niveau d'invalidation large."
        },
        {
            "Élément": "Target 1",
            "Valeur": f"{plan['target_1']:.2f}",
            "Lecture": "Objectif intermédiaire principal."
        },
        {
            "Élément": "Target 2",
            "Valeur": f"{plan['target_2']:.2f}",
            "Lecture": "Objectif étendu."
        },
        {
            "Élément": "Sizing",
            "Valeur": decision["sizing"],
            "Lecture": "Taille théorique liée au risque simulé."
        },
        {
            "Élément": "Probabilité stop court",
            "Valeur": f"{mc_row['Prob toucher stop court']:.2%}",
            "Lecture": "Probabilité simulée de toucher l'invalidation courte."
        },
        {
            "Élément": "Probabilité Target 1",
            "Valeur": f"{mc_row['Prob toucher Target 1']:.2%}",
            "Lecture": "Probabilité simulée d'atteindre le premier objectif."
        },
    ]

    return pd.DataFrame(rows)


def get_theoretical_order_table(
    decision: dict,
    entry_zone: dict,
    mc_row: pd.Series,
    analysis: dict
) -> pd.DataFrame:
    plan = analysis["trading_plan"]
    price = analysis["latest_price"]

    if decision["label"] == "BUY_CONFIRMED":
        order_type = "Limit ou fractionné"
        trigger = "Entrée proche zone active"
    elif decision["label"] in ["BUY_RISKY", "BUY_QUALITY_PULLBACK"]:
        order_type = "Limit uniquement"
        trigger = "Attendre retour dans zone prudente"
    elif decision["label"] == "WATCH":
        order_type = "Aucun ordre immédiat"
        trigger = "Attendre revalidation"
    else:
        order_type = "Aucun ordre"
        trigger = "Setup non exploitable"

    if price > entry_zone["zone_high"]:
        execution_state = "Attente pullback"
    elif price < entry_zone["zone_low"]:
        execution_state = "Sous zone : attendre stabilisation"
    else:
        execution_state = "Prix dans zone"

    rows = [
        {
            "Champ": "Type d'ordre théorique",
            "Valeur": order_type,
            "Lecture": trigger
        },
        {
            "Champ": "État d'exécution",
            "Valeur": execution_state,
            "Lecture": "Indique si le prix permet une action mécanique immédiate."
        },
        {
            "Champ": "Zone limite basse",
            "Valeur": f"{entry_zone['zone_low']:.2f}",
            "Lecture": "Bas de la zone d'entrée."
        },
        {
            "Champ": "Zone limite haute",
            "Valeur": f"{entry_zone['zone_high']:.2f}",
            "Lecture": "Haut de la zone d'entrée."
        },
        {
            "Champ": "Stop court terme",
            "Valeur": f"{plan['stop_short']:.2f}",
            "Lecture": "Invalidation rapide."
        },
        {
            "Champ": "Stop structurel",
            "Valeur": f"{plan['stop_structural']:.2f}",
            "Lecture": "Invalidation large."
        },
        {
            "Champ": "Target 1",
            "Valeur": f"{plan['target_1']:.2f}",
            "Lecture": "Premier objectif."
        },
        {
            "Champ": "Target 2",
            "Valeur": f"{plan['target_2']:.2f}",
            "Lecture": "Objectif étendu."
        },
        {
            "Champ": "Sizing mécanique",
            "Valeur": decision["sizing"],
            "Lecture": "Taille théorique, pas une recommandation personnalisée."
        },
        {
            "Champ": "Condition de renforcement",
            "Valeur": "MC Score ≥ 70 et stop court < 40%",
            "Lecture": "Conditions minimales pour passage vers BUY_CONFIRMED."
        },
    ]

    return pd.DataFrame(rows)


def build_decision_export(
    ticker: str,
    horizon_label: str,
    decision: dict,
    entry_zone: dict,
    mc_row: pd.Series,
    analysis: dict
) -> pd.DataFrame:
    plan = analysis["trading_plan"]

    rows = [
        {"Champ": "Ticker", "Valeur": ticker},
        {"Champ": "Horizon", "Valeur": horizon_label},
        {"Champ": "Prix actuel", "Valeur": round(analysis["latest_price"], 2)},
        {"Champ": "Signal brut", "Valeur": analysis["signal"]},
        {"Champ": "Signal final", "Valeur": decision["label"]},
        {"Champ": "Score quant", "Valeur": decision["quant_score"]},
        {"Champ": "Trend Score", "Valeur": decision["trend_score"]},
        {"Champ": "MC Score", "Valeur": decision["mc_score"]},
        {"Champ": "Company Score", "Valeur": decision.get("company_score", "N/A")},
        {"Champ": "Valuation Score", "Valeur": decision.get("valuation_score", "N/A")},
        {"Champ": "Analyst Score", "Valeur": decision.get("analyst_score", "N/A")},
        {"Champ": "Score composite", "Valeur": decision["composite_score"]},
        {"Champ": "Sizing", "Valeur": decision["sizing"]},
        {"Champ": "Zone type", "Valeur": entry_zone["zone_type"]},
        {"Champ": "Zone basse", "Valeur": round(entry_zone["zone_low"], 2)},
        {"Champ": "Zone haute", "Valeur": round(entry_zone["zone_high"], 2)},
        {"Champ": "Position du prix", "Valeur": entry_zone["price_position"]},
        {"Champ": "Stop court", "Valeur": round(plan["stop_short"], 2)},
        {"Champ": "Stop structurel", "Valeur": round(plan["stop_structural"], 2)},
        {"Champ": "Target 1", "Valeur": round(plan["target_1"], 2)},
        {"Champ": "Target 2", "Valeur": round(plan["target_2"], 2)},
        {"Champ": "Probabilité positif", "Valeur": f"{mc_row['Prob finir positif']:.2%}"},
        {"Champ": "Probabilité stop court", "Valeur": f"{mc_row['Prob toucher stop court']:.2%}"},
        {"Champ": "Probabilité Target 1", "Valeur": f"{mc_row['Prob toucher Target 1']:.2%}"},
        {"Champ": "Asymétrie T1/Stop", "Valeur": f"{mc_row['Asymétrie T1/Stop'] * 100:.2f} pts"},
        {"Champ": "Espérance MC", "Valeur": f"{mc_row['Expected Return']:.2%}"},
        {"Champ": "Action mécanique", "Valeur": decision["action"]},
    ]

    return pd.DataFrame(rows)


# ============================================================
# ANALYSIS
# ============================================================

def analyze_ticker(
    ticker: str,
    price_data: pd.DataFrame,
    mc_simulations: int = 1000,
    mc_scenario: str = "Conservateur"
) -> dict:
    close = price_data["close"].dropna()

    if len(close) < 60:
        raise ValueError("Pas assez de données pour analyser ce ticker.")

    latest_price = float(close.iloc[-1])
    returns = calculate_returns(close)

    volatility = calculate_volatility(returns)
    drift = calculate_drift(returns)
    momentum = calculate_momentum(close)
    max_drawdown = calculate_max_drawdown(close)
    atr = calculate_atr(price_data, window=14)

    effective_drift, effective_volatility, mc_assumption_text = get_monte_carlo_assumptions(
        drift=drift,
        volatility=volatility,
        scenario=mc_scenario
    )

    basic_levels = calculate_basic_trade_levels(
        price=latest_price,
        volatility=volatility,
        momentum=momentum
    )

    global_score, signal = generate_signal(
        momentum=momentum,
        volatility=volatility,
        risk_reward=basic_levels["risk_reward"],
        max_drawdown=max_drawdown
    )

    trading_plan = calculate_trading_plan(
        price=latest_price,
        atr=atr,
        momentum=momentum,
        volatility=volatility
    )

    levels_52w = calculate_52w_levels(close)

    trend_metrics = calculate_trend_metrics(price_data)
    trend_score = calculate_trend_score(trend_metrics)
    trend_diagnosis = generate_trend_diagnosis(trend_metrics)

    momentum_v2 = None  # Legacy contract only; the modular engine computes on demand.

    mc_paths = monte_carlo_simulation(
        start_price=latest_price,
        drift=effective_drift,
        volatility=effective_volatility,
        days=30,
        simulations=mc_simulations
    )

    mc_summary = {
        "p05": float(np.percentile(mc_paths[-1], 5)),
        "p25": float(np.percentile(mc_paths[-1], 25)),
        "p50": float(np.percentile(mc_paths[-1], 50)),
        "p75": float(np.percentile(mc_paths[-1], 75)),
        "p95": float(np.percentile(mc_paths[-1], 95)),
    }

    mc_advanced_table, mc_advanced_paths = calculate_monte_carlo_advanced_metrics(
        price=latest_price,
        drift=effective_drift,
        volatility=effective_volatility,
        plan=trading_plan,
        horizons=(7, 30, 90),
        simulations=mc_simulations
    )

    commentary = generate_commentary(
        signal=signal,
        momentum=momentum,
        volatility=volatility,
        max_drawdown=max_drawdown,
        risk_reward=basic_levels["risk_reward"]
    )

    if not callable(analyze_company_intelligence):
        raise RuntimeError(
            f"Company Intelligence package unavailable: {COMPANY_INTELLIGENCE_IMPORT_ERROR}"
        )
    company_analysis = analyze_company_intelligence(ticker, latest_price)

    return {
        "latest_price": latest_price,
        "volatility": volatility,
        "drift": drift,
        "effective_drift": effective_drift,
        "effective_volatility": effective_volatility,
        "mc_scenario": mc_scenario,
        "mc_assumption_text": mc_assumption_text,
        "mc_simulations": mc_simulations,
        "momentum": momentum,
        "max_drawdown": max_drawdown,
        "atr": atr,
        "global_score": global_score,
        "signal": signal,
        "basic_levels": basic_levels,
        "trading_plan": trading_plan,
        "levels_52w": levels_52w,
        "trend_metrics": trend_metrics,
        "trend_score": trend_score,
        "trend_diagnosis": trend_diagnosis,
        "momentum_v2": momentum_v2,
        "monte_carlo": mc_summary,
        "monte_carlo_paths": mc_paths,
        "mc_advanced_table": mc_advanced_table,
        "mc_advanced_paths": mc_advanced_paths,
        "commentary": commentary,
        "company_analysis": company_analysis,
    }


# ============================================================
# UI HELPERS
# ============================================================

def get_key_levels_table(analysis: dict) -> pd.DataFrame:
    plan = analysis["trading_plan"]

    rows = [
        {"Niveau": "Stop structurel", "Prix": plan["stop_structural"], "Type": "Risque large"},
        {"Niveau": "Stop court terme", "Prix": plan["stop_short"], "Type": "Risque court terme"},
        {"Niveau": "Prix actuel", "Prix": analysis["latest_price"], "Type": "Référence"},
        {"Niveau": "Target 1", "Prix": plan["target_1"], "Type": "Objectif intermédiaire"},
        {"Niveau": "Target 2", "Prix": plan["target_2"], "Type": "Objectif principal"},
    ]

    return pd.DataFrame(rows)


def add_clean_level_lines(fig: go.Figure, levels: list[tuple[str, float]], show_text: bool = False):
    for label, value in levels:
        if show_text:
            fig.add_hline(
                y=value,
                line_dash="dash",
                line_width=1,
                opacity=0.70,
                annotation_text=label,
                annotation_position="right"
            )
        else:
            fig.add_hline(
                y=value,
                line_dash="dash",
                line_width=1,
                opacity=0.65
            )


def add_clean_vertical_lines(fig: go.Figure, levels: list[tuple[str, float]], show_text: bool = False):
    for label, value in levels:
        if show_text:
            fig.add_vline(
                x=value,
                line_dash="dash",
                line_width=1,
                opacity=0.70,
                annotation_text=label,
                annotation_position="top"
            )
        else:
            fig.add_vline(
                x=value,
                line_dash="dash",
                line_width=1,
                opacity=0.65
            )


def get_distribution_bounds(final_prices: np.ndarray, analysis: dict) -> tuple[float, float]:
    plan = analysis["trading_plan"]

    relevant_values = [
        float(np.min(final_prices)),
        float(np.max(final_prices)),
        analysis["latest_price"],
        plan["stop_short"],
        plan["stop_structural"],
        plan["target_1"],
        plan["target_2"]
    ]

    x_min = min(relevant_values)
    x_max = max(relevant_values)

    padding = (x_max - x_min) * 0.08 if x_max > x_min else x_max * 0.05

    return max(0, x_min - padding), x_max + padding


def add_distribution_zones(hist_fig: go.Figure, analysis: dict, final_prices: np.ndarray):
    plan = analysis["trading_plan"]

    stop_structural = plan["stop_structural"]
    stop_short = plan["stop_short"]
    current = analysis["latest_price"]
    target_1 = plan["target_1"]

    x_min, x_max = get_distribution_bounds(final_prices, analysis)

    zones = [
        (x_min, stop_structural, "Risque extrême", "rgba(255, 75, 75, 0.10)"),
        (stop_structural, stop_short, "Risque élevé", "rgba(255, 165, 0, 0.10)"),
        (stop_short, current, "Zone défavorable", "rgba(255, 220, 80, 0.08)"),
        (current, target_1, "Zone positive", "rgba(80, 150, 255, 0.08)"),
        (target_1, x_max, "Zone favorable", "rgba(50, 220, 120, 0.10)"),
    ]

    for x0, x1, _, color in zones:
        if x1 > x0:
            hist_fig.add_vrect(
                x0=x0,
                x1=x1,
                fillcolor=color,
                line_width=0,
                layer="below"
            )

    hist_fig.update_xaxes(range=[x_min, x_max])


def render_distribution_legend():
    legend_df = pd.DataFrame([
        {"Zone": "Rouge", "Lecture": "Sous stop structurel", "Interprétation": "Risque extrême"},
        {"Zone": "Orange", "Lecture": "Stop structurel → Stop court", "Interprétation": "Risque élevé"},
        {"Zone": "Jaune", "Lecture": "Stop court → Prix actuel", "Interprétation": "Zone défavorable"},
        {"Zone": "Bleu", "Lecture": "Prix actuel → Target 1", "Interprétation": "Zone positive"},
        {"Zone": "Vert", "Lecture": "Au-dessus Target 1", "Interprétation": "Zone favorable"},
    ])

    with st.expander("Légende des zones de distribution"):
        st.dataframe(legend_df, use_container_width=True, hide_index=True)


def split_mc_tables(mc_table: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    distribution_cols = ["Horizon", "P5", "P25", "P50", "P75", "P95"]

    probability_cols = [
        "Horizon",
        "Prob finir positif",
        "Prob perte > 5%",
        "Prob toucher stop court",
        "Prob toucher stop structurel",
        "Prob toucher Target 1",
        "Prob toucher Target 2",
        "Asymétrie T1/Stop",
        "Expected Return",
        "Median Return",
        "MC Score"
    ]

    distribution_table = mc_table[distribution_cols].copy()
    probability_table = mc_table[probability_cols].copy()

    probability_table = probability_table.rename(columns={
        "Prob finir positif": "Prob. positif",
        "Prob perte > 5%": "Perte > 5 %",
        "Prob toucher stop court": "Stop court",
        "Prob toucher stop structurel": "Stop structurel",
        "Prob toucher Target 1": "Target 1",
        "Prob toucher Target 2": "Target 2",
        "Expected Return": "Espérance",
        "Median Return": "Médiane"
    })

    for col in ["P5", "P25", "P50", "P75", "P95"]:
        distribution_table[col] = distribution_table[col].apply(lambda x: round(x, 2))

    percent_cols = [
        "Prob. positif",
        "Perte > 5 %",
        "Stop court",
        "Stop structurel",
        "Target 1",
        "Target 2",
        "Espérance",
        "Médiane"
    ]

    for col in percent_cols:
        probability_table[col] = probability_table[col].apply(lambda x: f"{x:.2%}")

    probability_table["Asymétrie T1/Stop"] = probability_table["Asymétrie T1/Stop"].apply(
        lambda x: f"{x * 100:.2f} pts"
    )

    probability_table["MC Score"] = probability_table["MC Score"].apply(
        lambda x: f"{int(x)}/100"
    )

    return distribution_table, probability_table


def format_scenario_comparison(df: pd.DataFrame) -> pd.DataFrame:
    display = df.copy()

    percent_cols = [
        "Drift utilisé",
        "Volatilité utilisée",
        "Prob. positif",
        "Prob. stop court",
        "Prob. Target 1",
        "Espérance"
    ]

    for col in percent_cols:
        display[col] = display[col].apply(lambda x: f"{x:.2%}")

    display["Asymétrie T1/Stop"] = display["Asymétrie T1/Stop"].apply(lambda x: f"{x * 100:.2f} pts")
    display["MC Score"] = display["MC Score"].apply(lambda x: f"{int(x)}/100")

    for col in ["P5", "P50", "P95"]:
        display[col] = display[col].apply(lambda x: round(x, 2))

    return display


# UI COMPONENTS
# ============================================================

def render_header():
    """Terminal shell header with an additive Market Psychology autonomous view."""
    apply_terminal_shell_theme()

    # Market Psychology is intentionally outside the normal ticker-mode router.
    # While its direct-route flag is active, use its own non-sensitive session-state
    # context instead of leaking the previously selected Correlation Matrix workspace
    # into the global header. Every other module follows the exact legacy path below.
    if st.session_state.get("market_psychology_lab_open", False):
        try:
            if callable(globals().get("render_market_psychology_shell_header")):
                render_market_psychology_shell_header()
                return
        except Exception:
            # Header failure must never block the research workspace.
            pass

    render_terminal_header_shell(
        ticker=st.session_state.get("ticker"),
        analysis=st.session_state.get("analysis"),
        last_params=st.session_state.get("last_params"),
    )



def render_main_metrics(analysis: dict):
    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Prix", round(analysis["latest_price"], 2))
    col2.metric("Signal", analysis["signal"])
    col3.metric("Score", round(analysis["global_score"], 2))
    col4.metric("ATR 14", round(analysis["atr"], 2))

    col5, col6, col7, col8 = st.columns(4)

    col5.metric("Volatilité annualisée", f"{analysis['volatility']:.2%}")
    col6.metric("Drift historique", f"{analysis['drift']:.2%}")
    col7.metric("Momentum", f"{analysis['momentum']:.2%}")
    col8.metric("Max Drawdown", f"{analysis['max_drawdown']:.2%}")


def render_price_chart(
    price_data: pd.DataFrame,
    ticker: str,
    analysis: dict,
    use_trading_plan: bool = False
):
    fig = go.Figure()

    fig.add_trace(go.Candlestick(
        x=price_data["date"],
        open=price_data["open"],
        high=price_data["high"],
        low=price_data["low"],
        close=price_data["close"],
        name=ticker
    ))

    if use_trading_plan:
        plan = analysis["trading_plan"]

        lines = [
            ("Entry agressive", plan["entry_aggressive"]),
            ("Entry prudente", plan["entry_prudent"]),
            ("Stop court terme", plan["stop_short"]),
            ("Stop structurel", plan["stop_structural"]),
            ("Target 1", plan["target_1"]),
            ("Target 2", plan["target_2"]),
        ]
    else:
        levels = analysis["basic_levels"]

        lines = [
            ("Entry", levels["entry_price"]),
            ("Stop", levels["stop_loss"]),
            ("Take Profit", levels["take_profit"]),
        ]

    add_clean_level_lines(fig, lines, show_text=True)

    fig.update_layout(
        height=650,
        xaxis_rangeslider_visible=False
    )

    st.plotly_chart(fig, use_container_width=True)


def render_trend_chart(price_data: pd.DataFrame, ticker: str):
    chart_data = price_data.copy()

    chart_data["sma_20"] = chart_data["close"].rolling(window=20).mean()
    chart_data["sma_50"] = chart_data["close"].rolling(window=50).mean()
    chart_data["sma_200"] = chart_data["close"].rolling(window=200).mean()

    fig = go.Figure()

    fig.add_trace(go.Candlestick(
        x=chart_data["date"],
        open=chart_data["open"],
        high=chart_data["high"],
        low=chart_data["low"],
        close=chart_data["close"],
        name=ticker
    ))

    fig.add_trace(go.Scatter(
        x=chart_data["date"],
        y=chart_data["sma_20"],
        mode="lines",
        name="SMA 20"
    ))

    fig.add_trace(go.Scatter(
        x=chart_data["date"],
        y=chart_data["sma_50"],
        mode="lines",
        name="SMA 50"
    ))

    fig.add_trace(go.Scatter(
        x=chart_data["date"],
        y=chart_data["sma_200"],
        mode="lines",
        name="SMA 200"
    ))

    fig.update_layout(
        height=650,
        xaxis_rangeslider_visible=False,
        title=f"Tendance et moyennes mobiles — {ticker}"
    )

    st.plotly_chart(fig, use_container_width=True)


def render_monte_carlo(analysis: dict):
    st.subheader("Monte Carlo — distribution à 30 jours")

    st.caption(
        f"Scénario : {analysis['mc_scenario']} | "
        f"Simulations : {analysis['mc_simulations']} | "
        f"Drift utilisé : {analysis['effective_drift']:.2%} | "
        f"Volatilité utilisée : {analysis['effective_volatility']:.2%}"
    )

    mc = analysis["monte_carlo"]

    mc_df = pd.DataFrame([{
        "P5": mc["p05"],
        "P25": mc["p25"],
        "P50": mc["p50"],
        "P75": mc["p75"],
        "P95": mc["p95"]
    }])

    st.dataframe(mc_df, use_container_width=True)

    mc_paths = analysis["monte_carlo_paths"]
    mc_fig = go.Figure()

    max_paths_to_display = min(50, mc_paths.shape[1])

    for i in range(max_paths_to_display):
        mc_fig.add_trace(go.Scatter(
            y=mc_paths[:, i],
            mode="lines",
            showlegend=False,
            opacity=0.25,
            hoverinfo="skip"
        ))

    percentiles = compute_path_percentiles(mc_paths)
    x_values = list(range(mc_paths.shape[0]))

    mc_fig.add_trace(go.Scatter(
        x=x_values,
        y=percentiles["p50"],
        mode="lines",
        name="P50",
        line=dict(width=3)
    ))

    mc_fig.add_trace(go.Scatter(
        x=x_values,
        y=percentiles["p05"],
        mode="lines",
        name="P5",
        line=dict(width=2, dash="dot")
    ))

    mc_fig.add_trace(go.Scatter(
        x=x_values,
        y=percentiles["p95"],
        mode="lines",
        name="P95",
        line=dict(width=2, dash="dot")
    ))

    mc_fig.update_layout(
        height=500,
        title="Scénarios Monte Carlo sur 30 jours avec percentiles",
        xaxis_title="Jours",
        yaxis_title="Prix simulé"
    )

    st.plotly_chart(mc_fig, use_container_width=True)


def render_decision_price_chart(
    price_data: pd.DataFrame,
    ticker: str,
    analysis: dict,
    entry_zone: dict
):
    plan = analysis["trading_plan"]
    current_price = analysis["latest_price"]

    fig = go.Figure()

    fig.add_trace(go.Candlestick(
        x=price_data["date"],
        open=price_data["open"],
        high=price_data["high"],
        low=price_data["low"],
        close=price_data["close"],
        name=ticker
    ))

    fig.add_hrect(
        y0=entry_zone["zone_low"],
        y1=entry_zone["zone_high"],
        fillcolor="rgba(80, 150, 255, 0.22)",
        line_width=0,
        layer="below"
    )

    styled_levels = [
        ("Stop structurel", plan["stop_structural"], "rgba(255, 75, 75, 0.90)", "dot"),
        ("Stop court", plan["stop_short"], "rgba(255, 165, 0, 0.95)", "dash"),
        ("Bas zone", entry_zone["zone_low"], "rgba(80, 150, 255, 0.95)", "dash"),
        ("Haut zone", entry_zone["zone_high"], "rgba(80, 150, 255, 0.95)", "dash"),
        ("Prix actuel", current_price, "rgba(255, 255, 255, 0.95)", "solid"),
        ("Target 1", plan["target_1"], "rgba(50, 220, 120, 0.90)", "dash"),
        ("Target 2", plan["target_2"], "rgba(50, 220, 120, 0.65)", "dot"),
    ]

    for label, value, color, dash in styled_levels:
        fig.add_hline(
            y=value,
            line_dash=dash,
            line_width=2 if label == "Prix actuel" else 1,
            line_color=color,
            opacity=0.85
        )

    last_x = price_data["date"].iloc[-1]

    annotations = [
        ("Stop court", plan["stop_short"]),
        ("Zone basse", entry_zone["zone_low"]),
        ("Zone haute", entry_zone["zone_high"]),
        ("Prix actuel", current_price),
        ("Target 1", plan["target_1"]),
    ]

    for text, y in annotations:
        fig.add_annotation(
            x=last_x,
            y=y,
            text=f"{text} {y:.2f}",
            showarrow=False,
            xshift=75,
            align="left",
            font=dict(size=11)
        )

    if current_price > entry_zone["zone_high"]:
        fig.add_annotation(
            x=last_x,
            y=current_price,
            text="Prix au-dessus de la zone : attendre pullback",
            showarrow=True,
            arrowhead=2,
            ax=-160,
            ay=-50,
            font=dict(size=12)
        )
    elif current_price < entry_zone["zone_low"]:
        fig.add_annotation(
            x=last_x,
            y=current_price,
            text="Prix sous la zone : attendre stabilisation",
            showarrow=True,
            arrowhead=2,
            ax=-160,
            ay=50,
            font=dict(size=12)
        )
    else:
        fig.add_annotation(
            x=last_x,
            y=current_price,
            text="Prix dans la zone d'entrée",
            showarrow=True,
            arrowhead=2,
            ax=-140,
            ay=-50,
            font=dict(size=12)
        )

    key_values = [
        plan["stop_structural"],
        plan["stop_short"],
        entry_zone["zone_low"],
        entry_zone["zone_high"],
        current_price,
        plan["target_1"],
        plan["target_2"],
    ]

    y_min = min(key_values) - analysis["atr"] * 1.8
    y_max = max(key_values) + analysis["atr"] * 1.8

    fig.update_layout(
        height=700,
        title=f"Prix avec zone d'entrée et niveaux de décision — {ticker}",
        xaxis_rangeslider_visible=False,
        yaxis_title="Prix",
        yaxis=dict(range=[y_min, y_max])
    )

    st.plotly_chart(fig, use_container_width=True)

    chart_levels_df = pd.DataFrame([
        {"Niveau": "Stop structurel", "Prix": plan["stop_structural"], "Lecture": "Invalidation large"},
        {"Niveau": "Stop court", "Prix": plan["stop_short"], "Lecture": "Invalidation rapide"},
        {"Niveau": "Bas zone", "Prix": entry_zone["zone_low"], "Lecture": "Bas de zone d'entrée"},
        {"Niveau": "Haut zone", "Prix": entry_zone["zone_high"], "Lecture": "Haut de zone d'entrée"},
        {"Niveau": "Prix actuel", "Prix": current_price, "Lecture": "Référence actuelle"},
        {"Niveau": "Target 1", "Prix": plan["target_1"], "Lecture": "Objectif principal court terme"},
        {"Niveau": "Target 2", "Prix": plan["target_2"], "Lecture": "Objectif étendu"},
    ])

    chart_levels_df["Prix"] = chart_levels_df["Prix"].apply(lambda x: round(x, 2))

    with st.expander("Voir les niveaux affichés sur le graphique"):
        st.dataframe(chart_levels_df, use_container_width=True, hide_index=True)



# ============================================================



def render_monte_carlo_advanced_mode(ticker: str, price_data: pd.DataFrame, analysis: dict):
    render_monte_carlo_advanced_lab(
        ticker=ticker,
        price_data=price_data,
        analysis=analysis
    )


def render_decision_engine_mode(ticker: str, price_data: pd.DataFrame, analysis: dict):
    render_decision_engine_v2(
        ticker=ticker,
        price_data=price_data,
        analysis=analysis
    )


def render_options_futures_mode(ticker: str, price_data: pd.DataFrame, analysis: dict):
    render_options_futures_v1(
        ticker=ticker,
        price_data=price_data,
        analysis=analysis,
    )

# ============================================================
# APP STATE
# ============================================================

if "analysis" not in st.session_state:
    st.session_state["analysis"] = None

if "price_data" not in st.session_state:
    st.session_state["price_data"] = None

if "ticker" not in st.session_state:
    st.session_state["ticker"] = None

if "last_params" not in st.session_state:
    st.session_state["last_params"] = None
if "asset_class" not in st.session_state:
    st.session_state["asset_class"] = "Equity"

if "asset_class_selected" not in st.session_state:
    st.session_state["asset_class_selected"] = False

# ============================================================
# APP
# ============================================================
# V6 — ROUTING STABLE + COMMAND LINE HORIZONTALE
# Objectif :
# - garder la landing JARVIS ;
# - garder le routing historique ;
# - mettre le JARVIS Control Panel dans la sidebar ;
# - mettre les paramètres ticker / période / intervalle / mode dans la page principale.

if "terminal_entered" not in st.session_state:
    st.session_state["terminal_entered"] = False


# Restore a launched workspace after a browser refresh. Streamlit session state is
# ephemeral; the URL route is intentionally limited to non-sensitive navigation
# parameters and is validated again by the central asset router.
def _route_query_value(name: str, default: str = "") -> str:
    value = st.query_params.get(name, default)
    if isinstance(value, list):
        value = value[-1] if value else default
    return str(value or default).strip()


if _route_query_value("workspace") == "terminal":
    try:
        _route_asset, _route_symbol, _route_mode = resolve_asset_symbol_and_mode(
            _route_query_value("asset", "Auto"),
            _route_query_value("symbol", "NVDA"),
            _route_query_value("mode", "Correlation Matrix"),
        )
        _route_profile = get_asset_profile(_route_asset)
        _route_period = _route_query_value(
            "period", _route_profile.get("default_period", "1y")
        )
        _route_interval = _route_query_value(
            "interval", _route_profile.get("default_interval", "1d")
        )
        if _route_period not in {"3mo", "6mo", "1y", "2y", "5y", "10y"}:
            _route_period = _route_profile.get("default_period", "1y")
        if _route_interval not in {"1d", "1wk", "1mo"}:
            _route_interval = _route_profile.get("default_interval", "1d")
    except Exception:
        # Invalid or obsolete routes fail closed to the normal landing page.
        st.query_params.clear()
    else:
        st.session_state["terminal_entered"] = True
        st.session_state["asset_class_selected"] = True
        st.session_state["asset_class"] = _route_asset
        st.session_state["ticker"] = _route_symbol
        st.session_state["mode_input"] = _route_mode
        st.session_state["terminal_command_ticker"] = _route_symbol
        st.session_state["terminal_command_mode"] = _route_mode
        st.session_state["auto_run_requested"] = False
        st.session_state["last_params"] = {
            "ticker": _route_symbol,
            "period": _route_period,
            "interval": _route_interval,
            "asset_class": _route_asset,
        }

if not st.session_state.get("terminal_entered", False):
    if callable(render_landing_page):
        render_landing_page()
        st.stop()
    else:
        st.warning("Module ui_landing introuvable : affichage direct du terminal.")

# ============================================================
# MULTI-ASSET HOME
# ============================================================
# Après la landing JARVIS, on force le choix d'une classe d'actif.
# Cela évite d'arriver directement sur Equity/NVDA par défaut.

if not st.session_state.get("asset_class_selected", False):
    apply_terminal_shell_theme()
    render_asset_class_home()
    st.stop()

# ============================================================
# WORLDMONITOR — AUTONOMOUS DIRECT VIEW
# ============================================================
# Route before the global header/sidebar.  The terminal shell renders market
# tape and cross-asset widgets of its own, so entering WorldMonitor after that
# shell would leave unrelated command-center content above the map.
if st.session_state.get("worldmonitor_v211_open", False):
    apply_terminal_shell_theme()
    top_cols = st.columns([1, 5])

    with top_cols[0]:
        if st.button("← Command Center", use_container_width=True, key="wm211_back_to_command_center"):
            st.session_state["worldmonitor_v211_open"] = False
            st.session_state["asset_class_selected"] = False
            st.rerun()

    with top_cols[1]:
        st.caption("WORLDMONITOR · JARVIS GEOPOLITICAL + QUANT INTELLIGENCE")

    if callable(render_worldmonitor_bridge_v211):
        render_worldmonitor_bridge_v211()
    else:
        st.error(f"WorldMonitor import error: {WM_V211_IMPORT_ERROR}")
        st.info("Expected file location: /workspaces/quant-terminal/worldmonitor_bridge_v211.py")

    st.stop()

# Header / sidebar are intentionally suppressed inside Quant AI V2.
# Quant AI owns a full-screen CIO Control Room and renders its own compact status strip.
if not st.session_state.get("quant_ai_open", False):
    if callable(globals().get("render_header")):
        render_header()
    else:
        apply_terminal_shell_theme()
        render_terminal_header_shell(
            ticker=st.session_state.get("ticker"),
            analysis=st.session_state.get("analysis"),
            last_params=st.session_state.get("last_params"),
        )

    # Sidebar = statut système uniquement.
    with st.sidebar:
        render_asset_control_sidebar()
        st.divider()

        render_sidebar_control_panel(
            analysis=st.session_state.get("analysis"),
            ticker=st.session_state.get("ticker"),
            mode=st.session_state.get("mode_input", "Correlation Matrix"),
            last_params=st.session_state.get("last_params"),
        )
else:
    # Keep the global dark shell, but do not render legacy header/sidebar content.
    apply_terminal_shell_theme()

# ============================================================
# MARKET PSYCHOLOGY LAB — DIRECT COMMAND CENTER VIEW
# ============================================================
# Autonomous behavioral workspace, deliberately kept OUTSIDE the normal
# ticker-mode routing so no existing asset module is replaced or reordered.
if st.session_state.get("market_psychology_lab_open", False):
    top_cols = st.columns([1, 5])

    with top_cols[0]:
        if st.button(
            "← Command Center",
            use_container_width=True,
            key="psychology_lab_back_to_command_center_v1",
        ):
            st.session_state["market_psychology_lab_open"] = False
            st.session_state["asset_class_selected"] = False
            st.rerun()

    with top_cols[1]:
        st.caption(
            "MARKET PSYCHOLOGY LAB · EXPERIMENTAL BEHAVIORAL STATE / BELIEFS / REFLEXIVITY"
        )

    if callable(render_market_psychology_lab):
        render_market_psychology_lab(
            default_symbol=st.session_state.get("psychology_symbol", "SPY")
        )
    else:
        st.error(
            "Market Psychology Lab import error: "
            f"{MARKET_PSYCHOLOGY_IMPORT_ERROR}"
        )
        st.info(
            "Expected files: market_psychology_lab.py and market_psychology/ at project root."
        )

    st.stop()


# ============================================================
# QUANT AI CIO — DIRECT COMMAND CENTER VIEW
# ============================================================
# Autonomous CIO / Investment Committee workspace. It is deliberately kept
# outside the normal ticker-mode registry, like Market Psychology Lab.
if st.session_state.get("quant_ai_open", False):
    # Quant AI V2 renders its own full-screen navigation and control strip.
    _qai_ticker = str(
        st.session_state.get("ticker")
        or (st.session_state.get("last_params") or {}).get("ticker")
        or "NVDA"
    ).upper().strip()

    _qai_price_data = st.session_state.get("price_data")
    _qai_analysis = st.session_state.get("analysis")

    _qai_needs_bootstrap = (
        not isinstance(_qai_price_data, pd.DataFrame)
        or _qai_price_data.empty
        or not isinstance(_qai_analysis, dict)
    )

    if _qai_needs_bootstrap:
        _qai_last_params = st.session_state.get("last_params") or {}
        _qai_period = str(_qai_last_params.get("period") or "1y")
        _qai_interval = str(_qai_last_params.get("interval") or "1d")

        try:
            with st.spinner(f"Preparing Quant AI market context for {_qai_ticker}..."):
                _qai_price_data = get_price_history(
                    _qai_ticker,
                    period=_qai_period,
                    interval=_qai_interval,
                )
                _qai_analysis = analyze_ticker(
                    ticker=_qai_ticker,
                    price_data=_qai_price_data,
                    mc_simulations=1000,
                    mc_scenario="Conservateur",
                )

            st.session_state["ticker"] = _qai_ticker
            st.session_state["price_data"] = _qai_price_data
            st.session_state["analysis"] = _qai_analysis
            st.session_state["last_params"] = {
                "ticker": _qai_ticker,
                "period": _qai_period,
                "interval": _qai_interval,
                "asset_class": st.session_state.get("asset_class", "Equity"),
            }

        except Exception as _qai_bootstrap_exc:
            st.warning(
                "Quant AI opened in degraded data mode because the initial market "
                f"context could not be prepared: {_qai_bootstrap_exc}"
            )
            _qai_price_data = (
                _qai_price_data
                if isinstance(_qai_price_data, pd.DataFrame)
                else pd.DataFrame()
            )
            _qai_analysis = _qai_analysis if isinstance(_qai_analysis, dict) else {}

    if callable(render_quant_ai_terminal):
        render_quant_ai_terminal(
            ticker=_qai_ticker,
            price_data=_qai_price_data,
            analysis=_qai_analysis,
        )
    else:
        st.error(f"Quant AI import error: {QUANT_AI_IMPORT_ERROR}")
        st.info(
            "Expected files: quant_ai_lab.py and quant_ai/ at project root. "
            "Install the optional Agents SDK dependency with requirements_quant_ai.txt."
        )

    st.stop()


# Command Line horizontale = paramètres d'analyse.
last_params = st.session_state.get("last_params") or {}

asset_class = st.session_state.get("asset_class", "Equity")
asset_profile = get_asset_profile(asset_class)

st.markdown(
    f"""
    <div style="
        border:1px solid rgba(90,205,255,0.20);
        background:rgba(7,20,38,0.54);
        border-radius:14px;
        padding:10px 14px;
        margin-bottom:10px;
        color:rgba(235,245,255,0.88);
        font-weight:800;">
        ACTIVE UNIVERSE · {asset_profile["label"]} · {asset_profile["subtitle"]}
    </div>
    """,
    unsafe_allow_html=True,
)

ticker_input, period_input, interval_input, mode_input, run_analysis = render_terminal_command_panel(
    default_ticker=st.session_state.get("ticker") or last_params.get("ticker") or asset_profile["default_symbol"],
    default_period=last_params.get("period", asset_profile["default_period"]),
    default_interval=last_params.get("interval", asset_profile["default_interval"]),
    default_mode=st.session_state.get("mode_input", asset_profile["mode_options"][0]),
    mode_options=asset_profile["mode_options"],
)

asset_class, ticker_input, mode_input = resolve_asset_symbol_and_mode(
    asset_class,
    ticker_input,
    mode_input,
)

st.session_state["asset_class"] = asset_class
st.session_state["mode_input"] = mode_input

# ============================================================
# FIXED INCOME & CREDIT ANALYTICS — AUTONOMOUS ROUTE
# ============================================================
# Cette route doit rester AVANT get_price_history() et analyze_ticker().
# Le module Fixed Income charge ses propres courbes et données crédit.

if mode_input == "Fixed Income & Credit Analytics":

    if callable(render_fixed_income_credit_analytics):
        render_fixed_income_credit_analytics(
            ticker=ticker_input,
            price_data=st.session_state.get("price_data"),
            analysis=st.session_state.get("analysis"),
        )

    else:
        st.error(
            "Fixed Income & Credit Analytics est indisponible."
        )

        if FIC_IMPORT_ERROR is not None:
            st.exception(FIC_IMPORT_ERROR)

    st.stop()

auto_run_requested = bool(st.session_state.pop("auto_run_requested", False))

if run_analysis or auto_run_requested:
    try:
        with st.spinner(f"Analyse de {ticker_input} en cours..."):
            price_data = get_price_history(
                ticker=ticker_input,
                period=period_input,
                interval=interval_input,
            )

            analysis = analyze_ticker(
                ticker=ticker_input,
                price_data=price_data,
                mc_simulations=1000,
                mc_scenario="Conservateur",
            )

        st.session_state["analysis"] = analysis
        st.session_state["price_data"] = price_data
        st.session_state["ticker"] = ticker_input
        st.session_state["mode_input"] = mode_input
        st.session_state["last_params"] = {
            "ticker": ticker_input,
            "period": period_input,
            "interval": interval_input,
            "asset_class": asset_class,
        }

        st.rerun()

    except Exception as e:
        st.error(f"Erreur : {e}")

analysis = st.session_state["analysis"]
price_data = st.session_state["price_data"]
ticker = st.session_state["ticker"]

# ============================================================
# PORTFOLIO LAB — STANDALONE MULTI-ASSET ROUTE
# ============================================================
# Cette route est volontairement placée avant le contrôle
# analysis / price_data / ticker.
#
# Portfolio Lab gère son propre book et télécharge ses propres
# historiques multi-actifs. Il ne doit donc pas obliger
# l'utilisateur à analyser un ticker individuel au préalable.
if mode_input == "Portfolio Lab":
    if callable(render_portfolio_lab_v1):
        render_portfolio_lab_v1(
            ticker=ticker or ticker_input,
            price_data=price_data,
            analysis=analysis,
        )
    else:
        st.error(
            "Le module portfolio_lab.py est introuvable ou n'a pas pu être importé."
        )

        if PORTFOLIO_LAB_IMPORT_ERROR is not None:
            st.exception(PORTFOLIO_LAB_IMPORT_ERROR)

        st.info(
            "Vérifie que portfolio_lab.py se trouve à la racine du projet, "
            "au même niveau que app.py."
        )

    st.stop()

if analysis is None or price_data is None or ticker is None:
    st.info("Entre un ticker dans la Command Line, choisis les paramètres, puis clique sur Analyser.")

else:
    if mode_input == "FX Dashboard":
        if callable(globals().get("render_fx_dashboard")):
            render_fx_dashboard(ticker, price_data, analysis)
        else:
            st.warning("FX Dashboard indisponible : fonction render_fx_dashboard introuvable.")

    elif mode_input == "Commodity Dashboard":
        if callable(globals().get("render_commodity_dashboard")):
            render_commodity_dashboard(ticker, price_data, analysis)
        else:
            st.warning("Commodity Dashboard indisponible : fonction render_commodity_dashboard introuvable.")

    elif mode_input == "Rates Dashboard":
        if callable(globals().get("render_rates_dashboard")):
            render_rates_dashboard(ticker, price_data, analysis)
        else:
            st.warning("Rates Dashboard indisponible : fonction render_rates_dashboard introuvable.")

    elif mode_input == "Correlation Matrix":
        if callable(render_correlation_intelligence_v1):
            render_correlation_intelligence_v1(ticker, price_data, analysis)
        else:
            st.error(
                "Le module correlation_matrix.py est introuvable ou mal importé. "
                "Vérifie qu'il est bien à la racine du projet."
            )

    elif mode_input == "Trading Plan":
        render_trading_plan_mode(ticker, price_data, analysis)

    elif mode_input == "Backtest Lab":
        if callable(render_backtest_lab_mode):
            render_backtest_lab_mode(ticker, price_data, analysis)
        else:
            st.error(
                "Le module backtest_lab.py est introuvable ou mal importé. "
                "Vérifie que le fichier est bien à la racine du projet."
            )

    elif mode_input == "Risk Monitor":
        render_risk_monitor_mode(ticker, price_data, analysis)

    elif mode_input == "Momentum / Trend":
        render_momentum_trend_mode(ticker, price_data, analysis)

    elif mode_input == "Monte Carlo Advanced":
        render_monte_carlo_advanced_mode(ticker, price_data, analysis)

    elif mode_input == "Company Intelligence":
        if callable(render_company_intelligence_mode):
            render_company_intelligence_mode(ticker, analysis)
        else:
            st.error(
                "Company Intelligence indisponible : vérifie le dossier company_intelligence/."
            )
            if COMPANY_INTELLIGENCE_IMPORT_ERROR is not None:
                st.exception(COMPANY_INTELLIGENCE_IMPORT_ERROR)

    elif mode_input == "Decision Engine":
        render_decision_engine_mode(ticker, price_data, analysis)

    elif mode_input == "Decision Engine Lite":
        st.warning(
            "Decision Engine Lite multi-asset : version provisoire. "
            "Le Decision Engine actuel est surtout calibré Equity."
        )
        render_decision_engine_mode(ticker, price_data, analysis)

    elif mode_input == "ML Research Lab":
        render_ml_research_lab_v1(ticker, price_data, analysis)

    elif mode_input == "Macro / Central Banks":
        if callable(render_macro_central_bank_lab):
            render_macro_central_bank_lab(
                ticker=ticker,
                price_data=price_data,
                analysis=analysis,
            )
        else:
            st.error(
                "Le module macro_central_bank.py est introuvable ou mal importé. "
                "Vérifie que le fichier est bien à la racine du projet et que l'import "
                "`from macro_central_bank import render_macro_central_bank_lab` est présent."
            )

    elif mode_input == "Options / Futures":
        if callable(render_options_futures_v1):
            render_options_futures_v1(ticker=ticker, price_data=price_data, analysis=analysis)
        else:
            st.error(
                "Le module options_futures.py est introuvable ou mal importé. "
                "Vérifie qu'il est bien à la racine du projet."
            )

    elif mode_input in {"WorldMonitor", "WorldMonitor Bridge V2.11", "World Monitor V2.11", "Global Event Map V2.11"}:
        if render_worldmonitor_bridge_v211 is None:
            st.error(f"WorldMonitor import error: {WM_V211_IMPORT_ERROR}")
            st.info("Expected file location: /workspaces/quant-terminal/worldmonitor_bridge_v211.py")
        else:
            render_worldmonitor_bridge_v211()

    else:
        st.warning(f"Mode non reconnu : {mode_input}")
