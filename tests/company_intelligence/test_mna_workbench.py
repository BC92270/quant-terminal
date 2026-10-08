"""Deterministic regression coverage for the Company Intelligence M&A engine."""
from __future__ import annotations

from copy import deepcopy

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from company_intelligence.mna_workbench import (
    accretion_dilution_case,
    dcf_valuation,
    enterprise_value_bridge,
    relative_valuation_ranges,
    reverse_dcf_growth,
    simplified_ppa,
    synergy_npv,
    target_deal_case,
    extract_mna_facts,
)


def _dcf_facts(**overrides):
    facts = {
        "shares": 100.0,
        "debt": 200.0,
        "cash": 50.0,
        "price": 12.0,
    }
    facts.update(overrides)
    return facts


def _dcf_assumptions(**overrides):
    assumptions = {
        "base_fcf": 100.0,
        "wacc": 0.10,
        "terminal_growth": 0.025,
        "initial_growth": 0.12,
        "years": 5,
    }
    assumptions.update(overrides)
    return assumptions


def _target_facts(**overrides):
    facts = {
        "market_cap": 1_000.0,
        "debt": 200.0,
        "cash": 100.0,
        "price": 10.0,
        "shares": 100.0,
        "revenue": 500.0,
        "ebitda": 100.0,
        "ebit": 80.0,
        "net_income": 50.0,
        "free_cash_flow": 40.0,
        "coverage": 90.0,
    }
    facts.update(overrides)
    return facts


def _acquirer(**overrides):
    facts = {
        "price": 50.0,
        "shares": 100.0,
        "net_income": 500.0,
        "ebitda": 1_000.0,
        "debt": 1_000.0,
        "cash": 300.0,
        "free_cash_flow": 600.0,
        "market_cap": 5_000.0,
    }
    facts.update(overrides)
    return facts


def _transaction_target(**overrides):
    facts = {
        "equity_value": 2_000.0,
        "debt": 400.0,
        "cash": 100.0,
        "net_income": 100.0,
        "ebitda": 300.0,
        "free_cash_flow": 120.0,
    }
    facts.update(overrides)
    return facts


def _financing_assumptions(**overrides):
    assumptions = {
        "cash_pct": 0.20,
        "debt_pct": 0.30,
        "stock_pct": 0.50,
        "tax_rate": 0.25,
        "debt_interest_rate": 0.05,
        "cash_yield": 0.02,
        "pre_tax_synergies": 100.0,
        "incremental_amortization": 20.0,
        "integration_cost": 50.0,
    }
    assumptions.update(overrides)
    return assumptions


def test_enterprise_value_bridge_reconciles_every_component_and_blocks_missing_core_inputs():
    result = enterprise_value_bridge(
        1_000,
        250,
        125,
        preferred=20,
        minority_interest=30,
        lease_liabilities=40,
        unfunded_pensions=10,
        non_operating_investments=25,
    )

    assert result["status"] == "READY_FOR_HUMAN_REVIEW"
    assert result["enterprise_value"] == pytest.approx(1_200.0)
    assert sum(result["components"].values()) == pytest.approx(result["enterprise_value"])

    blocked = enterprise_value_bridge(1_000, None, float("nan"))
    assert blocked == {
        "status": "BLOCKED",
        "missing": ["debt", "cash"],
        "enterprise_value": None,
    }


def test_dcf_enforces_wacc_terminal_growth_spread_and_is_monotonic_in_wacc():
    facts = _dcf_facts()
    blocked = dcf_valuation(
        facts,
        _dcf_assumptions(wacc=0.04, terminal_growth=0.03),
    )
    low_wacc = dcf_valuation(facts, _dcf_assumptions(wacc=0.08))
    high_wacc = dcf_valuation(facts, _dcf_assumptions(wacc=0.12))

    assert blocked["status"] == "BLOCKED"
    assert "125 bps" in blocked["reason"]
    assert blocked["value_per_share"] is None
    assert low_wacc["status"] == high_wacc["status"] == "READY_FOR_HUMAN_REVIEW"
    assert low_wacc["value_per_share"] > high_wacc["value_per_share"]
    assert len(low_wacc["forecast"]) == 5


