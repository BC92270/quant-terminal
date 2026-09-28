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
    target_timing: str = "raw_signal"
    signal_latency_bars: int = 1
    adv_lookback_bars: int = 20
    volatility_lookback_bars: int = 20
    fallback_bar_volatility: float = 0.02
    bar_frequency: str = "1d"
    periods_per_year: float = 252.0
    trading_calendar: str = "BUSINESS_DAY"
    price_basis: str = "raw"
    corporate_action_policy: str = "apply_if_present"
    short_sale_policy: str = "allow_unverified"
    require_locate: bool = True
    settlement_days: int = 2
    settlement_cash_policy: str = "trade_date_proxy"
    annual_borrow_bps: float | None = None

    def validate(self) -> None:
        if self.model not in {"constant", "volume_share", "square_root", "almgren_chriss_proxy"}:
            raise ValueError(f"Unsupported execution model: {self.model}")
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        for name in ("commission_bps", "spread_bps", "slippage_bps", "impact_coefficient"):
            if not np.isfinite(getattr(self, name)) or getattr(self, name) < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        if not 0 < self.impact_exponent <= 2:
            raise ValueError("impact_exponent must be in (0, 2]")
        if not 0 < self.max_participation <= 1:
            raise ValueError("max_participation must be in (0, 1]")
        if self.target_timing not in {"raw_signal", "pre_lagged_target"}:
            raise ValueError("target_timing must be 'raw_signal' or 'pre_lagged_target'")
        minimum_latency = 1 if self.target_timing == "raw_signal" else 0
        if self.signal_latency_bars < minimum_latency:
            raise ValueError(
                f"signal_latency_bars must be >= {minimum_latency} for target_timing={self.target_timing!r}"
            )
        if self.adv_lookback_bars < 1 or self.volatility_lookback_bars < 2:
            raise ValueError("ADV lookback must be >= 1 and volatility lookback must be >= 2")
        if not np.isfinite(self.fallback_bar_volatility) or self.fallback_bar_volatility <= 0:
            raise ValueError("fallback_bar_volatility must be positive")
        if not str(self.bar_frequency).strip():
            raise ValueError("bar_frequency must be explicit")
        if not np.isfinite(self.periods_per_year) or self.periods_per_year <= 0:
            raise ValueError("periods_per_year must be positive")
        if self.trading_calendar not in {"BUSINESS_DAY", "CALENDAR_DAY"}:
            raise ValueError("trading_calendar must be BUSINESS_DAY or CALENDAR_DAY")
        adjusted_aliases = {"adjusted", "total_return", "total_return_adjusted", "adjusted_total_return"}
        if self.price_basis not in {"raw", *adjusted_aliases}:
            raise ValueError("price_basis must be raw or total_return_adjusted")
        if self.corporate_action_policy not in {"apply_if_present", "require", "ignore"}:
            raise ValueError("Unsupported corporate_action_policy")
        if self.price_basis in adjusted_aliases and self.corporate_action_policy == "require":
            raise ValueError("Corporate actions cannot be applied again to total-return-adjusted prices")
        if self.short_sale_policy not in {"allow_unverified", "require"}:
            raise ValueError("short_sale_policy must be allow_unverified or require")
        if self.settlement_days < 0:
            raise ValueError("settlement_days must be non-negative")
        if self.settlement_cash_policy != "trade_date_proxy":
            raise ValueError(
                "Only trade_date_proxy is implemented; settlement-date buying-power simulation is unavailable"
            )
        if self.annual_borrow_bps is not None and (
            not np.isfinite(self.annual_borrow_bps) or self.annual_borrow_bps < 0
        ):
            raise ValueError("annual_borrow_bps must be finite and non-negative")


