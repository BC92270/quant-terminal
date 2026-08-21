from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.stats import kurtosis, norm, skew

from .heston_calibration import HestonParameters, heston_call_prices
from .options_risk_neutral import implied_volatility

HESTON_SIMULATION_VERSION = "HESTON-Q-SIMULATION-2.6.1A"
HESTON_SIMULATION_SCHEMES = (
    "Andersen QE-M",
    "Andersen QE (uncorrected)",
    "Full truncation Euler",
)
LEGACY_SCHEME_ALIASES = {
    "QE variance + log-Euler spot": "Andersen QE-M",
}


@dataclass(frozen=True)
class HestonSimulationSettings:
    paths: int = 10_000
    steps_per_year: int = 365
    scheme: str = "Andersen QE-M"
    seed: int = 42
    antithetic: bool = True
    martingale_correction: bool = True
    confidence_level: float = 0.95
    sample_paths: int = 40
    convergence_check: bool = True
    convergence_paths: int = 5_000
    convergence_replications: int = 3


def _signature(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(payload), sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16].upper()



def _normalize_scheme(scheme: str) -> str:
    normalized = LEGACY_SCHEME_ALIASES.get(str(scheme), str(scheme))
    if normalized not in HESTON_SIMULATION_SCHEMES:
        raise ValueError(f"Unsupported Heston simulation scheme: {scheme}")
    return normalized

def _parameters_from_calibration(calibration_result: Mapping[str, Any]) -> HestonParameters:
    values = calibration_result.get("parameters")
    if not isinstance(values, Mapping):
        raise ValueError("A completed Heston calibration with parameters is required.")
    return HestonParameters(
        kappa=float(values["kappa"]),
        theta=float(values["theta"]),
        sigma_v=float(values["sigma_v"]),
        rho=float(values["rho"]),
        v0=float(values["v0"]),
    )


