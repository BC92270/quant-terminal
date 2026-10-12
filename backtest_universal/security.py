"""Point-in-time instrument registry and contract resolver."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from .types import Instrument


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timezone-aware timestamp required")
    return value.astimezone(timezone.utc)


class SecurityMaster:
    def __init__(self, instruments: list[Instrument] | tuple[Instrument, ...] = ()) -> None:
        self._items: dict[str, Instrument] = {}
        self._symbols: dict[str, list[str]] = defaultdict(list)
        self._roots: dict[str, list[str]] = defaultdict(list)
        for instrument in instruments:
            self.register(instrument)

    def register(self, instrument: Instrument) -> None:
        if instrument.key in self._items:
            raise ValueError(f"duplicate instrument: {instrument.key}")
        self._items[instrument.key] = instrument
        self._symbols[instrument.symbol].append(instrument.key)
        if instrument.root_symbol:
            self._roots[str(instrument.root_symbol).upper()].append(instrument.key)

    def get(self, symbol: str) -> Instrument:
        key = str(symbol).strip().upper()
        if key in self._items:
            return self._items[key]
        matches = self._symbols.get(key, [])
        if not matches:
            raise KeyError(f"unknown instrument: {key}")
        if len(matches) > 1:
            raise KeyError(f"ambiguous symbol {key}; use the instrument_id/key")
        return self._items[matches[0]]

    def active(self, symbol: str, at: datetime) -> Instrument:
        instrument = self.get(symbol)
        stamp = _utc(at)
        if instrument.active_from is not None and stamp < instrument.active_from:
            raise ValueError(f"{instrument.symbol} is not active yet")
        end = instrument.active_to or instrument.expiry
        if end is not None and stamp > end:
            raise ValueError(f"{instrument.symbol} is expired or inactive")
        return instrument

    def front_contract(self, root_symbol: str, at: datetime) -> Instrument:
        stamp = _utc(at)
        contracts: list[Instrument] = []
        for symbol in self._roots.get(str(root_symbol).strip().upper(), []):
            instrument = self._items[symbol]
            if instrument.expiry is None or instrument.expiry < stamp:
                continue
            if instrument.active_from is not None and instrument.active_from > stamp:
                continue
            contracts.append(instrument)
        if not contracts:
            raise KeyError(f"no active contract for root {root_symbol}")
        return min(contracts, key=lambda item: item.expiry or datetime.max.replace(tzinfo=timezone.utc))

    def records(self) -> list[dict[str, object]]:
        return [
            {
                "symbol": item.symbol,
                "instrument_id": item.key,
                "asset_class": item.asset_class.value,
                "quote_currency": item.quote_currency,
                "base_currency": item.base_currency,
                "exchange": item.exchange,
                "multiplier": item.multiplier,
                "lot_size": item.lot_size,
                "tick_size": item.tick_size,
                "settlement_days": item.settlement_days,
                "initial_margin_rate": item.initial_margin_rate,
                "maintenance_margin_rate": item.maintenance_margin_rate,
                "expiry": item.expiry.isoformat() if item.expiry else None,
                "root_symbol": item.root_symbol,
                "underlying_symbol": item.underlying_symbol,
                "strike": item.strike,
                "option_right": item.option_right.value if item.option_right else None,
                "settlement_type": item.settlement_type.value,
                "active_from": item.active_from.isoformat() if item.active_from else None,
                "active_to": item.active_to.isoformat() if item.active_to else None,
                "metadata": dict(item.metadata),
            }
            for item in self._items.values()
        ]
