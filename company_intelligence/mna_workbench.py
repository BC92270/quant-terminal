"""Institutional M&A decision workbench for Company Intelligence.

This module is intentionally independent from the Core Fundamental Score.  It
provides deterministic, inspectable research calculations for transaction
screening, relative valuation, DCF, sources/uses and accretion/dilution.  No
result is an approval, a probability of a deal, or an execution instruction.

The command views are inspired by common institutional workflows (description,
relative valuation, financial analysis and sourced industry research).  They do
not reproduce proprietary Bloomberg data, research or interface layouts.
"""
from __future__ import annotations

from datetime import date
from html import escape
import json
import math
from typing import Any, Mapping, Sequence

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .common import fmt_large_number, safe_float
from .mna_scenarios import (
    ScenarioLedgerError,
    append_scenario,
    load_scenarios,
    verify_ledger,
)


MNA_VERSION = "M&A LAB · 8.1"
RESEARCH_ONLY = "RESEARCH_ONLY · HUMAN REVIEW REQUIRED"

SCENARIO_PROFILES: dict[str, dict[str, float]] = {
    "Bear": {
        "premium": 0.15,
        "synergy_probability": 0.45,
        "synergy_discount_rate": 0.13,
        "cost_synergy_pct_ebitda": 0.020,
        "revenue_synergy_pct_revenue": 0.005,
        "revenue_synergy_margin": 0.25,
        "integration_pct_ebitda": 0.030,
        "dcf_growth_adjustment": -0.04,
        "wacc": 0.115,
        "terminal_growth": 0.020,
        "cash_pct": 0.20,
        "debt_pct": 0.50,
        "run_rate_synergy_pct_target_ebitda": 0.050,
    },
    "Base": {
        "premium": 0.30,
        "synergy_probability": 0.70,
        "synergy_discount_rate": 0.11,
        "cost_synergy_pct_ebitda": 0.030,
        "revenue_synergy_pct_revenue": 0.010,
        "revenue_synergy_margin": 0.30,
        "integration_pct_ebitda": 0.020,
        "dcf_growth_adjustment": 0.0,
        "wacc": 0.100,
        "terminal_growth": 0.030,
        "cash_pct": 0.35,
        "debt_pct": 0.35,
        "run_rate_synergy_pct_target_ebitda": 0.080,
    },
    "Bull": {
        "premium": 0.45,
        "synergy_probability": 0.85,
        "synergy_discount_rate": 0.095,
        "cost_synergy_pct_ebitda": 0.045,
        "revenue_synergy_pct_revenue": 0.020,
        "revenue_synergy_margin": 0.35,
        "integration_pct_ebitda": 0.015,
        "dcf_growth_adjustment": 0.04,
        "wacc": 0.090,
        "terminal_growth": 0.035,
        "cash_pct": 0.40,
        "debt_pct": 0.25,
        "run_rate_synergy_pct_target_ebitda": 0.120,
    },
}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _finite(value: Any) -> float | None:
    value = safe_float(value)
    if value is None or not math.isfinite(value):
        return None
    return float(value)


