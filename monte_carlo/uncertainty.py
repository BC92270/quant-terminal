from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import asdict
from typing import Any, Dict, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from .barriers import resolve_barrier_monitoring
from .calibration import fit_conditional_volatility
from .config import (
    DEFAULT_CONFIDENCE,
    DEFAULT_HORIZONS,
    EPS,
    MAX_HORIZON,
    MODELS,
    ScenarioParameters,
)
from .data_quality import _estimate_student_df, _ewma_variance
from .models.bootstrap import generate_stationary_indices
from .models.dispatcher import simulate_paths_max_horizon
from .risk_metrics import _summarize_paths
from .utils import _clamp, _moment_excess_kurtosis, _moment_skew, _normal_ppf

UNCERTAINTY_VERSION = "PARAMETER-MODEL-UNCERTAINTY-2.4.1"
UNCERTAINTY_WEIGHTING_METHODS = (
    "Equal eligible",
    "Validation inverse CRPS",
    "Validation governed rank",
)

_CONDITIONAL_FIT_MAP = {
    "GARCH(1,1) normal": "GARCH(1,1) normal",
    "GARCH(1,1) Student-t": "GARCH(1,1) Student-t",
    "GJR-GARCH Student-t": "GJR-GARCH Student-t",
    "Filtered historical GARCH-t": "GARCH(1,1) Student-t",
}


def _finite_array(values: Iterable[float]) -> np.ndarray:
    array = np.asarray(list(values) if not isinstance(values, np.ndarray) else values, dtype=float)
    return array[np.isfinite(array)]


def _stationary_bootstrap_sample(
    values: np.ndarray,
    rng: np.random.Generator,
    mean_block_length: int,
) -> np.ndarray:
    values = _finite_array(values)
    if values.size < 2:
        raise ValueError("At least two returns are required for parameter bootstrap.")
    indices = generate_stationary_indices(
        rng,
        n_history=int(values.size),
        simulations=1,
        horizon=int(values.size),
        mean_block_length=max(2, int(mean_block_length)),
    )[0]
    return values[indices]


def _bootstrap_ci(values: Iterable[float], confidence: float) -> tuple[float, float, float]:
    array = _finite_array(values)
    if array.size == 0:
        return float("nan"), float("nan"), float("nan")
    alpha = (1.0 - _clamp(float(confidence), 0.50, 0.999)) / 2.0
    return (
        float(np.quantile(array, alpha)),
        float(np.median(array)),
        float(np.quantile(array, 1.0 - alpha)),
    )


def _rebuild_base_from_log_returns(
    base: Mapping[str, Any],
    sampled_log_returns: np.ndarray,
    ewma_lambda: float,
) -> Dict[str, Any]:
    """Create a non-mutating calibration draw from bootstrapped log returns."""
    sampled = _finite_array(sampled_log_returns)
    if sampled.size < 30:
        raise ValueError("Bootstrapped calibration sample is too short.")

    output = copy.copy(dict(base))
    ppy = int(base["periods_per_year"])
    n = int(sampled.size)
    mean_log_period = float(np.mean(sampled))
    sigma_period = max(float(np.std(sampled, ddof=1)), 1e-8)
    vol_ann = sigma_period * math.sqrt(ppy)
    drift_ann = mean_log_period * ppy + 0.5 * vol_ann**2
    expected_return_ann = math.exp(float(np.clip(drift_ann, -20.0, 20.0))) - 1.0
    drift_se_ann = sigma_period / math.sqrt(n) * ppy
    z95 = _normal_ppf(0.975)

    ewma_lambda = _clamp(float(ewma_lambda), 0.50, 0.999)
    ewma_vars = _ewma_variance(sampled, decay=ewma_lambda)
    ewma_vol_ann = math.sqrt(float(ewma_vars[-1]) * ppy) if ewma_vars.size else vol_ann
    standardized = np.array([], dtype=float)
    if ewma_vars.size == sampled.size:
        standardized = (sampled - mean_log_period) / np.sqrt(np.maximum(ewma_vars, EPS))
        standardized = standardized[np.isfinite(standardized)]
        if standardized.size:
            standardized = standardized - float(np.mean(standardized))
            std = float(np.std(standardized, ddof=1)) if standardized.size > 1 else 1.0
            if std > EPS:
                standardized = standardized / std

    excess_kurtosis = float(_moment_excess_kurtosis(sampled))
    output.update(
        {
            "simple_returns": pd.Series(np.expm1(sampled)),
            "log_returns": pd.Series(sampled),
            "log_return_values": sampled,
            "standardized_residuals": standardized,
            "ewma_variances": ewma_vars,
            "mean_log_period": mean_log_period,
            "sigma_period": sigma_period,
            "drift_ann": float(drift_ann),
            "expected_return_ann": float(expected_return_ann),
            "drift_se_ann": float(drift_se_ann),
            "drift_ci_95": (
                float(drift_ann - z95 * drift_se_ann),
                float(drift_ann + z95 * drift_se_ann),
            ),
            "vol_ann": float(vol_ann),
            "ewma_vol_ann": float(ewma_vol_ann),
            "skewness": float(_moment_skew(sampled)),
            "excess_kurtosis": excess_kurtosis,
            "student_df": float(_estimate_student_df(excess_kurtosis)),
            "calibration_observations": n,
        }
    )
    return output


