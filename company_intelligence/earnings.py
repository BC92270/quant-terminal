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
from .analysts import *
from .financials import *
from .valuation import *

def normalize_ticker_for_compare(value) -> str:
    text = str(value or "").upper().strip()
    text = text.replace(".", "-")
    return text


def get_company_data_symbol(company_data: dict) -> str:
    candidates = []

    if isinstance(company_data, dict):
        candidates += [
            company_data.get("ticker"),
            company_data.get("symbol"),
        ]

        info = company_data.get("info", {})
        if isinstance(info, dict):
            candidates += [
                info.get("symbol"),
                info.get("ticker"),
            ]

        fmp = company_data.get("fmp", {})
        if isinstance(fmp, dict):
            candidates += [
                fmp.get("symbol"),
                fmp.get("ticker"),
            ]

            profile = fmp.get("profile")
            if isinstance(profile, list) and profile:
                first_profile = profile[0]
                if isinstance(first_profile, dict):
                    candidates += [
                        first_profile.get("symbol"),
                        first_profile.get("ticker"),
                    ]

            elif isinstance(profile, dict):
                candidates += [
                    profile.get("symbol"),
                    profile.get("ticker"),
                ]

    for candidate in candidates:
        normalized = normalize_ticker_for_compare(candidate)
        if normalized:
            return normalized

    return ""


def fmp_record_matches_company(record: dict, ticker: str) -> bool:
    """
    Filtre anti-calendrier global FMP.

    FMP earnings calendar peut renvoyer des lignes d'autres sociétés.
    Si le record expose un symbol/ticker, on exige qu'il corresponde au ticker analysé.
    Si aucun symbol n'est fourni, on garde la ligne pour ne pas supprimer de donnée utile.
    """
    if not isinstance(record, dict):
        return False

    if not ticker:
        return True

    record_symbol = None

    for key in ["symbol", "ticker"]:
        if record.get(key):
            record_symbol = record.get(key)
            break

    if record_symbol is None:
        return True

    return normalize_ticker_for_compare(record_symbol) == normalize_ticker_for_compare(ticker)


def build_earnings_surprise_df(company_data: dict) -> pd.DataFrame:
    rows = []
    ticker = get_company_data_symbol(company_data)
    fmp = company_data.get("fmp", {})

    raw_rows = []
    raw_rows += fmp.get("earnings_calendar", [])
    raw_rows += fmp.get("earnings_surprises", [])

    for item in raw_rows:
        if not isinstance(item, dict):
            continue
        
        if not fmp_record_matches_company(item, ticker):
            continue

        date = parse_date_safe(first_present(item, ["date", "fiscalDateEnding"]))
        if pd.isna(date):
            continue

        eps_actual = safe_float(first_present(item, [
            "eps", "actualEarningResult", "actualEPS", "reportedEPS", "epsActual"
        ]))

        eps_estimate = safe_float(first_present(item, [
            "epsEstimated", "estimatedEarning", "estimatedEPS", "epsEstimate", "estimatedEps"
        ]))

        revenue_actual = safe_float(first_present(item, [
            "revenue", "actualRevenue", "revenueActual"
        ]))

        revenue_estimate = safe_float(first_present(item, [
            "revenueEstimated", "estimatedRevenue", "revenueEstimate"
        ]))

        eps_surprise = None
        eps_surprise_pct = None

        if eps_actual is not None and eps_estimate not in [None, 0]:
            eps_surprise = eps_actual - eps_estimate
            eps_surprise_pct = eps_surprise / abs(eps_estimate)

        revenue_surprise = None
        revenue_surprise_pct = None

        if revenue_actual is not None and revenue_estimate not in [None, 0]:
            revenue_surprise = revenue_actual - revenue_estimate
            revenue_surprise_pct = revenue_surprise / abs(revenue_estimate)

        rows.append({
            "Date": date,
            "Period": period_label_from_record(item, "Trimestriel"),
            "EPS Actual": eps_actual,
            "EPS Estimate": eps_estimate,
            "EPS Surprise": eps_surprise,
            "EPS Surprise %": eps_surprise_pct,
            "Revenue Actual": revenue_actual,
            "Revenue Estimate": revenue_estimate,
            "Revenue Surprise": revenue_surprise,
            "Revenue Surprise %": revenue_surprise_pct,
            "Source": "FMP",
        })

    earnings_dates = company_data.get("earnings_dates", pd.DataFrame())

    if isinstance(earnings_dates, pd.DataFrame) and not earnings_dates.empty:
        yf_df = earnings_dates.copy().reset_index()

        for _, row in yf_df.iterrows():
            date = parse_date_safe(row.iloc[0])

            eps_estimate = safe_float(row.get("EPS Estimate"))
            eps_actual = safe_float(row.get("Reported EPS"))
            surprise_pct = safe_float(row.get("Surprise(%)"))

            if eps_actual is None and eps_estimate is None:
                continue

            eps_surprise = None
            if eps_actual is not None and eps_estimate is not None:
                eps_surprise = eps_actual - eps_estimate

            rows.append({
                "Date": date,
                "Period": period_label(date, "Trimestriel") if not pd.isna(date) else "N/A",
                "EPS Actual": eps_actual,
                "EPS Estimate": eps_estimate,
                "EPS Surprise": eps_surprise,
                "EPS Surprise %": surprise_pct,
                "Revenue Actual": None,
                "Revenue Estimate": None,
                "Revenue Surprise": None,
                "Revenue Surprise %": None,
                "Source": "yfinance",
            })

    finnhub_surprises = finnhub_earnings_calendar_to_surprise_df(company_data)

    if not finnhub_surprises.empty:
        for _, row in finnhub_surprises.iterrows():
            rows.append(row.to_dict())

    alpha_surprises = alpha_earnings_history_to_surprise_df(company_data)

    if not alpha_surprises.empty:
        for _, row in alpha_surprises.iterrows():
            rows.append(row.to_dict())

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # Provider payloads mix ISO strings, Python dates and timezone-aware
    # timestamps. Normalize once before sorting to avoid heterogeneous object
    # comparisons in pandas and keep a deterministic newest-first calendar.
    df["Date"] = pd.to_datetime(
        df["Date"],
        errors="coerce",
        utc=True,
    ).dt.tz_convert(None)

    priority = {"FMP": 0, "Finnhub": 1, "Alpha Vantage": 2, "yfinance": 3}
    df["_priority"] = df["Source"].map(lambda x: priority.get(str(x), 9))
    df = df.sort_values(
        ["Date", "_priority"],
        ascending=[False, True],
        na_position="last",
        kind="stable",
    )
    df = df.drop_duplicates(subset=["Date", "Period"], keep="first")
    df = df.drop(columns=["_priority"], errors="ignore")
    return df


def normalize_surprise_pct_value(value):
    value = safe_float(value)

    if value is None or pd.isna(value):
        return None

    # Certaines sources donnent 12.3 pour 12.3%, d'autres 0.123.
    # On standardise en format décimal : 0.123 = 12.3%.
    if abs(value) > 3:
        return value / 100.0

    return value


def earnings_verdict(row) -> str:
    eps_pct = safe_float(row.get("EPS Surprise %"))
    rev_pct = safe_float(row.get("Revenue Surprise %"))

    has_eps = eps_pct is not None
    has_rev = rev_pct is not None

    if not has_eps and not has_rev:
        return "N/A"

    # Cas EPS seul : ne pas appeler ça Mixed.
    if has_eps and not has_rev:
        if eps_pct >= 0.05:
            return "EPS Strong Beat / Revenue N/A"
        if eps_pct >= 0:
            return "EPS Beat / Revenue N/A"
        return "EPS Miss / Revenue N/A"

    # Cas Revenue seul.
    if has_rev and not has_eps:
        if rev_pct >= 0.03:
            return "Revenue Strong Beat / EPS N/A"
        if rev_pct >= 0:
            return "Revenue Beat / EPS N/A"
        return "Revenue Miss / EPS N/A"

    # Cas EPS + Revenue disponibles.
    strong_eps = eps_pct >= 0.05
    strong_rev = rev_pct >= 0.03

    eps_ok = eps_pct >= 0
    rev_ok = rev_pct >= 0

    if strong_eps and strong_rev:
        return "Strong Beat"

    if eps_ok and rev_ok:
        return "Beat"

    if not eps_ok and not rev_ok:
        return "Miss"

    if eps_ok and not rev_ok:
        return "EPS Beat / Revenue Miss"

    if not eps_ok and rev_ok:
        return "EPS Miss / Revenue Beat"

    return "Mixed"


