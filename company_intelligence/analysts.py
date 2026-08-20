# Auto-extracted from Quant Terminal app.py and refactored into package modules.
# Existing runtime logic is preserved unless explicitly marked as a fix.

import os
import re
import time
import requests
from datetime import datetime, timedelta
from html import escape, unescape
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf
import plotly.graph_objects as go

from .common import *
from .providers import *
from .fundamentals import *

# ANALYST CONSENSUS INTELLIGENCE CENTER
# ============================================================

def fmt_ratio(value):
    value = safe_float(value)
    if value is None or pd.isna(value):
        return "N/A"
    return f"{value:.2f}x"


def analyst_metric_signal(score) -> str:
    score = safe_float(score)

    if score is None:
        return "N/A"

    if score >= 80:
        return "Très favorable"
    if score >= 65:
        return "Favorable"
    if score >= 50:
        return "Neutre / mixte"
    if score >= 35:
        return "Risque élevé"
    return "Défavorable"


def analyst_numeric_score(metric: str, value) -> int:
    value = safe_float(value)

    if value is None or pd.isna(value):
        return 50

    if metric in ["Upside Mean", "Upside High"]:
        if value >= 0.30:
            return 90
        if value >= 0.20:
            return 80
        if value >= 0.10:
            return 70
        if value >= 0.03:
            return 60
        if value >= 0:
            return 50
        return 30

    if metric == "Downside Low":
        if value >= -0.10:
            return 80
        if value >= -0.20:
            return 65
        if value >= -0.35:
            return 45
        if value >= -0.50:
            return 30
        return 20

    if metric == "Risk / Reward Mean":
        if value >= 1.50:
            return 90
        if value >= 1.00:
            return 75
        if value >= 0.60:
            return 60
        if value >= 0.30:
            return 45
        return 30

    if metric == "Risk / Reward High":
        if value >= 2.00:
            return 90
        if value >= 1.50:
            return 75
        if value >= 1.00:
            return 60
        if value >= 0.50:
            return 45
        return 30

    if metric == "Target Dispersion":
        if value <= 0.20:
            return 85
        if value <= 0.40:
            return 70
        if value <= 0.70:
            return 50
        if value <= 1.00:
            return 35
        return 25

    if metric == "Bullish Ratio":
        if value >= 0.90:
            return 90
        if value >= 0.75:
            return 75
        if value >= 0.60:
            return 60
        if value >= 0.45:
            return 45
        return 30

    if metric == "Recommendation Mean":
        # yfinance : plus bas = meilleur.
        if value <= 1.5:
            return 90
        if value <= 2.0:
            return 75
        if value <= 2.5:
            return 60
        if value <= 3.0:
            return 45
        return 30

    if metric == "Coverage":
        if value >= 40:
            return 90
        if value >= 25:
            return 80
        if value >= 10:
            return 65
        if value >= 5:
            return 50
        return 35

    return 50


def get_recommendation_row(recommendation_trend: pd.DataFrame, current: bool = True):
    if not isinstance(recommendation_trend, pd.DataFrame) or recommendation_trend.empty:
        return None

    df = recommendation_trend.copy()

    if "Période" not in df.columns:
        return df.iloc[0] if current else df.iloc[-1]

    period_text = df["Période"].astype(str)

    if current and (period_text == "0m").any():
        return df.loc[period_text == "0m"].iloc[0]

    if not current and (period_text == "-3m").any():
        return df.loc[period_text == "-3m"].iloc[0]

    return df.iloc[0] if current else df.iloc[-1]


def compute_row_bullish_ratio(row) -> float | None:
    if row is None:
        return None

    existing = safe_float(row.get("Ratio bullish"))

    if existing is not None:
        return existing

    strong_buy = safe_float(row.get("Strong Buy"), 0) or 0
    buy = safe_float(row.get("Buy"), 0) or 0
    hold = safe_float(row.get("Hold"), 0) or 0
    sell = safe_float(row.get("Sell"), 0) or 0
    strong_sell = safe_float(row.get("Strong Sell"), 0) or 0

    total = strong_buy + buy + hold + sell + strong_sell

    if total == 0:
        return None

    return (strong_buy + buy) / total


