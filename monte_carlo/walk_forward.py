from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict
from typing import Any, Callable, Dict, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from .barriers import _build_levels, resolve_barrier_monitoring
from .calibration import fit_conditional_model_set
from .config import (
    BRIDGE_COMPATIBLE_MODELS,
    CONDITIONAL_MODEL_NAMES,
    DEFAULT_CONFIDENCE,
    MODEL_ALIASES,
    MODELS,
    SCENARIOS,
    VALIDATION_HORIZONS,
    VALIDATION_QUANTILES,
    WalkForwardSettings,
)
from .data_quality import _normalize_price_data, _prepare_base
from .eligibility import build_model_eligibility, ljung_box_p_value
from .models.dispatcher import simulate_paths_max_horizon
from .risk_metrics import _summarize_paths
from .utils import _clamp, _jsonable
from .validation import _christoffersen_independence, _kupiec_unconditional_coverage

try:
    from scipy.special import logsumexp
    from scipy.stats import chi2, kstest, norm, ttest_1samp
except Exception:  # pragma: no cover
    logsumexp = None
    chi2 = None
    kstest = None
    norm = None
    ttest_1samp = None

ProgressCallback = Callable[[int, int, str], None]

_CONDITIONAL_SIMULATION_MODELS = {
    "GARCH(1,1) normal",
    "GARCH(1,1) Student-t",
    "GJR-GARCH Student-t",
    "Filtered historical GARCH-t",
}


def _walk_forward_signature(ticker: str, settings: WalkForwardSettings, models: Sequence[str], rows: int) -> str:
    payload = {
        "ticker": str(ticker),
        "settings": asdict(settings),
        "models": list(models),
        "rows": int(rows),
    }
    encoded = json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16].upper()


def _canonical_models(models: Iterable[str] | None) -> list[str]:
    requested = list(models or MODELS)
    output: list[str] = []
    for model in requested:
        canonical = MODEL_ALIASES.get(str(model), str(model))
        if canonical in MODELS and canonical not in output:
            output.append(canonical)
    return output


def _empirical_crps(samples: np.ndarray, realized: float) -> float:
    x = np.asarray(samples, dtype=float)
    x = x[np.isfinite(x)]
    if x.size == 0 or not np.isfinite(realized):
        return float("nan")
    x.sort()
    n = x.size
    first_term = float(np.mean(np.abs(x - realized)))
    coefficients = 2.0 * np.arange(1, n + 1, dtype=float) - n - 1.0
    pairwise_half = float(np.dot(coefficients, x) / (n * n))
    return max(0.0, first_term - pairwise_half)


def _kernel_log_score(samples: np.ndarray, realized: float) -> float:
    x = np.asarray(samples, dtype=float)
    x = x[np.isfinite(x)]
    if x.size < 5 or not np.isfinite(realized):
        return float("nan")
    std = float(np.std(x, ddof=1))
    iqr = float(np.subtract(*np.percentile(x, [75, 25])))
    robust_scale = min(std, iqr / 1.349) if iqr > 0 else std
    robust_scale = max(robust_scale, 1e-5)
    bandwidth = max(0.9 * robust_scale * x.size ** (-1.0 / 5.0), 1e-4)
    z = (realized - x) / bandwidth
    log_terms = -0.5 * z * z - math.log(bandwidth) - 0.5 * math.log(2.0 * math.pi)
    if logsumexp is not None:
        return float(logsumexp(log_terms) - math.log(x.size))
    maximum = float(np.max(log_terms))
    density_log = maximum + math.log(float(np.mean(np.exp(log_terms - maximum))))
    return float(max(density_log, -100.0))


def _pit_value(samples: np.ndarray, realized: float) -> float:
    x = np.asarray(samples, dtype=float)
    x = x[np.isfinite(x)]
    if x.size == 0 or not np.isfinite(realized):
        return float("nan")
    less = int(np.sum(x < realized))
    equal = int(np.sum(x == realized))
    return float((less + 0.5 * equal + 0.5) / (x.size + 1.0))


