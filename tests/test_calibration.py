from __future__ import annotations

import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from monte_carlo.calibration import fit_conditional_volatility


def synthetic_garch(seed: int = 17, n: int = 900) -> np.ndarray:
    rng = np.random.default_rng(seed)
    eps = np.zeros(n)
    h = np.zeros(n)
    h[0] = 0.0001
    for idx in range(1, n):
        h[idx] = 0.000002 + 0.06 * eps[idx - 1] ** 2 + 0.92 * h[idx - 1]
        eps[idx] = np.sqrt(h[idx]) * rng.standard_t(8) / np.sqrt(8 / 6)
    return 0.0002 + eps


def test_garch_calibrations_are_stationary_and_positive():
    returns = synthetic_garch()
    for model in ("GARCH(1,1) normal", "GARCH(1,1) Student-t", "GJR-GARCH Student-t"):
        fit = fit_conditional_volatility(
            returns,
            periods_per_year=252,
            model_name=model,
            maxiter=500,
            min_observations=120,
        )
        assert fit["ok"], (model, fit.get("warning"), fit.get("optimizer_message"))
        assert 0.0 < fit["persistence"] < 0.9995
        assert np.all(np.asarray(fit["conditional_variance"]) > 0.0)
        assert np.isfinite(fit["aic"])
        assert np.isfinite(fit["bic"])
        assert fit["last_vol_ann"] > 0.0