def _first_scalar(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is None or isinstance(value, (pd.DataFrame, pd.Series, Mapping, list, tuple, set)):
            continue
        if isinstance(value, str) and not value.strip():
            continue
        try:
            if pd.isna(value):
                continue
        except Exception:
            pass
        return value
    return None


def _first_number(*values: Any) -> float | None:
    for value in values:
        number = _finite(value)
        if number is not None:
            return number
    return None


def _frame(value: Any) -> pd.DataFrame:
    return value.copy() if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _statement_value(frame: pd.DataFrame, names: Sequence[str]) -> float | None:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return None
    for name in names:
        if name not in frame.index:
            continue
        selected = frame.loc[name]
        if isinstance(selected, pd.DataFrame):
            selected = selected.iloc[0]
        if not isinstance(selected, pd.Series):
            return _finite(selected)
        values = pd.to_numeric(selected, errors="coerce").dropna()
        if not values.empty:
            return _finite(values.iloc[0])
    return None


def _money(value: Any, currency: str = "USD") -> str:
    number = _finite(value)
    if number is None:
        return "N/A"
    symbol = {"USD": "$", "EUR": "€", "GBP": "£"}.get(str(currency).upper(), "")
    text = fmt_large_number(number)
    return f"{symbol}{text}" if symbol else f"{text} {currency}".strip()


def _multiple(value: Any) -> str:
    number = _finite(value)
    return "N/M" if number is None else f"{number:.2f}x"


def _percent(value: Any, digits: int = 1) -> str:
    number = _finite(value)
    return "N/A" if number is None else f"{number:.{digits}%}"


def _clip(value: Any, low: float, high: float, default: float) -> float:
    number = _finite(value)
    return default if number is None else max(low, min(high, number))


def enterprise_value_bridge(
    equity_value: Any,
    debt: Any,
    cash: Any,
    *,
    preferred: Any = 0.0,
    minority_interest: Any = 0.0,
    lease_liabilities: Any = 0.0,
    unfunded_pensions: Any = 0.0,
    non_operating_investments: Any = 0.0,
) -> dict[str, Any]:
    """Reconcile equity value to enterprise value under an explicit policy."""
    equity = _finite(equity_value)
    debt_value = _finite(debt)
    cash_value = _finite(cash)
    missing = [
        label
        for label, value in (("equity_value", equity), ("debt", debt_value), ("cash", cash_value))
        if value is None
    ]
    if missing:
        return {"status": "BLOCKED", "missing": missing, "enterprise_value": None}
    components = {
        "Equity value": equity,
        "Debt assumed / refinanced": debt_value,
        "Preferred equity": _finite(preferred) or 0.0,
        "Non-controlling interest": _finite(minority_interest) or 0.0,
        "Lease liabilities (policy)": _finite(lease_liabilities) or 0.0,
        "Unfunded pensions": _finite(unfunded_pensions) or 0.0,
        "Cash acquired": -cash_value,
        "Non-operating investments": -(_finite(non_operating_investments) or 0.0),
    }
    return {
        "status": "READY_FOR_HUMAN_REVIEW",
        "missing": [],
        "components": components,
        "enterprise_value": float(sum(components.values())),
    }


def extract_mna_facts(ticker: str, analysis: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize the existing Company Intelligence bundle into an M&A snapshot."""
    outer = _mapping(analysis)
    company = _mapping(outer.get("company_analysis")) or outer
    profile = _mapping(company.get("profile"))
    raw = _mapping(company.get("raw_data"))
    info = _mapping(raw.get("info"))
    growth = _mapping(company.get("growth"))
    profitability = _mapping(company.get("profitability"))
    valuation = _mapping(company.get("valuation"))
    balance = _mapping(company.get("balance"))
    analysts = _mapping(company.get("analysts"))
    forward = _mapping(company.get("forward"))

    financials = _frame(raw.get("financials"))
    balance_sheet = _frame(raw.get("balance_sheet"))
    cashflow = _frame(raw.get("cashflow"))

    price = _first_number(
        _first_scalar(outer, "latest_price", "price", "current_price"),
        _first_scalar(analysts, "current_price", "price"),
        _first_scalar(info, "currentPrice", "regularMarketPrice", "previousClose"),
    )
    market_cap = _first_number(
        _first_scalar(profile, "market_cap", "marketCap"),
        _first_scalar(valuation, "market_cap", "marketCap"),
        _first_scalar(info, "marketCap"),
    )
    shares_observed = _first_number(
        _first_scalar(info, "sharesOutstanding", "impliedSharesOutstanding"),
        _statement_value(balance_sheet, ["Ordinary Shares Number", "Share Issued"]),
    )
    shares = shares_observed
    shares_status = "OBSERVED" if shares is not None else "UNAVAILABLE"
    if shares is None and market_cap is not None and price not in (None, 0):
        shares = market_cap / price
        shares_status = "DERIVED"

    cash = _first_number(
        _first_scalar(balance, "total_cash", "cash"),
        _first_scalar(info, "totalCash"),
        _statement_value(balance_sheet, ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents", "Cash"]),
    )
    debt = _first_number(
        _first_scalar(balance, "total_debt", "debt"),
        _first_scalar(info, "totalDebt"),
        _statement_value(balance_sheet, ["Total Debt", "Long Term Debt And Capital Lease Obligation", "Long Term Debt"]),
    )
    revenue = _first_number(
        _first_scalar(growth, "revenue_ttm", "revenue"),
        _first_scalar(info, "totalRevenue"),
        _statement_value(financials, ["Total Revenue", "Operating Revenue"]),
    )
    ebitda = _first_number(
        _first_scalar(profitability, "ebitda"),
        _first_scalar(info, "ebitda"),
        _statement_value(financials, ["EBITDA", "Normalized EBITDA"]),
    )
    ebit = _first_number(
        _first_scalar(info, "ebit"),
        _statement_value(financials, ["EBIT", "Operating Income"]),
    )
    net_income = _first_number(
        _first_scalar(growth, "latest_net_income", "net_income"),
        _first_scalar(info, "netIncomeToCommon"),
        _statement_value(financials, ["Net Income", "Net Income Common Stockholders"]),
    )
    free_cash_flow = _first_number(
        _first_scalar(growth, "latest_free_cash_flow", "free_cash_flow"),
        _first_scalar(balance, "free_cash_flow"),
        _first_scalar(info, "freeCashflow"),
        _statement_value(cashflow, ["Free Cash Flow"]),
    )
    depreciation = _first_number(
        _statement_value(cashflow, ["Depreciation And Amortization", "Depreciation Amortization Depletion"]),
        _statement_value(financials, ["Reconciled Depreciation"]),
    )
    capex = _first_number(_statement_value(cashflow, ["Capital Expenditure", "Capital Expenditures"]))
    if capex is not None:
        capex = abs(capex)
    change_nwc = _first_number(_statement_value(cashflow, ["Change In Working Capital", "Change In Net Working Capital"]))
    book_value_per_share = _first_number(_first_scalar(info, "bookValue"))
    book_equity = _first_number(
        _statement_value(balance_sheet, ["Stockholders Equity", "Total Stockholder Equity", "Common Stock Equity"]),
        book_value_per_share * shares if book_value_per_share is not None and shares is not None else None,
    )

    if market_cap is None and price is not None and shares is not None:
        market_cap = price * shares
        market_cap_status = "DERIVED"
    else:
        market_cap_status = "OBSERVED" if market_cap is not None else "UNAVAILABLE"

    ev_bridge = enterprise_value_bridge(market_cap, debt, cash)
    observed_ev = _first_number(
        _first_scalar(profile, "enterprise_value", "enterpriseValue"),
        _first_scalar(valuation, "enterprise_value", "enterpriseValue"),
        _first_scalar(info, "enterpriseValue"),
    )
    derived_ev = _finite(ev_bridge.get("enterprise_value"))
    enterprise_value = observed_ev if observed_ev is not None else derived_ev
    enterprise_value_status = "OBSERVED" if observed_ev is not None else "DERIVED" if derived_ev is not None else "UNAVAILABLE"

    eps = _first_number(
        _first_scalar(info, "trailingEps", "epsTrailingTwelveMonths"),
        net_income / shares if net_income is not None and shares not in (None, 0) else None,
    )
    currency = str(_first_scalar(profile, "currency") or _first_scalar(info, "currency", "financialCurrency") or "USD")
    critical = {
        "Price": (price, "OBSERVED" if price is not None else "UNAVAILABLE", "Market snapshot"),
        "Diluted shares": (shares, shares_status, "Issuer/provider or market-cap bridge"),
        "Market capitalization": (market_cap, market_cap_status, "Provider or price × shares"),
        "Cash": (cash, "OBSERVED" if cash is not None else "UNAVAILABLE", "Latest balance sheet"),
        "Debt": (debt, "OBSERVED" if debt is not None else "UNAVAILABLE", "Latest balance sheet"),
        "Revenue": (revenue, "OBSERVED" if revenue is not None else "UNAVAILABLE", "TTM/latest financials"),
        "EBITDA": (ebitda, "OBSERVED" if ebitda is not None else "UNAVAILABLE", "TTM/latest financials"),
        "Net income": (net_income, "OBSERVED" if net_income is not None else "UNAVAILABLE", "TTM/latest financials"),
        "Free cash flow": (free_cash_flow, "OBSERVED" if free_cash_flow is not None else "UNAVAILABLE", "TTM/latest cash flow"),
    }
    status_weight = {"OBSERVED": 1.0, "DERIVED": 0.8, "ASSUMPTION": 0.45, "UNAVAILABLE": 0.0}
    coverage = 100.0 * sum(status_weight[state] for _, state, _ in critical.values()) / len(critical)
    evidence = pd.DataFrame(
        [
            {"Field": field, "Value": value, "Status": state, "Source / transformation": source, "Critical": True}
            for field, (value, state, source) in critical.items()
        ]
    )

    return {
        "ticker": str(ticker or _first_scalar(profile, "symbol") or "N/A").upper().strip(),
        "name": str(_first_scalar(profile, "name", "long_name") or _first_scalar(info, "longName", "shortName") or ticker),
        "sector": str(_first_scalar(profile, "sector") or _first_scalar(info, "sector") or "Not reported"),
        "industry": str(_first_scalar(profile, "industry") or _first_scalar(info, "industry") or "Not reported"),
        "country": str(_first_scalar(profile, "country") or _first_scalar(info, "country") or "Not reported"),
        "website": str(_first_scalar(profile, "website") or _first_scalar(info, "website") or ""),
        "summary": str(_first_scalar(profile, "summary") or _first_scalar(info, "longBusinessSummary") or "Business description unavailable."),
        "currency": currency,
        "price": price,
        "shares": shares,
        "market_cap": market_cap,
        "enterprise_value": enterprise_value,
        "observed_enterprise_value": observed_ev,
        "derived_enterprise_value": derived_ev,
        "ev_reconciliation_gap": observed_ev - derived_ev if observed_ev is not None and derived_ev is not None else None,
        "cash": cash,
        "debt": debt,
        "net_debt": debt - cash if debt is not None and cash is not None else None,
        "revenue": revenue,
        "ebitda": ebitda,
        "ebit": ebit,
        "net_income": net_income,
        "free_cash_flow": free_cash_flow,
        "depreciation": depreciation,
        "capex": capex,
        "change_nwc": change_nwc,
        "book_equity": book_equity,
        "eps": eps,
        "revenue_growth": _first_number(_first_scalar(growth, "revenue_growth_yoy", "annual_revenue_growth"), _first_scalar(forward, "revenue_growth_forward")),
        "ebitda_margin": _first_number(_first_scalar(profitability, "ebitda_margin"), ebitda / revenue if ebitda is not None and revenue not in (None, 0) else None),
        "operating_margin": _first_number(_first_scalar(profitability, "operating_margin"), ebit / revenue if ebit is not None and revenue not in (None, 0) else None),
        # Keep the displayed ratio on the same normalized period/basis as the
        # numerator and denominator shown in this workbench. Provider ratios can
        # silently mix TTM and last-fiscal-year values.
        "fcf_margin": _first_number(free_cash_flow / revenue if free_cash_flow is not None and revenue not in (None, 0) else None, _first_scalar(balance, "fcf_margin")),
        "trailing_pe": _first_number(_first_scalar(valuation, "trailing_pe"), _first_scalar(info, "trailingPE")),
        "forward_pe": _first_number(_first_scalar(valuation, "forward_pe"), _first_scalar(info, "forwardPE")),
        "ev_to_revenue": _first_number(_first_scalar(valuation, "ev_to_revenue"), enterprise_value / revenue if enterprise_value is not None and revenue not in (None, 0) else None),
        "ev_to_ebitda": _first_number(_first_scalar(valuation, "ev_to_ebitda"), enterprise_value / ebitda if enterprise_value is not None and ebitda not in (None, 0) else None),
        "coverage": round(coverage, 1),
        "evidence": evidence,
        "company": company,
        "raw_frames": {"Income statement": financials, "Balance sheet": balance_sheet, "Cash flow": cashflow},
        "enterprise_bridge": ev_bridge,
        "enterprise_value_status": enterprise_value_status,
    }


def synergy_npv(
    *,
    cost_synergy_run_rate: Any,
    revenue_synergy_run_rate: Any,
    contribution_margin: Any,
    tax_rate: Any,
    integration_cost: Any,
    discount_rate: Any,
    probability: Any = 1.0,
    ramp: Sequence[float] = (0.25, 0.65, 1.0, 1.0, 0.85),
) -> dict[str, Any]:
    """Finite-horizon risk-adjusted synergy NPV with no hidden terminal value."""
    cost = _finite(cost_synergy_run_rate) or 0.0
    revenue = _finite(revenue_synergy_run_rate) or 0.0
    margin = _clip(contribution_margin, 0.0, 1.0, 0.0)
    tax = _clip(tax_rate, 0.0, 0.60, 0.21)
    integration = max(0.0, _finite(integration_cost) or 0.0)
    discount = _finite(discount_rate)
    probability_value = _clip(probability, 0.0, 1.0, 1.0)
    if discount is None or discount <= -1:
        return {"status": "BLOCKED", "npv": None, "cash_flows": []}
    normalized_ramp = [max(0.0, min(1.0, _finite(x) or 0.0)) for x in ramp]
    cash_flows: list[float] = []
    schedule_rows: list[dict[str, float]] = []
    npv = -integration
    pre_tax_run_rate = cost + revenue * margin
    for year, factor in enumerate(normalized_ramp, start=1):
        cost_contribution = cost * factor
        revenue_contribution = revenue * margin * factor
        pre_tax_cash_flow = cost_contribution + revenue_contribution
        cash_flow = pre_tax_cash_flow * probability_value * (1.0 - tax)
        discount_factor = (1.0 + discount) ** year
        present_value = cash_flow / discount_factor
        cash_flows.append(cash_flow)
        npv += present_value
        schedule_rows.append(
            {
                "Year": float(year),
                "Ramp": factor,
                "Cost synergy contribution": cost_contribution,
                "Revenue synergy contribution": revenue_contribution,
                "Pre-tax synergy": pre_tax_cash_flow,
                "Probability": probability_value,
                "After-tax risk-adjusted FCF": cash_flow,
                "Discount factor": discount_factor,
                "Present value": present_value,
            }
        )
    return {
        "status": "READY_FOR_HUMAN_REVIEW",
        "npv": npv,
        "cash_flows": cash_flows,
        "schedule": pd.DataFrame(schedule_rows),
        "integration_cost": integration,
        "pre_tax_run_rate": pre_tax_run_rate,
        "probability": probability_value,
        "horizon_years": len(normalized_ramp),
    }


def target_deal_case(facts: Mapping[str, Any], assumptions: Mapping[str, Any]) -> dict[str, Any]:
    """Value the current company as a hypothetical target under explicit assumptions."""
    market_cap = _finite(facts.get("market_cap"))
    debt = _finite(facts.get("debt"))
    cash = _finite(facts.get("cash"))
    price = _finite(facts.get("price"))
    shares = _finite(facts.get("shares"))
    missing = [name for name, value in (("market_cap", market_cap), ("debt", debt), ("cash", cash)) if value is None]
    if missing:
        return {"status": "BLOCKED", "missing": missing, "publishable": False}

    premium = _clip(assumptions.get("premium"), -0.95, 5.0, 0.0)
    offer_equity = market_cap * (1.0 + premium)
    bridge = enterprise_value_bridge(
        offer_equity,
        debt,
        cash,
        preferred=assumptions.get("preferred", 0.0),
        minority_interest=assumptions.get("minority_interest", 0.0),
        lease_liabilities=assumptions.get("lease_liabilities", 0.0),
        unfunded_pensions=assumptions.get("unfunded_pensions", 0.0),
        non_operating_investments=assumptions.get("non_operating_investments", 0.0),
    )
    transaction_ev = _finite(bridge.get("enterprise_value"))
    synergy = synergy_npv(
        cost_synergy_run_rate=assumptions.get("cost_synergy_run_rate", 0.0),
        revenue_synergy_run_rate=assumptions.get("revenue_synergy_run_rate", 0.0),
        contribution_margin=assumptions.get("contribution_margin", 0.0),
        tax_rate=assumptions.get("tax_rate", 0.21),
        integration_cost=assumptions.get("integration_cost", 0.0),
        discount_rate=assumptions.get("discount_rate", 0.10),
        probability=assumptions.get("synergy_probability", 1.0),
        ramp=assumptions.get("synergy_ramp", (0.25, 0.65, 1.0, 1.0, 0.85)),
    )
    synergy_value = _finite(synergy.get("npv"))
    premium_dollars = offer_equity - market_cap
    revenue = _finite(facts.get("revenue"))
    ebitda = _finite(facts.get("ebitda"))
    ebit = _finite(facts.get("ebit"))
    net_income = _finite(facts.get("net_income"))
    free_cash_flow = _finite(facts.get("free_cash_flow"))
    synergy_run_rate = _finite(synergy.get("pre_tax_run_rate")) or 0.0
    post_synergy_ebitda = ebitda + synergy_run_rate if ebitda is not None else None
    metrics = {
        "offer_price": price * (1.0 + premium) if price is not None else None,
        "offer_equity_value": offer_equity,
        "transaction_ev": transaction_ev,
        "premium": premium,
        "premium_dollars": premium_dollars,
        "ev_revenue": transaction_ev / revenue if transaction_ev is not None and revenue not in (None, 0) else None,
        "ev_ebitda": transaction_ev / ebitda if transaction_ev is not None and ebitda not in (None, 0) else None,
        "ev_ebit": transaction_ev / ebit if transaction_ev is not None and ebit not in (None, 0) else None,
        "price_earnings": offer_equity / net_income if net_income not in (None, 0) else None,
        "fcf_yield": free_cash_flow / offer_equity if free_cash_flow is not None and offer_equity > 0 else None,
        "synergy_npv": synergy_value,
        "seller_capture": premium_dollars / synergy_value if synergy_value not in (None, 0) else None,
        "buyer_retained_value": synergy_value - premium_dollars if synergy_value is not None else None,
        "post_synergy_ev_ebitda": transaction_ev / post_synergy_ebitda if transaction_ev is not None and post_synergy_ebitda is not None and post_synergy_ebitda > 0 else None,
    }
    coverage = _finite(facts.get("coverage")) or 0.0
    return {
        "status": "READY_FOR_HUMAN_REVIEW" if coverage >= 85 else "LIMITED",
        "missing": [],
        "publishable": coverage >= 85 and transaction_ev is not None,
        "coverage": coverage,
        "bridge": bridge,
        "synergy": synergy,
        **metrics,
    }


def dcf_valuation(facts: Mapping[str, Any], assumptions: Mapping[str, Any]) -> dict[str, Any]:
    """Five-year FCF-proxy DCF with an explicit Gordon-growth terminal value."""
    base_fcf = _finite(assumptions.get("base_fcf"))
    shares = _finite(facts.get("shares"))
    debt = _finite(facts.get("debt"))
    cash = _finite(facts.get("cash"))
    wacc = _finite(assumptions.get("wacc"))
    terminal_growth = _finite(assumptions.get("terminal_growth"))
    initial_growth = _finite(assumptions.get("initial_growth"))
    years = max(3, min(10, int(_finite(assumptions.get("years")) or 5)))
    if base_fcf is None or base_fcf <= 0:
        return {"status": "BLOCKED", "reason": "Positive base FCF is required.", "value_per_share": None}
    if shares in (None, 0) or debt is None or cash is None:
        return {"status": "BLOCKED", "reason": "Shares, debt and cash are required.", "value_per_share": None}
    if wacc is None or terminal_growth is None or initial_growth is None or wacc - terminal_growth < 0.0125:
        return {"status": "BLOCKED", "reason": "WACC must exceed terminal growth by at least 125 bps.", "value_per_share": None}

    forecasts: list[dict[str, float]] = []
    fcf = base_fcf
    pv_forecasts = 0.0
    for year in range(1, years + 1):
        growth = initial_growth if years == 1 else initial_growth + (terminal_growth - initial_growth) * (year - 1) / (years - 1)
        fcf *= 1.0 + growth
        discount_factor = (1.0 + wacc) ** year
        present_value = fcf / discount_factor
        forecasts.append({"Year": year, "Growth": growth, "FCF": fcf, "Present Value": present_value})
        pv_forecasts += present_value
    terminal_value = fcf * (1.0 + terminal_growth) / (wacc - terminal_growth)
    pv_terminal = terminal_value / ((1.0 + wacc) ** years)
    enterprise_value = pv_forecasts + pv_terminal
    equity_value = enterprise_value - debt + cash
    value_per_share = equity_value / shares
    terminal_share = pv_terminal / enterprise_value if enterprise_value else None
    return {
        "status": "READY_FOR_HUMAN_REVIEW",
        "reason": "FCF proxy; confirm unlevered cash-flow definition before IC use.",
        "enterprise_value": enterprise_value,
        "equity_value": equity_value,
        "value_per_share": value_per_share,
        "pv_forecasts": pv_forecasts,
        "pv_terminal": pv_terminal,
        "terminal_value_share": terminal_share,
        "forecast": pd.DataFrame(forecasts),
    }


def reverse_dcf_growth(facts: Mapping[str, Any], assumptions: Mapping[str, Any], *, low: float = -0.50, high: float = 1.50) -> float | None:
    """Solve the initial FCF growth required to recover the current share price."""
    target = _finite(facts.get("price"))
    if target is None or target <= 0:
        return None

    def difference(growth: float) -> float | None:
        result = dcf_valuation(facts, {**dict(assumptions), "initial_growth": growth})
        value = _finite(result.get("value_per_share"))
        return None if value is None else value - target

    lo_value, hi_value = difference(low), difference(high)
    if lo_value is None or hi_value is None or lo_value == 0:
        return low if lo_value == 0 else None
    if hi_value == 0:
        return high
    if lo_value * hi_value > 0:
        return None
    lo, hi = low, high
    for _ in range(80):
        mid = (lo + hi) / 2.0
        mid_value = difference(mid)
        if mid_value is None:
            return None
        if abs(mid_value) <= max(1e-10, target * 1e-10):
            return mid
        if lo_value * mid_value <= 0:
            hi = mid
        else:
            lo, lo_value = mid, mid_value
    return (lo + hi) / 2.0


def dcf_sensitivity_table(facts: Mapping[str, Any], assumptions: Mapping[str, Any]) -> pd.DataFrame:
    base_wacc = _finite(assumptions.get("wacc")) or 0.10
    base_terminal = _finite(assumptions.get("terminal_growth")) or 0.03
    waccs = [base_wacc + delta for delta in (-0.02, -0.01, 0.0, 0.01, 0.02)]
    growths = [base_terminal + delta for delta in (-0.01, -0.005, 0.0, 0.005, 0.01)]
    rows: list[dict[str, Any]] = []
    for wacc in waccs:
        row: dict[str, Any] = {"WACC": wacc}
        for growth in growths:
            result = dcf_valuation(facts, {**dict(assumptions), "wacc": wacc, "terminal_growth": growth})
            row[f"g {growth:.1%}"] = _finite(result.get("value_per_share"))
        rows.append(row)
    return pd.DataFrame(rows)


def relative_valuation_ranges(facts: Mapping[str, Any], peer_table: pd.DataFrame) -> pd.DataFrame:
    """Calculate implied target values from peer quartiles under the same metric basis."""
    if not isinstance(peer_table, pd.DataFrame) or peer_table.empty:
        return pd.DataFrame()
    peers = peer_table.copy()
    if "Peer Type" in peers.columns:
        peers = peers[peers["Peer Type"].ne("Target")]
    if peers.empty:
        return pd.DataFrame()

    debt, cash, shares, price = (_finite(facts.get(key)) for key in ("debt", "cash", "shares", "price"))
    methods = {
        "EV/Revenue": ("EV/Sales", _finite(facts.get("revenue")), "EV"),
        "EV/EBITDA": ("EV/EBITDA", _finite(facts.get("ebitda")), "EV"),
        "P/E": ("P/E TTM", _finite(facts.get("net_income")), "Equity"),
    }
    rows: list[dict[str, Any]] = []
    for method, (column, denominator, basis) in methods.items():
        if column not in peers.columns or denominator in (None, 0) or shares in (None, 0):
            continue
        values = pd.to_numeric(peers[column], errors="coerce").dropna()
        values = values[values > 0]
        if len(values) < 4:
            continue
        for label, quantile in (("25th", 0.25), ("Median", 0.50), ("75th", 0.75)):
            reference = float(values.quantile(quantile))
            implied_value = denominator * reference
            if basis == "EV":
                implied_ev = implied_value
                implied_equity = implied_ev - debt + cash if debt is not None and cash is not None else None
            else:
                implied_equity = implied_value
                implied_ev = implied_equity + debt - cash if debt is not None and cash is not None else None
            implied_price = implied_equity / shares if implied_equity is not None else None
            rows.append(
                {
                    "Method": method,
                    "Statistic": label,
                    "Reference multiple": reference,
                    "Implied EV": implied_ev,
                    "Implied equity": implied_equity,
                    "Implied price": implied_price,
                    "Upside / downside": implied_price / price - 1 if implied_price is not None and price not in (None, 0) else None,
                    "Valid peers": int(len(values)),
                }
            )
    return pd.DataFrame(rows)


def accretion_dilution_case(
    acquirer: Mapping[str, Any], target: Mapping[str, Any], assumptions: Mapping[str, Any]
) -> dict[str, Any]:
    """Simplified recurring and year-one EPS/FCF transaction model."""
    required_acquirer = {key: _finite(acquirer.get(key)) for key in ("price", "shares", "net_income", "ebitda", "debt", "cash")}
    required_target = {key: _finite(target.get(key)) for key in ("equity_value", "debt", "cash", "net_income", "ebitda")}
    missing = [f"acquirer.{key}" for key, value in required_acquirer.items() if value is None]
    missing += [f"target.{key}" for key, value in required_target.items() if value is None]
    if missing:
        return {"status": "BLOCKED", "missing": missing, "publishable": False}

    weights = {
        "cash": max(0.0, _finite(assumptions.get("cash_pct")) or 0.0),
        "debt": max(0.0, _finite(assumptions.get("debt_pct")) or 0.0),
        "stock": max(0.0, _finite(assumptions.get("stock_pct")) or 0.0),
    }
    total_weight = sum(weights.values())
    if total_weight <= 0:
        return {"status": "BLOCKED", "missing": ["financing_mix"], "publishable": False}
    if abs(total_weight - 1.0) > 1e-6:
        return {
            "status": "BLOCKED",
            "missing": ["financing_mix_total"],
            "publishable": False,
            "financing_mix_total": total_weight,
        }
    equity_value = required_target["equity_value"]
    debt_refinanced = min(required_target["debt"], max(0.0, _finite(assumptions.get("debt_refinanced")) or 0.0))
    transaction_fees = max(0.0, _finite(assumptions.get("transaction_fees")) or 0.0)
    other_uses = max(0.0, _finite(assumptions.get("other_uses")) or 0.0)
    total_uses = equity_value + debt_refinanced + transaction_fees + other_uses
    funding = {key: total_uses * weight for key, weight in weights.items()}
    total_sources = sum(funding.values())
    sources_uses_gap = total_sources - total_uses

    tax = _clip(assumptions.get("tax_rate"), 0.0, 0.60, 0.21)
    interest_rate = max(0.0, _finite(assumptions.get("debt_interest_rate")) or 0.0)
    cash_yield = max(0.0, _finite(assumptions.get("cash_yield")) or 0.0)
    synergies = _finite(assumptions.get("pre_tax_synergies")) or 0.0
    amortization = max(0.0, _finite(assumptions.get("incremental_amortization")) or 0.0)
    integration = max(0.0, _finite(assumptions.get("integration_cost")) or 0.0)

    new_shares = funding["stock"] / required_acquirer["price"] if required_acquirer["price"] else None
    proforma_shares = required_acquirer["shares"] + (new_shares or 0.0)
    standalone_eps = required_acquirer["net_income"] / required_acquirer["shares"] if required_acquirer["shares"] else None
    after_tax_synergy = synergies * (1.0 - tax)
    after_tax_interest = funding["debt"] * interest_rate * (1.0 - tax)
    after_tax_cash_drag = funding["cash"] * cash_yield * (1.0 - tax)
    after_tax_amortization = amortization * (1.0 - tax)
    recurring_ni = (
        required_acquirer["net_income"]
        + required_target["net_income"]
        + after_tax_synergy
        - after_tax_interest
        - after_tax_cash_drag
        - after_tax_amortization
    )
    year_one_ni = recurring_ni - integration * (1.0 - tax)
    recurring_eps = recurring_ni / proforma_shares if proforma_shares else None
    year_one_eps = year_one_ni / proforma_shares if proforma_shares else None
    eps_accretion = recurring_eps / standalone_eps - 1 if standalone_eps not in (None, 0) and standalone_eps > 0 else None
    year_one_accretion = year_one_eps / standalone_eps - 1 if standalone_eps not in (None, 0) and standalone_eps > 0 else None

    acquirer_fcf = _finite(acquirer.get("free_cash_flow"))
    target_fcf = _finite(target.get("free_cash_flow"))
    standalone_fcf_share = acquirer_fcf / required_acquirer["shares"] if acquirer_fcf is not None else None
    recurring_fcf = None
    recurring_fcf_share = None
    fcf_accretion = None
    if acquirer_fcf is not None and target_fcf is not None:
        recurring_fcf = acquirer_fcf + target_fcf + after_tax_synergy - after_tax_interest - after_tax_cash_drag
        recurring_fcf_share = recurring_fcf / proforma_shares if proforma_shares else None
        if standalone_fcf_share not in (None, 0):
            fcf_accretion = recurring_fcf_share / standalone_fcf_share - 1

    pf_gross_debt = required_acquirer["debt"] + (required_target["debt"] - debt_refinanced) + funding["debt"]
    pf_cash = max(0.0, required_acquirer["cash"] + required_target["cash"] - funding["cash"])
    pf_net_debt = pf_gross_debt - pf_cash
    pf_ebitda_reported = required_acquirer["ebitda"] + required_target["ebitda"]
    pf_ebitda_adjusted = pf_ebitda_reported + synergies
    leverage_reported = pf_net_debt / pf_ebitda_reported if pf_ebitda_reported > 0 else None
    leverage_adjusted = pf_net_debt / pf_ebitda_adjusted if pf_ebitda_adjusted > 0 else None
    target_ev = equity_value + required_target["debt"] - required_target["cash"]
    acquirer_market_cap = _finite(acquirer.get("market_cap"))
    transaction_to_market_cap = equity_value / acquirer_market_cap if acquirer_market_cap not in (None, 0) else None
    target_ownership = (new_shares or 0.0) / proforma_shares if proforma_shares else None
    identity_tolerance = max(1.0, 1e-6 * abs(total_uses))
    identity_ok = abs(sources_uses_gap) <= identity_tolerance
    cash_available = max(0.0, _finite(assumptions.get("cash_available")) if _finite(assumptions.get("cash_available")) is not None else required_acquirer["cash"])
    cash_shortfall = max(0.0, funding["cash"] - cash_available)
    liquidity_ok = cash_shortfall <= identity_tolerance
    hard_failures = []
    if not identity_ok:
        hard_failures.append("sources_uses_identity")
    if not liquidity_ok:
        hard_failures.append("cash_funding_capacity")
    return {
        "status": "READY_FOR_HUMAN_REVIEW" if identity_ok and liquidity_ok else "BLOCKED",
        "publishable": identity_ok and liquidity_ok,
        "missing": hard_failures,
        "weights": weights,
        "funding": funding,
        "uses": {
            "equity_purchase_price": equity_value,
            "target_debt_refinanced": debt_refinanced,
            "transaction_fees": transaction_fees,
            "other_uses": other_uses,
        },
        "total_sources": total_sources,
        "total_uses": total_uses,
        "sources_uses_gap": sources_uses_gap,
        "cash_available": cash_available,
        "cash_shortfall": cash_shortfall,
        "liquidity_ok": liquidity_ok,
        "target_ev": target_ev,
        "new_shares": new_shares,
        "proforma_shares": proforma_shares,
        "standalone_eps": standalone_eps,
        "recurring_net_income": recurring_ni,
        "year_one_net_income": year_one_ni,
        "after_tax_synergy": after_tax_synergy,
        "after_tax_interest": after_tax_interest,
        "after_tax_cash_drag": after_tax_cash_drag,
        "after_tax_amortization": after_tax_amortization,
        "after_tax_integration": integration * (1.0 - tax),
        "recurring_eps": recurring_eps,
        "year_one_eps": year_one_eps,
        "eps_accretion": eps_accretion,
        "year_one_eps_accretion": year_one_accretion,
        "standalone_fcf_per_share": standalone_fcf_share,
        "recurring_fcf_per_share": recurring_fcf_share,
        "recurring_free_cash_flow": recurring_fcf,
        "fcf_accretion": fcf_accretion,
        "pf_gross_debt": pf_gross_debt,
        "pf_cash": pf_cash,
        "pf_net_debt": pf_net_debt,
        "pf_ebitda_reported": pf_ebitda_reported,
        "pf_ebitda_adjusted": pf_ebitda_adjusted,
        "net_leverage_reported": leverage_reported,
        "net_leverage_adjusted": leverage_adjusted,
        "target_seller_ownership": target_ownership,
        "deal_to_acquirer_market_cap": transaction_to_market_cap,
    }


def simplified_ppa(
    *,
    consideration: Any,
    target_book_equity: Any,
    existing_goodwill: Any = 0.0,
    identifiable_intangibles_step_up: Any = 0.0,
    ppe_step_up: Any = 0.0,
    inventory_step_up: Any = 0.0,
    liability_step_up: Any = 0.0,
    tax_rate: Any = 0.21,
    intangible_life_years: Any = 10.0,
) -> dict[str, Any]:
    """Research-only PPA bridge; not an audited ASC 805 / IFRS 3 allocation."""
    consideration_value = _finite(consideration)
    book_equity = _finite(target_book_equity)
    if consideration_value is None or book_equity is None:
        return {"status": "BLOCKED", "goodwill": None}
    existing = max(0.0, _finite(existing_goodwill) or 0.0)
    intangibles = max(0.0, _finite(identifiable_intangibles_step_up) or 0.0)
    ppe = _finite(ppe_step_up) or 0.0
    inventory = _finite(inventory_step_up) or 0.0
    liabilities = max(0.0, _finite(liability_step_up) or 0.0)
    tax = _clip(tax_rate, 0.0, 0.60, 0.21)
    taxable_step_up = max(0.0, intangibles + ppe + inventory - liabilities)
    deferred_tax_liability = taxable_step_up * tax
    fair_value_net_assets = book_equity - existing + intangibles + ppe + inventory - liabilities - deferred_tax_liability
    goodwill = consideration_value - fair_value_net_assets
    life = max(1.0, _finite(intangible_life_years) or 10.0)
    annual_amortization = intangibles / life
    status = "BARGAIN_PURCHASE_REVIEW" if goodwill < 0 else "PROVISIONAL_ASSUMPTION"
    return {
        "status": status,
        "fair_value_net_assets": fair_value_net_assets,
        "deferred_tax_liability": deferred_tax_liability,
        "goodwill": goodwill,
        "annual_intangible_amortization": annual_amortization,
    }


def screening_gates(facts: Mapping[str, Any]) -> pd.DataFrame:
    ebitda = _finite(facts.get("ebitda"))
    net_debt = _finite(facts.get("net_debt"))
    leverage = net_debt / ebitda if ebitda not in (None, 0) and ebitda > 0 and net_debt is not None else None
    rows = [
        ("Capital structure", facts.get("market_cap") is not None and facts.get("debt") is not None and facts.get("cash") is not None, "Equity, debt and cash bridge"),
        ("Earnings base", facts.get("revenue") is not None and ebitda is not None, "Revenue and EBITDA available"),
        ("Cash conversion", facts.get("free_cash_flow") is not None, "Reported/derived free cash flow"),
        ("Share count", facts.get("shares") is not None, "Observed or explicitly derived shares"),
        ("Evidence coverage", (_finite(facts.get("coverage")) or 0.0) >= 85, f"{_finite(facts.get('coverage')) or 0.0:.0f}% versus 85% gate"),
        ("Balance-sheet pressure", leverage is not None and leverage <= 3.0, "N/A" if leverage is None else f"Net debt / EBITDA {leverage:.2f}x"),
    ]
    return pd.DataFrame(
        [{"Gate": gate, "State": "PASS" if passed else "BLOCKED", "Evidence": evidence} for gate, passed, evidence in rows]
    )


def filter_peer_universe(
    peer_table: pd.DataFrame,
    selected_symbols: Sequence[str] | None,
    *,
    exclusion_rationale: str = "",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return an immutable peer subset and an explicit inclusion/exclusion audit."""
    if not isinstance(peer_table, pd.DataFrame) or peer_table.empty:
        return pd.DataFrame(), pd.DataFrame()
    peers = peer_table.copy(deep=True)
    symbol_column = next((column for column in ("Symbol", "symbol", "Ticker", "ticker") if column in peers.columns), None)
    if symbol_column is None:
        return peers, pd.DataFrame()
    selected = None if selected_symbols is None else {str(value).upper().strip() for value in selected_symbols}
    rows: list[dict[str, Any]] = []
    keep_mask: list[bool] = []
    for _, row in peers.iterrows():
        symbol = str(row.get(symbol_column) or "").upper().strip()
        is_target = str(row.get("Peer Type") or "").lower() == "target"
        included = is_target or selected is None or symbol in selected
        keep_mask.append(included)
        rows.append(
            {
                "Symbol": symbol,
                "Peer type": row.get("Peer Type", "Peer"),
                "Decision": "INCLUDED" if included else "EXCLUDED",
                "Rationale": "Target retained" if is_target else "Selected comparable" if included else exclusion_rationale.strip() or "RATIONALE REQUIRED",
            }
        )
    return peers.loc[keep_mask].reset_index(drop=True), pd.DataFrame(rows)


def build_scenario_comparison(facts: Mapping[str, Any]) -> pd.DataFrame:
    """Build linked Bear/Base/Bull deal and standalone valuation cases."""
    base_growth = _clip(facts.get("revenue_growth"), -0.20, 0.45, 0.08)
    base_fcf = max(0.0, _finite(facts.get("free_cash_flow")) or 0.0)
    revenue = max(0.0, _finite(facts.get("revenue")) or 0.0)
    ebitda = max(0.0, _finite(facts.get("ebitda")) or 0.0)
    price = _finite(facts.get("price"))
    rows: list[dict[str, Any]] = []
    for name, profile in SCENARIO_PROFILES.items():
        target = target_deal_case(
            facts,
            {
                "premium": profile["premium"],
                "discount_rate": profile["synergy_discount_rate"],
                "tax_rate": 0.21,
                "synergy_probability": profile["synergy_probability"],
                "cost_synergy_run_rate": ebitda * profile["cost_synergy_pct_ebitda"],
                "revenue_synergy_run_rate": revenue * profile["revenue_synergy_pct_revenue"],
                "contribution_margin": profile["revenue_synergy_margin"],
                "integration_cost": ebitda * profile["integration_pct_ebitda"],
            },
        )
        dcf = dcf_valuation(
            facts,
            {
                "base_fcf": base_fcf,
                "initial_growth": _clip(base_growth + profile["dcf_growth_adjustment"], -0.50, 1.50, base_growth),
                "wacc": profile["wacc"],
                "terminal_growth": profile["terminal_growth"],
                "years": 5,
            },
        )
        dcf_price = _finite(dcf.get("value_per_share"))
        rows.append(
            {
                "Scenario": name,
                "Offer premium": profile["premium"],
                "Offer price": target.get("offer_price"),
                "Transaction EV": target.get("transaction_ev"),
                "EV / EBITDA": target.get("ev_ebitda"),
                "Synergy confidence": profile["synergy_probability"],
                "Synergy NPV": target.get("synergy_npv"),
                "Buyer retained value": target.get("buyer_retained_value"),
                "DCF value / share": dcf_price,
                "DCF upside / downside": dcf_price / price - 1 if dcf_price is not None and price not in (None, 0) else None,
                "WACC": profile["wacc"],
                "Terminal growth": profile["terminal_growth"],
                "Review state": target.get("status"),
            }
        )
    return pd.DataFrame(rows)


def build_acquirer_scenario_comparison(
    acquirer: Mapping[str, Any],
    target: Mapping[str, Any],
    base_assumptions: Mapping[str, Any],
) -> pd.DataFrame:
    """Stress a live acquirer case across explicit Bear/Base/Bull profiles."""
    earnings_factors = {"Bear": 0.80, "Base": 1.00, "Bull": 1.10}
    ebitda_factors = {"Bear": 0.90, "Base": 1.00, "Bull": 1.10}
    rate_adjustments = {"Bear": 0.020, "Base": 0.0, "Bull": -0.010}
    base_rate = max(0.0, _finite(base_assumptions.get("debt_interest_rate")) or 0.0)
    target_ebitda = _finite(target.get("ebitda")) or 0.0
    rows: list[dict[str, Any]] = []
    for name, profile in SCENARIO_PROFILES.items():
        stressed_target = dict(target)
        for field in ("net_income", "free_cash_flow"):
            value = _finite(target.get(field))
            stressed_target[field] = value * earnings_factors[name] if value is not None else value
        stressed_target["ebitda"] = target_ebitda * ebitda_factors[name]
        cash_pct = profile["cash_pct"]
        debt_pct = profile["debt_pct"]
        assumptions = {
            **dict(base_assumptions),
            "cash_pct": cash_pct,
            "debt_pct": debt_pct,
            "stock_pct": 1.0 - cash_pct - debt_pct,
            "pre_tax_synergies": target_ebitda * profile["run_rate_synergy_pct_target_ebitda"],
            "debt_interest_rate": max(0.0, base_rate + rate_adjustments[name]),
        }
        result = accretion_dilution_case(acquirer, stressed_target, assumptions)
        rows.append(
            {
                "Scenario": name,
                "Target earnings factor": earnings_factors[name],
                "Target EBITDA factor": ebitda_factors[name],
                "Cash funding": cash_pct,
                "Debt funding": debt_pct,
                "Stock funding": 1.0 - cash_pct - debt_pct,
                "Debt cost": assumptions["debt_interest_rate"],
                "Run-rate synergies": assumptions["pre_tax_synergies"],
                "Recurring EPS accretion": result.get("eps_accretion"),
                "Year-one EPS accretion": result.get("year_one_eps_accretion"),
                "FCF/share accretion": result.get("fcf_accretion"),
                "Net leverage": result.get("net_leverage_reported"),
                "Synergy-adjusted leverage": result.get("net_leverage_adjusted"),
                "Cash shortfall": result.get("cash_shortfall"),
                "Review state": result.get("status"),
            }
        )
    return pd.DataFrame(rows)


def validate_deal_identities(
    acquirer: Mapping[str, Any],
    target: Mapping[str, Any],
    result: Mapping[str, Any],
) -> pd.DataFrame:
    """Recompute the hard accounting identities exposed by the deal model."""
    funding = _mapping(result.get("funding"))
    price = _finite(acquirer.get("price"))
    acquirer_shares = _finite(acquirer.get("shares"))
    target_net_income = _finite(target.get("net_income"))
    expected_recurring_ni = None
    if _finite(acquirer.get("net_income")) is not None and target_net_income is not None:
        expected_recurring_ni = (
            (_finite(acquirer.get("net_income")) or 0.0)
            + target_net_income
            + (_finite(result.get("after_tax_synergy")) or 0.0)
            - (_finite(result.get("after_tax_interest")) or 0.0)
            - (_finite(result.get("after_tax_cash_drag")) or 0.0)
            - (_finite(result.get("after_tax_amortization")) or 0.0)
        )
    identities = [
        ("Sources = uses", _finite(result.get("total_uses")), _finite(result.get("total_sources"))),
        (
            "Stock proceeds = new shares × price",
            _finite(funding.get("stock")),
            (_finite(result.get("new_shares")) or 0.0) * price if price is not None else None,
        ),
        (
            "Share roll-forward",
            (acquirer_shares or 0.0) + (_finite(result.get("new_shares")) or 0.0) if acquirer_shares is not None else None,
            _finite(result.get("proforma_shares")),
        ),
        ("Recurring net-income bridge", expected_recurring_ni, _finite(result.get("recurring_net_income"))),
        (
            "Year-one net-income bridge",
            expected_recurring_ni - (_finite(result.get("after_tax_integration")) or 0.0) if expected_recurring_ni is not None else None,
            _finite(result.get("year_one_net_income")),
        ),
        (
            "Net debt = gross debt − cash",
            (_finite(result.get("pf_gross_debt")) or 0.0) - (_finite(result.get("pf_cash")) or 0.0),
            _finite(result.get("pf_net_debt")),
        ),
        (
            "Reported EBITDA bridge",
            (_finite(acquirer.get("ebitda")) or 0.0) + (_finite(target.get("ebitda")) or 0.0),
            _finite(result.get("pf_ebitda_reported")),
        ),
    ]
    rows: list[dict[str, Any]] = []
    for name, expected, actual in identities:
        gap = actual - expected if expected is not None and actual is not None else None
        tolerance = max(1e-8, 1e-8 * max(abs(expected or 0.0), abs(actual or 0.0), 1.0))
        rows.append(
            {
                "Identity": name,
                "Expected": expected,
                "Actual": actual,
                "Gap": gap,
                "Tolerance": tolerance,
                "State": "PASS" if gap is not None and abs(gap) <= tolerance else "BLOCKED",
            }
        )
    rows.append(
        {
            "Identity": "Cash funding capacity",
            "Expected": 0.0,
            "Actual": _finite(result.get("cash_shortfall")),
            "Gap": _finite(result.get("cash_shortfall")),
            "Tolerance": max(1.0, 1e-6 * abs(_finite(result.get("total_uses")) or 0.0)),
            "State": "PASS" if result.get("liquidity_ok") else "BLOCKED",
        }
    )
    return pd.DataFrame(rows)


def build_football_field(
    facts: Mapping[str, Any],
    peer_ranges: pd.DataFrame,
    scenario_comparison: pd.DataFrame,
    dcf_sensitivity: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Normalize comparable, DCF and control-premium outputs into price ranges."""
    rows: list[dict[str, Any]] = []
    if isinstance(peer_ranges, pd.DataFrame) and not peer_ranges.empty:
        for method, group in peer_ranges.groupby("Method", sort=False):
            points = {
                str(item.get("Statistic")): _finite(item.get("Implied price"))
                for _, item in group.iterrows()
            }
            if all(points.get(label) is not None for label in ("25th", "Median", "75th")):
                rows.append(
                    {
                        "Method": f"Peer {method}",
                        "Low": points["25th"],
                        "Mid": points["Median"],
                        "High": points["75th"],
                        "Evidence": "Current comparable-company quartiles",
                    }
                )
    if isinstance(dcf_sensitivity, pd.DataFrame) and not dcf_sensitivity.empty:
        values = pd.to_numeric(dcf_sensitivity.drop(columns=["WACC"], errors="ignore").stack(), errors="coerce").dropna()
        values = values[values > 0]
        if not values.empty:
            rows.append(
                {
                    "Method": "DCF sensitivity",
                    "Low": float(values.min()),
                    "Mid": float(values.median()),
                    "High": float(values.max()),
                    "Evidence": "Documented WACC × terminal-growth grid",
                }
            )
    if isinstance(scenario_comparison, pd.DataFrame) and not scenario_comparison.empty:
        lookup = {
            str(item.get("Scenario")): _finite(item.get("Offer price"))
            for _, item in scenario_comparison.iterrows()
        }
        if all(lookup.get(label) is not None for label in ("Bear", "Base", "Bull")):
            rows.append(
                {
                    "Method": "Control premium",
                    "Low": lookup["Bear"],
                    "Mid": lookup["Base"],
                    "High": lookup["Bull"],
                    "Evidence": "User-reviewable Bear / Base / Bull profiles",
                }
            )
    return pd.DataFrame(rows, columns=["Method", "Low", "Mid", "High", "Evidence"])


def build_sources_uses_bridge(target: Mapping[str, Any], result: Mapping[str, Any]) -> pd.DataFrame:
    """Build a waterfall-ready sources-and-uses identity without a hidden plug."""
    funding = _mapping(result.get("funding"))
    uses = _mapping(result.get("uses"))
    equity_value = _finite(uses.get("equity_purchase_price"))
    if equity_value is None:
        equity_value = _finite(target.get("equity_value")) or 0.0
    rows = [
        {"Item": "Target equity purchase price", "Side": "Use", "Amount": equity_value, "Bridge value": equity_value, "Measure": "relative"},
    ]
    for item, key in (
        ("Target debt refinancing", "target_debt_refinanced"),
        ("Transaction fees", "transaction_fees"),
        ("Other uses", "other_uses"),
    ):
        value = _finite(uses.get(key)) or 0.0
        if value:
            rows.append({"Item": item, "Side": "Use", "Amount": value, "Bridge value": value, "Measure": "relative"})
    rows.extend(
        [
            {"Item": "Acquirer cash", "Side": "Source", "Amount": _finite(funding.get("cash")) or 0.0, "Bridge value": -(_finite(funding.get("cash")) or 0.0), "Measure": "relative"},
            {"Item": "New debt", "Side": "Source", "Amount": _finite(funding.get("debt")) or 0.0, "Bridge value": -(_finite(funding.get("debt")) or 0.0), "Measure": "relative"},
            {"Item": "Stock consideration", "Side": "Source", "Amount": _finite(funding.get("stock")) or 0.0, "Bridge value": -(_finite(funding.get("stock")) or 0.0), "Measure": "relative"},
            {"Item": "Uses less sources", "Side": "Reconciliation", "Amount": -(_finite(result.get("sources_uses_gap")) or 0.0), "Bridge value": -(_finite(result.get("sources_uses_gap")) or 0.0), "Measure": "total"},
        ]
    )
    return pd.DataFrame(rows)


def build_eps_bridge(
    acquirer: Mapping[str, Any],
    target: Mapping[str, Any],
    result: Mapping[str, Any],
) -> pd.DataFrame:
    """Build an auditable net-income bridge underlying EPS accretion/dilution."""
    rows = [
        ("Acquirer standalone net income", _finite(acquirer.get("net_income")) or 0.0, "relative"),
        ("Target net income", _finite(target.get("net_income")) or 0.0, "relative"),
        ("After-tax synergies", _finite(result.get("after_tax_synergy")) or 0.0, "relative"),
        ("New debt interest", -(_finite(result.get("after_tax_interest")) or 0.0), "relative"),
        ("Foregone cash yield", -(_finite(result.get("after_tax_cash_drag")) or 0.0), "relative"),
        ("Incremental amortization", -(_finite(result.get("after_tax_amortization")) or 0.0), "relative"),
        ("Recurring pro forma net income", _finite(result.get("recurring_net_income")) or 0.0, "total"),
        ("Year-one integration cost", -(_finite(result.get("after_tax_integration")) or 0.0), "relative"),
        ("Year-one pro forma net income", _finite(result.get("year_one_net_income")) or 0.0, "total"),
    ]
    return pd.DataFrame([{"Item": item, "Value": value, "Measure": measure} for item, value, measure in rows])


def build_leverage_trajectory(
    result: Mapping[str, Any],
    *,
    annual_paydown: Any = None,
    years: int = 3,
) -> pd.DataFrame:
    """Illustrate deleveraging under an explicit annual debt-paydown assumption."""
    starting_debt = _finite(result.get("pf_net_debt"))
    reported_ebitda = _finite(result.get("pf_ebitda_reported"))
    adjusted_ebitda = _finite(result.get("pf_ebitda_adjusted"))
    if starting_debt is None or reported_ebitda is None or reported_ebitda <= 0:
        return pd.DataFrame()
    default_paydown = max(0.0, (_finite(result.get("recurring_free_cash_flow")) or 0.0) * 0.50)
    paydown = max(0.0, _finite(annual_paydown) if _finite(annual_paydown) is not None else default_paydown)
    horizon = max(1, min(10, int(years)))
    rows: list[dict[str, Any]] = []
    for year in range(0, horizon + 1):
        net_debt = max(0.0, starting_debt - paydown * year)
        rows.append(
            {
                "Year": "Close" if year == 0 else f"Year {year}",
                "Net debt": net_debt,
                "Reported leverage": net_debt / reported_ebitda,
                "Synergy-adjusted leverage": net_debt / adjusted_ebitda if adjusted_ebitda not in (None, 0) and adjusted_ebitda > 0 else None,
                "Annual paydown": 0.0 if year == 0 else paydown,
            }
        )
    return pd.DataFrame(rows)


def build_synergy_ramp(synergy: Mapping[str, Any]) -> pd.DataFrame:
    """Return annual and cumulative risk-adjusted synergy cash flows."""
    schedule = _frame(synergy.get("schedule"))
    if not schedule.empty and "After-tax risk-adjusted FCF" in schedule.columns:
        output = schedule.copy(deep=True)
        output["Cumulative synergy FCF"] = pd.to_numeric(output["After-tax risk-adjusted FCF"], errors="coerce").fillna(0.0).cumsum()
        return output
    cash_flows = [_finite(value) or 0.0 for value in list(synergy.get("cash_flows") or [])]
    cumulative = 0.0
    rows: list[dict[str, Any]] = []
    for year, cash_flow in enumerate(cash_flows, start=1):
        cumulative += cash_flow
        rows.append({"Year": year, "Risk-adjusted after-tax synergy FCF": cash_flow, "Cumulative synergy FCF": cumulative})
    return pd.DataFrame(rows)


def build_peer_scatter(peer_table: pd.DataFrame) -> pd.DataFrame:
    """Normalize the growth-versus-margin peer map when those fields exist."""
    required = {"Revenue Growth", "EBITDA Margin"}
    if not isinstance(peer_table, pd.DataFrame) or peer_table.empty or not required.issubset(peer_table.columns):
        return pd.DataFrame()
    output = peer_table.copy(deep=True)
    label_column = next((column for column in ("Symbol", "Company", "Ticker") if column in output.columns), None)
    if label_column is None:
        output["Label"] = "Peer"
    else:
        output["Label"] = output[label_column].astype(str)
    output["Revenue Growth"] = pd.to_numeric(output["Revenue Growth"], errors="coerce")
    output["EBITDA Margin"] = pd.to_numeric(output["EBITDA Margin"], errors="coerce")
    if "EV/EBITDA" in output.columns:
        output["EV/EBITDA"] = pd.to_numeric(output["EV/EBITDA"], errors="coerce")
    else:
        output["EV/EBITDA"] = math.nan
    output["Peer Type"] = output.get("Peer Type", pd.Series("Peer", index=output.index)).fillna("Peer").astype(str)
    return output[["Label", "Peer Type", "Revenue Growth", "EBITDA Margin", "EV/EBITDA"]].dropna(subset=["Revenue Growth", "EBITDA Margin"]).reset_index(drop=True)


def _inject_css() -> None:
    st.markdown(
        """
<style>
.mna-shell{margin:2px 0 14px;padding:22px 24px;border:1px solid rgba(103,181,204,.28);border-radius:18px;background:radial-gradient(circle at 88% 12%,rgba(49,199,212,.14),transparent 30%),linear-gradient(135deg,#0c2130,#06131e 58%,#091826);box-shadow:0 22px 56px rgba(0,0,0,.24)}
.mna-top{display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap}.mna-code{color:#e5c36c;font-size:.62rem;letter-spacing:.20em;text-transform:uppercase;font-weight:900}.mna-policy{padding:5px 9px;border:1px solid rgba(104,214,154,.28);border-radius:999px;color:#9ce6bb;font-size:.58rem;letter-spacing:.11em;text-transform:uppercase;font-weight:900}.mna-title{margin-top:17px;color:#f6f9fb;font:800 clamp(1.8rem,3.5vw,2.8rem)/1.05 Georgia,serif}.mna-title span{color:#65d7e7}.mna-sub{margin-top:7px;color:#91a9bb;font-size:.75rem;line-height:1.5;max-width:920px}.mna-strip{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;margin-top:18px}.mna-stat{padding:11px 12px;border:1px solid rgba(121,162,190,.20);border-radius:11px;background:rgba(7,22,34,.76)}.mna-stat .k{font-size:.54rem;letter-spacing:.15em;text-transform:uppercase;color:#7991a5;font-weight:900}.mna-stat .v{font:800 1.16rem Georgia,serif;color:#f1f6f9;margin-top:5px}.mna-stat .s{font-size:.59rem;color:#7890a3;margin-top:3px}.mna-note{padding:13px 15px;border-left:3px solid #e5c36c;border-radius:8px;background:rgba(229,195,108,.07);color:#b3c1cc;font-size:.72rem;line-height:1.55}.mna-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;margin:10px 0}.mna-card{padding:14px;border:1px solid rgba(121,162,190,.19);border-radius:13px;background:linear-gradient(145deg,rgba(10,31,45,.86),rgba(5,17,27,.90))}.mna-card .k{font-size:.55rem;letter-spacing:.15em;text-transform:uppercase;color:#e5c36c;font-weight:900}.mna-card h4{font:800 1rem Georgia,serif;color:#eef5fa;margin:7px 0}.mna-card p{font-size:.70rem;color:#94aabc;line-height:1.5;margin:0}.mna-pass{color:#68d69a}.mna-watch{color:#e5c36c}.mna-block{color:#ff7c80}
.mna-context{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;margin:0 0 12px;padding:11px 13px;border:1px solid rgba(121,162,190,.20);border-radius:13px;background:linear-gradient(90deg,rgba(13,38,54,.88),rgba(7,21,32,.80))}.mna-context-main{color:#eef5fa;font:800 .88rem Georgia,serif}.mna-context-meta{display:flex;gap:6px;flex-wrap:wrap}.mna-chip{padding:4px 8px;border:1px solid rgba(121,162,190,.24);border-radius:999px;color:#9db2c1;font-size:.55rem;letter-spacing:.08em;text-transform:uppercase}.mna-chip.active{border-color:rgba(99,215,231,.45);color:#79deeb;background:rgba(37,143,160,.10)}
.mna-section-head{margin:6px 0 12px;padding-bottom:10px;border-bottom:1px solid rgba(121,162,190,.15)}.mna-section-code{font-size:.57rem;letter-spacing:.18em;color:#e5c36c;text-transform:uppercase;font-weight:900}.mna-section-title{font:800 1.24rem Georgia,serif;color:#edf4f8;margin-top:4px}.mna-section-sub{font-size:.68rem;line-height:1.5;color:#8fa5b5;margin-top:4px}.mna-rail-label{font-size:.56rem;letter-spacing:.18em;color:#6f899d;text-transform:uppercase;font-weight:900;margin:7px 0 5px}.mna-mini{padding:10px;border:1px solid rgba(121,162,190,.16);border-radius:11px;background:rgba(5,17,27,.68);color:#8fa5b5;font-size:.62rem;line-height:1.55}.mna-mini b{color:#e8f1f6}.mna-audit-ok{color:#68d69a}.mna-audit-warn{color:#e5c36c}
[class*="st-key-mna_command_"] div[role="radiogroup"]{display:flex;flex-direction:column;gap:6px;padding:8px;border:1px solid rgba(121,162,190,.20);border-radius:14px;background:rgba(5,16,26,.80)}[class*="st-key-mna_command_"] div[role="radiogroup"] label{min-height:39px;padding:7px 10px!important;border:1px solid transparent;border-radius:9px;background:rgba(13,35,50,.68)}[class*="st-key-mna_command_"] div[role="radiogroup"] label:has(input:checked){border-color:rgba(99,215,231,.55);background:linear-gradient(90deg,rgba(36,120,140,.30),rgba(36,120,140,.10))}
@media(max-width:900px){.mna-shell{padding:18px}.mna-strip{grid-template-columns:repeat(2,minmax(0,1fr))}.mna-grid{grid-template-columns:1fr}[class*="st-key-mna_command_"] div[role="radiogroup"]{flex-direction:row;flex-wrap:wrap}.mna-context{align-items:flex-start}}
@media(max-width:520px){.mna-strip{grid-template-columns:1fr}.mna-shell{padding:15px}.mna-title{font-size:1.55rem}.mna-context-meta{width:100%}.mna-chip{font-size:.50rem}}
</style>
""",
        unsafe_allow_html=True,
    )


def _hero(facts: Mapping[str, Any]) -> None:
    coverage = _finite(facts.get("coverage")) or 0.0
    coverage_state = "Ready" if coverage >= 85 else "Limited"
    st.markdown(
        f"""
<section class="mna-shell">
  <div class="mna-top"><div class="mna-code">{MNA_VERSION} · transaction intelligence</div><div class="mna-policy">{RESEARCH_ONLY}</div></div>
  <div class="mna-title">{escape(str(facts.get('name') or facts.get('ticker')))} <span>{escape(str(facts.get('ticker')))}</span></div>
  <div class="mna-sub">Standalone company evidence transformed into an inspectable M&A decision case. Observed facts, derived values and editable assumptions remain visibly separated.</div>
  <div class="mna-strip">
    <div class="mna-stat"><div class="k">Standalone EV</div><div class="v">{escape(_money(facts.get('enterprise_value'), str(facts.get('currency'))))}</div><div class="s">{escape(str(facts.get('enterprise_value_status')))}</div></div>
    <div class="mna-stat"><div class="k">Net debt / (cash)</div><div class="v">{escape(_money(facts.get('net_debt'), str(facts.get('currency'))))}</div><div class="s">Capital structure</div></div>
    <div class="mna-stat"><div class="k">EV / EBITDA</div><div class="v">{escape(_multiple(facts.get('ev_to_ebitda')))}</div><div class="s">Standalone</div></div>
    <div class="mna-stat"><div class="k">FCF margin</div><div class="v">{escape(_percent(facts.get('fcf_margin')))}</div><div class="s">Cash conversion</div></div>
    <div class="mna-stat"><div class="k">Evidence</div><div class="v">{coverage:.0f}%</div><div class="s">{coverage_state}</div></div>
  </div>
</section>
""",
        unsafe_allow_html=True,
    )


def _dataframe(frame: pd.DataFrame, *, height: int | None = None, formats: Mapping[str, str] | None = None) -> None:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        st.info("No usable observations for this view. Missing values remain unavailable.")
        return
    styler = frame.style
    if formats:
        existing = {key: value for key, value in formats.items() if key in frame.columns}
        if existing:
            styler = styler.format(existing, na_rep="N/A")
    kwargs: dict[str, Any] = {"width": "stretch", "hide_index": True}
    if height is not None:
        kwargs["height"] = height
    st.dataframe(styler, **kwargs)


def _section_heading(code: str, title: str, subtitle: str) -> None:
    anchor = f"mna-{str(code).lower().replace(' ', '-')}"
    st.markdown(
        f"""
<section id="{escape(anchor)}" class="mna-section-head" aria-labelledby="{escape(anchor)}-title">
  <div class="mna-section-code">{escape(code)}</div>
  <div id="{escape(anchor)}-title" class="mna-section-title">{escape(title)}</div>
  <div class="mna-section-sub">{escape(subtitle)}</div>
</section>
""",
        unsafe_allow_html=True,
    )


def _sync_scenario_defaults(ticker: str, facts: Mapping[str, Any], scenario: str) -> None:
    """Load a scenario profile only when the active profile changes."""
    marker = f"mna_profile_loaded_{ticker}"
    profile_signature = f"{MNA_VERSION} · {scenario}"
    if st.session_state.get(marker) == profile_signature:
        return
    profile = SCENARIO_PROFILES.get(scenario, SCENARIO_PROFILES["Base"])
    revenue = max(0.0, _finite(facts.get("revenue")) or 0.0)
    ebitda = max(0.0, _finite(facts.get("ebitda")) or 0.0)
    base_growth = _clip(facts.get("revenue_growth"), -0.20, 0.45, 0.08)
    market_cap = max(1.0, _finite(facts.get("market_cap")) or 1e9)
    cash_available = max(0.0, _finite(facts.get("cash")) or 0.0)
    indicative_uses = max(1.0, market_cap * 0.111)
    capacity_pct = max(0, min(100, int((100.0 * cash_available / indicative_uses) // 5 * 5)))
    cash_funding_pct = min(int(round(profile["cash_pct"] * 100)), capacity_pct)
    debt_funding_pct = min(int(round(profile["debt_pct"] * 100)), 100 - cash_funding_pct)
    values = {
        f"mna_target_premium_{ticker}": int(round(profile["premium"] * 100)),
        f"mna_target_discount_{ticker}": profile["synergy_discount_rate"] * 100.0,
        f"mna_target_probability_{ticker}": int(round(profile["synergy_probability"] * 100)),
        f"mna_target_cost_syn_{ticker}": ebitda * profile["cost_synergy_pct_ebitda"] / 1e9,
        f"mna_target_rev_syn_{ticker}": revenue * profile["revenue_synergy_pct_revenue"] / 1e9,
        f"mna_target_syn_margin_{ticker}": profile["revenue_synergy_margin"] * 100.0,
        f"mna_target_integration_{ticker}": ebitda * profile["integration_pct_ebitda"] / 1e9,
        f"mna_fa_growth_{ticker}": 100.0 * _clip(base_growth + profile["dcf_growth_adjustment"], -0.50, 1.50, base_growth),
        f"mna_fa_wacc_{ticker}": profile["wacc"] * 100.0,
        f"mna_fa_terminal_{ticker}": profile["terminal_growth"] * 100.0,
        f"mna_buy_cash_pct_{ticker}": cash_funding_pct,
        f"mna_buy_debt_pct_{ticker}": debt_funding_pct,
    }
    for key, value in values.items():
        st.session_state[key] = value
    st.session_state[marker] = profile_signature


def _render_context_editor(facts: Mapping[str, Any], ticker: str, scenario: str, density: str) -> dict[str, Any]:
    """Render and return the persistent, cross-view deal context."""
    with st.expander("Deal context · ownership, perimeter & review state", expanded=False):
        c1, c2, c3, c4 = st.columns(4)
        counterparty = c1.text_input(
            "Counterparty / target",
            value="Unspecified",
            key=f"mna_ctx_counterparty_{ticker}",
            help="Name or identifier supplied by the analyst; no entity match is inferred.",
        )
        valuation_date = c2.date_input(
            "Valuation date",
            value=date.today(),
            key=f"mna_ctx_date_{ticker}",
            help="Scenario valuation date, not a claim that every source is point-in-time complete.",
        )
        currencies = list(dict.fromkeys([str(facts.get("currency") or "USD").upper(), "USD", "EUR", "GBP", "JPY"]))
        currency = c3.selectbox("Presentation currency", currencies, key=f"mna_ctx_currency_{ticker}")
        stage = c4.selectbox(
            "Deal stage",
            ["Screening", "Indicative", "Diligence", "IC review"],
            key=f"mna_ctx_stage_{ticker}",
        )
        d1, d2, d3 = st.columns(3)
        owner = d1.text_input("Case owner", value="Unassigned", key=f"mna_ctx_owner_{ticker}")
        reviewer = d2.text_input("Human reviewer", value="Unassigned", key=f"mna_ctx_reviewer_{ticker}")
        review_status = d3.selectbox(
            "Review status",
            ["DRAFT", "EVIDENCE PENDING", "READY FOR HUMAN REVIEW"],
            key=f"mna_ctx_review_{ticker}",
        )
        st.caption("Context persists across DES, RV, FA, DOWW and BI for this browser session; governed snapshots persist in the append-only scenario ledger.")
    return {
        "ticker": ticker,
        "company": str(facts.get("name") or ticker),
        "counterparty": counterparty.strip() or "Unspecified",
        "valuation_date": valuation_date.isoformat() if hasattr(valuation_date, "isoformat") else str(valuation_date),
        "currency": currency,
        "stage": stage,
        "owner": owner.strip() or "Unassigned",
        "reviewer": reviewer.strip() or "Unassigned",
        "review_status": review_status,
        "scenario": scenario,
        "density": density,
        "valuation_anchor": st.session_state.get(f"mna_ctx_anchor_{ticker}", "Standalone market price"),
    }


def _render_context_ribbon(context: Mapping[str, Any]) -> None:
    st.markdown(
        f"""
<div class="mna-context" role="status" aria-label="Active deal context">
  <div class="mna-context-main">{escape(str(context.get('company')))} ↔ {escape(str(context.get('counterparty')))}</div>
  <div class="mna-context-meta">
    <span class="mna-chip active">{escape(str(context.get('scenario')))}</span>
    <span class="mna-chip">{escape(str(context.get('stage')))}</span>
    <span class="mna-chip">{escape(str(context.get('valuation_date')))}</span>
    <span class="mna-chip">{escape(str(context.get('currency')))}</span>
    <span class="mna-chip">{escape(str(context.get('review_status')))}</span>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def _render_football_field(field: pd.DataFrame, facts: Mapping[str, Any], *, key: str) -> None:
    if not isinstance(field, pd.DataFrame) or field.empty:
        st.info("Football field pending: current peers, DCF inputs or control-premium cases are incomplete.")
        return
    figure = go.Figure()
    palette = ["#63d7e7", "#e5c36c", "#7fa8ff", "#68d69a", "#d593ff"]
    for index, (_, row) in enumerate(field.iterrows()):
        low, mid, high = (_finite(row.get(column)) for column in ("Low", "Mid", "High"))
        if low is None or mid is None or high is None:
            continue
        method = str(row.get("Method"))
        color = palette[index % len(palette)]
        figure.add_trace(
            go.Scatter(
                x=[low, high],
                y=[method, method],
                mode="lines",
                line={"color": color, "width": 10},
                hovertemplate=f"{escape(method)}<br>Low %{{x:,.2f}}<extra></extra>",
                showlegend=False,
            )
        )
        figure.add_trace(
            go.Scatter(
                x=[mid],
                y=[method],
                mode="markers",
                marker={"color": "#f5f8fa", "size": 10, "symbol": "diamond", "line": {"color": color, "width": 2}},
                hovertemplate="Mid %{x:,.2f}<extra></extra>",
                showlegend=False,
            )
        )
    current_price = _finite(facts.get("price"))
    if current_price is not None:
        figure.add_vline(x=current_price, line_dash="dash", line_color="#ff8589", annotation_text="Current price")
    figure.update_layout(
        height=max(270, 62 * len(field) + 90),
        margin=dict(l=8, r=18, t=30, b=12),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color="#a9bdcb",
        xaxis={"title": f"Price per share · {facts.get('currency', '')}", "gridcolor": "rgba(130,160,180,.12)"},
        yaxis={"title": None},
    )
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False, "responsive": True}, key=key)


def _render_waterfall(frame: pd.DataFrame, *, value_column: str, title: str, key: str) -> None:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        st.info(f"{title} unavailable because required inputs are incomplete.")
        return
    figure = go.Figure(
        go.Waterfall(
            name=title,
            orientation="v",
            measure=frame["Measure"].tolist(),
            x=frame["Item"].tolist(),
            y=pd.to_numeric(frame[value_column], errors="coerce").fillna(0.0).tolist(),
            connector={"line": {"color": "rgba(150,175,190,.35)"}},
            increasing={"marker": {"color": "#63d7e7"}},
            decreasing={"marker": {"color": "#ff8589"}},
            totals={"marker": {"color": "#e5c36c"}},
            hovertemplate="%{x}<br>%{y:,.0f}<extra></extra>",
        )
    )
    figure.update_layout(
        height=360,
        margin=dict(l=8, r=8, t=35, b=80),
        title={"text": title, "font": {"size": 13}},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color="#a9bdcb",
        showlegend=False,
    )
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False, "responsive": True}, key=key)


def _render_des(facts: Mapping[str, Any], density: str) -> None:
    _section_heading(
        "DES · COMPANY 360",
        "Company & transaction description",
        "Identity resolution, business perimeter, capital structure and transaction-screening evidence.",
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Market capitalization", _money(facts.get("market_cap"), str(facts.get("currency"))))
    c2.metric("Cash", _money(facts.get("cash"), str(facts.get("currency"))))
    c3.metric("Debt", _money(facts.get("debt"), str(facts.get("currency"))))
    c4.metric("Diluted shares", fmt_large_number(facts.get("shares")))

    st.markdown(
        f"""
<div class="mna-grid">
  <div class="mna-card"><div class="k">Business perimeter</div><h4>{escape(str(facts.get('sector')))} · {escape(str(facts.get('industry')))}</h4><p>{escape(str(facts.get('country')))} · {escape(str(facts.get('summary'))[:420])}</p></div>
  <div class="mna-card"><div class="k">Operating base</div><h4>{escape(_money(facts.get('revenue'), str(facts.get('currency'))))} revenue</h4><p>EBITDA {escape(_money(facts.get('ebitda'), str(facts.get('currency'))))} · margin {escape(_percent(facts.get('ebitda_margin')))} · growth {escape(_percent(facts.get('revenue_growth')))}</p></div>
  <div class="mna-card"><div class="k">Cash economics</div><h4>{escape(_money(facts.get('free_cash_flow'), str(facts.get('currency'))))} FCF</h4><p>FCF margin {escape(_percent(facts.get('fcf_margin')))} · current multiple {escape(_multiple(facts.get('ev_to_ebitda')))} EV/EBITDA.</p></div>
</div>
""",
        unsafe_allow_html=True,
    )

    bridge = _mapping(facts.get("enterprise_bridge"))
    components = _mapping(bridge.get("components"))
    st.markdown("##### Equity value → enterprise value")
    if components:
        bridge_df = pd.DataFrame(
            [{"Item": key, "Value": value, "Measure": "relative"} for key, value in components.items()]
            + [{"Item": "Derived enterprise value", "Value": bridge.get("enterprise_value"), "Measure": "total"}]
        )
        _render_waterfall(
            bridge_df,
            value_column="Value",
            title="Equity value → enterprise value",
            key=f"mna_des_ev_bridge_{facts.get('ticker')}",
        )
        if density == "Audit":
            _dataframe(bridge_df[["Item", "Value"]], formats={"Value": "{:,.0f}"})
    else:
        st.warning("EV bridge blocked: equity value, debt and cash are required.")

    gates = screening_gates(facts)
    blocked_count = int(gates["State"].eq("BLOCKED").sum()) if not gates.empty else 0
    if density == "Executive":
        tone = "mna-audit-ok" if blocked_count == 0 else "mna-audit-warn"
        st.markdown(
            f'<div class="mna-mini"><b class="{tone}">{len(gates) - blocked_count}/{len(gates)} screening gates pass</b><br>Switch to Analyst or Audit density for the field-level contract.</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown("##### Transaction screening gates")
        _dataframe(gates)
    if density == "Audit":
        with st.expander("Evidence contract · field-level audit", expanded=True):
            _dataframe(_frame(facts.get("evidence")), formats={"Value": "{:,.2f}"})
            gap = _finite(facts.get("ev_reconciliation_gap"))
            if gap is not None:
                st.caption(f"Observed-versus-derived EV reconciliation gap: {_money(gap, str(facts.get('currency')))}.")


def _render_rv(facts: Mapping[str, Any], ticker: str, density: str, context: Mapping[str, Any]) -> None:
    _section_heading(
        "RV · RELATIVE VALUE",
        "Valuation range & offer anchor",
        "Current comparable-company evidence, DCF sensitivity and control-premium scenarios in one decision field.",
    )
    st.markdown(
        '<div class="mna-note"><b>Evidence boundary.</b> Current trading comparables are not point-in-time precedent transactions. No precedent range is manufactured until dated transaction data are connected.</div>',
        unsafe_allow_html=True,
    )
    company = _mapping(facts.get("company"))
    inst = _mapping(company.get("institutional"))
    peer = _mapping(inst.get("peer_intelligence"))
    peer_table = _frame(peer.get("table"))
    summary = _frame(peer.get("summary"))

    symbol_column = next((column for column in ("Symbol", "symbol", "Ticker", "ticker") if column in peer_table.columns), None)
    available_symbols: list[str] = []
    if symbol_column is not None:
        available_symbols = list(
            dict.fromkeys(
                peer_table.loc[
                    ~peer_table.get("Peer Type", pd.Series("Peer", index=peer_table.index)).astype(str).str.lower().eq("target"),
                    symbol_column,
                ]
                .dropna()
                .astype(str)
                .str.upper()
                .str.strip()
                .tolist()
            )
        )
    selected_symbols = available_symbols
    rationale = ""
    if available_symbols and density != "Executive":
        with st.expander("Comparable-universe controls", expanded=density == "Audit"):
            selected_symbols = st.multiselect(
                "Included comparable companies",
                available_symbols,
                default=available_symbols,
                key=f"mna_rv_peers_{ticker}",
                help="At least four positive observations per metric are required.",
            )
            excluded = [symbol for symbol in available_symbols if symbol not in selected_symbols]
            rationale = st.text_input(
                "Exclusion rationale",
                value="",
                key=f"mna_rv_exclusion_{ticker}",
                placeholder="Required when one or more peers are excluded",
                disabled=not excluded,
            )
            if excluded and not rationale.strip():
                st.warning("Peer exclusions are visible but cannot become the live deal anchor until a rationale is recorded.")
    filtered_peers, peer_audit = filter_peer_universe(peer_table, selected_symbols, exclusion_rationale=rationale)
    has_ungoverned_exclusion = not peer_audit.empty and peer_audit["Rationale"].eq("RATIONALE REQUIRED").any()
    ranges = relative_valuation_ranges(facts, filtered_peers)
    scenario_comparison = build_scenario_comparison(facts)
    profile = SCENARIO_PROFILES.get(str(context.get("scenario")), SCENARIO_PROFILES["Base"])
    dcf_assumptions = {
        "base_fcf": max(0.0, _finite(facts.get("free_cash_flow")) or 0.0),
        "initial_growth": _clip(
            (_finite(facts.get("revenue_growth")) or 0.08) + profile["dcf_growth_adjustment"],
            -0.50,
            1.50,
            0.08,
        ),
        "wacc": profile["wacc"],
        "terminal_growth": profile["terminal_growth"],
        "years": 5,
    }
    sensitivity = dcf_sensitivity_table(facts, dcf_assumptions)
    football_field = build_football_field(facts, ranges, scenario_comparison, sensitivity)

    st.markdown("##### Valuation football field")
    _render_football_field(football_field, facts, key=f"mna_football_{ticker}_{context.get('scenario')}")
    if not football_field.empty and density == "Audit":
        _dataframe(football_field, formats={"Low": "{:,.2f}", "Mid": "{:,.2f}", "High": "{:,.2f}"})

    if not ranges.empty:
        anchor_options = {
            f"{row['Method']} · {row['Statistic']} · {row['Implied price']:,.2f}": row
            for _, row in ranges.dropna(subset=["Implied price"]).iterrows()
        }
        if anchor_options:
            a1, a2 = st.columns([2, 1])
            choice = a1.selectbox("Live valuation anchor", list(anchor_options), key=f"mna_rv_anchor_choice_{ticker}")
            chosen = anchor_options[choice]
            current_price = _finite(facts.get("price"))
            implied_price = _finite(chosen.get("Implied price"))
            premium = implied_price / current_price - 1 if implied_price is not None and current_price not in (None, 0) else None
            if a2.button(
                "Apply to DOWW",
                key=f"mna_rv_apply_{ticker}",
                width="stretch",
                disabled=premium is None or has_ungoverned_exclusion,
                help="Writes the selected implied premium into the target deal case.",
            ):
                st.session_state[f"mna_target_premium_{ticker}"] = int(round(100 * _clip(premium, 0.0, 1.0, 0.0)))
                st.session_state[f"mna_ctx_anchor_{ticker}"] = f"RV · {chosen['Method']} {chosen['Statistic']}"
                st.success("RV anchor linked to DOWW. Open Deal Watch to inspect the resulting transaction case.")
    else:
        st.info("At least four valid current peers per metric are required for a comparable-company range.")

    st.markdown("##### Bear / Base / Bull decision matrix")
    _dataframe(
        scenario_comparison,
        formats={
            "Offer premium": "{:.0%}",
            "Offer price": "{:,.2f}",
            "Transaction EV": "{:,.0f}",
            "EV / EBITDA": "{:.2f}x",
            "Synergy confidence": "{:.0%}",
            "Synergy NPV": "{:,.0f}",
            "Buyer retained value": "{:,.0f}",
            "DCF value / share": "{:,.2f}",
            "DCF upside / downside": "{:+.1%}",
            "WACC": "{:.1%}",
            "Terminal growth": "{:.1%}",
        },
    )

    if density != "Executive":
        st.markdown("##### Comparable universe")
        if filtered_peers.empty:
            st.warning("Comparable universe is unavailable. No quartile is manufactured from missing peers.")
        else:
            columns = [
                column
                for column in ("Symbol", "Company", "Peer Type", "Similarity", "Revenue Growth", "EBITDA Margin", "Operating Margin", "FCF Margin", "ROIC", "P/E TTM", "Forward P/E", "EV/Sales", "EV/EBITDA", "Source")
                if column in filtered_peers.columns
            ]
            _dataframe(filtered_peers[columns], height=420)
        scatter = build_peer_scatter(filtered_peers)
        if not scatter.empty:
            figure = go.Figure()
            for peer_type, group in scatter.groupby("Peer Type", sort=False):
                figure.add_trace(
                    go.Scatter(
                        x=group["Revenue Growth"],
                        y=group["EBITDA Margin"],
                        text=group["Label"],
                        customdata=group[["EV/EBITDA"]].to_numpy(),
                        mode="markers+text",
                        textposition="top center",
                        marker={"size": 12, "color": "#e5c36c" if str(peer_type).lower() == "target" else "#63d7e7"},
                        name=str(peer_type),
                        hovertemplate="%{text}<br>Growth %{x:.1%}<br>EBITDA margin %{y:.1%}<br>EV/EBITDA %{customdata[0]:.2f}x<extra></extra>",
                    )
                )
            figure.update_layout(
                height=360,
                margin=dict(l=8, r=8, t=25, b=15),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font_color="#a9bdcb",
                xaxis={"title": "Revenue growth", "tickformat": ".0%", "gridcolor": "rgba(130,160,180,.12)"},
                yaxis={"title": "EBITDA margin", "tickformat": ".0%", "gridcolor": "rgba(130,160,180,.12)"},
            )
            st.plotly_chart(figure, width="stretch", config={"displayModeBar": False}, key=f"mna_peer_map_{ticker}")
        if not summary.empty:
            with st.expander("Peer median, percentile and premium audit", expanded=density == "Audit"):
                _dataframe(summary, formats={"Target": "{:.2f}", "Peer Median": "{:.2f}", "Target Percentile": "{:.1f}", "Premium / Discount": "{:.1%}"})
        if density == "Audit" and not peer_audit.empty:
            with st.expander("Peer selection audit", expanded=True):
                _dataframe(peer_audit)
                st.caption("Selection affects only this research scenario; the source universe is never overwritten.")

    if density == "Audit":
        premiums = []
        for premium_value in (0.0, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60):
            case = target_deal_case(facts, {"premium": premium_value})
            premiums.append(
                {
                    "Premium": premium_value,
                    "Offer price": case.get("offer_price"),
                    "Equity purchase price": case.get("offer_equity_value"),
                    "Transaction EV": case.get("transaction_ev"),
                    "EV / Revenue": case.get("ev_revenue"),
                    "EV / EBITDA": case.get("ev_ebitda"),
                    "P / E": case.get("price_earnings"),
                }
            )
        with st.expander("Control-premium ladder · formula audit", expanded=False):
            _dataframe(pd.DataFrame(premiums), formats={"Premium": "{:.0%}", "Offer price": "{:,.2f}", "Equity purchase price": "{:,.0f}", "Transaction EV": "{:,.0f}", "EV / Revenue": "{:.2f}x", "EV / EBITDA": "{:.2f}x", "P / E": "{:.2f}x"})


def _render_fa(facts: Mapping[str, Any], ticker: str, density: str) -> None:
    _section_heading(
        "FA · FINANCIAL ANALYSIS",
        "DCF, reverse DCF & financial diagnostics",
        "Reported financial evidence and deterministic valuation remain separate from editable analyst assumptions.",
    )
    ratios = pd.DataFrame(
        [
            {"Metric": "Revenue growth", "Value": facts.get("revenue_growth"), "Basis": "TTM / latest provider"},
            {"Metric": "EBITDA margin", "Value": facts.get("ebitda_margin"), "Basis": "EBITDA / revenue"},
            {"Metric": "Operating margin", "Value": facts.get("operating_margin"), "Basis": "EBIT / revenue"},
            {"Metric": "FCF margin", "Value": facts.get("fcf_margin"), "Basis": "FCF / revenue"},
            {"Metric": "EV / Revenue", "Value": facts.get("ev_to_revenue"), "Basis": "Current EV / revenue"},
            {"Metric": "EV / EBITDA", "Value": facts.get("ev_to_ebitda"), "Basis": "Current EV / EBITDA"},
            {"Metric": "Trailing P/E", "Value": facts.get("trailing_pe"), "Basis": "Current price / trailing EPS"},
            {"Metric": "Forward P/E", "Value": facts.get("forward_pe"), "Basis": "Provider consensus"},
        ]
    )
    if density != "Executive":
        _dataframe(ratios, formats={"Value": "{:.2f}"})

    base_fcf = max(0.0, _finite(facts.get("free_cash_flow")) or 0.0)
    default_growth = 100.0 * _clip(facts.get("revenue_growth"), -0.20, 0.45, 0.08)
    st.markdown("##### DCF assumption deck")
    a, b, c, d = st.columns(4)
    base_fcf_bn = a.number_input("Base FCF proxy · bn", min_value=0.0, value=float(base_fcf / 1e9), step=0.1, key=f"mna_fa_fcf_{ticker}")
    initial_growth_pct = b.number_input("Initial growth · %", min_value=-50.0, max_value=150.0, value=float(default_growth), step=0.5, key=f"mna_fa_growth_{ticker}")
    wacc_pct = c.number_input("WACC · %", min_value=1.0, max_value=40.0, value=10.0, step=0.25, key=f"mna_fa_wacc_{ticker}")
    terminal_pct = d.number_input("Terminal growth · %", min_value=-5.0, max_value=10.0, value=3.0, step=0.25, key=f"mna_fa_terminal_{ticker}")
    assumptions = {
        "base_fcf": base_fcf_bn * 1e9,
        "initial_growth": initial_growth_pct / 100.0,
        "wacc": wacc_pct / 100.0,
        "terminal_growth": terminal_pct / 100.0,
        "years": 5,
    }
    result = dcf_valuation(facts, assumptions)
    if result.get("status") == "BLOCKED":
        st.error(str(result.get("reason")))
    else:
        x1, x2, x3, x4 = st.columns(4)
        x1.metric("DCF enterprise value", _money(result.get("enterprise_value"), str(facts.get("currency"))))
        x2.metric("DCF equity value", _money(result.get("equity_value"), str(facts.get("currency"))))
        x3.metric("DCF value / share", _money(result.get("value_per_share"), str(facts.get("currency"))))
        terminal_share = _finite(result.get("terminal_value_share"))
        x4.metric("Terminal value share", _percent(terminal_share), "High concentration" if terminal_share is not None and terminal_share > 0.75 else "")
        st.caption(str(result.get("reason") or "Illustrative valuation assumptions require human review."))
        current_price = _finite(facts.get("price"))
        dcf_price = _finite(result.get("value_per_share"))
        if st.button(
            "Use DCF as DOWW valuation anchor",
            key=f"mna_fa_apply_{ticker}",
            disabled=current_price in (None, 0) or dcf_price is None,
            help="Converts the active DCF value per share into a live target premium for Deal Watch.",
        ):
            premium = dcf_price / current_price - 1
            st.session_state[f"mna_target_premium_{ticker}"] = int(round(100 * _clip(premium, 0.0, 1.0, 0.0)))
            st.session_state[f"mna_ctx_anchor_{ticker}"] = "FA · active DCF"
            st.success("DCF anchor linked to DOWW.")
        implied_growth = reverse_dcf_growth(facts, assumptions)
        if implied_growth is None:
            st.warning("Reverse DCF is infeasible inside the documented -50% to +150% growth bracket.")
        else:
            st.info(f"Reverse DCF: the current price implies approximately {implied_growth:.1%} initial FCF growth under the active WACC and terminal assumptions.")
        forecast = _frame(result.get("forecast"))
        if not forecast.empty:
            figure = go.Figure()
            figure.add_trace(go.Bar(x=forecast["Year"], y=forecast["FCF"], name="Forecast FCF", marker_color="#63d7e7"))
            figure.add_trace(go.Scatter(x=forecast["Year"], y=forecast["Present Value"], name="Present value", mode="lines+markers", line={"color": "#e5c36c", "width": 3}))
            figure.update_layout(
                height=310,
                margin=dict(l=8, r=8, t=25, b=10),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font_color="#a9bdcb",
                legend={"orientation": "h", "y": 1.08},
                xaxis={"title": "Forecast year", "gridcolor": "rgba(130,160,180,.08)"},
                yaxis={"title": str(facts.get("currency") or ""), "gridcolor": "rgba(130,160,180,.12)"},
            )
            st.plotly_chart(figure, width="stretch", config={"displayModeBar": False}, key=f"mna_dcf_forecast_{ticker}")
        if density == "Audit":
            with st.expander("DCF cash-flow bridge", expanded=False):
                _dataframe(forecast, formats={"Growth": "{:.1%}", "FCF": "{:,.0f}", "Present Value": "{:,.0f}"})
        st.markdown("##### WACC × terminal-growth sensitivity · value per share")
        sensitivity = dcf_sensitivity_table(facts, assumptions)
        indexed = sensitivity.copy()
        indexed["WACC"] = indexed["WACC"].map(lambda value: f"{value:.1%}")
        _dataframe(indexed, formats={column: "{:,.2f}" for column in indexed.columns if column != "WACC"})
    if density == "Audit":
        with st.expander("Reported financial statements", expanded=False):
            for label, frame in _mapping(facts.get("raw_frames")).items():
                st.markdown(f"**{label}**")
                if isinstance(frame, pd.DataFrame) and not frame.empty:
                    st.dataframe(frame, width="stretch", height=300)
                else:
                    st.caption("Unavailable")


def _save_scenario(
    ticker: str,
    label: str,
    payload: Mapping[str, Any],
    context: Mapping[str, Any],
) -> dict[str, Any]:
    """Persist a new immutable revision in the governed local ledger."""
    return append_scenario(ticker, label, payload, context=context)


def _hypothesis_board(rows: Sequence[Mapping[str, Any]]) -> None:
    cards = []
    for row in rows:
        state = str(row.get("State") or "BLOCKED")
        tone = "mna-pass" if state == "PASS" else "mna-watch" if state == "WATCH" else "mna-block"
        cards.append(
            f'<div class="mna-card"><div class="k {tone}">{escape(state)}</div><h4>{escape(str(row.get("Hypothesis")))}</h4><p>{escape(str(row.get("Evidence")))}<br><br><b>Falsifier:</b> {escape(str(row.get("Falsifier")))}</p></div>'
        )
    st.markdown(f'<div class="mna-grid">{"".join(cards)}</div>', unsafe_allow_html=True)


def _render_target_watch(facts: Mapping[str, Any], ticker: str, density: str) -> dict[str, Any]:
    st.markdown("##### Hypothetical target case")
    st.caption("No deal is asserted. Every term below is a user-editable scenario assumption.")
    a, b, c, d = st.columns(4)
    premium = a.slider("Offer premium · %", 0, 100, 30, 1, key=f"mna_target_premium_{ticker}") / 100.0
    discount_rate = b.number_input("Synergy discount rate · %", 1.0, 40.0, 11.0, 0.25, key=f"mna_target_discount_{ticker}") / 100.0
    tax_rate = c.number_input("Tax rate · %", 0.0, 60.0, 21.0, 0.5, key=f"mna_target_tax_{ticker}") / 100.0
    probability = d.slider("Synergy confidence · %", 0, 100, 70, 5, key=f"mna_target_probability_{ticker}") / 100.0

    revenue = max(0.0, _finite(facts.get("revenue")) or 0.0)
    ebitda = max(0.0, _finite(facts.get("ebitda")) or 0.0)
    e, f, g, h = st.columns(4)
    cost_synergy_bn = e.number_input("Cost synergy run-rate · bn", min_value=0.0, value=float(ebitda * 0.03 / 1e9), step=0.05, key=f"mna_target_cost_syn_{ticker}")
    revenue_synergy_bn = f.number_input("Revenue synergy run-rate · bn", min_value=0.0, value=float(revenue * 0.01 / 1e9), step=0.05, key=f"mna_target_rev_syn_{ticker}")
    contribution_margin = g.number_input("Revenue synergy margin · %", min_value=0.0, max_value=100.0, value=30.0, step=1.0, key=f"mna_target_syn_margin_{ticker}") / 100.0
    integration_bn = h.number_input("Integration cost · bn", min_value=0.0, value=float(ebitda * 0.02 / 1e9), step=0.05, key=f"mna_target_integration_{ticker}")
    ramp_name = st.selectbox(
        "Synergy realization curve",
        ["Slow · 15 / 45 / 75 / 100 / 85", "Base · 25 / 65 / 100 / 100 / 85", "Fast · 45 / 85 / 100 / 100 / 85"],
        index=1,
        key=f"mna_target_ramp_{ticker}",
        help="Five-year finite ramp. No terminal synergy value is included.",
    )
    ramp = {
        "Slow": (0.15, 0.45, 0.75, 1.0, 0.85),
        "Base": (0.25, 0.65, 1.0, 1.0, 0.85),
        "Fast": (0.45, 0.85, 1.0, 1.0, 0.85),
    }[ramp_name.split(" · ", 1)[0]]
    assumptions = {
        "premium": premium,
        "discount_rate": discount_rate,
        "tax_rate": tax_rate,
        "synergy_probability": probability,
        "cost_synergy_run_rate": cost_synergy_bn * 1e9,
        "revenue_synergy_run_rate": revenue_synergy_bn * 1e9,
        "contribution_margin": contribution_margin,
        "integration_cost": integration_bn * 1e9,
        "synergy_ramp": ramp,
    }
    result = target_deal_case(facts, assumptions)
    if result.get("status") == "BLOCKED":
        st.error(f"Deal model blocked: {', '.join(result.get('missing', []))}")
        return result
    x1, x2, x3, x4, x5 = st.columns(5)
    x1.metric("Offer price", _money(result.get("offer_price"), str(facts.get("currency"))), f"{premium:.0%} premium")
    x2.metric("Equity purchase price", _money(result.get("offer_equity_value"), str(facts.get("currency"))))
    x3.metric("Transaction EV", _money(result.get("transaction_ev"), str(facts.get("currency"))))
    x4.metric("EV / EBITDA", _multiple(result.get("ev_ebitda")))
    x5.metric("Synergy-adjusted", _multiple(result.get("post_synergy_ev_ebitda")), "EV / EBITDA")

    seller_capture = _finite(result.get("seller_capture"))
    retained = _finite(result.get("buyer_retained_value"))
    hypotheses = [
        {
            "Hypothesis": "The modeled synergy pool can support the control premium.",
            "State": "PASS" if retained is not None and retained >= 0 else "WATCH" if retained is not None else "BLOCKED",
            "Evidence": f"Risk-adjusted synergy NPV {_money(result.get('synergy_npv'), str(facts.get('currency')))}; seller capture {_percent(seller_capture)}.",
            "Falsifier": "Lower realization, higher integration costs, or a higher offer price eliminates retained value.",
        },
        {
            "Hypothesis": "The transaction multiple remains inside an inspectable range.",
            "State": "PASS" if _finite(result.get("ev_ebitda")) is not None else "BLOCKED",
            "Evidence": f"Headline EV/EBITDA {_multiple(result.get('ev_ebitda'))}; post-synergy {_multiple(result.get('post_synergy_ev_ebitda'))}.",
            "Falsifier": "EBITDA normalization or debt-like items materially change the denominator or EV bridge.",
        },
        {
            "Hypothesis": "Critical transaction evidence is sufficient for review.",
            "State": "PASS" if result.get("publishable") else "WATCH",
            "Evidence": f"Atomic evidence coverage {result.get('coverage', 0):.0f}%.",
            "Falsifier": "Missing share, debt, cash or period alignment blocks publication.",
        },
    ]
    _hypothesis_board(hypotheses)
    bridge = _mapping(result.get("bridge"))
    bridge_components = _mapping(bridge.get("components"))
    synergy_schedule = build_synergy_ramp(_mapping(result.get("synergy")))
    visual_left, visual_right = st.columns(2)
    with visual_left:
        if bridge_components:
            bridge_frame = pd.DataFrame(
                [
                    {"Item": key, "Value": value, "Measure": "relative"}
                    for key, value in bridge_components.items()
                ]
                + [{"Item": "Transaction EV", "Value": bridge.get("enterprise_value"), "Measure": "total"}]
            )
            _render_waterfall(
                bridge_frame,
                value_column="Value",
                title="Offer equity → transaction EV",
                key=f"mna_target_ev_waterfall_{ticker}",
            )
    with visual_right:
        if not synergy_schedule.empty:
            figure = go.Figure()
            figure.add_trace(
                go.Bar(
                    x=synergy_schedule["Year"],
                    y=synergy_schedule["After-tax risk-adjusted FCF"],
                    name="Annual synergy FCF",
                    marker_color="#63d7e7",
                )
            )
            figure.add_trace(
                go.Scatter(
                    x=synergy_schedule["Year"],
                    y=synergy_schedule["Cumulative synergy FCF"],
                    name="Cumulative",
                    mode="lines+markers",
                    line={"color": "#e5c36c", "width": 3},
                )
            )
            figure.update_layout(
                height=360,
                title={"text": "Risk-adjusted synergy ramp", "font": {"size": 13}},
                margin=dict(l=8, r=8, t=35, b=20),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font_color="#a9bdcb",
                legend={"orientation": "h", "y": 1.08},
                xaxis={"title": "Year", "gridcolor": "rgba(130,160,180,.08)"},
                yaxis={"title": str(facts.get("currency") or ""), "gridcolor": "rgba(130,160,180,.12)"},
            )
            st.plotly_chart(figure, width="stretch", config={"displayModeBar": False}, key=f"mna_target_synergy_{ticker}")
    if density == "Audit":
        with st.expander("Transaction EV bridge & synergy schedule audit", expanded=False):
            _dataframe(pd.DataFrame([{"Item": key, "Value": value} for key, value in bridge_components.items()]), formats={"Value": "{:,.0f}"})
            _dataframe(
                synergy_schedule,
                formats={
                    "Ramp": "{:.0%}",
                    "Probability": "{:.0%}",
                    "Cost synergy contribution": "{:,.0f}",
                    "Revenue synergy contribution": "{:,.0f}",
                    "Pre-tax synergy": "{:,.0f}",
                    "After-tax risk-adjusted FCF": "{:,.0f}",
                    "Discount factor": "{:.3f}",
                    "Present value": "{:,.0f}",
                    "Cumulative synergy FCF": "{:,.0f}",
                },
            )
    return {**assumptions, **{key: value for key, value in result.items() if isinstance(value, (str, int, float, bool, type(None)))}}


def _render_acquirer_watch(facts: Mapping[str, Any], ticker: str, density: str) -> dict[str, Any]:
    st.markdown("##### Hypothetical acquirer case")
    st.caption(f"{facts.get('ticker')} is treated as the acquirer; target inputs are manual assumptions, not observed deal terms.")
    currency = str(facts.get("currency"))
    market_cap = max(1.0, _finite(facts.get("market_cap")) or 1e9)
    a, b, c, d = st.columns(4)
    target_equity_bn = a.number_input("Target equity value · bn", min_value=0.01, value=float(max(1.0, market_cap * 0.10 / 1e9)), step=0.5, key=f"mna_buy_target_equity_{ticker}")
    target_debt_bn = b.number_input("Target debt · bn", min_value=0.0, value=float(max(0.0, market_cap * 0.01 / 1e9)), step=0.1, key=f"mna_buy_target_debt_{ticker}")
    target_cash_bn = c.number_input("Target cash · bn", min_value=0.0, value=float(max(0.0, market_cap * 0.005 / 1e9)), step=0.1, key=f"mna_buy_target_cash_{ticker}")
    target_ebitda_bn = d.number_input("Target EBITDA · bn", min_value=0.01, value=float(max(0.1, (_finite(facts.get('ebitda')) or market_cap * 0.04) * 0.12 / 1e9)), step=0.1, key=f"mna_buy_target_ebitda_{ticker}")
    e, f, g, h = st.columns(4)
    target_ni_bn = e.number_input("Target net income · bn", value=float(max(0.0, (_finite(facts.get('net_income')) or market_cap * 0.02) * 0.10 / 1e9)), step=0.1, key=f"mna_buy_target_ni_{ticker}")
    target_fcf_bn = f.number_input("Target FCF · bn", value=float(max(0.0, (_finite(facts.get('free_cash_flow')) or market_cap * 0.02) * 0.10 / 1e9)), step=0.1, key=f"mna_buy_target_fcf_{ticker}")
    cash_pct = g.slider("Cash funding · %", 0, 100, 35, 5, key=f"mna_buy_cash_pct_{ticker}")
    debt_pct = h.slider("Debt funding · %", 0, 100 - cash_pct, min(35, 100 - cash_pct), 5, key=f"mna_buy_debt_pct_{ticker}")
    stock_pct = 100 - cash_pct - debt_pct
    st.caption(f"Stock funding is the residual: {stock_pct}% · financing mix always reconciles to 100%.")

    i, j, k, l = st.columns(4)
    synergy_bn = i.number_input("Pre-tax run-rate synergies · bn", min_value=0.0, value=float(max(0.0, target_ebitda_bn * 0.08)), step=0.05, key=f"mna_buy_synergy_{ticker}")
    integration_bn = j.number_input("Year-one integration cost · bn", min_value=0.0, value=float(max(0.0, target_ebitda_bn * 0.10)), step=0.05, key=f"mna_buy_integration_{ticker}")
    debt_rate_pct = k.number_input("New debt cost · %", min_value=0.0, max_value=30.0, value=6.0, step=0.25, key=f"mna_buy_debt_rate_{ticker}")
    tax_pct = l.number_input("Tax rate · %", min_value=0.0, max_value=60.0, value=21.0, step=0.5, key=f"mna_buy_tax_{ticker}")

    with st.expander("Close mechanics & linked purchase price allocation", expanded=density == "Audit"):
        m1, m2, m3, m4 = st.columns(4)
        debt_refi_pct = m1.slider("Target debt refinanced · %", 0, 100, 100, 5, key=f"mna_buy_refi_{ticker}")
        fees_bn = m2.number_input("Transaction fees · bn", min_value=0.0, value=float(target_equity_bn * 0.01), step=0.05, key=f"mna_buy_fees_{ticker}")
        book_equity_bn = m3.number_input("Target book equity · bn", value=float(max(0.0, target_equity_bn * 0.35)), step=0.1, key=f"mna_ppa_book_{ticker}")
        intangibles_bn = m4.number_input("Identifiable intangibles · bn", min_value=0.0, value=float(target_equity_bn * 0.15), step=0.1, key=f"mna_ppa_intangibles_{ticker}")
        n1, n2 = st.columns(2)
        ppe_bn = n1.number_input("PP&E step-up · bn", value=0.0, step=0.1, key=f"mna_ppa_ppe_{ticker}")
        life = n2.number_input("Intangible life · years", min_value=1.0, max_value=30.0, value=10.0, step=1.0, key=f"mna_ppa_life_{ticker}")

    target = {
        "equity_value": target_equity_bn * 1e9,
        "debt": target_debt_bn * 1e9,
        "cash": target_cash_bn * 1e9,
        "ebitda": target_ebitda_bn * 1e9,
        "net_income": target_ni_bn * 1e9,
        "free_cash_flow": target_fcf_bn * 1e9,
    }
    ppa = simplified_ppa(
        consideration=target["equity_value"],
        target_book_equity=book_equity_bn * 1e9,
        identifiable_intangibles_step_up=intangibles_bn * 1e9,
        ppe_step_up=ppe_bn * 1e9,
        tax_rate=tax_pct / 100.0,
        intangible_life_years=life,
    )
    assumptions = {
        "cash_pct": cash_pct / 100.0,
        "debt_pct": debt_pct / 100.0,
        "stock_pct": stock_pct / 100.0,
        "pre_tax_synergies": synergy_bn * 1e9,
        "integration_cost": integration_bn * 1e9,
        "debt_interest_rate": debt_rate_pct / 100.0,
        "cash_yield": 0.03,
        "tax_rate": tax_pct / 100.0,
        "incremental_amortization": ppa.get("annual_intangible_amortization", 0.0),
        "debt_refinanced": target["debt"] * debt_refi_pct / 100.0,
        "transaction_fees": fees_bn * 1e9,
        "cash_available": max(0.0, _finite(facts.get("cash")) or 0.0),
    }
    result = accretion_dilution_case(facts, target, assumptions)
    if result.get("status") == "BLOCKED" and not result.get("funding"):
        st.error(f"Accretion model blocked: {', '.join(result.get('missing', []))}")
        return result
    if result.get("status") == "BLOCKED":
        st.error(
            f"Hard gate blocked: {', '.join(result.get('missing', []))}. "
            f"Cash funding exceeds available balance-sheet cash by {_money(result.get('cash_shortfall'), currency)}."
        )
    x1, x2, x3, x4, x5 = st.columns(5)
    x1.metric("Recurring EPS", _money(result.get("recurring_eps"), currency), _percent(result.get("eps_accretion")))
    x2.metric("Year-one EPS", _money(result.get("year_one_eps"), currency), _percent(result.get("year_one_eps_accretion")))
    x3.metric("FCF/share accretion", _percent(result.get("fcf_accretion")))
    x4.metric("PF net leverage", _multiple(result.get("net_leverage_reported")), "reported EBITDA")
    x5.metric("Synergy-adjusted leverage", _multiple(result.get("net_leverage_adjusted")))

    acquirer_scenarios = build_acquirer_scenario_comparison(facts, target, assumptions)
    scenario_figure = go.Figure()
    scenario_figure.add_trace(
        go.Bar(
            x=acquirer_scenarios["Scenario"],
            y=acquirer_scenarios["Recurring EPS accretion"],
            name="Recurring EPS",
            marker_color="#63d7e7",
        )
    )
    scenario_figure.add_trace(
        go.Bar(
            x=acquirer_scenarios["Scenario"],
            y=acquirer_scenarios["Year-one EPS accretion"],
            name="Year-one EPS",
            marker_color="#e5c36c",
        )
    )
    scenario_figure.add_hline(y=0, line_color="#ff8589", line_dash="dash")
    scenario_figure.update_layout(
        height=310,
        barmode="group",
        margin=dict(l=8, r=8, t=25, b=15),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color="#a9bdcb",
        legend={"orientation": "h", "y": 1.08},
        yaxis={"title": "EPS accretion / dilution", "tickformat": ".1%", "gridcolor": "rgba(130,160,180,.12)"},
    )
    st.plotly_chart(scenario_figure, width="stretch", config={"displayModeBar": False}, key=f"mna_acquirer_scenarios_{ticker}")
    with st.expander("Acquirer Bear / Base / Bull matrix", expanded=density == "Audit"):
        _dataframe(
            acquirer_scenarios,
            formats={
                "Target earnings factor": "{:.2f}x",
                "Target EBITDA factor": "{:.2f}x",
                "Cash funding": "{:.0%}",
                "Debt funding": "{:.0%}",
                "Stock funding": "{:.0%}",
                "Debt cost": "{:.1%}",
                "Run-rate synergies": "{:,.0f}",
                "Recurring EPS accretion": "{:+.1%}",
                "Year-one EPS accretion": "{:+.1%}",
                "FCF/share accretion": "{:+.1%}",
                "Net leverage": "{:.2f}x",
                "Synergy-adjusted leverage": "{:.2f}x",
                "Cash shortfall": "{:,.0f}",
            },
        )

    sources_uses = build_sources_uses_bridge(target, result)
    eps_bridge = build_eps_bridge(facts, target, result)
    identity_audit = validate_deal_identities(facts, target, result)
    visual_left, visual_right = st.columns(2)
    with visual_left:
        _render_waterfall(
            sources_uses,
            value_column="Bridge value",
            title="Sources & uses · no hidden plug",
            key=f"mna_sources_uses_{ticker}",
        )
    with visual_right:
        _render_waterfall(
            eps_bridge,
            value_column="Value",
            title="Net-income bridge underlying EPS",
            key=f"mna_eps_bridge_{ticker}",
        )
    hypotheses = [
        {
            "Hypothesis": "The deal is recurring EPS accretive.",
            "State": "PASS" if _finite(result.get("eps_accretion")) is not None and result.get("eps_accretion") >= 0 else "WATCH" if _finite(result.get("eps_accretion")) is not None else "BLOCKED",
            "Evidence": f"Recurring EPS accretion {_percent(result.get('eps_accretion'))}; year one {_percent(result.get('year_one_eps_accretion'))}.",
            "Falsifier": "Higher financing cost, lower target earnings or more issued shares turns the result dilutive.",
        },
        {
            "Hypothesis": "Pro forma leverage remains below 3.0x.",
            "State": "PASS" if _finite(result.get("net_leverage_reported")) is not None and result.get("net_leverage_reported") <= 3.0 else "WATCH",
            "Evidence": f"Reported {_multiple(result.get('net_leverage_reported'))}; synergy-adjusted {_multiple(result.get('net_leverage_adjusted'))}.",
            "Falsifier": "Debt funding, target debt or EBITDA downside pushes reported leverage above the threshold.",
        },
        {
            "Hypothesis": "Sources and uses reconcile without a hidden plug.",
            "State": "PASS" if abs(_finite(result.get("sources_uses_gap")) or 0.0) <= max(1.0, 1e-6 * abs(_finite(result.get("total_uses")) or 0.0)) else "BLOCKED",
            "Evidence": f"Sources less uses {_money(result.get('sources_uses_gap'), currency)}.",
            "Falsifier": "Any unmodelled fee, refinancing or award cash-out creates an unexplained funding gap.",
        },
        {
            "Hypothesis": "Balance-sheet cash can fund the modeled cash consideration.",
            "State": "PASS" if result.get("liquidity_ok") else "BLOCKED",
            "Evidence": f"Available cash {_money(result.get('cash_available'), currency)}; shortfall {_money(result.get('cash_shortfall'), currency)}.",
            "Falsifier": "Minimum cash, trapped cash, covenants or settlement timing reduce deployable liquidity.",
        },
    ]
    _hypothesis_board(hypotheses)

    st.markdown("##### Deleveraging trajectory")
    paydown_pct = st.slider(
        "Recurring pro forma FCF applied to annual debt paydown · %",
        0,
        100,
        50,
        5,
        key=f"mna_buy_paydown_{ticker}",
        help="Illustrative policy only; minimum cash, dividends and capex priorities are not inferred.",
    )
    annual_paydown = max(0.0, (_finite(result.get("recurring_free_cash_flow")) or 0.0) * paydown_pct / 100.0)
    leverage = build_leverage_trajectory(result, annual_paydown=annual_paydown, years=3)
    if not leverage.empty:
        figure = go.Figure()
        figure.add_trace(go.Bar(x=leverage["Year"], y=leverage["Net debt"], name="Net debt", marker_color="#284f68", yaxis="y"))
        figure.add_trace(go.Scatter(x=leverage["Year"], y=leverage["Reported leverage"], name="Reported leverage", mode="lines+markers", line={"color": "#e5c36c", "width": 3}, yaxis="y2"))
        figure.add_trace(go.Scatter(x=leverage["Year"], y=leverage["Synergy-adjusted leverage"], name="Synergy-adjusted", mode="lines+markers", line={"color": "#63d7e7", "width": 3, "dash": "dot"}, yaxis="y2"))
        figure.update_layout(
            height=350,
            margin=dict(l=8, r=8, t=30, b=15),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font_color="#a9bdcb",
            legend={"orientation": "h", "y": 1.10},
            yaxis={"title": f"Net debt · {currency}", "gridcolor": "rgba(130,160,180,.12)"},
            yaxis2={"title": "Net leverage", "overlaying": "y", "side": "right", "ticksuffix": "x", "showgrid": False},
        )
        st.plotly_chart(figure, width="stretch", config={"displayModeBar": False}, key=f"mna_leverage_path_{ticker}")

    st.markdown("##### Linked research-only PPA")
    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Provisional goodwill", _money(ppa.get("goodwill"), currency))
    q2.metric("FV identifiable net assets", _money(ppa.get("fair_value_net_assets"), currency))
    q3.metric("Deferred tax liability", _money(ppa.get("deferred_tax_liability"), currency))
    q4.metric("Annual amortization", _money(ppa.get("annual_intangible_amortization"), currency), "Linked to EPS")
    st.caption(f"{ppa.get('status')} · Research estimate only, not an audited ASC 805 or IFRS 3 allocation. The modeled amortization is included in recurring and year-one EPS.")

    if density == "Audit":
        with st.expander("Model identity audit", expanded=True):
            _dataframe(identity_audit, formats={"Expected": "{:,.4f}", "Actual": "{:,.4f}", "Gap": "{:,.4f}", "Tolerance": "{:,.4f}"})
            _dataframe(sources_uses[["Side", "Item", "Amount", "Bridge value"]], formats={"Amount": "{:,.0f}", "Bridge value": "{:,.0f}"})
            _dataframe(eps_bridge, formats={"Value": "{:,.0f}"})
            _dataframe(leverage, formats={"Net debt": "{:,.0f}", "Reported leverage": "{:.2f}x", "Synergy-adjusted leverage": "{:.2f}x", "Annual paydown": "{:,.0f}"})
            st.caption(
                f"Sources {_money(result.get('total_sources'), currency)} · uses {_money(result.get('total_uses'), currency)} · "
                f"gap {_money(result.get('sources_uses_gap'), currency)} · cash capacity {'PASS' if result.get('liquidity_ok') else 'BLOCKED'}."
            )
    ppa_payload = {f"ppa_{key}": value for key, value in ppa.items() if isinstance(value, (str, int, float, bool, type(None)))}
    return {
        **target,
        **assumptions,
        **ppa_payload,
        **{key: value for key, value in result.items() if isinstance(value, (str, int, float, bool, type(None)))},
    }


def _render_doww(
    facts: Mapping[str, Any],
    ticker: str,
    density: str,
    context: Mapping[str, Any],
) -> None:
    _section_heading(
        "DOWW · QNTM LOCAL",
        "Deal & Opportunity Watch Workbench",
        "Living target and acquirer cases with explicit assumptions, hard gates, linked valuation and immutable revisions.",
    )
    st.markdown(
        '<div class="mna-note"><b>QNTM local workflow.</b> DOWW could not be verified in public Bloomberg documentation as an analytical function. Here it is deliberately defined as the living M&A hypothesis, deal-model and scenario workspace.</div>',
        unsafe_allow_html=True,
    )
    scenario_comparison = build_scenario_comparison(facts)
    active_case = scenario_comparison[scenario_comparison["Scenario"].eq(str(context.get("scenario")))]
    if not active_case.empty:
        row = active_case.iloc[0]
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Active offer profile", str(row.get("Scenario")), _percent(row.get("Offer premium")))
        s2.metric("Profile offer price", _money(row.get("Offer price"), str(facts.get("currency"))))
        s3.metric("Profile transaction EV", _money(row.get("Transaction EV"), str(facts.get("currency"))))
        s4.metric("Profile synergy confidence", _percent(row.get("Synergy confidence")))
    with st.expander("Compare Bear / Base / Bull profiles", expanded=False):
        _dataframe(
            scenario_comparison,
            formats={
                "Offer premium": "{:.0%}",
                "Offer price": "{:,.2f}",
                "Transaction EV": "{:,.0f}",
                "EV / EBITDA": "{:.2f}x",
                "Synergy confidence": "{:.0%}",
                "Synergy NPV": "{:,.0f}",
                "Buyer retained value": "{:,.0f}",
                "DCF value / share": "{:,.2f}",
                "DCF upside / downside": "{:+.1%}",
                "WACC": "{:.1%}",
                "Terminal growth": "{:.1%}",
            },
        )
    lens = st.radio(
        "Transaction lens",
        ["Target / takeover screen", "Acquirer / accretion case"],
        horizontal=True,
        key=f"mna_deal_lens_{ticker}",
    )
    payload = _render_target_watch(facts, ticker, density) if lens.startswith("Target") else _render_acquirer_watch(facts, ticker, density)
    c1, c2 = st.columns([1, 2])
    lens_key = "target" if lens.startswith("Target") else "acquirer"
    label = c1.text_input(
        "Scenario label",
        value=f"{ticker} · {lens}",
        key=f"mna_scenario_label_{ticker}_{lens_key}",
    )
    if c1.button("Save governed snapshot", key=f"mna_save_scenario_{ticker}", width="stretch"):
        try:
            saved = _save_scenario(ticker, label, payload, {**dict(context), "lens": lens})
            st.success(f"Immutable revision #{saved.get('sequence')} saved · {str(saved.get('scenario_id'))[:8]}.")
        except ScenarioLedgerError as exc:
            st.error(f"Governed save blocked: {exc}")
    try:
        scenarios = load_scenarios(ticker)
        integrity = verify_ledger(ticker)
    except ScenarioLedgerError as exc:
        scenarios = []
        integrity = {"valid": False, "count": 0, "reason": str(exc), "head_hash": None}
        st.error(f"Scenario ledger unavailable: {exc}")
    integrity_tone = "mna-audit-ok" if integrity.get("valid") else "mna-block"
    c2.markdown(
        f'<div class="mna-mini"><b class="{integrity_tone}">Ledger {"VERIFIED" if integrity.get("valid") else "BLOCKED"}</b><br>{integrity.get("count", 0)} immutable revision(s) · head {escape(str(integrity.get("head_hash") or "GENESIS")[:12])}</div>',
        unsafe_allow_html=True,
    )
    if scenarios:
        c2.download_button(
            "Export verified scenario audit JSON",
            data=json.dumps(scenarios, indent=2, default=str),
            file_name=f"{ticker.lower()}_mna_scenarios.json",
            mime="application/json",
            key=f"mna_download_scenarios_{ticker}_{len(scenarios)}",
            width="stretch",
        )
        with st.expander(f"Append-only scenario ledger · {len(scenarios)} revision(s)", expanded=density == "Audit"):
            _dataframe(
                pd.DataFrame(
                    [
                        {
                            "Revision": item.get("sequence"),
                            "Scenario ID": str(item.get("scenario_id"))[:12],
                            "Label": item.get("label"),
                            "Lens": _mapping(item.get("context")).get("lens"),
                            "Profile": _mapping(item.get("context")).get("scenario"),
                            "Owner": item.get("owner"),
                            "Review status": item.get("review_status"),
                            "Saved at": item.get("saved_at"),
                            "Record hash": str(item.get("record_hash"))[:16],
                        }
                        for item in scenarios
                    ]
                )
            )
            st.caption("Append-only: revisions are never edited or deleted. Any byte-level change breaks the SHA-256 chain and blocks the next save.")


def _render_bi(facts: Mapping[str, Any], density: str) -> None:
    _section_heading(
        "BI · SOURCED INTELLIGENCE",
        "Company, sector & deal evidence center",
        "Current public or licensed provider evidence; no Bloomberg Intelligence research or proprietary taxonomy is reproduced.",
    )
    company = _mapping(facts.get("company"))
    inst = _mapping(company.get("institutional"))
    what_changed = _mapping(inst.get("what_changed"))
    table = _frame(what_changed.get("table"))
    summary = _mapping(what_changed.get("summary"))
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Evidence bias", str(summary.get("bias") or "N/A"))
    c2.metric("Material observations", str(summary.get("material", 0)))
    c3.metric("Structural risks", str(summary.get("structural_risks", 0)))
    c4.metric("Evidence confidence", f"{_finite(summary.get('confidence')):.0f}/100" if _finite(summary.get("confidence")) is not None else "N/A")

    relationships = _mapping(inst.get("relationships"))
    rel_summary = _mapping(relationships.get("summary"))
    overlay = _mapping(inst.get("overlay"))
    st.markdown(
        f"""
<div class="mna-grid">
  <div class="mna-card"><div class="k">Industry structure</div><h4>{escape(str(facts.get('sector')))} · {escape(str(facts.get('industry')))}</h4><p>Current company and peer evidence; no proprietary industry forecast is inferred.</p></div>
  <div class="mna-card"><div class="k">Dependency map</div><h4>Customer {escape(_percent(rel_summary.get('max_customer_concentration')))}</h4><p>Largest explicit supplier {escape(_percent(rel_summary.get('max_supplier_concentration')))} · single-source flags {escape(str(rel_summary.get('single_source_count', 'N/A')))}.</p></div>
  <div class="mna-card"><div class="k">Institutional overlay</div><h4>{escape(str(round(_finite(overlay.get('score')) or 0)) if _finite(overlay.get('score')) is not None else 'N/A')}/100</h4><p>Coverage {escape(_percent((_finite(overlay.get('coverage')) or 0) / 100.0) if _finite(overlay.get('coverage')) is not None else 'N/A')} · kept separate from transaction valuation.</p></div>
</div>
""",
        unsafe_allow_html=True,
    )
    st.markdown("##### Evidence timeline")
    if table.empty:
        st.info("No material delta table is available; BI remains evidence-pending.")
    else:
        filtered = table.copy(deep=True)
        if density != "Executive":
            f1, f2 = st.columns(2)
            if "Class" in filtered.columns:
                classes = sorted(filtered["Class"].dropna().astype(str).unique().tolist())
                selected_classes = f1.multiselect("Evidence classes", classes, default=classes, key=f"mna_bi_classes_{facts.get('ticker')}")
                filtered = filtered[filtered["Class"].astype(str).isin(selected_classes)]
            if "Direction" in filtered.columns:
                directions = sorted(filtered["Direction"].dropna().astype(str).unique().tolist())
                selected_directions = f2.multiselect("Directions", directions, default=directions, key=f"mna_bi_directions_{facts.get('ticker')}")
                filtered = filtered[filtered["Direction"].astype(str).isin(selected_directions)]
        if {"Materiality", "Confidence"}.issubset(filtered.columns) and not filtered.empty:
            chart_frame = filtered.copy(deep=True)
            chart_frame["Materiality"] = pd.to_numeric(chart_frame["Materiality"], errors="coerce")
            chart_frame["Confidence"] = pd.to_numeric(chart_frame["Confidence"], errors="coerce")
            chart_frame = chart_frame.dropna(subset=["Materiality", "Confidence"])
            if not chart_frame.empty:
                figure = go.Figure()
                direction_series = chart_frame.get("Direction", pd.Series("Evidence", index=chart_frame.index)).astype(str)
                for direction, group in chart_frame.groupby(direction_series, sort=False):
                    figure.add_trace(
                        go.Scatter(
                            x=group["Confidence"],
                            y=group["Materiality"],
                            text=group.get("Dimension", pd.Series("Evidence", index=group.index)).astype(str),
                            customdata=group.get("Detail", pd.Series("", index=group.index)).astype(str).to_numpy(),
                            mode="markers",
                            marker={"size": 13, "opacity": 0.78},
                            name=str(direction),
                            hovertemplate="%{text}<br>Confidence %{x:.0f}<br>Materiality %{y:.0f}<br>%{customdata}<extra></extra>",
                        )
                    )
                figure.update_layout(
                    height=330,
                    margin=dict(l=8, r=8, t=25, b=20),
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font_color="#a9bdcb",
                    legend={"orientation": "h", "y": 1.08},
                    xaxis={"title": "Evidence confidence", "range": [0, 105], "gridcolor": "rgba(130,160,180,.12)"},
                    yaxis={"title": "Materiality", "range": [0, 105], "gridcolor": "rgba(130,160,180,.12)"},
                )
                st.plotly_chart(figure, width="stretch", config={"displayModeBar": False}, key=f"mna_bi_map_{facts.get('ticker')}")
        display = filtered[[column for column in ("Class", "Dimension", "Window", "Direction", "Materiality", "Signal", "Detail", "Confidence", "Source") if column in filtered.columns]]
        if density == "Executive":
            display = display.head(10)
        _dataframe(display, height=440)

    sentiment = _mapping(company.get("sentiment"))
    news = _frame(sentiment.get("news_table"))
    if not news.empty:
        with st.expander("Current news evidence", expanded=False):
            _dataframe(news.head(20), height=360)
    with st.expander("BI evidence boundaries", expanded=density == "Audit"):
        st.markdown(
            "- Facts and provider observations are separated from derived transaction scenarios.\n"
            "- No deal probability, antitrust outcome or management intention is inferred from missing evidence.\n"
            "- Point-in-time precedent transactions, licensed consensus history and analyst-authored industry research remain outside the current public-data contract."
        )


def render_mna_workbench(ticker: str, analysis: Mapping[str, Any]) -> None:
    """Render the complete M&A command deck inside Company Intelligence."""
    _inject_css()
    facts = extract_mna_facts(ticker, analysis)
    _hero(facts)
    normalized_ticker = str(facts.get("ticker"))
    rail, canvas = st.columns([0.22, 0.78], gap="large")
    with rail:
        st.markdown('<div class="mna-rail-label">Command rail</div>', unsafe_allow_html=True)
        command = st.radio(
            "M&A command workflow",
            [
                "DES · Company 360",
                "RV · Relative Value",
                "FA · Financial Analysis",
                "DOWW · Deal Watch",
                "BI · Intelligence",
            ],
            horizontal=False,
            key=f"mna_command_{normalized_ticker}",
            label_visibility="collapsed",
        )
        st.markdown('<div class="mna-rail-label">Live case</div>', unsafe_allow_html=True)
        scenario = st.selectbox(
            "Scenario profile",
            ["Bear", "Base", "Bull"],
            index=1,
            key=f"mna_ctx_scenario_{normalized_ticker}",
        )
        density = st.selectbox(
            "Information density",
            ["Executive", "Analyst", "Audit"],
            index=1,
            key=f"mna_ctx_density_{normalized_ticker}",
        )
        _sync_scenario_defaults(normalized_ticker, facts, scenario)
        coverage = _finite(facts.get("coverage")) or 0.0
        anchor = st.session_state.get(f"mna_ctx_anchor_{normalized_ticker}", "Standalone market price")
        st.markdown(
            f'<div class="mna-mini"><b>{escape(scenario)} · {escape(density)}</b><br>Evidence {coverage:.0f}%<br>Anchor: {escape(str(anchor))}<br><br><span class="mna-audit-warn">RESEARCH_ONLY</span></div>',
            unsafe_allow_html=True,
        )
    with canvas:
        context = _render_context_editor(facts, normalized_ticker, scenario, density)
        _render_context_ribbon(context)
        if command.startswith("DES"):
            _render_des(facts, density)
        elif command.startswith("RV"):
            _render_rv(facts, normalized_ticker, density, context)
        elif command.startswith("FA"):
            _render_fa(facts, normalized_ticker, density)
        elif command.startswith("DOWW"):
            _render_doww(facts, normalized_ticker, density, context)
        else:
            _render_bi(facts, density)


__all__ = [
    "MNA_VERSION",
    "RESEARCH_ONLY",
    "SCENARIO_PROFILES",
    "accretion_dilution_case",
    "build_acquirer_scenario_comparison",
    "build_eps_bridge",
    "build_football_field",
    "build_leverage_trajectory",
    "build_peer_scatter",
    "build_scenario_comparison",
    "build_sources_uses_bridge",
    "build_synergy_ramp",
    "dcf_sensitivity_table",
    "dcf_valuation",
    "enterprise_value_bridge",
    "extract_mna_facts",
    "filter_peer_universe",
    "relative_valuation_ranges",
    "render_mna_workbench",
    "reverse_dcf_growth",
    "screening_gates",
    "simplified_ppa",
    "synergy_npv",
    "target_deal_case",
    "validate_deal_identities",
]