def compute_earnings_quality_score(df: pd.DataFrame) -> int:
    if df is None or df.empty:
        return 0

    eps = pd.to_numeric(df.get("EPS Surprise %"), errors="coerce").dropna()
    rev = pd.to_numeric(df.get("Revenue Surprise %"), errors="coerce").dropna()

    if eps.empty and rev.empty:
        return 0

    eps_beat = float((eps > 0).mean()) if not eps.empty else 0.5
    rev_beat = float((rev > 0).mean()) if not rev.empty else 0.5

    avg_eps = float(eps.clip(-0.50, 0.50).mean()) if not eps.empty else 0.0
    avg_rev = float(rev.clip(-0.50, 0.50).mean()) if not rev.empty else 0.0

    score = 50
    score += (eps_beat - 0.5) * 30
    score += (rev_beat - 0.5) * 30
    score += max(-0.20, min(0.20, avg_eps + avg_rev)) * 50

    return int(max(0, min(100, round(score))))


def fmt_pct_with_observation_count(value, count: int) -> str:
    count = int(count or 0)

    if value is None or pd.isna(value):
        return f"N/A · n={count}"

    return f"{fmt_pct(value)} · n={count}"


def build_earnings_forward_estimates_df(
    company_data: dict,
    base_earnings_df: pd.DataFrame,
    max_forward_periods: int = 4
) -> pd.DataFrame:
    """
    Ajoute au Earnings Intelligence Center les estimates EPS / Revenue futures
    déjà disponibles dans le pipeline income estimates.

    Important :
    - ne touche pas aux actuals ;
    - ne modifie pas build_income_estimate_long ;
    - ne modifie pas les explorers financiers ;
    - ajoute uniquement des lignes estimate-only forward.
    """
    try:
        estimates = build_income_estimate_long(company_data, "Trimestriel")
    except Exception:
        return pd.DataFrame()

    if estimates is None or estimates.empty:
        return pd.DataFrame()

    work = estimates[
        estimates["Metric"].isin(["EPS", "Revenue"])
        & estimates["Estimate"].notna()
    ].copy()

    if work.empty:
        return pd.DataFrame()

    work["Date Estimate"] = pd.to_datetime(work["Date Estimate"], errors="coerce")
    work["Estimate"] = pd.to_numeric(work["Estimate"], errors="coerce")
    work = work.dropna(subset=["Date Estimate", "Estimate", "Period"])

    if work.empty:
        return pd.DataFrame()

    latest_actual_sort = None

    if isinstance(base_earnings_df, pd.DataFrame) and not base_earnings_df.empty:
        base = base_earnings_df.copy()
        base["Date"] = pd.to_datetime(base.get("Date"), errors="coerce")

        has_actual = (
            base.get("EPS Actual", pd.Series(index=base.index, dtype=float)).notna()
            | base.get("Revenue Actual", pd.Series(index=base.index, dtype=float)).notna()
        )

        actual_base = base[has_actual].copy()

        if not actual_base.empty:
            actual_base["_PeriodSort"] = actual_base.apply(
                lambda row: period_sort_key(row.get("Period"), row.get("Date")),
                axis=1
            )
            latest_actual_sort = actual_base["_PeriodSort"].max()

    if latest_actual_sort is None:
        latest_actual_sort = -1

    work["_PeriodSort"] = work.apply(
        lambda row: period_sort_key(row.get("Period"), row.get("Date Estimate")),
        axis=1
    )

    # On garde uniquement les périodes après le dernier earnings actual connu.
    work = work[work["_PeriodSort"] > latest_actual_sort].copy()

    if work.empty:
        return pd.DataFrame()

    work["_priority"] = work["Source Estimate"].apply(estimate_source_priority)

    work = work.sort_values(
        ["Period", "Metric", "_priority", "Date Estimate"],
        ascending=[True, True, True, False],
        na_position="last"
    )

    work = work.drop_duplicates(
        subset=["Period", "Metric"],
        keep="first"
    )

    periods = (
        work[["Period", "_PeriodSort"]]
        .drop_duplicates()
        .sort_values("_PeriodSort")
        .head(max_forward_periods)["Period"]
        .tolist()
    )

    work = work[work["Period"].isin(periods)].copy()

    if work.empty:
        return pd.DataFrame()

    pivot_values = work.pivot_table(
        index=["Period"],
        columns="Metric",
        values="Estimate",
        aggfunc="first"
    ).reset_index()

    pivot_dates = (
        work
        .groupby("Period", as_index=False)["Date Estimate"]
        .max()
    )

    pivot_sources = (
        work
        .groupby("Period", as_index=False)["Source Estimate"]
        .agg(lambda s: " / ".join(sorted(set(str(x) for x in s if str(x)))))
    )

    pivot_sort = (
        work[["Period", "_PeriodSort"]]
        .drop_duplicates()
    )

    merged = (
        pivot_values
        .merge(pivot_dates, on="Period", how="left")
        .merge(pivot_sources, on="Period", how="left")
        .merge(pivot_sort, on="Period", how="left")
        .sort_values("_PeriodSort")
    )

    rows = []

    for _, row in merged.iterrows():
        eps_estimate = safe_float(row.get("EPS"))
        revenue_estimate = safe_float(row.get("Revenue"))

        if eps_estimate is None and revenue_estimate is None:
            continue

        rows.append({
            "Date": row.get("Date Estimate"),
            "Period": row.get("Period"),
            "EPS Actual": None,
            "EPS Estimate": eps_estimate,
            "EPS Surprise": None,
            "EPS Surprise %": None,
            "Revenue Actual": None,
            "Revenue Estimate": revenue_estimate,
            "Revenue Surprise": None,
            "Revenue Surprise %": None,
            "Source": f"Forward estimates: {row.get('Source Estimate', 'income estimates')}",
            "Forward": True,
        })

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def clean_earnings_intelligence_df(df: pd.DataFrame, max_periods: int = 16) -> pd.DataFrame:
    """
    Transforme le dataframe brut earnings surprise en table analytique propre :
    - dates valides ;
    - surprises % normalisées ;
    - uniquement lignes avec actual + estimate exploitable ;
    - une seule ligne par période ;
    - historique limité aux derniers earnings.
    """
    if df is None or df.empty:
        return pd.DataFrame()

    clean = df.copy()

    required_cols = [
        "Date",
        "Period",
        "EPS Actual",
        "EPS Estimate",
        "EPS Surprise",
        "EPS Surprise %",
        "Revenue Actual",
        "Revenue Estimate",
        "Revenue Surprise",
        "Revenue Surprise %",
        "Source",
    ]

    for col in required_cols:
        if col not in clean.columns:
            clean[col] = np.nan

    clean["Date"] = pd.to_datetime(clean["Date"], errors="coerce")
    clean = clean.dropna(subset=["Date", "Period"])

    if clean.empty:
        return pd.DataFrame()

    numeric_cols = [
        "EPS Actual",
        "EPS Estimate",
        "EPS Surprise",
        "EPS Surprise %",
        "Revenue Actual",
        "Revenue Estimate",
        "Revenue Surprise",
        "Revenue Surprise %",
    ]

    for col in numeric_cols:
        clean[col] = pd.to_numeric(clean[col], errors="coerce")

    clean["EPS Surprise %"] = clean["EPS Surprise %"].apply(normalize_surprise_pct_value)
    clean["Revenue Surprise %"] = clean["Revenue Surprise %"].apply(normalize_surprise_pct_value)

    eps_surprise_missing = (
        clean["EPS Surprise"].isna()
        & clean["EPS Actual"].notna()
        & clean["EPS Estimate"].notna()
    )

    clean.loc[eps_surprise_missing, "EPS Surprise"] = (
        clean.loc[eps_surprise_missing, "EPS Actual"]
        - clean.loc[eps_surprise_missing, "EPS Estimate"]
    )

    eps_pct_missing = (
        clean["EPS Surprise %"].isna()
        & clean["EPS Surprise"].notna()
        & clean["EPS Estimate"].notna()
        & (clean["EPS Estimate"] != 0)
    )

    clean.loc[eps_pct_missing, "EPS Surprise %"] = (
        clean.loc[eps_pct_missing, "EPS Surprise"]
        / clean.loc[eps_pct_missing, "EPS Estimate"].abs()
    )

    revenue_surprise_missing = (
        clean["Revenue Surprise"].isna()
        & clean["Revenue Actual"].notna()
        & clean["Revenue Estimate"].notna()
    )

    clean.loc[revenue_surprise_missing, "Revenue Surprise"] = (
        clean.loc[revenue_surprise_missing, "Revenue Actual"]
        - clean.loc[revenue_surprise_missing, "Revenue Estimate"]
    )

    revenue_pct_missing = (
        clean["Revenue Surprise %"].isna()
        & clean["Revenue Surprise"].notna()
        & clean["Revenue Estimate"].notna()
        & (clean["Revenue Estimate"] != 0)
    )

    clean.loc[revenue_pct_missing, "Revenue Surprise %"] = (
        clean.loc[revenue_pct_missing, "Revenue Surprise"]
        / clean.loc[revenue_pct_missing, "Revenue Estimate"].abs()
    )

    if "Forward" not in clean.columns:
        clean["Forward"] = False

    clean["Forward"] = clean["Forward"].fillna(False).astype(bool)

    has_usable_eps = clean["EPS Actual"].notna() & clean["EPS Estimate"].notna()
    has_usable_revenue = clean["Revenue Actual"].notna() & clean["Revenue Estimate"].notna()

    # Important :
    # - les lignes historiques doivent avoir Actual + Estimate ;
    # - les lignes forward peuvent être Estimate only, mais uniquement si elles ont été
    #   explicitement ajoutées par build_earnings_forward_estimates_df().
    clean = clean[
        has_usable_eps
        | has_usable_revenue
        | clean["Forward"]
    ].copy()

    if clean.empty:
        return pd.DataFrame()

    clean["_PeriodSort"] = clean.apply(
        lambda row: period_sort_key(row.get("Period"), row.get("Date")),
        axis=1
    )

    clean["_priority"] = clean["Source"].map(
        lambda x: {
            "FMP": 0,
            "Finnhub": 1,
            "Alpha Vantage": 2,
            "yfinance": 3,
        }.get(str(x), 9)
    )

    clean["_quality"] = 0
    clean.loc[has_usable_eps.reindex(clean.index, fill_value=False), "_quality"] += 2
    clean.loc[has_usable_revenue.reindex(clean.index, fill_value=False), "_quality"] += 2

    # Dédoublonnage analytique : une seule ligne par période.
    # On garde la ligne la plus complète, puis la meilleure source.
    clean = clean.sort_values(
        ["_PeriodSort", "_quality", "_priority", "Date"],
        ascending=[False, False, True, False],
        na_position="last"
    )

    clean = clean.drop_duplicates(subset=["Period"], keep="first")

    clean = clean.sort_values("_PeriodSort").tail(max_periods).copy()

    clean["Verdict"] = clean.apply(earnings_verdict, axis=1)

    return clean


