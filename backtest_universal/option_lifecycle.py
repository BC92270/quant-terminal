"""Fail-closed listed-option lifecycle and settlement instructions.

The resolver is deliberately independent from the event loop.  It converts
point-in-time contract/reference facts into an atomic instruction that an OMS
or portfolio ledger can apply at settlement.  Missing calendars, cut-offs or
reference marks never fall back to a fabricated price.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
import math
from typing import Mapping

from .portfolio import PortfolioLedger
from .types import (
    AssetClass,
    Event,
    EventKind,
    Instrument,
    OptionCalendarContract,
    OptionRight,
    SettlementType,
)


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("timezone-aware timestamp required")
    return value.astimezone(timezone.utc)


class OptionLifecycleRequestKind(str, Enum):
    EXPIRATION = "EXPIRATION"
    EARLY_EXERCISE = "EARLY_EXERCISE"
    EARLY_ASSIGNMENT = "EARLY_ASSIGNMENT"


class OptionLifecycleAction(str, Enum):
    CASH_SETTLEMENT = "CASH_SETTLEMENT"
    PHYSICAL_EXERCISE = "PHYSICAL_EXERCISE"
    PHYSICAL_ASSIGNMENT = "PHYSICAL_ASSIGNMENT"
    LAPSE = "LAPSE"
    DATA_REQUIRED = "DATA_REQUIRED"


@dataclass(frozen=True)
class OptionSettlementReference:
    """Reference facts as they were observable to the simulator."""

    observed_at: datetime
    available_at: datetime
    source: str
    source_version: str
    underlying_price: float | None = None
    official_settlement_value: float | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        observed = _utc(self.observed_at)
        available = _utc(self.available_at)
        source = str(self.source).strip()
        version = str(self.source_version).strip()
        if not source or not version:
            raise ValueError("settlement reference source and source_version are required")
        for name in ("underlying_price", "official_settlement_value"):
            value = getattr(self, name)
            if value is not None and (not math.isfinite(float(value)) or float(value) < 0):
                raise ValueError(f"{name} must be finite and non-negative")
        object.__setattr__(self, "observed_at", observed)
        object.__setattr__(self, "available_at", available)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "source_version", version)


@dataclass(frozen=True)
class OptionSettlementInstruction:
    lifecycle_id: str
    status: str
    action: OptionLifecycleAction
    request_kind: OptionLifecycleRequestKind
    option_instrument_id: str
    option_quantity: float
    option_close_quantity: float
    action_at: datetime
    settlement_at: datetime
    settlement_value: float
    intrinsic_value: float
    multiplier: float
    quote_currency: str
    underlying_instrument_id: str | None = None
    underlying_quantity_delta: float = 0.0
    cash_delta_quote: float = 0.0
    strike: float = 0.0
    underlying_reference_price: float | None = None
    automatic: bool = False
    reference_source: str = ""
    reference_version: str = ""
    reasons: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        return self.status == "READY"


class OptionLifecycleDataRequired(ValueError):
    """Raised when strict lifecycle resolution lacks authoritative facts."""


class OptionLifecycleProcessor:
    """Resolve and optionally apply cash or physical option settlement."""

    @staticmethod
    def _unavailable(
        instrument: Instrument,
        quantity: float,
        at: datetime,
        request_kind: OptionLifecycleRequestKind,
        reasons: list[str],
    ) -> OptionSettlementInstruction:
        stamp = _utc(at)
        payload = {
            "option": instrument.key,
            "quantity": quantity,
            "at": stamp.isoformat(),
            "request": request_kind.value,
            "reasons": reasons,
        }
        lifecycle_id = "OL-" + sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()[:20].upper()
        return OptionSettlementInstruction(
            lifecycle_id=lifecycle_id,
            status="DATA_REQUIRED",
            action=OptionLifecycleAction.DATA_REQUIRED,
            request_kind=request_kind,
            option_instrument_id=instrument.key,
            option_quantity=float(quantity),
            option_close_quantity=0.0,
            action_at=stamp,
            settlement_at=stamp,
            settlement_value=0.0,
            intrinsic_value=0.0,
            multiplier=float(instrument.multiplier),
            quote_currency=instrument.quote_currency,
            strike=float(instrument.strike or 0.0),
            reasons=tuple(reasons),
        )

    def resolve(
        self,
        *,
        instrument: Instrument,
        position_quantity: float,
        at: datetime,
        calendar: OptionCalendarContract | None,
        reference: OptionSettlementReference | None,
        underlying: Instrument | None = None,
        request_kind: OptionLifecycleRequestKind = OptionLifecycleRequestKind.EXPIRATION,
        requested_contracts: float | None = None,
        strict: bool = False,
    ) -> OptionSettlementInstruction:
        stamp = _utc(at)
        quantity = float(position_quantity)
        reasons: list[str] = []
        if instrument.asset_class != AssetClass.OPTION:
            reasons.append("instrument is not an option")
        if not math.isfinite(quantity) or abs(quantity) <= 1e-15:
            reasons.append("open option quantity is required")
        if instrument.expiry is None:
            reasons.append("option expiry reference is missing")
        if not instrument.option_calendar_id:
            reasons.append("option calendar_id is missing")
        if instrument.option_exercise_style is None:
            reasons.append("option exercise style is missing")
        if calendar is None:
            reasons.append("option calendar contract is missing")
        else:
            if instrument.option_calendar_id and calendar.calendar_id != instrument.option_calendar_id:
                reasons.append("option calendar_id does not match calendar contract")
            if instrument.option_exercise_style and calendar.exercise_style != instrument.option_exercise_style:
                reasons.append("option exercise style does not match calendar contract")
            if instrument.expiry and calendar.expiration_at != instrument.expiry:
                reasons.append("option expiry does not match calendar contract")
            if not calendar.is_known_at(stamp):
                reasons.append("option calendar was not available at lifecycle time")
        if reference is None:
            reasons.append("settlement reference is missing")
        else:
            if reference.observed_at > stamp or reference.available_at > stamp:
                reasons.append("settlement reference was not point-in-time available")

        requested = abs(quantity) if requested_contracts is None else float(requested_contracts)
        if not math.isfinite(requested) or requested <= 0 or requested > abs(quantity) + 1e-12:
            reasons.append("requested contracts must be positive and within the open position")
        if request_kind == OptionLifecycleRequestKind.EARLY_EXERCISE and quantity < 0:
            reasons.append("early exercise requires a long option position")
        if request_kind == OptionLifecycleRequestKind.EARLY_ASSIGNMENT and quantity > 0:
            reasons.append("early assignment requires a short option position")
        if calendar is not None:
            if request_kind == OptionLifecycleRequestKind.EXPIRATION:
                if stamp < calendar.exercise_cutoff_at:
                    reasons.append("expiration lifecycle cannot resolve before exercise cutoff")
            elif not calendar.permits_early_exercise(stamp):
                reasons.append("calendar/style does not permit early exercise at this time")

        if reference is not None:
            underlying_price = reference.underlying_price
            official_value = reference.official_settlement_value
        else:
            underlying_price = None
            official_value = None
        if underlying_price is None and official_value is None:
            reasons.append("underlying or official settlement reference is required")
        if instrument.settlement_type == SettlementType.PHYSICAL:
            if underlying is None:
                reasons.append("physical settlement requires the deliverable instrument")
            elif str(instrument.underlying_symbol).strip().upper() not in {
                underlying.key,
                underlying.symbol,
            }:
                reasons.append("deliverable instrument does not match option underlying")
            if underlying_price is None:
                reasons.append("physical settlement requires an underlying reference price")
            elif underlying is not None and underlying.quote_currency != instrument.quote_currency:
                reasons.append("cross-currency physical delivery requires an explicit FX adapter")

        if reasons:
            instruction = self._unavailable(instrument, quantity, stamp, request_kind, reasons)
            if strict:
                raise OptionLifecycleDataRequired("; ".join(instruction.reasons))
            return instruction

        assert calendar is not None and reference is not None
        assert instrument.strike is not None and instrument.option_right is not None
        signed_quantity = math.copysign(requested, quantity)
        if underlying_price is not None:
            if instrument.option_right == OptionRight.CALL:
                intrinsic = max(float(underlying_price) - float(instrument.strike), 0.0)
            else:
                intrinsic = max(float(instrument.strike) - float(underlying_price), 0.0)
        else:
            intrinsic = float(official_value or 0.0)
        settlement_value = (
            float(official_value) if official_value is not None else float(intrinsic)
        )
        automatic = request_kind == OptionLifecycleRequestKind.EXPIRATION
        lapses = automatic and intrinsic <= float(instrument.automatic_exercise_threshold)
        delivery_units = float(
            instrument.deliverable_quantity
            if instrument.deliverable_quantity is not None
            else instrument.multiplier
        )
        underlying_delta = 0.0
        cash_delta = 0.0
        underlying_id: str | None = None
        if lapses:
            action = OptionLifecycleAction.LAPSE
            settlement_value = 0.0
        elif instrument.settlement_type == SettlementType.CASH:
            action = OptionLifecycleAction.CASH_SETTLEMENT
            cash_delta = signed_quantity * float(instrument.multiplier) * settlement_value
        else:
            assert underlying is not None
            underlying_id = underlying.key
            direction = 1.0 if instrument.option_right == OptionRight.CALL else -1.0
            underlying_delta = signed_quantity * delivery_units * direction
            cash_delta = -signed_quantity * delivery_units * float(instrument.strike) * direction
            action = (
                OptionLifecycleAction.PHYSICAL_EXERCISE
                if signed_quantity > 0
                else OptionLifecycleAction.PHYSICAL_ASSIGNMENT
            )

        payload = {
            "option": instrument.key,
            "quantity": signed_quantity,
            "action_at": stamp.isoformat(),
            "settlement_at": calendar.settlement_at.isoformat(),
            "action": action.value,
            "reference": reference.source,
            "reference_version": reference.source_version,
            "settlement_value": settlement_value,
        }
        lifecycle_id = "OL-" + sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()[:20].upper()
        return OptionSettlementInstruction(
            lifecycle_id=lifecycle_id,
            status="READY",
            action=action,
            request_kind=request_kind,
            option_instrument_id=instrument.key,
            option_quantity=signed_quantity,
            option_close_quantity=-signed_quantity,
            action_at=stamp,
            settlement_at=calendar.settlement_at,
            settlement_value=settlement_value,
            intrinsic_value=float(intrinsic),
            multiplier=float(instrument.multiplier),
            quote_currency=instrument.quote_currency,
            underlying_instrument_id=underlying_id,
            underlying_quantity_delta=underlying_delta,
            cash_delta_quote=cash_delta,
            strike=float(instrument.strike),
            underlying_reference_price=(
                float(underlying_price) if underlying_price is not None else None
            ),
            automatic=automatic,
            reference_source=reference.source,
            reference_version=reference.source_version,
        )

    def apply(
        self,
        *,
        ledger: PortfolioLedger,
        instruction: OptionSettlementInstruction,
        option: Instrument,
        at: datetime,
        underlying: Instrument | None = None,
    ) -> None:
        """Atomically apply a previously resolved instruction at settlement."""

        stamp = _utc(at)
        if not instruction.available:
            raise OptionLifecycleDataRequired("; ".join(instruction.reasons))
        if stamp < instruction.settlement_at:
            raise ValueError("option lifecycle instruction is not due for settlement")
        if option.key != instruction.option_instrument_id:
            raise ValueError("option instrument does not match lifecycle instruction")
        if any(
            event.get("lifecycle_id") == instruction.lifecycle_id
            for event in ledger.realized_events
        ):
            raise ValueError("option lifecycle instruction was already applied")
        position = ledger.position(option.key)
        quantity = instruction.option_quantity
        if position.quantity * quantity <= 0 or abs(position.quantity) + 1e-12 < abs(quantity):
            raise ValueError("ledger option position no longer covers lifecycle instruction")
        if instruction.action in {
            OptionLifecycleAction.PHYSICAL_EXERCISE,
            OptionLifecycleAction.PHYSICAL_ASSIGNMENT,
        }:
            if underlying is None or underlying.key != instruction.underlying_instrument_id:
                raise ValueError("physical lifecycle instruction requires matching underlying")

        # Validation above is intentionally complete before the first mutation.
        close_price = (
            instruction.settlement_value
            if instruction.action == OptionLifecycleAction.CASH_SETTLEMENT
            else 0.0
        )
        realized = position.trade(instruction.option_close_quantity, close_price)
        realized *= float(option.multiplier)
        if instruction.cash_delta_quote:
            ledger.cash.deposit(option.quote_currency, instruction.cash_delta_quote)
        if underlying is not None and instruction.underlying_quantity_delta:
            delivered = ledger.position(underlying.key)
            delivered.trade(instruction.underlying_quantity_delta, instruction.strike)
            if instruction.underlying_reference_price is not None:
                delivered.last_price = instruction.underlying_reference_price
        ledger.realized_events.append(
            {
                "timestamp": stamp.isoformat(),
                "lifecycle_id": instruction.lifecycle_id,
                "kind": instruction.action.value.lower(),
                "instrument_id": option.key,
                "quantity": quantity,
                "settlement_value": instruction.settlement_value,
                "underlying_instrument_id": instruction.underlying_instrument_id,
                "underlying_quantity_delta": instruction.underlying_quantity_delta,
                "cash_delta_quote": instruction.cash_delta_quote,
                "currency": instruction.quote_currency,
                "realized_pnl": realized,
                "reference_source": instruction.reference_source,
                "reference_version": instruction.reference_version,
            }
        )

    @staticmethod
    def to_event(
        instruction: OptionSettlementInstruction,
        *,
        source_sequence: int = 0,
    ) -> Event:
        """Create a stable event suitable for the point-in-time queue."""

        return Event(
            EventKind.OPTION_LIFECYCLE,
            instruction.action_at,
            instruction.action_at,
            instruction.option_instrument_id,
            {
                "lifecycle_id": instruction.lifecycle_id,
                "status": instruction.status,
                "action": instruction.action.value,
                "settlement_at": instruction.settlement_at.isoformat(),
                "option_quantity": instruction.option_quantity,
                "underlying_instrument_id": instruction.underlying_instrument_id,
                "underlying_quantity_delta": instruction.underlying_quantity_delta,
                "cash_delta_quote": instruction.cash_delta_quote,
                "reasons": list(instruction.reasons),
            },
            source="option_lifecycle",
            source_sequence=source_sequence,
            event_id=instruction.lifecycle_id,
        )
