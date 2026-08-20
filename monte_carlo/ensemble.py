from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict
from typing import Any, Dict, Mapping, Sequence

import numpy as np
import pandas as pd

from .config import DEFAULT_CONFIDENCE, DEFAULT_HORIZONS, MODELS, ScenarioParameters
from .models.dispatcher import simulate_paths_max_horizon
from .risk_metrics import _summarize_paths
from .utils import _jsonable


ENSEMBLE_WEIGHTING_METHODS = (
    "Equal validated",
    "Inverse CRPS",
    "Softmax CRPS",
    "Governed composite",
)


def _ensemble_signature(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(_jsonable(dict(payload)), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16].upper()


def _capped_normalize(scores: np.ndarray, max_weight: float) -> np.ndarray:
    scores = np.asarray(scores, dtype=float)
    scores = np.where(np.isfinite(scores) & (scores > 0.0), scores, 0.0)
    n = scores.size
    if n == 0:
        return scores
    if float(np.sum(scores)) <= 0.0:
        scores = np.ones(n, dtype=float)

    cap = min(1.0, max(float(max_weight), 1.0 / n))
    weights = scores / float(np.sum(scores))
    fixed = np.zeros(n, dtype=bool)

    for _ in range(n + 2):
        over = (~fixed) & (weights > cap + 1e-12)
        if not np.any(over):
            break
        weights[over] = cap
        fixed[over] = True
        remaining = 1.0 - float(np.sum(weights[fixed]))
        free = ~fixed
        if not np.any(free) or remaining <= 0.0:
            break
        free_scores = scores[free]
        if float(np.sum(free_scores)) <= 0.0:
            weights[free] = remaining / int(np.sum(free))
        else:
            weights[free] = remaining * free_scores / float(np.sum(free_scores))

    total = float(np.sum(weights))
    if total <= 0.0:
        return np.full(n, 1.0 / n)
    return weights / total


def _error_correlation_penalties(
    forecasts: pd.DataFrame,
    models: Sequence[str],
    strength: float,
) -> Dict[str, float]:
    strength = max(0.0, float(strength))
    if strength <= 0.0 or forecasts.empty or len(models) < 2:
        return {model: 1.0 for model in models}
    subset = forecasts[forecasts["model"].isin(models)].copy()
    subset["forecast_error"] = subset["realized_return"] - subset["predictive_mean"]
    pivot = subset.pivot_table(index="origin_date", columns="model", values="forecast_error", aggfunc="mean")
    correlation = pivot.corr(min_periods=5).abs()
    output: Dict[str, float] = {}
    for model in models:
        if model not in correlation.index:
            output[model] = 1.0
            continue
        peers = correlation.loc[model].drop(labels=[model], errors="ignore").dropna()
        average = float(peers.mean()) if not peers.empty else 0.0
        output[model] = 1.0 / (1.0 + strength * average)
    return output


def _raw_weight_scores(
    leaderboard: pd.DataFrame,
    method: str,
    correlation_penalties: Mapping[str, float],
    temperature: float,
) -> np.ndarray:
    method = method if method in ENSEMBLE_WEIGHTING_METHODS else "Inverse CRPS"
    crps = pd.to_numeric(leaderboard["Mean CRPS"], errors="coerce").to_numpy(dtype=float)
    finite = crps[np.isfinite(crps) & (crps > 0.0)]
    fallback_value = float(np.median(finite)) if finite.size else 1.0
    crps = np.where(np.isfinite(crps) & (crps > 0.0), crps, fallback_value)

    if method == "Equal validated":
        scores = np.ones(len(leaderboard), dtype=float)
    elif method == "Inverse CRPS":
        scores = 1.0 / np.maximum(crps, 1e-12)
    elif method == "Softmax CRPS":
        scale = float(np.std(crps, ddof=1)) if len(crps) > 1 else float(np.mean(crps))
        scale = max(scale, float(np.mean(crps)) * 0.05, 1e-6)
        tau = max(float(temperature), 0.05)
        scores = np.exp(-(crps - float(np.min(crps))) / (scale * tau))
    else:
        coverage = pd.to_numeric(leaderboard.get("Coverage penalty", 0.0), errors="coerce").fillna(1.0).to_numpy(dtype=float)
        fallback = pd.to_numeric(leaderboard.get("Fallback rate", 0.0), errors="coerce").fillna(1.0).to_numpy(dtype=float)
        eligible = pd.to_numeric(leaderboard.get("Eligible-origin share", 0.0), errors="coerce").fillna(0.0).to_numpy(dtype=float)
        rank = pd.to_numeric(leaderboard.get("Governed rank score", 1.0), errors="coerce").fillna(10.0).to_numpy(dtype=float)
        scores = (
            (1.0 / np.maximum(crps, 1e-12))
            * np.exp(-2.0 * np.maximum(coverage, 0.0))
            * np.maximum(1.0 - fallback, 0.05)
            * np.maximum(eligible, 0.05)
            / np.maximum(rank, 0.25)
        )

    diversity = np.array([float(correlation_penalties.get(str(model), 1.0)) for model in leaderboard["Model"]], dtype=float)
    return scores * np.maximum(diversity, 1e-6)


def _bootstrap_weight_intervals(
    forecasts: pd.DataFrame,
    candidates: pd.DataFrame,
    method: str,
    max_weight: float,
    temperature: float,
    correlation_penalty: float,
    repetitions: int,
    seed: int,
) -> Dict[str, tuple[float, float, float]]:
    models = candidates["Model"].astype(str).tolist()
    if repetitions <= 0 or forecasts.empty or len(models) == 0:
        return {model: (float("nan"), float("nan"), float("nan")) for model in models}
    dates = pd.Index(forecasts.loc[forecasts["model"].isin(models), "origin_date"].dropna().unique())
    if len(dates) < 4:
        return {model: (float("nan"), float("nan"), float("nan")) for model in models}

    rng = np.random.default_rng(int(seed))
    draws = np.zeros((int(repetitions), len(models)), dtype=float)
    indexed = {date: forecasts[forecasts["origin_date"] == date] for date in dates}

    for rep in range(int(repetitions)):
        sampled_dates = rng.choice(dates.to_numpy(), size=len(dates), replace=True)
        sampled = pd.concat([indexed[date] for date in sampled_dates], ignore_index=True)
        mean_crps = sampled.groupby("model", sort=False)["crps"].mean()
        boot = candidates.copy()
        boot["Mean CRPS"] = boot["Model"].map(mean_crps).fillna(boot["Mean CRPS"])
        penalties = _error_correlation_penalties(sampled, models, correlation_penalty)
        scores = _raw_weight_scores(boot, method, penalties, temperature)
        draws[rep] = _capped_normalize(scores, max_weight)

    output: Dict[str, tuple[float, float, float]] = {}
    for idx, model in enumerate(models):
        output[model] = (
            float(np.quantile(draws[:, idx], 0.05)),
            float(np.median(draws[:, idx])),
            float(np.quantile(draws[:, idx], 0.95)),
        )
    return output


def derive_ensemble_weights(
    validation_result: Mapping[str, Any],
    method: str = "Inverse CRPS",
    max_weight: float = 0.40,
    minimum_models: int = 2,
    minimum_forecasts: int = 20,
    include_warning: bool = False,
    temperature: float = 1.0,
    correlation_penalty: float = 0.50,
    bootstrap_repetitions: int = 200,
    seed: int = 42,
) -> Dict[str, Any]:
    leaderboard = validation_result.get("leaderboard")
    forecasts = validation_result.get("forecasts")
    if not isinstance(leaderboard, pd.DataFrame) or leaderboard.empty:
        return {"ok": False, "status": "BLOCKED", "reasons": ["No walk-forward leaderboard is available."]}
    if not isinstance(forecasts, pd.DataFrame) or forecasts.empty:
        return {"ok": False, "status": "BLOCKED", "reasons": ["No forecast-level validation history is available."]}

    allowed = {"VALIDATED"}
    if include_warning:
        allowed.add("WARNING")
    candidates = leaderboard[
        leaderboard["Validation status"].isin(allowed)
        & (pd.to_numeric(leaderboard["Forecasts"], errors="coerce") >= int(minimum_forecasts))
        & (pd.to_numeric(leaderboard["Eligible-origin share"], errors="coerce") >= 0.50)
        & (pd.to_numeric(leaderboard["Fallback rate"], errors="coerce") <= 0.20)
    ].copy()

    reasons: list[str] = []
    validated_count = int((leaderboard["Validation status"] == "VALIDATED").sum())
    if int(validation_result.get("forecast_origins", 0)) < int(minimum_forecasts):
        reasons.append(
            f"Validation power is insufficient: {int(validation_result.get('forecast_origins', 0))} origins < required {int(minimum_forecasts)}."
        )
    if len(candidates) < int(minimum_models):
        tier = "VALIDATED/WARNING" if include_warning else "VALIDATED"
        reasons.append(f"Only {len(candidates)} {tier} model(s) satisfy the ensemble gate; minimum is {int(minimum_models)}.")
    if reasons:
        return {
            "ok": False,
            "status": "BLOCKED",
            "reasons": reasons,
            "candidate_table": candidates,
            "validated_models": validated_count,
            "minimum_forecasts": int(minimum_forecasts),
            "minimum_models": int(minimum_models),
        }

    candidates = candidates.sort_values(["Validation rank", "Mean CRPS"], ascending=[True, True]).reset_index(drop=True)
    models = candidates["Model"].astype(str).tolist()
    penalties = _error_correlation_penalties(forecasts, models, correlation_penalty)
    scores = _raw_weight_scores(candidates, method, penalties, temperature)
    weights = _capped_normalize(scores, max_weight)
    intervals = _bootstrap_weight_intervals(
        forecasts=forecasts,
        candidates=candidates,
        method=method,
        max_weight=max_weight,
        temperature=temperature,
        correlation_penalty=correlation_penalty,
        repetitions=int(bootstrap_repetitions),
        seed=int(seed),
    )

    table = candidates[
        [
            column
            for column in (
                "Model",
                "Validation status",
                "Forecasts",
                "Validation rank",
                "Mean CRPS",
                "Mean log score",
                "Coverage penalty",
                "Barrier multiclass Brier",
                "Fallback rate",
                "Eligible-origin share",
            )
            if column in candidates.columns
        ]
    ].copy()
    table["Diversity multiplier"] = table["Model"].map(penalties).astype(float)
    table["Raw score"] = scores
    table["Weight"] = weights
    table["Weight CI low"] = table["Model"].map(lambda model: intervals[str(model)][0])
    table["Weight bootstrap median"] = table["Model"].map(lambda model: intervals[str(model)][1])
    table["Weight CI high"] = table["Model"].map(lambda model: intervals[str(model)][2])
    table = table.sort_values("Weight", ascending=False).reset_index(drop=True)

    status = "RESEARCH_ONLY" if include_warning and any(table["Validation status"] != "VALIDATED") else "ACTIVE"
    effective_n = float(1.0 / np.sum(np.square(weights)))
    entropy = float(-np.sum(weights * np.log(np.maximum(weights, 1e-12))) / math.log(len(weights))) if len(weights) > 1 else 0.0
    return {
        "ok": True,
        "status": status,
        "reasons": [],
        "method": method,
        "weights": {str(model): float(weight) for model, weight in zip(candidates["Model"], weights)},
        "weight_table": table,
        "effective_model_count": effective_n,
        "normalized_entropy": entropy,
        "maximum_weight": float(np.max(weights)),
        "validated_models": validated_count,
        "candidate_models": len(table),
        "minimum_forecasts": int(minimum_forecasts),
        "minimum_models": int(minimum_models),
        "include_warning": bool(include_warning),
        "bootstrap_repetitions": int(bootstrap_repetitions),
    }


def _allocate_paths(weights: Mapping[str, float], simulations: int) -> Dict[str, int]:
    models = list(weights)
    total = max(int(simulations), 100 * max(len(models), 1))
    raw = np.array([float(weights[model]) for model in models]) * total
    counts = np.floor(raw).astype(int)
    counts = np.maximum(counts, 1)
    difference = total - int(np.sum(counts))
    fractions = raw - np.floor(raw)
    if difference > 0:
        for idx in np.argsort(-fractions)[:difference]:
            counts[idx] += 1
    elif difference < 0:
        for idx in np.argsort(fractions):
            if difference == 0:
                break
            reducible = min(counts[idx] - 1, -difference)
            counts[idx] -= reducible
            difference += reducible
    return {model: int(count) for model, count in zip(models, counts)}


def build_validated_ensemble(
    lab: Mapping[str, Any],
    validation_result: Mapping[str, Any],
    method: str = "Inverse CRPS",
    simulations: int = 5_000,
    max_weight: float = 0.40,
    minimum_models: int = 2,
    minimum_forecasts: int = 20,
    include_warning: bool = False,
    temperature: float = 1.0,
    correlation_penalty: float = 0.50,
    bootstrap_repetitions: int = 200,
    seed: int = 42,
    confidence_level: float = DEFAULT_CONFIDENCE,
) -> Dict[str, Any]:
    weight_result = derive_ensemble_weights(
        validation_result=validation_result,
        method=method,
        max_weight=max_weight,
        minimum_models=minimum_models,
        minimum_forecasts=minimum_forecasts,
        include_warning=include_warning,
        temperature=temperature,
        correlation_penalty=correlation_penalty,
        bootstrap_repetitions=bootstrap_repetitions,
        seed=seed,
    )
    if not weight_result.get("ok"):
        return {
            "ok": False,
            "status": "BLOCKED",
            "reasons": list(weight_result.get("reasons", [])),
            "weight_result": weight_result,
        }

    weights = dict(weight_result["weights"])
    counts = _allocate_paths(weights, int(simulations))
    base = lab["base"]
    levels_object = lab["levels_object"]
    scenario = str(lab["settings"]["scenario"])
    mean_block_length = int(lab["settings"].get("mean_block_length", 10))
    ewma_lambda = float(lab["settings"].get("ewma_lambda", 0.94))
    ruin_threshold = float(lab["settings"].get("ruin_threshold", -0.30))

    member_paths: list[np.ndarray] = []
    member_rows: list[dict[str, Any]] = []
    params_rows: list[tuple[float, float, float, float, float]] = []
    for model, weight in weights.items():
        paths, params, metadata = simulate_paths_max_horizon(
            base=base,
            scenario=scenario,
            model=model,
            simulations=counts[model],
            seed=int(seed),
            max_horizon=max(DEFAULT_HORIZONS),
            mean_block_length=mean_block_length,
            ewma_lambda=ewma_lambda,
        )
        member_paths.append(paths)
        params_rows.append((weight, params.drift_ann, params.vol_ann, params.drift_multiplier, params.volatility_multiplier))
        for horizon in DEFAULT_HORIZONS:
            member_summary = _summarize_paths(
                paths=paths,
                levels=levels_object,
                params=params,
                model_metadata={
                    **dict(metadata),
                    "eligibility_status": "ELIGIBLE",
                    "eligible_for_aggregation": True,
                    "research_only": weight_result["status"] != "ACTIVE",
                    "barrier_monitoring_requested": "Clôture de chaque pas",
                    "barrier_monitoring_effective": "Clôture de chaque pas",
                    "barrier_monitoring_forced": True,
                    "barrier_monitoring_warning": "Validated ensembles use a common discrete monitoring convention across heterogeneous engines.",
                },
                horizon=horizon,
                scenario=scenario,
                model=model,
                monitoring="Clôture de chaque pas",
                seed=int(seed),
                confidence=float(confidence_level),
                ruin_threshold=ruin_threshold,
                include_diagnostics=False,
            )
            member_rows.append(
                {
                    "Model": model,
                    "Weight": float(weight),
                    "Paths": int(counts[model]),
                    "Horizon": int(horizon),
                    "Expected return": float(member_summary["expected_return"]),
                    "Median return": float(member_summary["median_return"]),
                    "ES 5%": float(member_summary["es_5"]),
                    "VaR 5%": float(member_summary["var_5"]),
                    "Target before stop": float(member_summary["prob_target_before_stop"]),
                    "Stop before target": float(member_summary["prob_stop_before_target"]),
                    "Expected max drawdown": float(member_summary["expected_max_drawdown"]),
                }
            )

    combined_paths = np.concatenate(member_paths, axis=0)
    rng = np.random.default_rng(int(seed) + 991)
    combined_paths = combined_paths[rng.permutation(len(combined_paths))]
    param_array = np.asarray(params_rows, dtype=float)
    normalized = param_array[:, 0] / np.sum(param_array[:, 0])
    ensemble_params = ScenarioParameters(
        drift_ann=float(np.sum(normalized * param_array[:, 1])),
        vol_ann=float(np.sum(normalized * param_array[:, 2])),
        drift_multiplier=float(np.sum(normalized * param_array[:, 3])),
        volatility_multiplier=float(np.sum(normalized * param_array[:, 4])),
        note=f"Validated mixture under {method}; heterogeneous engines summarized with common discrete barrier monitoring.",
    )
    ensemble_metadata = {
        "model": "Validated model ensemble",
        "scenario": scenario,
        "supports_bridge": False,
        "calibration_status": "ENSEMBLE",
        "calibration_converged": True,
        "calibration_warning": "",
        "fallback_used": False,
        "eligibility_status": "ELIGIBLE" if weight_result["status"] == "ACTIVE" else "WARNING",
        "eligibility_reasons": [] if weight_result["status"] == "ACTIVE" else ["Warning-tier models included under research override."],
        "eligible_for_aggregation": weight_result["status"] == "ACTIVE",
        "research_only": weight_result["status"] != "ACTIVE",
        "barrier_monitoring_requested": "Clôture de chaque pas",
        "barrier_monitoring_effective": "Clôture de chaque pas",
        "barrier_monitoring_forced": True,
        "barrier_monitoring_warning": "Continuous bridge monitoring is not common across heterogeneous ensemble members.",
    }

    paths_by_horizon: Dict[int, np.ndarray] = {}
    summaries_by_horizon: Dict[int, Dict[str, Any]] = {}
    for horizon in DEFAULT_HORIZONS:
        paths_by_horizon[horizon] = combined_paths[:, : horizon + 1]
        summaries_by_horizon[horizon] = _summarize_paths(
            paths=combined_paths,
            levels=levels_object,
            params=ensemble_params,
            model_metadata=ensemble_metadata,
            horizon=horizon,
            scenario=scenario,
            model="Validated model ensemble",
            monitoring="Clôture de chaque pas",
            seed=int(seed),
            confidence=float(confidence_level),
            ruin_threshold=ruin_threshold,
            include_diagnostics=True,
        )

    members = pd.DataFrame(member_rows)
    disagreement_rows: list[dict[str, Any]] = []
    for horizon, group in members.groupby("Horizon"):
        w = group["Weight"].to_numpy(dtype=float)
        w = w / np.sum(w)
        row = {"Horizon": int(horizon)}
        for column in ("Expected return", "ES 5%", "Target before stop", "Expected max drawdown"):
            x = group[column].to_numpy(dtype=float)
            mean = float(np.sum(w * x))
            row[f"{column} weighted mean"] = mean
            row[f"{column} dispersion"] = float(np.sqrt(np.sum(w * np.square(x - mean))))
        disagreement_rows.append(row)
    disagreement = pd.DataFrame(disagreement_rows)

    payload = {
        "validation_signature": validation_result.get("configuration_signature"),
        "engine_signature": lab.get("configuration_signature"),
        "method": method,
        "weights": weights,
        "simulations": int(len(combined_paths)),
        "seed": int(seed),
        "status": weight_result["status"],
    }
    return {
        "ok": True,
        "status": weight_result["status"],
        "ensemble_version": "VALIDATED-ENSEMBLE-2.2.2",
        "configuration_signature": _ensemble_signature(payload),
        "validation_signature": validation_result.get("configuration_signature"),
        "engine_signature": lab.get("configuration_signature"),
        "method": method,
        "weights": weights,
        "weight_table": weight_result["weight_table"],
        "weight_governance": weight_result,
        "path_allocation": counts,
        "paths_by_horizon": paths_by_horizon,
        "summaries_by_horizon": summaries_by_horizon,
        "member_summaries": members,
        "disagreement": disagreement,
        "base": base,
        "levels": lab["levels"],
        "levels_object": levels_object,
        "settings": {
            "simulations": int(len(combined_paths)),
            "scenario": scenario,
            "seed": int(seed),
            "method": method,
            "max_weight": float(max_weight),
            "minimum_models": int(minimum_models),
            "minimum_forecasts": int(minimum_forecasts),
            "include_warning": bool(include_warning),
            "bootstrap_repetitions": int(bootstrap_repetitions),
        },
        "assumptions": {
            "weight_source": "Leakage-safe walk-forward validation metrics.",
            "weight_cap": float(max_weight),
            "diversification": "Forecast-error correlation penalty plus maximum member weight.",
            "uncertainty": "Origin bootstrap confidence intervals for member weights.",
            "barrier_monitoring": "Common discrete close monitoring across heterogeneous engines.",
            "governance": "ACTIVE requires sufficient VALIDATED members; WARNING inclusion is explicitly RESEARCH_ONLY.",
        },
    }
