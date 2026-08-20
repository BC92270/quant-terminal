from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
import time
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd

from .portfolio import PortfolioMandate, review_portfolio
from .schemas import Evidence, NodeStatus, ToolResult
from .strategy import StrategySpec, run_strategy_backtest


@dataclass(slots=True)
class QuantContext:
    ticker: str
    price_data: pd.DataFrame
    analysis: dict[str, Any] = field(default_factory=dict)
    session_state: dict[str, Any] = field(default_factory=dict)
    portfolio: dict[str, Any] = field(default_factory=dict)
    strategy: dict[str, Any] = field(default_factory=dict)
    portfolio_mandate: dict[str, Any] = field(default_factory=dict)


ToolFunction = Callable[[QuantContext], ToolResult]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolFunction] = {}

    def register(self, name: str, function: ToolFunction) -> "ToolRegistry":
        self._tools[name] = function
        return self

    def names(self) -> list[str]:
        return sorted(self._tools)

    def run(self, name: str, context: QuantContext) -> ToolResult:
        started = time.perf_counter()
        function = self._tools.get(name)
        if function is None:
            return ToolResult(
                name=name,
                status=NodeStatus.ERROR,
                warnings=[f"Unknown deterministic tool: {name}"],
            )
        try:
            result = function(context)
        except Exception as exc:  # fail closed: one data adapter must not stop the committee
            result = ToolResult(
                name=name,
                status=NodeStatus.ERROR,
                warnings=[f"{type(exc).__name__}: {exc}"],
            )
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result


def _as_of() -> str:
    return datetime.now(timezone.utc).isoformat()


def _column(frame: pd.DataFrame, name: str) -> pd.Series:
    for column in frame.columns:
        if str(column).strip().lower() == name:
            return pd.to_numeric(frame[column], errors="coerce")
    return pd.Series(dtype=float)


def _returns(context: QuantContext) -> pd.Series:
    close = _column(context.price_data, "close").dropna()
    if close.empty:
        return pd.Series(dtype=float)
    return close.pct_change().replace([np.inf, -np.inf], np.nan).dropna()


def _number(value: Any, digits: int = 6) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return round(result, digits) if math.isfinite(result) else None


def market_snapshot(context: QuantContext) -> ToolResult:
    close = _column(context.price_data, "close").dropna()
    returns = _returns(context)
    if close.empty or returns.empty:
        return ToolResult(
            name="market_snapshot",
            status=NodeStatus.NOT_AVAILABLE,
            warnings=["Price history with a close column is required."],
        )
    observations = int(len(close))
    latest = float(close.iloc[-1])
    start = float(close.iloc[0])
    ann_vol = float(returns.std(ddof=1) * np.sqrt(252)) if len(returns) > 1 else 0.0
    annualized_return = float((latest / start) ** (252 / max(observations - 1, 1)) - 1) if start > 0 else 0.0
    running_max = close.cummax()
    drawdown = close / running_max - 1.0
    data = {
        "ticker": context.ticker,
        "observations": observations,
        "latest_price": _number(latest),
        "total_return": _number(latest / start - 1.0) if start else None,
        "annualized_return": _number(annualized_return),
        "annualized_volatility": _number(ann_vol),
        "max_drawdown": _number(drawdown.min()),
        "return_20d": _number(close.iloc[-1] / close.iloc[-21] - 1.0) if observations > 21 else None,
        "return_63d": _number(close.iloc[-1] / close.iloc[-64] - 1.0) if observations > 64 else None,
    }
    evidence = [
        Evidence("Market Data", "Latest price", data["latest_price"], f"{observations} observations", _as_of(), 0.95),
        Evidence("Market Data", "Annualized volatility", data["annualized_volatility"], "Daily close-to-close", _as_of(), 0.9),
        Evidence("Market Data", "Maximum drawdown", data["max_drawdown"], "Full supplied window", _as_of(), 0.9),
    ]
    return ToolResult("market_snapshot", NodeStatus.COMPLETE, data, evidence)


def technical_regime(context: QuantContext) -> ToolResult:
    close = _column(context.price_data, "close").dropna()
    if len(close) < 20:
        return ToolResult("technical_regime", NodeStatus.NOT_AVAILABLE, warnings=["At least 20 close observations are required."])
    latest = float(close.iloc[-1])
    ma20 = float(close.tail(20).mean())
    ma50 = float(close.tail(min(50, len(close))).mean())
    ma200 = float(close.tail(min(200, len(close))).mean())
    momentum = latest / float(close.iloc[max(0, len(close) - 64)]) - 1.0
    trend_score = int(latest > ma20) + int(ma20 > ma50) + int(ma50 > ma200)
    regime = "bullish" if trend_score >= 2 else "bearish" if trend_score == 0 else "mixed"
    data = {
        "regime": regime,
        "trend_score": trend_score,
        "price_vs_ma20": _number(latest / ma20 - 1.0),
        "price_vs_ma50": _number(latest / ma50 - 1.0),
        "price_vs_ma200": _number(latest / ma200 - 1.0),
        "momentum_63d": _number(momentum),
    }
    return ToolResult(
        "technical_regime",
        NodeStatus.COMPLETE,
        data,
        [Evidence("Momentum / Trend", "Technical regime", regime, f"trend score {trend_score}/3", _as_of(), 0.82)],
    )


