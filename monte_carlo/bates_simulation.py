from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.stats import kurtosis, norm, skew

from .bates_calibration import BatesParameters
from .heston_calibration import HestonParameters
from .heston_simulation import (
    HESTON_SIMULATION_SCHEMES,
    _carry_schedule,
    _fit_table_from_calibration,
    _normalize_scheme,
    _parameters_from_calibration,
    _qe_log_spot_increment,
    _qe_variance_transition,
    _random_drivers,
    _simulate_core as _simulate_heston_core,
)
from .options_risk_neutral import implied_volatility

BATES_SIMULATION_VERSION = "BATES-Q-SIMULATION-2.7.1C"
BATES_SIMULATION_SCHEMES = HESTON_SIMULATION_SCHEMES


@dataclass(frozen=True)
class BatesSimulationSettings:
    paths: int = 10_000
    steps_per_year: int = 365
    scheme: str = "Andersen QE-M"
    seed: int = 42
    antithetic: bool = True
    martingale_correction: bool = True
    confidence_level: float = 0.95
    sample_paths: int = 40
    time_convergence_check: bool = True
    convergence_paths: int = 5_000
    convergence_replications: int = 3
    path_convergence_check: bool = True
    path_convergence_base_paths: int = 5_000
    path_convergence_replications: int = 3
    simulate_heston_benchmark: bool = True


def _signature(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(payload), sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16].upper()


def _parameters_from_bates_calibration(calibration_result: Mapping[str, Any]) -> BatesParameters:
    values = calibration_result.get("parameters")
    if not isinstance(values, Mapping):
        raise ValueError("A completed Bates calibration with parameters is required.")
    return BatesParameters(
        kappa=float(values["kappa"]),
        theta=float(values["theta"]),
        sigma_v=float(values["sigma_v"]),
        rho=float(values["rho"]),
        v0=float(values["v0"]),
        jump_intensity=float(values["jump_intensity"]),
        jump_mean=float(values["jump_mean"]),
        jump_volatility=float(values["jump_volatility"]),
    )


