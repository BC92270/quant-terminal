from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.integrate import quad
from scipy.optimize import least_squares
from scipy.special import roots_laguerre
from scipy.stats import qmc

from .heston_calibration import (
    HESTON_OBJECTIVES,
    HestonParameters,
    _prepare_dataset,
    _target_prices,
    heston_characteristic_function,
)
from .options_risk_neutral import implied_volatility

BATES_CALIBRATION_VERSION = "BATES-CALIBRATION-2.7.0A"
BATES_CHAMPION_STATUSES = (
    "HESTON_CHAMPION",
    "BATES_CHAMPION",
    "BATES_RESEARCH_ONLY",
    "INCONCLUSIVE",
    "BATES_REJECTED",
)

PARAMETER_NAMES = (
    "kappa",
    "theta",
    "sigma_v",
    "rho",
    "v0",
    "jump_intensity",
    "jump_mean",
    "jump_volatility",
)

DEFAULT_BOUNDS = {
    "kappa": (0.05, 30.0),
    "theta": (0.0025, 1.50),
    "sigma_v": (0.02, 4.00),
    "rho": (-0.999, 0.50),
    "v0": (0.0025, 1.50),
    "jump_intensity": (0.0, 8.0),
    "jump_mean": (-0.50, 0.25),
    "jump_volatility": (0.01, 0.60),
}


@dataclass(frozen=True)
class BatesParameters:
    kappa: float
    theta: float
    sigma_v: float
    rho: float
    v0: float
    jump_intensity: float
    jump_mean: float
    jump_volatility: float


@dataclass(frozen=True)
class BatesCalibrationSettings:
    objective: str = "Composite linearized IV + total variance"
    multi_start: int = 8
    max_nfev: int = 260
    quadrature_nodes: int = 64
    seed: int = 42
    numerical_crosscheck_points: int = 6
    numerical_crosscheck_tolerance: float = 3.5e-3
    minimum_holdout_improvement: float = 0.10
    minimum_front_wing_improvement: float = 0.20
    maximum_other_maturity_degradation: float = 0.15
    maximum_other_maturity_absolute_degradation: float = 0.0035
    require_bic_improvement: bool = True


def _signature(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(payload), sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16].upper()


def _coerce_parameters(parameters: BatesParameters | Mapping[str, float] | Sequence[float]) -> BatesParameters:
    if isinstance(parameters, BatesParameters):
        return parameters
    if isinstance(parameters, Mapping):
        return BatesParameters(**{name: float(parameters[name]) for name in PARAMETER_NAMES})
    values = np.asarray(parameters, dtype=float).reshape(-1)
    if values.size != len(PARAMETER_NAMES):
        raise ValueError("Bates parameters must contain 8 values.")
    return BatesParameters(*map(float, values))


def _jump_compensator(parameters: BatesParameters) -> float:
    return float(math.exp(parameters.jump_mean + 0.5 * parameters.jump_volatility**2) - 1.0)


def bates_characteristic_function(
    u: np.ndarray | complex | float,
    time_to_expiry: float,
    spot: float,
    risk_free_rate: float,
    dividend_yield: float,
    parameters: BatesParameters | Mapping[str, float] | Sequence[float],
) -> np.ndarray:
    """Risk-neutral characteristic function of log(S_T) under Bates.

    The Heston diffusion drift is reduced by the compensator
    lambda * E[e^J - 1], while the compound-Poisson normal-jump
    characteristic exponent is applied multiplicatively.
    """
    p = _coerce_parameters(parameters)
    u_arr = np.asarray(u, dtype=np.complex128)
    t = max(float(time_to_expiry), 0.0)
    heston = HestonParameters(p.kappa, p.theta, p.sigma_v, p.rho, p.v0)
    kappa_j = _jump_compensator(p)
    adjusted_q = float(dividend_yield) + float(p.jump_intensity) * kappa_j
    base = heston_characteristic_function(
        u_arr,
        t,
        float(spot),
        float(risk_free_rate),
        adjusted_q,
        heston,
    )
    if t <= 0.0 or p.jump_intensity <= 0.0:
        return base
    jump_cf = np.exp(1j * u_arr * p.jump_mean - 0.5 * p.jump_volatility**2 * u_arr**2)
    return base * np.exp(p.jump_intensity * t * (jump_cf - 1.0))


def _laguerre_grid(nodes: int) -> tuple[np.ndarray, np.ndarray]:
    count = int(np.clip(nodes, 24, 192))
    x, w = roots_laguerre(count)
    return x.astype(float), (w * np.exp(x)).astype(float)


def _bates_probabilities_laguerre(
    strikes: np.ndarray,
    time_to_expiry: float,
    spot: float,
    risk_free_rate: float,
    dividend_yield: float,
    parameters: BatesParameters,
    quadrature_nodes: int,
) -> tuple[np.ndarray, np.ndarray]:
    strikes = np.asarray(strikes, dtype=float)
    x, weights = _laguerre_grid(quadrature_nodes)
    u = x.astype(np.complex128)
    phi_u = bates_characteristic_function(u, time_to_expiry, spot, risk_free_rate, dividend_yield, parameters)
    phi_shift = bates_characteristic_function(u - 1j, time_to_expiry, spot, risk_free_rate, dividend_yield, parameters)
    phi_minus_i = bates_characteristic_function(np.asarray([-1j]), time_to_expiry, spot, risk_free_rate, dividend_yield, parameters)[0]
    denom = 1j * u
    f2 = phi_u / denom
    f1 = (phi_shift / (phi_minus_i + 1e-32)) / denom
    phase = np.exp(-1j * np.outer(np.log(np.maximum(strikes, 1e-12)), u))
    p1 = 0.5 + np.real(phase * f1[None, :]) @ weights / math.pi
    p2 = 0.5 + np.real(phase * f2[None, :]) @ weights / math.pi
    return np.clip(p1, 0.0, 1.0), np.clip(p2, 0.0, 1.0)


def bates_call_prices(
    spot: float,
    strikes: Sequence[float],
    time_to_expiry: float,
    risk_free_rate: float,
    dividend_yield: float,
    parameters: BatesParameters | Mapping[str, float] | Sequence[float],
    quadrature_nodes: int = 64,
) -> np.ndarray:
    p = _coerce_parameters(parameters)
    k = np.asarray(strikes, dtype=float)
    t = max(float(time_to_expiry), 0.0)
    if t <= 0.0:
        return np.maximum(float(spot) - k, 0.0)
    p1, p2 = _bates_probabilities_laguerre(
        k, t, float(spot), float(risk_free_rate), float(dividend_yield), p, quadrature_nodes
    )
    calls = float(spot) * math.exp(-float(dividend_yield) * t) * p1 - k * math.exp(-float(risk_free_rate) * t) * p2
    upper = float(spot) * math.exp(-float(dividend_yield) * t)
    lower = np.maximum(upper - k * math.exp(-float(risk_free_rate) * t), 0.0)
    return np.clip(np.real(calls), lower, upper)