def _refit_draw_conditional_model(
    draw_base: Dict[str, Any],
    model: str,
    maxiter: int,
    min_observations: int,
) -> Mapping[str, Any] | None:
    fit_name = _CONDITIONAL_FIT_MAP.get(model)
    if fit_name is None:
        return None
    fit = fit_conditional_volatility(
        np.asarray(draw_base["log_return_values"], dtype=float),
        periods_per_year=int(draw_base["periods_per_year"]),
        model_name=fit_name,
        maxiter=max(100, int(maxiter)),
        min_observations=max(60, int(min_observations)),
    )
    calibrations = dict(draw_base.get("conditional_calibrations", {}))
    calibrations[fit_name] = fit
    draw_base["conditional_calibrations"] = calibrations
    return fit


def _eligible_models(lab: Mapping[str, Any]) -> list[str]:
    eligibility = lab.get("model_eligibility", {})
    return [
        model
        for model in MODELS
        if str(eligibility.get(model, {}).get("status")) == "ELIGIBLE"
    ]


def _normalise_models(lab: Mapping[str, Any], models: Sequence[str] | None) -> list[str]:
    selected = [str(model) for model in (models or []) if str(model) in MODELS]
    if not selected:
        selected_model = str(lab.get("settings", {}).get("model", "GBM normal"))
        selected = [selected_model if selected_model in MODELS else "GBM normal"]
    # Preserve order while removing duplicates.
    return list(dict.fromkeys(selected))


def _validation_weight_lookup(
    validation_result: Mapping[str, Any] | None,
    models: Sequence[str],
    method: str,
) -> Dict[str, float] | None:
    if not isinstance(validation_result, Mapping) or not validation_result.get("ok"):
        return None
    leaderboard = validation_result.get("leaderboard")
    if not isinstance(leaderboard, pd.DataFrame) or leaderboard.empty or "Model" not in leaderboard:
        return None
    frame = leaderboard[leaderboard["Model"].isin(models)].copy()
    if frame.empty:
        return None

    if method == "Validation inverse CRPS" and "Mean CRPS" in frame:
        score = 1.0 / np.maximum(pd.to_numeric(frame["Mean CRPS"], errors="coerce").to_numpy(float), 1e-8)
    elif method == "Validation governed rank":
        rank_col = "Governed rank score" if "Governed rank score" in frame else "Validation rank"
        if rank_col not in frame:
            return None
        score = 1.0 / np.maximum(pd.to_numeric(frame[rank_col], errors="coerce").to_numpy(float), 1e-8)
    else:
        return None
    score = np.where(np.isfinite(score) & (score > 0), score, 0.0)
    if float(np.sum(score)) <= 0:
        return None
    score = score / np.sum(score)
    return {str(model): float(weight) for model, weight in zip(frame["Model"], score)}


