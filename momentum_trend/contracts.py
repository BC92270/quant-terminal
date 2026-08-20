from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class DataQuality:
    rows: int
    start: pd.Timestamp | None
    end: pd.Timestamp | None
    missing_close: int
    missing_volume_ratio: float
    duplicate_dates: int
    stale_bars: int
    quality_score: float
    status: str
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class RegimeSnapshot:
    label: str
    confidence: float
    entropy: float
    persistence_bars: int
    transition_risk: float
    probabilities: dict[str, float]


@dataclass(frozen=True)
class ModelForecast:
    name: str
    family: str
    status: str
    horizon: int
    expected_return: float | None = None
    lower: float | None = None
    upper: float | None = None
    probability_up: float | None = None
    oos_directional_accuracy: float | None = None
    oos_ic: float | None = None
    oos_mae: float | None = None
    observations: int = 0
    weight: float = 0.0
    note: str = ""


@dataclass(frozen=True)
class EnsembleForecast:
    horizon: int
    expected_return: float
    lower: float
    upper: float
    probability_up: float
    confidence: float
    disagreement: float
    forecasts: tuple[ModelForecast, ...]


@dataclass(frozen=True)
class DecisionTicket:
    action: str
    bias: str
    conviction: float
    thesis: str
    invalidation: str
    entry_low: float | None
    entry_high: float | None
    stop: float | None
    target_1: float | None
    target_2: float | None
    risk_reward: float | None
    suggested_weight: float
    risk_budget: float
    blockers: tuple[str, ...] = ()


@dataclass
class EngineResult:
    ticker: str
    as_of: pd.Timestamp
    price: float
    config: Any
    quality: DataQuality
    frame: pd.DataFrame
    regimes: pd.DataFrame
    regime: RegimeSnapshot
    forecasts: tuple[ModelForecast, ...]
    ensemble: EnsembleForecast
    decision: DecisionTicket
    timeframe_table: pd.DataFrame
    scenario_table: pd.DataFrame
    validation_table: pd.DataFrame
    equity_curve: pd.DataFrame
    audit: dict[str, Any] = field(default_factory=dict)

