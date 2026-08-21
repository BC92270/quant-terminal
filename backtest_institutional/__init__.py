"""Institutional Backtest V7: auditable, fail-closed research components."""

from .data_catalog import DataCatalogAssessment, assess_market_data, capability_or_unavailable
from .types import (
    AvailabilityState,
    CapabilityStatus,
    FieldStatus,
    Fill,
    LedgerResult,
    Order,
    RunManifest,
    ValidationMetric,
    ValidationState,
)

__all__ = [
    "AvailabilityState",
    "CapabilityStatus",
    "DataCatalogAssessment",
    "FieldStatus",
    "Fill",
    "LedgerResult",
    "Order",
    "RunManifest",
    "ValidationMetric",
    "ValidationState",
    "assess_market_data",
    "capability_or_unavailable",
]

__version__ = "7.0.0"
