from __future__ import annotations

import math
from typing import Any, Dict, Mapping

import numpy as np
import pandas as pd

from .barriers import _barrier_events
from .config import BarrierLevels, ScenarioParameters, EPS, DEFAULT_CONFIDENCE, MODEL_ALIASES
from .utils import _moment_excess_kurtosis, _moment_skew, _normal_ppf, _wilson_interval

def _expected_shortfall(values: np.ndarray, alpha: float) -> Tuple[float, float, int, Tuple[float, float]]:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return float("nan"), float("nan"), 0, (float("nan"), float("nan"))

    var = float(np.quantile(values, alpha))
    tail = values[values <= var]
    if tail.size == 0:
        tail = np.array([var])
    es = float(np.mean(tail))
    tail_se = float(np.std(tail, ddof=1) / math.sqrt(tail.size)) if tail.size > 1 else 0.0
    z = _normal_ppf(0.975)
    interval = (es - z * tail_se, es + z * tail_se)
    return var, es, int(tail.size), interval


def _path_drawdown_metrics(paths: np.ndarray) -> Dict[str, float]:
    running_max = np.maximum.accumulate(paths, axis=1)
    drawdowns = paths / np.maximum(running_max, EPS) - 1.0
    max_drawdowns = drawdowns.min(axis=1)
    return {
        "expected_max_drawdown": float(np.mean(max_drawdowns)),
        "median_max_drawdown": float(np.median(max_drawdowns)),
        "max_drawdown_p95_loss": float(np.quantile(max_drawdowns, 0.05)),
        "prob_drawdown_gt_10": float(np.mean(max_drawdowns <= -0.10) * 100.0),
        "prob_drawdown_gt_20": float(np.mean(max_drawdowns <= -0.20) * 100.0),
    }


def _build_convergence_table(
    final_returns: np.ndarray,
    barrier_events: Mapping[str, Any],
    confidence: float,
) -> pd.DataFrame:
    n_total = len(final_returns)
    candidate_sizes = (250, 500, 1_000, 2_000, 3_000, 5_000, 10_000, 25_000, 50_000)
    sizes = [n for n in candidate_sizes if n <= n_total]
    if n_total not in sizes:
        sizes.append(n_total)
    sizes = sorted(set(sizes))

    target_mask = np.asarray(barrier_events["target_before_stop_mask"], dtype=bool)
    rows: List[Dict[str, Any]] = []

    for n in sizes:
        sample = final_returns[:n]
        var5, es5, tail_count, es_ci = _expected_shortfall(sample, 0.05)
        target_count = int(target_mask[:n].sum())
        target_prob = target_count / n
        target_ci = _wilson_interval(target_count, n, confidence)
        rows.append(
            {
                "Simulations": n,
                "Expected return": float(np.mean(sample)),
                "Expected return MCSE": float(np.std(sample, ddof=1) / math.sqrt(n)) if n > 1 else float("nan"),
                "VaR 5%": var5,
                "ES 5%": es5,
                "ES 5% CI low": es_ci[0],
                "ES 5% CI high": es_ci[1],
                "Tail observations": tail_count,
                "Target before stop": target_prob * 100.0,
                "Target CI low": target_ci[0] * 100.0,
                "Target CI high": target_ci[1] * 100.0,
            }
        )
    return pd.DataFrame(rows)


