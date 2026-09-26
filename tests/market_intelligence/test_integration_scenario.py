from __future__ import annotations

from market_intelligence.demo import build_workspace_snapshot
from market_intelligence.monitoring import run_fixture_integrity_audit


def test_fed_nvda_collision_canonical_qualitative_outputs() -> None:
    snapshot = build_workspace_snapshot("NVDA")
    assert snapshot.interaction.collision_score >= 0.90
    assert -0.20 < snapshot.interaction.catalyst_pressure < 0.0
    assert snapshot.interaction.state == "negative_catalyst_absorption"
    by_horizon = {forecast.horizon: forecast for forecast in snapshot.forecasts}
    assert by_horizon["10m"].p_up <= by_horizon["30m"].p_up
    assert snapshot.audit["information_gap"]["unexplained_residual"] < 0.70
    assert snapshot.audit["information_gap"]["status"] == "NO UNEXPLAINED-FLOW ALARM"


def test_fixture_integrity_audit_has_no_blocking_failures() -> None:
    result = run_fixture_integrity_audit(build_workspace_snapshot("NVDA"))
    assert not ((result["Blocking"]) & (result["Result"] == "FAIL")).any()
    assert (result["Result"] == "PASS").all()


def test_non_fixture_symbol_is_not_repainted_or_fused() -> None:
    snapshot = build_workspace_snapshot("AAPL")
    assert snapshot.symbol == "NVDA"
    context = snapshot.audit["context_integrity"]
    assert context["requested_symbol"] == "AAPL"
    assert context["fixture_symbol"] == "NVDA"
    assert context["state"] == "MISMATCH_BLOCKED"
    assert context["fusion_allowed"] is False
    assert snapshot.audit["terminal_context"]["available"] is False
    assert any("NVDA" in event.title for event in snapshot.events)
