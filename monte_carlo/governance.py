from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any, Dict, Mapping

import pandas as pd

from .config import ENGINE_VERSION, MODEL_ALIASES, BarrierLevels, MonteCarloSettings
from .utils import _jsonable


def _matrix_diagnostics(
    matrix_df: pd.DataFrame,
    selected_horizon: int,
    selected_scenario: str,
    selected_model: str,
) -> Dict[str, Any]:
    empty = {
        "model_expected_return_range_pp": float("nan"),
        "model_es_range_pp": float("nan"),
        "model_barrier_std_pp": float("nan"),
        "drift_expected_return_sensitivity_pp": float("nan"),
        "drift_barrier_sensitivity_pp": float("nan"),
        "eligible_model_count": 0,
        "warning_model_count": 0,
        "ineligible_model_count": 0,
        "fallback_model_count": 0,
        "aggregation_basis": "NONE",
    }
    if matrix_df.empty:
        return empty

    horizon_df = matrix_df[matrix_df["horizon"] == selected_horizon].copy()
    if horizon_df.empty:
        return empty

    model_status = horizon_df[["model", "eligibility_status"]].drop_duplicates()
    counts = model_status["eligibility_status"].value_counts()
    fallback_count = int(counts.get("FALLBACK", 0))
    warning_count = int(counts.get("WARNING", 0))
    ineligible_count = int(counts.get("INELIGIBLE", 0))
    eligible_count = int(counts.get("ELIGIBLE", 0))

    aggregate_df = horizon_df[horizon_df.get("eligible_for_aggregation", False).astype(bool)].copy()
    aggregation_basis = "ELIGIBLE_ONLY"
    if aggregate_df.empty:
        aggregate_df = horizon_df[horizon_df["eligibility_status"] == "WARNING"].copy()
        aggregation_basis = "WARNING_FALLBACK" if not aggregate_df.empty else "NONE"

    scenario_models = aggregate_df[aggregate_df["scenario"] == selected_scenario]
    if scenario_models.empty:
        model_return_range = model_es_range = model_barrier_std = float("nan")
    else:
        model_return_range = float(
            (scenario_models["expected_return"].max() - scenario_models["expected_return"].min()) * 100.0
        )
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
        "eligible_model_count": eligible_count,
        "warning_model_count": warning_count,
        "ineligible_model_count": ineligible_count,
        "fallback_model_count": fallback_count,
        "aggregation_basis": aggregation_basis,
    }


def _configuration_signature(
    ticker: str,
    base: Mapping[str, Any],
    settings: MonteCarloSettings,
    levels: BarrierLevels,
) -> str:
    quality = base.get("quality", {})
    payload = {
        "engine_version": ENGINE_VERSION,
        "ticker": ticker,
        "settings": asdict(settings),
        "levels": asdict(levels),
        "calibration_source": base.get("calibration_source"),
        "calibration_source_report": base.get("calibration_source_report"),
        "sample_start": str(quality.get("sample_start")),
        "sample_end": str(quality.get("sample_end")),
        "display_rows": int(len(base.get("df", []))),
        "calibration_rows": int(len(base.get("calibration_df", []))),
        "calibration_observations": int(base.get("calibration_observations", 0)),
        "current_price": round(float(base["current_price"]), 8),
    }
    encoded = json.dumps(_jsonable(payload), sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16].upper()