def _normalise_bars(bars: pd.DataFrame) -> pd.DataFrame:
    clean = bars.copy()
    clean.columns = [str(c).strip().lower().replace(" ", "_") for c in clean.columns]
    aliases = {
        "dividends": "dividend",
        "stock_splits": "split",
        "is_shortable": "shortable",
        "locate": "locate_available",
    }
    for source, target in aliases.items():
        if source in clean.columns and target not in clean.columns:
            clean = clean.rename(columns={source: target})
    needed = {"open", "high", "low", "close"}
    missing = sorted(needed.difference(clean.columns))
    if missing:
        raise ValueError("Missing OHLC fields: " + ", ".join(missing))
    clean = clean.sort_index()
    for column in needed | {"volume", "borrow_rate", "dividend", "split"}:
        if column in clean:
            clean[column] = pd.to_numeric(clean[column], errors="coerce")
    for column in {"shortable", "locate_available"}:
        if column in clean:
            values = clean[column]
            if not pd.api.types.is_bool_dtype(values):
                values = values.map({
                    True: True, False: False, 1: True, 0: False,
                    "1": True, "0": False, "true": True, "false": False,
                    "TRUE": True, "FALSE": False, "yes": True, "no": False,
                    "YES": True, "NO": False,
                })
            clean[column] = values.astype("boolean")
    return clean


def _causal_forecasts(clean: pd.DataFrame, config: ExecutionModelConfig) -> tuple[pd.Series, pd.Series]:
    """Return forecasts known immediately before each bar opens.

    The shift is deliberately unconditional: neither the current close nor the
    current full-session volume may participate in an opening fill.
    """
    close_returns = clean["close"].pct_change()
    volatility = (
        close_returns.rolling(config.volatility_lookback_bars, min_periods=2)
        .std(ddof=0)
        .shift(1)
        .fillna(config.fallback_bar_volatility)
    )
    if "volume" in clean:
        observed_volume = clean["volume"].where(clean["volume"] > 0)
        adv = observed_volume.rolling(config.adv_lookback_bars, min_periods=1).mean().shift(1)
    else:
        adv = pd.Series(np.nan, index=clean.index, dtype=float)
    return volatility.astype(float), adv.astype(float)


def _settlement_date(timestamp: object, config: ExecutionModelConfig) -> str:
    value = pd.Timestamp(timestamp)
    if config.trading_calendar == "BUSINESS_DAY":
        value = value + pd.tseries.offsets.BDay(config.settlement_days)
    else:
        value = value + pd.Timedelta(days=config.settlement_days)
    return str(value.date())