def test_reverse_dcf_recovers_the_growth_used_to_generate_the_market_price():
    assumptions = _dcf_assumptions(initial_growth=0.14)
    seed = dcf_valuation(_dcf_facts(), assumptions)
    facts = _dcf_facts(price=seed["value_per_share"])

    solved_growth = reverse_dcf_growth(facts, assumptions, low=-0.20, high=0.60)

    assert solved_growth == pytest.approx(0.14, abs=1e-7)
    repriced = dcf_valuation(facts, {**assumptions, "initial_growth": solved_growth})
    assert repriced["value_per_share"] == pytest.approx(facts["price"], rel=1e-8)


def test_synergy_npv_is_finite_horizon_risk_adjusted_and_net_of_integration_cost():
    result = synergy_npv(
        cost_synergy_run_rate=100.0,
        revenue_synergy_run_rate=200.0,
        contribution_margin=0.25,
        tax_rate=0.20,
        integration_cost=20.0,
        discount_rate=0.10,
        probability=0.50,
        ramp=(0.50, 1.00),
    )
    expected_cash_flows = [30.0, 60.0]
    expected_npv = -20.0 + 30.0 / 1.10 + 60.0 / (1.10**2)

    assert result["status"] == "READY_FOR_HUMAN_REVIEW"
    assert result["pre_tax_run_rate"] == pytest.approx(150.0)
    assert result["cash_flows"] == pytest.approx(expected_cash_flows)
    assert result["horizon_years"] == 2
    assert result["npv"] == pytest.approx(expected_npv)
    assert synergy_npv(
        cost_synergy_run_rate=100,
        revenue_synergy_run_rate=0,
        contribution_margin=0,
        tax_rate=0.2,
        integration_cost=0,
        discount_rate=-1,
    )["status"] == "BLOCKED"


def test_relative_valuation_requires_four_valid_peers_and_reconciles_ev_to_equity():
    peers = pd.DataFrame(
        [
            {"Symbol": "TGT", "Peer Type": "Target", "EV/Sales": 99, "EV/EBITDA": 99, "P/E TTM": 99},
            {"Symbol": "A", "Peer Type": "Peer", "EV/Sales": 1, "EV/EBITDA": 5, "P/E TTM": 10},
            {"Symbol": "B", "Peer Type": "Peer", "EV/Sales": 2, "EV/EBITDA": 6, "P/E TTM": 20},
            {"Symbol": "C", "Peer Type": "Peer", "EV/Sales": 3, "EV/EBITDA": 7, "P/E TTM": 30},
            {"Symbol": "D", "Peer Type": "Peer", "EV/Sales": 4, "EV/EBITDA": 8, "P/E TTM": 40},
        ]
    )
    facts = {
        "debt": 50.0,
        "cash": 10.0,
        "shares": 10.0,
        "price": 20.0,
        "revenue": 100.0,
        "ebitda": 20.0,
        "net_income": 10.0,
    }

    ranges = relative_valuation_ranges(facts, peers)
    revenue_median = ranges[
        ranges["Method"].eq("EV/Revenue") & ranges["Statistic"].eq("Median")
    ].iloc[0]
    ebitda_median = ranges[
        ranges["Method"].eq("EV/EBITDA") & ranges["Statistic"].eq("Median")
    ].iloc[0]
    pe_median = ranges[
        ranges["Method"].eq("P/E") & ranges["Statistic"].eq("Median")
    ].iloc[0]

    assert len(ranges) == 9
    assert set(ranges["Valid peers"]) == {4}
    assert revenue_median["Reference multiple"] == pytest.approx(2.5)
    assert revenue_median["Implied EV"] == pytest.approx(250.0)
    assert revenue_median["Implied equity"] == pytest.approx(210.0)
    assert revenue_median["Implied price"] == pytest.approx(21.0)
    assert ebitda_median["Implied price"] == pytest.approx(9.0)
    assert pe_median["Implied price"] == pytest.approx(25.0)

    only_three_peers = peers[~peers["Symbol"].isin(["TGT", "D"])]
    assert relative_valuation_ranges(facts, only_three_peers).empty


