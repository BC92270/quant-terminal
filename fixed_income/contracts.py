"""Validated domain contracts for institutional fixed-income analytics."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from math import isfinite
from typing import Any, Iterable


class DataClassification(str, Enum):
    OBSERVED = "observed"
    LICENSED = "licensed"
    ANALYST = "analyst"
    DERIVED = "derived"
    ILLUSTRATIVE = "illustrative"


@dataclass(frozen=True)
class BasisPoints:
    value: float

    def __post_init__(self) -> None:
        value = float(self.value)
        if not isfinite(value):
            raise ValueError("basis points must be finite")
        object.__setattr__(self, "value", value)

    @property
    def decimal(self) -> float:
        return self.value / 10_000.0

    @property
    def percent(self) -> float:
        return self.value / 100.0


@dataclass(frozen=True)
class Percent:
    value: float

    def __post_init__(self) -> None:
        value = float(self.value)
        if not isfinite(value):
            raise ValueError("percent must be finite")
        object.__setattr__(self, "value", value)

    @property
    def decimal(self) -> float:
        return self.value / 100.0

    @classmethod
    def from_decimal(cls, value: float) -> "Percent":
        return cls(float(value) * 100.0)


@dataclass(frozen=True)
class Money:
    amount: float
    currency: str = "USD"

    def __post_init__(self) -> None:
        amount = float(self.amount)
        currency = str(self.currency).strip().upper()
        if not isfinite(amount):
            raise ValueError("money amount must be finite")
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError("currency must be a three-letter ISO code")
        object.__setattr__(self, "amount", amount)
        object.__setattr__(self, "currency", currency)


@dataclass(frozen=True)
class DataPoint:
    series_id: str
    value: Any
    observation_time: datetime
    available_time: datetime
    source: str
    classification: DataClassification
    unit: str = ""
    vintage_id: str = ""
    transformation: str = ""

    def __post_init__(self) -> None:
        if not str(self.series_id).strip():
            raise ValueError("series_id is required")
        if not str(self.source).strip():
            raise ValueError("source is required")
        observation = _as_utc(self.observation_time)
        available = _as_utc(self.available_time)
        if available < observation:
            raise ValueError("available_time cannot precede observation_time")
        object.__setattr__(self, "observation_time", observation)
        object.__setattr__(self, "available_time", available)

    def available_at(self, decision_time: datetime) -> bool:
        return self.available_time <= _as_utc(decision_time)


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    severity: str = "ERROR"
    field: str = ""
    row: int | None = None

    def __post_init__(self) -> None:
        severity = str(self.severity).upper()
        if severity not in {"INFO", "WARNING", "ERROR"}:
            raise ValueError("severity must be INFO, WARNING or ERROR")
        object.__setattr__(self, "severity", severity)


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "ERROR" for issue in self.issues)

    def add(
        self,
        code: str,
        message: str,
        severity: str = "ERROR",
        field: str = "",
        row: int | None = None,
    ) -> None:
        self.issues.append(ValidationIssue(code, message, severity, field, row))

    def extend(self, issues: Iterable[ValidationIssue]) -> None:
        self.issues.extend(list(issues))

    def as_dicts(self) -> list[dict[str, Any]]:
        return [
            {
                "code": issue.code,
                "message": issue.message,
                "severity": issue.severity,
                "field": issue.field,
                "row": issue.row,
            }
            for issue in self.issues
        ]


def _as_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("timestamp must be a datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def validate_weight_bounds(
    lower: Iterable[float],
    upper: Iterable[float],
    total: float = 1.0,
) -> ValidationReport:
    lower_values = [float(value) for value in lower]
    upper_values = [float(value) for value in upper]
    report = ValidationReport()
    if len(lower_values) != len(upper_values):
        report.add("BOUNDS_LENGTH", "lower and upper bounds must have equal length")
        return report
    for index, (low, high) in enumerate(zip(lower_values, upper_values)):
        if not isfinite(low) or not isfinite(high):
            report.add("BOUNDS_FINITE", "bounds must be finite", row=index)
        elif low < 0.0 or high < 0.0 or low > high:
            report.add("BOUNDS_ORDER", "expected 0 <= lower <= upper", row=index)
    if sum(lower_values) > total + 1e-10:
        report.add("LOWER_INFEASIBLE", "minimum weights exceed the total")
    if sum(upper_values) < total - 1e-10:
        report.add("UPPER_INFEASIBLE", "maximum weights sum below the total")
    return report