def _fit_table_from_bates_calibration(calibration_result: Mapping[str, Any]) -> pd.DataFrame:
    frame = calibration_result.get("fit_table")
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError("The Bates calibration fit table is unavailable.")
    required = {
        "dte",
        "time_to_expiry",
        "strike",
        "option_type",
        "effective_q",
        "target_price",
        "bates_price",
        "target_iv",
        "bates_iv",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Bates fit table missing columns: {sorted(missing)}")
    output = frame.copy().reset_index(drop=True)
    output["dte"] = pd.to_numeric(output["dte"], errors="coerce").round().astype("Int64")
    output = output.dropna(subset=["dte", "strike", "time_to_expiry", "effective_q"]).copy()
    output["dte"] = output["dte"].astype(int)
    return output


def _jump_compensator(parameters: BatesParameters) -> float:
    return float(math.exp(parameters.jump_mean + 0.5 * parameters.jump_volatility**2) - 1.0)


def _jump_draws(
    rng: np.random.Generator,
    paths: int,
    intensity_dt: float,
    jump_mean: float,
    jump_volatility: float,
    antithetic: bool,
) -> tuple[np.ndarray, np.ndarray]:
    """Exact compound-Poisson aggregate for one time step.

    Poisson counts remain exact independent draws. When antithetic sampling is enabled,
    the Gaussian jump-size innovations are paired; the count component is not altered.
    """
    if intensity_dt <= 0.0:
        return np.zeros(paths, dtype=np.int32), np.zeros(paths, dtype=float)
    counts = rng.poisson(float(intensity_dt), size=int(paths)).astype(np.int32)
    if antithetic:
        half = (int(paths) + 1) // 2
        z_half = rng.standard_normal(half)
        z = np.concatenate([z_half, -z_half])[:paths]
    else:
        z = rng.standard_normal(paths)
    aggregate = counts.astype(float) * float(jump_mean)
    positive = counts > 0
    aggregate[positive] += np.sqrt(counts[positive].astype(float)) * float(jump_volatility) * z[positive]
    return counts, aggregate


def _expected_shortfall(values: np.ndarray, alpha: float) -> tuple[float, float]:
    values = np.asarray(values, dtype=float)
    var = float(np.quantile(values, alpha))
    tail = values[values <= var]
    return var, float(np.mean(tail)) if len(tail) else var


def _terminal_risk_metrics(values: np.ndarray, spot: float) -> dict[str, float]:
    values = np.asarray(values, dtype=float)
    returns = values / float(spot) - 1.0
    var5, es5 = _expected_shortfall(returns, 0.05)
    var1, es1 = _expected_shortfall(returns, 0.01)
    return {
        "terminal_mean": float(np.mean(values)),
        "terminal_median": float(np.median(values)),
        "mean_return": float(np.mean(returns)),
        "median_return": float(np.median(returns)),
        "var_5": var5,
        "es_5": es5,
        "var_1": var1,
        "es_1": es1,
        "prob_below_spot": float(np.mean(values < float(spot))),
        "skewness": float(skew(returns, bias=False)),
        "excess_kurtosis": float(kurtosis(returns, fisher=True, bias=False)),
    }


def _simulate_bates_core(
    spot: float,
    risk_free_rate: float,
    parameters: BatesParameters,
    fit_table: pd.DataFrame,
    paths: int,
    steps_per_year: int,
    scheme: str,
    seed: int,
    antithetic: bool,
    martingale_correction: bool,
    sample_paths: int,
    requested_dtes: Sequence[int] | None = None,
    record_curves: bool = True,
) -> dict[str, Any]:
    scheme = _normalize_scheme(scheme)
    paths = max(int(paths), 2)
    requested = sorted(set(int(value) for value in (requested_dtes or fit_table["dte"].unique())))
    max_dte = int(max(requested))
    max_time = max_dte / 365.0
    steps = max(int(math.ceil(max_time * int(steps_per_year))), 1)
    time_grid, q_step, carry_nodes = _carry_schedule(fit_table, max_time, steps)
    dt_grid = np.diff(time_grid)
    dte_to_step = {
        int(dte): int(np.clip(round((int(dte) / 365.0) / max_time * steps), 1, steps))
        for dte in requested
        if int(dte) <= max_dte
    }
    step_to_dtes: dict[int, list[int]] = {}
    for dte, index in dte_to_step.items():
        step_to_dtes.setdefault(index, []).append(dte)

    diffusion_rng = np.random.default_rng(int(seed))
    jump_rng = np.random.default_rng(int(seed) + 1_000_003)
    log_spot = np.full(paths, math.log(float(spot)), dtype=float)
    log_spot_diffusion_only = np.full(paths, math.log(float(spot)), dtype=float)
    variance = np.full(paths, max(float(parameters.v0), 0.0), dtype=float)
    cumulative_jump_count = np.zeros(paths, dtype=np.int32)
    cumulative_jump_log = np.zeros(paths, dtype=float)

    sample_count = int(np.clip(sample_paths, 0, paths))
    sample_spot = np.empty((sample_count, steps + 1), dtype=float) if sample_count else np.empty((0, steps + 1), dtype=float)
    sample_diffusion_spot = np.empty_like(sample_spot)
    sample_variance = np.empty_like(sample_spot)
    sample_jump_count = np.empty_like(sample_spot)
    if sample_count:
        sample_spot[:, 0] = float(spot)
        sample_diffusion_spot[:, 0] = float(spot)
        sample_variance[:, 0] = variance[:sample_count]
        sample_jump_count[:, 0] = 0.0

    quantile_levels = np.asarray([0.05, 0.25, 0.50, 0.75, 0.95], dtype=float)
    if record_curves:
        spot_quantiles = np.empty((steps + 1, len(quantile_levels)), dtype=float)
        variance_quantiles = np.empty_like(spot_quantiles)
        mean_spot = np.empty(steps + 1, dtype=float)
        mean_diffusion_spot = np.empty(steps + 1, dtype=float)
        mean_variance = np.empty(steps + 1, dtype=float)
        theoretical_variance = np.empty(steps + 1, dtype=float)
        forward_target = np.empty(steps + 1, dtype=float)
        forward_bias_bps = np.empty(steps + 1, dtype=float)
        mean_jump_count = np.empty(steps + 1, dtype=float)
        probability_any_jump = np.empty(steps + 1, dtype=float)
        mean_jump_log = np.empty(steps + 1, dtype=float)
        zero_fraction = np.empty(steps + 1, dtype=float)
        spot_quantiles[0] = float(spot)
        variance_quantiles[0] = float(parameters.v0)
        mean_spot[0] = float(spot)
        mean_diffusion_spot[0] = float(spot)
        mean_variance[0] = float(parameters.v0)
        theoretical_variance[0] = float(parameters.v0)
        forward_target[0] = float(spot)
        forward_bias_bps[0] = 0.0
        mean_jump_count[0] = 0.0
        probability_any_jump[0] = 0.0
        mean_jump_log[0] = 0.0
        zero_fraction[0] = float(parameters.v0 <= 1e-10)
    else:
        spot_quantiles = variance_quantiles = np.empty((0, 0), dtype=float)
        mean_spot = mean_diffusion_spot = mean_variance = theoretical_variance = np.empty(0, dtype=float)
        forward_target = forward_bias_bps = mean_jump_count = probability_any_jump = mean_jump_log = zero_fraction = np.empty(0, dtype=float)

    heston_parameters = HestonParameters(
        parameters.kappa,
        parameters.theta,
        parameters.sigma_v,
        parameters.rho,
        parameters.v0,
    )
    jump_compensator = _jump_compensator(parameters)
    terminal_spot: dict[int, np.ndarray] = {}
    terminal_diffusion_spot: dict[int, np.ndarray] = {}
    terminal_variance: dict[int, np.ndarray] = {}
    terminal_jump_count: dict[int, np.ndarray] = {}
    terminal_jump_log: dict[int, np.ndarray] = {}
    cumulative_q = 0.0
    max_abs_forward_bias = 0.0
    max_abs_analytic_adjustment = 0.0
    sum_sq_analytic_adjustment = 0.0
    sum_abs_analytic_adjustment = 0.0
    analytic_adjustment_observations = 0
    zero_observations = 0
    use_qe = scheme in {"Andersen QE-M", "Andersen QE (uncorrected)"}
    use_qe_m = scheme == "Andersen QE-M" and bool(martingale_correction)
    rho = float(np.clip(parameters.rho, -0.999999, 0.999999))
    rho_perp = math.sqrt(max(1.0 - rho * rho, 0.0))

    for step in range(1, steps + 1):
        dt = float(dt_grid[step - 1])
        q_rate = float(q_step[step - 1])
        cumulative_q += q_rate * dt
        z_var, z_independent, uniform = _random_drivers(diffusion_rng, paths, antithetic)
        v_prev = np.maximum(variance, 0.0)
        adjusted_q = q_rate + parameters.jump_intensity * jump_compensator

        if use_qe:
            variance_next, transition_state = _qe_variance_transition(v_prev, dt, heston_parameters, z_var, uniform)
            diffusion_increment, analytic_adjustment = _qe_log_spot_increment(
                v_prev=v_prev,
                v_next=variance_next,
                dt=dt,
                risk_free_rate=float(risk_free_rate),
                q_rate=adjusted_q,
                parameters=heston_parameters,
                z_independent=z_independent,
                transition_state=transition_state,
                martingale_corrected=use_qe_m,
            )
            if use_qe_m:
                adjustment_bps = analytic_adjustment * 10_000.0
                max_abs_analytic_adjustment = max(max_abs_analytic_adjustment, float(np.max(np.abs(adjustment_bps))))
                sum_sq_analytic_adjustment += float(np.sum(adjustment_bps * adjustment_bps))
                sum_abs_analytic_adjustment += float(np.sum(np.abs(adjustment_bps)))
                analytic_adjustment_observations += int(len(adjustment_bps))
        else:
            z_spot = rho * z_var + rho_perp * z_independent
            variance_next = np.maximum(
                variance
                + parameters.kappa * (parameters.theta - v_prev) * dt
                + parameters.sigma_v * np.sqrt(np.maximum(v_prev * dt, 0.0)) * z_var,
                0.0,
            )
            integrated_variance = np.maximum(v_prev * dt, 0.0)
            diffusion_increment = (
                (float(risk_free_rate) - adjusted_q) * dt
                - 0.5 * integrated_variance
                + np.sqrt(integrated_variance) * z_spot
            )

        counts, jump_log = _jump_draws(
            jump_rng,
            paths,
            parameters.jump_intensity * dt,
            parameters.jump_mean,
            parameters.jump_volatility,
            antithetic,
        )
        cumulative_jump_count += counts
        cumulative_jump_log += jump_log
        log_spot += diffusion_increment + jump_log
        # Same Bates diffusion parameters and common diffusion drivers, but no jumps.
        # The compensator is removed to isolate the jump contribution pathwise.
        log_spot_diffusion_only += diffusion_increment + parameters.jump_intensity * jump_compensator * dt

        current_spot = np.exp(np.clip(log_spot, -50.0, 50.0))
        current_diffusion_spot = np.exp(np.clip(log_spot_diffusion_only, -50.0, 50.0))
        target_forward = float(spot) * math.exp(float(risk_free_rate) * time_grid[step] - cumulative_q)
        sample_mean = float(np.mean(current_spot))
        bias_bps = (sample_mean / max(target_forward, 1e-14) - 1.0) * 10_000.0
        max_abs_forward_bias = max(max_abs_forward_bias, abs(bias_bps))

        variance = variance_next
        zero_observations += int(np.sum(variance <= 1e-10))
        if sample_count:
            sample_spot[:, step] = current_spot[:sample_count]
            sample_diffusion_spot[:, step] = current_diffusion_spot[:sample_count]
            sample_variance[:, step] = variance[:sample_count]
            sample_jump_count[:, step] = cumulative_jump_count[:sample_count]
        if record_curves:
            spot_quantiles[step] = np.quantile(current_spot, quantile_levels)
            variance_quantiles[step] = np.quantile(variance, quantile_levels)
            mean_spot[step] = sample_mean
            mean_diffusion_spot[step] = float(np.mean(current_diffusion_spot))
            mean_variance[step] = float(np.mean(variance))
            theoretical_variance[step] = float(parameters.theta + (parameters.v0 - parameters.theta) * math.exp(-parameters.kappa * time_grid[step]))
            forward_target[step] = target_forward
            forward_bias_bps[step] = bias_bps
            mean_jump_count[step] = float(np.mean(cumulative_jump_count))
            probability_any_jump[step] = float(np.mean(cumulative_jump_count > 0))
            mean_jump_log[step] = float(np.mean(cumulative_jump_log))
            zero_fraction[step] = float(np.mean(variance <= 1e-10))
        if step in step_to_dtes:
            for dte in step_to_dtes[step]:
                terminal_spot[int(dte)] = current_spot.copy()
                terminal_diffusion_spot[int(dte)] = current_diffusion_spot.copy()
                terminal_variance[int(dte)] = variance.copy()
                terminal_jump_count[int(dte)] = cumulative_jump_count.copy()
                terminal_jump_log[int(dte)] = cumulative_jump_log.copy()

    if record_curves:
        path_quantiles = pd.DataFrame({
            "time_years": time_grid,
            "day": time_grid * 365.0,
            "spot_p05": spot_quantiles[:, 0],
            "spot_p25": spot_quantiles[:, 1],
            "spot_p50": spot_quantiles[:, 2],
            "spot_p75": spot_quantiles[:, 3],
            "spot_p95": spot_quantiles[:, 4],
            "spot_mean": mean_spot,
            "diffusion_only_mean": mean_diffusion_spot,
            "forward_target": forward_target,
            "forward_bias_bps": forward_bias_bps,
        })
        variance_diagnostics = pd.DataFrame({
            "time_years": time_grid,
            "day": time_grid * 365.0,
            "variance_p05": variance_quantiles[:, 0],
            "variance_p25": variance_quantiles[:, 1],
            "variance_p50": variance_quantiles[:, 2],
            "variance_p75": variance_quantiles[:, 3],
            "variance_p95": variance_quantiles[:, 4],
            "mean_variance": mean_variance,
            "theoretical_mean_variance": theoretical_variance,
            "zero_fraction": zero_fraction,
        })
        jump_diagnostics = pd.DataFrame({
            "time_years": time_grid,
            "day": time_grid * 365.0,
            "expected_cumulative_jumps": parameters.jump_intensity * time_grid,
            "mean_cumulative_jumps": mean_jump_count,
            "probability_at_least_one_jump": probability_any_jump,
            "mean_cumulative_log_jump": mean_jump_log,
        })
    else:
        path_quantiles = pd.DataFrame()
        variance_diagnostics = pd.DataFrame()
        jump_diagnostics = pd.DataFrame()

    return {
        "terminal_spot": terminal_spot,
        "terminal_diffusion_spot": terminal_diffusion_spot,
        "terminal_variance": terminal_variance,
        "terminal_jump_count": terminal_jump_count,
        "terminal_jump_log": terminal_jump_log,
        "dte_to_step": dte_to_step,
        "time_grid": time_grid,
        "carry_nodes": carry_nodes,
        "path_quantiles": path_quantiles,
        "variance_diagnostics": variance_diagnostics,
        "jump_diagnostics": jump_diagnostics,
        "sample_spot_paths": sample_spot,
        "sample_diffusion_spot_paths": sample_diffusion_spot,
        "sample_variance_paths": sample_variance,
        "sample_jump_count_paths": sample_jump_count,
        "max_abs_forward_bias_bps": float(max_abs_forward_bias),
        "max_abs_martingale_correction_bps": float(max_abs_analytic_adjustment),
        "rms_martingale_correction_bps": float(math.sqrt(sum_sq_analytic_adjustment / max(analytic_adjustment_observations, 1))),
        "mean_abs_martingale_correction_bps": float(sum_abs_analytic_adjustment / max(analytic_adjustment_observations, 1)),
        "martingale_method": "Andersen analytic QE-M + exact jump compensator" if use_qe_m else "Exact jump compensator only",
        "jump_compensator": jump_compensator,
        "variance_zero_observation_rate": float(zero_observations / max(paths * steps, 1)),
        "steps": steps,
        "paths": paths,
    }


def _distribution_summaries(
    simulation: Mapping[str, Any],
    fit_table: pd.DataFrame,
    spot: float,
    risk_free_rate: float,
    confidence_level: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    carry = fit_table.groupby("dte", as_index=False).agg(
        time_to_expiry=("time_to_expiry", "median"),
        effective_q=("effective_q", "median"),
    ).set_index("dte")
    rows: list[dict[str, Any]] = []
    jump_rows: list[dict[str, Any]] = []
    attribution_rows: list[dict[str, Any]] = []
    zcrit = float(norm.ppf(0.5 + float(confidence_level) / 2.0))
    for dte, terminal in sorted(simulation["terminal_spot"].items()):
        terminal = np.asarray(terminal, dtype=float)
        diffusion = np.asarray(simulation["terminal_diffusion_spot"][dte], dtype=float)
        variance = np.asarray(simulation["terminal_variance"][dte], dtype=float)
        counts = np.asarray(simulation["terminal_jump_count"][dte], dtype=float)
        jump_log = np.asarray(simulation["terminal_jump_log"][dte], dtype=float)
        t = float(carry.loc[dte, "time_to_expiry"]) if dte in carry.index else dte / 365.0
        q = float(carry.loc[dte, "effective_q"]) if dte in carry.index else float(fit_table["effective_q"].median())
        forward = float(spot) * math.exp((float(risk_free_rate) - q) * t)
        metrics = _terminal_risk_metrics(terminal, spot)
        diffusion_metrics = _terminal_risk_metrics(diffusion, spot)
        mean_se = float(np.std(terminal, ddof=1) / math.sqrt(len(terminal))) if len(terminal) > 1 else float("nan")
        bias = metrics["terminal_mean"] - forward
        bias_bps = bias / max(forward, 1e-14) * 10_000.0
        bias_se_bps = mean_se / max(forward, 1e-14) * 10_000.0 if np.isfinite(mean_se) else float("nan")
        bias_z = bias / mean_se if np.isfinite(mean_se) and mean_se > 0.0 else float("nan")
        rows.append({
            "dte": int(dte),
            "time_to_expiry": t,
            "effective_q": q,
            "forward_target": forward,
            **metrics,
            "terminal_mean_se": mean_se,
            "forward_bias_bps": bias_bps,
            "forward_bias_se_bps": bias_se_bps,
            "forward_bias_z": bias_z,
            "forward_bias_ci_low_bps": bias_bps - zcrit * bias_se_bps if np.isfinite(bias_se_bps) else float("nan"),
            "forward_bias_ci_high_bps": bias_bps + zcrit * bias_se_bps if np.isfinite(bias_se_bps) else float("nan"),
            "forward_bias_statistically_significant": bool(np.isfinite(bias_z) and abs(bias_z) > zcrit),
            "terminal_variance_mean": float(np.mean(variance)),
            "terminal_variance_p05": float(np.quantile(variance, 0.05)),
            "terminal_variance_p95": float(np.quantile(variance, 0.95)),
            "terminal_variance_zero_fraction": float(np.mean(variance <= 1e-10)),
            "expected_jump_count": float(simulation.get("jump_intensity", np.nan) * t),
            "empirical_jump_count": float(np.mean(counts)),
            "probability_at_least_one_jump": float(np.mean(counts > 0)),
            "probability_two_or_more_jumps": float(np.mean(counts >= 2)),
        })
        expected_count = float(simulation.get("jump_intensity", np.nan) * t)
        count_se = math.sqrt(max(expected_count, 0.0) / max(len(counts), 1)) if np.isfinite(expected_count) else float("nan")
        jump_rows.append({
            "dte": int(dte),
            "time_to_expiry": t,
            "expected_jump_count": expected_count,
            "empirical_jump_count": float(np.mean(counts)),
            "jump_count_variance": float(np.var(counts, ddof=1)) if len(counts) > 1 else float("nan"),
            "jump_count_mean_se": count_se,
            "jump_count_z": (float(np.mean(counts)) - expected_count) / count_se if np.isfinite(count_se) and count_se > 0.0 else float("nan"),
            "probability_zero_jumps": float(np.mean(counts == 0)),
            "probability_at_least_one_jump": float(np.mean(counts > 0)),
            "probability_two_or_more_jumps": float(np.mean(counts >= 2)),
            "mean_cumulative_log_jump": float(np.mean(jump_log)),
            "median_cumulative_log_jump": float(np.median(jump_log)),
        })
        attribution_rows.append({
            "dte": int(dte),
            "bates_mean_return": metrics["mean_return"],
            "diffusion_only_mean_return": diffusion_metrics["mean_return"],
            "jump_mean_return_contribution": metrics["mean_return"] - diffusion_metrics["mean_return"],
            "bates_var_5": metrics["var_5"],
            "diffusion_only_var_5": diffusion_metrics["var_5"],
            "jump_var_5_contribution": metrics["var_5"] - diffusion_metrics["var_5"],
            "bates_es_5": metrics["es_5"],
            "diffusion_only_es_5": diffusion_metrics["es_5"],
            "jump_es_5_contribution": metrics["es_5"] - diffusion_metrics["es_5"],
            "bates_skewness": metrics["skewness"],
            "diffusion_only_skewness": diffusion_metrics["skewness"],
            "jump_skewness_contribution": metrics["skewness"] - diffusion_metrics["skewness"],
            "probability_at_least_one_jump": float(np.mean(counts > 0)),
        })
    return pd.DataFrame(rows), pd.DataFrame(jump_rows), pd.DataFrame(attribution_rows)


def _black_scholes_vega(
    spot: float,
    strike: float,
    time_to_expiry: float,
    risk_free_rate: float,
    dividend_yield: float,
    volatility: float,
) -> float:
    """Return Black--Scholes vega for a unit volatility change.

    Multiplying the result by 0.01 gives price sensitivity to one implied-
    volatility percentage point. The diagnostic is used only to interpret
    Monte Carlo/Fourier IV residuals; it does not alter pricing.
    """
    values = (spot, strike, time_to_expiry, risk_free_rate, dividend_yield, volatility)
    if not all(np.isfinite(float(value)) for value in values):
        return float("nan")
    if spot <= 0.0 or strike <= 0.0 or time_to_expiry <= 0.0 or volatility <= 0.0:
        return float("nan")
    sqrt_t = math.sqrt(float(time_to_expiry))
    denominator = float(volatility) * sqrt_t
    if denominator <= 0.0:
        return float("nan")
    d1 = (
        math.log(float(spot) / float(strike))
        + (float(risk_free_rate) - float(dividend_yield) + 0.5 * float(volatility) ** 2) * float(time_to_expiry)
    ) / denominator
    return float(float(spot) * math.exp(-float(dividend_yield) * float(time_to_expiry)) * norm.pdf(d1) * sqrt_t)


def _source_champion_reason(calibration_result: Mapping[str, Any]) -> str:
    """Extract an auditable explanation for a non-champion Bates decision."""
    notes = calibration_result.get("champion_notes")
    if isinstance(notes, Sequence) and not isinstance(notes, (str, bytes)):
        clean = [str(value).strip() for value in notes if str(value).strip()]
        if clean:
            return " ".join(clean[:3])
    gate_table = calibration_result.get("champion_gate_table")
    if isinstance(gate_table, pd.DataFrame) and not gate_table.empty and "result" in gate_table:
        failed = gate_table[gate_table["result"].astype(str).str.upper().ne("PASS")]
        if not failed.empty:
            details: list[str] = []
            for row in failed.head(3).itertuples(index=False):
                gate = str(getattr(row, "gate", "Gate"))
                detail = str(getattr(row, "detail", "")).strip()
                details.append(f"{gate}: {detail}" if detail else gate)
            return "Failed champion gate(s): " + "; ".join(details)
    status = str(calibration_result.get("champion_status", "UNKNOWN"))
    return f"Source champion decision is {status}."


def _classify_iv_residuals(
    table: pd.DataFrame,
    confidence_level: float,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Classify large IV residuals using price significance and option vega.

    A large IV difference on a very low-vega option can be generated by a
    numerically small, statistically insignificant price difference. Such rows
    are retained in the audit but labelled LOW_VEGA_IV_AMPLIFICATION rather
    than being treated as primary evidence of discretisation failure.
    """
    output = table.copy()
    if output.empty:
        return output, {
            "low_vega_threshold_per_iv_point": float("nan"),
            "low_vega_amplification_count": 0,
            "statistically_significant_price_error_count": 0,
        }
    vega = pd.to_numeric(output.get("vega_per_iv_point"), errors="coerce")
    positive = vega[np.isfinite(vega) & (vega > 0.0)]
    if positive.empty:
        threshold = float("nan")
    else:
        median = float(np.nanmedian(positive.to_numpy(dtype=float)))
        threshold = max(1e-6, 0.15 * median)
    zcrit = float(norm.ppf(0.5 + float(confidence_level) / 2.0))
    iv_error_pp = pd.to_numeric(output.get("mc_fourier_iv_error"), errors="coerce") * 100.0
    z_score = pd.to_numeric(output.get("mc_fourier_z_score"), errors="coerce")
    inside_ci = output.get("fourier_inside_mc_ci", pd.Series(False, index=output.index)).astype(bool)
    within_price_noise = inside_ci | (np.isfinite(z_score) & (np.abs(z_score) <= zcrit))
    low_vega = np.isfinite(vega) & np.isfinite(threshold) & (vega <= threshold)
    large_iv = np.isfinite(iv_error_pp) & (np.abs(iv_error_pp) >= 1.0)
    significant_price = np.isfinite(z_score) & (np.abs(z_score) > zcrit) & ~inside_ci

    diagnostic = np.full(len(output), "PASS", dtype=object)
    diagnostic[~np.isfinite(iv_error_pp)] = "IV_UNAVAILABLE"
    diagnostic[large_iv & within_price_noise] = "IV_RESIDUAL_WITHIN_MC_NOISE"
    diagnostic[significant_price] = "PRICE_ERROR_STATISTICALLY_SIGNIFICANT"
    diagnostic[large_iv & within_price_noise & low_vega] = "LOW_VEGA_IV_AMPLIFICATION"

    output["iv_error_pp"] = iv_error_pp
    output["vega_low_threshold_per_iv_point"] = threshold
    output["low_vega_flag"] = low_vega
    output["price_error_statistically_significant"] = significant_price
    output["iv_residual_diagnostic"] = diagnostic
    non_low = output.loc[output["iv_residual_diagnostic"] != "LOW_VEGA_IV_AMPLIFICATION", "iv_error_pp"]
    summary = {
        "low_vega_threshold_per_iv_point": threshold,
        "low_vega_amplification_count": int(np.sum(diagnostic == "LOW_VEGA_IV_AMPLIFICATION")),
        "statistically_significant_price_error_count": int(np.sum(diagnostic == "PRICE_ERROR_STATISTICALLY_SIGNIFICANT")),
        "max_abs_iv_error_pp": float(np.nanmax(np.abs(iv_error_pp))) if np.isfinite(iv_error_pp).any() else float("nan"),
        "max_abs_iv_error_pp_excluding_low_vega": (
            float(np.nanmax(np.abs(pd.to_numeric(non_low, errors="coerce"))))
            if len(non_low) and np.isfinite(pd.to_numeric(non_low, errors="coerce")).any()
            else float("nan")
        ),
    }
    return output, summary


def _pricing_validation(
    fit_table: pd.DataFrame,
    simulation: Mapping[str, Any],
    spot: float,
    risk_free_rate: float,
    confidence_level: float,
) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    zcrit = float(norm.ppf(0.5 + float(confidence_level) / 2.0))
    for row in fit_table.itertuples(index=False):
        dte = int(row.dte)
        if dte not in simulation["terminal_spot"]:
            continue
        terminal = np.asarray(simulation["terminal_spot"][dte], dtype=float)
        strike = float(row.strike)
        option_type = str(row.option_type).lower()
        payoff = np.maximum(terminal - strike, 0.0) if option_type == "call" else np.maximum(strike - terminal, 0.0)
        discounted = math.exp(-float(risk_free_rate) * float(row.time_to_expiry)) * payoff
        mc_price = float(np.mean(discounted))
        mc_se = float(np.std(discounted, ddof=1) / math.sqrt(len(discounted))) if len(discounted) > 1 else float("nan")
        fourier_price = float(row.bates_price)
        error = mc_price - fourier_price
        mc_iv = implied_volatility(
            mc_price,
            float(spot),
            strike,
            float(row.time_to_expiry),
            float(risk_free_rate),
            float(row.effective_q),
            option_type,
        )
        fourier_iv = float(row.bates_iv)
        vega = _black_scholes_vega(
            float(spot),
            strike,
            float(row.time_to_expiry),
            float(risk_free_rate),
            float(row.effective_q),
            fourier_iv,
        )
        rows.append({
            "sample_role": getattr(row, "sample_role", "UNKNOWN"),
            "expiration": getattr(row, "expiration", None),
            "dte": dte,
            "time_to_expiry": float(row.time_to_expiry),
            "strike": strike,
            "option_type": option_type,
            "log_moneyness": float(getattr(row, "log_moneyness", np.nan)),
            "moneyness_bucket": getattr(row, "moneyness_bucket", "UNKNOWN"),
            "target_price": float(row.target_price),
            "fourier_price": fourier_price,
            "mc_price": mc_price,
            "mc_standard_error": mc_se,
            "mc_ci_low": mc_price - zcrit * mc_se if np.isfinite(mc_se) else float("nan"),
            "mc_ci_high": mc_price + zcrit * mc_se if np.isfinite(mc_se) else float("nan"),
            "mc_fourier_price_error": error,
            "mc_fourier_z_score": error / mc_se if np.isfinite(mc_se) and mc_se > 0.0 else float("nan"),
            "fourier_inside_mc_ci": bool(abs(error) <= zcrit * mc_se) if np.isfinite(mc_se) else False,
            "target_iv": float(row.target_iv),
            "fourier_iv": fourier_iv,
            "mc_iv": float(mc_iv),
            "mc_fourier_iv_error": float(mc_iv - fourier_iv) if np.isfinite(mc_iv) else float("nan"),
            "mc_target_iv_error": float(mc_iv - float(row.target_iv)) if np.isfinite(mc_iv) else float("nan"),
            "black_scholes_vega": vega,
            "vega_per_iv_point": vega * 0.01 if np.isfinite(vega) else float("nan"),
        })
    table = pd.DataFrame(rows)
    if table.empty:
        return table, {}, pd.DataFrame(), pd.DataFrame()
    table, residual_diagnostics = _classify_iv_residuals(table, confidence_level)
    valid_price = table[np.isfinite(table["mc_fourier_price_error"])].copy()
    valid_iv = table[np.isfinite(table["mc_fourier_iv_error"])].copy()
    target_valid = table[np.isfinite(table["mc_target_iv_error"])].copy()
    summary = {
        "count": int(len(table)),
        "price_rmse": float(np.sqrt(np.mean(valid_price["mc_fourier_price_error"] ** 2))) if len(valid_price) else float("nan"),
        "price_rmse_pct_spot": float(np.sqrt(np.mean(valid_price["mc_fourier_price_error"] ** 2)) / spot) if len(valid_price) else float("nan"),
        "mean_abs_price_error": float(np.mean(np.abs(valid_price["mc_fourier_price_error"]))) if len(valid_price) else float("nan"),
        "iv_rmse": float(np.sqrt(np.mean(valid_iv["mc_fourier_iv_error"] ** 2))) if len(valid_iv) else float("nan"),
        "target_iv_rmse": float(np.sqrt(np.mean(target_valid["mc_target_iv_error"] ** 2))) if len(target_valid) else float("nan"),
        "confidence_coverage": float(np.mean(table["fourier_inside_mc_ci"])),
        "median_abs_z_score": float(np.nanmedian(np.abs(table["mc_fourier_z_score"]))),
        "p95_abs_z_score": float(np.nanquantile(np.abs(table["mc_fourier_z_score"]), 0.95)),
        **residual_diagnostics,
    }
    maturity = (
        table.groupby(["sample_role", "expiration", "dte"], dropna=False)
        .agg(
            count=("strike", "size"),
            price_rmse=("mc_fourier_price_error", lambda x: float(np.sqrt(np.nanmean(np.asarray(x, dtype=float) ** 2)))),
            iv_rmse=("mc_fourier_iv_error", lambda x: float(np.sqrt(np.nanmean(np.asarray(x, dtype=float) ** 2)))),
            coverage=("fourier_inside_mc_ci", "mean"),
            mean_abs_z=("mc_fourier_z_score", lambda x: float(np.nanmean(np.abs(np.asarray(x, dtype=float))))),
            low_vega_amplification_count=("iv_residual_diagnostic", lambda x: int(np.sum(np.asarray(x, dtype=object) == "LOW_VEGA_IV_AMPLIFICATION"))),
            price_significant_count=("iv_residual_diagnostic", lambda x: int(np.sum(np.asarray(x, dtype=object) == "PRICE_ERROR_STATISTICALLY_SIGNIFICANT"))),
            max_abs_iv_error_pp=("iv_error_pp", lambda x: float(np.nanmax(np.abs(np.asarray(x, dtype=float))))),
        )
        .reset_index()
    )
    bucket = (
        table.groupby(["sample_role", "moneyness_bucket"], dropna=False)
        .agg(
            count=("strike", "size"),
            price_rmse=("mc_fourier_price_error", lambda x: float(np.sqrt(np.nanmean(np.asarray(x, dtype=float) ** 2)))),
            iv_rmse=("mc_fourier_iv_error", lambda x: float(np.sqrt(np.nanmean(np.asarray(x, dtype=float) ** 2)))),
            coverage=("fourier_inside_mc_ci", "mean"),
            mean_abs_z=("mc_fourier_z_score", lambda x: float(np.nanmean(np.abs(np.asarray(x, dtype=float))))),
            low_vega_amplification_count=("iv_residual_diagnostic", lambda x: int(np.sum(np.asarray(x, dtype=object) == "LOW_VEGA_IV_AMPLIFICATION"))),
            price_significant_count=("iv_residual_diagnostic", lambda x: int(np.sum(np.asarray(x, dtype=object) == "PRICE_ERROR_STATISTICALLY_SIGNIFICANT"))),
            max_abs_iv_error_pp=("iv_error_pp", lambda x: float(np.nanmax(np.abs(np.asarray(x, dtype=float))))),
        )
        .reset_index()
    )
    return table, summary, maturity, bucket


def _representative_quotes(fit_table: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, group in fit_table.groupby("dte"):
        rows.append(group.iloc[np.argmin(np.abs(group["log_moneyness"].to_numpy(dtype=float)))])
    return pd.DataFrame(rows).reset_index(drop=True)


def _aggregate_replications(raw: pd.DataFrame, group_column: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    zcrit = 1.96
    for value, group in raw.groupby(group_column, sort=True):
        n = max(len(group), 1)
        mean_rmse = float(group["price_rmse"].mean())
        sd_rmse = float(group["price_rmse"].std(ddof=1)) if len(group) > 1 else 0.0
        half_width = zcrit * sd_rmse / math.sqrt(n) if n > 1 else float("nan")
        rows.append({
            group_column: int(value),
            "replications": int(n),
            "price_rmse_mean": mean_rmse,
            "price_rmse_sd": sd_rmse,
            "price_rmse_ci_low": max(mean_rmse - half_width, 0.0) if np.isfinite(half_width) else float("nan"),
            "price_rmse_ci_high": mean_rmse + half_width if np.isfinite(half_width) else float("nan"),
            "mean_mc_standard_error": float(group["mean_mc_standard_error"].mean()),
            "max_abs_forward_bias_bps_mean": float(group["max_abs_forward_bias_bps"].mean()),
            "max_abs_forward_z_mean": float(group["max_abs_forward_z"].mean()),
            "representative_quotes": int(group["representative_quotes"].iloc[0]),
            "paths_per_replication": int(group["paths"].iloc[0]),
            "max_steps": int(group["max_steps"].max()),
        })
    return pd.DataFrame(rows).sort_values(group_column).reset_index(drop=True)


def _convergence_run(
    spot: float,
    risk_free_rate: float,
    parameters: BatesParameters,
    fit_table: pd.DataFrame,
    paths: int,
    steps_per_year: int,
    settings: BatesSimulationSettings,
    seed: int,
) -> dict[str, float]:
    representative = _representative_quotes(fit_table)
    sim = _simulate_bates_core(
        spot=spot,
        risk_free_rate=risk_free_rate,
        parameters=parameters,
        fit_table=fit_table,
        paths=max(int(paths), 500),
        steps_per_year=int(steps_per_year),
        scheme=settings.scheme,
        seed=int(seed),
        antithetic=settings.antithetic,
        martingale_correction=settings.martingale_correction,
        sample_paths=0,
        requested_dtes=representative["dte"].astype(int).tolist(),
        record_curves=False,
    )
    errors: list[float] = []
    ses: list[float] = []
    forward_biases: list[float] = []
    forward_z: list[float] = []
    for quote in representative.itertuples(index=False):
        terminal = np.asarray(sim["terminal_spot"][int(quote.dte)], dtype=float)
        payoff = np.maximum(terminal - float(quote.strike), 0.0) if str(quote.option_type).lower() == "call" else np.maximum(float(quote.strike) - terminal, 0.0)
        discounted = math.exp(-risk_free_rate * float(quote.time_to_expiry)) * payoff
        price = float(np.mean(discounted))
        se = float(np.std(discounted, ddof=1) / math.sqrt(len(discounted)))
        errors.append(price - float(quote.bates_price))
        ses.append(se)
        forward = spot * math.exp((risk_free_rate - float(quote.effective_q)) * float(quote.time_to_expiry))
        mean_se = float(np.std(terminal, ddof=1) / math.sqrt(len(terminal)))
        bias = float(np.mean(terminal) - forward)
        forward_biases.append(bias / forward * 10_000.0)
        forward_z.append(bias / mean_se if mean_se > 0.0 else 0.0)
    errors_arr = np.asarray(errors, dtype=float)
    return {
        "paths": int(sim["paths"]),
        "max_steps": int(sim["steps"]),
        "representative_quotes": int(len(representative)),
        "price_rmse": float(np.sqrt(np.mean(errors_arr**2))),
        "mean_mc_standard_error": float(np.mean(ses)),
        "max_abs_forward_bias_bps": float(np.max(np.abs(forward_biases))),
        "max_abs_forward_z": float(np.max(np.abs(forward_z))),
    }


def _time_convergence_table(
    spot: float,
    risk_free_rate: float,
    parameters: BatesParameters,
    fit_table: pd.DataFrame,
    settings: BatesSimulationSettings,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    step_sets = sorted(set([max(91, settings.steps_per_year // 2), settings.steps_per_year, min(730, settings.steps_per_year * 2)]))
    rows: list[dict[str, Any]] = []
    for replication in range(max(int(settings.convergence_replications), 1)):
        seed = int(settings.seed) + replication * 100_003
        for steps_per_year in step_sets:
            row = _convergence_run(
                spot,
                risk_free_rate,
                parameters,
                fit_table,
                settings.convergence_paths,
                steps_per_year,
                settings,
                seed,
            )
            row.update({"replication": replication + 1, "steps_per_year": steps_per_year})
            rows.append(row)
    raw = pd.DataFrame(rows)
    table = _aggregate_replications(raw, "steps_per_year")
    if table.empty:
        return table, {"status": "NOT_RUN", "reason": "No time-step convergence rows were produced.", "raw_replications": raw}
    means = table["price_rmse_mean"].to_numpy(dtype=float)
    low = table["price_rmse_ci_low"].to_numpy(dtype=float)
    high = table["price_rmse_ci_high"].to_numpy(dtype=float)
    overlap = bool(np.nanmax(low) <= np.nanmin(high)) if np.isfinite(low).all() and np.isfinite(high).all() else False
    monotone = bool(np.all(np.diff(means) <= 0.0))
    if overlap:
        status = "INCONCLUSIVE_MC_NOISE"
        reason = "RMSE confidence intervals overlap across tested time grids; Monte Carlo noise dominates the observed differences."
    elif monotone and means[-1] < means[0]:
        status = "CONVERGED"
        reason = "Pricing RMSE declines monotonically as the time grid is refined."
    elif means[-1] < 0.90 * means[0]:
        status = "IMPROVING_NON_MONOTONIC"
        reason = "The finest time grid improves materially on the coarsest grid, but the sequence is not monotone."
    else:
        status = "NOT_CONVERGED"
        reason = "The finest time grid does not improve materially on the coarsest grid after replication averaging."
    return table, {
        "status": status,
        "reason": reason,
        "coarsest_rmse": float(means[0]),
        "finest_rmse": float(means[-1]),
        "relative_change": float(means[-1] / max(means[0], 1e-14) - 1.0),
        "raw_replications": raw,
    }


def _path_convergence_table(
    spot: float,
    risk_free_rate: float,
    parameters: BatesParameters,
    fit_table: pd.DataFrame,
    settings: BatesSimulationSettings,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    base = max(int(settings.path_convergence_base_paths), 1_000)
    path_sets = sorted(set([max(1_000, base // 2), base, min(40_000, base * 2)]))
    rows: list[dict[str, Any]] = []
    for replication in range(max(int(settings.path_convergence_replications), 1)):
        seed = int(settings.seed) + 700_001 + replication * 100_019
        for paths in path_sets:
            row = _convergence_run(
                spot,
                risk_free_rate,
                parameters,
                fit_table,
                paths,
                settings.steps_per_year,
                settings,
                seed,
            )
            row.update({"replication": replication + 1, "path_count": paths})
            rows.append(row)
    raw = pd.DataFrame(rows)
    table = _aggregate_replications(raw, "path_count")
    if table.empty:
        return table, {"status": "NOT_RUN", "reason": "No path-count convergence rows were produced.", "raw_replications": raw}
    se = table["mean_mc_standard_error"].to_numpy(dtype=float)
    rmse_low = table["price_rmse_ci_low"].to_numpy(dtype=float)
    rmse_high = table["price_rmse_ci_high"].to_numpy(dtype=float)
    se_monotone = bool(np.all(np.diff(se) <= 0.0))
    expected_ratio = math.sqrt(float(table["path_count"].iloc[0]) / float(table["path_count"].iloc[-1]))
    observed_ratio = float(se[-1] / max(se[0], 1e-14))
    rmse_overlap = bool(np.nanmax(rmse_low) <= np.nanmin(rmse_high)) if np.isfinite(rmse_low).all() and np.isfinite(rmse_high).all() else False
    if se_monotone and observed_ratio <= min(0.90, expected_ratio * 1.45):
        status = "PRECISION_CONVERGED"
        reason = "Average Monte Carlo standard error declines with path count at a rate consistent with sampling precision."
    elif observed_ratio < 0.90:
        status = "IMPROVING_NON_MONOTONIC"
        reason = "Precision improves with additional paths, but not monotonically across all replicated grids."
    elif rmse_overlap:
        status = "INCONCLUSIVE_MC_NOISE"
        reason = "Price-RMSE intervals overlap and the standard-error decline is too small to distinguish from replication noise."
    else:
        status = "NOT_CONVERGED"
        reason = "Increasing path count does not deliver the expected reduction in Monte Carlo standard error."
    return table, {
        "status": status,
        "reason": reason,
        "expected_standard_error_ratio": expected_ratio,
        "observed_standard_error_ratio": observed_ratio,
        "raw_replications": raw,
    }


def _heston_bates_comparison(
    bates_distribution: pd.DataFrame,
    heston_simulation: Mapping[str, Any] | None,
    heston_fit_table: pd.DataFrame | None,
    spot: float,
    risk_free_rate: float,
) -> pd.DataFrame:
    if not heston_simulation or heston_fit_table is None or heston_fit_table.empty:
        return pd.DataFrame()
    heston_rows: list[dict[str, Any]] = []
    carry = heston_fit_table.groupby("dte", as_index=False).agg(
        time_to_expiry=("time_to_expiry", "median"),
        effective_q=("effective_q", "median"),
    ).set_index("dte")
    for dte, terminal in sorted(heston_simulation["terminal_spot"].items()):
        metrics = _terminal_risk_metrics(np.asarray(terminal, dtype=float), spot)
        t = float(carry.loc[dte, "time_to_expiry"]) if dte in carry.index else dte / 365.0
        q = float(carry.loc[dte, "effective_q"]) if dte in carry.index else float(heston_fit_table["effective_q"].median())
        forward = spot * math.exp((risk_free_rate - q) * t)
        heston_rows.append({"dte": int(dte), "heston_forward": forward, **{f"heston_{k}": v for k, v in metrics.items()}})
    heston = pd.DataFrame(heston_rows)
    if heston.empty or bates_distribution.empty:
        return pd.DataFrame()
    bates_columns = [
        "dte",
        "terminal_mean",
        "mean_return",
        "median_return",
        "var_5",
        "es_5",
        "var_1",
        "es_1",
        "prob_below_spot",
        "skewness",
        "excess_kurtosis",
    ]
    merged = bates_distribution[bates_columns].rename(columns={c: f"bates_{c}" for c in bates_columns if c != "dte"}).merge(heston, on="dte", how="inner")
    for metric in ("mean_return", "median_return", "var_5", "es_5", "var_1", "es_1", "prob_below_spot", "skewness", "excess_kurtosis"):
        merged[f"delta_{metric}"] = merged[f"bates_{metric}"] - merged[f"heston_{metric}"]
    return merged


def build_bates_q_simulation(
    bates_calibration_result: Mapping[str, Any],
    heston_calibration_result: Mapping[str, Any] | None = None,
    paths: int = 10_000,
    steps_per_year: int = 365,
    scheme: str = "Andersen QE-M",
    seed: int = 42,
    antithetic: bool = True,
    martingale_correction: bool = True,
    confidence_level: float = 0.95,
    sample_paths: int = 40,
    time_convergence_check: bool = True,
    convergence_paths: int = 5_000,
    convergence_replications: int = 3,
    path_convergence_check: bool = True,
    path_convergence_base_paths: int = 5_000,
    path_convergence_replications: int = 3,
    simulate_heston_benchmark: bool = True,
) -> dict[str, Any]:
    if not isinstance(bates_calibration_result, Mapping) or not bates_calibration_result.get("ok"):
        return {"ok": False, "status": "FAILED", "reason": "A completed PASS/WARNING Bates calibration is required."}
    try:
        parameters = _parameters_from_bates_calibration(bates_calibration_result)
        fit_table = _fit_table_from_bates_calibration(bates_calibration_result)
        spot = float(bates_calibration_result["spot"])
        risk_free_rate = float(bates_calibration_result["risk_free_rate"])
        scheme = _normalize_scheme(scheme)
    except Exception as exc:
        return {"ok": False, "status": "FAILED", "reason": str(exc)}
    if scheme == "Andersen QE-M" and not bool(martingale_correction):
        scheme = "Andersen QE (uncorrected)"
    if scheme != "Andersen QE-M":
        martingale_correction = False

    settings = BatesSimulationSettings(
        paths=int(paths),
        steps_per_year=int(steps_per_year),
        scheme=str(scheme),
        seed=int(seed),
        antithetic=bool(antithetic),
        martingale_correction=bool(martingale_correction),
        confidence_level=float(confidence_level),
        sample_paths=int(sample_paths),
        time_convergence_check=bool(time_convergence_check),
        convergence_paths=int(convergence_paths),
        convergence_replications=max(int(convergence_replications), 1),
        path_convergence_check=bool(path_convergence_check),
        path_convergence_base_paths=int(path_convergence_base_paths),
        path_convergence_replications=max(int(path_convergence_replications), 1),
        simulate_heston_benchmark=bool(simulate_heston_benchmark),
    )

    source_champion_status = str(bates_calibration_result.get("champion_status", "UNKNOWN"))
    source_champion_reason = _source_champion_reason(bates_calibration_result)

    try:
        simulation = _simulate_bates_core(
            spot=spot,
            risk_free_rate=risk_free_rate,
            parameters=parameters,
            fit_table=fit_table,
            paths=settings.paths,
            steps_per_year=settings.steps_per_year,
            scheme=settings.scheme,
            seed=settings.seed,
            antithetic=settings.antithetic,
            martingale_correction=settings.martingale_correction,
            sample_paths=settings.sample_paths,
        )
        simulation["jump_intensity"] = parameters.jump_intensity
        distribution, jump_summary, jump_attribution = _distribution_summaries(
            simulation,
            fit_table,
            spot,
            risk_free_rate,
            settings.confidence_level,
        )
        pricing_table, pricing_summary, maturity_validation, bucket_validation = _pricing_validation(
            fit_table,
            simulation,
            spot,
            risk_free_rate,
            settings.confidence_level,
        )
        if settings.time_convergence_check:
            time_convergence, time_convergence_diagnostic = _time_convergence_table(spot, risk_free_rate, parameters, fit_table, settings)
        else:
            time_convergence = pd.DataFrame()
            time_convergence_diagnostic = {"status": "NOT_RUN", "reason": "Time-step convergence was disabled."}
        if settings.path_convergence_check:
            path_convergence, path_convergence_diagnostic = _path_convergence_table(spot, risk_free_rate, parameters, fit_table, settings)
        else:
            path_convergence = pd.DataFrame()
            path_convergence_diagnostic = {"status": "NOT_RUN", "reason": "Path-count convergence was disabled."}
    except Exception as exc:
        return {"ok": False, "status": "FAILED", "reason": str(exc)}

    heston_simulation = None
    heston_fit_table = None
    heston_benchmark_error = None
    if settings.simulate_heston_benchmark:
        if not isinstance(heston_calibration_result, Mapping) or not heston_calibration_result.get("ok"):
            heston_benchmark_error = "A completed Heston calibration was unavailable; benchmark simulation was skipped."
        else:
            try:
                if bates_calibration_result.get("heston_signature") and bates_calibration_result.get("heston_signature") != heston_calibration_result.get("configuration_signature"):
                    heston_benchmark_error = "The Heston calibration signature does not match the Bates source calibration."
                heston_parameters = _parameters_from_calibration(heston_calibration_result)
                heston_fit_table = _fit_table_from_calibration(heston_calibration_result)
                heston_simulation = _simulate_heston_core(
                    spot=spot,
                    risk_free_rate=risk_free_rate,
                    parameters=heston_parameters,
                    fit_table=heston_fit_table,
                    paths=settings.paths,
                    steps_per_year=settings.steps_per_year,
                    scheme=settings.scheme,
                    seed=settings.seed,
                    antithetic=settings.antithetic,
                    martingale_correction=settings.martingale_correction,
                    sample_paths=0,
                    requested_dtes=fit_table["dte"].astype(int).unique().tolist(),
                    record_curves=False,
                )
            except Exception as exc:
                heston_simulation = None
                heston_benchmark_error = f"Heston benchmark simulation failed: {exc}"
    comparison = _heston_bates_comparison(distribution, heston_simulation, heston_fit_table, spot, risk_free_rate)

    variance_diag = simulation["variance_diagnostics"]
    variance_mean_rmse = float(np.sqrt(np.mean((variance_diag["mean_variance"] - variance_diag["theoretical_mean_variance"]) ** 2))) if not variance_diag.empty else float("nan")
    variance_mean_relative_rmse = variance_mean_rmse / max(float(parameters.theta), 1e-12)
    significant_forward = distribution[
        distribution["forward_bias_statistically_significant"].astype(bool)
        & (distribution["forward_bias_bps"].abs() > 25.0)
    ] if not distribution.empty else pd.DataFrame()

    warnings: list[str] = []
    blockers: list[str] = []
    if settings.paths < 500:
        blockers.append("Fewer than 500 paths are insufficient for governed Bates Q simulation.")
    elif settings.paths < 5_000:
        warnings.append("Fewer than 5,000 paths provide limited precision for jump-tail and option-pricing diagnostics.")
    if settings.steps_per_year < 180:
        warnings.append("The time grid is coarse relative to the shortest option maturities.")
    if float(pricing_summary.get("price_rmse_pct_spot", np.inf)) > 0.005:
        blockers.append("Bates Monte Carlo versus Fourier price RMSE exceeds 0.50% of spot.")
    elif float(pricing_summary.get("price_rmse_pct_spot", np.inf)) > 0.002:
        warnings.append("Bates Monte Carlo versus Fourier price RMSE exceeds the preferred 0.20% of spot.")
    coverage = float(pricing_summary.get("confidence_coverage", np.nan))
    if np.isfinite(coverage):
        if coverage < 0.60:
            blockers.append("Fourier-price coverage by Bates Monte Carlo confidence intervals is below 60%.")
        elif coverage < 0.85:
            warnings.append("Fourier-price coverage by Bates Monte Carlo confidence intervals is below the preferred 85%.")
    if variance_mean_relative_rmse > 0.25:
        blockers.append("Simulated mean variance materially misses the Bates/Heston conditional variance expectation.")
    elif variance_mean_relative_rmse > 0.10:
        warnings.append("Simulated mean variance differs from the conditional variance expectation by more than 10% of theta.")
    if simulation["variance_zero_observation_rate"] > 0.20:
        warnings.append("The variance process spends more than 20% of simulated states at the numerical zero boundary.")
    if not significant_forward.empty:
        worst = significant_forward.iloc[np.argmax(significant_forward["forward_bias_bps"].abs().to_numpy(dtype=float))]
        message = (
            f"A forward bias is statistically significant at {int(worst['dte'])}D: "
            f"{float(worst['forward_bias_bps']):+.1f} bp (z={float(worst['forward_bias_z']):+.2f})."
        )
        if abs(float(worst["forward_bias_bps"])) > 75.0 and abs(float(worst["forward_bias_z"])) > 3.0:
            blockers.append(message)
        else:
            warnings.append(message)
    if not jump_summary.empty:
        jump_z_values = np.abs(jump_summary["jump_count_z"].to_numpy(dtype=float))
        finite_jump_z = jump_z_values[np.isfinite(jump_z_values)]
        if finite_jump_z.size and float(np.max(finite_jump_z)) > 3.5:
            warnings.append("Empirical Poisson jump counts differ from their expected intensity by more than 3.5 standard errors at one or more maturities.")
    time_status = str(time_convergence_diagnostic.get("status", "NOT_RUN"))
    if time_status == "NOT_CONVERGED":
        blockers.append("Bates time-step convergence failed after replication averaging.")
    elif time_status in {"INCONCLUSIVE_MC_NOISE", "IMPROVING_NON_MONOTONIC"}:
        warnings.append("Time-step convergence is " + time_status.replace("_", " ").lower() + ": " + str(time_convergence_diagnostic.get("reason", "")))
    path_status = str(path_convergence_diagnostic.get("status", "NOT_RUN"))
    if path_status == "NOT_CONVERGED":
        blockers.append("Bates path-count convergence failed to reduce Monte Carlo precision error.")
    elif path_status in {"INCONCLUSIVE_MC_NOISE", "IMPROVING_NON_MONOTONIC"}:
        warnings.append("Path-count convergence is " + path_status.replace("_", " ").lower() + ": " + str(path_convergence_diagnostic.get("reason", "")))
    if str(bates_calibration_result.get("status")) != "PASS":
        warnings.append(f"The source Bates calibration is {bates_calibration_result.get('status')}; simulation fidelity does not remove calibration model risk.")
    if source_champion_status != "BATES_CHAMPION":
        warnings.append(
            f"The source champion decision is {source_champion_status}; Bates simulation remains challenger/research output. "
            f"Reason: {source_champion_reason}"
        )
    if heston_benchmark_error:
        warnings.append(heston_benchmark_error)

    status = "INELIGIBLE" if blockers else ("WARNING" if warnings else "PASS")
    signature = _signature({
        "version": BATES_SIMULATION_VERSION,
        "bates_calibration_signature": bates_calibration_result.get("configuration_signature"),
        "heston_calibration_signature": (heston_calibration_result or {}).get("configuration_signature") if isinstance(heston_calibration_result, Mapping) else None,
        "settings": asdict(settings),
        "parameters": asdict(parameters),
    })

    terminal_samples = pd.DataFrame({str(dte): values for dte, values in simulation["terminal_spot"].items()})
    diffusion_terminal_samples = pd.DataFrame({str(dte): values for dte, values in simulation["terminal_diffusion_spot"].items()})
    jump_count_samples = pd.DataFrame({str(dte): values for dte, values in simulation["terminal_jump_count"].items()})
    heston_terminal_samples = pd.DataFrame({str(dte): values for dte, values in (heston_simulation or {}).get("terminal_spot", {}).items()})

    return {
        "ok": not bool(blockers),
        "status": status,
        "version": BATES_SIMULATION_VERSION,
        "configuration_signature": signature,
        "bates_calibration_signature": bates_calibration_result.get("configuration_signature"),
        "heston_calibration_signature": (heston_calibration_result or {}).get("configuration_signature") if isinstance(heston_calibration_result, Mapping) else None,
        "bates_champion_status": source_champion_status,
        "bates_champion_reason": source_champion_reason,
        "settings": asdict(settings),
        "parameters": asdict(parameters),
        "spot": spot,
        "risk_free_rate": risk_free_rate,
        "fit_table": fit_table,
        "distribution_summary": distribution,
        "jump_count_summary": jump_summary,
        "jump_attribution": jump_attribution,
        "heston_bates_comparison": comparison,
        "pricing_validation": pricing_table,
        "pricing_summary": pricing_summary,
        "maturity_validation": maturity_validation,
        "moneyness_validation": bucket_validation,
        "path_quantiles": simulation["path_quantiles"],
        "variance_diagnostics": variance_diag,
        "jump_diagnostics": simulation["jump_diagnostics"],
        "sample_spot_paths": simulation["sample_spot_paths"],
        "sample_diffusion_spot_paths": simulation["sample_diffusion_spot_paths"],
        "sample_variance_paths": simulation["sample_variance_paths"],
        "sample_jump_count_paths": simulation["sample_jump_count_paths"],
        "terminal_spot_samples": terminal_samples,
        "diffusion_only_terminal_samples": diffusion_terminal_samples,
        "jump_count_samples": jump_count_samples,
        "heston_terminal_samples": heston_terminal_samples,
        "carry_nodes": simulation["carry_nodes"],
        "time_convergence": time_convergence,
        "time_convergence_diagnostic": time_convergence_diagnostic,
        "time_convergence_replications_raw": time_convergence_diagnostic.get("raw_replications", pd.DataFrame()),
        "path_convergence": path_convergence,
        "path_convergence_diagnostic": path_convergence_diagnostic,
        "path_convergence_replications_raw": path_convergence_diagnostic.get("raw_replications", pd.DataFrame()),
        "variance_mean_rmse": variance_mean_rmse,
        "variance_mean_relative_rmse": variance_mean_relative_rmse,
        "variance_zero_observation_rate": simulation["variance_zero_observation_rate"],
        "max_abs_forward_bias_bps": simulation["max_abs_forward_bias_bps"],
        "max_abs_martingale_correction_bps": simulation["max_abs_martingale_correction_bps"],
        "rms_martingale_correction_bps": simulation["rms_martingale_correction_bps"],
        "mean_abs_martingale_correction_bps": simulation["mean_abs_martingale_correction_bps"],
        "martingale_method": simulation["martingale_method"],
        "jump_compensator": simulation["jump_compensator"],
        "warnings": list(dict.fromkeys(warnings)),
        "blockers": list(dict.fromkeys(blockers)),
        "governance": {
            "measure": "All Bates paths, jump intensities and terminal probabilities are generated under the risk-neutral Q measure.",
            "diffusion_scheme": "The stochastic-variance diffusion uses the selected Andersen QE-M/QE or full-truncation scheme.",
            "jump_scheme": "Compound-Poisson lognormal jumps are sampled exactly per step through a Poisson count and the conditional normal aggregate jump size.",
            "compensator": "The log-spot drift includes -lambda*(E[e^J]-1), preserving the risk-neutral martingale in expectation.",
            "common_random_numbers": "Heston and Bates benchmark paths reuse the same diffusion seed; the Bates jump stream is independent and separately seeded.",
            "attribution": "A Bates diffusion-only counterfactual uses identical Bates variance and diffusion drivers but removes jumps and their compensator.",
            "pricing_validation": "Monte Carlo prices are compared with Fourier Bates prices; this tests simulation fidelity, not the market calibration fit.",
            "iv_residual_interpretation": "Large implied-volatility residuals are interpreted jointly with price z-scores and Black--Scholes vega; low-vega amplification is labelled separately.",
            "source_model_role": f"Bates source decision: {source_champion_status}. {source_champion_reason}",
            "forward_test": "Forward bias is reported with a Monte Carlo standard error, confidence interval and z-score; raw basis-point bias is not interpreted without sampling uncertainty.",
            "convergence": "Time-step and path-count diagnostics are replication averaged and explicitly distinguish convergence from Monte Carlo-noise inconclusiveness.",
            "prohibition": "Bates Q jump frequency and probabilities are pricing quantities, not physical event forecasts, and do not enter the validated P-measure ensemble.",
        },
    }


__all__ = [
    "BATES_SIMULATION_VERSION",
    "BATES_SIMULATION_SCHEMES",
    "BatesSimulationSettings",
    "build_bates_q_simulation",
]
