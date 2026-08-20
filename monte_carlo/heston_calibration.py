from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.integrate import quad
from scipy.optimize import least_squares, minimize
from scipy.special import roots_laguerre
from scipy.stats import qmc

from .options_risk_neutral import black_scholes_price, implied_volatility

HESTON_CALIBRATION_VERSION = "HESTON-CALIBRATION-2.6.0A"
HESTON_OBJECTIVES = (
    "Composite linearized IV + total variance",
    "Vega-normalized price",
    "Linearized implied volatility",
    "Linearized total variance",
)


FELLER_POLICIES = (
    "No penalty",
    "Soft boundary penalty",
    "Hard Feller constraint",
)

PARAMETER_NAMES = ("kappa", "theta", "sigma_v", "rho", "v0")
DEFAULT_BOUNDS = {
    "kappa": (0.05, 30.0),
    "theta": (0.0025, 1.50),
    "sigma_v": (0.02, 4.00),
    "rho": (-0.999, 0.50),
    "v0": (0.0025, 1.50),
}


@dataclass(frozen=True)
class HestonParameters:
    kappa: float
    theta: float
    sigma_v: float
    rho: float
    v0: float


@dataclass(frozen=True)
class HestonCalibrationSettings:
    objective: str = "Composite linearized IV + total variance"
    multi_start: int = 8
    max_nfev: int = 300
    quadrature_nodes: int = 64
    feller_policy: str = "No penalty"
    feller_penalty: float = 1.0
    kappa_upper_bound: float = 20.0
    seed: int = 42
    holdout_weighted: bool = False
    numerical_crosscheck_points: int = 6
    numerical_crosscheck_tolerance: float = 2.5e-3
    run_robustness_checks: bool = True
    robustness_max_nfev: int = 120


def _signature(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(payload), sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16].upper()


def _coerce_parameters(parameters: HestonParameters | Mapping[str, float] | Sequence[float]) -> HestonParameters:
    if isinstance(parameters, HestonParameters):
        return parameters
    if isinstance(parameters, Mapping):
        return HestonParameters(**{name: float(parameters[name]) for name in PARAMETER_NAMES})
    values = np.asarray(parameters, dtype=float).reshape(-1)
    if values.size != 5:
        raise ValueError("Heston parameters must contain kappa, theta, sigma_v, rho and v0.")
    return HestonParameters(*map(float, values))


def heston_characteristic_function(
    u: np.ndarray | complex | float,
    time_to_expiry: float,
    spot: float,
    risk_free_rate: float,
    dividend_yield: float,
    parameters: HestonParameters | Mapping[str, float] | Sequence[float],
) -> np.ndarray:
    """Risk-neutral characteristic function of log(S_T) under Heston.

    The implementation uses the stable "little Heston trap" representation and
    is vectorized over the Fourier argument ``u``.
    """
    p = _coerce_parameters(parameters)
    u_arr = np.asarray(u, dtype=np.complex128)
    t = max(float(time_to_expiry), 0.0)
    if t == 0.0:
        return np.exp(1j * u_arr * math.log(float(spot)))

    kappa = max(float(p.kappa), 1e-12)
    theta = max(float(p.theta), 1e-12)
    sigma = max(float(p.sigma_v), 1e-10)
    rho = float(np.clip(p.rho, -0.999999, 0.999999))
    v0 = max(float(p.v0), 1e-12)
    iu = 1j * u_arr

    beta = kappa - rho * sigma * iu
    d = np.sqrt(beta * beta + sigma * sigma * (u_arr * u_arr + iu))
    # Enforce the principal branch with non-negative real part.
    d = np.where(np.real(d) < 0.0, -d, d)
    g = (beta - d) / (beta + d + 1e-32)
    exp_minus_dt = np.exp(-d * t)
    one_minus_g_exp = 1.0 - g * exp_minus_dt
    one_minus_g = 1.0 - g

    c = (
        iu * (math.log(float(spot)) + (float(risk_free_rate) - float(dividend_yield)) * t)
        + (kappa * theta / (sigma * sigma))
        * ((beta - d) * t - 2.0 * np.log(one_minus_g_exp / (one_minus_g + 1e-32)))
    )
    dcoef = ((beta - d) / (sigma * sigma)) * ((1.0 - exp_minus_dt) / (one_minus_g_exp + 1e-32))
    return np.exp(c + dcoef * v0)


def _laguerre_grid(nodes: int) -> tuple[np.ndarray, np.ndarray]:
    count = int(np.clip(nodes, 24, 192))
    x, w = roots_laguerre(count)
    # roots_laguerre integrates exp(-x) f(x); the Heston probability integral
    # has no exp(-x), hence the compensating exp(x).
    return x.astype(float), (w * np.exp(x)).astype(float)


def _heston_probabilities_laguerre(
    strikes: np.ndarray,
    time_to_expiry: float,
    spot: float,
    risk_free_rate: float,
    dividend_yield: float,
    parameters: HestonParameters,
    quadrature_nodes: int,
) -> tuple[np.ndarray, np.ndarray]:
    strikes = np.asarray(strikes, dtype=float)
    x, weights = _laguerre_grid(quadrature_nodes)
    u = x.astype(np.complex128)
    phi_u = heston_characteristic_function(u, time_to_expiry, spot, risk_free_rate, dividend_yield, parameters)
    phi_shift = heston_characteristic_function(u - 1j, time_to_expiry, spot, risk_free_rate, dividend_yield, parameters)
    phi_minus_i = heston_characteristic_function(np.asarray([-1j]), time_to_expiry, spot, risk_free_rate, dividend_yield, parameters)[0]
    denom = 1j * u
    f2 = phi_u / denom
    f1 = (phi_shift / (phi_minus_i + 1e-32)) / denom
    phase = np.exp(-1j * np.outer(np.log(np.maximum(strikes, 1e-12)), u))
    p1 = 0.5 + np.real(phase * f1[None, :]) @ weights / math.pi
    p2 = 0.5 + np.real(phase * f2[None, :]) @ weights / math.pi
    return np.clip(p1, 0.0, 1.0), np.clip(p2, 0.0, 1.0)


