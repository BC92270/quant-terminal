from __future__ import annotations

import numpy as np
import pandas as pd

from .config import EngineConfig
from .contracts import DataQuality, DecisionTicket, EnsembleForecast, RegimeSnapshot


def build_decision(
    frame: pd.DataFrame,
    ensemble: EnsembleForecast,
    regime: RegimeSnapshot,
    quality: DataQuality,
    config: EngineConfig,
) -> tuple[DecisionTicket, pd.DataFrame]:
    latest = frame.iloc[-1]
    price = float(latest["close"])
    atr = float(latest.get("atr_14")) if np.isfinite(latest.get("atr_14", np.nan)) else price * 0.025
    horizon_vol = float(latest.get("vol_20", 0.30)) * np.sqrt(ensemble.horizon / config.annualisation)
    edge_z = ensemble.expected_return / max(horizon_vol, 1e-4)
    probability_up = ensemble.probability_up
    signed_conviction = float(np.clip(edge_z / 1.5, -1, 1)) * ensemble.confidence

    if probability_up >= 0.57 and ensemble.expected_return > 0:
        bias = "LONG"
    elif probability_up <= 0.43 and ensemble.expected_return < 0:
        bias = "SHORT"
    else:
        bias = "NEUTRAL"

    blockers: list[str] = []
    if quality.quality_score < 65:
        blockers.append("couverture de données dégradée")
    if ensemble.confidence < 0.45:
        blockers.append("confiance ensemble insuffisante")
    if regime.transition_risk > 0.48:
        blockers.append("risque de transition de régime")
    if float(latest.get("noise_score", 0.5)) > 0.76:
        blockers.append("bruit microstructurel / directionnel élevé")
    if ensemble.lower < 0 < ensemble.upper and abs(edge_z) < 0.35:
        blockers.append("intervalle de prévision sans edge directionnel")

    distance_atr = float(np.nan_to_num(latest.get("distance_ema20_atr"), nan=0.0))
    breakout = float(np.nan_to_num(latest.get("breakout_20_atr"), nan=-1.0))
    breakdown = float(np.nan_to_num(latest.get("breakdown_20_atr"), nan=1.0))
    severe_block = quality.quality_score < 50 or ensemble.confidence < 0.30

    if bias == "LONG" and not severe_block:
        if breakout > 0 and distance_atr < 2.6:
            action = "LONG_BREAKOUT"
            thesis = "Cassure confirmée par un ensemble directionnel positif dans un régime compatible."
        elif -0.6 <= distance_atr <= 1.2:
            action = "LONG_PULLBACK"
            thesis = "Repli contrôlé vers la tendance avec asymétrie haussière encore favorable."
        else:
            action = "LONG_WATCH"
            thesis = "Biais haussier, mais le point d’entrée n’est pas encore efficient."
    elif bias == "SHORT" and not severe_block:
        if breakdown < 0 and distance_atr > -2.6:
            action = "SHORT_BREAKDOWN"
            thesis = "Rupture baissière avec consensus directionnel et régime défensif."
        elif -1.2 <= distance_atr <= 0.6:
            action = "SHORT_RALLY_FADE"
            thesis = "Rebond vers la tendance dans une structure baissière encore active."
        else:
            action = "SHORT_WATCH"
            thesis = "Biais baissier, sans fenêtre d’exécution suffisamment propre."
    else:
        action = "NO_TRADE"
        thesis = "Les horizons ou les modèles ne produisent pas une asymétrie exploitable."

    if severe_block:
        action = "NO_TRADE"
        bias = "NEUTRAL"
        thesis = "Signal neutralisé : qualité ou confiance sous le seuil institutionnel."

    if bias == "LONG":
        entry_low = price - 0.55 * atr
        entry_high = price + 0.15 * atr
        stop = min(price - 1.75 * atr, float(np.nan_to_num(latest.get("ema_50"), nan=price)) - 0.55 * atr)
        target_1 = price + 1.6 * atr
        target_2 = price + 2.8 * atr
        invalidation = f"Clôture sous {stop:.2f} ou probabilité Bull trend < 35%."
        stop_distance = max(price - stop, 0.25 * atr)
    elif bias == "SHORT":
        entry_low = price - 0.15 * atr
        entry_high = price + 0.55 * atr
        stop = max(price + 1.75 * atr, float(np.nan_to_num(latest.get("ema_50"), nan=price)) + 0.55 * atr)
        target_1 = price - 1.6 * atr
        target_2 = price - 2.8 * atr
        invalidation = f"Clôture au-dessus de {stop:.2f} ou probabilité Bear trend < 35%."
        stop_distance = max(stop - price, 0.25 * atr)
    else:
        entry_low = entry_high = stop = target_1 = target_2 = None
        invalidation = "Réévaluer après alignement des horizons et réduction du désaccord modèle."
        stop_distance = price

    raw_weight = config.risk_budget / max(stop_distance / price, 1e-4)
    confidence_multiplier = max(0.0, ensemble.confidence * (1 - regime.transition_risk))
    suggested_weight = 0.0 if bias == "NEUTRAL" else float(min(config.max_position_weight, raw_weight) * confidence_multiplier)
    reward = abs((target_1 or price) - price)
    risk_reward = None if bias == "NEUTRAL" else float(reward / max(stop_distance, 1e-8))
    decision = DecisionTicket(
        action=action,
        bias=bias,
        conviction=abs(signed_conviction),
        thesis=thesis,
        invalidation=invalidation,
        entry_low=entry_low,
        entry_high=entry_high,
        stop=stop,
        target_1=target_1,
        target_2=target_2,
        risk_reward=risk_reward,
        suggested_weight=suggested_weight,
        risk_budget=config.risk_budget,
        blockers=tuple(blockers),
    )

    if bias == "SHORT":
        continuation_probability = 1 - probability_up
        signs = -1
    else:
        continuation_probability = probability_up
        signs = 1
    scenarios = pd.DataFrame(
        [
            {
                "Scenario": "Continuation",
                "Probability": float(np.clip(continuation_probability, 0.05, 0.90)),
                "Horizon return": signs * abs(ensemble.expected_return),
                "Reference": target_1,
                "Response": "Scale only after confirmation; trail on EMA20 / ATR.",
            },
            {
                "Scenario": "Range / pullback",
                "Probability": float(np.clip(1 - regime.confidence, 0.08, 0.65)),
                "Horizon return": -signs * min(abs(ensemble.expected_return) * 0.45, horizon_vol * 0.55),
                "Reference": entry_low if bias != "SHORT" else entry_high,
                "Response": "Wait for absorption; avoid adding inside the noise band.",
            },
            {
                "Scenario": "Adverse break",
                "Probability": float(np.clip((1 - continuation_probability) * 0.55 + regime.transition_risk * 0.35, 0.05, 0.65)),
                "Horizon return": -signs * max(abs(ensemble.lower if signs > 0 else ensemble.upper), horizon_vol),
                "Reference": stop,
                "Response": "Respect hard invalidation; no averaging through regime change.",
            },
        ]
    )
    scenarios["Probability"] = scenarios["Probability"] / scenarios["Probability"].sum()
    return decision, scenarios

