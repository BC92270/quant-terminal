"""Deterministic regression coverage for the Company Intelligence M&A engine."""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import company_intelligence.mna_workbench as mna_workbench

from company_intelligence.mna_workbench import (
    accretion_dilution_case,
    build_acquirer_scenario_comparison,
    build_eps_bridge,
    build_football_field,
    build_leverage_trajectory,
    build_scenario_comparison,
    build_sources_uses_bridge,
    build_synergy_ramp,
    dcf_valuation,
    enterprise_value_bridge,
    filter_peer_universe,
    relative_valuation_ranges,
    reverse_dcf_growth,
    simplified_ppa,
    synergy_npv,
    target_deal_case,
    validate_deal_identities,
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
        "cash_available": 500.0,
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


def test_peer_filter_is_immutable_and_records_exclusion_rationale():
    peers = pd.DataFrame(
        [
            {"Symbol": "TGT", "Peer Type": "Target", "EV/EBITDA": 20.0},
            {"Symbol": "AAA", "Peer Type": "Peer", "EV/EBITDA": 10.0},
            {"Symbol": "BBB", "Peer Type": "Peer", "EV/EBITDA": 12.0},
        ]
    )
    before = peers.copy(deep=True)

    selected, audit = filter_peer_universe(peers, ["AAA"], exclusion_rationale="Different end market")

    assert selected["Symbol"].tolist() == ["TGT", "AAA"]
    assert audit.set_index("Symbol").loc["BBB", "Decision"] == "EXCLUDED"
    assert audit.set_index("Symbol").loc["BBB", "Rationale"] == "Different end market"
    pd.testing.assert_frame_equal(peers, before)


def test_scenario_comparison_and_football_field_keep_ordered_explicit_ranges():
    facts = _target_facts(revenue_growth=0.10, currency="USD")
    scenarios = build_scenario_comparison(facts)
    peer_ranges = pd.DataFrame(
        [
            {"Method": "EV/EBITDA", "Statistic": "25th", "Implied price": 8.0},
            {"Method": "EV/EBITDA", "Statistic": "Median", "Implied price": 10.0},
            {"Method": "EV/EBITDA", "Statistic": "75th", "Implied price": 12.0},
        ]
    )
    sensitivity = pd.DataFrame([{"WACC": 0.09, "g 2.0%": 9.0, "g 3.0%": 11.0}])

    field = build_football_field(facts, peer_ranges, scenarios, sensitivity)

    assert scenarios["Scenario"].tolist() == ["Bear", "Base", "Bull"]
    assert scenarios["Offer price"].is_monotonic_increasing
    assert scenarios["Offer premium"].tolist() == pytest.approx([0.15, 0.30, 0.45])
    assert {"Peer EV/EBITDA", "DCF sensitivity", "Control premium"}.issubset(set(field["Method"]))
    assert (field["Low"] <= field["Mid"]).all()
    assert (field["Mid"] <= field["High"]).all()


def test_transaction_bridges_reconcile_and_leverage_rolls_down():
    acquirer = _acquirer()
    target = _transaction_target()
    assumptions = _financing_assumptions(
        debt_refinanced=200.0,
        transaction_fees=100.0,
        cash_available=1_000.0,
    )
    result = accretion_dilution_case(acquirer, target, assumptions)

    sources_uses = build_sources_uses_bridge(target, result)
    eps_bridge = build_eps_bridge(acquirer, target, result)
    leverage = build_leverage_trajectory(result, annual_paydown=200.0, years=3)
    scenario_matrix = build_acquirer_scenario_comparison(acquirer, target, assumptions)
    identities = validate_deal_identities(acquirer, target, result)

    assert result["status"] == "READY_FOR_HUMAN_REVIEW"
    relative_sources_uses = sources_uses[sources_uses["Measure"].eq("relative")]["Bridge value"].sum()
    assert relative_sources_uses == pytest.approx(-result["sources_uses_gap"])
    recurring_steps = eps_bridge.iloc[:6]["Value"].sum()
    assert recurring_steps == pytest.approx(result["recurring_net_income"])
    assert result["recurring_net_income"] - result["after_tax_integration"] == pytest.approx(result["year_one_net_income"])
    assert leverage["Net debt"].is_monotonic_decreasing
    assert leverage["Reported leverage"].is_monotonic_decreasing
    assert (leverage["Net debt"] >= 0).all()
    assert scenario_matrix["Scenario"].tolist() == ["Bear", "Base", "Bull"]
    assert set(identities["State"]) == {"PASS"}

    tampered = dict(result)
    tampered["proforma_shares"] = result["proforma_shares"] + 1.0
    tampered_identities = validate_deal_identities(acquirer, target, tampered)
    assert tampered_identities.set_index("Identity").loc["Share roll-forward", "State"] == "BLOCKED"


def test_cash_capacity_and_non_reconciling_financing_mix_fail_closed():
    cash_blocked = accretion_dilution_case(
        _acquirer(),
        _transaction_target(),
        _financing_assumptions(cash_available=100.0),
    )
    mix_blocked = accretion_dilution_case(
        _acquirer(),
        _transaction_target(),
        _financing_assumptions(cash_pct=0.20, debt_pct=0.30, stock_pct=0.40),
    )

    assert cash_blocked["status"] == "BLOCKED"
    assert cash_blocked["liquidity_ok"] is False
    assert cash_blocked["cash_shortfall"] == pytest.approx(300.0)
    assert "cash_funding_capacity" in cash_blocked["missing"]
    assert mix_blocked["status"] == "BLOCKED"
    assert mix_blocked["missing"] == ["financing_mix_total"]


def test_ppa_amortization_flows_into_eps_and_synergy_schedule_reconciles_npv():
    no_amortization = accretion_dilution_case(
        _acquirer(),
        _transaction_target(),
        _financing_assumptions(incremental_amortization=0.0),
    )
    with_amortization = accretion_dilution_case(
        _acquirer(),
        _transaction_target(),
        _financing_assumptions(incremental_amortization=40.0),
    )
    synergy = synergy_npv(
        cost_synergy_run_rate=100.0,
        revenue_synergy_run_rate=100.0,
        contribution_margin=0.50,
        tax_rate=0.20,
        integration_cost=25.0,
        discount_rate=0.10,
        probability=0.75,
        ramp=(0.25, 0.75, 1.0),
    )
    schedule = build_synergy_ramp(synergy)

    assert no_amortization["recurring_net_income"] - with_amortization["recurring_net_income"] == pytest.approx(30.0)
    assert with_amortization["after_tax_amortization"] == pytest.approx(30.0)
    assert schedule["Present value"].sum() - synergy["integration_cost"] == pytest.approx(synergy["npv"])
    assert schedule["Cumulative synergy FCF"].iloc[-1] == pytest.approx(schedule["After-tax risk-adjusted FCF"].sum())


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


def test_scoped_scenario_defaults_refresh_active_conditional_view(monkeypatch):
    state = {
        "mna_profile_loaded_NVDA": "Base",
        "mna_buy_cash_pct_NVDA": 35,
        "mna_buy_debt_pct_NVDA": 35,
        "mna_target_premium_NVDA": 99,
    }
    monkeypatch.setattr(mna_workbench, "st", SimpleNamespace(session_state=state))
    facts = {
        "market_cap": 5_570_000_000_000.0,
        "cash": 34_650_000_000.0,
        "revenue": 215_940_000_000.0,
        "ebitda": 144_550_000_000.0,
        "revenue_growth": 0.65,
    }

    mna_workbench._sync_scenario_defaults("NVDA", facts, "Base", "acquirer")

    assert state["mna_buy_cash_pct_NVDA"] == 5
    assert state["mna_buy_debt_pct_NVDA"] == 35
    assert state["mna_target_premium_NVDA"] == 99
    assert state["mna_profile_loaded_NVDA_acquirer"] == f"{mna_workbench.SCENARIO_PROFILE_SCHEMA_VERSION} · Base"
    assert state["mna_buy_cash_pct_NVDA__persisted"] == 5
    assert state["mna_buy_debt_pct_NVDA__persisted"] == 35

    # A normal rerun preserves edits already present in the active view.
    state["mna_buy_cash_pct_NVDA"] = 0
    state["mna_buy_debt_pct_NVDA"] = 70
    mna_workbench._sync_scenario_defaults("NVDA", facts, "Base", "acquirer")
    assert state["mna_buy_cash_pct_NVDA"] == 0
    assert state["mna_buy_debt_pct_NVDA"] == 70

    # Leaving the view captures the edits; re-entering after Streamlit's widget
    # cleanup restores them from non-widget backing keys.
    mna_workbench._persist_scenario_inputs("NVDA")
    del state["mna_buy_cash_pct_NVDA"]
    del state["mna_buy_debt_pct_NVDA"]
    mna_workbench._sync_scenario_defaults("NVDA", facts, "Base", "acquirer")
    assert state["mna_buy_cash_pct_NVDA"] == 0
    assert state["mna_buy_debt_pct_NVDA"] == 70

    # If no analyst-backed value exists, the same-profile re-entry still
    # repopulates capacity-aware defaults instead of widget literals.
    for suffix in ("buy_cash_pct", "buy_debt_pct"):
        del state[f"mna_{suffix}_NVDA"]
        del state[f"mna_{suffix}_NVDA__persisted"]
    mna_workbench._sync_scenario_defaults("NVDA", facts, "Base", "acquirer")
    assert state["mna_buy_cash_pct_NVDA"] == 5
    assert state["mna_buy_debt_pct_NVDA"] == 35

    mna_workbench._sync_scenario_defaults("NVDA", facts, "Base", "target")
    assert state["mna_target_premium_NVDA"] == 30


def test_linked_valuation_anchor_survives_target_widget_cleanup(monkeypatch):
    state: dict[str, object] = {}
    monkeypatch.setattr(mna_workbench, "st", SimpleNamespace(session_state=state))
    facts = {
        "market_cap": 5_570_000_000_000.0,
        "cash": 34_650_000_000.0,
        "revenue": 215_940_000_000.0,
        "ebitda": 144_550_000_000.0,
        "revenue_growth": 0.65,
    }

    # The Apply handlers first synchronize the complete target profile, then
    # override only the linked valuation anchor. This prevents hybrid profiles.
    mna_workbench._sync_scenario_defaults("NVDA", facts, "Bull", "target")
    assert state["mna_target_discount_NVDA"] == 9.5
    mna_workbench._sync_scenario_defaults("NVDA", facts, "Base", "target")
    mna_workbench._set_scenario_input("NVDA", "target_premium", 42)
    del state["mna_target_premium_NVDA"]
    mna_workbench._sync_scenario_defaults("NVDA", facts, "Base", "target")

    assert state["mna_target_premium_NVDA"] == 42
    assert state["mna_target_premium_NVDA__persisted"] == 42
    assert state["mna_target_discount_NVDA"] == 11.0
    assert state["mna_target_probability_NVDA"] == 70
    assert state["mna_profile_loaded_NVDA_target"] == f"{mna_workbench.SCENARIO_PROFILE_SCHEMA_VERSION} · Base"

    state["mna_ctx_anchor_NVDA"] = "RV · EV / EBITDA Median"
    mna_workbench._sync_scenario_defaults("NVDA", facts, "Bull", "target")
    assert state["mna_target_premium_NVDA"] == 45
    assert state["mna_ctx_anchor_NVDA"] == "Scenario profile · Bull"


def test_non_profile_inputs_restore_for_every_conditional_scope(monkeypatch):
    signature = f"{mna_workbench.SCENARIO_PROFILE_SCHEMA_VERSION} · Base"
    state: dict[str, object] = {
        "mna_profile_loaded_TST_target": signature,
        "mna_profile_loaded_TST_fa": signature,
        "mna_profile_loaded_TST_acquirer": signature,
        "mna_target_tax_TST": 27.0,
        "mna_fa_fcf_TST": 4.2,
        "mna_buy_target_equity_TST": 12.5,
        "mna_ppa_book_TST": 3.3,
    }
    monkeypatch.setattr(mna_workbench, "st", SimpleNamespace(session_state=state))
    facts = {
        "market_cap": 100_000_000_000.0,
        "cash": 10_000_000_000.0,
        "revenue": 20_000_000_000.0,
        "ebitda": 5_000_000_000.0,
        "revenue_growth": 0.15,
    }

    mna_workbench._persist_scenario_inputs("TST")
    for key in (
        "mna_target_tax_TST",
        "mna_fa_fcf_TST",
        "mna_buy_target_equity_TST",
        "mna_ppa_book_TST",
    ):
        del state[key]

    for scope in ("target", "fa", "acquirer"):
        mna_workbench._sync_scenario_defaults("TST", facts, "Base", scope)

    assert state["mna_target_tax_TST"] == 27.0
    assert state["mna_fa_fcf_TST"] == 4.2
    assert state["mna_buy_target_equity_TST"] == 12.5
    assert state["mna_ppa_book_TST"] == 3.3


def test_cross_ticker_capture_and_conditional_option_reconciliation(monkeypatch):
    signature = f"{mna_workbench.SCENARIO_PROFILE_SCHEMA_VERSION} · Base"
    state: dict[str, object] = {
        "mna_profile_loaded_NVDA_target": signature,
        "mna_target_tax_NVDA": 29.0,
        "mna_deal_lens_NVDA": "Acquirer / accretion case",
        "mna_rv_peers_NVDA": ["AAA", "STALE"],
        "mna_ctx_owner_NVDA": "Deal team A",
        "mna_command_NVDA": "DOWW · Deal Watch",
    }
    monkeypatch.setattr(mna_workbench, "st", SimpleNamespace(session_state=state))

    mna_workbench._persist_all_scenario_inputs()
    mna_workbench._persist_conditional_view_inputs()
    del state["mna_target_tax_NVDA"]
    del state["mna_deal_lens_NVDA"]
    del state["mna_rv_peers_NVDA"]
    del state["mna_ctx_owner_NVDA"]
    del state["mna_command_NVDA"]

    facts = {
        "market_cap": 5_570_000_000_000.0,
        "cash": 34_650_000_000.0,
        "revenue": 215_940_000_000.0,
        "ebitda": 144_550_000_000.0,
        "revenue_growth": 0.65,
    }
    mna_workbench._sync_scenario_defaults("NVDA", facts, "Base", "target")
    mna_workbench._restore_conditional_widget(
        "mna_deal_lens_NVDA",
        "Target / takeover screen",
        options=["Target / takeover screen", "Acquirer / accretion case"],
    )
    mna_workbench._restore_conditional_widget(
        "mna_rv_peers_NVDA",
        ["AAA", "BBB"],
        options=["AAA", "BBB"],
        multiple=True,
    )
    mna_workbench._restore_conditional_widget("mna_ctx_owner_NVDA", "Unassigned")
    mna_workbench._restore_conditional_widget(
        "mna_command_NVDA",
        "DES · Company 360",
        options=["DES · Company 360", "DOWW · Deal Watch"],
    )
    state["mna_rv_anchor_choice_NVDA"] = "Stale implied-price label"
    mna_workbench._restore_conditional_widget(
        "mna_rv_anchor_choice_NVDA",
        "EV / EBITDA · Median",
        options=["EV / EBITDA · Median", "P/E · Median"],
    )
    state["mna_bi_classes_NVDA"] = ["Stale class"]
    mna_workbench._restore_conditional_widget(
        "mna_bi_classes_NVDA",
        ["Operating"],
        options=["Operating", "Structural"],
        multiple=True,
    )

    assert state["mna_target_tax_NVDA"] == 29.0
    assert state["mna_deal_lens_NVDA"] == "Acquirer / accretion case"
    assert state["mna_rv_peers_NVDA"] == ["AAA"]
    assert state["mna_ctx_owner_NVDA"] == "Deal team A"
    assert state["mna_command_NVDA"] == "DOWW · Deal Watch"
    assert state["mna_rv_anchor_choice_NVDA"] == "EV / EBITDA · Median"
    assert state["mna_bi_classes_NVDA"] == ["Operating"]


def test_acquirer_funding_restore_is_normalized_before_slider_render(monkeypatch):
    signature = f"{mna_workbench.SCENARIO_PROFILE_SCHEMA_VERSION} · Base"
    state: dict[str, object] = {
        "mna_profile_loaded_TST_acquirer": signature,
        "mna_buy_cash_pct_TST__persisted": 80,
        "mna_buy_debt_pct_TST__persisted": 35,
    }
    monkeypatch.setattr(mna_workbench, "st", SimpleNamespace(session_state=state))
    facts = {
        "market_cap": 100_000_000_000.0,
        "cash": 10_000_000_000.0,
        "revenue": 20_000_000_000.0,
        "ebitda": 5_000_000_000.0,
        "revenue_growth": 0.15,
    }

    mna_workbench._sync_scenario_defaults("TST", facts, "Base", "acquirer")

    assert state["mna_buy_cash_pct_TST"] == 80
    assert state["mna_buy_debt_pct_TST"] == 20
    assert state["mna_buy_debt_pct_TST__persisted"] == 20


def test_diligence_routing_is_workstream_specific_and_fail_closed():
    facts = {
        "coverage": 100.0,
        "price": 100.0,
        "shares": 1_000_000_000.0,
        "market_cap": 100_000_000_000.0,
        "debt": 15_000_000_000.0,
        "cash": 10_000_000_000.0,
        "revenue": 20_000_000_000.0,
        "ebitda": 5_000_000_000.0,
        "net_income": 3_000_000_000.0,
        "free_cash_flow": 3_500_000_000.0,
    }
    unrelated = pd.DataFrame(
        [{"Class": "Ownership", "Dimension": "Insider sale", "Signal": "Filed", "Detail": "Form 4"}]
    )
    empty_relationships = {
        "summary": {
            "max_customer_concentration": None,
            "max_supplier_concentration": None,
            "single_source_count": 0,
            "customer_confidence": 0,
            "supplier_confidence": 0,
        }
    }
    context = {"scenario": "Base", "owner": "Analyst", "valuation_anchor": "Standalone market price"}

    routing = mna_workbench._build_diligence_routing(facts, unrelated, empty_relationships, context).set_index("Workstream")

    assert routing.loc["Commercial & market", "State"] == "DATA GAP"
    assert routing.loc["Customer & supplier dependencies", "State"] == "DATA GAP"
    assert routing.loc["Financial & quality of earnings", "State"] == "LIMITED"
    assert "no QoE" in routing.loc["Financial & quality of earnings", "Current evidence"]
    assert routing.loc["Valuation & synergies", "Current evidence"].startswith("Base case · Standalone market price")
    assert "AVAILABLE" not in set(routing["State"])

    operating = pd.DataFrame([{"Class": "Operating", "Dimension": "Growth", "Signal": "Revenue growth"}])
    substantive_relationships = {"summary": {"max_customer_concentration": 0.22, "single_source_count": 0}}
    routing = mna_workbench._build_diligence_routing(
        facts,
        operating,
        substantive_relationships,
        context,
    ).set_index("Workstream")
    assert routing.loc["Commercial & market", "State"] == "LIMITED"
    assert routing.loc["Customer & supplier dependencies", "State"] == "LIMITED"

    blocked = mna_workbench._build_diligence_routing({}, pd.DataFrame(), {}, context).set_index("Workstream")
    assert blocked.loc["Valuation & synergies", "State"] == "DATA GAP"


def test_all_five_workflows_and_both_deal_lenses_render_offline():
    app = AppTest.from_file(
        "tests/company_intelligence/mna_ui_harness.py",
        default_timeout=60,
    ).run()

    assert not app.exception
    assert app.radio[0].value == "DES · Company 360"
    next(widget for widget in app.selectbox if widget.label == "Information density").set_value("Audit").run()
    assert not app.exception
    next(widget for widget in app.selectbox if widget.label == "Scenario profile").set_value("Bull").run()
    assert not app.exception
    next(widget for widget in app.selectbox if widget.label == "Information density").set_value("Analyst").run()
    for command in (
        "RV · Relative Value",
        "FA · Financial Analysis",
        "DOWW · Deal Watch",
        "BI · Intelligence",
    ):
        app.radio[0].set_value(command).run()
        assert not app.exception, command

    assert {metric.label for metric in app.metric}.issuperset(
        {
            "Overall evidence bias",
            "Overall material observations",
            "Overall structural risks",
            "Overall evidence confidence",
        }
    )
    assert {widget.label for widget in app.multiselect}.issuperset({"Evidence classes", "Directions"})
    assert any("Transaction diligence routing" in element.value for element in app.markdown)
    assert any("Evidence map · confidence × materiality" in element.value for element in app.markdown)
    assert any("Bull · Scenario profile · Bull" in element.value for element in app.markdown)
    assert not any("Bull · None" in element.value for element in app.markdown)

    app.radio[0].set_value("RV · Relative Value").run()
    next(widget for widget in app.multiselect if widget.label == "Included comparable companies").set_value(
        ["AAA", "BBB", "CCC"]
    ).run()
    next(widget for widget in app.text_input if widget.label == "Exclusion rationale").set_value(
        "DDD excluded as an outlier"
    ).run()
    next(widget for widget in app.selectbox if widget.label == "Information density").set_value("Executive").run()
    assert any("At least four valid current peers" in element.value for element in app.info)
    next(widget for widget in app.selectbox if widget.label == "Information density").set_value("Analyst").run()
    assert next(widget for widget in app.multiselect if widget.label == "Included comparable companies").value == [
        "AAA",
        "BBB",
        "CCC",
    ]
    assert next(widget for widget in app.text_input if widget.label == "Exclusion rationale").value == "DDD excluded as an outlier"

    app.radio[0].set_value("FA · Financial Analysis").run()
    next(widget for widget in app.number_input if widget.label == "Base FCF proxy · bn").set_value(4.2).run()
    app.radio[0].set_value("DES · Company 360").run()
    app.radio[0].set_value("FA · Financial Analysis").run()
    assert next(widget for widget in app.number_input if widget.label == "Base FCF proxy · bn").value == 4.2

    app.radio[0].set_value("DOWW · Deal Watch").run()
    next(widget for widget in app.number_input if widget.label == "Tax rate · %").set_value(27.0).run()
    app.radio[0].set_value("DES · Company 360").run()
    app.radio[0].set_value("DOWW · Deal Watch").run()
    assert next(widget for widget in app.number_input if widget.label == "Tax rate · %").value == 27.0

    app.radio[1].set_value("Acquirer / accretion case").run()
    assert not app.exception
    next(widget for widget in app.number_input if widget.label == "Target equity value · bn").set_value(12.5).run()
    app.radio[1].set_value("Target / takeover screen").run()
    app.radio[1].set_value("Acquirer / accretion case").run()
    assert next(widget for widget in app.number_input if widget.label == "Target equity value · bn").value == 12.5
    next(widget for widget in app.text_input if widget.label == "Scenario label").set_value("Persistent acquisition case").run()
    app.radio[0].set_value("DES · Company 360").run()
    app.radio[0].set_value("DOWW · Deal Watch").run()
    assert app.radio[1].value == "Acquirer / accretion case"
    assert next(widget for widget in app.number_input if widget.label == "Target equity value · bn").value == 12.5
    assert any(metric.label == "PF net leverage" for metric in app.metric)
    scenario_label = next(widget for widget in app.text_input if widget.label == "Scenario label")
    assert scenario_label.value == "Persistent acquisition case"
    assert next(widget for widget in app.selectbox if widget.label == "Scenario profile").value == "Bull"
    assert next(widget for widget in app.selectbox if widget.label == "Information density").value == "Analyst"
