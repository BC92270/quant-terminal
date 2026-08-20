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

def alpha_reports_to_actual_long(
    reports: list[dict],
    metric_key_map: dict[str, list[str]],
    frequency: str,
    source: str,
) -> pd.DataFrame:
    rows = []

    for record in reports or []:
        if not isinstance(record, dict):
            continue

        date = parse_date_safe(first_present_flexible(record, ["fiscalDateEnding", "date"]))

        if pd.isna(date):
            continue

        period = period_label(date, frequency)

        for metric, keys in metric_key_map.items():
            value = safe_float(first_present_flexible(record, keys))

            if value is None:
                continue

            rows.append({
                "Date": date,
                "Period": period,
                "Frequency": frequency,
                "Metric": metric,
                "Actual": value,
                "Source Actual": source,
            })

    if not rows:
        return pd.DataFrame(columns=["Date", "Period", "Frequency", "Metric", "Actual", "Source Actual"])

    out = pd.DataFrame(rows)
    out = out.drop_duplicates(subset=["Period", "Frequency", "Metric"], keep="last")
    out = out.sort_values(["Metric", "Date"])
    return out


def alpha_income_actual_long(company_data: dict, frequency: str) -> pd.DataFrame:
    alpha = company_data.get("alpha", {})
    income_payload = alpha.get("income_statement", {}) if isinstance(alpha, dict) else {}

    if not isinstance(income_payload, dict):
        return pd.DataFrame(columns=["Date", "Period", "Frequency", "Metric", "Actual", "Source Actual"])

    key = "annualReports" if frequency == "Annuel" else "quarterlyReports"
    reports = income_payload.get(key, [])

    return alpha_reports_to_actual_long(
        reports,
        ALPHA_INCOME_ACTUAL_KEYS,
        frequency,
        "Alpha Vantage income statement",
    )


def alpha_cashflow_actual_long(company_data: dict, frequency: str) -> pd.DataFrame:
    alpha = company_data.get("alpha", {})
    cash_payload = alpha.get("cash_flow", {}) if isinstance(alpha, dict) else {}

    if not isinstance(cash_payload, dict):
        return pd.DataFrame(columns=["Date", "Period", "Frequency", "Metric", "Actual", "Source Actual"])

    key = "annualReports" if frequency == "Annuel" else "quarterlyReports"
    reports = cash_payload.get(key, [])

    return alpha_reports_to_actual_long(
        reports,
        ALPHA_CASHFLOW_ACTUAL_KEYS,
        frequency,
        "Alpha Vantage cash flow",
    )



def alpha_balance_actual_long(company_data: dict, frequency: str) -> pd.DataFrame:
    alpha = company_data.get("alpha", {})
    balance_payload = alpha.get("balance_sheet", {}) if isinstance(alpha, dict) else {}

    if not isinstance(balance_payload, dict):
        return pd.DataFrame(columns=["Date", "Period", "Frequency", "Metric", "Actual", "Source Actual"])

    key = "annualReports" if frequency == "Annuel" else "quarterlyReports"
    reports = balance_payload.get(key, [])

    return alpha_reports_to_actual_long(
        reports,
        ALPHA_BALANCE_ACTUAL_KEYS,
        frequency,
        "Alpha Vantage balance sheet",
    )


BALANCE_SHEET_DISPLAY_METRICS = [
    "Total Cash",
    "Total Debt",
    "Net Debt",
    "Total Assets",
    "Total Equity",
    "Total Liabilities",
    "Current Assets",
    "Current Liabilities",
]

BALANCE_STRENGTH_DISPLAY_METRICS = [
    "Cash / Debt",
    "Current Ratio",
    "Quick Ratio",
    "Debt / Equity",
]


def balance_actual_source_priority(source: str) -> int:
    source = str(source or "").lower()

    if "fmp" in source:
        return 0
    if "alpha" in source:
        return 1
    if "yfinance" in source:
        return 2
    if "derived" in source or "calculated" in source:
        return 3

    return 9


def derive_balance_sheet_actual_metrics(balance_df: pd.DataFrame) -> pd.DataFrame:
    """
    Enrichit le bilan actual avec quelques métriques dérivées sans toucher
    aux providers ni aux estimates.

    Exemple :
    - Total Debt depuis Short Term Debt + Long Term Debt si Total Debt manque.
    - Net Debt = Total Debt - Total Cash si Net Debt manque.
    """
    if balance_df is None or balance_df.empty:
        return pd.DataFrame(columns=["Date", "Period", "Frequency", "Metric", "Actual", "Source Actual"])

    out = balance_df.copy()
    out["Date"] = pd.to_datetime(out["Date"], errors="coerce")
    out["Actual"] = pd.to_numeric(out["Actual"], errors="coerce")
    out = out.dropna(subset=["Actual"])

    if out.empty:
        return pd.DataFrame(columns=["Date", "Period", "Frequency", "Metric", "Actual", "Source Actual"])

    pivot_values = out.pivot_table(
        index=["Period", "Frequency"],
        columns="Metric",
        values="Actual",
        aggfunc="first"
    ).reset_index()

    pivot_dates = (
        out
        .dropna(subset=["Date"])
        .groupby(["Period", "Frequency"], as_index=False)["Date"]
        .max()
    )

    pivot = pivot_values.merge(
        pivot_dates,
        on=["Period", "Frequency"],
        how="left"
    )

    existing_keys = set(
        zip(
            out["Period"].astype(str),
            out["Frequency"].astype(str),
            out["Metric"].astype(str),
        )
    )

    derived_rows = []

    def add_derived(row, metric: str, value, source: str):
        value = safe_float(value)

        if value is None or pd.isna(value):
            return

        key = (
            str(row.get("Period")),
            str(row.get("Frequency")),
            str(metric),
        )

        if key in existing_keys:
            return

        derived_rows.append({
            "Date": row.get("Date"),
            "Period": row.get("Period"),
            "Frequency": row.get("Frequency"),
            "Metric": metric,
            "Actual": value,
            "Source Actual": source,
        })

        existing_keys.add(key)

    for _, row in pivot.iterrows():
        total_cash = safe_float(row.get("Total Cash"))
        total_debt = safe_float(row.get("Total Debt"))
        short_debt = safe_float(row.get("Short Term Debt"))
        long_debt = safe_float(row.get("Long Term Debt"))

        if total_debt is None and (short_debt is not None or long_debt is not None):
            total_debt = (short_debt or 0) + (long_debt or 0)
            add_derived(
                row,
                "Total Debt",
                total_debt,
                "Derived: Short Term Debt + Long Term Debt"
            )

        if total_debt is not None and total_cash is not None:
            add_derived(
                row,
                "Net Debt",
                total_debt - total_cash,
                "Derived: Total Debt - Total Cash"
            )

    if derived_rows:
        out = pd.concat([out, pd.DataFrame(derived_rows)], ignore_index=True)

    out["_priority"] = out["Source Actual"].apply(balance_actual_source_priority)
    out["_period_sort"] = out.apply(
        lambda row: period_sort_key(row.get("Period"), row.get("Date")),
        axis=1
    )

    out = out.sort_values(
        ["_period_sort", "Metric", "_priority", "Date"],
        na_position="last"
    )

    out = out.drop_duplicates(
        subset=["Period", "Frequency", "Metric"],
        keep="first"
    )

    out = out.drop(columns=["_priority", "_period_sort"], errors="ignore")

    return out[["Date", "Period", "Frequency", "Metric", "Actual", "Source Actual"]]


def build_balance_strength_actual_long(company_data: dict, frequency: str) -> pd.DataFrame:
    """
    Ratios de solidité financière historiques.

    On sépare ce bloc du bilan pur car les ratios n'ont pas la même échelle
    que les montants cash / dette / actifs.
    """
    balance_actual = build_balance_actual_long(company_data, frequency)
    rows = []

    if not balance_actual.empty:
        work = balance_actual.copy()
        work["Date"] = pd.to_datetime(work["Date"], errors="coerce")
        work["Actual"] = pd.to_numeric(work["Actual"], errors="coerce")

        pivot_values = work.pivot_table(
            index=["Period", "Frequency"],
            columns="Metric",
            values="Actual",
            aggfunc="first"
        ).reset_index()

        pivot_dates = (
            work
            .dropna(subset=["Date"])
            .groupby(["Period", "Frequency"], as_index=False)["Date"]
            .max()
        )

        pivot = pivot_values.merge(
            pivot_dates,
            on=["Period", "Frequency"],
            how="left"
        )

        for _, row in pivot.iterrows():
            total_cash = safe_float(row.get("Total Cash"))
            total_debt = safe_float(row.get("Total Debt"))
            total_equity = safe_float(row.get("Total Equity"))
            current_assets = safe_float(row.get("Current Assets"))
            current_liabilities = safe_float(row.get("Current Liabilities"))
            inventory = safe_float(row.get("Inventory"))

            if total_cash is not None and total_debt not in [None, 0]:
                rows.append({
                    "Date": row.get("Date"),
                    "Period": row.get("Period"),
                    "Frequency": row.get("Frequency"),
                    "Metric": "Cash / Debt",
                    "Actual": total_cash / total_debt,
                    "Source Actual": "Calculated: Total Cash / Total Debt",
                })

            if current_assets is not None and current_liabilities not in [None, 0]:
                rows.append({
                    "Date": row.get("Date"),
                    "Period": row.get("Period"),
                    "Frequency": row.get("Frequency"),
                    "Metric": "Current Ratio",
                    "Actual": current_assets / current_liabilities,
                    "Source Actual": "Calculated: Current Assets / Current Liabilities",
                })

            if (
                current_assets is not None
                and inventory is not None
                and current_liabilities not in [None, 0]
            ):
                rows.append({
                    "Date": row.get("Date"),
                    "Period": row.get("Period"),
                    "Frequency": row.get("Frequency"),
                    "Metric": "Quick Ratio",
                    "Actual": (current_assets - inventory) / current_liabilities,
                    "Source Actual": "Calculated: (Current Assets - Inventory) / Current Liabilities",
                })

            if total_debt is not None and total_equity not in [None, 0]:
                rows.append({
                    "Date": row.get("Date"),
                    "Period": row.get("Period"),
                    "Frequency": row.get("Frequency"),
                    "Metric": "Debt / Equity",
                    "Actual": total_debt / total_equity,
                    "Source Actual": "Calculated: Total Debt / Total Equity",
                })

    fmp = company_data.get("fmp", {})
    ratio_key = "ratios_annual" if frequency == "Annuel" else "ratios_quarterly"
    ratio_records = fmp.get(ratio_key, []) if isinstance(fmp, dict) else []

    ratio_map = {
        "Current Ratio": ["currentRatio"],
        "Quick Ratio": ["quickRatio"],
        "Debt / Equity": [
            "debtEquityRatio",
            "debtToEquity",
            "debtToEquityRatio",
        ],
    }

    ratio_rows = records_to_actual_long(
        ratio_records,
        ratio_map,
        frequency,
        "FMP balance ratios"
    )

    frames = []

    if rows:
        frames.append(pd.DataFrame(rows))

    if not ratio_rows.empty:
        frames.append(ratio_rows)

    frames = [df for df in frames if isinstance(df, pd.DataFrame) and not df.empty]

    if not frames:
        return pd.DataFrame(columns=["Date", "Period", "Frequency", "Metric", "Actual", "Source Actual"])

    out = pd.concat(frames, ignore_index=True)
    out["Date"] = pd.to_datetime(out["Date"], errors="coerce")
    out["Actual"] = pd.to_numeric(out["Actual"], errors="coerce")
    out = out.dropna(subset=["Actual"])

    if out.empty:
        return pd.DataFrame(columns=["Date", "Period", "Frequency", "Metric", "Actual", "Source Actual"])

    out["_priority"] = out["Source Actual"].apply(balance_actual_source_priority)
    out["_period_sort"] = out.apply(
        lambda row: period_sort_key(row.get("Period"), row.get("Date")),
        axis=1
    )

    out = out.sort_values(
        ["_period_sort", "Metric", "_priority", "Date"],
        na_position="last"
    )

    out = out.drop_duplicates(
        subset=["Period", "Frequency", "Metric"],
        keep="first"
    )

    out = out.drop(columns=["_priority", "_period_sort"], errors="ignore")

    return out[["Date", "Period", "Frequency", "Metric", "Actual", "Source Actual"]]


