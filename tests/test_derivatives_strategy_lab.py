import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from derivatives_strategy_lab import (  # noqa: E402
    StrategyLeg,
    aggregate_strategy_greeks,
    black_scholes_greeks,
    black_scholes_price,
    build_cross_greek_shocks,
    build_greek_profile,
    build_template_legs,
    greek_leg_contributions,
    quote_quality,
    rank_strategy_templates,
    scenario_matrix,
    strategy_mark_pnl,
    strategy_pnl_at_expiry,
    summarize_strategy,
)


def option_leg(kind, side, strike, premium=0.0, iv=0.20, dte=365, quantity=1):
    return StrategyLeg(kind, side, quantity, strike, premium, iv, dte, 1.0, 1.1, f"{kind}-{strike}")


def sample_chain(kind: str) -> pd.DataFrame:
    strikes = np.arange(80.0, 121.0, 5.0)
    intrinsic = np.maximum(100.0 - strikes, 0.0) if kind == "put" else np.maximum(strikes - 100.0, 0.0)
    mids = 2.0 + intrinsic * 0.2 + np.abs(strikes - 100.0) * 0.04
    return pd.DataFrame({
        "strike": strikes,
        "bid": mids - 0.10,
        "ask": mids + 0.10,
        "mid": mids,
        "iv": 0.25 + np.abs(strikes / 100.0 - 1.0) * 0.15,
        "dte": 30,
    })


def test_black_scholes_atm_reference_values():
    greeks = black_scholes_greeks(100.0, 100.0, 365, 0.20, "call", rate=0.0, dividend=0.0)
    assert greeks["price"] == pytest.approx(7.9656, rel=2e-4)
    assert greeks["delta"] == pytest.approx(0.53983, rel=2e-4)
    assert greeks["gamma"] == pytest.approx(0.019848, rel=2e-4)
    assert greeks["vega_1vol"] == pytest.approx(0.39695, rel=2e-4)
    assert greeks["prob_itm"] < greeks["delta"]


def test_put_call_parity_with_dividend_yield():
    spot, strike, t, rate, dividend, iv = 123.0, 117.0, 0.7, 0.038, 0.012, 0.31
    call = black_scholes_price(spot, strike, t, rate, dividend, iv, "call")
    put = black_scholes_price(spot, strike, t, rate, dividend, iv, "put")
    parity = spot * math.exp(-dividend * t) - strike * math.exp(-rate * t)
    assert call - put == pytest.approx(parity, abs=1e-10)


def test_call_butterfly_expiry_profile_is_bounded_and_peaks_at_body():
    legs = [
        option_leg("call", 1, 90.0),
        option_leg("call", -1, 100.0, quantity=2),
        option_leg("call", 1, 110.0),
    ]
    pnl = strategy_pnl_at_expiry(legs, [80.0, 90.0, 100.0, 110.0, 120.0])
    assert pnl.tolist() == pytest.approx([0.0, 0.0, 1000.0, 0.0, 0.0])
    summary = summarize_strategy(legs, 100.0, 30, 0.25)
    assert summary.max_profit == pytest.approx(1000.0, abs=1.0)
    assert summary.max_loss == pytest.approx(0.0, abs=1e-8)
    assert summary.right_tail == "Payoff borné"


def test_short_strangle_flags_unbounded_right_tail():
    legs = [option_leg("put", -1, 90.0, premium=2.0), option_leg("call", -1, 110.0, premium=2.0)]
    summary = summarize_strategy(legs, 100.0, 30, 0.25)
    assert math.isinf(summary.max_loss)
    assert summary.max_profit == pytest.approx(400.0, abs=2.0)


def test_mark_to_model_converges_to_intrinsic_at_expiry():
    legs = [option_leg("call", 1, 100.0, premium=5.0, iv=0.25, dte=30)]
    marks = strategy_mark_pnl(legs, [90.0, 100.0, 110.0], 30)
    expiry = strategy_pnl_at_expiry(legs, [90.0, 100.0, 110.0])
    assert marks == pytest.approx(expiry)


def test_portfolio_delta_matches_finite_difference():
    legs = [option_leg("call", 1, 100.0, premium=8.0, iv=0.24, dte=90), option_leg("put", -1, 90.0, premium=3.0, iv=0.28, dte=90)]
    greeks = aggregate_strategy_greeks(legs, 100.0)
    bump = 0.01
    up = strategy_mark_pnl(legs, [100.0 + bump], 0)[0]
    down = strategy_mark_pnl(legs, [100.0 - bump], 0)[0]
    finite_delta = (up - down) / (2.0 * bump)
    assert greeks["delta"] == pytest.approx(finite_delta, rel=2e-5)


def test_scenario_matrix_has_complete_cartesian_grid():
    legs = [option_leg("call", 1, 100.0, premium=5.0, iv=0.25, dte=30)]
    matrix = scenario_matrix(legs, 100.0, 5, [-0.1, 0.0, 0.1], [-5.0, 0.0])
    assert matrix.shape == (6, 3)
    assert set(matrix.columns) == {"Spot shock", "IV shift", "P&L"}


