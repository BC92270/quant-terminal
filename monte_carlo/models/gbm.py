from __future__ import annotations

import math
import numpy as np

from ..utils import _clamp

def gaussian_log_steps(rng, simulations: int, horizon: int, log_drift_step: float, log_vol_step: float) -> np.ndarray:
    shocks = rng.normal(size=(simulations, horizon))
    return log_drift_step + log_vol_step * shocks

def student_t_log_steps(rng, simulations: int, horizon: int, log_drift_step: float, log_vol_step: float, degrees: float):
    degrees = _clamp(degrees, 4.25, 30.0)
    shocks = rng.standard_t(df=degrees, size=(simulations, horizon))
    shocks = shocks / math.sqrt(degrees / (degrees - 2.0))
    return log_drift_step + log_vol_step * shocks, float(degrees)
