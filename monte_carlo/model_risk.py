from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

from .heston_calibration import (
    DEFAULT_BOUNDS as HESTON_DEFAULT_BOUNDS,
    PARAMETER_NAMES as HESTON_PARAMETER_NAMES,
    _bounds_arrays as _heston_bounds_arrays,
    _build_residual_function as _heston_residual_function,
    _coerce_parameters as _coerce_heston,
)
from .bates_calibration import (
    DEFAULT_BOUNDS as BATES_DEFAULT_BOUNDS,
    PARAMETER_NAMES as BATES_PARAMETER_NAMES,
    _bounds_arrays as _bates_bounds_arrays,
    _build_residual_function as _bates_residual_function,
    _coerce_parameters as _coerce_bates,
)

MODEL_RISK_VERSION = "MODEL-RISK-GOVERNANCE-FINISHING-2.8.1A"
MODEL_RISK_STATUSES = ("PRODUCTION_ELIGIBLE", "RESEARCH_ONLY", "INELIGIBLE", "FAILED")


@dataclass(frozen=True)
class ModelRiskSettings:
    bootstrap_draws: int = 20
    bootstrap_confidence: float = 0.95
    max_nfev_per_draw: int = 80
    quadrature_nodes: int = 48
    seed: int = 42
    run_maturity_jackknife: bool = True
    profile_grid_points: int = 7
    profile_span_fraction: float = 0.20
    minimum_bootstrap_success_rate: float = 0.80
    production_bates_selection_probability: float = 0.70
    maximum_normalized_interval_width: float = 0.60
    maximum_maturity_sensitivity: float = 0.35
    minimum_production_bootstrap_draws: int = 40
    bound_proximity_fraction: float = 0.01
    condition_number_warning: float = 1.0e8
    condition_number_block: float = 1.0e12


def _signature(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(payload), sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16].upper()


def _validate_inputs(
    dataset_result: Mapping[str, Any],
    heston_result: Mapping[str, Any],
    bates_result: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, float, float]:
    if not isinstance(dataset_result, Mapping) or not dataset_result.get("ok"):
        raise ValueError("A completed governed calibration dataset is required.")
    if not isinstance(heston_result, Mapping) or not heston_result.get("parameters"):
        raise ValueError("A completed Heston calibration is required.")
    if not isinstance(bates_result, Mapping) or not bates_result.get("parameters"):
        raise ValueError("A completed Bates calibration is required.")
    train = dataset_result.get("training_dataset")
    holdout = dataset_result.get("holdout_dataset")
    if not isinstance(train, pd.DataFrame) or train.empty:
        raise ValueError("The governed training dataset is empty.")
    holdout = holdout.copy() if isinstance(holdout, pd.DataFrame) else pd.DataFrame(columns=train.columns)
    required = {
        "strike", "time_to_expiry", "effective_q", "target_iv", "option_type",
        "calibration_weight", "expiration",
    }
    missing = required.difference(train.columns)
    if missing:
        raise ValueError(f"Model-risk dataset is missing columns: {sorted(missing)}")
    spot = float(dataset_result.get("spot", heston_result.get("spot", np.nan)))
    risk_free_rate = float(dataset_result.get("risk_free_rate", heston_result.get("risk_free_rate", np.nan)))
    if not np.isfinite(spot) or spot <= 0.0:
        raise ValueError("A valid spot price is required for model-risk diagnostics.")
    if not np.isfinite(risk_free_rate):
        raise ValueError("A valid risk-free rate is required for model-risk diagnostics.")
    return train.reset_index(drop=True), holdout.reset_index(drop=True), spot, risk_free_rate


def _normalize_weights(frame: pd.DataFrame, *, equal_if_zero: bool = True) -> pd.DataFrame:
    output = frame.copy().reset_index(drop=True)
    weights = pd.to_numeric(output.get("calibration_weight", 0.0), errors="coerce").fillna(0.0).to_numpy(dtype=float)
    weights = np.maximum(weights, 0.0)
    if float(np.sum(weights)) <= 0.0 and equal_if_zero and len(output):
        weights = np.ones(len(output), dtype=float)
    if len(output):
        weights /= max(float(np.sum(weights)), 1e-12)
    output["calibration_weight"] = weights
    return output