def build_balance_estimate_long(company_data: dict, frequency: str) -> pd.DataFrame:
    """
    Estimates / forward de bilan.

    Version prudente :
    - conserve les estimates futures déjà fonctionnelles ;
    - ajoute un backfill historique proxy pour les périodes déjà réalisées ;
    - ne touche pas aux actuals ;
    - ne touche pas au render ;
    - ne touche pas aux modules income / cash-flow / profitability.
    """
    balance_actual = build_balance_actual_long(company_data, frequency)

    if balance_actual.empty:
        return empty_estimate_long()

    income_estimates = build_income_estimate_long(company_data, frequency)
    cashflow_estimates = build_cashflow_estimate_long(company_data, frequency)
    income_actual = build_income_actual_long(company_data, frequency)

    if income_estimates.empty and cashflow_estimates.empty:
        return empty_estimate_long()

    work = balance_actual.copy()
    work["Date"] = pd.to_datetime(work["Date"], errors="coerce")
    work["Actual"] = pd.to_numeric(work["Actual"], errors="coerce")
    work = work.dropna(subset=["Actual"])

    if work.empty:
        return empty_estimate_long()

    work["_PeriodSort"] = work.apply(
        lambda row: period_sort_key(row.get("Period"), row.get("Date")),
        axis=1
    )

    latest_actual_sort = work["_PeriodSort"].max()

    latest_by_metric = (
        work
        .sort_values(["_PeriodSort", "Date"], na_position="last")
        .drop_duplicates(subset=["Metric"], keep="last")
        .set_index("Metric")["Actual"]
        .to_dict()
    )

    actual_pivot_values = work.pivot_table(
        index=["Period", "Frequency"],
        columns="Metric",
        values="Actual",
        aggfunc="first"
    ).reset_index()

    actual_pivot_dates = (
        work
        .dropna(subset=["Date"])
        .groupby(["Period", "Frequency"], as_index=False)["Date"]
        .max()
    )

    actual_pivot = actual_pivot_values.merge(
        actual_pivot_dates,
        on=["Period", "Frequency"],
        how="left"
    )

    actual_pivot["_PeriodSort"] = actual_pivot.apply(
        lambda row: period_sort_key(row.get("Period"), row.get("Date")),
        axis=1
    )

    actual_pivot = (
        actual_pivot
        .sort_values(["_PeriodSort", "Date"], na_position="last")
        .drop_duplicates(subset=["Period", "Frequency"], keep="last")
    )

    period_frames = []

    if not income_estimates.empty:
        period_frames.append(
            income_estimates[["Date Estimate", "Period", "Frequency"]].copy()
        )

    if not cashflow_estimates.empty:
        period_frames.append(
            cashflow_estimates[["Date Estimate", "Period", "Frequency"]].copy()
        )

    if not period_frames:
        return empty_estimate_long()

    estimate_periods = pd.concat(period_frames, ignore_index=True)
    estimate_periods["Date Estimate"] = pd.to_datetime(
        estimate_periods["Date Estimate"],
        errors="coerce"
    )

    estimate_periods = estimate_periods[
        estimate_periods["Frequency"].astype(str) == str(frequency)
    ].copy()

    if estimate_periods.empty:
        return empty_estimate_long()

    estimate_periods["_PeriodSort"] = estimate_periods.apply(
        lambda row: period_sort_key(row.get("Period"), row.get("Date Estimate")),
        axis=1
    )

    estimate_periods = (
        estimate_periods
        .sort_values(["_PeriodSort", "Date Estimate"], na_position="last")
        .drop_duplicates(subset=["Period", "Frequency"], keep="first")
    )

    historical_periods = estimate_periods[
        estimate_periods["_PeriodSort"] <= latest_actual_sort
    ].copy()

    future_periods = estimate_periods[
        estimate_periods["_PeriodSort"] > latest_actual_sort
    ].copy()

    def get_estimate(df: pd.DataFrame, period, metric: str):
        if df is None or df.empty:
            return None

        subset = df[
            (df["Period"].astype(str) == str(period))
            & (df["Frequency"] == frequency)
            & (df["Metric"] == metric)
            & df["Estimate"].notna()
        ].copy()

        if subset.empty:
            return None

        subset["Date Estimate"] = pd.to_datetime(
            subset["Date Estimate"],
            errors="coerce"
        )

        subset = subset.sort_values("Date Estimate", na_position="last")
        return safe_float(subset.iloc[-1].get("Estimate"))

    income_revenue_actuals = pd.DataFrame()

    if not income_actual.empty:
        income_work = income_actual.copy()
        income_work["Date"] = pd.to_datetime(income_work["Date"], errors="coerce")
        income_work["Actual"] = pd.to_numeric(income_work["Actual"], errors="coerce")
        income_work["_PeriodSort"] = income_work.apply(
            lambda row: period_sort_key(row.get("Period"), row.get("Date")),
            axis=1
        )

        income_revenue_actuals = income_work[
            (income_work["Metric"] == "Revenue")
            & income_work["Actual"].notna()
        ].copy()

        income_revenue_actuals = income_revenue_actuals.sort_values(
            ["_PeriodSort", "Date"],
            na_position="last"
        )

    def get_revenue_actual_before(period_sort_value):
        if income_revenue_actuals.empty:
            return None

        candidates = income_revenue_actuals[
            income_revenue_actuals["_PeriodSort"] < period_sort_value
        ].copy()

        if candidates.empty:
            return None

        return safe_float(candidates.iloc[-1].get("Actual"))

    latest_revenue_actual = get_revenue_actual_before(999999999)

    rows = []

    def add_estimate(date, period, metric: str, value, source: str):
        value = safe_float(value)

        if value is None or pd.isna(value):
            return

        rows.append({
            "Date Estimate": date,
            "Period": period,
            "Frequency": frequency,
            "Metric": metric,
            "Estimate": value,
            "Source Estimate": source,
        })

    def bounded_revenue_scale(revenue_estimate, revenue_base):
        if revenue_estimate is None or revenue_base in [None, 0]:
            return 1.0

        scale = revenue_estimate / revenue_base

        if pd.isna(scale) or np.isinf(scale):
            return 1.0

        return max(0.50, min(2.50, float(scale)))

    def project_balance_period(
        date_estimate,
        period,
        previous_values: dict,
        revenue_base,
        historical_backfill: bool,
    ) -> dict:
        revenue_estimate = get_estimate(income_estimates, period, "Revenue")
        net_income_estimate = get_estimate(income_estimates, period, "Net Income")

        fcf_estimate = get_estimate(cashflow_estimates, period, "Free Cash Flow")

        if fcf_estimate is None:
            ocf_estimate = get_estimate(cashflow_estimates, period, "Operating Cash Flow")
            capex_estimate = get_estimate(cashflow_estimates, period, "Capital Expenditure")

            if ocf_estimate is not None and capex_estimate is not None:
                fcf_estimate = ocf_estimate + capex_estimate

        revenue_scale = bounded_revenue_scale(revenue_estimate, revenue_base)

        previous_cash = safe_float(previous_values.get("Total Cash"))
        previous_debt = safe_float(previous_values.get("Total Debt"))
        previous_assets = safe_float(previous_values.get("Total Assets"))
        previous_equity = safe_float(previous_values.get("Total Equity"))
        previous_liabilities = safe_float(previous_values.get("Total Liabilities"))
        previous_current_assets = safe_float(previous_values.get("Current Assets"))
        previous_current_liabilities = safe_float(previous_values.get("Current Liabilities"))
        previous_inventory = safe_float(previous_values.get("Inventory"))

        cash_estimate = previous_cash

        if previous_cash is not None and fcf_estimate is not None:
            cash_estimate = previous_cash + fcf_estimate

        debt_estimate = previous_debt

        equity_estimate = previous_equity

        if previous_equity is not None:
            if net_income_estimate is not None:
                equity_estimate = previous_equity + net_income_estimate
            elif revenue_scale != 1.0:
                equity_estimate = previous_equity * revenue_scale

        assets_estimate = previous_assets

        if previous_assets is not None and revenue_scale != 1.0:
            assets_estimate = previous_assets * revenue_scale

        if assets_estimate is not None and equity_estimate is not None:
            minimum_assets = equity_estimate + max(debt_estimate or 0, 0)
            assets_estimate = max(assets_estimate, minimum_assets)

        current_assets_estimate = (
            previous_current_assets * revenue_scale
            if previous_current_assets is not None
            else None
        )

        current_liabilities_estimate = (
            previous_current_liabilities * revenue_scale
            if previous_current_liabilities is not None
            else None
        )

        inventory_estimate = (
            previous_inventory * revenue_scale
            if previous_inventory is not None
            else None
        )

        liabilities_estimate = None

        if previous_liabilities is not None:
            liabilities_estimate = previous_liabilities * revenue_scale
        elif assets_estimate is not None and equity_estimate is not None:
            liabilities_estimate = assets_estimate - equity_estimate

        net_debt_estimate = None

        if debt_estimate is not None and cash_estimate is not None:
            net_debt_estimate = debt_estimate - cash_estimate

        if historical_backfill:
            prefix = "Proxy backfill balance"
            cash_source = f"{prefix}: previous actual cash + same-period FCF estimate"
            debt_source = f"{prefix}: previous actual debt carried forward"
            net_debt_source = f"{prefix}: debt estimate - cash estimate"
            assets_source = f"{prefix}: previous actual assets × revenue scale"
            equity_source = f"{prefix}: previous actual equity + same-period net income estimate"
            liabilities_source = f"{prefix}: previous actual liabilities × revenue scale"
            current_assets_source = f"{prefix}: previous actual current assets × revenue scale"
            current_liabilities_source = f"{prefix}: previous actual current liabilities × revenue scale"
            inventory_source = f"{prefix}: previous actual inventory × revenue scale"
        else:
            cash_source = "Proxy balance: latest cash + FCF estimate"
            debt_source = "Proxy balance: latest debt carried forward"
            net_debt_source = "Proxy balance: debt estimate - cash estimate"
            assets_source = "Proxy balance: latest assets × revenue scale"
            equity_source = "Proxy balance: latest equity + net income estimate"
            liabilities_source = "Proxy balance: latest liabilities × revenue scale"
            current_assets_source = "Proxy balance: latest current assets × revenue scale"
            current_liabilities_source = "Proxy balance: latest current liabilities × revenue scale"
            inventory_source = "Proxy balance: latest inventory × revenue scale"

        add_estimate(date_estimate, period, "Total Cash", cash_estimate, cash_source)
        add_estimate(date_estimate, period, "Total Debt", debt_estimate, debt_source)
        add_estimate(date_estimate, period, "Net Debt", net_debt_estimate, net_debt_source)
        add_estimate(date_estimate, period, "Total Assets", assets_estimate, assets_source)
        add_estimate(date_estimate, period, "Total Equity", equity_estimate, equity_source)
        add_estimate(date_estimate, period, "Total Liabilities", liabilities_estimate, liabilities_source)
        add_estimate(date_estimate, period, "Current Assets", current_assets_estimate, current_assets_source)
        add_estimate(date_estimate, period, "Current Liabilities", current_liabilities_estimate, current_liabilities_source)
        add_estimate(date_estimate, period, "Inventory", inventory_estimate, inventory_source)

        return {
            "Total Cash": cash_estimate,
            "Total Debt": debt_estimate,
            "Total Assets": assets_estimate,
            "Total Equity": equity_estimate,
            "Total Liabilities": liabilities_estimate,
            "Current Assets": current_assets_estimate,
            "Current Liabilities": current_liabilities_estimate,
            "Inventory": inventory_estimate,
            "_revenue_base": revenue_estimate if revenue_estimate is not None else revenue_base,
        }

    # ------------------------------------------------------------
    # 1) Backfill historique
    # ------------------------------------------------------------
    # Pour une période réalisée, on construit une estimate comme si l'on partait
    # du bilan actual de la période précédente.
    # Cela donne un vrai Actual vs Estimate historique sans modifier les actuals.
    for _, period_row in historical_periods.iterrows():
        period_sort = period_row.get("_PeriodSort")
        period = period_row.get("Period")
        date_estimate = period_row.get("Date Estimate")

        previous_actual_candidates = actual_pivot[
            actual_pivot["_PeriodSort"] < period_sort
        ].copy()

        if previous_actual_candidates.empty:
            continue

        previous_actual_row = previous_actual_candidates.iloc[-1]

        previous_values = {
            "Total Cash": previous_actual_row.get("Total Cash"),
            "Total Debt": previous_actual_row.get("Total Debt"),
            "Total Assets": previous_actual_row.get("Total Assets"),
            "Total Equity": previous_actual_row.get("Total Equity"),
            "Total Liabilities": previous_actual_row.get("Total Liabilities"),
            "Current Assets": previous_actual_row.get("Current Assets"),
            "Current Liabilities": previous_actual_row.get("Current Liabilities"),
            "Inventory": previous_actual_row.get("Inventory"),
        }

        revenue_base = get_revenue_actual_before(period_sort)

        project_balance_period(
            date_estimate=date_estimate,
            period=period,
            previous_values=previous_values,
            revenue_base=revenue_base,
            historical_backfill=True,
        )

    # ------------------------------------------------------------
    # 2) Forward futur
    # ------------------------------------------------------------
    # On garde la logique qui marchait déjà : dernière période actual,
    # puis projection séquentielle.
    previous_values = {
        "Total Cash": safe_float(latest_by_metric.get("Total Cash")),
        "Total Debt": safe_float(latest_by_metric.get("Total Debt")),
        "Total Assets": safe_float(latest_by_metric.get("Total Assets")),
        "Total Equity": safe_float(latest_by_metric.get("Total Equity")),
        "Total Liabilities": safe_float(latest_by_metric.get("Total Liabilities")),
        "Current Assets": safe_float(latest_by_metric.get("Current Assets")),
        "Current Liabilities": safe_float(latest_by_metric.get("Current Liabilities")),
        "Inventory": safe_float(latest_by_metric.get("Inventory")),
    }

    revenue_base = latest_revenue_actual

    for _, period_row in future_periods.iterrows():
        projected_values = project_balance_period(
            date_estimate=period_row.get("Date Estimate"),
            period=period_row.get("Period"),
            previous_values=previous_values,
            revenue_base=revenue_base,
            historical_backfill=False,
        )

        if projected_values:
            revenue_base = projected_values.get("_revenue_base", revenue_base)

            for key in [
                "Total Cash",
                "Total Debt",
                "Total Assets",
                "Total Equity",
                "Total Liabilities",
                "Current Assets",
                "Current Liabilities",
                "Inventory",
            ]:
                value = projected_values.get(key)

                if value is not None and not pd.isna(value):
                    previous_values[key] = value

    if not rows:
        return empty_estimate_long()

    out = pd.DataFrame(rows)
    out["Date Estimate"] = pd.to_datetime(out["Date Estimate"], errors="coerce")
    out["Estimate"] = pd.to_numeric(out["Estimate"], errors="coerce")
    out = out.dropna(subset=["Estimate"])

    if out.empty:
        return empty_estimate_long()

    out["_PeriodSort"] = out.apply(
        lambda row: period_sort_key(row.get("Period"), row.get("Date Estimate")),
        axis=1
    )

    out = out.sort_values(
        ["_PeriodSort", "Metric", "Date Estimate"],
        na_position="last"
    )

    out = out.drop_duplicates(
        subset=["Period", "Frequency", "Metric"],
        keep="last"
    )

    out = out.drop(columns=["_PeriodSort"], errors="ignore")

    return out[ESTIMATE_LONG_COLUMNS]

