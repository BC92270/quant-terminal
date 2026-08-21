from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Any

import numpy as np
import pandas as pd


@dataclass(slots=True)
class PortfolioMandate:
    nav: float = 1_000_000.0
    max_position_pct: float = 20.0
    min_cash_pct: float = 5.0
    max_gross_pct: float = 130.0
    max_annual_vol_pct: float = 18.0
    turnover_budget_pct: float = 25.0
    base_correlation: float = 0.20

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "PortfolioMandate":
        value = value or {}
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: value[key] for key in allowed if key in value})


@dataclass(slots=True)
class PortfolioReview:
    status: str
    metrics: dict[str, Any]
    holdings: list[dict[str, Any]]
    risk_contributions: list[dict[str, Any]]
    scenarios: list[dict[str, Any]]
    proposed_weights: list[dict[str, Any]]
    breaches: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def serializable(self) -> dict[str, Any]:
        return asdict(self)


def _decimal(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number / 100.0 if abs(number) > 2 else number


def _holdings(book: dict[str, Any] | pd.DataFrame | None) -> list[dict[str, Any]]:
    if isinstance(book, pd.DataFrame):
        records = book.to_dict("records")
    elif isinstance(book, dict):
        raw = book.get("holdings", book.get("positions", []))
        records = raw.to_dict("records") if isinstance(raw, pd.DataFrame) else list(raw) if isinstance(raw, list) else []
    else:
        records = []
    holdings: list[dict[str, Any]] = []
    for item in records:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or item.get("Ticker") or item.get("symbol") or "").upper().strip()
        if not ticker:
            continue
        weight = _decimal(item.get("weight", item.get("Weight %", item.get("weight_pct", 0.0))))
        expected = _decimal(item.get("expected_return", item.get("Expected return %", 0.0)))
        volatility = abs(_decimal(item.get("volatility", item.get("Volatility %", 0.20)), 0.20))
        asset_class = str(item.get("asset_class") or item.get("Asset class") or "Other").strip()
        liquidity = float(item.get("liquidity_score", item.get("Liquidity", 75.0)) or 75.0)
        holdings.append(
            {
                "ticker": ticker,
                "weight": weight,
                "expected_return": expected,
                "volatility": volatility,
                "asset_class": asset_class,
                "liquidity_score": max(0.0, min(100.0, liquidity)),
            }
        )
    return holdings


def _scenario_shock(asset_class: str, scenario: str) -> float:
    label = asset_class.lower()
    shocks = {
        "growth_shock": {"equity": -0.22, "credit": -0.12, "bond": 0.06, "rates": 0.06, "commodity": -0.15, "cash": 0.0, "other": -0.10},
        "inflation_shock": {"equity": -0.12, "credit": -0.08, "bond": -0.10, "rates": -0.10, "commodity": 0.15, "cash": 0.01, "other": -0.06},
        "liquidity_crunch": {"equity": -0.18, "credit": -0.16, "bond": -0.05, "rates": -0.05, "commodity": -0.10, "cash": 0.0, "other": -0.14},
        "risk_on": {"equity": 0.12, "credit": 0.06, "bond": -0.03, "rates": -0.03, "commodity": 0.08, "cash": 0.0, "other": 0.07},
    }
    bucket = "cash" if "cash" in label else "equity" if any(token in label for token in ("equity", "stock", "etf")) else "credit" if "credit" in label else "bond" if any(token in label for token in ("bond", "fixed", "rates")) else "commodity" if any(token in label for token in ("commodity", "gold", "energy")) else "other"
    return shocks[scenario][bucket]