def test_template_builder_uses_executable_side_prices():
    calls, puts = sample_chain("call"), sample_chain("put")
    legs = build_template_legs("Bull Call Spread", calls, puts, 100.0, 30, 0.25, 100.0, 2, 2, 1, "Exécutable (ask/bid)")
    assert len(legs) == 2
    assert legs[0].side == 1 and legs[0].premium == pytest.approx(legs[0].ask)
    assert legs[1].side == -1 and legs[1].premium == pytest.approx(legs[1].bid)
    assert legs[0].strike < legs[1].strike


def test_quote_quality_penalizes_wide_and_missing_markets():
    tight = [StrategyLeg("call", 1, 1, 100, 2.05, 0.2, 30, 2.0, 2.1)]
    wide = [StrategyLeg("call", 1, 1, 100, 3.0, 0.2, 30, 1.0, 5.0)]
    missing = [StrategyLeg("call", 1, 1, 100, 2.0, 0.2, 30, 0.0, 0.0)]
    assert quote_quality(tight)["score"] > quote_quality(wide)["score"]
    assert quote_quality(tight)["score"] > quote_quality(missing)["score"]


def test_strategy_ranker_respects_direction_and_volatility_view():
    bullish = rank_strategy_templates("Haussier", "Expansion", -0.20, 30, 90.0)
    neutral_short_vol = rank_strategy_templates("Neutre / range", "Compression", 0.35, 30, 90.0)
    assert bullish.iloc[0]["Stratégie"] in {"Long Call", "Risk Reversal", "Bull Call Spread"}
    assert neutral_short_vol.iloc[0]["Stratégie"] in {"Iron Butterfly", "Iron Condor", "Call Butterfly", "Short Strangle"}


@pytest.mark.parametrize(
    "greek",
    ["Delta", "Gamma", "Vega", "Theta", "Rho", "Vanna", "Vomma", "Charm", "Speed", "Color", "Zomma"],
)
def test_every_greek_has_a_finite_scenario_cube(greek):
    legs = [
        option_leg("call", 1, 100.0, premium=5.0, iv=0.25, dte=30),
        option_leg("put", -1, 95.0, premium=2.5, iv=0.28, dte=30),
    ]
    profile = build_greek_profile(legs, 100.0, greek, [0.9, 1.0, 1.1], [-5.0, 0.0, 5.0], [0, 5])
    assert profile.shape == (18, 6)
    assert profile["Greek"].eq(greek).all()
    assert np.isfinite(profile["Exposure"]).all()


@pytest.mark.parametrize(
    ("greek", "aggregate_key"),
    [
        ("Delta", "delta"),
        ("Gamma", "dollar_gamma_1pct"),
        ("Vega", "vega_1vol"),
        ("Theta", "theta_1d"),
        ("Rho", "rho_100bp"),
        ("Vanna", "vanna_1vol"),
        ("Vomma", "vomma_1vol2"),
        ("Charm", "charm_1d"),
        ("Speed", "speed"),
        ("Color", "color_1d"),
        ("Zomma", "zomma_1vol"),
    ],
)
def test_leg_contributions_reconcile_to_portfolio_greek(greek, aggregate_key):
    legs = [
        option_leg("call", 1, 100.0, premium=5.0, iv=0.25, dte=30),
        option_leg("put", -1, 95.0, premium=2.5, iv=0.28, dte=30),
        StrategyLeg("stock", 1, 25, premium=100.0, label="Actions"),
    ]
    contribution = greek_leg_contributions(legs, 100.0, greek)["Contribution"].sum()
    aggregate = aggregate_strategy_greeks(legs, 100.0)[aggregate_key]
    assert contribution == pytest.approx(aggregate, abs=1e-10)


def test_cross_greek_shocks_cover_all_risks_and_canonical_scenarios():
    legs = [option_leg("call", 1, 100.0, premium=5.0, iv=0.25, dte=30)]
    shocks = build_cross_greek_shocks(legs, 100.0)
    assert shocks.shape == (66, 6)
    assert shocks["Greek"].nunique() == 11
    assert shocks["Scénario"].nunique() == 6
    assert np.isfinite(shocks[["Base", "Après choc", "Variation"]]).all().all()


def test_streamlit_strategy_lab_harness_renders_without_exception():
    harness = Path(__file__).with_name("strategy_lab_harness.py")
    app = AppTest.from_file(str(harness), default_timeout=30).run()
    assert not app.exception
    labels = [tab.label for tab in app.tabs]
    assert labels[:2] == [
        "Payoff & Scénarios",
        "Greek Intelligence · 11",
    ]
    assert {"Vue des 11 Greeks", "Analyse individuelle", "Interactions & hedge"}.issubset(labels)
    assert {"Strategy Selector", "Risk & Execution"}.issubset(labels)