def render_earnings_surprise_center_v6(company_data: dict):
    st.subheader("Actual vs Estimate — Earnings Intelligence Center")

    raw_df = build_earnings_surprise_df(company_data)

    forward_df = build_earnings_forward_estimates_df(
        company_data=company_data,
        base_earnings_df=raw_df,
        max_forward_periods=4
    )

    if isinstance(forward_df, pd.DataFrame) and not forward_df.empty:
        raw_df = pd.concat([raw_df, forward_df], ignore_index=True)

    df = clean_earnings_intelligence_df(raw_df, max_periods=20)

    if df.empty:
        st.info(
            "Aucune donnée earnings actual vs estimate exploitable. "
            "La section nécessite au moins EPS ou Revenue avec actual + estimate."
        )
        return

    df = df.sort_values("_PeriodSort").copy()

    latest_actual_df = df[
        (~df.get("Forward", False).astype(bool))
        & (
            df["EPS Actual"].notna()
            | df["Revenue Actual"].notna()
        )
    ].copy()

    if not latest_actual_df.empty:
        latest = latest_actual_df.iloc[-1]
    else:
        latest = df.iloc[-1]

    eps_surprises = pd.to_numeric(df["EPS Surprise %"], errors="coerce").dropna()
    revenue_surprises = pd.to_numeric(df["Revenue Surprise %"], errors="coerce").dropna()

    eps_n = int(len(eps_surprises))
    revenue_n = int(len(revenue_surprises))

    eps_beat_rate = float((eps_surprises > 0).mean()) if eps_n > 0 else None
    revenue_beat_rate = float((revenue_surprises > 0).mean()) if revenue_n > 0 else None

    avg_eps_surprise = float(eps_surprises.mean()) if eps_n > 0 else None
    avg_revenue_surprise = float(revenue_surprises.mean()) if revenue_n > 0 else None

    quality_score = compute_earnings_quality_score(df)

    latest_date = latest.get("Date")
    latest_date_text = latest_date.strftime("%Y-%m-%d") if not pd.isna(latest_date) else "N/A"

    kpi_cols = st.columns(6)

    kpi_cols[0].metric(
        "Dernier earnings",
        str(latest.get("Period", "N/A")),
        latest_date_text
    )

    kpi_cols[1].metric(
        "EPS beat rate",
        fmt_pct_with_observation_count(eps_beat_rate, eps_n)
    )

    kpi_cols[2].metric(
        "Revenue beat rate",
        fmt_pct_with_observation_count(revenue_beat_rate, revenue_n)
    )

    kpi_cols[3].metric(
        "Avg EPS surprise",
        fmt_pct_with_observation_count(avg_eps_surprise, eps_n)
    )

    kpi_cols[4].metric(
        "Avg Revenue surprise",
        fmt_pct_with_observation_count(avg_revenue_surprise, revenue_n)
    )

    kpi_cols[5].metric(
        "Earnings Quality",
        f"{quality_score}/100"
    )

    coverage_notes = []

    if eps_n < 3:
        coverage_notes.append(f"EPS coverage faible : n={eps_n}")

    if revenue_n < 3:
        coverage_notes.append(f"Revenue coverage faible : n={revenue_n}")

    if coverage_notes:
        st.caption("⚠️ " + " · ".join(coverage_notes))

    control_cols = st.columns([2, 1])

    view_mode = control_cols[0].selectbox(
        "Vue affichée",
        ["Surprise Timeline", "Actual vs Estimate"],
        key="earnings_intelligence_view"
    )

    selected_metric = "EPS"

    if view_mode == "Actual vs Estimate":
        selected_metric = control_cols[1].selectbox(
            "Métrique",
            ["EPS", "Revenue"],
            key="earnings_intelligence_metric"
        )
    else:
        control_cols[1].markdown("**Métrique**")
        control_cols[1].caption("Timeline combinée : EPS Surprise % + Revenue Surprise %")

    period_order = df["Period"].astype(str).tolist()

    fig = go.Figure()

    if view_mode == "Surprise Timeline":
        eps_plot = df.copy()
        revenue_plot = df.copy()

        if eps_plot["EPS Surprise %"].notna().any():
            fig.add_trace(go.Bar(
                x=eps_plot["Period"],
                y=eps_plot["EPS Surprise %"].clip(-1.0, 1.0),
                name="EPS Surprise %"
            ))

        if revenue_plot["Revenue Surprise %"].notna().any():
            fig.add_trace(go.Scatter(
                x=revenue_plot["Period"],
                y=revenue_plot["Revenue Surprise %"].clip(-1.0, 1.0),
                mode="lines+markers",
                name="Revenue Surprise %"
            ))

        fig.update_layout(
            height=500,
            title="Surprise Timeline — derniers earnings",
            yaxis=dict(
                title="Surprise %",
                tickformat=".0%"
            ),
            barmode="relative",
            margin=dict(l=20, r=20, t=70, b=40)
        )

    else:
        if selected_metric == "EPS":
            valid = df[
                df["EPS Actual"].notna()
                | df["EPS Estimate"].notna()
            ].copy()

            if valid.empty:
                st.info("Aucune donnée EPS actual/estimate exploitable.")
                return

            fig.add_trace(go.Bar(
                x=valid["Period"],
                y=valid["EPS Actual"],
                name="EPS Actual"
            ))

            fig.add_trace(go.Bar(
                x=valid["Period"],
                y=valid["EPS Estimate"],
                name="EPS Estimate"
            ))

            if valid["EPS Surprise %"].notna().any():
                fig.add_trace(go.Scatter(
                    x=valid["Period"],
                    y=valid["EPS Surprise %"].clip(-1.0, 1.0),
                    mode="lines+markers",
                    name="EPS Surprise %",
                    yaxis="y2"
                ))

            yaxis_title = "EPS"

        else:
            valid = df[
                df["Revenue Actual"].notna()
                | df["Revenue Estimate"].notna()
            ].copy()

            if valid.empty:
                st.info("Aucune donnée Revenue actual/estimate exploitable.")
                return

            fig.add_trace(go.Bar(
                x=valid["Period"],
                y=valid["Revenue Actual"],
                name="Revenue Actual"
            ))

            fig.add_trace(go.Bar(
                x=valid["Period"],
                y=valid["Revenue Estimate"],
                name="Revenue Estimate"
            ))

            if valid["Revenue Surprise %"].notna().any():
                fig.add_trace(go.Scatter(
                    x=valid["Period"],
                    y=valid["Revenue Surprise %"].clip(-1.0, 1.0),
                    mode="lines+markers",
                    name="Revenue Surprise %",
                    yaxis="y2"
                ))

            yaxis_title = "Revenue"

        fig.update_layout(
            height=500,
            title=f"{selected_metric} actual vs estimate",
            barmode="group",
            yaxis=dict(title=yaxis_title),
            yaxis2=dict(
                title="Surprise %",
                overlaying="y",
                side="right",
                tickformat=".0%"
            ),
            margin=dict(l=20, r=20, t=70, b=40)
        )

    fig.update_xaxes(
        categoryorder="array",
        categoryarray=period_order
    )

    st.plotly_chart(fig, use_container_width=True)

    display = df.sort_values("_PeriodSort", ascending=False).copy()

    display["Date"] = pd.to_datetime(display["Date"], errors="coerce").dt.strftime("%Y-%m-%d")

    if "Forward" not in display.columns:
        display["Forward"] = False

    display["Forward"] = display["Forward"].fillna(False).apply(
        lambda x: "Oui" if bool(x) else "Non"
    )

    for col in ["EPS Actual", "EPS Estimate", "EPS Surprise"]:
        display[col] = display[col].apply(fmt_num)

    for col in ["Revenue Actual", "Revenue Estimate", "Revenue Surprise"]:
        display[col] = display[col].apply(fmt_large_number)

    for col in ["EPS Surprise %", "Revenue Surprise %"]:
        display[col] = display[col].apply(fmt_pct)

    display_cols = [
        "Date",
        "Period",
        "EPS Actual",
        "EPS Estimate",
        "EPS Surprise %",
        "Revenue Actual",
        "Revenue Estimate",
        "Revenue Surprise %",
        "Forward",
        "Verdict",
        "Source",
    ]

    st.dataframe(
        display[display_cols],
        use_container_width=True,
        hide_index=True
    )


