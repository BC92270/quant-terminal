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
from .earnings import *
from .news import *

def render_company_intelligence_mode(ticker: str, analysis: dict):
    company = analysis.get("company_analysis", {})
    profile = company.get("profile", {})
    growth = company.get("growth", {})
    profitability = company.get("profitability", {})
    valuation = company.get("valuation", {})
    balance = company.get("balance", {})
    analysts = company.get("analysts", {})
    sentiment = company.get("sentiment", {})
    forward = company.get("forward", {})
    raw = company.get("raw_data", {})

    st.subheader(f"Company Intelligence — {ticker}")

    scores = company.get("scores", {})

    col1, col2, col3, col4, col5, col6 = st.columns(6)

    col1.metric("Core Fundamental Score", f"{scores.get('company_score', 50)}/100")
    col2.metric("Growth Score", f"{scores.get('growth_score', 50)}/100")
    col3.metric("Forward Score", f"{scores.get('forward_score', 50)}/100")
    col4.metric("Surprise Score", f"{scores.get('surprise_score', 50)}/100")
    col5.metric("Valuation Score", f"{scores.get('valuation_score', 50)}/100")
    col6.metric("Analyst Score", f"{scores.get('analyst_score', 50)}/100")

    st.info(company.get("diagnosis", "Diagnostic entreprise indisponible."))

    if forward:
        st.info(generate_forward_diagnosis(forward))

    st.divider()

    st.subheader("Commandes d'affichage")

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        financial_frequency = st.radio(
            "Temporalité financière",
            ["Annuel", "Trimestriel"],
            index=0,
            horizontal=True,
            key="company_v6_financial_frequency"
        )

    with c2:
        max_periods = st.selectbox(
            "Historique affiché",
            [4, 6, 8, 10, 12],
            index=0,
            key="company_v6_max_periods"
        )

    with c3:
        chart_type = st.selectbox(
            "Type de graphique",
            ["Barres", "Lignes"],
            index=0,
            key="company_v6_chart_type"
        )

    with c4:
        show_estimates = st.checkbox(
            "Afficher estimates / forward / surprise",
            value=True,
            key="company_v6_show_estimates"
        )
    
    with st.expander("Debug providers estimates", expanded=False):
        fmp = raw.get("fmp", {}) if isinstance(raw, dict) else {}
        alpha = raw.get("alpha", {}) if isinstance(raw, dict) else {}
        finnhub = raw.get("finnhub", {}) if isinstance(raw, dict) else {}

        alpha_payload = alpha.get("earnings_estimates", {}) if isinstance(alpha, dict) else {}
        alpha_records = []
        if isinstance(alpha_payload, dict):
            raw_alpha_estimates = alpha_payload.get("estimates", [])
            if isinstance(raw_alpha_estimates, list):
                alpha_records = raw_alpha_estimates
            elif isinstance(raw_alpha_estimates, dict):
                for value in raw_alpha_estimates.values():
                    if isinstance(value, list):
                        alpha_records.extend(value)
                    elif isinstance(value, dict):
                        alpha_records.append(value)

        finnhub_eps_rows = []
        finnhub_eps_rows += finnhub_rows(finnhub.get("eps_estimate_annual", {}), ["data"])
        finnhub_eps_rows += finnhub_rows(finnhub.get("eps_estimate_quarterly", {}), ["data"])

        finnhub_revenue_rows = []
        finnhub_revenue_rows += finnhub_rows(finnhub.get("revenue_estimate_annual", {}), ["data"])
        finnhub_revenue_rows += finnhub_rows(finnhub.get("revenue_estimate_quarterly", {}), ["data"])

        provider_audit = pd.DataFrame([
            {"Provider": "FMP", "Enabled": bool(fmp.get("enabled", False)), "Estimate rows": len(fmp.get("estimates_annual", []) or []) + len(fmp.get("estimates_quarterly", []) or []), "Earnings rows": len(fmp.get("earnings_calendar", []) or []) + len(fmp.get("earnings_surprises", []) or [])},
            {"Provider": "Alpha Vantage", "Enabled": bool(alpha.get("enabled", False)), "Estimate rows": len(alpha_records), "Earnings rows": 0},
            {"Provider": "Finnhub", "Enabled": bool(finnhub.get("enabled", False)), "Estimate rows": len(finnhub_eps_rows) + len(finnhub_revenue_rows), "Earnings rows": len(finnhub.get("earnings_calendar", []) or [])},
        ])
        st.dataframe(provider_audit, use_container_width=True, hide_index=True)

        if isinstance(alpha_payload, dict) and "_alpha_error" in alpha_payload:
            st.warning("Alpha Vantage returned a provider error / plan limit.")
            st.write(alpha_payload["_alpha_error"])
        if isinstance(alpha_payload, dict) and "_alpha_exception" in alpha_payload:
            st.error(f"Alpha Vantage exception: {alpha_payload['_alpha_exception']}")

        if st.checkbox("Show normalized estimate source audit", value=False, key=f"company_debug_source_audit_{ticker}"):
            try:
                income_est_debug = build_income_estimate_long(raw, financial_frequency)
                cash_est_debug = build_cashflow_estimate_long(raw, financial_frequency)
                profitability_est_debug = build_profitability_estimate_long(raw, financial_frequency)
                for label, frame in [
                    ("Income", income_est_debug),
                    ("Cash-flow", cash_est_debug),
                    ("Profitability", profitability_est_debug),
                ]:
                    st.write(label)
                    st.dataframe(
                        frame.groupby("Source Estimate").size().reset_index(name="Rows")
                        if not frame.empty else pd.DataFrame(),
                        use_container_width=True,
                        hide_index=True,
                    )
            except Exception as debug_error:
                st.error(f"Debug estimates error: {debug_error}")

    fmp_status = raw.get("fmp", {}).get("enabled", False)

    if fmp_status:
        st.caption(
            "Mode enrichi actif : FMP est connecté. Les estimates, forward curves, earnings surprises et news enrichies sont disponibles quand l'API les fournit."
        )
    else:
        st.warning(
            "FMP_API_KEY non configurée : le dashboard fonctionne en fallback yfinance. "
            "Les vraies données Actual vs Estimate / Forward Curve / Surprise seront limitées ou indisponibles."
        )

    st.divider()

    st.subheader("Profil entreprise")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Market Cap", fmt_large_number(profile.get("market_cap")))
    col2.metric("Enterprise Value", fmt_large_number(profile.get("enterprise_value")))
    col3.metric("Beta", fmt_num(profile.get("beta")))
    col4.metric("Employés", "N/A" if profile.get("employees") is None else f"{profile.get('employees'):,}")

    profile_df = pd.DataFrame([
        {"Champ": "Nom", "Valeur": profile.get("name")},
        {"Champ": "Secteur", "Valeur": profile.get("sector")},
        {"Champ": "Industrie", "Valeur": profile.get("industry")},
        {"Champ": "Pays", "Valeur": profile.get("country")},
        {"Champ": "Devise", "Valeur": profile.get("currency")},
        {"Champ": "Site", "Valeur": profile.get("website")},
    ])

    st.dataframe(profile_df, use_container_width=True, hide_index=True)

    with st.expander("Business summary"):
        st.write(profile.get("summary", "N/A"))

    st.divider()

    st.subheader("Score entreprise")
    st.dataframe(company_score_table(company), use_container_width=True, hide_index=True)

    st.divider()

    income_actual = build_income_actual_long(raw, financial_frequency)
    income_estimate = build_income_estimate_long(raw, financial_frequency)
    income_explorer = merge_actual_estimate_long(income_actual, income_estimate)

    render_unified_financial_explorer_v6(
        title=f"Compte de résultat — {financial_frequency.lower()}",
        base_df=income_explorer,
        available_metrics=["Revenue", "Gross Profit", "Operating Income", "Net Income", "EBITDA", "EBIT", "EPS"],
        default_metrics=["Revenue", "Gross Profit", "Operating Income", "Net Income", "EBITDA", "EBIT"],
        value_kind="money",
        frequency=financial_frequency,
        max_periods=max_periods,
        show_estimates=show_estimates,
        chart_type=chart_type,
        key_prefix="income_v6"
    )

    st.divider()

    render_earnings_surprise_center_v6(raw)

    st.divider()

    render_growth_forward_setup_v7(
        growth=growth,
        forward=forward,
        valuation=valuation,
        balance=balance,
        scores=scores,
    )

    st.divider()

    cash_actual = build_cashflow_actual_long(raw, financial_frequency)
    cash_estimate = build_cashflow_estimate_long(raw, financial_frequency)
    cash_explorer = merge_actual_estimate_long(cash_actual, cash_estimate)

    render_unified_financial_explorer_v6(
        title=f"Cash-flow — {financial_frequency.lower()}",
        base_df=cash_explorer,
        available_metrics=["Operating Cash Flow", "Free Cash Flow", "Capital Expenditure"],
        default_metrics=["Operating Cash Flow", "Free Cash Flow", "Capital Expenditure"],
        value_kind="money",
        frequency=financial_frequency,
        max_periods=max_periods,
        show_estimates=show_estimates,
        chart_type=chart_type,
        key_prefix="cashflow_v6"
    )

    st.divider()

    profitability_actual = build_profitability_long(raw, financial_frequency)
    profitability_estimate = build_profitability_estimate_long(raw, financial_frequency)
    profitability_explorer = merge_actual_estimate_long(profitability_actual, profitability_estimate)

    render_unified_financial_explorer_v6(
        title=f"Rentabilité — {financial_frequency.lower()}",
        base_df=profitability_explorer,
        available_metrics=["Gross Margin", "EBITDA Margin", "Operating Margin", "Net Margin", "ROE", "ROA", "FCF Margin"],
        default_metrics=["Gross Margin", "EBITDA Margin", "Operating Margin", "Net Margin"],
        value_kind="pct",
        frequency=financial_frequency,
        max_periods=max_periods,
        show_estimates=show_estimates,
        chart_type=chart_type,
        key_prefix="profitability_v6"
    )

    st.divider()

    st.subheader("Bilan / solidité financière")

    balance_df = make_metric_table(balance, [
        ("Total Cash", "total_cash", "money"),
        ("Total Debt", "total_debt", "money"),
        ("Net Debt", "net_debt", "money"),
        ("Cash / Debt", "cash_to_debt", "num"),
        ("Current Ratio", "current_ratio", "num"),
        ("Quick Ratio", "quick_ratio", "num"),
        ("Debt / Equity", "debt_to_equity", "num"),
        ("Operating Cash Flow", "operating_cash_flow", "money"),
        ("Free Cash Flow", "free_cash_flow", "money"),
        ("FCF Margin", "fcf_margin", "pct"),
    ])

    st.dataframe(balance_df, use_container_width=True, hide_index=True)

    st.divider()

    balance_actual_long = build_balance_actual_long(raw, financial_frequency)
    balance_estimate_long = (
        build_balance_estimate_long(raw, financial_frequency)
        if show_estimates
        else empty_estimate_long()
    )

    balance_explorer = merge_actual_estimate_long(
        balance_actual_long,
        balance_estimate_long
    )

    balance_available_metrics = [
        metric for metric in BALANCE_SHEET_DISPLAY_METRICS
        if metric in balance_explorer["Metric"].dropna().unique().tolist()
    ]

    if balance_available_metrics:
        render_unified_financial_explorer_v6(
            title=f"Bilan — {financial_frequency.lower()}",
            base_df=balance_explorer,
            available_metrics=balance_available_metrics,
            default_metrics=[
                metric for metric in [
                    "Total Cash",
                    "Total Debt",
                    "Net Debt",
                    "Total Assets",
                    "Total Equity",
                ]
                if metric in balance_available_metrics
            ],
            value_kind="money",
            frequency=financial_frequency,
            max_periods=max_periods,
            show_estimates=show_estimates,
            chart_type=chart_type,
            key_prefix="balance_sheet_v6"
        )
    else:
        st.info("Historique bilan indisponible pour les métriques sélectionnées.")

    st.divider()

    balance_strength_actual = build_balance_strength_actual_long(
        raw,
        financial_frequency
    )

    balance_strength_estimate = (
        build_balance_strength_estimate_long(raw, financial_frequency)
        if show_estimates
        else empty_estimate_long()
    )

    balance_strength_explorer = merge_actual_estimate_long(
        balance_strength_actual,
        balance_strength_estimate
    )

    strength_available_metrics = [
        metric for metric in BALANCE_STRENGTH_DISPLAY_METRICS
        if metric in balance_strength_explorer["Metric"].dropna().unique().tolist()
    ]

    if strength_available_metrics:
        render_unified_financial_explorer_v6(
            title=f"Solidité financière — {financial_frequency.lower()}",
            base_df=balance_strength_explorer,
            available_metrics=strength_available_metrics,
            default_metrics=[
                metric for metric in [
                    "Cash / Debt",
                    "Current Ratio",
                    "Quick Ratio",
                    "Debt / Equity",
                ]
                if metric in strength_available_metrics
            ],
            value_kind="num",
            frequency=financial_frequency,
            max_periods=max_periods,
            show_estimates=show_estimates,
            chart_type=chart_type,
            key_prefix="balance_strength_v6"
        )
    else:
        st.info("Historique de solidité financière indisponible pour les métriques sélectionnées.")


    render_valuation_interactive_v6(raw, valuation, financial_frequency)

    st.divider()

    render_analyst_consensus_intelligence_center_v1(
        analysis=analysis,
        analysts=analysts,
        scores=scores
    )

    st.divider()

    render_latest_news_briefing_v6(company, ticker)

    st.divider()

    render_market_feeling_news_v2(
        company_analysis=company,
        ticker=ticker,
        scores=scores,
    )