def compute_row_recommendation_total(row) -> float | None:
    if row is None:
        return None

    existing_total = safe_float(row.get("Total"))

    if existing_total is not None and existing_total > 0:
        return existing_total

    total = 0

    for col in ["Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"]:
        total += safe_float(row.get(col), 0) or 0

    return total if total > 0 else None


def compute_row_strong_buy_share(row) -> float | None:
    if row is None:
        return None

    total = compute_row_recommendation_total(row)

    if total in [None, 0]:
        return None

    strong_buy = safe_float(row.get("Strong Buy"), 0) or 0
    return strong_buy / total


def analyze_consensus_momentum(recommendation_trend: pd.DataFrame) -> dict:
    current_row = get_recommendation_row(recommendation_trend, current=True)
    old_row = get_recommendation_row(recommendation_trend, current=False)

    current_bullish = compute_row_bullish_ratio(current_row)
    old_bullish = compute_row_bullish_ratio(old_row)

    current_strong_buy = safe_float(current_row.get("Strong Buy"), 0) if current_row is not None else None
    old_strong_buy = safe_float(old_row.get("Strong Buy"), 0) if old_row is not None else None

    current_total = compute_row_recommendation_total(current_row)
    old_total = compute_row_recommendation_total(old_row)

    current_strong_buy_share = compute_row_strong_buy_share(current_row)
    old_strong_buy_share = compute_row_strong_buy_share(old_row)

    bullish_delta = None
    strong_buy_delta = None
    total_delta = None
    strong_buy_share_delta = None

    if current_bullish is not None and old_bullish is not None:
        bullish_delta = current_bullish - old_bullish

    if current_strong_buy is not None and old_strong_buy is not None:
        strong_buy_delta = current_strong_buy - old_strong_buy

    if current_total is not None and old_total is not None:
        total_delta = current_total - old_total

    if current_strong_buy_share is not None and old_strong_buy_share is not None:
        strong_buy_share_delta = current_strong_buy_share - old_strong_buy_share

    high_current_bullish = current_bullish is not None and current_bullish >= 0.85

    if bullish_delta is not None:
        delta_display = f"{bullish_delta * 100:+.2f} pts bullish"
    elif strong_buy_delta is not None:
        delta_display = f"{strong_buy_delta:+.0f} Strong Buy"
    else:
        delta_display = None

    has_signal = any(
        value is not None
        for value in [bullish_delta, strong_buy_delta, strong_buy_share_delta]
    )

    if not has_signal:
        label = "Indisponible"
        score = 50

    else:
        severe_down = (
            (bullish_delta is not None and bullish_delta <= -0.08)
            or (
                current_bullish is not None
                and current_bullish < 0.55
                and old_bullish is not None
            )
        )

        material_down = (
            (bullish_delta is not None and bullish_delta <= -0.03)
            or (
                strong_buy_share_delta is not None
                and strong_buy_share_delta <= -0.08
                and not high_current_bullish
            )
        )

        strong_buy_rotation_down = (
            strong_buy_share_delta is not None
            and strong_buy_share_delta <= -0.08
            and high_current_bullish
        )

        mild_down = (
            (bullish_delta is not None and bullish_delta <= -0.01)
            or (
                strong_buy_share_delta is not None
                and strong_buy_share_delta <= -0.04
            )
            or (
                strong_buy_delta is not None
                and strong_buy_delta <= -2
            )
        )

        material_up = (
            (bullish_delta is not None and bullish_delta >= 0.03)
            or (
                strong_buy_share_delta is not None
                and strong_buy_share_delta >= 0.08
            )
        )

        mild_up = (
            (bullish_delta is not None and bullish_delta >= 0.01)
            or (
                strong_buy_share_delta is not None
                and strong_buy_share_delta >= 0.04
            )
            or (
                strong_buy_delta is not None
                and strong_buy_delta >= 2
            )
        )

        if severe_down:
            label = "Dégradation forte"
            score = 25

        elif material_down:
            label = "Dégradation"
            score = 38

        elif material_up:
            label = "Amélioration"
            score = 75

        elif mild_up:
            label = "Légère amélioration"
            score = 68

        elif strong_buy_rotation_down:
            label = "Légère érosion"
            score = 55

        elif mild_down:
            if high_current_bullish and (bullish_delta is None or bullish_delta > -0.01):
                label = "Stable / légère érosion"
                score = 60
            else:
                label = "Légère érosion"
                score = 52

        else:
            label = "Stable"
            score = 62

    return {
        "label": label,
        "score": score,
        "current_bullish": current_bullish,
        "old_bullish": old_bullish,
        "bullish_delta": bullish_delta,
        "strong_buy_delta": strong_buy_delta,
        "total_delta": total_delta,
        "current_total": current_total,
        "old_total": old_total,
        "current_strong_buy_share": current_strong_buy_share,
        "old_strong_buy_share": old_strong_buy_share,
        "strong_buy_share_delta": strong_buy_share_delta,
        "delta_display": delta_display,
    }