def build_balance_strength_estimate_long(company_data: dict, frequency: str) -> pd.DataFrame:
    """
    Estimates des ratios de solidité financière,
    calculés uniquement depuis les estimates de bilan.
    """
    balance_estimates = build_balance_estimate_long(company_data, frequency)

    if balance_estimates.empty:
        return empty_estimate_long()

    work = balance_estimates.copy()
    work["Date Estimate"] = pd.to_datetime(work["Date Estimate"], errors="coerce")
    work["Estimate"] = pd.to_numeric(work["Estimate"], errors="coerce")
    work = work.dropna(subset=["Estimate"])

    if work.empty:
        return empty_estimate_long()

    pivot_values = work.pivot_table(
        index=["Period", "Frequency"],
        columns="Metric",
        values="Estimate",
        aggfunc="first"
    ).reset_index()

    pivot_dates = (
        work
        .dropna(subset=["Date Estimate"])
        .groupby(["Period", "Frequency"], as_index=False)["Date Estimate"]
        .max()
    )

    pivot = pivot_values.merge(
        pivot_dates,
        on=["Period", "Frequency"],
        how="left"
    )

    rows = []

    for _, row in pivot.iterrows():
        total_cash = safe_float(row.get("Total Cash"))
        total_debt = safe_float(row.get("Total Debt"))
        total_equity = safe_float(row.get("Total Equity"))
        current_assets = safe_float(row.get("Current Assets"))
        current_liabilities = safe_float(row.get("Current Liabilities"))
        inventory = safe_float(row.get("Inventory"))

        if total_cash is not None and total_debt not in [None, 0]:
            rows.append({
                "Date Estimate": row.get("Date Estimate"),
                "Period": row.get("Period"),
                "Frequency": row.get("Frequency"),
                "Metric": "Cash / Debt",
                "Estimate": total_cash / total_debt,
                "Source Estimate": "Calculated from balance estimates",
            })

        if current_assets is not None and current_liabilities not in [None, 0]:
            rows.append({
                "Date Estimate": row.get("Date Estimate"),
                "Period": row.get("Period"),
                "Frequency": row.get("Frequency"),
                "Metric": "Current Ratio",
                "Estimate": current_assets / current_liabilities,
                "Source Estimate": "Calculated from balance estimates",
            })

        if (
            current_assets is not None
            and inventory is not None
            and current_liabilities not in [None, 0]
        ):
            rows.append({
                "Date Estimate": row.get("Date Estimate"),
                "Period": row.get("Period"),
                "Frequency": row.get("Frequency"),
                "Metric": "Quick Ratio",
                "Estimate": (current_assets - inventory) / current_liabilities,
                "Source Estimate": "Calculated from balance estimates",
            })

        if total_debt is not None and total_equity not in [None, 0]:
            rows.append({
                "Date Estimate": row.get("Date Estimate"),
                "Period": row.get("Period"),
                "Frequency": row.get("Frequency"),
                "Metric": "Debt / Equity",
                "Estimate": total_debt / total_equity,
                "Source Estimate": "Calculated from balance estimates",
            })

    if not rows:
        return empty_estimate_long()

    out = pd.DataFrame(rows)
    out["Date Estimate"] = pd.to_datetime(out["Date Estimate"], errors="coerce")
    out["Estimate"] = pd.to_numeric(out["Estimate"], errors="coerce")
    out = out.dropna(subset=["Estimate"])

    if out.empty:
        return empty_estimate_long()

    out["_PeriodSort"] = out.apply(
        lambda row: period_sort_key(row.get("Period"), row.get("Date Estimate")),
        axis=1
    )

    out = out.sort_values(["_PeriodSort", "Metric", "Date Estimate"], na_position="last")
    out = out.drop_duplicates(subset=["Period", "Frequency", "Metric"], keep="last")
    out = out.drop(columns=["_PeriodSort"], errors="ignore")

    return out[ESTIMATE_LONG_COLUMNS]


def build_balance_actual_long(company_data: dict, frequency: str) -> pd.DataFrame:
    frames = []

    fmp = company_data.get("fmp", {})
    key = "balance_annual" if frequency == "Annuel" else "balance_quarterly"
    records = fmp.get(key, []) if isinstance(fmp, dict) else []

    if records:
        frames.append(records_to_actual_long(records, FMP_BALANCE_ACTUAL_KEYS, frequency, "FMP balance sheet"))

    alpha_df = alpha_balance_actual_long(company_data, frequency)
    if not alpha_df.empty:
        frames.append(alpha_df)

    statement = (
        company_data.get("balance_sheet", pd.DataFrame())
        if frequency == "Annuel"
        else company_data.get("quarterly_balance_sheet", pd.DataFrame())
    )

    yf_df = yfinance_statement_to_actual_long(statement, YF_BALANCE_ROW_MAP, frequency, "yfinance balance sheet")
    if not yf_df.empty:
        frames.append(yf_df)

    frames = [df for df in frames if isinstance(df, pd.DataFrame) and not df.empty]

    if not frames:
        return pd.DataFrame(columns=["Date", "Period", "Frequency", "Metric", "Actual", "Source Actual"])

    out = pd.concat(frames, ignore_index=True)
    out["_priority"] = out["Source Actual"].map(
        lambda x: 0 if str(x).startswith("FMP") else 1 if str(x).startswith("Alpha") else 2
    )
    out = out.sort_values(["Period", "Frequency", "Metric", "_priority", "Date"])
    out = out.drop_duplicates(subset=["Period", "Frequency", "Metric"], keep="first")
    return out.drop(columns=["_priority"], errors="ignore")


def combine_actual_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    frames = [df for df in frames if isinstance(df, pd.DataFrame) and not df.empty]

    if not frames:
        return pd.DataFrame(columns=["Date", "Period", "Frequency", "Metric", "Actual", "Source Actual"])

    out = pd.concat(frames, ignore_index=True)
    out["Date"] = pd.to_datetime(out["Date"], errors="coerce")

    def source_priority(source):
        s = str(source).lower()
        if "fmp" in s:
            return 0
        if "alpha" in s:
            return 1
        if "sec" in s:
            return 2
        if "yfinance" in s:
            return 3
        return 4

    out["_priority"] = out["Source Actual"].apply(source_priority)
    out = out.sort_values(["Period", "Frequency", "Metric", "_priority", "Date"])
    out = out.drop_duplicates(subset=["Period", "Frequency", "Metric"], keep="first")
    out = out.drop(columns=["_priority"], errors="ignore")

    # Enrichissement prudent : ne touche pas aux providers.
    # Ajoute uniquement Total Debt / Net Debt dérivés si la donnée directe manque.
    out = derive_balance_sheet_actual_metrics(out)

    return out


def derive_fcf_and_standardize_capex(cash_df: pd.DataFrame) -> pd.DataFrame:
    if cash_df.empty:
        return cash_df

    out = cash_df.copy()

    capex_mask = out["Metric"] == "Capital Expenditure"
    out.loc[capex_mask, "Actual"] = pd.to_numeric(out.loc[capex_mask, "Actual"], errors="coerce").apply(
        lambda x: -abs(x) if not pd.isna(x) else x
    )

    pivot = out.pivot_table(
        index=["Date", "Period", "Frequency"],
        columns="Metric",
        values="Actual",
        aggfunc="first",
    ).reset_index()

    existing_fcf_periods = set(out.loc[out["Metric"] == "Free Cash Flow", "Period"].astype(str))
    rows = []

    for _, row in pivot.iterrows():
        period = str(row.get("Period"))
        if period in existing_fcf_periods:
            continue

        ocf = safe_float(row.get("Operating Cash Flow"))
        capex = safe_float(row.get("Capital Expenditure"))

        if ocf is None or capex is None:
            continue

        rows.append({
            "Date": row.get("Date"),
            "Period": row.get("Period"),
            "Frequency": row.get("Frequency"),
            "Metric": "Free Cash Flow",
            "Actual": ocf + capex,
            "Source Actual": "Derived: Operating Cash Flow + Capex",
        })

    if rows:
        out = pd.concat([out, pd.DataFrame(rows)], ignore_index=True)

    return out.sort_values(["Metric", "Date"])


def finnhub_estimates_to_income_estimate_long(company_data: dict, frequency: str) -> pd.DataFrame:
    finnhub = company_data.get("finnhub", {})

    if not isinstance(finnhub, dict) or not finnhub.get("enabled"):
        return empty_estimate_long()

    if frequency == "Annuel":
        eps_payload = finnhub.get("eps_estimate_annual", {})
        revenue_payload = finnhub.get("revenue_estimate_annual", {})
    else:
        eps_payload = finnhub.get("eps_estimate_quarterly", {})
        revenue_payload = finnhub.get("revenue_estimate_quarterly", {})

    rows = []

    specs = [
        (
            "EPS",
            finnhub_rows(eps_payload, ["data"]),
            ["epsAvg", "epsAverage", "epsEstimate", "estimatedEPS", "estimate", "eps"],
        ),
        (
            "Revenue",
            finnhub_rows(revenue_payload, ["data"]),
            ["revenueAvg", "revenueAverage", "revenueEstimate", "estimatedRevenue", "estimate", "revenue"],
        ),
    ]

    for metric, records, value_keys in specs:
        for item in records:
            date = parse_date_safe(first_present_flexible(item, ["period", "date", "fiscalDateEnding"]))

            year = first_present_flexible(item, ["year", "fiscalYear"])
            quarter = first_present_flexible(item, ["quarter", "q"])

            if pd.isna(date):
                if year is not None and frequency == "Annuel":
                    date = pd.to_datetime(f"{int(year)}-12-31", errors="coerce")
                elif year is not None and quarter is not None:
                    month = {1: 3, 2: 6, 3: 9, 4: 12}.get(safe_int(quarter, 4), 12)
                    date = pd.to_datetime(f"{int(year)}-{month:02d}-28", errors="coerce")

            if pd.isna(date):
                continue

            value = safe_float(first_present_flexible(item, value_keys))

            if value is None:
                continue

            rows.append({
                "Date Estimate": date,
                "Period": period_label(date, frequency),
                "Frequency": frequency,
                "Metric": metric,
                "Estimate": value,
                "Source Estimate": "Finnhub estimates",
            })

    if not rows:
        return empty_estimate_long()

    out = pd.DataFrame(rows)
    out["Date Estimate"] = pd.to_datetime(out["Date Estimate"], errors="coerce")
    out["Estimate"] = pd.to_numeric(out["Estimate"], errors="coerce")
    out = out.dropna(subset=["Date Estimate", "Estimate"])
    out = out.drop_duplicates(subset=["Period", "Frequency", "Metric"], keep="last")
    return out[ESTIMATE_LONG_COLUMNS]


def finnhub_earnings_calendar_to_surprise_df(company_data: dict) -> pd.DataFrame:
    finnhub = company_data.get("finnhub", {})

    if not isinstance(finnhub, dict) or not finnhub.get("enabled"):
        return pd.DataFrame()

    records = finnhub_rows(finnhub.get("earnings_calendar", {}), ["earningsCalendar"])

    if not records:
        return pd.DataFrame()

    rows = []

    for item in records:
        date = parse_date_safe(first_present_flexible(item, ["date", "period", "fiscalDateEnding"]))

        if pd.isna(date):
            continue

        eps_actual = safe_float(first_present_flexible(item, ["epsActual", "actualEPS", "reportedEPS"]))
        eps_estimate = safe_float(first_present_flexible(item, ["epsEstimate", "estimatedEPS", "epsEstimated"]))
        revenue_actual = safe_float(first_present_flexible(item, ["revenueActual", "actualRevenue", "revenue"]))
        revenue_estimate = safe_float(first_present_flexible(item, ["revenueEstimate", "estimatedRevenue", "revenueEstimated"]))

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

        if eps_actual is None and eps_estimate is None and revenue_actual is None and revenue_estimate is None:
            continue

        rows.append({
            "Date": date,
            "Period": period_label(date, "Trimestriel"),
            "EPS Actual": eps_actual,
            "EPS Estimate": eps_estimate,
            "EPS Surprise": eps_surprise,
            "EPS Surprise %": eps_surprise_pct,
            "Revenue Actual": revenue_actual,
            "Revenue Estimate": revenue_estimate,
            "Revenue Surprise": revenue_surprise,
            "Revenue Surprise %": revenue_surprise_pct,
            "Source": "Finnhub",
        })

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def alpha_earnings_estimates_to_income_estimate_long(
    company_data: dict,
    frequency: str
) -> pd.DataFrame:
    """
    Parse Alpha Vantage EARNINGS_ESTIMATES.

    Ton debug montre un payload du type :
    {
        "symbol": "...",
        "estimates": [...]
    }

    Donc on lit prioritairement payload["estimates"].
    """
    alpha = company_data.get("alpha", {})
    payload = alpha.get("earnings_estimates", {}) if isinstance(alpha, dict) else {}

    if not isinstance(payload, dict):
        return empty_estimate_long()

    raw_estimates = payload.get("estimates", [])

    records = []

    if isinstance(raw_estimates, list):
        records = raw_estimates
    elif isinstance(raw_estimates, dict):
        for value in raw_estimates.values():
            if isinstance(value, list):
                records.extend(value)
            elif isinstance(value, dict):
                records.append(value)

    if not records:
        return empty_estimate_long()

    def infer_record_frequency(record: dict) -> str | None:
        blob = " ".join([
            str(first_present_flexible(record, [
                "period",
                "fiscalPeriod",
                "fiscal_period",
                "type",
                "estimateType",
                "horizon",
                "frequency",
            ], "") or ""),
            str(record)
        ]).lower()

        if "quarter" in blob or "quarterly" in blob or re.search(r"\bq[1-4]\b", blob):
            return "Trimestriel"

        if "annual" in blob or "year" in blob or "yearly" in blob or "fy" in blob:
            return "Annuel"

        return None

    def date_from_estimate_record(record: dict, target_frequency: str):
        date = parse_date_safe(first_present_flexible(record, [
            "date",
            "reportedDate",
            "reportDate",
            "fiscalDateEnding",
            "fiscal_date_ending",
            "periodEnding",
            "periodEndingDate",
            "endDate",
        ]))

        if not pd.isna(date):
            return date

        year_value = first_present_flexible(record, [
            "fiscalYear",
            "fiscal_year",
            "calendarYear",
            "calendar_year",
            "year",
        ])

        quarter_value = first_present_flexible(record, [
            "quarter",
            "fiscalQuarter",
            "fiscal_quarter",
            "period",
            "fiscalPeriod",
        ])

        try:
            year = int(str(year_value).replace("FY", "").strip())
        except Exception:
            return pd.NaT

        if target_frequency == "Annuel":
            return pd.Timestamp(year=year, month=12, day=31)

        quarter_text = str(quarter_value or "").upper()
        match = re.search(r"Q([1-4])", quarter_text)

        if match:
            quarter = int(match.group(1))
        else:
            quarter = 4

        month = quarter * 3
        return pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)

    def best_numeric(record: dict, preferred_keys: list[str], fuzzy_terms: list[str]):
        value = safe_float(first_present_flexible(record, preferred_keys))

        if value is not None:
            return value

        candidates = []

        for key, raw_value in record.items():
            normalized_key = normalize_external_key(key)

            if not all(term in normalized_key for term in fuzzy_terms):
                continue

            if any(bad in normalized_key for bad in [
                "low",
                "high",
                "min",
                "max",
                "growth",
                "change",
                "number",
                "count",
                "analyst",
            ]):
                continue

            numeric_value = safe_float(raw_value)

            if numeric_value is None:
                continue

            score = 0

            if "avg" in normalized_key or "average" in normalized_key:
                score -= 3
            if "mean" in normalized_key:
                score -= 3
            if "estimate" in normalized_key or "estimated" in normalized_key:
                score -= 2
            if "consensus" in normalized_key:
                score -= 2

            candidates.append((score, numeric_value))

        if not candidates:
            return None

        candidates = sorted(candidates, key=lambda x: x[0])
        return candidates[0][1]

    rows = []

    for item in records:
        if not isinstance(item, dict):
            continue

        record_frequency = infer_record_frequency(item)

        if record_frequency is not None and record_frequency != frequency:
            continue

        date = date_from_estimate_record(item, frequency)

        if pd.isna(date):
            continue

        period = period_label(date, frequency)

        revenue_estimate = best_numeric(
            item,
            [
                "revenue_estimate_average",
                "revenue_estimate_avg",
                "revenue_estimate_mean",
                "revenue_estimate",
                "estimatedRevenue",
                "estimatedRevenueAvg",
                "estimatedRevenueAverage",
                "revenueEstimate",
                "revenueEstimateAvg",
                "revenueAverage",
                "revenueAvg",
                "revenueMean",
                "consensusRevenue",
                "salesEstimate",
                "salesEstimateAvg",
                "salesAvg",
            ],
            ["revenue"]
        )

        if revenue_estimate is None:
            revenue_estimate = best_numeric(
                item,
                [
                    "salesEstimate",
                    "salesEstimateAvg",
                    "salesAvg",
                    "consensusSales",
                ],
                ["sales"]
            )

        eps_estimate = best_numeric(
            item,
            [
                "eps_estimate_average",
                "eps_estimate_avg",
                "eps_estimate_mean",
                "eps_estimate",
                "estimatedEPS",
                "estimatedEps",
                "estimatedEPSAvg",
                "estimatedEpsAvg",
                "epsEstimate",
                "epsEstimateAvg",
                "epsAverage",
                "epsAvg",
                "epsMean",
                "consensusEPS",
            ],
            ["eps"]
        )

        if revenue_estimate is not None:
            rows.append({
                "Date Estimate": date,
                "Period": period,
                "Frequency": frequency,
                "Metric": "Revenue",
                "Estimate": revenue_estimate,
                "Source Estimate": "Alpha Vantage earnings estimates",
            })

        if eps_estimate is not None:
            rows.append({
                "Date Estimate": date,
                "Period": period,
                "Frequency": frequency,
                "Metric": "EPS",
                "Estimate": eps_estimate,
                "Source Estimate": "Alpha Vantage earnings estimates",
            })

    if not rows:
        return empty_estimate_long()

    out = pd.DataFrame(rows)
    out["Date Estimate"] = pd.to_datetime(out["Date Estimate"], errors="coerce")
    out["Estimate"] = pd.to_numeric(out["Estimate"], errors="coerce")
    out = out.dropna(subset=["Date Estimate", "Estimate"])

    if out.empty:
        return empty_estimate_long()

    out = out.sort_values(["Metric", "Date Estimate"])

    return out[ESTIMATE_LONG_COLUMNS]

