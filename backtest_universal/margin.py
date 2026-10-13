"""Pluggable, point-in-time margin architecture.

The legacy rate model remains available for compatibility.  SPAN, SIMM,
OCC-TIMS and portfolio-margin implementations below are deterministic
*reference* engines: they become useful when versioned parameter packages are
loaded, but never claim clearing-house or broker certification.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
import math
from typing import Mapping, Protocol

from .fx import FXMatrix
from .portfolio import Position
from .types import AssetClass, Instrument


_DEFAULTS: dict[AssetClass, tuple[float, float]] = {
    AssetClass.EQUITY: (0.50, 0.25),
    AssetClass.ETF: (0.50, 0.25),
    AssetClass.FX: (0.0333, 0.0250),
    AssetClass.CRYPTO_SPOT: (1.00, 1.00),
    AssetClass.CRYPTO_PERPETUAL: (0.10, 0.05),
    AssetClass.FUTURE: (0.10, 0.075),
    AssetClass.CFD: (0.20, 0.10),
    AssetClass.RATE: (0.10, 0.075),
    AssetClass.OPTION: (1.00, 1.00),
}


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("timezone-aware timestamp required")
    return value.astimezone(timezone.utc)


class MarginMethod(str, Enum):
    UNIVERSAL_RATE = "UNIVERSAL_RATE"
    SPAN = "SPAN"
    SIMM = "SIMM"
    OCC_TIMS = "OCC_TIMS"
    PORTFOLIO_MARGIN = "PORTFOLIO_MARGIN"


@dataclass(frozen=True)
class MarginParameterSet:
    """Immutable identity and PIT envelope around a provider parameter file."""

    method: MarginMethod
    version: str
    effective_from: datetime
    available_at: datetime
    source: str
    parameters: Mapping[str, object]
    source_sha256: str = ""
    official: bool = False

    def __post_init__(self) -> None:
        version = str(self.version).strip()
        source = str(self.source).strip()
        if not version or not source:
            raise ValueError("margin parameter version and source are required")
        effective = _utc(self.effective_from)
        available = _utc(self.available_at)
        if not isinstance(self.parameters, Mapping) or not self.parameters:
            raise ValueError("margin parameters must be a non-empty mapping")
        canonical = json.dumps(self.parameters, sort_keys=True, default=str).encode("utf-8")
        computed = sha256(canonical).hexdigest()
        supplied = str(self.source_sha256).strip().lower()
        if supplied and (len(supplied) != 64 or any(c not in "0123456789abcdef" for c in supplied)):
            raise ValueError("source_sha256 must be a lowercase SHA-256 digest")
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "effective_from", effective)
        object.__setattr__(self, "available_at", available)
        object.__setattr__(self, "source_sha256", supplied or computed)


class VersionedMarginParameterStore:
    """Select the newest parameter package that was known at simulation time."""

    def __init__(self) -> None:
        self._sets: list[MarginParameterSet] = []

    def register(self, parameter_set: MarginParameterSet) -> None:
        identity = (
            parameter_set.method,
            parameter_set.version,
            parameter_set.effective_from,
            parameter_set.available_at,
        )
        if any(
            (item.method, item.version, item.effective_from, item.available_at) == identity
            for item in self._sets
        ):
            raise ValueError("duplicate margin parameter set")
        self._sets.append(parameter_set)

    def resolve(
        self,
        method: MarginMethod,
        at: datetime,
        *,
        version: str | None = None,
    ) -> MarginParameterSet:
        stamp = _utc(at)
        candidates = [
            item
            for item in self._sets
            if item.method == method
            and item.effective_from <= stamp
            and item.available_at <= stamp
            and (version is None or item.version == version)
        ]
        if not candidates:
            suffix = f" version {version}" if version else ""
            raise LookupError(
                f"DATA REQUIRED: no point-in-time {method.value}{suffix} parameters"
            )
        return max(
            candidates,
            key=lambda item: (item.effective_from, item.available_at, item.version),
        )

    def records(self) -> tuple[MarginParameterSet, ...]:
        return tuple(
            sorted(
                self._sets,
                key=lambda item: (
                    item.method.value,
                    item.effective_from,
                    item.available_at,
                    item.version,
                ),
            )
        )


@dataclass(frozen=True)
class MarginSnapshot:
    equity_base: float
    initial_required_base: float
    maintenance_required_base: float
    initial_excess_base: float
    maintenance_excess_base: float
    gross_notional_base: float
    available: bool
    reasons: tuple[str, ...]
    method: str = MarginMethod.UNIVERSAL_RATE.value
    parameter_version: str | None = None
    parameter_sha256: str | None = None
    certified: bool = False
    reference_model: bool = True
    components: Mapping[str, float] = field(default_factory=dict)

    @property
    def margin_call(self) -> bool:
        return self.available and self.maintenance_excess_base < 0


@dataclass(frozen=True)
class MarginContext:
    equity_base: float
    positions: Mapping[str, Position]
    instruments: Mapping[str, Instrument]
    fx: FXMatrix
    as_of: datetime
    sensitivities: Mapping[str, Mapping[str, float]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of", _utc(self.as_of))


class MarginEngine(Protocol):
    method: MarginMethod

    def calculate(self, context: MarginContext) -> MarginSnapshot: ...


def _position_notional(
    key: str,
    position: Position,
    instruments: Mapping[str, Instrument],
    fx: FXMatrix,
) -> float:
    instrument = instruments[key]
    quote = abs(position.quantity * position.last_price * float(instrument.multiplier))
    return abs(fx.to_base(quote, instrument.quote_currency))


def _gross_notional(context: MarginContext) -> tuple[float, list[str]]:
    gross = 0.0
    reasons: list[str] = []
    for key, position in context.positions.items():
        if not position.quantity:
            continue
        try:
            gross += _position_notional(key, position, context.instruments, context.fx)
        except (KeyError, LookupError, ValueError) as exc:
            reasons.append(f"{key}: notional unavailable ({exc})")
    return gross, reasons


def _snapshot(
    context: MarginContext,
    *,
    method: MarginMethod,
    initial: float,
    maintenance: float,
    gross: float,
    reasons: list[str] | tuple[str, ...] = (),
    parameter_set: MarginParameterSet | None = None,
    components: Mapping[str, float] | None = None,
) -> MarginSnapshot:
    failures = tuple(str(reason) for reason in reasons)
    return MarginSnapshot(
        equity_base=float(context.equity_base),
        initial_required_base=float(initial),
        maintenance_required_base=float(maintenance),
        initial_excess_base=float(context.equity_base - initial),
        maintenance_excess_base=float(context.equity_base - maintenance),
        gross_notional_base=float(gross),
        available=not failures,
        reasons=failures,
        method=method.value,
        parameter_version=parameter_set.version if parameter_set else None,
        parameter_sha256=parameter_set.source_sha256 if parameter_set else None,
        # Reference engines are never certified merely because an official file
        # was loaded.  Certification belongs to a separately validated adapter.
        certified=False,
        reference_model=True,
        components=dict(components or {}),
    )


class UniversalMarginModel:
    """Backward-compatible fixed-rate research margin model."""

    method = MarginMethod.UNIVERSAL_RATE

    def rates(self, instrument: Instrument, quantity: float = 0.0) -> tuple[float, float]:
        default_initial, default_maintenance = _DEFAULTS[instrument.asset_class]
        initial_rate = (
            float(instrument.initial_margin_rate)
            if instrument.initial_margin_rate is not None
            else default_initial
        )
        maintenance_rate = (
            float(instrument.maintenance_margin_rate)
            if instrument.maintenance_margin_rate is not None
            else default_maintenance
        )
        if instrument.asset_class == AssetClass.OPTION and quantity < 0:
            if instrument.initial_margin_rate is None or instrument.maintenance_margin_rate is None:
                raise ValueError("short-option margin requires broker or clearing parameters")
        return initial_rate, maintenance_rate

    def requirements(
        self,
        *,
        equity_base: float,
        positions: Mapping[str, Position],
        instruments: Mapping[str, Instrument],
        fx: FXMatrix,
    ) -> MarginSnapshot:
        initial = 0.0
        maintenance = 0.0
        gross = 0.0
        reasons: list[str] = []
        for symbol, position in positions.items():
            if not position.quantity:
                continue
            try:
                instrument = instruments[symbol]
                notional_base = _position_notional(symbol, position, instruments, fx)
            except (KeyError, LookupError, ValueError) as exc:
                reasons.append(f"{symbol}: notional unavailable ({exc})")
                continue
            gross += notional_base
            try:
                initial_rate, maintenance_rate = self.rates(instrument, position.quantity)
            except ValueError as exc:
                reasons.append(f"{symbol}: {exc}")
                continue
            initial += notional_base * initial_rate
            maintenance += notional_base * maintenance_rate
        context = MarginContext(
            equity_base=equity_base,
            positions=positions,
            instruments=instruments,
            fx=fx,
            as_of=datetime.min.replace(tzinfo=timezone.utc),
        )
        return _snapshot(
            context,
            method=self.method,
            initial=initial,
            maintenance=maintenance,
            gross=gross,
            reasons=reasons,
            components={"rate_margin": initial},
        )

    def calculate(self, context: MarginContext) -> MarginSnapshot:
        return self.requirements(
            equity_base=context.equity_base,
            positions=context.positions,
            instruments=context.instruments,
            fx=context.fx,
        )


class _VersionedReferenceEngine:
    method: MarginMethod

    def __init__(
        self,
        parameter_store: VersionedMarginParameterStore,
        *,
        parameter_version: str | None = None,
    ) -> None:
        self.parameter_store = parameter_store
        self.parameter_version = parameter_version

    def _parameters(self, context: MarginContext) -> MarginParameterSet:
        return self.parameter_store.resolve(
            self.method, context.as_of, version=self.parameter_version
        )

    def requirements(
        self,
        *,
        equity_base: float,
        positions: Mapping[str, Position],
        instruments: Mapping[str, Instrument],
        fx: FXMatrix,
        as_of: datetime,
        sensitivities: Mapping[str, Mapping[str, float]] | None = None,
    ) -> MarginSnapshot:
        return self.calculate(
            MarginContext(
                equity_base=equity_base,
                positions=positions,
                instruments=instruments,
                fx=fx,
                as_of=as_of,
                sensitivities=sensitivities or {},
            )
        )

    def _missing_parameters(self, context: MarginContext, exc: Exception) -> MarginSnapshot:
        gross, gross_reasons = _gross_notional(context)
        return _snapshot(
            context,
            method=self.method,
            initial=0.0,
            maintenance=0.0,
            gross=gross,
            reasons=[*gross_reasons, str(exc)],
        )


class _ScenarioReferenceEngine(_VersionedReferenceEngine):
    """Aggregate full-portfolio scenarios, preserving cross-position offsets."""

    scenario_field = "scenario_shocks"

    def calculate(self, context: MarginContext) -> MarginSnapshot:
        try:
            parameter_set = self._parameters(context)
        except LookupError as exc:
            return self._missing_parameters(context, exc)
        gross, reasons = _gross_notional(context)
        contracts = parameter_set.parameters.get("contracts")
        if not isinstance(contracts, Mapping):
            reasons.append("margin parameter package has no contracts mapping")
            return _snapshot(
                context,
                method=self.method,
                initial=0.0,
                maintenance=0.0,
                gross=gross,
                reasons=reasons,
                parameter_set=parameter_set,
            )
        scenario_totals: list[float] = []
        short_option_minimum = 0.0
        active_positions = 0
        for key, position in context.positions.items():
            if not position.quantity:
                continue
            active_positions += 1
            instrument = context.instruments.get(key)
            specification = contracts.get(key)
            if instrument is None:
                reasons.append(f"{key}: instrument metadata missing")
                continue
            if not isinstance(specification, Mapping):
                reasons.append(f"{key}: {self.method.value} parameters missing")
                continue
            scenarios = specification.get(self.scenario_field)
            if not isinstance(scenarios, (list, tuple)) or not scenarios:
                reasons.append(f"{key}: {self.scenario_field} missing")
                continue
            if scenario_totals and len(scenarios) != len(scenario_totals):
                reasons.append(f"{key}: scenario vector length mismatch")
                continue
            if not scenario_totals:
                scenario_totals = [0.0] * len(scenarios)
            for index, raw_value in enumerate(scenarios):
                try:
                    value = float(raw_value)
                    if not math.isfinite(value):
                        raise ValueError
                    if self.scenario_field == "scenario_shocks":
                        pnl_quote = (
                            position.quantity
                            * position.last_price
                            * float(instrument.multiplier)
                            * value
                        )
                    else:
                        pnl_quote = position.quantity * value
                    scenario_totals[index] += context.fx.to_base(
                        pnl_quote, instrument.quote_currency
                    )
                except (LookupError, TypeError, ValueError):
                    reasons.append(f"{key}: invalid scenario value at index {index}")
                    break
            if instrument.asset_class == AssetClass.OPTION and position.quantity < 0:
                rate = float(specification.get("short_option_min_rate", 0.0) or 0.0)
                short_option_minimum += _position_notional(
                    key, position, context.instruments, context.fx
                ) * max(rate, 0.0)
        if active_positions and not scenario_totals:
            reasons.append("no usable portfolio scenarios")
        worst_loss = max([0.0, *(-value for value in scenario_totals)])
        add_on = float(parameter_set.parameters.get("add_on_base", 0.0) or 0.0)
        maintenance_factor = float(
            parameter_set.parameters.get("maintenance_factor", 1.0) or 1.0
        )
        if not math.isfinite(add_on) or add_on < 0:
            reasons.append("add_on_base must be finite and non-negative")
            add_on = 0.0
        if not math.isfinite(maintenance_factor) or maintenance_factor <= 0:
            reasons.append("maintenance_factor must be finite and positive")
            maintenance_factor = 1.0
        initial = max(worst_loss, short_option_minimum) + add_on
        maintenance = initial * maintenance_factor
        return _snapshot(
            context,
            method=self.method,
            initial=initial,
            maintenance=maintenance,
            gross=gross,
            reasons=reasons,
            parameter_set=parameter_set,
            components={
                "worst_scenario_loss": worst_loss,
                "short_option_minimum": short_option_minimum,
                "add_on": add_on,
            },
        )


class SpanReferenceMarginEngine(_ScenarioReferenceEngine):
    method = MarginMethod.SPAN
    scenario_field = "scenario_shocks"


class OccTimsReferenceMarginEngine(_ScenarioReferenceEngine):
    method = MarginMethod.OCC_TIMS
    scenario_field = "scenario_pnl_per_contract"


class PortfolioMarginReferenceEngine(_ScenarioReferenceEngine):
    method = MarginMethod.PORTFOLIO_MARGIN
    scenario_field = "scenario_shocks"


class SimmReferenceMarginEngine(_VersionedReferenceEngine):
    method = MarginMethod.SIMM

    def calculate(self, context: MarginContext) -> MarginSnapshot:
        try:
            parameter_set = self._parameters(context)
        except LookupError as exc:
            return self._missing_parameters(context, exc)
        gross, reasons = _gross_notional(context)
        risk_weights = parameter_set.parameters.get("risk_weights")
        correlations = parameter_set.parameters.get("correlations", {})
        thresholds = parameter_set.parameters.get("concentration_thresholds", {})
        if not isinstance(risk_weights, Mapping) or not risk_weights:
            reasons.append("SIMM risk_weights are missing")
            risk_weights = {}
        if not isinstance(correlations, Mapping):
            reasons.append("SIMM correlations must be a mapping")
            correlations = {}
        if not isinstance(thresholds, Mapping):
            reasons.append("SIMM concentration_thresholds must be a mapping")
            thresholds = {}

        weighted_by_risk: dict[str, float] = {}
        for key, position in context.positions.items():
            if not position.quantity:
                continue
            vector = context.sensitivities.get(key)
            if not isinstance(vector, Mapping) or not vector:
                reasons.append(f"{key}: point-in-time SIMM sensitivities missing")
                continue
            for raw_risk, raw_sensitivity in vector.items():
                risk = str(raw_risk).strip().upper()
                if risk not in risk_weights:
                    reasons.append(f"{key}: SIMM risk weight missing for {risk}")
                    continue
                try:
                    sensitivity = float(raw_sensitivity)
                    weight = float(risk_weights[risk])
                    threshold = float(thresholds.get(risk, math.inf))
                    if not math.isfinite(sensitivity) or not math.isfinite(weight) or weight < 0:
                        raise ValueError
                    concentration = (
                        max(1.0, math.sqrt(abs(sensitivity) / threshold))
                        if math.isfinite(threshold) and threshold > 0
                        else 1.0
                    )
                    weighted_by_risk[risk] = weighted_by_risk.get(risk, 0.0) + (
                        sensitivity * weight * concentration
                    )
                except (TypeError, ValueError):
                    reasons.append(f"{key}: invalid SIMM sensitivity for {risk}")

        risks = sorted(weighted_by_risk)
        variance = sum(weighted_by_risk[risk] ** 2 for risk in risks)
        for left_index, left in enumerate(risks):
            for right in risks[left_index + 1 :]:
                pair = f"{left}|{right}"
                reverse = f"{right}|{left}"
                correlation = float(correlations.get(pair, correlations.get(reverse, 0.0)) or 0.0)
                if not math.isfinite(correlation) or not -1 <= correlation <= 1:
                    reasons.append(f"SIMM correlation invalid for {pair}")
                    continue
                variance += 2.0 * correlation * weighted_by_risk[left] * weighted_by_risk[right]
        add_on = float(parameter_set.parameters.get("add_on_base", 0.0) or 0.0)
        if not math.isfinite(add_on) or add_on < 0:
            reasons.append("SIMM add_on_base must be finite and non-negative")
            add_on = 0.0
        initial = math.sqrt(max(variance, 0.0)) + add_on
        return _snapshot(
            context,
            method=self.method,
            initial=initial,
            maintenance=initial,
            gross=gross,
            reasons=reasons,
            parameter_set=parameter_set,
            components={
                **{f"weighted_{key.lower()}": abs(value) for key, value in weighted_by_risk.items()},
                "add_on": add_on,
            },
        )


class MarginEngineRegistry:
    """Explicit routing layer for account/clearing-specific margin engines."""

    def __init__(self, engines: tuple[MarginEngine, ...] = ()) -> None:
        self._engines: dict[MarginMethod, MarginEngine] = {}
        for engine in engines:
            self.register(engine)

    def register(self, engine: MarginEngine) -> None:
        if engine.method in self._engines:
            raise ValueError(f"margin engine already registered: {engine.method.value}")
        self._engines[engine.method] = engine

    def get(self, method: MarginMethod) -> MarginEngine:
        try:
            return self._engines[MarginMethod(method)]
        except KeyError as exc:
            raise LookupError(f"margin engine not registered: {method.value}") from exc

    def calculate(self, method: MarginMethod, context: MarginContext) -> MarginSnapshot:
        return self.get(method).calculate(context)

    def methods(self) -> tuple[MarginMethod, ...]:
        return tuple(sorted(self._engines, key=lambda item: item.value))
