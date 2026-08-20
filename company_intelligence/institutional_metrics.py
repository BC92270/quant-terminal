"""Shared institutional metrics and evidence-quality primitives.

V2.4.1 centralizes definitions that previously drifted across workspaces:
* ROIC calculation
* data-confidence scoring
* institutional overlay composition

The module intentionally contains no provider/network code so it can be reused by
Peer Intelligence, Capital Allocation, Institutional Overview and tests without
creating import cycles.
"""
from __future__ import annotations

from typing import Any, Mapping
import math


def _num(value: Any) -> float | None:
    try:
        if value is None:
            return None
        value = float(value)
        if not math.isfinite(value):
            return None
        return value
    except Exception:
        return None


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def normalized_tax_rate(
    pretax_income: Any,
    tax_expense: Any,
    default: float = 0.21,
    low: float = 0.0,
    high: float = 0.40,
) -> float:
    """Return a bounded effective tax rate for NOPAT calculations."""
    pretax = _num(pretax_income)
    tax = _num(tax_expense)
    if pretax is None or tax is None or pretax <= 0:
        return float(default)
    candidate = tax / pretax
    if not math.isfinite(candidate):
        return float(default)
    return max(low, min(high, float(candidate)))


def invested_capital(
    debt: Any,
    equity: Any,
    cash: Any,
    direct_invested_capital: Any = None,
) -> float | None:
    """Canonical invested-capital denominator used throughout Company Intelligence.

    Preferred provider-reported invested capital is accepted when positive. Otherwise:

        invested capital = total debt + shareholders' equity - cash & equivalents

    The same definition is used in both TTM and fiscal-year ROIC variants.
    """
    direct = _num(direct_invested_capital)
    if direct is not None and direct > 0:
        return direct

    eq = _num(equity)
    if eq is None:
        return None
    d = _num(debt) or 0.0
    c = _num(cash) or 0.0
    result = d + eq - c
    return result if result > 0 else None


def calculate_roic_audit(
    *,
    operating_income: Any,
    pretax_income: Any = None,
    tax_expense: Any = None,
    current_debt: Any = None,
    current_equity: Any = None,
    current_cash: Any = None,
    prior_debt: Any = None,
    prior_equity: Any = None,
    prior_cash: Any = None,
    current_invested_capital: Any = None,
    prior_invested_capital: Any = None,
    default_tax_rate: float = 0.21,
) -> dict[str, float | None]:
    """Return the canonical ROIC result together with its auditable bridge.

    This is deliberately the *same* calculation used by :func:`calculate_roic`; the
    helper only exposes the intermediate values so unusually high/low ROIC figures can
    be inspected directly in the UI.
    """
    op = _num(operating_income)
    if op is None:
        return {
            "roic": None, "operating_income": None, "tax_rate": None, "nopat": None,
            "current_invested_capital": None, "prior_invested_capital": None,
            "average_invested_capital": None,
        }

    tax_rate = normalized_tax_rate(
        pretax_income,
        tax_expense,
        default=default_tax_rate,
    )
    nopat = op * (1.0 - tax_rate)

    current_ic = invested_capital(
        current_debt,
        current_equity,
        current_cash,
        current_invested_capital,
    )
    prior_ic = invested_capital(
        prior_debt,
        prior_equity,
        prior_cash,
        prior_invested_capital,
    )
    avg_ic = None
    if current_ic is not None:
        avg_ic = (current_ic + prior_ic) / 2.0 if prior_ic is not None else current_ic

    roic = None
    if avg_ic is not None and avg_ic > 0:
        candidate = nopat / avg_ic
        roic = candidate if math.isfinite(candidate) else None

    return {
        "roic": roic,
        "operating_income": op,
        "tax_rate": tax_rate,
        "nopat": nopat,
        "current_invested_capital": current_ic,
        "prior_invested_capital": prior_ic,
        "average_invested_capital": avg_ic,
    }