def alpha_earnings_history_to_surprise_df(company_data: dict) -> pd.DataFrame:
    alpha = company_data.get("alpha", {})
    payload = alpha.get("earnings", {}) if isinstance(alpha, dict) else {}

    if not isinstance(payload, dict):
        return pd.DataFrame()

    records = payload.get("quarterlyEarnings", [])

    if not isinstance(records, list) or not records:
        return pd.DataFrame()

    rows = []

    for item in records:
        if not isinstance(item, dict):
            continue

        date = parse_date_safe(first_present_flexible(item, [
            "reportedDate",
            "fiscalDateEnding",
            "date",
        ]))

        if pd.isna(date):
            continue

        eps_actual = safe_float(first_present_flexible(item, [
            "reportedEPS",
            "reportedEps",
            "actualEPS",
            "epsActual",
        ]))

        eps_estimate = safe_float(first_present_flexible(item, [
            "estimatedEPS",
            "estimatedEps",
            "epsEstimate",
        ]))

        eps_surprise = safe_float(first_present_flexible(item, [
            "surprise",
            "epsSurprise",
        ]))

        eps_surprise_pct = safe_float(first_present_flexible(item, [
            "surprisePercentage",
            "surprisePercent",
            "epsSurprisePercentage",
        ]))

        if eps_surprise is None and eps_actual is not None and eps_estimate is not None:
            eps_surprise = eps_actual - eps_estimate

        if eps_surprise_pct is None and eps_surprise is not None and eps_estimate not in [None, 0]:
            eps_surprise_pct = eps_surprise / abs(eps_estimate)

        # Alpha renvoie parfois 5.2 au lieu de 0.052.
        if eps_surprise_pct is not None and abs(eps_surprise_pct) > 1:
            eps_surprise_pct = eps_surprise_pct / 100

        rows.append({
            "Date": date,
            "Period": period_label(date, "Trimestriel"),
            "EPS Actual": eps_actual,
            "EPS Estimate": eps_estimate,
            "EPS Surprise": eps_surprise,
            "EPS Surprise %": eps_surprise_pct,
            "Revenue Actual": None,
            "Revenue Estimate": None,
            "Revenue Surprise": None,
            "Revenue Surprise %": None,
            "Source": "Alpha Vantage",
        })

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows)


def sec_extract_concept_facts(companyfacts: dict, concept_names: list[str]) -> list[dict]:
    facts_root = (
        companyfacts.get("facts", {})
        .get("us-gaap", {})
        if isinstance(companyfacts, dict)
        else {}
    )

    for concept in concept_names:
        concept_data = facts_root.get(concept)

        if not isinstance(concept_data, dict):
            continue

        units = concept_data.get("units", {})

        # La plupart des métriques income/cash-flow sont en USD.
        if "USD" in units and isinstance(units["USD"], list):
            return units["USD"]

    return []


def sec_companyfacts_to_actual_long(
    company_data: dict,
    frequency: str,
    metric_map: dict[str, list[str]],
    source: str,
) -> pd.DataFrame:
    sec = company_data.get("sec", {})

    if not isinstance(sec, dict) or not sec.get("enabled"):
        return pd.DataFrame(columns=["Date", "Period", "Frequency", "Metric", "Actual", "Source Actual"])

    companyfacts = sec.get("companyfacts", {})

    rows = []

    for metric, concepts in metric_map.items():
        facts = sec_extract_concept_facts(companyfacts, concepts)

        for fact in facts:
            if not isinstance(fact, dict):
                continue

            form = str(fact.get("form", ""))
            fp = str(fact.get("fp", ""))
            fy = fact.get("fy")
            end = fact.get("end")
            val = safe_float(fact.get("val"))

            if val is None or not end:
                continue

            if form not in ["10-K", "10-Q", "20-F", "40-F"]:
                continue

            if frequency == "Annuel":
                if form not in ["10-K", "20-F", "40-F"]:
                    continue
                period = f"FY {fy}" if fy else period_label(end, frequency)
            else:
                if form != "10-Q":
                    continue
                if not fp.startswith("Q"):
                    continue
                period = f"{fp} {fy}" if fy else period_label(end, frequency)

            date = parse_date_safe(end)

            if pd.isna(date):
                continue

            rows.append({
                "Date": date,
                "Period": period,
                "Frequency": frequency,
                "Metric": metric,
                "Actual": val,
                "Source Actual": source,
            })

    if not rows:
        return pd.DataFrame(columns=["Date", "Period", "Frequency", "Metric", "Actual", "Source Actual"])

    out = pd.DataFrame(rows)
    out = out.sort_values(["Metric", "Date"])
    out = out.drop_duplicates(subset=["Period", "Frequency", "Metric"], keep="last")
    return out


def records_to_actual_long(
    records: list[dict],
    metric_key_map: dict[str, list[str]],
    frequency: str,
    source: str
) -> pd.DataFrame:
    rows = []

    for record in records:
        if not isinstance(record, dict):
            continue

        date = parse_date_safe(first_present_flexible(
            record,
            [
                "date",
                "fiscalDateEnding",
                "fiscal_date_ending",
                "pricedDate",
                "priced_date",
                "reportedDate",
                "reportDate",
            ]
        ))

        if not pd.isna(date):
            period = period_label(date, frequency)
        else:
            period = period_label_from_record(record, frequency)

        for metric, keys in metric_key_map.items():
            value = safe_float(first_present_flexible(record, keys))
            if value is None:
                continue

            rows.append({
                "Date": date,
                "Period": period,
                "Frequency": frequency,
                "Metric": metric,
                "Actual": value,
                "Source Actual": source,
            })

    if not rows:
        return pd.DataFrame(columns=["Date", "Period", "Frequency", "Metric", "Actual", "Source Actual"])

    df = pd.DataFrame(rows)
    df = df.dropna(subset=["Date"])
    df = df.sort_values(["Metric", "Date"])
    df = df.drop_duplicates(subset=["Period", "Frequency", "Metric"], keep="last")
    return df


def records_to_estimate_long(
    records: list[dict],
    metric_key_map: dict[str, list[str]],
    frequency: str,
    source: str
) -> pd.DataFrame:
    rows = []

    for record in records:
        if not isinstance(record, dict):
            continue

        date = parse_date_safe(first_present_flexible(
            record,
            [
                "date",
                "fiscalDateEnding",
                "fiscal_date_ending",
                "pricedDate",
                "priced_date",
                "reportedDate",
                "reportDate",
            ]
        ))

        if not pd.isna(date):
            period = period_label(date, frequency)
        else:
            period = period_label_from_record(record, frequency)

        for metric, keys in metric_key_map.items():
            value = safe_float(first_present_flexible(record, keys))
            if value is None:
                continue

            rows.append({
                "Date Estimate": date,
                "Period": period,
                "Frequency": frequency,
                "Metric": metric,
                "Estimate": value,
                "Source Estimate": source,
            })

    if not rows:
        return pd.DataFrame(columns=["Date Estimate", "Period", "Frequency", "Metric", "Estimate", "Source Estimate"])

    df = pd.DataFrame(rows)
    df = df.sort_values(["Metric", "Date Estimate"])
    df = df.drop_duplicates(subset=["Period", "Frequency", "Metric"], keep="last")
    return df


def yfinance_statement_to_actual_long(
    statement: pd.DataFrame,
    row_map: dict[str, list[str]],
    frequency: str,
    source: str = "yfinance"
) -> pd.DataFrame:
    chart_df = make_statement_chart_df(statement, row_map)

    if chart_df.empty:
        return pd.DataFrame(columns=["Date", "Period", "Frequency", "Metric", "Actual", "Source Actual"])

    df = chart_df.copy()
    df = df.rename(columns={"Value": "Actual"})
    df["Frequency"] = frequency
    df["Period"] = df["Date"].apply(lambda x: period_label(x, frequency))
    df["Source Actual"] = source

    return df[["Date", "Period", "Frequency", "Metric", "Actual", "Source Actual"]]


def get_frequency_key(frequency: str) -> str:
    return "annual" if frequency == "Annuel" else "quarterly"

def build_income_actual_long(company_data: dict, frequency: str) -> pd.DataFrame:
    """
    Actuals income combinés : FMP -> Alpha -> SEC -> yfinance.
    On ne s'arrête plus au premier provider, afin d'éviter qu'une source partielle bloque l'historique complet.
    """
    frames = []

    fmp = company_data.get("fmp", {})
    key = "income_annual" if frequency == "Annuel" else "income_quarterly"
    records = fmp.get(key, []) if isinstance(fmp, dict) else []

    if records:
        frames.append(records_to_actual_long(records, FMP_INCOME_ACTUAL_KEYS, frequency, "FMP income statement"))

    alpha_df = alpha_income_actual_long(company_data, frequency)
    if not alpha_df.empty:
        frames.append(alpha_df)

    sec_income_map = {
        metric: concepts
        for metric, concepts in SEC_CONCEPT_MAP.items()
        if metric in ["Revenue", "Gross Profit", "Operating Income", "Net Income"]
    }

    # SEC companyfacts est utile en annuel.
    # En trimestriel, SEC peut utiliser des labels fiscaux fp/fy
    # et créer des périodes type Q2 2026 / Q3 2026 alors que la date réelle est en 2025.
    # On l'exclut donc du compte de résultat trimestriel pour éviter les faux actuals futurs.
    if frequency == "Annuel":
        sec_df = sec_companyfacts_to_actual_long(
            company_data,
            frequency,
            sec_income_map,
            "SEC companyfacts"
        )
        if not sec_df.empty:
            frames.append(sec_df)

    statement = (
        company_data.get("financials", pd.DataFrame())
        if frequency == "Annuel"
        else company_data.get("quarterly_financials", pd.DataFrame())
    )

    yf_df = yfinance_statement_to_actual_long(statement, YF_INCOME_ROW_MAP, frequency, "yfinance")
    if not yf_df.empty:
        frames.append(yf_df)

    return combine_actual_frames(frames)


def build_cashflow_actual_long(company_data: dict, frequency: str) -> pd.DataFrame:
    """
    Actuals cash-flow combinés : FMP -> Alpha -> SEC -> yfinance.
    Important : on combine les providers au lieu de retourner FMP seulement, car FMP/yfinance peuvent limiter l'historique à 4 ans.
    """
    frames = []

    fmp = company_data.get("fmp", {})
    key = "cashflow_annual" if frequency == "Annuel" else "cashflow_quarterly"
    records = fmp.get(key, []) if isinstance(fmp, dict) else []

    if records:
        frames.append(records_to_actual_long(records, FMP_CASHFLOW_ACTUAL_KEYS, frequency, "FMP cash-flow statement"))

    alpha_df = alpha_cashflow_actual_long(company_data, frequency)
    if not alpha_df.empty:
        frames.append(alpha_df)

    sec_cash_map = {
        metric: concepts
        for metric, concepts in SEC_CONCEPT_MAP.items()
        if metric in ["Operating Cash Flow", "Capital Expenditure"]
    }

    # SEC cash-flow trimestriel est souvent cumulatif/YTD.
    # Cela peut créer de faux actuals très élevés sur Q2 2026 / Q3 2026.
    # On garde SEC en annuel, mais on l'exclut du cash-flow trimestriel.
    if frequency == "Annuel":
        sec_df = sec_companyfacts_to_actual_long(
            company_data,
            frequency,
            sec_cash_map,
            "SEC companyfacts"
        )
        if not sec_df.empty:
            frames.append(sec_df)

    statement = (
        company_data.get("cashflow", pd.DataFrame())
        if frequency == "Annuel"
        else company_data.get("quarterly_cashflow", pd.DataFrame())
    )

    yf_df = yfinance_statement_to_actual_long(statement, YF_CASHFLOW_ROW_MAP, frequency, "yfinance")
    if not yf_df.empty:
        frames.append(yf_df)

    out = combine_actual_frames(frames)
    return derive_fcf_and_standardize_capex(out)


