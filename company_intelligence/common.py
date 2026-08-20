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


# COMPANY INTELLIGENCE V6 — UNIFIED ACTUAL / ESTIMATE / FORWARD
# ============================================================

def is_missing(value) -> bool:
    if value is None:
        return True
    try:
        result = pd.isna(value)
        if isinstance(result, (bool, np.bool_)):
            return bool(result)
        return False
    except Exception:
        return False


def first_present(row: dict, keys: list[str], default=None):
    if not isinstance(row, dict):
        return default

    for key in keys:
        if key in row:
            value = row.get(key)
            if not is_missing(value) and value != "":
                return value

    return default


def parse_date_safe(value):
    try:
        if value is None or value == "":
            return pd.NaT
        return pd.to_datetime(value)
    except Exception:
        return pd.NaT


def infer_frequency_label(frequency: str) -> str:
    return "Annuel" if frequency == "Annuel" else "Trimestriel"

ESTIMATE_LONG_COLUMNS = [
    "Date Estimate",
    "Period",
    "Frequency",
    "Metric",
    "Estimate",
    "Source Estimate",
]


def empty_estimate_long() -> pd.DataFrame:
    return pd.DataFrame(columns=ESTIMATE_LONG_COLUMNS)


def normalize_external_key(key) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def first_present_flexible(row: dict, keys: list[str], default=None):
    """
    Version robuste de first_present :
    - accepte camelCase ;
    - accepte snake_case ;
    - accepte différences de casse ;
    - ignore None / NaN / string vide.
    """
    if not isinstance(row, dict):
        return default

    for key in keys:
        if key in row:
            value = row.get(key)
            if not is_missing(value) and value != "":
                return value

    normalized_map = {
        normalize_external_key(k): k
        for k in row.keys()
    }

    for key in keys:
        normalized_key = normalize_external_key(key)
        real_key = normalized_map.get(normalized_key)

        if real_key is None:
            continue

        value = row.get(real_key)

        if not is_missing(value) and value != "":
            return value

    return default


def estimate_source_priority(source: str) -> int:
    source = str(source or "").lower()

    if "fmp analyst" in source or "fmp estimates" in source:
        return 0

    if "alpha vantage earnings estimates" in source:
        return 1

    if "fmp earnings calendar" in source:
        return 2

    if "finnhub estimates" in source:
        return 3

    if "finnhub earnings calendar" in source:
        return 4

    if "calculated" in source:
        return 5

    if "proxy" in source:
        return 9

    return 8


def period_label_from_record(record: dict, frequency: str) -> str:
    date_value = first_present_flexible(record, [
        "date",
        "fiscalDateEnding",
        "fiscal_date_ending",
        "pricedDate",
        "priced_date",
        "reportedDate",
        "reportDate",
    ])

    date = parse_date_safe(date_value)

    calendar_year = first_present_flexible(record, [
        "calendarYear",
        "calendar_year",
        "year",
        "fiscalYear",
        "fiscal_year",
    ])

    period = first_present_flexible(record, [
        "period",
        "fiscalPeriod",
        "fiscal_period",
    ])

    if frequency == "Annuel":
        if calendar_year is not None:
            return f"FY {calendar_year}"
        if not pd.isna(date):
            return f"FY {date.year}"
        return "FY N/A"

    if period is not None and str(period).upper().startswith("Q"):
        if calendar_year is not None:
            return f"{str(period).upper()} {calendar_year}"
        if not pd.isna(date):
            return f"{str(period).upper()} {date.year}"

    if not pd.isna(date):
        return f"Q{date.quarter} {date.year}"

    return "Q N/A"


def period_sort_key(period, fallback_date=None) -> int:
    """
    Clé de tri basée sur le label affiché.

    Objectif :
    - Q1 2025 < Q2 2025 < Q3 2025 < Q4 2025 < Q1 2026 < Q2 2026
    - Ne pas trier par Date, car certains fiscal quarters NVDA ont une date calendrier en 2025
      mais un label fiscal 2026.
    """
    text = str(period or "").upper().strip()

    match = re.search(r"Q\s*([1-4])\s*(\d{4})", text)
    if match:
        quarter = int(match.group(1))
        year = int(match.group(2))
        return year * 10 + quarter

    match = re.search(r"FY\s*(\d{4})", text)
    if match:
        year = int(match.group(1))
        return year * 10 + 5

    date = parse_date_safe(fallback_date)
    if not pd.isna(date):
        return int(date.year) * 10 + int(date.quarter)

    return 999999


FMP_INCOME_ACTUAL_KEYS = {
    "Revenue": ["revenue", "totalRevenue", "Revenue"],
    "Gross Profit": ["grossProfit", "Gross Profit"],
    "Operating Income": ["operatingIncome", "operatingIncomeLoss", "Operating Income"],
    "Net Income": ["netIncome", "netIncomeCommonStockholders", "Net Income"],
    "EBITDA": ["ebitda", "EBITDA"],
    "EBIT": ["ebit", "EBIT"],
    "EPS": ["eps", "epsdiluted", "reportedEPS", "actualEPS"],
}