def _fit_table_from_calibration(calibration_result: Mapping[str, Any]) -> pd.DataFrame:
    frame = calibration_result.get("fit_table")
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError("The Heston calibration fit table is unavailable.")
    required = {
        "dte",
        "time_to_expiry",
        "strike",
        "option_type",
        "effective_q",
        "target_price",
        "heston_price",
        "target_iv",
        "heston_iv",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Heston fit table missing columns: {sorted(missing)}")
    output = frame.copy().reset_index(drop=True)
    output["dte"] = pd.to_numeric(output["dte"], errors="coerce").round().astype("Int64")
    output = output.dropna(subset=["dte", "strike", "time_to_expiry", "effective_q"]).copy()
    output["dte"] = output["dte"].astype(int)
    return output


def _maturity_carry_nodes(fit_table: pd.DataFrame) -> pd.DataFrame:
    nodes = (
        fit_table.groupby("dte", as_index=False)
        .agg(time_to_expiry=("time_to_expiry", "median"), effective_q=("effective_q", "median"))
        .sort_values("time_to_expiry")
        .reset_index(drop=True)
    )
    nodes = pd.concat(
        [pd.DataFrame([{"dte": 0, "time_to_expiry": 0.0, "effective_q": float(nodes["effective_q"].iloc[0])}]), nodes],
        ignore_index=True,
    )
    nodes["cumulative_q"] = nodes["effective_q"] * nodes["time_to_expiry"]
    nodes.loc[0, "cumulative_q"] = 0.0
    return nodes


def _carry_schedule(fit_table: pd.DataFrame, max_time: float, steps: int) -> tuple[np.ndarray, np.ndarray, pd.DataFrame]:
    nodes = _maturity_carry_nodes(fit_table)
    time_grid = np.linspace(0.0, float(max_time), int(steps) + 1)
    node_t = nodes["time_to_expiry"].to_numpy(dtype=float)
    node_c = nodes["cumulative_q"].to_numpy(dtype=float)
    cumulative_q = np.interp(time_grid, node_t, node_c)
    if max_time > node_t[-1] and len(node_t) >= 2:
        last_slope = (node_c[-1] - node_c[-2]) / max(node_t[-1] - node_t[-2], 1e-12)
        beyond = time_grid > node_t[-1]
        cumulative_q[beyond] = node_c[-1] + last_slope * (time_grid[beyond] - node_t[-1])
    dt = np.diff(time_grid)
    q_step = np.diff(cumulative_q) / np.maximum(dt, 1e-12)
    return time_grid, q_step, nodes


def _antithetic_normals(rng: np.random.Generator, paths: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    half = (int(paths) + 1) // 2
    z1_half = rng.standard_normal(half)
    z2_half = rng.standard_normal(half)
    u_half = rng.random(half)
    z1 = np.concatenate([z1_half, -z1_half])[:paths]
    z2 = np.concatenate([z2_half, -z2_half])[:paths]
    u = np.concatenate([u_half, 1.0 - u_half])[:paths]
    return z1, z2, np.clip(u, 1e-12, 1.0 - 1e-12)


def _random_drivers(rng: np.random.Generator, paths: int, antithetic: bool) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if antithetic:
        return _antithetic_normals(rng, paths)
    return (
        rng.standard_normal(paths),
        rng.standard_normal(paths),
        np.clip(rng.random(paths), 1e-12, 1.0 - 1e-12),
    )


def _qe_variance_transition(
    variance: np.ndarray,
    dt: float,
    parameters: HestonParameters,
    z_var: np.ndarray,
    uniform: np.ndarray,
    psi_c: float = 1.5,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Andersen quadratic-exponential transition for the CIR variance process.

    The returned branch state is also used by the QE-M conditional moment correction.
    """
    kappa = max(float(parameters.kappa), 1e-12)
    theta = max(float(parameters.theta), 1e-12)
    sigma = max(float(parameters.sigma_v), 1e-12)
    v = np.maximum(np.asarray(variance, dtype=float), 0.0)
    exp_kdt = math.exp(-kappa * dt)
    m = theta + (v - theta) * exp_kdt
    s2 = (
        v * sigma * sigma * exp_kdt * (1.0 - exp_kdt) / kappa
        + theta * sigma * sigma * (1.0 - exp_kdt) ** 2 / (2.0 * kappa)
    )
    m = np.maximum(m, 1e-14)
    psi = np.maximum(s2 / np.maximum(m * m, 1e-28), 1e-14)
    output = np.empty_like(v)

    low = psi <= float(psi_c)
    a = np.full_like(v, np.nan)
    b2 = np.full_like(v, np.nan)
    p = np.full_like(v, np.nan)
    beta = np.full_like(v, np.nan)

    if np.any(low):
        psi_low = psi[low]
        two_over = 2.0 / psi_low
        b2_low = two_over - 1.0 + np.sqrt(np.maximum(two_over * (two_over - 1.0), 0.0))
        a_low = m[low] / (1.0 + b2_low)
        output[low] = a_low * (np.sqrt(np.maximum(b2_low, 0.0)) + z_var[low]) ** 2
        a[low] = a_low
        b2[low] = b2_low

    high = ~low
    if np.any(high):
        psi_high = psi[high]
        p_high = np.clip((psi_high - 1.0) / (psi_high + 1.0), 0.0, 1.0 - 1e-12)
        beta_high = (1.0 - p_high) / np.maximum(m[high], 1e-14)
        u = uniform[high]
        positive = u > p_high
        values = np.zeros(np.sum(high), dtype=float)
        values[positive] = np.log((1.0 - p_high[positive]) / np.maximum(1.0 - u[positive], 1e-14)) / np.maximum(beta_high[positive], 1e-14)
        output[high] = values
        p[high] = p_high
        beta[high] = beta_high

    state = {
        "low": low,
        "a": a,
        "b2": b2,
        "p": p,
        "beta": beta,
        "m": m,
        "psi": psi,
    }
    return np.maximum(output, 0.0), state


def _qe_log_spot_increment(
    v_prev: np.ndarray,
    v_next: np.ndarray,
    dt: float,
    risk_free_rate: float,
    q_rate: float,
    parameters: HestonParameters,
    z_independent: np.ndarray,
    transition_state: Mapping[str, np.ndarray],
    martingale_corrected: bool,
    gamma1: float = 0.5,
    gamma2: float = 0.5,
) -> tuple[np.ndarray, np.ndarray]:
    """Andersen QE spot update with optional analytic QE-M correction.

    Correlation is encoded through the variance endpoints and the K coefficients; the
    Gaussian driver supplied here must be independent of the variance transition.
    """
    kappa = max(float(parameters.kappa), 1e-12)
    theta = max(float(parameters.theta), 1e-12)
    sigma = max(float(parameters.sigma_v), 1e-12)
    rho = float(np.clip(parameters.rho, -0.999999, 0.999999))
    one_minus_rho2 = max(1.0 - rho * rho, 0.0)

    common = kappa * rho / sigma - 0.5
    k0 = -rho * kappa * theta * dt / sigma
    k1 = float(gamma1) * dt * common - rho / sigma
    k2 = float(gamma2) * dt * common + rho / sigma
    k3 = float(gamma1) * dt * one_minus_rho2
    k4 = float(gamma2) * dt * one_minus_rho2
    gaussian_variance = np.maximum(k3 * v_prev + k4 * v_next, 0.0)

    analytic_adjustment = np.zeros_like(v_prev)
    if martingale_corrected:
        a_mgf = k2 + 0.5 * k4
        low = np.asarray(transition_state["low"], dtype=bool)
        log_mgf = np.empty_like(v_prev)
        if np.any(low):
            a = np.asarray(transition_state["a"], dtype=float)[low]
            b2 = np.asarray(transition_state["b2"], dtype=float)[low]
            denominator = 1.0 - 2.0 * a_mgf * a
            if np.any(denominator <= 1e-12):
                raise FloatingPointError("QE-M quadratic-branch moment condition failed.")
            log_mgf[low] = -0.5 * np.log(denominator) + (a_mgf * a * b2) / denominator
        high = ~low
        if np.any(high):
            p = np.asarray(transition_state["p"], dtype=float)[high]
            beta = np.asarray(transition_state["beta"], dtype=float)[high]
            denominator = beta - a_mgf
            if np.any(denominator <= 1e-12):
                raise FloatingPointError("QE-M exponential-branch moment condition failed.")
            mgf = p + (1.0 - p) * beta / denominator
            if np.any(mgf <= 0.0) or not np.all(np.isfinite(mgf)):
                raise FloatingPointError("QE-M exponential-branch moment is invalid.")
            log_mgf[high] = np.log(mgf)

        k0_star = -(k1 + 0.5 * k3) * v_prev - log_mgf
        analytic_adjustment = k0_star - k0
        constant_term = k0_star
    else:
        constant_term = np.full_like(v_prev, k0)

    increment = (
        (float(risk_free_rate) - float(q_rate)) * dt
        + constant_term
        + k1 * v_prev
        + k2 * v_next
        + np.sqrt(gaussian_variance) * z_independent
    )
    return increment, analytic_adjustment

def _simulate_core(
    spot: float,
    risk_free_rate: float,
    parameters: HestonParameters,
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
    max_dte = int(max(requested_dtes or fit_table["dte"].unique()))
    max_time = max_dte / 365.0
    steps = max(int(math.ceil(max_time * int(steps_per_year))), 1)
    time_grid, q_step, carry_nodes = _carry_schedule(fit_table, max_time, steps)
    dt_grid = np.diff(time_grid)
    dte_to_step = {
        int(dte): int(np.clip(round((int(dte) / 365.0) / max_time * steps), 1, steps))
        for dte in sorted(set(int(value) for value in (requested_dtes or fit_table["dte"].unique())))
        if int(dte) <= max_dte
    }
    step_to_dtes: dict[int, list[int]] = {}
    for dte, index in dte_to_step.items():
        step_to_dtes.setdefault(index, []).append(dte)

    rng = np.random.default_rng(int(seed))
    log_spot = np.full(paths, math.log(float(spot)), dtype=float)
    variance = np.full(paths, max(float(parameters.v0), 0.0), dtype=float)
    sample_count = int(np.clip(sample_paths, 0, paths))
    sample_spot = np.empty((sample_count, steps + 1), dtype=float) if sample_count else np.empty((0, steps + 1), dtype=float)
    sample_variance = np.empty((sample_count, steps + 1), dtype=float) if sample_count else np.empty((0, steps + 1), dtype=float)
    if sample_count:
        sample_spot[:, 0] = float(spot)
        sample_variance[:, 0] = variance[:sample_count]

    quantile_levels = np.asarray([0.05, 0.25, 0.50, 0.75, 0.95], dtype=float)
    spot_quantiles = np.empty((steps + 1, len(quantile_levels)), dtype=float) if record_curves else np.empty((0, 0), dtype=float)
    variance_quantiles = np.empty_like(spot_quantiles) if record_curves else np.empty((0, 0), dtype=float)
    mean_spot = np.empty(steps + 1, dtype=float) if record_curves else np.empty(0, dtype=float)
    mean_variance = np.empty(steps + 1, dtype=float) if record_curves else np.empty(0, dtype=float)
    theoretical_variance = np.empty(steps + 1, dtype=float) if record_curves else np.empty(0, dtype=float)
    zero_fraction = np.empty(steps + 1, dtype=float) if record_curves else np.empty(0, dtype=float)
    forward_target = np.empty(steps + 1, dtype=float) if record_curves else np.empty(0, dtype=float)
    pre_correction_bias_bps = np.empty(steps + 1, dtype=float) if record_curves else np.empty(0, dtype=float)
    correction_bps = np.empty(steps + 1, dtype=float) if record_curves else np.empty(0, dtype=float)

    if record_curves:
        spot_quantiles[0] = float(spot)
        variance_quantiles[0] = float(parameters.v0)
        mean_spot[0] = float(spot)
        mean_variance[0] = float(parameters.v0)
        theoretical_variance[0] = float(parameters.v0)
        zero_fraction[0] = float(parameters.v0 <= 1e-10)
        forward_target[0] = float(spot)
        pre_correction_bias_bps[0] = 0.0
        correction_bps[0] = 0.0

    terminal_spot: dict[int, np.ndarray] = {}
    terminal_variance: dict[int, np.ndarray] = {}
    cumulative_q = 0.0
    max_abs_forward_bias = 0.0
    max_abs_analytic_adjustment = 0.0
    sum_sq_analytic_adjustment = 0.0
    mean_abs_analytic_adjustment = 0.0
    analytic_adjustment_observations = 0
    zero_observations = 0

    rho = float(np.clip(parameters.rho, -0.999999, 0.999999))
    rho_perp = math.sqrt(max(1.0 - rho * rho, 0.0))
    use_qe = scheme in {"Andersen QE-M", "Andersen QE (uncorrected)"}
    use_qe_m = scheme == "Andersen QE-M" and bool(martingale_correction)

    for step in range(1, steps + 1):
        dt = float(dt_grid[step - 1])
        q_rate = float(q_step[step - 1])
        cumulative_q += q_rate * dt
        z_var, z_independent, uniform = _random_drivers(rng, paths, antithetic)
        v_prev = np.maximum(variance, 0.0)

        if use_qe:
            variance_next, transition_state = _qe_variance_transition(v_prev, dt, parameters, z_var, uniform)
            increment, analytic_adjustment = _qe_log_spot_increment(
                v_prev=v_prev,
                v_next=variance_next,
                dt=dt,
                risk_free_rate=float(risk_free_rate),
                q_rate=q_rate,
                parameters=parameters,
                z_independent=z_independent,
                transition_state=transition_state,
                martingale_corrected=use_qe_m,
            )
            log_spot = log_spot + increment
            if use_qe_m:
                adjustment_bps = analytic_adjustment * 10_000.0
                max_abs_analytic_adjustment = max(max_abs_analytic_adjustment, float(np.max(np.abs(adjustment_bps))))
                sum_sq_analytic_adjustment += float(np.sum(adjustment_bps * adjustment_bps))
                mean_abs_analytic_adjustment += float(np.sum(np.abs(adjustment_bps)))
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
            log_spot = log_spot + (float(risk_free_rate) - q_rate) * dt - 0.5 * integrated_variance + np.sqrt(integrated_variance) * z_spot

        current_spot = np.exp(np.clip(log_spot, -50.0, 50.0))
        target_forward = float(spot) * math.exp(float(risk_free_rate) * time_grid[step] - cumulative_q)
        sample_mean = float(np.mean(current_spot))
        bias_bps = (sample_mean / max(target_forward, 1e-14) - 1.0) * 10_000.0
        max_abs_forward_bias = max(max_abs_forward_bias, abs(bias_bps))

        variance = variance_next
        zero_observations += int(np.sum(variance <= 1e-10))
        if sample_count:
            sample_spot[:, step] = current_spot[:sample_count]
            sample_variance[:, step] = variance[:sample_count]
        if record_curves:
            spot_quantiles[step] = np.quantile(current_spot, quantile_levels)
            variance_quantiles[step] = np.quantile(variance, quantile_levels)
            mean_spot[step] = sample_mean
            mean_variance[step] = float(np.mean(variance))
            theoretical_variance[step] = float(parameters.theta + (parameters.v0 - parameters.theta) * math.exp(-parameters.kappa * time_grid[step]))
            zero_fraction[step] = float(np.mean(variance <= 1e-10))
            forward_target[step] = target_forward
            pre_correction_bias_bps[step] = bias_bps
            correction_bps[step] = 0.0
        if step in step_to_dtes:
            for dte in step_to_dtes[step]:
                terminal_spot[int(dte)] = current_spot.copy()
                terminal_variance[int(dte)] = variance.copy()

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
            "forward_target": forward_target,
            "pre_correction_bias_bps": pre_correction_bias_bps,
            "martingale_correction_bps": correction_bps,
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
    else:
        path_quantiles = pd.DataFrame()
        variance_diagnostics = pd.DataFrame()

    return {
        "terminal_spot": terminal_spot,
        "terminal_variance": terminal_variance,
        "dte_to_step": dte_to_step,
        "time_grid": time_grid,
        "carry_nodes": carry_nodes,
        "path_quantiles": path_quantiles,
        "variance_diagnostics": variance_diagnostics,
        "sample_spot_paths": sample_spot,
        "sample_variance_paths": sample_variance,
        "max_abs_pre_correction_forward_bias_bps": float(max_abs_forward_bias),
        "max_abs_post_correction_forward_bias_bps": float(max_abs_forward_bias),
        "total_abs_martingale_correction_bps": float(mean_abs_analytic_adjustment),
        "max_abs_martingale_correction_bps": float(max_abs_analytic_adjustment),
        "rms_martingale_correction_bps": float(math.sqrt(sum_sq_analytic_adjustment / max(analytic_adjustment_observations, 1))),
        "mean_abs_martingale_correction_bps": float(mean_abs_analytic_adjustment / max(analytic_adjustment_observations, 1)),
        "martingale_method": "Andersen analytic QE-M" if use_qe_m else "None",
        "variance_zero_observation_rate": float(zero_observations / max(paths * steps, 1)),
        "steps": steps,
        "paths": paths,
    }


def _expected_shortfall(values: np.ndarray, alpha: float) -> tuple[float, float]:
    values = np.asarray(values, dtype=float)
    var = float(np.quantile(values, alpha))
    tail = values[values <= var]
    return var, float(np.mean(tail)) if len(tail) else var


def _distribution_summaries(
    simulation: Mapping[str, Any],
    fit_table: pd.DataFrame,
    spot: float,
    risk_free_rate: float,
) -> pd.DataFrame:
    carry = _maturity_carry_nodes(fit_table).set_index("dte")
    rows = []
    for dte, terminal in sorted(simulation["terminal_spot"].items()):
        terminal = np.asarray(terminal, dtype=float)
        returns = terminal / float(spot) - 1.0
        variance = np.asarray(simulation["terminal_variance"][dte], dtype=float)
        t = dte / 365.0
        q = float(carry.loc[dte, "effective_q"]) if dte in carry.index else float(fit_table["effective_q"].median())
        forward = float(spot) * math.exp((float(risk_free_rate) - q) * t)
        var5, es5 = _expected_shortfall(returns, 0.05)
        var1, es1 = _expected_shortfall(returns, 0.01)
        rows.append({
            "dte": int(dte),
            "time_to_expiry": t,
            "effective_q": q,
            "forward_target": forward,
            "terminal_mean": float(np.mean(terminal)),
            "forward_bias_bps": float((np.mean(terminal) / forward - 1.0) * 10_000.0),
            "mean_return": float(np.mean(returns)),
            "median_return": float(np.median(returns)),
            "var_5": var5,
            "es_5": es5,
            "var_1": var1,
            "es_1": es1,
            "prob_below_spot": float(np.mean(terminal < spot)),
            "skewness": float(skew(returns, bias=False)),
            "excess_kurtosis": float(kurtosis(returns, fisher=True, bias=False)),
            "terminal_variance_mean": float(np.mean(variance)),
            "terminal_variance_p05": float(np.quantile(variance, 0.05)),
            "terminal_variance_p95": float(np.quantile(variance, 0.95)),
            "terminal_variance_zero_fraction": float(np.mean(variance <= 1e-10)),
        })
    return pd.DataFrame(rows)


def _pricing_validation(
    fit_table: pd.DataFrame,
    simulation: Mapping[str, Any],
    spot: float,
    risk_free_rate: float,
    confidence_level: float,
) -> tuple[pd.DataFrame, dict[str, float], pd.DataFrame, pd.DataFrame]:
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
        discount = math.exp(-float(risk_free_rate) * float(row.time_to_expiry))
        discounted = discount * payoff
        mc_price = float(np.mean(discounted))
        mc_se = float(np.std(discounted, ddof=1) / math.sqrt(len(discounted))) if len(discounted) > 1 else float("nan")
        fourier_price = float(row.heston_price)
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
        fourier_iv = float(row.heston_iv)
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
        })
    table = pd.DataFrame(rows)
    valid_price = table[np.isfinite(table["mc_fourier_price_error"])].copy()
    valid_iv = table[np.isfinite(table["mc_fourier_iv_error"])].copy()
    summary = {
        "count": int(len(table)),
        "price_rmse": float(np.sqrt(np.mean(valid_price["mc_fourier_price_error"] ** 2))) if len(valid_price) else float("nan"),
        "price_rmse_pct_spot": float(np.sqrt(np.mean(valid_price["mc_fourier_price_error"] ** 2)) / spot) if len(valid_price) else float("nan"),
        "mean_abs_price_error": float(np.mean(np.abs(valid_price["mc_fourier_price_error"]))) if len(valid_price) else float("nan"),
        "iv_rmse": float(np.sqrt(np.mean(valid_iv["mc_fourier_iv_error"] ** 2))) if len(valid_iv) else float("nan"),
        "target_iv_rmse": float(np.sqrt(np.mean(table.loc[np.isfinite(table["mc_target_iv_error"]), "mc_target_iv_error"] ** 2))) if np.isfinite(table["mc_target_iv_error"]).any() else float("nan"),
        "confidence_coverage": float(np.mean(table["fourier_inside_mc_ci"])) if len(table) else float("nan"),
        "median_abs_z_score": float(np.nanmedian(np.abs(table["mc_fourier_z_score"]))) if len(table) else float("nan"),
        "p95_abs_z_score": float(np.nanquantile(np.abs(table["mc_fourier_z_score"]), 0.95)) if np.isfinite(table["mc_fourier_z_score"]).any() else float("nan"),
    }
    maturity = (
        table.groupby(["sample_role", "expiration", "dte"], dropna=False)
        .agg(
            count=("strike", "size"),
            price_rmse=("mc_fourier_price_error", lambda x: float(np.sqrt(np.nanmean(np.asarray(x, dtype=float) ** 2)))),
            iv_rmse=("mc_fourier_iv_error", lambda x: float(np.sqrt(np.nanmean(np.asarray(x, dtype=float) ** 2)))),
            coverage=("fourier_inside_mc_ci", "mean"),
            mean_abs_z=("mc_fourier_z_score", lambda x: float(np.nanmean(np.abs(np.asarray(x, dtype=float))))),
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
        )
        .reset_index()
    )
    return table, summary, maturity, bucket


def _representative_quotes(fit_table: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for dte, group in fit_table.groupby("dte"):
        selected = group.iloc[np.argmin(np.abs(group["log_moneyness"].to_numpy(dtype=float)))]
        rows.append(selected)
    return pd.DataFrame(rows).reset_index(drop=True)


def _convergence_table(
    spot: float,
    risk_free_rate: float,
    parameters: HestonParameters,
    fit_table: pd.DataFrame,
    settings: HestonSimulationSettings,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    representative = _representative_quotes(fit_table)
    step_sets = sorted(set([max(91, settings.steps_per_year // 2), settings.steps_per_year, min(730, settings.steps_per_year * 2)]))
    replication_rows: list[dict[str, Any]] = []
    for replication in range(max(int(settings.convergence_replications), 1)):
        # The same replication seed is reused across time grids. This is not an exact
        # Brownian bridge coupling, but it materially reduces gratuitous seed noise.
        replication_seed = int(settings.seed) + replication * 100_003
        for steps_per_year in step_sets:
            sim = _simulate_core(
                spot=spot,
                risk_free_rate=risk_free_rate,
                parameters=parameters,
                fit_table=fit_table,
                paths=max(int(settings.convergence_paths), 500),
                steps_per_year=int(steps_per_year),
                scheme=settings.scheme,
                seed=replication_seed,
                antithetic=bool(settings.antithetic),
                martingale_correction=bool(settings.martingale_correction),
                sample_paths=0,
                requested_dtes=representative["dte"].astype(int).tolist(),
                record_curves=False,
            )
            errors = []
            ses = []
            forward_biases = []
            for quote in representative.itertuples(index=False):
                terminal = np.asarray(sim["terminal_spot"][int(quote.dte)], dtype=float)
                payoff = np.maximum(terminal - float(quote.strike), 0.0) if str(quote.option_type).lower() == "call" else np.maximum(float(quote.strike) - terminal, 0.0)
                discounted = math.exp(-risk_free_rate * float(quote.time_to_expiry)) * payoff
                price = float(np.mean(discounted))
                se = float(np.std(discounted, ddof=1) / math.sqrt(len(discounted)))
                errors.append(price - float(quote.heston_price))
                ses.append(se)
                q = float(quote.effective_q)
                forward = spot * math.exp((risk_free_rate - q) * float(quote.time_to_expiry))
                forward_biases.append((np.mean(terminal) / forward - 1.0) * 10_000.0)
            errors_arr = np.asarray(errors, dtype=float)
            replication_rows.append({
                "replication": int(replication + 1),
                "steps_per_year": int(steps_per_year),
                "paths": int(sim["paths"]),
                "max_steps": int(sim["steps"]),
                "representative_quotes": int(len(representative)),
                "price_rmse": float(np.sqrt(np.mean(errors_arr ** 2))),
                "mean_mc_standard_error": float(np.mean(ses)),
                "max_abs_forward_bias_bps": float(np.max(np.abs(forward_biases))),
                "max_abs_pre_correction_forward_bias_bps": float(sim["max_abs_pre_correction_forward_bias_bps"]),
            })

    raw = pd.DataFrame(replication_rows)
    rows: list[dict[str, Any]] = []
    zcrit = 1.96
    for steps_per_year, group in raw.groupby("steps_per_year", sort=True):
        n = max(len(group), 1)
        mean_rmse = float(group["price_rmse"].mean())
        sd_rmse = float(group["price_rmse"].std(ddof=1)) if len(group) > 1 else 0.0
        half_width = zcrit * sd_rmse / math.sqrt(n) if n > 1 else float("nan")
        rows.append({
            "steps_per_year": int(steps_per_year),
            "paths_per_replication": int(group["paths"].iloc[0]),
            "replications": int(n),
            "max_steps": int(group["max_steps"].max()),
            "representative_quotes": int(group["representative_quotes"].iloc[0]),
            "price_rmse_mean": mean_rmse,
            "price_rmse_sd": sd_rmse,
            "price_rmse_ci_low": max(mean_rmse - half_width, 0.0) if np.isfinite(half_width) else float("nan"),
            "price_rmse_ci_high": mean_rmse + half_width if np.isfinite(half_width) else float("nan"),
            "mean_mc_standard_error": float(group["mean_mc_standard_error"].mean()),
            "max_abs_forward_bias_bps_mean": float(group["max_abs_forward_bias_bps"].mean()),
            "max_abs_forward_bias_bps_max": float(group["max_abs_forward_bias_bps"].max()),
            "max_abs_pre_correction_forward_bias_bps_mean": float(group["max_abs_pre_correction_forward_bias_bps"].mean()),
        })
    table = pd.DataFrame(rows).sort_values("steps_per_year").reset_index(drop=True)
    if table.empty:
        return table, {"status": "NOT_RUN", "reason": "No convergence rows were produced."}

    means = table["price_rmse_mean"].to_numpy(dtype=float)
    ci_low = table["price_rmse_ci_low"].to_numpy(dtype=float)
    ci_high = table["price_rmse_ci_high"].to_numpy(dtype=float)
    finest = float(means[-1])
    coarsest = float(means[0])
    monotone = bool(np.all(np.diff(means) <= 0.0))
    intervals_overlap = bool(np.nanmax(ci_low) <= np.nanmin(ci_high)) if np.isfinite(ci_low).all() and np.isfinite(ci_high).all() else False
    if intervals_overlap:
        status = "INCONCLUSIVE_MC_NOISE"
        reason = "RMSE confidence intervals overlap across all tested time grids; Monte Carlo noise dominates the observed differences."
    elif monotone and finest < coarsest:
        status = "CONVERGED"
        reason = "Pricing RMSE declines monotonically as the time grid is refined."
    elif finest < 0.90 * coarsest:
        status = "IMPROVING_NON_MONOTONIC"
        reason = "The finest grid improves materially on the coarsest grid, but the sequence is not monotone."
    else:
        status = "NOT_CONVERGED"
        reason = "The finest grid does not improve materially on the coarsest grid after replication averaging."
    diagnostic = {
        "status": status,
        "reason": reason,
        "coarsest_rmse": coarsest,
        "finest_rmse": finest,
        "relative_change": float(finest / max(coarsest, 1e-14) - 1.0),
        "monotone": monotone,
        "replications": int(settings.convergence_replications),
        "raw_replications": raw,
    }
    return table, diagnostic

def build_heston_q_simulation(
    calibration_result: Mapping[str, Any],
    paths: int = 10_000,
    steps_per_year: int = 365,
    scheme: str = "Andersen QE-M",
    seed: int = 42,
    antithetic: bool = True,
    martingale_correction: bool = True,
    confidence_level: float = 0.95,
    sample_paths: int = 40,
    convergence_check: bool = True,
    convergence_paths: int = 5_000,
    convergence_replications: int = 3,
) -> dict[str, Any]:
    if not isinstance(calibration_result, Mapping) or not calibration_result.get("ok"):
        return {"ok": False, "status": "FAILED", "reason": "A completed PASS/WARNING Heston calibration is required."}
    try:
        parameters = _parameters_from_calibration(calibration_result)
        fit_table = _fit_table_from_calibration(calibration_result)
        spot = float(calibration_result["spot"])
        risk_free_rate = float(calibration_result["risk_free_rate"])
    except Exception as exc:
        return {"ok": False, "status": "FAILED", "reason": str(exc)}
    try:
        scheme = _normalize_scheme(scheme)
    except Exception as exc:
        return {"ok": False, "status": "FAILED", "reason": str(exc)}
    if scheme == "Andersen QE-M" and not bool(martingale_correction):
        scheme = "Andersen QE (uncorrected)"
    if scheme != "Andersen QE-M":
        martingale_correction = False

    settings = HestonSimulationSettings(
        paths=int(paths),
        steps_per_year=int(steps_per_year),
        scheme=str(scheme),
        seed=int(seed),
        antithetic=bool(antithetic),
        martingale_correction=bool(martingale_correction),
        confidence_level=float(confidence_level),
        sample_paths=int(sample_paths),
        convergence_check=bool(convergence_check),
        convergence_paths=int(convergence_paths),
        convergence_replications=max(int(convergence_replications), 1),
    )
    try:
        simulation = _simulate_core(
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
        distribution = _distribution_summaries(simulation, fit_table, spot, risk_free_rate)
        pricing_table, pricing_summary, maturity_validation, bucket_validation = _pricing_validation(
            fit_table,
            simulation,
            spot,
            risk_free_rate,
            settings.confidence_level,
        )
        if settings.convergence_check:
            convergence, convergence_diagnostic = _convergence_table(spot, risk_free_rate, parameters, fit_table, settings)
        else:
            convergence = pd.DataFrame()
            convergence_diagnostic = {"status": "NOT_RUN", "reason": "Time-step convergence was disabled."}
    except Exception as exc:
        return {"ok": False, "status": "FAILED", "reason": str(exc)}

    variance_diag = simulation["variance_diagnostics"]
    variance_mean_rmse = float(np.sqrt(np.mean((variance_diag["mean_variance"] - variance_diag["theoretical_mean_variance"]) ** 2))) if not variance_diag.empty else float("nan")
    variance_mean_relative_rmse = variance_mean_rmse / max(float(parameters.theta), 1e-12)

    warnings: list[str] = []
    blockers: list[str] = []
    if settings.paths < 500:
        blockers.append("Fewer than 500 paths are insufficient for governed Heston Q simulation.")
    elif settings.paths < 5_000:
        warnings.append("Fewer than 5,000 paths provide limited precision for tail and option-pricing diagnostics.")
    if settings.steps_per_year < 180:
        warnings.append("The time grid is coarse relative to the shortest option maturities.")
    if float(pricing_summary.get("price_rmse_pct_spot", np.inf)) > 0.005:
        blockers.append("Monte Carlo versus Fourier price RMSE exceeds 0.50% of spot.")
    elif float(pricing_summary.get("price_rmse_pct_spot", np.inf)) > 0.002:
        warnings.append("Monte Carlo versus Fourier price RMSE exceeds the preferred 0.20% of spot.")
    coverage = float(pricing_summary.get("confidence_coverage", np.nan))
    if np.isfinite(coverage):
        if coverage < 0.60:
            blockers.append("Fourier-price coverage by Monte Carlo confidence intervals is below 60%.")
        elif coverage < 0.85:
            warnings.append("Fourier-price coverage by Monte Carlo confidence intervals is below the preferred 85%.")
    if variance_mean_relative_rmse > 0.25:
        blockers.append("Simulated mean variance materially misses the Heston conditional expectation.")
    elif variance_mean_relative_rmse > 0.10:
        warnings.append("Simulated mean variance differs from the Heston conditional expectation by more than 10% of theta.")
    if simulation["variance_zero_observation_rate"] > 0.20:
        warnings.append("The variance process spends more than 20% of simulated states at the numerical zero boundary.")
    if simulation["max_abs_pre_correction_forward_bias_bps"] > 100.0:
        warnings.append("Sample forward means deviate from the governed forward curve by more than 100 bp at one or more monitoring dates.")
    if simulation.get("martingale_method") == "Andersen analytic QE-M" and simulation["max_abs_martingale_correction_bps"] > 250.0:
        warnings.append("The analytic QE-M log-moment adjustment is unusually large; inspect the calibrated variance regime and time grid.")
    convergence_status = str(convergence_diagnostic.get("status", "NOT_RUN"))
    if convergence_status == "NOT_CONVERGED":
        blockers.append("Time-step convergence failed after replication averaging.")
    elif convergence_status in {"INCONCLUSIVE_MC_NOISE", "IMPROVING_NON_MONOTONIC"}:
        warnings.append("Time-step convergence is " + convergence_status.replace("_", " ").lower() + ": " + str(convergence_diagnostic.get("reason", "")))
    if str(calibration_result.get("status")) != "PASS":
        warnings.append(f"The source Heston calibration is {calibration_result.get('status')}; simulation fidelity does not remove calibration model risk.")
    local_summary = calibration_result.get("local_error_summary", {})
    if float(local_summary.get("worst_cell_mean_abs_iv_error", 0.0) or 0.0) > 0.04:
        warnings.append("The calibrated continuous Heston model retains a material local IV miss; Bates remains the required jump challenger.")

    status = "INELIGIBLE" if blockers else ("WARNING" if warnings else "PASS")
    signature = _signature({
        "version": HESTON_SIMULATION_VERSION,
        "calibration_signature": calibration_result.get("configuration_signature"),
        "settings": asdict(settings),
        "parameters": asdict(parameters),
    })
    terminal_samples = pd.DataFrame({str(dte): values for dte, values in simulation["terminal_spot"].items()})
    variance_terminal_samples = pd.DataFrame({str(dte): values for dte, values in simulation["terminal_variance"].items()})
    return {
        "ok": not bool(blockers),
        "status": status,
        "version": HESTON_SIMULATION_VERSION,
        "configuration_signature": signature,
        "calibration_signature": calibration_result.get("configuration_signature"),
        "calibration_status": calibration_result.get("status"),
        "settings": asdict(settings),
        "parameters": asdict(parameters),
        "spot": spot,
        "risk_free_rate": risk_free_rate,
        "fit_table": fit_table,
        "distribution_summary": distribution,
        "pricing_validation": pricing_table,
        "pricing_summary": pricing_summary,
        "maturity_validation": maturity_validation,
        "moneyness_validation": bucket_validation,
        "path_quantiles": simulation["path_quantiles"],
        "variance_diagnostics": variance_diag,
        "sample_spot_paths": simulation["sample_spot_paths"],
        "sample_variance_paths": simulation["sample_variance_paths"],
        "terminal_spot_samples": terminal_samples,
        "terminal_variance_samples": variance_terminal_samples,
        "carry_nodes": simulation["carry_nodes"],
        "convergence": convergence,
        "convergence_diagnostic": convergence_diagnostic,
        "convergence_replications_raw": convergence_diagnostic.get("raw_replications", pd.DataFrame()),
        "variance_mean_rmse": variance_mean_rmse,
        "variance_mean_relative_rmse": variance_mean_relative_rmse,
        "variance_zero_observation_rate": simulation["variance_zero_observation_rate"],
        "max_abs_pre_correction_forward_bias_bps": simulation["max_abs_pre_correction_forward_bias_bps"],
        "total_abs_martingale_correction_bps": simulation["total_abs_martingale_correction_bps"],
        "max_abs_martingale_correction_bps": simulation["max_abs_martingale_correction_bps"],
        "rms_martingale_correction_bps": simulation["rms_martingale_correction_bps"],
        "mean_abs_martingale_correction_bps": simulation.get("mean_abs_martingale_correction_bps", float("nan")),
        "martingale_method": simulation.get("martingale_method", "None"),
        "warnings": list(dict.fromkeys(warnings)),
        "blockers": list(dict.fromkeys(blockers)),
        "governance": {
            "measure": "All paths and probabilities are generated under the risk-neutral Q measure using the calibrated Heston parameters.",
            "scheme": "Andersen QE-M couples the QE variance transition to the log spot through endpoint coefficients and an independent Gaussian driver. Full truncation Euler is retained as a challenger.",
            "carry": "The cross-expiry governed effective-q curve is converted to a deterministic cumulative carry schedule.",
            "martingale": "QE-M uses Andersen's conditional exponential-moment correction. No empirical per-step rescaling to the simulated sample mean is applied.",
            "convergence": "Time-step convergence is estimated from replicated grids; overlapping confidence intervals are classified as Monte Carlo-noise inconclusive rather than as numerical convergence.",
            "pricing_validation": "Monte Carlo prices are compared with Fourier Heston prices; this tests simulation fidelity, not market fit.",
            "model_fit": "Target-versus-Heston residuals remain governed by the calibration result and are not erased by successful simulation validation.",
            "feller": "A violated Feller condition is compatible with characteristic-function pricing but can increase near-zero variance states in discretized paths.",
            "prohibition": "Q terminal probabilities are pricing probabilities and must not be interpreted as unbiased physical forecasts.",
        },
    }


__all__ = [
    "HESTON_SIMULATION_VERSION",
    "HESTON_SIMULATION_SCHEMES",
    "HestonSimulationSettings",
    "build_heston_q_simulation",
]