def fmp_earnings_calendar_to_income_estimate_long(
    company_data: dict,
    frequency: str
) -> pd.DataFrame:
    """
    Transforme FMP earnings_calendar / earnings_surprises en estimates Revenue / EPS.

    Trimestriel :
    - garde chaque trimestre séparé.

    Annuel :
    - agrège les trimestres par année :
      Revenue FY = somme des revenue estimates trimestrielles
      EPS FY = somme des EPS estimates trimestrielles.
    """
    fmp = company_data.get("fmp", {})

    if not isinstance(fmp, dict):
        return empty_estimate_long()

    # FMP earnings_calendar est fiable pour EPS/Revenue trimestriel.
    # En annuel, l'agrégation crée des faux estimates énormes.
    # Les estimates annuelles doivent venir de Alpha / analyst estimates / proxy.
    if frequency == "Annuel":
        return empty_estimate_long()

    records = []
    records += fmp.get("earnings_calendar", []) or []
    records += fmp.get("earnings_surprises", []) or []

    if not records:
        return empty_estimate_long()

    rows = []

    for item in records:
        if not isinstance(item, dict):
            continue

        date = parse_date_safe(first_present_flexible(item, [
            "date",
            "fiscalDateEnding",
            "fiscal_date_ending",
            "reportedDate",
            "reportDate",
        ]))

        if pd.isna(date):
            continue

        eps_estimate = safe_float(first_present_flexible(item, [
            "epsEstimated",
            "estimatedEarning",
            "estimatedEPS",
            "estimatedEps",
            "epsEstimate",
            "eps_estimated",
            "estimated_eps",
        ]))

        revenue_estimate = safe_float(first_present_flexible(item, [
            "revenueEstimated",
            "estimatedRevenue",
            "revenueEstimate",
            "revenue_estimated",
            "estimated_revenue",
            "revenue_estimate",
        ]))

        if eps_estimate is not None:
            rows.append({
                "Date Estimate": date,
                "Period": period_label(date, "Trimestriel"),
                "Frequency": "Trimestriel",
                "Metric": "EPS",
                "Estimate": eps_estimate,
                "Source Estimate": "FMP earnings calendar",
            })

        if revenue_estimate is not None:
            rows.append({
                "Date Estimate": date,
                "Period": period_label(date, "Trimestriel"),
                "Frequency": "Trimestriel",
                "Metric": "Revenue",
                "Estimate": revenue_estimate,
                "Source Estimate": "FMP earnings calendar",
            })

    if not rows:
        return empty_estimate_long()

    quarterly = pd.DataFrame(rows)
    quarterly["Date Estimate"] = pd.to_datetime(quarterly["Date Estimate"], errors="coerce")
    quarterly["Estimate"] = pd.to_numeric(quarterly["Estimate"], errors="coerce")
    quarterly = quarterly.dropna(subset=["Date Estimate", "Estimate"])

    if quarterly.empty:
        return empty_estimate_long()

    if frequency == "Trimestriel":
        return quarterly[ESTIMATE_LONG_COLUMNS]

    quarterly["Year"] = quarterly["Date Estimate"].dt.year

    annual = (
        quarterly.groupby(["Year", "Metric"], as_index=False)
        .agg({
            "Estimate": "sum",
            "Date Estimate": "max",
        })
    )

    annual_rows = []

    for _, row in annual.iterrows():
        year = int(row["Year"])
        estimate = safe_float(row["Estimate"])

        if estimate is None:
            continue

        annual_rows.append({
            "Date Estimate": row["Date Estimate"],
            "Period": f"FY {year}",
            "Frequency": "Annuel",
            "Metric": row["Metric"],
            "Estimate": estimate,
            "Source Estimate": "FMP earnings calendar aggregate",
        })

    if not annual_rows:
        return empty_estimate_long()

    return pd.DataFrame(annual_rows)[ESTIMATE_LONG_COLUMNS]


