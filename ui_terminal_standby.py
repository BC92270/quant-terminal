# ui_terminal_standby.py — consolidated single-file UI shell V12
# Objectif V12 :
# - Garder les corrections V10/V11.
# - Ajouter Backtest Lab dans les modes UI.
# - Préparer le data label Backtest Lab.
# - Ne toucher ni au routing app.py, ni aux calculs des autres modules.
# - Aucun calcul financier ici : design + widgets UI seulement.

from __future__ import annotations

from html import escape
from textwrap import dedent
from typing import Any

import pandas as pd
import streamlit as st

try:
    import streamlit.components.v1 as components
except Exception:  # pragma: no cover
    components = None


# ============================================================
# SAFE HELPERS
# ============================================================

def _safe_str(value: Any, default: str = "N/A") -> str:
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    return str(value)


def _fmt_value(value: Any, decimals: int = 2, default: str = "N/A") -> str:
    try:
        if value is None or pd.isna(value):
            return default
        return f"{float(value):,.{decimals}f}"
    except Exception:
        return default


def _extract_signal(analysis: dict[str, Any] | None) -> str:
    if not isinstance(analysis, dict):
        return "STANDBY"

    for key in ["signal", "decision", "final_signal", "status"]:
        value = analysis.get(key)
        if value not in [None, ""]:
            return str(value)

    return "N/A"


def _extract_score(analysis: dict[str, Any] | None) -> str:
    if not isinstance(analysis, dict):
        return "—"

    for key in ["global_score", "composite_score", "score", "decision_score"]:
        if key in analysis:
            return _fmt_value(analysis.get(key), decimals=1, default="—")

    return "—"


def _extract_price(analysis: dict[str, Any] | None) -> str:
    if not isinstance(analysis, dict):
        return "N/A"

    for key in ["latest_price", "last_price", "price", "close"]:
        if key in analysis:
            return _fmt_value(analysis.get(key), decimals=2, default="N/A")

    return "N/A"


def _extract_mode_from_state(default: str = "Correlation Matrix") -> str:
    """
    Lecture UI seulement : récupère le mode actif depuis les clés déjà utilisées
    par app.py / render_terminal_command_panel, sans modifier le routing.
    """
    for key in ["mode_input", "terminal_selected_mode", "terminal_command_mode", "selected_mode", "mode"]:
        value = st.session_state.get(key)
        if value not in [None, ""]:
            return str(value)
    return default


def _module_data_label(mode: str | None) -> str:
    """Libellé data-source purement visuel selon le module actif."""
    mode_text = _safe_str(mode, "").lower()
    if "fixed income" in mode_text or "credit analytics" in mode_text:
        return "CURVES · OAS · BONDS · DV01 · CS01 · CREDIT RISK"
    if "portfolio" in mode_text:
        return "POSITIONS · COVARIANCE · OPTIMIZATION · ATTRIBUTION"
    if "option" in mode_text and "future" in mode_text:
        return "PUBLIC OPTIONS CHAIN · YAHOO PROXIES"
    if "macro" in mode_text or "central bank" in mode_text:
        return "FRED · RATES · CENTRAL BANK PROXIES"
    if "correlation" in mode_text:
        return "ADJUSTED PRICES · CROSS-ASSET PROXIES"
    if "monte" in mode_text:
        return "PRICE RETURNS · SIMULATION ENGINE"
    if "risk" in mode_text:
        return "ATR · DRAWDOWN · POSITION RISK"
    if "momentum" in mode_text or "trend" in mode_text:
        return "TREND · MOMENTUM · RELATIVE STRENGTH"
    if "backtest" in mode_text:
        return "HISTORICAL REPLAY · COSTS · WALK-FORWARD"
    if "decision" in mode_text:
        return "COMPOSITE SCORE · RULE ENGINE"
    if "company" in mode_text:
        return "FUNDAMENTALS · VALUATION · QUALITY"
    if "trading" in mode_text:
        return "ENTRY PLAN · EXECUTION CHECKLIST"
    return "MARKET DATA · MODULE CONTEXT"