FMP_INCOME_ESTIMATE_KEYS = {
    "Revenue": [
        "estimatedRevenueAvg", "estimated_revenue_avg",
        "estimatedRevenueAverage", "estimated_revenue_average",
        "revenueAvg", "revenue_avg",
        "revenueAverage", "revenue_average",
        "estimatedRevenue", "estimated_revenue",
    ],
    "Gross Profit": [
        "estimatedGrossProfitAvg", "estimated_gross_profit_avg",
        "grossProfitAvg", "gross_profit_avg",
        "estimatedGrossProfit", "estimated_gross_profit",
    ],
    "Operating Income": [
        "estimatedOperatingIncomeAvg", "estimated_operating_income_avg",
        "operatingIncomeAvg", "operating_income_avg",
        "estimatedOperatingIncome", "estimated_operating_income",
    ],
    "Net Income": [
        "estimatedNetIncomeAvg", "estimated_net_income_avg",
        "netIncomeAvg", "net_income_avg",
        "estimatedNetIncome", "estimated_net_income",
    ],
    "EBITDA": [
        "estimatedEbitdaAvg", "estimatedEBITDAAvg", "estimated_ebitda_avg",
        "ebitdaAvg", "ebitda_avg",
        "estimatedEbitda", "estimated_ebitda",
    ],
    "EBIT": [
        "estimatedEbitAvg", "estimatedEBITAvg", "estimated_ebit_avg",
        "ebitAvg", "ebit_avg",
        "estimatedEbit", "estimated_ebit",
    ],
    "EPS": [
        "estimatedEpsAvg", "estimatedEPSAvg", "estimated_eps_avg",
        "epsAvg", "eps_avg",
        "epsEstimated", "eps_estimated",
        "estimatedEPS", "estimatedEps", "estimated_eps",
    ],
}

FMP_CASHFLOW_ACTUAL_KEYS = {
    "Operating Cash Flow": ["operatingCashFlow", "netCashProvidedByOperatingActivities", "Operating Cash Flow"],
    "Free Cash Flow": ["freeCashFlow", "Free Cash Flow"],
    "Capital Expenditure": ["capitalExpenditure", "capitalExpenditures", "Capital Expenditure"],
}

FMP_CASHFLOW_ESTIMATE_KEYS = {
    "Operating Cash Flow": [
        "estimatedOperatingCashFlowAvg",
        "estimated_operating_cash_flow_avg",
        "operatingCashFlowAvg",
        "operating_cash_flow_avg",
        "estimatedOperatingCashFlow",
        "estimated_operating_cash_flow",
    ],
    "Free Cash Flow": [
        "estimatedFreeCashFlowAvg",
        "estimated_free_cash_flow_avg",
        "freeCashFlowAvg",
        "free_cash_flow_avg",
        "estimatedFCFAvg",
        "estimated_fcf_avg",
        "estimatedFreeCashFlow",
        "estimated_free_cash_flow",
    ],
    "Capital Expenditure": [
        "estimatedCapitalExpenditureAvg",
        "estimated_capital_expenditure_avg",
        "capitalExpenditureAvg",
        "capital_expenditure_avg",
        "estimatedCapexAvg",
        "estimated_capex_avg",
        "estimatedCapitalExpenditure",
        "estimated_capital_expenditure",
    ],
}

YF_INCOME_ROW_MAP = {
    "Revenue": ["Total Revenue", "Operating Revenue"],
    "Gross Profit": ["Gross Profit"],
    "Operating Income": ["Operating Income", "Operating Income Loss"],
    "Net Income": ["Net Income", "Net Income Common Stockholders"],
    "EBITDA": ["EBITDA", "Normalized EBITDA"],
    "EBIT": ["EBIT", "Operating Income", "Operating Income Loss"],
}

YF_CASHFLOW_ROW_MAP = {
    "Operating Cash Flow": ["Operating Cash Flow", "Total Cash From Operating Activities"],
    "Free Cash Flow": ["Free Cash Flow"],
    "Capital Expenditure": ["Capital Expenditure", "Capital Expenditures"],
}

ALPHA_INCOME_ACTUAL_KEYS = {
    "Revenue": ["totalRevenue"],
    "Gross Profit": ["grossProfit"],
    "Operating Income": ["operatingIncome"],
    "Net Income": ["netIncome"],
    "EBITDA": ["ebitda"],
    "EBIT": ["ebit"],
}

ALPHA_CASHFLOW_ACTUAL_KEYS = {
    "Operating Cash Flow": ["operatingCashflow"],
    "Free Cash Flow": ["freeCashFlow"],
    "Capital Expenditure": ["capitalExpenditures"],
}