def resolve_uncertainty_model_weights(
    lab: Mapping[str, Any],
    models: Sequence[str] | None = None,
    method: str = "Equal eligible",
    validation_result: Mapping[str, Any] | None = None,
    custom_weights: Mapping[str, float] | None = None,
) -> Dict[str, Any]:
    selected = _normalise_models(lab, models)
    warnings: list[str] = []

    if custom_weights:
        raw = np.array([max(float(custom_weights.get(model, 0.0)), 0.0) for model in selected], dtype=float)
        if float(raw.sum()) > 0:
            raw = raw / raw.sum()
            return {
                "models": selected,
                "weights": {model: float(weight) for model, weight in zip(selected, raw)},
                "method_requested": method,
                "method_effective": "Custom",
                "warnings": warnings,
            }
        warnings.append("Custom model weights were non-positive; equal weights applied.")

    validation_weights = _validation_weight_lookup(validation_result, selected, method)
    if validation_weights:
        missing = [model for model in selected if model not in validation_weights]
        if missing:
            warnings.append(
                "Validation weights were unavailable for: " + ", ".join(missing) + "; zero weight assigned."
            )
        weights = {model: float(validation_weights.get(model, 0.0)) for model in selected}
        total = float(sum(weights.values()))
        if total > 0:
            weights = {model: value / total for model, value in weights.items()}
            return {
                "models": selected,
                "weights": weights,
                "method_requested": method,
                "method_effective": method,
                "warnings": warnings,
            }

    if method != "Equal eligible":
        warnings.append("Requested validation weighting was unavailable; equal weights applied.")
    weight = 1.0 / len(selected)
    return {
        "models": selected,
        "weights": {model: weight for model in selected},
        "method_requested": method,
        "method_effective": "Equal eligible",
        "warnings": warnings,
    }


def _allocate_integer_counts(total: int, weights: Mapping[str, float]) -> Dict[str, int]:
    total = max(int(total), 1)
    models = list(weights)
    raw = np.array([max(float(weights[model]), 0.0) for model in models], dtype=float)
    raw = raw / raw.sum() if raw.sum() > 0 else np.full(len(models), 1.0 / len(models))
    exact = raw * total
    counts = np.floor(exact).astype(int)
    remainder = int(total - counts.sum())
    if remainder > 0:
        order = np.argsort(-(exact - counts))
        for idx in order[:remainder]:
            counts[idx] += 1
    return {model: int(count) for model, count in zip(models, counts)}


def _parameter_row(
    draw_id: int,
    model: str,
    draw_base: Mapping[str, Any],
    fit: Mapping[str, Any] | None,
    metadata: Mapping[str, Any],
) -> Dict[str, Any]:
    return {
        "Draw": int(draw_id),
        "Model": model,
        "Drift ann": float(draw_base.get("drift_ann", float("nan"))),
        "Vol ann": float(draw_base.get("vol_ann", float("nan"))),
        "EWMA vol ann": float(draw_base.get("ewma_vol_ann", float("nan"))),
        "Student df": float(draw_base.get("student_df", float("nan"))),
        "Persistence": float((fit or {}).get("persistence", float("nan"))),
        "Initial conditional vol ann": float((fit or {}).get("last_vol_ann", float("nan"))),
        "Long-run conditional vol ann": float((fit or {}).get("long_run_vol_ann", float("nan"))),
        "Calibration status": str((fit or {}).get("status", metadata.get("calibration_status", "NOT_REQUIRED"))),
        "Fallback used": bool(metadata.get("fallback_used", False)),
    }


def _draw_metric_row(draw_id: int, model: str, horizon: int, summary: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "Draw": int(draw_id),
        "Model": model,
        "Horizon": int(horizon),
        "Expected return": float(summary["expected_return"]),
        "Median return": float(summary["median_return"]),
        "VaR 5%": float(summary["var_5"]),
        "ES 5%": float(summary["es_5"]),
        "VaR 1%": float(summary["var_1"]),
        "ES 1%": float(summary["es_1"]),
        "Expected max drawdown": float(summary["expected_max_drawdown"]),
        "P(Ruin)": float(summary["prob_ruin"]),
        "P(Target before stop)": float(summary["prob_target_before_stop"]),
        "P(Stop before target)": float(summary["prob_stop_before_target"]),
        "Final-return variance": float(np.var(np.asarray(summary["final_returns"], dtype=float), ddof=0)),
    }


def _metric_interval_table(draw_metrics: pd.DataFrame, confidence: float) -> pd.DataFrame:
    if draw_metrics.empty:
        return pd.DataFrame()
    metrics = [
        ("Expected return", "rate"),
        ("Median return", "rate"),
        ("VaR 5%", "rate"),
        ("ES 5%", "rate"),
        ("VaR 1%", "rate"),
        ("ES 1%", "rate"),
        ("Expected max drawdown", "rate"),
        ("P(Ruin)", "pp"),
        ("P(Target before stop)", "pp"),
        ("P(Stop before target)", "pp"),
    ]
    rows: list[Dict[str, Any]] = []
    for horizon in sorted(draw_metrics["Horizon"].unique()):
        subset = draw_metrics[draw_metrics["Horizon"] == horizon]
        for metric, unit in metrics:
            low, median, high = _bootstrap_ci(subset[metric].to_numpy(float), confidence)
            rows.append(
                {
                    "Horizon": int(horizon),
                    "Metric": metric,
                    "Unit": unit,
                    "CI low": low,
                    "Median": median,
                    "CI high": high,
                    "Draws": int(len(subset)),
                }
            )
    return pd.DataFrame(rows)


