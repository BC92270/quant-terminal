from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from monte_carlo.options_risk_neutral import black_scholes_price
from monte_carlo.options_surface import (
    build_multi_expiry_surface,
    build_governed_carry_curve,
    diagnose_atm_term_structure_events,
    fit_svi_slice,
    select_surface_expirations,
)


def _lab(spot: float = 100.0) -> dict:
    rng = np.random.default_rng(17)
    returns = rng.normal(0.0001, 0.017, size=(1_000, 90))
    paths = np.concatenate([np.full((1_000, 1), spot), spot * np.exp(np.cumsum(returns, axis=1))], axis=1)
    return {"ticker": "SYNTH", "base": {"current_price": spot}, "paths_by_horizon": {30: paths[:, :31], 90: paths}}


def _chain(expiration: str, dte: int, volatility_shift: float = 0.0, spot: float = 100.0, q: float = 0.01) -> pd.DataFrame:
    r = 0.04
    t = dte / 365.0
    rows = []
    for strike in np.arange(70.0, 131.0, 2.5):
        k = np.log(strike / (spot * np.exp((r - q) * t)))
        iv = 0.24 + volatility_shift + 0.12 * k * k - 0.08 * k
        for option_type in ("call", "put"):
            price = black_scholes_price(spot, strike, t, r, q, iv, option_type)
            rows.append(
                {
                    "strike": strike,
                    "option_type": option_type,
                    "bid": max(0.001, price - 0.02),
                    "ask": price + 0.02,
                    "last_price": price,
                    "open_interest": 1_000,
                    "volume": 100,
                    "implied_volatility": 2.5,
                    "expiration": expiration,
                    "valuation_date": "2026-08-05",
                }
            )
    return pd.DataFrame(rows)


def test_select_surface_expirations_is_unique_and_tenor_aligned():
    expirations = ["2026-08-14", "2026-08-21", "2026-09-04", "2026-10-02", "2026-11-06", "2027-02-05"]
    selected = select_surface_expirations(expirations, "2026-08-05", target_days=(14, 30, 60, 90, 180), max_expiries=5)
    assert len(selected) == len(set(selected))
    assert len(selected) >= 4
    assert selected[0] in expirations


def test_svi_slice_fit_is_positive_and_within_butterfly_tolerance():
    k = np.linspace(-0.30, 0.30, 21)
    true = np.array([0.025, 0.18, -0.25, 0.01, 0.20])
    x = k - true[3]
    w = true[0] + true[1] * (true[2] * x + np.sqrt(x * x + true[4] ** 2))
    fit = fit_svi_slice(k, w, np.ones_like(k))
    assert fit["ok"] is True
    assert fit["minimum_total_variance"] > 0.0
    assert fit["butterfly_g_min"] > -1e-4
    assert fit["rmse_total_variance"] < 0.01


def test_multi_expiry_surface_builds_and_calendar_projection_is_monotone():
    expiries = {
        "2026-08-19": _chain("2026-08-19", 14, 0.00),
        "2026-09-04": _chain("2026-09-04", 30, 0.01),
        "2026-10-04": _chain("2026-10-04", 60, 0.015),
        "2026-11-03": _chain("2026-11-03", 90, 0.02),
    }
    result = build_multi_expiry_surface(
        _lab(),
        option_chains=expiries,
        expirations=list(expiries),
        risk_free_rate=0.04,
        dividend_yield=0.01,
        contract_style="European",
        max_relative_spread=1.0,
        minimum_open_interest=1,
        valuation_date="2026-08-05",
    )
    assert result["ok"] is True
    assert result["expiry_count"] == 4
    assert result["projected_calendar_violations"] == 0
    table = result["surface_table"].pivot(index="dte", columns="log_moneyness", values="projected_total_variance").sort_index()
    assert np.min(np.diff(table.to_numpy(), axis=0)) >= -1e-10
    assert set(["atm_iv_projected", "risk_reversal_25d", "butterfly_25d"]).issubset(result["term_structure"].columns)


def test_calendar_violation_is_detected_and_corrected():
    # The 60D slice is deliberately much lower than the 30D slice.
    expiries = {
        "2026-08-19": _chain("2026-08-19", 14, 0.08),
        "2026-09-04": _chain("2026-09-04", 30, 0.10),
        "2026-10-04": _chain("2026-10-04", 60, -0.08),
        "2026-11-03": _chain("2026-11-03", 90, 0.02),
    }
    result = build_multi_expiry_surface(
        _lab(),
        option_chains=expiries,
        expirations=list(expiries),
        risk_free_rate=0.04,
        dividend_yield=0.01,
        contract_style="European",
        max_relative_spread=1.0,
        valuation_date="2026-08-05",
    )
    assert result["ok"] is True
    assert result["raw_calendar_violations"] > 0
    assert result["projected_calendar_violations"] == 0
    assert result["calendar_adjustment_max"] > 0.0