def test_target_deal_case_applies_control_premium_and_transaction_ev_bridge():
    facts = _target_facts()
    result = target_deal_case(facts, {"premium": 0.25})

    assert result["status"] == "READY_FOR_HUMAN_REVIEW"
    assert result["publishable"] is True
    assert result["offer_price"] == pytest.approx(12.50)
    assert result["offer_equity_value"] == pytest.approx(1_250.0)
    assert result["transaction_ev"] == pytest.approx(1_350.0)
    assert result["ev_revenue"] == pytest.approx(2.70)
    assert result["ev_ebitda"] == pytest.approx(13.50)
    assert result["price_earnings"] == pytest.approx(25.0)

    lower = target_deal_case(facts, {"premium": 0.10})
    assert result["offer_price"] > lower["offer_price"]
    assert result["transaction_ev"] > lower["transaction_ev"]


def test_fact_normalization_keeps_fcf_margin_on_the_displayed_period_basis():
    analysis = {
        "latest_price": 10.0,
        "company_analysis": {
            "profile": {"name": "Target", "market_cap": 1_000.0, "currency": "USD"},
            "growth": {"revenue_ttm": 500.0, "latest_net_income": 50.0, "latest_free_cash_flow": 100.0},
            "profitability": {"ebitda": 125.0},
            "valuation": {},
            "balance": {"total_cash": 100.0, "total_debt": 200.0, "fcf_margin": 0.05},
            "analysts": {},
            "forward": {},
            "raw_data": {"info": {"sharesOutstanding": 100.0}},
        },
    }

    facts = extract_mna_facts("TST", analysis)

    assert facts["free_cash_flow"] == pytest.approx(100.0)
    assert facts["revenue"] == pytest.approx(500.0)
    assert facts["fcf_margin"] == pytest.approx(0.20)


def test_target_deal_case_accepts_numeric_provider_scalars_after_validation():
    facts = {key: str(value) if isinstance(value, float) else value for key, value in _target_facts().items()}

    result = target_deal_case(facts, {"premium": "0.25"})

    assert result["transaction_ev"] == pytest.approx(1_350.0)
    assert result["ev_revenue"] == pytest.approx(2.70)
    assert result["ev_ebitda"] == pytest.approx(13.50)
    assert result["fcf_yield"] == pytest.approx(40.0 / 1_250.0)


def test_accretion_case_normalizes_sources_uses_and_reconciles_leverage():
    result = accretion_dilution_case(
        _acquirer(),
        _transaction_target(),
        _financing_assumptions(),
    )

    assert result["status"] == "READY_FOR_HUMAN_REVIEW"
    assert result["publishable"] is True
    assert result["weights"] == pytest.approx({"cash": 0.20, "debt": 0.30, "stock": 0.50})
    assert result["funding"] == pytest.approx({"cash": 400.0, "debt": 600.0, "stock": 1_000.0})
    assert result["sources_uses_gap"] == pytest.approx(0.0, abs=1e-12)
    assert result["new_shares"] == pytest.approx(20.0)
    assert result["proforma_shares"] == pytest.approx(120.0)
    assert result["standalone_eps"] == pytest.approx(5.0)
    assert result["recurring_eps"] == pytest.approx(631.5 / 120.0)
    assert result["year_one_eps"] == pytest.approx(594.0 / 120.0)
    assert result["pf_gross_debt"] == pytest.approx(2_000.0)
    assert result["pf_cash"] == pytest.approx(0.0)
    assert result["pf_net_debt"] == pytest.approx(2_000.0)
    assert result["net_leverage_reported"] == pytest.approx(2_000.0 / 1_300.0)
    assert result["net_leverage_adjusted"] == pytest.approx(2_000.0 / 1_400.0)


def test_accretion_case_blocks_incomplete_input_and_zero_financing_mix():
    incomplete = accretion_dilution_case(
        _acquirer(net_income=None),
        _transaction_target(),
        _financing_assumptions(),
    )
    zero_mix = accretion_dilution_case(
        _acquirer(),
        _transaction_target(),
        _financing_assumptions(cash_pct=0, debt_pct=0, stock_pct=0),
    )

    assert incomplete["status"] == "BLOCKED"
    assert "acquirer.net_income" in incomplete["missing"]
    assert incomplete["publishable"] is False
    assert zero_mix["status"] == "BLOCKED"
    assert zero_mix["missing"] == ["financing_mix"]
    assert zero_mix["publishable"] is False