def _parameter_interval_table(parameter_draws: pd.DataFrame, confidence: float) -> pd.DataFrame:
    if parameter_draws.empty:
        return pd.DataFrame()
    metrics = [
        ("Drift ann", "rate"),
        ("Vol ann", "rate"),
        ("EWMA vol ann", "rate"),
        ("Student df", "number"),
        ("Persistence", "number"),
        ("Initial conditional vol ann", "rate"),
        ("Long-run conditional vol ann", "rate"),
    ]
    rows: list[Dict[str, Any]] = []
    for model, subset in parameter_draws.groupby("Model", sort=False):
        for metric, unit in metrics:
            values = pd.to_numeric(subset[metric], errors="coerce").to_numpy(float)
            values = values[np.isfinite(values)]
            if values.size == 0:
                continue
            low, median, high = _bootstrap_ci(values, confidence)
            rows.append(
                {
                    "Model": model,
                    "Parameter": metric,
                    "Unit": unit,
                    "CI low": low,
                    "Median": median,
                    "CI high": high,
                    "Draws": int(values.size),
                }
            )
    return pd.DataFrame(rows)


def _variance_decomposition(draw_metrics: pd.DataFrame) -> pd.DataFrame:
    rows: list[Dict[str, Any]] = []
    if draw_metrics.empty:
        return pd.DataFrame()
    for horizon, subset in draw_metrics.groupby("Horizon"):
        means = subset["Expected return"].to_numpy(float)
        within = float(np.mean(np.maximum(subset["Final-return variance"].to_numpy(float), 0.0)))
        between_total = float(np.var(means, ddof=0)) if means.size else 0.0
        model_group = subset.groupby("Model")["Expected return"].agg(["mean", "count"])
        model_weights = model_group["count"].to_numpy(float)
        model_weights = model_weights / model_weights.sum()
        model_means = model_group["mean"].to_numpy(float)
        global_mean = float(np.sum(model_weights * model_means))
        model_component = float(np.sum(model_weights * (model_means - global_mean) ** 2))
        parameter_component = max(between_total - model_component, 0.0)
        total = max(within + between_total, EPS)
        rows.append(
            {
                "Horizon": int(horizon),
                "Aleatory variance": within,
                "Parameter variance": parameter_component,
                "Model variance": model_component,
                "Epistemic variance": parameter_component + model_component,
                "Total predictive variance": total,
                "Aleatory share": within / total,
                "Parameter share": parameter_component / total,
                "Model share": model_component / total,
                "Epistemic share": (parameter_component + model_component) / total,
            }
        )
    return pd.DataFrame(rows)


def _draw_convergence_table(draw_metrics: pd.DataFrame, horizon: int, confidence: float) -> pd.DataFrame:
    subset = draw_metrics[draw_metrics["Horizon"] == int(horizon)].sort_values("Draw")
    n_total = int(len(subset))
    candidates = [10, 20, 25, 50, 75, 100, 150, 200, 300, 500]
    sizes = [n for n in candidates if n <= n_total]
    if n_total and n_total not in sizes:
        sizes.append(n_total)
    rows = []
    for size in sorted(set(sizes)):
        sample = subset.head(size)
        er_low, er_med, er_high = _bootstrap_ci(sample["Expected return"], confidence)
        es_low, es_med, es_high = _bootstrap_ci(sample["ES 5%"], confidence)
        rows.append(
            {
                "Draws": int(size),
                "Expected return median": er_med,
                "Expected return CI low": er_low,
                "Expected return CI high": er_high,
                "Expected return CI width": er_high - er_low,
                "ES 5% median": es_med,
                "ES 5% CI low": es_low,
                "ES 5% CI high": es_high,
                "ES 5% CI width": es_high - es_low,
            }
        )
    return pd.DataFrame(rows)


