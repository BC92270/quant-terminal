"""Deterministic L2/L3 order-book replay contracts.

This is a venue-neutral reference implementation.  It validates sequence and
knowledge time before mutating state and permanently labels simulated depth as
synthetic.  Exchange-specific queue priority and packet recovery can be added
through adapters without weakening those invariants.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
import math
from types import MappingProxyType
from typing import Any, Iterable, Mapping


class ReplayMode(str, Enum):
    REAL_REPLAY = "REAL_REPLAY"
    SYNTHETIC_MODEL = "SYNTHETIC_MODEL"


class BookDepth(str, Enum):
    L2 = "L2"
    L3 = "L3"


class BookSide(str, Enum):
    BID = "BID"
    ASK = "ASK"


class BookEventKind(str, Enum):
    UPSERT = "UPSERT"
    CANCEL = "CANCEL"
    TRADE = "TRADE"
    CLEAR = "CLEAR"


def _utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class BookEvent:
    instrument_id: str
    sequence: int
    event_time: datetime
    available_at: datetime
    kind: BookEventKind
    side: BookSide | None = None
    price: float | None = None
    size: float | None = None
    order_id: str = ""
    source: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        instrument_id = str(self.instrument_id).strip().upper()
        if not instrument_id:
            raise ValueError("instrument_id is required")
        if int(self.sequence) < 0:
            raise ValueError("sequence must be non-negative")
        event_time = _utc(self.event_time, "event_time")
        available_at = _utc(self.available_at, "available_at")
        if available_at < event_time:
            raise ValueError("available_at cannot precede event_time")
        if self.kind in {BookEventKind.UPSERT, BookEventKind.CANCEL} and self.side is None:
            raise ValueError(f"{self.kind.value} requires side")
        if self.kind is BookEventKind.UPSERT:
            if self.price is None or self.size is None:
                raise ValueError("UPSERT requires price and size")
            if not math.isfinite(float(self.price)) or float(self.price) <= 0:
                raise ValueError("book price must be finite and positive")
            if not math.isfinite(float(self.size)) or float(self.size) <= 0:
                raise ValueError("book size must be finite and positive")
        if self.kind is BookEventKind.CANCEL and self.price is None and not self.order_id:
            raise ValueError("CANCEL requires price for L2 or order_id for L3")
        if self.kind is BookEventKind.TRADE:
            if self.price is None or self.size is None:
                raise ValueError("TRADE requires price and size")
            if float(self.price) <= 0 or float(self.size) <= 0:
                raise ValueError("trade price and size must be positive")
        object.__setattr__(self, "instrument_id", instrument_id)
        object.__setattr__(self, "event_time", event_time)
        object.__setattr__(self, "available_at", available_at)
        object.__setattr__(self, "order_id", str(self.order_id).strip())
        object.__setattr__(self, "source", str(self.source).strip())
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True)
class PriceLevel:
    price: float
    size: float
    order_count: int


@dataclass(frozen=True)
class OrderBookSnapshot:
    instrument_id: str
    sequence: int
    as_of: datetime
    bids: tuple[PriceLevel, ...]
    asks: tuple[PriceLevel, ...]
    last_trade_price: float | None
    state_sha256: str
    replay_mode: ReplayMode

    @property
    def best_bid(self) -> float | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0].price if self.asks else None


@dataclass(frozen=True)
class ReplayReport:
    status: str
    replay_mode: ReplayMode
    depth: BookDepth
    events_processed: int
    first_sequence: int | None
    last_sequence: int | None
    gaps: tuple[tuple[int, int], ...]
    out_of_order: tuple[int, ...]
    source_authenticated: bool
    state_sha256: str
    reason: str = ""

    @property
    def certified_real_replay(self) -> bool:
        return bool(
            self.status == "PASS"
            and self.replay_mode is ReplayMode.REAL_REPLAY
            and self.source_authenticated
            and not self.gaps
            and not self.out_of_order
        )


class SequenceIntegrityError(RuntimeError):
    pass


class OrderBookReplay:
    """Strict one-instrument book with deterministic state hashing."""

    def __init__(
        self,
        instrument_id: str,
        *,
        depth: BookDepth,
        mode: ReplayMode,
        source_authenticated: bool = False,
        strict_sequence: bool = True,
    ) -> None:
        self.instrument_id = str(instrument_id).strip().upper()
        if not self.instrument_id:
            raise ValueError("instrument_id is required")
        self.depth = BookDepth(depth)
        self.mode = ReplayMode(mode)
        self.source_authenticated = bool(source_authenticated)
        self.strict_sequence = bool(strict_sequence)
        self._levels: dict[BookSide, dict[float, float]] = {
            BookSide.BID: {},
            BookSide.ASK: {},
        }
        self._orders: dict[str, tuple[BookSide, float, float]] = {}
        self._last_sequence: int | None = None
        self._first_sequence: int | None = None
        self._clock: datetime | None = None
        self._last_trade: float | None = None
        self._processed = 0
        self._gaps: list[tuple[int, int]] = []
        self._out_of_order: list[int] = []

    def _check_sequence(self, sequence: int) -> None:
        if self._last_sequence is None:
            self._first_sequence = sequence
            return
        expected = self._last_sequence + 1
        if sequence <= self._last_sequence:
            self._out_of_order.append(sequence)
            if self.strict_sequence:
                raise SequenceIntegrityError(
                    f"out-of-order sequence {sequence}; last={self._last_sequence}"
                )
        elif sequence != expected:
            self._gaps.append((expected, sequence - 1))
            if self.strict_sequence:
                raise SequenceIntegrityError(
                    f"sequence gap {expected}-{sequence - 1}"
                )

    def _add_level(self, side: BookSide, price: float, delta: float) -> None:
        level = self._levels[side]
        updated = level.get(price, 0.0) + float(delta)
        if updated <= 1e-12:
            level.pop(price, None)
        else:
            level[price] = updated

    def apply(self, event: BookEvent) -> OrderBookSnapshot:
        if event.instrument_id != self.instrument_id:
            raise ValueError("event instrument does not match replay book")
        if self._clock is not None and event.available_at < self._clock:
            raise SequenceIntegrityError("knowledge clock moved backwards")
        self._check_sequence(int(event.sequence))
        if event.kind is BookEventKind.CLEAR:
            self._levels = {BookSide.BID: {}, BookSide.ASK: {}}
            self._orders.clear()
        elif event.kind is BookEventKind.TRADE:
            self._last_trade = float(event.price)
            if self.depth is BookDepth.L3 and event.order_id:
                current = self._orders.get(event.order_id)
                if current is None:
                    raise ValueError("trade references unknown L3 order_id")
                side, price, size = current
                remaining = size - float(event.size)
                if remaining < -1e-12:
                    raise ValueError("trade size exceeds resting L3 order")
                self._add_level(side, price, -min(size, float(event.size)))
                if remaining <= 1e-12:
                    self._orders.pop(event.order_id, None)
                else:
                    self._orders[event.order_id] = (side, price, remaining)
        elif self.depth is BookDepth.L2:
            assert event.side is not None
            price = float(event.price)
            if event.kind is BookEventKind.CANCEL:
                self._levels[event.side].pop(price, None)
            else:
                self._levels[event.side][price] = float(event.size)
        else:
            assert event.side is not None
            if not event.order_id:
                raise ValueError("L3 UPSERT/CANCEL requires order_id")
            previous = self._orders.get(event.order_id)
            if event.kind is BookEventKind.CANCEL:
                if previous is None:
                    raise ValueError("cancel references unknown L3 order_id")
                side, price, size = previous
                if side is not event.side:
                    raise ValueError("cancel side does not match resting L3 order")
                self._add_level(side, price, -size)
                self._orders.pop(event.order_id, None)
            else:
                if previous is not None:
                    side, price, size = previous
                    self._add_level(side, price, -size)
                current = (event.side, float(event.price), float(event.size))
                self._orders[event.order_id] = current
                self._add_level(*current)
        self._last_sequence = int(event.sequence)
        self._clock = event.available_at
        self._processed += 1
        return self.snapshot()

    def _price_levels(self, side: BookSide) -> tuple[PriceLevel, ...]:
        prices = sorted(self._levels[side], reverse=side is BookSide.BID)
        counts: dict[float, int] = {}
        if self.depth is BookDepth.L3:
            for order_side, price, _ in self._orders.values():
                if order_side is side:
                    counts[price] = counts.get(price, 0) + 1
        return tuple(
            PriceLevel(price, self._levels[side][price], counts.get(price, 0))
            for price in prices
        )

    def snapshot(self) -> OrderBookSnapshot:
        bids = self._price_levels(BookSide.BID)
        asks = self._price_levels(BookSide.ASK)
        payload = {
            "instrument_id": self.instrument_id,
            "sequence": self._last_sequence,
            "clock": self._clock.isoformat() if self._clock else None,
            "bids": [(item.price, item.size, item.order_count) for item in bids],
            "asks": [(item.price, item.size, item.order_count) for item in asks],
            "last_trade": self._last_trade,
            "mode": self.mode.value,
        }
        digest = sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return OrderBookSnapshot(
            instrument_id=self.instrument_id,
            sequence=-1 if self._last_sequence is None else self._last_sequence,
            as_of=self._clock or datetime.min.replace(tzinfo=timezone.utc),
            bids=bids,
            asks=asks,
            last_trade_price=self._last_trade,
            state_sha256=digest,
            replay_mode=self.mode,
        )

    def replay(self, events: Iterable[BookEvent]) -> ReplayReport:
        reason = ""
        status = "PASS"
        try:
            for event in events:
                self.apply(event)
        except Exception as exc:
            status = "FAIL"
            reason = str(exc)
            if self.strict_sequence:
                raise
        if self._gaps or self._out_of_order:
            status = "FAIL"
            if not reason:
                reason = "sequence integrity failure"
        snapshot = self.snapshot()
        return ReplayReport(
            status=status,
            replay_mode=self.mode,
            depth=self.depth,
            events_processed=self._processed,
            first_sequence=self._first_sequence,
            last_sequence=self._last_sequence,
            gaps=tuple(self._gaps),
            out_of_order=tuple(self._out_of_order),
            source_authenticated=self.source_authenticated,
            state_sha256=snapshot.state_sha256,
            reason=reason,
        )


__all__ = [
    "BookDepth",
    "BookEvent",
    "BookEventKind",
    "BookSide",
    "OrderBookReplay",
    "OrderBookSnapshot",
    "PriceLevel",
    "ReplayMode",
    "ReplayReport",
    "SequenceIntegrityError",
]
