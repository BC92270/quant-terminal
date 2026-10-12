"""Multi-currency cash, settlement and position accounting."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
from typing import Mapping

from .fx import FXMatrix
from .types import AssetClass, Instrument, SettlementType


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timezone-aware timestamp required")
    return value.astimezone(timezone.utc)


@dataclass
class PendingSettlement:
    currency: str
    amount: float
    settle_at: datetime
    reference: str = ""


class CashBook:
    def __init__(self, base_currency: str, initial_cash: float = 0.0) -> None:
        self.base_currency = str(base_currency).strip().upper()
        self.balances: dict[str, float] = {self.base_currency: float(initial_cash)}
        self.pending: list[PendingSettlement] = []
        self.conversions: list[dict[str, float | str]] = []

    def balance(self, currency: str) -> float:
        return float(self.balances.get(str(currency).strip().upper(), 0.0))

    def deposit(self, currency: str, amount: float) -> None:
        code = str(currency).strip().upper()
        value = float(amount)
        if not math.isfinite(value):
            raise ValueError("cash movement must be finite")
        self.balances[code] = self.balance(code) + value

    def withdraw(self, currency: str, amount: float, *, allow_negative: bool = False) -> None:
        code = str(currency).strip().upper()
        value = float(amount)
        if not math.isfinite(value) or value < 0:
            raise ValueError("withdrawal must be finite and non-negative")
        if not allow_negative and self.balance(code) + 1e-10 < value:
            raise ValueError(f"insufficient settled {code} cash")
        self.balances[code] = self.balance(code) - value

    def schedule(
        self,
        currency: str,
        amount: float,
        settle_at: datetime,
        *,
        reference: str = "",
    ) -> None:
        value = float(amount)
        if not math.isfinite(value):
            raise ValueError("settlement amount must be finite")
        self.pending.append(
            PendingSettlement(
                str(currency).strip().upper(), value, _utc(settle_at), reference
            )
        )

    def settle(self, at: datetime) -> list[PendingSettlement]:
        stamp = _utc(at)
        matured = [item for item in self.pending if item.settle_at <= stamp]
        self.pending = [item for item in self.pending if item.settle_at > stamp]
        for item in matured:
            self.deposit(item.currency, item.amount)
        return matured

    def convert(
        self,
        amount: float,
        from_currency: str,
        to_currency: str,
        fx: FXMatrix,
        *,
        fee_bps: float = 0.0,
    ) -> float:
        source = str(from_currency).strip().upper()
        target = str(to_currency).strip().upper()
        value = float(amount)
        if value < 0 or not math.isfinite(value):
            raise ValueError("conversion amount must be finite and non-negative")
        self.withdraw(source, value)
        gross = fx.convert(value, source, target)
        fee = gross * max(float(fee_bps), 0.0) / 10_000.0
        net = gross - fee
        self.deposit(target, net)
        self.conversions.append(
            {
                "from": source,
                "to": target,
                "source_amount": value,
                "target_amount": net,
                "fee_target": fee,
            }
        )
        return net

    def ensure(
        self,
        currency: str,
        required: float,
        fx: FXMatrix,
        *,
        fee_bps: float = 0.0,
    ) -> None:
        code = str(currency).strip().upper()
        shortfall = float(required) - self.balance(code)
        if shortfall <= 1e-10:
            return
        if code == self.base_currency:
            raise ValueError(f"insufficient settled {code} cash")
        target_per_base = fx.rate(self.base_currency, code)
        fee_fraction = max(float(fee_bps), 0.0) / 10_000.0
        source_required = shortfall / max(target_per_base * (1.0 - fee_fraction), 1e-12)
        self.convert(
            source_required,
            self.base_currency,
            code,
            fx,
            fee_bps=fee_bps,
        )

    def total_value(self, fx: FXMatrix, *, include_pending: bool = True) -> float:
        total = sum(fx.to_base(amount, currency) for currency, amount in self.balances.items())
        if include_pending:
            total += sum(fx.to_base(item.amount, item.currency) for item in self.pending)
        return float(total)

    def snapshot(self, fx: FXMatrix) -> list[dict[str, float | str]]:
        currencies = sorted(set(self.balances) | {item.currency for item in self.pending})
        return [
            {
                "currency": code,
                "settled": self.balance(code),
                "unsettled": sum(item.amount for item in self.pending if item.currency == code),
                "base_value": fx.to_base(
                    self.balance(code)
                    + sum(item.amount for item in self.pending if item.currency == code),
                    code,
                ),
            }
            for code in currencies
        ]


@dataclass
class Position:
    symbol: str
    quantity: float = 0.0
    average_price: float = 0.0
    last_price: float = 0.0
    realized_pnl_quote: float = 0.0

    def trade(self, quantity: float, price: float) -> float:
        """Apply a signed trade and return realized PnL per unit multiplier."""

        delta = float(quantity)
        trade_price = float(price)
        old = self.quantity
        if abs(delta) <= 1e-15:
            return 0.0
        realized = 0.0
        same_direction = old == 0 or old * delta > 0
        if same_direction:
            new = old + delta
            self.average_price = (
                (abs(old) * self.average_price + abs(delta) * trade_price) / abs(new)
                if abs(new) > 1e-15
                else 0.0
            )
            self.quantity = new
        else:
            closed = min(abs(old), abs(delta))
            realized = closed * (trade_price - self.average_price) * (1.0 if old > 0 else -1.0)
            new = old + delta
            if abs(new) <= 1e-15:
                self.quantity = 0.0
                self.average_price = 0.0
            elif old * new < 0:
                self.quantity = new
                self.average_price = trade_price
            else:
                self.quantity = new
        self.last_price = trade_price
        self.realized_pnl_quote += realized
        return realized


@dataclass
class PortfolioLedger:
    base_currency: str
    initial_cash: float
    cash: CashBook = field(init=False)
    positions: dict[str, Position] = field(default_factory=dict)
    realized_events: list[dict[str, object]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.cash = CashBook(self.base_currency, self.initial_cash)

    def position(self, symbol: str) -> Position:
        key = str(symbol).strip().upper()
        if key not in self.positions:
            self.positions[key] = Position(key)
        return self.positions[key]

    def mark(self, instrument: Instrument, price: float, at: datetime) -> float:
        position = self.position(instrument.key)
        value = float(price)
        pnl = 0.0
        if instrument.uses_variation_margin and position.quantity and position.last_price:
            pnl = (
                position.quantity
                * (value - position.last_price)
                * float(instrument.multiplier)
            )
            self.cash.deposit(instrument.quote_currency, pnl)
            position.realized_pnl_quote += pnl
            self.realized_events.append(
                {
                    "timestamp": _utc(at).isoformat(),
                    "symbol": instrument.symbol,
                    "instrument_id": instrument.key,
                    "kind": "variation_margin",
                    "amount": pnl,
                    "currency": instrument.quote_currency,
                }
            )
        position.last_price = value
        return pnl

    def apply_fill(
        self,
        instrument: Instrument,
        signed_quantity: float,
        price: float,
        commission_quote: float,
        at: datetime,
        settle_at: datetime,
    ) -> float:
        position = self.position(instrument.key)
        quantity = float(signed_quantity)
        fill_price = float(price)
        commission = max(float(commission_quote), 0.0)
        realized = position.trade(quantity, fill_price) * float(instrument.multiplier)
        quote = instrument.quote_currency
        if instrument.is_cash_asset:
            notional = quantity * fill_price * float(instrument.multiplier)
            if notional > 0:
                self.cash.withdraw(quote, notional + commission)
            else:
                # Sale commissions settle with the sale proceeds.  Requiring
                # separate settled cash here can make a perfectly valid exit
                # (including a forced liquidation) impossible when the account
                # is fully invested.
                self.cash.schedule(
                    quote,
                    -notional - commission,
                    settle_at,
                    reference=f"sale:{instrument.symbol}",
                )
        else:
            if commission:
                self.cash.withdraw(quote, commission, allow_negative=True)
        self.realized_events.append(
            {
                "timestamp": _utc(at).isoformat(),
                "symbol": instrument.symbol,
                "instrument_id": instrument.key,
                "kind": "fill",
                "quantity": quantity,
                "price": fill_price,
                "commission": commission,
                "currency": quote,
                "realized_pnl": realized,
            }
        )
        return realized

    def apply_split(self, instrument: Instrument, ratio: float, at: datetime) -> None:
        value = float(ratio)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("split ratio must be finite and positive")
        position = self.position(instrument.key)
        if not position.quantity:
            return
        position.quantity *= value
        position.average_price /= value
        position.last_price /= value
        self.realized_events.append(
            {
                "timestamp": _utc(at).isoformat(),
                "symbol": instrument.symbol,
                "instrument_id": instrument.key,
                "kind": "split",
                "ratio": value,
            }
        )

    def apply_income(
        self,
        instrument: Instrument,
        amount_quote: float,
        at: datetime,
        *,
        kind: str,
    ) -> None:
        value = float(amount_quote)
        self.cash.deposit(instrument.quote_currency, value)
        self.realized_events.append(
            {
                "timestamp": _utc(at).isoformat(),
                "symbol": instrument.symbol,
                "instrument_id": instrument.key,
                "kind": kind,
                "amount": value,
                "currency": instrument.quote_currency,
            }
        )

    def settle_cash_option(
        self,
        instrument: Instrument,
        settlement_value: float,
        at: datetime,
    ) -> float:
        """Settle an expiring cash-settled option at intrinsic/final value."""

        if instrument.asset_class != AssetClass.OPTION:
            raise ValueError("cash option settlement requires an option")
        if instrument.settlement_type != SettlementType.CASH:
            raise ValueError("physical option assignment requires a dedicated adapter")
        value = float(settlement_value)
        if not math.isfinite(value) or value < 0:
            raise ValueError("option settlement value must be finite and non-negative")
        position = self.position(instrument.key)
        quantity = float(position.quantity)
        if not quantity:
            return 0.0
        realized = position.trade(-quantity, value) * float(instrument.multiplier)
        payout = quantity * value * float(instrument.multiplier)
        self.cash.deposit(instrument.quote_currency, payout)
        self.realized_events.append(
            {
                "timestamp": _utc(at).isoformat(),
                "symbol": instrument.symbol,
                "instrument_id": instrument.key,
                "kind": "option_cash_settlement",
                "quantity": quantity,
                "settlement_value": value,
                "amount": payout,
                "currency": instrument.quote_currency,
                "realized_pnl": realized,
            }
        )
        return payout

    def nav(
        self,
        fx: FXMatrix,
        instruments: Mapping[str, Instrument],
    ) -> float:
        total = self.cash.total_value(fx)
        for symbol, position in self.positions.items():
            if not position.quantity:
                continue
            instrument = instruments[symbol]
            if instrument.is_cash_asset:
                market_value = (
                    position.quantity * position.last_price * float(instrument.multiplier)
                )
                total += fx.to_base(market_value, instrument.quote_currency)
        return float(total)

    def positions_snapshot(
        self,
        fx: FXMatrix,
        instruments: Mapping[str, Instrument],
    ) -> list[dict[str, float | str]]:
        rows: list[dict[str, float | str]] = []
        for symbol, position in sorted(self.positions.items()):
            if abs(position.quantity) <= 1e-15:
                continue
            instrument = instruments[symbol]
            notional = position.quantity * position.last_price * float(instrument.multiplier)
            rows.append(
                {
                    "symbol": instrument.symbol,
                    "instrument_id": instrument.key,
                    "asset_class": instrument.asset_class.value,
                    "quantity": position.quantity,
                    "average_price": position.average_price,
                    "last_price": position.last_price,
                    "quote_currency": instrument.quote_currency,
                    "notional_base": fx.to_base(notional, instrument.quote_currency),
                    "realized_pnl_quote": position.realized_pnl_quote,
                }
            )
        return rows
