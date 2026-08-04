from __future__ import annotations

import math
from typing import Any, Dict, Mapping

import numpy as np

from .config import BarrierLevels, EPS
from .utils import _safe_float, _wilson_interval

def _build_levels(
    base: Mapping[str, Any],
    custom_levels: Mapping[str, float] | None = None,
) -> BarrierLevels:
    current = float(base["current_price"])
    df = base["df"]
    close = df["close"].astype(float)
    atr_14 = float(base["atr_14"])

    if custom_levels:
        stop_short = _safe_float(custom_levels.get("stop_short"))
        stop_structural = _safe_float(custom_levels.get("stop_structural"))
        target_1 = _safe_float(custom_levels.get("target_1"))
        target_2 = _safe_float(custom_levels.get("target_2"))

        if all(v is not None and v > 0 for v in (stop_short, stop_structural, target_1, target_2)):
            if not (stop_structural < stop_short < current < target_1 < target_2):
                raise ValueError(
                    "Les niveaux personnalisés doivent respecter : stop structurel < stop court < prix < target 1 < target 2."
                )
            return BarrierLevels(
                current=current,
                stop_short=float(stop_short),
                stop_structural=float(stop_structural),
                target_1=float(target_1),
                target_2=float(target_2),
                source="Niveaux personnalisés",
            )

    low_20 = float(close.tail(min(20, len(close))).min())
    low_60 = float(close.tail(min(60, len(close))).min())
    high_20 = float(close.tail(min(20, len(close))).max())
    high_60 = float(close.tail(min(60, len(close))).max())

    stop_short = max(current - 1.5 * atr_14, low_20 * 0.985)
    stop_structural = min(current - 2.7 * atr_14, low_60 * 0.98)
    target_1 = max(current + 1.5 * atr_14, high_20 * 1.01)
    target_2 = max(current + 2.8 * atr_14, high_60 * 1.025)

    stop_short = min(stop_short, current * 0.985)
    stop_structural = min(stop_structural, stop_short * 0.985)
    target_1 = max(target_1, current * 1.015)
    target_2 = max(target_2, target_1 * 1.02)

    return BarrierLevels(
        current=current,
        stop_short=float(stop_short),
        stop_structural=float(stop_structural),
        target_1=float(target_1),
        target_2=float(target_2),
        source="Automatique ATR + structure 20/60 périodes",
    )


def _first_index(mask: np.ndarray) -> np.ndarray:
    any_hit = mask.any(axis=1)
    return np.where(any_hit, mask.argmax(axis=1) + 1, np.inf)


def _bridge_hit_masks(
    paths: np.ndarray,
    lower: float,
    upper: float,
    step_log_variance: float,
    rng: np.random.Generator,
) -> Tuple[np.ndarray, np.ndarray]:
    """Approximate continuous within-step touches using the Brownian bridge formula.

    The formula is exact for a drifted Brownian motion conditional on step endpoints;
    drift cancels under conditioning. It is therefore restricted to continuous GBM models.
    """
    x0 = np.log(np.maximum(paths[:, :-1], EPS))
    x1 = np.log(np.maximum(paths[:, 1:], EPS))
    lower_log = math.log(lower)
    upper_log = math.log(upper)
    variance = max(float(step_log_variance), 1e-12)

    lower_endpoint = (x0 <= lower_log) | (x1 <= lower_log)
    upper_endpoint = (x0 >= upper_log) | (x1 >= upper_log)

    lower_probability = np.zeros_like(x0)
    both_above = (x0 > lower_log) & (x1 > lower_log)
    lower_probability[both_above] = np.exp(
        -2.0 * (x0[both_above] - lower_log) * (x1[both_above] - lower_log) / variance
    )

    upper_probability = np.zeros_like(x0)
    both_below = (x0 < upper_log) & (x1 < upper_log)
    upper_probability[both_below] = np.exp(
        -2.0 * (upper_log - x0[both_below]) * (upper_log - x1[both_below]) / variance
    )

    lower_probability = np.clip(lower_probability, 0.0, 1.0)
    upper_probability = np.clip(upper_probability, 0.0, 1.0)

    lower_hit = lower_endpoint | (rng.random(x0.shape) < lower_probability)
    upper_hit = upper_endpoint | (rng.random(x0.shape) < upper_probability)
    return lower_hit, upper_hit