def heston_call_prices(
    spot: float,
    strikes: Sequence[float],
    time_to_expiry: float,
    risk_free_rate: float,
    dividend_yield: float,
    parameters: HestonParameters | Mapping[str, float] | Sequence[float],
    quadrature_nodes: int = 64,
) -> np.ndarray:
    p = _coerce_parameters(parameters)
    k = np.asarray(strikes, dtype=float)
    t = max(float(time_to_expiry), 0.0)
    if t <= 0.0:
        return np.maximum(float(spot) - k, 0.0)
    p1, p2 = _heston_probabilities_laguerre(k, t, float(spot), float(risk_free_rate), float(dividend_yield), p, quadrature_nodes)
    calls = float(spot) * math.exp(-float(dividend_yield) * t) * p1 - k * math.exp(-float(risk_free_rate) * t) * p2
    upper = float(spot) * math.exp(-float(dividend_yield) * t)
    lower = np.maximum(float(spot) * math.exp(-float(dividend_yield) * t) - k * math.exp(-float(risk_free_rate) * t), 0.0)
    return np.clip(np.real(calls), lower, upper)


def heston_option_prices(
    spot: float,
    strikes: Sequence[float],
    time_to_expiry: float,
    risk_free_rate: float,
    dividend_yield: float,
    option_types: Sequence[str],
    parameters: HestonParameters | Mapping[str, float] | Sequence[float],
    quadrature_nodes: int = 64,
) -> np.ndarray:
    k = np.asarray(strikes, dtype=float)
    types = np.asarray([str(value).lower() for value in option_types], dtype=object)
    calls = heston_call_prices(spot, k, time_to_expiry, risk_free_rate, dividend_yield, parameters, quadrature_nodes)
    puts = calls - float(spot) * math.exp(-float(dividend_yield) * float(time_to_expiry)) + k * math.exp(-float(risk_free_rate) * float(time_to_expiry))
    return np.where(types == "put", np.maximum(puts, 0.0), calls)


def _heston_call_price_quad(
    spot: float,
    strike: float,
    time_to_expiry: float,
    risk_free_rate: float,
    dividend_yield: float,
    parameters: HestonParameters,
) -> float:
    log_k = math.log(max(float(strike), 1e-12))
    phi_minus_i = heston_characteristic_function(np.asarray([-1j]), time_to_expiry, spot, risk_free_rate, dividend_yield, parameters)[0]

    def integrand(u: float, shifted: bool) -> float:
        z = complex(u)
        if shifted:
            value = heston_characteristic_function(np.asarray([z - 1j]), time_to_expiry, spot, risk_free_rate, dividend_yield, parameters)[0] / (phi_minus_i + 1e-32)
        else:
            value = heston_characteristic_function(np.asarray([z]), time_to_expiry, spot, risk_free_rate, dividend_yield, parameters)[0]
        return float(np.real(np.exp(-1j * z * log_k) * value / (1j * z)))

    p1 = 0.5 + quad(lambda value: integrand(value, True), 1e-8, 150.0, epsabs=1e-8, epsrel=1e-7, limit=300)[0] / math.pi
    p2 = 0.5 + quad(lambda value: integrand(value, False), 1e-8, 150.0, epsabs=1e-8, epsrel=1e-7, limit=300)[0] / math.pi
    return float(spot * math.exp(-dividend_yield * time_to_expiry) * p1 - strike * math.exp(-risk_free_rate * time_to_expiry) * p2)


