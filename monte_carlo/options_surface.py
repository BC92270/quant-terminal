from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Dict, Mapping, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from .options_risk_neutral import (
    build_options_risk_neutral_lab,
    fetch_option_chain,
    list_option_expirations,
)

OPTIONS_SURFACE_VERSION = "OPTIONS-VOL-SURFACE-2.7.1B"
SURFACE_TARGET_DAYS: Tuple[int, ...] = (14, 30, 60, 90, 180, 365)
SURFACE_MIN_EXPIRIES = 3
SURFACE_MIN_QUOTES_PER_EXPIRY = 6
SURFACE_K_GRID = np.linspace(-0.35, 0.35, 71)


@dataclass(frozen=True)
class OptionsSurfaceSettings:
    expirations: Tuple[str, ...]
    risk_free_rate: float = 0.04
    dividend_yield: float = 0.0
    borrow_cost: float = 0.0
    carry_max_deviation: float = 0.05
    carry_anchor_strength: float = 1.0
    carry_smoothness: float = 20.0
    contract_style: str = "American equity/ETF approximation"
    parity_moneyness_band: float = 0.20
    max_relative_spread: float = 0.50
    minimum_open_interest: int = 1
    minimum_volume: int = 0
    smoothing_penalty: float = 1e-4
    svi_penalty: float = 2_500.0
    calendar_projection: bool = True


def _configuration_signature(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(payload), sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16].upper()


def select_surface_expirations(
    expirations: Sequence[str],
    valuation_date: str | pd.Timestamp,
    target_days: Sequence[int] = SURFACE_TARGET_DAYS,
    max_expiries: int = 6,
) -> list[str]:
    valuation = pd.Timestamp(valuation_date).normalize()
    future: list[tuple[str, int]] = []
    for value in expirations:
        expiry = pd.Timestamp(value).normalize()
        dte = int((expiry - valuation).days)
        if dte > 1:
            future.append((str(expiry.date()), dte))
    if not future:
        return []
    chosen: list[str] = []
    for target in target_days:
        candidate = min(future, key=lambda item: abs(item[1] - int(target)))[0]
        if candidate not in chosen:
            chosen.append(candidate)
        if len(chosen) >= int(max_expiries):
            break
    if len(chosen) < min(int(max_expiries), len(future)):
        for expiry, _ in sorted(future, key=lambda item: item[1]):
            if expiry not in chosen:
                chosen.append(expiry)
            if len(chosen) >= int(max_expiries):
                break
    return chosen


def fetch_option_surface_chains(
    ticker: str,
    expirations: Sequence[str],
    cache_ttl_hours: int = 2,
    force_refresh: bool = False,
    cache_dir: str | None = None,
    provider_fetcher=None,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, list[str]]:
    chains: dict[str, pd.DataFrame] = {}
    reports: list[dict[str, Any]] = []
    warnings: list[str] = []
    for expiration in expirations:
        frame, report = fetch_option_chain(
            ticker=ticker,
            expiration=str(expiration),
            cache_ttl_hours=int(cache_ttl_hours),
            force_refresh=bool(force_refresh),
            cache_dir=cache_dir,
            provider_fetcher=provider_fetcher,
        )
        row = dict(report)
        row["expiration"] = str(expiration)
        reports.append(row)
        if isinstance(frame, pd.DataFrame) and not frame.empty and report.get("ok"):
            chains[str(expiration)] = frame
        for warning in report.get("warnings", []):
            warnings.append(f"{expiration}: {warning}")
    return chains, pd.DataFrame(reports), warnings


def _svi_total_variance(k: np.ndarray, params: Sequence[float]) -> np.ndarray:
    a, b, rho, m, sigma = [float(value) for value in params]
    x = np.asarray(k, dtype=float) - m
    return a + b * (rho * x + np.sqrt(x * x + sigma * sigma))