def _interval_score(realized: float, lower: float, upper: float, alpha: float = 0.10) -> float:
    if not all(np.isfinite(value) for value in (realized, lower, upper)) or upper < lower:
        return float("nan")
    score = upper - lower
    if realized < lower:
        score += 2.0 / alpha * (lower - realized)
    elif realized > upper:
        score += 2.0 / alpha * (realized - upper)
    return float(score)


def _quantile_loss(realized: float, quantile: float, forecast: float) -> float:
    error = realized - forecast
    return float((quantile - (1.0 if error < 0.0 else 0.0)) * error)


def _actual_barrier_outcome(
    future: pd.DataFrame,
    levels: Mapping[str, float],
    monitoring: str,
) -> Dict[str, Any]:
    if future.empty:
        return {"outcome": "neither", "target_day": float("nan"), "stop_day": float("nan")}
    close = pd.to_numeric(future["close"], errors="coerce").to_numpy(dtype=float)
    if monitoring == "Brownian bridge (GBM)":
        high = pd.to_numeric(future.get("high", future["close"]), errors="coerce").to_numpy(dtype=float)
        low = pd.to_numeric(future.get("low", future["close"]), errors="coerce").to_numpy(dtype=float)
    else:
        high = close
        low = close
    target_hits = np.flatnonzero(high >= float(levels["target_1"]))
    stop_hits = np.flatnonzero(low <= float(levels["stop_short"]))
    target_day = float(target_hits[0] + 1) if target_hits.size else float("nan")
    stop_day = float(stop_hits[0] + 1) if stop_hits.size else float("nan")

    if np.isfinite(target_day) and np.isfinite(stop_day):
        if target_day < stop_day:
            outcome = "target"
        elif stop_day < target_day:
            outcome = "stop"
        else:
            outcome = "ambiguous"
    elif np.isfinite(target_day):
        outcome = "target"
    elif np.isfinite(stop_day):
        outcome = "stop"
    else:
        outcome = "neither"
    return {"outcome": outcome, "target_day": target_day, "stop_day": stop_day}


def _multiclass_brier(probabilities: Sequence[float], observed_index: int) -> float:
    p = np.asarray(probabilities, dtype=float)
    p = np.clip(p, 0.0, 1.0)
    total = float(np.sum(p))
    if total <= 0:
        return float("nan")
    p = p / total
    y = np.zeros_like(p)
    y[int(observed_index)] = 1.0
    return float(np.mean((p - y) ** 2))


def _origin_indexes(
    rows: int,
    horizon: int,
    minimum_training_observations: int,
    forecast_origins: int,
    origin_stride: int,
) -> list[int]:
    first = max(int(minimum_training_observations), 40)
    last = int(rows) - int(horizon) - 1
    if last < first:
        return []
    candidates = list(range(first, last + 1, max(1, int(origin_stride))))
    if len(candidates) > int(forecast_origins):
        candidates = candidates[-int(forecast_origins):]
    return candidates


def _conditional_coverage(exceptions: np.ndarray, alpha: float) -> Dict[str, float]:
    kupiec = _kupiec_unconditional_coverage(exceptions, alpha)
    independence = _christoffersen_independence(exceptions)
    lr = float(kupiec.get("lr", float("nan"))) + float(independence.get("lr", float("nan")))
    p_value = float(chi2.sf(lr, 2)) if chi2 is not None and np.isfinite(lr) else float("nan")
    return {
        "exception_rate": float(np.mean(exceptions)) if len(exceptions) else float("nan"),
        "kupiec_p": float(kupiec.get("p_value", float("nan"))),
        "independence_p": float(independence.get("p_value", float("nan"))),
        "conditional_coverage_p": p_value,
    }


