from __future__ import annotations

import numpy as np
import pandas as pd

from market_psychology.engine import build_psychology_state, build_scenario_monitor
from market_psychology.latent_state import (
    acute_alarm_level,
    adaptive_alarm_level,
    causal_local_level_filter,
    causal_robust_normalize,
    structural_state_label,
)


def _frame(seed: int, start: float, vol: float, drift: float, n: int = 650) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2023-01-02", periods=n, freq="B", tz="UTC")
    ret = drift + vol * rng.normal(size=n)
    close = start * np.exp(np.cumsum(ret))
    return pd.DataFrame({
        "date": dates,
        "open": close * (1 + rng.normal(0, .002, n)),
        "high": close * (1 + np.abs(rng.normal(0, .004, n))),
        "low": close * (1 - np.abs(rng.normal(0, .004, n))),
        "close": close,
        "volume": np.maximum(1.0, 8e6 * (1 + rng.normal(0, .25, n))),
    })


def test_filter_is_one_sided_and_smoother() -> None:
    raw = pd.Series([np.nan] * 5 + [50, 51, 49, 100, 48, 50, 52, 49] * 20, dtype=float)
    f = causal_local_level_filter(raw)
    assert len(f) == len(raw)
    # Initial missing values must not be filled from a future first observation.
    assert f["latent"].iloc[:5].isna().all()
    valid = f["latent"].dropna()
    assert valid.between(0, 100).all()
    assert valid.diff().abs().mean() < raw.dropna().diff().abs().mean()


def test_causal_normalization_recentres_structural_proxy() -> None:
    rng = np.random.default_rng(123)
    raw = pd.Series(82 + rng.normal(0, 3, 500), dtype=float)
    n = causal_robust_normalize(raw)
    calibrated = n["normalized"].dropna().tail(200)
    assert len(calibrated) >= 150
    # A proxy structurally centred around ~82 should map back near the behavioural centre.
    assert 42 <= float(calibrated.median()) <= 58


def test_legacy_adaptive_alarm_level_stays_compatible() -> None:
    assert adaptive_alarm_level(50, 40, 0)[0] == "NORMAL"
    assert adaptive_alarm_level(60, 80, 0)[0] == "WATCH"
    assert adaptive_alarm_level(74, 95, 0)[0] == "HIGH"
    assert adaptive_alarm_level(85, 99, 0)[0] == "CRITICAL"


def test_structural_state_is_not_acute_alarm() -> None:
    assert structural_state_label(85)[0] == "EXTREME"
    # Long-standing high state + ordinary/negative shock is not an acute event.
    assert acute_alarm_level("herding", 85, 37, -0.6, 0.05, 0.0)[0] == "NORMAL"
    # Negative Fear shock is relief, not stress.
    assert acute_alarm_level("fear", 44, 16, -2.3, -0.8, -0.1)[0] == "NORMAL"
    # Positive Fear shock can trigger an acute stress alert.
    assert acute_alarm_level("fear", 70, 90, 2.5, 0.8, 0.1)[0] in {"HIGH", "CRITICAL"}


def test_post_capitulation_requires_recent_extreme_fear() -> None:
    dates = pd.date_range("2025-01-01", periods=120, freq="B", tz="UTC")
    history = pd.DataFrame({"date": dates, "fear_latent": np.full(len(dates), 48.0)})
    latent = pd.DataFrame([
        {"Key": "fear", "5D velocity": -1.0, "Acceleration": -0.1, "Persistence": 70, "Shock z": -1.0},
        {"Key": "extrapolation", "5D velocity": 0.8, "Acceleration": 0.1, "Persistence": 70},
        {"Key": "attention", "5D velocity": 0.0, "Acceleration": 0.0, "Persistence": 70},
        {"Key": "herding", "5D velocity": 0.0, "Acceleration": 0.0, "Persistence": 70},
        {"Key": "reflexivity", "5D velocity": 0.0, "Acceleration": 0.0, "Persistence": 70},
    ])
    scores = {
        "fear": 48, "attention": 45, "extrapolation": 45, "narrative": 50,
        "herding": 50, "higher_order": 50, "confidence": 50, "disagreement": 50,
        "ambiguity": 50, "reflexivity": 50, "mechanical_reflexivity": 50,
        "risk_appetite": 55, "lottery_demand": 50, "arbitrage_capacity": 55,
    }
    out = build_scenario_monitor(scores, latent_table=latent, history=history)
    row = out[out["Scenario"] == "POST-CAPITULATION"].iloc[0]
    assert row["Gate"] == "FAIL"
    assert row["Status"] == "GATED"
    assert float(row["Match"]) <= 47


def test_full_state_bundle() -> None:
    pack = {
        "SPY": _frame(1, 400, .009, .0004),
        "QQQ": _frame(2, 300, .011, .0005),
        "IWM": _frame(3, 190, .013, .0002),
        "HYG": _frame(4, 75, .003, .0001),
        "TLT": _frame(5, 95, .006, .0000),
        "GLD": _frame(6, 180, .006, .0002),
        "^VIX": _frame(7, 18, .025, .0000),
    }
    news = pd.DataFrame([
        {"title": "AI chip demand surges as earnings beat", "summary": "strong growth", "published": "2026-08-10"},
        {"title": "Fed rate uncertainty remains", "summary": "inflation risk", "published": "2026-08-09"},
    ] * 5)
    options = {
        "available": True,
        "put_call_volume": .95,
        "put_call_oi": 1.05,
        "near_term_share": .60,
        "call_volume": 400_000,
        "put_volume": 380_000,
        "rows": 700,
        "call_iv": .24,
        "put_iv": .31,
    }
    state = build_psychology_state("SPY", pack, news, options)
    assert state["available"] is True
    assert state["latent_coverage"] == 5
    assert len(state["latent_state"]) == 5
    assert not state["history"].empty
    assert "attention_raw" in state["history"].columns
    assert "attention_normalized" in state["history"].columns
    assert "attention_latent" in state["history"].columns
    assert {"Structural state", "Acute alarm", "Shock direction"}.issubset(state["latent_state"].columns)
    assert {"Structural State", "Acute Alarm"}.issubset(state["alerts"].columns)
    assert not state["scenarios"].empty
    assert state["evidence_quality_label"] in {"LOW", "MEDIUM", "HIGH"}


if __name__ == "__main__":
    test_filter_is_one_sided_and_smoother()
    test_causal_normalization_recentres_structural_proxy()
    test_legacy_adaptive_alarm_level_stays_compatible()
    test_structural_state_is_not_acute_alarm()
    test_post_capitulation_requires_recent_extreme_fear()
    test_full_state_bundle()
    print("Market Psychology V2.0.1 calibration smoke tests: PASS")