def _prior_value(clean: pd.DataFrame, column: str, i: int) -> object | None:
    """Return the last value observable before bar ``i`` opens."""
    if column not in clean.columns or i <= 0:
        return None
    value = clean[column].iloc[i - 1]
    return None if pd.isna(value) else value


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
    if clean.index.has_duplicates:
        return LedgerResult(
            AvailabilityState.UNAVAILABLE,
            "DATA REQUIRED: duplicate bar timestamps",
            diagnostics={"fail_closed": True},
        )
    ohlc = clean[["open", "high", "low", "close"]]
    if (
        not bool(np.isfinite(ohlc.to_numpy(dtype=float)).all())
        or bool((ohlc <= 0.0).to_numpy().any())
    ):
        return LedgerResult(
            AvailabilityState.UNAVAILABLE,
            "DATA REQUIRED: OHLC bars must be complete, finite and strictly positive",
            diagnostics={"fail_closed": True},
        )
    invalid_envelope = (clean["high"] < clean[["open", "close"]].max(axis=1)) | (
        clean["low"] > clean[["open", "close"]].min(axis=1)
    )
    if bool(invalid_envelope.any()):
        return LedgerResult(
            AvailabilityState.UNAVAILABLE,
            "DATA REQUIRED: invalid OHLC envelope",
            diagnostics={"fail_closed": True},
        )
    if "borrow_rate" in clean and bool((clean["borrow_rate"].dropna() < 0.0).any()):
        return LedgerResult(
            AvailabilityState.UNAVAILABLE,
            "DATA REQUIRED: borrow rates must be non-negative",
            diagnostics={"fail_closed": True},
        )
    exposure = pd.to_numeric(target_exposure.reindex(clean.index), errors="coerce").ffill().fillna(0.0)
    if len(clean) < config.signal_latency_bars + 2:
        return LedgerResult(AvailabilityState.UNAVAILABLE, "DATA REQUIRED: insufficient bars")

    adjusted_aliases = {"adjusted", "total_return", "total_return_adjusted", "adjusted_total_return"}
    adjusted_price_basis = config.price_basis in adjusted_aliases
    declared_data_basis = str(bars.attrs.get("price_basis", "unspecified")).strip().lower()
    declared_adjusted = declared_data_basis in adjusted_aliases
    if declared_data_basis != "unspecified" and declared_adjusted != adjusted_price_basis:
        return LedgerResult(
            AvailabilityState.UNAVAILABLE,
            "DATA REQUIRED: execution price_basis conflicts with the market-data declaration",
            diagnostics={
                "configured_price_basis": config.price_basis,
                "declared_price_basis": declared_data_basis,
                "fail_closed": True,
            },
        )

    action_columns = {"dividend", "split"}
    supplied_actions = action_columns.intersection(clean.columns)
    if config.corporate_action_policy == "require" and supplied_actions != action_columns:
        missing = sorted(action_columns.difference(supplied_actions))
        return LedgerResult(
            AvailabilityState.UNAVAILABLE,
            "DATA REQUIRED: raw-price corporate actions missing: " + ", ".join(missing),
            diagnostics={
                "corporate_action_policy": config.corporate_action_policy,
                "price_basis": config.price_basis,
                "fail_closed": True,
            },
        )
    if config.corporate_action_policy == "require" and bool(clean[list(action_columns)].isna().to_numpy().any()):
        return LedgerResult(
            AvailabilityState.UNAVAILABLE,
            "DATA REQUIRED: corporate-action fields contain unknown observations",
            diagnostics={
                "corporate_action_policy": config.corporate_action_policy,
                "price_basis": config.price_basis,
                "fail_closed": True,
            },
        )
    if not adjusted_price_basis and "split" in clean:
        split_values = pd.to_numeric(clean["split"], errors="coerce")
        if bool((split_values.dropna() < 0).any()):
            return LedgerResult(
                AvailabilityState.UNAVAILABLE,
                "DATA REQUIRED: split ratios must be positive (zero denotes no event)",
                diagnostics={"corporate_action_policy": config.corporate_action_policy, "fail_closed": True},
            )

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

    rolling_vol, adv_forecast = _causal_forecasts(clean, config)
    cash = float(config.initial_capital)
    position = 0.0
    orders: list[Order] = []
    fills: list[Fill] = []
    rows: list[dict[str, float | str]] = []
    pending: list[tuple[int, float]] = []
    total_cost = 0.0
    requested_quantity = 0.0
    filled_quantity = 0.0
    rejected = 0
    partial = 0
    liquidity_forecast_failures = 0
    short_gate_failures = 0
    short_borrow_missing = False
    unverified_short_exposure = False
    split_events = 0
    dividend_events = 0
    corporate_action_cash = 0.0

    for i, (timestamp, row) in enumerate(clean.iterrows()):
        close = float(row["close"])
        open_price = float(row["open"])

        split_ratio = 1.0
        dividend = 0.0
        if not adjusted_price_basis and config.corporate_action_policy != "ignore":
            if "split" in clean and np.isfinite(row.get("split", np.nan)):
                candidate = float(row["split"])
                split_ratio = candidate if candidate > 0 else 1.0
            if "dividend" in clean and np.isfinite(row.get("dividend", np.nan)):
                dividend = float(row["dividend"])
            if split_ratio != 1.0:
                position *= split_ratio
                split_events += 1
            if dividend != 0.0 and position != 0.0:
                dividend_cash = position * dividend
                cash += dividend_cash
                corporate_action_cash += dividend_cash
                dividend_events += 1

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
                requested_quantity += abs(requested)
                volume = float(adv_forecast.iloc[i]) if np.isfinite(adv_forecast.iloc[i]) else None
                fill_quantity = abs(requested)
                liquidity_flag = "FULL"
                order_reasons: list[str] = []

                intended_position = position + requested
                existing_short = max(-position, 0.0)
                intended_short = max(-intended_position, 0.0)
                short_increase = max(intended_short - existing_short, 0.0)
                # Locate/shortable/borrow gates apply only to newly created or
                # increased short exposure.  A BUY that covers an existing
                # short is risk-reducing and must remain executable even after
                # locate availability disappears.
                if short_increase > 1e-10:
                    if config.short_sale_policy == "require":
                        shortable = _prior_value(clean, "shortable", i)
                        locate = _prior_value(clean, "locate_available", i)
                        borrow = _prior_value(clean, "borrow_rate", i)
                        gate_reasons: list[str] = []
                        if shortable is None:
                            gate_reasons.append("shortable status is not affirmatively true as of the prior bar")
                        elif not bool(shortable):
                            gate_reasons.append("instrument is not shortable as of the prior bar")
                        if config.require_locate and not bool(locate):
                            gate_reasons.append("locate is unavailable as of the prior bar")
                        if borrow is None and config.annual_borrow_bps is None:
                            gate_reasons.append("borrow rate is unavailable as of the prior bar")
                        if gate_reasons:
                            short_gate_failures += 1
                            order_reasons.append("short gate: " + "; ".join(gate_reasons))
                            # A sell order may close an existing long, but it may
                            # never create or increase an unlocatable short.
                            fill_quantity = min(fill_quantity, max(position, 0.0))
                    else:
                        shortable = _prior_value(clean, "shortable", i)
                        locate = _prior_value(clean, "locate_available", i)
                        unverified_short_exposure = (
                            shortable is None
                            or not bool(shortable)
                            or (config.require_locate and not bool(locate))
                        ) or unverified_short_exposure

                if config.model != "constant" and volume is None:
                    fill_quantity = 0.0
                    liquidity_forecast_failures += 1
                    order_reasons.append("no lagged ADV was available before the opening fill")
                elif volume is not None and fill_quantity > 0:
                    cap = config.max_participation * volume
                    if fill_quantity > cap:
                        if config.allow_partial_fills and cap > 0:
                            fill_quantity = cap
                            liquidity_flag = "PARTIAL"
                            order_reasons.append("lagged ADV participation cap")
                        else:
                            fill_quantity = 0.0
                            order_reasons.append("lagged ADV participation cap exceeded")

                if fill_quantity <= 0:
                    order_status = "REJECTED"
                    rejected += 1
                elif fill_quantity + 1e-10 < abs(requested):
                    order_status = "PARTIAL"
                    liquidity_flag = "PARTIAL"
                    partial += 1
                else:
                    order_status = "FILLED"
                orders.append(Order(
                    order_id, str(timestamp), symbol, side, abs(requested),
                    target_exposure=target,
                    status=order_status,
                    reason="; ".join(order_reasons),
                ))
                if fill_quantity > 0:
                    signed_qty = fill_quantity if side == "BUY" else -fill_quantity
                    try:
                        impact_bps, participation = _impact_bps(
                            config.model,
                            quantity=fill_quantity,
                            volume=volume,
                            price=open_price,
                            volatility=float(rolling_vol.iloc[i]),
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
                    filled_quantity += fill_quantity
                    day_turnover += fill_quantity * open_price
                    day_cost += explicit_implicit
                    total_cost += explicit_implicit
                    fills.append(Fill(
                        f"FILL-{i:06d}", order_id, str(timestamp), symbol, side,
                        float(fill_quantity), open_price, float(fill_price), float(commission),
                        float(spread_cost), float(impact_cost), float(slippage_cost),
                        None if participation is None else float(participation),
                        liquidity_flag, _settlement_date(timestamp, config),
                    ))

        borrow_cost = 0.0
        if position < 0:
            prior_borrow = _prior_value(clean, "borrow_rate", i)
            annual_borrow_bps = float(prior_borrow) if prior_borrow is not None else config.annual_borrow_bps
            if annual_borrow_bps is not None:
                borrow_cost = abs(position) * close * annual_borrow_bps / 10_000.0 / config.periods_per_year
                cash -= borrow_cost
                total_cost += borrow_cost
                day_cost += borrow_cost
            else:
                short_borrow_missing = True

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
            "adv_forecast": float(adv_forecast.iloc[i]) if np.isfinite(adv_forecast.iloc[i]) else np.nan,
            "volatility_forecast": float(rolling_vol.iloc[i]),
            "split_ratio": split_ratio,
            "dividend_per_share": dividend,
        })

    daily = pd.DataFrame(rows, index=clean.index)
    nav_values = pd.to_numeric(daily["nav"], errors="coerce").to_numpy(dtype=float)
    prior_nav = np.concatenate(([float(config.initial_capital)], nav_values[:-1]))
    with np.errstate(divide="ignore", invalid="ignore"):
        daily["return"] = np.divide(
            nav_values,
            prior_nav,
            out=np.full_like(nav_values, np.nan),
            where=np.isfinite(prior_nav) & (prior_nav != 0.0),
        ) - 1.0
    anchored_peaks = np.maximum.accumulate(
        np.concatenate(([float(config.initial_capital)], nav_values))
    )[1:]
    with np.errstate(divide="ignore", invalid="ignore"):
        daily["drawdown"] = np.divide(
            nav_values,
            anchored_peaks,
            out=np.full_like(nav_values, np.nan),
            where=np.isfinite(anchored_peaks) & (anchored_peaks != 0.0),
        ) - 1.0
    fill_ratio = min(filled_quantity / requested_quantity, 1.0) if requested_quantity > 0 else 1.0
    if short_gate_failures:
        status = AvailabilityState.UNAVAILABLE
        reason = "DATA REQUIRED: one or more requested shorts failed the shortable/locate/borrow gate"
    elif liquidity_forecast_failures:
        status = AvailabilityState.UNAVAILABLE
        reason = "DATA REQUIRED: one or more opening orders lacked a causal ADV forecast"
    elif short_borrow_missing:
        status = AvailabilityState.PARTIAL
        reason = "PARTIAL: short exposure present but borrow/rebate data unavailable"
    else:
        status = AvailabilityState.AVAILABLE
        reason = "Event ledger complete"
    return LedgerResult(
        status,
        reason,
        orders=orders,
        fills=fills,
        daily=daily,
        diagnostics={
            "model": config.model,
            "target_timing": config.target_timing,
            "target_timing_contract": (
                "raw signal; latency enforced"
                if config.target_timing == "raw_signal"
                else "caller-certified pre-lagged target; no implicit extra lag"
            ),
            "lookahead_guard_bars": config.signal_latency_bars,
            "fill_clock": "bar open",
            "volume_forecast": f"rolling ADV({config.adv_lookback_bars}) shifted by one bar",
            "volatility_forecast": (
                f"close-to-close volatility({config.volatility_lookback_bars}) shifted by one bar"
            ),
            "market_observation_lag_bars": 1,
            "forecast_is_causal": True,
            "causal_inputs_only": True,
            "bar_frequency": config.bar_frequency,
            "periods_per_year": float(config.periods_per_year),
            "trading_calendar": config.trading_calendar,
            "exchange_holiday_calendar_enforced": False,
            "settlement_days": config.settlement_days,
            "settlement_cash_policy": config.settlement_cash_policy,
            "cash_settlement_enforced": False,
            "settlement_assumption": (
                "trade-date cash accounting proxy; settlement_date is metadata and does not model "
                "cash-account buying-power restrictions"
            ),
            "price_basis": config.price_basis,
            "corporate_action_policy": config.corporate_action_policy,
            "corporate_action_integrity_verified": (
                adjusted_price_basis or supplied_actions == action_columns
            ),
            "split_events_applied": split_events,
            "dividend_events_applied": dividend_events,
            "corporate_action_cash": float(corporate_action_cash),
            "total_cost": float(total_cost),
            "filled_orders": len(fills),
            "requested_quantity": float(requested_quantity),
            "filled_quantity": float(filled_quantity),
            "fill_ratio": float(fill_ratio),
            "partial_orders": partial,
            "rejected_orders": rejected,
            "liquidity_forecast_failures": liquidity_forecast_failures,
            "short_sale_policy": config.short_sale_policy,
            "short_gate_failures": short_gate_failures,
            "short_borrow_available": not short_borrow_missing,
            "unverified_short_exposure": unverified_short_exposure,
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