def _pit_diagnostics(values: np.ndarray) -> Dict[str, float]:
    pits = np.asarray(values, dtype=float)
    pits = pits[np.isfinite(pits)]
    if pits.size == 0:
        return {
            "pit_mean": float("nan"),
            "pit_std": float("nan"),
            "pit_ks_p": float("nan"),
            "pit_ljung_box_p": float("nan"),
        }
    ks_p = float(kstest(pits, "uniform").pvalue) if kstest is not None and pits.size >= 8 else float("nan")
    return {
        "pit_mean": float(np.mean(pits)),
        "pit_std": float(np.std(pits, ddof=1)) if pits.size > 1 else float("nan"),
        "pit_ks_p": ks_p,
        "pit_ljung_box_p": float(ljung_box_p_value(pits - 0.5, lags=5)),
    }


def _validation_status(row: Mapping[str, Any]) -> str:
    n = int(row.get("Forecasts", 0))
    fallback = float(row.get("Fallback rate", 0.0))
    pit_p = float(row.get("PIT KS p", float("nan")))
    kupiec = float(row.get("VaR 5% Kupiec p", float("nan")))
    conditional = float(row.get("VaR 5% conditional p", float("nan")))
    if n < 8:
        return "INSUFFICIENT"
    if fallback > 0.20 or (np.isfinite(kupiec) and kupiec < 0.01) or (np.isfinite(pit_p) and pit_p < 0.01):
        return "REJECTED"
    if n >= 20 and fallback == 0.0 and all(
        not np.isfinite(value) or value >= 0.05 for value in (pit_p, kupiec, conditional)
    ):
        return "VALIDATED"
    return "WARNING"


