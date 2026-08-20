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

VALUATION_METRIC_KEYS = {
    "P/E": ["peRatio", "priceEarningsRatio", "pe"],
    "P/S": ["priceToSalesRatio", "priceSalesRatio", "psRatio"],
    "P/B": ["pbRatio", "priceToBookRatio", "priceBookValueRatio"],
    "EV/Revenue": ["evToSales", "enterpriseValueOverRevenue", "evToRevenue"],
    "EV/EBITDA": ["enterpriseValueOverEBITDA", "evToEbitda", "enterpriseValueMultiple"],
    "FCF Yield": ["freeCashFlowYield", "fcfYield"],
    "Earnings Yield": ["earningsYield"],
    "PEG": ["pegRatio", "peg"],
}


def build_valuation_history_long(
    company_data: dict,
    frequency: str,
    valuation: dict | None = None
) -> pd.DataFrame:
    """
    Historique valorisation.

    Priorité :
    1) vrais multiples historiques FMP si disponibles ;
    2) fallback normalisé depuis les fondamentaux historiques déjà chargés.

    Le fallback n'est pas un multiple historique de marché pur :
    il utilise la Market Cap / Enterprise Value actuelle contre les fondamentaux historiques.
    Cela permet de garder une vraie lecture utile même si FMP ne fournit pas key metrics / ratios historiques.
    """
    valuation = valuation or {}
    fmp = company_data.get("fmp", {})

    key_metrics_key = "key_metrics_annual" if frequency == "Annuel" else "key_metrics_quarterly"
    ratios_key = "ratios_annual" if frequency == "Annuel" else "ratios_quarterly"

    records = []
    if isinstance(fmp, dict):
        records += fmp.get(key_metrics_key, []) or []
        records += fmp.get(ratios_key, []) or []

    frames = []

    if records:
        fmp_history = records_to_actual_long(
            records,
            VALUATION_METRIC_KEYS,
            frequency,
            "FMP valuation"
        )

        if not fmp_history.empty:
            frames.append(fmp_history)

    info = company_data.get("info", {}) if isinstance(company_data.get("info", {}), dict) else {}

    market_cap = safe_float(
        valuation.get("market_cap")
        or info.get("marketCap")
    )

    enterprise_value = safe_float(
        valuation.get("enterprise_value")
        or info.get("enterpriseValue")
    )

    income_actual = build_income_actual_long(company_data, frequency)
    cash_actual = build_cashflow_actual_long(company_data, frequency)
    balance_actual = build_balance_actual_long(company_data, frequency)

    proxy_rows = []

    income_pivot = pd.DataFrame()

    if not income_actual.empty:
        income_work = income_actual.copy()
        income_work["Date"] = pd.to_datetime(income_work["Date"], errors="coerce")
        income_work["Actual"] = pd.to_numeric(income_work["Actual"], errors="coerce")

        income_values = income_work.pivot_table(
            index=["Period", "Frequency"],
            columns="Metric",
            values="Actual",
            aggfunc="first"
        ).reset_index()

        income_dates = (
            income_work
            .dropna(subset=["Date"])
            .groupby(["Period", "Frequency"], as_index=False)["Date"]
            .max()
        )

        income_pivot = income_values.merge(
            income_dates,
            on=["Period", "Frequency"],
            how="left"
        )

    balance_pivot = pd.DataFrame()

    if not balance_actual.empty:
        balance_work = balance_actual.copy()
        balance_work["Date"] = pd.to_datetime(balance_work["Date"], errors="coerce")
        balance_work["Actual"] = pd.to_numeric(balance_work["Actual"], errors="coerce")

        balance_values = balance_work.pivot_table(
            index=["Period", "Frequency"],
            columns="Metric",
            values="Actual",
            aggfunc="first"
        ).reset_index()

        balance_dates = (
            balance_work
            .dropna(subset=["Date"])
            .groupby(["Period", "Frequency"], as_index=False)["Date"]
            .max()
        )

        balance_pivot = balance_values.merge(
            balance_dates,
            on=["Period", "Frequency"],
            how="left"
        )

    cash_pivot = pd.DataFrame()

    if not cash_actual.empty:
        cash_work = cash_actual.copy()
        cash_work["Date"] = pd.to_datetime(cash_work["Date"], errors="coerce")
        cash_work["Actual"] = pd.to_numeric(cash_work["Actual"], errors="coerce")

        cash_values = cash_work.pivot_table(
            index=["Period", "Frequency"],
            columns="Metric",
            values="Actual",
            aggfunc="first"
        ).reset_index()

        cash_dates = (
            cash_work
            .dropna(subset=["Date"])
            .groupby(["Period", "Frequency"], as_index=False)["Date"]
            .max()
        )

        cash_pivot = cash_values.merge(
            cash_dates,
            on=["Period", "Frequency"],
            how="left"
        )

    def add_proxy(date, period, metric: str, value):
        value = safe_float(value)

        if value is None or pd.isna(value):
            return

        if np.isinf(value):
            return

        proxy_rows.append({
            "Date": date,
            "Period": period,
            "Frequency": frequency,
            "Metric": metric,
            "Actual": value,
            "Source Actual": "Proxy valuation: current market value / historical fundamentals",
        })

    if not income_pivot.empty:
        for _, row in income_pivot.iterrows():
            date = row.get("Date")
            period = row.get("Period")

            revenue = safe_float(row.get("Revenue"))
            net_income = safe_float(row.get("Net Income"))
            ebitda = safe_float(row.get("EBITDA"))

            if market_cap is not None and revenue not in [None, 0]:
                add_proxy(date, period, "P/S", market_cap / revenue)

            if market_cap is not None and net_income not in [None, 0]:
                add_proxy(date, period, "P/E", market_cap / net_income)
                add_proxy(date, period, "Earnings Yield", net_income / market_cap if market_cap else None)

            if enterprise_value is not None and revenue not in [None, 0]:
                add_proxy(date, period, "EV/Revenue", enterprise_value / revenue)

            if enterprise_value is not None and ebitda not in [None, 0]:
                add_proxy(date, period, "EV/EBITDA", enterprise_value / ebitda)

    if not balance_pivot.empty and market_cap is not None:
        for _, row in balance_pivot.iterrows():
            equity = safe_float(row.get("Total Equity"))

            if equity not in [None, 0]:
                add_proxy(
                    row.get("Date"),
                    row.get("Period"),
                    "P/B",
                    market_cap / equity
                )

    if not cash_pivot.empty and market_cap is not None:
        for _, row in cash_pivot.iterrows():
            fcf = safe_float(row.get("Free Cash Flow"))

            if fcf is not None and market_cap not in [None, 0]:
                add_proxy(
                    row.get("Date"),
                    row.get("Period"),
                    "FCF Yield",
                    fcf / market_cap
                )

    if proxy_rows:
        proxy_history = pd.DataFrame(proxy_rows)
        proxy_history["Date"] = pd.to_datetime(proxy_history["Date"], errors="coerce")
        proxy_history["Actual"] = pd.to_numeric(proxy_history["Actual"], errors="coerce")
        proxy_history = proxy_history.dropna(subset=["Actual"])

        if not proxy_history.empty:
            frames.append(proxy_history)

    frames = [df for df in frames if isinstance(df, pd.DataFrame) and not df.empty]

    if not frames:
        return pd.DataFrame(columns=["Date", "Period", "Frequency", "Metric", "Actual", "Source Actual"])

    out = pd.concat(frames, ignore_index=True)
    out["Date"] = pd.to_datetime(out["Date"], errors="coerce")
    out["Actual"] = pd.to_numeric(out["Actual"], errors="coerce")
    out = out.dropna(subset=["Actual"])

    if out.empty:
        return pd.DataFrame(columns=["Date", "Period", "Frequency", "Metric", "Actual", "Source Actual"])

    def valuation_history_priority(source: str) -> int:
        source = str(source or "").lower()

        if "fmp" in source:
            return 0

        if "proxy" in source:
            return 1

        return 9

    out["_priority"] = out["Source Actual"].apply(valuation_history_priority)
    out["_PeriodSort"] = out.apply(
        lambda row: period_sort_key(row.get("Period"), row.get("Date")),
        axis=1
    )

    out = out.sort_values(
        ["_PeriodSort", "Metric", "_priority", "Date"],
        na_position="last"
    )

    out = out.drop_duplicates(
        subset=["Period", "Frequency", "Metric"],
        keep="first"
    )

    out = out.drop(columns=["_priority", "_PeriodSort"], errors="ignore")

    return out[["Date", "Period", "Frequency", "Metric", "Actual", "Source Actual"]]


