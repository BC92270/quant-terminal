from __future__ import annotations

from typing import Any, Mapping

import numpy as np

from .config import MODEL_ALIASES, ScenarioParameters


def _scenario_parameters(base: Mapping[str, Any], scenario: str, model: str) -> ScenarioParameters:
    # model is accepted for API compatibility; scenario overlays are model-agnostic in V2.2.
    _ = MODEL_ALIASES.get(model, model)
    historical_drift = float(base["drift_ann"])
    historical_vol = float(base["vol_ann"])

    if scenario == "Historique":
        drift_multiplier = 1.0
        volatility_multiplier = 1.0
        note = "Drift de diffusion historique et niveau de volatilité calibré."
    elif scenario == "Conservateur":
        drift_multiplier = 0.50
        volatility_multiplier = 1.0
        note = "Drift réduit de 50 % ; niveau de volatilité calibré conservé."
    elif scenario == "Neutre":
        drift_multiplier = 0.0
        volatility_multiplier = 1.0
        note = "Drift neutralisé ; niveau de volatilité calibré conservé."
    elif scenario == "Stress volatilité":
        drift_multiplier = 0.25
        volatility_multiplier = 1.35
        note = "Drift plafonné à zéro et niveau de volatilité multiplié par 1,35."
    else:
        drift_multiplier = 0.50
        volatility_multiplier = 1.0
        note = "Scénario inconnu : fallback conservateur."

    drift_ann = historical_drift * drift_multiplier
    vol_ann = historical_vol * volatility_multiplier
    if scenario == "Stress volatilité":
        drift_ann = min(drift_ann, 0.0)

    return ScenarioParameters(
        drift_ann=float(np.clip(drift_ann, -1.50, 3.00)),
        vol_ann=float(np.clip(vol_ann, 0.005, 3.00)),
        drift_multiplier=float(drift_multiplier),
        volatility_multiplier=float(volatility_multiplier),
        note=note,
    )
