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

from datetime import datetime, timezone
from html import escape
import json
import math
from typing import Any, Mapping, Sequence

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .common import fmt_large_number, safe_float


MNA_VERSION = "M&A LAB · 8.0"
RESEARCH_ONLY = "RESEARCH_ONLY · HUMAN REVIEW REQUIRED"


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
        "fcf_margin": _first_number(_first_scalar(balance, "fcf_margin"), free_cash_flow / revenue if free_cash_flow is not None and revenue not in (None, 0) else None),
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
    npv = -integration
    pre_tax_run_rate = cost + revenue * margin
    for year, factor in enumerate(normalized_ramp, start=1):
        cash_flow = pre_tax_run_rate * factor * probability_value * (1.0 - tax)
        cash_flows.append(cash_flow)
        npv += cash_flow / ((1.0 + discount) ** year)
    return {
        "status": "READY_FOR_HUMAN_REVIEW",
        "npv": npv,
        "cash_flows": cash_flows,
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
    weights = {key: value / total_weight for key, value in weights.items()}
    equity_value = required_target["equity_value"]
    funding = {key: equity_value * weight for key, weight in weights.items()}
    sources_uses_gap = sum(funding.values()) - equity_value

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

    pf_gross_debt = required_acquirer["debt"] + required_target["debt"] + funding["debt"]
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
    identity_tolerance = max(1.0, 1e-6 * abs(equity_value))
    identity_ok = abs(sources_uses_gap) <= identity_tolerance
    return {
        "status": "READY_FOR_HUMAN_REVIEW" if identity_ok else "BLOCKED",
        "publishable": identity_ok,
        "missing": [],
        "weights": weights,
        "funding": funding,
        "sources_uses_gap": sources_uses_gap,
        "target_ev": target_ev,
        "new_shares": new_shares,
        "proforma_shares": proforma_shares,
        "standalone_eps": standalone_eps,
        "recurring_eps": recurring_eps,
        "year_one_eps": year_one_eps,
        "eps_accretion": eps_accretion,
        "year_one_eps_accretion": year_one_accretion,
        "standalone_fcf_per_share": standalone_fcf_share,
        "recurring_fcf_per_share": recurring_fcf_share,
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


def _inject_css() -> None:
    st.markdown(
        """
<style>
.mna-shell{margin:2px 0 14px;padding:22px 24px;border:1px solid rgba(103,181,204,.28);border-radius:18px;background:radial-gradient(circle at 88% 12%,rgba(49,199,212,.14),transparent 30%),linear-gradient(135deg,#0c2130,#06131e 58%,#091826);box-shadow:0 22px 56px rgba(0,0,0,.24)}
.mna-top{display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap}.mna-code{color:#e5c36c;font-size:.62rem;letter-spacing:.20em;text-transform:uppercase;font-weight:900}.mna-policy{padding:5px 9px;border:1px solid rgba(104,214,154,.28);border-radius:999px;color:#9ce6bb;font-size:.58rem;letter-spacing:.11em;text-transform:uppercase;font-weight:900}.mna-title{margin-top:17px;color:#f6f9fb;font:800 clamp(1.8rem,3.5vw,2.8rem)/1.05 Georgia,serif}.mna-title span{color:#65d7e7}.mna-sub{margin-top:7px;color:#91a9bb;font-size:.75rem;line-height:1.5;max-width:920px}.mna-strip{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;margin-top:18px}.mna-stat{padding:11px 12px;border:1px solid rgba(121,162,190,.20);border-radius:11px;background:rgba(7,22,34,.76)}.mna-stat .k{font-size:.54rem;letter-spacing:.15em;text-transform:uppercase;color:#7991a5;font-weight:900}.mna-stat .v{font:800 1.16rem Georgia,serif;color:#f1f6f9;margin-top:5px}.mna-stat .s{font-size:.59rem;color:#7890a3;margin-top:3px}.mna-note{padding:13px 15px;border-left:3px solid #e5c36c;border-radius:8px;background:rgba(229,195,108,.07);color:#b3c1cc;font-size:.72rem;line-height:1.55}.mna-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;margin:10px 0}.mna-card{padding:14px;border:1px solid rgba(121,162,190,.19);border-radius:13px;background:linear-gradient(145deg,rgba(10,31,45,.86),rgba(5,17,27,.90))}.mna-card .k{font-size:.55rem;letter-spacing:.15em;text-transform:uppercase;color:#e5c36c;font-weight:900}.mna-card h4{font:800 1rem Georgia,serif;color:#eef5fa;margin:7px 0}.mna-card p{font-size:.70rem;color:#94aabc;line-height:1.5;margin:0}.mna-pass{color:#68d69a}.mna-watch{color:#e5c36c}.mna-block{color:#ff7c80}
[class*="st-key-mna_command_"] div[role="radiogroup"]{display:flex;flex-wrap:wrap;gap:7px;padding:8px;border:1px solid rgba(121,162,190,.20);border-radius:14px;background:rgba(5,16,26,.80)}[class*="st-key-mna_command_"] div[role="radiogroup"] label{min-height:40px;padding:7px 12px!important;border:1px solid transparent;border-radius:9px;background:rgba(13,35,50,.68)}[class*="st-key-mna_command_"] div[role="radiogroup"] label:has(input:checked){border-color:rgba(99,215,231,.55);background:rgba(36,120,140,.22)}
@media(max-width:900px){.mna-shell{padding:18px}.mna-strip{grid-template-columns:repeat(2,minmax(0,1fr))}.mna-grid{grid-template-columns:1fr}}
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


def _render_des(facts: Mapping[str, Any]) -> None:
    st.markdown("#### DES · Company & transaction description")
    st.caption("Independent Company 360 workflow. Identity resolution, business profile, capital structure and screening evidence.")
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
        bridge_df = pd.DataFrame([{"Bridge item": key, "Value": value} for key, value in components.items()])
        bridge_df.loc[len(bridge_df)] = {"Bridge item": "Derived enterprise value", "Value": bridge.get("enterprise_value")}
        _dataframe(bridge_df, formats={"Value": "{:,.0f}"})
    else:
        st.warning("EV bridge blocked: equity value, debt and cash are required.")

    st.markdown("##### Transaction screening gates")
    _dataframe(screening_gates(facts))
    with st.expander("Evidence contract · field-level audit", expanded=False):
        _dataframe(_frame(facts.get("evidence")), formats={"Value": "{:,.2f}"})
        gap = _finite(facts.get("ev_reconciliation_gap"))
        if gap is not None:
            st.caption(f"Observed-versus-derived EV reconciliation gap: {_money(gap, str(facts.get('currency')))}.")


def _render_rv(facts: Mapping[str, Any]) -> None:
    st.markdown("#### RV · Relative valuation & offer range")
    st.caption("Current comparable-company snapshot. It is not point-in-time precedent-transaction evidence.")
    company = _mapping(facts.get("company"))
    inst = _mapping(company.get("institutional"))
    peer = _mapping(inst.get("peer_intelligence"))
    peer_table = _frame(peer.get("table"))
    summary = _frame(peer.get("summary"))
    ranges = relative_valuation_ranges(facts, peer_table)

    if peer_table.empty:
        st.warning("Comparable universe is unavailable. No quartile is manufactured from missing peers.")
    else:
        columns = [
            column
            for column in ("Symbol", "Company", "Peer Type", "Similarity", "Revenue Growth", "EBITDA Margin", "Operating Margin", "FCF Margin", "ROIC", "P/E TTM", "Forward P/E", "EV/Sales", "EV/EBITDA", "Source")
            if column in peer_table.columns
        ]
        _dataframe(peer_table[columns], height=420)
    if not summary.empty:
        with st.expander("Peer median, percentile and premium audit", expanded=False):
            _dataframe(summary, formats={"Target": "{:.2f}", "Peer Median": "{:.2f}", "Target Percentile": "{:.1f}", "Premium / Discount": "{:.1%}"})

    st.markdown("##### Implied standalone valuation range")
    if not ranges.empty:
        _dataframe(
            ranges,
            formats={"Reference multiple": "{:.2f}x", "Implied EV": "{:,.0f}", "Implied equity": "{:,.0f}", "Implied price": "{:,.2f}", "Upside / downside": "{:+.1%}"},
        )
        chart = ranges[ranges["Statistic"].eq("Median")].dropna(subset=["Implied price"])
        if not chart.empty:
            figure = go.Figure()
            figure.add_trace(go.Bar(x=chart["Implied price"], y=chart["Method"], orientation="h", marker_color="#63d7e7", name="Peer median implied price"))
            if _finite(facts.get("price")) is not None:
                figure.add_vline(x=facts.get("price"), line_dash="dash", line_color="#e5c36c", annotation_text="Current price")
            figure.update_layout(height=280, margin=dict(l=10, r=10, t=25, b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#a9bdcb", showlegend=False)
            st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})
    else:
        st.info("At least four valid current peers per metric are required for an implied range.")

    premiums = []
    for premium in (0.0, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60):
        case = target_deal_case(facts, {"premium": premium})
        premiums.append(
            {
                "Premium": premium,
                "Offer price": case.get("offer_price"),
                "Equity purchase price": case.get("offer_equity_value"),
                "Transaction EV": case.get("transaction_ev"),
                "EV / Revenue": case.get("ev_revenue"),
                "EV / EBITDA": case.get("ev_ebitda"),
                "P / E": case.get("price_earnings"),
            }
        )
    st.markdown("##### Control-premium ladder")
    _dataframe(pd.DataFrame(premiums), formats={"Premium": "{:.0%}", "Offer price": "{:,.2f}", "Equity purchase price": "{:,.0f}", "Transaction EV": "{:,.0f}", "EV / Revenue": "{:.2f}x", "EV / EBITDA": "{:.2f}x", "P / E": "{:.2f}x"})


def _render_fa(facts: Mapping[str, Any], ticker: str) -> None:
    st.markdown("#### FA · Financial analysis, DCF & reverse DCF")
    st.caption("Reported history and deterministic valuation remain separate from editable analyst assumptions.")
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
        implied_growth = reverse_dcf_growth(facts, assumptions)
        if implied_growth is None:
            st.warning("Reverse DCF is infeasible inside the documented -50% to +150% growth bracket.")
        else:
            st.info(f"Reverse DCF: the current price implies approximately {implied_growth:.1%} initial FCF growth under the active WACC and terminal assumptions.")
        with st.expander("DCF cash-flow bridge", expanded=False):
            _dataframe(_frame(result.get("forecast")), formats={"Growth": "{:.1%}", "FCF": "{:,.0f}", "Present Value": "{:,.0f}"})
        st.markdown("##### WACC × terminal-growth sensitivity · value per share")
        sensitivity = dcf_sensitivity_table(facts, assumptions)
        indexed = sensitivity.copy()
        indexed["WACC"] = indexed["WACC"].map(lambda value: f"{value:.1%}")
        _dataframe(indexed, formats={column: "{:,.2f}" for column in indexed.columns if column != "WACC"})
    with st.expander("Reported financial statements", expanded=False):
        for label, frame in _mapping(facts.get("raw_frames")).items():
            st.markdown(f"**{label}**")
            if isinstance(frame, pd.DataFrame) and not frame.empty:
                st.dataframe(frame, width="stretch", height=300)
            else:
                st.caption("Unavailable")


def _save_scenario(ticker: str, label: str, payload: Mapping[str, Any]) -> None:
    key = f"mna_saved_scenarios_{ticker}"
    snapshots = st.session_state.setdefault(key, [])
    snapshots.append(
        {
            "label": label,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "policy": RESEARCH_ONLY,
            "payload": {key: value for key, value in payload.items() if isinstance(value, (str, int, float, bool, type(None)))},
        }
    )


def _hypothesis_board(rows: Sequence[Mapping[str, Any]]) -> None:
    cards = []
    for row in rows:
        state = str(row.get("State") or "BLOCKED")
        tone = "mna-pass" if state == "PASS" else "mna-watch" if state == "WATCH" else "mna-block"
        cards.append(
            f'<div class="mna-card"><div class="k {tone}">{escape(state)}</div><h4>{escape(str(row.get("Hypothesis")))}</h4><p>{escape(str(row.get("Evidence")))}<br><br><b>Falsifier:</b> {escape(str(row.get("Falsifier")))}</p></div>'
        )
    st.markdown(f'<div class="mna-grid">{"".join(cards)}</div>', unsafe_allow_html=True)


def _render_target_watch(facts: Mapping[str, Any], ticker: str) -> dict[str, Any]:
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
    assumptions = {
        "premium": premium,
        "discount_rate": discount_rate,
        "tax_rate": tax_rate,
        "synergy_probability": probability,
        "cost_synergy_run_rate": cost_synergy_bn * 1e9,
        "revenue_synergy_run_rate": revenue_synergy_bn * 1e9,
        "contribution_margin": contribution_margin,
        "integration_cost": integration_bn * 1e9,
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
    with st.expander("Transaction EV bridge & synergy cash flows", expanded=False):
        bridge = _mapping(result.get("bridge"))
        _dataframe(pd.DataFrame([{"Item": key, "Value": value} for key, value in _mapping(bridge.get("components")).items()]), formats={"Value": "{:,.0f}"})
        cash_flows = list(_mapping(result.get("synergy")).get("cash_flows") or [])
        if cash_flows:
            _dataframe(pd.DataFrame({"Year": range(1, len(cash_flows) + 1), "Risk-adjusted after-tax synergy FCF": cash_flows}), formats={"Risk-adjusted after-tax synergy FCF": "{:,.0f}"})
    return {**assumptions, **{key: value for key, value in result.items() if isinstance(value, (str, int, float, bool, type(None)))}}


def _render_acquirer_watch(facts: Mapping[str, Any], ticker: str) -> dict[str, Any]:
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

    target = {
        "equity_value": target_equity_bn * 1e9,
        "debt": target_debt_bn * 1e9,
        "cash": target_cash_bn * 1e9,
        "ebitda": target_ebitda_bn * 1e9,
        "net_income": target_ni_bn * 1e9,
        "free_cash_flow": target_fcf_bn * 1e9,
    }
    assumptions = {
        "cash_pct": cash_pct / 100.0,
        "debt_pct": debt_pct / 100.0,
        "stock_pct": stock_pct / 100.0,
        "pre_tax_synergies": synergy_bn * 1e9,
        "integration_cost": integration_bn * 1e9,
        "debt_interest_rate": debt_rate_pct / 100.0,
        "cash_yield": 0.03,
        "tax_rate": tax_pct / 100.0,
        "incremental_amortization": 0.0,
    }
    result = accretion_dilution_case(facts, target, assumptions)
    if result.get("status") == "BLOCKED":
        st.error(f"Accretion model blocked: {', '.join(result.get('missing', []))}")
        return result
    x1, x2, x3, x4, x5 = st.columns(5)
    x1.metric("Recurring EPS", _money(result.get("recurring_eps"), currency), _percent(result.get("eps_accretion")))
    x2.metric("Year-one EPS", _money(result.get("year_one_eps"), currency), _percent(result.get("year_one_eps_accretion")))
    x3.metric("FCF/share accretion", _percent(result.get("fcf_accretion")))
    x4.metric("PF net leverage", _multiple(result.get("net_leverage_reported")), "reported EBITDA")
    x5.metric("Synergy-adjusted leverage", _multiple(result.get("net_leverage_adjusted")))

    sources_uses = pd.DataFrame(
        [
            {"Type": "Use", "Item": "Target equity purchase price", "Value": target["equity_value"]},
            {"Type": "Source", "Item": "Acquirer cash", "Value": result.get("funding", {}).get("cash")},
            {"Type": "Source", "Item": "New debt", "Value": result.get("funding", {}).get("debt")},
            {"Type": "Source", "Item": "Stock consideration", "Value": result.get("funding", {}).get("stock")},
            {"Type": "Reconciliation", "Item": "Sources less uses", "Value": result.get("sources_uses_gap")},
        ]
    )
    _dataframe(sources_uses, formats={"Value": "{:,.0f}"})
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
            "State": "PASS" if result.get("publishable") else "BLOCKED",
            "Evidence": f"Sources less uses {_money(result.get('sources_uses_gap'), currency)}.",
            "Falsifier": "Any unmodelled fee, refinancing or award cash-out creates an unexplained funding gap.",
        },
    ]
    _hypothesis_board(hypotheses)

    with st.expander("Research-only purchase price allocation", expanded=False):
        p1, p2, p3, p4 = st.columns(4)
        book_equity_bn = p1.number_input("Target book equity · bn", value=float(max(0.0, target_equity_bn * 0.35)), step=0.1, key=f"mna_ppa_book_{ticker}")
        intangibles_bn = p2.number_input("Identifiable intangible step-up · bn", min_value=0.0, value=float(target_equity_bn * 0.15), step=0.1, key=f"mna_ppa_intangibles_{ticker}")
        ppe_bn = p3.number_input("PP&E step-up · bn", value=0.0, step=0.1, key=f"mna_ppa_ppe_{ticker}")
        life = p4.number_input("Intangible life · years", min_value=1.0, max_value=30.0, value=10.0, step=1.0, key=f"mna_ppa_life_{ticker}")
        ppa = simplified_ppa(
            consideration=target["equity_value"],
            target_book_equity=book_equity_bn * 1e9,
            identifiable_intangibles_step_up=intangibles_bn * 1e9,
            ppe_step_up=ppe_bn * 1e9,
            tax_rate=tax_pct / 100.0,
            intangible_life_years=life,
        )
        q1, q2, q3, q4 = st.columns(4)
        q1.metric("Provisional goodwill", _money(ppa.get("goodwill"), currency))
        q2.metric("FV identifiable net assets", _money(ppa.get("fair_value_net_assets"), currency))
        q3.metric("Deferred tax liability", _money(ppa.get("deferred_tax_liability"), currency))
        q4.metric("Annual amortization", _money(ppa.get("annual_intangible_amortization"), currency), str(ppa.get("status")))
        st.caption("This bridge is a research estimate, not an audited ASC 805 or IFRS 3 allocation.")
    return {**target, **assumptions, **{key: value for key, value in result.items() if isinstance(value, (str, int, float, bool, type(None)))}}


def _render_doww(facts: Mapping[str, Any], ticker: str) -> None:
    st.markdown("#### DOWW · Deal & Opportunity Watch Workbench")
    st.markdown(
        '<div class="mna-note"><b>QNTM local workflow.</b> DOWW could not be verified in public Bloomberg documentation as an analytical function. Here it is deliberately defined as the living M&A hypothesis, deal-model and scenario workspace.</div>',
        unsafe_allow_html=True,
    )
    lens = st.radio(
        "Transaction lens",
        ["Target / takeover screen", "Acquirer / accretion case"],
        horizontal=True,
        key=f"mna_deal_lens_{ticker}",
    )
    payload = _render_target_watch(facts, ticker) if lens.startswith("Target") else _render_acquirer_watch(facts, ticker)
    c1, c2 = st.columns([1, 2])
    label = c1.text_input("Scenario label", value=f"{ticker} · {lens}", key=f"mna_scenario_label_{ticker}")
    if c1.button("Save governed snapshot", key=f"mna_save_scenario_{ticker}", width="stretch"):
        _save_scenario(ticker, label, payload)
        st.success("Scenario saved in the current research session.")
    scenarios = st.session_state.get(f"mna_saved_scenarios_{ticker}", [])
    if scenarios:
        c2.download_button(
            "Export scenario audit JSON",
            data=json.dumps(scenarios, indent=2, default=str),
            file_name=f"{ticker.lower()}_mna_scenarios.json",
            mime="application/json",
            key=f"mna_download_scenarios_{ticker}_{len(scenarios)}",
            width="stretch",
        )
        with st.expander(f"Saved scenario ledger · {len(scenarios)}", expanded=False):
            _dataframe(pd.DataFrame([{"Label": item.get("label"), "Saved at": item.get("saved_at"), "Policy": item.get("policy")} for item in scenarios]))


def _render_bi(facts: Mapping[str, Any]) -> None:
    st.markdown("#### BI · Sourced company, sector & deal intelligence")
    st.caption("Independent evidence center using the current public/licensed provider bundle; it does not reproduce Bloomberg Intelligence research.")
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
        display = table[[column for column in ("Class", "Dimension", "Window", "Direction", "Materiality", "Signal", "Detail", "Confidence", "Source") if column in table.columns]]
        _dataframe(display, height=440)

    sentiment = _mapping(company.get("sentiment"))
    news = _frame(sentiment.get("news_table"))
    if not news.empty:
        with st.expander("Current news evidence", expanded=False):
            _dataframe(news.head(20), height=360)
    with st.expander("BI evidence boundaries", expanded=False):
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
    command = st.radio(
        "M&A command workflow",
        [
            "DES · Company 360",
            "RV · Relative Value",
            "FA · Financial Analysis",
            "DOWW · Deal Watch",
            "BI · Intelligence",
        ],
        horizontal=True,
        key=f"mna_command_{facts.get('ticker')}",
        label_visibility="collapsed",
    )
    if command.startswith("DES"):
        _render_des(facts)
    elif command.startswith("RV"):
        _render_rv(facts)
    elif command.startswith("FA"):
        _render_fa(facts, str(facts.get("ticker")))
    elif command.startswith("DOWW"):
        _render_doww(facts, str(facts.get("ticker")))
    else:
        _render_bi(facts)


__all__ = [
    "MNA_VERSION",
    "RESEARCH_ONLY",
    "accretion_dilution_case",
    "dcf_sensitivity_table",
    "dcf_valuation",
    "enterprise_value_bridge",
    "extract_mna_facts",
    "relative_valuation_ranges",
    "render_mna_workbench",
    "reverse_dcf_growth",
    "screening_gates",
    "simplified_ppa",
    "synergy_npv",
    "target_deal_case",
]