def risk_snapshot(context: QuantContext) -> ToolResult:
    returns = _returns(context)
    if len(returns) < 20:
        return ToolResult("risk_snapshot", NodeStatus.NOT_AVAILABLE, warnings=["At least 20 returns are required."])
    q05 = float(returns.quantile(0.05))
    tail = returns[returns <= q05]
    downside = returns[returns < 0]
    ann_vol = float(returns.std(ddof=1) * np.sqrt(252))
    data = {
        "hist_var_95": _number(max(0.0, -q05)),
        "hist_cvar_95": _number(max(0.0, -float(tail.mean()))) if not tail.empty else _number(max(0.0, -q05)),
        "annualized_volatility": _number(ann_vol),
        "downside_volatility": _number(float(downside.std(ddof=1) * np.sqrt(252))) if len(downside) > 1 else None,
        "worst_day": _number(float(returns.min())),
        "best_day": _number(float(returns.max())),
        "positive_day_ratio": _number(float((returns > 0).mean())),
    }
    return ToolResult(
        "risk_snapshot",
        NodeStatus.COMPLETE,
        data,
        [
            Evidence("Risk Monitor", "Historical VaR 95%", data["hist_var_95"], "1-day empirical", _as_of(), 0.88),
            Evidence("Risk Monitor", "Historical CVaR 95%", data["hist_cvar_95"], "Mean loss beyond VaR", _as_of(), 0.88),
        ],
    )


def strategy_backtest_tool(context: QuantContext) -> ToolResult:
    spec = StrategySpec.from_dict(context.strategy)
    result = run_strategy_backtest(context.price_data, spec)
    if result.status == "not_available":
        return ToolResult(
            "strategy_backtest",
            NodeStatus.NOT_AVAILABLE,
            data=result.serializable(),
            warnings=result.warnings,
        )
    status = NodeStatus.COMPLETE if result.status == "validated_candidate" else NodeStatus.PARTIAL
    return ToolResult(
        "strategy_backtest",
        status,
        data=result.serializable(),
        evidence=[
            Evidence("Strategy Lab", "Validation score", result.summary.get("validation_score"), "Shifted signal, costs and train/test split", _as_of(), 0.88),
            Evidence("Strategy Lab", "Out-of-sample Sharpe", result.out_of_sample.get("sharpe"), "Reserved chronological test window", _as_of(), 0.84),
            Evidence("Strategy Lab", "Cost-adjusted return", result.summary.get("total_return"), f"{spec.cost_bps + spec.slippage_bps:.1f} bps one-way cost", _as_of(), 0.82),
        ],
        warnings=result.warnings,
    )


def portfolio_diagnostics_tool(context: QuantContext) -> ToolResult:
    review = review_portfolio(context.portfolio, PortfolioMandate.from_dict(context.portfolio_mandate))
    if review.status == "not_available":
        return ToolResult(
            "portfolio_diagnostics",
            NodeStatus.NOT_AVAILABLE,
            data=review.serializable(),
            warnings=review.warnings,
        )
    status = NodeStatus.PARTIAL if review.breaches else NodeStatus.COMPLETE
    return ToolResult(
        "portfolio_diagnostics",
        status,
        data=review.serializable(),
        evidence=[
            Evidence("Portfolio Lab", "Gross exposure", review.metrics.get("gross_exposure"), "Current book", _as_of(), 0.94),
            Evidence("Portfolio Lab", "Effective bets", review.metrics.get("effective_bets"), "HHI-based concentration", _as_of(), 0.88),
            Evidence("Portfolio Lab", "Mandate breaches", len(review.breaches), "Configured limits", _as_of(), 0.92),
        ],
        warnings=review.warnings + review.breaches,
    )


_SENSITIVE = ("api_key", "apikey", "token", "password", "secret", "credential")


def _compact(value: Any, depth: int = 0) -> Any:
    if depth > 2:
        return "…"
    if value is None or isinstance(value, (str, bool, int)):
        text = value
        if isinstance(text, str) and len(text) > 320:
            return text[:317] + "…"
        return text
    if isinstance(value, float):
        return _number(value)
    if isinstance(value, pd.DataFrame):
        return {"rows": int(len(value)), "columns": [str(item) for item in list(value.columns)[:16]]}
    if isinstance(value, pd.Series):
        return {"observations": int(len(value)), "latest": _compact(value.iloc[-1], depth + 1) if len(value) else None}
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:24]:
            key_text = str(key)
            if any(token in key_text.lower() for token in _SENSITIVE):
                continue
            result[key_text] = _compact(item, depth + 1)
        return result
    if isinstance(value, (list, tuple, set)):
        return [_compact(item, depth + 1) for item in list(value)[:16]]
    return str(value)[:320]


