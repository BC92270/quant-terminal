"""Deterministic multi-asset, multi-currency bar-event engine.

Signals are target portfolio weights observed at a timestamp.  They are never
eligible for execution until the next strictly later bar for each instrument.
The engine is intentionally independent from the statistical approval layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
import math
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .fx import FXMatrix, MissingFXRate
from .margin import MarginSnapshot, UniversalMarginModel
from .portfolio import PortfolioLedger
from .security import SecurityMaster
from .types import AssetClass, Instrument, OptionRight, SettlementType


@dataclass(frozen=True)
class UniversalEngineConfig:
    base_currency: str = "USD"
    initial_cash: float = 1_000_000.0
    commission_bps: float = 0.5
    spread_bps: float = 2.0
    slippage_bps: float = 1.0
    impact_bps_at_full_participation: float = 25.0
    max_participation: float = 0.10
    fx_conversion_bps: float = 1.0
    auto_fx: bool = True
    allow_short: bool = False
    allow_fractional: bool = True
    allow_fractional_contracts: bool = False
    require_volume: bool = True
    max_target_weight: float = 3.0
    max_gross_exposure: float = 4.0
    rebalance_tolerance_weight: float = 0.001
    liquidate_on_margin_call: bool = True
    periods_per_year: float = 252.0
    data_timezone: str = "UTC"
    price_basis: str = "raw"
    apply_corporate_actions: bool = True
    initial_fx_rates: Mapping[str, float] = field(default_factory=dict)
    max_fx_staleness_seconds: float | None = 7.0 * 24.0 * 60.0 * 60.0

    def validate(self) -> None:
        if len(str(self.base_currency).strip()) != 3:
            raise ValueError("base_currency must be explicit")
        if not math.isfinite(self.initial_cash) or self.initial_cash <= 0:
            raise ValueError("initial_cash must be finite and positive")
        for name in (
            "commission_bps",
            "spread_bps",
            "slippage_bps",
            "impact_bps_at_full_participation",
            "fx_conversion_bps",
        ):
            if not math.isfinite(float(getattr(self, name))) or float(getattr(self, name)) < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        if not 0 < float(self.max_participation) <= 1:
            raise ValueError("max_participation must be in (0, 1]")
        if self.max_target_weight <= 0 or self.max_gross_exposure <= 0:
            raise ValueError("exposure limits must be positive")
        if not 0 <= float(self.rebalance_tolerance_weight) <= 0.10:
            raise ValueError("rebalance_tolerance_weight must be in [0, 0.10]")
        if self.periods_per_year <= 0:
            raise ValueError("periods_per_year must be positive")
        if (
            self.max_fx_staleness_seconds is not None
            and float(self.max_fx_staleness_seconds) < 0
        ):
            raise ValueError("max_fx_staleness_seconds must be non-negative or None")
        if self.price_basis not in {"raw", "adjusted", "total_return_adjusted"}:
            raise ValueError("unsupported price_basis")
        if self.price_basis != "raw" and self.apply_corporate_actions:
            raise ValueError("corporate actions cannot be replayed on adjusted prices")


@dataclass
class UniversalRunResult:
    status: str
    reason: str
    daily: pd.DataFrame
    orders: pd.DataFrame
    fills: pd.DataFrame
    events: pd.DataFrame
    positions: pd.DataFrame
    cash: pd.DataFrame
    diagnostics: dict[str, Any]

    def records(self) -> dict[str, list[dict[str, Any]]]:
        def rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
            if not isinstance(frame, pd.DataFrame) or frame.empty:
                return []
            return frame.reset_index().to_dict(orient="records")

        return {
            "orders": rows(self.orders),
            "fills": rows(self.fills),
            "events": rows(self.events),
            "positions": rows(self.positions),
            "cash": rows(self.cash),
        }


def _utc_index(index: Any, timezone_name: str, *, label: str) -> pd.DatetimeIndex:
    parsed = pd.DatetimeIndex(pd.to_datetime(index, errors="coerce"))
    if parsed.isna().any():
        raise ValueError(f"{label} contains invalid timestamps")
    if parsed.tz is None:
        if not str(timezone_name).strip():
            raise ValueError(f"{label} requires an explicit source timezone")
        parsed = parsed.tz_localize(timezone_name, ambiguous="raise", nonexistent="raise")
    return parsed.tz_convert("UTC")


def _normalise_bars(frame: pd.DataFrame, timezone_name: str, symbol: str) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError(f"{symbol}: market data is empty")
    clean = frame.copy()
    clean.columns = [str(column).strip().lower().replace(" ", "_") for column in clean.columns]
    aliases = {"stock_splits": "split", "dividends": "dividend"}
    clean = clean.rename(columns={key: value for key, value in aliases.items() if key in clean})
    missing = sorted({"open", "high", "low", "close"}.difference(clean.columns))
    if missing:
        raise ValueError(f"{symbol}: missing OHLC fields: {', '.join(missing)}")
    clean.index = _utc_index(clean.index, timezone_name, label=f"{symbol} bars")
    if clean.index.has_duplicates:
        raise ValueError(f"{symbol}: duplicate market timestamps")
    clean = clean.sort_index()
    numeric = {
        "open", "high", "low", "close", "volume", "split", "dividend",
        "funding_rate", "rollover_rate", "borrow_rate", "gas_fee",
        "spinoff_ratio", "spinoff_cost_allocation", "rights_ratio",
        "rights_cost_allocation", "merger_cash", "symbol_change_ratio",
    }
    for column in numeric.intersection(clean.columns):
        clean[column] = pd.to_numeric(clean[column], errors="coerce")
    ohlc = clean[["open", "high", "low", "close"]]
    invalid = (
        ohlc.isna().any(axis=1)
        | (ohlc <= 0).any(axis=1)
        | (clean["high"] < clean[["open", "close"]].max(axis=1))
        | (clean["low"] > clean[["open", "close"]].min(axis=1))
    )
    if bool(invalid.any()):
        raise ValueError(f"{symbol}: invalid OHLC observations")
    return clean


def _normalise_series(series: pd.Series, timezone_name: str, label: str) -> pd.Series:
    clean = pd.to_numeric(series, errors="coerce").copy()
    clean.index = _utc_index(clean.index, timezone_name, label=label)
    if clean.index.has_duplicates:
        raise ValueError(f"{label} contains duplicate timestamps")
    return clean.sort_index()


def _round_lot(quantity: float, lot: float, fractional: bool) -> float:
    effective_lot = float(lot) if not fractional else min(float(lot), 1e-8)
    raw_units = abs(float(quantity)) / effective_lot
    nearest_units = round(raw_units)
    units = (
        int(nearest_units)
        if math.isclose(raw_units, nearest_units, rel_tol=2e-14, abs_tol=1e-8)
        else math.floor(raw_units + 1e-12)
    )
    return math.copysign(units * effective_lot, quantity) if units else 0.0


def _instrument_lot(instrument: Instrument, config: UniversalEngineConfig) -> float:
    """Return the enforceable quantity increment for an instrument.

    Futures and listed options represent contracts.  They remain integral by
    default even when the portfolio permits fractional cash assets.  The
    dedicated opt-in keeps the previous flexibility available for venues that
    genuinely list fractional contracts.
    """

    lot = float(instrument.lot_size)
    if (
        instrument.asset_class in {AssetClass.FUTURE, AssetClass.OPTION}
        and not config.allow_fractional_contracts
    ):
        return max(lot, 1.0)
    return lot


def _round_instrument_quantity(
    quantity: float,
    instrument: Instrument,
    config: UniversalEngineConfig,
) -> float:
    fractional = bool(config.allow_fractional)
    if instrument.asset_class in {AssetClass.FUTURE, AssetClass.OPTION}:
        fractional = bool(config.allow_fractional_contracts)
    return _round_lot(quantity, _instrument_lot(instrument, config), fractional)


def _quantity_tolerance(
    quantity: float,
    instrument: Instrument,
    config: UniversalEngineConfig,
) -> float:
    return max(
        1e-12,
        _instrument_lot(instrument, config) * 1e-6,
        abs(float(quantity)) * 1e-10,
    )


def _round_fill_price(price: float, tick_size: float, signed_quantity: float) -> float:
    """Round executions to a valid tick without improving the simulated fill."""

    value = float(price)
    tick = float(tick_size)
    ratio = value / tick
    if signed_quantity > 0:
        ticks = math.ceil(ratio - 1e-12)
    else:
        ticks = math.floor(ratio + 1e-12)
    return max(float(ticks) * tick, tick)


def _settlement_at(timestamp: pd.Timestamp, days: int) -> datetime:
    if int(days) <= 0:
        return timestamp.to_pydatetime()
    return (timestamp + pd.offsets.BDay(int(days))).to_pydatetime()


class UniversalBacktestEngine:
    def __init__(
        self,
        *,
        security_master: SecurityMaster,
        config: UniversalEngineConfig | None = None,
        margin_model: UniversalMarginModel | None = None,
    ) -> None:
        self.security_master = security_master
        self.config = config or UniversalEngineConfig()
        self.config.validate()
        self.margin_model = margin_model or UniversalMarginModel()

    def _instrument_map(
        self, market_data: Mapping[str, pd.DataFrame]
    ) -> tuple[dict[str, Instrument], dict[str, pd.DataFrame]]:
        instruments: dict[str, Instrument] = {}
        frames: dict[str, pd.DataFrame] = {}
        for supplied_key, frame in market_data.items():
            instrument = self.security_master.get(str(supplied_key))
            key = instrument.key
            if key in frames:
                raise ValueError(f"duplicate market feed for {key}")
            instruments[key] = instrument
            frames[key] = _normalise_bars(
                frame, self.config.data_timezone, instrument.symbol
            )
        if not frames:
            raise ValueError("at least one market feed is required")
        return instruments, frames

    def _targets(
        self,
        target_weights: pd.DataFrame,
        instruments: Mapping[str, Instrument],
        target_available_at: pd.Series | None,
    ) -> tuple[pd.DataFrame, pd.Series]:
        if not isinstance(target_weights, pd.DataFrame) or target_weights.empty:
            raise ValueError("target_weights must be a non-empty DataFrame")
        targets = target_weights.copy()
        targets.index = _utc_index(
            targets.index, self.config.data_timezone, label="target event times"
        )
        if targets.index.has_duplicates:
            raise ValueError("target event times contain duplicates")
        targets = targets.sort_index()
        aliases: dict[str, str] = {}
        for column in targets.columns:
            instrument = self.security_master.get(str(column))
            if instrument.key not in instruments:
                raise ValueError(f"target has no subscribed feed: {column}")
            aliases[str(column)] = instrument.key
        targets = targets.rename(columns=aliases)
        if targets.columns.duplicated().any():
            raise ValueError("multiple target columns resolve to the same instrument")
        targets = targets.apply(pd.to_numeric, errors="coerce")
        finite = targets.replace([np.inf, -np.inf], np.nan)
        if bool((finite.abs() > float(self.config.max_target_weight)).any(axis=None)):
            raise ValueError("target weight exceeds the per-instrument limit")
        gross = finite.abs().sum(axis=1, min_count=1)
        if bool((gross > float(self.config.max_gross_exposure) + 1e-12).any()):
            raise ValueError("target portfolio exceeds the gross exposure limit")
        if target_available_at is None:
            available = pd.Series(targets.index, index=targets.index)
        else:
            raw_available = pd.to_datetime(target_available_at, errors="coerce")
            available = pd.Series(
                _utc_index(raw_available, self.config.data_timezone, label="target available_at"),
                index=targets.index,
            )
        if available.isna().any():
            raise ValueError("target available_at contains invalid timestamps")
        event_ns = targets.index.view("i8")
        available_ns = pd.DatetimeIndex(available).view("i8")
        if bool((available_ns < event_ns).any()):
            raise ValueError("target cannot be available before its event time")
        return finite, available

    def run(
        self,
        *,
        market_data: Mapping[str, pd.DataFrame],
        target_weights: pd.DataFrame,
        fx_rates: Mapping[str, pd.Series] | None = None,
        cash_rates: Mapping[str, pd.Series] | None = None,
        target_available_at: pd.Series | None = None,
    ) -> UniversalRunResult:
        instruments, frames = self._instrument_map(market_data)
        targets, available = self._targets(
            target_weights, instruments, target_available_at
        )
        fx = FXMatrix(self.config.base_currency)
        start_stamp = min(frame.index.min() for frame in frames.values()).to_pydatetime()
        for pair, value in sorted(dict(self.config.initial_fx_rates).items()):
            left, right = str(pair).replace("-", "/").upper().split("/", 1)
            fx.set_rate(left, right, float(value), as_of=start_stamp)
        normalised_fx: dict[tuple[str, str], pd.Series] = {}
        for pair, series in dict(fx_rates or {}).items():
            left, right = str(pair).replace("-", "/").upper().split("/", 1)
            normalised_fx[(left, right)] = _normalise_series(
                series, self.config.data_timezone, f"FX {left}/{right}"
            )
        normalised_cash_rates: dict[str, pd.Series] = {}
        for currency, series in dict(cash_rates or {}).items():
            code = str(currency).strip().upper()
            if len(code) != 3:
                raise ValueError(f"invalid cash-rate currency: {currency!r}")
            normalised_cash_rates[code] = _normalise_series(
                series, self.config.data_timezone, f"cash rate {code}"
            )

        timeline_values: set[pd.Timestamp] = set()
        for frame in frames.values():
            timeline_values.update(frame.index)
        timeline_values.update(pd.DatetimeIndex(available))
        for series in normalised_fx.values():
            timeline_values.update(series.index)
        for series in normalised_cash_rates.values():
            timeline_values.update(series.index)
        for frame in frames.values():
            if "dividend_payable_at" not in frame:
                continue
            payable = pd.to_datetime(frame["dividend_payable_at"], errors="coerce")
            payable = payable[payable.notna()]
            if len(payable):
                timeline_values.update(
                    _utc_index(
                        payable,
                        self.config.data_timezone,
                        label="dividend payable dates",
                    )
                )
        timeline = pd.DatetimeIndex(sorted(timeline_values))

        signals_by_clock: dict[pd.Timestamp, list[pd.Timestamp]] = {}
        for event_time, known_at in available.items():
            signals_by_clock.setdefault(pd.Timestamp(known_at), []).append(pd.Timestamp(event_time))
        pending: dict[str, tuple[pd.Timestamp, float]] = {}
        pending_is_change: dict[str, bool] = {}
        last_target_values: dict[str, float] = {}
        portfolio = PortfolioLedger(
            str(self.config.base_currency).upper(), float(self.config.initial_cash)
        )
        orders: list[dict[str, Any]] = []
        fills: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        valuations: list[dict[str, Any]] = []
        last_rows: dict[str, pd.Series] = {}
        rejections = 0
        partial_fills = 0
        gross_limit_clips = 0
        margin_calls = 0
        forced_liquidations = 0
        no_trade_targets = 0
        volume_used: dict[tuple[pd.Timestamp, str], float] = {}
        lifecycle_gaps: list[str] = []
        fatal_reasons: list[str] = []
        order_counter = 0
        active_cash_rates: dict[str, float] = {}
        previous_timestamp: pd.Timestamp | None = None

        def record_event(timestamp: pd.Timestamp, kind: str, **payload: Any) -> None:
            events.append({"timestamp": timestamp, "kind": kind, **payload})

        def current_margin() -> MarginSnapshot:
            nav = portfolio.nav(fx, instruments)
            return self.margin_model.requirements(
                equity_base=nav,
                positions=portfolio.positions,
                instruments=instruments,
                fx=fx,
            )

        def execute_delta(
            key: str,
            timestamp: pd.Timestamp,
            row: pd.Series,
            desired_quantity: float,
            *,
            forced: bool = False,
            reason: str = "target_rebalance",
            reference_field: str = "open",
        ) -> str:
            nonlocal order_counter, rejections, partial_fills
            instrument = instruments[key]
            position = portfolio.position(key)
            delta = float(desired_quantity) - float(position.quantity)
            if abs(delta) <= 1e-12:
                return "NOOP"
            order_counter += 1
            order_id = f"UO-{order_counter:09d}"
            reference_price = float(row[reference_field])
            order = {
                "timestamp": timestamp,
                "order_id": order_id,
                "instrument_id": key,
                "symbol": instrument.symbol,
                "side": "BUY" if delta > 0 else "SELL",
                "requested_quantity": abs(delta),
                "desired_quantity": desired_quantity,
                "order_type": "MARKET",
                "reason": reason,
                "status": "NEW",
            }
            if delta < 0 and desired_quantity < -1e-12 and not self.config.allow_short and not forced:
                order.update(status="REJECTED", rejection_reason="short exposure disabled")
                orders.append(order)
                rejections += 1
                return "REJECTED"
            available_quantity = abs(delta)
            volume = float(row.get("volume", np.nan))
            # A margin call or expiry does not create infinite liquidity.
            # Forced orders remain subject to the same causal volume envelope.
            if np.isfinite(volume) and volume > 0:
                remaining_volume = max(
                    float(self.config.max_participation) * volume
                    - volume_used.get((timestamp, key), 0.0),
                    0.0,
                )
                available_quantity = min(
                    available_quantity,
                    remaining_volume,
                )
            elif self.config.require_volume:
                order.update(status="REJECTED", rejection_reason="causal volume unavailable")
                orders.append(order)
                rejections += 1
                return "REJECTED"
            fill_quantity = _round_instrument_quantity(
                available_quantity, instrument, self.config
            )
            if fill_quantity <= 0:
                order.update(status="REJECTED", rejection_reason="quantity below tradable lot")
                orders.append(order)
                rejections += 1
                return "REJECTED"
            fill_quantity = math.copysign(fill_quantity, delta)
            quantity_tolerance = _quantity_tolerance(delta, instrument, self.config)
            if abs(fill_quantity) + quantity_tolerance < abs(delta):
                partial_fills += 1
                order["status"] = "PARTIAL"
            else:
                order["status"] = "FILLED"

            participation = (
                abs(fill_quantity) / volume if np.isfinite(volume) and volume > 0 else 0.0
            )
            impact_bps = float(self.config.impact_bps_at_full_participation) * math.sqrt(
                max(participation, 0.0)
            )
            all_in_bps = (
                float(self.config.spread_bps) / 2.0
                + float(self.config.slippage_bps)
                + impact_bps
            )
            fill_price = _round_fill_price(
                reference_price
                * (1.0 + math.copysign(all_in_bps / 10_000.0, fill_quantity)),
                instrument.tick_size,
                fill_quantity,
            )
            gas_fee = max(float(row.get("gas_fee", 0.0) or 0.0), 0.0)
            if instrument.is_cash_asset and fill_quantity > 0:
                quote_balance = portfolio.cash.balance(instrument.quote_currency)
                spendable_quote = quote_balance
                if (
                    self.config.auto_fx
                    and instrument.quote_currency != portfolio.cash.base_currency
                ):
                    spendable_quote += (
                        portfolio.cash.balance(portfolio.cash.base_currency)
                        * fx.rate(
                            portfolio.cash.base_currency,
                            instrument.quote_currency,
                        )
                        * (1.0 - float(self.config.fx_conversion_bps) / 10_000.0)
                    )
                unit_cost = (
                    fill_price
                    * float(instrument.multiplier)
                    * (1.0 + float(self.config.commission_bps) / 10_000.0)
                )
                affordable_quantity = max(spendable_quote - gas_fee, 0.0) / max(
                    unit_cost, 1e-12
                )
                if abs(fill_quantity) > affordable_quantity + quantity_tolerance:
                    fill_quantity = _round_instrument_quantity(
                        affordable_quantity, instrument, self.config
                    )
                    if fill_quantity <= 0:
                        order.update(
                            status="REJECTED",
                            rejection_reason="insufficient settled cash after costs",
                        )
                        orders.append(order)
                        rejections += 1
                        return "REJECTED"
                    partial_fills += 1
                    order["status"] = "PARTIAL"
                    participation = (
                        abs(fill_quantity) / volume
                        if np.isfinite(volume) and volume > 0
                        else 0.0
                    )
                    impact_bps = float(
                        self.config.impact_bps_at_full_participation
                    ) * math.sqrt(max(participation, 0.0))
                    all_in_bps = (
                        float(self.config.spread_bps) / 2.0
                        + float(self.config.slippage_bps)
                        + impact_bps
                    )
                    fill_price = _round_fill_price(
                        reference_price * (1.0 + all_in_bps / 10_000.0),
                        instrument.tick_size,
                        fill_quantity,
                    )
            notional_quote = abs(
                fill_quantity * fill_price * float(instrument.multiplier)
            )
            commission = notional_quote * float(self.config.commission_bps) / 10_000.0
            cash_required = gas_fee
            if instrument.is_cash_asset and fill_quantity > 0:
                cash_required += notional_quote + commission
            elif not instrument.is_cash_asset:
                cash_required += commission
            try:
                if cash_required > portfolio.cash.balance(instrument.quote_currency) + 1e-10:
                    if not self.config.auto_fx:
                        raise ValueError("automatic FX funding disabled")
                    portfolio.cash.ensure(
                        instrument.quote_currency,
                        cash_required,
                        fx,
                        fee_bps=self.config.fx_conversion_bps,
                    )
            except (ValueError, MissingFXRate) as exc:
                order.update(status="REJECTED", rejection_reason=str(exc))
                orders.append(order)
                rejections += 1
                return "REJECTED"

            settle_at = _settlement_at(timestamp, instrument.settlement_days)
            portfolio.apply_fill(
                instrument,
                fill_quantity,
                fill_price,
                commission,
                timestamp.to_pydatetime(),
                settle_at,
            )
            volume_used[(timestamp, key)] = volume_used.get((timestamp, key), 0.0) + abs(
                fill_quantity
            )
            if gas_fee:
                portfolio.apply_income(
                    instrument,
                    -gas_fee,
                    timestamp.to_pydatetime(),
                    kind="gas_fee",
                )
            fill_id = "UF-" + sha256(
                f"{order_id}|{timestamp.isoformat()}|{fill_quantity}|{fill_price}".encode("utf-8")
            ).hexdigest()[:16].upper()
            fills.append(
                {
                    "timestamp": timestamp,
                    "fill_id": fill_id,
                    "order_id": order_id,
                    "instrument_id": key,
                    "symbol": instrument.symbol,
                    "signed_quantity": fill_quantity,
                    "reference_price": reference_price,
                    "fill_price": fill_price,
                    "commission_quote": commission,
                    "gas_fee_quote": gas_fee,
                    "impact_bps": impact_bps,
                    "participation": participation,
                    "settlement_at": settle_at,
                    "quote_currency": instrument.quote_currency,
                    "forced": forced,
                }
            )
            order["filled_quantity"] = abs(fill_quantity)
            orders.append(order)
            record_event(
                timestamp,
                "fill",
                instrument_id=key,
                order_id=order_id,
                quantity=fill_quantity,
                price=fill_price,
                forced=forced,
            )
            return str(order["status"])

        try:
            for timestamp in timeline:
                stamp_dt = timestamp.to_pydatetime()
                fx.set_valuation_clock(
                    stamp_dt,
                    max_age_seconds=self.config.max_fx_staleness_seconds,
                )
                if previous_timestamp is not None:
                    year_fraction = max(
                        (timestamp - previous_timestamp).total_seconds(), 0.0
                    ) / (365.0 * 24.0 * 60.0 * 60.0)
                    for currency, annual_rate in sorted(active_cash_rates.items()):
                        balance = portfolio.cash.balance(currency)
                        accrual = balance * annual_rate * year_fraction
                        if accrual:
                            portfolio.cash.deposit(currency, accrual)
                            record_event(
                                timestamp,
                                "cash_carry",
                                currency=currency,
                                annual_rate=annual_rate,
                                year_fraction=year_fraction,
                                amount=accrual,
                            )
                matured = portfolio.cash.settle(stamp_dt)
                for item in matured:
                    record_event(
                        timestamp,
                        "settlement",
                        currency=item.currency,
                        amount=item.amount,
                        reference=item.reference,
                    )

                for (left, right), series in normalised_fx.items():
                    if timestamp in series.index and pd.notna(series.loc[timestamp]):
                        fx.set_rate(
                            left,
                            right,
                            float(series.loc[timestamp]),
                            as_of=stamp_dt,
                        )
                        record_event(
                            timestamp,
                            "fx_rate",
                            pair=f"{left}/{right}",
                            rate=float(series.loc[timestamp]),
                        )
                for currency, series in normalised_cash_rates.items():
                    if timestamp in series.index and pd.notna(series.loc[timestamp]):
                        annual_rate = float(series.loc[timestamp])
                        if not np.isfinite(annual_rate) or annual_rate <= -1.0:
                            raise ValueError(
                                f"cash rate for {currency} must be finite and greater than -100%"
                            )
                        active_cash_rates[currency] = annual_rate
                        record_event(
                            timestamp,
                            "cash_rate",
                            currency=currency,
                            annual_rate=annual_rate,
                        )

                rows_at_time: dict[str, pd.Series] = {
                    key: frame.loc[timestamp]
                    for key, frame in frames.items()
                    if timestamp in frame.index
                }

                for key in sorted(rows_at_time):
                    instrument = instruments[key]
                    row = rows_at_time[key]
                    self.security_master.active(key, stamp_dt)
                    if self.config.apply_corporate_actions:
                        split = float(row.get("split", 0.0) or 0.0)
                        if np.isfinite(split) and split not in {0.0, 1.0}:
                            portfolio.apply_split(instrument, split, stamp_dt)
                            record_event(timestamp, "split", instrument_id=key, ratio=split)
                        dividend = float(row.get("dividend", 0.0) or 0.0)
                        position = portfolio.position(key)
                        if np.isfinite(dividend) and dividend != 0.0 and position.quantity:
                            cash = position.quantity * dividend * float(instrument.multiplier)
                            payable_raw = row.get("dividend_payable_at")
                            payable_at: pd.Timestamp | None = None
                            if payable_raw is not None and pd.notna(payable_raw) and str(payable_raw).strip():
                                payable_at = pd.Timestamp(payable_raw)
                                if payable_at.tzinfo is None:
                                    payable_at = payable_at.tz_localize(
                                        self.config.data_timezone,
                                        ambiguous="raise",
                                        nonexistent="raise",
                                    )
                                payable_at = payable_at.tz_convert("UTC")
                                if payable_at < timestamp:
                                    raise ValueError(
                                        f"{key}: dividend payable date precedes entitlement"
                                    )
                                portfolio.cash.schedule(
                                    instrument.quote_currency,
                                    cash,
                                    payable_at.to_pydatetime(),
                                    reference=f"dividend:{instrument.symbol}",
                                )
                            else:
                                portfolio.apply_income(
                                    instrument, cash, stamp_dt, kind="dividend"
                                )
                                lifecycle_gaps.append(
                                    f"{key}: dividend payable date unavailable; same-day cash proxy used"
                                )
                            record_event(
                                timestamp,
                                "dividend_entitlement",
                                instrument_id=key,
                                amount_quote=cash,
                                payable_at=payable_at,
                            )
                        spinoff_ratio = float(row.get("spinoff_ratio", 0.0) or 0.0)
                        rights_ratio = float(row.get("rights_ratio", 0.0) or 0.0)
                        merger_cash = float(row.get("merger_cash", 0.0) or 0.0)
                        if np.isfinite(spinoff_ratio) and spinoff_ratio > 0:
                            distributed_id = str(
                                row.get("spinoff_instrument_id", "") or ""
                            ).strip()
                            if distributed_id:
                                try:
                                    distributed = self.security_master.get(distributed_id)
                                    if distributed.key not in instruments:
                                        raise ValueError("distributed security has no subscribed feed")
                                    distributed_row = rows_at_time.get(distributed.key)
                                    if distributed_row is None:
                                        raise ValueError("distributed security has no contemporaneous mark")
                                    quantity = portfolio.apply_distribution(
                                        instrument,
                                        distributed,
                                        spinoff_ratio,
                                        stamp_dt,
                                        kind="spinoff",
                                        cost_allocation=float(
                                            row.get("spinoff_cost_allocation", 0.0) or 0.0
                                        ),
                                    )
                                    if quantity:
                                        portfolio.mark(
                                            distributed,
                                            float(distributed_row["open"]),
                                            stamp_dt,
                                        )
                                    record_event(
                                        timestamp,
                                        "spinoff",
                                        instrument_id=key,
                                        distributed_instrument_id=distributed.key,
                                        ratio=spinoff_ratio,
                                        quantity=quantity,
                                    )
                                except (KeyError, ValueError) as exc:
                                    lifecycle_gaps.append(f"{key}: spinoff incomplete ({exc})")
                            else:
                                lifecycle_gaps.append(
                                    f"{key}: spinoff_instrument_id required"
                                )
                        if np.isfinite(rights_ratio) and rights_ratio > 0:
                            rights_id = str(
                                row.get("rights_instrument_id", "") or ""
                            ).strip()
                            if rights_id:
                                try:
                                    rights = self.security_master.get(rights_id)
                                    if rights.key not in instruments:
                                        raise ValueError("rights security has no subscribed feed")
                                    rights_row = rows_at_time.get(rights.key)
                                    if rights_row is None:
                                        raise ValueError("rights security has no contemporaneous mark")
                                    quantity = portfolio.apply_distribution(
                                        instrument,
                                        rights,
                                        rights_ratio,
                                        stamp_dt,
                                        kind="rights_distribution",
                                        cost_allocation=float(
                                            row.get("rights_cost_allocation", 0.0) or 0.0
                                        ),
                                    )
                                    if quantity:
                                        portfolio.mark(rights, float(rights_row["open"]), stamp_dt)
                                    record_event(
                                        timestamp,
                                        "rights_distribution",
                                        instrument_id=key,
                                        distributed_instrument_id=rights.key,
                                        ratio=rights_ratio,
                                        quantity=quantity,
                                    )
                                except (KeyError, ValueError) as exc:
                                    lifecycle_gaps.append(
                                        f"{key}: rights distribution incomplete ({exc})"
                                    )
                            else:
                                lifecycle_gaps.append(
                                    f"{key}: rights_instrument_id required"
                                )
                        if np.isfinite(merger_cash) and merger_cash != 0:
                            if merger_cash < 0:
                                lifecycle_gaps.append(
                                    f"{key}: merger consideration cannot be negative"
                                )
                            else:
                                amount = portfolio.apply_cash_merger(
                                    instrument, merger_cash, stamp_dt
                                )
                                pending.pop(key, None)
                                pending_is_change.pop(key, None)
                                record_event(
                                    timestamp,
                                    "cash_merger",
                                    instrument_id=key,
                                    cash_per_unit=merger_cash,
                                    amount_quote=amount,
                                )
                        symbol_change_to = str(
                            row.get("symbol_change_to", "") or ""
                        ).strip()
                        if symbol_change_to:
                            try:
                                destination = self.security_master.get(symbol_change_to)
                                if destination.key not in instruments:
                                    raise ValueError("successor security has no subscribed feed")
                                destination_row = rows_at_time.get(destination.key)
                                if destination_row is None:
                                    raise ValueError("successor security has no contemporaneous mark")
                                ratio = float(row.get("symbol_change_ratio", 1.0) or 1.0)
                                quantity = portfolio.apply_symbol_change(
                                    instrument, destination, stamp_dt, ratio=ratio
                                )
                                if quantity:
                                    portfolio.mark(
                                        destination,
                                        float(destination_row["open"]),
                                        stamp_dt,
                                    )
                                pending.pop(key, None)
                                pending_is_change.pop(key, None)
                                record_event(
                                    timestamp,
                                    "symbol_change",
                                    instrument_id=key,
                                    destination_instrument_id=destination.key,
                                    ratio=ratio,
                                    quantity=quantity,
                                )
                            except (KeyError, ValueError) as exc:
                                lifecycle_gaps.append(
                                    f"{key}: symbol change incomplete ({exc})"
                                )
                    # Every position is valued at the executable opening mark before
                    # sizing. Margined derivatives additionally realize variation P&L.
                    portfolio.mark(instrument, float(row["open"]), stamp_dt)

                for key in sorted(rows_at_time):
                    if key not in pending:
                        continue
                    signal_clock, weight = pending[key]
                    if not signal_clock < timestamp:
                        continue
                    instrument = instruments[key]
                    row = rows_at_time[key]
                    pretrade_nav = portfolio.nav(fx, instruments)
                    quote_to_base = fx.rate(
                        instrument.quote_currency, self.config.base_currency
                    )
                    desired_notional_base = pretrade_nav * float(weight)
                    desired_quantity = desired_notional_base / max(
                        float(row["open"])
                        * float(instrument.multiplier)
                        * quote_to_base,
                        1e-12,
                    )
                    desired_quantity = _round_instrument_quantity(
                        desired_quantity, instrument, self.config
                    )
                    requested_desired_quantity = desired_quantity
                    current = portfolio.position(key).quantity
                    target_was_clipped = False

                    # Enforce gross exposure against the positions that actually
                    # persist in the portfolio, not merely the non-null targets
                    # present on this signal row.
                    snapshot = current_margin()
                    current_notional_base = abs(
                        current
                        * float(row["open"])
                        * float(instrument.multiplier)
                        * quote_to_base
                    )
                    other_gross_base = max(
                        snapshot.gross_notional_base - current_notional_base, 0.0
                    )
                    gross_budget_base = max(
                        max(pretrade_nav, 0.0)
                        * float(self.config.max_gross_exposure)
                        - other_gross_base,
                        0.0,
                    )
                    max_gross_quantity = gross_budget_base / max(
                        float(row["open"])
                        * float(instrument.multiplier)
                        * quote_to_base,
                        1e-12,
                    )
                    if (
                        abs(desired_quantity)
                        > max_gross_quantity
                        + _quantity_tolerance(
                            desired_quantity, instrument, self.config
                        )
                    ):
                        desired_quantity = math.copysign(
                            _round_instrument_quantity(
                                max_gross_quantity, instrument, self.config
                            ),
                            desired_quantity,
                        )
                        target_was_clipped = True
                        partial_fills += 1
                        gross_limit_clips += 1
                        record_event(
                            timestamp,
                            "pretrade_gross_clip",
                            instrument_id=key,
                            requested_quantity=abs(requested_desired_quantity),
                            max_quantity=abs(desired_quantity),
                            other_gross_base=other_gross_base,
                            gross_limit_base=max(pretrade_nav, 0.0)
                            * float(self.config.max_gross_exposure),
                        )
                    delta_notional_base = abs(
                        (desired_quantity - current)
                        * float(row["open"])
                        * float(instrument.multiplier)
                        * quote_to_base
                    )
                    if (
                        pretrade_nav > 0
                        and delta_notional_base / pretrade_nav
                        < float(self.config.rebalance_tolerance_weight)
                    ):
                        no_trade_targets += 1
                        record_event(
                            timestamp,
                            "target_no_trade_band",
                            instrument_id=key,
                            drift_weight=delta_notional_base / pretrade_nav,
                        )
                        if target_was_clipped and abs(
                            portfolio.position(key).quantity
                            - requested_desired_quantity
                        ) > _quantity_tolerance(
                            requested_desired_quantity, instrument, self.config
                        ):
                            continue
                        pending.pop(key, None)
                        pending_is_change.pop(key, None)
                        continue
                    if abs(desired_quantity) > abs(current) + 1e-12:
                        try:
                            initial_rate, _ = self.margin_model.rates(
                                instrument, desired_quantity
                            )
                            snapshot = current_margin()
                            current_notional = abs(
                                current
                                * float(row["open"])
                                * float(instrument.multiplier)
                                * quote_to_base
                            )
                            current_requirement = current_notional * initial_rate
                            other_requirement = max(
                                snapshot.initial_required_base - current_requirement, 0.0
                            )
                            affordable = max(pretrade_nav - other_requirement, 0.0)
                            max_quantity = affordable / max(
                                initial_rate
                                * float(row["open"])
                                * float(instrument.multiplier)
                                * quote_to_base,
                                1e-12,
                            )
                            if abs(desired_quantity) > max_quantity + 1e-12:
                                desired_quantity = math.copysign(
                                    _round_instrument_quantity(
                                        max_quantity, instrument, self.config
                                    ),
                                    desired_quantity,
                                )
                                target_was_clipped = True
                                partial_fills += 1
                                record_event(
                                    timestamp,
                                    "pretrade_margin_clip",
                                    instrument_id=key,
                                    max_quantity=abs(desired_quantity),
                                )
                        except ValueError as exc:
                            rejections += 1
                            orders.append(
                                {
                                    "timestamp": timestamp,
                                    "order_id": f"UO-R{rejections:08d}",
                                    "instrument_id": key,
                                    "symbol": instrument.symbol,
                                    "status": "REJECTED",
                                    "rejection_reason": str(exc),
                                    "reason": "pretrade_margin",
                                }
                            )
                            pending.pop(key, None)
                            continue
                    execution_status = execute_delta(
                        key,
                        timestamp,
                        row,
                        desired_quantity,
                        reason="target_rebalance",
                    )
                    target_complete = abs(
                        portfolio.position(key).quantity
                        - requested_desired_quantity
                    ) <= _quantity_tolerance(
                        requested_desired_quantity, instrument, self.config
                    )
                    if (
                        execution_status != "REJECTED"
                        and not target_complete
                        and (execution_status == "PARTIAL" or target_was_clipped)
                    ):
                        record_event(
                            timestamp,
                            "target_remainder",
                            instrument_id=key,
                            requested_quantity=requested_desired_quantity,
                            current_quantity=portfolio.position(key).quantity,
                        )
                        continue
                    pending.pop(key, None)
                    pending_is_change.pop(key, None)

                for key in sorted(rows_at_time):
                    instrument = instruments[key]
                    row = rows_at_time[key]
                    portfolio.mark(instrument, float(row["close"]), stamp_dt)
                    last_rows[key] = row
                    position = portfolio.position(key)
                    if position.quantity:
                        funding_rate = float(row.get("funding_rate", 0.0) or 0.0)
                        if np.isfinite(funding_rate) and funding_rate != 0.0:
                            funding = -position.quantity * float(row["close"]) * float(
                                instrument.multiplier
                            ) * funding_rate
                            portfolio.apply_income(
                                instrument, funding, stamp_dt, kind="funding"
                            )
                            record_event(
                                timestamp,
                                "funding",
                                instrument_id=key,
                                amount_quote=funding,
                            )
                        rollover_rate = float(row.get("rollover_rate", 0.0) or 0.0)
                        if np.isfinite(rollover_rate) and rollover_rate != 0.0:
                            rollover = position.quantity * float(row["close"]) * float(
                                instrument.multiplier
                            ) * rollover_rate
                            portfolio.apply_income(
                                instrument, rollover, stamp_dt, kind="rollover"
                            )
                            record_event(
                                timestamp,
                                "rollover",
                                instrument_id=key,
                                amount_quote=rollover,
                            )
                        borrow_rate = float(row.get("borrow_rate", 0.0) or 0.0)
                        if position.quantity < 0 and np.isfinite(borrow_rate) and borrow_rate > 0:
                            borrow = -abs(
                                position.quantity
                                * float(row["close"])
                                * float(instrument.multiplier)
                            ) * borrow_rate / float(self.config.periods_per_year)
                            portfolio.apply_income(
                                instrument, borrow, stamp_dt, kind="borrow"
                            )
                            record_event(
                                timestamp,
                                "borrow",
                                instrument_id=key,
                                amount_quote=borrow,
                            )

                    delisted = bool(row.get("delisted", False))
                    expired = instrument.expiry is not None and stamp_dt >= instrument.expiry
                    if position.quantity and expired and instrument.asset_class == AssetClass.OPTION:
                        settlement_value = float(row.get("settlement_price", np.nan))
                        settlement_source = "official settlement"
                        if not np.isfinite(settlement_value) or settlement_value < 0:
                            try:
                                underlying = self.security_master.get(
                                    str(instrument.underlying_symbol)
                                )
                                underlying_row = rows_at_time.get(underlying.key)
                                if underlying_row is None:
                                    raise ValueError("contemporaneous underlying mark unavailable")
                                underlying_close = float(underlying_row["close"])
                                if instrument.option_right == OptionRight.CALL:
                                    settlement_value = max(
                                        underlying_close - float(instrument.strike), 0.0
                                    )
                                else:
                                    settlement_value = max(
                                        float(instrument.strike) - underlying_close, 0.0
                                    )
                                settlement_source = "intrinsic value from subscribed underlying"
                            except (KeyError, ValueError, TypeError) as exc:
                                settlement_value = np.nan
                                lifecycle_gaps.append(
                                    f"{key}: option settlement unavailable ({exc})"
                                )
                        if (
                            instrument.settlement_type == SettlementType.CASH
                            and np.isfinite(settlement_value)
                            and settlement_value >= 0
                        ):
                            payout = portfolio.settle_cash_option(
                                instrument, settlement_value, stamp_dt
                            )
                            record_event(
                                timestamp,
                                "option_cash_settlement",
                                instrument_id=key,
                                settlement_value=settlement_value,
                                amount_quote=payout,
                                source=settlement_source,
                            )
                        else:
                            execute_delta(
                                key,
                                timestamp,
                                row,
                                0.0,
                                forced=True,
                                reason="option_expiry_unresolved",
                                reference_field="close",
                            )
                            if instrument.settlement_type == SettlementType.PHYSICAL:
                                lifecycle_gaps.append(
                                    f"{key}: physical exercise/assignment adapter unavailable"
                                )
                    elif position.quantity and expired and instrument.asset_class == AssetClass.FUTURE:
                        roll_to = str(row.get("roll_to", "") or "").strip()
                        rolled = False
                        if roll_to:
                            try:
                                next_contract = self.security_master.get(roll_to)
                                next_row = rows_at_time.get(next_contract.key)
                                if next_contract.asset_class != AssetClass.FUTURE:
                                    raise ValueError("roll target is not a future")
                                if next_row is None:
                                    raise ValueError("roll target has no contemporaneous bar")
                                if (
                                    instrument.root_symbol
                                    and next_contract.root_symbol
                                    and instrument.root_symbol != next_contract.root_symbol
                                ):
                                    raise ValueError("future roots do not match")
                                old_quantity = float(position.quantity)
                                desired_new = (
                                    old_quantity
                                    * float(row["close"])
                                    * float(instrument.multiplier)
                                    / max(
                                        float(next_row["close"])
                                        * float(next_contract.multiplier),
                                        1e-12,
                                    )
                                )
                                desired_new = _round_instrument_quantity(
                                    desired_new, next_contract, self.config
                                )
                                execute_delta(
                                    key,
                                    timestamp,
                                    row,
                                    0.0,
                                    forced=True,
                                    reason="future_roll_close",
                                    reference_field="close",
                                )
                                if abs(portfolio.position(key).quantity) > 1e-12:
                                    raise ValueError("expiring leg was not fully closed")
                                execute_delta(
                                    next_contract.key,
                                    timestamp,
                                    next_row,
                                    desired_new,
                                    reason="future_roll_open",
                                    reference_field="close",
                                )
                                rolled = abs(
                                    portfolio.position(next_contract.key).quantity
                                    - desired_new
                                ) <= max(1e-8, abs(desired_new) * 1e-10)
                                record_event(
                                    timestamp,
                                    "future_roll",
                                    from_instrument=key,
                                    to_instrument=next_contract.key,
                                    old_quantity=old_quantity,
                                    new_quantity=portfolio.position(next_contract.key).quantity,
                                    complete=rolled,
                                )
                                if not rolled:
                                    raise ValueError("next contract was not fully established")
                            except (KeyError, ValueError) as exc:
                                lifecycle_gaps.append(f"{key}: future roll incomplete ({exc})")
                        if not rolled:
                            execute_delta(
                                key,
                                timestamp,
                                row,
                                0.0,
                                forced=True,
                                reason="future_expiry",
                                reference_field="close",
                            )
                            if abs(portfolio.position(key).quantity) > 1e-12:
                                lifecycle_gaps.append(
                                    f"{key}: residual position remained after expiry"
                                )
                    elif position.quantity and (delisted or expired):
                        execute_delta(
                            key,
                            timestamp,
                            row,
                            0.0,
                            forced=True,
                            reason="delisting" if delisted else "expiry",
                            reference_field="close",
                        )
                        if abs(portfolio.position(key).quantity) > 1e-12:
                            lifecycle_gaps.append(
                                f"{key}: residual position remained after lifecycle close"
                            )

                same_day = portfolio.cash.settle(stamp_dt)
                for item in same_day:
                    record_event(
                        timestamp,
                        "settlement",
                        currency=item.currency,
                        amount=item.amount,
                        reference=item.reference,
                    )
                nav = portfolio.nav(fx, instruments)
                margin = current_margin()
                if margin.margin_call:
                    margin_calls += 1
                    record_event(
                        timestamp,
                        "margin_call",
                        maintenance_excess_base=margin.maintenance_excess_base,
                    )
                    if self.config.liquidate_on_margin_call:
                        for key in sorted(portfolio.positions):
                            if not portfolio.position(key).quantity:
                                continue
                            row = rows_at_time.get(key)
                            if row is None:
                                fatal_reasons.append(
                                    f"margin liquidation has no contemporaneous price for {key}"
                                )
                                continue
                            execute_delta(
                                key,
                                timestamp,
                                row,
                                0.0,
                                forced=True,
                                reason="margin_liquidation",
                                reference_field="close",
                            )
                            forced_liquidations += 1
                        nav = portfolio.nav(fx, instruments)
                        margin = current_margin()

                gross = margin.gross_notional_base / nav if nav > 0 else np.nan
                valuations.append(
                    {
                        "timestamp": timestamp,
                        "nav": nav,
                        "gross_exposure": gross,
                        "initial_margin": margin.initial_required_base,
                        "maintenance_margin": margin.maintenance_required_base,
                        "maintenance_excess": margin.maintenance_excess_base,
                        "margin_available": margin.available,
                    }
                )
                if not margin.available:
                    lifecycle_gaps.extend(margin.reasons)

                for event_time in sorted(signals_by_clock.get(timestamp, [])):
                    row = targets.loc[event_time]
                    for key, value in row.items():
                        if pd.notna(value):
                            prior_target = last_target_values.get(key)
                            pending[key] = (timestamp, float(value))
                            pending_is_change[key] = bool(
                                prior_target is None
                                or abs(float(value) - prior_target)
                                > float(self.config.rebalance_tolerance_weight)
                            )
                            last_target_values[key] = float(value)
                            record_event(
                                timestamp,
                                "strategy_target",
                                event_time=event_time,
                                instrument_id=key,
                                target_weight=float(value),
                            )
                previous_timestamp = timestamp
        except (ValueError, KeyError, MissingFXRate) as exc:
            fatal_reasons.append(str(exc))

        daily = pd.DataFrame(valuations)
        if not daily.empty:
            daily = daily.set_index("timestamp").sort_index()
            daily["return"] = daily["nav"].pct_change().fillna(0.0)
            daily["drawdown"] = daily["nav"] / daily["nav"].cummax() - 1.0
        order_frame = pd.DataFrame(orders)
        fill_frame = pd.DataFrame(fills)
        event_frame = pd.DataFrame(events)
        position_frame = pd.DataFrame(
            portfolio.positions_snapshot(fx, instruments)
        )
        cash_frame = pd.DataFrame(portfolio.cash.snapshot(fx))
        reconciled_nav = float(cash_frame.get("base_value", pd.Series(dtype=float)).sum())
        if not position_frame.empty:
            cash_asset_classes = {
                AssetClass.EQUITY.value,
                AssetClass.ETF.value,
                AssetClass.CRYPTO_SPOT.value,
                AssetClass.OPTION.value,
            }
            reconciled_nav += float(
                pd.to_numeric(
                    position_frame.loc[
                        position_frame["asset_class"].isin(cash_asset_classes),
                        "notional_base",
                    ],
                    errors="coerce",
                ).fillna(0.0).sum()
            )
        final_nav = float(daily["nav"].iloc[-1]) if not daily.empty else np.nan
        reconciliation_residual = (
            reconciled_nav - final_nav if np.isfinite(final_nav) else np.nan
        )
        accounting_reconciled = bool(
            np.isfinite(reconciliation_residual)
            and abs(reconciliation_residual)
            <= max(1e-6, abs(final_nav) * 1e-10)
        )
        terminal_target_changes = sorted(
            key for key in pending if pending_is_change.get(key, False)
        )
        if fatal_reasons or daily.empty:
            status = "UNAVAILABLE"
            reason = "DATA REQUIRED: " + "; ".join(dict.fromkeys(fatal_reasons or ["no valuations"]))
        elif rejections or partial_fills or lifecycle_gaps or terminal_target_changes:
            status = "PARTIAL"
            reason = "Run completed with fail-closed limitations"
        else:
            status = "AVAILABLE"
            reason = "Universal event ledger complete"
        diagnostics = {
            "engine": "universal_bar_event_kernel",
            "engine_version": "0.2.0",
            "research_only": True,
            "automatic_production_authorization": False,
            "base_currency": self.config.base_currency,
            "instrument_count": len(instruments),
            "asset_classes": sorted({item.asset_class.value for item in instruments.values()}),
            "currencies": sorted({item.quote_currency for item in instruments.values()} | {self.config.base_currency}),
            "max_fx_staleness_seconds": self.config.max_fx_staleness_seconds,
            "cash_carry_currencies": sorted(normalised_cash_rates),
            "cash_carry_available": set(
                {item.quote_currency for item in instruments.values()}
                | {self.config.base_currency}
            ).issubset(normalised_cash_rates),
            "event_clock": "UTC knowledge/effective time",
            "target_timing_contract": "target known at t; execution strictly after t on next eligible bar",
            "causal_inputs_only": True,
            "multi_currency_cashbook": True,
            "cash_settlement_enforced": True,
            "margin_pretrade": True,
            "maintenance_margin_enforced": True,
            "orders": len(order_frame),
            "fills": len(fill_frame),
            "rejections": rejections,
            "partial_fills": partial_fills,
            "gross_limit_clips": gross_limit_clips,
            "margin_calls": margin_calls,
            "forced_liquidations": forced_liquidations,
            "no_trade_targets": no_trade_targets,
            "rebalance_tolerance_weight": self.config.rebalance_tolerance_weight,
            "fx_conversions": list(portfolio.cash.conversions),
            "accounting_events": list(portfolio.realized_events),
            "accounting_reconciled": accounting_reconciled,
            "accounting_reconciliation_residual_base": reconciliation_residual,
            "pending_settlements": len(portfolio.cash.pending),
            "lifecycle_gaps": sorted(set(lifecycle_gaps)),
            "terminal_targets_without_execution": sorted(pending),
            "terminal_target_changes_without_execution": terminal_target_changes,
            "fatal_reasons": list(dict.fromkeys(fatal_reasons)),
            "price_basis": self.config.price_basis,
            "corporate_actions_replayed": self.config.apply_corporate_actions,
            "sandbox_attested": False,
        }
        return UniversalRunResult(
            status=status,
            reason=reason,
            daily=daily,
            orders=order_frame,
            fills=fill_frame,
            events=event_frame,
            positions=position_frame,
            cash=cash_frame,
            diagnostics=diagnostics,
        )
