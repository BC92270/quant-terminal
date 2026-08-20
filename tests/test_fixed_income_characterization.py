from datetime import date

import numpy as np
import pandas as pd

import fixed_income_credit as legacy
from fixed_income.analytics.portfolio import optimize_portfolio
from fixed_income.analytics.refinancing import analyze_refinancing_schedule
from fixed_income.research.decision import audit_point_in_time, diagnose_decisions


def test_bond_price_yield_round_trip() -> None:
    spec = legacy.BondSpec(
        face_value=100.0,
        coupon_rate=0.0525,
        settlement_date=date(2026, 1, 15),
        maturity_date=date(2031, 1, 15),
        coupon_frequency=2,
    )
    clean = legacy.clean_price_from_ytm(spec, 0.0475)
    recovered = legacy.ytm_from_clean_price(spec, clean)
    risk = legacy.bond_risk_metrics(spec, recovered)
    assert recovered == pytest.approx(0.0475, abs=1e-10)
    assert risk["modified_duration"] > 0.0
    assert risk["dv01"] > 0.0
    assert risk["convexity"] > 0.0


def test_portfolio_wrapper_matches_modular_engine() -> None:
    universe = legacy._fic7_default_universe()
    wrapped = legacy.fixed_income_portfolio_optimizer(universe)
    modular = optimize_portfolio(universe)
    assert wrapped["errors"] == []
    assert modular["errors"] == []
    assert np.allclose(
        wrapped["assets"]["optimized_weight_pct"],
        modular["assets"]["optimized_weight_pct"],
        atol=1e-10,
    )
    assert wrapped["assets"]["optimized_weight_pct"].sum() == pytest.approx(100.0)
    assert wrapped["sectors"]["optimized_weight_pct"].max() <= 35.0 + 1e-8
    assert wrapped["metrics"]["covariance_min_eigenvalue"] >= -1e-10


def test_refinancing_characterization() -> None:
    schedule = pd.DataFrame(
        {
            "year": [2027, 2028],
            "debt_due": [100.0, 200.0],
            "coupon_pct": [3.0, 4.0],
            "benchmark_pct": [4.0, 4.0],
            "current_spread_bp": [100.0, 100.0],
            "refi_spread_bp": [150.0, 175.0],
            "secured_pct": [0.0, 0.0],
        }
    )
    wrapped_rows, wrapped = legacy.refinancing_schedule_analytics(
        schedule, cash=100.0, revolver=50.0, annual_fcf=25.0
    )
    modular_rows, modular = analyze_refinancing_schedule(
        schedule, cash=100.0, revolver=50.0, annual_fcf=25.0
    )
    pd.testing.assert_frame_equal(wrapped_rows, modular_rows)
    assert wrapped == modular
    assert wrapped["total_debt_due"] == 300.0
    assert wrapped["liquidity_coverage_24m"] == pytest.approx(2.0 / 3.0)


def test_decision_and_pit_characterization() -> None:
    journal = pd.DataFrame(
        {
            "decision_date": ["2026-01-01"],
            "review_date": ["2026-02-01"],
            "issuer": ["Issuer X"],
            "instrument": ["X 5Y"],
            "decision": ["BUY"],
            "conviction_pct": [70.0],
            "entry_spread_bp": [150.0],
            "exit_spread_bp": [110.0],
            "status": ["CLOSED"],
            "thesis": ["Compression"],
            "invalidation_trigger": ["Leverage deterioration"],
        }
    )
    wrapped_rows, wrapped = legacy.decision_journal_diagnostics(journal)
    modular_rows, modular = diagnose_decisions(journal)
    pd.testing.assert_frame_equal(wrapped_rows, modular_rows)
    assert wrapped == modular
    assert wrapped["hit_rate_pct"] == 100.0
    assert wrapped["average_alpha_bp"] == 40.0

    pit = pd.DataFrame(
        {
            "series": ["REVISION_SENSITIVE"],
            "observation_date": ["2026-01-01"],
            "available_date": ["2026-02-01"],
            "decision_date": ["2026-01-15"],
            "value": [1.0],
        }
    )
    audited, metrics = audit_point_in_time(pit)
    assert bool(audited.loc[0, "leakage_flag"])
    assert metrics["leakage_rate_pct"] == 100.0


def test_blank_research_inputs_do_not_create_false_evidence() -> None:
    journal, journal_metrics = diagnose_decisions(legacy._fic7_blank_journal())
    pit, pit_metrics = audit_point_in_time(legacy._fic7_blank_pit())
    assert journal.empty
    assert journal_metrics["decisions"] == 0.0
    assert pit.empty
    assert pit_metrics["rows"] == 0.0


import pytest