def test_ppa_flags_negative_goodwill_for_bargain_purchase_review():
    bargain = simplified_ppa(consideration=500.0, target_book_equity=600.0)
    provisional = simplified_ppa(
        consideration=1_000.0,
        target_book_equity=600.0,
        identifiable_intangibles_step_up=100.0,
        ppe_step_up=50.0,
        inventory_step_up=20.0,
        liability_step_up=10.0,
        tax_rate=0.20,
        intangible_life_years=10,
    )

    assert bargain["status"] == "BARGAIN_PURCHASE_REVIEW"
    assert bargain["goodwill"] == pytest.approx(-100.0)
    assert provisional["status"] == "PROVISIONAL_ASSUMPTION"
    assert provisional["deferred_tax_liability"] == pytest.approx(32.0)
    assert provisional["fair_value_net_assets"] == pytest.approx(728.0)
    assert provisional["goodwill"] == pytest.approx(272.0)
    assert provisional["annual_intangible_amortization"] == pytest.approx(10.0)


def test_calculation_engines_do_not_mutate_caller_inputs():
    target_facts = _target_facts()
    target_assumptions = {
        "premium": 0.20,
        "synergy_ramp": [0.25, 0.65, 1.0],
    }
    dcf_facts = _dcf_facts()
    dcf_assumptions = _dcf_assumptions()
    acquirer = _acquirer()
    target = _transaction_target()
    financing = _financing_assumptions()
    peers = pd.DataFrame(
        [
            {"Peer Type": "Peer", "EV/Sales": value, "EV/EBITDA": value + 4, "P/E TTM": value * 10}
            for value in (1.0, 2.0, 3.0, 4.0)
        ]
    )
    snapshots = {
        "target_facts": deepcopy(target_facts),
        "target_assumptions": deepcopy(target_assumptions),
        "dcf_facts": deepcopy(dcf_facts),
        "dcf_assumptions": deepcopy(dcf_assumptions),
        "acquirer": deepcopy(acquirer),
        "target": deepcopy(target),
        "financing": deepcopy(financing),
        "peers": peers.copy(deep=True),
    }

    target_deal_case(target_facts, target_assumptions)
    dcf_valuation(dcf_facts, dcf_assumptions)
    reverse_dcf_growth(dcf_facts, dcf_assumptions)
    relative_valuation_ranges(
        {
            "debt": 50.0,
            "cash": 10.0,
            "shares": 10.0,
            "price": 20.0,
            "revenue": 100.0,
            "ebitda": 20.0,
            "net_income": 10.0,
        },
        peers,
    )
    accretion_dilution_case(acquirer, target, financing)

    assert target_facts == snapshots["target_facts"]
    assert target_assumptions == snapshots["target_assumptions"]
    assert dcf_facts == snapshots["dcf_facts"]
    assert dcf_assumptions == snapshots["dcf_assumptions"]
    assert acquirer == snapshots["acquirer"]
    assert target == snapshots["target"]
    assert financing == snapshots["financing"]
    pd.testing.assert_frame_equal(peers, snapshots["peers"])


def test_all_five_workflows_and_both_deal_lenses_render_offline():
    app = AppTest.from_file(
        "tests/company_intelligence/mna_ui_harness.py",
        default_timeout=30,
    ).run()

    assert not app.exception
    assert app.radio[0].value == "DES · Company 360"
    for command in (
        "RV · Relative Value",
        "FA · Financial Analysis",
        "DOWW · Deal Watch",
        "BI · Intelligence",
    ):
        app.radio[0].set_value(command).run()
        assert not app.exception, command

    app.radio[0].set_value("DOWW · Deal Watch").run()
    app.radio[1].set_value("Acquirer / accretion case").run()
    assert not app.exception
    assert any(metric.label == "PF net leverage" for metric in app.metric)
    assert app.text_input[0].value == "TST · Acquirer / accretion case"