def bates_option_prices(
    spot: float,
    strikes: Sequence[float],
    time_to_expiry: float,
    risk_free_rate: float,
    dividend_yield: float,
    option_types: Sequence[str],
    parameters: BatesParameters | Mapping[str, float] | Sequence[float],
    quadrature_nodes: int = 64,
) -> np.ndarray:
    k = np.asarray(strikes, dtype=float)
    types = np.asarray([str(value).lower() for value in option_types], dtype=object)
    calls = bates_call_prices(spot, k, time_to_expiry, risk_free_rate, dividend_yield, parameters, quadrature_nodes)
    puts = calls - float(spot) * math.exp(-float(dividend_yield) * float(time_to_expiry)) + k * math.exp(-float(risk_free_rate) * float(time_to_expiry))
    return np.where(types == "put", np.maximum(puts, 0.0), calls)


def _bates_call_price_quad(
    spot: float,
    strike: float,
    time_to_expiry: float,
    risk_free_rate: float,
    dividend_yield: float,
    parameters: BatesParameters,
) -> float:
    log_k = math.log(max(float(strike), 1e-12))
    phi_minus_i = bates_characteristic_function(
        np.asarray([-1j]), time_to_expiry, spot, risk_free_rate, dividend_yield, parameters
    )[0]

    def integrand(u: float, shifted: bool) -> float:
        z = complex(u)
        if shifted:
            value = bates_characteristic_function(
                np.asarray([z - 1j]), time_to_expiry, spot, risk_free_rate, dividend_yield, parameters
            )[0] / (phi_minus_i + 1e-32)
        else:
            value = bates_characteristic_function(
                np.asarray([z]), time_to_expiry, spot, risk_free_rate, dividend_yield, parameters
            )[0]
        return float(np.real(np.exp(-1j * z * log_k) * value / (1j * z)))

    p1 = 0.5 + quad(lambda value: integrand(value, True), 1e-8, 160.0, epsabs=1e-8, epsrel=1e-7, limit=320)[0] / math.pi
    p2 = 0.5 + quad(lambda value: integrand(value, False), 1e-8, 160.0, epsabs=1e-8, epsrel=1e-7, limit=320)[0] / math.pi
    return float(spot * math.exp(-dividend_yield * time_to_expiry) * p1 - strike * math.exp(-risk_free_rate * time_to_expiry) * p2)


def _bounds_arrays(bounds: Mapping[str, Sequence[float]] | None = None) -> tuple[np.ndarray, np.ndarray, dict[str, tuple[float, float]]]:
    merged = {name: tuple(DEFAULT_BOUNDS[name]) for name in PARAMETER_NAMES}
    if bounds:
        for name, values in bounds.items():
            if name in merged:
                low, high = map(float, values)
                if high <= low:
                    raise ValueError(f"Invalid Bates bound for {name}.")
                merged[name] = (low, high)
    lower = np.asarray([merged[name][0] for name in PARAMETER_NAMES], dtype=float)
    upper = np.asarray([merged[name][1] for name in PARAMETER_NAMES], dtype=float)
    return lower, upper, merged