def _matching_context(context: QuantContext, aliases: Iterable[str]) -> dict[str, Any]:
    normalized = tuple(alias.lower() for alias in aliases)
    matches: dict[str, Any] = {}

    def visit(value: Any, prefix: str, depth: int) -> None:
        if depth > 3 or len(matches) >= 28:
            return
        if isinstance(value, dict):
            for key, item in value.items():
                key_text = str(key)
                path = f"{prefix}.{key_text}" if prefix else key_text
                lower = path.lower()
                if any(token in lower for token in _SENSITIVE):
                    continue
                if any(alias in lower for alias in normalized):
                    matches[path] = _compact(item)
                elif isinstance(item, dict):
                    visit(item, path, depth + 1)

    visit(context.analysis or {}, "analysis", 0)
    visit(context.session_state or {}, "session", 0)
    visit(context.portfolio or {}, "portfolio", 0)
    return matches


SECTION_SPECS: dict[str, tuple[str, tuple[str, ...]]] = {
    "portfolio_context": ("Portfolio Lab", ("portfolio", "holding", "position", "allocation", "exposure", "book")),
    "company_intelligence": ("Company Intelligence", ("company", "fundamental", "valuation", "earnings", "financial", "quality", "peer")),
    "macro_context": ("Macro / Central Banks", ("macro", "central_bank", "inflation", "gdp", "liquidity", "rate", "yield", "fx")),
    "fixed_income_context": ("Fixed Income & Credit", ("fixed_income", "credit", "bond", "spread", "duration", "curve", "yield")),
    "derivatives_context": ("Options / Futures", ("option", "future", "derivative", "volatility_surface", "skew", "gamma", "delta", "iv")),
    "correlation_context": ("Correlation Matrix", ("correlation", "dependency", "beta", "covariance", "cluster")),
    "monte_carlo_context": ("Monte Carlo Advanced", ("monte_carlo", "simulation", "scenario", "percentile", "terminal_value")),
    "backtest_context": ("Backtest Lab", ("backtest", "walk_forward", "out_of_sample", "strategy", "sharpe", "turnover")),
    "ml_research_context": ("ML Research Lab", ("ml_", "machine_learning", "feature", "model_score", "cross_validation", "prediction")),
    "behavioral_context": ("Market Psychology", ("psychology", "sentiment", "positioning", "reflexivity", "attention", "crowding")),
    "event_intelligence": ("WorldMonitor / News", ("worldmonitor", "event", "news", "geopolit", "country", "conflict", "supply_chain")),
    "execution_context": ("Execution / Microstructure", ("execution", "liquidity", "slippage", "spread", "market_impact", "borrow", "capacity", "tca")),
}


def section_context_tool(name: str, label: str, aliases: tuple[str, ...]) -> ToolFunction:
    def run(context: QuantContext) -> ToolResult:
        matches = _matching_context(context, aliases)
        if not matches:
            return ToolResult(
                name,
                NodeStatus.NOT_AVAILABLE,
                data={"section": label, "available": False},
                warnings=[f"No structured {label} state is available in this session."],
            )
        return ToolResult(
            name,
            NodeStatus.COMPLETE,
            data={"section": label, "available": True, "signals": matches},
            evidence=[Evidence(label, "Connected section state", len(matches), "Structured fields captured", _as_of(), 0.75)],
        )

    return run


def section_inventory(context: QuantContext) -> ToolResult:
    coverage: dict[str, bool] = {}
    for name, (_, aliases) in SECTION_SPECS.items():
        coverage[name] = bool(_matching_context(context, aliases))
    coverage["market_snapshot"] = not _column(context.price_data, "close").dropna().empty
    return ToolResult(
        "section_inventory",
        NodeStatus.COMPLETE,
        data={"coverage": coverage, "connected": sum(coverage.values()), "total": len(coverage)},
        evidence=[Evidence("Quant Terminal", "Connected analytical sections", sum(coverage.values()), f"of {len(coverage)} adapters", _as_of(), 0.9)],
    )


def build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register("market_snapshot", market_snapshot)
    registry.register("technical_regime", technical_regime)
    registry.register("risk_snapshot", risk_snapshot)
    registry.register("strategy_backtest", strategy_backtest_tool)
    registry.register("portfolio_diagnostics", portfolio_diagnostics_tool)
    registry.register("section_inventory", section_inventory)
    for name, (label, aliases) in SECTION_SPECS.items():
        registry.register(name, section_context_tool(name, label, aliases))
    return registry