def _prepare_dataset(dataset_result: Mapping[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame, float, float]:
    if not isinstance(dataset_result, Mapping) or not dataset_result.get("ok"):
        raise ValueError("A PASS/WARNING governed calibration dataset is required.")
    train = dataset_result.get("training_dataset")
    holdout = dataset_result.get("holdout_dataset")
    if not isinstance(train, pd.DataFrame) or train.empty:
        raise ValueError("The governed training dataset is empty.")
    holdout = holdout.copy() if isinstance(holdout, pd.DataFrame) else pd.DataFrame(columns=train.columns)
    spot = float(dataset_result.get("spot", np.nan))
    risk_free_rate = float(dataset_result.get("risk_free_rate", np.nan))
    if not np.isfinite(spot) or spot <= 0.0:
        raise ValueError("The calibration dataset does not contain a valid spot price.")
    if not np.isfinite(risk_free_rate):
        raise ValueError("The calibration dataset does not contain a valid risk-free rate.")
    required = {"strike", "time_to_expiry", "effective_q", "target_iv", "option_type", "calibration_weight"}
    missing = required.difference(train.columns)
    if missing:
        raise ValueError(f"Calibration dataset missing columns: {sorted(missing)}")
    return train.reset_index(drop=True), holdout.reset_index(drop=True), spot, risk_free_rate


def _target_prices(frame: pd.DataFrame, spot: float, risk_free_rate: float) -> np.ndarray:
    return np.asarray([
        black_scholes_price(
            spot,
            float(row.strike),
            float(row.time_to_expiry),
            risk_free_rate,
            float(row.effective_q),
            float(row.target_iv),
            str(row.option_type),
        )
        for row in frame.itertuples(index=False)
    ], dtype=float)


def _price_frame(
    frame: pd.DataFrame,
    spot: float,
    risk_free_rate: float,
    parameters: HestonParameters,
    quadrature_nodes: int,
) -> np.ndarray:
    output = np.empty(len(frame), dtype=float)
    for (_, maturity_group) in frame.groupby(["time_to_expiry", "effective_q"], sort=False):
        indices = maturity_group.index.to_numpy(dtype=int)
        output[indices] = heston_option_prices(
            spot=spot,
            strikes=maturity_group["strike"].to_numpy(dtype=float),
            time_to_expiry=float(maturity_group["time_to_expiry"].iloc[0]),
            risk_free_rate=risk_free_rate,
            dividend_yield=float(maturity_group["effective_q"].iloc[0]),
            option_types=maturity_group["option_type"].astype(str).tolist(),
            parameters=parameters,
            quadrature_nodes=quadrature_nodes,
        )
    return output


def _bounds_arrays(bounds: Mapping[str, Sequence[float]] | None = None) -> tuple[np.ndarray, np.ndarray, dict[str, tuple[float, float]]]:
    merged = {name: tuple(DEFAULT_BOUNDS[name]) for name in PARAMETER_NAMES}
    if bounds:
        for name, values in bounds.items():
            if name in merged:
                low, high = map(float, values)
                if high <= low:
                    raise ValueError(f"Invalid Heston bound for {name}.")
                merged[name] = (low, high)
    lower = np.asarray([merged[name][0] for name in PARAMETER_NAMES], dtype=float)
    upper = np.asarray([merged[name][1] for name in PARAMETER_NAMES], dtype=float)
    return lower, upper, merged


def _smart_start(train: pd.DataFrame, lower: np.ndarray, upper: np.ndarray) -> np.ndarray:
    atm = train.loc[train["log_moneyness"].astype(float).abs() <= 0.08, "target_iv"]
    sigma0 = float(np.nanmedian(atm)) if len(atm) else float(np.nanmedian(train["target_iv"]))
    variance = float(np.clip(sigma0 * sigma0, lower[1], upper[1]))
    start = np.asarray([2.0, variance, 0.60, -0.55, variance], dtype=float)
    return np.clip(start, lower + 1e-6, upper - 1e-6)


def _initial_starts(train: pd.DataFrame, lower: np.ndarray, upper: np.ndarray, count: int, seed: int) -> np.ndarray:
    count = max(int(count), 1)
    starts = [_smart_start(train, lower, upper)]
    if count > 1:
        sampler = qmc.LatinHypercube(d=5, seed=int(seed))
        samples = sampler.random(count - 1)
        scaled = qmc.scale(samples, lower, upper)
        starts.extend(np.asarray(scaled, dtype=float))
    return np.vstack(starts)


def _build_residual_function(
    train: pd.DataFrame,
    spot: float,
    risk_free_rate: float,
    objective: str,
    quadrature_nodes: int,
    feller_policy: str,
    feller_penalty: float,
):
    target_prices = _target_prices(train, spot, risk_free_rate)
    target_iv = train["target_iv"].to_numpy(dtype=float)
    t = train["time_to_expiry"].to_numpy(dtype=float)
    vega = np.maximum(train.get("vega_raw", pd.Series(np.ones(len(train)))).to_numpy(dtype=float), spot * 1e-5)
    weights = np.maximum(train["calibration_weight"].to_numpy(dtype=float), 0.0)
    weights = weights / max(float(np.sum(weights)), 1e-12)
    sqrt_w = np.sqrt(weights)
    soft_feller = str(feller_policy) == "Soft boundary penalty" and float(feller_penalty) > 0.0

    def residual(values: np.ndarray) -> np.ndarray:
        p = _coerce_parameters(values)
        try:
            model_prices = _price_frame(train, spot, risk_free_rate, p, quadrature_nodes)
            linearized_iv = (model_prices - target_prices) / vega
            linearized_tv = 2.0 * np.maximum(target_iv, 0.02) * t * linearized_iv
            if objective == "Vega-normalized price" or objective == "Linearized implied volatility":
                core = sqrt_w * linearized_iv
            elif objective == "Linearized total variance":
                scale = max(float(np.nanmedian(np.abs(2.0 * target_iv * t))), 1e-4)
                core = sqrt_w * linearized_tv / scale
            else:
                tv_scale = max(float(np.nanmedian(np.abs(2.0 * target_iv * t))), 1e-4)
                core = np.concatenate([0.75 * sqrt_w * linearized_iv, 0.25 * sqrt_w * linearized_tv / tv_scale])
            if not np.isfinite(core).all():
                return np.full(core.shape, 1e3, dtype=float)
            if soft_feller:
                feller_gap = max(p.sigma_v * p.sigma_v - 2.0 * p.kappa * p.theta, 0.0)
                penalty = math.sqrt(float(feller_penalty)) * feller_gap / max(p.sigma_v * p.sigma_v, 1e-8)
                core = np.concatenate([core, np.asarray([penalty], dtype=float)])
            return core
        except Exception:
            length = 2 * len(train) if objective == "Composite linearized IV + total variance" else len(train)
            return np.full(length + (1 if soft_feller else 0), 1e3, dtype=float)

    return residual


def _project_start_to_hard_feller(start: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> np.ndarray:
    values = np.asarray(start, dtype=float).copy()
    kappa, theta, sigma_v = max(values[0], 1e-12), max(values[1], 1e-12), max(values[2], 1e-12)
    admissible_sigma = math.sqrt(max(2.0 * kappa * theta, 1e-12))
    if sigma_v >= admissible_sigma:
        values[2] = min(max(0.98 * admissible_sigma, lower[2] + 1e-8), upper[2] - 1e-8)
    return np.clip(values, lower + 1e-8, upper - 1e-8)


def _fit_start(
    residual,
    start: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    max_nfev: int,
    feller_policy: str,
) -> dict[str, Any]:
    if str(feller_policy) == "Hard Feller constraint":
        x0 = _project_start_to_hard_feller(start, lower, upper)

        def scalar_objective(values: np.ndarray) -> float:
            errors = np.asarray(residual(values), dtype=float)
            if not np.isfinite(errors).all():
                return 1e6
            return float(np.mean(errors * errors))

        constraint = {
            "type": "ineq",
            "fun": lambda values: float(2.0 * values[0] * values[1] - values[2] * values[2]),
        }
        fit = minimize(
            scalar_objective,
            x0=x0,
            method="SLSQP",
            bounds=list(zip(lower, upper)),
            constraints=[constraint],
            options={"maxiter": int(max_nfev), "ftol": 1e-11, "disp": False},
        )
        jac = np.asarray(getattr(fit, "jac", np.asarray([], dtype=float)), dtype=float)
        optimality = float(np.linalg.norm(jac)) if jac.size and np.isfinite(jac).all() else float("nan")
        return {
            "x": np.asarray(fit.x, dtype=float),
            "success": bool(fit.success),
            "cost": float(fit.fun),
            "optimality": optimality,
            "nfev": int(getattr(fit, "nfev", 0)),
            "message": str(fit.message),
            "method": "SLSQP hard Feller",
        }

    fit = least_squares(
        residual,
        x0=start,
        bounds=(lower, upper),
        method="trf",
        max_nfev=int(max_nfev),
        xtol=1e-8,
        ftol=1e-8,
        gtol=1e-8,
        x_scale="jac",
    )
    return {
        "x": np.asarray(fit.x, dtype=float),
        "success": bool(fit.success),
        "cost": float(2.0 * fit.cost / max(len(fit.fun), 1)),
        "optimality": float(fit.optimality),
        "nfev": int(fit.nfev),
        "message": str(fit.message),
        "method": "least_squares",
    }

def _implied_vol_table(
    frame: pd.DataFrame,
    model_prices: np.ndarray,
    target_prices: np.ndarray,
    spot: float,
    risk_free_rate: float,
    role: str,
) -> pd.DataFrame:
    output = frame.copy().reset_index(drop=True)
    output["sample_role"] = role
    output["target_price"] = target_prices
    output["heston_price"] = model_prices
    fitted_iv = []
    for row, price in zip(output.itertuples(index=False), model_prices):
        fitted_iv.append(
            implied_volatility(
                float(price),
                spot,
                float(row.strike),
                float(row.time_to_expiry),
                risk_free_rate,
                float(row.effective_q),
                str(row.option_type),
            )
        )
    output["heston_iv"] = np.asarray(fitted_iv, dtype=float)
    output["price_error"] = output["heston_price"] - output["target_price"]
    output["iv_error"] = output["heston_iv"] - output["target_iv"]
    output["target_total_variance"] = output["target_iv"] ** 2 * output["time_to_expiry"]
    output["heston_total_variance"] = output["heston_iv"] ** 2 * output["time_to_expiry"]
    output["total_variance_error"] = output["heston_total_variance"] - output["target_total_variance"]
    return output


def _metric_summary(frame: pd.DataFrame, weighted: bool) -> dict[str, float]:
    valid = frame[np.isfinite(frame["heston_iv"]) & np.isfinite(frame["iv_error"])].copy()
    if valid.empty:
        return {"count": 0, "iv_rmse": float("nan"), "tv_rmse": float("nan"), "price_rmse": float("nan"), "mean_abs_iv_error": float("nan")}
    if weighted and "calibration_weight" in valid:
        w = np.maximum(valid["calibration_weight"].to_numpy(dtype=float), 0.0)
        if float(np.sum(w)) <= 0.0:
            w = np.ones(len(valid), dtype=float)
    else:
        w = np.ones(len(valid), dtype=float)
    w /= float(np.sum(w))
    return {
        "count": int(len(valid)),
        "iv_rmse": float(np.sqrt(np.sum(w * valid["iv_error"].to_numpy(dtype=float) ** 2))),
        "tv_rmse": float(np.sqrt(np.sum(w * valid["total_variance_error"].to_numpy(dtype=float) ** 2))),
        "price_rmse": float(np.sqrt(np.sum(w * valid["price_error"].to_numpy(dtype=float) ** 2))),
        "mean_abs_iv_error": float(np.sum(w * np.abs(valid["iv_error"].to_numpy(dtype=float)))),
    }


def _error_breakdown(table: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    maturity_rows = []
    for (role, expiration), group in table.groupby(["sample_role", "expiration"], sort=True):
        metrics = _metric_summary(group, weighted=(role == "TRAIN"))
        maturity_rows.append({"sample_role": role, "expiration": str(expiration), "dte": int(group["dte"].iloc[0]), **metrics})
    bucket_rows = []
    if "moneyness_bucket" in table:
        for (role, bucket), group in table.groupby(["sample_role", "moneyness_bucket"], observed=False, sort=False):
            if len(group) == 0:
                continue
            metrics = _metric_summary(group, weighted=(role == "TRAIN"))
            bucket_rows.append({"sample_role": role, "moneyness_bucket": str(bucket), **metrics})
    return pd.DataFrame(maturity_rows), pd.DataFrame(bucket_rows)


def _near_bound_flags(parameters: HestonParameters, bounds: Mapping[str, tuple[float, float]], tolerance: float = 0.015) -> list[str]:
    warnings = []
    for name in PARAMETER_NAMES:
        value = float(getattr(parameters, name))
        low, high = bounds[name]
        relative = min((value - low) / (high - low), (high - value) / (high - low))
        if relative <= tolerance:
            warnings.append(f"{name} is within {tolerance:.1%} of a calibration bound.")
    return warnings


def _solution_stability(solutions: pd.DataFrame, best_cost: float, bounds: Mapping[str, tuple[float, float]]) -> dict[str, Any]:
    if solutions.empty:
        return {"near_optimal_solutions": 0, "maximum_normalized_range": float("nan"), "parameter_ranges": {}}
    threshold = best_cost * 1.05 + 1e-10
    near = solutions[solutions["cost"] <= threshold]
    ranges: dict[str, float] = {}
    for name in PARAMETER_NAMES:
        low, high = bounds[name]
        ranges[name] = float((near[name].max() - near[name].min()) / max(high - low, 1e-12)) if len(near) else float("nan")
    return {
        "near_optimal_solutions": int(len(near)),
        "maximum_normalized_range": float(np.nanmax(list(ranges.values()))) if ranges else float("nan"),
        "parameter_ranges": ranges,
    }


def _numerical_crosscheck(
    table: pd.DataFrame,
    parameters: HestonParameters,
    spot: float,
    risk_free_rate: float,
    quadrature_nodes: int,
    points: int,
) -> pd.DataFrame:
    if table.empty or points <= 0:
        return pd.DataFrame()
    selected_positions = np.unique(np.round(np.linspace(0, len(table) - 1, min(int(points), len(table)))).astype(int))
    rows = []
    for position in selected_positions:
        row = table.iloc[int(position)]
        call_laguerre = float(heston_call_prices(
            spot,
            [float(row["strike"])],
            float(row["time_to_expiry"]),
            risk_free_rate,
            float(row["effective_q"]),
            parameters,
            quadrature_nodes,
        )[0])
        call_quad = _heston_call_price_quad(
            spot,
            float(row["strike"]),
            float(row["time_to_expiry"]),
            risk_free_rate,
            float(row["effective_q"]),
            parameters,
        )
        rows.append({
            "expiration": str(row["expiration"]),
            "strike": float(row["strike"]),
            "laguerre_call": call_laguerre,
            "adaptive_quad_call": call_quad,
            "absolute_difference": abs(call_laguerre - call_quad),
        })
    return pd.DataFrame(rows)



def _local_error_governance(
    fit_table: pd.DataFrame,
    maturity_errors: pd.DataFrame,
    bucket_errors: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any], list[str], list[str]]:
    warnings: list[str] = []
    blockers: list[str] = []
    if fit_table.empty:
        return pd.DataFrame(), {}, warnings, blockers

    frame = fit_table.copy()
    if "moneyness_bucket" not in frame:
        frame["moneyness_bucket"] = pd.cut(
            frame["log_moneyness"],
            [-np.inf, -0.20, -0.08, 0.08, 0.20, np.inf],
            labels=["Left wing", "Put shoulder", "ATM", "Call shoulder", "Right wing"],
        )
    cell_rows: list[dict[str, Any]] = []
    for (role, expiration, dte, bucket), group in frame.groupby(
        ["sample_role", "expiration", "dte", "moneyness_bucket"],
        observed=False,
        sort=True,
    ):
        if len(group) == 0:
            continue
        errors = group["iv_error"].to_numpy(dtype=float)
        errors = errors[np.isfinite(errors)]
        if not len(errors):
            continue
        cell_rows.append({
            "sample_role": str(role),
            "expiration": str(expiration),
            "dte": int(dte),
            "moneyness_bucket": str(bucket),
            "count": int(len(errors)),
            "mean_iv_error": float(np.mean(errors)),
            "iv_rmse": float(np.sqrt(np.mean(errors * errors))),
            "max_abs_iv_error": float(np.max(np.abs(errors))),
        })
    cells = pd.DataFrame(cell_rows)

    worst_train_maturity = float(maturity_errors.loc[maturity_errors["sample_role"] == "TRAIN", "iv_rmse"].max()) if not maturity_errors.empty and (maturity_errors["sample_role"] == "TRAIN").any() else float("nan")
    worst_holdout_maturity = float(maturity_errors.loc[maturity_errors["sample_role"] == "HOLDOUT", "iv_rmse"].max()) if not maturity_errors.empty and (maturity_errors["sample_role"] == "HOLDOUT").any() else float("nan")
    worst_bucket = float(bucket_errors["iv_rmse"].max()) if not bucket_errors.empty else float("nan")
    worst_cell_mean = float(cells["mean_iv_error"].abs().max()) if not cells.empty else float("nan")
    worst_cell_rmse = float(cells["iv_rmse"].max()) if not cells.empty else float("nan")

    short_dated = cells[cells["dte"] == cells["dte"].min()] if not cells.empty else pd.DataFrame()
    short_wings = short_dated[short_dated["moneyness_bucket"].isin(["Left wing", "Right wing"])] if not short_dated.empty else pd.DataFrame()
    short_wing_mean_abs = float(short_wings["mean_iv_error"].abs().max()) if not short_wings.empty else float("nan")

    if np.isfinite(worst_train_maturity):
        if worst_train_maturity > 0.080:
            blockers.append(f"Worst training-maturity IV RMSE {worst_train_maturity:.2%} exceeds the 8.0% local ceiling.")
        elif worst_train_maturity > 0.040:
            warnings.append(f"Worst training-maturity IV RMSE {worst_train_maturity:.2%} exceeds the preferred 4.0% local level.")
    if np.isfinite(worst_holdout_maturity):
        if worst_holdout_maturity > 0.100:
            blockers.append(f"Worst holdout-maturity IV RMSE {worst_holdout_maturity:.2%} exceeds the 10.0% local ceiling.")
        elif worst_holdout_maturity > 0.050:
            warnings.append(f"Worst holdout-maturity IV RMSE {worst_holdout_maturity:.2%} exceeds the preferred 5.0% local level.")
    if np.isfinite(worst_bucket) and worst_bucket > 0.050:
        warnings.append(f"At least one moneyness bucket has IV RMSE {worst_bucket:.2%}, above the preferred 5.0% level.")
    if np.isfinite(worst_cell_mean):
        if worst_cell_mean > 0.100:
            blockers.append(f"A maturity/moneyness cell has mean IV bias {worst_cell_mean:.2%}, above the 10.0% ceiling.")
        elif worst_cell_mean > 0.050:
            warnings.append(f"A maturity/moneyness cell has mean IV bias {worst_cell_mean:.2%}, indicating a systematic local miss.")
    if np.isfinite(short_wing_mean_abs) and short_wing_mean_abs > 0.050:
        warnings.append(
            f"The shortest-maturity wing bias reaches {short_wing_mean_abs:.2%}; continuous Heston is not reproducing the front-end wings cleanly."
        )

    summary = {
        "worst_training_maturity_iv_rmse": worst_train_maturity,
        "worst_holdout_maturity_iv_rmse": worst_holdout_maturity,
        "worst_bucket_iv_rmse": worst_bucket,
        "worst_cell_mean_abs_iv_error": worst_cell_mean,
        "worst_cell_iv_rmse": worst_cell_rmse,
        "shortest_maturity_wing_mean_abs_iv_error": short_wing_mean_abs,
    }
    return cells, summary, warnings, blockers


def _parameter_distance(
    first: HestonParameters,
    second: HestonParameters,
    bounds: Mapping[str, tuple[float, float]],
) -> float:
    distances = []
    for name in PARAMETER_NAMES:
        low, high = bounds[name]
        distances.append(abs(float(getattr(first, name)) - float(getattr(second, name))) / max(high - low, 1e-12))
    return float(np.sqrt(np.mean(np.asarray(distances, dtype=float) ** 2)))


def _evaluate_parameter_set(
    train: pd.DataFrame,
    holdout: pd.DataFrame,
    spot: float,
    risk_free_rate: float,
    parameters: HestonParameters,
    quadrature_nodes: int,
) -> tuple[dict[str, float], dict[str, float]]:
    train_targets = _target_prices(train, spot, risk_free_rate)
    train_prices = _price_frame(train, spot, risk_free_rate, parameters, quadrature_nodes)
    train_fit = _implied_vol_table(train, train_prices, train_targets, spot, risk_free_rate, "TRAIN")
    train_metrics = _metric_summary(train_fit, weighted=True)
    if len(holdout):
        holdout_targets = _target_prices(holdout, spot, risk_free_rate)
        holdout_prices = _price_frame(holdout, spot, risk_free_rate, parameters, quadrature_nodes)
        holdout_fit = _implied_vol_table(holdout, holdout_prices, holdout_targets, spot, risk_free_rate, "HOLDOUT")
        holdout_metrics = _metric_summary(holdout_fit, weighted=False)
    else:
        holdout_metrics = {"count": 0, "iv_rmse": float("nan"), "tv_rmse": float("nan"), "price_rmse": float("nan"), "mean_abs_iv_error": float("nan")}
    return train_metrics, holdout_metrics


def _run_robustness_checks(
    train: pd.DataFrame,
    holdout: pd.DataFrame,
    spot: float,
    risk_free_rate: float,
    base_parameters: HestonParameters,
    base_cost: float,
    base_policy: str,
    objective: str,
    quadrature_nodes: int,
    feller_penalty: float,
    lower: np.ndarray,
    upper: np.ndarray,
    bound_map: Mapping[str, tuple[float, float]],
    max_nfev: int,
) -> tuple[pd.DataFrame, str, list[str]]:
    specifications: list[tuple[str, str, np.ndarray, np.ndarray, float]] = []
    wider_upper = upper.copy()
    wider_upper[0] = max(float(upper[0]), min(40.0, max(24.0, float(upper[0]) * 1.5)))
    if wider_upper[0] > upper[0] + 1e-9:
        specifications.append(("Wider kappa cap", str(base_policy), lower.copy(), wider_upper, float(feller_penalty)))
    if str(base_policy) != "No penalty":
        specifications.append(("No Feller penalty", "No penalty", lower.copy(), upper.copy(), 0.0))
    if str(base_policy) != "Hard Feller constraint":
        specifications.append(("Hard Feller constraint", "Hard Feller constraint", lower.copy(), wider_upper.copy(), 0.0))

    base_train, base_holdout = _evaluate_parameter_set(train, holdout, spot, risk_free_rate, base_parameters, quadrature_nodes)
    rows = [{
        "specification": "Selected calibration",
        "feller_policy": str(base_policy),
        "success": True,
        "cost": float(base_cost),
        "cost_improvement_vs_selected": 0.0,
        "parameter_distance_vs_selected": 0.0,
        "kappa": float(base_parameters.kappa),
        "theta": float(base_parameters.theta),
        "sigma_v": float(base_parameters.sigma_v),
        "rho": float(base_parameters.rho),
        "v0": float(base_parameters.v0),
        "feller_ratio": float(2.0 * base_parameters.kappa * base_parameters.theta / max(base_parameters.sigma_v ** 2, 1e-12)),
        "train_iv_rmse": float(base_train["iv_rmse"]),
        "holdout_iv_rmse": float(base_holdout["iv_rmse"]),
        "kappa_upper_bound": float(upper[0]),
    }]

    for name, policy, spec_lower, spec_upper, penalty in specifications:
        residual = _build_residual_function(
            train,
            spot,
            risk_free_rate,
            objective,
            quadrature_nodes,
            policy,
            penalty,
        )
        fitted = _fit_start(
            residual,
            np.asarray([base_parameters.kappa, base_parameters.theta, base_parameters.sigma_v, base_parameters.rho, base_parameters.v0], dtype=float),
            spec_lower,
            spec_upper,
            max_nfev=max_nfev,
            feller_policy=policy,
        )
        parameters = _coerce_parameters(fitted["x"])
        train_metrics, holdout_metrics = _evaluate_parameter_set(train, holdout, spot, risk_free_rate, parameters, quadrature_nodes)
        local_bounds = dict(bound_map)
        local_bounds["kappa"] = (float(spec_lower[0]), float(spec_upper[0]))
        rows.append({
            "specification": name,
            "feller_policy": policy,
            "success": bool(fitted["success"]),
            "cost": float(fitted["cost"]),
            "cost_improvement_vs_selected": float((base_cost - float(fitted["cost"])) / max(abs(base_cost), 1e-14)),
            "parameter_distance_vs_selected": _parameter_distance(base_parameters, parameters, local_bounds),
            "kappa": float(parameters.kappa),
            "theta": float(parameters.theta),
            "sigma_v": float(parameters.sigma_v),
            "rho": float(parameters.rho),
            "v0": float(parameters.v0),
            "feller_ratio": float(2.0 * parameters.kappa * parameters.theta / max(parameters.sigma_v ** 2, 1e-12)),
            "train_iv_rmse": float(train_metrics["iv_rmse"]),
            "holdout_iv_rmse": float(holdout_metrics["iv_rmse"]),
            "kappa_upper_bound": float(spec_upper[0]),
        })

    table = pd.DataFrame(rows)
    warnings: list[str] = []
    status = "STABLE"
    wider = table[table["specification"] == "Wider kappa cap"]
    if not wider.empty:
        row = wider.iloc[0]
        if float(row["cost_improvement_vs_selected"]) > 0.02 or (
            float(row["kappa"]) > 1.15 * float(base_parameters.kappa)
            and float(row["parameter_distance_vs_selected"]) > 0.08
        ):
            status = "BOUND_SENSITIVE"
            warnings.append(
                "Widening the kappa bound materially changes the optimum; mean-reversion speed is not stable under the selected bound."
            )
    no_feller = table[table["specification"] == "No Feller penalty"]
    if not no_feller.empty:
        row = no_feller.iloc[0]
        if float(row["cost_improvement_vs_selected"]) > 0.03 and float(row["parameter_distance_vs_selected"]) > 0.08:
            status = "FELLER_SENSITIVE" if status == "STABLE" else "MIXED_SENSITIVITY"
            warnings.append(
                "Removing the Feller penalty materially improves fit or changes parameters; the selected calibration is penalty-sensitive."
            )
    hard = table[table["specification"] == "Hard Feller constraint"]
    if not hard.empty:
        row = hard.iloc[0]
        deterioration = -float(row["cost_improvement_vs_selected"])
        if deterioration > 0.25:
            warnings.append("Enforcing the hard Feller condition deteriorates the objective by more than 25%.")
    return table, status, warnings


def calibrate_heston(
    dataset_result: Mapping[str, Any],
    objective: str = "Composite linearized IV + total variance",
    multi_start: int = 8,
    max_nfev: int = 300,
    quadrature_nodes: int = 64,
    feller_policy: str = "No penalty",
    feller_penalty: float = 1.0,
    kappa_upper_bound: float = 20.0,
    seed: int = 42,
    bounds: Mapping[str, Sequence[float]] | None = None,
    numerical_crosscheck_points: int = 6,
    numerical_crosscheck_tolerance: float = 2.5e-3,
    run_robustness_checks: bool = True,
    robustness_max_nfev: int = 120,
) -> dict[str, Any]:
    if objective not in HESTON_OBJECTIVES:
        return {"ok": False, "status": "FAILED", "reason": f"Unsupported Heston objective: {objective}"}
    if feller_policy not in FELLER_POLICIES:
        return {"ok": False, "status": "FAILED", "reason": f"Unsupported Feller policy: {feller_policy}"}
    try:
        train, holdout, spot, risk_free_rate = _prepare_dataset(dataset_result)
    except Exception as exc:
        return {"ok": False, "status": "FAILED", "reason": str(exc)}

    selected_bounds = dict(bounds or {})
    if "kappa" not in selected_bounds:
        selected_bounds["kappa"] = (DEFAULT_BOUNDS["kappa"][0], float(kappa_upper_bound))
    settings = HestonCalibrationSettings(
        objective=str(objective),
        multi_start=int(multi_start),
        max_nfev=int(max_nfev),
        quadrature_nodes=int(quadrature_nodes),
        feller_policy=str(feller_policy),
        feller_penalty=float(feller_penalty),
        kappa_upper_bound=float(kappa_upper_bound),
        seed=int(seed),
        numerical_crosscheck_points=int(numerical_crosscheck_points),
        numerical_crosscheck_tolerance=float(numerical_crosscheck_tolerance),
        run_robustness_checks=bool(run_robustness_checks),
        robustness_max_nfev=int(robustness_max_nfev),
    )
    lower, upper, bound_map = _bounds_arrays(selected_bounds)
    starts = _initial_starts(train, lower, upper, settings.multi_start, settings.seed)
    residual = _build_residual_function(
        train,
        spot,
        risk_free_rate,
        settings.objective,
        settings.quadrature_nodes,
        settings.feller_policy,
        settings.feller_penalty,
    )

    solution_rows: list[dict[str, Any]] = []
    best: tuple[float, dict[str, Any]] | None = None
    for index, start in enumerate(starts):
        try:
            fitted = _fit_start(
                residual,
                start,
                lower,
                upper,
                max_nfev=settings.max_nfev,
                feller_policy=settings.feller_policy,
            )
            cost = float(fitted["cost"])
            row = {
                "start_id": index + 1,
                "success": bool(fitted["success"]),
                "cost": cost,
                "optimality": float(fitted.get("optimality", float("nan"))),
                "nfev": int(fitted.get("nfev", 0)),
                "method": str(fitted.get("method", "unknown")),
                "message": str(fitted.get("message", "")),
                **{name: float(value) for name, value in zip(PARAMETER_NAMES, fitted["x"])},
            }
            solution_rows.append(row)
            if np.isfinite(cost) and (best is None or cost < best[0]):
                best = (cost, fitted)
        except Exception as exc:
            solution_rows.append({
                "start_id": index + 1,
                "success": False,
                "cost": float("inf"),
                "optimality": float("nan"),
                "nfev": 0,
                "method": "failed",
                "message": str(exc),
                **{name: float("nan") for name in PARAMETER_NAMES},
            })

    solutions = pd.DataFrame(solution_rows).sort_values("cost", na_position="last").reset_index(drop=True)
    if best is None:
        return {"ok": False, "status": "FAILED", "reason": "All Heston multi-start optimizations failed.", "multi_start_solutions": solutions}

    best_cost, best_fit = best
    if np.isfinite(best_cost) and best_cost > 0.0:
        solutions["relative_cost_bps"] = (solutions["cost"] / best_cost - 1.0) * 10_000.0
        solutions["cost_improvement_vs_best"] = 1.0 - solutions["cost"] / best_cost
    else:
        solutions["relative_cost_bps"] = np.nan
        solutions["cost_improvement_vs_best"] = np.nan

    parameters = _coerce_parameters(best_fit["x"])
    train_targets = _target_prices(train, spot, risk_free_rate)
    train_prices = _price_frame(train, spot, risk_free_rate, parameters, settings.quadrature_nodes)
    holdout_targets = _target_prices(holdout, spot, risk_free_rate) if len(holdout) else np.asarray([], dtype=float)
    holdout_prices = _price_frame(holdout, spot, risk_free_rate, parameters, settings.quadrature_nodes) if len(holdout) else np.asarray([], dtype=float)
    train_fit = _implied_vol_table(train, train_prices, train_targets, spot, risk_free_rate, "TRAIN")
    holdout_fit = _implied_vol_table(holdout, holdout_prices, holdout_targets, spot, risk_free_rate, "HOLDOUT") if len(holdout) else pd.DataFrame(columns=train_fit.columns)
    fit_table = pd.concat([train_fit, holdout_fit], ignore_index=True, sort=False)

    train_metrics = _metric_summary(train_fit, weighted=True)
    holdout_metrics = _metric_summary(holdout_fit, weighted=False) if len(holdout_fit) else {"count": 0, "iv_rmse": float("nan"), "tv_rmse": float("nan"), "price_rmse": float("nan"), "mean_abs_iv_error": float("nan")}
    maturity_errors, bucket_errors = _error_breakdown(fit_table)
    local_error_table, local_error_summary, local_warnings, local_blockers = _local_error_governance(
        fit_table,
        maturity_errors,
        bucket_errors,
    )
    stability = _solution_stability(solutions, best_cost, bound_map)
    crosscheck = _numerical_crosscheck(
        train_fit.sort_values(["time_to_expiry", "strike"]),
        parameters,
        spot,
        risk_free_rate,
        settings.quadrature_nodes,
        settings.numerical_crosscheck_points,
    )
    max_crosscheck_error = float(crosscheck["absolute_difference"].max()) if not crosscheck.empty else float("nan")

    feller_ratio = float(2.0 * parameters.kappa * parameters.theta / max(parameters.sigma_v * parameters.sigma_v, 1e-12))
    if feller_ratio >= 1.02:
        feller_regime = "SATISFIED"
    elif feller_ratio >= 0.98:
        feller_regime = "BOUNDARY"
    else:
        feller_regime = "VIOLATED"
    variance_half_life_days = float(math.log(2.0) / parameters.kappa * 365.0) if parameters.kappa > 0.0 else float("inf")

    robustness_table = pd.DataFrame()
    robustness_status = "NOT_RUN"
    robustness_warnings: list[str] = []
    if settings.run_robustness_checks:
        try:
            robustness_table, robustness_status, robustness_warnings = _run_robustness_checks(
                train=train,
                holdout=holdout,
                spot=spot,
                risk_free_rate=risk_free_rate,
                base_parameters=parameters,
                base_cost=best_cost,
                base_policy=settings.feller_policy,
                objective=settings.objective,
                quadrature_nodes=settings.quadrature_nodes,
                feller_penalty=settings.feller_penalty,
                lower=lower,
                upper=upper,
                bound_map=bound_map,
                max_nfev=settings.robustness_max_nfev,
            )
        except Exception as exc:
            robustness_status = "FAILED"
            robustness_warnings.append(f"Calibration robustness checks failed: {exc}")

    warnings: list[str] = []
    blockers: list[str] = []
    if not bool(best_fit.get("success", False)):
        blockers.append(f"Best optimization did not report convergence: {best_fit.get('message', '')}")
    if not np.isfinite(train_metrics["iv_rmse"]):
        blockers.append("Training implied-volatility errors could not be computed.")
    elif train_metrics["iv_rmse"] > 0.050:
        blockers.append(f"Training IV RMSE {train_metrics['iv_rmse']:.2%} exceeds the 5.0% institutional ceiling.")
    elif train_metrics["iv_rmse"] > 0.030:
        warnings.append(f"Training IV RMSE {train_metrics['iv_rmse']:.2%} exceeds the preferred 3.0% level.")
    if np.isfinite(holdout_metrics["iv_rmse"]):
        if holdout_metrics["iv_rmse"] > 0.070:
            blockers.append(f"Holdout IV RMSE {holdout_metrics['iv_rmse']:.2%} exceeds the 7.0% ceiling.")
        elif holdout_metrics["iv_rmse"] > 0.045:
            warnings.append(f"Holdout IV RMSE {holdout_metrics['iv_rmse']:.2%} exceeds the preferred 4.5% level.")
        if train_metrics["iv_rmse"] > 0 and holdout_metrics["iv_rmse"] / train_metrics["iv_rmse"] > 2.0:
            warnings.append("Holdout IV RMSE is more than twice the training IV RMSE.")

    if settings.feller_policy == "Hard Feller constraint" and feller_ratio < 0.999:
        blockers.append(f"Hard Feller constraint was requested but the fitted ratio is {feller_ratio:.4f}.")
    elif feller_regime == "VIOLATED":
        warnings.append(f"Feller condition is violated (ratio {feller_ratio:.3f}); pricing remains valid but variance can reach zero.")
    elif feller_regime == "BOUNDARY":
        warnings.append(
            f"Feller ratio {feller_ratio:.3f} lies on the admissibility boundary; interpret parameter stability with caution."
        )
        if settings.feller_policy == "Soft boundary penalty":
            warnings.append("The soft Feller penalty is materially influencing the optimum near the boundary.")

    warnings.extend(_near_bound_flags(parameters, bound_map))
    warnings.extend(local_warnings)
    blockers.extend(local_blockers)
    warnings.extend(robustness_warnings)
    if stability.get("near_optimal_solutions", 0) >= 2 and float(stability.get("maximum_normalized_range", 0.0)) > 0.25:
        warnings.append("Near-optimal multi-start solutions show material parameter dispersion; identifiability is weak.")
    if np.isfinite(max_crosscheck_error) and max_crosscheck_error > settings.numerical_crosscheck_tolerance:
        blockers.append(f"Pricing cross-check error {max_crosscheck_error:.6f} exceeds tolerance {settings.numerical_crosscheck_tolerance:.6f}.")
    elif np.isfinite(max_crosscheck_error) and max_crosscheck_error > settings.numerical_crosscheck_tolerance * 0.40:
        warnings.append("Pricing cross-check is within tolerance but above the preferred numerical margin.")

    status = "INELIGIBLE" if blockers else ("WARNING" if warnings else "PASS")
    signature = _signature({
        "version": HESTON_CALIBRATION_VERSION,
        "dataset_signature": dataset_result.get("configuration_signature"),
        "settings": asdict(settings),
        "bounds": bound_map,
        "parameters": asdict(parameters),
        "robustness_status": robustness_status,
    })
    parameter_table = pd.DataFrame([
        {
            "parameter": name,
            "estimate": float(getattr(parameters, name)),
            "lower_bound": float(bound_map[name][0]),
            "upper_bound": float(bound_map[name][1]),
            "near_bound": any(warning.startswith(name + " ") for warning in warnings),
        }
        for name in PARAMETER_NAMES
    ])

    return {
        "ok": not bool(blockers),
        "status": status,
        "version": HESTON_CALIBRATION_VERSION,
        "configuration_signature": signature,
        "dataset_signature": dataset_result.get("configuration_signature"),
        "settings": asdict(settings),
        "bounds": bound_map,
        "spot": spot,
        "risk_free_rate": risk_free_rate,
        "parameters": asdict(parameters),
        "parameter_table": parameter_table,
        "feller_ratio": feller_ratio,
        "feller_regime": feller_regime,
        "feller_satisfied": bool(feller_ratio >= 1.0),
        "variance_half_life_days": variance_half_life_days,
        "train_metrics": train_metrics,
        "holdout_metrics": holdout_metrics,
        "fit_table": fit_table,
        "maturity_errors": maturity_errors,
        "moneyness_errors": bucket_errors,
        "local_error_table": local_error_table,
        "local_error_summary": local_error_summary,
        "multi_start_solutions": solutions,
        "solution_stability": stability,
        "robustness_table": robustness_table,
        "robustness_status": robustness_status,
        "numerical_crosscheck": crosscheck,
        "maximum_crosscheck_error": max_crosscheck_error,
        "warnings": list(dict.fromkeys(warnings)),
        "blockers": list(dict.fromkeys(blockers)),
        "governance": {
            "measure": "Heston is calibrated under Q to the governed option-implied training dataset.",
            "objective": str(objective),
            "training_holdout": "Training weights are used only in calibration; holdout instruments remain excluded from the objective.",
            "feller": "Feller treatment is explicit. No-penalty, soft-boundary and hard-constraint specifications are not economically equivalent.",
            "local_fit": "Global RMSE is supplemented by maturity, moneyness and cell-level residual gates.",
            "robustness": "Kappa-bound and Feller-policy challengers are retained when robustness checks are enabled.",
            "identifiability": "Multiple near-optimal solutions are retained to assess parameter identification.",
            "numerical_control": "Gauss-Laguerre pricing is cross-checked against adaptive quadrature on a governed subset.",
            "prohibition": "A calibrated Q model is not a physical expected-return forecast and is not added to the validated P-measure ensemble.",
        },
    }
