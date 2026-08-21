"""Typed contracts shared by the institutional backtest stack."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional


class AvailabilityState(str, Enum):
    AVAILABLE = "AVAILABLE"
    ESTIMATED = "ESTIMATED"
    PARTIAL = "PARTIAL"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class ValidationState(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class FieldStatus:
    name: str
    state: AvailabilityState
    required: bool
    reason: str = ""
    missing_ratio: float = 0.0
    provenance: str = ""


@dataclass(frozen=True)
class CapabilityStatus:
    name: str
    state: AvailabilityState
    reason: str
    required_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class Order:
    order_id: str
    timestamp: str
    symbol: str
    side: str
    quantity: float
    order_type: str = "MARKET"
    target_exposure: float = 0.0
    status: str = "NEW"
    reason: str = ""


@dataclass(frozen=True)
class Fill:
    fill_id: str
    order_id: str
    timestamp: str
    symbol: str
    side: str
    quantity: float
    reference_price: float
    fill_price: float
    commission: float
    spread_cost: float
    impact_cost: float
    slippage_cost: float
    participation: Optional[float]
    liquidity_flag: str
    settlement_date: str


@dataclass
class LedgerResult:
    status: AvailabilityState
    reason: str
    orders: list[Order] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)
    daily: Any = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def records(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "orders": [asdict(item) for item in self.orders],
            "fills": [asdict(item) for item in self.fills],
        }


@dataclass(frozen=True)
class ValidationMetric:
    name: str
    value: Optional[float]
    state: ValidationState
    threshold: str
    interpretation: str
    method: str


@dataclass(frozen=True)
class RunManifest:
    run_id: str
    created_at: str
    engine_version: str
    strategy: str
    symbol: str
    seed: int
    config_hash: str
    data_hash: str
    code_hash: str
    environment_hash: str
    parent_run_id: Optional[str] = None
    tags: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