def _summarize_paths(
    paths: np.ndarray,
    levels: BarrierLevels,
    params: ScenarioParameters,
    model_metadata: Mapping[str, Any],
    horizon: int,
    scenario: str,
    model: str,
    monitoring: str,
    seed: int,
    confidence: float = DEFAULT_CONFIDENCE,
    ruin_threshold: float = -0.30,
    include_diagnostics: bool = False,
) -> Dict[str, Any]:
    horizon_paths = paths[:, : horizon + 1]
    current = float(levels.current)
    final_prices = horizon_paths[:, -1]
    final_returns = final_prices / current - 1.0
    n = final_returns.size

    quantile_levels = (1, 2.5, 5, 10, 25, 50, 75, 90, 95, 97.5, 99)
    price_quantiles = np.percentile(final_prices, quantile_levels)
    return_quantiles = np.percentile(final_returns, quantile_levels)

    var5, es5, es5_count, es5_ci = _expected_shortfall(final_returns, 0.05)
    var1, es1, es1_count, es1_ci = _expected_shortfall(final_returns, 0.01)

    mean_return = float(np.mean(final_returns))
    mean_mcse = float(np.std(final_returns, ddof=1) / math.sqrt(n)) if n > 1 else float("nan")
    z = _normal_ppf(0.5 + confidence / 2.0)
    mean_ci = (mean_return - z * mean_mcse, mean_return + z * mean_mcse)

    positive_count = int(np.sum(final_returns > 0.0))
    positive_ci = _wilson_interval(positive_count, n, confidence)

    barrier = _barrier_events(
        paths=horizon_paths,
        levels=levels,
        model_metadata=model_metadata,
        monitoring=monitoring,
        seed=seed + horizon,
    )

    drawdown = _path_drawdown_metrics(horizon_paths)

    summary: Dict[str, Any] = {
        "horizon": int(horizon),
        "scenario": scenario,
        "model": MODEL_ALIASES.get(model, model),
        "drift_used": float(params.drift_ann),
        "vol_used": float(params.vol_ann),
        "drift_multiplier": float(params.drift_multiplier),
        "volatility_multiplier": float(params.volatility_multiplier),
        "p1": float(price_quantiles[0]),
        "p2_5": float(price_quantiles[1]),
        "p5": float(price_quantiles[2]),
        "p10": float(price_quantiles[3]),
        "p25": float(price_quantiles[4]),
        "p50": float(price_quantiles[5]),
        "p75": float(price_quantiles[6]),
        "p90": float(price_quantiles[7]),
        "p95": float(price_quantiles[8]),
        "p97_5": float(price_quantiles[9]),
        "p99": float(price_quantiles[10]),
        "return_p1": float(return_quantiles[0]),
        "return_p5": float(return_quantiles[2]),
        "return_p50": float(return_quantiles[5]),
        "return_p95": float(return_quantiles[8]),
        "return_p99": float(return_quantiles[10]),
        "expected_return": mean_return,
        "expected_return_mcse": mean_mcse,
        "expected_return_ci": mean_ci,
        "median_return": float(np.median(final_returns)),
        "prob_positive": positive_count / n * 100.0,
        "prob_positive_ci": (positive_ci[0] * 100.0, positive_ci[1] * 100.0),
        "prob_loss_gt_5": float(np.mean(final_returns < -0.05) * 100.0),
        "prob_loss_gt_10": float(np.mean(final_returns < -0.10) * 100.0),
        "prob_ruin": float(np.mean(final_returns <= ruin_threshold) * 100.0),
        "var_5": var5,
        "es_5": es5,
        "es_5_tail_count": es5_count,
        "es_5_ci": es5_ci,
        "var_1": var1,
        "es_1": es1,
        "es_1_tail_count": es1_count,
        "es_1_ci": es1_ci,
        "skewness": _moment_skew(final_returns),
        "excess_kurtosis": _moment_excess_kurtosis(final_returns),
        "simulations": int(n),
        "effective_monitoring": barrier["effective_monitoring"],
        "bridge_requested_but_unavailable": barrier["bridge_requested_but_unavailable"],
        "calibration_model": model_metadata.get("calibration_model"),
        "calibration_status": model_metadata.get("calibration_status", "NOT_REQUIRED"),
        "calibration_converged": bool(model_metadata.get("calibration_converged", True)),
        "calibration_warning": model_metadata.get("calibration_warning", ""),
        "fallback_used": bool(model_metadata.get("fallback_used", False)),
        "persistence": model_metadata.get("persistence"),
        "initial_conditional_vol_ann": model_metadata.get("initial_conditional_vol_ann"),
        "long_run_vol_ann": model_metadata.get("long_run_vol_ann"),
        "conditional_distribution": model_metadata.get("conditional_distribution"),
        "eligibility_status": model_metadata.get("eligibility_status", "INELIGIBLE"),
        "eligibility_reasons": list(model_metadata.get("eligibility_reasons", [])),
        "eligible_for_aggregation": bool(model_metadata.get("eligible_for_aggregation", False)),
        "research_only": bool(model_metadata.get("research_only", True)),
        "barrier_monitoring_requested": model_metadata.get("barrier_monitoring_requested", monitoring),
        "barrier_monitoring_effective": model_metadata.get("barrier_monitoring_effective", monitoring),
        "barrier_monitoring_forced": bool(model_metadata.get("barrier_monitoring_forced", False)),
        "barrier_monitoring_warning": model_metadata.get("barrier_monitoring_warning", ""),
    }
    summary.update(drawdown)

    for key, value in barrier.items():
        if not key.endswith("_mask") and key not in {"stop_first_day", "target_first_day"}:
            summary[key] = value

    if include_diagnostics:
        summary["convergence"] = _build_convergence_table(final_returns, barrier, confidence)
        summary["final_returns"] = final_returns
        summary["final_prices"] = final_prices
        summary["stop_first_day_array"] = barrier["stop_first_day"]
        summary["target_first_day_array"] = barrier["target_first_day"]

    return summary
