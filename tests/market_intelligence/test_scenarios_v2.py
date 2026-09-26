from __future__ import annotations

from dataclasses import replace

from market_intelligence.demo import build_workspace_snapshot
from market_intelligence.risk import ScenarioDefinition, ScenarioState, evaluate_scenarios


def test_evidenced_stress_transform_is_monotone_and_research_only() -> None:
    forecast = build_workspace_snapshot("NVDA").forecasts[0]
    scenario = ScenarioDefinition(
        "TEST_STRESS",
        "Test tail stress",
        return_shift=-0.01,
        volatility_multiplier=1.5,
        evidence_ids=("sensitivity:test",),
    )
    envelope = evaluate_scenarios((forecast,), (scenario,), evidence_ids=("forecast:test",))
    result = envelope.assessments[0]
    assert result.state == ScenarioState.EVALUATED
    assert result.stressed_q05 <= result.stressed_q50 <= result.stressed_q95
    assert envelope.research_boundary == "RESEARCH_ONLY"
    assert envelope.execution_allowed is False


def test_missing_quantiles_make_scenario_unpriced() -> None:
    forecast = build_workspace_snapshot("NVDA").forecasts[0]
    missing = replace(
        forecast,
        q05=None,
        q25=None,
        q50=None,
        q75=None,
        q95=None,
        uncertainty_flags=(*forecast.uncertainty_flags, "MISSING_QUANTILES"),
    )
    envelope = evaluate_scenarios(
        (missing,),
        (ScenarioDefinition("UNPRICED", "Unpriced scenario", evidence_ids=("test",)),),
    )
    assert envelope.assessments[0].state == ScenarioState.UNPRICED