def _svi_derivatives(k: np.ndarray, params: Sequence[float]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    a, b, rho, m, sigma = [float(value) for value in params]
    x = np.asarray(k, dtype=float) - m
    root = np.sqrt(x * x + sigma * sigma)
    w = a + b * (rho * x + root)
    wp = b * (rho + x / root)
    wpp = b * sigma * sigma / np.maximum(root**3, 1e-12)
    return w, wp, wpp


def _svi_butterfly_g(k: np.ndarray, params: Sequence[float]) -> np.ndarray:
    w, wp, wpp = _svi_derivatives(k, params)
    w = np.maximum(w, 1e-10)
    return (1.0 - np.asarray(k, dtype=float) * wp / (2.0 * w)) ** 2 - 0.25 * wp**2 * (1.0 / w + 0.25) + 0.5 * wpp


def fit_svi_slice(
    k: Sequence[float],
    total_variance: Sequence[float],
    weights: Sequence[float] | None = None,
    penalty: float = 2_500.0,
) -> dict[str, Any]:
    x = np.asarray(k, dtype=float)
    y = np.asarray(total_variance, dtype=float)
    wgt = np.ones_like(x) if weights is None else np.asarray(weights, dtype=float)
    valid = np.isfinite(x) & np.isfinite(y) & np.isfinite(wgt) & (y > 0.0) & (wgt > 0.0)
    x, y, wgt = x[valid], y[valid], wgt[valid]
    if x.size < SURFACE_MIN_QUOTES_PER_EXPIRY:
        return {"ok": False, "status": "BLOCKED", "reason": "Fewer than six reliable smile quotes."}
    wgt = wgt / max(float(np.mean(wgt)), 1e-12)
    y_min = float(np.min(y))
    y_med = float(np.median(y))
    slope = max(0.02, min(1.0, float(np.ptp(y)) / max(float(np.ptp(x)), 1e-4)))
    initial = np.array([max(1e-6, 0.65 * y_min), slope, -0.25, 0.0, 0.15], dtype=float)
    bounds = [
        (1e-10, max(2.0, 10.0 * y_med)),
        (1e-8, 3.0),
        (-0.999, 0.999),
        (-1.5, 1.5),
        (1e-4, 2.0),
    ]
    dense_k = np.linspace(min(-0.7, float(np.min(x)) - 0.10), max(0.7, float(np.max(x)) + 0.10), 281)

    def objective(params: np.ndarray) -> float:
        fitted = _svi_total_variance(x, params)
        residual = fitted - y
        loss = float(np.average(residual * residual, weights=wgt))
        dense_w = _svi_total_variance(dense_k, params)
        g = _svi_butterfly_g(dense_k, params)
        left_slope = float(params[1] * (1.0 - params[2]))
        right_slope = float(params[1] * (1.0 + params[2]))
        penalties = (
            float(np.sum(np.minimum(dense_w - 1e-9, 0.0) ** 2))
            + float(np.sum(np.minimum(g, 0.0) ** 2))
            + max(left_slope - 2.0, 0.0) ** 2
            + max(right_slope - 2.0, 0.0) ** 2
        )
        return loss + float(penalty) * penalties

    result = minimize(objective, initial, method="L-BFGS-B", bounds=bounds, options={"maxiter": 2_000, "ftol": 1e-14})
    params = np.asarray(result.x, dtype=float)
    fitted = _svi_total_variance(x, params)
    dense_w = _svi_total_variance(dense_k, params)
    g = _svi_butterfly_g(dense_k, params)
    left_slope = float(params[1] * (1.0 - params[2]))
    right_slope = float(params[1] * (1.0 + params[2]))
    rmse_w = float(np.sqrt(np.average((fitted - y) ** 2, weights=wgt)))
    iv_scale = max(float(np.median(np.sqrt(y))), 1e-8)
    rmse_iv_approx = rmse_w / max(2.0 * iv_scale, 1e-8)
    min_g = float(np.min(g))
    positivity = float(np.min(dense_w))
    status = "PASS"
    warnings: list[str] = []
    if not result.success:
        status = "WARNING"
        warnings.append(f"SVI optimizer: {result.message}")
    if min_g < -1e-5:
        status = "WARNING"
        warnings.append("SVI slice retains numerical butterfly-arbitrage risk.")
    if left_slope >= 2.0 or right_slope >= 2.0:
        status = "WARNING"
        warnings.append("SVI wing slope breaches the Lee moment bound.")
    if positivity <= 0.0:
        status = "WARNING"
        warnings.append("SVI total variance is non-positive on the diagnostic grid.")
    return {
        "ok": True,
        "status": status,
        "params": {"a": float(params[0]), "b": float(params[1]), "rho": float(params[2]), "m": float(params[3]), "sigma": float(params[4])},
        "rmse_total_variance": rmse_w,
        "rmse_iv_approx": rmse_iv_approx,
        "butterfly_g_min": min_g,
        "lee_left_slope": left_slope,
        "lee_right_slope": right_slope,
        "minimum_total_variance": positivity,
        "optimizer_success": bool(result.success),
        "optimizer_message": str(result.message),
        "warnings": warnings,
    }


def _pava_non_decreasing(values: np.ndarray, weights: np.ndarray | None = None) -> np.ndarray:
    y = np.asarray(values, dtype=float)
    w = np.ones_like(y) if weights is None else np.asarray(weights, dtype=float)
    blocks: list[list[float]] = []
    for value, weight in zip(y, w):
        blocks.append([float(value), float(max(weight, 1e-12)), 1.0])
        while len(blocks) >= 2 and blocks[-2][0] > blocks[-1][0]:
            last = blocks.pop()
            prev = blocks.pop()
            total_weight = prev[1] + last[1]
            blocks.append([(prev[0] * prev[1] + last[0] * last[1]) / total_weight, total_weight, prev[2] + last[2]])
    output: list[float] = []
    for mean, _, count in blocks:
        output.extend([mean] * int(count))
    return np.asarray(output, dtype=float)


def _black_scholes_deltas(k: np.ndarray, total_variance: np.ndarray, risk_free_rate: float, dividend_yield: float, t: float) -> tuple[np.ndarray, np.ndarray]:
    w = np.maximum(np.asarray(total_variance, dtype=float), 1e-10)
    sigma_sqrt_t = np.sqrt(w)
    d1 = (-np.asarray(k, dtype=float) + 0.5 * w) / sigma_sqrt_t
    # k = log(K/F); spot delta includes exp(-qT)
    from scipy.special import ndtr

    disc_q = math.exp(-float(dividend_yield) * float(t))
    call_delta = disc_q * ndtr(d1)
    put_delta = call_delta - disc_q
    return call_delta, put_delta


def _surface_skew_metrics(k_grid: np.ndarray, total_variance: np.ndarray, t: float, risk_free_rate: float, dividend_yield: float) -> dict[str, float]:
    iv = np.sqrt(np.maximum(total_variance, 0.0) / max(float(t), 1e-12))
    call_delta, put_delta = _black_scholes_deltas(k_grid, total_variance, risk_free_rate, dividend_yield, t)
    atm_iv = float(np.interp(0.0, k_grid, iv))
    call_idx = int(np.argmin(np.abs(call_delta - 0.25)))
    put_idx = int(np.argmin(np.abs(put_delta + 0.25)))
    call25 = float(iv[call_idx])
    put25 = float(iv[put_idx])
    return {
        "atm_iv": atm_iv,
        "call_25d_iv": call25,
        "put_25d_iv": put25,
        "risk_reversal_25d": call25 - put25,
        "butterfly_25d": 0.5 * (call25 + put25) - atm_iv,
    }




def _is_generic_exercise_warning(message: str) -> bool:
    text = str(message).lower()
    return (
        "american-style exercise makes european put-call parity" in text
        or "us equity/etf options are american-style" in text
        or "governed put-call parity was rejected" in text
    )


def _carry_candidate_row(expiration: str, result: Mapping[str, Any], manual_carry: float) -> dict[str, Any]:
    report = dict(result.get("forward_report", {}))
    candidate_q = report.get("candidate_implied_dividend_yield")
    candidate_forward = report.get("candidate_forward")
    dispersion = report.get("forward_dispersion_relative")
    pair_count = int(report.get("paired_quotes", 0) or 0)
    return {
        "expiration": str(expiration),
        "dte": int(result.get("calendar_days", 0) or 0),
        "time_to_expiry": float(result.get("time_to_expiry", float("nan"))),
        "manual_carry_anchor": float(manual_carry),
        "parity_candidate_q": float(candidate_q) if candidate_q is not None and np.isfinite(candidate_q) else float("nan"),
        "parity_candidate_forward": float(candidate_forward) if candidate_forward is not None and np.isfinite(candidate_forward) else float("nan"),
        "parity_individual_accepted": bool(report.get("accepted", False)),
        "parity_pairs": pair_count,
        "parity_dispersion_relative": float(dispersion) if dispersion is not None and np.isfinite(dispersion) else float("nan"),
        "single_expiry_status": str(result.get("status", "UNKNOWN")),
        "pricing_spot": float(result.get("pricing_spot", result.get("spot", float("nan")))),
        "lab_spot": float(result.get("lab_spot", float("nan"))),
        "pricing_spot_source": str(result.get("pricing_spot_source", "unknown")),
        "spot_sync_gap": float(result.get("spot_sync_gap", float("nan"))),
    }


def build_governed_carry_curve(
    candidate_table: pd.DataFrame,
    spot: float,
    risk_free_rate: float,
    manual_dividend_yield: float,
    borrow_cost: float = 0.0,
    max_deviation: float = 0.05,
    anchor_strength: float = 1.0,
    smoothness: float = 20.0,
    hard_min_carry: float = -0.03,
    hard_max_carry: float = 0.20,
) -> dict[str, Any]:
    """Build one governed carry curve across expiries.

    The curve is estimated jointly. Accepted near-ATM parity candidates anchor the
    fit, while every node is shrunk toward the explicit dividend + borrow input.
    Rejected or missing expiries are interpolated/extrapolated by the same curve,
    never accepted independently.
    """
    if not isinstance(candidate_table, pd.DataFrame) or candidate_table.empty:
        return {"ok": False, "status": "BLOCKED", "reason": "No expiry-level carry candidates were available."}
    table = candidate_table.copy().sort_values("time_to_expiry").reset_index(drop=True)
    manual_carry = float(manual_dividend_yield) + float(borrow_cost)
    max_dev = max(0.005, float(max_deviation))
    lower = max(float(hard_min_carry), manual_carry - max_dev)
    upper = min(float(hard_max_carry), manual_carry + max_dev)
    if lower >= upper:
        lower, upper = manual_carry - max_dev, manual_carry + max_dev

    candidate = pd.to_numeric(table["parity_candidate_q"], errors="coerce").to_numpy(dtype=float)
    dispersion = pd.to_numeric(table["parity_dispersion_relative"], errors="coerce").to_numpy(dtype=float)
    pairs = pd.to_numeric(table["parity_pairs"], errors="coerce").fillna(0).to_numpy(dtype=float)
    individually_accepted = table["parity_individual_accepted"].astype(bool).to_numpy()
    finite = np.isfinite(candidate)
    within_anchor_band = finite & (candidate >= lower) & (candidate <= upper)
    dispersion_ok = np.isfinite(dispersion) & (dispersion <= 0.02)
    pair_ok = pairs >= 4
    accepted = individually_accepted & within_anchor_band & dispersion_ok & pair_ok

    table["carry_candidate_gate"] = np.where(accepted, "ACCEPTED", "REJECTED")
    reasons: list[str] = []
    for idx in range(len(table)):
        row_reasons: list[str] = []
        if not finite[idx]:
            row_reasons.append("candidate unavailable")
        else:
            if not individually_accepted[idx]:
                row_reasons.append("single-expiry parity gate failed")
            if not within_anchor_band[idx]:
                row_reasons.append(f"outside manual carry band [{lower:.2%}, {upper:.2%}]")
            if not dispersion_ok[idx]:
                row_reasons.append("forward dispersion above 2% of spot")
            if not pair_ok[idx]:
                row_reasons.append("fewer than four robust parity pairs")
        reasons.append("; ".join(row_reasons) if row_reasons else "accepted")
    table["carry_candidate_reason"] = reasons

    n = len(table)
    times = pd.to_numeric(table["time_to_expiry"], errors="coerce").to_numpy(dtype=float)
    x0 = np.full(n, manual_carry, dtype=float)
    accepted_count = int(np.sum(accepted))
    optimizer_success = False
    optimizer_message = "Manual anchor used."

    if accepted_count >= 2:
        raw_weights = np.sqrt(np.maximum(pairs[accepted], 1.0)) / np.maximum(dispersion[accepted], 0.002)
        raw_weights = raw_weights / max(float(np.mean(raw_weights)), 1e-12)
        candidate_weights = np.zeros(n, dtype=float)
        candidate_weights[accepted] = 4.0 * raw_weights
        anchor = max(float(anchor_strength), 1e-6)
        smooth = max(float(smoothness), 0.0)

        def objective(q_values: np.ndarray) -> float:
            q = np.asarray(q_values, dtype=float)
            candidate_loss = float(np.sum(candidate_weights[accepted] * (q[accepted] - candidate[accepted]) ** 2))
            anchor_loss = anchor * float(np.sum((q - manual_carry) ** 2))
            if len(q) >= 3:
                # Scale second differences by tenor spacing to avoid a front-end
                # node dominating merely because expiries are unevenly spaced.
                log_t = np.log(np.maximum(times, 1e-6))
                slopes = np.diff(q) / np.maximum(np.diff(log_t), 1e-6)
                smooth_loss = smooth * float(np.sum(np.diff(slopes) ** 2))
            else:
                smooth_loss = smooth * float(np.sum(np.diff(q) ** 2))
            return candidate_loss + anchor_loss + smooth_loss

        result = minimize(
            objective,
            x0,
            method="L-BFGS-B",
            bounds=[(lower, upper)] * n,
            options={"maxiter": 2_000, "ftol": 1e-15},
        )
        if result.success and np.isfinite(result.x).all():
            q_curve = np.asarray(result.x, dtype=float)
            optimizer_success = True
            optimizer_message = str(result.message)
        else:
            q_curve = x0.copy()
            optimizer_message = f"Carry-curve optimizer fallback: {getattr(result, 'message', 'unknown failure')}"
    else:
        q_curve = x0.copy()

    q_curve = np.clip(q_curve, lower, upper)
    accepted_times = times[accepted]
    sources: list[str] = []
    for idx in range(n):
        if accepted[idx]:
            sources.append("PARITY_ANCHORED")
        elif accepted_count >= 2 and float(np.min(accepted_times)) <= times[idx] <= float(np.max(accepted_times)):
            sources.append("CURVE_INTERPOLATED")
        elif accepted_count >= 2:
            sources.append("MANUAL_ANCHORED_EXTRAPOLATION")
        else:
            sources.append("MANUAL_ANCHOR")

    table["curve_carry_q"] = q_curve
    table["carry_curve_source"] = sources
    table["candidate_minus_curve"] = candidate - q_curve
    table["effective_forward"] = float(spot) * np.exp((float(risk_free_rate) - q_curve) * times)
    table["manual_dividend_yield"] = float(manual_dividend_yield)
    table["manual_borrow_cost"] = float(borrow_cost)
    table["parity_early_exercise_residual"] = candidate - q_curve

    curve_roughness = 0.0
    if n >= 3:
        curve_roughness = float(np.sqrt(np.mean(np.diff(q_curve, n=2) ** 2)))
    candidate_adjustments = np.abs(candidate[accepted] - q_curve[accepted]) if accepted_count else np.asarray([], dtype=float)
    max_candidate_adjustment = float(np.max(candidate_adjustments)) if candidate_adjustments.size else 0.0

    warnings: list[str] = []
    if accepted_count < 2:
        status = "FALLBACK"
        warnings.append("Fewer than two cross-expiry parity candidates passed the joint carry gate; the manual dividend + borrow curve was used.")
    else:
        status = "PASS" if optimizer_success else "WARNING"
        if not optimizer_success:
            warnings.append(optimizer_message)
        rejected_finite = int(np.sum(finite & ~accepted))
        if rejected_finite:
            warnings.append(f"{rejected_finite} finite parity carry candidate(s) were rejected by the joint cross-expiry gate.")
        if max_candidate_adjustment > 0.02:
            status = "WARNING"
            warnings.append("The governed carry curve moved at least one accepted parity candidate by more than 2 percentage points.")
    if float(np.ptp(q_curve)) > 0.05:
        status = "WARNING"
        warnings.append("The fitted effective-carry curve spans more than 5 percentage points across selected expiries.")

    return {
        "ok": True,
        "status": status,
        "manual_dividend_yield": float(manual_dividend_yield),
        "manual_borrow_cost": float(borrow_cost),
        "manual_effective_carry": manual_carry,
        "carry_lower_bound": lower,
        "carry_upper_bound": upper,
        "accepted_candidates": accepted_count,
        "rejected_candidates": int(n - accepted_count),
        "optimizer_success": optimizer_success,
        "optimizer_message": optimizer_message,
        "curve_roughness": curve_roughness,
        "max_candidate_adjustment": max_candidate_adjustment,
        "table": table,
        "warnings": warnings,
        "governance": {
            "definition": "Effective carry q = cash-dividend yield + explicit borrow/specialness input, adjusted only by robust near-ATM parity evidence.",
            "american_residual": "Candidate q minus governed curve is retained as a parity/early-exercise distortion diagnostic, not interpreted as a dividend forecast.",
            "joint_gate": "All expiries are fitted jointly; rejected nodes cannot independently determine their forward.",
        },
    }


def diagnose_atm_term_structure_events(term_structure: pd.DataFrame) -> pd.DataFrame:
    """Flag potential event-premium windows without pretending to know the event calendar."""
    if not isinstance(term_structure, pd.DataFrame) or len(term_structure) < 2:
        return pd.DataFrame()
    term = term_structure.sort_values("time_to_expiry").reset_index(drop=True).copy()
    t = term["time_to_expiry"].to_numpy(dtype=float)
    iv = term["atm_iv_projected"].to_numpy(dtype=float)
    total_variance = iv**2 * t
    dt = np.diff(t)
    incremental_variance = np.diff(total_variance) / np.maximum(dt, 1e-12)
    forward_vol = np.sqrt(np.maximum(incremental_variance, 0.0))
    median_forward_vol = float(np.nanmedian(forward_vol)) if forward_vol.size else float("nan")
    rows: list[dict[str, Any]] = []
    for idx in range(1, len(term)):
        iv_change_pp = (iv[idx] - iv[idx - 1]) * 100.0
        fvol = float(forward_vol[idx - 1])
        short_window = int(term.loc[idx, "dte"]) <= 180
        local_jump = short_window and iv_change_pp >= 3.0
        forward_spike = short_window and np.isfinite(median_forward_vol) and median_forward_vol > 0.0 and fvol >= 1.30 * median_forward_vol
        event_flag = bool(local_jump or forward_spike)
        reasons: list[str] = []
        if local_jump:
            reasons.append(f"ATM IV rises {iv_change_pp:+.2f} pp")
        if forward_spike:
            reasons.append(f"forward vol {fvol:.2%} exceeds 1.30× median")
        rows.append(
            {
                "window_start": str(term.loc[idx - 1, "expiration"]),
                "window_end": str(term.loc[idx, "expiration"]),
                "start_dte": int(term.loc[idx - 1, "dte"]),
                "end_dte": int(term.loc[idx, "dte"]),
                "atm_iv_start": float(iv[idx - 1]),
                "atm_iv_end": float(iv[idx]),
                "atm_iv_change_pp": float(iv_change_pp),
                "incremental_forward_variance": float(incremental_variance[idx - 1]),
                "incremental_forward_vol": fvol,
                "potential_event_window": event_flag,
                "diagnostic": "; ".join(reasons) if reasons else "No material event-premium signal",
            }
        )
    return pd.DataFrame(rows)

def build_multi_expiry_surface(
    lab: Mapping[str, Any],
    option_chains: Mapping[str, pd.DataFrame],
    expirations: Sequence[str],
    risk_free_rate: float = 0.04,
    dividend_yield: float = 0.0,
    borrow_cost: float = 0.0,
    contract_style: str = "American equity/ETF approximation",
    parity_moneyness_band: float = 0.20,
    max_relative_spread: float = 0.50,
    minimum_open_interest: int = 1,
    minimum_volume: int = 0,
    smoothing_penalty: float = 1e-4,
    svi_penalty: float = 2_500.0,
    calendar_projection: bool = True,
    carry_max_deviation: float = 0.05,
    carry_anchor_strength: float = 1.0,
    carry_smoothness: float = 20.0,
    source_reports: Mapping[str, Mapping[str, Any]] | None = None,
    valuation_date: str | pd.Timestamp | None = None,
    k_grid: Sequence[float] = SURFACE_K_GRID,
) -> dict[str, Any]:
    spot = float(lab.get("base", {}).get("current_price", float("nan")))
    if not np.isfinite(spot) or spot <= 0.0:
        return {"ok": False, "status": "BLOCKED", "reason": "A positive spot price is required."}

    requested = [str(pd.Timestamp(value).date()) for value in expirations]
    settings = OptionsSurfaceSettings(
        expirations=tuple(requested),
        risk_free_rate=float(risk_free_rate),
        dividend_yield=float(dividend_yield),
        borrow_cost=float(borrow_cost),
        contract_style=str(contract_style),
        parity_moneyness_band=float(parity_moneyness_band),
        max_relative_spread=float(max_relative_spread),
        minimum_open_interest=int(minimum_open_interest),
        minimum_volume=int(minimum_volume),
        smoothing_penalty=float(smoothing_penalty),
        svi_penalty=float(svi_penalty),
        calendar_projection=bool(calendar_projection),
        carry_max_deviation=float(carry_max_deviation),
        carry_anchor_strength=float(carry_anchor_strength),
        carry_smoothness=float(carry_smoothness),
    )
    manual_carry = float(dividend_yield) + float(borrow_cost)
    warnings: list[str] = []
    failures: list[dict[str, Any]] = []
    expiry_warning_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    first_pass: dict[str, Any] = {}

    # Pass 1: obtain robust near-ATM parity diagnostics for every expiry. These
    # candidates are not applied independently; they feed one joint carry curve.
    for expiration in requested:
        chain = option_chains.get(expiration)
        if chain is None or not isinstance(chain, pd.DataFrame) or chain.empty:
            failures.append({"expiration": expiration, "stage": "SOURCE", "reason": "Option chain unavailable."})
            continue
        candidate_result = build_options_risk_neutral_lab(
            lab=lab,
            option_chain=chain,
            expiration=expiration,
            risk_free_rate=float(risk_free_rate),
            dividend_yield=float(manual_carry),
            forward_method="Governed put-call parity",
            contract_style=str(contract_style),
            parity_moneyness_band=float(parity_moneyness_band),
            max_relative_spread=float(max_relative_spread),
            minimum_open_interest=int(minimum_open_interest),
            minimum_volume=int(minimum_volume),
            smoothing_penalty=float(smoothing_penalty),
            source_report=(source_reports or {}).get(expiration, {}),
            valuation_date=valuation_date,
        )
        if not candidate_result.get("ok"):
            failures.append({"expiration": expiration, "stage": "PARITY", "reason": candidate_result.get("reason", "Single-expiry build failed.")})
            continue
        first_pass[expiration] = candidate_result
        candidate_rows.append(_carry_candidate_row(expiration, candidate_result, manual_carry))

    if len(candidate_rows) < SURFACE_MIN_EXPIRIES:
        return {
            "ok": False,
            "status": "BLOCKED",
            "reason": f"At least {SURFACE_MIN_EXPIRIES} usable expiries are required; {len(candidate_rows)} reached the carry gate.",
            "failures": pd.DataFrame(failures),
        }

    candidate_frame = pd.DataFrame(candidate_rows)
    synchronized_spots = pd.to_numeric(candidate_frame.get("pricing_spot"), errors="coerce")
    synchronized_spots = synchronized_spots[np.isfinite(synchronized_spots) & (synchronized_spots > 0.0)]
    surface_spot = float(synchronized_spots.median()) if not synchronized_spots.empty else float(spot)
    if np.isfinite(surface_spot) and np.isfinite(spot) and spot > 0.0 and abs(surface_spot / spot - 1.0) > 0.0025:
        warnings.append(
            f"Surface option quotes were synchronized to a common chain underlying of {surface_spot:.4f} rather than the parent-lab spot of {spot:.4f}."
        )

    carry_result = build_governed_carry_curve(
        candidate_frame,
        spot=surface_spot,
        risk_free_rate=float(risk_free_rate),
        manual_dividend_yield=float(dividend_yield),
        borrow_cost=float(borrow_cost),
        max_deviation=float(carry_max_deviation),
        anchor_strength=float(carry_anchor_strength),
        smoothness=float(carry_smoothness),
    )
    if not carry_result.get("ok"):
        return {"ok": False, "status": "BLOCKED", "reason": carry_result.get("reason", "Carry curve build failed."), "failures": pd.DataFrame(failures)}
    carry_table = carry_result["table"].copy().sort_values("time_to_expiry").reset_index(drop=True)
    carry_by_expiry = carry_table.set_index("expiration")["curve_carry_q"].to_dict()
    warnings.extend(carry_result.get("warnings", []))

    # Pass 2: rebuild every expiry with the jointly governed carry curve, then fit
    # the SVI slices on one coherent forward/log-moneyness convention.
    slice_results: dict[str, Any] = {}
    point_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    for expiration in requested:
        if expiration not in first_pass or expiration not in carry_by_expiry:
            continue
        chain = option_chains.get(expiration)
        q_curve = float(carry_by_expiry[expiration])
        result = build_options_risk_neutral_lab(
            lab=lab,
            option_chain=chain,
            expiration=expiration,
            risk_free_rate=float(risk_free_rate),
            dividend_yield=q_curve,
            forward_method="Manual carry curve",
            contract_style=str(contract_style),
            parity_moneyness_band=float(parity_moneyness_band),
            max_relative_spread=float(max_relative_spread),
            minimum_open_interest=int(minimum_open_interest),
            minimum_volume=int(minimum_volume),
            smoothing_penalty=float(smoothing_penalty),
            source_report=(source_reports or {}).get(expiration, {}),
            valuation_date=valuation_date,
        )
        if not result.get("ok"):
            failures.append({"expiration": expiration, "stage": "CARRY_REBUILD", "reason": result.get("reason", "Carry-consistent rebuild failed.")})
            continue
        clean = result["clean_chain"]
        smile = clean[clean["smile_eligible"]].copy()
        if len(smile) < SURFACE_MIN_QUOTES_PER_EXPIRY:
            mark_mid = clean.get("mark_source", pd.Series(index=clean.index, dtype=str)).eq("bid_ask_mid")
            finite_iv_mask = np.isfinite(pd.to_numeric(clean.get("effective_iv", pd.Series(index=clean.index, dtype=float)), errors="coerce"))
            forward_value = float(result.get("forward", float("nan")))
            log_m = np.log(pd.to_numeric(clean.get("strike", pd.Series(index=clean.index, dtype=float)), errors="coerce") / max(forward_value, 1e-12))
            preferred_otm = (
                (clean.get("option_type", pd.Series(index=clean.index, dtype=str)).eq("call") & (pd.to_numeric(clean.get("strike"), errors="coerce") >= forward_value))
                | (clean.get("option_type", pd.Series(index=clean.index, dtype=str)).eq("put") & (pd.to_numeric(clean.get("strike"), errors="coerce") <= forward_value))
            )
            midpoint_quotes = int(mark_mid.sum())
            finite_mid_iv = int(finite_iv_mask.sum())
            finite_midpoint_iv = int((mark_mid & finite_iv_mask).sum())
            otm_midpoint_iv = int((mark_mid & finite_iv_mask & preferred_otm).sum())
            moneyness_midpoint_iv = int((mark_mid & finite_iv_mask & preferred_otm & (log_m.abs() <= 0.35)).sum())
            failures.append(
                {
                    "expiration": expiration,
                    "stage": "SMILE",
                    "reason": f"Only {len(smile)} reliable midpoint-recomputed OTM IV quotes; at least {SURFACE_MIN_QUOTES_PER_EXPIRY} are required.",
                    "final_smile_quotes": int(len(smile)),
                    "midpoint_quotes": midpoint_quotes,
                    "finite_iv_all_marks": finite_mid_iv,
                    "finite_midpoint_iv": finite_midpoint_iv,
                    "otm_midpoint_iv": otm_midpoint_iv,
                    "moneyness_midpoint_iv": moneyness_midpoint_iv,
                    "pricing_spot": float(result.get("pricing_spot", float("nan"))),
                    "lab_spot": float(result.get("lab_spot", float("nan"))),
                    "spot_gap_pct": 100.0 * float(result.get("spot_sync_gap", float("nan"))),
                    "spot_source": str(result.get("pricing_spot_source", "unknown")),
                    "chain_status": str((source_reports or {}).get(expiration, {}).get("status", "unknown")),
                }
            )
            continue
        t = float(result["time_to_expiry"])
        forward = float(result["forward"])
        smile["log_moneyness"] = np.log(smile["strike"].astype(float) / max(forward, 1e-12))
        smile["total_variance"] = smile["effective_iv"].astype(float) ** 2 * t
        fit = fit_svi_slice(
            smile["log_moneyness"].to_numpy(),
            smile["total_variance"].to_numpy(),
            smile["quote_weight"].to_numpy(),
            penalty=float(svi_penalty),
        )
        if not fit.get("ok"):
            failures.append({"expiration": expiration, "stage": "SVI", "reason": fit.get("reason")})
            continue

        params = [fit["params"][name] for name in ("a", "b", "rho", "m", "sigma")]
        candidate_row = carry_table[carry_table["expiration"] == expiration].iloc[0]
        initial = first_pass[expiration]
        slice_results[expiration] = {
            "single_expiry": result,
            "parity_diagnostic": initial.get("forward_report", {}),
            "svi_fit": fit,
            "params": params,
        }
        for row in smile.itertuples(index=False):
            point_rows.append(
                {
                    "expiration": expiration,
                    "dte": int(result["calendar_days"]),
                    "time_to_expiry": t,
                    "forward": forward,
                    "strike": float(row.strike),
                    "log_moneyness": float(row.log_moneyness),
                    "effective_iv": float(row.effective_iv),
                    "total_variance": float(row.total_variance),
                    "quote_weight": float(row.quote_weight),
                    "option_type": str(row.option_type),
                }
            )
        summary_rows.append(
            {
                "expiration": expiration,
                "dte": int(result["calendar_days"]),
                "time_to_expiry": t,
                "forward": forward,
                "pricing_spot": float(result.get("pricing_spot", surface_spot)),
                "lab_spot": float(result.get("lab_spot", spot)),
                "spot_sync_gap": float(result.get("spot_sync_gap", float("nan"))),
                "pricing_spot_source": str(result.get("pricing_spot_source", "unknown")),
                "effective_q": q_curve,
                "manual_dividend_yield": float(dividend_yield),
                "manual_borrow_cost": float(borrow_cost),
                "parity_candidate_q": float(candidate_row["parity_candidate_q"]),
                "parity_candidate_forward": float(candidate_row["parity_candidate_forward"]),
                "parity_individual_accepted": bool(candidate_row["parity_individual_accepted"]),
                "carry_candidate_gate": str(candidate_row["carry_candidate_gate"]),
                "carry_candidate_reason": str(candidate_row["carry_candidate_reason"]),
                "carry_curve_source": str(candidate_row["carry_curve_source"]),
                "parity_early_exercise_residual": float(candidate_row["parity_early_exercise_residual"]),
                "parity_pairs": int(candidate_row["parity_pairs"]),
                "parity_dispersion_relative": float(candidate_row["parity_dispersion_relative"]),
                "single_expiry_status": result["status"],
                "reliable_quotes": int(result["reliable_smile_quotes"]),
                "model_free_vol": float(result["model_free_volatility"]),
                "svi_status": fit["status"],
                "svi_rmse_iv": float(fit["rmse_iv_approx"]),
                "butterfly_g_min": float(fit["butterfly_g_min"]),
                "lee_left_slope": float(fit["lee_left_slope"]),
                "lee_right_slope": float(fit["lee_right_slope"]),
                **{f"svi_{key}": float(value) for key, value in fit["params"].items()},
            }
        )

        for message in result.get("warnings", []):
            if not _is_generic_exercise_warning(str(message)):
                expiry_warning_rows.append({"expiration": expiration, "category": "SINGLE_EXPIRY", "severity": "WARNING", "message": str(message)})
        if str(candidate_row["carry_candidate_gate"]) != "ACCEPTED":
            expiry_warning_rows.append(
                {
                    "expiration": expiration,
                    "category": "CARRY",
                    "severity": "INFO",
                    "message": str(candidate_row["carry_candidate_reason"]),
                }
            )
        for message in fit.get("warnings", []):
            expiry_warning_rows.append({"expiration": expiration, "category": "SVI", "severity": "WARNING", "message": str(message)})

    if len(slice_results) < SURFACE_MIN_EXPIRIES:
        return {
            "ok": False,
            "status": "BLOCKED",
            "reason": f"At least {SURFACE_MIN_EXPIRIES} usable expiries are required; {len(slice_results)} succeeded after joint carry governance.",
            "failures": pd.DataFrame(failures),
            "carry_curve": carry_result,
        }

    expiry_summary = pd.DataFrame(summary_rows).sort_values("time_to_expiry").reset_index(drop=True)
    ordered_expiries = expiry_summary["expiration"].tolist()
    grid = np.asarray(k_grid, dtype=float)
    raw_matrix = np.vstack([_svi_total_variance(grid, slice_results[expiration]["params"]) for expiration in ordered_expiries])
    weights = np.maximum(expiry_summary["reliable_quotes"].to_numpy(dtype=float), 1.0)
    projected_matrix = raw_matrix.copy()
    if calendar_projection:
        for column in range(projected_matrix.shape[1]):
            projected_matrix[:, column] = _pava_non_decreasing(projected_matrix[:, column], weights)
    raw_calendar_diffs = np.diff(raw_matrix, axis=0)
    projected_calendar_diffs = np.diff(projected_matrix, axis=0)
    raw_calendar_violations = int(np.sum(raw_calendar_diffs < -1e-8))
    projected_calendar_violations = int(np.sum(projected_calendar_diffs < -1e-10))
    adjustment_rmse = float(np.sqrt(np.mean((projected_matrix - raw_matrix) ** 2)))
    adjustment_max = float(np.max(np.abs(projected_matrix - raw_matrix)))

    surface_rows: list[dict[str, Any]] = []
    term_rows: list[dict[str, Any]] = []
    for row_idx, summary in expiry_summary.iterrows():
        expiration = str(summary["expiration"])
        t = float(summary["time_to_expiry"])
        forward = float(summary["forward"])
        q = float(summary["effective_q"])
        raw_w = raw_matrix[row_idx]
        projected_w = projected_matrix[row_idx]
        skew = _surface_skew_metrics(grid, projected_w, t, float(risk_free_rate), q)
        term_rows.append(
            {
                "expiration": expiration,
                "dte": int(summary["dte"]),
                "time_to_expiry": t,
                "forward": forward,
                "pricing_spot": float(summary.get("pricing_spot", surface_spot)),
                "lab_spot": float(summary.get("lab_spot", spot)),
                "spot_sync_gap": float(summary.get("spot_sync_gap", float("nan"))),
                "pricing_spot_source": str(summary.get("pricing_spot_source", "unknown")),
                "effective_q": q,
                "manual_dividend_yield": float(dividend_yield),
                "manual_borrow_cost": float(borrow_cost),
                "carry_curve_source": str(summary["carry_curve_source"]),
                "parity_candidate_q": float(summary["parity_candidate_q"]),
                "parity_early_exercise_residual": float(summary["parity_early_exercise_residual"]),
                "atm_iv_raw": float(np.sqrt(max(np.interp(0.0, grid, raw_w), 0.0) / t)),
                "atm_iv_projected": skew["atm_iv"],
                "model_free_vol": float(summary["model_free_vol"]),
                "expected_move_1sigma": surface_spot * skew["atm_iv"] * math.sqrt(t),
                "risk_reversal_25d": skew["risk_reversal_25d"],
                "butterfly_25d": skew["butterfly_25d"],
                "call_25d_iv": skew["call_25d_iv"],
                "put_25d_iv": skew["put_25d_iv"],
            }
        )
        for column, k_value in enumerate(grid):
            surface_rows.append(
                {
                    "expiration": expiration,
                    "dte": int(summary["dte"]),
                    "time_to_expiry": t,
                    "forward": forward,
                    "effective_q": q,
                    "log_moneyness": float(k_value),
                    "strike": float(forward * math.exp(float(k_value))),
                    "raw_total_variance": float(raw_w[column]),
                    "projected_total_variance": float(projected_w[column]),
                    "raw_iv": float(math.sqrt(max(raw_w[column], 0.0) / t)),
                    "projected_iv": float(math.sqrt(max(projected_w[column], 0.0) / t)),
                    "calendar_adjustment": float(projected_w[column] - raw_w[column]),
                }
            )

    surface_table = pd.DataFrame(surface_rows)
    term_structure = pd.DataFrame(term_rows)
    point_table = pd.DataFrame(point_rows)
    event_diagnostics = diagnose_atm_term_structure_events(term_structure)
    event_count = int(event_diagnostics["potential_event_window"].sum()) if not event_diagnostics.empty else 0

    status = "PASS"
    if str(contract_style).lower().startswith("american"):
        status = "WARNING"
        warnings.append("American equity/ETF chains produce one OTM European-equivalent surface approximation; early-exercise effects remain in the parity residual audit.")
    if carry_result.get("status") in {"WARNING", "FALLBACK"}:
        status = "WARNING"
    if raw_calendar_violations > 0:
        status = "WARNING"
        warnings.append(f"Raw SVI slices contained {raw_calendar_violations} calendar-arbitrage grid violations; isotonic total-variance projection was applied.")
    if any(value == "WARNING" for value in expiry_summary["svi_status"]):
        status = "WARNING"
    if adjustment_rmse > 0.01:
        status = "WARNING"
        warnings.append("Calendar projection required a material total-variance adjustment.")
    if len(failures) > max(1, len(requested) // 3):
        status = "WARNING"
        warnings.append("More than one-third of requested expiries failed the surface gate.")
    if event_count:
        warnings.append(f"Potential event premium detected in {event_count} adjacent maturity window(s); verify the earnings and corporate-event calendar independently.")

    signature = _configuration_signature(
        {
            "version": OPTIONS_SURFACE_VERSION,
            "ticker": lab.get("ticker"),
            "spot": spot,
            "settings": asdict(settings),
            "surface_expiries": ordered_expiries,
            "carry_curve": carry_table[["expiration", "curve_carry_q", "carry_curve_source"]].to_dict("records"),
        }
    )
    expiry_warnings = pd.DataFrame(expiry_warning_rows)
    if not expiry_warnings.empty:
        expiry_warnings = expiry_warnings.drop_duplicates().sort_values(["expiration", "category", "message"]).reset_index(drop=True)

    return {
        "ok": True,
        "status": status,
        "version": OPTIONS_SURFACE_VERSION,
        "configuration_signature": signature,
        "settings": asdict(settings),
        "surface_spot": float(surface_spot),
        "lab_spot": float(spot),
        "surface_spot_gap": float(surface_spot / spot - 1.0) if spot > 0.0 else float("nan"),
        "spot": spot,
        "expirations": ordered_expiries,
        "expiry_count": len(ordered_expiries),
        "raw_calendar_violations": raw_calendar_violations,
        "projected_calendar_violations": projected_calendar_violations,
        "calendar_adjustment_rmse": adjustment_rmse,
        "calendar_adjustment_max": adjustment_max,
        "calendar_adjustment_required": bool(adjustment_max > 1e-10 or raw_calendar_violations > 0),
        "expiry_summary": expiry_summary,
        "surface_table": surface_table,
        "term_structure": term_structure,
        "event_diagnostics": event_diagnostics,
        "potential_event_windows": event_count,
        "smile_points": point_table,
        "failures": pd.DataFrame(failures),
        "expiry_warnings": expiry_warnings,
        "carry_curve": carry_result,
        "carry_curve_table": carry_table,
        "source_reports": dict(source_reports or {}),
        "warnings": list(dict.fromkeys(str(value) for value in warnings if str(value))),
        "governance": {
            "measure": "Multi-expiry Q total-variance surface inferred from governed option midpoints.",
            "exercise_style": "American equity/ETF chains are OTM European-equivalent approximations.",
            "carry_curve": "Forwards are derived from one joint dividend + borrow carry curve. Rejected parity nodes cannot determine log-moneyness independently.",
            "carry_components": "The explicit cash-dividend and borrow/specialness inputs form the manual anchor; parity residuals are retained as potential early-exercise/quote distortion.",
            "event_diagnostic": "ATM term-structure flags are statistical event-premium diagnostics only; no earnings calendar is inferred or fabricated.",
            "calendar_projection": "Total variance is projected non-decreasing across maturity at fixed log-moneyness.",
            "butterfly_control": "Raw SVI slices are penalized and numerically diagnosed; a PASS is not a proof of global no-arbitrage outside the displayed grid.",
            "prohibition": "The surface is a pricing object and is not a physical return forecast.",
        },
    }