FMP_BALANCE_ACTUAL_KEYS = {
    "Total Cash": [
        "cashAndCashEquivalents",
        "cashAndShortTermInvestments",
        "cashAndCashEquivalentsAtCarryingValue",
        "Cash And Cash Equivalents",
    ],
    "Total Debt": [
        "totalDebt",
        "Total Debt",
    ],
    "Net Debt": [
        "netDebt",
        "Net Debt",
    ],
    "Total Assets": [
        "totalAssets",
        "Total Assets",
    ],
    "Total Liabilities": [
        "totalLiabilities",
        "totalLiabilitiesAndStockholdersEquity",
        "Total Liabilities",
    ],
    "Total Equity": [
        "totalStockholdersEquity",
        "totalEquity",
        "stockholdersEquity",
        "Total Stockholders Equity",
    ],
    "Current Assets": [
        "totalCurrentAssets",
        "Total Current Assets",
    ],
    "Current Liabilities": [
        "totalCurrentLiabilities",
        "Total Current Liabilities",
    ],
    "Inventory": [
        "inventory",
        "Inventory",
    ],
}

ALPHA_BALANCE_ACTUAL_KEYS = {
    "Total Cash": [
        "cashAndCashEquivalentsAtCarryingValue",
        "cashAndCashEquivalents",
        "cashAndShortTermInvestments",
    ],
    "Short Term Debt": [
        "shortTermDebt",
        "currentDebt",
    ],
    "Long Term Debt": [
        "longTermDebt",
        "longTermDebtNoncurrent",
    ],
    "Total Assets": [
        "totalAssets",
    ],
    "Total Liabilities": [
        "totalLiabilities",
    ],
    "Total Equity": [
        "totalShareholderEquity",
        "totalStockholdersEquity",
    ],
    "Current Assets": [
        "totalCurrentAssets",
    ],
    "Current Liabilities": [
        "totalCurrentLiabilities",
    ],
    "Inventory": [
        "inventory",
    ],
}

YF_BALANCE_ROW_MAP = {
    "Total Cash": [
        "Cash And Cash Equivalents",
        "Cash Cash Equivalents And Short Term Investments",
        "Cash Financial",
    ],
    "Total Debt": [
        "Total Debt",
    ],
    "Net Debt": [
        "Net Debt",
    ],
    "Total Assets": [
        "Total Assets",
    ],
    "Total Liabilities": [
        "Total Liabilities Net Minority Interest",
        "Total Liab",
        "Total Liabilities",
    ],
    "Total Equity": [
        "Stockholders Equity",
        "Total Equity Gross Minority Interest",
        "Total Stockholder Equity",
    ],
    "Current Assets": [
        "Current Assets",
        "Total Current Assets",
    ],
    "Current Liabilities": [
        "Current Liabilities",
        "Total Current Liabilities",
    ],
    "Inventory": [
        "Inventory",
    ],
}

SEC_CONCEPT_MAP = {
    "Revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "Gross Profit": [
        "GrossProfit",
    ],
    "Operating Income": [
        "OperatingIncomeLoss",
    ],
    "Net Income": [
        "NetIncomeLoss",
        "ProfitLoss",
    ],
    "Operating Cash Flow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "Capital Expenditure": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ],
}




def company_score_table(company_analysis: dict) -> pd.DataFrame:
    scores = company_analysis.get("scores", {})

    return pd.DataFrame([
        {"Bloc": "Croissance", "Score": f"{scores.get('growth_score', 50)}/100", "Poids": "18%"},
        {"Bloc": "Rentabilité", "Score": f"{scores.get('profitability_score', 50)}/100", "Poids": "18%"},
        {"Bloc": "Bilan", "Score": f"{scores.get('balance_score', 50)}/100", "Poids": "12%"},
        {"Bloc": "Valorisation", "Score": f"{scores.get('valuation_score', 50)}/100", "Poids": "14%"},
        {"Bloc": "Forward", "Score": f"{scores.get('forward_score', 50)}/100", "Poids": "16%"},
        {"Bloc": "Surprise estimates", "Score": f"{scores.get('estimate_surprise_score', 50)}/100", "Poids": "12%"},
        {"Bloc": "Analystes", "Score": f"{scores.get('analyst_score', 50)}/100", "Poids": "7%"},
        {"Bloc": "Market feeling", "Score": f"{scores.get('sentiment_score', 50)}/100", "Poids": "3%"},
        {"Bloc": "Core Fundamental Score", "Score": f"{scores.get('company_score', 50)}/100", "Poids": "Composite"},
    ])


def make_metric_table(metrics: dict, rows: list[tuple[str, str, str]]) -> pd.DataFrame:
    output = []
    for label, key, kind in rows:
        value = metrics.get(key)
        if kind == "pct":
            display = fmt_pct(value)
        elif kind == "money":
            display = fmt_large_number(value)
        elif kind == "num":
            display = fmt_num(value)
        else:
            display = "N/A" if value is None else value
        output.append({"Métrique": label, "Valeur": display})
    return pd.DataFrame(output)


def period_label(date_value, frequency: str) -> str:
    date = pd.to_datetime(date_value)

    if frequency == "Trimestriel":
        return f"Q{date.quarter} {date.year}"

    return f"FY {date.year}"