def _price_frame(
    frame: pd.DataFrame,
    spot: float,
    risk_free_rate: float,
    parameters: BatesParameters,
    quadrature_nodes: int,
) -> np.ndarray:
    output = np.empty(len(frame), dtype=float)
    for (_, maturity_group) in frame.groupby(["time_to_expiry", "effective_q"], sort=False):
        indices = maturity_group.index.to_numpy(dtype=int)
        output[indices] = bates_option_prices(
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


def _initial_starts(
    train: pd.DataFrame,
    heston_result: Mapping[str, Any],
    lower: np.ndarray,
    upper: np.ndarray,
    count: int,
    seed: int,
) -> np.ndarray:
    h = heston_result.get("parameters", {}) if isinstance(heston_result, Mapping) else {}
    atm = train.loc[train["log_moneyness"].astype(float).abs() <= 0.08, "target_iv"]
    variance = float(np.nanmedian(atm) ** 2) if len(atm) else 0.05
    base = np.asarray([
        float(h.get("kappa", 2.0)),
        float(h.get("theta", variance)),
        float(h.get("sigma_v", 0.6)),
        float(h.get("rho", -0.55)),
        float(h.get("v0", variance)),
        1.0,
        -0.08,
        0.18,
    ], dtype=float)
    base = np.clip(base, lower + 1e-6, upper - 1e-6)
    starts = [base]
    rng = np.random.default_rng(int(seed))
    anchored = min(max(int(count) - 1, 0), 3)
    for _ in range(anchored):
        perturb = np.asarray([0.25, 0.20, 0.20, 0.12, 0.20, 0.80, 0.08, 0.08])
        candidate = base * (1.0 + rng.normal(0.0, perturb))
        candidate[3] = base[3] + rng.normal(0.0, 0.12)
        candidate[6] = base[6] + rng.normal(0.0, 0.08)
        candidate[7] = abs(base[7] + rng.normal(0.0, 0.06))
        starts.append(np.clip(candidate, lower + 1e-6, upper - 1e-6))
    remaining = int(count) - len(starts)
    if remaining > 0:
        sampler = qmc.LatinHypercube(d=len(PARAMETER_NAMES), seed=int(seed) + 17)
        starts.extend(qmc.scale(sampler.random(remaining), lower, upper))
    return np.vstack(starts[: max(int(count), 1)])


def _build_residual_function(
    train: pd.DataFrame,
    spot: float,
    risk_free_rate: float,
    objective: str,
    quadrature_nodes: int,
):
    target_prices = _target_prices(train, spot, risk_free_rate)
    target_iv = train["target_iv"].to_numpy(dtype=float)
    t = train["time_to_expiry"].to_numpy(dtype=float)
    vega = np.maximum(train.get("vega_raw", pd.Series(np.ones(len(train)))).to_numpy(dtype=float), spot * 1e-5)
    weights = np.maximum(train["calibration_weight"].to_numpy(dtype=float), 0.0)
    weights = weights / max(float(np.sum(weights)), 1e-12)
    sqrt_w = np.sqrt(weights)

    def residual(values: np.ndarray) -> np.ndarray:
        p = _coerce_parameters(values)
        try:
            model_prices = _price_frame(train, spot, risk_free_rate, p, quadrature_nodes)
            linearized_iv = (model_prices - target_prices) / vega
            linearized_tv = 2.0 * np.maximum(target_iv, 0.02) * t * linearized_iv
            if objective in {"Vega-normalized price", "Linearized implied volatility"}:
                core = sqrt_w * linearized_iv
            elif objective == "Linearized total variance":
                scale = max(float(np.nanmedian(np.abs(2.0 * target_iv * t))), 1e-4)
                core = sqrt_w * linearized_tv / scale
            else:
                tv_scale = max(float(np.nanmedian(np.abs(2.0 * target_iv * t))), 1e-4)
                core = np.concatenate([
                    0.75 * sqrt_w * linearized_iv,
                    0.25 * sqrt_w * linearized_tv / tv_scale,
                ])
            if not np.isfinite(core).all():
                return np.full(core.shape, 1e3, dtype=float)
            return core
        except Exception:
            length = 2 * len(train) if objective == "Composite linearized IV + total variance" else len(train)
            return np.full(length, 1e3, dtype=float)

    return residual


def _fit_table(
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
    output["bates_price"] = model_prices
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
    output["bates_iv"] = np.asarray(fitted_iv, dtype=float)
    output["price_error"] = output["bates_price"] - output["target_price"]
    output["iv_error"] = output["bates_iv"] - output["target_iv"]
    output["target_total_variance"] = output["target_iv"] ** 2 * output["time_to_expiry"]
    output["bates_total_variance"] = output["bates_iv"] ** 2 * output["time_to_expiry"]
    output["total_variance_error"] = output["bates_total_variance"] - output["target_total_variance"]
    return output


def _metric_summary(frame: pd.DataFrame, weighted: bool) -> dict[str, float]:
    valid = frame[np.isfinite(frame["bates_iv"]) & np.isfinite(frame["iv_error"])].copy()
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
    maturity_rows: list[dict[str, Any]] = []
    for (role, expiration), group in table.groupby(["sample_role", "expiration"], sort=True):
        metrics = _metric_summary(group, weighted=(role == "TRAIN"))
        maturity_rows.append({"sample_role": role, "expiration": str(expiration), "dte": int(group["dte"].iloc[0]), **metrics})
    bucket_rows: list[dict[str, Any]] = []
    if "moneyness_bucket" in table:
        for (role, bucket), group in table.groupby(["sample_role", "moneyness_bucket"], observed=False, sort=False):
            if len(group) == 0:
                continue
            metrics = _metric_summary(group, weighted=(role == "TRAIN"))
            bucket_rows.append({"sample_role": role, "moneyness_bucket": str(bucket), **metrics})
    return pd.DataFrame(maturity_rows), pd.DataFrame(bucket_rows)

def _near_bound_flags(parameters: BatesParameters, bounds: Mapping[str, tuple[float, float]], tolerance: float = 0.015) -> list[str]:
    warnings: list[str] = []
    for name in PARAMETER_NAMES:
        value = float(getattr(parameters, name))
        low, high = bounds[name]
        position = min((value - low) / max(high - low, 1e-12), (high - value) / max(high - low, 1e-12))
        if position <= tolerance:
            warnings.append(f"{name} is within {tolerance:.1%} of a calibration bound.")
    return warnings


def _solution_stability(solutions: pd.DataFrame, best_cost: float, bounds: Mapping[str, tuple[float, float]]) -> dict[str, Any]:
    if solutions.empty:
        return {"near_optimal_solutions": 0, "maximum_normalized_range": float("nan"), "jump_maximum_normalized_range": float("nan"), "parameter_ranges": {}}
    near = solutions[solutions["cost"] <= best_cost * 1.05 + 1e-10]
    ranges: dict[str, float] = {}
    for name in PARAMETER_NAMES:
        low, high = bounds[name]
        ranges[name] = float((near[name].max() - near[name].min()) / max(high - low, 1e-12)) if len(near) else float("nan")
    jump_ranges = [ranges[name] for name in ("jump_intensity", "jump_mean", "jump_volatility")]
    return {
        "near_optimal_solutions": int(len(near)),
        "maximum_normalized_range": float(np.nanmax(list(ranges.values()))) if ranges else float("nan"),
        "jump_maximum_normalized_range": float(np.nanmax(jump_ranges)) if jump_ranges else float("nan"),
        "parameter_ranges": ranges,
    }



def _local_error_governance_bates(
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
    rows: list[dict[str, Any]] = []
    for (role, expiration, dte, bucket), group in frame.groupby(
        ["sample_role", "expiration", "dte", "moneyness_bucket"], observed=False, sort=True
    ):
        if len(group) == 0:
            continue
        errors = group["iv_error"].to_numpy(dtype=float)
        errors = errors[np.isfinite(errors)]
        if not len(errors):
            continue
        rows.append({
            "sample_role": str(role),
            "expiration": str(expiration),
            "dte": int(dte),
            "moneyness_bucket": str(bucket),
            "count": int(len(errors)),
            "mean_iv_error": float(np.mean(errors)),
            "iv_rmse": float(np.sqrt(np.mean(errors**2))),
            "max_abs_iv_error": float(np.max(np.abs(errors))),
        })
    cells = pd.DataFrame(rows)
    worst_train = float(maturity_errors.loc[maturity_errors["sample_role"] == "TRAIN", "iv_rmse"].max()) if not maturity_errors.empty and (maturity_errors["sample_role"] == "TRAIN").any() else float("nan")
    worst_holdout = float(maturity_errors.loc[maturity_errors["sample_role"] == "HOLDOUT", "iv_rmse"].max()) if not maturity_errors.empty and (maturity_errors["sample_role"] == "HOLDOUT").any() else float("nan")
    worst_bucket = float(bucket_errors["iv_rmse"].max()) if not bucket_errors.empty else float("nan")
    worst_cell_mean = float(cells["mean_iv_error"].abs().max()) if not cells.empty else float("nan")
    worst_cell_rmse = float(cells["iv_rmse"].max()) if not cells.empty else float("nan")
    shortest = cells[cells["dte"] == cells["dte"].min()] if not cells.empty else pd.DataFrame()
    wings = shortest[shortest["moneyness_bucket"].isin(["Left wing", "Right wing"])] if not shortest.empty else pd.DataFrame()
    short_wing_mean_abs = float(wings["mean_iv_error"].abs().max()) if not wings.empty else float("nan")
    if np.isfinite(worst_train):
        if worst_train > 0.080:
            blockers.append(f"Worst training-maturity IV RMSE {worst_train:.2%} exceeds the 8.0% local ceiling.")
        elif worst_train > 0.040:
            warnings.append(f"Worst training-maturity IV RMSE {worst_train:.2%} exceeds the preferred 4.0% local level.")
    if np.isfinite(worst_holdout):
        if worst_holdout > 0.100:
            blockers.append(f"Worst holdout-maturity IV RMSE {worst_holdout:.2%} exceeds the 10.0% local ceiling.")
        elif worst_holdout > 0.050:
            warnings.append(f"Worst holdout-maturity IV RMSE {worst_holdout:.2%} exceeds the preferred 5.0% local level.")
    if np.isfinite(worst_bucket) and worst_bucket > 0.050:
        warnings.append(f"At least one moneyness bucket has IV RMSE {worst_bucket:.2%}, above the preferred 5.0% level.")
    if np.isfinite(worst_cell_mean):
        if worst_cell_mean > 0.100:
            blockers.append(f"A maturity/moneyness cell has mean IV bias {worst_cell_mean:.2%}, above the 10.0% ceiling.")
        elif worst_cell_mean > 0.050:
            warnings.append(f"A maturity/moneyness cell has mean IV bias {worst_cell_mean:.2%}, indicating a systematic local miss.")
    if np.isfinite(short_wing_mean_abs) and short_wing_mean_abs > 0.050:
        warnings.append(f"The shortest-maturity Bates wing bias reaches {short_wing_mean_abs:.2%}; jumps have not fully resolved the front-end wings.")
    return cells, {
        "worst_training_maturity_iv_rmse": worst_train,
        "worst_holdout_maturity_iv_rmse": worst_holdout,
        "worst_bucket_iv_rmse": worst_bucket,
        "worst_cell_mean_abs_iv_error": worst_cell_mean,
        "worst_cell_iv_rmse": worst_cell_rmse,
        "shortest_maturity_wing_mean_abs_iv_error": short_wing_mean_abs,
    }, warnings, blockers

def _front_wing_metric(table: pd.DataFrame) -> float:
    if not isinstance(table, pd.DataFrame) or table.empty:
        return float("nan")
    frame = table.copy()
    shortest = int(frame["dte"].min())
    role = "HOLDOUT" if np.any(frame["sample_role"].astype(str) == "HOLDOUT") else "TRAIN"
    subset = frame[
        (frame["dte"].astype(int) == shortest)
        & (frame["sample_role"].astype(str) == role)
        & (frame["moneyness_bucket"].astype(str).isin(["Left wing", "Right wing"]))
    ]
    if subset.empty:
        subset = frame[(frame["dte"].astype(int) == shortest) & (frame["moneyness_bucket"].astype(str).isin(["Left wing", "Right wing"]))]
    errors = subset["iv_error"].to_numpy(dtype=float)
    errors = errors[np.isfinite(errors)]
    return float(np.sqrt(np.mean(errors**2))) if len(errors) else float("nan")


def _heston_front_wing_metric(heston_result: Mapping[str, Any]) -> float:
    table = heston_result.get("fit_table") if isinstance(heston_result, Mapping) else None
    if not isinstance(table, pd.DataFrame) or table.empty:
        return float("nan")
    frame = table.copy()
    if "iv_error" not in frame and "heston_iv" in frame:
        frame["iv_error"] = frame["heston_iv"] - frame["target_iv"]
    return _front_wing_metric(frame)


def _other_maturity_degradation_diagnostics(
    heston_result: Mapping[str, Any],
    bates_maturity_errors: pd.DataFrame,
) -> dict[str, Any]:
    """Compare non-front maturities on the most relevant common sample role.

    V2.7.0 used the maximum *relative* deterioration across both TRAIN and
    HOLDOUT rows. That gate was too brittle: a tiny absolute change on a low
    Heston RMSE could create a large percentage deterioration, and a training
    cell could override materially better out-of-sample performance. The
    governed comparison now prioritizes HOLDOUT when available, reports both
    relative and absolute changes, and preserves the full audit table.
    """

    heston_maturity = heston_result.get("maturity_errors") if isinstance(heston_result, Mapping) else None
    empty = {
        "sample_role": None,
        "comparison_table": pd.DataFrame(),
        "maximum_relative_degradation": float("nan"),
        "maximum_absolute_degradation": float("nan"),
        "weighted_mean_relative_degradation": float("nan"),
        "weighted_mean_absolute_degradation": float("nan"),
        "degraded_maturity_count": 0,
    }
    if not isinstance(heston_maturity, pd.DataFrame) or heston_maturity.empty or bates_maturity_errors.empty:
        return empty

    shortest = min(int(heston_maturity["dte"].min()), int(bates_maturity_errors["dte"].min()))
    h = heston_maturity[heston_maturity["dte"].astype(int) > shortest].copy()
    b = bates_maturity_errors[bates_maturity_errors["dte"].astype(int) > shortest].copy()
    if h.empty or b.empty:
        return empty

    common_roles = set(h["sample_role"].astype(str)) & set(b["sample_role"].astype(str))
    role = "HOLDOUT" if "HOLDOUT" in common_roles else ("TRAIN" if "TRAIN" in common_roles else None)
    if role is None:
        return empty

    h = h[h["sample_role"].astype(str) == role]
    b = b[b["sample_role"].astype(str) == role]
    h_cols = [column for column in ("expiration", "dte", "count", "iv_rmse") if column in h.columns]
    b_cols = [column for column in ("expiration", "dte", "count", "iv_rmse") if column in b.columns]
    h = h[h_cols].rename(columns={"count": "heston_count", "iv_rmse": "heston_iv_rmse"})
    b = b[b_cols].rename(columns={"count": "bates_count", "iv_rmse": "bates_iv_rmse"})
    merge_keys = [key for key in ("expiration", "dte") if key in h.columns and key in b.columns]
    if not merge_keys:
        return empty
    merged = h.merge(b, on=merge_keys, how="inner")
    if merged.empty:
        return empty

    merged["absolute_degradation"] = merged["bates_iv_rmse"] - merged["heston_iv_rmse"]
    merged["relative_degradation"] = merged["absolute_degradation"] / np.maximum(
        merged["heston_iv_rmse"].astype(float), 1e-8
    )
    if "bates_count" in merged:
        weights = np.maximum(merged["bates_count"].to_numpy(dtype=float), 1.0)
    elif "heston_count" in merged:
        weights = np.maximum(merged["heston_count"].to_numpy(dtype=float), 1.0)
    else:
        weights = np.ones(len(merged), dtype=float)
    weights = weights / max(float(np.sum(weights)), 1e-12)
    rel = merged["relative_degradation"].to_numpy(dtype=float)
    absolute = merged["absolute_degradation"].to_numpy(dtype=float)
    finite_rel = rel[np.isfinite(rel)]
    finite_abs = absolute[np.isfinite(absolute)]

    return {
        "sample_role": role,
        "comparison_table": merged,
        "maximum_relative_degradation": float(np.max(finite_rel)) if len(finite_rel) else float("nan"),
        "maximum_absolute_degradation": float(np.max(finite_abs)) if len(finite_abs) else float("nan"),
        "weighted_mean_relative_degradation": float(np.nansum(weights * rel)),
        "weighted_mean_absolute_degradation": float(np.nansum(weights * absolute)),
        "degraded_maturity_count": int(np.sum(np.isfinite(absolute) & (absolute > 0.0))),
    }


def _pseudo_information_criteria(iv_errors: np.ndarray, parameter_count: int) -> tuple[float, float]:
    errors = np.asarray(iv_errors, dtype=float)
    errors = errors[np.isfinite(errors)]
    n = len(errors)
    if n <= parameter_count or n == 0:
        return float("nan"), float("nan")
    sse = max(float(np.sum(errors**2)), 1e-16)
    base = n * math.log(sse / n)
    return float(base + 2.0 * parameter_count), float(base + parameter_count * math.log(n))


def _numerical_crosscheck(
    fit_table: pd.DataFrame,
    parameters: BatesParameters,
    spot: float,
    risk_free_rate: float,
    quadrature_nodes: int,
    points: int,
) -> pd.DataFrame:
    if fit_table.empty or points <= 0:
        return pd.DataFrame()
    selected = np.unique(np.round(np.linspace(0, len(fit_table) - 1, min(points, len(fit_table)))).astype(int))
    rows: list[dict[str, Any]] = []
    for position in selected:
        row = fit_table.iloc[int(position)]
        laguerre = float(bates_call_prices(
            spot,
            [float(row["strike"])],
            float(row["time_to_expiry"]),
            risk_free_rate,
            float(row["effective_q"]),
            parameters,
            quadrature_nodes,
        )[0])
        adaptive = _bates_call_price_quad(
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
            "laguerre_call": laguerre,
            "adaptive_quad_call": adaptive,
            "absolute_difference": abs(laguerre - adaptive),
        })
    return pd.DataFrame(rows)


def _champion_decision(
    heston_result: Mapping[str, Any],
    bates_result: Mapping[str, Any],
    settings: BatesCalibrationSettings,
) -> tuple[str, dict[str, Any], list[str], pd.DataFrame]:
    notes: list[str] = []
    h_train = float(heston_result.get("train_metrics", {}).get("iv_rmse", np.nan))
    h_holdout = float(heston_result.get("holdout_metrics", {}).get("iv_rmse", np.nan))
    b_train = float(bates_result.get("train_metrics", {}).get("iv_rmse", np.nan))
    b_holdout = float(bates_result.get("holdout_metrics", {}).get("iv_rmse", np.nan))
    h_front = _heston_front_wing_metric(heston_result)
    b_front = float(bates_result.get("front_wing_iv_rmse", np.nan))
    holdout_improvement = float((h_holdout - b_holdout) / max(h_holdout, 1e-12)) if np.isfinite(h_holdout) and np.isfinite(b_holdout) else float("nan")
    train_improvement = float((h_train - b_train) / max(h_train, 1e-12)) if np.isfinite(h_train) and np.isfinite(b_train) else float("nan")
    front_improvement = float((h_front - b_front) / max(h_front, 1e-12)) if np.isfinite(h_front) and np.isfinite(b_front) else float("nan")

    degradation = bates_result.get("other_maturity_degradation", {})
    other_relative = float(degradation.get("maximum_relative_degradation", np.nan)) if isinstance(degradation, Mapping) else float("nan")
    other_absolute = float(degradation.get("maximum_absolute_degradation", np.nan)) if isinstance(degradation, Mapping) else float("nan")
    other_weighted_relative = float(degradation.get("weighted_mean_relative_degradation", np.nan)) if isinstance(degradation, Mapping) else float("nan")
    other_weighted_absolute = float(degradation.get("weighted_mean_absolute_degradation", np.nan)) if isinstance(degradation, Mapping) else float("nan")
    other_role = degradation.get("sample_role") if isinstance(degradation, Mapping) else None

    h_fit = heston_result.get("fit_table")
    b_fit = bates_result.get("fit_table")
    h_train_errors = h_fit.loc[h_fit["sample_role"] == "TRAIN", "iv_error"].to_numpy(dtype=float) if isinstance(h_fit, pd.DataFrame) and not h_fit.empty else np.asarray([])
    b_train_errors = b_fit.loc[b_fit["sample_role"] == "TRAIN", "iv_error"].to_numpy(dtype=float) if isinstance(b_fit, pd.DataFrame) and not b_fit.empty else np.asarray([])
    h_aic, h_bic = _pseudo_information_criteria(h_train_errors, 5)
    b_aic, b_bic = _pseudo_information_criteria(b_train_errors, 8)
    aic_delta = float(h_aic - b_aic) if np.isfinite(h_aic) and np.isfinite(b_aic) else float("nan")
    bic_delta = float(h_bic - b_bic) if np.isfinite(h_bic) and np.isfinite(b_bic) else float("nan")
    parameters = bates_result.get("parameters", {})
    jump_intensity = float(parameters.get("jump_intensity", np.nan))
    jump_mean = float(parameters.get("jump_mean", np.nan))
    jump_vol = float(parameters.get("jump_volatility", np.nan))
    jump_material = bool(np.isfinite(jump_intensity) and jump_intensity > 0.05 and (abs(jump_mean) > 0.01 or jump_vol > 0.03))
    jump_dispersion = float(bates_result.get("solution_stability", {}).get("jump_maximum_normalized_range", np.inf))
    jump_stable = bool(np.isfinite(jump_dispersion) and jump_dispersion <= 0.35)
    near_jump_bound = any(
        str(warning).startswith(name + " ")
        for warning in bates_result.get("warnings", [])
        for name in ("jump_intensity", "jump_mean", "jump_volatility")
    )

    material_holdout = bool(np.isfinite(holdout_improvement) and holdout_improvement >= settings.minimum_holdout_improvement)
    material_front = bool(np.isfinite(front_improvement) and front_improvement >= settings.minimum_front_wing_improvement)
    relative_control = (not np.isfinite(other_relative)) or other_relative <= settings.maximum_other_maturity_degradation
    absolute_control = (not np.isfinite(other_absolute)) or other_absolute <= settings.maximum_other_maturity_absolute_degradation
    # A non-front maturity is treated as materially degraded only when both the
    # relative and absolute tolerances are breached. This prevents a small
    # absolute miss on a low-RMSE maturity from dominating the full decision.
    controlled_elsewhere = bool(relative_control or absolute_control)
    complexity_ok = bool((not settings.require_bic_improvement) or (np.isfinite(bic_delta) and bic_delta > 0.0))
    eligible = bool(bates_result.get("ok", False) and bates_result.get("status") not in {"FAILED", "INELIGIBLE"})

    metrics: dict[str, Any] = {
        "train_improvement": train_improvement,
        "holdout_improvement": holdout_improvement,
        "front_wing_improvement": front_improvement,
        "maximum_other_maturity_degradation": other_relative,  # compatibility alias
        "maximum_other_maturity_relative_degradation": other_relative,
        "maximum_other_maturity_absolute_degradation": other_absolute,
        "weighted_mean_other_maturity_relative_degradation": other_weighted_relative,
        "weighted_mean_other_maturity_absolute_degradation": other_weighted_absolute,
        "other_maturity_comparison_role": other_role,
        "heston_aic": h_aic,
        "bates_aic": b_aic,
        "aic_delta_heston_minus_bates": aic_delta,
        "heston_bic": h_bic,
        "bates_bic": b_bic,
        "bic_delta_heston_minus_bates": bic_delta,
        "heston_front_wing_iv_rmse": h_front,
        "bates_front_wing_iv_rmse": b_front,
        "jump_material": jump_material,
        "jump_stable": jump_stable,
        "jump_dispersion": jump_dispersion,
        "near_jump_bound": near_jump_bound,
        "material_holdout": material_holdout,
        "material_front": material_front,
        "controlled_elsewhere": controlled_elsewhere,
        "complexity_ok": complexity_ok,
        "eligible": eligible,
    }

    gate_rows = [
        {
            "gate": "Bates calibration eligibility",
            "observed": str(bates_result.get("status", "FAILED")),
            "threshold": "PASS or WARNING",
            "passed": eligible,
            "detail": "Calibration and numerical pricing gate",
        },
        {
            "gate": "Holdout IV RMSE improvement",
            "observed": holdout_improvement,
            "threshold": settings.minimum_holdout_improvement,
            "passed": material_holdout,
            "detail": "Out-of-sample improvement versus Heston",
        },
        {
            "gate": "Front-wing IV RMSE improvement",
            "observed": front_improvement,
            "threshold": settings.minimum_front_wing_improvement,
            "passed": material_front,
            "detail": "Shortest-maturity left/right-wing improvement",
        },
        {
            "gate": "Other-maturity relative degradation",
            "observed": other_relative,
            "threshold": settings.maximum_other_maturity_degradation,
            "passed": relative_control,
            "detail": f"Maximum on {other_role or 'available'} non-front maturities",
        },
        {
            "gate": "Other-maturity absolute degradation",
            "observed": other_absolute,
            "threshold": settings.maximum_other_maturity_absolute_degradation,
            "passed": absolute_control,
            "detail": "Maximum absolute IV-RMSE deterioration; relative OR absolute control is sufficient",
        },
        {
            "gate": "Pseudo-BIC improvement",
            "observed": bic_delta,
            "threshold": 0.0,
            "passed": complexity_ok,
            "detail": "Positive Heston minus Bates pseudo-BIC favors Bates",
        },
        {
            "gate": "Material jump component",
            "observed": jump_intensity,
            "threshold": 0.05,
            "passed": jump_material,
            "detail": "Intensity plus non-trivial jump mean or volatility",
        },
        {
            "gate": "Jump-parameter stability",
            "observed": jump_dispersion,
            "threshold": 0.35,
            "passed": jump_stable,
            "detail": "Maximum normalized range across near-optimal jump parameters",
        },
        {
            "gate": "Jump parameters away from bounds",
            "observed": not near_jump_bound,
            "threshold": True,
            "passed": not near_jump_bound,
            "detail": "No jump parameter within the governed bound tolerance",
        },
    ]
    gate_table = pd.DataFrame(gate_rows)

    failed_gates = gate_table.loc[~gate_table["passed"].astype(bool), "gate"].astype(str).tolist()
    if not eligible:
        return "BATES_REJECTED", metrics, ["Bates calibration failed the model eligibility gate."], gate_table
    if np.isfinite(holdout_improvement) and holdout_improvement <= -0.05:
        return "HESTON_CHAMPION", metrics, ["Bates materially worsens holdout IV RMSE."], gate_table
    if np.isfinite(bic_delta) and bic_delta < -5.0:
        return "HESTON_CHAMPION", metrics, ["The Bates fit improvement does not compensate for its three additional parameters under pseudo-BIC."], gate_table

    if material_holdout and material_front and controlled_elsewhere and complexity_ok and jump_material and jump_stable and not near_jump_bound:
        notes.append("Bates clears the holdout, front-wing, non-front-maturity, complexity and jump-identification gates.")
        return "BATES_CHAMPION", metrics, notes, gate_table

    if material_holdout and material_front and not controlled_elsewhere:
        notes.append(
            "Bates materially improves holdout and front wings, but at least one non-front holdout maturity breaches both the relative and absolute degradation tolerances."
        )
        return "BATES_RESEARCH_ONLY", metrics, notes, gate_table

    if (material_holdout or material_front) and (not jump_stable or near_jump_bound or not complexity_ok or not jump_material):
        notes.append("Bates improves part of the fit, but jump identification or complexity governance is insufficient for champion status.")
        return "BATES_RESEARCH_ONLY", metrics, notes, gate_table

    if np.isfinite(holdout_improvement) and holdout_improvement < 0.02 and np.isfinite(front_improvement) and front_improvement < 0.05:
        notes.append("Bates does not deliver a material out-of-sample or front-wing improvement.")
        return "HESTON_CHAMPION", metrics, notes, gate_table

    if failed_gates:
        notes.append("Champion selection remains inconclusive because these gates did not pass: " + ", ".join(failed_gates) + ".")
    else:
        notes.append("Champion selection is mixed despite all recorded gates; inspect the raw audit.")
    return "INCONCLUSIVE", metrics, notes, gate_table


def calibrate_bates(
    dataset_result: Mapping[str, Any],
    heston_result: Mapping[str, Any],
    objective: str = "Composite linearized IV + total variance",
    multi_start: int = 8,
    max_nfev: int = 260,
    quadrature_nodes: int = 64,
    seed: int = 42,
    bounds: Mapping[str, Sequence[float]] | None = None,
    numerical_crosscheck_points: int = 6,
    numerical_crosscheck_tolerance: float = 3.5e-3,
    minimum_holdout_improvement: float = 0.10,
    minimum_front_wing_improvement: float = 0.20,
    maximum_other_maturity_degradation: float = 0.15,
    maximum_other_maturity_absolute_degradation: float = 0.0035,
    require_bic_improvement: bool = True,
) -> dict[str, Any]:
    if objective not in HESTON_OBJECTIVES:
        return {"ok": False, "status": "FAILED", "champion_status": "BATES_REJECTED", "reason": f"Unsupported Bates objective: {objective}"}
    if not isinstance(heston_result, Mapping) or not heston_result.get("parameters"):
        return {"ok": False, "status": "FAILED", "champion_status": "BATES_REJECTED", "reason": "A completed Heston calibration is required as the continuous-model benchmark."}
    try:
        train, holdout, spot, risk_free_rate = _prepare_dataset(dataset_result)
    except Exception as exc:
        return {"ok": False, "status": "FAILED", "champion_status": "BATES_REJECTED", "reason": str(exc)}

    settings = BatesCalibrationSettings(
        objective=str(objective),
        multi_start=int(multi_start),
        max_nfev=int(max_nfev),
        quadrature_nodes=int(quadrature_nodes),
        seed=int(seed),
        numerical_crosscheck_points=int(numerical_crosscheck_points),
        numerical_crosscheck_tolerance=float(numerical_crosscheck_tolerance),
        minimum_holdout_improvement=float(minimum_holdout_improvement),
        minimum_front_wing_improvement=float(minimum_front_wing_improvement),
        maximum_other_maturity_degradation=float(maximum_other_maturity_degradation),
        maximum_other_maturity_absolute_degradation=float(maximum_other_maturity_absolute_degradation),
        require_bic_improvement=bool(require_bic_improvement),
    )
    lower, upper, bound_map = _bounds_arrays(bounds)
    starts = _initial_starts(train, heston_result, lower, upper, settings.multi_start, settings.seed)
    residual = _build_residual_function(train, spot, risk_free_rate, settings.objective, settings.quadrature_nodes)

    rows: list[dict[str, Any]] = []
    best: tuple[float, Any] | None = None
    for index, start in enumerate(starts):
        try:
            fit = least_squares(
                residual,
                x0=start,
                bounds=(lower, upper),
                method="trf",
                max_nfev=settings.max_nfev,
                xtol=1e-8,
                ftol=1e-8,
                gtol=1e-8,
                x_scale="jac",
            )
            cost = float(2.0 * fit.cost / max(len(fit.fun), 1))
            row = {
                "start_id": index + 1,
                "success": bool(fit.success),
                "cost": cost,
                "optimality": float(fit.optimality),
                "nfev": int(fit.nfev),
                "message": str(fit.message),
                **{name: float(value) for name, value in zip(PARAMETER_NAMES, fit.x)},
            }
            rows.append(row)
            if np.isfinite(cost) and (best is None or cost < best[0]):
                best = (cost, fit)
        except Exception as exc:
            rows.append({
                "start_id": index + 1,
                "success": False,
                "cost": float("inf"),
                "optimality": float("nan"),
                "nfev": 0,
                "message": str(exc),
                **{name: float("nan") for name in PARAMETER_NAMES},
            })

    solutions = pd.DataFrame(rows).sort_values("cost", na_position="last").reset_index(drop=True)
    if best is None:
        return {"ok": False, "status": "FAILED", "champion_status": "BATES_REJECTED", "reason": "All Bates multi-start optimizations failed.", "multi_start_solutions": solutions}
    best_cost, best_fit = best
    if best_cost > 0.0:
        solutions["relative_cost_bps"] = (solutions["cost"] / best_cost - 1.0) * 10_000.0
    else:
        solutions["relative_cost_bps"] = np.nan

    parameters = _coerce_parameters(best_fit.x)
    train_targets = _target_prices(train, spot, risk_free_rate)
    train_prices = _price_frame(train, spot, risk_free_rate, parameters, settings.quadrature_nodes)
    holdout_targets = _target_prices(holdout, spot, risk_free_rate) if len(holdout) else np.asarray([], dtype=float)
    holdout_prices = _price_frame(holdout, spot, risk_free_rate, parameters, settings.quadrature_nodes) if len(holdout) else np.asarray([], dtype=float)
    train_fit = _fit_table(train, train_prices, train_targets, spot, risk_free_rate, "TRAIN")
    holdout_fit = _fit_table(holdout, holdout_prices, holdout_targets, spot, risk_free_rate, "HOLDOUT") if len(holdout) else pd.DataFrame(columns=train_fit.columns)
    fit_table = pd.concat([train_fit, holdout_fit], ignore_index=True, sort=False)
    train_metrics = _metric_summary(train_fit, weighted=True)
    holdout_metrics = _metric_summary(holdout_fit, weighted=False) if len(holdout_fit) else {"count": 0, "iv_rmse": float("nan"), "tv_rmse": float("nan"), "price_rmse": float("nan"), "mean_abs_iv_error": float("nan")}
    maturity_errors, bucket_errors = _error_breakdown(fit_table)
    local_error_table, local_error_summary, local_warnings, local_blockers = _local_error_governance_bates(fit_table, maturity_errors, bucket_errors)
    front_wing_iv_rmse = _front_wing_metric(fit_table)
    other_maturity_degradation = _other_maturity_degradation_diagnostics(heston_result, maturity_errors)
    stability = _solution_stability(solutions, best_cost, bound_map)
    crosscheck = _numerical_crosscheck(train_fit.sort_values(["time_to_expiry", "strike"]), parameters, spot, risk_free_rate, settings.quadrature_nodes, settings.numerical_crosscheck_points)
    max_crosscheck_error = float(crosscheck["absolute_difference"].max()) if not crosscheck.empty else float("nan")
    feller_ratio = float(2.0 * parameters.kappa * parameters.theta / max(parameters.sigma_v**2, 1e-12))

    warnings: list[str] = []
    blockers: list[str] = []
    if not bool(best_fit.success):
        blockers.append(f"Best Bates optimization did not report convergence: {best_fit.message}")
    if not np.isfinite(train_metrics["iv_rmse"]):
        blockers.append("Training implied-volatility errors could not be computed.")
    elif train_metrics["iv_rmse"] > 0.050:
        blockers.append(f"Training IV RMSE {train_metrics['iv_rmse']:.2%} exceeds the 5.0% ceiling.")
    elif train_metrics["iv_rmse"] > 0.030:
        warnings.append(f"Training IV RMSE {train_metrics['iv_rmse']:.2%} exceeds the preferred 3.0% level.")
    if np.isfinite(holdout_metrics["iv_rmse"]):
        if holdout_metrics["iv_rmse"] > 0.070:
            blockers.append(f"Holdout IV RMSE {holdout_metrics['iv_rmse']:.2%} exceeds the 7.0% ceiling.")
        elif holdout_metrics["iv_rmse"] > 0.045:
            warnings.append(f"Holdout IV RMSE {holdout_metrics['iv_rmse']:.2%} exceeds the preferred 4.5% level.")
    if feller_ratio < 0.98:
        warnings.append(f"Feller condition is violated (ratio {feller_ratio:.3f}); pricing remains valid but variance can reach zero.")
    warnings.extend(_near_bound_flags(parameters, bound_map))
    warnings.extend(local_warnings)
    blockers.extend(local_blockers)
    if stability["near_optimal_solutions"] >= 2 and stability["jump_maximum_normalized_range"] > 0.35:
        warnings.append("Near-optimal Bates solutions show weak identification of jump intensity or jump-size parameters.")
    if parameters.jump_intensity < 0.05:
        warnings.append("Jump intensity is close to zero; Bates effectively collapses toward the continuous Heston benchmark.")
    if np.isfinite(max_crosscheck_error) and max_crosscheck_error > settings.numerical_crosscheck_tolerance:
        blockers.append(f"Pricing cross-check error {max_crosscheck_error:.6f} exceeds tolerance {settings.numerical_crosscheck_tolerance:.6f}.")
    elif np.isfinite(max_crosscheck_error) and max_crosscheck_error > settings.numerical_crosscheck_tolerance * 0.40:
        warnings.append("Pricing cross-check is within tolerance but above the preferred numerical margin.")

    status = "INELIGIBLE" if blockers else ("WARNING" if warnings else "PASS")
    provisional = {
        "ok": not bool(blockers),
        "status": status,
        "train_metrics": train_metrics,
        "holdout_metrics": holdout_metrics,
        "fit_table": fit_table,
        "maturity_errors": maturity_errors,
        "front_wing_iv_rmse": front_wing_iv_rmse,
        "maximum_other_maturity_degradation": other_maturity_degradation.get("maximum_relative_degradation"),
        "other_maturity_degradation": other_maturity_degradation,
        "parameters": asdict(parameters),
        "solution_stability": stability,
        "warnings": warnings,
    }
    champion_status, comparison_metrics, champion_notes, champion_gate_table = _champion_decision(heston_result, provisional, settings)
    if champion_status == "BATES_RESEARCH_ONLY":
        warnings.extend(champion_notes)
    if champion_status == "BATES_REJECTED" and not blockers:
        warnings.extend(champion_notes)

    comparison_table = pd.DataFrame([
        {
            "model": "Heston",
            "parameter_count": 5,
            "train_iv_rmse": float(heston_result.get("train_metrics", {}).get("iv_rmse", np.nan)),
            "holdout_iv_rmse": float(heston_result.get("holdout_metrics", {}).get("iv_rmse", np.nan)),
            "front_wing_iv_rmse": comparison_metrics["heston_front_wing_iv_rmse"],
            "pseudo_aic": comparison_metrics["heston_aic"],
            "pseudo_bic": comparison_metrics["heston_bic"],
        },
        {
            "model": "Bates",
            "parameter_count": 8,
            "train_iv_rmse": train_metrics["iv_rmse"],
            "holdout_iv_rmse": holdout_metrics["iv_rmse"],
            "front_wing_iv_rmse": front_wing_iv_rmse,
            "pseudo_aic": comparison_metrics["bates_aic"],
            "pseudo_bic": comparison_metrics["bates_bic"],
        },
    ])

    parameter_table = pd.DataFrame([
        {
            "parameter": name,
            "estimate": float(getattr(parameters, name)),
            "lower_bound": float(bound_map[name][0]),
            "upper_bound": float(bound_map[name][1]),
            "near_bound": any(str(warning).startswith(name + " ") for warning in warnings),
        }
        for name in PARAMETER_NAMES
    ])
    jump_compensator = _jump_compensator(parameters)
    jump_expected_return = float(math.exp(parameters.jump_mean + 0.5 * parameters.jump_volatility**2) - 1.0)
    signature = _signature({
        "version": BATES_CALIBRATION_VERSION,
        "dataset_signature": dataset_result.get("configuration_signature"),
        "heston_signature": heston_result.get("configuration_signature"),
        "settings": asdict(settings),
        "bounds": bound_map,
        "parameters": asdict(parameters),
        "champion_status": champion_status,
    })

    return {
        "ok": not bool(blockers),
        "status": status,
        "version": BATES_CALIBRATION_VERSION,
        "configuration_signature": signature,
        "dataset_signature": dataset_result.get("configuration_signature"),
        "heston_signature": heston_result.get("configuration_signature"),
        "settings": asdict(settings),
        "bounds": bound_map,
        "spot": spot,
        "risk_free_rate": risk_free_rate,
        "parameters": asdict(parameters),
        "parameter_table": parameter_table,
        "jump_compensator": jump_compensator,
        "expected_jump_return": jump_expected_return,
        "expected_jumps_30d": float(parameters.jump_intensity * 30.0 / 365.0),
        "expected_jumps_1y": float(parameters.jump_intensity),
        "feller_ratio": feller_ratio,
        "train_metrics": train_metrics,
        "holdout_metrics": holdout_metrics,
        "fit_table": fit_table,
        "maturity_errors": maturity_errors,
        "moneyness_errors": bucket_errors,
        "local_error_table": local_error_table,
        "local_error_summary": local_error_summary,
        "front_wing_iv_rmse": front_wing_iv_rmse,
        "maximum_other_maturity_degradation": other_maturity_degradation.get("maximum_relative_degradation"),
        "other_maturity_degradation": other_maturity_degradation,
        "other_maturity_comparison": other_maturity_degradation.get("comparison_table", pd.DataFrame()),
        "multi_start_solutions": solutions,
        "solution_stability": stability,
        "numerical_crosscheck": crosscheck,
        "maximum_crosscheck_error": max_crosscheck_error,
        "champion_status": champion_status,
        "champion_comparison": comparison_metrics,
        "champion_gate_table": champion_gate_table,
        "champion_notes": champion_notes,
        "comparison_table": comparison_table,
        "warnings": list(dict.fromkeys(warnings)),
        "blockers": list(dict.fromkeys(blockers)),
        "governance": {
            "measure": "Bates is calibrated under Q to the same frozen option-implied dataset used by Heston.",
            "comparison": "Heston and Bates use identical training, holdout, weights, carry curve and numerical pricing conventions.",
            "complexity": "Bates adds jump intensity, mean jump and jump volatility; champion selection penalizes the extra parameters.",
            "holdout": "Champion status requires material holdout and front-wing improvement, not merely lower training error.",
            "identifiability": "Near-optimal multi-start solutions are retained to assess jump-parameter identification.",
            "prohibition": "Bates Q probabilities are pricing quantities and do not enter the validated P-measure ensemble.",
        },
    }