def _derive_risk_mode(analysis: dict[str, Any] | None) -> str:
    """
    Badge de risque purement UI.
    Ce n'est pas un nouveau signal : lecture compacte du signal/score déjà calculés.
    """
    if not isinstance(analysis, dict) or not analysis:
        return "STANDBY"

    signal = _extract_signal(analysis).upper()
    score_value = None
    for key in ["global_score", "composite_score", "score", "decision_score"]:
        try:
            if key in analysis and analysis.get(key) is not None:
                score_value = float(analysis.get(key))
                break
        except Exception:
            pass

    if "SELL" in signal or "SHORT" in signal or "RISK_OFF" in signal:
        return "DEFENSIVE"
    if "BUY" in signal or "LONG" in signal or "RISK_ON" in signal:
        return "CONSTRUCTIVE"
    if score_value is not None:
        if score_value >= 70:
            return "CONSTRUCTIVE"
        if score_value <= 40:
            return "DEFENSIVE"
    return "BALANCED"


def _last_run_label(last_params: dict[str, Any] | None) -> str:
    if not isinstance(last_params, dict):
        return "Awaiting command"

    ticker = _safe_str(last_params.get("ticker"), "N/A").upper()
    period = _safe_str(last_params.get("period"), "N/A")
    interval = _safe_str(last_params.get("interval"), "N/A")
    return f"{ticker} · {period} / {interval}"


def _select_index(options: list[str], value: str | None, default_index: int = 0) -> int:
    try:
        return options.index(str(value))
    except Exception:
        return default_index


# ============================================================
# GLOBAL TERMINAL THEME
# ============================================================