def review_portfolio(
    book: dict[str, Any] | pd.DataFrame | None,
    mandate: PortfolioMandate | dict[str, Any] | None = None,
) -> PortfolioReview:
    mandate = mandate if isinstance(mandate, PortfolioMandate) else PortfolioMandate.from_dict(mandate)
    holdings = _holdings(book)
    if not holdings:
        return PortfolioReview(
            "not_available",
            {},
            [],
            [],
            [],
            [],
            warnings=["A holdings table is required for portfolio diagnostics."],
        )

    weights = np.array([item["weight"] for item in holdings], dtype=float)
    vols = np.array([item["volatility"] for item in holdings], dtype=float)
    expected = np.array([item["expected_return"] for item in holdings], dtype=float)
    gross = float(np.abs(weights).sum())
    net = float(weights.sum())
    long_weight = float(weights[weights > 0].sum())
    short_weight = float(abs(weights[weights < 0].sum()))
    cash_weight = float(sum(item["weight"] for item in holdings if item["ticker"] == "CASH" or "cash" in item["asset_class"].lower()))
    normalized = np.abs(weights) / gross if gross > 0 else np.zeros_like(weights)
    hhi = float(np.square(normalized).sum())
    effective_bets = float(1.0 / hhi) if hhi > 0 else 0.0

    corr = np.full((len(holdings), len(holdings)), float(mandate.base_correlation))
    np.fill_diagonal(corr, 1.0)
    covariance = np.outer(vols, vols) * corr
    variance = float(weights @ covariance @ weights)
    portfolio_vol = math.sqrt(max(0.0, variance))
    portfolio_return = float(weights @ expected)
    marginal = covariance @ weights
    contributions = weights * marginal / variance if variance > 0 else np.zeros_like(weights)
    risk_contributions = [
        {"ticker": item["ticker"], "weight": round(float(weights[index]), 6), "risk_contribution": round(float(contributions[index]), 6)}
        for index, item in enumerate(holdings)
    ]
    risk_contributions.sort(key=lambda item: abs(item["risk_contribution"]), reverse=True)

    max_position = float(max(np.abs(weights))) if len(weights) else 0.0
    weighted_liquidity = float(sum(abs(item["weight"]) * item["liquidity_score"] for item in holdings) / gross) if gross > 0 else 0.0
    breaches: list[str] = []
    if max_position > mandate.max_position_pct / 100.0:
        breaches.append(f"Largest position {max_position:.1%} exceeds the {mandate.max_position_pct:.1f}% limit.")
    if cash_weight < mandate.min_cash_pct / 100.0:
        breaches.append(f"Cash {cash_weight:.1%} is below the {mandate.min_cash_pct:.1f}% floor.")
    if gross > mandate.max_gross_pct / 100.0:
        breaches.append(f"Gross exposure {gross:.1%} exceeds the {mandate.max_gross_pct:.1f}% limit.")
    if portfolio_vol > mandate.max_annual_vol_pct / 100.0:
        breaches.append(f"Approximate volatility {portfolio_vol:.1%} exceeds the {mandate.max_annual_vol_pct:.1f}% budget.")
    if weighted_liquidity < 50:
        breaches.append(f"Weighted liquidity score {weighted_liquidity:.0f}/100 is below the operating threshold.")

    scenarios: list[dict[str, Any]] = []
    for scenario, title in (
        ("growth_shock", "Growth shock"),
        ("inflation_shock", "Inflation / rates shock"),
        ("liquidity_crunch", "Liquidity crunch"),
        ("risk_on", "Risk-on rally"),
    ):
        pnl = float(sum(item["weight"] * _scenario_shock(item["asset_class"], scenario) for item in holdings))
        scenarios.append({"scenario": title, "portfolio_return": round(pnl, 6), "pnl_value": round(pnl * mandate.nav, 2)})

    rng = np.random.default_rng(20260812)
    simulated_returns = rng.normal(portfolio_return, portfolio_vol, size=10_000)
    loss_cutoff = float(np.quantile(simulated_returns, 0.05))
    simulation = {
        "paths": 10_000,
        "probability_of_annual_loss": round(float((simulated_returns < 0).mean()), 6),
        "p05_return": round(loss_cutoff, 6),
        "median_return": round(float(np.median(simulated_returns)), 6),
        "p95_return": round(float(np.quantile(simulated_returns, 0.95)), 6),
        "expected_shortfall_95": round(float(simulated_returns[simulated_returns <= loss_cutoff].mean()), 6),
        "p05_pnl_value": round(loss_cutoff * mandate.nav, 2),
    }

    cap = mandate.max_position_pct / 100.0
    proposed: list[dict[str, Any]] = []
    released = 0.0
    for item in holdings:
        proposed_weight = item["weight"]
        if proposed_weight > cap:
            released += proposed_weight - cap
            proposed_weight = cap
        elif proposed_weight < -cap:
            released += abs(proposed_weight) - cap
            proposed_weight = -cap
        proposed.append({"ticker": item["ticker"], "current_weight": round(item["weight"], 6), "proposed_weight": round(proposed_weight, 6)})
    cash_row = next((item for item in proposed if item["ticker"] == "CASH"), None)
    target_cash = max(cash_weight + released, mandate.min_cash_pct / 100.0)
    if cash_row:
        cash_row["proposed_weight"] = round(target_cash, 6)
    else:
        proposed.append({"ticker": "CASH", "current_weight": 0.0, "proposed_weight": round(target_cash, 6)})

    turnover = float(sum(abs(item["proposed_weight"] - item["current_weight"]) for item in proposed) / 2.0)
    recommendations = [
        "Fund any new risk from the most concentrated or lowest-conviction exposure, not by silently increasing gross.",
        "Validate the covariance estimate with connected multi-asset history before approving risk contributions.",
        "Run the four scenario losses through the committee and require Chief Risk sign-off on binding breaches.",
    ]
    if breaches:
        recommendations.insert(0, "Remediate mandate breaches before adding discretionary risk.")
    if turnover > mandate.turnover_budget_pct / 100.0:
        breaches.append(f"Indicative rebalance turnover {turnover:.1%} exceeds the {mandate.turnover_budget_pct:.1f}% budget.")

    metrics = {
        "nav": round(float(mandate.nav), 2),
        "positions": len(holdings),
        "net_exposure": round(net, 6),
        "gross_exposure": round(gross, 6),
        "long_exposure": round(long_weight, 6),
        "short_exposure": round(short_weight, 6),
        "cash_weight": round(cash_weight, 6),
        "largest_position": round(max_position, 6),
        "concentration_hhi": round(hhi, 6),
        "effective_bets": round(effective_bets, 2),
        "expected_return": round(portfolio_return, 6),
        "approximate_volatility": round(portfolio_vol, 6),
        "return_to_risk": round(portfolio_return / portfolio_vol, 4) if portfolio_vol > 0 else None,
        "weighted_liquidity_score": round(weighted_liquidity, 2),
        "indicative_rebalance_turnover": round(turnover, 6),
        "breach_count": len(breaches),
        "simulation": simulation,
    }
    status = "breach" if breaches else "within_mandate"
    warnings = ["Portfolio volatility uses supplied standalone volatilities and a configurable constant-correlation approximation; connect a full covariance matrix for capital use."]
    return PortfolioReview(status, metrics, holdings, risk_contributions, scenarios, proposed, breaches, recommendations, warnings)
