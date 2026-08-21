from __future__ import annotations

import math
import hashlib
from collections import OrderedDict
from typing import Any, Dict, Mapping

import numpy as np
import pandas as pd

from .config import CONDITIONAL_MODEL_NAMES, EPS
from .utils import _moment_excess_kurtosis, _moment_skew

_CALIBRATION_CACHE: "OrderedDict[tuple[str, int, int, int, bool], Dict[str, Dict[str, Any]]]" = OrderedDict()
_CALIBRATION_CACHE_MAXSIZE = 8


try:  # scipy is already part of the project requirements, but keep a safe fallback.
    from scipy.optimize import minimize
    from scipy.special import gammaln
    from scipy.signal import lfilter
except Exception:  # pragma: no cover - exercised only in degraded environments
    minimize = None
    gammaln = None
    lfilter = None


def _variance_recursion(
    values_pct: np.ndarray,
    mu_pct: float,
    omega: float,
    alpha: float,
    beta: float,
    gamma: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Return conditional variances and residuals in percentage-point units."""
    y = np.asarray(values_pct, dtype=float)
    eps = y - float(mu_pct)
    n = y.size
    h = np.empty(n, dtype=float)
    sample_var = float(np.var(eps, ddof=1)) if n > 1 else float(eps[0] ** 2)
    h0 = max(sample_var, 1e-8)
    h[0] = h0

    if n > 1 and lfilter is not None:
        previous_sq = eps[:-1] ** 2
        leverage = gamma * previous_sq * (eps[:-1] < 0.0)
        forcing = omega + alpha * previous_sq + leverage
        filtered, _ = lfilter([1.0], [1.0, -beta], forcing, zi=[beta * h0])
        h[1:] = filtered
        h = np.maximum(np.where(np.isfinite(h), h, 1e-12), 1e-12)
        return h, eps

    for idx in range(1, n):
        previous_eps = eps[idx - 1]
        leverage = gamma * previous_eps**2 if previous_eps < 0.0 else 0.0
        h[idx] = omega + alpha * previous_eps**2 + leverage + beta * h[idx - 1]
        if not np.isfinite(h[idx]) or h[idx] <= 1e-12:
            h[idx] = 1e-12
    return h, eps


def _student_log_density_standardized(z: np.ndarray, degrees: float) -> np.ndarray:
    """Log-density of a Student-t standardized to unit variance."""
    nu = float(degrees)
    if gammaln is None or nu <= 2.0:
        return np.full_like(z, -np.inf, dtype=float)
    constant = (
        gammaln((nu + 1.0) / 2.0)
        - gammaln(nu / 2.0)
        - 0.5 * math.log((nu - 2.0) * math.pi)
    )
    return constant - 0.5 * (nu + 1.0) * np.log1p((z**2) / (nu - 2.0))


def _negative_log_likelihood(
    theta: np.ndarray,
    values_pct: np.ndarray,
    asymmetric: bool,
    student_t: bool,
) -> float:
    if asymmetric and student_t:
        mu, omega, alpha, gamma, beta, degrees = theta
    elif student_t:
        mu, omega, alpha, beta, degrees = theta
        gamma = 0.0
    else:
        mu, omega, alpha, beta = theta
        gamma = 0.0
        degrees = float("nan")

    persistence = alpha + beta + 0.5 * gamma
    if omega <= 0.0 or alpha < 0.0 or beta < 0.0 or gamma < 0.0 or persistence >= 0.9995:
        return 1e12 + 1e9 * max(persistence - 0.9995, 0.0) ** 2
    if student_t and (degrees <= 2.05 or degrees > 100.0):
        return 1e12

    h, eps = _variance_recursion(values_pct, mu, omega, alpha, beta, gamma)
    if np.any(~np.isfinite(h)) or np.any(h <= 0.0):
        return 1e12

    z = eps / np.sqrt(h)
    if student_t:
        log_density = _student_log_density_standardized(z, degrees) - 0.5 * np.log(h)
        if np.any(~np.isfinite(log_density)):
            return 1e12
        return float(-np.sum(log_density))

    nll = 0.5 * np.sum(math.log(2.0 * math.pi) + np.log(h) + eps**2 / h)
    return float(nll) if np.isfinite(nll) else 1e12


def _initial_candidates(values_pct: np.ndarray, asymmetric: bool, student_t: bool) -> list[np.ndarray]:
    mu = float(np.mean(values_pct))
    variance = max(float(np.var(values_pct - mu, ddof=1)), 1e-6)
    candidates: list[np.ndarray] = []
    base_pairs = ((0.05, 0.90), (0.10, 0.80), (0.03, 0.94), (0.15, 0.70))

    for alpha, beta in base_pairs:
        gamma = 0.05 if asymmetric else 0.0
        persistence = alpha + beta + 0.5 * gamma
        omega = max(variance * (1.0 - persistence), 1e-6)
        if asymmetric and student_t:
            candidates.append(np.array([mu, omega, alpha, gamma, beta, 8.0], dtype=float))
        elif student_t:
            candidates.append(np.array([mu, omega, alpha, beta, 8.0], dtype=float))
        else:
            candidates.append(np.array([mu, omega, alpha, beta], dtype=float))
    return candidates


def _bounds(values_pct: np.ndarray, asymmetric: bool, student_t: bool) -> list[tuple[float, float]]:
    scale = max(float(np.std(values_pct, ddof=1)), 0.1)
    mean_bound = max(5.0, 5.0 * scale)
    variance = max(float(np.var(values_pct, ddof=1)), 1e-4)
    omega_upper = max(10.0 * variance, 1.0)

    result: list[tuple[float, float]] = [
        (-mean_bound, mean_bound),
        (1e-10, omega_upper),
        (1e-8, 0.60),
    ]
    if asymmetric:
        result.append((0.0, 0.80))
    result.append((1e-8, 0.999))
    if student_t:
        result.append((2.10, 60.0))
    return result


def fit_conditional_volatility(
    log_returns: np.ndarray,
    periods_per_year: int,
    model_name: str,
    maxiter: int = 800,
    min_observations: int = 120,
) -> Dict[str, Any]:
    """Fit GARCH/GJR-GARCH by maximum likelihood.

    The optimizer works on returns expressed in percentage points for numerical
    stability. Returned variances and means are converted back to decimal units.
    """
    raw = np.asarray(log_returns, dtype=float)
    raw = raw[np.isfinite(raw)]
    n = int(raw.size)
    asymmetric = model_name == "GJR-GARCH Student-t"
    student_t = model_name in {"GARCH(1,1) Student-t", "GJR-GARCH Student-t"}

    empty: Dict[str, Any] = {
        "model": model_name,
        "ok": False,
        "converged": False,
        "status": "FAILED",
        "warning": "",
        "observations": n,
        "parameters": {},
        "conditional_variance": np.array([], dtype=float),
        "standardized_residuals": np.array([], dtype=float),
    }

    if n < max(60, int(min_observations)):
        empty["warning"] = (
            f"Échantillon insuffisant pour {model_name}: {n} observations, "
            f"minimum configuré {max(60, int(min_observations))}."
        )
        empty["status"] = "INSUFFICIENT_SAMPLE"
        return empty
    if minimize is None:
        empty["warning"] = "scipy.optimize indisponible : calibration GARCH impossible."
        empty["status"] = "SCIPY_UNAVAILABLE"
        return empty

    values_pct = raw * 100.0
    best = None
    best_value = float("inf")
    bounds = _bounds(values_pct, asymmetric, student_t)

    for initial in _initial_candidates(values_pct, asymmetric, student_t):
        try:
            result = minimize(
                _negative_log_likelihood,
                initial,
                args=(values_pct, asymmetric, student_t),
                method="L-BFGS-B",
                bounds=bounds,
                options={"maxiter": int(maxiter), "ftol": 1e-11, "gtol": 1e-7, "maxls": 50},
            )
        except Exception:
            continue
        if np.isfinite(result.fun) and float(result.fun) < best_value:
            best = result
            best_value = float(result.fun)

    if best is None:
        empty["warning"] = "Aucune optimisation GARCH exploitable."
        empty["status"] = "OPTIMIZATION_FAILED"
        return empty

    theta = np.asarray(best.x, dtype=float)
    if asymmetric and student_t:
        mu_pct, omega_pct2, alpha, gamma, beta, degrees = theta
    elif student_t:
        mu_pct, omega_pct2, alpha, beta, degrees = theta
        gamma = 0.0
    else:
        mu_pct, omega_pct2, alpha, beta = theta
        gamma = 0.0
        degrees = float("nan")

    persistence = float(alpha + beta + 0.5 * gamma)
    h_pct2, eps_pct = _variance_recursion(values_pct, mu_pct, omega_pct2, alpha, beta, gamma)
    h_decimal = h_pct2 / 10_000.0
    eps_decimal = eps_pct / 100.0
    standardized = eps_decimal / np.sqrt(np.maximum(h_decimal, EPS))
    standardized = standardized[np.isfinite(standardized)]
    if standardized.size:
        standardized = standardized - standardized.mean()
        std = float(standardized.std(ddof=1)) if standardized.size > 1 else 1.0
        if std > EPS:
            standardized = standardized / std

    log_likelihood = -best_value
    parameter_count = int(theta.size)
    aic = 2.0 * parameter_count - 2.0 * log_likelihood
    bic = math.log(max(n, 1)) * parameter_count - 2.0 * log_likelihood
    long_run_var_pct2 = omega_pct2 / max(1.0 - persistence, 1e-8)
    long_run_var_decimal = long_run_var_pct2 / 10_000.0
    last_var = float(h_decimal[-1])
    last_vol_ann = math.sqrt(max(last_var, 0.0) * periods_per_year)
    long_run_vol_ann = math.sqrt(max(long_run_var_decimal, 0.0) * periods_per_year)

    stationarity_ok = persistence < 0.9995
    optimizer_ok = bool(best.success)
    converged = optimizer_ok and stationarity_ok and np.isfinite(best_value)
    warning_parts: list[str] = []
    if not optimizer_ok:
        warning_parts.append(str(getattr(best, "message", "optimizer did not report success")))
    if not stationarity_ok:
        warning_parts.append("persistence non stationnaire")
    if persistence > 0.985:
        warning_parts.append("persistence très élevée")
    if student_t and degrees <= 2.25:
        warning_parts.append("degrés de liberté proches de la frontière de variance")

    status = "PASS" if converged and not warning_parts else ("WARNING" if np.isfinite(best_value) else "FAILED")
    parameters = {
        "mu_period": float(mu_pct / 100.0),
        "omega": float(omega_pct2 / 10_000.0),
        "alpha": float(alpha),
        "beta": float(beta),
        "gamma": float(gamma),
        "degrees_of_freedom": float(degrees) if student_t else None,
    }

    return {
        "model": model_name,
        "ok": bool(np.isfinite(best_value) and stationarity_ok),
        "converged": converged,
        "status": status,
        "warning": "; ".join(warning_parts),
        "optimizer_message": str(getattr(best, "message", "")),
        "optimizer_iterations": int(getattr(best, "nit", 0) or 0),
        "observations": n,
        "parameters": parameters,
        "persistence": persistence,
        "log_likelihood": float(log_likelihood),
        "aic": float(aic),
        "bic": float(bic),
        "last_variance": last_var,
        "last_vol_ann": float(last_vol_ann),
        "long_run_variance": float(long_run_var_decimal),
        "long_run_vol_ann": float(long_run_vol_ann),
        "conditional_variance": h_decimal,
        "residuals": eps_decimal,
        "standardized_residuals": standardized,
        "residual_skewness": float(_moment_skew(standardized)) if standardized.size else float("nan"),
        "residual_excess_kurtosis": float(_moment_excess_kurtosis(standardized)) if standardized.size else float("nan"),
        "distribution": "Student-t" if student_t else "Normal",
        "asymmetric": asymmetric,
    }


def _fit_stability_diagnostic(
    full_fit: Mapping[str, Any],
    returns: np.ndarray,
    periods_per_year: int,
    model_name: str,
    maxiter: int,
    min_observations: int,
) -> Dict[str, Any]:
    n = int(len(returns))
    required = max(500, int(min_observations) * 2)
    if n < required:
        return {
            "status": "NOT_RUN",
            "warning": f"stability check requires at least {required} observations",
            "full_observations": n,
            "trailing_observations": 0,
        }

    trailing_n = max(int(min_observations), int(round(n * 0.70)))
    trailing = np.asarray(returns[-trailing_n:], dtype=float)
    trailing_fit = fit_conditional_volatility(
        trailing,
        periods_per_year=periods_per_year,
        model_name=model_name,
        maxiter=min(int(maxiter), 500),
        min_observations=min_observations,
    )
    if not trailing_fit.get("ok"):
        return {
            "status": "FAILED",
            "warning": str(trailing_fit.get("warning") or "trailing-window fit unavailable"),
            "full_observations": n,
            "trailing_observations": trailing_n,
        }

    full_p = float(full_fit.get("persistence", float("nan")))
    trailing_p = float(trailing_fit.get("persistence", float("nan")))
    full_vol = float(full_fit.get("last_vol_ann", float("nan")))
    trailing_vol = float(trailing_fit.get("last_vol_ann", float("nan")))
    persistence_delta = abs(full_p - trailing_p) if np.isfinite(full_p) and np.isfinite(trailing_p) else float("nan")
    vol_ratio = trailing_vol / full_vol if np.isfinite(full_vol) and full_vol > 0 and np.isfinite(trailing_vol) else float("nan")

    warning_parts: list[str] = []
    if np.isfinite(persistence_delta) and persistence_delta > 0.15:
        warning_parts.append(f"persistence delta {persistence_delta:.3f}")
    if np.isfinite(vol_ratio) and not 0.50 <= vol_ratio <= 2.00:
        warning_parts.append(f"conditional-vol ratio {vol_ratio:.2f}")

    status = "WARNING" if warning_parts else "PASS"
    return {
        "status": status,
        "warning": "; ".join(warning_parts),
        "full_observations": n,
        "trailing_observations": trailing_n,
        "full_persistence": full_p,
        "trailing_persistence": trailing_p,
        "persistence_delta": persistence_delta,
        "full_last_vol_ann": full_vol,
        "trailing_last_vol_ann": trailing_vol,
        "last_vol_ratio": vol_ratio,
    }


def fit_conditional_model_set(
    base: Mapping[str, Any],
    maxiter: int = 800,
    min_observations: int = 120,
    stability_check: bool = True,
) -> Dict[str, Dict[str, Any]]:
    returns = np.ascontiguousarray(np.asarray(base["log_return_values"], dtype=np.float64))
    periods_per_year = int(base["periods_per_year"])
    digest = hashlib.sha256(returns.tobytes()).hexdigest()
    cache_key = (digest, periods_per_year, int(maxiter), int(min_observations), bool(stability_check))
    cached = _CALIBRATION_CACHE.get(cache_key)
    if cached is not None:
        _CALIBRATION_CACHE.move_to_end(cache_key)
        return cached

    fitted: Dict[str, Dict[str, Any]] = {}
    for name in CONDITIONAL_MODEL_NAMES:
        fit = fit_conditional_volatility(
            returns,
            periods_per_year=periods_per_year,
            model_name=name,
            maxiter=maxiter,
            min_observations=min_observations,
        )
        fit["stability"] = (
            _fit_stability_diagnostic(
                fit, returns, periods_per_year, name, maxiter, min_observations
            )
            if stability_check and fit.get("ok")
            else {"status": "NOT_RUN", "warning": "stability check disabled or full fit unavailable"}
        )
        fitted[name] = fit

    _CALIBRATION_CACHE[cache_key] = fitted
    _CALIBRATION_CACHE.move_to_end(cache_key)
    while len(_CALIBRATION_CACHE) > _CALIBRATION_CACHE_MAXSIZE:
        _CALIBRATION_CACHE.popitem(last=False)
    return fitted

def conditional_calibration_table(calibrations: Mapping[str, Mapping[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for name in CONDITIONAL_MODEL_NAMES:
        fit = calibrations.get(name, {})
        params = fit.get("parameters", {}) if isinstance(fit, Mapping) else {}
        rows.append(
            {
                "Model": name,
                "Status": fit.get("status", "NOT_RUN"),
                "N": fit.get("observations", 0),
                "Omega": params.get("omega"),
                "Alpha": params.get("alpha"),
                "Beta": params.get("beta"),
                "Gamma": params.get("gamma"),
                "Nu": params.get("degrees_of_freedom"),
                "Persistence": fit.get("persistence"),
                "Last vol ann.": fit.get("last_vol_ann"),
                "Long-run vol ann.": fit.get("long_run_vol_ann"),
                "Log-likelihood": fit.get("log_likelihood"),
                "AIC": fit.get("aic"),
                "BIC": fit.get("bic"),
                "Residual skew": fit.get("residual_skewness"),
                "Residual excess kurtosis": fit.get("residual_excess_kurtosis"),
                "Stability": (fit.get("stability") or {}).get("status", "NOT_RUN"),
                "Persistence delta": (fit.get("stability") or {}).get("persistence_delta"),
                "Last-vol ratio": (fit.get("stability") or {}).get("last_vol_ratio"),
                "Warning": "; ".join(filter(None, [str(fit.get("warning", "")), str((fit.get("stability") or {}).get("warning", ""))])),
            }
        )
    return pd.DataFrame(rows)