def apply_terminal_shell_theme() -> None:
    """
    Thème global Streamlit.
    Design uniquement : ne modifie aucun calcul.
    """
    st.markdown(
        dedent(
            """
            <style>
            :root {
                --qt-bg: #020713;
                --qt-panel: rgba(7, 20, 38, 0.88);
                --qt-border: rgba(90, 205, 255, 0.25);
                --qt-cyan: #55e8ff;
                --qt-blue: #3494ff;
                --qt-green: #62ffbf;
                --qt-warn: #ffd56a;
                --qt-red: #ff6d6d;
                --qt-text: #f4f8ff;
                --qt-muted: rgba(215, 230, 246, 0.70);
            }

            html, body, [data-testid="stAppViewContainer"] {
                background:
                    radial-gradient(circle at 52% 0%, rgba(40, 150, 255, 0.10), transparent 34%),
                    radial-gradient(circle at 86% 22%, rgba(50, 220, 255, 0.055), transparent 28%),
                    linear-gradient(180deg, #030813 0%, #020713 44%, #01050d 100%) !important;
                color: var(--qt-text) !important;
            }

            [data-testid="stHeader"] {
                background: rgba(2, 6, 15, 0.94) !important;
                border-bottom: 1px solid rgba(90, 205, 255, 0.08);
            }

            .block-container {
                max-width: 1540px !important;
                padding-top: 0.78rem !important;
                padding-left: 1.70rem !important;
                padding-right: 1.70rem !important;
                padding-bottom: 3.2rem !important;
            }

            [data-testid="stSidebar"] {
                background:
                    radial-gradient(circle at 50% 0%, rgba(50, 170, 255, 0.13), transparent 28%),
                    linear-gradient(180deg, rgba(5, 15, 30, 0.99), rgba(3, 10, 22, 0.99)) !important;
                border-right: 1px solid rgba(90, 205, 255, 0.18);
                box-shadow: 18px 0 54px rgba(0, 0, 0, 0.20);
            }

            [data-testid="stSidebar"] .block-container {
                padding-top: 1.15rem !important;
                padding-left: 1rem !important;
                padding-right: 1rem !important;
            }

            [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
            [data-testid="stSidebar"] label,
            [data-testid="stSidebar"] span {
                color: rgba(235, 245, 255, 0.92) !important;
            }

            [data-testid="stTextInput"] input,
            [data-testid="stSelectbox"] div[data-baseweb="select"] > div {
                min-height: 38px !important;
                background: rgba(4, 14, 28, 0.86) !important;
                border-color: rgba(90, 205, 255, 0.30) !important;
                color: #f5f9ff !important;
                border-radius: 11px !important;
                box-shadow: inset 0 0 18px rgba(55, 150, 255, 0.04) !important;
            }

            div.stButton > button,
            div[data-testid="stFormSubmitButton"] button {
                min-height: 38px !important;
                border-radius: 11px !important;
                border: 1px solid rgba(105, 220, 255, 0.46) !important;
                background:
                    linear-gradient(90deg, rgba(44, 112, 255, 0.98), rgba(70, 210, 255, 0.96)) !important;
                color: #ffffff !important;
                font-weight: 840 !important;
                letter-spacing: 0.018em !important;
                box-shadow:
                    0 0 22px rgba(60, 175, 255, 0.18),
                    inset 0 0 16px rgba(255, 255, 255, 0.08) !important;
            }

            [data-testid="stMetric"] {
                border-radius: 15px;
                border: 1px solid rgba(90, 205, 255, 0.17);
                background: linear-gradient(180deg, rgba(8, 19, 36, 0.58), rgba(3, 10, 22, 0.60));
                padding: 12px 13px;
            }

            [data-testid="stAlert"] {
                border-radius: 14px !important;
                border: 1px solid rgba(85, 200, 255, 0.20) !important;
                background: rgba(12, 43, 72, 0.72) !important;
            }

            [data-testid="stDataFrame"] {
                border-radius: 14px !important;
                overflow: hidden !important;
            }

            /* V9 : densité terminal + status tape, sans toucher aux calculs ni au routing. */
            [data-testid="stForm"] {
                border-radius: 15px !important;
                border: 1px solid rgba(90, 205, 255, 0.18) !important;
                background:
                    radial-gradient(circle at 12% 0%, rgba(85, 232, 255, 0.055), transparent 30%),
                    linear-gradient(180deg, rgba(5, 16, 32, 0.50), rgba(2, 8, 18, 0.38)) !important;
                padding: 10px 12px 8px 12px !important;
                margin: 5px 0 10px 0 !important;
                box-shadow: inset 0 0 20px rgba(80, 170, 255, 0.025) !important;
            }

            .qt-side-title {
                margin: 4px 0 4px 0;
                color: #f4f8ff;
                font-size: 16px;
                font-weight: 950;
                letter-spacing: -0.03em;
            }

            .qt-side-subtitle {
                margin: 0 0 12px 0;
                color: rgba(215, 230, 246, 0.66);
                font-size: 10.5px;
                line-height: 1.35;
                font-weight: 700;
            }

            .qt-side-card {
                margin: 10px 0;
                padding: 12px 13px;
                border-radius: 16px;
                border: 1px solid rgba(90, 205, 255, 0.23);
                background:
                    radial-gradient(circle at 18% 0%, rgba(85, 232, 255, 0.09), transparent 34%),
                    linear-gradient(180deg, rgba(8, 20, 38, 0.74), rgba(3, 10, 22, 0.68));
                box-shadow: inset 0 0 22px rgba(80, 170, 255, 0.035);
            }

            .qt-side-kicker {
                color: #55e8ff;
                font-size: 9px;
                font-weight: 950;
                letter-spacing: 0.18em;
                text-transform: uppercase;
                margin-bottom: 8px;
            }

            .qt-side-row {
                display: flex;
                align-items: baseline;
                justify-content: space-between;
                gap: 8px;
                padding: 5px 0;
                border-bottom: 1px solid rgba(120, 210, 255, 0.08);
            }

            .qt-side-row:last-child { border-bottom: 0; }

            .qt-side-key {
                color: rgba(210, 226, 244, 0.60);
                font-size: 9px;
                font-weight: 950;
                letter-spacing: 0.14em;
                text-transform: uppercase;
            }

            .qt-side-val {
                color: #ffffff;
                font-size: 10.5px;
                font-weight: 900;
                text-align: right;
                word-break: break-word;
            }

            .qt-side-ready {
                color: var(--qt-green);
                text-shadow: 0 0 12px rgba(98,255,191,0.25);
            }

            .qt-side-warn {
                color: var(--qt-warn);
                text-shadow: 0 0 12px rgba(255,213,106,0.20);
            }

            .qt-side-bar {
                height: 4px;
                border-radius: 999px;
                overflow: hidden;
                background: rgba(145, 190, 255, 0.13);
                margin-top: 5px;
            }

            .qt-side-fill {
                height: 100%;
                border-radius: inherit;
                background: linear-gradient(90deg, rgba(52, 148, 255, 0.96), rgba(85, 232, 255, 0.96));
            }

            .qt-command-tape {
                display: flex;
                flex-wrap: wrap;
                gap: 8px;
                align-items: center;
                margin: -4px 0 22px 0;
                padding: 7px 10px;
                border-radius: 12px;
                border: 1px solid rgba(90, 205, 255, 0.13);
                background: linear-gradient(90deg, rgba(4, 15, 31, 0.58), rgba(3, 10, 22, 0.28));
                box-shadow: inset 0 0 18px rgba(80, 170, 255, 0.020);
            }

            .qt-command-chip {
                color: rgba(215, 230, 246, 0.64);
                font-size: 9px;
                font-weight: 900;
                letter-spacing: 0.12em;
                text-transform: uppercase;
                white-space: nowrap;
            }

            .qt-command-chip b {
                color: #f4f8ff;
                font-weight: 950;
                letter-spacing: 0.04em;
            }

            .qt-command-chip .ok {
                color: var(--qt-green);
                text-shadow: 0 0 10px rgba(98,255,191,0.22);
            }


            /* V11 : lisibilité cards KPI / Decision Engine.
               Objectif : corriger les valeurs tronquées type "OR mainten..." sans toucher au moteur. */
            [data-testid="stMetric"] {
                min-height: 92px !important;
                overflow: visible !important;
            }

            [data-testid="stMetric"] * {
                text-overflow: unset !important;
            }

            [data-testid="stMetricLabel"] {
                white-space: normal !important;
                overflow: visible !important;
                text-overflow: unset !important;
            }

            [data-testid="stMetricLabel"] p {
                color: rgba(215, 230, 246, 0.78) !important;
                font-size: 0.78rem !important;
                line-height: 1.15 !important;
                white-space: normal !important;
                overflow: visible !important;
                text-overflow: unset !important;
            }

            [data-testid="stMetricValue"] {
                max-width: 100% !important;
                overflow: visible !important;
                white-space: normal !important;
                text-overflow: unset !important;
                line-height: 1.05 !important;
            }

            [data-testid="stMetricValue"] > div,
            [data-testid="stMetricValue"] p,
            [data-testid="stMetricValue"] span {
                max-width: 100% !important;
                overflow: visible !important;
                white-space: normal !important;
                text-overflow: unset !important;
                overflow-wrap: anywhere !important;
                word-break: normal !important;
                line-height: 1.08 !important;
                font-size: clamp(1.18rem, 1.55vw, 1.70rem) !important;
            }

            [data-testid="stMetricDelta"] {
                max-width: 100% !important;
                overflow: visible !important;
                white-space: normal !important;
                text-overflow: unset !important;
            }

            [data-testid="stMetricDelta"] p,
            [data-testid="stMetricDelta"] span {
                white-space: normal !important;
                overflow: visible !important;
                text-overflow: unset !important;
                overflow-wrap: anywhere !important;
                font-size: 0.76rem !important;
                line-height: 1.12 !important;
            }

            /* Compatibilité avec les cards HTML custom éventuellement utilisées par Decision Engine. */
            .decision-card,
            .decision-kpi,
            .decision-metric,
            .kpi-card,
            .metric-card,
            .qt-kpi-card,
            .jarvis-kpi-card {
                overflow: visible !important;
                min-height: 92px !important;
            }

            .decision-card *,
            .decision-kpi *,
            .decision-metric *,
            .kpi-card *,
            .metric-card *,
            .qt-kpi-card *,
            .jarvis-kpi-card * {
                white-space: normal !important;
                overflow: visible !important;
                text-overflow: unset !important;
                overflow-wrap: anywhere !important;
            }
            </style>
            """
        ),
        unsafe_allow_html=True,
    )


