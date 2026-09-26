"""Transparent catalyst collision and absorption-state baselines."""

from __future__ import annotations

import math
from typing import Iterable, Mapping

from ..config import (
    ABSORPTION_IMPACT_TREND,
    ABSORPTION_REPLENISHMENT_Z,
    ABSORPTION_SELL_FLOW_Z,
    COLLISION_HIGH,
)
from ..contracts import InteractionAssessment


def collision_metrics(contributions: Iterable[float]) -> dict[str, float]:
    values = [float(value) for value in contributions]
    if any(not math.isfinite(value) for value in values):
        raise ValueError("Catalyst contributions must be finite")
    positive_mass = sum(max(value, 0.0) for value in values)
    negative_mass = sum(abs(min(value, 0.0)) for value in values)
    intensity = positive_mass + negative_mass
    collision = 0.0 if intensity == 0.0 else 2.0 * min(positive_mass, negative_mass) / intensity
    return {
        "positive_mass": positive_mass,
        "negative_mass": negative_mass,
        "net_pressure": positive_mass - negative_mass,
        "intensity": intensity,
        "collision_score": collision,
    }


def assess_interaction(
    contributions: Iterable[float],
    micro: Mapping[str, float | None],
) -> InteractionAssessment:
    contribution_values = [float(value) for value in contributions]
    metrics = collision_metrics(contribution_values)
    net = metrics["net_pressure"]
    collision = metrics["collision_score"]
    required_micro = (
        "sell_flow_z",
        "bid_replenishment_z",
        "sell_impact_trend",
        "spread_change_z",
        "microstructure_pressure",
    )
    missing = tuple(name for name in required_micro if micro.get(name) is None)
    invalid = tuple(
        name
        for name in required_micro
        if micro.get(name) is not None and not math.isfinite(float(micro[name]))
    )
    if not contribution_values or missing or invalid:
        flags = []
        if not contribution_values:
            flags.append("NO_CATALYST_CONTRIBUTIONS")
        if missing:
            flags.append("MISSING_MICRO_INPUTS:" + ",".join(missing))
        if invalid:
            flags.append("INVALID_MICRO_INPUTS:" + ",".join(invalid))
        return InteractionAssessment(
            state="unexplained_information_flow",
            catalyst_pressure=net,
            microstructure_pressure=0.0,
            collision_score=collision,
            intensity=metrics["intensity"],
            explanation=(
                "The catalyst × microstructure state is invalid because required "
                "point-in-time sensor inputs are missing or non-finite."
            ),
            evidence=tuple(flags),
            confidence="INVALID",
            validation_flags=tuple(flags),
        )

    sell_flow = float(micro["sell_flow_z"])
    replenishment = float(micro["bid_replenishment_z"])
    impact_trend = float(micro["sell_impact_trend"])
    spread_change = float(micro["spread_change_z"])
    micro_pressure = float(micro["microstructure_pressure"])

    absorption = (
        net < 0.0
        and sell_flow <= ABSORPTION_SELL_FLOW_Z
        and replenishment >= ABSORPTION_REPLENISHMENT_Z
        and impact_trend <= ABSORPTION_IMPACT_TREND
        and spread_change < 1.0
    )
    if absorption:
        state = "negative_catalyst_absorption"
        explanation = (
            "Negative catalyst pressure is present, while marginal sell impact is "
            "falling and displayed bid replenishment is rising."
        )
        evidence = (
            f"sell flow z {sell_flow:+.2f}",
            f"bid replenishment z {replenishment:+.2f}",
            f"sell-impact trend {impact_trend:+.2f}",
            f"spread change z {spread_change:+.2f}",
        )
        confidence = "MEDIUM"
    elif collision >= COLLISION_HIGH and metrics["intensity"] > 0.0:
        state = "collision_instability"
        explanation = "Large opposing catalyst masses coexist; direction is weak and uncertainty is elevated."
        evidence = (f"collision {collision:.0%}", f"net catalyst pressure {net:+.2f}")
        confidence = "MEDIUM"
    elif net > 0.0 and micro_pressure > 0.0:
        state = "positive_confirmation"
        explanation = "Positive catalyst pressure and measured market absorption state point in the same direction."
        evidence = (f"net catalyst pressure {net:+.2f}", f"micro pressure {micro_pressure:+.2f}")
        confidence = "LOW"
    elif net < 0.0 and micro_pressure < 0.0:
        state = "negative_confirmation"
        explanation = "Negative catalyst pressure is confirmed by the measured microstructure state."
        evidence = (f"net catalyst pressure {net:+.2f}", f"micro pressure {micro_pressure:+.2f}")
        confidence = "LOW"
    elif net > 0.0 and micro_pressure < 0.0:
        state = "catalyst_rejection"
        explanation = "Positive catalyst pressure is not confirmed by current market absorption measures."
        evidence = (f"net catalyst pressure {net:+.2f}", f"micro pressure {micro_pressure:+.2f}")
        confidence = "LOW"
    elif net >= 0.0:
        state = "positive_weak_confirmation"
        explanation = "Positive catalyst pressure has only weak microstructure confirmation."
        evidence = (f"net catalyst pressure {net:+.2f}",)
        confidence = "LOW"
    else:
        state = "negative_weak_confirmation"
        explanation = "Negative catalyst pressure has only weak microstructure confirmation."
        evidence = (f"net catalyst pressure {net:+.2f}",)
        confidence = "LOW"

    return InteractionAssessment(
        state=state,
        catalyst_pressure=net,
        microstructure_pressure=micro_pressure,
        collision_score=collision,
        intensity=metrics["intensity"],
        explanation=explanation,
        evidence=evidence,
        confidence=confidence,
    )