def extract_forward_metrics(company_analysis_parts: dict) -> dict:
    growth = company_analysis_parts.get("growth", {})
    valuation = company_analysis_parts.get("valuation", {})
    analysts = company_analysis_parts.get("analysts", {})

    revenue_growth_forward = (
        growth.get("revenue_growth_yoy")
        or growth.get("quarterly_revenue_growth")
        or growth.get("annual_revenue_growth")
    )

    earnings_growth_forward = (
        growth.get("earnings_growth_yoy")
        or growth.get("quarterly_earnings_growth")
    )

    trailing_pe = valuation.get("trailing_pe")
    forward_pe = valuation.get("forward_pe")

    forward_pe_discount = None
    implied_eps_growth = None

    if trailing_pe not in [None, 0] and forward_pe not in [None, 0]:
        forward_pe_discount = forward_pe / trailing_pe - 1
        implied_eps_growth = trailing_pe / forward_pe - 1

    target_mean_upside = analysts.get("upside_mean")
    target_high_upside = analysts.get("upside_high")
    recommendation_key = analysts.get("recommendation_key")

    positive_count = 0
    negative_count = 0

    if revenue_growth_forward is not None:
        if revenue_growth_forward >= 0.10:
            positive_count += 1
        elif revenue_growth_forward < 0:
            negative_count += 1

    if earnings_growth_forward is not None:
        if earnings_growth_forward >= 0.10:
            positive_count += 1
        elif earnings_growth_forward < 0:
            negative_count += 1

    if forward_pe_discount is not None:
        if forward_pe_discount <= -0.15:
            positive_count += 1
        elif forward_pe_discount > 0.15:
            negative_count += 1

    if target_mean_upside is not None:
        if target_mean_upside >= 0.10:
            positive_count += 1
        elif target_mean_upside < 0:
            negative_count += 1

    if positive_count >= 3 and negative_count == 0:
        forward_bias = "Accélération positive"
    elif positive_count >= 2:
        forward_bias = "Forward constructif"
    elif negative_count >= 2:
        forward_bias = "Forward dégradé"
    else:
        forward_bias = "Forward mixte / neutre"

    return {
        "forward_bias": forward_bias,
        "revenue_growth_forward": revenue_growth_forward,
        "earnings_growth_forward": earnings_growth_forward,
        "quarterly_earnings_growth": growth.get("quarterly_earnings_growth"),
        "trailing_pe": trailing_pe,
        "forward_pe": forward_pe,
        "forward_pe_discount": forward_pe_discount,
        "implied_eps_growth": implied_eps_growth,
        "peg_ratio": valuation.get("peg_ratio"),
        "target_mean_upside": target_mean_upside,
        "target_high_upside": target_high_upside,
        "recommendation_key": recommendation_key,
    }


def score_forward_metrics(forward: dict) -> int:
    score = 50

    revenue_growth = forward.get("revenue_growth_forward")
    earnings_growth = forward.get("earnings_growth_forward")
    forward_pe_discount = forward.get("forward_pe_discount")
    implied_eps_growth = forward.get("implied_eps_growth")
    target_upside = forward.get("target_mean_upside")
    peg = forward.get("peg_ratio")

    if revenue_growth is not None:
        if revenue_growth >= 0.25:
            score += 18
        elif revenue_growth >= 0.10:
            score += 12
        elif revenue_growth >= 0.03:
            score += 6
        elif revenue_growth < 0:
            score -= 12

    if earnings_growth is not None:
        if earnings_growth >= 0.25:
            score += 18
        elif earnings_growth >= 0.10:
            score += 10
        elif earnings_growth < 0:
            score -= 12

    if forward_pe_discount is not None:
        if forward_pe_discount <= -0.30:
            score += 14
        elif forward_pe_discount <= -0.10:
            score += 8
        elif forward_pe_discount > 0.20:
            score -= 8

    if implied_eps_growth is not None:
        if implied_eps_growth >= 0.25:
            score += 10
        elif implied_eps_growth >= 0.10:
            score += 5

    if target_upside is not None:
        if target_upside >= 0.20:
            score += 10
        elif target_upside >= 0.05:
            score += 5
        elif target_upside < 0:
            score -= 8

    if peg is not None and peg > 0:
        if peg <= 1:
            score += 8
        elif peg > 3:
            score -= 8

    return int(clamp(round(score)))


def score_estimate_surprises_from_df(surprise_df: pd.DataFrame) -> int:
    if surprise_df is None or surprise_df.empty:
        return 50

    recent = surprise_df.sort_values("Date", ascending=False).head(8)

    score = 50

    eps_surprise = pd.to_numeric(recent.get("EPS Surprise %"), errors="coerce").dropna()
    rev_surprise = pd.to_numeric(recent.get("Revenue Surprise %"), errors="coerce").dropna()

    if not eps_surprise.empty:
        avg_eps = float(eps_surprise.mean())
        positive_ratio = float((eps_surprise > 0).mean())

        score += avg_eps * 120
        score += (positive_ratio - 0.50) * 30

    if not rev_surprise.empty:
        avg_rev = float(rev_surprise.mean())
        positive_ratio = float((rev_surprise > 0).mean())

        score += avg_rev * 80
        score += (positive_ratio - 0.50) * 20

    return int(clamp(round(score)))