# ============================================================
# COMPACT SYSTEM STRIP
# ============================================================

def render_terminal_header_shell(
    ticker: str | None = None,
    analysis: dict[str, Any] | None = None,
    last_params: dict[str, Any] | None = None,
    auto_sidebar: bool = False,
) -> None:
    """
    Barre système compacte du terminal.
    V9 : légèrement descendue pour éviter le clipping, et contextualisée par module actif.
    """
    active_ticker = escape(_safe_str(ticker, "NO ACTIVE TICKER").upper())
    signal = escape(_extract_signal(analysis))
    score = escape(_extract_score(analysis))
    price = escape(_extract_price(analysis))
    run = escape(_last_run_label(last_params))
    mode_label = escape(_extract_mode_from_state())

    live = bool(ticker and isinstance(analysis, dict) and analysis)
    state = "LIVE ANALYSIS" if live else "STANDBY"
    state_class = "ready" if live else "standby"

    if auto_sidebar:
        try:
            with st.sidebar:
                render_sidebar_control_panel(
                    analysis=analysis,
                    ticker=ticker,
                    mode=st.session_state.get("mode_input")
                    or st.session_state.get("selected_mode")
                    or st.session_state.get("mode")
                    or "Correlation Matrix",
                    last_params=last_params,
                )
        except Exception:
            pass

    header_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
