from __future__ import annotations

import math
from typing import Any, Dict, Mapping

import numpy as np
import pandas as pd

from .utils import _chi2_survival_1df, _clamp, _normal_ppf, _scipy_chi2

def _kupiec_unconditional_coverage(exceptions: np.ndarray, alpha: float) -> Dict[str, Any]:
    hits = np.asarray(exceptions, dtype=bool)
    n = int(hits.size)
    x = int(hits.sum())
    if n == 0:
        return {"n": 0, "exceptions": 0, "rate": float("nan"), "lr": float("nan"), "p_value": float("nan")}

    p_hat = _clamp(x / n, 1e-12, 1.0 - 1e-12)
    alpha = _clamp(alpha, 1e-12, 1.0 - 1e-12)
    log_l0 = (n - x) * math.log(1.0 - alpha) + x * math.log(alpha)
    log_l1 = (n - x) * math.log(1.0 - p_hat) + x * math.log(p_hat)
    lr = max(0.0, -2.0 * (log_l0 - log_l1))
    return {
        "n": n,
        "exceptions": x,
        "rate": x / n,
        "lr": lr,
        "p_value": _chi2_survival_1df(lr),
    }


def _christoffersen_independence(exceptions: np.ndarray) -> Dict[str, Any]:
    hits = np.asarray(exceptions, dtype=int)
    if hits.size < 2:
        return {"lr": float("nan"), "p_value": float("nan"), "n00": 0, "n01": 0, "n10": 0, "n11": 0}

    previous = hits[:-1]
    current = hits[1:]
    n00 = int(np.sum((previous == 0) & (current == 0)))
    n01 = int(np.sum((previous == 0) & (current == 1)))
    n10 = int(np.sum((previous == 1) & (current == 0)))
    n11 = int(np.sum((previous == 1) & (current == 1)))

    pi01 = n01 / max(n00 + n01, 1)
    pi11 = n11 / max(n10 + n11, 1)
    pi = (n01 + n11) / max(n00 + n01 + n10 + n11, 1)

    def bernoulli_log_likelihood(successes: int, failures: int, probability: float) -> float:
        probability = _clamp(probability, 1e-12, 1.0 - 1e-12)
        return successes * math.log(probability) + failures * math.log(1.0 - probability)

    log_independent = bernoulli_log_likelihood(n01 + n11, n00 + n10, pi)
    log_markov = bernoulli_log_likelihood(n01, n00, pi01) + bernoulli_log_likelihood(n11, n10, pi11)
    lr = max(0.0, -2.0 * (log_independent - log_markov))
    return {
        "lr": lr,
        "p_value": _chi2_survival_1df(lr),
        "n00": n00,
        "n01": n01,
        "n10": n10,
        "n11": n11,
    }


def _baseline_var_validation(base: Mapping[str, Any], alpha: float = 0.05, window: int = 60) -> Dict[str, Any]:
    log_returns = pd.Series(np.asarray(base["log_return_values"], dtype=float))
    if len(log_returns) < window + 20:
        return {
            "ok": False,
            "reason": f"Au moins {window + 20} rendements sont requis pour le backtest VaR roulant.",
        }

    rolling_mean = log_returns.rolling(window).mean().shift(1)
    rolling_std = log_returns.rolling(window).std(ddof=1).shift(1)
    z_alpha = _normal_ppf(alpha)
    forecast_var = rolling_mean + z_alpha * rolling_std
    valid = forecast_var.notna() & log_returns.notna()
    realized = log_returns[valid].to_numpy(dtype=float)
    forecasts = forecast_var[valid].to_numpy(dtype=float)
    exceptions = realized < forecasts

    kupiec = _kupiec_unconditional_coverage(exceptions, alpha)
    christoffersen = _christoffersen_independence(exceptions)
    combined_lr = kupiec["lr"] + christoffersen["lr"]
    combined_p = float(_scipy_chi2.sf(combined_lr, 2)) if _scipy_chi2 is not None else float("nan")

    return {
        "ok": True,
        "method": f"Gaussian rolling {window} periods",
        "alpha": alpha,
        "observations": int(len(realized)),
        "exceptions": int(exceptions.sum()),
        "exception_rate": float(exceptions.mean()),
        "expected_rate": alpha,
        "kupiec_lr": kupiec["lr"],
        "kupiec_p_value": kupiec["p_value"],
        "christoffersen_lr": christoffersen["lr"],
        "christoffersen_p_value": christoffersen["p_value"],
        "conditional_coverage_lr": combined_lr,
        "conditional_coverage_p_value": combined_p,
        "exception_series": exceptions,
        "forecast_var": forecasts,
        "realized_returns": realized,
    }
