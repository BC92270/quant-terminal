"""Explicit data-quality and freshness policy evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import math
import re
from typing import Any, Iterable

from ..contracts import AvailabilityStatus, ProviderHealth, WorkspaceSnapshot, as_utc


class QualityState(str, Enum):
    CURRENT = "current"
    DEGRADED = "degraded"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    SIMULATED = "simulated"
    RESEARCH_ONLY = "research_only"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class FreshnessRule:
    layer: str
    max_age: timedelta
    min_completeness: float = 1.0
    required: bool = True

    def __post_init__(self) -> None:
        if not self.layer.strip():
            raise ValueError("FreshnessRule layer cannot be empty")
        if self.max_age < timedelta(0):
            raise ValueError("max_age cannot be negative")
        if not 0.0 <= float(self.min_completeness) <= 1.0:
            raise ValueError("min_completeness must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class QualityPolicy:
    version: str
    rules: tuple[FreshnessRule, ...]
    fallback_max_age: timedelta = timedelta(minutes=5)

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("QualityPolicy version cannot be empty")
        if self.fallback_max_age < timedelta(0):
            raise ValueError("fallback_max_age cannot be negative")
        names = [rule.layer for rule in self.rules]
        if len(names) != len(set(names)):
            raise ValueError("QualityPolicy cannot contain duplicate layers")

    def rule_for(self, layer: str) -> FreshnessRule:
        return next(
            (rule for rule in self.rules if rule.layer == layer),
            FreshnessRule(layer=layer, max_age=self.fallback_max_age),
        )

    @classmethod
    def institutional_default(cls) -> "QualityPolicy":
        return cls(
            version="mi-quality-2.0.0",
            rules=(
                FreshnessRule("quant_terminal_context", timedelta(minutes=15), min_completeness=0.95),
                FreshnessRule("catalyst_news", timedelta(minutes=5), min_completeness=0.95),
                FreshnessRule("order_book", timedelta(seconds=30), min_completeness=0.99),
                FreshnessRule("forecast_registry", timedelta(hours=1), min_completeness=1.0),
            ),
        )


@dataclass(frozen=True, slots=True)
class LayerQuality:
    layer: str
    state: QualityState
    as_of: datetime
    evaluated_at: datetime
    age_seconds: float | None
    completeness: float | None
    source_status: AvailabilityStatus
    required: bool
    flags: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.layer.strip():
            raise ValueError("LayerQuality layer cannot be empty")
        object.__setattr__(self, "as_of", as_utc(self.as_of))
        object.__setattr__(self, "evaluated_at", as_utc(self.evaluated_at))
        if self.age_seconds is not None and not math.isfinite(float(self.age_seconds)):
            raise ValueError("age_seconds must be finite or null")
        if self.completeness is not None and not 0.0 <= float(self.completeness) <= 1.0:
            raise ValueError("completeness must be in [0, 1]")

    @property
    def blocking(self) -> bool:
        return self.required and self.state not in {QualityState.CURRENT, QualityState.DEGRADED}


def provider_layer(provider_name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(provider_name).casefold()).strip("_")
    return normalized or "unnamed_provider"


def assess_provider_quality(
    provider: ProviderHealth,
    *,
    evaluated_at: Any,
    policy: QualityPolicy | None = None,
    layer: str | None = None,
    completeness: float | None = None,
    evidence_ids: Iterable[str] = (),
) -> LayerQuality:
    active_policy = policy or QualityPolicy.institutional_default()
    layer_name = layer or provider_layer(provider.provider)
    rule = active_policy.rule_for(layer_name)
    evaluation_time = as_utc(evaluated_at)
    age = (evaluation_time - provider.as_of).total_seconds()
    flags: list[str] = []

    if age < 0.0:
        state = QualityState.INVALID
        flags.append("PROVIDER_TIMESTAMP_AFTER_EVALUATION")
    elif provider.status == AvailabilityStatus.UNAVAILABLE:
        state = QualityState.UNAVAILABLE
        flags.append("PROVIDER_UNAVAILABLE")
    elif provider.status == AvailabilityStatus.SIMULATED:
        state = QualityState.SIMULATED
        flags.append("SIMULATED_INPUT")
    elif provider.status == AvailabilityStatus.RESEARCH_ONLY:
        state = QualityState.RESEARCH_ONLY
        flags.append("RESEARCH_ONLY_INPUT")
    elif completeness is None and rule.required:
        state = QualityState.INVALID
        flags.append("COMPLETENESS_NOT_ASSERTED")
    elif completeness is not None and completeness < rule.min_completeness:
        state = QualityState.INVALID
        flags.append("COMPLETENESS_BELOW_POLICY")
    elif age > rule.max_age.total_seconds():
        state = QualityState.STALE
        flags.append("FRESHNESS_SLA_BREACH")
    elif provider.status in {AvailabilityStatus.CACHED, AvailabilityStatus.DELAYED}:
        state = QualityState.DEGRADED
        flags.append(provider.status.value.upper())
    else:
        state = QualityState.CURRENT

    if completeness is None and "COMPLETENESS_NOT_ASSERTED" not in flags:
        flags.append("COMPLETENESS_NOT_ASSERTED")
    return LayerQuality(
        layer=layer_name,
        state=state,
        as_of=provider.as_of,
        evaluated_at=evaluation_time,
        age_seconds=age,
        completeness=completeness,
        source_status=provider.status,
        required=rule.required,
        flags=tuple(flags),
        evidence_ids=tuple(str(item) for item in evidence_ids),
    )


def assess_snapshot_quality(
    snapshot: WorkspaceSnapshot,
    *,
    evaluated_at: Any | None = None,
    policy: QualityPolicy | None = None,
    evidence_ids: dict[str, tuple[str, ...]] | None = None,
) -> tuple[LayerQuality, ...]:
    """Assess provider layers without turning simulation into current data."""

    evaluation_time = snapshot.as_of if evaluated_at is None else as_utc(evaluated_at)
    active_policy = policy or QualityPolicy.institutional_default()
    references = evidence_ids or {}
    results: list[LayerQuality] = []
    for provider in snapshot.provider_health:
        layer = provider_layer(provider.provider)
        results.append(
            assess_provider_quality(
                provider,
                evaluated_at=evaluation_time,
                policy=active_policy,
                layer=layer,
                evidence_ids=references.get(layer, ()),
            )
        )
    return tuple(results)