def calculate_roic(
    *,
    operating_income: Any,
    pretax_income: Any = None,
    tax_expense: Any = None,
    current_debt: Any = None,
    current_equity: Any = None,
    current_cash: Any = None,
    prior_debt: Any = None,
    prior_equity: Any = None,
    prior_cash: Any = None,
    current_invested_capital: Any = None,
    prior_invested_capital: Any = None,
    default_tax_rate: float = 0.21,
) -> float | None:
    """Canonical ROIC implementation.

    Formula
    -------
    NOPAT = Operating Income × (1 - normalized effective tax rate)
    ROIC  = NOPAT / average invested capital

    Average invested capital uses current and prior observations when both exist;
    otherwise the current observation is used. The caller is responsible for labeling
    the temporal basis (e.g. TTM or FY).
    """
    return calculate_roic_audit(
        operating_income=operating_income,
        pretax_income=pretax_income,
        tax_expense=tax_expense,
        current_debt=current_debt,
        current_equity=current_equity,
        current_cash=current_cash,
        prior_debt=prior_debt,
        prior_equity=prior_equity,
        prior_cash=prior_cash,
        current_invested_capital=current_invested_capital,
        prior_invested_capital=prior_invested_capital,
        default_tax_rate=default_tax_rate,
    )["roic"]


def calculate_data_confidence(
    field_presence: Mapping[str, Any] | None,
    *,
    source_quality: float,
    freshness: float = 0.80,
    cross_validation: float = 0.50,
    weights: tuple[float, float, float, float] = (0.45, 0.25, 0.15, 0.15),
) -> dict[str, float]:
    """Common evidence-quality score used by institutional workspaces.

    Inputs are normalized 0..1 except field_presence, whose coverage is inferred from
    truthy values. The returned score is explicitly an evidence-quality diagnostic, not
    an investment signal.
    """
    presence = dict(field_presence or {})
    total = len(presence)
    present = sum(bool(v) for v in presence.values())
    coverage = present / total if total else 0.0

    sq = max(0.0, min(1.0, float(source_quality)))
    fr = max(0.0, min(1.0, float(freshness)))
    cv = max(0.0, min(1.0, float(cross_validation)))
    wc, ws, wf, wx = weights
    denom = wc + ws + wf + wx
    score = 100.0 * (wc * coverage + ws * sq + wf * fr + wx * cv) / denom
    return {
        "score": round(clamp(score), 1),
        "coverage": round(100.0 * coverage, 1),
        "source_quality": round(100.0 * sq, 1),
        "freshness": round(100.0 * fr, 1),
        "cross_validation": round(100.0 * cv, 1),
    }


def calculate_institutional_overlay(
    *,
    ownership_score: Any = None,
    insider_score: Any = None,
    product_diversification: Any = None,
    geographic_diversification: Any = None,
    customer_risk: Any = None,
    supplier_risk: Any = None,
) -> dict[str, Any]:
    """Transparent institutional overlay kept separate from the core fundamental score.

    This is *not* merged into Company Score. It summarizes positioning and business
    resilience using only available institutional dimensions. Structural risk scores are
    inverted into resilience scores before aggregation.
    """
    raw = {
        "Ownership / reported-holder conviction": (_num(ownership_score), 0.25),
        "Informative insider activity": (_num(insider_score), 0.20),
        "Product diversification": (_num(product_diversification), 0.15),
        "Geographic diversification": (_num(geographic_diversification), 0.10),
        "Customer resilience": (None if _num(customer_risk) is None else 100.0 - _num(customer_risk), 0.20),
        "Supplier resilience": (None if _num(supplier_risk) is None else 100.0 - _num(supplier_risk), 0.10),
    }

    total_weight = sum(w for _, w in raw.values())
    available_weight = sum(w for v, w in raw.values() if v is not None)
    weighted_sum = sum(clamp(v) * w for v, w in raw.values() if v is not None)
    score = weighted_sum / available_weight if available_weight > 0 else None
    coverage = 100.0 * available_weight / total_weight if total_weight > 0 else 0.0

    components = []
    for name, (value, weight) in raw.items():
        components.append({
            "Dimension": name,
            "Score": None if value is None else round(clamp(value), 1),
            "Weight": round(100.0 * weight, 1),
            "Available": value is not None,
        })

    label = "N/A"
    if score is not None:
        label = "Supportive" if score >= 65 else "Balanced" if score >= 45 else "Cautious"

    return {
        "score": None if score is None else round(clamp(score), 1),
        "coverage": round(coverage, 1),
        "label": label,
        "components": components,
    }
