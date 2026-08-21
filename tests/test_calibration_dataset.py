from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from monte_carlo.calibration_dataset import (
    CALIBRATION_DATASET_VERSION,
    build_calibration_dataset,
    estimate_event_variance_adjustments,
)
from monte_carlo.options_risk_neutral import black_scholes_price
from monte_carlo.options_surface import build_multi_expiry_surface


def _lab(spot: float = 100.0) -> dict:
    return {"ticker": "DATASET", "base": {"current_price": spot}, "paths_by_horizon": {}}


def _chain(expiration: str, dte: int, volatility_shift: float = 0.0, spot: float = 100.0, q: float = 0.01) -> pd.DataFrame:
    r = 0.04
    t = dte / 365.0
    rows = []
    for strike in np.arange(65.0, 136.0, 2.5):
        k = np.log(strike / (spot * np.exp((r - q) * t)))
        iv = 0.24 + volatility_shift + 0.11 * k * k - 0.07 * k
        for option_type in ("call", "put"):
            price = black_scholes_price(spot, strike, t, r, q, iv, option_type)
            rows.append({
                "strike": strike,
                "option_type": option_type,
                "bid": max(0.001, price - 0.02),
                "ask": price + 0.02,
                "last_price": price,
                "open_interest": 800,
                "volume": 80,
                "implied_volatility": 2.0,
                "expiration": expiration,
                "valuation_date": "2026-08-05",
            })
    return pd.DataFrame(rows)


def _surface() -> dict:
    expiries = {
        "2026-08-21": _chain("2026-08-21", 16, 0.00),
        "2026-09-04": _chain("2026-09-04", 30, 0.075),
        "2026-10-16": _chain("2026-10-16", 72, 0.010),
        "2026-11-20": _chain("2026-11-20", 107, 0.015),
        "2027-01-15": _chain("2027-01-15", 163, 0.018),
        "2027-09-17": _chain("2027-09-17", 408, 0.020),
    }
    result = build_multi_expiry_surface(
        _lab(),
        expiries,
        list(expiries),
        risk_free_rate=0.04,
        dividend_yield=0.01,
        contract_style="European",
        max_relative_spread=1.0,
        valuation_date="2026-08-05",
    )
    assert result["ok"]
    assert result["potential_event_windows"] >= 1
    return result


def test_event_variance_estimate_is_positive_for_flagged_front_window():
    adjustments = estimate_event_variance_adjustments(_surface())
    flagged = adjustments[adjustments["potential_event_window"]]
    assert not flagged.empty
    assert float(flagged.iloc[0]["estimated_event_variance"]) > 0.0


def test_dataset_builds_weighted_train_holdout_and_caps_weights():
    result = build_calibration_dataset(_surface())
    assert result["ok"] is True
    assert result["version"] == CALIBRATION_DATASET_VERSION
    assert result["training_points"] >= 40
    assert result["holdout_points"] > 0
    assert result["training_maturities"] >= 4
    assert np.isclose(result["training_dataset"]["calibration_weight"].sum(), 1.0)
    assert result["maximum_quote_weight"] <= 0.0500001
    assert result["effective_sample_size"] >= 25.0
    assert {"target_total_variance", "target_iv", "vega_score", "liquidity_score", "quality_score"}.issubset(result["dataset"].columns)


def test_strip_event_policy_reduces_later_total_variance_but_keep_does_not():
    surface = _surface()
    stripped = build_calibration_dataset(surface, event_policy="Strip estimated discrete event variance")
    kept = build_calibration_dataset(surface, event_policy="Keep observed event premium")
    assert stripped["event_variance_removed_total"] > 0.0
    later = stripped["dataset"][stripped["dataset"]["event_variance_removed"] > 0.0]
    assert not later.empty
    assert np.all(later["target_total_variance"] < later["raw_total_variance"])
    assert np.allclose(kept["dataset"]["target_total_variance"], kept["dataset"]["raw_total_variance"])


def test_exclude_event_maturity_removes_flagged_end_expiry_from_training():
    surface = _surface()
    flagged_end = str(surface["event_diagnostics"].loc[surface["event_diagnostics"]["potential_event_window"], "window_end"].iloc[0])
    result = build_calibration_dataset(surface, event_policy="Exclude event-window maturity")
    assert flagged_end not in set(result["training_dataset"]["expiration"].astype(str))
    audit = result["dataset"][result["dataset"]["expiration"].astype(str) == flagged_end]
    assert not audit.empty
    assert set(audit["sample_role"]) == {"EXCLUDED"}


def test_maturity_holdout_is_deterministic_and_has_zero_calibration_weight():
    surface = _surface()
    first = build_calibration_dataset(surface, holdout_policy="Maturity holdout")
    second = build_calibration_dataset(surface, holdout_policy="Maturity holdout")
    assert first["configuration_signature"] == second["configuration_signature"]
    assert first["holdout_dataset"]["expiration"].astype(str).tolist() == second["holdout_dataset"]["expiration"].astype(str).tolist()
    assert np.allclose(first["holdout_dataset"]["calibration_weight"], 0.0)


def test_dataset_blocks_when_governance_minimums_are_impossible():
    result = build_calibration_dataset(_surface(), min_maturities=10, min_training_points=500)
    assert result["ok"] is False
    assert result["status"] == "BLOCKED"
    assert len(result["blockers"]) >= 2