def build_analyst_intelligence(analysis: dict, analysts: dict, scores: dict | None = None) -> dict:
    scores = scores or {}

    latest_price = safe_float(analysis.get("latest_price")) if isinstance(analysis, dict) else None

    target_low = safe_float(analysts.get("target_low"))
    target_mean = safe_float(analysts.get("target_mean"))
    target_median = safe_float(analysts.get("target_median"))
    target_high = safe_float(analysts.get("target_high"))

    upside_mean = safe_float(analysts.get("upside_mean"))
    upside_high = safe_float(analysts.get("upside_high"))
    downside_low = safe_float(analysts.get("downside_low"))

    recommendation_mean = safe_float(analysts.get("recommendation_mean"))
    recommendation_key = analysts.get("recommendation_key") or "N/A"
    number_of_analysts = safe_float(analysts.get("number_of_analysts"))

    recommendation_trend = analysts.get("recommendation_trend", pd.DataFrame())
    momentum = analyze_consensus_momentum(recommendation_trend)

    current_bullish = momentum.get("current_bullish")

    target_dispersion = None
    if latest_price not in [None, 0] and target_low is not None and target_high is not None:
        target_dispersion = (target_high - target_low) / latest_price

    risk_reward_mean = None
    if upside_mean is not None and downside_low is not None and downside_low < 0:
        risk_reward_mean = upside_mean / abs(downside_low)

    risk_reward_high = None
    if upside_high is not None and downside_low is not None and downside_low < 0:
        risk_reward_high = upside_high / abs(downside_low)

    raw_scores = [
        analyst_numeric_score("Upside Mean", upside_mean),
        analyst_numeric_score("Downside Low", downside_low),
        analyst_numeric_score("Risk / Reward Mean", risk_reward_mean),
        analyst_numeric_score("Target Dispersion", target_dispersion),
        analyst_numeric_score("Bullish Ratio", current_bullish),
        analyst_numeric_score("Recommendation Mean", recommendation_mean),
        analyst_numeric_score("Coverage", number_of_analysts),
        momentum.get("score", 50),
    ]

    analyst_score_display = int(clamp(round(np.nanmean(raw_scores)))) if raw_scores else scores.get("analyst_score", 50)

    reading_rows = [
        {
            "Métrique": "Upside Mean",
            "Valeur": fmt_pct(upside_mean),
            "Lecture": "Potentiel moyen implicite du consensus vs prix actuel.",
            "Signal": analyst_metric_signal(analyst_numeric_score("Upside Mean", upside_mean)),
            "Score": analyst_numeric_score("Upside Mean", upside_mean),
        },
        {
            "Métrique": "Downside Low",
            "Valeur": fmt_pct(downside_low),
            "Lecture": "Risque baissier si le scénario analyste le plus prudent se matérialise.",
            "Signal": analyst_metric_signal(analyst_numeric_score("Downside Low", downside_low)),
            "Score": analyst_numeric_score("Downside Low", downside_low),
        },
        {
            "Métrique": "Risk / Reward Mean",
            "Valeur": fmt_ratio(risk_reward_mean),
            "Lecture": "Upside moyen rapporté au downside low. Plus il est élevé, meilleure est l'asymétrie.",
            "Signal": analyst_metric_signal(analyst_numeric_score("Risk / Reward Mean", risk_reward_mean)),
            "Score": analyst_numeric_score("Risk / Reward Mean", risk_reward_mean),
        },
        {
            "Métrique": "Risk / Reward High",
            "Valeur": fmt_ratio(risk_reward_high),
            "Lecture": "Upside high rapporté au downside low. Utile pour lire le scénario optimiste.",
            "Signal": analyst_metric_signal(analyst_numeric_score("Risk / Reward High", risk_reward_high)),
            "Score": analyst_numeric_score("Risk / Reward High", risk_reward_high),
        },
        {
            "Métrique": "Target Dispersion",
            "Valeur": fmt_pct(target_dispersion),
            "Lecture": "Écart entre target high et target low rapporté au prix actuel. Mesure l'incertitude du consensus.",
            "Signal": analyst_metric_signal(analyst_numeric_score("Target Dispersion", target_dispersion)),
            "Score": analyst_numeric_score("Target Dispersion", target_dispersion),
        },
        {
            "Métrique": "Bullish Ratio",
            "Valeur": fmt_pct(current_bullish),
            "Lecture": "Part des recommandations Buy + Strong Buy dans le consensus disponible.",
            "Signal": analyst_metric_signal(analyst_numeric_score("Bullish Ratio", current_bullish)),
            "Score": analyst_numeric_score("Bullish Ratio", current_bullish),
        },
        {
            "Métrique": "Consensus Momentum",
            "Valeur": momentum.get("label", "N/A"),
            "Lecture": "Évolution récente du consensus pondérée par ratio bullish, part de Strong Buy et couverture. Évite de sur-réagir aux micro-variations.",
            "Signal": analyst_metric_signal(momentum.get("score", 50)),
            "Score": momentum.get("score", 50),
        },
        {
            "Métrique": "Recommendation Mean",
            "Valeur": fmt_num(recommendation_mean),
            "Lecture": "Note moyenne yfinance. Plus le chiffre est bas, plus le consensus est positif.",
            "Signal": analyst_metric_signal(analyst_numeric_score("Recommendation Mean", recommendation_mean)),
            "Score": analyst_numeric_score("Recommendation Mean", recommendation_mean),
        },
        {
            "Métrique": "Coverage",
            "Valeur": "N/A" if number_of_analysts is None else int(number_of_analysts),
            "Lecture": "Nombre d'analystes couvrant le titre. Plus la couverture est large, plus le consensus est robuste.",
            "Signal": analyst_metric_signal(analyst_numeric_score("Coverage", number_of_analysts)),
            "Score": analyst_numeric_score("Coverage", number_of_analysts),
        },
    ]

    if analyst_score_display >= 75:
        narrative = (
            "Consensus analystes très favorable. Le marché price encore un potentiel positif, "
            "mais il faut vérifier que l'asymétrie upside/downside reste suffisante."
        )
    elif analyst_score_display >= 60:
        narrative = (
            "Consensus analystes constructif mais pas sans risque. Le target moyen reste au-dessus du prix actuel, "
            "mais la dispersion et le downside low doivent être surveillés."
        )
    elif analyst_score_display >= 45:
        narrative = (
            "Consensus analystes mixte. Le potentiel implicite n'est pas assez net ou la dispersion du consensus réduit la qualité du signal."
        )
    else:
        narrative = (
            "Consensus analystes fragile. Le potentiel implicite est limité ou le risque baissier ressort trop important."
        )

    return {
        "latest_price": latest_price,
        "target_low": target_low,
        "target_mean": target_mean,
        "target_median": target_median,
        "target_high": target_high,
        "upside_mean": upside_mean,
        "upside_high": upside_high,
        "downside_low": downside_low,
        "risk_reward_mean": risk_reward_mean,
        "risk_reward_high": risk_reward_high,
        "target_dispersion": target_dispersion,
        "recommendation_mean": recommendation_mean,
        "recommendation_key": recommendation_key,
        "number_of_analysts": number_of_analysts,
        "bullish_ratio": current_bullish,
        "momentum": momentum,
        "analyst_score_display": analyst_score_display,
        "reading_table": pd.DataFrame(reading_rows),
        "narrative": narrative,
    }


