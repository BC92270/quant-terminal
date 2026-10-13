"""Public strategy contracts for the isolated Backtest Lab runner.

This package contains types only.  It does not execute strategy source and it
does not expose filesystem, network, process or broker access.  A sandbox runner
supplies the concrete ``Context`` implementation at execution time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from random import Random
from types import MappingProxyType
from typing import Any, Iterator, Mapping, Protocol, Sequence


SDK_CONTRACT_VERSION = "2"


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("strategy timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class Bar:
    symbol: str
    event_time: datetime
    available_at: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    fields: Mapping[str, float | str | bool | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", str(self.symbol).strip().upper())
        object.__setattr__(self, "event_time", _utc(self.event_time))
        object.__setattr__(self, "available_at", _utc(self.available_at))
        if self.available_at < self.event_time:
            raise ValueError("available_at cannot precede event_time")


@dataclass(frozen=True)
class Slice(Mapping[str, Bar]):
    """Atomic market-data view delivered to ``on_slice``.

    Every member has the same event and availability timestamps.  The mapping
    is copied and frozen so strategy code cannot mutate the observation shared
    by the attested runner.
    """

    event_time: datetime
    available_at: datetime
    bars: Mapping[str, Bar]

    def __post_init__(self) -> None:
        event_time = _utc(self.event_time)
        available_at = _utc(self.available_at)
        if available_at < event_time:
            raise ValueError("available_at cannot precede event_time")
        normalized: dict[str, Bar] = {}
        for raw_symbol, bar in dict(self.bars).items():
            if not isinstance(bar, Bar):
                raise TypeError("slice members must be Bar instances")
            symbol = str(raw_symbol).strip().upper()
            if not symbol or symbol != bar.symbol:
                raise ValueError("slice key must match bar.symbol")
            if bar.event_time != event_time or bar.available_at != available_at:
                raise ValueError("slice bars must share event_time and available_at")
            normalized[symbol] = bar
        if not normalized:
            raise ValueError("slice must contain at least one bar")
        object.__setattr__(self, "event_time", event_time)
        object.__setattr__(self, "available_at", available_at)
        object.__setattr__(
            self, "bars", MappingProxyType(dict(sorted(normalized.items())))
        )

    def __getitem__(self, symbol: str) -> Bar:
        return self.bars[str(symbol).strip().upper()]

    def __iter__(self) -> Iterator[str]:
        return iter(self.bars)

    def __len__(self) -> int:
        return len(self.bars)

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(self.bars)


@dataclass(frozen=True)
class PortfolioSnapshot:
    """Read-only portfolio state supplied by the trusted host.

    The current batch target runner deliberately sets ``available=False``:
    authoritative positions are created later by ``backtest_universal``.  The
    explicit availability flag prevents an empty mapping from being mistaken
    for a flat, fully reconciled portfolio.
    """

    available: bool = False
    as_of: datetime | None = None
    positions: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    cash: Mapping[str, float] = field(default_factory=dict)
    open_orders: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    reason: str = "AUTHORITATIVE_PORTFOLIO_NOT_CONNECTED"

    def __post_init__(self) -> None:
        as_of = _utc(self.as_of) if self.as_of is not None else None
        positions = {
            str(symbol).strip().upper(): MappingProxyType(dict(values))
            for symbol, values in dict(self.positions).items()
        }
        cash = {
            str(currency).strip().upper(): float(balance)
            for currency, balance in dict(self.cash).items()
        }
        orders = tuple(MappingProxyType(dict(order)) for order in self.open_orders)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(
            self, "positions", MappingProxyType(dict(sorted(positions.items())))
        )
        object.__setattr__(self, "cash", MappingProxyType(dict(sorted(cash.items()))))
        object.__setattr__(self, "open_orders", orders)
        object.__setattr__(self, "reason", str(self.reason))


@dataclass(frozen=True)
class TargetSignal:
    symbol: str
    event_time: datetime
    available_at: datetime
    target_exposure: float
    reason_code: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", str(self.symbol).strip().upper())
        object.__setattr__(self, "event_time", _utc(self.event_time))
        object.__setattr__(self, "available_at", _utc(self.available_at))
        if self.available_at < self.event_time:
            raise ValueError("available_at cannot precede event_time")
        if not -4.0 <= float(self.target_exposure) <= 4.0:
            raise ValueError("target_exposure is outside the SDK safety envelope")


class Context(Protocol):
    """Capabilities injected by the attested runner, never by Streamlit."""

    now: datetime
    parameters: Mapping[str, Any]
    state: Any
    rng: Random
    portfolio: PortfolioSnapshot
    positions: Mapping[str, Mapping[str, Any]]
    cash: Mapping[str, float]
    open_orders: Sequence[Mapping[str, Any]]

    def history(self, symbol: str, field: str, periods: int) -> Sequence[float]: ...

    def target_percent(
        self,
        symbol: str,
        target: float,
        *,
        reason_code: str = "",
    ) -> None: ...

    def log(self, message: str, *, level: str = "INFO") -> None: ...


__all__ = [
    "Bar",
    "Context",
    "PortfolioSnapshot",
    "SDK_CONTRACT_VERSION",
    "Slice",
    "TargetSignal",
]