def generate_forward_diagnosis(forward: dict) -> str:
    parts = [f"Lecture forward : {forward.get('forward_bias', 'N/A')}."]

    revenue_growth = forward.get("revenue_growth_forward")
    earnings_growth = forward.get("earnings_growth_forward")
    forward_pe_discount = forward.get("forward_pe_discount")
    target_upside = forward.get("target_mean_upside")

    if revenue_growth is not None:
        if revenue_growth >= 0.15:
            parts.append("La croissance attendue du chiffre d'affaires reste forte.")
        elif revenue_growth >= 0.03:
            parts.append("La croissance attendue du chiffre d'affaires reste positive.")
        else:
            parts.append("La croissance attendue du chiffre d'affaires est faible ou négative.")

    if earnings_growth is not None:
        if earnings_growth >= 0.20:
            parts.append("La croissance attendue des bénéfices est élevée.")
        elif earnings_growth >= 0.05:
            parts.append("La croissance attendue des bénéfices reste positive.")
        else:
            parts.append("La croissance attendue des bénéfices est fragile.")

    if forward_pe_discount is not None:
        if forward_pe_discount <= -0.20:
            parts.append("Le Forward P/E est nettement inférieur au Trailing P/E, ce qui implique une amélioration attendue des résultats.")
        elif forward_pe_discount > 0:
            parts.append("Le Forward P/E ne montre pas d'amélioration claire face au Trailing P/E.")

    if target_upside is not None:
        if target_upside >= 0.10:
            parts.append("Le target moyen des analystes implique encore un potentiel notable.")
        elif target_upside < 0:
            parts.append("Le target moyen des analystes implique un potentiel négatif.")

    return " ".join(parts)


def make_forward_table(forward: dict) -> pd.DataFrame:
    rows = [
        {"Métrique": "Forward Bias", "Valeur": forward.get("forward_bias")},
        {"Métrique": "Revenue Growth Forward", "Valeur": fmt_pct(forward.get("revenue_growth_forward"))},
        {"Métrique": "Earnings Growth Forward", "Valeur": fmt_pct(forward.get("earnings_growth_forward"))},
        {"Métrique": "Quarterly Earnings Growth", "Valeur": fmt_pct(forward.get("quarterly_earnings_growth"))},
        {"Métrique": "Trailing P/E", "Valeur": fmt_num(forward.get("trailing_pe"))},
        {"Métrique": "Forward P/E", "Valeur": fmt_num(forward.get("forward_pe"))},
        {"Métrique": "Forward P/E Discount / Premium", "Valeur": fmt_pct(forward.get("forward_pe_discount"))},
        {"Métrique": "Implied EPS Growth", "Valeur": fmt_pct(forward.get("implied_eps_growth"))},
        {"Métrique": "PEG Ratio", "Valeur": fmt_num(forward.get("peg_ratio"))},
        {"Métrique": "Target Mean Upside", "Valeur": fmt_pct(forward.get("target_mean_upside"))},
        {"Métrique": "Target High Upside", "Valeur": fmt_pct(forward.get("target_high_upside"))},
        {"Métrique": "Recommendation Key", "Valeur": forward.get("recommendation_key")},
    ]

    return pd.DataFrame(rows)


# ============================================================
# GROWTH / FORWARD SETUP — DECISION LAYER V7
# ============================================================

def _gf_mean(values: list[float], default: float = 50) -> float:
    clean = [
        safe_float(v)
        for v in values
        if safe_float(v) is not None and not pd.isna(safe_float(v))
    ]

    if not clean:
        return default

    return float(np.mean(clean))


def _gf_label(score: float) -> str:
    score = safe_float(score, 50) or 50

    if score >= 80:
        return "Très fort"
    if score >= 68:
        return "Solide"
    if score >= 55:
        return "Correct"
    if score >= 45:
        return "À confirmer"
    return "Fragile"


def _gf_setup_label(score: float, risk_score: float) -> str:
    score = safe_float(score, 50) or 50
    risk_score = safe_float(risk_score, 50) or 50

    # Labels courts pour éviter les valeurs tronquées dans st.metric.
    if score >= 80 and risk_score >= 65:
        return "Validé"
    if score >= 72 and risk_score >= 55:
        return "Constructif"
    if score >= 65:
        return "Prudent +"
    if score >= 55:
        return "À confirmer"
    if score >= 45:
        return "Fragile +"
    return "Fragile"


def _gf_growth_score(value) -> int:
    value = safe_float(value)

    if value is None:
        return 50

    if value >= 0.50:
        return 95
    if value >= 0.25:
        return 85
    if value >= 0.10:
        return 72
    if value >= 0.03:
        return 58
    if value >= 0:
        return 48
    if value >= -0.08:
        return 35
    return 22


def _gf_upside_score(value) -> int:
    value = safe_float(value)

    if value is None:
        return 50

    if value >= 0.35:
        return 90
    if value >= 0.20:
        return 78
    if value >= 0.10:
        return 66
    if value >= 0.03:
        return 56
    if value >= 0:
        return 48
    return 30


def _gf_forward_pe_score(value) -> int:
    value = safe_float(value)

    if value is None or value <= 0:
        return 50

    if value <= 15:
        return 85
    if value <= 25:
        return 74
    if value <= 40:
        return 60
    if value <= 60:
        return 45
    return 28


def _gf_pe_discount_score(value) -> int:
    value = safe_float(value)

    if value is None:
        return 50

    if value <= -0.35:
        return 90
    if value <= -0.20:
        return 78
    if value <= -0.10:
        return 66
    if value <= 0:
        return 55
    if value <= 0.15:
        return 45
    return 30


def _gf_peg_score(value) -> int:
    value = safe_float(value)

    if value is None or value <= 0:
        return 50

    if value <= 0.75:
        return 88
    if value <= 1.00:
        return 80
    if value <= 1.50:
        return 68
    if value <= 2.50:
        return 52
    if value <= 3.50:
        return 42
    return 30


def _gf_cash_score(balance: dict, growth: dict) -> int:
    fcf = safe_float(growth.get("latest_free_cash_flow"))
    ocf = safe_float(growth.get("operating_cash_flow"))
    fcf_margin = safe_float(balance.get("fcf_margin"))

    scores = []

    if fcf is not None:
        scores.append(75 if fcf > 0 else 25)

    if ocf is not None:
        scores.append(75 if ocf > 0 else 25)

    if fcf_margin is not None:
        if fcf_margin >= 0.25:
            scores.append(88)
        elif fcf_margin >= 0.15:
            scores.append(76)
        elif fcf_margin >= 0.08:
            scores.append(62)
        elif fcf_margin >= 0:
            scores.append(48)
        else:
            scores.append(25)

    return int(clamp(round(_gf_mean(scores, 50))))


def _gf_estimate_risk_score(growth: dict, forward: dict, valuation: dict) -> int:
    """
    Score élevé = risque faible.
    Score faible = forward trop dépendant d'estimates agressives.

    Cette version est volontairement plus stricte :
    - un implied EPS growth très élevé baisse le score ;
    - un forward P/E raisonnable aide, mais ne compense pas totalement
      un scénario EPS trop agressif ;
    - l'upside analyste négatif ou faible pénalise le setup.
    """
    score = 78

    implied_eps_growth = safe_float(forward.get("implied_eps_growth"))
    forward_pe = safe_float(forward.get("forward_pe"))
    revenue_growth = safe_float(forward.get("revenue_growth_forward"))
    earnings_growth = safe_float(forward.get("earnings_growth_forward"))
    target_mean_upside = safe_float(forward.get("target_mean_upside"))

    if implied_eps_growth is not None:
        if implied_eps_growth > 1.20:
            score -= 28
        elif implied_eps_growth > 0.80:
            score -= 20
        elif implied_eps_growth > 0.50:
            score -= 12
        elif implied_eps_growth > 0.25:
            score -= 5
        elif implied_eps_growth < 0:
            score -= 12

    if forward_pe is not None:
        if forward_pe > 70:
            score -= 20
        elif forward_pe > 50:
            score -= 12
        elif forward_pe > 35:
            score -= 5
        elif forward_pe <= 25:
            score += 4

    if revenue_growth is None:
        score -= 5
    elif revenue_growth < 0:
        score -= 14
    elif revenue_growth < 0.05:
        score -= 4

    if earnings_growth is None:
        score -= 5
    elif earnings_growth < 0:
        score -= 14
    elif earnings_growth < 0.05:
        score -= 4

    if target_mean_upside is not None:
        if target_mean_upside < 0:
            score -= 12
        elif target_mean_upside < 0.05 and implied_eps_growth is not None and implied_eps_growth > 0.80:
            score -= 6

    return int(clamp(round(score)))