def build_current_valuation_df(valuation: dict) -> pd.DataFrame:
    rows = [
        {"Metric": "Trailing P/E", "Value": valuation.get("trailing_pe")},
        {"Metric": "Forward P/E", "Value": valuation.get("forward_pe")},
        {"Metric": "PEG", "Value": valuation.get("peg_ratio")},
        {"Metric": "P/S", "Value": valuation.get("price_to_sales")},
        {"Metric": "P/B", "Value": valuation.get("price_to_book")},
        {"Metric": "EV/Revenue", "Value": valuation.get("ev_to_revenue")},
        {"Metric": "EV/EBITDA", "Value": valuation.get("ev_to_ebitda")},
        {"Metric": "Market Cap", "Value": valuation.get("market_cap")},
        {"Metric": "Enterprise Value", "Value": valuation.get("enterprise_value")},
    ]

    return pd.DataFrame(rows)


def valuation_score_from_metric(metric: str, value) -> int | None:
    value = safe_float(value)

    if value is None or pd.isna(value):
        return None

    metric = str(metric)

    if metric in ["Forward P/E"]:
        if value <= 15:
            return 90
        if value <= 25:
            return 75
        if value <= 40:
            return 55
        if value <= 60:
            return 35
        return 20

    if metric in ["Trailing P/E"]:
        if value <= 20:
            return 85
        if value <= 35:
            return 65
        if value <= 55:
            return 45
        if value <= 80:
            return 30
        return 15

    if metric == "PEG":
        if value <= 0:
            return None
        if value <= 0.8:
            return 90
        if value <= 1.2:
            return 80
        if value <= 2.0:
            return 60
        if value <= 3.0:
            return 40
        return 20

    if metric in ["P/S", "EV/Revenue"]:
        if value <= 3:
            return 85
        if value <= 8:
            return 65
        if value <= 15:
            return 45
        if value <= 25:
            return 30
        return 15

    if metric == "EV/EBITDA":
        if value <= 12:
            return 85
        if value <= 25:
            return 65
        if value <= 40:
            return 45
        if value <= 60:
            return 30
        return 15

    if metric == "P/B":
        if value <= 3:
            return 75
        if value <= 8:
            return 55
        if value <= 15:
            return 35
        return 20

    return None


def valuation_signal_from_score(score) -> str:
    score = safe_float(score)

    if score is None:
        return "N/A"

    if score >= 75:
        return "Attractif"
    if score >= 60:
        return "Correct"
    if score >= 45:
        return "Exigeant"
    if score >= 30:
        return "Tendu"
    return "Très tendu"


def valuation_reading(metric: str, value) -> str:
    value = safe_float(value)

    if value is None or pd.isna(value):
        return "Donnée indisponible."

    if metric == "Forward P/E":
        if value <= 25:
            return "Multiple forward raisonnable si la croissance reste solide."
        if value <= 40:
            return "Multiple forward exigeant mais encore acceptable pour un profil croissance."
        return "Multiple forward élevé : la croissance future doit être très robuste."

    if metric == "Trailing P/E":
        if value <= 35:
            return "Multiple trailing encore maîtrisé."
        if value <= 60:
            return "Multiple trailing élevé, à comparer au forward."
        return "Multiple trailing très élevé."

    if metric == "PEG":
        if value <= 1:
            return "PEG favorable : la valorisation reste cohérente avec la croissance attendue."
        if value <= 2:
            return "PEG acceptable."
        return "PEG élevé : croissance attendue moins suffisante face au multiple."

    if metric == "P/S":
        if value <= 8:
            return "Sales multiple acceptable."
        if value <= 15:
            return "Sales multiple exigeant."
        return "Sales multiple très élevé : forte dépendance aux marges et à la croissance."

    if metric == "EV/Revenue":
        if value <= 8:
            return "EV/Revenue acceptable."
        if value <= 15:
            return "EV/Revenue exigeant."
        return "EV/Revenue très élevé."

    if metric == "EV/EBITDA":
        if value <= 25:
            return "EV/EBITDA acceptable pour un profil qualité/croissance."
        if value <= 40:
            return "EV/EBITDA exigeant."
        return "EV/EBITDA très élevé."

    if metric == "P/B":
        if value <= 8:
            return "P/B acceptable."
        return "P/B élevé : le marché price fortement les actifs intangibles / la rentabilité."

    return "Lecture disponible."


