from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any, Dict, Mapping

import pandas as pd

from .config import ENGINE_VERSION, MODEL_ALIASES, BarrierLevels, MonteCarloSettings
from .utils import _jsonable

def _matrix_diagnostics(matrix_df: pd.DataFrame, selected_horizon: int, selected_scenario: str, selected_model: str) -> Dict[str, Any]:
    if matrix_df.empty:
        return {
            "model_expected_return_range_pp": float("nan"),
            "model_es_range_pp": float("nan"),
            "model_barrier_std_pp": float("nan"),
            "drift_expected_return_sensitivity_pp": float("nan"),
            "drift_barrier_sensitivity_pp": float("nan"),
        }

    horizon_df = matrix_df[matrix_df["horizon"] == selected_horizon].copy()
    scenario_models = horizon_df[horizon_df["scenario"] == selected_scenario]

    if scenario_models.empty:
        model_return_range = model_es_range = model_barrier_std = float("nan")
    else:
        model_return_range = float((scenario_models["expected_return"].max() - scenario_models["expected_return"].min()) * 100.0)
        model_es_range = float((scenario_models["es_5"].max() - scenario_models["es_5"].min()) * 100.0)
        model_barrier_std = float(scenario_models["barrier_asymmetry_pp"].std(ddof=0))

    selected_model = MODEL_ALIASES.get(selected_model, selected_model)
    model_df = horizon_df[horizon_df["model"] == selected_model]
    historical = model_df[model_df["scenario"] == "Historique"]
    neutral = model_df[model_df["scenario"] == "Neutre"]

    if historical.empty or neutral.empty:
        drift_return_sensitivity = drift_barrier_sensitivity = float("nan")
    else:
        drift_return_sensitivity = float(
            (historical["expected_return"].iloc[0] - neutral["expected_return"].iloc[0]) * 100.0
        )
        drift_barrier_sensitivity = float(
            historical["barrier_asymmetry_pp"].iloc[0] - neutral["barrier_asymmetry_pp"].iloc[0]
        )

    return {
        "model_expected_return_range_pp": model_return_range,
        "model_es_range_pp": model_es_range,
        "model_barrier_std_pp": model_barrier_std,
        "drift_expected_return_sensitivity_pp": drift_return_sensitivity,
        "drift_barrier_sensitivity_pp": drift_barrier_sensitivity,
    }


def _configuration_signature(
    ticker: str,
    base: Mapping[str, Any],
    settings: MonteCarloSettings,
    levels: BarrierLevels,
) -> str:
    payload = {
        "engine_version": ENGINE_VERSION,
        "ticker": ticker,
        "settings": asdict(settings),
        "levels": asdict(levels),
        "sample_start": str(base["quality"].get("sample_start")),
        "sample_end": str(base["quality"].get("sample_end")),
        "rows": int(len(base["df"])),
        "current_price": round(float(base["current_price"]), 8),
    }
    encoded = json.dumps(_jsonable(payload), sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16].upper()