def build_growth_forward_setup_v7(
    growth: dict,
    forward: dict,
    valuation: dict,
    balance: dict,
    scores: dict | None = None
) -> dict:
    scores = scores or {}

    revenue_growth = (
        safe_float(forward.get("revenue_growth_forward"))
        if safe_float(forward.get("revenue_growth_forward")) is not None
        else safe_float(growth.get("revenue_growth_yoy"))
    )

    annual_revenue_growth = safe_float(growth.get("annual_revenue_growth"))
    quarterly_revenue_growth = safe_float(growth.get("quarterly_revenue_growth"))
    earnings_growth = safe_float(forward.get("earnings_growth_forward"))
    quarterly_earnings_growth = safe_float(forward.get("quarterly_earnings_growth"))

    growth_quality_score = int(clamp(round(_gf_mean([
        _gf_growth_score(revenue_growth),
        _gf_growth_score(annual_revenue_growth),
        _gf_growth_score(quarterly_revenue_growth),
        _gf_growth_score(earnings_growth),
        _gf_growth_score(quarterly_earnings_growth),
    ]))))

    forward_pe = safe_float(forward.get("forward_pe"))
    trailing_pe = safe_float(forward.get("trailing_pe"))
    forward_pe_discount = safe_float(forward.get("forward_pe_discount"))
    peg_ratio = safe_float(forward.get("peg_ratio"))
    target_mean_upside = safe_float(forward.get("target_mean_upside"))
    implied_eps_growth = safe_float(forward.get("implied_eps_growth"))

    valuation_support_score = int(clamp(round(_gf_mean([
        _gf_forward_pe_score(forward_pe),
        _gf_pe_discount_score(forward_pe_discount),
        _gf_peg_score(peg_ratio),
        _gf_upside_score(target_mean_upside),
    ]))))

    cash_conversion_score = _gf_cash_score(balance, growth)

    analyst_upside_score = int(clamp(round(_gf_mean([
        _gf_upside_score(target_mean_upside),
        _gf_upside_score(forward.get("target_high_upside")),
        scores.get("analyst_score", 50),
    ]))))

    estimate_risk_score = _gf_estimate_risk_score(growth, forward, valuation)

    setup_score = int(clamp(round(
        0.26 * growth_quality_score
        + 0.21 * valuation_support_score
        + 0.17 * cash_conversion_score
        + 0.13 * analyst_upside_score
        + 0.23 * estimate_risk_score
    )))

    # Garde-fou : si le risque d'estimates est trop élevé, on évite
    # que la croissance seule donne un verdict trop agressif.
    if estimate_risk_score < 45:
        setup_score = int(clamp(setup_score - 6))
    elif estimate_risk_score < 55:
        setup_score = int(clamp(setup_score - 3))

    if valuation_support_score < 55 and growth_quality_score >= 75:
        setup_score = int(clamp(setup_score - 3))

    setup_label = _gf_setup_label(setup_score, estimate_risk_score)

    if setup_score >= 78 and estimate_risk_score >= 60:
        narrative = (
            "La croissance, la valorisation forward et la conversion cash valident majoritairement le narratif fondamental. "
            "Le setup reste exploitable tant que les estimates ne se dégradent pas."
        )
    elif setup_score >= 70:
        narrative = (
            "Le setup reste constructif, mais il dépend encore de la confirmation des estimates. "
            "La croissance soutient le dossier, mais le risque d'exécution doit rester surveillé."
        )
    elif setup_score >= 60:
        narrative = (
            "Le dossier reste exploitable mais pas pleinement validé. "
            "La croissance est présente, toutefois le forward price déjà une partie importante de l'amélioration attendue."
        )
    elif setup_score >= 50:
        narrative = (
            "Le setup est à confirmer. "
            "Il faut privilégier une validation par les prochains chiffres, une détente de valorisation ou un meilleur point d'entrée."
        )
    else:
        narrative = (
            "Le forward ne valide pas assez le narratif actuel. "
            "Le risque de déception ou de valorisation trop exigeante domine."
        )

    decision_rows = [
        {
            "Dimension": "Growth Quality",
            "Lecture": _gf_label(growth_quality_score),
            "Score": growth_quality_score,
            "Détail": (
                f"Revenue YoY {fmt_pct(revenue_growth)} · "
                f"Annual revenue {fmt_pct(annual_revenue_growth)} · "
                f"Earnings YoY {fmt_pct(earnings_growth)}."
            ),
        },
        {
            "Dimension": "Forward Valuation Support",
            "Lecture": _gf_label(valuation_support_score),
            "Score": valuation_support_score,
            "Détail": (
                f"Forward P/E {fmt_num(forward_pe)} vs Trailing P/E {fmt_num(trailing_pe)} · "
                f"Discount/Premium {fmt_pct(forward_pe_discount)} · PEG {fmt_num(peg_ratio)}."
            ),
        },
        {
            "Dimension": "Cash Conversion",
            "Lecture": _gf_label(cash_conversion_score),
            "Score": cash_conversion_score,
            "Détail": (
                f"FCF {fmt_large_number(growth.get('latest_free_cash_flow'))} · "
                f"OCF {fmt_large_number(growth.get('operating_cash_flow'))} · "
                f"FCF margin {fmt_pct(balance.get('fcf_margin'))}."
            ),
        },
        {
            "Dimension": "Analyst Upside",
            "Lecture": _gf_label(analyst_upside_score),
            "Score": analyst_upside_score,
            "Détail": (
                f"Target mean upside {fmt_pct(target_mean_upside)} · "
                f"Target high upside {fmt_pct(forward.get('target_high_upside'))} · "
                f"Reco {forward.get('recommendation_key', 'N/A')}."
            ),
        },
        {
            "Dimension": "Estimate Risk",
            "Lecture": _gf_label(estimate_risk_score),
            "Score": estimate_risk_score,
            "Détail": (
                f"Implied EPS growth {fmt_pct(implied_eps_growth)} · "
                f"Plus le score est bas, plus le forward dépend d'estimates agressives."
            ),
        },
        {
            "Dimension": "Composite Setup",
            "Lecture": setup_label,
            "Score": setup_score,
            "Détail": (
                "Score pondéré : growth quality, valuation support, cash conversion, "
                "analyst upside et estimate risk."
            ),
        },
    ]

    bridge_rows = [
        {
            "Métrique": "Revenue Growth Forward",
            "Valeur brute": fmt_pct(revenue_growth),
            "Score": _gf_growth_score(revenue_growth),
            "Lecture": "Croissance attendue du chiffre d'affaires.",
        },
        {
            "Métrique": "Earnings Growth Forward",
            "Valeur brute": fmt_pct(earnings_growth),
            "Score": _gf_growth_score(earnings_growth),
            "Lecture": "Croissance attendue des bénéfices.",
        },
        {
            "Métrique": "Quarterly Earnings Growth",
            "Valeur brute": fmt_pct(quarterly_earnings_growth),
            "Score": _gf_growth_score(quarterly_earnings_growth),
            "Lecture": "Momentum bénéficiaire court terme.",
        },
        {
            "Métrique": "Forward P/E",
            "Valeur brute": fmt_num(forward_pe),
            "Score": _gf_forward_pe_score(forward_pe),
            "Lecture": "Valorisation forward absolue.",
        },
        {
            "Métrique": "Forward P/E Discount / Premium",
            "Valeur brute": fmt_pct(forward_pe_discount),
            "Score": _gf_pe_discount_score(forward_pe_discount),
            "Lecture": "Détente ou tension vs trailing multiple.",
        },
        {
            "Métrique": "PEG Ratio",
            "Valeur brute": fmt_num(peg_ratio),
            "Score": _gf_peg_score(peg_ratio),
            "Lecture": "Prix payé par unité de croissance.",
        },
        {
            "Métrique": "Target Mean Upside",
            "Valeur brute": fmt_pct(target_mean_upside),
            "Score": _gf_upside_score(target_mean_upside),
            "Lecture": "Potentiel moyen implicite des analystes.",
        },
        {
            "Métrique": "Implied EPS Growth",
            "Valeur brute": fmt_pct(implied_eps_growth),
            "Score": estimate_risk_score,
            "Lecture": "Risque si le marché price déjà une forte amélioration EPS.",
        },
    ]

    return {
        "setup_score": setup_score,
        "setup_label": setup_label,
        "narrative": narrative,
        "growth_quality_score": growth_quality_score,
        "valuation_support_score": valuation_support_score,
        "cash_conversion_score": cash_conversion_score,
        "analyst_upside_score": analyst_upside_score,
        "estimate_risk_score": estimate_risk_score,
        "decision_table": pd.DataFrame(decision_rows),
        "bridge_table": pd.DataFrame(bridge_rows),
    }


