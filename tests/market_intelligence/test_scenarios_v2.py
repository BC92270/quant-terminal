from __future__ import annotations

from dataclasses import replace

from market_intelligence.demo import build_workspace_snapshot
from market_intelligence.governance import assess_workspace
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


def test_scenario_evidence_can_be_scoped_to_exact_horizon() -> None:
    forecasts = build_workspace_snapshot("NVDA").forecasts[:2]
    envelope = evaluate_scenarios(
        forecasts,
        (ScenarioDefinition("SCOPED", "Scoped scenario"),),
        evidence_ids=("forecast:shared",),
        evidence_ids_by_horizon={
            forecasts[0].horizon: (f"forecast:exact:{forecasts[0].horizon}",),
            forecasts[1].horizon: (f"forecast:exact:{forecasts[1].horizon}",),
        },
    )
    for result in envelope.assessments:
        assert result.evidence_ids == (f"forecast:exact:{result.horizon}",)


def test_multi_model_same_horizon_has_unique_scenarios_and_exact_evidence() -> None:
    snapshot = build_workspace_snapshot("NVDA")
    baseline = snapshot.forecasts[0]
    challenger = replace(
        baseline,
        model_id="SECOND_BASELINE",
        model_version="0.2.0",
        expected_return=(baseline.expected_return or 0.0) + 0.001,
    )
    assessment = assess_workspace(replace(snapshot, forecasts=(*snapshot.forecasts, challenger)))
    scenario_records = [
        record for record in assessment.ledger.records if record.kind == "scenario_assessment"
    ]
    assert len(scenario_records) == len(assessment.risk_envelope.assessments)
    assert len({record.evidence_id for record in scenario_records}) == len(scenario_records)
    for item in assessment.risk_envelope.assessments:
        forecast_ids = [value for value in item.evidence_ids if value.startswith("forecast:")]
        assert forecast_ids == [f"forecast:{item.model_id}:{item.model_version}:{item.horizon}"]