def _stratified_bootstrap(train: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    sampled: list[pd.DataFrame] = []
    for _, group in train.groupby("expiration", sort=False):
        indices = rng.integers(0, len(group), size=len(group))
        sampled.append(group.iloc[indices].copy())
    if not sampled:
        return train.copy().reset_index(drop=True)
    return _normalize_weights(pd.concat(sampled, ignore_index=True))


def _fit_local(
    model: str,
    train: pd.DataFrame,
    start: Sequence[float],
    spot: float,
    risk_free_rate: float,
    objective: str,
    quadrature_nodes: int,
    max_nfev: int,
    bounds: Mapping[str, Sequence[float]],
) -> dict[str, Any]:
    if model == "Heston":
        lower, upper, bound_map = _heston_bounds_arrays(bounds)
        residual = _heston_residual_function(
            train,
            spot,
            risk_free_rate,
            objective,
            quadrature_nodes,
            "No penalty",
            0.0,
        )
        parameter_names = HESTON_PARAMETER_NAMES
    elif model == "Bates":
        lower, upper, bound_map = _bates_bounds_arrays(bounds)
        residual = _bates_residual_function(train, spot, risk_free_rate, objective, quadrature_nodes)
        parameter_names = BATES_PARAMETER_NAMES
    else:
        raise ValueError(f"Unsupported model: {model}")

    x0 = np.asarray(start, dtype=float)
    x0 = np.clip(x0, lower + 1e-8, upper - 1e-8)
    fit = least_squares(
        residual,
        x0=x0,
        bounds=(lower, upper),
        method="trf",
        max_nfev=max(int(max_nfev), 10),
        xtol=1e-7,
        ftol=1e-7,
        gtol=1e-7,
        x_scale="jac",
    )
    errors = np.asarray(fit.fun, dtype=float)
    cost = float(np.mean(errors * errors)) if errors.size and np.isfinite(errors).all() else float("inf")
    return {
        "success": bool(fit.success) and np.isfinite(cost),
        "parameters": {name: float(value) for name, value in zip(parameter_names, fit.x)},
        "cost": cost,
        "nfev": int(fit.nfev),
        "optimality": float(fit.optimality),
        "message": str(fit.message),
        "bounds": bound_map,
    }


def _linearized_iv_rmse(
    model: str,
    frame: pd.DataFrame,
    parameters: Mapping[str, float],
    spot: float,
    risk_free_rate: float,
    quadrature_nodes: int,
) -> float:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return float("nan")
    evaluation = _normalize_weights(frame)
    if model == "Heston":
        residual = _heston_residual_function(
            evaluation,
            spot,
            risk_free_rate,
            "Linearized implied volatility",
            quadrature_nodes,
            "No penalty",
            0.0,
        )
        values = np.asarray([float(parameters[name]) for name in HESTON_PARAMETER_NAMES], dtype=float)
    else:
        residual = _bates_residual_function(
            evaluation,
            spot,
            risk_free_rate,
            "Linearized implied volatility",
            quadrature_nodes,
        )
        values = np.asarray([float(parameters[name]) for name in BATES_PARAMETER_NAMES], dtype=float)
    errors = np.asarray(residual(values), dtype=float)
    if not errors.size or not np.isfinite(errors).all():
        return float("nan")
    return float(np.sqrt(np.sum(errors * errors)))


def _pseudo_bic(rmse: float, observations: int, parameter_count: int) -> float:
    n = max(int(observations), 2)
    variance = max(float(rmse) ** 2, 1e-16)
    return float(n * math.log(variance) + parameter_count * math.log(n))


def _bootstrap_calibrations(
    train: pd.DataFrame,
    holdout: pd.DataFrame,
    spot: float,
    risk_free_rate: float,
    heston_result: Mapping[str, Any],
    bates_result: Mapping[str, Any],
    settings: ModelRiskSettings,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    rng = np.random.default_rng(int(settings.seed))
    heston_start = [float(heston_result["parameters"][name]) for name in HESTON_PARAMETER_NAMES]
    bates_start = [float(bates_result["parameters"][name]) for name in BATES_PARAMETER_NAMES]
    heston_bounds = heston_result.get("bounds", HESTON_DEFAULT_BOUNDS)
    bates_bounds = bates_result.get("bounds", BATES_DEFAULT_BOUNDS)
    objective = str(bates_result.get("settings", {}).get("objective", heston_result.get("settings", {}).get("objective", "Composite linearized IV + total variance")))
    holdout_eval = _normalize_weights(holdout) if isinstance(holdout, pd.DataFrame) and not holdout.empty else pd.DataFrame()
    min_improvement = float(bates_result.get("settings", {}).get("minimum_holdout_improvement", 0.10))

    for draw in range(max(int(settings.bootstrap_draws), 1)):
        sampled = _stratified_bootstrap(train, rng)
        row: dict[str, Any] = {"draw": draw + 1, "observations": int(len(sampled))}
        try:
            h_fit = _fit_local(
                "Heston", sampled, heston_start, spot, risk_free_rate, objective,
                settings.quadrature_nodes, settings.max_nfev_per_draw, heston_bounds,
            )
            row["heston_success"] = bool(h_fit["success"])
            row["heston_cost"] = float(h_fit["cost"])
            for name, value in h_fit["parameters"].items():
                row[f"heston_{name}"] = value
        except Exception as exc:
            h_fit = {"success": False, "parameters": {}}
            row.update({"heston_success": False, "heston_error": str(exc)})

        try:
            b_fit = _fit_local(
                "Bates", sampled, bates_start, spot, risk_free_rate, objective,
                settings.quadrature_nodes, settings.max_nfev_per_draw, bates_bounds,
            )
            row["bates_success"] = bool(b_fit["success"])
            row["bates_cost"] = float(b_fit["cost"])
            for name, value in b_fit["parameters"].items():
                row[f"bates_{name}"] = value
        except Exception as exc:
            b_fit = {"success": False, "parameters": {}}
            row.update({"bates_success": False, "bates_error": str(exc)})

        h_rmse = float("nan")
        b_rmse = float("nan")
        if not holdout_eval.empty and h_fit.get("success"):
            h_rmse = _linearized_iv_rmse("Heston", holdout_eval, h_fit["parameters"], spot, risk_free_rate, settings.quadrature_nodes)
        if not holdout_eval.empty and b_fit.get("success"):
            b_rmse = _linearized_iv_rmse("Bates", holdout_eval, b_fit["parameters"], spot, risk_free_rate, settings.quadrature_nodes)
        row["heston_holdout_linearized_iv_rmse"] = h_rmse
        row["bates_holdout_linearized_iv_rmse"] = b_rmse
        improvement = (h_rmse - b_rmse) / max(h_rmse, 1e-12) if np.isfinite(h_rmse) and np.isfinite(b_rmse) else float("nan")
        row["holdout_improvement"] = improvement
        h_bic = _pseudo_bic(h_rmse, len(holdout_eval), len(HESTON_PARAMETER_NAMES)) if np.isfinite(h_rmse) else float("nan")
        b_bic = _pseudo_bic(b_rmse, len(holdout_eval), len(BATES_PARAMETER_NAMES)) if np.isfinite(b_rmse) else float("nan")
        row["heston_pseudo_bic"] = h_bic
        row["bates_pseudo_bic"] = b_bic
        row["bates_selected"] = bool(
            h_fit.get("success") and b_fit.get("success") and np.isfinite(improvement)
            and improvement >= min_improvement and np.isfinite(h_bic) and np.isfinite(b_bic) and b_bic < h_bic
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _parameter_intervals(
    bootstrap: pd.DataFrame,
    heston_result: Mapping[str, Any],
    bates_result: Mapping[str, Any],
    confidence: float,
) -> pd.DataFrame:
    alpha = max(min(1.0 - float(confidence), 0.50), 0.001)
    low_q, high_q = alpha / 2.0, 1.0 - alpha / 2.0
    rows: list[dict[str, Any]] = []
    specs = [
        ("Heston", HESTON_PARAMETER_NAMES, heston_result.get("parameters", {}), heston_result.get("bounds", HESTON_DEFAULT_BOUNDS), "heston_success"),
        ("Bates", BATES_PARAMETER_NAMES, bates_result.get("parameters", {}), bates_result.get("bounds", BATES_DEFAULT_BOUNDS), "bates_success"),
    ]
    for model, names, base_parameters, bounds, success_column in specs:
        valid = bootstrap[bootstrap.get(success_column, False).astype(bool)] if success_column in bootstrap else pd.DataFrame()
        for name in names:
            column = f"{model.lower()}_{name}"
            series = pd.to_numeric(valid.get(column, pd.Series(dtype=float)), errors="coerce").dropna()
            base = float(base_parameters.get(name, np.nan))
            bound = bounds.get(name, (np.nan, np.nan)) if isinstance(bounds, Mapping) else (np.nan, np.nan)
            span = float(bound[1]) - float(bound[0]) if np.isfinite(bound[0]) and np.isfinite(bound[1]) else float("nan")
            if series.empty:
                low = median = high = std = float("nan")
            else:
                low = float(series.quantile(low_q))
                median = float(series.median())
                high = float(series.quantile(high_q))
                std = float(series.std(ddof=1)) if len(series) > 1 else 0.0
            rows.append({
                "model": model,
                "parameter": name,
                "base_estimate": base,
                "ci_low": low,
                "bootstrap_median": median,
                "ci_high": high,
                "bootstrap_std": std,
                "normalized_interval_width": (high - low) / span if np.isfinite(high) and np.isfinite(low) and np.isfinite(span) and span > 0.0 else float("nan"),
                "successful_draws": int(len(series)),
                "lower_bound": float(bound[0]),
                "upper_bound": float(bound[1]),
            })
    return pd.DataFrame(rows)


def _finite_difference_jacobian(residual, values: np.ndarray, spans: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    base = np.asarray(residual(values), dtype=float)
    columns: list[np.ndarray] = []
    for index in range(len(values)):
        step = max(abs(float(spans[index])) * 1e-4, abs(float(values[index])) * 1e-5, 1e-7)
        plus = values.copy(); plus[index] += step
        minus = values.copy(); minus[index] -= step
        r_plus = np.asarray(residual(plus), dtype=float)
        r_minus = np.asarray(residual(minus), dtype=float)
        if r_plus.shape != base.shape or r_minus.shape != base.shape:
            columns.append(np.full(base.shape, np.nan))
        else:
            columns.append((r_plus - r_minus) / (2.0 * step) * spans[index])
    return base, np.column_stack(columns)


def _identifiability(
    model: str,
    train: pd.DataFrame,
    spot: float,
    risk_free_rate: float,
    result: Mapping[str, Any],
    quadrature_nodes: int,
    condition_warning: float,
    condition_block: float,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    objective = str(result.get("settings", {}).get("objective", "Composite linearized IV + total variance"))
    if model == "Heston":
        names = HESTON_PARAMETER_NAMES
        values = np.asarray([float(result["parameters"][name]) for name in names], dtype=float)
        _, _, bounds = _heston_bounds_arrays(result.get("bounds", HESTON_DEFAULT_BOUNDS))
        residual = _heston_residual_function(train, spot, risk_free_rate, objective, quadrature_nodes, "No penalty", 0.0)
    else:
        names = BATES_PARAMETER_NAMES
        values = np.asarray([float(result["parameters"][name]) for name in names], dtype=float)
        _, _, bounds = _bates_bounds_arrays(result.get("bounds", BATES_DEFAULT_BOUNDS))
        residual = _bates_residual_function(train, spot, risk_free_rate, objective, quadrature_nodes)
    spans = np.asarray([float(bounds[name][1]) - float(bounds[name][0]) for name in names], dtype=float)
    base_residual, jacobian = _finite_difference_jacobian(residual, values, spans)
    if not np.isfinite(jacobian).all():
        summary = {"model": model, "status": "FAILED", "effective_rank": 0, "parameter_count": len(names), "condition_number": float("inf"), "reason": "Non-finite numerical Jacobian."}
        return summary, pd.DataFrame(), pd.DataFrame()
    singular = np.linalg.svd(jacobian, compute_uv=False)
    largest = float(np.max(singular)) if singular.size else 0.0
    threshold = max(largest * 1e-6, 1e-12)
    effective_rank = int(np.sum(singular > threshold))
    positive = singular[singular > 1e-14]
    condition = float(positive.max() / positive.min()) if len(positive) else float("inf")
    gram = jacobian.T @ jacobian
    covariance = np.linalg.pinv(gram, rcond=1e-10)
    scale = np.sqrt(np.maximum(np.diag(covariance), 1e-30))
    correlation = covariance / np.outer(scale, scale)
    correlation = np.clip(correlation, -1.0, 1.0)
    status = "PASS"
    if condition > condition_block or effective_rank < max(len(names) - 3, 1):
        status = "INELIGIBLE"
    elif condition > condition_warning or effective_rank < len(names) - 1:
        status = "WARNING"
    singular_table = pd.DataFrame({
        "model": model,
        "component": np.arange(1, len(singular) + 1),
        "singular_value": singular,
        "relative_singular_value": singular / max(largest, 1e-30),
    })
    corr_rows = []
    for i, left in enumerate(names):
        for j, right in enumerate(names):
            corr_rows.append({"model": model, "parameter_1": left, "parameter_2": right, "correlation": float(correlation[i, j])})
    summary = {
        "model": model,
        "status": status,
        "effective_rank": effective_rank,
        "parameter_count": len(names),
        "condition_number": condition,
        "minimum_relative_singular_value": float(np.min(singular / max(largest, 1e-30))) if singular.size else float("nan"),
        "residual_rms": float(np.sqrt(np.mean(base_residual * base_residual))) if base_residual.size else float("nan"),
    }
    return summary, singular_table, pd.DataFrame(corr_rows)


def _cost_profiles(
    model: str,
    train: pd.DataFrame,
    spot: float,
    risk_free_rate: float,
    result: Mapping[str, Any],
    quadrature_nodes: int,
    points: int,
    span_fraction: float,
) -> pd.DataFrame:
    objective = str(result.get("settings", {}).get("objective", "Composite linearized IV + total variance"))
    if model == "Heston":
        names = HESTON_PARAMETER_NAMES
        values = np.asarray([float(result["parameters"][name]) for name in names], dtype=float)
        _, _, bounds = _heston_bounds_arrays(result.get("bounds", HESTON_DEFAULT_BOUNDS))
        residual = _heston_residual_function(train, spot, risk_free_rate, objective, quadrature_nodes, "No penalty", 0.0)
    else:
        names = BATES_PARAMETER_NAMES
        values = np.asarray([float(result["parameters"][name]) for name in names], dtype=float)
        _, _, bounds = _bates_bounds_arrays(result.get("bounds", BATES_DEFAULT_BOUNDS))
        residual = _bates_residual_function(train, spot, risk_free_rate, objective, quadrature_nodes)
    base_errors = np.asarray(residual(values), dtype=float)
    base_cost = float(np.mean(base_errors * base_errors))
    rows: list[dict[str, Any]] = []
    grid_count = max(int(points), 3)
    for index, name in enumerate(names):
        low, high = bounds[name]
        span = float(high) - float(low)
        local_low = max(float(low), values[index] - float(span_fraction) * span)
        local_high = min(float(high), values[index] + float(span_fraction) * span)
        grid = np.linspace(local_low, local_high, grid_count)
        grid = np.unique(np.concatenate([grid, [values[index]]]))
        for candidate in grid:
            trial = values.copy(); trial[index] = float(candidate)
            errors = np.asarray(residual(trial), dtype=float)
            cost = float(np.mean(errors * errors)) if errors.size and np.isfinite(errors).all() else float("inf")
            rows.append({
                "model": model,
                "parameter": name,
                "parameter_value": float(candidate),
                "base_value": float(values[index]),
                "cost": cost,
                "relative_cost": cost / max(base_cost, 1e-30),
                "cost_deterioration_bps": (cost / max(base_cost, 1e-30) - 1.0) * 1e4,
            })
    return pd.DataFrame(rows)


def _maturity_jackknife(
    train: pd.DataFrame,
    holdout: pd.DataFrame,
    spot: float,
    risk_free_rate: float,
    heston_result: Mapping[str, Any],
    bates_result: Mapping[str, Any],
    settings: ModelRiskSettings,
) -> pd.DataFrame:
    if not settings.run_maturity_jackknife:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    objective = str(bates_result.get("settings", {}).get("objective", "Composite linearized IV + total variance"))
    specs = [
        ("Heston", HESTON_PARAMETER_NAMES, heston_result, heston_result.get("bounds", HESTON_DEFAULT_BOUNDS)),
        ("Bates", BATES_PARAMETER_NAMES, bates_result, bates_result.get("bounds", BATES_DEFAULT_BOUNDS)),
    ]
    for expiration in sorted(train["expiration"].astype(str).unique()):
        reduced = train[train["expiration"].astype(str) != str(expiration)].copy().reset_index(drop=True)
        if reduced.empty or reduced["expiration"].nunique() < 2:
            continue
        reduced = _normalize_weights(reduced)
        for model, names, result, bounds in specs:
            start = [float(result["parameters"][name]) for name in names]
            try:
                fit = _fit_local(
                    model, reduced, start, spot, risk_free_rate, objective,
                    settings.quadrature_nodes, settings.max_nfev_per_draw, bounds,
                )
                shifts = []
                row: dict[str, Any] = {"excluded_expiration": str(expiration), "model": model, "success": bool(fit["success"]), "cost": float(fit["cost"])}
                for name in names:
                    base = float(result["parameters"][name])
                    estimate = float(fit["parameters"][name])
                    low, high = bounds[name]
                    normalized = abs(estimate - base) / max(float(high) - float(low), 1e-12)
                    row[f"{name}_estimate"] = estimate
                    row[f"{name}_normalized_shift"] = normalized
                    shifts.append(normalized)
                row["maximum_normalized_parameter_shift"] = float(max(shifts)) if shifts else float("nan")
                row["holdout_linearized_iv_rmse"] = _linearized_iv_rmse(model, holdout, fit["parameters"], spot, risk_free_rate, settings.quadrature_nodes) if not holdout.empty else float("nan")
                rows.append(row)
            except Exception as exc:
                rows.append({"excluded_expiration": str(expiration), "model": model, "success": False, "error": str(exc), "maximum_normalized_parameter_shift": float("nan")})
    return pd.DataFrame(rows)


def _gate_row(gate: str, observed: Any, threshold: str, passed: bool, severity: str, detail: str) -> dict[str, Any]:
    return {
        "gate": gate,
        "observed": observed,
        "threshold": threshold,
        "passed": bool(passed),
        "severity": severity,
        "detail": detail,
    }


def _parameter_bound_diagnostics(
    model: str,
    parameters: Mapping[str, Any],
    bounds: Mapping[str, Sequence[float]],
    intervals: pd.DataFrame,
    proximity_fraction: float,
) -> tuple[pd.DataFrame, list[str], list[str]]:
    rows: list[dict[str, Any]] = []
    source_flags: list[str] = []
    interval_flags: list[str] = []
    model_intervals = intervals[intervals["model"].astype(str) == model] if isinstance(intervals, pd.DataFrame) and not intervals.empty else pd.DataFrame()
    for parameter, value_raw in parameters.items():
        if parameter not in bounds:
            continue
        low, high = bounds[parameter]
        value = float(value_raw)
        low = float(low); high = float(high)
        span = max(high - low, 1e-12)
        lower_distance = (value - low) / span
        upper_distance = (high - value) / span
        source_near_lower = bool(np.isfinite(lower_distance) and lower_distance <= proximity_fraction)
        source_near_upper = bool(np.isfinite(upper_distance) and upper_distance <= proximity_fraction)
        interval_row = model_intervals[model_intervals["parameter"].astype(str) == str(parameter)] if not model_intervals.empty else pd.DataFrame()
        ci_low = float(interval_row.iloc[0].get("ci_low", np.nan)) if not interval_row.empty else float("nan")
        ci_high = float(interval_row.iloc[0].get("ci_high", np.nan)) if not interval_row.empty else float("nan")
        ci_touches_lower = bool(np.isfinite(ci_low) and ci_low <= low + proximity_fraction * span)
        ci_touches_upper = bool(np.isfinite(ci_high) and ci_high >= high - proximity_fraction * span)
        source_side = "LOWER" if source_near_lower else "UPPER" if source_near_upper else "NONE"
        ci_side = "LOWER" if ci_touches_lower else "UPPER" if ci_touches_upper else "BOTH" if ci_touches_lower and ci_touches_upper else "NONE"
        if source_near_lower or source_near_upper:
            source_flags.append(f"{model} {parameter} near {source_side.lower()} bound")
        if ci_touches_lower or ci_touches_upper:
            if ci_touches_lower and ci_touches_upper:
                ci_side = "BOTH"
            interval_flags.append(f"{model} {parameter} bootstrap CI touches {ci_side.lower()} bound")
        rows.append({
            "model": model,
            "parameter": parameter,
            "estimate": value,
            "lower_bound": low,
            "upper_bound": high,
            "distance_to_lower_normalized": lower_distance,
            "distance_to_upper_normalized": upper_distance,
            "source_near_bound": source_near_lower or source_near_upper,
            "source_bound_side": source_side,
            "ci_low": ci_low,
            "ci_high": ci_high,
            "ci_touches_bound": ci_touches_lower or ci_touches_upper,
            "ci_bound_side": ci_side,
        })
    return pd.DataFrame(rows), source_flags, interval_flags


def _largest_interval_driver(intervals: pd.DataFrame, model: str | None = None, jump_only: bool = False) -> dict[str, Any]:
    if not isinstance(intervals, pd.DataFrame) or intervals.empty:
        return {}
    frame = intervals.copy()
    if model is not None:
        frame = frame[frame["model"].astype(str) == str(model)]
    if jump_only:
        frame = frame[frame["parameter"].astype(str).isin(["jump_intensity", "jump_mean", "jump_volatility"])]
    frame["normalized_interval_width"] = pd.to_numeric(frame["normalized_interval_width"], errors="coerce")
    frame = frame[np.isfinite(frame["normalized_interval_width"])]
    if frame.empty:
        return {}
    return frame.loc[frame["normalized_interval_width"].idxmax()].to_dict()


def _largest_maturity_driver(maturity: pd.DataFrame) -> dict[str, Any]:
    if not isinstance(maturity, pd.DataFrame) or maturity.empty:
        return {}
    frame = maturity.copy()
    frame["maximum_normalized_parameter_shift"] = pd.to_numeric(frame["maximum_normalized_parameter_shift"], errors="coerce")
    frame = frame[np.isfinite(frame["maximum_normalized_parameter_shift"])]
    if frame.empty:
        return {}
    row = frame.loc[frame["maximum_normalized_parameter_shift"].idxmax()].to_dict()
    shift_columns = [column for column in frame.columns if column.endswith("_normalized_shift") and column != "maximum_normalized_parameter_shift"]
    best_parameter = None
    best_shift = float("nan")
    for column in shift_columns:
        value = float(row.get(column, np.nan))
        if np.isfinite(value) and (best_parameter is None or value > best_shift):
            best_parameter = column[: -len("_normalized_shift")]
            best_shift = value
    row["driving_parameter"] = best_parameter
    row["driving_parameter_shift"] = best_shift
    return row


def _evidence_tier(draws: int, minimum_production_draws: int) -> str:
    draws = int(draws)
    if draws >= max(80, minimum_production_draws):
        return "PRODUCTION_EVIDENCE"
    if draws >= minimum_production_draws:
        return "ROBUST"
    return "PRELIMINARY"


def _format_gate_failure(row: Mapping[str, Any]) -> str:
    detail = str(row.get("detail", "")).strip()
    suffix = f" {detail}" if detail else ""
    return f"{row.get('gate')}: {row.get('observed')} (limit {row.get('threshold')}).{suffix}"


def _build_gate_table(
    dataset_result: Mapping[str, Any],
    heston_result: Mapping[str, Any],
    bates_result: Mapping[str, Any],
    bootstrap: pd.DataFrame,
    intervals: pd.DataFrame,
    identifiability_summary: pd.DataFrame,
    maturity: pd.DataFrame,
    settings: ModelRiskSettings,
) -> tuple[pd.DataFrame, list[str], list[str], str, str, dict[str, Any], pd.DataFrame]:
    blockers: list[str] = []
    warnings: list[str] = []
    rows: list[dict[str, Any]] = []
    h_success = float(bootstrap.get("heston_success", pd.Series(dtype=bool)).mean()) if len(bootstrap) else 0.0
    b_success = float(bootstrap.get("bates_success", pd.Series(dtype=bool)).mean()) if len(bootstrap) else 0.0
    selection_probability = float(bootstrap.get("bates_selected", pd.Series(dtype=bool)).mean()) if len(bootstrap) else 0.0
    h_ident = identifiability_summary[identifiability_summary["model"] == "Heston"].iloc[0].to_dict() if not identifiability_summary.empty and (identifiability_summary["model"] == "Heston").any() else {}
    b_ident = identifiability_summary[identifiability_summary["model"] == "Bates"].iloc[0].to_dict() if not identifiability_summary.empty and (identifiability_summary["model"] == "Bates").any() else {}

    h_driver = _largest_interval_driver(intervals, model="Heston")
    b_driver = _largest_interval_driver(intervals, model="Bates")
    jump_driver = _largest_interval_driver(intervals, model="Bates", jump_only=True)
    maturity_driver = _largest_maturity_driver(maturity)
    h_width = float(h_driver.get("normalized_interval_width", np.inf))
    b_width = float(b_driver.get("normalized_interval_width", np.inf))
    jump_width = float(jump_driver.get("normalized_interval_width", np.inf))
    maturity_sensitivity = float(maturity_driver.get("maximum_normalized_parameter_shift", 0.0))

    h_bound_table, h_source_bound_flags, h_ci_bound_flags = _parameter_bound_diagnostics(
        "Heston", heston_result.get("parameters", {}), heston_result.get("bounds", HESTON_DEFAULT_BOUNDS),
        intervals, settings.bound_proximity_fraction,
    )
    b_bound_table, b_source_bound_flags, b_ci_bound_flags = _parameter_bound_diagnostics(
        "Bates", bates_result.get("parameters", {}), bates_result.get("bounds", BATES_DEFAULT_BOUNDS),
        intervals, settings.bound_proximity_fraction,
    )
    bound_diagnostics = pd.concat([h_bound_table, b_bound_table], ignore_index=True)

    h_cross = float(heston_result.get("maximum_crosscheck_error", np.nan))
    b_cross = float(bates_result.get("maximum_crosscheck_error", np.nan))
    h_tol = float(heston_result.get("settings", {}).get("numerical_crosscheck_tolerance", 2.5e-3))
    b_tol = float(bates_result.get("settings", {}).get("numerical_crosscheck_tolerance", 3.5e-3))
    numerical_pass = (not np.isfinite(h_cross) or h_cross <= h_tol) and (not np.isfinite(b_cross) or b_cross <= b_tol)

    dataset_status = str(dataset_result.get("status", "FAILED"))
    heston_status = str(heston_result.get("status", "FAILED"))
    bates_status = str(bates_result.get("status", "FAILED"))
    source_champion = str(bates_result.get("champion_status", "UNKNOWN"))
    draw_count = int(len(bootstrap))
    evidence_tier = _evidence_tier(draw_count, settings.minimum_production_bootstrap_draws)

    rows.append(_gate_row("Calibration dataset admissibility", dataset_status, "PASS or WARNING", dataset_status in {"PASS", "WARNING"}, "BLOCKER", "Frozen training/holdout dataset must remain governed."))
    rows.append(_gate_row("Calibration dataset production quality", dataset_status, "PASS", dataset_status == "PASS", "WARNING", "A WARNING dataset remains research-usable but is not production-clean."))
    rows.append(_gate_row("Heston source calibration", heston_status, "PASS", heston_status == "PASS", "WARNING", "Source calibration warnings remain part of model risk even when numerical repricing succeeds."))
    rows.append(_gate_row("Bates source calibration", bates_status, "PASS", bates_status == "PASS", "WARNING", "Bates production eligibility requires a clean source calibration in addition to challenger gains."))
    rows.append(_gate_row("Bootstrap evidence depth", f"{draw_count} draws ({evidence_tier})", f">= {settings.minimum_production_bootstrap_draws} draws", draw_count >= settings.minimum_production_bootstrap_draws, "WARNING", "Fewer draws are diagnostic; production evidence requires a more stable empirical interval estimate."))
    rows.append(_gate_row("Heston bootstrap success", f"{h_success:.1%}", f">= {settings.minimum_bootstrap_success_rate:.0%}", h_success >= settings.minimum_bootstrap_success_rate, "WARNING", "Successful maturity-stratified warm-start recalibrations."))
    rows.append(_gate_row("Bates bootstrap success", f"{b_success:.1%}", f">= {settings.minimum_bootstrap_success_rate:.0%}", b_success >= settings.minimum_bootstrap_success_rate, "BLOCKER", "Jump-model recalibration stability across quote resamples."))
    rows.append(_gate_row("Heston local effective rank", f"{h_ident.get('effective_rank', 0)}/{h_ident.get('parameter_count', len(HESTON_PARAMETER_NAMES))}", f">= {len(HESTON_PARAMETER_NAMES)-1}", int(h_ident.get("effective_rank", 0)) >= len(HESTON_PARAMETER_NAMES)-1, "WARNING", "Numerical Jacobian rank in bound-normalized parameter coordinates."))
    rows.append(_gate_row("Bates local effective rank", f"{b_ident.get('effective_rank', 0)}/{b_ident.get('parameter_count', len(BATES_PARAMETER_NAMES))}", f">= {len(BATES_PARAMETER_NAMES)-1}", int(b_ident.get("effective_rank", 0)) >= len(BATES_PARAMETER_NAMES)-1, "BLOCKER", "Jump parameters must be locally distinguishable from diffusion parameters."))
    rows.append(_gate_row(
        "Heston maximum normalized interval width",
        f"{h_width:.1%} ({h_driver.get('parameter', 'N/A')})",
        f"<= {settings.maximum_normalized_interval_width:.1%}",
        np.isfinite(h_width) and h_width <= settings.maximum_normalized_interval_width,
        "WARNING",
        "Largest Heston bootstrap interval relative to its governed bound span.",
    ))
    rows.append(_gate_row(
        "Bates maximum normalized interval width",
        f"{b_width:.1%} ({b_driver.get('parameter', 'N/A')})",
        f"<= {settings.maximum_normalized_interval_width:.1%}",
        np.isfinite(b_width) and b_width <= settings.maximum_normalized_interval_width,
        "WARNING",
        "Largest Bates bootstrap interval relative to its governed bound span.",
    ))
    rows.append(_gate_row(
        "Bates jump-parameter interval width",
        f"{jump_width:.1%} ({jump_driver.get('parameter', 'N/A')})",
        f"<= {settings.maximum_normalized_interval_width:.1%}",
        np.isfinite(jump_width) and jump_width <= settings.maximum_normalized_interval_width,
        "BLOCKER",
        "Identification of jump intensity, mean and volatility.",
    ))
    maturity_observed = (
        f"{maturity_sensitivity:.1%} · {maturity_driver.get('model', 'N/A')} {maturity_driver.get('driving_parameter', 'N/A')} "
        f"when excluding {maturity_driver.get('excluded_expiration', 'N/A')}"
    )
    rows.append(_gate_row(
        "Leave-one-maturity sensitivity",
        maturity_observed,
        f"<= {settings.maximum_maturity_sensitivity:.1%}",
        maturity_sensitivity <= settings.maximum_maturity_sensitivity,
        "WARNING",
        "Maximum parameter move relative to its governed bound span.",
    ))
    rows.append(_gate_row(
        "Heston source parameters away from bounds",
        "; ".join(h_source_bound_flags) if h_source_bound_flags else "No source parameter within bound proximity tolerance",
        f"> {settings.bound_proximity_fraction:.1%} from both bounds",
        not h_source_bound_flags,
        "WARNING",
        "Source parameters pinned near a bound can make economic interpretation constraint-dependent.",
    ))
    rows.append(_gate_row(
        "Bates source parameters away from bounds",
        "; ".join(b_source_bound_flags) if b_source_bound_flags else "No source parameter within bound proximity tolerance",
        f"> {settings.bound_proximity_fraction:.1%} from both bounds",
        not b_source_bound_flags,
        "WARNING",
        "Source parameters pinned near a bound can make the jump/diffusion decomposition constraint-dependent.",
    ))
    rows.append(_gate_row(
        "Heston bootstrap intervals away from bounds",
        "; ".join(h_ci_bound_flags) if h_ci_bound_flags else "No bootstrap CI touches a governed bound",
        "No CI bound contact",
        not h_ci_bound_flags,
        "WARNING",
        "A confidence interval reaching a bound indicates incomplete identification inside the allowed parameter domain.",
    ))
    rows.append(_gate_row(
        "Bates bootstrap intervals away from bounds",
        "; ".join(b_ci_bound_flags) if b_ci_bound_flags else "No bootstrap CI touches a governed bound",
        "No CI bound contact",
        not b_ci_bound_flags,
        "WARNING",
        "A confidence interval reaching a bound indicates incomplete identification inside the allowed parameter domain.",
    ))
    rows.append(_gate_row("Independent numerical cross-check", f"H={h_cross:.3g}; B={b_cross:.3g}", "within source tolerances", numerical_pass, "BLOCKER", "Fourier pricing cross-check inherited from calibration engines."))
    rows.append(_gate_row("Source champion decision", source_champion, "BATES_CHAMPION for Bates production role", source_champion == "BATES_CHAMPION", "WARNING", "Current champion/challenger decision on the frozen holdout."))
    rows.append(_gate_row("Bootstrap Bates preference probability", f"{selection_probability:.1%}", f">= {settings.production_bates_selection_probability:.0%}", selection_probability >= settings.production_bates_selection_probability, "WARNING", "Frequency with which Bates clears holdout-improvement and pseudo-BIC controls across quote resamples."))

    for row in rows:
        if row["passed"]:
            continue
        message = _format_gate_failure(row)
        if row["severity"] == "BLOCKER":
            blockers.append(message)
        else:
            warnings.append(message)

    hard_failure = (
        b_success < 0.50
        or str(b_ident.get("status", "FAILED")) == "INELIGIBLE"
        or not numerical_pass
        or dataset_status not in {"PASS", "WARNING"}
    )
    if hard_failure:
        status = "INELIGIBLE"
        recommended_role = "NO_PRODUCTION_MODEL"
    elif not blockers and not warnings and source_champion == "BATES_CHAMPION":
        status = "PRODUCTION_ELIGIBLE"
        recommended_role = "BATES_CHAMPION"
    else:
        status = "RESEARCH_ONLY"
        if source_champion == "HESTON_CHAMPION":
            recommended_role = "HESTON_CHAMPION"
        elif source_champion == "BATES_CHAMPION" and selection_probability >= settings.production_bates_selection_probability:
            recommended_role = "BATES_CHAMPION_WITH_MODEL_RISK_RESERVES"
        else:
            recommended_role = "NO_PRODUCTION_CHAMPION"

    relative_preference = (
        "BATES" if selection_probability >= 0.50 else "HESTON"
    )
    absolute_production_status = "ELIGIBLE" if status == "PRODUCTION_ELIGIBLE" else "NOT_ELIGIBLE"
    diagnostics = {
        "evidence_tier": evidence_tier,
        "bootstrap_draws": draw_count,
        "minimum_production_bootstrap_draws": int(settings.minimum_production_bootstrap_draws),
        "relative_model_preference": relative_preference,
        "absolute_production_status": absolute_production_status,
        "largest_heston_interval": h_driver,
        "largest_bates_interval": b_driver,
        "largest_jump_interval": jump_driver,
        "largest_maturity_sensitivity": maturity_driver,
        "heston_source_bound_flags": h_source_bound_flags,
        "bates_source_bound_flags": b_source_bound_flags,
        "heston_ci_bound_flags": h_ci_bound_flags,
        "bates_ci_bound_flags": b_ci_bound_flags,
    }
    return pd.DataFrame(rows), blockers, warnings, status, recommended_role, diagnostics, bound_diagnostics



def _model_card(
    status: str,
    recommended_role: str,
    dataset_result: Mapping[str, Any],
    heston_result: Mapping[str, Any],
    bates_result: Mapping[str, Any],
    settings: ModelRiskSettings,
    bootstrap_summary: Mapping[str, Any],
    blockers: Sequence[str],
    warnings: Sequence[str],
    diagnostics: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "model_risk_version": MODEL_RISK_VERSION,
        "final_status": status,
        "recommended_role": recommended_role,
        "relative_model_preference": diagnostics.get("relative_model_preference"),
        "absolute_production_status": diagnostics.get("absolute_production_status"),
        "evidence_tier": diagnostics.get("evidence_tier"),
        "decision_summary": {
            "relative_model_preference": diagnostics.get("relative_model_preference"),
            "absolute_production_status": diagnostics.get("absolute_production_status"),
            "largest_parameter_uncertainty": diagnostics.get("largest_bates_interval"),
            "largest_jump_parameter_uncertainty": diagnostics.get("largest_jump_interval"),
            "largest_maturity_sensitivity": diagnostics.get("largest_maturity_sensitivity"),
            "source_bound_flags": list(diagnostics.get("heston_source_bound_flags", [])) + list(diagnostics.get("bates_source_bound_flags", [])),
            "bootstrap_ci_bound_flags": list(diagnostics.get("heston_ci_bound_flags", [])) + list(diagnostics.get("bates_ci_bound_flags", [])),
        },
        "intended_use": "Risk-neutral vanilla-option surface pricing, scenario analysis and governed Q-measure simulation.",
        "prohibited_use": "Do not interpret Q jump intensity or Q terminal probabilities as physical forecasts; do not inject Heston/Bates into the validated P-measure ensemble.",
        "dataset_signature": dataset_result.get("configuration_signature"),
        "heston_signature": heston_result.get("configuration_signature"),
        "bates_signature": bates_result.get("configuration_signature"),
        "source_champion_status": bates_result.get("champion_status"),
        "bootstrap_summary": dict(bootstrap_summary),
        "settings": asdict(settings),
        "blockers": list(blockers),
        "warnings": list(warnings),
        "monitoring_expectations": [
            "Rebuild the surface after material changes in spot, carry, quote quality or expiry coverage.",
            "Re-run model-risk diagnostics when the champion decision or any parameter crosses a governed threshold.",
            "Track parameter intervals, leave-one-maturity sensitivity and numerical cross-checks over time.",
            "Retain calibration inputs, configuration signatures, model versions and exports for reproducibility.",
        ],
        "limitations": [
            "US equity/ETF option chains remain an American-style European-equivalent approximation.",
            "Bootstrap intervals quantify quote-sample instability, not all structural model uncertainty.",
            "Conditional cost profiles hold other parameters fixed and are sensitivity diagnostics, not exact profile likelihoods.",
            "Production eligibility is a governance classification within this terminal, not a regulatory approval.",
        ],
    }


def build_model_risk_governance(
    dataset_result: Mapping[str, Any],
    heston_result: Mapping[str, Any],
    bates_result: Mapping[str, Any],
    *,
    bootstrap_draws: int = 20,
    bootstrap_confidence: float = 0.95,
    max_nfev_per_draw: int = 80,
    quadrature_nodes: int = 48,
    seed: int = 42,
    run_maturity_jackknife: bool = True,
    profile_grid_points: int = 7,
    profile_span_fraction: float = 0.20,
    minimum_bootstrap_success_rate: float = 0.80,
    production_bates_selection_probability: float = 0.70,
    maximum_normalized_interval_width: float = 0.60,
    maximum_maturity_sensitivity: float = 0.35,
    minimum_production_bootstrap_draws: int = 40,
    bound_proximity_fraction: float = 0.01,
    condition_number_warning: float = 1.0e8,
    condition_number_block: float = 1.0e12,
) -> dict[str, Any]:
    settings = ModelRiskSettings(
        bootstrap_draws=max(int(bootstrap_draws), 1),
        bootstrap_confidence=float(bootstrap_confidence),
        max_nfev_per_draw=max(int(max_nfev_per_draw), 10),
        quadrature_nodes=int(quadrature_nodes),
        seed=int(seed),
        run_maturity_jackknife=bool(run_maturity_jackknife),
        profile_grid_points=max(int(profile_grid_points), 3),
        profile_span_fraction=float(profile_span_fraction),
        minimum_bootstrap_success_rate=float(minimum_bootstrap_success_rate),
        production_bates_selection_probability=float(production_bates_selection_probability),
        maximum_normalized_interval_width=float(maximum_normalized_interval_width),
        maximum_maturity_sensitivity=float(maximum_maturity_sensitivity),
        minimum_production_bootstrap_draws=max(int(minimum_production_bootstrap_draws), 1),
        bound_proximity_fraction=max(float(bound_proximity_fraction), 0.0),
        condition_number_warning=float(condition_number_warning),
        condition_number_block=float(condition_number_block),
    )
    try:
        train, holdout, spot, risk_free_rate = _validate_inputs(dataset_result, heston_result, bates_result)
        train = _normalize_weights(train)
        bootstrap = _bootstrap_calibrations(train, holdout, spot, risk_free_rate, heston_result, bates_result, settings)
        intervals = _parameter_intervals(bootstrap, heston_result, bates_result, settings.bootstrap_confidence)

        h_ident, h_singular, h_corr = _identifiability(
            "Heston", train, spot, risk_free_rate, heston_result, settings.quadrature_nodes,
            settings.condition_number_warning, settings.condition_number_block,
        )
        b_ident, b_singular, b_corr = _identifiability(
            "Bates", train, spot, risk_free_rate, bates_result, settings.quadrature_nodes,
            settings.condition_number_warning, settings.condition_number_block,
        )
        identifiability_summary = pd.DataFrame([h_ident, b_ident])
        singular_values = pd.concat([h_singular, b_singular], ignore_index=True)
        parameter_correlations = pd.concat([h_corr, b_corr], ignore_index=True)

        h_profiles = _cost_profiles(
            "Heston", train, spot, risk_free_rate, heston_result, settings.quadrature_nodes,
            settings.profile_grid_points, settings.profile_span_fraction,
        )
        b_profiles = _cost_profiles(
            "Bates", train, spot, risk_free_rate, bates_result, settings.quadrature_nodes,
            settings.profile_grid_points, settings.profile_span_fraction,
        )
        cost_profiles = pd.concat([h_profiles, b_profiles], ignore_index=True)
        maturity = _maturity_jackknife(train, holdout, spot, risk_free_rate, heston_result, bates_result, settings)

        gate_table, blockers, warnings, status, recommended_role, decision_diagnostics, bound_diagnostics = _build_gate_table(
            dataset_result, heston_result, bates_result, bootstrap, intervals,
            identifiability_summary, maturity, settings,
        )
        h_success = float(bootstrap["heston_success"].mean()) if "heston_success" in bootstrap else 0.0
        b_success = float(bootstrap["bates_success"].mean()) if "bates_success" in bootstrap else 0.0
        selection_probability = float(bootstrap["bates_selected"].mean()) if "bates_selected" in bootstrap else 0.0
        bootstrap_summary = {
            "draws": int(len(bootstrap)),
            "heston_success_rate": h_success,
            "bates_success_rate": b_success,
            "bates_selection_probability": selection_probability,
            "median_holdout_improvement": float(pd.to_numeric(bootstrap.get("holdout_improvement", pd.Series(dtype=float)), errors="coerce").median()),
        }
        model_card = _model_card(
            status, recommended_role, dataset_result, heston_result, bates_result,
            settings, bootstrap_summary, blockers, warnings, decision_diagnostics,
        )
        signature = _signature({
            "version": MODEL_RISK_VERSION,
            "dataset": dataset_result.get("configuration_signature"),
            "heston": heston_result.get("configuration_signature"),
            "bates": bates_result.get("configuration_signature"),
            "settings": asdict(settings),
            "status": status,
        })
        return {
            "ok": status != "FAILED",
            "status": status,
            "version": MODEL_RISK_VERSION,
            "configuration_signature": signature,
            "settings": asdict(settings),
            "dataset_signature": dataset_result.get("configuration_signature"),
            "heston_signature": heston_result.get("configuration_signature"),
            "bates_signature": bates_result.get("configuration_signature"),
            "source_champion_status": bates_result.get("champion_status"),
            "recommended_role": recommended_role,
            "decision_diagnostics": decision_diagnostics,
            "parameter_bound_diagnostics": bound_diagnostics,
            "bootstrap_summary": bootstrap_summary,
            "bootstrap_draws": bootstrap,
            "parameter_intervals": intervals,
            "identifiability_summary": identifiability_summary,
            "singular_values": singular_values,
            "parameter_correlations": parameter_correlations,
            "cost_profiles": cost_profiles,
            "maturity_sensitivity": maturity,
            "gate_table": gate_table,
            "blockers": blockers,
            "warnings": warnings,
            "model_card": model_card,
            "governance": {
                "development": "Calibration inputs, objective functions, numerical methods and parameter bounds are versioned and reproducible.",
                "validation": "Quote-resample recalibration, holdout challenger selection, local Jacobian diagnostics, cost profiles and leave-one-maturity tests are combined.",
                "monitoring": "Results are a point-in-time snapshot; repeated signatures should be archived to create an ongoing champion/challenger history.",
                "independence": "This layer challenges source calibrations and does not alter their parameters or champion decision.",
                "measure": "All Heston/Bates diagnostics remain under Q and are excluded from physical-probability aggregation.",
            },
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": "FAILED",
            "version": MODEL_RISK_VERSION,
            "reason": str(exc),
            "settings": asdict(settings),
            "blockers": [str(exc)],
            "warnings": [],
        }
