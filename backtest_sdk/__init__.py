"""Public strategy contracts for the isolated Backtest Lab runner.

This package contains types only.  It does not execute strategy source and it
does not expose filesystem, network, process or broker access.  A sandbox runner
supplies the concrete ``Context`` implementation at execution time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from random import Random
from typing import Any, Mapping, Protocol, Sequence


SDK_CONTRACT_VERSION = "1"


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
    "SDK_CONTRACT_VERSION",
    "TargetSignal",
]
