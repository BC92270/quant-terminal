"""Typed contracts for the universal backtest kernel."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum, IntEnum
from hashlib import sha256
import json
import math
import re
from typing import Any, Mapping


_CURRENCY = re.compile(r"^[A-Z]{3}$")


class AssetClass(str, Enum):
    EQUITY = "EQUITY"
    ETF = "ETF"
    FX = "FX"
    CRYPTO_SPOT = "CRYPTO_SPOT"
    CRYPTO_PERPETUAL = "CRYPTO_PERPETUAL"
    FUTURE = "FUTURE"
    OPTION = "OPTION"
    CFD = "CFD"
    RATE = "RATE"


class OptionRight(str, Enum):
    CALL = "CALL"
    PUT = "PUT"


class OptionExerciseStyle(str, Enum):
    """Contractual exercise convention for a listed option."""

    AMERICAN = "AMERICAN"
    EUROPEAN = "EUROPEAN"
    BERMUDAN = "BERMUDAN"


class SettlementType(str, Enum):
    CASH = "CASH"
    PHYSICAL = "PHYSICAL"


class CorporateActionKind(str, Enum):
    SPLIT = "SPLIT"
    DIVIDEND = "DIVIDEND"
    DELISTING = "DELISTING"
    SPINOFF = "SPINOFF"
    SYMBOL_CHANGE = "SYMBOL_CHANGE"


class EventKind(IntEnum):
    """Stable same-clock processing priority.

    Lower values run first.  Corporate actions and cash settlements must be
    known before orders; marks and accounting snapshots run last.
    """

    CORPORATE_ACTION = 10
    OPTION_LIFECYCLE = 15
    SETTLEMENT = 20
    FX_RATE = 30
    MARKET_DATA = 40
    STRATEGY = 50
    ORDER = 60
    FILL = 70
    FUNDING = 80
    MARGIN = 90
    SNAPSHOT = 100


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("timestamp must be a datetime")
    if value.tzinfo is None:
        raise ValueError("timezone-aware timestamp required")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class OptionCalendarContract:
    """Versionable option calendar facts supplied by a reference-data adapter.

    Calendar facts deliberately live outside :class:`Instrument`: exchanges
    can revise cut-offs and settlement dates after a security master snapshot
    was created.  The ``available_at`` timestamp prevents a corrected calendar
    from leaking backwards into a point-in-time simulation.
    """

    calendar_id: str
    timezone_name: str
    expiration_at: datetime
    exercise_cutoff_at: datetime
    settlement_at: datetime
    exercise_style: OptionExerciseStyle
    source: str
    source_version: str
    available_at: datetime
    early_exercise_dates: tuple[date, ...] = ()

    def __post_init__(self) -> None:
        calendar_id = str(self.calendar_id).strip()
        timezone_name = str(self.timezone_name).strip()
        source = str(self.source).strip()
        source_version = str(self.source_version).strip()
        if not calendar_id:
            raise ValueError("option calendar_id is required")
        if not timezone_name:
            raise ValueError("option calendar timezone is required")
        if not source or not source_version:
            raise ValueError("option calendar source and source_version are required")
        expiration = _utc(self.expiration_at)
        cutoff = _utc(self.exercise_cutoff_at)
        settlement = _utc(self.settlement_at)
        available = _utc(self.available_at)
        if settlement < expiration or settlement < cutoff:
            raise ValueError("option settlement_at cannot precede expiry or exercise cutoff")
        dates = tuple(sorted(set(self.early_exercise_dates)))
        if any(not isinstance(item, date) for item in dates):
            raise TypeError("early_exercise_dates must contain date values")
        object.__setattr__(self, "calendar_id", calendar_id)
        object.__setattr__(self, "timezone_name", timezone_name)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "source_version", source_version)
        object.__setattr__(self, "expiration_at", expiration)
        object.__setattr__(self, "exercise_cutoff_at", cutoff)
        object.__setattr__(self, "settlement_at", settlement)
        object.__setattr__(self, "available_at", available)
        object.__setattr__(self, "early_exercise_dates", dates)

    def is_known_at(self, at: datetime) -> bool:
        return self.available_at <= _utc(at)

    def permits_early_exercise(self, at: datetime) -> bool:
        stamp = _utc(at)
        if stamp >= self.expiration_at or stamp > self.exercise_cutoff_at:
            return False
        if self.exercise_style == OptionExerciseStyle.AMERICAN:
            return True
        if self.exercise_style == OptionExerciseStyle.BERMUDAN:
            return stamp.date() in self.early_exercise_dates
        return False


@dataclass(frozen=True)
class Instrument:
    symbol: str
    asset_class: AssetClass
    quote_currency: str
    instrument_id: str | None = None
    exchange: str = "UNKNOWN"
    multiplier: float = 1.0
    lot_size: float = 1.0
    tick_size: float = 0.01
    settlement_days: int = 0
    initial_margin_rate: float | None = None
    maintenance_margin_rate: float | None = None
    base_currency: str | None = None
    underlying_symbol: str | None = None
    root_symbol: str | None = None
    expiry: datetime | None = None
    strike: float | None = None
    option_right: OptionRight | None = None
    settlement_type: SettlementType = SettlementType.CASH
    option_exercise_style: OptionExerciseStyle | None = None
    option_calendar_id: str | None = None
    automatic_exercise_threshold: float = 0.0
    deliverable_quantity: float | None = None
    active_from: datetime | None = None
    active_to: datetime | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        symbol = str(self.symbol).strip().upper()
        quote = str(self.quote_currency).strip().upper()
        if not symbol:
            raise ValueError("instrument symbol is required")
        if not _CURRENCY.fullmatch(quote):
            raise ValueError("quote_currency must be an ISO-4217-like code")
        if self.base_currency is not None and not _CURRENCY.fullmatch(
            str(self.base_currency).strip().upper()
        ):
            raise ValueError("base_currency must be an ISO-4217-like code")
        for name in ("multiplier", "lot_size", "tick_size"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if int(self.settlement_days) < 0:
            raise ValueError("settlement_days must be non-negative")
        for name in ("initial_margin_rate", "maintenance_margin_rate"):
            value = getattr(self, name)
            if value is not None and (not math.isfinite(float(value)) or not 0 <= float(value) <= 1):
                raise ValueError(f"{name} must be in [0, 1]")
        if self.asset_class == AssetClass.FX and not self.base_currency:
            raise ValueError("FX instruments require base_currency")
        if self.asset_class == AssetClass.OPTION:
            if not self.underlying_symbol or self.strike is None or self.option_right is None:
                raise ValueError("options require underlying_symbol, strike and option_right")
            if self.expiry is None:
                raise ValueError("options require an explicit expiry")
        threshold = float(self.automatic_exercise_threshold)
        if not math.isfinite(threshold) or threshold < 0:
            raise ValueError("automatic_exercise_threshold must be finite and non-negative")
        if self.deliverable_quantity is not None:
            deliverable = float(self.deliverable_quantity)
            if not math.isfinite(deliverable) or deliverable <= 0:
                raise ValueError("deliverable_quantity must be finite and positive")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "quote_currency", quote)
        object.__setattr__(self, "automatic_exercise_threshold", threshold)
        if self.option_calendar_id is not None:
            calendar_id = str(self.option_calendar_id).strip()
            object.__setattr__(self, "option_calendar_id", calendar_id or None)
        if self.deliverable_quantity is not None:
            object.__setattr__(self, "deliverable_quantity", float(self.deliverable_quantity))
        if self.base_currency is not None:
            object.__setattr__(self, "base_currency", str(self.base_currency).strip().upper())
        if self.expiry is not None:
            object.__setattr__(self, "expiry", _utc(self.expiry))
        if self.active_from is not None:
            object.__setattr__(self, "active_from", _utc(self.active_from))
        if self.active_to is not None:
            object.__setattr__(self, "active_to", _utc(self.active_to))

    @property
    def key(self) -> str:
        if self.instrument_id:
            return str(self.instrument_id).strip().upper()
        expiry = self.expiry.date().isoformat() if self.expiry else "OPEN"
        return f"{self.exchange}:{self.asset_class.value}:{self.symbol}:{expiry}".upper()

    @property
    def is_derivative(self) -> bool:
        return self.asset_class in {
            AssetClass.FX,
            AssetClass.CRYPTO_PERPETUAL,
            AssetClass.FUTURE,
            AssetClass.OPTION,
            AssetClass.CFD,
        }

    @property
    def uses_variation_margin(self) -> bool:
        return self.asset_class in {
            AssetClass.FX,
            AssetClass.CRYPTO_PERPETUAL,
            AssetClass.FUTURE,
            AssetClass.CFD,
            AssetClass.RATE,
        }

    @property
    def is_cash_asset(self) -> bool:
        """Whether trades exchange principal or premium on trade date."""

        return not self.uses_variation_margin


@dataclass(frozen=True)
class Event:
    kind: EventKind
    occurred_at: datetime
    available_at: datetime
    symbol: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)
    source: str = ""
    source_sequence: int = 0
    event_id: str = ""

    def __post_init__(self) -> None:
        occurred = _utc(self.occurred_at)
        available = _utc(self.available_at)
        object.__setattr__(self, "occurred_at", occurred)
        object.__setattr__(self, "available_at", available)
        object.__setattr__(self, "symbol", str(self.symbol).strip().upper())
        if int(self.source_sequence) < 0:
            raise ValueError("source_sequence must be non-negative")
        if not self.event_id:
            identity = {
                "kind": int(self.kind),
                "occurred_at": occurred.isoformat(),
                "available_at": available.isoformat(),
                "symbol": self.symbol,
                "source": self.source,
                "source_sequence": int(self.source_sequence),
                "payload": self.payload,
            }
            encoded = json.dumps(identity, sort_keys=True, default=repr).encode("utf-8")
            object.__setattr__(self, "event_id", sha256(encoded).hexdigest())

    @property
    def process_at(self) -> datetime:
        """Clock when the event is both known and economically effective."""

        return max(self.occurred_at, self.available_at)