def build_valuation_intelligence_table(company_data: dict, valuation: dict) -> pd.DataFrame:
    growth = extract_growth_metrics(company_data)
    profitability = extract_profitability_metrics(company_data)

    trailing_pe = safe_float(valuation.get("trailing_pe"))
    forward_pe = safe_float(valuation.get("forward_pe"))
    peg = safe_float(valuation.get("peg_ratio"))
    ps = safe_float(valuation.get("price_to_sales"))
    pb = safe_float(valuation.get("price_to_book"))
    ev_revenue = safe_float(valuation.get("ev_to_revenue"))
    ev_ebitda = safe_float(valuation.get("ev_to_ebitda"))

    gross_margin = safe_float(profitability.get("gross_margin"))
    operating_margin = safe_float(profitability.get("operating_margin"))
    revenue_growth = safe_float(growth.get("revenue_growth_yoy") or growth.get("annual_revenue_growth"))

    rows = []

    base_metrics = [
        ("Trailing P/E", trailing_pe),
        ("Forward P/E", forward_pe),
        ("PEG", peg),
        ("P/S", ps),
        ("P/B", pb),
        ("EV/Revenue", ev_revenue),
        ("EV/EBITDA", ev_ebitda),
    ]

    for metric, value in base_metrics:
        if value is None or pd.isna(value):
            continue

        score = valuation_score_from_metric(metric, value)

        rows.append({
            "Métrique": metric,
            "Valeur brute": value,
            "Valeur": fmt_num(value),
            "Lecture": valuation_reading(metric, value),
            "Signal": valuation_signal_from_score(score),
            "Score": score,
        })

    if trailing_pe not in [None, 0] and forward_pe is not None:
        pe_compression = forward_pe / trailing_pe - 1

        if pe_compression <= -0.40:
            compression_score = 90
            reading = "Très forte détente du multiple forward : le marché attend une forte progression des bénéfices."
        elif pe_compression <= -0.20:
            compression_score = 75
            reading = "Détente forward nette : amélioration bénéficiaire attendue."
        elif pe_compression <= 0:
            compression_score = 60
            reading = "Légère détente forward."
        else:
            compression_score = 30
            reading = "Pas de détente forward : le forward reste aussi cher ou plus cher que le trailing."

        rows.append({
            "Métrique": "P/E Compression",
            "Valeur brute": pe_compression,
            "Valeur": fmt_pct(pe_compression),
            "Lecture": reading,
            "Signal": valuation_signal_from_score(compression_score),
            "Score": compression_score,
        })

    if ps is not None and gross_margin not in [None, 0]:
        ps_gross_adjusted = ps / gross_margin

        if ps_gross_adjusted <= 10:
            adjusted_score = 80
        elif ps_gross_adjusted <= 20:
            adjusted_score = 60
        elif ps_gross_adjusted <= 35:
            adjusted_score = 40
        else:
            adjusted_score = 20

        rows.append({
            "Métrique": "P/S ajusté marge brute",
            "Valeur brute": ps_gross_adjusted,
            "Valeur": fmt_num(ps_gross_adjusted),
            "Lecture": "P/S corrigé par la marge brute : utile pour juger si un sales multiple élevé est soutenu par la qualité économique.",
            "Signal": valuation_signal_from_score(adjusted_score),
            "Score": adjusted_score,
        })

    if ps is not None and revenue_growth not in [None, 0]:
        ps_growth_adjusted = ps / abs(revenue_growth)

        if ps_growth_adjusted <= 60:
            growth_score = 80
        elif ps_growth_adjusted <= 120:
            growth_score = 60
        elif ps_growth_adjusted <= 220:
            growth_score = 40
        else:
            growth_score = 20

        rows.append({
            "Métrique": "P/S ajusté croissance",
            "Valeur brute": ps_growth_adjusted,
            "Valeur": fmt_num(ps_growth_adjusted),
            "Lecture": "P/S rapporté à la croissance du revenu : plus il est bas, plus la croissance compense le multiple de ventes.",
            "Signal": valuation_signal_from_score(growth_score),
            "Score": growth_score,
        })

    if not rows:
        return pd.DataFrame(columns=["Métrique", "Valeur brute", "Valeur", "Lecture", "Signal", "Score"])

    out = pd.DataFrame(rows)
    out["Score"] = pd.to_numeric(out["Score"], errors="coerce")

    return out


def valuation_metric_weight(metric: str) -> float:
    """
    Pondération du score de valorisation.

    Objectif :
    - donner plus de poids aux métriques forward/growth ;
    - ne pas sur-pénaliser les sociétés growth avec P/S ou P/B élevés ;
    - garder les métriques absolues dans le score, mais avec moins de poids.
    """
    weights = {
        "Forward P/E": 2.40,
        "PEG": 2.00,
        "P/E Compression": 2.00,
        "P/S ajusté croissance": 1.50,
        "EV/EBITDA": 1.20,
        "Trailing P/E": 0.90,
        "P/S ajusté marge brute": 0.80,
        "P/S": 0.70,
        "EV/Revenue": 0.70,
        "P/B": 0.40,
    }

    return float(weights.get(str(metric), 1.00))


def valuation_global_score(scorecard: pd.DataFrame) -> int:
    """
    Score global de valorisation pondéré.
    logique :
    - Forward P/E, PEG, P/E Compression et P/S ajusté croissance pèsent davantage ;
    - P/S, P/B et EV/Revenue restent pris en compte, mais ne dominent plus tout le score ;
    - fallback propre à 50 si données insuffisantes.
    """
    if scorecard is None or scorecard.empty or "Score" not in scorecard.columns:
        return 50

    work = scorecard.copy()
    work["Score Numeric"] = pd.to_numeric(work["Score"], errors="coerce")

    if "Métrique" not in work.columns:
        scores = work["Score Numeric"].dropna()
        if scores.empty:
            return 50
        return int(clamp(round(scores.mean())))

    work["Weight"] = work["Métrique"].apply(valuation_metric_weight)

    work = work[
        work["Score Numeric"].notna()
        & work["Weight"].notna()
        & (work["Weight"] > 0)
    ].copy()

    if work.empty:
        return 50

    weighted_score = np.average(
        work["Score Numeric"],
        weights=work["Weight"]
    )

    return int(clamp(round(weighted_score)))


def valuation_global_verdict(score: int) -> str:
    if score >= 75:
        return "Valorisation attractive au regard du profil forward et des métriques disponibles."
    if score >= 65:
        return "Valorisation correcte, soutenue par le forward si la croissance se confirme."
    if score >= 55:
        return "Valorisation exigeante mais soutenable si les bénéfices et la croissance continuent de délivrer."
    if score >= 40:
        return "Valorisation exigeante : le titre doit continuer à délivrer, avec peu de marge d'erreur."
    return "Valorisation très tendue : marge d'erreur faible et risque élevé de décompression."


def generate_valuation_diagnosis(company_data: dict, valuation: dict, scorecard: pd.DataFrame) -> str:
    score = valuation_global_score(scorecard)

    trailing_pe = safe_float(valuation.get("trailing_pe"))
    forward_pe = safe_float(valuation.get("forward_pe"))
    peg = safe_float(valuation.get("peg_ratio"))
    ps = safe_float(valuation.get("price_to_sales"))
    ev_ebitda = safe_float(valuation.get("ev_to_ebitda"))

    parts = [valuation_global_verdict(score)]

    if trailing_pe not in [None, 0] and forward_pe is not None:
        compression = forward_pe / trailing_pe - 1

        if compression <= -0.35:
            parts.append("La forte baisse entre Trailing P/E et Forward P/E indique que le marché price une progression importante des bénéfices.")
        elif compression < 0:
            parts.append("Le Forward P/E est inférieur au Trailing P/E, ce qui améliore la lecture de valorisation.")
        else:
            parts.append("Le Forward P/E ne montre pas de détente claire face au Trailing P/E.")

    if peg is not None:
        if peg <= 1:
            parts.append("Le PEG est favorable.")
        elif peg > 2:
            parts.append("Le PEG est élevé.")

    if ps is not None and ps > 15:
        parts.append("Le P/S reste très exigeant : le marché valorise fortement la croissance future et les marges.")

    if ev_ebitda is not None and ev_ebitda > 40:
        parts.append("L'EV/EBITDA est élevé, ce qui réduit la marge de sécurité.")

    return " ".join(parts)


