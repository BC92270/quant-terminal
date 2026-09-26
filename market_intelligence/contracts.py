"""Typed, point-in-time-safe contracts for Market Intelligence.

The contracts use only the standard library so importing the package never
requires a provider, a model artifact, or network access.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Mapping, Sequence

from .config import INTERACTION_STATES, PROVIDER_STATUSES, SCHEMA_VERSION


def as_utc(value: Any) -> datetime:
    """Return an aware UTC datetime, rejecting ambiguous naive timestamps."""

    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, str):
        candidate = value.strip().replace("Z", "+00:00")
        value = datetime.fromisoformat(candidate)
    if not isinstance(value, datetime):
        raise TypeError(f"Expected datetime-compatible value, got {type(value)!r}")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Point-in-time timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _finite_or_none(value: float | None, name: str) -> float | None:
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite or null")
    return number


class AvailabilityStatus(str, Enum):
    LIVE = "live"
    CACHED = "cached"
    DELAYED = "delayed"
    UNAVAILABLE = "unavailable"
    RESEARCH_ONLY = "research_only"
    SIMULATED = "simulated"


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    provider: str
    status: AvailabilityStatus
    as_of: datetime
    schema_level: str = "N/A"
    latency_ms: float | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of", as_utc(self.as_of))
        object.__setattr__(self, "latency_ms", _finite_or_none(self.latency_ms, "latency_ms"))
        if not str(self.provider).strip():
            raise ValueError("provider cannot be empty")
        if self.latency_ms is not None and self.latency_ms < 0.0:
            raise ValueError("latency_ms cannot be negative")
        if self.status.value not in PROVIDER_STATUSES:
            raise ValueError(f"Unsupported provider status: {self.status}")


@dataclass(frozen=True, slots=True)
class StructuredEvent:
    event_id: str
    title: str
    source: str
    source_url: str
    entity: str
    event_class: str
    subtype: str
    direction: str
    event_time: datetime
    publication_time: datetime
    first_seen_time: datetime
    ingested_at: datetime
    tradable_at: datetime
    feature_computed_at: datetime
    sentiment: float
    novelty: float
    confidence: float
    surprise_z: float | None = None
    cluster_id: str = ""
    revision_id: str = "r1"
    validation_flags: tuple[str, ...] = ()
    text: str = ""
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "event_time",
            "publication_time",
            "first_seen_time",
            "ingested_at",
            "tradable_at",
            "feature_computed_at",
        ):
            object.__setattr__(self, name, as_utc(getattr(self, name)))
        for name in ("event_id", "title", "source", "entity", "event_class", "revision_id"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} cannot be empty")
        if self.ingested_at < self.first_seen_time:
            raise ValueError("ingested_at cannot precede first_seen_time")
        if self.tradable_at < max(self.publication_time, self.first_seen_time):
            raise ValueError("tradable_at must not precede publication/first-seen time")
        if self.feature_computed_at < self.tradable_at:
            raise ValueError("feature_computed_at cannot precede tradable_at")
        if self.direction not in {"positive", "negative", "mixed", "neutral", "unknown"}:
            raise ValueError(f"Unsupported event direction: {self.direction}")
        for name in ("novelty", "confidence"):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
            object.__setattr__(self, name, value)
        sentiment = float(self.sentiment)
        if not -1.0 <= sentiment <= 1.0:
            raise ValueError("sentiment must be in [-1, 1]")
        object.__setattr__(self, "sentiment", sentiment)
        object.__setattr__(self, "surprise_z", _finite_or_none(self.surprise_z, "surprise_z"))

    @property
    def known_at(self) -> datetime:
        return self.tradable_at

    def to_record(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.event_time,
            "title": self.title,
            "entity": self.entity,
            "source": self.source,
            "event_class": self.event_class,
            "subtype": self.subtype,
            "direction": self.direction,
            "novelty": self.novelty,
            "surprise_z": self.surprise_z,
            "sentiment": self.sentiment,
            "confidence": self.confidence,
            "cluster_id": self.cluster_id,
            "revision_id": self.revision_id,
            "publication_time": self.publication_time,
            "first_seen_time": self.first_seen_time,
            "tradable_at": self.tradable_at,
            "feature_computed_at": self.feature_computed_at,
        }


@dataclass(frozen=True, slots=True)
class MicrostructureSnapshot:
    symbol: str
    as_of: datetime
    window: str
    schema_level: str
    provider_status: AvailabilityStatus
    best_bid: float | None
    best_ask: float | None
    bid_size: float | None
    ask_size: float | None
    mid: float | None
    microprice: float | None
    spread: float | None
    ofi: float | None
    queue_imbalance: float | None
    trade_imbalance: float | None = None
    cancel_intensity: float | None = None
    add_intensity: float | None = None
    bid_replenishment: float | None = None
    ask_replenishment: float | None = None
    price_impact_proxy: float | None = None
    anomaly_percentile: float | None = None
    uncertainty_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of", as_utc(self.as_of))
        if self.schema_level not in {"L1", "L2", "L3"}:
            raise ValueError("schema_level must be L1, L2, or L3")
        numeric_fields = (
            "best_bid", "best_ask", "bid_size", "ask_size", "mid", "microprice",
            "spread", "ofi", "queue_imbalance", "trade_imbalance", "cancel_intensity",
            "add_intensity", "bid_replenishment", "ask_replenishment",
            "price_impact_proxy", "anomaly_percentile",
        )
        for name in numeric_fields:
            object.__setattr__(self, name, _finite_or_none(getattr(self, name), name))
        for name in ("best_bid", "best_ask"):
            value = getattr(self, name)
            if value is not None and value <= 0.0:
                raise ValueError(f"{name} must be positive")
        for name in (
            "bid_size",
            "ask_size",
            "spread",
            "cancel_intensity",
            "add_intensity",
            "bid_replenishment",
            "ask_replenishment",
        ):
            value = getattr(self, name)
            if value is not None and value < 0.0:
                raise ValueError(f"{name} cannot be negative")
        if self.best_bid is not None and self.best_ask is not None and self.best_bid > self.best_ask:
            raise ValueError("best_bid cannot exceed best_ask")
        if self.best_bid is not None and self.best_ask is not None:
            expected_mid = (self.best_bid + self.best_ask) / 2.0
            expected_spread = self.best_ask - self.best_bid
            tolerance = max(1e-9, expected_spread * 1e-6)
            if self.mid is not None and not math.isclose(self.mid, expected_mid, rel_tol=1e-9, abs_tol=tolerance):
                raise ValueError("mid must equal the best-quote midpoint")
            if self.spread is not None and not math.isclose(
                self.spread, expected_spread, rel_tol=1e-9, abs_tol=tolerance
            ):
                raise ValueError("spread must equal best_ask minus best_bid")
        if self.queue_imbalance is not None and not -1.0 <= self.queue_imbalance <= 1.0:
            raise ValueError("queue_imbalance must be in [-1, 1]")
        if self.trade_imbalance is not None and not -1.0 <= self.trade_imbalance <= 1.0:
            raise ValueError("trade_imbalance must be in [-1, 1]")
        if self.anomaly_percentile is not None and not 0.0 <= self.anomaly_percentile <= 1.0:
            raise ValueError("anomaly_percentile must be in [0, 1]")
        if (
            self.microprice is not None
            and self.best_bid is not None
            and self.best_ask is not None
            and not self.best_bid <= self.microprice <= self.best_ask
        ):
            raise ValueError("microprice must remain within the spread")
        if self.schema_level == "L1":
            l2_only = (
                self.cancel_intensity,
                self.add_intensity,
                self.bid_replenishment,
                self.ask_replenishment,
            )
            if any(value is not None for value in l2_only):
                raise ValueError("L2/L3 event-intensity metrics cannot be populated in L1 mode")


@dataclass(frozen=True, slots=True)
class ForecastDistribution:
    symbol: str
    as_of: datetime
    horizon: str
    p_up: float | None
    expected_return: float | None
    q05: float | None
    q25: float | None
    q50: float | None
    q75: float | None
    q95: float | None
    expected_volatility: float | None
    jump_probability: float | None
    calibration_status: str
    model_id: str
    model_version: str
    feature_set_version: str
    data_cutoff: datetime
    provider_status: AvailabilityStatus
    regime_state: str
    primary_drivers: tuple[str, ...] = ()
    uncertainty_flags: tuple[str, ...] = ()
    sample_size: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of", as_utc(self.as_of))
        object.__setattr__(self, "data_cutoff", as_utc(self.data_cutoff))
        if self.data_cutoff > self.as_of:
            raise ValueError("Forecast data_cutoff cannot be after as_of")
        for name in (
            "p_up", "expected_return", "q05", "q25", "q50", "q75", "q95",
            "expected_volatility", "jump_probability",
        ):
            object.__setattr__(self, name, _finite_or_none(getattr(self, name), name))
        for name in ("p_up", "jump_probability"):
            value = getattr(self, name)
            if value is not None and not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
        if self.expected_volatility is not None and self.expected_volatility < 0.0:
            raise ValueError("expected_volatility cannot be negative")
        for name in ("symbol", "horizon", "model_id", "model_version", "feature_set_version"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} cannot be empty")
        quantiles = (self.q05, self.q25, self.q50, self.q75, self.q95)
        populated = [value is not None for value in quantiles]
        if any(populated) and not all(populated):
            raise ValueError("Forecast quantiles must be all populated or all null")
        if all(populated) and list(quantiles) != sorted(quantiles):
            raise ValueError("Forecast quantiles must be monotone")
        if self.sample_size < 0:
            raise ValueError("sample_size cannot be negative")
        required_values = (self.p_up, self.expected_return, *quantiles)
        if any(value is None for value in required_values) and not self.uncertainty_flags:
            raise ValueError("Null forecast fields require an uncertainty flag")

    def to_record(self) -> dict[str, Any]:
        return {
            "Horizon": self.horizon,
            "P(up)": self.p_up,
            "Expected return": self.expected_return,
            "Q05": self.q05,
            "Q25": self.q25,
            "Q50": self.q50,
            "Q75": self.q75,
            "Q95": self.q95,
            "Expected volatility": self.expected_volatility,
            "Jump probability": self.jump_probability,
            "Calibration": self.calibration_status,
            "Model": f"{self.model_id} · {self.model_version}",
            "Sample": self.sample_size,
            "Drivers": " · ".join(self.primary_drivers),
            "Uncertainty": " · ".join(self.uncertainty_flags),
        }


@dataclass(frozen=True, slots=True)
class InteractionAssessment:
    state: str
    catalyst_pressure: float
    microstructure_pressure: float
    collision_score: float
    intensity: float
    explanation: str
    evidence: tuple[str, ...]
    confidence: str
    validation_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.state not in INTERACTION_STATES:
            raise ValueError(f"Unsupported interaction state: {self.state}")
        if not 0.0 <= self.collision_score <= 1.0:
            raise ValueError("collision_score must be in [0, 1]")
        if self.intensity < 0.0:
            raise ValueError("intensity cannot be negative")
        if self.confidence not in {"HIGH", "MEDIUM", "LOW", "INVALID"}:
            raise ValueError("Unsupported confidence label")
        for name in ("catalyst_pressure", "microstructure_pressure", "collision_score", "intensity"):
            if not math.isfinite(float(getattr(self, name))):
                raise ValueError(f"{name} must be finite")
        if self.confidence == "INVALID" and not self.validation_flags:
            raise ValueError("INVALID interaction assessments require validation_flags")


@dataclass(frozen=True, slots=True)
class WorkspaceSnapshot:
    symbol: str
    instrument_name: str
    as_of: datetime
    price: float | None
    price_change: float | None
    regime: str
    regime_probability: float | None
    overall_status: str
    market_status: str
    catalyst_status: str
    microstructure_level: str
    timeline: Any
    events: tuple[StructuredEvent, ...]
    catalyst_contributions: Any
    microstructure: MicrostructureSnapshot
    interaction: InteractionAssessment
    forecasts: tuple[ForecastDistribution, ...]
    narratives: Any
    analogues: Any
    relationships: Any
    patterns: Any
    model_registry: Any
    provider_health: tuple[ProviderHealth, ...]
    audit: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of", as_utc(self.as_of))
        if not str(self.symbol).strip():
            raise ValueError("symbol cannot be empty")
        if self.regime_probability is not None and not 0.0 <= self.regime_probability <= 1.0:
            raise ValueError("regime_probability must be in [0, 1]")
        normalized_symbol = str(self.symbol).upper()
        if str(self.microstructure.symbol).upper() != normalized_symbol:
            raise ValueError("microstructure symbol must match workspace symbol")
        if self.microstructure.as_of > self.as_of:
            raise ValueError("microstructure as_of cannot be after workspace as_of")
        for event in self.events:
            if event.feature_computed_at > self.as_of:
                raise ValueError("event features cannot be computed after workspace as_of")
        for forecast in self.forecasts:
            if str(forecast.symbol).upper() != normalized_symbol:
                raise ValueError("forecast symbol must match workspace symbol")
            if forecast.as_of > self.as_of or forecast.data_cutoff > self.as_of:
                raise ValueError("forecast timestamps cannot be after workspace as_of")