def _summary_metadata(
    model: str,
    eligibility: Mapping[str, Any],
    monitoring: str,
) -> Dict[str, Any]:
    return {
        "model": model,
        "supports_bridge": model == "GBM normal",
        "calibration_status": "BOOTSTRAP_MIXTURE",
        "calibration_converged": True,
        "calibration_warning": "",
        "fallback_used": False,
        "eligibility_status": str(eligibility.get("status", "INELIGIBLE")),
        "eligibility_reasons": list(eligibility.get("reasons", [])),
        "eligible_for_aggregation": bool(eligibility.get("eligible_for_aggregation", False)),
        "research_only": bool(eligibility.get("research_only", True)),
        "barrier_monitoring_requested": monitoring,
        "barrier_monitoring_effective": monitoring,
        "barrier_monitoring_forced": False,
        "barrier_monitoring_warning": "",
    }


def _mix_fixed_parameter_paths(
    lab: Mapping[str, Any],
    weights: Mapping[str, float],
    simulations: int,
    scenario: str,
    seed: int,
    mean_block_length: int,
    ewma_lambda: float,
) -> tuple[np.ndarray, pd.DataFrame, ScenarioParameters]:
    counts = _allocate_integer_counts(simulations, weights)
    path_blocks: list[np.ndarray] = []
    rows: list[Dict[str, Any]] = []
    drift_values: list[float] = []
    vol_values: list[float] = []
    weight_values: list[float] = []
    for offset, model in enumerate(weights):
        count = counts.get(model, 0)
        if count <= 0:
            continue
        paths, params, metadata = simulate_paths_max_horizon(
            base=lab["base"],
            scenario=scenario,
            model=model,
            simulations=count,
            seed=seed + 700_001 + offset * 1009,
            max_horizon=MAX_HORIZON,
            mean_block_length=mean_block_length,
            ewma_lambda=ewma_lambda,
        )
        path_blocks.append(paths)
        final_returns = paths[:, -1] / float(lab["levels"]["current"]) - 1.0
        rows.append(
            {
                "Model": model,
                "Weight": float(weights[model]),
                "Paths": int(count),
                "Expected return 90D": float(np.mean(final_returns)),
                "Variance 90D": float(np.var(final_returns, ddof=0)),
                "Calibration status": metadata.get("calibration_status", "NOT_REQUIRED"),
                "Fallback used": bool(metadata.get("fallback_used", False)),
            }
        )
        drift_values.append(float(params.drift_ann))
        vol_values.append(float(params.vol_ann))
        weight_values.append(float(weights[model]))
    if not path_blocks:
        raise ValueError("No fixed-parameter model paths could be simulated.")
    combined = np.vstack(path_blocks)
    rng = np.random.default_rng(seed + 123_457)
    combined = combined[rng.permutation(len(combined))]
    w = np.asarray(weight_values, dtype=float)
    w = w / w.sum()
    params = ScenarioParameters(
        drift_ann=float(np.sum(w * np.asarray(drift_values))),
        vol_ann=float(np.sum(w * np.asarray(vol_values))),
        drift_multiplier=1.0,
        volatility_multiplier=1.0,
        note="Fixed-parameter model mixture used as aleatory benchmark.",
    )
    return combined, pd.DataFrame(rows), params


def _uncertainty_signature(lab: Mapping[str, Any], payload: Mapping[str, Any]) -> str:
    serializable = {
        "lab_signature": lab.get("configuration_signature"),
        "uncertainty_version": UNCERTAINTY_VERSION,
        **dict(payload),
    }
    raw = json.dumps(serializable, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16].upper()


