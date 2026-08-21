"""Advanced, deterministic research models for the institutional Risk Monitor.

The functions in this module are deliberately UI-agnostic.  They reuse the
calibrated Monte Carlo stack already shipped with the terminal and expose
explicit eligibility gates so a failed challenger can never silently replace a
validated benchmark.
"""

from __future__ import annotations

from math import sqrt
from typing import Any, Mapping

import numpy as np
import pandas as pd

from backtest_institutional.scenarios import ScenarioConfig, run_institutional_scenario_suite
from monte_carlo.calibration import fit_conditional_volatility
from monte_carlo.models.garch import conditional_volatility_log_steps


EPS = 1e-12
TRADING_DAYS = 252


def _finite(values: pd.Series | np.ndarray) -> pd.Series:
    series = pd.to_numeric(pd.Series(values, copy=False), errors="coerce")
    return series.replace([np.inf, -np.inf], np.nan).dropna().astype(float)


def _tail_pair(values: np.ndarray, confidence: float) -> tuple[float | None, float | None, int]:
    clean = np.asarray(values, dtype=float)
    clean = clean[np.isfinite(clean)]
    if clean.size < 100:
        return None, None, 0
    alpha = 1.0 - float(confidence)
    value_at_risk = float(np.quantile(clean, alpha))
    tail = clean[clean <= value_at_risk]
    return value_at_risk, float(np.mean(tail)) if tail.size else value_at_risk, int(tail.size)


def build_gjr_garch_tail(
    returns: pd.Series,
    *,
    horizon: int,
    confidence: float,
    seed: int,
    simulations: int = 8_000,
) -> dict[str, Any]:
    """Fit GJR-GARCH Student-t and run a residual-bootstrap tail forecast."""

    clean = _finite(returns)
    if len(clean) < 120:
        return {
            "ok": False,
            "status": "INELIGIBLE",
            "reason": f"{len(clean)} returns available; 120 required for GJR-GARCH Student-t.",
        }
    logs = np.log1p(np.clip(clean.to_numpy(dtype=float), -0.999999, None))
    fit = fit_conditional_volatility(
        logs,
        periods_per_year=TRADING_DAYS,
        model_name="GJR-GARCH Student-t",
        maxiter=500,
        min_observations=120,
    )
    if not fit.get("ok"):
        return {
            "ok": False,
            "status": str(fit.get("status", "FAILED")),
            "reason": str(fit.get("warning") or "GJR-GARCH calibration failed."),
            "fit": fit,
        }

    count = max(2_000, min(int(simulations), 30_000))
    rng = np.random.default_rng(int(seed) + 701)
    historical_vol = max(float(np.std(logs, ddof=1) * sqrt(TRADING_DAYS)), EPS)
    scenario_vol = max(float(fit.get("last_vol_ann", historical_vol)), EPS)
    try:
        log_steps, metadata = conditional_volatility_log_steps(
            rng=rng,
            fit=fit,
            simulations=count,
            horizon=max(1, int(horizon)),
            drift_ann=float(np.mean(logs) * TRADING_DAYS),
            scenario_vol_ann=scenario_vol,
            historical_vol_ann=historical_vol,
            periods_per_year=TRADING_DAYS,
            empirical_residuals=True,
        )
    except Exception as exc:
        return {
            "ok": False,
            "status": "SIMULATION_FAILED",
            "reason": f"Conditional residual bootstrap failed: {type(exc).__name__}.",
            "fit": fit,
        }

    terminal = np.expm1(np.sum(log_steps, axis=1))
    value_at_risk, expected_shortfall, tail_count = _tail_pair(terminal, confidence)
    parameters = fit.get("parameters", {})
    return {
        "ok": value_at_risk is not None and expected_shortfall is not None,
        "status": "CHALLENGER" if fit.get("status") in {"PASS", "WARNING"} else str(fit.get("status")),
        "reason": str(fit.get("warning") or "Conditional-volatility calibration is usable."),
        "var": value_at_risk,
        "es": expected_shortfall,
        "tail_observations": tail_count,
        "terminal_returns": terminal,
        "fit": fit,
        "metadata": metadata,
        "method": (
            f"GJR-GARCH(1,1), Student-t df={float(parameters.get('degrees_of_freedom') or 0):.1f}, "
            f"persistence={float(fit.get('persistence') or 0):.3f}; empirical residual bootstrap"
        ),
    }


