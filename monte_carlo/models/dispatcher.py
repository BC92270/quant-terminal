from __future__ import annotations

import math
from typing import Any, Dict, Mapping, Tuple

import numpy as np

from ..config import MAX_HORIZON, MODEL_ALIASES, MODELS, ScenarioParameters
from ..scenarios import _scenario_parameters
from ..utils import _stable_model_seed
from .gbm import gaussian_log_steps, student_t_log_steps
from .bootstrap import historical_bootstrap_log_steps, stationary_bootstrap_log_steps
from .filtered_historical import filtered_historical_log_steps

def simulate_paths_max_horizon(
    base: Mapping[str, Any], scenario: str, model: str, simulations: int, seed: int,
    max_horizon: int = MAX_HORIZON, mean_block_length: int = 10, ewma_lambda: float = 0.94,
) -> Tuple[np.ndarray, ScenarioParameters, Dict[str, Any]]:
    model = MODEL_ALIASES.get(model, model)
    if model not in MODELS:
        raise ValueError(f"Moteur Monte Carlo inconnu : {model}")
    simulations = max(100, int(simulations))
    max_horizon = max(1, int(max_horizon))
    ppy = int(base["periods_per_year"])
    current = float(base["current_price"])
    params = _scenario_parameters(base, scenario, model)
    rng = np.random.default_rng(_stable_model_seed(seed, model))
    paths = np.empty((simulations, max_horizon + 1), dtype=np.float64)
    paths[:, 0] = current
    mu_ann = float(params.drift_ann)
    vol_ann = float(params.vol_ann)
    log_drift_step = (mu_ann - 0.5 * vol_ann**2) / ppy
    log_vol_step = vol_ann / math.sqrt(ppy)
    metadata: Dict[str, Any] = {
        "model": model, "scenario": scenario,
        "supports_bridge": model in {"GBM normal", "Stress volatility"},
        "step_log_variance": float(log_vol_step**2),
        "random_seed": _stable_model_seed(seed, model),
        "student_df": None, "mean_block_length": None, "ewma_lambda": None,
    }
    if model in {"GBM normal", "Stress volatility"}:
        log_steps = gaussian_log_steps(rng, simulations, max_horizon, log_drift_step, log_vol_step)
    elif model == "GBM Student-t calibré":
        log_steps, degrees = student_t_log_steps(rng, simulations, max_horizon, log_drift_step, log_vol_step, float(base["student_df"]))
        metadata["student_df"] = degrees
    elif model == "Historical bootstrap":
        historical = np.asarray(base["log_return_values"], dtype=float)
        log_steps = historical_bootstrap_log_steps(rng, historical, simulations, max_horizon, log_drift_step, scenario == "Stress volatilité")
    elif model == "Stationary bootstrap":
        historical = np.asarray(base["log_return_values"], dtype=float)
        log_steps = stationary_bootstrap_log_steps(rng, historical, simulations, max_horizon, log_drift_step, mean_block_length, scenario == "Stress volatilité")
        metadata["mean_block_length"] = int(mean_block_length)
    elif model == "Filtered historical simulation":
        log_steps, decay = filtered_historical_log_steps(rng, base, simulations, max_horizon, log_drift_step, params.vol_ann, ewma_lambda)
        metadata["ewma_lambda"] = decay
    else:
        raise ValueError(f"Moteur non géré : {model}")
    cumulative = np.cumsum(log_steps, axis=1)
    paths[:, 1:] = current * np.exp(cumulative)
    paths = np.maximum(paths, current * 1e-4)
    return paths, params, metadata

# Compatibility alias used by existing tests and notebooks.
_simulate_paths_max_horizon = simulate_paths_max_horizon