def build_parameter_model_uncertainty(
    lab: Mapping[str, Any],
    models: Sequence[str] | None = None,
    weighting_method: str = "Equal eligible",
    validation_result: Mapping[str, Any] | None = None,
    parameter_draws: int = 100,
    paths_per_draw: int = 250,
    mean_block_length: int = 10,
    confidence_level: float = DEFAULT_CONFIDENCE,
    scenario: str | None = None,
    refit_conditional_models: bool = True,
    garch_maxiter: int | None = None,
    garch_min_observations: int | None = None,
    seed: int | None = None,
    custom_weights: Mapping[str, float] | None = None,
) -> Dict[str, Any]:
    """Bootstrap parameter and model uncertainty around the forward-risk engine.

    The procedure uses a stationary bootstrap of the calibration return history.
    It is a frequentist resampling diagnostic, not a Bayesian posterior.
    """
    if not isinstance(lab, Mapping) or not lab.get("ok"):
        return {"ok": False, "status": "BLOCKED", "reason": "A valid Monte Carlo lab is required."}

    parameter_draws = max(10, min(int(parameter_draws), 500))
    paths_per_draw = max(50, min(int(paths_per_draw), 2_000))
    mean_block_length = max(2, min(int(mean_block_length), 120))
    confidence_level = _clamp(float(confidence_level), 0.80, 0.999)
    scenario = str(scenario or lab.get("settings", {}).get("scenario", "Conservateur"))
    seed = int(seed if seed is not None else lab.get("settings", {}).get("seed", 42))
    garch_maxiter = int(garch_maxiter or lab.get("settings", {}).get("garch_maxiter", 800))
    garch_min_observations = int(
        garch_min_observations or lab.get("settings", {}).get("garch_min_observations", 120)
    )
    ewma_lambda = float(lab.get("settings", {}).get("ewma_lambda", 0.94))
    ruin_threshold = float(lab.get("settings", {}).get("ruin_threshold", -0.30))

    weight_result = resolve_uncertainty_model_weights(
        lab=lab,
        models=models,
        method=weighting_method,
        validation_result=validation_result,
        custom_weights=custom_weights,
    )
    selected_models = list(weight_result["models"])
    weights = dict(weight_result["weights"])
    if not selected_models:
        return {"ok": False, "status": "BLOCKED", "reason": "No simulation model selected."}

    original_returns = _finite_array(lab.get("base", {}).get("log_return_values", np.array([])))
    if original_returns.size < 60:
        return {
            "ok": False,
            "status": "BLOCKED",
            "reason": f"At least 60 calibration returns are required; {original_returns.size} available.",
        }

    common_monitoring = (
        "Brownian bridge (GBM)"
        if set(selected_models) == {"GBM normal"}
        and str(lab.get("settings", {}).get("barrier_monitoring")) == "Brownian bridge (GBM)"
        else "Clôture de chaque pas"
    )
    draw_counts = _allocate_integer_counts(parameter_draws, weights)
    model_schedule: list[str] = []
    for model, count in draw_counts.items():
        model_schedule.extend([model] * count)
    schedule_rng = np.random.default_rng(seed + 2_400_001)
    schedule_rng.shuffle(model_schedule)

    path_blocks: list[np.ndarray] = []
    parameter_rows: list[Dict[str, Any]] = []
    metric_rows: list[Dict[str, Any]] = []
    failed_rows: list[Dict[str, Any]] = []
    draw_scenario_params: list[ScenarioParameters] = []

    for draw_id, model in enumerate(model_schedule, start=1):
        draw_seed = seed + draw_id * 10_007 + list(MODELS).index(model) * 1_000_003
        rng = np.random.default_rng(draw_seed)
        try:
            sampled_returns = _stationary_bootstrap_sample(
                original_returns,
                rng=rng,
                mean_block_length=mean_block_length,
            )
            draw_base = _rebuild_base_from_log_returns(lab["base"], sampled_returns, ewma_lambda)
            fit = None
            if refit_conditional_models and model in _CONDITIONAL_FIT_MAP:
                fit = _refit_draw_conditional_model(
                    draw_base,
                    model=model,
                    maxiter=garch_maxiter,
                    min_observations=garch_min_observations,
                )
                if not fit or not fit.get("ok"):
                    raise RuntimeError(str((fit or {}).get("warning") or "conditional refit failed"))
            elif model in _CONDITIONAL_FIT_MAP:
                fit_name = _CONDITIONAL_FIT_MAP[model]
                fit = draw_base.get("conditional_calibrations", {}).get(fit_name)

            paths, params, metadata = simulate_paths_max_horizon(
                base=draw_base,
                scenario=scenario,
                model=model,
                simulations=paths_per_draw,
                seed=draw_seed + 97,
                max_horizon=MAX_HORIZON,
                mean_block_length=mean_block_length,
                ewma_lambda=ewma_lambda,
            )
            if metadata.get("fallback_used") and refit_conditional_models:
                raise RuntimeError(str(metadata.get("calibration_warning") or "conditional fallback used"))
            path_blocks.append(paths)
            draw_scenario_params.append(params)
            parameter_rows.append(_parameter_row(draw_id, model, draw_base, fit, metadata))

            eligibility = lab.get("model_eligibility", {}).get(model, {})
            summary_metadata = dict(metadata)
            summary_metadata.update(
                {
                    "eligibility_status": eligibility.get("status", "INELIGIBLE"),
                    "eligibility_reasons": list(eligibility.get("reasons", [])),
                    "eligible_for_aggregation": bool(eligibility.get("eligible_for_aggregation", False)),
                    "research_only": bool(eligibility.get("research_only", True)),
                    "barrier_monitoring_requested": common_monitoring,
                    "barrier_monitoring_effective": common_monitoring,
                    "barrier_monitoring_forced": common_monitoring != lab.get("settings", {}).get("barrier_monitoring"),
                    "barrier_monitoring_warning": "Common discrete monitoring used for cross-model comparability."
                    if common_monitoring == "Clôture de chaque pas" and len(selected_models) > 1
                    else "",
                }
            )
            for horizon in DEFAULT_HORIZONS:
                summary = _summarize_paths(
                    paths=paths,
                    levels=lab["levels_object"],
                    params=params,
                    model_metadata=summary_metadata,
                    horizon=int(horizon),
                    scenario=scenario,
                    model=model,
                    monitoring=common_monitoring,
                    seed=draw_seed + int(horizon),
                    confidence=confidence_level,
                    ruin_threshold=ruin_threshold,
                    include_diagnostics=True,
                )
                metric_rows.append(_draw_metric_row(draw_id, model, int(horizon), summary))
        except Exception as exc:
            failed_rows.append({"Draw": int(draw_id), "Model": model, "Reason": str(exc)})

    successful_draws = int(len(path_blocks))
    failure_count = int(len(failed_rows))
    failure_rate = failure_count / max(parameter_draws, 1)
    if successful_draws < 10:
        return {
            "ok": False,
            "status": "BLOCKED",
            "reason": f"Only {successful_draws} successful parameter draws were produced.",
            "failed_draws": pd.DataFrame(failed_rows),
            "weight_resolution": weight_result,
        }

    combined_paths = np.vstack(path_blocks)
    combined_rng = np.random.default_rng(seed + 2_400_101)
    combined_paths = combined_paths[combined_rng.permutation(len(combined_paths))]

    fixed_paths, model_contribution_table, fixed_params = _mix_fixed_parameter_paths(
        lab=lab,
        weights=weights,
        simulations=len(combined_paths),
        scenario=scenario,
        seed=seed,
        mean_block_length=mean_block_length,
        ewma_lambda=ewma_lambda,
    )

    if draw_scenario_params:
        total_params = ScenarioParameters(
            drift_ann=float(np.mean([param.drift_ann for param in draw_scenario_params])),
            vol_ann=float(np.mean([param.vol_ann for param in draw_scenario_params])),
            drift_multiplier=float(np.mean([param.drift_multiplier for param in draw_scenario_params])),
            volatility_multiplier=float(np.mean([param.volatility_multiplier for param in draw_scenario_params])),
            note="Stationary-bootstrap parameter and model mixture.",
        )
    else:
        total_params = fixed_params

    generic_eligibility = {
        "status": "ELIGIBLE" if all(
            str(lab.get("model_eligibility", {}).get(model, {}).get("status")) == "ELIGIBLE"
            for model in selected_models
        ) else "WARNING",
        "reasons": [],
        "eligible_for_aggregation": True,
        "research_only": False,
    }
    generic_model_name = selected_models[0] if len(selected_models) == 1 else "Parameter/model mixture"
    generic_metadata = _summary_metadata(generic_model_name, generic_eligibility, common_monitoring)

    paths_by_horizon: Dict[int, np.ndarray] = {}
    fixed_paths_by_horizon: Dict[int, np.ndarray] = {}
    summaries_by_horizon: Dict[int, Dict[str, Any]] = {}
    fixed_summaries_by_horizon: Dict[int, Dict[str, Any]] = {}
    for horizon in DEFAULT_HORIZONS:
        paths_by_horizon[int(horizon)] = combined_paths[:, : int(horizon) + 1]
        fixed_paths_by_horizon[int(horizon)] = fixed_paths[:, : int(horizon) + 1]
        summaries_by_horizon[int(horizon)] = _summarize_paths(
            paths=combined_paths,
            levels=lab["levels_object"],
            params=total_params,
            model_metadata=generic_metadata,
            horizon=int(horizon),
            scenario=scenario,
            model=generic_model_name,
            monitoring=common_monitoring,
            seed=seed + 500_000 + int(horizon),
            confidence=confidence_level,
            ruin_threshold=ruin_threshold,
            include_diagnostics=True,
        )
        fixed_summaries_by_horizon[int(horizon)] = _summarize_paths(
            paths=fixed_paths,
            levels=lab["levels_object"],
            params=fixed_params,
            model_metadata=generic_metadata,
            horizon=int(horizon),
            scenario=scenario,
            model=generic_model_name,
            monitoring=common_monitoring,
            seed=seed + 600_000 + int(horizon),
            confidence=confidence_level,
            ruin_threshold=ruin_threshold,
            include_diagnostics=True,
        )

    parameter_draw_table = pd.DataFrame(parameter_rows)
    draw_metric_table = pd.DataFrame(metric_rows)
    failed_draw_table = pd.DataFrame(failed_rows)
    metric_intervals = _metric_interval_table(draw_metric_table, confidence_level)
    parameter_intervals = _parameter_interval_table(parameter_draw_table, confidence_level)
    variance_decomposition = _variance_decomposition(draw_metric_table)
    convergence = {
        int(horizon): _draw_convergence_table(draw_metric_table, int(horizon), confidence_level)
        for horizon in DEFAULT_HORIZONS
    }

    if successful_draws >= 50 and failure_rate <= 0.10:
        status = "ACTIVE"
    elif successful_draws >= 20 and failure_rate <= 0.30:
        status = "WARNING"
    else:
        status = "RESEARCH_ONLY"
    warnings = list(weight_result.get("warnings", []))
    if failure_rate > 0:
        warnings.append(f"{failure_count}/{parameter_draws} parameter draws failed ({failure_rate:.1%}).")
    if not refit_conditional_models and any(model in _CONDITIONAL_FIT_MAP for model in selected_models):
        warnings.append("Conditional models were not refitted inside bootstrap draws; conditional-parameter uncertainty is partial.")
    if len(selected_models) == 1:
        warnings.append("Model-uncertainty component is zero because only one simulation engine was selected.")

    payload = {
        "models": selected_models,
        "weights": weights,
        "weighting_method": weight_result["method_effective"],
        "parameter_draws": parameter_draws,
        "paths_per_draw": paths_per_draw,
        "mean_block_length": mean_block_length,
        "confidence_level": confidence_level,
        "scenario": scenario,
        "refit_conditional_models": bool(refit_conditional_models),
        "seed": seed,
    }
    signature = _uncertainty_signature(lab, payload)

    return {
        "ok": True,
        "status": status,
        "uncertainty_version": UNCERTAINTY_VERSION,
        "configuration_signature": signature,
        "ticker": lab.get("ticker"),
        "scenario": scenario,
        "models": selected_models,
        "weights": weights,
        "weight_resolution": weight_result,
        "requested_draws": int(parameter_draws),
        "successful_draws": successful_draws,
        "failed_draw_count": failure_count,
        "failure_rate": float(failure_rate),
        "paths_per_draw": int(paths_per_draw),
        "total_predictive_paths": int(len(combined_paths)),
        "mean_block_length": int(mean_block_length),
        "confidence_level": float(confidence_level),
        "refit_conditional_models": bool(refit_conditional_models),
        "common_barrier_monitoring": common_monitoring,
        "paths_by_horizon": paths_by_horizon,
        "fixed_paths_by_horizon": fixed_paths_by_horizon,
        "summaries_by_horizon": summaries_by_horizon,
        "fixed_summaries_by_horizon": fixed_summaries_by_horizon,
        "parameter_draw_table": parameter_draw_table,
        "draw_metric_table": draw_metric_table,
        "failed_draws": failed_draw_table,
        "parameter_interval_table": parameter_intervals,
        "metric_interval_table": metric_intervals,
        "variance_decomposition": variance_decomposition,
        "model_contribution_table": model_contribution_table,
        "draw_convergence": convergence,
        "levels": dict(lab["levels"]),
        "base": lab["base"],
        "warnings": warnings,
        "assumptions": {
            "method": "Stationary bootstrap of calibration log returns with nested forward simulation",
            "uncertainty_taxonomy": {
                "aleatory": "Average within-draw terminal-return variance",
                "parameter": "Between-draw mean variance net of model component",
                "model": "Weighted variance of model-specific draw means",
            },
            "interpretation": "Frequentist resampling diagnostic; not a Bayesian posterior and not an alpha estimate.",
            "barrier_monitoring": common_monitoring,
            "conditional_refit": bool(refit_conditional_models),
            "limitations": [
                "Bootstrap intervals inherit the historical sample and block-length assumptions.",
                "Variance decomposition is an operational law-of-total-variance approximation.",
                "Model uncertainty is conditional on the selected model set and weighting rule.",
                "Parameter and model uncertainty are estimated jointly; interaction terms are allocated to parameter uncertainty after the model-mean component.",
            ],
        },
    }


__all__ = [
    "UNCERTAINTY_VERSION",
    "UNCERTAINTY_WEIGHTING_METHODS",
    "build_parameter_model_uncertainty",
    "resolve_uncertainty_model_weights",
]