def build_nonlinear_scenario_suite(
    returns: pd.Series,
    *,
    horizon: int,
    confidence: float,
    seed: int,
    paths: int = 4_000,
    factor_returns: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Run Markov, EVT, multivariate-t and liquidity-feedback challengers."""

    clean = _finite(returns)
    if len(clean) < 120:
        return {
            "ok": False,
            "status": "INELIGIBLE",
            "reason": f"{len(clean)} returns available; 120 required for nonlinear scenarios.",
            "summary": pd.DataFrame(),
            "regime_mix": {},
        }
    config = ScenarioConfig(
        horizon_days=max(1, int(horizon)),
        paths=max(1_000, min(int(paths), 20_000)),
        seed=int(seed) + 1_303,
        confidence=float(confidence),
    )
    try:
        suite = run_institutional_scenario_suite(clean, factor_returns=factor_returns, config=config)
    except Exception as exc:
        return {
            "ok": False,
            "status": "FAILED",
            "reason": f"Nonlinear scenario suite failed: {type(exc).__name__}.",
            "summary": pd.DataFrame(),
            "regime_mix": {},
        }

    model_rows: list[dict[str, Any]] = []
    for scenario, model_name, method in (
        (
            "Markov regime switching",
            "Markov regime Student-t proxy",
            "Three-state sticky Markov chain with calm, volatile and crisis emissions",
        ),
        (
            "EVT empirical tail",
            "EVT tail injection",
            "Empirical body with calibrated exponential loss-tail excess",
        ),
    ):
        daily_paths = np.asarray(suite.get("paths", {}).get(scenario, []), dtype=float)
        if daily_paths.ndim != 2 or daily_paths.size == 0:
            continue
        terminal = np.prod(1.0 + np.clip(daily_paths, -0.99, None), axis=1) - 1.0
        value_at_risk, expected_shortfall, tail_count = _tail_pair(terminal, confidence)
        model_rows.append(
            {
                "Model": model_name,
                "VaR": value_at_risk,
                "ES": expected_shortfall,
                "Tail observations": tail_count,
                "Status": "RESEARCH",
                "Method": method,
            }
        )

    summary = suite.get("summary", pd.DataFrame()).copy()
    if isinstance(summary, pd.DataFrame) and not summary.empty:
        summary = summary.reset_index().rename(columns={"scenario": "Scenario"})
    return {
        "ok": True,
        "status": "RESEARCH",
        "reason": "Nonlinear challengers are active and remain outside validated production limits.",
        "summary": summary,
        "model_rows": pd.DataFrame(model_rows),
        "regime_mix": dict(suite.get("regime_mix", {})),
        "reverse_stress": dict(suite.get("reverse_stress", {})),
        "evt": dict(suite.get("evt", {})),
        "factor_mode": "MULTIVARIATE" if factor_returns is not None and not factor_returns.empty else "SINGLE_ASSET_PROXY",
        "config": config,
    }


def bootstrap_tail_uncertainty(
    returns: pd.Series,
    *,
    horizon: int,
    confidence: float,
    seed: int,
    repetitions: int = 240,
    block_size: int = 10,
) -> dict[str, Any]:
    """Moving-block bootstrap confidence intervals for historical VaR and ES."""

    clean = _finite(returns).to_numpy(dtype=float)
    if clean.size < 120:
        return {
            "ok": False,
            "status": "INELIGIBLE",
            "reason": f"{clean.size} returns available; 120 required for bootstrap uncertainty.",
            "table": pd.DataFrame(),
        }
    horizon = max(1, int(horizon))
    block_size = max(2, min(int(block_size), max(2, clean.size // 4)))
    repetitions = max(80, min(int(repetitions), 1_000))
    rng = np.random.default_rng(int(seed) + 2_009)
    starts = np.arange(clean.size)
    rows: list[tuple[float, float]] = []

    for _ in range(repetitions):
        sampled: list[np.ndarray] = []
        length = 0
        while length < clean.size:
            start = int(rng.choice(starts))
            indexes = (start + np.arange(block_size)) % clean.size
            block = clean[indexes]
            sampled.append(block)
            length += len(block)
        series = np.concatenate(sampled)[: clean.size]
        horizon_values = (
            series
            if horizon == 1
            else np.asarray(
                [np.prod(1.0 + np.clip(series[index : index + horizon], -0.99, None)) - 1.0 for index in range(clean.size - horizon + 1)],
                dtype=float,
            )
        )
        value_at_risk, expected_shortfall, _ = _tail_pair(horizon_values, confidence)
        if value_at_risk is not None and expected_shortfall is not None:
            rows.append((value_at_risk, expected_shortfall))

    draws = pd.DataFrame(rows, columns=["VaR", "ES"])
    if len(draws) < max(40, repetitions // 2):
        return {
            "ok": False,
            "status": "UNSTABLE",
            "reason": f"Only {len(draws)} successful bootstrap draws.",
            "table": pd.DataFrame(),
        }

    interval_rows: list[dict[str, Any]] = []
    for metric in ("VaR", "ES"):
        series = draws[metric]
        low, median, high = (float(series.quantile(q)) for q in (0.025, 0.50, 0.975))
        interval_rows.append(
            {
                "Metric": metric,
                "CI low": low,
                "Median": median,
                "CI high": high,
                "CI width": high - low,
            }
        )
    table = pd.DataFrame(interval_rows)
    es_width = float(table.loc[table["Metric"] == "ES", "CI width"].iloc[0])
    status = "HIGH" if clean.size >= 750 and es_width <= 0.03 else "MEDIUM" if clean.size >= 250 and es_width <= 0.07 else "LOW"
    return {
        "ok": True,
        "status": status,
        "reason": f"{len(draws)} moving-block bootstrap draws; block length {block_size}.",
        "table": table,
        "draws": draws,
        "successful_draws": int(len(draws)),
        "block_size": block_size,
    }


def build_oos_weighted_benchmark(
    tail_models: pd.DataFrame,
    backtest_summary: pd.DataFrame,
) -> dict[str, Any]:
    """Weight production benchmarks using observed coverage and independence."""

    if tail_models.empty or backtest_summary.empty:
        return {"ok": False, "status": "BLOCKED", "weight_table": pd.DataFrame()}
    mapping = {
        "Historical VaR": "Historical simulation",
        "EWMA Gaussian VaR": "Gaussian parametric",
    }
    rows: list[dict[str, Any]] = []
    for _, validation in backtest_summary.iterrows():
        benchmark = mapping.get(str(validation.get("Model")))
        estimate = tail_models.loc[tail_models["Model"] == benchmark]
        if benchmark is None or estimate.empty:
            continue
        estimate_row = estimate.iloc[0]
        expected = float(validation.get("expected_rate") or 0.0)
        observed = float(validation.get("exception_rate") or 0.0)
        coverage_error = abs(observed - expected)
        conditional_p = float(validation.get("conditional_p_value") or 0.0)
        score = np.exp(-50.0 * coverage_error) * (0.25 + 0.75 * np.clip(conditional_p, 0.0, 1.0))
        if str(validation.get("status")) == "FAIL":
            score *= 0.05
        elif str(validation.get("status")) in {"WARNING", "LIMITED"}:
            score *= 0.50
        rows.append(
            {
                "Model": benchmark,
                "Validation status": validation.get("status"),
                "Forecasts": validation.get("observations"),
                "Exception rate": observed,
                "Expected rate": expected,
                "Conditional p-value": conditional_p,
                "Raw score": float(score),
                "VaR": float(estimate_row["VaR"]),
                "ES": float(estimate_row["ES"]),
            }
        )
    table = pd.DataFrame(rows)
    if len(table) < 2 or float(table["Raw score"].sum()) <= EPS:
        return {"ok": False, "status": "BLOCKED", "weight_table": table}
    table["Weight"] = table["Raw score"] / table["Raw score"].sum()
    value_at_risk = float(np.sum(table["Weight"] * table["VaR"]))
    expected_shortfall = float(np.sum(table["Weight"] * table["ES"]))
    status = "ACTIVE" if (table["Validation status"] == "PASS").all() else "RESEARCH_ONLY"
    return {
        "ok": True,
        "status": status,
        "method": "Coverage-error exponential score × conditional-coverage p-value",
        "var": value_at_risk,
        "es": min(expected_shortfall, value_at_risk),
        "weight_table": table.sort_values("Weight", ascending=False).reset_index(drop=True),
        "effective_models": float(1.0 / np.sum(np.square(table["Weight"]))),
    }


def factor_risk_decomposition(
    returns: pd.Series,
    factor_returns: pd.DataFrame | None,
) -> dict[str, Any]:
    """OLS factor decomposition with an explicit data contract when unavailable."""

    contract = pd.DataFrame(
        [
            {"Field": "date index", "Type": "datetime", "Required": "YES", "Meaning": "Synchronized observation time"},
            {"Field": "factor columns", "Type": "decimal returns", "Required": "YES", "Meaning": "Market, rates, FX, volatility or commodity factors"},
            {"Field": "minimum history", "Type": ">= 120 rows", "Required": "YES", "Meaning": "Aligned non-null observations"},
        ]
    )
    if factor_returns is None or not isinstance(factor_returns, pd.DataFrame) or factor_returns.empty:
        return {
            "ok": False,
            "status": "AWAITING_DATA",
            "reason": "Factor-return matrix is not attached to this instrument snapshot.",
            "contract": contract,
            "table": pd.DataFrame(),
        }
    y = _finite(returns).rename("asset")
    x = factor_returns.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    joined = pd.concat([y, x], axis=1, join="inner").dropna()
    if len(joined) < 120 or joined.shape[1] < 2:
        return {
            "ok": False,
            "status": "INSUFFICIENT_DATA",
            "reason": f"{len(joined)} aligned observations; at least 120 required.",
            "contract": contract,
            "table": pd.DataFrame(),
        }
    yv = joined.pop("asset").to_numpy(dtype=float)
    xv = joined.to_numpy(dtype=float)
    design = np.column_stack([np.ones(len(joined)), xv])
    coefficients, *_ = np.linalg.lstsq(design, yv, rcond=None)
    fitted = design @ coefficients
    residuals = yv - fitted
    total_variance = max(float(np.var(yv, ddof=1)), EPS)
    r_squared = float(np.clip(1.0 - np.var(residuals, ddof=1) / total_variance, 0.0, 1.0))
    factor_cov = np.cov(xv, rowvar=False)
    beta = coefficients[1:]
    factor_variance = np.asarray(beta).reshape(1, -1) @ np.atleast_2d(factor_cov) @ np.asarray(beta).reshape(-1, 1)
    factor_variance = float(factor_variance.item())
    rows = []
    for name, coefficient in zip(joined.columns, beta):
        rows.append(
            {
                "Factor": str(name),
                "Beta": float(coefficient),
                "Standalone contribution proxy": float(abs(coefficient) * joined[name].std(ddof=1)),
            }
        )
    return {
        "ok": True,
        "status": "ACTIVE",
        "reason": f"OLS factor model on {len(joined)} synchronized observations.",
        "contract": contract,
        "table": pd.DataFrame(rows).sort_values("Standalone contribution proxy", ascending=False),
        "r_squared": r_squared,
        "factor_volatility": sqrt(max(factor_variance, 0.0) * TRADING_DAYS),
        "idiosyncratic_volatility": float(np.std(residuals, ddof=1) * sqrt(TRADING_DAYS)),
        "observations": int(len(joined)),
    }


def build_advanced_research_snapshot(
    returns: pd.Series,
    *,
    horizon: int,
    confidence: float,
    seed: int,
    base_tail_models: pd.DataFrame,
    backtest_summary: pd.DataFrame,
    factor_returns: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Build all advanced challengers and their governance artefacts."""

    gjr = build_gjr_garch_tail(
        returns,
        horizon=horizon,
        confidence=confidence,
        seed=seed,
    )
    nonlinear = build_nonlinear_scenario_suite(
        returns,
        horizon=horizon,
        confidence=confidence,
        seed=seed,
        factor_returns=factor_returns,
    )
    uncertainty = bootstrap_tail_uncertainty(
        returns,
        horizon=horizon,
        confidence=confidence,
        seed=seed,
    )
    rows: list[dict[str, Any]] = []
    if gjr.get("ok"):
        rows.append(
            {
                "Model": "GJR-GARCH-t FHS",
                "VaR": gjr.get("var"),
                "ES": gjr.get("es"),
                "Tail observations": gjr.get("tail_observations", 0),
                "Status": gjr.get("status", "CHALLENGER"),
                "Method": gjr.get("method"),
            }
        )
    nonlinear_rows = nonlinear.get("model_rows", pd.DataFrame())
    if isinstance(nonlinear_rows, pd.DataFrame) and not nonlinear_rows.empty:
        rows.extend(nonlinear_rows.to_dict("records"))
    challengers = pd.DataFrame(rows)
    combined = pd.concat([base_tail_models, challengers], ignore_index=True) if not challengers.empty else base_tail_models.copy()
    benchmark = build_oos_weighted_benchmark(combined, backtest_summary)
    if benchmark.get("ok"):
        benchmark_row = pd.DataFrame(
            [
                {
                    "Model": "OOS weighted benchmark",
                    "VaR": benchmark.get("var"),
                    "ES": benchmark.get("es"),
                    "Tail observations": int(backtest_summary["exceptions"].sum()) if "exceptions" in backtest_summary else 0,
                    "Status": benchmark.get("status"),
                    "Method": benchmark.get("method"),
                }
            ]
        )
        combined = pd.concat([combined, benchmark_row], ignore_index=True)
    factors = factor_risk_decomposition(returns, factor_returns)
    catalog = pd.DataFrame(
        [
            {"Research block": "GJR-GARCH Student-t FHS", "State": gjr.get("status", "INELIGIBLE"), "Gate": "120+ returns and converged stationary fit", "Role": "Conditional-volatility challenger"},
            {"Research block": "Markov regime switching", "State": nonlinear.get("status", "INELIGIBLE"), "Gate": "120+ returns", "Role": "Nonlinear path challenger"},
            {"Research block": "EVT tail injection", "State": nonlinear.get("status", "INELIGIBLE"), "Gate": "120+ returns", "Role": "Crisis-tail challenger"},
            {"Research block": "Moving-block uncertainty", "State": uncertainty.get("status", "INELIGIBLE"), "Gate": "120+ returns", "Role": "Parameter uncertainty"},
            {"Research block": "OOS weighted benchmark", "State": benchmark.get("status", "BLOCKED"), "Gate": "2 validated benchmark histories", "Role": "Outcome-weighted benchmark"},
            {"Research block": "Multi-factor decomposition", "State": factors.get("status", "AWAITING_DATA"), "Gate": "120+ aligned factor returns", "Role": "Systematic / idiosyncratic split"},
        ]
    )
    return {
        "tail_models": combined,
        "challengers": challengers,
        "gjr": gjr,
        "nonlinear": nonlinear,
        "uncertainty": uncertainty,
        "benchmark": benchmark,
        "factors": factors,
        "catalog": catalog,
    }
