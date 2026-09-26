"""Transparent distribution stress transforms, never trading instructions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import math
from typing import Iterable

from ..contracts import AvailabilityStatus, ForecastDistribution, as_utc


class ScenarioState(str, Enum):
    EVALUATED = "evaluated"
    WAITING_EVIDENCE = "waiting_evidence"
    UNPRICED = "unpriced"


@dataclass(frozen=True, slots=True)
class ScenarioDefinition:
    scenario_id: str
    label: str
    return_shift: float = 0.0
    volatility_multiplier: float = 1.0
    liquidity_haircut: float = 0.0
    method: str = "deterministic_quantile_stress"
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.scenario_id.strip() or not self.label.strip():
            raise ValueError("Scenario ID and label cannot be empty")
        for name in ("return_shift", "volatility_multiplier", "liquidity_haircut"):
            if not math.isfinite(float(getattr(self, name))):
                raise ValueError(f"{name} must be finite")
        if self.volatility_multiplier <= 0.0:
            raise ValueError("volatility_multiplier must be positive")
        if not 0.0 <= self.liquidity_haircut < 1.0:
            raise ValueError("liquidity_haircut must be in [0, 1)")


@dataclass(frozen=True, slots=True)
class ScenarioAssessment:
    scenario_id: str
    horizon: str
    state: ScenarioState
    as_of: datetime
    base_q05: float | None
    base_q50: float | None
    base_q95: float | None
    stressed_q05: float | None
    stressed_q50: float | None
    stressed_q95: float | None
    stressed_expected_return: float | None
    method: str
    evidence_ids: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of", as_utc(self.as_of))
        values = (
            self.base_q05,
            self.base_q50,
            self.base_q95,
            self.stressed_q05,
            self.stressed_q50,
            self.stressed_q95,
            self.stressed_expected_return,
        )
        if any(value is not None and not math.isfinite(float(value)) for value in values):
            raise ValueError("Scenario values must be finite or null")
        stressed = (self.stressed_q05, self.stressed_q50, self.stressed_q95)
        if all(value is not None for value in stressed) and list(stressed) != sorted(stressed):
            raise ValueError("Stressed scenario quantiles must be monotone")


@dataclass(frozen=True, slots=True)
class RiskEnvelope:
    symbol: str
    as_of: datetime
    assessments: tuple[ScenarioAssessment, ...]
    research_boundary: str = "RESEARCH_ONLY"
    execution_allowed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of", as_utc(self.as_of))
        if self.research_boundary != "RESEARCH_ONLY":
            raise ValueError("Risk envelopes must remain RESEARCH_ONLY")
        if self.execution_allowed:
            raise ValueError("Research risk envelopes cannot authorize execution")


def institutional_research_scenarios() -> tuple[ScenarioDefinition, ...]:
    """Return explicit assumption-only scenarios for deterministic validation."""

    return (
        ScenarioDefinition("BASE_DISTRIBUTION", "Observed empirical distribution"),
        ScenarioDefinition(
            "TAIL_150",
            "Tail width ×1.50",
            volatility_multiplier=1.5,
        ),
        ScenarioDefinition(
            "LIQUIDITY_50",
            "50% liquidity haircut",
            liquidity_haircut=0.5,
        ),
    )


def evaluate_scenarios(
    forecasts: Iterable[ForecastDistribution],
    scenarios: Iterable[ScenarioDefinition],
    *,
    evidence_ids: Iterable[str] = (),
) -> RiskEnvelope:
    forecasts_tuple = tuple(forecasts)
    scenarios_tuple = tuple(scenarios)
    if not forecasts_tuple:
        raise ValueError("At least one forecast is required for a risk envelope")
    if not scenarios_tuple:
        raise ValueError("At least one scenario is required for a risk envelope")
    symbols = {forecast.symbol for forecast in forecasts_tuple}
    if len(symbols) != 1:
        raise ValueError("Risk envelope forecasts must share one symbol")
    as_of = max(forecast.as_of for forecast in forecasts_tuple)
    shared_evidence = tuple(str(item) for item in evidence_ids)
    outputs: list[ScenarioAssessment] = []
    for scenario in scenarios_tuple:
        for forecast in forecasts_tuple:
            base = (forecast.q05, forecast.q50, forecast.q95)
            flags = ["RESEARCH_ONLY", "NO_TRADING_INTERPRETATION"]
            if forecast.provider_status == AvailabilityStatus.SIMULATED:
                flags.append("SIMULATED_INPUT")
            if not scenario.evidence_ids:
                flags.append("ASSUMPTION_ONLY_NO_EMPIRICAL_SENSITIVITY")
            if any(value is None for value in base):
                state = ScenarioState.UNPRICED
                stressed_q05 = stressed_q50 = stressed_q95 = stressed_mean = None
                flags.append("MISSING_FORECAST_QUANTILES")
            else:
                assert forecast.q05 is not None and forecast.q50 is not None and forecast.q95 is not None
                tail_multiplier = scenario.volatility_multiplier / (1.0 - scenario.liquidity_haircut)
                stressed_q50 = forecast.q50 + scenario.return_shift
                stressed_q05 = stressed_q50 + (forecast.q05 - forecast.q50) * tail_multiplier
                stressed_q95 = stressed_q50 + (forecast.q95 - forecast.q50) * tail_multiplier
                stressed_mean = (
                    None
                    if forecast.expected_return is None
                    else forecast.expected_return + scenario.return_shift
                )
                state = ScenarioState.EVALUATED if scenario.evidence_ids else ScenarioState.WAITING_EVIDENCE
            outputs.append(
                ScenarioAssessment(
                    scenario_id=scenario.scenario_id,
                    horizon=forecast.horizon,
                    state=state,
                    as_of=forecast.as_of,
                    base_q05=forecast.q05,
                    base_q50=forecast.q50,
                    base_q95=forecast.q95,
                    stressed_q05=stressed_q05,
                    stressed_q50=stressed_q50,
                    stressed_q95=stressed_q95,
                    stressed_expected_return=stressed_mean,
                    method=scenario.method,
                    evidence_ids=(*shared_evidence, *scenario.evidence_ids),
                    flags=tuple(flags),
                )
            )
    return RiskEnvelope(symbol=next(iter(symbols)), as_of=as_of, assessments=tuple(outputs))
