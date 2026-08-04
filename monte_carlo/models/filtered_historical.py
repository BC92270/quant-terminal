from __future__ import annotations

import math
import numpy as np

from ..config import EPS
from ..utils import _clamp

def filtered_historical_log_steps(rng, base, simulations, horizon, target_mean_step, params_vol_ann, ewma_lambda):
    residuals = np.asarray(base["standardized_residuals"], dtype=float)
    if residuals.size < 20:
        residuals = np.asarray(base["log_return_values"], dtype=float)
        residuals = residuals - residuals.mean()
        residual_std = residuals.std(ddof=1)
        residuals = residuals / residual_std if residual_std > EPS else residuals
    sampled_residuals = residuals[rng.integers(0, len(residuals), size=(simulations, horizon))]
    decay = _clamp(ewma_lambda, 0.50, 0.999)
    ppy = int(base["periods_per_year"])
    initial_sigma = float(base["ewma_vol_ann"]) / math.sqrt(ppy)
    initial_sigma = max(initial_sigma * (params_vol_ann / max(float(base["vol_ann"]), EPS)), 1e-6)
    log_steps = np.empty((simulations, horizon), dtype=np.float64)
    sigma_t = np.full(simulations, initial_sigma, dtype=np.float64)
    for step in range(horizon):
        innovation = sigma_t * sampled_residuals[:, step]
        step_return = target_mean_step + innovation
        log_steps[:, step] = step_return
        sigma_t = np.sqrt(decay * sigma_t**2 + (1.0 - decay) * innovation**2)
    return log_steps, float(decay)
