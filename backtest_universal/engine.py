"""Deterministic multi-asset, multi-currency bar-event engine.

Signals are target portfolio weights observed at a timestamp.  They are never
eligible for execution until the next strictly later bar for each instrument.
The engine is intentionally independent from the statistical approval layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
import json
import math
from typing import Any, Mapping

import numpy as np
import pandas as pd

from backtest_sdk import Bar, PortfolioSnapshot, Slice

from .fx import FXMatrix, MissingFXRate
from .margin import MarginContext, MarginEngine, MarginSnapshot, UniversalMarginModel
from .option_lifecycle import (
    OptionLifecycleAction,
    OptionLifecycleProcessor,
    OptionLifecycleRequestKind,
    OptionSettlementInstruction,
    OptionSettlementReference,
)
from .orders import (
    OrderKernel,
    OrderRequest,
    OrderSide,
    OrderType,
    TimeInForce,
)
from .portfolio import PortfolioLedger, Position
from .security import SecurityMaster
from .strategy import (
    CausalStrategyRuntime,
    StrategyRuntimeError,
    request_causal_targets,
)
from .types import (
    AssetClass,
    Instrument,
    OptionCalendarContract,
    OptionRight,
    SettlementType,
)


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
    portfolio_snapshot: PortfolioSnapshot | None = None

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
        margin_model: MarginEngine | None = None,
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
            if not isinstance(target_available_at, pd.Series):
                raise TypeError("target_available_at must be a pandas Series")
            indexed_available = target_available_at.copy()
            indexed_available.index = _utc_index(
                indexed_available.index,
                self.config.data_timezone,
                label="target available_at event index",
            )
            if indexed_available.index.has_duplicates:
                raise ValueError("target_available_at event index contains duplicates")
            missing = targets.index.difference(indexed_available.index)
            extra = indexed_available.index.difference(targets.index)
            if len(missing) or len(extra):
                raise ValueError(
                    "target_available_at index must exactly match target event times"
                )
            indexed_available = indexed_available.reindex(targets.index)
            raw_available = pd.to_datetime(indexed_available, errors="coerce")
            available = pd.Series(
                _utc_index(
                    raw_available,
                    self.config.data_timezone,
                    label="target available_at",
                ),
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
        target_weights: pd.DataFrame | None = None,
        fx_rates: Mapping[str, pd.Series] | None = None,
        cash_rates: Mapping[str, pd.Series] | None = None,
        target_available_at: pd.Series | None = None,
        strategy_runtime: CausalStrategyRuntime | None = None,
        option_calendars: Mapping[str, OptionCalendarContract] | None = None,
        margin_sensitivities: Mapping[str, Mapping[str, float]] | None = None,
    ) -> UniversalRunResult:
        instruments, frames = self._instrument_map(market_data)
        if (target_weights is None) == (strategy_runtime is None):
            raise ValueError(
                "exactly one signal source is required: target_weights or strategy_runtime"
            )
        if target_weights is None:
            if target_available_at is not None:
                raise ValueError(
                    "target_available_at is only valid with target_weights"
                )
            targets = pd.DataFrame()
            available = pd.Series(dtype="datetime64[ns, UTC]")
        else:
            targets, available = self._targets(
                target_weights, instruments, target_available_at
            )
        calendar_contracts: dict[str, OptionCalendarContract] = {}
        for supplied_id, calendar in dict(option_calendars or {}).items():
            if not isinstance(calendar, OptionCalendarContract):
                raise TypeError("option_calendars values must be OptionCalendarContract")
            calendar_id = str(supplied_id).strip()
            if calendar_id != calendar.calendar_id:
                raise ValueError("option calendar mapping key must match calendar_id")
            calendar_contracts[calendar_id] = calendar
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
        market_horizon = max(frame.index.max() for frame in frames.values())
        timeline_values.update(pd.DatetimeIndex(available))
        for series in normalised_fx.values():
            timeline_values.update(series.index)
        for series in normalised_cash_rates.values():
            timeline_values.update(series.index)
        for calendar in calendar_contracts.values():
            timeline_values.add(pd.Timestamp(calendar.exercise_cutoff_at))
            timeline_values.add(pd.Timestamp(calendar.settlement_at))
        for instrument in instruments.values():
            if (
                instrument.expiry is not None
                and pd.Timestamp(instrument.expiry) <= market_horizon
            ):
                timeline_values.add(pd.Timestamp(instrument.expiry))
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
        oms = OrderKernel()
        orders: list[dict[str, Any]] = []
        fills: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        valuations: list[dict[str, Any]] = []
        last_rows: dict[str, pd.Series] = {}
        last_row_times: dict[str, pd.Timestamp] = {}
        rejections = 0
        partial_fills = 0
        gross_limit_clips = 0
        margin_calls = 0
        forced_liquidations = 0
        no_trade_targets = 0
        volume_used: dict[tuple[pd.Timestamp, str], float] = {}
        lifecycle_gaps: list[str] = []
        fatal_reasons: list[str] = []
        risk_failures: list[str] = []
        order_counter = 0
        active_cash_rates: dict[str, float] = {}
        previous_timestamp: pd.Timestamp | None = None
        snapshot_sequence = 0
        last_portfolio_snapshot: PortfolioSnapshot | None = None
        last_margin_snapshot: MarginSnapshot | None = None
        portfolio_feedback_slices = 0
        option_lifecycle = OptionLifecycleProcessor()
        pending_option_instructions: dict[
            str, tuple[OptionSettlementInstruction, Instrument | None]
        ] = {}
        option_instructions_resolved = 0
        option_instructions_applied = 0
        physical_option_actions = 0
        option_data_required = 0
        option_data_required_ids: set[str] = set()

        def record_event(timestamp: pd.Timestamp, kind: str, **payload: Any) -> None:
            events.append({"timestamp": timestamp, "kind": kind, **payload})

        def current_margin(
            timestamp: pd.Timestamp,
            *,
            positions: Mapping[str, Position] | None = None,
        ) -> MarginSnapshot:
            nav = portfolio.nav(fx, instruments)
            return self.margin_model.calculate(
                MarginContext(
                    equity_base=nav,
                    positions=(
                        portfolio.positions if positions is None else positions
                    ),
                    instruments=instruments,
                    fx=fx,
                    as_of=timestamp.to_pydatetime(),
                    sensitivities=margin_sensitivities or {},
                )
            )

        def candidate_margin(
            timestamp: pd.Timestamp,
            key: str,
            desired_quantity: float,
            price: float,
        ) -> MarginSnapshot:
            hypothetical = dict(portfolio.positions)
            current = portfolio.position(key)
            hypothetical[key] = Position(
                symbol=current.symbol,
                quantity=float(desired_quantity),
                average_price=float(current.average_price),
                last_price=float(price),
                realized_pnl_quote=float(current.realized_pnl_quote),
            )
            return current_margin(timestamp, positions=hypothetical)

        def build_portfolio_snapshot(
            timestamp: pd.Timestamp,
            nav: float,
            margin: MarginSnapshot,
        ) -> PortfolioSnapshot:
            """Freeze ledger state after all events at ``timestamp``."""

            nonlocal snapshot_sequence
            snapshot_sequence += 1
            position_rows = portfolio.positions_snapshot(fx, instruments)
            positions: dict[str, dict[str, Any]] = {}
            realized_base = 0.0
            unrealized_base = 0.0
            for row in position_rows:
                key = str(row["instrument_id"])
                instrument = instruments[key]
                position = portfolio.position(key)
                realized = fx.to_base(
                    position.realized_pnl_quote, instrument.quote_currency
                )
                unrealized_quote = 0.0
                if not instrument.uses_variation_margin:
                    unrealized_quote = (
                        position.quantity
                        * (position.last_price - position.average_price)
                        * float(instrument.multiplier)
                    )
                unrealized = fx.to_base(
                    unrealized_quote, instrument.quote_currency
                )
                item = dict(row)
                item["market_value_base"] = float(row["notional_base"])
                item["realized_pnl_base"] = realized
                item["unrealized_pnl_base"] = unrealized
                positions[key] = item
                realized_base += realized
                unrealized_base += unrealized
            cash_rows = portfolio.cash.snapshot(fx)
            settled_cash = {
                str(item["currency"]): float(item["settled"])
                for item in cash_rows
            }
            unsettled_cash = {
                str(item["currency"]): float(item["unsettled"])
                for item in cash_rows
            }
            open_orders = [
                {
                    "order_id": item.order_id,
                    "instrument_id": item.symbol,
                    "side": item.side.value,
                    "order_type": item.order_type.value,
                    "time_in_force": item.time_in_force.value,
                    "status": item.status.value,
                    "quantity": float(item.quantity),
                    "filled_quantity": float(item.filled_quantity),
                    "remaining_quantity": float(item.remaining_quantity),
                    "submitted_at": item.submitted_at.isoformat(),
                    "updated_at": (
                        item.updated_at.isoformat() if item.updated_at else None
                    ),
                }
                for item in oms.active_orders()
            ]
            # Keep this language-neutral: protocol v3 transports margin values
            # as finite numbers to Python, JS/TS, C++, Rust and C#.  Model
            # identity and parameter provenance remain in run diagnostics.
            margin_payload: dict[str, float | bool | None] = {
                "available": bool(margin.available),
                "initial_required_base": float(margin.initial_required_base),
                "maintenance_required_base": float(
                    margin.maintenance_required_base
                ),
                "maintenance_excess_base": float(
                    margin.maintenance_excess_base
                ),
                "margin_call": bool(margin.margin_call),
            }
            pnl = {
                "total_base": float(nav - self.config.initial_cash),
                "realized_trade_base": float(realized_base),
                "unrealized_base": float(unrealized_base),
            }
            authoritative_payload = {
                "as_of": timestamp.isoformat(),
                "sequence": snapshot_sequence,
                "positions": positions,
                "cash": settled_cash,
                "unsettled_cash": unsettled_cash,
                "open_orders": open_orders,
                "nav_base": float(nav),
                "margin": margin_payload,
                "pnl": pnl,
                "oms_fill_ledger_sha256": oms.fill_ledger_sha256,
                "applied_fill_ids": sorted(portfolio.applied_oms_fill_ids),
            }
            ledger_sha256 = sha256(
                json.dumps(
                    authoritative_payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                    default=str,
                ).encode("utf-8")
            ).hexdigest()
            return PortfolioSnapshot(
                available=True,
                as_of=timestamp.to_pydatetime(),
                positions=positions,
                cash=settled_cash,
                unsettled_cash=unsettled_cash,
                open_orders=open_orders,
                base_currency=self.config.base_currency,
                nav_base=nav,
                margin=margin_payload,
                pnl=pnl,
                sequence=snapshot_sequence,
                ledger_sha256=ledger_sha256,
                source="OMS_EXECUTION_LEDGER",
                reason="",
            )

        def reject_order_intent(
            key: str,
            timestamp: pd.Timestamp,
            desired_quantity: float,
            *,
            reason: str,
            category: str,
        ) -> None:
            """Record a risk rejection through the same authoritative OMS."""

            nonlocal order_counter, rejections
            instrument = instruments[key]
            delta = float(desired_quantity) - portfolio.position(key).quantity
            if abs(delta) <= 1e-12:
                return
            order_counter += 1
            order_id = f"UO-{order_counter:09d}"
            oms.submit(
                OrderRequest(
                    symbol=key,
                    side=OrderSide.BUY if delta > 0 else OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    quantity=abs(delta),
                    submitted_at=timestamp.to_pydatetime(),
                    time_in_force=TimeInForce.IOC,
                    order_id=order_id,
                    metadata={
                        "instrument_id": key,
                        "display_symbol": instrument.symbol,
                        "desired_quantity": float(desired_quantity),
                        "reason": category,
                    },
                )
            )
            rejected = oms.reject(
                order_id,
                at=timestamp.to_pydatetime(),
                reason=reason,
            )
            orders.append(
                {
                    "timestamp": timestamp,
                    "order_id": order_id,
                    "instrument_id": key,
                    "symbol": instrument.symbol,
                    "side": "BUY" if delta > 0 else "SELL",
                    "requested_quantity": abs(delta),
                    "desired_quantity": desired_quantity,
                    "order_type": "MARKET",
                    "reason": category,
                    "status": "REJECTED",
                    "oms_status": rejected.status.value,
                    "rejection_reason": reason,
                }
            )
            rejections += 1

        def apply_option_instruction(
            key: str,
            instruction: OptionSettlementInstruction,
            underlying: Instrument | None,
            timestamp: pd.Timestamp,
        ) -> None:
            nonlocal option_instructions_applied, physical_option_actions
            option = instruments[key]
            option_lifecycle.apply(
                ledger=portfolio,
                instruction=instruction,
                option=option,
                underlying=underlying,
                at=timestamp.to_pydatetime(),
            )
            event_kind = {
                OptionLifecycleAction.CASH_SETTLEMENT: "option_cash_settlement",
                OptionLifecycleAction.PHYSICAL_EXERCISE: "option_physical_exercise",
                OptionLifecycleAction.PHYSICAL_ASSIGNMENT: "option_physical_assignment",
                OptionLifecycleAction.LAPSE: "option_lapse",
            }.get(instruction.action, "option_lifecycle")
            record_event(
                timestamp,
                event_kind,
                lifecycle_id=instruction.lifecycle_id,
                instrument_id=key,
                action=instruction.action.value,
                option_quantity=instruction.option_quantity,
                settlement_value=instruction.settlement_value,
                underlying_instrument_id=instruction.underlying_instrument_id,
                underlying_quantity_delta=instruction.underlying_quantity_delta,
                cash_delta_quote=instruction.cash_delta_quote,
                source=instruction.reference_source,
                source_version=instruction.reference_version,
            )
            option_instructions_applied += 1
            if instruction.action in {
                OptionLifecycleAction.PHYSICAL_EXERCISE,
                OptionLifecycleAction.PHYSICAL_ASSIGNMENT,
            }:
                physical_option_actions += 1
            pending_option_instructions.pop(key, None)
            pending.pop(key, None)
            pending_is_change.pop(key, None)

        def resolve_option_instruction(
            key: str,
            timestamp: pd.Timestamp,
            rows_at_time: Mapping[str, pd.Series],
        ) -> None:
            nonlocal option_instructions_resolved, option_data_required
            if key in pending_option_instructions:
                return
            option = instruments[key]
            position = portfolio.position(key)
            if option.asset_class != AssetClass.OPTION or not position.quantity:
                return
            option_row = rows_at_time.get(key, last_rows.get(key))
            raw_request = ""
            if option_row is not None:
                raw_request = str(
                    option_row.get("option_lifecycle_request", "") or ""
                ).strip().upper()
            calendar = (
                calendar_contracts.get(option.option_calendar_id)
                if option.option_calendar_id
                else None
            )
            if raw_request:
                try:
                    request_kind = OptionLifecycleRequestKind(raw_request)
                except ValueError as exc:
                    raise ValueError(
                        f"{key}: invalid option_lifecycle_request {raw_request!r}"
                    ) from exc
            else:
                request_kind = OptionLifecycleRequestKind.EXPIRATION
                eligible_at = (
                    calendar.exercise_cutoff_at
                    if calendar is not None
                    else option.expiry
                )
                if eligible_at is None or timestamp.to_pydatetime() < eligible_at:
                    return

            underlying: Instrument | None = None
            if option.underlying_symbol:
                try:
                    candidate = self.security_master.get(option.underlying_symbol)
                    if candidate.key in instruments:
                        underlying = candidate
                except KeyError:
                    underlying = None

            underlying_row: pd.Series | None = None
            underlying_observed_at: pd.Timestamp | None = None
            if underlying is not None:
                underlying_row = rows_at_time.get(
                    underlying.key, last_rows.get(underlying.key)
                )
                underlying_observed_at = (
                    timestamp
                    if underlying.key in rows_at_time
                    else last_row_times.get(underlying.key)
                )
            option_observed_at = (
                timestamp if key in rows_at_time else last_row_times.get(key)
            )
            official_value: float | None = None
            if option_row is not None:
                raw_official = option_row.get("settlement_price", np.nan)
                if pd.notna(raw_official):
                    official_value = float(raw_official)
            underlying_price = (
                float(underlying_row["close"])
                if underlying_row is not None
                else None
            )
            observed_candidates = [
                item
                for item in (option_observed_at, underlying_observed_at)
                if item is not None
            ]
            reference: OptionSettlementReference | None = None
            if observed_candidates and (
                official_value is not None or underlying_price is not None
            ):
                observed_at = max(observed_candidates)
                source = (
                    str(option_row.get("settlement_source", "") or "").strip()
                    if option_row is not None
                    else ""
                ) or "subscribed_market_data"
                source_version = (
                    str(
                        option_row.get("settlement_source_version", "") or ""
                    ).strip()
                    if option_row is not None
                    else ""
                ) or observed_at.isoformat()
                reference = OptionSettlementReference(
                    observed_at=observed_at.to_pydatetime(),
                    available_at=observed_at.to_pydatetime(),
                    source=source,
                    source_version=source_version,
                    underlying_price=underlying_price,
                    official_settlement_value=official_value,
                )
            requested_contracts: float | None = None
            if option_row is not None:
                raw_requested = option_row.get("requested_contracts", np.nan)
                if pd.notna(raw_requested):
                    requested_contracts = float(raw_requested)
            instruction = option_lifecycle.resolve(
                instrument=option,
                position_quantity=position.quantity,
                at=timestamp.to_pydatetime(),
                calendar=calendar,
                reference=reference,
                underlying=underlying,
                request_kind=request_kind,
                requested_contracts=requested_contracts,
                strict=False,
            )
            if not instruction.available:
                gap = f"{key}: option lifecycle data required ({'; '.join(instruction.reasons)})"
                lifecycle_gaps.append(gap)
                if instruction.lifecycle_id not in option_data_required_ids:
                    option_data_required_ids.add(instruction.lifecycle_id)
                    option_data_required += 1
                    record_event(
                        timestamp,
                        "option_lifecycle_data_required",
                        lifecycle_id=instruction.lifecycle_id,
                        instrument_id=key,
                        reasons=list(instruction.reasons),
                    )
                return
            pending_option_instructions[key] = (instruction, underlying)
            option_instructions_resolved += 1
            record_event(
                timestamp,
                "option_lifecycle_resolved",
                lifecycle_id=instruction.lifecycle_id,
                instrument_id=key,
                action=instruction.action.value,
                settlement_at=instruction.settlement_at,
                source=instruction.reference_source,
                source_version=instruction.reference_version,
            )
            if instruction.settlement_at <= timestamp.to_pydatetime():
                apply_option_instruction(
                    key, instruction, underlying, timestamp
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
            oms_order = oms.submit(
                OrderRequest(
                    symbol=key,
                    side=OrderSide.BUY if delta > 0 else OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    quantity=abs(delta),
                    submitted_at=timestamp.to_pydatetime(),
                    time_in_force=TimeInForce.IOC,
                    order_id=order_id,
                    metadata={
                        "instrument_id": key,
                        "display_symbol": instrument.symbol,
                        "desired_quantity": float(desired_quantity),
                        "reason": reason,
                        "forced": bool(forced),
                    },
                )
            )
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
                "oms_status": oms_order.status.value,
            }

            def reject_current(rejection_reason: str) -> str:
                nonlocal rejections
                rejected = oms.reject(
                    order_id,
                    at=timestamp.to_pydatetime(),
                    reason=rejection_reason,
                )
                order.update(
                    status="REJECTED",
                    oms_status=rejected.status.value,
                    rejection_reason=rejection_reason,
                )
                orders.append(order)
                rejections += 1
                return "REJECTED"

            if delta < 0 and desired_quantity < -1e-12 and not self.config.allow_short and not forced:
                return reject_current("short exposure disabled")
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
                return reject_current("causal volume unavailable")
            fill_quantity = _round_instrument_quantity(
                available_quantity, instrument, self.config
            )
            if fill_quantity <= 0:
                return reject_current("quantity below tradable lot")
            fill_quantity = math.copysign(fill_quantity, delta)
            # Floating lot arithmetic may place the rounded value a few ulps
            # above the remaining OMS quantity.  An authoritative OMS must
            # never accept an overfill, so cap that numerical residue to the
            # exact client intent before costs and accounting are computed.
            if abs(fill_quantity) > abs(delta):
                fill_quantity = float(delta)
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
                        return reject_current(
                            "insufficient settled cash after costs"
                        )
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
            oms_remaining = float(oms.get(order_id).remaining_quantity)
            if abs(fill_quantity) > oms_remaining:
                fill_quantity = math.copysign(oms_remaining, fill_quantity)
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
                return reject_current(str(exc))

            settle_at = _settlement_at(timestamp, instrument.settlement_days)
            authoritative_fill = oms.apply_fill(
                order_id,
                at=timestamp.to_pydatetime(),
                quantity=abs(fill_quantity),
                price=fill_price,
                source="UNIVERSAL_BAR_EXECUTION",
            )
            portfolio.apply_oms_fill(
                instrument,
                authoritative_fill,
                commission,
                settle_at,
            )
            fill_quantity = float(authoritative_fill.signed_quantity)
            fill_price = float(authoritative_fill.price)
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
            fills.append(
                {
                    "timestamp": timestamp,
                    "fill_id": authoritative_fill.fill_id,
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
                    "source": authoritative_fill.source,
                    "authority": "OMS",
                }
            )
            order["filled_quantity"] = abs(fill_quantity)
            current_oms_order = oms.get(order_id)
            if current_oms_order.active:
                current_oms_order = oms.cancel(
                    order_id,
                    at=timestamp.to_pydatetime(),
                    reason="BAR_REMAINDER_REQUEUED",
                )
            order["oms_status"] = current_oms_order.status.value
            orders.append(order)
            record_event(
                timestamp,
                "fill",
                instrument_id=key,
                order_id=order_id,
                fill_id=authoritative_fill.fill_id,
                quantity=fill_quantity,
                price=fill_price,
                forced=forced,
                authority="OMS",
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
                    snapshot = current_margin(timestamp)
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
                    rates = getattr(self.margin_model, "rates", None)
                    # Scenario/portfolio models must assess every target
                    # transition: reducing one leg can remove a hedge and
                    # increase portfolio margin.  The legacy independent-rate
                    # model only needs the historical increase check.
                    margin_check_required = (
                        not callable(rates)
                        or abs(desired_quantity) > abs(current) + 1e-12
                    )
                    if margin_check_required:
                        try:
                            if callable(rates):
                                initial_rate, _ = rates(
                                    instrument, desired_quantity
                                )
                                snapshot = current_margin(timestamp)
                                current_notional = abs(
                                    current
                                    * float(row["open"])
                                    * float(instrument.multiplier)
                                    * quote_to_base
                                )
                                current_requirement = current_notional * initial_rate
                                other_requirement = max(
                                    snapshot.initial_required_base
                                    - current_requirement,
                                    0.0,
                                )
                                affordable = max(
                                    pretrade_nav - other_requirement, 0.0
                                )
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
                                        requested_quantity=abs(
                                            requested_desired_quantity
                                        ),
                                        max_quantity=abs(desired_quantity),
                                        method=snapshot.method,
                                    )
                            else:
                                requested_margin = candidate_margin(
                                    timestamp,
                                    key,
                                    desired_quantity,
                                    float(row["open"]),
                                )
                                if not requested_margin.available:
                                    raise ValueError(
                                        "; ".join(requested_margin.reasons)
                                        or "margin model unavailable"
                                    )
                                if (
                                    requested_margin.initial_required_base
                                    > pretrade_nav + 1e-12
                                ):
                                    current_margin_snapshot = candidate_margin(
                                        timestamp,
                                        key,
                                        current,
                                        float(row["open"]),
                                    )
                                    if not current_margin_snapshot.available:
                                        raise ValueError(
                                            "; ".join(
                                                current_margin_snapshot.reasons
                                            )
                                            or "current portfolio margin unavailable"
                                        )
                                    if (
                                        current_margin_snapshot.initial_required_base
                                        > pretrade_nav + 1e-12
                                    ):
                                        raise ValueError(
                                            "current portfolio already exceeds initial margin"
                                        )
                                    low_fraction = 0.0
                                    high_fraction = 1.0
                                    for _ in range(56):
                                        midpoint = (
                                            low_fraction + high_fraction
                                        ) / 2.0
                                        candidate_quantity = current + midpoint * (
                                            desired_quantity - current
                                        )
                                        midpoint_margin = candidate_margin(
                                            timestamp,
                                            key,
                                            candidate_quantity,
                                            float(row["open"]),
                                        )
                                        if not midpoint_margin.available:
                                            raise ValueError(
                                                "; ".join(midpoint_margin.reasons)
                                                or "margin model unavailable"
                                            )
                                        if (
                                            midpoint_margin.initial_required_base
                                            <= pretrade_nav + 1e-12
                                        ):
                                            low_fraction = midpoint
                                        else:
                                            high_fraction = midpoint
                                    max_quantity = current + low_fraction * (
                                        desired_quantity - current
                                    )
                                    desired_quantity = _round_instrument_quantity(
                                        max_quantity, instrument, self.config
                                    )
                                    target_was_clipped = True
                                    partial_fills += 1
                                    record_event(
                                        timestamp,
                                        "pretrade_margin_clip",
                                        instrument_id=key,
                                        requested_quantity=abs(
                                            requested_desired_quantity
                                        ),
                                        max_quantity=abs(desired_quantity),
                                        method=requested_margin.method,
                                        parameter_version=(
                                            requested_margin.parameter_version
                                        ),
                                    )
                        except (LookupError, TypeError, ValueError) as exc:
                            reject_order_intent(
                                key,
                                timestamp,
                                desired_quantity,
                                reason=str(exc),
                                category="pretrade_margin",
                            )
                            pending.pop(key, None)
                            pending_is_change.pop(key, None)
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
                    last_row_times[key] = timestamp
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
                        if instrument.option_calendar_id:
                            # The strict lifecycle processor resolves this
                            # position after all same-clock closing marks are
                            # available.  Never fall back to a synthetic sale.
                            continue
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

                for key, (instruction, underlying) in sorted(
                    list(pending_option_instructions.items())
                ):
                    if instruction.settlement_at > stamp_dt:
                        continue
                    try:
                        apply_option_instruction(
                            key, instruction, underlying, timestamp
                        )
                    except ValueError as exc:
                        lifecycle_gaps.append(
                            f"{key}: option settlement failed ({exc})"
                        )
                        pending_option_instructions.pop(key, None)

                for key in sorted(instruments):
                    instrument = instruments[key]
                    if instrument.asset_class != AssetClass.OPTION:
                        continue
                    row = rows_at_time.get(key)
                    explicit_request = bool(
                        row is not None
                        and str(
                            row.get("option_lifecycle_request", "") or ""
                        ).strip()
                    )
                    if not instrument.option_calendar_id and not explicit_request:
                        continue
                    resolve_option_instruction(key, timestamp, rows_at_time)

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
                margin = current_margin(timestamp)
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
                        margin = current_margin(timestamp)

                insolvency_tolerance = max(
                    1e-8, abs(float(self.config.initial_cash)) * 1e-12
                )
                if not np.isfinite(nav) or nav <= insolvency_tolerance:
                    risk_failures.append(
                        f"portfolio insolvency at {timestamp.isoformat()} (NAV={nav})"
                    )
                if (
                    margin.available
                    and margin.maintenance_excess_base < -insolvency_tolerance
                ):
                    risk_failures.append(
                        "unresolved maintenance-margin deficit at "
                        f"{timestamp.isoformat()} "
                        f"({margin.maintenance_excess_base})"
                    )

                last_margin_snapshot = margin

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
                last_portfolio_snapshot = build_portfolio_snapshot(
                    timestamp, nav, margin
                )
                if not margin.available:
                    lifecycle_gaps.extend(margin.reasons)

                if risk_failures:
                    break

                if strategy_runtime is not None and rows_at_time:
                    bars: dict[str, Bar] = {}
                    for key in sorted(rows_at_time):
                        row = rows_at_time[key]
                        volume_value = row.get("volume", np.nan)
                        bars[key] = Bar(
                            symbol=key,
                            event_time=timestamp.to_pydatetime(),
                            available_at=timestamp.to_pydatetime(),
                            open=float(row["open"]),
                            high=float(row["high"]),
                            low=float(row["low"]),
                            close=float(row["close"]),
                            volume=(
                                float(volume_value)
                                if pd.notna(volume_value)
                                else None
                            ),
                            fields={
                                "instrument_id": key,
                                "display_symbol": instruments[key].symbol,
                                "asset_class": instruments[key].asset_class.value,
                            },
                        )
                    market_slice = Slice(
                        event_time=timestamp.to_pydatetime(),
                        available_at=timestamp.to_pydatetime(),
                        bars=bars,
                    )
                    runtime_targets = request_causal_targets(
                        strategy_runtime,
                        portfolio=last_portfolio_snapshot,
                        market_slice=market_slice,
                    )
                    resolved_targets: dict[str, float] = {}
                    for supplied_key, value in runtime_targets.items():
                        instrument = self.security_master.get(supplied_key)
                        if instrument.key not in instruments:
                            raise StrategyRuntimeError(
                                "strategy runtime targeted unsubscribed instrument "
                                f"{supplied_key!r}"
                            )
                        if abs(value) > float(self.config.max_target_weight):
                            raise StrategyRuntimeError(
                                f"target for {instrument.key} exceeds the per-instrument limit"
                            )
                        if instrument.key in resolved_targets:
                            raise StrategyRuntimeError(
                                "multiple runtime targets resolve to "
                                f"{instrument.key}"
                            )
                        resolved_targets[instrument.key] = float(value)
                    candidate_state = dict(last_target_values)
                    candidate_state.update(resolved_targets)
                    if (
                        sum(abs(value) for value in candidate_state.values())
                        > float(self.config.max_gross_exposure) + 1e-12
                    ):
                        raise StrategyRuntimeError(
                            "strategy runtime target state exceeds the gross exposure limit"
                        )
                    for key, value in sorted(resolved_targets.items()):
                        prior_target = last_target_values.get(key)
                        pending[key] = (timestamp, value)
                        pending_is_change[key] = bool(
                            prior_target is None
                            or abs(value - prior_target)
                            > float(self.config.rebalance_tolerance_weight)
                        )
                        last_target_values[key] = value
                        record_event(
                            timestamp,
                            "strategy_target",
                            event_time=timestamp,
                            instrument_id=key,
                            target_weight=value,
                            source="causal_strategy_runtime",
                            portfolio_snapshot_sequence=last_portfolio_snapshot.sequence,
                            portfolio_ledger_sha256=last_portfolio_snapshot.ledger_sha256,
                        )
                    portfolio_feedback_slices += 1

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
        oms_fill_ids = [item.fill_id for item in oms.authoritative_fills]
        engine_fill_ids = (
            [str(item) for item in fill_frame["fill_id"].tolist()]
            if "fill_id" in fill_frame
            else []
        )
        ledger_fill_ids = sorted(portfolio.applied_oms_fill_ids)
        oms_ledger_reconciled = bool(
            oms_fill_ids == engine_fill_ids
            and sorted(oms_fill_ids) == ledger_fill_ids
        )
        if not oms_ledger_reconciled:
            fatal_reasons.append("OMS fill ledger does not reconcile to portfolio accounting")
        if pending_option_instructions:
            lifecycle_gaps.extend(
                f"{key}: option lifecycle instruction remains unsettled"
                for key in sorted(pending_option_instructions)
            )
        final_clock = timeline.max().to_pydatetime() if len(timeline) else None
        if final_clock is not None:
            for key, position in sorted(portfolio.positions.items()):
                instrument = instruments[key]
                if (
                    position.quantity
                    and instrument.expiry is not None
                    and final_clock >= instrument.expiry
                ):
                    lifecycle_gaps.append(
                        f"{key}: expired position remains open at terminal clock"
                    )
        oms_events = [
            {
                "event_id": item.event_id,
                "order_id": item.order_id,
                "occurred_at": item.occurred_at.isoformat(),
                "kind": item.kind.value,
                "previous_status": item.previous_status.value,
                "status": item.status.value,
                "reason": item.reason,
                "details": dict(item.details),
            }
            for item in oms.events
        ]
        terminal_target_changes = sorted(
            key for key in pending if pending_is_change.get(key, False)
        )
        if risk_failures:
            status = "UNAVAILABLE"
            reason = "RISK REJECTED: " + "; ".join(
                dict.fromkeys(risk_failures)
            )
        elif fatal_reasons or daily.empty:
            status = "UNAVAILABLE"
            reason = "DATA REQUIRED: " + "; ".join(dict.fromkeys(fatal_reasons or ["no valuations"]))
        elif (
            rejections
            or partial_fills
            or lifecycle_gaps
            or terminal_target_changes
            or margin_calls
            or forced_liquidations
        ):
            status = "PARTIAL"
            reason = "Run completed with fail-closed limitations"
        else:
            status = "AVAILABLE"
            reason = "Universal event ledger complete"
        diagnostics = {
            "engine": "universal_bar_event_kernel",
            "engine_version": "0.3.0",
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
            "signal_source": (
                "causal_strategy_runtime"
                if strategy_runtime is not None
                else "precomputed_target_weights"
            ),
            "portfolio_feedback_contract": (
                "OMS and ledger reconciled through t; immutable snapshot delivered "
                "with slice t; returned target executes strictly after t"
            ),
            "portfolio_feedback_slices": portfolio_feedback_slices,
            "last_portfolio_snapshot_sequence": (
                last_portfolio_snapshot.sequence
                if last_portfolio_snapshot is not None
                else 0
            ),
            "last_portfolio_ledger_sha256": (
                last_portfolio_snapshot.ledger_sha256
                if last_portfolio_snapshot is not None
                else ""
            ),
            "multi_currency_cashbook": True,
            "cash_settlement_enforced": True,
            "margin_pretrade": True,
            "maintenance_margin_enforced": True,
            "margin_method": (
                last_margin_snapshot.method
                if last_margin_snapshot is not None
                else getattr(
                    getattr(self.margin_model, "method", None),
                    "value",
                    str(getattr(self.margin_model, "method", "UNKNOWN")),
                )
            ),
            "margin_parameter_version": (
                last_margin_snapshot.parameter_version
                if last_margin_snapshot is not None
                else None
            ),
            "margin_parameter_sha256": (
                last_margin_snapshot.parameter_sha256
                if last_margin_snapshot is not None
                else None
            ),
            "margin_certified": bool(
                last_margin_snapshot.certified
                if last_margin_snapshot is not None
                else False
            ),
            "margin_reference_model": bool(
                last_margin_snapshot.reference_model
                if last_margin_snapshot is not None
                else True
            ),
            "orders": len(order_frame),
            "fills": len(fill_frame),
            "oms_authoritative": True,
            "ledger_fill_authority": "OrderKernel.authoritative_fills",
            "oms_fill_ledger_sha256": oms.fill_ledger_sha256,
            "oms_ledger_reconciled": oms_ledger_reconciled,
            "oms_active_orders": len(oms.active_orders()),
            "oms_events": oms_events,
            "rejections": rejections,
            "partial_fills": partial_fills,
            "gross_limit_clips": gross_limit_clips,
            "margin_calls": margin_calls,
            "forced_liquidations": forced_liquidations,
            "risk_failures": list(dict.fromkeys(risk_failures)),
            "portfolio_insolvent": any(
                "insolvency" in item for item in risk_failures
            ),
            "unresolved_margin_deficit": any(
                "maintenance-margin deficit" in item for item in risk_failures
            ),
            "no_trade_targets": no_trade_targets,
            "rebalance_tolerance_weight": self.config.rebalance_tolerance_weight,
            "fx_conversions": list(portfolio.cash.conversions),
            "accounting_events": list(portfolio.realized_events),
            "accounting_reconciled": accounting_reconciled,
            "accounting_reconciliation_residual_base": reconciliation_residual,
            "pending_settlements": len(portfolio.cash.pending),
            "physical_option_lifecycle": {
                "processor_connected": True,
                "calendar_contracts": len(calendar_contracts),
                "instructions_resolved": option_instructions_resolved,
                "instructions_applied": option_instructions_applied,
                "physical_actions_applied": physical_option_actions,
                "data_required": option_data_required,
                "pending_instructions": len(pending_option_instructions),
                "fail_closed": True,
            },
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
            portfolio_snapshot=last_portfolio_snapshot,
        )