def prepare_recommendation_trend_chart_df(recommendation_trend: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(recommendation_trend, pd.DataFrame) or recommendation_trend.empty:
        return pd.DataFrame()

    df = recommendation_trend.copy()

    if "Période" not in df.columns:
        return df

    def period_order(value):
        text = str(value).replace("m", "").strip()
        try:
            return int(text)
        except Exception:
            return 0

    df["_order"] = df["Période"].apply(period_order)
    df = df.sort_values("_order").drop(columns=["_order"], errors="ignore")

    return df


def render_analyst_consensus_intelligence_center_v1(
    analysis: dict,
    analysts: dict,
    scores: dict | None = None
):
    st.subheader("Analystes — Consensus Intelligence Center")

    intelligence = build_analyst_intelligence(analysis, analysts, scores)

    col1, col2, col3, col4, col5, col6 = st.columns(6)

    col1.metric("Analyst Score", f"{intelligence['analyst_score_display']}/100")
    col2.metric("Target Mean Upside", fmt_pct(intelligence.get("upside_mean")))
    col3.metric("Downside Low", fmt_pct(intelligence.get("downside_low")))
    col4.metric("Upside High", fmt_pct(intelligence.get("upside_high")))
    col5.metric("Bullish Ratio", fmt_pct(intelligence.get("bullish_ratio")))

    momentum = intelligence.get("momentum", {})
    momentum_label = momentum.get("label", "N/A")

    # UI compact : évite que Streamlit coupe "Stable / légère érosion"
    momentum_display = momentum_label
    if momentum_label == "Stable / légère érosion":
        momentum_display = "Stable"

    col6.metric(
        "Consensus Momentum",
        momentum_display,
        delta=momentum.get("delta_display")
    )

    st.caption(intelligence["narrative"])

    with st.expander("Table de lecture analystes", expanded=True):
        st.dataframe(
            intelligence["reading_table"],
            use_container_width=True,
            hide_index=True
        )

    analyst_view = st.radio(
        "Vue analystes",
        ["Target Range", "Risk / Reward", "Consensus Trend", "Recommendation Mix"],
        horizontal=True,
        key="analyst_consensus_view_v1"
    )

    latest_price = intelligence.get("latest_price")
    target_low = intelligence.get("target_low")
    target_mean = intelligence.get("target_mean")
    target_median = intelligence.get("target_median")
    target_high = intelligence.get("target_high")

    recommendation_trend = analysts.get("recommendation_trend", pd.DataFrame())

    if analyst_view == "Target Range":
        target_points = []

        for label, value in [
            ("Target Low", target_low),
            ("Prix actuel", latest_price),
            ("Target Median", target_median),
            ("Target Mean", target_mean),
            ("Target High", target_high),
        ]:
            value = safe_float(value)
            if value is not None:
                target_points.append({"Niveau": label, "Prix": value})

        target_df = pd.DataFrame(target_points)

        if target_df.empty:
            st.info("Targets analystes indisponibles pour ce ticker.")
        else:
            k1, k2, k3 = st.columns(3)
            k1.metric("Prix actuel", fmt_price(latest_price))
            k2.metric("Target Mean", fmt_price(target_mean), delta=fmt_pct(intelligence.get("upside_mean")))
            k3.metric("Target High", fmt_price(target_high), delta=fmt_pct(intelligence.get("upside_high")))

            fig = go.Figure()

            if target_low is not None and target_high is not None:
                fig.add_trace(go.Scatter(
                    x=[target_low, target_high],
                    y=[0, 0],
                    mode="lines",
                    name="Range Low → High",
                    line=dict(width=14),
                    hovertemplate="Range analystes<br>Low: %{x:.2f}<extra></extra>"
                ))

            for label, value in [
                ("Target Low", target_low),
                ("Prix actuel", latest_price),
                ("Target Median", target_median),
                ("Target Mean", target_mean),
                ("Target High", target_high),
            ]:
                value = safe_float(value)

                if value is None:
                    continue

                fig.add_trace(go.Scatter(
                    x=[value],
                    y=[0],
                    mode="markers",
                    name=label,
                    marker=dict(size=14),
                    hovertemplate=f"{label}<br>Prix: %{{x:.2f}}<extra></extra>"
                ))

            if latest_price is not None:
                fig.add_vline(
                    x=latest_price,
                    line_dash="dash",
                    annotation_text="Prix actuel",
                    annotation_position="top"
                )

            fig.update_layout(
                height=360,
                title="Target Range — position du prix actuel dans le consensus",
                xaxis_title="Prix",
                yaxis=dict(visible=False, range=[-1, 1]),
                hovermode="x",
                margin=dict(l=20, r=20, t=70, b=40)
            )

            st.plotly_chart(fig, use_container_width=True)

            display_target_df = target_df.copy()
            display_target_df["Prix"] = display_target_df["Prix"].apply(fmt_price)

            st.dataframe(display_target_df, use_container_width=True, hide_index=True)

    elif analyst_view == "Risk / Reward":
        rr_rows = []

        if intelligence.get("downside_low") is not None:
            rr_rows.append({
                "Scénario": "Downside Low",
                "Potentiel": intelligence.get("downside_low"),
                "Lecture": "Risque baissier vers le target low",
            })

        if intelligence.get("upside_mean") is not None:
            rr_rows.append({
                "Scénario": "Upside Mean",
                "Potentiel": intelligence.get("upside_mean"),
                "Lecture": "Potentiel moyen du consensus",
            })

        if intelligence.get("upside_high") is not None:
            rr_rows.append({
                "Scénario": "Upside High",
                "Potentiel": intelligence.get("upside_high"),
                "Lecture": "Potentiel du scénario optimiste",
            })

        rr_df = pd.DataFrame(rr_rows)

        k1, k2, k3 = st.columns(3)
        k1.metric("Risk / Reward Mean", fmt_ratio(intelligence.get("risk_reward_mean")))
        k2.metric("Risk / Reward High", fmt_ratio(intelligence.get("risk_reward_high")))
        k3.metric("Target Dispersion", fmt_pct(intelligence.get("target_dispersion")))

        if rr_df.empty:
            st.info("Risk / reward analyste indisponible.")
        else:
            fig = go.Figure()

            fig.add_trace(go.Bar(
                x=rr_df["Potentiel"],
                y=rr_df["Scénario"],
                orientation="h",
                text=rr_df["Potentiel"].apply(fmt_pct),
                textposition="auto",
                name="Potentiel"
            ))

            fig.add_vline(x=0, line_dash="dash")

            fig.update_layout(
                height=420,
                title="Risk / Reward analystes — downside vs upside",
                xaxis_title="Potentiel vs prix actuel",
                yaxis_title="Scénario",
                margin=dict(l=20, r=20, t=70, b=40)
            )

            fig.update_xaxes(tickformat=".0%")

            st.plotly_chart(fig, use_container_width=True)

            display_rr = rr_df.copy()
            display_rr["Potentiel"] = display_rr["Potentiel"].apply(fmt_pct)
            st.dataframe(display_rr, use_container_width=True, hide_index=True)

    elif analyst_view == "Consensus Trend":
        trend_df = prepare_recommendation_trend_chart_df(recommendation_trend)

        if trend_df.empty:
            st.info("Historique du consensus analystes indisponible.")
        else:
            display_trend = trend_df.copy()

            if "Ratio bullish" in display_trend.columns:
                display_trend["Ratio bullish"] = display_trend["Ratio bullish"].apply(fmt_pct)

            fig = go.Figure()

            for col in ["Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"]:
                if col in trend_df.columns:
                    fig.add_trace(go.Bar(
                        x=trend_df["Période"],
                        y=trend_df[col],
                        name=col
                    ))

            if "Ratio bullish" in trend_df.columns:
                fig.add_trace(go.Scatter(
                    x=trend_df["Période"],
                    y=trend_df["Ratio bullish"],
                    mode="lines+markers+text",
                    name="Ratio bullish",
                    yaxis="y2",
                    text=trend_df["Ratio bullish"].apply(fmt_pct),
                    textposition="top center"
                ))

            fig.update_layout(
                height=460,
                title="Consensus trend — recommandations + ratio bullish",
                barmode="stack",
                yaxis_title="Nombre de recommandations",
                yaxis2=dict(
                    title="Ratio bullish",
                    overlaying="y",
                    side="right",
                    tickformat=".0%",
                    range=[0, 1]
                ),
                hovermode="x unified",
                margin=dict(l=20, r=20, t=70, b=40)
            )

            st.plotly_chart(fig, use_container_width=True)

            current_row = get_recommendation_row(recommendation_trend, current=True)
            old_row = get_recommendation_row(recommendation_trend, current=False)

            if current_row is not None and old_row is not None:
                delta_rows = []

                for col in ["Strong Buy", "Buy", "Hold", "Sell", "Strong Sell", "Total"]:
                    if col not in recommendation_trend.columns:
                        continue

                    current_value = safe_float(current_row.get(col), 0) or 0
                    old_value = safe_float(old_row.get(col), 0) or 0

                    delta_rows.append({
                        "Métrique": col,
                        "Ancien": old_value,
                        "Actuel": current_value,
                        "Variation": current_value - old_value,
                    })

                old_bullish = compute_row_bullish_ratio(old_row)
                current_bullish = compute_row_bullish_ratio(current_row)

                delta_rows.append({
                    "Métrique": "Ratio bullish",
                    "Ancien": fmt_pct(old_bullish),
                    "Actuel": fmt_pct(current_bullish),
                    "Variation": fmt_pct(
                        None if old_bullish is None or current_bullish is None
                        else current_bullish - old_bullish
                    ),
                })

                st.subheader("Delta consensus")
                st.dataframe(
                    pd.DataFrame(delta_rows),
                    use_container_width=True,
                    hide_index=True
                )

    elif analyst_view == "Recommendation Mix":
        current_row = get_recommendation_row(recommendation_trend, current=True)

        if current_row is None:
            recent_recommendations = analysts.get("recent_recommendations")

            if recent_recommendations:
                st.subheader("Dernières recommandations disponibles")
                st.dataframe(
                    pd.DataFrame(recent_recommendations),
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("Répartition détaillée des recommandations indisponible.")
        else:
            mix_rows = []

            for col in ["Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"]:
                if col not in recommendation_trend.columns:
                    continue

                mix_rows.append({
                    "Recommandation": col,
                    "Nombre": safe_float(current_row.get(col), 0) or 0,
                })

            mix_df = pd.DataFrame(mix_rows)

            if mix_df.empty:
                st.info("Répartition détaillée des recommandations indisponible.")
            else:
                fig = go.Figure()

                fig.add_trace(go.Bar(
                    x=mix_df["Recommandation"],
                    y=mix_df["Nombre"],
                    text=mix_df["Nombre"],
                    textposition="auto",
                    name="Recommandations"
                ))

                fig.update_layout(
                    height=420,
                    title="Recommendation Mix — consensus actuel",
                    xaxis_title="Recommandation",
                    yaxis_title="Nombre d'analystes",
                    margin=dict(l=20, r=20, t=70, b=40)
                )

                st.plotly_chart(fig, use_container_width=True)

                st.dataframe(mix_df, use_container_width=True, hide_index=True)