def _single_barrier_bridge_mask(
    paths: np.ndarray,
    barrier: float,
    direction: str,
    step_log_variance: float,
    rng: np.random.Generator,
) -> np.ndarray:
    x0 = np.log(np.maximum(paths[:, :-1], EPS))
    x1 = np.log(np.maximum(paths[:, 1:], EPS))
    barrier_log = math.log(barrier)
    variance = max(float(step_log_variance), 1e-12)

    if direction == "lower":
        endpoint = (x0 <= barrier_log) | (x1 <= barrier_log)
        eligible = (x0 > barrier_log) & (x1 > barrier_log)
        probability = np.zeros_like(x0)
        probability[eligible] = np.exp(
            -2.0 * (x0[eligible] - barrier_log) * (x1[eligible] - barrier_log) / variance
        )
    else:
        endpoint = (x0 >= barrier_log) | (x1 >= barrier_log)
        eligible = (x0 < barrier_log) & (x1 < barrier_log)
        probability = np.zeros_like(x0)
        probability[eligible] = np.exp(
            -2.0 * (barrier_log - x0[eligible]) * (barrier_log - x1[eligible]) / variance
        )

    return endpoint | (rng.random(x0.shape) < np.clip(probability, 0.0, 1.0))


def _barrier_events(
    paths: np.ndarray,
    levels: BarrierLevels,
    model_metadata: Mapping[str, Any],
    monitoring: str,
    seed: int,
) -> Dict[str, Any]:
    future = paths[:, 1:]
    use_bridge = (
        monitoring == "Brownian bridge (GBM)"
        and bool(model_metadata.get("supports_bridge"))
        and float(model_metadata.get("step_log_variance", 0.0)) > 0
    )

    if use_bridge:
        rng = np.random.default_rng(int(seed) + 700_001)
        hit_stop, hit_t1 = _bridge_hit_masks(
            paths=paths,
            lower=levels.stop_short,
            upper=levels.target_1,
            step_log_variance=float(model_metadata["step_log_variance"]),
            rng=rng,
        )
        hit_struct = _single_barrier_bridge_mask(
            paths,
            levels.stop_structural,
            "lower",
            float(model_metadata["step_log_variance"]),
            rng,
        )
        hit_t2 = _single_barrier_bridge_mask(
            paths,
            levels.target_2,
            "upper",
            float(model_metadata["step_log_variance"]),
            rng,
        )
        effective_monitoring = "Brownian bridge continu"
    else:
        hit_stop = future <= levels.stop_short
        hit_struct = future <= levels.stop_structural
        hit_t1 = future >= levels.target_1
        hit_t2 = future >= levels.target_2
        effective_monitoring = "Clôture de chaque pas"

    stop_i = _first_index(hit_stop)
    t1_i = _first_index(hit_t1)
    same_day = np.isfinite(stop_i) & np.isfinite(t1_i) & (stop_i == t1_i)
    target_before_stop = np.isfinite(t1_i) & ~same_day & ((t1_i < stop_i) | ~np.isfinite(stop_i))
    stop_before_target = np.isfinite(stop_i) & ~same_day & ((stop_i < t1_i) | ~np.isfinite(t1_i))
    neither = ~np.isfinite(stop_i) & ~np.isfinite(t1_i)

    n = paths.shape[0]

    def probability(mask: np.ndarray) -> float:
        return float(np.mean(mask) * 100.0)

    stop_hits = hit_stop.any(axis=1)
    struct_hits = hit_struct.any(axis=1)
    t1_hits = hit_t1.any(axis=1)
    t2_hits = hit_t2.any(axis=1)

    target_successes = int(target_before_stop.sum())
    stop_successes = int(stop_before_target.sum())
    target_ci = _wilson_interval(target_successes, n)
    stop_ci = _wilson_interval(stop_successes, n)

    finite_stop_days = stop_i[np.isfinite(stop_i)]
    finite_target_days = t1_i[np.isfinite(t1_i)]

    return {
        "prob_hit_stop": probability(stop_hits),
        "prob_hit_structural_stop": probability(struct_hits),
        "prob_hit_target_1": probability(t1_hits),
        "prob_hit_target_2": probability(t2_hits),
        "prob_target_before_stop": probability(target_before_stop),
        "prob_stop_before_target": probability(stop_before_target),
        "prob_same_day_ambiguous": probability(same_day),
        "prob_neither": probability(neither),
        "barrier_asymmetry_pp": probability(target_before_stop) - probability(stop_before_target),
        "target_before_stop_ci": (target_ci[0] * 100.0, target_ci[1] * 100.0),
        "stop_before_target_ci": (stop_ci[0] * 100.0, stop_ci[1] * 100.0),
        "target_before_stop_mask": target_before_stop,
        "stop_before_target_mask": stop_before_target,
        "same_day_mask": same_day,
        "neither_mask": neither,
        "stop_first_day": stop_i,
        "target_first_day": t1_i,
        "median_stop_day": float(np.median(finite_stop_days)) if finite_stop_days.size else float("nan"),
        "median_target_day": float(np.median(finite_target_days)) if finite_target_days.size else float("nan"),
        "effective_monitoring": effective_monitoring,
        "bridge_requested_but_unavailable": monitoring == "Brownian bridge (GBM)" and not use_bridge,
    }