def build_income_estimate_long(company_data: dict, frequency: str) -> pd.DataFrame:
    """
    Estimates compte de résultat.

    Priorité :
    1. FMP analyst estimates.
    2. FMP earnings calendar pour EPS / Revenue trimestriels.
    3. Proxy transparent quand FMP ne fournit pas assez de lignes :
       Revenue = dernier actual × revenueGrowth.
       Marges = Revenue estimate × marge historique.
    """
    fmp = company_data.get("fmp", {})
    info = company_data.get("info", {})

    key = "estimates_annual" if frequency == "Annuel" else "estimates_quarterly"
    records = fmp.get(key, [])

    frames = []

    fmp_estimates = records_to_estimate_long(
        records,
        FMP_INCOME_ESTIMATE_KEYS,
        frequency,
        "FMP analyst estimates"
    )

    if not fmp_estimates.empty and fmp_estimates["Estimate"].notna().any():
        frames.append(fmp_estimates)

    fmp_calendar_estimates = fmp_earnings_calendar_to_income_estimate_long(
        company_data,
        frequency
    )

    if not fmp_calendar_estimates.empty and fmp_calendar_estimates["Estimate"].notna().any():
        frames.append(fmp_calendar_estimates)

    finnhub_calendar_estimates = finnhub_calendar_to_income_estimate_long(
        company_data,
        frequency
    )

    if not finnhub_calendar_estimates.empty and finnhub_calendar_estimates["Estimate"].notna().any():
        frames.append(finnhub_calendar_estimates)

    finnhub_estimates = finnhub_estimates_to_income_estimate_long(
        company_data,
        frequency
    )

    if not finnhub_estimates.empty and finnhub_estimates["Estimate"].notna().any():
        frames.append(finnhub_estimates)
    
    alpha_estimates = alpha_earnings_estimates_to_income_estimate_long(
        company_data,
        frequency
    )

    if not alpha_estimates.empty and alpha_estimates["Estimate"].notna().any():
        frames.append(alpha_estimates)

    if frequency == "Trimestriel":
        calendar_rows = []
        raw_calendar = []
        raw_calendar += fmp.get("earnings_calendar", []) or []
        raw_calendar += fmp.get("earnings_surprises", []) or []

        for item in raw_calendar:
            if not isinstance(item, dict):
                continue

            date = parse_date_safe(first_present_flexible(item, [
                "date",
                "fiscalDateEnding",
                "fiscal_date_ending",
                "reportedDate",
                "reportDate",
            ]))

            if pd.isna(date):
                continue

            period = period_label_from_record(item, "Trimestriel")

            eps_estimate = safe_float(first_present_flexible(item, [
                "epsEstimated",
                "estimatedEarning",
                "estimatedEPS",
                "epsEstimate",
                "estimatedEps",
                "eps_estimated",
                "estimated_eps",
            ]))

            revenue_estimate = safe_float(first_present_flexible(item, [
                "revenueEstimated",
                "estimatedRevenue",
                "revenueEstimate",
                "revenue_estimated",
                "estimated_revenue",
                "revenue_estimate",
            ]))

            if eps_estimate is not None:
                calendar_rows.append({
                    "Date Estimate": date,
                    "Period": period,
                    "Frequency": frequency,
                    "Metric": "EPS",
                    "Estimate": eps_estimate,
                    "Source Estimate": "FMP earnings calendar",
                })

            if revenue_estimate is not None:
                calendar_rows.append({
                    "Date Estimate": date,
                    "Period": period,
                    "Frequency": frequency,
                    "Metric": "Revenue",
                    "Estimate": revenue_estimate,
                    "Source Estimate": "FMP earnings calendar",
                })

        if calendar_rows:
            frames.append(pd.DataFrame(calendar_rows))

    existing = pd.concat(frames, ignore_index=True) if frames else empty_estimate_long()

    income_actual = build_income_actual_long(company_data, frequency)
    proxy_rows = []
    margin_map = {}

    if not income_actual.empty:
        actual_pivot = income_actual.pivot_table(
            index=["Date", "Period", "Frequency"],
            columns="Metric",
            values="Actual",
            aggfunc="first"
        ).reset_index()

        actual_pivot["Date"] = pd.to_datetime(actual_pivot["Date"], errors="coerce")
        actual_pivot = actual_pivot.sort_values("Date")

        revenue_hist = pd.to_numeric(actual_pivot.get("Revenue"), errors="coerce") if "Revenue" in actual_pivot.columns else pd.Series(dtype=float)
        revenue_hist = revenue_hist.dropna()

        margin_map = {}

        if frequency == "Trimestriel":
            # ------------------------------------------------------------
            # Robust quarterly margin map
            # ------------------------------------------------------------
            # Le problème Q2 2026 vient d'une marge historique quasi nulle.
            # On calcule donc les marges par Period/Frequency, pas par Date,
            # puis on filtre les marges absurdes.
            #
            # Important :
            # - ne touche pas aux FY ;
            # - ne touche pas aux actuals ;
            # - ne touche pas au render ;
            # - ne touche pas au merge ;
            # - ne remplace pas les vraies Revenue estimates.
            margin_source = income_actual.copy()
            margin_source["Date"] = pd.to_datetime(margin_source["Date"], errors="coerce")

            margin_pivot_values = margin_source.pivot_table(
                index=["Period", "Frequency"],
                columns="Metric",
                values="Actual",
                aggfunc="first"
            ).reset_index()

            margin_pivot_dates = (
                margin_source
                .dropna(subset=["Date"])
                .groupby(["Period", "Frequency"], as_index=False)["Date"]
                .max()
            )

            margin_pivot = margin_pivot_values.merge(
                margin_pivot_dates,
                on=["Period", "Frequency"],
                how="left"
            )

            margin_pivot = margin_pivot.sort_values("Date")

            info_margin_fallback = {
                "Gross Profit": safe_float(info.get("grossMargins")),
                "EBITDA": safe_float(info.get("ebitdaMargins")),
                "Operating Income": safe_float(info.get("operatingMargins")),
                "EBIT": safe_float(info.get("operatingMargins")),
                "Net Income": safe_float(info.get("profitMargins")),
            }

            if "Revenue" in margin_pivot.columns:
                revenue_series = pd.to_numeric(
                    margin_pivot["Revenue"],
                    errors="coerce"
                )

                for metric in ["Gross Profit", "Operating Income", "EBITDA", "EBIT", "Net Income"]:
                    if metric not in margin_pivot.columns:
                        fallback_margin = info_margin_fallback.get(metric)

                        if fallback_margin is not None and -0.75 < fallback_margin < 1.50:
                            margin_map[metric] = float(fallback_margin)

                        continue

                    numerator_series = pd.to_numeric(
                        margin_pivot[metric],
                        errors="coerce"
                    )

                    margins = (
                        numerator_series / revenue_series
                    ).replace([np.inf, -np.inf], np.nan).dropna()

                    # Filtres de plausibilité.
                    # Gross margin ne devrait pas être négative ou quasi nulle pour NVDA.
                    if metric == "Gross Profit":
                        margins = margins[
                            (margins > 0.03)
                            & (margins < 1.20)
                        ]
                    else:
                        margins = margins[
                            (margins > -0.75)
                            & (margins < 1.20)
                        ]

                    candidate_margin = None

                    if not margins.empty:
                        candidate_margin = safe_float(margins.tail(8).median())

                    fallback_margin = info_margin_fallback.get(metric)

                    if fallback_margin is not None and not (-0.75 < fallback_margin < 1.50):
                        fallback_margin = None

                    # Cas exact du bug :
                    # marge calculée autour de 0.1% alors que la marge info/yfinance
                    # est cohérente. On utilise alors le fallback.
                    if (
                        candidate_margin is not None
                        and fallback_margin is not None
                        and abs(candidate_margin) < 0.01
                        and abs(fallback_margin) > 0.03
                    ):
                        margin_map[metric] = float(fallback_margin)

                    elif candidate_margin is not None:
                        margin_map[metric] = float(candidate_margin)

                    elif fallback_margin is not None:
                        margin_map[metric] = float(fallback_margin)

        else:
            # FY : on garde la logique précédente, car l'annuel fonctionne.
            if "Revenue" in actual_pivot.columns:
                for metric in ["Gross Profit", "Operating Income", "EBITDA", "EBIT", "Net Income"]:
                    if metric not in actual_pivot.columns:
                        continue

                    margins = (
                        pd.to_numeric(actual_pivot[metric], errors="coerce")
                        / pd.to_numeric(actual_pivot["Revenue"], errors="coerce")
                    ).replace([np.inf, -np.inf], np.nan).dropna()

                    if not margins.empty:
                        margin_map[metric] = float(margins.tail(4).mean())
        # ------------------------------------------------------------
        # Annual FY backfill — uniquement pour les années réalisées
        # ------------------------------------------------------------
        # Problème :
        # Alpha fournit surtout les FY forward, par exemple FY2027/FY2028.
        # Pour FY2026 / FY2025 / FY2024 déjà réalisés, les APIs retail
        # ne donnent pas toujours le consensus historique annuel.
        #
        # Solution prudente :
        # - ne touche pas au trimestriel ;
        # - ne remplace jamais une vraie estimate existante ;
        # - crée seulement un proxy transparent pour Revenue annuel manquant ;
        # - les autres lignes seront ensuite dérivées via les marges historiques.
        if frequency == "Annuel":
            existing_revenue_periods = set()

            if not existing.empty:
                existing_revenue_periods = set(
                    existing.loc[
                        (existing["Metric"] == "Revenue")
                        & existing["Estimate"].notna(),
                        "Period"
                    ].astype(str)
                )

            if "Revenue" in actual_pivot.columns:
                annual_revenue_actuals = actual_pivot[
                    actual_pivot["Revenue"].notna()
                ].copy()

                annual_revenue_actuals["Date"] = pd.to_datetime(
                    annual_revenue_actuals["Date"],
                    errors="coerce"
                )

                annual_revenue_actuals["Revenue"] = pd.to_numeric(
                    annual_revenue_actuals["Revenue"],
                    errors="coerce"
                )

                annual_revenue_actuals = (
                    annual_revenue_actuals
                    .dropna(subset=["Date", "Revenue"])
                    .sort_values("Date")
                    .copy()
                )

                annual_revenue_actuals["Historical Revenue Growth"] = (
                    annual_revenue_actuals["Revenue"].pct_change()
                )

                for idx in range(1, len(annual_revenue_actuals)):
                    row = annual_revenue_actuals.iloc[idx]
                    period = str(row.get("Period"))

                    # Ne jamais écraser Alpha / FMP / Finnhub.
                    if period in existing_revenue_periods:
                        continue

                    previous_revenue = safe_float(
                        annual_revenue_actuals.iloc[idx - 1].get("Revenue")
                    )

                    if previous_revenue in [None, 0]:
                        continue

                    prior_growths = pd.to_numeric(
                        annual_revenue_actuals.iloc[:idx]["Historical Revenue Growth"],
                        errors="coerce"
                    ).replace([np.inf, -np.inf], np.nan).dropna()

                    if not prior_growths.empty:
                        revenue_growth_proxy = float(prior_growths.tail(3).median())
                    else:
                        revenue_growth_proxy = safe_float(info.get("revenueGrowth"), 0.0) or 0.0

                    # Garde-fou anti-estimates absurdes.
                    revenue_growth_proxy = max(-0.50, min(1.50, revenue_growth_proxy))

                    proxy_rows.append({
                        "Date Estimate": row.get("Date"),
                        "Period": period,
                        "Frequency": frequency,
                        "Metric": "Revenue",
                        "Estimate": previous_revenue * (1 + revenue_growth_proxy),
                        "Source Estimate": "Proxy backfill FY: previous Revenue × historical revenue growth",
                    })

        revenue_estimates = (
            existing[
                (existing["Metric"] == "Revenue")
                & existing["Estimate"].notna()
            ].copy()
            if not existing.empty
            else empty_estimate_long()
        )

        if revenue_estimates.empty and not revenue_hist.empty:
            latest_actual_row = actual_pivot[actual_pivot["Revenue"].notna()].iloc[-1]
            latest_date = pd.to_datetime(latest_actual_row["Date"], errors="coerce")
            latest_revenue = safe_float(latest_actual_row.get("Revenue"))

            revenue_growth = safe_float(info.get("revenueGrowth"))

            if revenue_growth is None and len(revenue_hist) >= 2 and revenue_hist.iloc[-2] not in [None, 0]:
                revenue_growth = float(revenue_hist.iloc[-1] / revenue_hist.iloc[-2] - 1)

            if latest_revenue is not None and revenue_growth is not None and not pd.isna(latest_date):
                if frequency == "Annuel":
                    next_date = latest_date + pd.DateOffset(years=1)
                    next_period = f"FY {next_date.year}"
                else:
                    next_date = latest_date + pd.DateOffset(months=3)
                    next_period = f"Q{next_date.quarter} {next_date.year}"

                proxy_rows.append({
                    "Date Estimate": next_date,
                    "Period": next_period,
                    "Frequency": frequency,
                    "Metric": "Revenue",
                    "Estimate": latest_revenue * (1 + revenue_growth),
                    "Source Estimate": "Proxy: latest Revenue × yfinance revenueGrowth",
                })

                revenue_estimates = pd.DataFrame([proxy_rows[-1]])

        working_estimates = pd.concat(
            [existing] + ([pd.DataFrame(proxy_rows)] if proxy_rows else []),
            ignore_index=True
        ) if (not existing.empty or proxy_rows) else empty_estimate_long()

        revenue_estimates = working_estimates[
            (working_estimates["Metric"] == "Revenue")
            & working_estimates["Estimate"].notna()
        ].copy()

        for _, rev_row in revenue_estimates.iterrows():
            revenue_forward = safe_float(rev_row.get("Estimate"))

            if revenue_forward is None:
                continue

            for metric in ["Gross Profit", "Operating Income", "EBITDA", "EBIT", "Net Income"]:
                margin = margin_map.get(metric)

                if margin is None or pd.isna(margin):
                    continue

                proxy_rows.append({
                    "Date Estimate": rev_row.get("Date Estimate"),
                    "Period": rev_row.get("Period"),
                    "Frequency": frequency,
                    "Metric": metric,
                    "Estimate": revenue_forward * margin,
                    "Source Estimate": f"Proxy: Revenue estimate × historical {metric} margin",
                })

        earnings_growth = safe_float(info.get("earningsGrowth"))

        if earnings_growth is None:
            earnings_growth = safe_float(info.get("earningsQuarterlyGrowth"))

        if "EPS" in actual_pivot.columns and earnings_growth is not None:
            eps_hist = pd.to_numeric(actual_pivot["EPS"], errors="coerce").dropna()

            if not eps_hist.empty:
                latest_eps = safe_float(eps_hist.iloc[-1])

                if latest_eps is not None and not revenue_estimates.empty:
                    for _, rev_row in revenue_estimates.iterrows():
                        proxy_rows.append({
                            "Date Estimate": rev_row.get("Date Estimate"),
                            "Period": rev_row.get("Period"),
                            "Frequency": frequency,
                            "Metric": "EPS",
                            "Estimate": latest_eps * (1 + earnings_growth),
                            "Source Estimate": "Proxy: latest EPS × yfinance earningsGrowth",
                        })

    if proxy_rows:
        frames.append(pd.DataFrame(proxy_rows))

    if not frames:
        return empty_estimate_long()

    out = pd.concat(frames, ignore_index=True)
    out["Date Estimate"] = pd.to_datetime(out["Date Estimate"], errors="coerce")
    out["Estimate"] = pd.to_numeric(out["Estimate"], errors="coerce")
    out = out.dropna(subset=["Estimate"])

    if out.empty:
        return empty_estimate_long()

    # ------------------------------------------------------------
    # Nettoyage trimestriel anti-mauvaise échelle
    # ------------------------------------------------------------
    # Certains providers peuvent renvoyer des estimates income très petites
    # pour Gross Profit / EBITDA / Operating Income / Net Income / EBIT
    # alors que Revenue Estimate est en dollars complets.
    #
    # Exemple typique :
    # Revenue Estimate = 78B
    # Gross Profit Estimate = 60 ou 60M
    #
    # Ces lignes bloquent ensuite le safety fill car elles existent déjà.
    # On supprime uniquement les lignes directes suspectes, jamais les proxies.
    # Le safety fill ou les proxies déjà calculés reprennent ensuite la main.
    if frequency == "Trimestriel" and margin_map:
        revenue_reference = out[
            (out["Metric"] == "Revenue")
            & out["Estimate"].notna()
        ].copy()

        revenue_reference["Period"] = revenue_reference["Period"].astype(str)

        revenue_by_period = (
            revenue_reference
            .sort_values("Date Estimate")
            .drop_duplicates(subset=["Period"], keep="last")
            .set_index("Period")["Estimate"]
            .to_dict()
        )

        min_ratio_by_metric = {
            "Gross Profit": 0.02,
            "Operating Income": 0.0025,
            "EBITDA": 0.0025,
            "EBIT": 0.0025,
            "Net Income": 0.0025,
        }

        rows_to_drop = []

        for idx, row in out.iterrows():
            metric = str(row.get("Metric"))
            if metric not in min_ratio_by_metric:
                continue

            source = str(row.get("Source Estimate", "")).lower()

            # Ne jamais supprimer les proxies/calculated.
            if "proxy" in source or "calculated" in source:
                continue

            period = str(row.get("Period"))
            revenue_estimate = safe_float(revenue_by_period.get(period))
            metric_estimate = safe_float(row.get("Estimate"))

            if revenue_estimate in [None, 0] or metric_estimate is None:
                continue

            # On ne déclenche ce filtre que sur des revenus vraiment grands.
            # Cela évite de pénaliser des small caps ou des cas particuliers.
            if abs(revenue_estimate) < 1_000_000_000:
                continue

            ratio = abs(metric_estimate) / abs(revenue_estimate)

            bad_unit_scale = abs(metric_estimate) < 1_000_000
            bad_margin_scale = ratio < min_ratio_by_metric[metric]

            if bad_unit_scale or bad_margin_scale:
                rows_to_drop.append(idx)

        if rows_to_drop:
            out = out.drop(index=rows_to_drop).copy()

    # ------------------------------------------------------------
    # Safety fill trimestriel :

    # ------------------------------------------------------------
    # Safety fill trimestriel :
    # si une période forward a Revenue Estimate mais pas les lignes income dérivées,
    # on complète uniquement les métriques manquantes.
    #
    # Cas visé : Q2 2026 avec Revenue Estimate disponible, mais Gross Profit /
    # Operating Income / Net Income / EBITDA / EBIT absents.
    # Ne remplace jamais une vraie estimate existante.
    # Ne touche pas aux annual/FY.
    # ------------------------------------------------------------
    if frequency == "Trimestriel" and margin_map:
        safety_rows = []

        revenue_estimate_rows = out[
            (out["Metric"] == "Revenue")
            & out["Estimate"].notna()
        ].copy()

        for _, rev_row in revenue_estimate_rows.iterrows():
            period = str(rev_row.get("Period"))
            revenue_forward = safe_float(rev_row.get("Estimate"))

            if revenue_forward is None:
                continue

            for metric in ["Gross Profit", "Operating Income", "EBITDA", "EBIT", "Net Income"]:
                already_exists = (
                    (out["Period"].astype(str) == period)
                    & (out["Frequency"] == frequency)
                    & (out["Metric"] == metric)
                    & (out["Estimate"].notna())
                ).any()

                if already_exists:
                    continue

                margin = margin_map.get(metric)

                if margin is None or pd.isna(margin):
                    continue

                safety_rows.append({
                    "Date Estimate": rev_row.get("Date Estimate"),
                    "Period": rev_row.get("Period"),
                    "Frequency": frequency,
                    "Metric": metric,
                    "Estimate": revenue_forward * margin,
                    "Source Estimate": f"Proxy safety fill: Revenue estimate × historical {metric} margin",
                })

        if safety_rows:
            out = pd.concat([out, pd.DataFrame(safety_rows)], ignore_index=True)
            out["Date Estimate"] = pd.to_datetime(out["Date Estimate"], errors="coerce")
            out["Estimate"] = pd.to_numeric(out["Estimate"], errors="coerce")
            out = out.dropna(subset=["Estimate"])

    # ------------------------------------------------------------
    # Rebuild canonique des proxies income trimestriels
    # ------------------------------------------------------------
    # Problème corrigé :
    # Q2 2026 a le bon Revenue Estimate Alpha Vantage (~78B),
    # mais les proxies Gross Profit / Operating Income / Net Income
    # peuvent avoir été générés plus tôt à partir d'un Revenue FMP calendar
    # parasite beaucoup trop petit.
    #
    # Solution :
    # - supprimer uniquement les proxies income trimestriels déjà créés ;
    # - sélectionner un seul meilleur Revenue Estimate par Period/Frequency ;
    # - reconstruire Gross Profit / Operating Income / EBITDA / EBIT / Net Income
    #   à partir de ce Revenue canonique.
    #
    # Ne touche pas :
    # - aux FY ;
    # - aux Revenue estimates ;
    # - aux actuals ;
    # - au cash-flow ;
    # - au rendu graphique.
    if frequency == "Trimestriel" and margin_map:
        income_proxy_metrics = [
            "Gross Profit",
            "Operating Income",
            "EBITDA",
            "EBIT",
            "Net Income",
        ]

        source_text = out["Source Estimate"].astype(str).str.lower()

        bad_existing_proxy_mask = (
            out["Metric"].isin(income_proxy_metrics)
            & source_text.str.contains("revenue estimate", na=False)
            & source_text.str.contains("historical", na=False)
            & source_text.str.contains("proxy", na=False)
        )

        # On enlève seulement les proxies income.
        # Les vraies estimates directes éventuelles restent intactes.
        out = out.loc[~bad_existing_proxy_mask].copy()

        revenue_candidates = out[
            (out["Metric"] == "Revenue")
            & out["Estimate"].notna()
        ].copy()

        if not revenue_candidates.empty:
            revenue_candidates["Date Estimate"] = pd.to_datetime(
                revenue_candidates["Date Estimate"],
                errors="coerce"
            )

            revenue_candidates["Estimate"] = pd.to_numeric(
                revenue_candidates["Estimate"],
                errors="coerce"
            )

            revenue_candidates = revenue_candidates.dropna(subset=["Estimate"])

            revenue_candidates["_priority"] = revenue_candidates["Source Estimate"].apply(
                estimate_source_priority
            )

            # À priorité égale, on garde la date la plus récente.
            # Si plusieurs lignes restent encore identiques, on garde le plus gros montant,
            # ce qui évite les petits revenus FMP calendar parasites.
            revenue_candidates["_abs_estimate"] = revenue_candidates["Estimate"].abs()

            revenue_candidates = revenue_candidates.sort_values(
                ["Period", "Frequency", "_priority", "Date Estimate", "_abs_estimate"],
                ascending=[True, True, True, False, False],
                na_position="last"
            )

            best_revenue_by_period = revenue_candidates.drop_duplicates(
                subset=["Period", "Frequency"],
                keep="first"
            )

            # Garde-fou : si le revenu sélectionné est absurde par rapport aux derniers actuals,
            # on ne génère pas de proxy income pour cette période.
            actual_revenue_reference = None

            try:
                if not income_actual.empty:
                    actual_revenues = pd.to_numeric(
                        income_actual.loc[
                            (income_actual["Metric"] == "Revenue")
                            & income_actual["Actual"].notna(),
                            "Actual"
                        ],
                        errors="coerce"
                    ).dropna()

                    if not actual_revenues.empty:
                        actual_revenue_reference = float(actual_revenues.tail(4).median())
            except Exception:
                actual_revenue_reference = None

            canonical_proxy_rows = []

            for _, rev_row in best_revenue_by_period.iterrows():
                revenue_forward = safe_float(rev_row.get("Estimate"))

                if revenue_forward is None:
                    continue

                # Si on a un business à dizaines de milliards de revenus,
                # on refuse de construire des proxies depuis un revenu minuscule.
                if (
                    actual_revenue_reference is not None
                    and abs(actual_revenue_reference) >= 1_000_000_000
                    and abs(revenue_forward) < abs(actual_revenue_reference) * 0.10
                ):
                    continue

                for metric in income_proxy_metrics:
                    margin = margin_map.get(metric)

                    if margin is None or pd.isna(margin):
                        continue

                    canonical_proxy_rows.append({
                        "Date Estimate": rev_row.get("Date Estimate"),
                        "Period": rev_row.get("Period"),
                        "Frequency": rev_row.get("Frequency"),
                        "Metric": metric,
                        "Estimate": revenue_forward * margin,
                        "Source Estimate": f"Proxy canonical: best Revenue estimate × historical {metric} margin",
                    })

            if canonical_proxy_rows:
                out = pd.concat(
                    [out, pd.DataFrame(canonical_proxy_rows)],
                    ignore_index=True
                )

                out["Date Estimate"] = pd.to_datetime(
                    out["Date Estimate"],
                    errors="coerce"
                )

                out["Estimate"] = pd.to_numeric(
                    out["Estimate"],
                    errors="coerce"
                )

                out = out.dropna(subset=["Estimate"])

    out["_priority"] = out["Source Estimate"].apply(estimate_source_priority)

    out = out.sort_values(
        ["Period", "Frequency", "Metric", "_priority", "Date Estimate"],
        na_position="last"
    )

    out = out.drop_duplicates(
        subset=["Period", "Frequency", "Metric"],
        keep="first"
    )

    out = out.drop(columns=["_priority"], errors="ignore")

    return out[ESTIMATE_LONG_COLUMNS]


