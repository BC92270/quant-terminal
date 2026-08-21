from __future__ import annotations

from dataclasses import replace

import numpy as np

from .contracts import EnsembleForecast, ModelForecast, RegimeSnapshot


def _base_reliability(forecast: ModelForecast) -> float:
    if forecast.status != "READY" or forecast.expected_return is None:
        return 0.0
    accuracy = forecast.oos_directional_accuracy
    accuracy_component = 0.55 if accuracy is None else float(np.clip(0.35 + 2.5 * (accuracy - 0.45), 0.15, 1.0))
    sample_component = float(np.clip(forecast.observations / 80, 0.25, 1.0))
    ic = forecast.oos_ic
    ic_component = 0.70 if ic is None else float(np.clip(0.65 + ic, 0.25, 1.15))
    return accuracy_component * sample_component * ic_component


def combine_forecasts(
    forecasts: tuple[ModelForecast, ...],
    regime: RegimeSnapshot,
    quality_score: float,
) -> EnsembleForecast:
    regime_key = max(regime.probabilities, key=regime.probabilities.get)
    raw_weights: list[float] = []
    for forecast in forecasts:
        weight = _base_reliability(forecast)
        name = forecast.name.lower()
        if regime_key in {"BULL_TREND", "BEAR_TREND"}:
            if "momentum" in name or "kalman" in name or "ridge" in name:
                weight *= 1.18
        elif regime_key == "RANGE":
            if "ar(1)" in name:
                weight *= 1.25
            if "momentum" in name or "kalman" in name:
                weight *= 0.70
        elif regime_key == "STRESS":
            weight *= 0.70
            if forecast.family == "Neural":
                weight *= 0.60
        raw_weights.append(weight)

    total = sum(raw_weights)
    if total <= 0:
        ready = [forecast for forecast in forecasts if forecast.status == "READY" and forecast.expected_return is not None]
        if not ready:
            return EnsembleForecast(1, 0.0, -0.01, 0.01, 0.5, 0.0, 1.0, forecasts)
        raw_weights = [1.0 if forecast in ready else 0.0 for forecast in forecasts]
        total = sum(raw_weights)
    weights = np.asarray(raw_weights, dtype=float) / total
    weighted = tuple(replace(forecast, weight=float(weight)) for forecast, weight in zip(forecasts, weights))

    means = np.array([forecast.expected_return or 0.0 for forecast in weighted], dtype=float)
    expected = float(np.dot(weights, means))
    probabilities = np.array([forecast.probability_up if forecast.probability_up is not None else 0.5 for forecast in weighted])
    probability_up = float(np.dot(weights, probabilities))
    model_sigmas = np.array(
        [
            max(((forecast.upper or 0) - (forecast.lower or 0)) / (2 * 1.2815515655), 1e-5)
            if forecast.status == "READY"
            else 0.0
            for forecast in weighted
        ]
    )
    mixture_variance = float(np.dot(weights, np.square(model_sigmas) + np.square(means - expected)))
    sigma = max(float(np.sqrt(max(mixture_variance, 1e-10))), 0.002)
    disagreement = float(np.sqrt(np.dot(weights, np.square(means - expected))))

    if regime_key == "STRESS":
        expected *= 0.65
        probability_up = 0.5 + (probability_up - 0.5) * 0.70
        sigma *= 1.20

    direction = np.sign(expected) if abs(expected) > 1e-9 else 1.0
    agreement = float(np.dot(weights, (np.sign(means) == direction).astype(float)))
    sample_depth = float(np.dot(weights, np.clip([forecast.observations / 80 for forecast in weighted], 0.2, 1.0)))
    confidence = float(
        np.clip(
            (quality_score / 100)
            * (0.40 + 0.60 * regime.confidence)
            * (0.35 + 0.65 * agreement)
            * (0.45 + 0.55 * sample_depth),
            0,
            1,
        )
    )
    horizon = next((forecast.horizon for forecast in weighted if forecast.status == "READY"), 1)
    return EnsembleForecast(
        horizon=horizon,
        expected_return=expected,
        lower=expected - 1.2815515655 * sigma,
        upper=expected + 1.2815515655 * sigma,
        probability_up=float(np.clip(probability_up, 0.01, 0.99)),
        confidence=confidence,
        disagreement=disagreement,
        forecasts=weighted,
    )