def render_growth_forward_setup_v7(
    growth: dict,
    forward: dict,
    valuation: dict,
    balance: dict,
    scores: dict | None = None
):
    st.subheader("Growth / Forward Setup — validation du narratif")

    setup = build_growth_forward_setup_v7(
        growth=growth,
        forward=forward,
        valuation=valuation,
        balance=balance,
        scores=scores or {},
    )

    c1, c2, c3, c4, c5, c6 = st.columns(6)

    c1.metric("Setup Score", f"{setup['setup_score']}/100")
    c2.metric("Verdict", setup["setup_label"])
    c3.metric("Growth Quality", f"{setup['growth_quality_score']}/100")
    c4.metric("Valuation Support", f"{setup['valuation_support_score']}/100")
    c5.metric("Cash Conversion", f"{setup['cash_conversion_score']}/100")
    c6.metric("Estimate Risk", f"{setup['estimate_risk_score']}/100")

    if setup["setup_score"] >= 62 and setup["estimate_risk_score"] >= 50:
        st.success(setup["narrative"])
    elif setup["setup_score"] >= 50:
        st.warning(setup["narrative"])
    else:
        st.error(setup["narrative"])

    st.caption(
        "Lecture : Estimate Risk est inversé. Plus le score est élevé, plus le forward dépend peu d'hypothèses agressives. "
        "Un score faible indique que le marché price déjà une forte amélioration future."
    )

    view = st.radio(
        "Vue Growth / Forward",
        ["Decision Setup", "Metric Bridge", "Raw Audit"],
        horizontal=True,
        key="growth_forward_setup_v7_view",
    )

    if view == "Decision Setup":
        decision_df = setup["decision_table"].copy()

        fig = go.Figure()

        chart_df = decision_df[
            decision_df["Dimension"] != "Composite Setup"
        ].copy()

        chart_df = chart_df.sort_values("Score", ascending=True)

        fig.add_trace(go.Bar(
            x=chart_df["Score"],
            y=chart_df["Dimension"],
            orientation="h",
            text=chart_df["Score"],
            textposition="auto",
            customdata=chart_df[["Lecture", "Détail"]],
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Score: %{x}/100<br>"
                "Lecture: %{customdata[0]}<br>"
                "%{customdata[1]}"
                "<extra></extra>"
            ),
            name="Score",
        ))

        fig.add_vline(
            x=50,
            line_dash="dot",
            annotation_text="Neutre",
            annotation_position="top"
        )

        fig.add_vline(
            x=70,
            line_dash="dash",
            annotation_text="Support fort",
            annotation_position="top"
        )

        fig.update_layout(
            height=430,
            title="Growth / Forward Scorecard — scores normalisés",
            xaxis_title="Score",
            yaxis_title="Dimension",
            xaxis=dict(range=[0, 100]),
            margin=dict(l=20, r=20, t=70, b=40),
        )

        st.plotly_chart(fig, use_container_width=True)

        st.dataframe(
            decision_df,
            use_container_width=True,
            hide_index=True,
        )

    elif view == "Metric Bridge":
        bridge_df = setup["bridge_table"].copy()

        fig = go.Figure()

        plot_df = bridge_df.sort_values("Score", ascending=True)

        fig.add_trace(go.Bar(
            x=plot_df["Score"],
            y=plot_df["Métrique"],
            orientation="h",
            text=plot_df["Score"],
            textposition="auto",
            customdata=plot_df[["Valeur brute", "Lecture"]],
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Valeur brute: %{customdata[0]}<br>"
                "Score normalisé: %{x}/100<br>"
                "%{customdata[1]}"
                "<extra></extra>"
            ),
            name="Score normalisé",
        ))

        fig.update_layout(
            height=500,
            title="Metric Bridge — valeurs brutes transformées en scores décisionnels",
            xaxis_title="Score normalisé",
            yaxis_title="Métrique",
            xaxis=dict(range=[0, 100]),
            margin=dict(l=20, r=20, t=70, b=40),
        )

        st.plotly_chart(fig, use_container_width=True)

        st.dataframe(
            bridge_df,
            use_container_width=True,
            hide_index=True,
        )

    elif view == "Raw Audit":
        growth_df = make_metric_table(growth, [
            ("Revenue TTM", "revenue_ttm", "money"),
            ("Revenue Growth YoY", "revenue_growth_yoy", "pct"),
            ("Annual Revenue Growth", "annual_revenue_growth", "pct"),
            ("Quarterly Revenue Growth YoY", "quarterly_revenue_growth", "pct"),
            ("Earnings Growth YoY", "earnings_growth_yoy", "pct"),
            ("Quarterly Earnings Growth", "quarterly_earnings_growth", "pct"),
            ("Net Income latest annual", "latest_net_income", "money"),
            ("Free Cash Flow", "latest_free_cash_flow", "money"),
            ("Operating Cash Flow", "operating_cash_flow", "money"),
        ])

        with st.expander("Raw growth metrics", expanded=True):
            st.dataframe(
                growth_df,
                use_container_width=True,
                hide_index=True,
            )

        with st.expander("Raw forward / valuation metrics", expanded=True):
            st.dataframe(
                make_forward_table(forward),
                use_container_width=True,
                hide_index=True,
            )


def render_forward_guidance_v6(forward: dict):
    st.subheader("Forward / Guidance / Implied Growth")

    st.info(generate_forward_diagnosis(forward))

    st.dataframe(
        make_forward_table(forward),
        use_container_width=True,
        hide_index=True
    )

    plot_rows = [
        {"Métrique": "Revenue Growth", "Valeur": forward.get("revenue_growth_forward")},
        {"Métrique": "Earnings Growth", "Valeur": forward.get("earnings_growth_forward")},
        {"Métrique": "Quarterly Earnings Growth", "Valeur": forward.get("quarterly_earnings_growth")},
        {"Métrique": "Implied EPS Growth", "Valeur": forward.get("implied_eps_growth")},
        {"Métrique": "Target Mean Upside", "Valeur": forward.get("target_mean_upside")},
    ]

    plot_df = pd.DataFrame(plot_rows).dropna()

    if not plot_df.empty:
        fig = go.Figure()
        fig.add_trace(go.Bar(x=plot_df["Métrique"], y=plot_df["Valeur"]))
        fig.update_layout(
            height=430,
            title="Forward / implied metrics",
            yaxis_title="Valeur",
            yaxis_tickformat=".0%",
            margin=dict(l=20, r=20, t=70, b=40)
        )
        st.plotly_chart(fig, use_container_width=True)


def build_news_briefing_rows(company_analysis: dict, ticker: str) -> pd.DataFrame:
    sentiment = company_analysis.get("sentiment", {})
    news_df = sentiment.get("news_table", pd.DataFrame())
    profile = company_analysis.get("profile", {})

    if not isinstance(news_df, pd.DataFrame) or news_df.empty:
        return pd.DataFrame()

    company_name = str(profile.get("name", "")).lower()
    sector = str(profile.get("sector", "")).lower()
    industry = str(profile.get("industry", "")).lower()
    ticker_lower = ticker.lower()

    rows = []

    for _, row in news_df.head(30).iterrows():
        title = str(row.get("Titre", ""))
        summary = str(row.get("Résumé", ""))
        text = f"{title} {summary}".lower()

        relevance = 0

        if ticker_lower in text:
            relevance += 4

        short_company = company_name.split(" ")[0] if company_name else ""
        if short_company and short_company in text:
            relevance += 3

        if sector and sector in text:
            relevance += 1

        if industry and any(word in text for word in industry.split()):
            relevance += 1

        thematic_keywords = [
            "earnings", "guidance", "revenue", "margin", "profit", "eps",
            "ai", "data center", "datacenter", "semiconductor", "chip",
            "customer", "contract", "partnership", "order", "forecast",
            "export", "china", "regulation"
        ]

        relevance += sum(1 for kw in thematic_keywords if kw in text)

        market_noise_keywords = ["crypto", "bitcoin", "dividend fund", "reit", "closed-end fund"]
        relevance -= sum(2 for kw in market_noise_keywords if kw in text)

        if relevance >= 6:
            impact = "Forte"
        elif relevance >= 3:
            impact = "Moyenne"
        else:
            impact = "Faible"

        sentiment_label = row.get("Sentiment mécanique", "Neutre")
        source = row.get("Source", "N/A")
        date = row.get("Date", "N/A")

        if summary and summary != "nan":
            one_liner = summary[:220]
        else:
            one_liner = title[:220]

        if sentiment_label == "Positif":
            interpretation = "Lecture positive : catalyseur ou perception favorable à surveiller."
        elif sentiment_label == "Négatif":
            interpretation = "Lecture négative : risque ou pression potentielle à surveiller."
        else:
            interpretation = "Lecture neutre : information utile pour le contexte, sans signal directionnel fort à elle seule."

        rows.append({
            "Date": date,
            "Titre": title,
            "Source": source,
            "Sentiment": sentiment_label,
            "Impact": impact,
            "Pertinence": relevance,
            "Brief": f"{interpretation} {one_liner}",
            "Lien": row.get("Lien", ""),
        })

    result = pd.DataFrame(rows)

    if result.empty:
        return result

    return result.sort_values(["Pertinence", "Date"], ascending=[False, False]).head(10)