def build_forward_valuation_bridge_df(company_data: dict, valuation: dict) -> pd.DataFrame:
    """
    Forward Multiple Compression View.

    Objectif :
    - élargir la vue Trailing vs Forward au-delà du P/E ;
    - garder le P/E direct quand yfinance le fournit ;
    - calculer P/S forward, EV/Revenue forward et EV/EBITDA forward depuis les estimates annuelles ;
    - fallback prudent : si annual estimates indisponibles, agrégation des 4 prochains trimestres ;
    - ne modifie aucun actual, aucun estimate, aucun provider, aucun merge.
    """
    info = company_data.get("info", {}) if isinstance(company_data.get("info", {}), dict) else {}

    market_cap = safe_float(valuation.get("market_cap"))
    if market_cap is None:
        market_cap = safe_float(info.get("marketCap"))

    enterprise_value = safe_float(valuation.get("enterprise_value"))
    if enterprise_value is None:
        enterprise_value = safe_float(info.get("enterpriseValue"))

    trailing_pe = safe_float(valuation.get("trailing_pe"))
    forward_pe = safe_float(valuation.get("forward_pe"))

    current_ps = safe_float(valuation.get("price_to_sales"))
    current_ev_revenue = safe_float(valuation.get("ev_to_revenue"))
    current_ev_ebitda = safe_float(valuation.get("ev_to_ebitda"))

    income_estimates_annual = build_income_estimate_long(company_data, "Annuel")
    income_actual_annual = build_income_actual_long(company_data, "Annuel")

    income_estimates_quarterly = build_income_estimate_long(company_data, "Trimestriel")
    income_actual_quarterly = build_income_actual_long(company_data, "Trimestriel")

    def latest_actual_sort(actual_df: pd.DataFrame):
        if actual_df is None or actual_df.empty:
            return None

        work = actual_df.copy()
        work["Date"] = pd.to_datetime(work.get("Date"), errors="coerce")
        work["_PeriodSort"] = work.apply(
            lambda row: period_sort_key(row.get("Period"), row.get("Date")),
            axis=1
        )

        valid = work[work["Actual"].notna()].copy()

        if valid.empty:
            return None

        return safe_float(valid["_PeriodSort"].max())

    latest_annual_sort = latest_actual_sort(income_actual_annual)
    latest_quarterly_sort = latest_actual_sort(income_actual_quarterly)

    def best_forward_estimate(estimates_df: pd.DataFrame, metric: str, latest_sort_value):
        if estimates_df is None or estimates_df.empty:
            return None

        if "Metric" not in estimates_df.columns or "Estimate" not in estimates_df.columns:
            return None

        work = estimates_df[
            (estimates_df["Metric"].astype(str) == str(metric))
            & estimates_df["Estimate"].notna()
        ].copy()

        if work.empty:
            return None

        work["Date Estimate"] = pd.to_datetime(work.get("Date Estimate"), errors="coerce")
        work["Estimate"] = pd.to_numeric(work["Estimate"], errors="coerce")
        work = work.dropna(subset=["Estimate"])

        if work.empty:
            return None

        work["_PeriodSort"] = work.apply(
            lambda row: period_sort_key(row.get("Period"), row.get("Date Estimate")),
            axis=1
        )

        if latest_sort_value is not None:
            future = work[work["_PeriodSort"] > latest_sort_value].copy()
        else:
            future = work.copy()

        if future.empty:
            future = work.copy()

        future["_priority"] = future["Source Estimate"].apply(estimate_source_priority)

        future = future.sort_values(
            ["_PeriodSort", "_priority", "Date Estimate"],
            ascending=[True, True, False],
            na_position="last"
        )

        row = future.iloc[0]

        return {
            "value": safe_float(row.get("Estimate")),
            "period": row.get("Period"),
            "date": row.get("Date Estimate"),
            "source": row.get("Source Estimate"),
            "basis": "Annual estimate",
        }

    def aggregate_next_quarters(metric: str, quarters: int = 4):
        if income_estimates_quarterly is None or income_estimates_quarterly.empty:
            return None

        work = income_estimates_quarterly[
            (income_estimates_quarterly["Metric"].astype(str) == str(metric))
            & income_estimates_quarterly["Estimate"].notna()
        ].copy()

        if work.empty:
            return None

        work["Date Estimate"] = pd.to_datetime(work.get("Date Estimate"), errors="coerce")
        work["Estimate"] = pd.to_numeric(work["Estimate"], errors="coerce")
        work = work.dropna(subset=["Estimate"])

        if work.empty:
            return None

        work["_PeriodSort"] = work.apply(
            lambda row: period_sort_key(row.get("Period"), row.get("Date Estimate")),
            axis=1
        )

        if latest_quarterly_sort is not None:
            work = work[work["_PeriodSort"] > latest_quarterly_sort].copy()

        if work.empty:
            return None

        work["_priority"] = work["Source Estimate"].apply(estimate_source_priority)

        work = work.sort_values(
            ["_PeriodSort", "_priority", "Date Estimate"],
            ascending=[True, True, False],
            na_position="last"
        )

        work = work.drop_duplicates(
            subset=["Period", "Frequency", "Metric"],
            keep="first"
        )

        selected = work.head(quarters).copy()

        if selected.empty:
            return None

        estimate_sum = safe_float(selected["Estimate"].sum())

        if estimate_sum is None:
            return None

        periods = selected["Period"].astype(str).tolist()
        sources = selected["Source Estimate"].dropna().astype(str).unique().tolist()

        return {
            "value": estimate_sum,
            "period": " + ".join(periods),
            "date": selected["Date Estimate"].max(),
            "source": "Quarterly aggregate: " + " / ".join(sources[:3]),
            "basis": f"Next {len(selected)} quarters aggregate",
        }

    def get_forward_fundamental(metric: str):
        annual = best_forward_estimate(
            income_estimates_annual,
            metric,
            latest_annual_sort
        )

        if annual is not None and annual.get("value") not in [None, 0]:
            return annual

        quarterly = aggregate_next_quarters(metric)

        if quarterly is not None and quarterly.get("value") not in [None, 0]:
            return quarterly

        return None

    revenue_forward = get_forward_fundamental("Revenue")
    ebitda_forward = get_forward_fundamental("EBITDA")
    net_income_forward = get_forward_fundamental("Net Income")

    rows = []

    def add_bridge_row(
        metric: str,
        current_label: str,
        forward_label: str,
        current_value,
        forward_value,
        forward_period,
        forward_source,
        forward_basis,
    ):
        current_value = safe_float(current_value)
        forward_value = safe_float(forward_value)

        if current_value is None or forward_value is None:
            return

        if current_value == 0 or pd.isna(current_value) or pd.isna(forward_value):
            return

        compression = forward_value / current_value - 1

        current_score = valuation_score_from_metric(current_label, current_value)
        forward_score = valuation_score_from_metric(forward_label, forward_value)

        rows.append({
            "Metric": metric,
            "Current Label": current_label,
            "Forward Label": forward_label,
            "Current Multiple": current_value,
            "Forward Multiple": forward_value,
            "Compression": compression,
            "Forward Period": forward_period,
            "Forward Basis": forward_basis,
            "Source": forward_source,
            "Current Score": current_score,
            "Forward Score": forward_score,
        })

    # P/E : priorité au forwardPE direct.
    computed_forward_pe = forward_pe
    forward_pe_period = "Forward"
    forward_pe_source = "yfinance forwardPE"
    forward_pe_basis = "Direct forward multiple"

    if computed_forward_pe is None and market_cap is not None and net_income_forward is not None:
        net_income_value = safe_float(net_income_forward.get("value"))

        if net_income_value not in [None, 0]:
            computed_forward_pe = market_cap / net_income_value
            forward_pe_period = net_income_forward.get("period")
            forward_pe_source = f"Market Cap / Net Income estimate · {net_income_forward.get('source')}"
            forward_pe_basis = net_income_forward.get("basis")

    add_bridge_row(
        metric="P/E",
        current_label="Trailing P/E",
        forward_label="Forward P/E",
        current_value=trailing_pe,
        forward_value=computed_forward_pe,
        forward_period=forward_pe_period,
        forward_source=forward_pe_source,
        forward_basis=forward_pe_basis,
    )

    # P/S forward = Market Cap / Revenue forward.
    if market_cap is not None and revenue_forward is not None:
        revenue_value = safe_float(revenue_forward.get("value"))

        if revenue_value not in [None, 0]:
            add_bridge_row(
                metric="P/S",
                current_label="P/S",
                forward_label="P/S",
                current_value=current_ps,
                forward_value=market_cap / revenue_value,
                forward_period=revenue_forward.get("period"),
                forward_source=f"Market Cap / Revenue estimate · {revenue_forward.get('source')}",
                forward_basis=revenue_forward.get("basis"),
            )

    # EV/Revenue forward = Enterprise Value / Revenue forward.
    if enterprise_value is not None and revenue_forward is not None:
        revenue_value = safe_float(revenue_forward.get("value"))

        if revenue_value not in [None, 0]:
            add_bridge_row(
                metric="EV/Revenue",
                current_label="EV/Revenue",
                forward_label="EV/Revenue",
                current_value=current_ev_revenue,
                forward_value=enterprise_value / revenue_value,
                forward_period=revenue_forward.get("period"),
                forward_source=f"Enterprise Value / Revenue estimate · {revenue_forward.get('source')}",
                forward_basis=revenue_forward.get("basis"),
            )

    # EV/EBITDA forward = Enterprise Value / EBITDA forward.
    if enterprise_value is not None and ebitda_forward is not None:
        ebitda_value = safe_float(ebitda_forward.get("value"))

        if ebitda_value not in [None, 0]:
            add_bridge_row(
                metric="EV/EBITDA",
                current_label="EV/EBITDA",
                forward_label="EV/EBITDA",
                current_value=current_ev_ebitda,
                forward_value=enterprise_value / ebitda_value,
                forward_period=ebitda_forward.get("period"),
                forward_source=f"Enterprise Value / EBITDA estimate · {ebitda_forward.get('source')}",
                forward_basis=ebitda_forward.get("basis"),
            )

    if not rows:
        return pd.DataFrame(columns=[
            "Metric",
            "Current Label",
            "Forward Label",
            "Current Multiple",
            "Forward Multiple",
            "Compression",
            "Forward Period",
            "Forward Basis",
            "Source",
            "Current Score",
            "Forward Score",
        ])

    out = pd.DataFrame(rows)
    out["Current Multiple"] = pd.to_numeric(out["Current Multiple"], errors="coerce")
    out["Forward Multiple"] = pd.to_numeric(out["Forward Multiple"], errors="coerce")
    out["Compression"] = pd.to_numeric(out["Compression"], errors="coerce")

    metric_order = {
        "P/E": 0,
        "P/S": 1,
        "EV/Revenue": 2,
        "EV/EBITDA": 3,
    }

    out["_order"] = out["Metric"].map(lambda x: metric_order.get(str(x), 999))
    out = out.sort_values("_order").drop(columns=["_order"], errors="ignore")

    return out