def test_american_surface_never_returns_silent_pass():
    expiries = {
        "2026-08-19": _chain("2026-08-19", 14, 0.00),
        "2026-09-04": _chain("2026-09-04", 30, 0.01),
        "2026-10-04": _chain("2026-10-04", 60, 0.015),
    }
    result = build_multi_expiry_surface(
        _lab(),
        option_chains=expiries,
        expirations=list(expiries),
        risk_free_rate=0.04,
        dividend_yield=0.01,
        contract_style="American equity/ETF approximation",
        max_relative_spread=1.0,
        valuation_date="2026-08-05",
    )
    assert result["ok"] is True
    assert result["status"] == "WARNING"
    assert any("American" in warning for warning in result["warnings"])



def test_joint_carry_curve_rejects_extreme_nodes_and_uses_one_bounded_curve():
    expiries = {
        "2026-08-21": _chain("2026-08-21", 16, 0.00, q=0.12),
        "2026-09-04": _chain("2026-09-04", 30, 0.01, q=-0.08),
        "2026-10-16": _chain("2026-10-16", 72, 0.015, q=0.025),
        "2026-11-20": _chain("2026-11-20", 107, 0.02, q=0.015),
    }
    result = build_multi_expiry_surface(
        _lab(),
        option_chains=expiries,
        expirations=list(expiries),
        risk_free_rate=0.04,
        dividend_yield=0.0,
        borrow_cost=0.0,
        contract_style="European",
        max_relative_spread=1.0,
        carry_max_deviation=0.05,
        valuation_date="2026-08-05",
    )
    assert result["ok"] is True
    carry = result["carry_curve_table"].sort_values("dte")
    assert np.max(np.abs(carry["curve_carry_q"].to_numpy())) <= 0.0500001
    assert carry.iloc[0]["carry_candidate_gate"] == "REJECTED"
    assert carry.iloc[1]["carry_candidate_gate"] == "REJECTED"
    assert result["carry_curve"]["accepted_candidates"] >= 2
    assert np.allclose(
        result["term_structure"].sort_values("dte")["effective_q"].to_numpy(),
        carry["curve_carry_q"].to_numpy(),
    )


def test_event_premium_diagnostic_flags_front_term_jump():
    term = pd.DataFrame(
        {
            "expiration": ["2026-08-21", "2026-09-04", "2026-10-16", "2026-11-20"],
            "dte": [16, 30, 72, 107],
            "time_to_expiry": np.asarray([16, 30, 72, 107]) / 365.0,
            "atm_iv_projected": [0.38, 0.445, 0.42, 0.425],
        }
    )
    diagnostics = diagnose_atm_term_structure_events(term)
    assert not diagnostics.empty
    assert bool(diagnostics.iloc[0]["potential_event_window"])
    assert "ATM IV rises" in diagnostics.iloc[0]["diagnostic"]


def test_zero_calendar_adjustment_is_explicitly_reported():
    expiries = {
        "2026-08-19": _chain("2026-08-19", 14, 0.00),
        "2026-09-04": _chain("2026-09-04", 30, 0.01),
        "2026-10-04": _chain("2026-10-04", 60, 0.015),
    }
    result = build_multi_expiry_surface(
        _lab(),
        expiries,
        list(expiries),
        risk_free_rate=0.04,
        dividend_yield=0.01,
        contract_style="European",
        valuation_date="2026-08-05",
    )
    assert result["ok"]
    assert result["raw_calendar_violations"] == 0
    assert result["calendar_adjustment_required"] is False


def test_surface_uses_common_provider_underlying_when_parent_lab_spot_is_stale():
    expiries = {
        "2026-08-19": _chain("2026-08-19", 14, 0.00),
        "2026-09-04": _chain("2026-09-04", 30, 0.01),
        "2026-10-04": _chain("2026-10-04", 60, 0.015),
    }
    for frame in expiries.values():
        frame["provider_underlying_price"] = 100.0
    result = build_multi_expiry_surface(
        _lab(spot=88.0),
        option_chains=expiries,
        expirations=list(expiries),
        risk_free_rate=0.04,
        dividend_yield=0.01,
        contract_style="European",
        max_relative_spread=1.0,
        valuation_date="2026-08-05",
    )
    assert result["ok"] is True
    assert abs(result["surface_spot"] - 100.0) < 1e-12
    assert abs(result["lab_spot"] - 88.0) < 1e-12
    assert result["expiry_count"] == 3
    assert all(result["term_structure"]["pricing_spot_source"] == "provider_option_chain_underlying")
