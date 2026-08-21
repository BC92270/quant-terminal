from __future__ import annotations

from html import escape
from typing import Mapping

import numpy as np
import pandas as pd
import streamlit as st

from .charts import equity_curve_chart, model_consensus_chart, price_decision_chart, regime_probability_chart
from .config import EngineConfig, Profile
from .contracts import EngineResult
from .engine import run_momentum_trend
from .styles import TERMINAL_CSS


def _pct(value: float | None, digits: int = 1) -> str:
    return "—" if value is None or not np.isfinite(value) else f"{value:.{digits}%}"


def _num(value: float | None, digits: int = 2) -> str:
    return "—" if value is None or not np.isfinite(value) else f"{value:,.{digits}f}"


def _tone(value: float, good: float = 0.67, bad: float = 0.40) -> str:
    return "good" if value >= good else "bad" if value < bad else "warn"


@st.cache_data(ttl=300, show_spinner=False)
def _compute_cached(
    ticker: str,
    price_data: pd.DataFrame,
    benchmarks: Mapping[str, pd.DataFrame] | None,
    config: EngineConfig,
) -> EngineResult:
    return run_momentum_trend(ticker, price_data, benchmarks, config)


def _command_bar(result: EngineResult) -> None:
    decision = result.decision
    quality_tone = _tone(result.quality.quality_score / 100)
    regime_tone = _tone(result.regime.confidence)
    signal_tone = "good" if decision.bias == "LONG" else "bad" if decision.bias == "SHORT" else "warn"
    st.markdown(
        f"""
        <div class="mt-shell mt-command">
          <div class="mt-brand"><div class="mt-eyebrow">Institutional time-series intelligence</div><div class="mt-title">Momentum / Trend Decision Terminal</div><div class="mt-sub">Causal features · probabilistic regimes · heterogeneous ensemble · explicit invalidation</div></div>
          <div class="mt-command-cell"><div class="mt-label">Instrument</div><div class="mt-value">{escape(result.ticker)}</div></div>
          <div class="mt-command-cell"><div class="mt-label">Regime</div><div class="mt-value {regime_tone}">{escape(result.regime.label)}</div></div>
          <div class="mt-command-cell"><div class="mt-label">Decision</div><div class="mt-value {signal_tone}">{escape(decision.action)}</div></div>
          <div class="mt-command-cell"><div class="mt-label">Confidence</div><div class="mt-value {_tone(result.ensemble.confidence)}">{result.ensemble.confidence:.0%}</div></div>
          <div class="mt-command-cell"><div class="mt-label">Data</div><div class="mt-value {quality_tone}">{escape(result.quality.status)} · {result.quality.quality_score:.0f}</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _kpis(result: EngineResult) -> None:
    latest = result.frame.iloc[-1]
    alignment = result.timeframe_table.attrs.get("alignment", 0.0)
    cards = (
        ("Last", f"{result.price:,.2f}", result.as_of.strftime("%Y-%m-%d %H:%M")),
        (f"{result.ensemble.horizon}D forecast", _pct(result.ensemble.expected_return), f"80% {_pct(result.ensemble.lower)} / {_pct(result.ensemble.upper)}"),
        ("Probability up", _pct(result.ensemble.probability_up, 0), f"disagreement {_pct(result.ensemble.disagreement)}"),
        ("Regime confidence", _pct(result.regime.confidence, 0), f"persistence {result.regime.persistence_bars} bars"),
        ("Horizon alignment", _pct(alignment, 0), f"trend quality {_num(latest.get('trend_quality'))}"),
        ("Suggested weight", _pct(result.decision.suggested_weight), f"risk budget {_pct(result.config.risk_budget)}"),
    )
    html = '<div class="mt-grid">' + "".join(
        f'<div class="mt-kpi"><div class="k">{escape(label)}</div><div class="v">{escape(value)}</div><div class="d">{escape(detail)}</div></div>'
        for label, value, detail in cards
    ) + "</div>"
    st.markdown(html, unsafe_allow_html=True)


def _decision_ticket(result: EngineResult) -> None:
    ticket = result.decision
    color = "#2ed6a1" if ticket.bias == "LONG" else "#ff6174" if ticket.bias == "SHORT" else "#f4bf58"
    levels = "No executable levels"
    if ticket.entry_low is not None:
        levels = (
            f"ENTRY {ticket.entry_low:.2f}—{ticket.entry_high:.2f}  ·  STOP {ticket.stop:.2f}  ·  "
            f"T1 {ticket.target_1:.2f}  ·  T2 {ticket.target_2:.2f}  ·  R/R {ticket.risk_reward:.2f}"
        )
    blockers = " · ".join(ticket.blockers) if ticket.blockers else "No hard blocker"
    st.markdown(
        f"""
        <div class="mt-ticket" style="--ticket-color:{color}">
          <div class="action">{escape(ticket.action)} · {escape(ticket.bias)}</div>
          <div class="thesis">{escape(ticket.thesis)}</div>
          <div class="meta">{escape(levels)}<br>INVALIDATION · {escape(ticket.invalidation)}<br>BLOCKERS · {escape(blockers)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _format_timeframes(table: pd.DataFrame) -> pd.DataFrame:
    display = table.copy()
    for column in ("Return", "Annualized slope", "R²", "Efficiency"):
        if column in display:
            display[column] = display[column].map(lambda value: _pct(value) if column in {"Return", "Annualized slope"} else _num(value))
    if "Directional score" in display:
        display["Directional score"] = display["Directional score"].map(lambda value: f"{value:+.0f}")
    return display


def _model_table(result: EngineResult) -> pd.DataFrame:
    rows = []
    for forecast in result.forecasts:
        rows.append(
            {
                "Model": forecast.name,
                "Family": forecast.family,
                "Status": forecast.status,
                "Forecast": _pct(forecast.expected_return),
                "P(up)": _pct(forecast.probability_up, 0),
                "OOS hit": _pct(forecast.oos_directional_accuracy, 0),
                "OOS IC": _num(forecast.oos_ic),
                "OOS N": forecast.observations,
                "Weight": _pct(forecast.weight, 0),
                "Method": forecast.note,
            }
        )
    return pd.DataFrame(rows)


def render_momentum_trend_terminal(
    ticker: str,
    price_data: pd.DataFrame,
    analysis: dict | None = None,
    benchmark_frames: Mapping[str, pd.DataFrame] | None = None,
    *,
    key_prefix: str = "institutional_mt",
) -> EngineResult | None:
    """Render the full terminal and return its typed result.

    ``analysis`` is accepted for drop-in compatibility with the legacy router;
    the new engine deliberately rebuilds its own auditable result from OHLCV.
    """

    st.markdown(TERMINAL_CSS, unsafe_allow_html=True)
    control_a, control_b, control_c, control_d = st.columns([1.15, 1.0, 1.0, 1.2])
    with control_a:
        profile = st.selectbox("Mandate", [profile.value for profile in Profile], index=1, key=f"{key_prefix}_profile")
    with control_b:
        horizon = st.selectbox("Forecast horizon", [1, 3, 5, 10, 20], index=2, format_func=lambda value: f"{value} bars", key=f"{key_prefix}_horizon")
    with control_c:
        risk_budget = st.select_slider("Risk budget", options=[0.0025, 0.0035, 0.005, 0.0075, 0.01], value=0.005, format_func=lambda value: f"{value:.2%}", key=f"{key_prefix}_risk")
    with control_d:
        neural = st.toggle("Neural sequence model", value=True, key=f"{key_prefix}_neural", help="Chronological holdout is mandatory. The model remains unavailable when history is insufficient.")

    config = EngineConfig.for_profile(Profile(profile), risk_budget=risk_budget, enable_neural_model=neural).with_horizon(horizon)
    try:
        with st.spinner("Filtering regimes and validating model consensus…"):
            result = _compute_cached(str(ticker).upper().strip(), price_data, benchmark_frames, config)
    except Exception as exc:
        st.error(f"Momentum / Trend engine unavailable: {exc}")
        return None

    data_context = price_data.attrs.get("data_context", {}) if hasattr(price_data, "attrs") else {}
    provider = str(data_context.get("provider") or "Inherited terminal feed")
    recency = str(data_context.get("recency") or "UNSPECIFIED")
    provider_status = str(data_context.get("status") or "unknown").upper()
    fallback_note = " · FALLBACK" if data_context.get("fallback_used") else ""

    _command_bar(result)
    st.caption(
        f"Market data · {provider} · {provider_status} · {recency}{fallback_note}. "
        "The model never upgrades reference or delayed data to real-time status."
    )
    _kpis(result)
    _decision_ticket(result)
    status_pills = [
        f'<span class="mt-pill {_tone(result.regime.confidence)}">REGIME {result.regime.confidence:.0%}</span>',
        f'<span class="mt-pill {_tone(result.ensemble.confidence)}">ENSEMBLE {result.ensemble.confidence:.0%}</span>',
        f'<span class="mt-pill {_tone(result.quality.quality_score/100)}">DATA {result.quality.quality_score:.0f}/100</span>',
        f'<span class="mt-pill">FEED {escape(provider.upper())}</span>',
        f'<span class="mt-pill {"warn" if result.regime.transition_risk>.35 else "good"}">TRANSITION {result.regime.transition_risk:.0%}</span>',
        f'<span class="mt-pill">AS OF {result.as_of:%Y-%m-%d %H:%M}</span>',
    ]
    st.markdown('<div class="mt-status-row">' + "".join(status_pills) + "</div>", unsafe_allow_html=True)

    cockpit, regimes_tab, models_tab, risk_tab, audit_tab = st.tabs(
        ["Decision cockpit", "Regimes & horizons", "Models & uncertainty", "Risk & validation", "Audit trail"]
    )
    with cockpit:
        st.plotly_chart(price_decision_chart(result), width="stretch", key=f"{key_prefix}_price_chart", config={"displaylogo": False, "scrollZoom": True})
        left, right = st.columns([1.05, 0.95])
        with left:
            st.markdown("#### Multi-horizon alignment")
            st.dataframe(_format_timeframes(result.timeframe_table), hide_index=True, width="stretch")
        with right:
            st.markdown("#### Scenario map")
            scenario_display = result.scenario_table.copy()
            scenario_display["Probability"] = scenario_display["Probability"].map(lambda value: _pct(value, 0))
            scenario_display["Horizon return"] = scenario_display["Horizon return"].map(_pct)
            scenario_display["Reference"] = scenario_display["Reference"].map(_num)
            st.dataframe(scenario_display, hide_index=True, width="stretch")

    with regimes_tab:
        st.plotly_chart(regime_probability_chart(result), width="stretch", key=f"{key_prefix}_regime_chart", config={"displaylogo": False})
        probability_table = pd.DataFrame(
            [{"Regime": key.replace("_", " ").title(), "Probability": value} for key, value in result.regime.probabilities.items()]
        )
        st.dataframe(
            probability_table,
            hide_index=True,
            width="stretch",
            column_config={"Probability": st.column_config.ProgressColumn(format="percent", min_value=0.0, max_value=1.0)},
        )
        st.caption("The displayed path is filtered forward in time. It is not a full-sample smoothed regime reconstruction.")

    with models_tab:
        st.plotly_chart(model_consensus_chart(result), width="stretch", key=f"{key_prefix}_model_chart", config={"displaylogo": False})
        st.dataframe(_model_table(result), hide_index=True, width="stretch", height=275)
        st.info(
            "TFT / N-BEATS / LSTM are production research candidates, not decorative switches. "
            "This build executes a compact three-hidden-layer sequence MLP only when enough chronological labels exist; "
            "otherwise it reports INSUFFICIENT_DATA and receives zero ensemble weight."
        )

    with risk_tab:
        risk_a, risk_b, risk_c, risk_d = st.columns(4)
        risk_a.metric("Position cap", _pct(result.config.max_position_weight))
        risk_b.metric("Suggested weight", _pct(result.decision.suggested_weight))
        risk_c.metric("Forecast disagreement", _pct(result.ensemble.disagreement))
        risk_d.metric("Transition risk", _pct(result.regime.transition_risk, 0))
        st.plotly_chart(equity_curve_chart(result), width="stretch", key=f"{key_prefix}_equity_chart", config={"displaylogo": False})
        validation = result.validation_table.copy()
        for column in ("CAGR", "Volatility", "Max drawdown", "Hit rate", "Avg turnover"):
            if column in validation:
                validation[column] = validation[column].map(_pct)
        if "Sharpe" in validation:
            validation["Sharpe"] = validation["Sharpe"].map(_num)
        st.dataframe(validation, hide_index=True, width="stretch")
        st.warning("Research diagnostic only: causal, one-bar lagged, transaction-cost adjusted, but not proof of live tradability. No parameter search or execution model is hidden behind this panel.")

    with audit_tab:
        quality_rows = pd.DataFrame(
            [
                {"Control": "Valid rows", "Value": result.quality.rows, "Status": "PASS" if result.quality.rows >= result.config.min_history else "WARN"},
                {"Control": "Missing close", "Value": result.quality.missing_close, "Status": "PASS" if result.quality.missing_close == 0 else "WARN"},
                {"Control": "Missing volume", "Value": _pct(result.quality.missing_volume_ratio), "Status": "PASS" if result.quality.missing_volume_ratio < 0.05 else "WARN"},
                {"Control": "Stale units", "Value": result.quality.stale_bars, "Status": "PASS" if result.quality.stale_bars == 0 else "WARN"},
                {"Control": "Causal feature policy", "Value": "rolling / expanding only", "Status": "PASS"},
                {"Control": "Validation", "Value": "chronological + horizon purge", "Status": "PASS"},
            ]
        )
        quality_rows["Value"] = quality_rows["Value"].astype(str)
        st.dataframe(quality_rows, hide_index=True, width="stretch")
        with st.expander("Methodology and machine-readable audit", expanded=False):
            st.json(result.audit)
        with st.expander("Latest causal feature vector", expanded=False):
            latest_features = result.frame.tail(1).T.reset_index()
            latest_features.columns = ["Feature", "Value"]
            st.dataframe(latest_features, hide_index=True, width="stretch", height=420)
        st.download_button(
            "Export feature audit CSV",
            result.frame.tail(260).to_csv(index=False).encode("utf-8"),
            file_name=f"{result.ticker.lower()}_momentum_trend_audit.csv",
            mime="text/csv",
            key=f"{key_prefix}_download",
        )
    return result
