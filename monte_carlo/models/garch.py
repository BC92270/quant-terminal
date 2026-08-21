from __future__ import annotations

import math
from typing import Any, Mapping

import numpy as np

from ..config import EPS
from ..utils import _clamp


def _standardized_t_shocks(rng: np.random.Generator, degrees: float, size: tuple[int, int]) -> np.ndarray:
    nu = _clamp(float(degrees), 2.10, 60.0)
    shocks = rng.standard_t(df=nu, size=size)
    return shocks / math.sqrt(nu / (nu - 2.0))


def conditional_volatility_log_steps(
    rng: np.random.Generator,
    fit: Mapping[str, Any],
    simulations: int,
    horizon: int,
    drift_ann: float,
    scenario_vol_ann: float,
    historical_vol_ann: float,
    periods_per_year: int,
    empirical_residuals: bool = False,
) -> tuple[np.ndarray, dict[str, Any]]:
    if not fit.get("ok"):
        raise ValueError(f"Calibration conditionnelle indisponible: {fit.get('warning', 'unknown error')}")

    params = fit.get("parameters", {})
    omega = float(params.get("omega", 0.0))
    alpha = float(params.get("alpha", 0.0))
    beta = float(params.get("beta", 0.0))
    gamma = float(params.get("gamma", 0.0) or 0.0)
    degrees = params.get("degrees_of_freedom")

    scale = float(scenario_vol_ann) / max(float(historical_vol_ann), EPS)
    scale = _clamp(scale, 0.10, 10.0)
    variance_scale = scale**2
    omega *= variance_scale
    initial_h = max(float(fit.get("last_variance", 0.0)) * variance_scale, 1e-12)

    residual_history = np.asarray(fit.get("standardized_residuals", []), dtype=float)
    residual_history = residual_history[np.isfinite(residual_history)]
    if empirical_residuals and residual_history.size < 20:
        raise ValueError("Résidus GARCH standardisés insuffisants pour FHS-GARCH.")

    log_steps = np.empty((int(simulations), int(horizon)), dtype=float)
    h_t = np.full(int(simulations), initial_h, dtype=float)
    drift_step = float(drift_ann) / int(periods_per_year)

    if empirical_residuals:
        innovations_z = residual_history[
            rng.integers(0, residual_history.size, size=(int(simulations), int(horizon)))
        ]
        distribution = "Empirical GARCH residuals"
    elif fit.get("distribution") == "Student-t":
        innovations_z = _standardized_t_shocks(
            rng,
            float(degrees or 8.0),
            (int(simulations), int(horizon)),
        )
        distribution = "Student-t"
    else:
        innovations_z = rng.normal(size=(int(simulations), int(horizon)))
        distribution = "Normal"

    for step in range(int(horizon)):
        sigma_t = np.sqrt(np.maximum(h_t, 1e-12))
        epsilon_t = sigma_t * innovations_z[:, step]
        log_steps[:, step] = drift_step - 0.5 * h_t + epsilon_t
        leverage = gamma * epsilon_t**2 * (epsilon_t < 0.0)
        h_t = omega + alpha * epsilon_t**2 + leverage + beta * h_t
        h_t = np.clip(h_t, 1e-12, 25.0)

    metadata = {
        "calibration_model": fit.get("model"),
        "calibration_status": fit.get("status"),
        "calibration_converged": bool(fit.get("converged")),
        "calibration_warning": fit.get("warning", ""),
        "persistence": fit.get("persistence"),
        "degrees_of_freedom": degrees,
        "conditional_distribution": distribution,
        "initial_conditional_vol_ann": math.sqrt(initial_h * int(periods_per_year)),
        "long_run_vol_ann": float(fit.get("long_run_vol_ann", float("nan"))) * scale,
        "volatility_scale": scale,
        "supports_bridge": False,
        "step_log_variance": initial_h,
    }
    return log_steps, metadata
