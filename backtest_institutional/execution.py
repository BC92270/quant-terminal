"""Event-driven bar execution ledger with calibratable transaction costs."""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Iterable

import numpy as np
import pandas as pd

from .types import AvailabilityState, Fill, LedgerResult, Order


@dataclass(frozen=True)
class ExecutionModelConfig:
    model: str = "square_root"
    initial_capital: float = 1_000_000.0
    commission_bps: float = 0.5
    spread_bps: float = 2.0
    slippage_bps: float = 1.0
    impact_coefficient: float = 0.10
    impact_exponent: float = 0.5
    max_participation: float = 0.10
    allow_partial_fills: bool = True
    signal_latency_bars: int = 1
    settlement_days: int = 2
    annual_borrow_bps: float | None = None

    def validate(self) -> None:
        if self.model not in {"constant", "volume_share", "square_root", "almgren_chriss_proxy"}:
            raise ValueError(f"Unsupported execution model: {self.model}")
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        if not 0 < self.max_participation <= 1:
            raise ValueError("max_participation must be in (0, 1]")
        if self.signal_latency_bars < 1:
            raise ValueError("signal_latency_bars must be >= 1 to prevent look-ahead")
        if self.settlement_days < 0:
            raise ValueError("settlement_days must be non-negative")


def _normalise_bars(bars: pd.DataFrame) -> pd.DataFrame:
    clean = bars.copy()
    clean.columns = [str(c).strip().lower().replace(" ", "_") for c in clean.columns]
    needed = {"open", "high", "low", "close"}
    missing = sorted(needed.difference(clean.columns))
    if missing:
        raise ValueError("Missing OHLC fields: " + ", ".join(missing))
    clean = clean.sort_index()
    for column in needed | {"volume", "borrow_rate"}:
        if column in clean:
            clean[column] = pd.to_numeric(clean[column], errors="coerce")
    return clean


def _impact_bps(
    model: str,
    *,
    quantity: float,
    volume: float | None,
    price: float,
    volatility: float,
    config: ExecutionModelConfig,
) -> tuple[float, float | None]:
    participation = None
    if volume is not None and np.isfinite(volume) and volume > 0:
        participation = abs(quantity) / volume
    if model == "constant":
        return float(config.slippage_bps), participation
    if participation is None:
        raise ValueError("DATA REQUIRED: volume for selected execution model")
    p = max(participation, 1e-12)
    if model == "volume_share":
        return float(config.slippage_bps + 10_000 * config.impact_coefficient * p ** 2), p
    sigma = max(float(volatility), 1e-6)
    if model == "square_root":
        return float(config.slippage_bps + 10_000 * config.impact_coefficient * sigma * p ** config.impact_exponent), p
    temporary = 10_000 * config.impact_coefficient * sigma * sqrt(p)
    permanent = 5_000 * config.impact_coefficient * sigma * p
    return float(config.slippage_bps + temporary + permanent), p


