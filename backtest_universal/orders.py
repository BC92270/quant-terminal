"""Deterministic order-management and top-of-book matching primitives.

This module is intentionally additive.  It does not change the existing
``UniversalBacktestEngine`` bar/target contract; it provides the stricter OMS
contract that later engine adapters can consume.

The kernel is single-clock and deterministic:

* callers provide timezone-aware timestamps and explicit visible liquidity;
* orders are evaluated in price-time priority, with a stable order-id tie-break;
* every transition and fill receives a monotonic, reproducible identifier;
* no fill is fabricated when the corresponding quote/trade size is unknown.

``MarketSnapshot`` is deliberately a small L1/trade contract.  An L2/L3 venue
simulator can consume the same order state machine while supplying its own fill
decisions through :meth:`OrderKernel.apply_fill`.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def sign(self) -> Decimal:
        return Decimal("1") if self is OrderSide.BUY else Decimal("-1")


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class TimeInForce(str, Enum):
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"
    DAY = "DAY"


class OrderStatus(str, Enum):
    NEW = "NEW"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"

    @property
    def terminal(self) -> bool:
        return self in {
            OrderStatus.FILLED,
            OrderStatus.CANCELED,
            OrderStatus.EXPIRED,
            OrderStatus.REJECTED,
        }


class OrderEventKind(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    TRIGGERED = "TRIGGERED"
    REPLACED = "REPLACED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


class InvalidOrderTransition(RuntimeError):
    """Raised when an operation is incompatible with the current order state."""


def _utc(value: datetime, *, name: str = "timestamp") -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _enum(value: Any, enum_type: type[Enum], *, name: str) -> Any:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value).strip().upper())
    except (TypeError, ValueError) as exc:
        choices = ", ".join(item.value for item in enum_type)
        raise ValueError(f"{name} must be one of: {choices}") from exc


def _decimal(
    value: Any,
    *,
    name: str,
    allow_none: bool = False,
    allow_zero: bool = False,
) -> Decimal | None:
    if value is None and allow_none:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not number.is_finite() or number < 0 or (not allow_zero and number == 0):
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{name} must be finite and {qualifier}")
    return number


@dataclass(frozen=True)
class OrderRequest:
    """Validated client intent before it enters the OMS.

    A ``DAY`` order requires an explicit ``expires_at``.  Exchange calendars
    differ, so silently treating UTC midnight as a venue close would produce a
    misleading simulation.
    """

    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    submitted_at: datetime
    time_in_force: TimeInForce = TimeInForce.GTC
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    expires_at: datetime | None = None
    order_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        symbol = str(self.symbol).strip().upper()
        if not symbol:
            raise ValueError("symbol is required")
        side = _enum(self.side, OrderSide, name="side")
        order_type = _enum(self.order_type, OrderType, name="order_type")
        tif = _enum(self.time_in_force, TimeInForce, name="time_in_force")
        quantity = _decimal(self.quantity, name="quantity")
        submitted = _utc(self.submitted_at, name="submitted_at")
        limit_price = _decimal(self.limit_price, name="limit_price", allow_none=True)
        stop_price = _decimal(self.stop_price, name="stop_price", allow_none=True)
        expires = (
            _utc(self.expires_at, name="expires_at")
            if self.expires_at is not None
            else None
        )
        if order_type is OrderType.MARKET and (limit_price is not None or stop_price is not None):
            raise ValueError("MARKET orders cannot define limit_price or stop_price")
        if order_type is OrderType.LIMIT and (limit_price is None or stop_price is not None):
            raise ValueError("LIMIT orders require only limit_price")
        if order_type is OrderType.STOP and (stop_price is None or limit_price is not None):
            raise ValueError("STOP orders require only stop_price")
        if order_type is OrderType.STOP_LIMIT and (
            stop_price is None or limit_price is None
        ):
            raise ValueError("STOP_LIMIT orders require stop_price and limit_price")
        if tif is TimeInForce.DAY and expires is None:
            raise ValueError("DAY orders require an explicit expires_at")
        if tif is not TimeInForce.DAY and expires is not None:
            raise ValueError("expires_at is only valid for DAY orders")
        if expires is not None and expires <= submitted:
            raise ValueError("expires_at must be after submitted_at")
        if order_type in {OrderType.STOP, OrderType.STOP_LIMIT} and tif in {
            TimeInForce.IOC,
            TimeInForce.FOK,
        }:
            raise ValueError("STOP orders do not support IOC or FOK in this kernel")
        supplied_id = None if self.order_id is None else str(self.order_id).strip()
        if self.order_id is not None and not supplied_id:
            raise ValueError("order_id cannot be blank")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "side", side)
        object.__setattr__(self, "order_type", order_type)
        object.__setattr__(self, "time_in_force", tif)
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "submitted_at", submitted)
        object.__setattr__(self, "limit_price", limit_price)
        object.__setattr__(self, "stop_price", stop_price)
        object.__setattr__(self, "expires_at", expires)
        object.__setattr__(self, "order_id", supplied_id)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True)
class Order:
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    submitted_at: datetime
    time_in_force: TimeInForce
    limit_price: Decimal | None
    stop_price: Decimal | None
    expires_at: datetime | None
    metadata: Mapping[str, Any]
    sequence: int
    priority_sequence: int
    status: OrderStatus = OrderStatus.NEW
    filled_quantity: Decimal = Decimal("0")
    average_fill_price: Decimal | None = None
    triggered: bool = False
    version: int = 1
    updated_at: datetime | None = None

    @property
    def remaining_quantity(self) -> Decimal:
        return self.quantity - self.filled_quantity

    @property
    def signed_filled_quantity(self) -> Decimal:
        return self.side.sign * self.filled_quantity

    @property
    def active(self) -> bool:
        return self.status in {OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED}


@dataclass(frozen=True)
class Fill:
    fill_id: str
    order_id: str
    symbol: str
    side: OrderSide
    occurred_at: datetime
    quantity: Decimal
    price: Decimal
    cumulative_quantity: Decimal
    remaining_quantity: Decimal
    source: str = "SIMULATED"

    @property
    def signed_quantity(self) -> Decimal:
        return self.side.sign * self.quantity


@dataclass(frozen=True)
class OrderEvent:
    event_id: str
    order_id: str
    occurred_at: datetime
    kind: OrderEventKind
    previous_status: OrderStatus
    status: OrderStatus
    reason: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MarketSnapshot:
    """A deterministic L1/trade observation used by the built-in matcher."""

    symbol: str
    observed_at: datetime
    bid: Decimal | None = None
    ask: Decimal | None = None
    last: Decimal | None = None
    bid_size: Decimal | None = None
    ask_size: Decimal | None = None
    last_size: Decimal | None = None
    source_sequence: int = 0

    def __post_init__(self) -> None:
        symbol = str(self.symbol).strip().upper()
        if not symbol:
            raise ValueError("symbol is required")
        observed = _utc(self.observed_at, name="observed_at")
        bid = _decimal(self.bid, name="bid", allow_none=True)
        ask = _decimal(self.ask, name="ask", allow_none=True)
        last = _decimal(self.last, name="last", allow_none=True)
        bid_size = _decimal(
            self.bid_size, name="bid_size", allow_none=True, allow_zero=True
        )
        ask_size = _decimal(
            self.ask_size, name="ask_size", allow_none=True, allow_zero=True
        )
        last_size = _decimal(
            self.last_size, name="last_size", allow_none=True, allow_zero=True
        )
        if bid is None and ask is None and last is None:
            raise ValueError("a market snapshot requires bid, ask, or last")
        if bid is not None and ask is not None and bid > ask:
            raise ValueError("bid cannot exceed ask")
        if bid_size is not None and bid is None:
            raise ValueError("bid_size requires bid")
        if ask_size is not None and ask is None:
            raise ValueError("ask_size requires ask")
        if last_size is not None and last is None:
            raise ValueError("last_size requires last")
        if int(self.source_sequence) < 0:
            raise ValueError("source_sequence must be non-negative")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "observed_at", observed)
        object.__setattr__(self, "bid", bid)
        object.__setattr__(self, "ask", ask)
        object.__setattr__(self, "last", last)
        object.__setattr__(self, "bid_size", bid_size)
        object.__setattr__(self, "ask_size", ask_size)
        object.__setattr__(self, "last_size", last_size)
        object.__setattr__(self, "source_sequence", int(self.source_sequence))


_UNSET = object()


class OrderKernel:
    """Deterministic OMS plus conservative top-of-book matching.

    The kernel owns order state and returns immutable snapshots.  Unknown
    liquidity is treated as zero.  This fail-closed rule prevents accidental
    infinite-liquidity fills and makes FOK behavior auditable.
    """

    def __init__(self) -> None:
        self._orders: dict[str, Order] = {}
        self._events: list[OrderEvent] = []
        self._fills: list[Fill] = []
        self._order_counter = 0
        self._priority_counter = 0
        self._event_counter = 0
        self._fill_counter = 0
        self._clock: datetime | None = None
        self._snapshot_ids: set[tuple[str, datetime, int]] = set()

    @property
    def clock(self) -> datetime | None:
        return self._clock

    @property
    def events(self) -> tuple[OrderEvent, ...]:
        return tuple(self._events)

    @property
    def fills(self) -> tuple[Fill, ...]:
        return tuple(self._fills)

    @property
    def orders(self) -> tuple[Order, ...]:
        return tuple(sorted(self._orders.values(), key=lambda item: item.sequence))

    def get(self, order_id: str) -> Order:
        key = str(order_id).strip()
        try:
            return self._orders[key]
        except KeyError as exc:
            raise KeyError(f"unknown order_id: {key}") from exc

    def active_orders(self, symbol: str | None = None) -> tuple[Order, ...]:
        key = None if symbol is None else str(symbol).strip().upper()
        active = [
            order
            for order in self._orders.values()
            if order.active and (key is None or order.symbol == key)
        ]
        return tuple(sorted(active, key=self._priority_key))

    def _advance_clock(self, value: datetime, *, name: str = "timestamp") -> datetime:
        stamp = _utc(value, name=name)
        if self._clock is not None and stamp < self._clock:
            raise ValueError("retroactive OMS operation rejected")
        self._clock = stamp
        return stamp

    def _next_priority(self) -> int:
        self._priority_counter += 1
        return self._priority_counter

    def _emit(
        self,
        order: Order,
        *,
        at: datetime,
        kind: OrderEventKind,
        previous_status: OrderStatus,
        reason: str = "",
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self._event_counter += 1
        self._events.append(
            OrderEvent(
                event_id=f"E{self._event_counter:012d}",
                order_id=order.order_id,
                occurred_at=at,
                kind=kind,
                previous_status=previous_status,
                status=order.status,
                reason=str(reason),
                details=MappingProxyType(dict(details or {})),
            )
        )

    def submit(self, request: OrderRequest) -> Order:
        if not isinstance(request, OrderRequest):
            raise TypeError("request must be an OrderRequest")
        stamp = self._advance_clock(request.submitted_at, name="submitted_at")
        self._order_counter += 1
        order_id = request.order_id or f"O{self._order_counter:012d}"
        if order_id in self._orders:
            raise ValueError(f"duplicate order_id: {order_id}")
        priority = self._next_priority()
        order = Order(
            order_id=order_id,
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            submitted_at=stamp,
            time_in_force=request.time_in_force,
            limit_price=request.limit_price,
            stop_price=request.stop_price,
            expires_at=request.expires_at,
            metadata=request.metadata,
            sequence=self._order_counter,
            priority_sequence=priority,
            updated_at=stamp,
        )
        self._orders[order_id] = order
        self._emit(
            order,
            at=stamp,
            kind=OrderEventKind.SUBMITTED,
            previous_status=OrderStatus.NEW,
        )
        accepted = replace(order, status=OrderStatus.ACCEPTED)
        self._orders[order_id] = accepted
        self._emit(
            accepted,
            at=stamp,
            kind=OrderEventKind.ACCEPTED,
            previous_status=OrderStatus.NEW,
        )
        return accepted

    def _require_active(self, order_id: str) -> Order:
        order = self.get(order_id)
        if not order.active:
            raise InvalidOrderTransition(
                f"order {order.order_id} is {order.status.value}, not active"
            )
        return order

    def cancel(self, order_id: str, *, at: datetime, reason: str = "CLIENT_REQUEST") -> Order:
        stamp = self._advance_clock(at)
        order = self._require_active(order_id)
        canceled = replace(order, status=OrderStatus.CANCELED, updated_at=stamp)
        self._orders[order.order_id] = canceled
        self._emit(
            canceled,
            at=stamp,
            kind=OrderEventKind.CANCELED,
            previous_status=order.status,
            reason=reason,
        )
        return canceled

    def reject(self, order_id: str, *, at: datetime, reason: str) -> Order:
        if not str(reason).strip():
            raise ValueError("rejection reason is required")
        stamp = self._advance_clock(at)
        order = self._require_active(order_id)
        rejected = replace(order, status=OrderStatus.REJECTED, updated_at=stamp)
        self._orders[order.order_id] = rejected
        self._emit(
            rejected,
            at=stamp,
            kind=OrderEventKind.REJECTED,
            previous_status=order.status,
            reason=reason,
        )
        return rejected

    def replace(
        self,
        order_id: str,
        *,
        at: datetime,
        quantity: Any = _UNSET,
        limit_price: Any = _UNSET,
        stop_price: Any = _UNSET,
        expires_at: Any = _UNSET,
        reason: str = "CLIENT_REPLACE",
    ) -> Order:
        stamp = self._advance_clock(at)
        order = self._require_active(order_id)
        new_quantity = (
            order.quantity
            if quantity is _UNSET
            else _decimal(quantity, name="quantity")
        )
        new_limit = (
            order.limit_price
            if limit_price is _UNSET
            else _decimal(limit_price, name="limit_price", allow_none=True)
        )
        new_stop = (
            order.stop_price
            if stop_price is _UNSET
            else _decimal(stop_price, name="stop_price", allow_none=True)
        )
        new_expires = order.expires_at
        if expires_at is not _UNSET:
            new_expires = (
                None
                if expires_at is None
                else _utc(expires_at, name="expires_at")
            )
        if new_quantity <= order.filled_quantity:
            raise ValueError("replacement quantity must exceed cumulative filled quantity")
        if order.order_type is OrderType.MARKET and (
            new_limit is not None or new_stop is not None
        ):
            raise ValueError("MARKET orders cannot define limit_price or stop_price")
        if order.order_type is OrderType.LIMIT and (
            new_limit is None or new_stop is not None
        ):
            raise ValueError("LIMIT orders require only limit_price")
        if order.order_type is OrderType.STOP and (
            new_stop is None or new_limit is not None
        ):
            raise ValueError("STOP orders require only stop_price")
        if order.order_type is OrderType.STOP_LIMIT and (
            new_stop is None or new_limit is None
        ):
            raise ValueError("STOP_LIMIT orders require stop_price and limit_price")
        if order.time_in_force is TimeInForce.DAY:
            if new_expires is None or new_expires <= stamp:
                raise ValueError("active DAY replacement requires a future expires_at")
        elif new_expires is not None:
            raise ValueError("expires_at is only valid for DAY orders")
        changes = {
            "quantity": (str(order.quantity), str(new_quantity)),
            "limit_price": (
                None if order.limit_price is None else str(order.limit_price),
                None if new_limit is None else str(new_limit),
            ),
            "stop_price": (
                None if order.stop_price is None else str(order.stop_price),
                None if new_stop is None else str(new_stop),
            ),
            "expires_at": (
                None if order.expires_at is None else order.expires_at.isoformat(),
                None if new_expires is None else new_expires.isoformat(),
            ),
        }
        material_changes = {key: value for key, value in changes.items() if value[0] != value[1]}
        if not material_changes:
            raise ValueError("replacement does not change the order")
        updated = replace(
            order,
            quantity=new_quantity,
            limit_price=new_limit,
            stop_price=new_stop,
            expires_at=new_expires,
            priority_sequence=self._next_priority(),
            version=order.version + 1,
            updated_at=stamp,
        )
        self._orders[order.order_id] = updated
        self._emit(
            updated,
            at=stamp,
            kind=OrderEventKind.REPLACED,
            previous_status=order.status,
            reason=reason,
            details={"changes": material_changes, "version": updated.version},
        )
        return updated

    def expire(self, order_id: str, *, at: datetime, reason: str = "SESSION_END") -> Order:
        stamp = self._advance_clock(at)
        order = self._require_active(order_id)
        expired = replace(order, status=OrderStatus.EXPIRED, updated_at=stamp)
        self._orders[order.order_id] = expired
        self._emit(
            expired,
            at=stamp,
            kind=OrderEventKind.EXPIRED,
            previous_status=order.status,
            reason=reason,
        )
        return expired

    def expire_orders(self, *, at: datetime) -> tuple[Order, ...]:
        stamp = self._advance_clock(at)
        due = sorted(
            (
                order
                for order in self._orders.values()
                if order.active
                and order.time_in_force is TimeInForce.DAY
                and order.expires_at is not None
                and order.expires_at <= stamp
            ),
            key=self._priority_key,
        )
        return tuple(self.expire(order.order_id, at=stamp) for order in due)

    def apply_fill(
        self,
        order_id: str,
        *,
        at: datetime,
        quantity: Any,
        price: Any,
        source: str = "SIMULATED",
    ) -> Fill:
        """Apply an externally determined fill to the OMS state machine."""

        stamp = self._advance_clock(at)
        order = self._require_active(order_id)
        fill_quantity = _decimal(quantity, name="fill quantity")
        fill_price = _decimal(price, name="fill price")
        if fill_quantity > order.remaining_quantity:
            raise ValueError("fill quantity exceeds order remaining quantity")
        cumulative = order.filled_quantity + fill_quantity
        if order.average_fill_price is None:
            average = fill_price
        else:
            average = (
                order.average_fill_price * order.filled_quantity
                + fill_price * fill_quantity
            ) / cumulative
        status = (
            OrderStatus.FILLED
            if cumulative == order.quantity
            else OrderStatus.PARTIALLY_FILLED
        )
        updated = replace(
            order,
            filled_quantity=cumulative,
            average_fill_price=average,
            status=status,
            updated_at=stamp,
        )
        self._orders[order.order_id] = updated
        self._fill_counter += 1
        fill = Fill(
            fill_id=f"F{self._fill_counter:012d}",
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            occurred_at=stamp,
            quantity=fill_quantity,
            price=fill_price,
            cumulative_quantity=cumulative,
            remaining_quantity=updated.remaining_quantity,
            source=str(source),
        )
        self._fills.append(fill)
        self._emit(
            updated,
            at=stamp,
            kind=(
                OrderEventKind.FILLED
                if status is OrderStatus.FILLED
                else OrderEventKind.PARTIALLY_FILLED
            ),
            previous_status=order.status,
            details={
                "fill_id": fill.fill_id,
                "quantity": str(fill.quantity),
                "price": str(fill.price),
                "cumulative_quantity": str(fill.cumulative_quantity),
                "remaining_quantity": str(fill.remaining_quantity),
            },
        )
        return fill

    @staticmethod
    def _priority_key(order: Order) -> tuple[int, str]:
        return order.priority_sequence, order.order_id

    @staticmethod
    def _stop_triggered(order: Order, snapshot: MarketSnapshot) -> bool:
        if order.order_type not in {OrderType.STOP, OrderType.STOP_LIMIT}:
            return True
        if order.triggered:
            return True
        reference = snapshot.last
        if reference is None:
            reference = snapshot.ask if order.side is OrderSide.BUY else snapshot.bid
        if reference is None or order.stop_price is None:
            return False
        if order.side is OrderSide.BUY:
            return reference >= order.stop_price
        return reference <= order.stop_price

    @staticmethod
    def _match(
        order: Order,
        snapshot: MarketSnapshot,
    ) -> tuple[Decimal, str] | None:
        effective_type = order.order_type
        if effective_type is OrderType.STOP:
            effective_type = OrderType.MARKET
        elif effective_type is OrderType.STOP_LIMIT:
            effective_type = OrderType.LIMIT

        if effective_type is OrderType.MARKET:
            if order.side is OrderSide.BUY and snapshot.ask is not None:
                return snapshot.ask, "ask"
            if order.side is OrderSide.SELL and snapshot.bid is not None:
                return snapshot.bid, "bid"
            if snapshot.last is not None:
                return snapshot.last, "last"
            return None

        if order.limit_price is None:
            return None
        if order.side is OrderSide.BUY:
            if snapshot.ask is not None and snapshot.ask <= order.limit_price:
                return snapshot.ask, "ask"
            if snapshot.last is not None and snapshot.last <= order.limit_price:
                return snapshot.last, "last"
        else:
            if snapshot.bid is not None and snapshot.bid >= order.limit_price:
                return snapshot.bid, "bid"
            if snapshot.last is not None and snapshot.last >= order.limit_price:
                return snapshot.last, "last"
        return None

    def process_snapshot(self, snapshot: MarketSnapshot) -> tuple[Fill, ...]:
        if not isinstance(snapshot, MarketSnapshot):
            raise TypeError("snapshot must be a MarketSnapshot")
        stamp = self._advance_clock(snapshot.observed_at, name="observed_at")
        snapshot_id = (snapshot.symbol, stamp, snapshot.source_sequence)
        if snapshot_id in self._snapshot_ids:
            raise ValueError("duplicate market snapshot rejected")
        self._snapshot_ids.add(snapshot_id)
        self.expire_orders(at=stamp)
        liquidity = {
            "bid": snapshot.bid_size or Decimal("0"),
            "ask": snapshot.ask_size or Decimal("0"),
            "last": snapshot.last_size or Decimal("0"),
        }
        created: list[Fill] = []
        for candidate in self.active_orders(snapshot.symbol):
            order = self.get(candidate.order_id)
            if not self._stop_triggered(order, snapshot):
                continue
            if order.order_type in {OrderType.STOP, OrderType.STOP_LIMIT} and not order.triggered:
                triggered = replace(order, triggered=True, updated_at=stamp)
                self._orders[order.order_id] = triggered
                self._emit(
                    triggered,
                    at=stamp,
                    kind=OrderEventKind.TRIGGERED,
                    previous_status=order.status,
                    details={"stop_price": str(order.stop_price)},
                )
                order = triggered
            matched = self._match(order, snapshot)
            available = Decimal("0") if matched is None else liquidity[matched[1]]
            if order.time_in_force is TimeInForce.FOK:
                if matched is not None and available >= order.remaining_quantity:
                    fill = self.apply_fill(
                        order.order_id,
                        at=stamp,
                        quantity=order.remaining_quantity,
                        price=matched[0],
                        source="L1_FOK",
                    )
                    liquidity[matched[1]] -= fill.quantity
                    created.append(fill)
                else:
                    self.cancel(
                        order.order_id,
                        at=stamp,
                        reason="FOK_NOT_FULLY_FILLABLE",
                    )
                continue
            if matched is not None and available > 0:
                fill_quantity = min(order.remaining_quantity, available)
                fill = self.apply_fill(
                    order.order_id,
                    at=stamp,
                    quantity=fill_quantity,
                    price=matched[0],
                    source="L1_MATCH",
                )
                liquidity[matched[1]] -= fill.quantity
                created.append(fill)
            current = self.get(order.order_id)
            if current.active and current.time_in_force is TimeInForce.IOC:
                self.cancel(
                    current.order_id,
                    at=stamp,
                    reason="IOC_REMAINDER_CANCELED",
                )
        return tuple(created)