def render_latest_news_briefing(sentiment: dict):
    sentiment = sentiment if isinstance(sentiment, dict) else {}

    raw_news_payload = (
        sentiment.get("news")
        or sentiment.get("latest_news")
        or sentiment.get("stock_news")
        or sentiment.get("fmp_news")
        or sentiment.get("articles")
        or sentiment
    )

    legacy_brief_df = pd.DataFrame()

    try:
        legacy_brief_df = build_latest_news_briefing(sentiment, max_items=20)
    except Exception:
        legacy_brief_df = pd.DataFrame()

    if legacy_brief_df is not None and not legacy_brief_df.empty:
        news_payload = []

        for _, row in legacy_brief_df.iterrows():
            news_payload.append({
                "date": row.get("Date"),
                "title": row.get("Titre") or row.get("Title") or row.get("Catégorie") or "News",
                "summary": row.get("Brief") or row.get("Summary") or "",
                "source": row.get("Source") or "N/A",
                "url": row.get("URL") or row.get("Url") or row.get("Lien") or "",
            })

        render_latest_news_intelligence_center_v1(
            news_payload,
            sector="",
            industry="",
            key_prefix="latest_news_ic_legacy"
        )
        return

    render_latest_news_intelligence_center_v1(
        raw_news_payload,
        sector="",
        industry="",
        key_prefix="latest_news_ic_legacy"
    )


def company_score_table(company_analysis: dict) -> pd.DataFrame:
    scores = company_analysis.get("scores", {})

    return pd.DataFrame([
        {"Bloc": "Croissance", "Score": f"{scores.get('growth_score', 50)}/100", "Poids": "18%"},
        {"Bloc": "Rentabilité", "Score": f"{scores.get('profitability_score', 50)}/100", "Poids": "18%"},
        {"Bloc": "Bilan", "Score": f"{scores.get('balance_score', 50)}/100", "Poids": "12%"},
        {"Bloc": "Valorisation", "Score": f"{scores.get('valuation_score', 50)}/100", "Poids": "14%"},
        {"Bloc": "Forward", "Score": f"{scores.get('forward_score', 50)}/100", "Poids": "16%"},
        {"Bloc": "Surprise estimates", "Score": f"{scores.get('surprise_score', 50)}/100", "Poids": "12%"},
        {"Bloc": "Analystes", "Score": f"{scores.get('analyst_score', 50)}/100", "Poids": "7%"},
        {"Bloc": "Market feeling", "Score": f"{scores.get('sentiment_score', 50)}/100", "Poids": "3%"},
        {"Bloc": "Core Fundamental Score", "Score": f"{scores.get('company_score', 50)}/100", "Poids": "Composite"},
    ])


def calculate_company_composite_score(company_analysis: dict) -> int:
    scores = company_analysis.get("scores", {})

    growth = scores.get("growth_score", 50)
    profitability = scores.get("profitability_score", 50)
    balance = scores.get("balance_score", 50)
    valuation = scores.get("valuation_score", 50)
    forward = scores.get("forward_score", 50)
    surprise = scores.get("surprise_score", 50)
    analysts = scores.get("analyst_score", 50)
    sentiment = scores.get("sentiment_score", 50)

    composite = (
        0.18 * growth
        + 0.18 * profitability
        + 0.12 * balance
        + 0.14 * valuation
        + 0.16 * forward
        + 0.12 * surprise
        + 0.07 * analysts
        + 0.03 * sentiment
    )

    return int(clamp(round(composite)))


def generate_company_diagnosis(company_analysis: dict) -> str:
    scores = company_analysis.get("scores", {})
    composite = scores.get("company_score", 50)
    growth = scores.get("growth_score", 50)
    profitability = scores.get("profitability_score", 50)
    valuation = scores.get("valuation_score", 50)
    forward = scores.get("forward_score", 50)
    surprise = scores.get("surprise_score", 50)
    analysts = scores.get("analyst_score", 50)

    parts = [get_company_quality_label(composite) + "."]

    if growth >= 75:
        parts.append("La croissance est forte.")
    elif growth >= 55:
        parts.append("La croissance reste correcte.")
    else:
        parts.append("La croissance est faible ou irrégulière.")

    if profitability >= 75:
        parts.append("La rentabilité est robuste.")
    elif profitability >= 55:
        parts.append("La rentabilité est acceptable.")
    else:
        parts.append("La rentabilité est fragile.")

    if forward >= 75:
        parts.append("Les métriques forward renforcent le scénario.")
    elif forward >= 55:
        parts.append("Les métriques forward sont constructives mais pas décisives.")
    else:
        parts.append("Les métriques forward ne confirment pas suffisamment l'amélioration attendue.")

    if surprise >= 65:
        parts.append("Les surprises de résultats disponibles sont favorables.")
    elif surprise <= 40:
        parts.append("Les surprises de résultats sont faibles ou indisponibles.")
    else:
        parts.append("Les surprises de résultats sont neutres.")

    if valuation >= 70:
        parts.append("La valorisation reste raisonnable au regard des métriques disponibles.")
    elif valuation >= 45:
        parts.append("La valorisation est exigeante mais pas forcément excessive si la croissance continue.")
    else:
        parts.append("La valorisation est tendue : privilégier les entrées sur repli.")

    if analysts >= 65:
        parts.append("Le consensus analyste est favorable.")
    elif analysts >= 45:
        parts.append("Le consensus analyste est neutre à modérément positif.")
    else:
        parts.append("Le consensus analyste est peu favorable ou insuffisamment robuste.")

    return " ".join(parts)


def score_market_feeling(sentiment: dict) -> int:
    """
    Convertit le score mécanique du newsflow en score 0-100.

    Cette fonction existait dans app.py avant le refactor et doit rester
    disponible dans le module qui construit Company Intelligence.
    L'absence de news reste neutre (50/100), comme dans le runtime legacy.
    """
    if not isinstance(sentiment, dict):
        return 50

    raw_score = safe_float(sentiment.get("raw_score"), 0) or 0
    news_count = safe_int(sentiment.get("news_count"), 0) or 0

    if news_count == 0:
        return 50

    score = 50 + raw_score * 6
    return int(clamp(round(score)))


def analyze_company_intelligence(ticker: str, latest_price: float) -> dict:
    company_data = get_company_intelligence_data(ticker)

    profile = extract_company_profile(company_data)
    growth = extract_growth_metrics(company_data)
    profitability = extract_profitability_metrics(company_data)
    valuation = extract_valuation_metrics(company_data)
    balance = extract_balance_sheet_metrics(company_data)
    analysts = extract_analyst_metrics(company_data, latest_price)
    sentiment = extract_news_sentiment(company_data)

    temp_parts = {
        "growth": growth,
        "valuation": valuation,
        "analysts": analysts,
    }

    forward = extract_forward_metrics(temp_parts)
    surprise_df = build_earnings_surprise_df(company_data)

    scores = {
        "growth_score": score_growth(growth),
        "profitability_score": score_profitability(profitability),
        "balance_score": score_balance_sheet(balance),
        "valuation_score": score_valuation(valuation, growth, profitability),
        "forward_score": score_forward_metrics(forward),
        "surprise_score": score_estimate_surprises_from_df(surprise_df),
        "analyst_score": score_analysts(analysts),
        "sentiment_score": score_market_feeling(sentiment),
    }

    temp = {"scores": scores}
    scores["company_score"] = calculate_company_composite_score(temp)

    company_analysis = {
        "raw_data": company_data,
        "profile": profile,
        "growth": growth,
        "profitability": profitability,
        "valuation": valuation,
        "balance": balance,
        "analysts": analysts,
        "sentiment": sentiment,
        "forward": forward,
        "surprise_df": surprise_df,
        "scores": scores,
    }

    company_analysis["diagnosis"] = generate_company_diagnosis(company_analysis)

    return company_analysis