html, body {{
    margin: 0;
    padding: 0;
    background: transparent;
    font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    color: #f4f8ff;
    overflow: hidden;
}}
.strip {{
    position: relative;
    height: 78px;
    margin-top: 5px;
    box-sizing: border-box;
    overflow: hidden;
    border-radius: 16px;
    border: 1px solid rgba(90, 205, 255, 0.24);
    background:
        radial-gradient(circle at 15% 0%, rgba(85, 232, 255, 0.12), transparent 36%),
        radial-gradient(circle at 88% 12%, rgba(53, 123, 255, 0.11), transparent 32%),
        linear-gradient(180deg, rgba(7, 20, 38, 0.94), rgba(3, 10, 22, 0.90));
    box-shadow:
        0 0 0 1px rgba(255,255,255,0.025) inset,
        0 12px 36px rgba(0,0,0,0.18),
        0 0 28px rgba(30, 146, 255, 0.06);
}}
.strip::before {{
    content: "";
    position: absolute;
    inset: 0;
    background:
        repeating-linear-gradient(
            to bottom,
            rgba(255,255,255,0.016) 0px,
            rgba(255,255,255,0.016) 1px,
            transparent 2px,
            transparent 7px
        );
    opacity: 0.34;
    pointer-events: none;
}}
.grid {{
    position: relative;
    z-index: 2;
    height: 100%;
    box-sizing: border-box;
    padding: 10px 14px;
    display: grid;
    grid-template-columns: minmax(205px, 1.10fr) repeat(5, minmax(96px, 0.54fr));
    gap: 8px;
    align-items: center;
}}
.identity {{ min-width: 0; }}
.kicker {{
    color: #55e8ff;
    font-size: 8px;
    font-weight: 950;
    letter-spacing: 0.22em;
    text-transform: uppercase;
    text-shadow: 0 0 13px rgba(85,232,255,0.38);
    margin-bottom: 4px;
}}
.title {{
    color: #f4f8ff;
    font-size: 17px;
    line-height: 1.02;
    font-weight: 950;
    letter-spacing: -0.04em;
    margin: 0;
    white-space: nowrap;
}}
.subtitle {{
    margin-top: 5px;
    color: rgba(215, 230, 246, 0.68);
    font-size: 9px;
    font-weight: 720;
    line-height: 1.20;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}}