def _aggregate_model_forecasts(forecasts: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for model, group in forecasts.groupby("model", sort=False):
        group = group.sort_values("origin_date").reset_index(drop=True)
        realized = group["realized_return"].to_numpy(dtype=float)
        var5_ex = group["var_5_exception"].to_numpy(dtype=bool)
        var1_ex = group["var_1_exception"].to_numpy(dtype=bool)
        coverage5 = _conditional_coverage(var5_ex, 0.05)
        coverage1 = _conditional_coverage(var1_ex, 0.01)
        pit = _pit_diagnostics(group["pit"].to_numpy(dtype=float))

        tail5 = group.loc[group["var_5_exception"], "realized_return"].to_numpy(dtype=float)
        predicted_es5 = group.loc[group["var_5_exception"], "es_5"].to_numpy(dtype=float)
        es_residuals = tail5 - predicted_es5
        es_t_p = float(ttest_1samp(es_residuals, 0.0, nan_policy="omit").pvalue) if (
            ttest_1samp is not None and es_residuals.size >= 5
        ) else float("nan")
        es_ratio = (
            float(abs(np.mean(tail5)) / max(abs(np.mean(predicted_es5)), 1e-12))
            if tail5.size and predicted_es5.size
            else float("nan")
        )

        resolved = group[group["actual_barrier_outcome"].isin(["target", "stop"])]
        target_brier = float(np.mean((resolved["prob_target_before_stop"] / 100.0 - (resolved["actual_barrier_outcome"] == "target").astype(float)) ** 2)) if not resolved.empty else float("nan")

        row = {
            "Model": model,
            "Forecasts": int(len(group)),
            "First origin": group["origin_date"].min(),
            "Last realization": group["realization_date"].max(),
            "Mean CRPS": float(group["crps"].mean()),
            "Median CRPS": float(group["crps"].median()),
            "Mean log score": float(group["log_score"].mean()),
            "Mean interval score 90%": float(group["interval_score_90"].mean()),
            "PIT mean": pit["pit_mean"],
            "PIT std": pit["pit_std"],
            "PIT KS p": pit["pit_ks_p"],
            "PIT independence p": pit["pit_ljung_box_p"],
            "Coverage 90%": float(group["inside_90"].mean()),
            "Coverage 50%": float(group["inside_50"].mean()),
            "VaR 5% exception rate": coverage5["exception_rate"],
            "VaR 5% Kupiec p": coverage5["kupiec_p"],
            "VaR 5% independence p": coverage5["independence_p"],
            "VaR 5% conditional p": coverage5["conditional_coverage_p"],
            "VaR 1% exception rate": coverage1["exception_rate"],
            "VaR 1% Kupiec p": coverage1["kupiec_p"],
            "ES 5% exceedances": int(tail5.size),
            "ES 5% residual mean": float(np.mean(es_residuals)) if es_residuals.size else float("nan"),
            "ES 5% residual p": es_t_p,
            "ES 5% severity ratio": es_ratio,
            "Positive-return Brier": float(group["positive_brier"].mean()),
            "Barrier multiclass Brier": float(group["barrier_multiclass_brier"].mean()),
            "Resolved target Brier": target_brier,
            "Resolved barriers": int(len(resolved)),
            "Fallback rate": float(group["fallback_used"].mean()),
            "Eligible-origin share": float(group["eligible_at_origin"].mean()),
            "Mean training observations": float(group["training_observations"].mean()),
        }
        row["Coverage penalty"] = (
            abs(row["Coverage 90%"] - 0.90)
            + abs(row["Coverage 50%"] - 0.50)
            + abs(row["VaR 5% exception rate"] - 0.05)
        )
        row["Validation status"] = _validation_status(row)
        rows.append(row)

    leaderboard = pd.DataFrame(rows)
    if leaderboard.empty:
        return leaderboard

    rank_specs = {
        "Mean CRPS": True,
        "Mean log score": False,
        "Mean interval score 90%": True,
        "Coverage penalty": True,
        "Positive-return Brier": True,
        "Barrier multiclass Brier": True,
    }
    rank_columns: list[str] = []
    for column, ascending in rank_specs.items():
        rank_name = f"Rank {column}"
        values = leaderboard[column].replace([np.inf, -np.inf], np.nan)
        leaderboard[rank_name] = values.rank(method="average", ascending=ascending, na_option="bottom")
        rank_columns.append(rank_name)
    leaderboard["Average rank"] = leaderboard[rank_columns].mean(axis=1)
    status_penalty = leaderboard["Validation status"].map(
        {"VALIDATED": 0.0, "WARNING": 1.0, "INSUFFICIENT": 3.0, "REJECTED": 5.0}
    ).fillna(3.0)
    leaderboard["Governed rank score"] = leaderboard["Average rank"] + status_penalty
    leaderboard = leaderboard.sort_values(["Governed rank score", "Mean CRPS"], ascending=[True, True]).reset_index(drop=True)
    leaderboard["Validation rank"] = np.arange(1, len(leaderboard) + 1)
    return leaderboard


def _quantile_calibration(forecasts: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for model, group in forecasts.groupby("model", sort=False):
        realized = group["realized_return"].to_numpy(dtype=float)
        for q in VALIDATION_QUANTILES:
            column = f"q_{int(round(q * 100)):02d}"
            predicted = group[column].to_numpy(dtype=float)
            valid = np.isfinite(realized) & np.isfinite(predicted)
            observed = float(np.mean(realized[valid] <= predicted[valid])) if np.any(valid) else float("nan")
            loss = float(np.mean([_quantile_loss(y, q, f) for y, f in zip(realized[valid], predicted[valid])])) if np.any(valid) else float("nan")
            rows.append(
                {
                    "Model": model,
                    "Quantile": q,
                    "Nominal coverage": q,
                    "Observed coverage": observed,
                    "Calibration error": observed - q if np.isfinite(observed) else float("nan"),
                    "Pinball loss": loss,
                    "Forecasts": int(np.sum(valid)),
                }
            )
    return pd.DataFrame(rows)


def _pit_histogram(forecasts: pd.DataFrame, bins: int = 10) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    edges = np.linspace(0.0, 1.0, bins + 1)
    for model, group in forecasts.groupby("model", sort=False):
        values = group["pit"].to_numpy(dtype=float)
        values = values[np.isfinite(values)]
        counts, _ = np.histogram(values, bins=edges)
        for idx, count in enumerate(counts):
            rows.append(
                {
                    "Model": model,
                    "Bin left": float(edges[idx]),
                    "Bin right": float(edges[idx + 1]),
                    "Bin midpoint": float((edges[idx] + edges[idx + 1]) / 2.0),
                    "Count": int(count),
                    "Frequency": float(count / max(values.size, 1)),
                }
            )
    return pd.DataFrame(rows)


def _reliability_table(forecasts: pd.DataFrame, bins: int = 5) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    edges = np.linspace(0.0, 1.0, bins + 1)
    for model, group in forecasts.groupby("model", sort=False):
        for event_name, probability_column, outcome in (
            ("Positive return", "prob_positive", (group["realized_return"] > 0.0).astype(float)),
            ("Target before stop", "prob_target_before_stop", (group["actual_barrier_outcome"] == "target").astype(float)),
        ):
            probabilities = group[probability_column].to_numpy(dtype=float) / 100.0
            outcomes = np.asarray(outcome, dtype=float)
            valid = np.isfinite(probabilities) & np.isfinite(outcomes)
            if event_name == "Target before stop":
                valid &= group["actual_barrier_outcome"].isin(["target", "stop"]).to_numpy(dtype=bool)
            for idx in range(bins):
                lower, upper = edges[idx], edges[idx + 1]
                if idx == bins - 1:
                    mask = valid & (probabilities >= lower) & (probabilities <= upper)
                else:
                    mask = valid & (probabilities >= lower) & (probabilities < upper)
                if not np.any(mask):
                    continue
                rows.append(
                    {
                        "Model": model,
                        "Event": event_name,
                        "Bin left": lower,
                        "Bin right": upper,
                        "Forecast probability": float(np.mean(probabilities[mask])),
                        "Observed frequency": float(np.mean(outcomes[mask])),
                        "Count": int(np.sum(mask)),
                    }
                )
    return pd.DataFrame(rows)


def _validation_warnings(settings: WalkForwardSettings, models: Sequence[str], origins: int, rows: int) -> list[str]:
    warnings: list[str] = []
    if rows < 500:
        warnings.append("Validation history below 500 price observations; conditional-model results are research-only.")
    if origins < 20:
        warnings.append("Fewer than 20 forecast origins; coverage and PIT tests have low statistical power.")
    if settings.paths_per_origin < 500:
        warnings.append("Fewer than 500 paths per origin; tail-score Monte Carlo noise may be material.")
    if settings.origin_stride < settings.horizon:
        warnings.append(
            "Forecast windows overlap because origin stride is shorter than the horizon; coverage-test independence assumptions are weakened."
        )
    if settings.conditional_refit_every > 1 and any(model in _CONDITIONAL_SIMULATION_MODELS for model in models):
        warnings.append(
            f"Conditional models are refit every {settings.conditional_refit_every} origins; intermediate forecasts reuse the latest fit."
        )
    if settings.scenario != "Neutre":
        warnings.append("Walk-forward validation uses a non-neutral drift overlay; distribution scores include that drift policy.")
    return warnings


def build_walk_forward_validation(
    ticker: str,
    price_data: pd.DataFrame,
    models: Sequence[str] | None = None,
    horizon: int = 7,
    forecast_origins: int = 12,
    origin_stride: int = 5,
    paths_per_origin: int = 500,
    scenario: str = "Neutre",
    training_window: int | None = None,
    minimum_training_observations: int = 120,
    conditional_refit_every: int = 1,
    seed: int = 42,
    mean_block_length: int = 10,
    ewma_lambda: float = 0.94,
    garch_maxiter: int = 500,
    garch_min_observations: int = 120,
    stability_check: bool = False,
    confidence_level: float = DEFAULT_CONFIDENCE,
    progress_callback: ProgressCallback | None = None,
) -> Dict[str, Any]:
    """Leakage-safe rolling-origin distribution validation.

    Each origin uses only observations available at that date. The function produces
    model-specific predictive distributions and evaluates PIT, CRPS, kernel log score,
    interval coverage, VaR/ES diagnostics, and realized barrier outcomes.
    """
    frame, quality = _normalize_price_data(price_data)
    if frame.empty:
        return {"ok": False, "reason": "Validation history is empty after normalization."}

    horizon = int(horizon)
    if horizon not in VALIDATION_HORIZONS:
        return {"ok": False, "reason": f"Unsupported validation horizon: {horizon}."}
    scenario = str(scenario)
    if scenario not in SCENARIOS:
        scenario = "Neutre"
    canonical_models = _canonical_models(models)
    if not canonical_models:
        return {"ok": False, "reason": "No valid simulation model selected for walk-forward validation."}

    settings = WalkForwardSettings(
        horizon=horizon,
        forecast_origins=max(3, min(int(forecast_origins), 250)),
        origin_stride=max(1, min(int(origin_stride), 60)),
        paths_per_origin=max(200, min(int(paths_per_origin), 10_000)),
        scenario=scenario,
        training_window=int(training_window) if training_window not in (None, 0) else None,
        minimum_training_observations=max(60, int(minimum_training_observations)),
        conditional_refit_every=max(1, min(int(conditional_refit_every), 20)),
        seed=int(seed),
        mean_block_length=max(2, int(mean_block_length)),
        ewma_lambda=_clamp(float(ewma_lambda), 0.50, 0.999),
        garch_maxiter=max(100, min(int(garch_maxiter), 2_000)),
        garch_min_observations=max(60, min(int(garch_min_observations), 2_000)),
        stability_check=bool(stability_check),
        confidence_level=_clamp(float(confidence_level), 0.80, 0.999),
    )

    origins = _origin_indexes(
        rows=len(frame),
        horizon=settings.horizon,
        minimum_training_observations=settings.minimum_training_observations,
        forecast_origins=settings.forecast_origins,
        origin_stride=settings.origin_stride,
    )
    if not origins:
        return {
            "ok": False,
            "reason": (
                f"Insufficient history for {settings.horizon}D walk-forward validation: "
                f"{len(frame)} prices, minimum training {settings.minimum_training_observations}."
            ),
        }

    forecast_rows: list[dict[str, Any]] = []
    conditional_cache: Dict[str, Any] | None = None
    cache_origin_position = -1
    total_jobs = len(origins) * len(canonical_models)
    completed = 0

    for origin_position, origin_idx in enumerate(origins):
        train_start = 0
        if settings.training_window is not None:
            train_start = max(0, origin_idx - settings.training_window)
        training = frame.iloc[train_start : origin_idx + 1].copy().reset_index(drop=True)
        future = frame.iloc[origin_idx + 1 : origin_idx + settings.horizon + 1].copy().reset_index(drop=True)
        if len(future) < settings.horizon:
            continue

        base = _prepare_base(
            training,
            analysis={},
            ewma_lambda=settings.ewma_lambda,
            calibration_data=training,
            calibration_window=None,
            calibration_source_label="walk_forward_training",
            calibration_source_report={
                "selected_source": "walk_forward_training",
                "warnings": [],
                "leakage_control": "training sample ends at forecast origin",
            },
        )
        if not base.get("ok"):
            for model in canonical_models:
                completed += 1
                if progress_callback:
                    progress_callback(completed, total_jobs, f"Skipped origin {origin_position + 1}: base preparation failed")
            continue

        needs_conditional = any(model in _CONDITIONAL_SIMULATION_MODELS for model in canonical_models)
        should_refit = (
            conditional_cache is None
            or origin_position == 0
            or (origin_position - cache_origin_position) >= settings.conditional_refit_every
        )
        if needs_conditional and should_refit:
            conditional_cache = fit_conditional_model_set(
                base,
                maxiter=settings.garch_maxiter,
                min_observations=settings.garch_min_observations,
                stability_check=settings.stability_check,
            )
            cache_origin_position = origin_position
        elif not needs_conditional:
            conditional_cache = {}
        base["conditional_calibrations"] = conditional_cache or {}
        eligibility = build_model_eligibility(base, base["conditional_calibrations"])
        levels_object = _build_levels(base)
        levels = asdict(levels_object)

        current = float(training["close"].iloc[-1])
        realized_return = float(future["close"].iloc[-1] / current - 1.0)
        for model in canonical_models:
            monitoring = resolve_barrier_monitoring(model, "Brownian bridge (GBM)")
            actual_barrier = _actual_barrier_outcome(future, levels, str(monitoring["effective"]))
            outcome_index = {"target": 0, "stop": 1, "ambiguous": 2, "neither": 3}[actual_barrier["outcome"]]
            item = eligibility.get(model, {})
            paths, params, metadata = simulate_paths_max_horizon(
                base=base,
                scenario=settings.scenario,
                model=model,
                simulations=settings.paths_per_origin,
                seed=settings.seed + origin_idx * 1009,
                max_horizon=settings.horizon,
                mean_block_length=settings.mean_block_length,
                ewma_lambda=settings.ewma_lambda,
            )
            metadata = dict(metadata)
            metadata.update(
                {
                    "eligibility_status": item.get("status", "INELIGIBLE"),
                    "eligibility_reasons": list(item.get("reasons", [])),
                    "eligible_for_aggregation": bool(item.get("eligible_for_aggregation", False)),
                    "research_only": bool(item.get("research_only", True)),
                    "barrier_monitoring_requested": monitoring["requested"],
                    "barrier_monitoring_effective": monitoring["effective"],
                    "barrier_monitoring_forced": bool(monitoring["forced"]),
                    "barrier_monitoring_warning": monitoring.get("warning", ""),
                }
            )
            summary = _summarize_paths(
                paths=paths,
                levels=levels_object,
                params=params,
                model_metadata=metadata,
                horizon=settings.horizon,
                scenario=settings.scenario,
                model=model,
                monitoring=str(monitoring["effective"]),
                seed=settings.seed + origin_idx * 1009,
                confidence=settings.confidence_level,
                ruin_threshold=-0.30,
                include_diagnostics=True,
            )
            samples = np.asarray(summary["final_returns"], dtype=float)
            quantiles = np.quantile(samples, VALIDATION_QUANTILES)
            qmap = {f"q_{int(round(q * 100)):02d}": float(value) for q, value in zip(VALIDATION_QUANTILES, quantiles)}
            pit = _pit_value(samples, realized_return)
            crps = _empirical_crps(samples, realized_return)
            log_score = _kernel_log_score(samples, realized_return)
            interval_score = _interval_score(realized_return, qmap["q_05"], qmap["q_95"], alpha=0.10)
            positive_probability = float(summary["prob_positive"]) / 100.0
            positive_outcome = 1.0 if realized_return > 0.0 else 0.0
            class_probabilities = [
                float(summary["prob_target_before_stop"]) / 100.0,
                float(summary["prob_stop_before_target"]) / 100.0,
                float(summary["prob_same_day_ambiguous"]) / 100.0,
                float(summary["prob_neither"]) / 100.0,
            ]

            row: dict[str, Any] = {
                "ticker": ticker,
                "model": model,
                "scenario": settings.scenario,
                "horizon": settings.horizon,
                "origin_index": int(origin_idx),
                "origin_date": pd.Timestamp(training["date"].iloc[-1]),
                "realization_date": pd.Timestamp(future["date"].iloc[-1]),
                "training_start": pd.Timestamp(training["date"].iloc[0]),
                "training_observations": int(base["calibration_observations"]),
                "realized_return": realized_return,
                "predictive_mean": float(summary["expected_return"]),
                "predictive_median": float(summary["median_return"]),
                "var_5": float(summary["var_5"]),
                "es_5": float(summary["es_5"]),
                "var_1": float(summary["var_1"]),
                "es_1": float(summary["es_1"]),
                "var_5_exception": bool(realized_return < float(summary["var_5"])),
                "var_1_exception": bool(realized_return < float(summary["var_1"])),
                "pit": pit,
                "crps": crps,
                "log_score": log_score,
                "interval_score_90": interval_score,
                "inside_90": bool(qmap["q_05"] <= realized_return <= qmap["q_95"]),
                "inside_50": bool(qmap["q_25"] <= realized_return <= qmap["q_75"]),
                "prob_positive": float(summary["prob_positive"]),
                "positive_brier": float((positive_probability - positive_outcome) ** 2),
                "prob_target_before_stop": float(summary["prob_target_before_stop"]),
                "prob_stop_before_target": float(summary["prob_stop_before_target"]),
                "prob_ambiguous": float(summary["prob_same_day_ambiguous"]),
                "prob_neither": float(summary["prob_neither"]),
                "actual_barrier_outcome": actual_barrier["outcome"],
                "actual_target_day": actual_barrier["target_day"],
                "actual_stop_day": actual_barrier["stop_day"],
                "barrier_multiclass_brier": _multiclass_brier(class_probabilities, outcome_index),
                "eligibility_status": item.get("status", "INELIGIBLE"),
                "eligible_at_origin": bool(item.get("eligible_for_aggregation", False)),
                "eligibility_reasons": "; ".join(item.get("reasons", [])),
                "fallback_used": bool(metadata.get("fallback_used", False)),
                "calibration_status": metadata.get("calibration_status", "NOT_REQUIRED"),
                "conditional_refit_age": int(origin_position - cache_origin_position) if needs_conditional else 0,
                "effective_monitoring": monitoring["effective"],
            }
            row.update(qmap)
            forecast_rows.append(row)
            completed += 1
            if progress_callback:
                progress_callback(
                    completed,
                    total_jobs,
                    f"{model} · origin {origin_position + 1}/{len(origins)}",
                )

    forecasts = pd.DataFrame(forecast_rows)
    if forecasts.empty:
        return {"ok": False, "reason": "No walk-forward forecast could be produced."}

    leaderboard = _aggregate_model_forecasts(forecasts)
    quantile_calibration = _quantile_calibration(forecasts)
    pit_histogram = _pit_histogram(forecasts)
    reliability = _reliability_table(forecasts)
    recommended = None
    research_leader = None
    if not leaderboard.empty:
        research_candidates = leaderboard[
            (~leaderboard["Validation status"].isin(["REJECTED", "INSUFFICIENT"]))
            & (leaderboard["Eligible-origin share"] >= 0.50)
            & (leaderboard["Fallback rate"] <= 0.20)
        ]
        if not research_candidates.empty:
            research_leader = str(research_candidates.iloc[0]["Model"])
        validated_candidates = research_candidates[
            research_candidates["Validation status"] == "VALIDATED"
        ]
        if not validated_candidates.empty and int(len(origins)) >= 20:
            recommended = str(validated_candidates.iloc[0]["Model"])

    signature = _walk_forward_signature(ticker, settings, canonical_models, len(frame))
    warnings = _validation_warnings(settings, canonical_models, len(origins), len(frame))
    return {
        "ok": True,
        "ticker": ticker,
        "validation_version": "WALK-FORWARD-2.2.2",
        "configuration_signature": signature,
        "settings": asdict(settings),
        "models": canonical_models,
        "history_rows": int(len(frame)),
        "history_start": pd.Timestamp(frame["date"].iloc[0]),
        "history_end": pd.Timestamp(frame["date"].iloc[-1]),
        "forecast_origins": int(len(origins)),
        "origin_indexes": origins,
        "forecasts": forecasts,
        "leaderboard": leaderboard,
        "quantile_calibration": quantile_calibration,
        "pit_histogram": pit_histogram,
        "reliability": reliability,
        "recommended_model": recommended,
        "research_leader": research_leader,
        "ensemble_ready": bool(recommended is not None and int(len(origins)) >= 20),
        "warnings": warnings,
        "quality": quality,
        "methodology": {
            "leakage_control": "Each forecast origin uses only prices dated on or before the origin.",
            "distribution_scores": "Empirical CRPS, Gaussian-kernel log score, 90% interval score, PIT diagnostics.",
            "tail_validation": "Kupiec and Christoffersen tests for VaR 5%/1%; ES exceedance residual severity diagnostic.",
            "barrier_validation": "Realized high/low first passage versus simulated target/stop/ambiguous/neither probabilities.",
            "ranking": "Average metric rank plus transparent governance status penalty; not an alpha score.",
            "recommendation_gate": "A validated recommendation requires status VALIDATED and at least 20 non-overlapping forecast origins.",
            "conditional_refit": f"Every {settings.conditional_refit_every} selected origin(s).",
        },
    }