def build_cashflow_estimate_long(company_data: dict, frequency: str) -> pd.DataFrame:
    """
    Estimates cash-flow.
    1) Vraies estimates FMP si disponibles.
    2) Proxy transparent basé sur Revenue Estimate × marges cash-flow historiques.
    Les APIs retail ne donnent généralement pas un consensus OCF/FCF/Capex fiable.
    """
    fmp = company_data.get("fmp", {})
    key = "estimates_annual" if frequency == "Annuel" else "estimates_quarterly"
    records = fmp.get(key, []) if isinstance(fmp, dict) else []

    frames = []

    direct = records_to_estimate_long(records, FMP_CASHFLOW_ESTIMATE_KEYS, frequency, "FMP cash-flow estimates")
    if not direct.empty and direct["Estimate"].notna().any():
        frames.append(direct)

    income_estimates = build_income_estimate_long(company_data, frequency)
    income_actual = build_income_actual_long(company_data, frequency)
    cash_actual = build_cashflow_actual_long(company_data, frequency)

    proxy_rows = []

    if not income_estimates.empty and not income_actual.empty and not cash_actual.empty:
        revenue_estimates = income_estimates[
            (income_estimates["Metric"] == "Revenue")
            & income_estimates["Estimate"].notna()
        ].copy()

        revenue_actual = income_actual[
            (income_actual["Metric"] == "Revenue")
            & income_actual["Actual"].notna()
        ][["Period", "Actual"]].rename(columns={"Actual": "Revenue Actual"})

        cash = cash_actual.merge(revenue_actual, on="Period", how="left")
        cash = cash[
            cash["Actual"].notna()
            & cash["Revenue Actual"].notna()
            & (cash["Revenue Actual"] != 0)
        ].copy()

        if not revenue_estimates.empty and not cash.empty:
            cash["Cash Margin"] = cash["Actual"] / cash["Revenue Actual"]

            margin_map = (
                cash.sort_values("Date")
                .groupby("Metric")["Cash Margin"]
                .apply(lambda s: float(s.tail(6).mean()))
                .to_dict()
            )

            for _, rev_row in revenue_estimates.iterrows():
                revenue_forward = safe_float(rev_row.get("Estimate"))
                if revenue_forward is None:
                    continue

                for metric in ["Operating Cash Flow", "Free Cash Flow", "Capital Expenditure"]:
                    margin = margin_map.get(metric)
                    if margin is None or pd.isna(margin):
                        continue

                    estimate = revenue_forward * margin
                    if metric == "Capital Expenditure":
                        estimate = -abs(estimate)

                    proxy_rows.append({
                        "Date Estimate": rev_row.get("Date Estimate"),
                        "Period": rev_row.get("Period"),
                        "Frequency": frequency,
                        "Metric": metric,
                        "Estimate": estimate,
                        "Source Estimate": "Proxy: Revenue estimate × historical cash-flow margin",
                    })

    if proxy_rows:
        frames.append(pd.DataFrame(proxy_rows))

    if not frames:
        return empty_estimate_long()

    out = pd.concat(frames, ignore_index=True)
    out["Date Estimate"] = pd.to_datetime(out["Date Estimate"], errors="coerce")
    out["Estimate"] = pd.to_numeric(out["Estimate"], errors="coerce")
    out = out.dropna(subset=["Estimate"])

    if out.empty:
        return empty_estimate_long()

    out["_priority"] = out["Source Estimate"].apply(estimate_source_priority)
    out = out.sort_values(["Period", "Frequency", "Metric", "_priority", "Date Estimate"], na_position="last")
    out = out.drop_duplicates(subset=["Period", "Frequency", "Metric"], keep="first")
    out = out.drop(columns=["_priority"], errors="ignore")
    return out[ESTIMATE_LONG_COLUMNS]


def merge_actual_estimate_long(actual_df: pd.DataFrame, estimate_df: pd.DataFrame) -> pd.DataFrame:
    if actual_df.empty and estimate_df.empty:
        return pd.DataFrame(columns=[
            "Date", "Period", "Frequency", "Metric", "Actual", "Estimate",
            "Surprise", "Surprise %", "Growth Actual", "Growth Estimate",
            "Forward", "Source Actual", "Source Estimate"
        ])

    merged = pd.merge(
        actual_df,
        estimate_df,
        on=["Period", "Frequency", "Metric"],
        how="outer"
    )

    if "Date" not in merged.columns:
        merged["Date"] = pd.NaT

    if "Date Estimate" not in merged.columns:
        merged["Date Estimate"] = pd.NaT

    merged["Date"] = merged["Date"].combine_first(merged["Date Estimate"])
    merged = merged.sort_values(["Metric", "Date"])

    latest_actual_by_metric = (
        merged[merged["Actual"].notna()]
        .groupby("Metric")["Date"]
        .max()
    )

    merged["_latest_actual_date"] = merged["Metric"].map(latest_actual_by_metric)

    merged["Forward"] = merged["Estimate"].notna() & (
        merged["Actual"].isna()
        | merged["_latest_actual_date"].isna()
        | (merged["Date"] > merged["_latest_actual_date"])
    )

    surprise_mask = (
        merged["Actual"].notna()
        & merged["Estimate"].notna()
        & (~merged["Forward"])
    )

    merged["Surprise"] = np.where(
        surprise_mask,
        merged["Actual"] - merged["Estimate"],
        np.nan
    )

    merged["Surprise %"] = np.where(
        surprise_mask & (merged["Estimate"] != 0),
        merged["Surprise"] / merged["Estimate"].abs(),
        np.nan
    )

    merged = merged.drop(columns=["_latest_actual_date"], errors="ignore")

    merged["Growth Actual"] = merged.groupby("Metric")["Actual"].pct_change()
    merged["Growth Estimate"] = merged.groupby("Metric")["Estimate"].pct_change()

    for col in ["Source Actual", "Source Estimate"]:
        if col not in merged.columns:
            merged[col] = ""

    return merged[[
        "Date",
        "Period",
        "Frequency",
        "Metric",
        "Actual",
        "Estimate",
        "Surprise",
        "Surprise %",
        "Growth Actual",
        "Growth Estimate",
        "Forward",
        "Source Actual",
        "Source Estimate",
    ]]


def limit_explorer_periods(df: pd.DataFrame, max_periods: int) -> pd.DataFrame:
    """
    Limite l'affichage sans casser l'ordre fiscal des quarters.

    Avant, la sélection utilisait Date.
    Problème : NVDA peut avoir un label Q2 2026 avec une date calendrier en 2025.
    Donc Q2 2026 était traité comme historique 2025 et pouvait être placé/supprimé au mauvais endroit.

    Maintenant :
    - sélection par clé de période affichée : Q1 2025, Q2 2025, ..., Q1 2026, Q2 2026
    - garde les périodes réalisées récentes
    - garde les périodes forward suivantes
    """
    if df.empty or "Period" not in df.columns:
        return df

    clean = df.copy()
    clean["Date"] = pd.to_datetime(clean.get("Date"), errors="coerce")
    clean["_PeriodSort"] = clean.apply(
        lambda row: period_sort_key(row.get("Period"), row.get("Date")),
        axis=1
    )

    periods = (
        clean[["Period", "_PeriodSort"]]
        .dropna(subset=["Period"])
        .drop_duplicates()
        .sort_values("_PeriodSort")
    )

    if periods.empty:
        return clean.drop(columns=["_PeriodSort"], errors="ignore")

    actual_rows = clean[clean["Actual"].notna()].copy()

    if actual_rows.empty:
        chosen_periods = periods.tail(max_periods)["Period"].tolist()
    else:
        latest_actual_sort = actual_rows["_PeriodSort"].max()

        actual_periods = (
            periods[periods["_PeriodSort"] <= latest_actual_sort]
            .tail(max_periods)["Period"]
            .tolist()
        )

        forward_periods = (
            periods[periods["_PeriodSort"] > latest_actual_sort]
            .head(max_periods)["Period"]
            .tolist()
        )

        chosen_periods = actual_periods + forward_periods

    out = clean[clean["Period"].isin(chosen_periods)].copy()
    out = out.sort_values(["_PeriodSort", "Metric", "Date"], na_position="last")
    out = out.drop(columns=["_PeriodSort"], errors="ignore")

    return out


def format_value_by_kind(value, kind: str):
    if value is None or pd.isna(value):
        return "N/A"

    if kind == "money":
        return fmt_large_number(value)

    if kind == "pct":
        return fmt_pct(value)

    if kind == "num":
        return fmt_num(value)

    return value


def format_explorer_table(df: pd.DataFrame, value_kind: str, show_estimates: bool) -> pd.DataFrame:
    if df.empty:
        return df

    display = df.copy()

    display["Date"] = pd.to_datetime(display["Date"], errors="coerce").dt.strftime("%Y-%m-%d")

    for col in ["Actual", "Estimate", "Surprise"]:
        if col in display.columns:
            display[col] = display[col].apply(lambda x: format_value_by_kind(x, value_kind))

    for col in ["Surprise %", "Growth Actual", "Growth Estimate"]:
        if col in display.columns:
            display[col] = display[col].apply(fmt_pct)

    display["Forward"] = display["Forward"].apply(lambda x: "Oui" if bool(x) else "Non")

    base_cols = ["Date", "Period", "Metric", "Actual", "Growth Actual"]

    advanced_cols = [
        "Estimate",
        "Surprise",
        "Surprise %",
        "Growth Estimate",
        "Forward",
        "Source Actual",
        "Source Estimate",
    ]

    if show_estimates:
        cols = base_cols + advanced_cols
    else:
        cols = base_cols + ["Source Actual"]

    cols = [col for col in cols if col in display.columns]
    return display[cols]


def render_metric_kpis_v6(df: pd.DataFrame, selected_metrics: list[str], value_kind: str):
    if df.empty or not selected_metrics:
        return

    latest_rows = []

    for metric in selected_metrics:
        sub = df[(df["Metric"] == metric) & (df["Actual"].notna())].sort_values("Date")
        if sub.empty:
            continue
        latest_rows.append(sub.iloc[-1])

    if not latest_rows:
        return

    for start in range(0, len(latest_rows), 4):
        chunk = latest_rows[start:start + 4]
        cols = st.columns(len(chunk))

        for col, row in zip(cols, chunk):
            delta = row.get("Growth Actual")
            delta_text = None if pd.isna(delta) else f"{delta:.2%}"
            col.metric(
                label=f"{row['Metric']} · {row['Period']}",
                value=format_value_by_kind(row["Actual"], value_kind),
                delta=delta_text
            )


def render_explorer_chart_v6(
    df: pd.DataFrame,
    metrics: list[str],
    mode: str,
    value_kind: str,
    title: str,
    chart_type: str
):
    if df.empty or not metrics:
        st.info("Aucune donnée disponible pour le graphique.")
        return

    plot_df = df[df["Metric"].isin(metrics)].copy()
    plot_df["Date"] = pd.to_datetime(plot_df["Date"], errors="coerce")
    plot_df["Period"] = plot_df["Period"].astype(str)

    plot_df["_PeriodSort"] = plot_df.apply(
        lambda row: period_sort_key(row.get("Period"), row.get("Date")),
        axis=1
    )

    plot_df = plot_df.sort_values(["_PeriodSort", "Metric", "Date"], na_position="last").copy()

    period_order = (
        plot_df[["Period", "_PeriodSort"]]
        .dropna(subset=["Period"])
        .drop_duplicates()
        .sort_values("_PeriodSort")["Period"]
        .tolist()
    )

    fig = go.Figure()

    if mode == "Historique":
        valid = plot_df[plot_df["Actual"].notna()]
        if valid.empty:
            st.info("Aucune donnée réalisée disponible.")
            return

        for metric in metrics:
            sub = valid[valid["Metric"] == metric]
            if sub.empty:
                continue

            if chart_type == "Barres":
                fig.add_trace(go.Bar(
                    x=sub["Period"],
                    y=sub["Actual"],
                    name=f"{metric} Actual"
                ))
            else:
                fig.add_trace(go.Scatter(
                    x=sub["Period"],
                    y=sub["Actual"],
                    mode="lines+markers",
                    name=f"{metric} Actual"
                ))

    elif mode == "Actual vs Estimate":
        valid = plot_df[plot_df["Actual"].notna() | plot_df["Estimate"].notna()]
        has_estimate = valid["Estimate"].notna().any()

        if not has_estimate:
            st.info("Aucune donnée estimate réelle disponible. Le graphique ne trace pas de faux estimate.")
            return

        for metric in metrics:
            sub = valid[valid["Metric"] == metric]
            if sub.empty:
                continue

            if sub["Actual"].notna().any():
                fig.add_trace(go.Bar(
                    x=sub["Period"],
                    y=sub["Actual"],
                    name=f"{metric} Actual"
                ))

            if sub["Estimate"].notna().any():
                fig.add_trace(go.Bar(
                    x=sub["Period"],
                    y=sub["Estimate"],
                    name=f"{metric} Estimate"
                ))

    elif mode == "Surprise":
        valid = plot_df[plot_df["Surprise %"].notna()]
        if valid.empty:
            st.info("Aucune surprise calculable : il faut Actual + Estimate sur la même période.")
            return

        for metric in metrics:
            sub = valid[valid["Metric"] == metric]
            if sub.empty:
                continue

            fig.add_trace(go.Bar(
                x=sub["Period"],
                y=sub["Surprise %"],
                name=f"{metric} Surprise %"
            ))

    elif mode == "Forward Curve":
        has_estimate = plot_df["Estimate"].notna().any()

        if not has_estimate:
            st.info("Aucune forward curve réelle disponible. Il faut des estimates externes.")
            return

        for metric in metrics:
            sub = plot_df[plot_df["Metric"] == metric].sort_values("Date")

            actual_sub = sub[sub["Actual"].notna()]
            estimate_sub = sub[sub["Estimate"].notna()]

            if not actual_sub.empty:
                fig.add_trace(go.Scatter(
                    x=actual_sub["Period"],
                    y=actual_sub["Actual"],
                    mode="lines+markers",
                    name=f"{metric} Actual"
                ))

            if not estimate_sub.empty:
                fig.add_trace(go.Scatter(
                    x=estimate_sub["Period"],
                    y=estimate_sub["Estimate"],
                    mode="lines+markers",
                    name=f"{metric} Estimate / Forward",
                    line=dict(dash="dash")
                ))

    y_title = "Valeur"
    tickformat = None

    if value_kind == "pct" or mode == "Surprise":
        tickformat = ".0%"
        y_title = "Pourcentage"

    fig.update_layout(
        height=560,
        title=title,
        xaxis_title="Période",
        yaxis_title=y_title,
        barmode="group",
        hovermode="x unified",
        margin=dict(l=20, r=20, t=70, b=40)
    )

    if tickformat:
        fig.update_yaxes(tickformat=tickformat)

    if period_order:
        fig.update_xaxes(
            categoryorder="array",
            categoryarray=period_order
        )

    st.plotly_chart(fig, use_container_width=True)