.stat {{
    border-left: 1px solid rgba(90, 205, 255, 0.14);
    padding-left: 10px;
    min-height: 40px;
    display: flex;
    flex-direction: column;
    justify-content: center;
}}
.key {{
    color: rgba(210, 226, 244, 0.56);
    font-size: 7.5px;
    font-weight: 950;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    margin-bottom: 5px;
}}
.value {{
    color: #ffffff;
    font-size: 11.5px;
    font-weight: 950;
    line-height: 1.12;
    word-break: break-word;
}}
.ready {{ color: #62ffbf; text-shadow: 0 0 12px rgba(98,255,191,0.28); }}
.standby {{ color: #ffd56a; text-shadow: 0 0 12px rgba(255,213,106,0.22); }}
@media (max-width: 980px) {{
    .strip {{ height: 190px; }}
    .grid {{ grid-template-columns: 1fr 1fr; }}
    .identity {{ grid-column: 1 / -1; }}
    .title, .subtitle {{ white-space: normal; }}
    .stat {{ min-height: auto; }}
}}
</style>
</head>
<body>
<div class="strip">
    <div class="grid">
        <div class="identity">
            <div class="kicker">Institutional Quant Workspace</div>
            <h1 class="title">JARVIS Terminal</h1>
            <div class="subtitle">Module actif · {mode_label} · routing stable · modules conservés</div>
        </div>
        <div class="stat"><div class="key">Workspace</div><div class="value">{active_ticker}</div></div>
        <div class="stat"><div class="key">State</div><div class="value {state_class}">{escape(state)}</div></div>
        <div class="stat"><div class="key">Signal</div><div class="value">{signal}</div></div>
        <div class="stat"><div class="key">Price / Score</div><div class="value">{price} · {score}</div></div>
        <div class="stat"><div class="key">Run</div><div class="value">{run}</div></div>
    </div>
</div>
</body>
</html>"""

    if callable(getattr(st, "iframe", None)):
        st.iframe(header_html, height=94)
        return

    if components is not None:
        components.html(header_html, height=94, scrolling=False)
        return

    st.markdown(
        f"### JARVIS Terminal\n\n"
        f"**Workspace:** {active_ticker} · **State:** {state} · "
        f"**Signal:** {signal} · **Price/Score:** {price} / {score} · **Run:** {run}"
    )


# ============================================================
# HORIZONTAL COMMAND LINE
# ============================================================

def render_terminal_command_panel(
    default_ticker: str | None = None,
    default_period: str = "1y",
    default_interval: str = "1d",
    default_mode: str = "Correlation Matrix",
    mode_options: list[str] | None = None,
) -> tuple[str, str, str, str, bool]:
    """
    Command Line horizontale.
    V10 :
    - ticker / période / intervalle restent contrôlés par le bouton Analyser ;
    - le Mode sort du formulaire pour changer instantanément de module ;
    - aucun calcul ni routing métier n'est modifié.
    """
    periods = ["3mo", "6mo", "1y", "2y", "5y"]
    intervals = ["1d", "1wk", "1mo"]
    modes = mode_options or [
        "Correlation Matrix",
        "Portfolio Lab",
        "Quant AI",
        "Trading Plan",
        "Macro / Central Banks",
        "Backtest Lab",
        "Risk Monitor",
        "Momentum / Trend",
        "Monte Carlo Advanced",
        "Company Intelligence",
        "Decision Engine",
        "ML Research Lab",
        "Options / Futures",
    ]

    ticker_default = _safe_str(default_ticker, "NVDA").upper()
    period_default = _safe_str(default_period, "1y")
    interval_default = _safe_str(default_interval, "1d")

    # Priorité au mode déjà choisi côté widget, puis aux clés non-widget,
    # puis au default transmis par app.py.
    mode_default = _safe_str(
        st.session_state.get("terminal_command_mode")
        or st.session_state.get("terminal_selected_mode")
        or st.session_state.get("mode_input")
        or default_mode,
        "Correlation Matrix",
    )

    c1, c2, c3, c4, c5 = st.columns(
        [2.25, 0.95, 0.95, 1.70, 1.05],
        vertical_alignment="bottom",
    )

    if "terminal_command_ticker" not in st.session_state:
        st.session_state["terminal_command_ticker"] = ticker_default
    ticker_input = c1.text_input("Ticker", key="terminal_command_ticker").upper().strip()

    if st.session_state.get("terminal_command_period") not in periods:
        st.session_state["terminal_command_period"] = periods[_select_index(periods, period_default, 2)]
    period_input = c2.selectbox("Période", periods, key="terminal_command_period")

    if st.session_state.get("terminal_command_interval") not in intervals:
        st.session_state["terminal_command_interval"] = intervals[_select_index(intervals, interval_default, 0)]
    interval_input = c3.selectbox("Intervalle", intervals, key="terminal_command_interval")

    # V10 : hors formulaire.
    # Changer le mode déclenche un rerun Streamlit immédiat, donc le module affiché
    # reste synchronisé avec le selectbox.
    if st.session_state.get("terminal_command_mode") not in modes:
        st.session_state["terminal_command_mode"] = modes[_select_index(modes, mode_default, 0)]
    mode_input = c4.selectbox("Mode", modes, key="terminal_command_mode")

    run_analysis = c5.button(
        "Analyser",
        key="terminal_run_analysis_button",
        use_container_width=True,
    )

    tape_ticker = escape(ticker_input or ticker_default)
    tape_mode = escape(mode_input)
    tape_data = escape(_module_data_label(mode_input))
    tape_period = escape(period_input)
    tape_interval = escape(interval_input)

    st.markdown(
        f"""
        <div class="qt-command-tape">
            <span class="qt-command-chip">Workspace <b>{tape_ticker}</b></span>
            <span class="qt-command-chip">Mode <b>{tape_mode}</b></span>
            <span class="qt-command-chip">Window <b>{tape_period} / {tape_interval}</b></span>
            <span class="qt-command-chip">Data <b>{tape_data}</b></span>
            <span class="qt-command-chip">Route <b class="ok">STABLE</b></span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Clés indépendantes des widgets Streamlit : safe, pas de mutation d'une clé widget.
    st.session_state["mode_input"] = mode_input
    st.session_state["terminal_selected_mode"] = mode_input

    return ticker_input, period_input, interval_input, mode_input, run_analysis


# ============================================================
# SIDEBAR CONTROL PANEL
# ============================================================

def render_sidebar_control_panel(
    analysis: dict[str, Any] | None = None,
    ticker: str | None = None,
    mode: str | None = None,
    last_params: dict[str, Any] | None = None,
) -> None:
    """
    Panneau système compact pour la sidebar.
    Design uniquement : ne crée aucun widget et ne modifie aucun calcul.
    """
    active_ticker = escape(_safe_str(ticker, "NONE").upper())
    signal = escape(_extract_signal(analysis))
    score = escape(_extract_score(analysis))
    price = escape(_extract_price(analysis))
    mode_display = escape(_safe_str(mode, "N/A"))
    run = escape(_last_run_label(last_params))
    risk_mode = escape(_derive_risk_mode(analysis))

    live = bool(ticker and isinstance(analysis, dict) and analysis)
    state = "LIVE" if live else "STANDBY"
    state_class = "qt-side-ready" if live else "qt-side-warn"

    market_state = "READY" if live else "WAIT"

    # Compatibilité prudente : l'app a déjà utilisé les deux libellés
    # "Options / Futures" et "Options & Futures" selon les versions.
    # On ne change pas le routing : on normalise seulement l'affichage du statut.
    mode_text = _safe_str(mode, "")
    option_mode_active = "options" in mode_text.lower() and "futures" in mode_text.lower()
    option_state = "READY" if live and option_mode_active else "STANDBY"

    macro_state = "READY" if live else "WAIT"
    session_state = "LIVE" if live else "IDLE"

    decision_width = "82%" if live else "38%"
    risk_width = "76%" if live else "42%"
    data_width = "88%" if live else "46%"

    st.markdown(
        f"""
        <div class="qt-side-title">JARVIS Control Panel</div>
        <div class="qt-side-subtitle">Statut système, flux et moteur. La recherche reste centralisée en haut du terminal.</div>

        <div class="qt-side-card">
            <div class="qt-side-kicker">Workspace</div>
            <div class="qt-side-row"><span class="qt-side-key">Ticker</span><span class="qt-side-val">{active_ticker}</span></div>
            <div class="qt-side-row"><span class="qt-side-key">Mode</span><span class="qt-side-val">{mode_display}</span></div>
            <div class="qt-side-row"><span class="qt-side-key">Signal</span><span class="qt-side-val">{signal}</span></div>
            <div class="qt-side-row"><span class="qt-side-key">Score</span><span class="qt-side-val">{score}</span></div>
            <div class="qt-side-row"><span class="qt-side-key">Risk Mode</span><span class="qt-side-val {state_class}">{risk_mode}</span></div>
            <div class="qt-side-row"><span class="qt-side-key">State</span><span class="qt-side-val {state_class}">{state}</span></div>
            <div class="qt-side-row"><span class="qt-side-key">Run</span><span class="qt-side-val">{run}</span></div>
        </div>

        <div class="qt-side-card">
            <div class="qt-side-kicker">Engine Status</div>
            <div class="qt-side-row"><span class="qt-side-key">Market Data</span><span class="qt-side-val qt-side-ready">{market_state}</span></div>
            <div class="qt-side-bar"><div class="qt-side-fill" style="width:{data_width};"></div></div>
            <div class="qt-side-row"><span class="qt-side-key">Risk Monitor</span><span class="qt-side-val qt-side-ready">{market_state}</span></div>
            <div class="qt-side-bar"><div class="qt-side-fill" style="width:{risk_width};"></div></div>
            <div class="qt-side-row"><span class="qt-side-key">Decision Layer</span><span class="qt-side-val {state_class}">{state}</span></div>
            <div class="qt-side-bar"><div class="qt-side-fill" style="width:{decision_width};"></div></div>
        </div>

        <div class="qt-side-card">
            <div class="qt-side-kicker">Data Status</div>
            <div class="qt-side-row"><span class="qt-side-key">Options Chain</span><span class="qt-side-val">{option_state}</span></div>
            <div class="qt-side-row"><span class="qt-side-key">Macro Proxies</span><span class="qt-side-val">{macro_state}</span></div>
            <div class="qt-side-row"><span class="qt-side-key">Session</span><span class="qt-side-val qt-side-ready">{session_state}</span></div>
            <div class="qt-side-row"><span class="qt-side-key">Price</span><span class="qt-side-val">{price}</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ============================================================
# BACKWARD-COMPATIBILITY STUBS
# ============================================================
# Ces fonctions évitent les ImportError si app.py contient encore un ancien import.
# Elles ne changent ni routing ni calculs.

def render_sidebar_system_status(*args, **kwargs) -> None:
    render_sidebar_control_panel(*args, **kwargs)


def render_workspace_header(*args, **kwargs) -> None:
    render_terminal_header_shell(*args, **kwargs)


def render_terminal_command_bar(*args, **kwargs) -> None:
    return render_terminal_command_panel(*args, **kwargs)


def render_terminal_standby_overview(*args, **kwargs) -> None:
    return None


def render_active_workspace_summary(*args, **kwargs) -> None:
    return None