def short_valuation_forward_source(source: str) -> str:
    """
    Source courte pour la table Trailing vs Forward.

    Objectif : garder la table lisible sans modifier la donnée brute.
    La colonne Source du bridge peut contenir le détail complet de calcul ;
    ici on affiche seulement une lecture compacte côté UI.
    """
    raw = str(source or "").strip()

    if not raw:
        return "N/A"

    s = raw.lower()

    if "yfinance forwardpe" in s:
        return "Direct yfinance"

    if "market cap / net income" in s:
        calc = "Market Cap / Net Income est."
    elif "market cap / revenue" in s:
        calc = "Market Cap / Revenue est."
    elif "enterprise value / revenue" in s:
        calc = "EV / Revenue est."
    elif "enterprise value / ebitda" in s:
        calc = "EV / EBITDA est."
    else:
        calc = "Forward estimate"

    if "alpha vantage" in s:
        provider = "Alpha"
    elif "fmp" in s:
        provider = "FMP"
    elif "finnhub" in s:
        provider = "Finnhub"
    elif "quarterly aggregate" in s:
        provider = "Quarterly aggregate"
    elif "proxy" in s:
        provider = "Proxy"
    else:
        provider = "Estimate"

    return f"{calc} · {provider}"


def render_valuation_interactive_v6(company_data: dict, valuation: dict, frequency: str):
    st.subheader("Valorisation — Intelligence Center")

    current_df = build_current_valuation_df(valuation)
    history = build_valuation_history_long(company_data, frequency, valuation)
    scorecard = build_valuation_intelligence_table(company_data, valuation)

    if scorecard.empty:
        st.info("Aucune donnée de valorisation exploitable.")
        return

    global_score = valuation_global_score(scorecard)
    diagnosis = generate_valuation_diagnosis(company_data, valuation, scorecard)

    trailing_pe = safe_float(valuation.get("trailing_pe"))
    forward_pe = safe_float(valuation.get("forward_pe"))
    peg = safe_float(valuation.get("peg_ratio"))
    ps = safe_float(valuation.get("price_to_sales"))
    ev_ebitda = safe_float(valuation.get("ev_to_ebitda"))
    market_cap = safe_float(valuation.get("market_cap"))

    pe_compression = None
    if trailing_pe not in [None, 0] and forward_pe is not None:
        pe_compression = forward_pe / trailing_pe - 1

    kpi_cols = st.columns(6)

    kpi_cols[0].metric(
        "Valuation Score",
        f"{global_score}/100"
    )

    kpi_cols[1].metric(
        "Forward P/E",
        fmt_num(forward_pe)
    )

    kpi_cols[2].metric(
        "P/E compression",
        fmt_pct(pe_compression)
    )

    kpi_cols[3].metric(
        "PEG",
        fmt_num(peg)
    )

    kpi_cols[4].metric(
        "P/S",
        fmt_num(ps)
    )

    kpi_cols[5].metric(
        "Market Cap",
        fmt_large_number(market_cap)
    )

    st.caption(diagnosis)

    with st.expander("Table de lecture valorisation", expanded=True):
        display_scorecard = scorecard[
            ["Métrique", "Valeur", "Lecture", "Signal", "Score"]
        ].copy()

        st.dataframe(
            display_scorecard,
            use_container_width=True,
            hide_index=True
        )

    available_metrics = scorecard["Métrique"].dropna().unique().tolist()

    default_metrics = [
        m for m in [
            "Forward P/E",
            "PEG",
            "P/S",
            "EV/Revenue",
            "EV/EBITDA",
            "P/E Compression",
            "P/S ajusté marge brute",
        ]
        if m in available_metrics
    ]

    selected_metrics = st.multiselect(
        "Métriques de valorisation affichées",
        available_metrics,
        default=default_metrics,
        key="valuation_intelligence_selected_metrics"
    )

    mode = st.radio(
        "Vue valorisation",
        [
            "Scorecard",
            "Multiples actuels",
            "Trailing vs Forward",
            "Historique focus",
        ],
        horizontal=True,
        key="valuation_intelligence_mode"
    )

    if not selected_metrics:
        st.info("Sélectionne au moins une métrique.")
        return

    selected_scorecard = scorecard[
        scorecard["Métrique"].isin(selected_metrics)
    ].copy()

    if mode == "Scorecard":
        plot_df = selected_scorecard.dropna(subset=["Score"]).copy()

        if plot_df.empty:
            st.info("Aucun score exploitable pour les métriques sélectionnées.")
            return

        plot_df = plot_df.sort_values("Score", ascending=True)

        fig = go.Figure()

        fig.add_trace(go.Bar(
            x=plot_df["Score"],
            y=plot_df["Métrique"],
            orientation="h",
            name="Score"
        ))

        fig.add_vline(
            x=50,
            line_dash="dash",
            annotation_text="Neutre",
            annotation_position="top"
        )

        fig.update_layout(
            height=520,
            title="Scorecard de valorisation",
            xaxis_title="Score",
            yaxis_title="Métrique",
            xaxis=dict(range=[0, 100]),
            margin=dict(l=20, r=20, t=70, b=40)
        )

        st.plotly_chart(fig, use_container_width=True)

    elif mode == "Multiples actuels":
        # ------------------------------------------------------------
        # Vue Multiples actuels — version lisible / robuste
        # ------------------------------------------------------------
        # Objectif :
        # - garder uniquement les vrais multiples actuels ;
        # - éviter que PEG soit invisible à cause de l'échelle brute ;
        # - afficher une lecture normalisée par défaut ;
        # - conserver une vue brute disponible ;
        # - ne pas toucher au score global, aux données, aux autres vues.
        # ------------------------------------------------------------

        raw_multiple_order = [
            "Forward P/E",
            "PEG",
            "P/S",
            "EV/Revenue",
            "EV/EBITDA",
            "Trailing P/E",
            "P/B",
        ]

        plot_df = selected_scorecard[
            selected_scorecard["Métrique"].isin(raw_multiple_order)
        ].copy()

        plot_df["Valeur brute"] = pd.to_numeric(
            plot_df["Valeur brute"],
            errors="coerce"
        )

        plot_df["Score Numeric"] = pd.to_numeric(
            plot_df["Score"],
            errors="coerce"
        )

        plot_df = plot_df.dropna(subset=["Valeur brute"])

        if plot_df.empty:
            st.info("Aucun multiple actuel exploitable pour cette vue.")
            return

        plot_df["_order"] = plot_df["Métrique"].apply(
            lambda metric: raw_multiple_order.index(metric)
            if metric in raw_multiple_order
            else 999
        )

        plot_df = plot_df.sort_values("_order").copy()

        plot_df["Valeur label"] = plot_df["Valeur brute"].apply(fmt_num)
        plot_df["Score label"] = plot_df["Score Numeric"].apply(
            lambda value: "N/A" if pd.isna(value) else f"{value:.0f}/100"
        )

        if "Signal" not in plot_df.columns:
            plot_df["Signal"] = "N/A"

        view_mode = st.radio(
            "Lecture des multiples",
            [
                "Lecture normalisée",
                "Valeurs brutes",
            ],
            horizontal=True,
            key="valuation_multiples_current_view_mode"
        )

        valid_score_rows = plot_df.dropna(subset=["Score Numeric"]).copy()

        if not valid_score_rows.empty:
            best_row = valid_score_rows.sort_values("Score Numeric", ascending=False).iloc[0]
            tightest_row = valid_score_rows.sort_values("Score Numeric", ascending=True).iloc[0]

            col1, col2, col3 = st.columns(3)

            col1.metric(
                "Multiple le plus favorable",
                str(best_row["Métrique"]),
                f"{best_row['Valeur label']} · {best_row['Score label']}"
            )

            col2.metric(
                "Multiple le plus exigeant",
                str(tightest_row["Métrique"]),
                f"{tightest_row['Valeur label']} · {tightest_row['Score label']}"
            )

            avg_score = safe_float(valid_score_rows["Score Numeric"].mean())

            col3.metric(
                "Score moyen des multiples affichés",
                "N/A" if avg_score is None else f"{avg_score:.0f}/100"
            )

        compact_table = plot_df[
            ["Métrique", "Valeur", "Signal", "Score"]
        ].copy()

        with st.expander("Détail des multiples affichés", expanded=False):
            st.dataframe(
                compact_table,
                use_container_width=True,
                hide_index=True
            )

        fig = go.Figure()

        if view_mode == "Lecture normalisée":
            normalized_df = plot_df.dropna(subset=["Score Numeric"]).copy()

            if normalized_df.empty:
                st.info("Aucun score exploitable pour normaliser les multiples.")
                return

            customdata = np.stack(
                [
                    normalized_df["Valeur label"].astype(str),
                    normalized_df["Signal"].astype(str),
                    normalized_df["Score label"].astype(str),
                ],
                axis=-1
            )

            fig.add_trace(go.Bar(
                x=normalized_df["Métrique"],
                y=normalized_df["Score Numeric"],
                text=normalized_df["Valeur label"],
                textposition="outside",
                customdata=customdata,
                name="Score de valorisation",
                hovertemplate=(
                    "<b>%{x}</b><br>"
                    "Valeur brute : %{customdata[0]}<br>"
                    "Signal : %{customdata[1]}<br>"
                    "Score : %{customdata[2]}"
                    "<extra></extra>"
                )
            ))

            fig.add_hline(
                y=50,
                line_dash="dash",
                annotation_text="Neutre",
                annotation_position="right"
            )

            fig.update_layout(
                height=540,
                title="Multiples actuels — lecture normalisée",
                xaxis_title="Multiple",
                yaxis_title="Score de valorisation",
                yaxis=dict(range=[0, 105]),
                margin=dict(l=20, r=20, t=70, b=40),
                hovermode="x unified"
            )

            st.caption(
                "Lecture normalisée : la hauteur représente le score de valorisation, "
                "le label au-dessus de chaque barre conserve la valeur brute du multiple. "
                "Cela évite que les petits ratios comme le PEG soient écrasés par les multiples élevés."
            )

        else:
            raw_df = plot_df.copy()

            customdata = np.stack(
                [
                    raw_df["Valeur label"].astype(str),
                    raw_df["Signal"].astype(str),
                    raw_df["Score label"].astype(str),
                ],
                axis=-1
            )

            fig.add_trace(go.Bar(
                x=raw_df["Métrique"],
                y=raw_df["Valeur brute"],
                text=raw_df["Valeur label"],
                textposition="outside",
                customdata=customdata,
                name="Valeur brute",
                hovertemplate=(
                    "<b>%{x}</b><br>"
                    "Valeur brute : %{customdata[0]}<br>"
                    "Signal : %{customdata[1]}<br>"
                    "Score : %{customdata[2]}"
                    "<extra></extra>"
                )
            ))

            score_overlay = raw_df.dropna(subset=["Score Numeric"]).copy()

            if not score_overlay.empty:
                fig.add_trace(go.Scatter(
                    x=score_overlay["Métrique"],
                    y=score_overlay["Score Numeric"],
                    mode="lines+markers+text",
                    text=score_overlay["Score label"],
                    textposition="top center",
                    name="Score",
                    yaxis="y2",
                    hovertemplate=(
                        "<b>%{x}</b><br>"
                        "Score : %{text}"
                        "<extra></extra>"
                    )
                ))

            fig.update_layout(
                height=540,
                title="Multiples actuels — valeurs brutes + score",
                xaxis_title="Multiple",
                yaxis_title="Valeur brute",
                yaxis2=dict(
                    title="Score",
                    overlaying="y",
                    side="right",
                    range=[0, 100],
                    showgrid=False
                ),
                margin=dict(l=20, r=20, t=70, b=40),
                hovermode="x unified"
            )

            st.caption(
                "Vue brute : les barres affichent les valeurs réelles des multiples. "
                "La ligne secondaire affiche le score afin de garder une lecture qualitative même quand les échelles sont très différentes."
            )

        st.plotly_chart(fig, use_container_width=True)


    elif mode == "Trailing vs Forward":
    # ------------------------------------------------------------
    # Forward Multiple Compression View
    # ------------------------------------------------------------
    # Avant : vue limitée à Trailing P/E vs Forward P/E.
    # Maintenant :
    # - P/E : Trailing P/E vs Forward P/E ;
    # - P/S : P/S actuel vs Market Cap / Revenue forward ;
    # - EV/Revenue : EV/Revenue actuel vs EV / Revenue forward ;
    # - EV/EBITDA : EV/EBITDA actuel vs EV / EBITDA forward.
    #
    # Important :
    # - ne touche pas aux estimates ;
    # - ne touche pas aux actuals ;
    # - ne touche pas aux autres vues ;
    # - utilise annual estimates en priorité, puis fallback 4 prochains trimestres.
    # ------------------------------------------------------------

        bridge_df = build_forward_valuation_bridge_df(company_data, valuation)

        if bridge_df.empty:
            st.info(
                "Forward multiple compression indisponible : il faut au minimum "
                "un multiple actuel et une estimate forward exploitable."
            )
            return

        def bridge_metric_selected(metric: str) -> bool:
            metric = str(metric)

            if metric == "P/E":
                return any(
                    m in selected_metrics
                    for m in ["Trailing P/E", "Forward P/E", "P/E Compression"]
                )

            return metric in selected_metrics

        bridge_df = bridge_df[
            bridge_df["Metric"].apply(bridge_metric_selected)
        ].copy()

        if bridge_df.empty:
            st.info(
                "Aucun multiple forward compatible avec les métriques sélectionnées. "
                "Ajoute Forward P/E, P/S, EV/Revenue ou EV/EBITDA dans le multiselect."
            )
            return

        bridge_df["Current Label Value"] = bridge_df["Current Multiple"].apply(fmt_num)
        bridge_df["Forward Label Value"] = bridge_df["Forward Multiple"].apply(fmt_num)
        bridge_df["Compression Label"] = bridge_df["Compression"].apply(fmt_pct)

        valid_compression = bridge_df.dropna(subset=["Compression"]).copy()

        if not valid_compression.empty:
            strongest_discount = valid_compression.sort_values(
                "Compression",
                ascending=True
            ).iloc[0]

            avg_compression = safe_float(valid_compression["Compression"].mean())

            demanding_candidates = bridge_df.dropna(subset=["Forward Multiple"]).copy()
            demanding_candidates["Forward Score Numeric"] = pd.to_numeric(
                demanding_candidates.get("Forward Score"),
                errors="coerce"
            )

            if demanding_candidates["Forward Score Numeric"].notna().any():
                most_demanding = (
                    demanding_candidates
                    .sort_values(
                        ["Forward Score Numeric", "Forward Multiple"],
                        ascending=[True, False],
                        na_position="last"
                    )
                    .iloc[0]
                )
            else:
                most_demanding = (
                    demanding_candidates
                    .sort_values("Forward Multiple", ascending=False)
                    .iloc[0]
                )

            col1, col2, col3 = st.columns(3)

            col1.metric(
                "Plus forte détente forward",
                str(strongest_discount["Metric"]),
                fmt_pct(strongest_discount["Compression"])
            )

            col2.metric(
                "Multiple forward le moins attractif",
                str(most_demanding["Metric"])
            )

            forward_score = safe_float(most_demanding.get("Forward Score"))
            forward_score_label = (
                "N/A" if forward_score is None else f"{forward_score:.0f}/100"
            )

            col2.caption(
                f"{fmt_num(most_demanding.get('Forward Multiple'))}x forward · score {forward_score_label}"
            )

            col3.metric(
                "Compression moyenne",
                fmt_pct(avg_compression)
            )

        st.caption(
            "Lecture : les barres comparent le multiple actuel au multiple forward recalculé. "
            "Pour P/S, EV/Revenue et EV/EBITDA, le forward est calculé avec les estimates annuelles en priorité ; "
            "si elles manquent, le modèle agrège les prochains trimestres disponibles."
        )

        display_bridge = bridge_df[
            [
                "Metric",
                "Current Label",
                "Current Multiple",
                "Forward Label",
                "Forward Multiple",
                "Compression",
                "Forward Period",
                "Forward Basis",
                "Source",
                "Current Score",
                "Forward Score",
            ]
        ].copy()

        display_bridge["Current Multiple"] = display_bridge["Current Multiple"].apply(fmt_num)
        display_bridge["Forward Multiple"] = display_bridge["Forward Multiple"].apply(fmt_num)
        display_bridge["Compression"] = display_bridge["Compression"].apply(fmt_pct)
        display_bridge["Source"] = display_bridge["Source"].apply(short_valuation_forward_source)
        display_bridge["Current Score"] = display_bridge["Current Score"].apply(
            lambda x: "N/A" if pd.isna(x) else f"{float(x):.0f}/100"
        )
        display_bridge["Forward Score"] = display_bridge["Forward Score"].apply(
            lambda x: "N/A" if pd.isna(x) else f"{float(x):.0f}/100"
        )

        display_bridge = display_bridge.rename(columns={
            "Metric": "Multiple",
            "Current Label": "Base actuelle",
            "Current Multiple": "Multiple actuel",
            "Forward Label": "Base forward",
            "Forward Multiple": "Multiple forward",
            "Compression": "Compression / détente",
            "Forward Period": "Période forward",
            "Forward Basis": "Base de calcul",
            "Source": "Source",
            "Current Score": "Score actuel",
            "Forward Score": "Score forward",
        })

        with st.expander("Détail de la compression forward", expanded=False):
            st.dataframe(
                display_bridge,
                use_container_width=True,
                hide_index=True
            )

        fig = go.Figure()

        fig.add_trace(go.Bar(
            x=bridge_df["Metric"],
            y=bridge_df["Current Multiple"],
            text=bridge_df["Current Label Value"],
            textposition="outside",
            name="Multiple actuel",
            customdata=np.stack(
                [
                    bridge_df["Current Label"].astype(str),
                    bridge_df["Current Label Value"].astype(str),
                ],
                axis=-1
            ),
            hovertemplate=(
                "<b>%{x}</b><br>"
                "Base : %{customdata[0]}<br>"
                "Multiple actuel : %{customdata[1]}"
                "<extra></extra>"
            )
        ))

        fig.add_trace(go.Bar(
            x=bridge_df["Metric"],
            y=bridge_df["Forward Multiple"],
            text=bridge_df["Forward Label Value"],
            textposition="outside",
            name="Multiple forward",
            customdata=np.stack(
                [
                    bridge_df["Forward Label"].astype(str),
                    bridge_df["Forward Label Value"].astype(str),
                    bridge_df["Forward Period"].astype(str),
                    bridge_df["Forward Basis"].astype(str),
                ],
                axis=-1
            ),
            hovertemplate=(
                "<b>%{x}</b><br>"
                "Base : %{customdata[0]}<br>"
                "Multiple forward : %{customdata[1]}<br>"
                "Période : %{customdata[2]}<br>"
                "Calcul : %{customdata[3]}"
                "<extra></extra>"
            )
        ))

        fig.add_trace(go.Scatter(
            x=bridge_df["Metric"],
            y=bridge_df["Compression"],
            mode="lines+markers+text",
            text=bridge_df["Compression Label"],
            textposition="top center",
            name="Compression %",
            yaxis="y2",
            hovertemplate=(
                "<b>%{x}</b><br>"
                "Compression : %{text}"
                "<extra></extra>"
            )
        ))

        fig.add_hline(
            y=0,
            line_dash="dot",
            annotation_text="0",
            annotation_position="right"
        )

        fig.update_layout(
            height=560,
            title="Forward Multiple Compression View",
            xaxis_title="Multiple",
            yaxis_title="Multiple",
            yaxis2=dict(
                title="Compression / détente",
                overlaying="y",
                side="right",
                tickformat=".0%",
                showgrid=False
            ),
            barmode="group",
            hovermode="x unified",
            margin=dict(l=20, r=20, t=70, b=40)
        )

        st.plotly_chart(fig, use_container_width=True)

    elif mode == "Historique focus":
        if history.empty:
            st.info(
                "Historique de valorisation indisponible : aucune donnée FMP ni fondamentaux suffisants "
                "pour construire une lecture historique normalisée."
            )
            return

        available_history = sorted(history["Metric"].dropna().unique().tolist())

        if not available_history:
            st.info("Aucun multiple historique exploitable.")
            return

        focus = st.selectbox(
            "Multiple historique",
            available_history,
            key="valuation_intelligence_history_focus"
        )

        sub = history[history["Metric"] == focus].copy()
        sub = limit_explorer_periods(sub, 12)

        if sub.empty:
            st.info("Aucun historique exploitable pour ce multiple.")
            return

        sub["Date"] = pd.to_datetime(sub["Date"], errors="coerce")
        sub["Actual"] = pd.to_numeric(sub["Actual"], errors="coerce")
        sub = sub.dropna(subset=["Actual"])

        if sub.empty:
            st.info("Aucun historique numérique exploitable pour ce multiple.")
            return

        sub["_PeriodSort"] = sub.apply(
            lambda row: period_sort_key(row.get("Period"), row.get("Date")),
            axis=1
        )

        sub = sub.sort_values("_PeriodSort")

        latest_value = safe_float(sub["Actual"].iloc[-1])
        avg_value = safe_float(sub["Actual"].mean())
        median_value = safe_float(sub["Actual"].median())

        col1, col2, col3 = st.columns(3)
        col1.metric("Dernier", fmt_num(latest_value))
        col2.metric("Moyenne historique", fmt_num(avg_value))

        if latest_value is not None and avg_value not in [None, 0]:
            col3.metric("Prime / discount vs moyenne", fmt_pct(latest_value / avg_value - 1))
        else:
            col3.metric("Prime / discount vs moyenne", "N/A")

        source_used = str(sub["Source Actual"].dropna().iloc[-1]) if "Source Actual" in sub.columns and sub["Source Actual"].notna().any() else ""

        if "proxy valuation" in source_used.lower():
            st.caption(
                "Lecture normalisée : la Market Cap / Enterprise Value actuelle est comparée aux fondamentaux historiques. "
                "Ce n'est pas un multiple historique de marché pur, mais une vue utile pour mesurer l'exigence actuelle face à l'historique fondamental."
            )
        else:
            st.caption("Lecture basée sur les multiples historiques fournis par FMP.")

        fig = go.Figure()

        fig.add_trace(go.Scatter(
            x=sub["Period"],
            y=sub["Actual"],
            mode="lines+markers",
            name=focus
        ))

        if avg_value is not None:
            fig.add_hline(
                y=avg_value,
                line_dash="dash",
                annotation_text="Moyenne",
                annotation_position="right"
            )

        if median_value is not None:
            fig.add_hline(
                y=median_value,
                line_dash="dot",
                annotation_text="Médiane",
                annotation_position="right"
            )

        fig.update_layout(
            height=540,
            title=f"Historique valorisation — {focus}",
            xaxis_title="Période",
            yaxis_title="Multiple",
            hovermode="x unified",
            margin=dict(l=20, r=20, t=70, b=40)
        )

        st.plotly_chart(fig, use_container_width=True)