def render_unified_financial_explorer_v6(
    title: str,
    base_df: pd.DataFrame,
    available_metrics: list[str],
    default_metrics: list[str],
    value_kind: str,
    frequency: str,
    max_periods: int,
    show_estimates: bool,
    chart_type: str,
    key_prefix: str
):
    st.subheader(title)

    if base_df.empty:
        st.info(f"Aucune donnée exploitable pour {title.lower()}.")
        return

    limited_df = limit_explorer_periods(base_df, max_periods)

    actual_period_count = (
        limited_df.loc[limited_df["Actual"].notna(), "Period"]
        .drop_duplicates()
        .shape[0]
    )

    if actual_period_count < max_periods:
        st.warning(
            f"Source disponible limitée : {actual_period_count} période(s) réalisée(s) affichée(s) "
            f"sur {max_periods} demandée(s)."
        )

    selected_metrics = st.multiselect(
        f"Métriques — {title}",
        available_metrics,
        default=[m for m in default_metrics if m in available_metrics],
        key=f"{key_prefix}_selected_metrics"
    )

    if not selected_metrics:
        st.info("Sélectionne au moins une métrique.")
        return

    mode_options = ["Historique"]

    if show_estimates:
        mode_options += ["Actual vs Estimate", "Surprise", "Forward Curve"]

    mode = st.radio(
        f"Mode graphique — {title}",
        mode_options,
        horizontal=True,
        key=f"{key_prefix}_mode"
    )

    chart_scope = st.radio(
        f"Portée graphique — {title}",
        ["Toutes les métriques sélectionnées", "Focus une métrique"],
        horizontal=True,
        key=f"{key_prefix}_scope"
    )

    if chart_scope == "Focus une métrique":
        chart_metric = st.selectbox(
            f"Métrique focus — {title}",
            selected_metrics,
            key=f"{key_prefix}_focus_metric"
        )
        chart_metrics = [chart_metric]
    else:
        chart_metrics = selected_metrics

    st.caption(
        f"Lecture en {frequency.lower()} · {actual_period_count} période(s) réalisée(s). "
        "Les données estimates/forward apparaissent si FMP les fournit ou si un proxy transparent est calculé."
    )

    filtered_df = limited_df[limited_df["Metric"].isin(selected_metrics)].copy()

    render_metric_kpis_v6(filtered_df, selected_metrics, value_kind)

    st.dataframe(
        format_explorer_table(filtered_df, value_kind, show_estimates),
        use_container_width=True,
        hide_index=True
    )

    render_explorer_chart_v6(
        df=filtered_df,
        metrics=chart_metrics,
        mode=mode,
        value_kind=value_kind,
        title=f"{title} — {mode}",
        chart_type=chart_type
    )


def build_profitability_long(company_data: dict, frequency: str) -> pd.DataFrame:
    income_actual = build_income_actual_long(company_data, frequency)
    cash_actual = build_cashflow_actual_long(company_data, frequency)
    balance_actual = build_balance_actual_long(company_data, frequency)

    rows = []
    
    if not income_actual.empty:
        income_work = income_actual.copy()
        income_work["Date"] = pd.to_datetime(income_work["Date"], errors="coerce")

        # Important :
        # On calcule les marges par Period/Frequency, pas par Date.
        # Sinon une même période fiscale peut être splitée si Revenue et Gross Profit
        # viennent de sources/dates légèrement différentes.
        pivot_values = income_work.pivot_table(
            index=["Period", "Frequency"],
            columns="Metric",
            values="Actual",
            aggfunc="first"
        ).reset_index()

        pivot_dates = (
            income_work
            .dropna(subset=["Date"])
            .groupby(["Period", "Frequency"], as_index=False)["Date"]
            .max()
        )

        pivot = pivot_values.merge(
            pivot_dates,
            on=["Period", "Frequency"],
            how="left"
        )

        for _, row in pivot.iterrows():
            revenue = safe_float(row.get("Revenue"))
            if revenue in [None, 0]:
                continue

            gross_profit = safe_float(row.get("Gross Profit"))
            ebitda = safe_float(row.get("EBITDA"))
            operating_income = safe_float(row.get("Operating Income"))
            net_income = safe_float(row.get("Net Income"))

            metrics = {
                "Gross Margin": gross_profit / revenue if gross_profit is not None else None,
                "EBITDA Margin": ebitda / revenue if ebitda is not None else None,
                "Operating Margin": operating_income / revenue if operating_income is not None else None,
                "Net Margin": net_income / revenue if net_income is not None else None,
            }

            for metric, value in metrics.items():
                if value is None:
                    continue

                rows.append({
                    "Date": row.get("Date"),
                    "Period": row.get("Period"),
                    "Frequency": frequency,
                    "Metric": metric,
                    "Actual": value,
                    "Source Actual": "Calculated from statements",
                })

    if not cash_actual.empty and not income_actual.empty:
        revenue_actual = income_actual[income_actual["Metric"] == "Revenue"][["Period", "Frequency", "Actual"]].rename(columns={"Actual": "Revenue Actual"})
        fcf_actual = cash_actual[cash_actual["Metric"] == "Free Cash Flow"].merge(revenue_actual, on=["Period", "Frequency"], how="left")

        for _, row in fcf_actual.iterrows():
            fcf = safe_float(row.get("Actual"))
            revenue = safe_float(row.get("Revenue Actual"))
            if fcf is None or revenue in [None, 0]:
                continue

            rows.append({
                "Date": row.get("Date"),
                "Period": row.get("Period"),
                "Frequency": frequency,
                "Metric": "FCF Margin",
                "Actual": fcf / revenue,
                "Source Actual": "Calculated from cash-flow statements",
            })

    if not income_actual.empty and not balance_actual.empty:
        net_income = income_actual[income_actual["Metric"] == "Net Income"][["Date", "Period", "Frequency", "Actual"]].rename(columns={"Actual": "Net Income"})
        balance_pivot = balance_actual.pivot_table(
            index=["Date", "Period", "Frequency"],
            columns="Metric",
            values="Actual",
            aggfunc="first",
        ).reset_index()

        merged = net_income.merge(
            balance_pivot[[c for c in ["Period", "Frequency", "Total Assets", "Total Equity"] if c in balance_pivot.columns]],
            on=["Period", "Frequency"],
            how="left",
        )

        for _, row in merged.iterrows():
            ni = safe_float(row.get("Net Income"))
            equity = safe_float(row.get("Total Equity"))
            assets = safe_float(row.get("Total Assets"))

            if ni is not None and equity not in [None, 0]:
                rows.append({
                    "Date": row.get("Date"),
                    "Period": row.get("Period"),
                    "Frequency": frequency,
                    "Metric": "ROE",
                    "Actual": ni / equity,
                    "Source Actual": "Calculated: Net Income / Equity",
                })

            if ni is not None and assets not in [None, 0]:
                rows.append({
                    "Date": row.get("Date"),
                    "Period": row.get("Period"),
                    "Frequency": frequency,
                    "Metric": "ROA",
                    "Actual": ni / assets,
                    "Source Actual": "Calculated: Net Income / Assets",
                })

    df = pd.DataFrame(rows)

    fmp = company_data.get("fmp", {})
    ratio_key = "ratios_annual" if frequency == "Annuel" else "ratios_quarterly"
    ratio_records = fmp.get(ratio_key, []) if isinstance(fmp, dict) else []

    ratio_map = {
        "ROE": ["returnOnEquity", "roe"],
        "ROA": ["returnOnAssets", "roa"],
        "FCF Margin": ["freeCashFlowMargin", "fcfMargin"],
    }

    ratio_rows = records_to_actual_long(ratio_records, ratio_map, frequency, "FMP ratios")

    if not ratio_rows.empty:
        df = pd.concat([df, ratio_rows], ignore_index=True) if not df.empty else ratio_rows

    if df.empty:
        return pd.DataFrame(columns=["Date", "Period", "Frequency", "Metric", "Actual", "Source Actual"])

    df["_priority"] = df["Source Actual"].map(lambda x: 0 if str(x).startswith("FMP") else 1)
    df = df.sort_values(["Period", "Frequency", "Metric", "_priority", "Date"])
    df = df.drop_duplicates(subset=["Period", "Frequency", "Metric"], keep="first")
    df = df.drop(columns=["_priority"], errors="ignore")
    return df.sort_values(["Metric", "Date"])


def build_profitability_estimate_long(company_data: dict, frequency: str) -> pd.DataFrame:
    """
    Estimates rentabilité dérivées.
    ROE/ROA forward sont calculés par proxy à partir de Net Income Estimate / dernier Equity ou Assets disponible.
    """
    income_estimates = build_income_estimate_long(company_data, frequency)
    cash_estimates = build_cashflow_estimate_long(company_data, frequency)
    balance_actual = build_balance_actual_long(company_data, frequency)

    rows = []

    if not income_estimates.empty:
        income_est_work = income_estimates.copy()
        income_est_work["Date Estimate"] = pd.to_datetime(
            income_est_work["Date Estimate"],
            errors="coerce"
        )

        # Même correction que les actuals :
        # on regroupe par période, pas par date exacte.
        pivot_values = income_est_work.pivot_table(
            index=["Period", "Frequency"],
            columns="Metric",
            values="Estimate",
            aggfunc="first"
        ).reset_index()

        pivot_dates = (
            income_est_work
            .dropna(subset=["Date Estimate"])
            .groupby(["Period", "Frequency"], as_index=False)["Date Estimate"]
            .max()
        )

        pivot = pivot_values.merge(
            pivot_dates,
            on=["Period", "Frequency"],
            how="left"
        )

        for _, row in pivot.iterrows():
            revenue = safe_float(row.get("Revenue"))
            if revenue not in [None, 0]:
                margin_specs = {
                    "Gross Margin": "Gross Profit",
                    "EBITDA Margin": "EBITDA",
                    "Operating Margin": "Operating Income",
                    "Net Margin": "Net Income",
                }

                for margin_metric, numerator_metric in margin_specs.items():
                    numerator = safe_float(row.get(numerator_metric))
                    if numerator is None:
                        continue

                    rows.append({
                        "Date Estimate": row.get("Date Estimate"),
                        "Period": row.get("Period"),
                        "Frequency": frequency,
                        "Metric": margin_metric,
                        "Estimate": numerator / revenue,
                        "Source Estimate": "Calculated from income estimates",
                    })

    if not income_estimates.empty and not cash_estimates.empty:
        revenue_estimates = income_estimates[
            income_estimates["Metric"] == "Revenue"
        ][["Period", "Frequency", "Estimate"]].rename(columns={"Estimate": "Revenue Estimate"})

        fcf_estimates = cash_estimates[
            cash_estimates["Metric"] == "Free Cash Flow"
        ].merge(revenue_estimates, on=["Period", "Frequency"], how="left")

        for _, row in fcf_estimates.iterrows():
            fcf = safe_float(row.get("Estimate"))
            revenue = safe_float(row.get("Revenue Estimate"))
            if fcf is None or revenue in [None, 0]:
                continue

            rows.append({
                "Date Estimate": row.get("Date Estimate"),
                "Period": row.get("Period"),
                "Frequency": frequency,
                "Metric": "FCF Margin",
                "Estimate": fcf / revenue,
                "Source Estimate": "Calculated from cash-flow estimates",
            })

    if not income_estimates.empty and not balance_actual.empty:
        latest_balance = (
            balance_actual.dropna(subset=["Date"])
            .sort_values("Date")
            .pivot_table(index=["Date", "Period", "Frequency"], columns="Metric", values="Actual", aggfunc="first")
            .reset_index()
        )

        latest_equity = None
        latest_assets = None

        if not latest_balance.empty:
            if "Total Equity" in latest_balance.columns:
                latest_equity = safe_float(latest_balance["Total Equity"].dropna().iloc[-1]) if latest_balance["Total Equity"].notna().any() else None
            if "Total Assets" in latest_balance.columns:
                latest_assets = safe_float(latest_balance["Total Assets"].dropna().iloc[-1]) if latest_balance["Total Assets"].notna().any() else None

        ni_estimates = income_estimates[
            (income_estimates["Metric"] == "Net Income")
            & income_estimates["Estimate"].notna()
        ]

        for _, row in ni_estimates.iterrows():
            ni = safe_float(row.get("Estimate"))
            if ni is None:
                continue

            if latest_equity not in [None, 0]:
                rows.append({
                    "Date Estimate": row.get("Date Estimate"),
                    "Period": row.get("Period"),
                    "Frequency": frequency,
                    "Metric": "ROE",
                    "Estimate": ni / latest_equity,
                    "Source Estimate": "Proxy: Net Income estimate / latest equity",
                })

            if latest_assets not in [None, 0]:
                rows.append({
                    "Date Estimate": row.get("Date Estimate"),
                    "Period": row.get("Period"),
                    "Frequency": frequency,
                    "Metric": "ROA",
                    "Estimate": ni / latest_assets,
                    "Source Estimate": "Proxy: Net Income estimate / latest assets",
                })

    if not rows:
        return empty_estimate_long()

    out = pd.DataFrame(rows)
    out["Date Estimate"] = pd.to_datetime(out["Date Estimate"], errors="coerce")
    out["Estimate"] = pd.to_numeric(out["Estimate"], errors="coerce")
    out = out.dropna(subset=["Estimate"])

    if out.empty:
        return empty_estimate_long()

    out["_priority"] = out["Source Estimate"].apply(estimate_source_priority)
    out = out.sort_values(["Period", "Frequency", "Metric", "_priority", "Date Estimate"], na_position="last")
    out = out.drop_duplicates(subset=["Period", "Frequency", "Metric"], keep="first")
    out = out.drop(columns=["_priority"], errors="ignore")
    return out[ESTIMATE_LONG_COLUMNS]