def simulate_execution(
    bars: pd.DataFrame,
    target_exposure: pd.Series,
    *,
    symbol: str,
    config: ExecutionModelConfig | None = None,
) -> LedgerResult:
    config = config or ExecutionModelConfig()
    config.validate()
    clean = _normalise_bars(bars)
    exposure = pd.to_numeric(target_exposure.reindex(clean.index), errors="coerce").ffill().fillna(0.0)
    if len(clean) < config.signal_latency_bars + 2:
        return LedgerResult(AvailabilityState.UNAVAILABLE, "DATA REQUIRED: insufficient bars")

    needs_volume = config.model != "constant"
    if needs_volume and (
        "volume" not in clean
        or clean["volume"].dropna().empty
        or not bool((clean["volume"] > 0.0).any())
    ):
        return LedgerResult(
            AvailabilityState.UNAVAILABLE,
            "DATA REQUIRED: strictly positive volume for impact, capacity and partial-fill modelling",
            diagnostics={"model": config.model, "fail_closed": True},
        )

    returns = clean["close"].pct_change()
    rolling_vol = returns.rolling(20, min_periods=5).std().fillna(returns.std(ddof=0))
    cash = float(config.initial_capital)
    position = 0.0
    orders: list[Order] = []
    fills: list[Fill] = []
    rows: list[dict[str, float | str]] = []
    pending: list[tuple[int, float]] = []
    total_cost = 0.0
    rejected = 0
    partial = 0

    for i, (timestamp, row) in enumerate(clean.iterrows()):
        close = float(row["close"])
        open_price = float(row["open"])
        pre_trade_nav = cash + position * open_price
        if i >= config.signal_latency_bars:
            source_i = i - config.signal_latency_bars
            pending.append((i, float(exposure.iloc[source_i])))

        day_turnover = 0.0
        day_cost = 0.0
        if pending:
            _, target = pending.pop(0)
            desired_shares = target * pre_trade_nav / open_price if open_price > 0 else position
            requested = desired_shares - position
            if abs(requested) > 1e-10:
                order_id = f"ORD-{i:06d}"
                side = "BUY" if requested > 0 else "SELL"
                volume = float(row["volume"]) if "volume" in row and np.isfinite(row["volume"]) else None
                fill_quantity = abs(requested)
                liquidity_flag = "FULL"
                if volume is not None:
                    cap = config.max_participation * volume
                    if fill_quantity > cap:
                        if config.allow_partial_fills and cap > 0:
                            fill_quantity = cap
                            liquidity_flag = "PARTIAL"
                            partial += 1
                        else:
                            rejected += 1
                            orders.append(Order(
                                order_id, str(timestamp), symbol, side, abs(requested),
                                target_exposure=target, status="REJECTED",
                                reason="participation cap exceeded",
                            ))
                            fill_quantity = 0.0
                orders.append(Order(
                    order_id, str(timestamp), symbol, side, abs(requested),
                    target_exposure=target,
                    status="PARTIAL" if liquidity_flag == "PARTIAL" else "FILLED",
                    reason="participation cap" if liquidity_flag == "PARTIAL" else "",
                ))
                if fill_quantity > 0:
                    signed_qty = fill_quantity if side == "BUY" else -fill_quantity
                    try:
                        impact_bps, participation = _impact_bps(
                            config.model,
                            quantity=fill_quantity,
                            volume=volume,
                            price=open_price,
                            volatility=float(rolling_vol.iloc[i]) if np.isfinite(rolling_vol.iloc[i]) else 0.0,
                            config=config,
                        )
                    except ValueError as exc:
                        return LedgerResult(
                            AvailabilityState.UNAVAILABLE,
                            str(exc),
                            orders=orders,
                            fills=fills,
                            diagnostics={"model": config.model, "fail_closed": True},
                        )
                    half_spread_bps = config.spread_bps / 2.0
                    adverse_bps = half_spread_bps + impact_bps
                    direction = 1.0 if side == "BUY" else -1.0
                    fill_price = open_price * (1.0 + direction * adverse_bps / 10_000.0)
                    notional = fill_quantity * fill_price
                    commission = notional * config.commission_bps / 10_000.0
                    spread_cost = fill_quantity * open_price * half_spread_bps / 10_000.0
                    impact_cost = fill_quantity * open_price * max(impact_bps - config.slippage_bps, 0.0) / 10_000.0
                    slippage_cost = fill_quantity * open_price * config.slippage_bps / 10_000.0
                    explicit_implicit = commission + spread_cost + impact_cost + slippage_cost
                    cash -= signed_qty * fill_price + commission
                    position += signed_qty
                    day_turnover += fill_quantity * open_price
                    day_cost += explicit_implicit
                    total_cost += explicit_implicit
                    settlement = pd.Timestamp(timestamp) + pd.tseries.offsets.BDay(config.settlement_days)
                    fills.append(Fill(
                        f"FILL-{i:06d}", order_id, str(timestamp), symbol, side,
                        float(fill_quantity), open_price, float(fill_price), float(commission),
                        float(spread_cost), float(impact_cost), float(slippage_cost),
                        None if participation is None else float(participation),
                        liquidity_flag, str(settlement.date()),
                    ))

        borrow_cost = 0.0
        if position < 0:
            if "borrow_rate" in clean and np.isfinite(row.get("borrow_rate", np.nan)):
                annual_borrow_bps = float(row["borrow_rate"])
            else:
                annual_borrow_bps = config.annual_borrow_bps
            if annual_borrow_bps is not None:
                borrow_cost = abs(position) * close * annual_borrow_bps / 10_000.0 / 252.0
                cash -= borrow_cost
                total_cost += borrow_cost
                day_cost += borrow_cost

        nav = cash + position * close
        rows.append({
            "timestamp": str(timestamp),
            "cash": cash,
            "position": position,
            "close": close,
            "nav": nav,
            "target_exposure": float(exposure.iloc[i]),
            "realized_exposure": position * close / nav if nav else 0.0,
            "turnover_notional": day_turnover,
            "cost": day_cost,
            "borrow_cost": borrow_cost,
        })

    daily = pd.DataFrame(rows, index=clean.index)
    daily["return"] = daily["nav"].pct_change().fillna(0.0)
    daily["drawdown"] = daily["nav"] / daily["nav"].cummax() - 1.0
    short_without_borrow = bool((daily["position"] < 0).any()) and (
        "borrow_rate" not in clean and config.annual_borrow_bps is None
    )
    status = AvailabilityState.PARTIAL if short_without_borrow else AvailabilityState.AVAILABLE
    reason = (
        "PARTIAL: short exposure present but borrow/rebate data unavailable"
        if short_without_borrow
        else "Event ledger complete"
    )
    return LedgerResult(
        status,
        reason,
        orders=orders,
        fills=fills,
        daily=daily,
        diagnostics={
            "model": config.model,
            "lookahead_guard_bars": config.signal_latency_bars,
            "settlement_days": config.settlement_days,
            "total_cost": float(total_cost),
            "filled_orders": len(fills),
            "partial_orders": partial,
            "rejected_orders": rejected,
            "short_borrow_available": not short_without_borrow,
            "fail_closed": True,
        },
    )


def calibrate_power_impact(
    observed_participation: Iterable[float],
    observed_impact_bps: Iterable[float],
    *,
    exponent: float = 0.5,
) -> dict[str, float]:
    p = np.asarray(list(observed_participation), dtype=float)
    y = np.asarray(list(observed_impact_bps), dtype=float) / 10_000.0
    mask = np.isfinite(p) & np.isfinite(y) & (p > 0) & (y >= 0)
    if int(mask.sum()) < 3:
        raise ValueError("At least three valid observations are required")
    x = np.power(p[mask], exponent)
    coefficient = float(np.dot(x, y[mask]) / max(np.dot(x, x), 1e-12))
    fitted = coefficient * x
    rmse_bps = float(np.sqrt(np.mean((y[mask] - fitted) ** 2)) * 10_000.0)
    return {
        "impact_coefficient": coefficient,
        "impact_exponent": float(exponent),
        "rmse_bps": rmse_bps,
        "observations": int(mask.sum()),
    }
