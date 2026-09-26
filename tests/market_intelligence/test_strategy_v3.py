from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import json

import pytest
from streamlit.testing.v1 import AppTest

from market_intelligence.demo import build_workspace_snapshot
from market_intelligence.governance import DecisionState, GateStatus, assess_workspace
from market_intelligence.strategy import (
    DecisionPurpose,
    HumanDisposition,
    MemoValidity,
    OptionClass,
    OptionStatus,
    StrategicDecisionJournal,
    StrategicDisposition,
    build_strategic_decision_memo,
)
from market_intelligence.strategy.engine import _options
from market_intelligence.ui.institutional_control import decision_dossier_json


def _memo(symbol: str = "NVDA", horizon: str = "30m", purpose: DecisionPurpose = DecisionPurpose.RESEARCH_PRIORITIZATION):
    snapshot = build_workspace_snapshot(symbol)
    assessment = assess_workspace(snapshot)
    return snapshot, assessment, build_strategic_decision_memo(
        snapshot,
        assessment,
        horizon=horizon,
        purpose=purpose,
    )


def test_strategic_memo_is_deterministic_and_separates_process_from_capital() -> None:
    snapshot, assessment, first = _memo()
    second = build_strategic_decision_memo(snapshot, assessment, horizon="30m")

    assert first == second
    assert first.memo_id == second.memo_id
    assert first.content_hash == second.content_hash
    assert first.disposition == StrategicDisposition.ACQUIRE_EVIDENCE
    assert first.recommended_process_option_id == "MI-OPT-ACQUIRE-EVIDENCE"
    assert first.preferred_portfolio_option_id is None
    assert first.authority == "ADVISORY_ONLY"
    assert first.execution_allowed is False
    assert first.order_payload is None
    assert "UNPRICED" in first.portfolio_summary
    selected = next(item for item in first.options if item.option_id == first.recommended_process_option_id)
    assert selected.option_class == OptionClass.PROCESS
    assert selected.status == OptionStatus.RECOMMENDED
    execution = next(item for item in first.options if item.option_class == OptionClass.EXECUTION)
    assert execution.status == OptionStatus.PROHIBITED
    assert execution.execution_allowed is False


def test_eligible_research_path_recommends_a_process_not_a_portfolio_option() -> None:
    options = _options(
        StrategicDisposition.READY_FOR_HUMAN_REVIEW,
        "MI-OPT-CONVENE-REVIEW",
        (),
    )
    recommended = next(option for option in options if option.status == OptionStatus.RECOMMENDED)
    portfolio = next(option for option in options if option.option_class == OptionClass.PORTFOLIO_REVIEW)
    assert recommended.option_id == "MI-OPT-CONVENE-REVIEW"
    assert recommended.option_class == OptionClass.PROCESS
    assert portfolio.status == OptionStatus.BLOCKED


def test_decision_lens_and_horizon_change_memo_not_governance_basis() -> None:
    snapshot = build_workspace_snapshot("NVDA")
    assessment = assess_workspace(snapshot)
    research = build_strategic_decision_memo(
        snapshot,
        assessment,
        horizon="30m",
        purpose=DecisionPurpose.RESEARCH_PRIORITIZATION,
    )
    monitor = build_strategic_decision_memo(
        snapshot,
        assessment,
        horizon="30m",
        purpose=DecisionPurpose.MARKET_MONITORING,
    )
    longer = build_strategic_decision_memo(
        snapshot,
        assessment,
        horizon="1h",
        purpose=DecisionPurpose.RESEARCH_PRIORITIZATION,
    )

    assert len({research.memo_id, monitor.memo_id, longer.memo_id}) == 3
    assert research.basis_evidence_root == monitor.basis_evidence_root == longer.basis_evidence_root
    assert research.basis_packet_id == monitor.basis_packet_id == longer.basis_packet_id


def test_context_mismatch_is_a_hard_gate_and_blocks_strategic_inference() -> None:
    snapshot, assessment, memo = _memo("AAPL")
    gates = {gate.gate_id: gate for gate in assessment.decision.validation.gates}

    assert assessment.decision.state == DecisionState.REJECTED
    assert gates["CONTEXT_INTEGRITY"].status == GateStatus.FAIL
    assert gates["CONTEXT_INTEGRITY"].blocks_progression
    assert memo.disposition == StrategicDisposition.BLOCKED_CONTEXT
    assert memo.context.requested_symbol == "AAPL"
    assert memo.context.subject_symbol == "NVDA"
    assert memo.recommended_process_option_id == "MI-OPT-RESOLVE-CONTEXT"
    assert memo.preferred_portfolio_option_id is None
    assert all(claim.claim_id in {"MI-SCLM-CONTEXT", "MI-SCLM-NO-CROSS-SYMBOL"} for claim in memo.claims)
    assert [rule.rule_id for rule in memo.monitoring_rules] == ["MI-MON-CONTEXT"]


@pytest.mark.parametrize(
    "context_patch",
    (
        {"requested_symbol": "AAPL", "state": "MATCHED", "fusion_allowed": True},
        {"fixture_symbol": "AAPL", "state": "MATCHED", "fusion_allowed": True},
        {"state": "MATCHED", "fusion_allowed": False},
        {"requested_symbol": None, "state": "MATCHED", "fusion_allowed": True},
    ),
)
def test_every_inadmissible_context_path_suppresses_market_inference(context_patch: dict[str, object]) -> None:
    snapshot = build_workspace_snapshot("NVDA")
    context = {**snapshot.audit["context_integrity"], **context_patch}
    forged = replace(snapshot, audit={**snapshot.audit, "context_integrity": context})
    assessment = assess_workspace(forged)
    memo = build_strategic_decision_memo(forged, assessment, horizon="30m")

    assert assessment.decision.state == DecisionState.REJECTED
    assert memo.context.context_admissible is False
    assert memo.disposition == StrategicDisposition.BLOCKED_CONTEXT
    assert {claim.claim_id for claim in memo.claims} == {
        "MI-SCLM-CONTEXT",
        "MI-SCLM-NO-CROSS-SYMBOL",
    }
    assert [rule.rule_id for rule in memo.monitoring_rules] == ["MI-MON-CONTEXT"]


def test_non_context_hard_failure_suppresses_market_inference_until_remediation() -> None:
    snapshot = build_workspace_snapshot("NVDA")
    invalid_interaction = replace(
        snapshot.interaction,
        confidence="INVALID",
        validation_flags=("INVALID_INTERACTION_INPUTS",),
    )
    rejected = replace(snapshot, interaction=invalid_interaction)
    assessment = assess_workspace(rejected)
    memo = build_strategic_decision_memo(rejected, assessment, horizon="30m")

    assert assessment.decision.state == DecisionState.REJECTED
    assert memo.context.context_admissible is True
    assert memo.disposition == StrategicDisposition.REMEDIATE_CONTROLS
    assert {claim.claim_id for claim in memo.claims} == {
        "MI-SCLM-CONTROL-FAILURE",
        "MI-SCLM-NO-INFERENCE",
    }
    assert [rule.rule_id for rule in memo.monitoring_rules] == ["MI-MON-CONTROLS"]
    selectable = [option.option_id for option in memo.options if option.selectable_for_session_record]
    assert selectable == ["MI-OPT-REMEDIATE"]


def test_strategy_rejects_missing_surplus_or_mutated_governance_inputs() -> None:
    snapshot = build_workspace_snapshot("NVDA")
    assessment = assess_workspace(snapshot)
    mutations = (
        replace(snapshot, events=snapshot.events[:-1]),
        replace(snapshot, forecasts=snapshot.forecasts[:-1]),
        replace(snapshot, price=99_999.0),
        replace(snapshot, regime="MUTATED_REGIME"),
        replace(snapshot, interaction=replace(snapshot.interaction, collision_score=0.01)),
    )
    for mutated in mutations:
        with pytest.raises(ValueError, match="does not (exactly )?bind"):
            build_strategic_decision_memo(mutated, assessment, horizon="30m")

    extra_event = replace(snapshot.events[0], event_id="evt-extra-unbound")
    assessment_with_extra = assess_workspace(replace(snapshot, events=(*snapshot.events, extra_event)))
    with pytest.raises(ValueError, match="does not exactly bind"):
        build_strategic_decision_memo(snapshot, assessment_with_extra, horizon="30m")


def test_public_strategy_boundaries_reject_untyped_purpose_and_disposition() -> None:
    snapshot = build_workspace_snapshot("NVDA")
    assessment = assess_workspace(snapshot)
    with pytest.raises(TypeError, match="DecisionPurpose"):
        build_strategic_decision_memo(snapshot, assessment, horizon="30m", purpose="BUY")  # type: ignore[arg-type]

    memo = build_strategic_decision_memo(snapshot, assessment, horizon="30m")
    with pytest.raises(TypeError, match="HumanDisposition"):
        StrategicDecisionJournal().append(
            memo,
            disposition="APPROVE_CAPITAL",  # type: ignore[arg-type]
            selected_process_option_id=memo.recommended_process_option_id,
            actor_id="committee-17",
            actor_role="RESEARCH_STRATEGY_LEAD",
            rationale="No raw string may cross the typed decision boundary.",
            recorded_at=memo.review_at,
        )


def test_claims_monitoring_and_scenarios_reference_exact_evidence() -> None:
    _, assessment, memo = _memo()
    known = {record.evidence_id for record in assessment.ledger.records}
    assert all(set(claim.evidence_ids).issubset(known) for claim in memo.claims)
    assert all(set(rule.evidence_ids).issubset(known) for rule in memo.monitoring_rules)
    for scenario in assessment.risk_envelope.assessments:
        scoped = [identifier for identifier in scenario.evidence_ids if identifier.startswith("forecast:")]
        assert scoped
        assert all(identifier.endswith(f":{scenario.horizon}") for identifier in scoped)


def test_session_decision_journal_is_hash_chained_and_non_authorizing() -> None:
    _, _, memo = _memo()
    journal = StrategicDecisionJournal()
    first = journal.append(
        memo,
        disposition=HumanDisposition.RETURN_FOR_EVIDENCE,
        selected_process_option_id=memo.recommended_process_option_id,
        actor_id="committee-17",
        actor_role="RESEARCH_STRATEGY_LEAD",
        rationale="Acquire the named evidence before any portfolio review.",
        recorded_at=memo.review_at,
    )
    second = journal.append(
        memo,
        disposition=HumanDisposition.DEFER,
        selected_process_option_id="MI-OPT-CONTINUE-OBSERVATION",
        actor_id="risk-02",
        actor_role="INDEPENDENT_RISK_REVIEWER",
        rationale="Defer while monitoring the explicit invalidation rules.",
        recorded_at=memo.expires_at,
    )

    assert journal.verify()
    assert first.execution_allowed is second.execution_allowed is False
    assert first.memo_validity == second.memo_validity == MemoValidity.CURRENT
    assert second.previous_hash == first.record_hash
    assert journal.root_hash == second.record_hash
    with pytest.raises(ValueError, match="not available"):
        journal.append(
            memo,
            disposition=HumanDisposition.DEFER,
            selected_process_option_id="MI-OPT-AUTHORIZE-EXECUTION",
            actor_id="risk-02",
            actor_role="INDEPENDENT_RISK_REVIEWER",
            rationale="This option must remain prohibited by the research boundary.",
            recorded_at=memo.expires_at,
        )
    with pytest.raises(ValueError, match="hash mismatch"):
        replace(first, rationale="tampered rationale")

    expired = StrategicDecisionJournal().append(
        memo,
        disposition=HumanDisposition.RETURN_FOR_EVIDENCE,
        selected_process_option_id=memo.recommended_process_option_id,
        actor_id="committee-17",
        actor_role="RESEARCH_STRATEGY_LEAD",
        rationale="Return the expired memo for a refreshed governed evidence basis.",
        recorded_at=memo.expires_at + timedelta(seconds=1),
    )
    assert expired.memo_validity == MemoValidity.EXPIRED
    with pytest.raises(ValueError, match="Expired memos"):
        StrategicDecisionJournal().append(
            memo,
            disposition=HumanDisposition.DEFER,
            selected_process_option_id="MI-OPT-CONTINUE-OBSERVATION",
            actor_id="risk-02",
            actor_role="INDEPENDENT_RISK_REVIEWER",
            rationale="This stale memo cannot support a current deferral record.",
            recorded_at=memo.expires_at + timedelta(seconds=1),
        )

    chronology = StrategicDecisionJournal()
    chronology.append(
        memo,
        disposition=HumanDisposition.DEFER,
        selected_process_option_id="MI-OPT-CONTINUE-OBSERVATION",
        actor_id="risk-02",
        actor_role="INDEPENDENT_RISK_REVIEWER",
        rationale="Record the later in-window observation decision first.",
        recorded_at=memo.expires_at,
    )
    with pytest.raises(ValueError, match="monotonic"):
        chronology.append(
            memo,
            disposition=HumanDisposition.RETURN_FOR_EVIDENCE,
            selected_process_option_id=memo.recommended_process_option_id,
            actor_id="committee-17",
            actor_role="RESEARCH_STRATEGY_LEAD",
            rationale="An earlier timestamp cannot be appended after the later record.",
            recorded_at=memo.review_at,
        )


def test_evidence_dossier_adds_complete_strategic_contract() -> None:
    snapshot, assessment, memo = _memo()
    payload = json.loads(decision_dossier_json(assessment, snapshot, memo))

    assert payload["strategic_decision_memo"]["memo_id"] == memo.memo_id
    assert payload["strategic_decision_memo"]["preferred_portfolio_option_id"] is None
    assert payload["strategic_decision_memo"]["execution_allowed"] is False
    assert payload["authority_contract"] == {
        "capital_authority": False,
        "execution_allowed": False,
        "human_decision_required": True,
        "order_payload": None,
        "scope": "ADVISORY_ONLY",
    }
    assert payload["source_contracts"]["context_integrity"] == dict(snapshot.audit["context_integrity"])
    assert payload["source_contracts"]["information_gap"] == dict(snapshot.audit["information_gap"])


def test_dossier_rejects_a_foreign_strategic_memo() -> None:
    snapshot = build_workspace_snapshot("NVDA")
    assessment = assess_workspace(snapshot)
    foreign_snapshot, _, foreign_memo = _memo("AAPL")
    assert foreign_snapshot.audit["context_integrity"]["requested_symbol"] == "AAPL"
    with pytest.raises(ValueError, match="does not bind"):
        decision_dossier_json(assessment, snapshot, foreign_memo)


def test_strategic_room_renders_options_impacts_monitoring_and_export() -> None:
    app = AppTest.from_file("scripts/market_intelligence_smoke_app.py")
    app.session_state["mi_active_view"] = "live"
    app.session_state["mi_selected_symbol"] = "NVDA"
    app.session_state["mi_context_initialized"] = True
    app.session_state["mi_horizon"] = "30m"
    app.run(timeout=30)

    assert not app.exception
    rendered = "\n".join(str(item.value) for item in app.markdown)
    assert "Strategic Decision Office" in rendered
    assert "SNAPSHOT-CLOCK STRATEGIC RESPONSE" in rendered
    assert "ACQUIRE_EVIDENCE" in rendered
    assert "UNPRICED" in rendered
    assert "Non-authorizing strategic decision record" in rendered
    tables = [element.value for element in app.dataframe]
    assert any({"Status", "Option", "Class", "Invalidation"}.issubset(table.columns) for table in tables)
    assert any({"Dimension", "State", "Assessment"}.issubset(table.columns) for table in tables)
    assert any({"Metric", "Warning trigger", "Invalidation"}.issubset(table.columns) for table in tables)
    labels = [button.label for button in app.get("download_button")]
    assert "EXPORT STRATEGIC DECISION MEMO · JSON" in labels
    assert not any(button.label.upper() in {"BUY", "SELL", "EXECUTE", "APPROVE"} for button in app.button)


def test_decision_lens_updates_the_strategic_question_and_response() -> None:
    app = AppTest.from_file("scripts/market_intelligence_smoke_app.py")
    app.session_state["mi_active_view"] = "live"
    app.session_state["mi_selected_symbol"] = "NVDA"
    app.session_state["mi_context_initialized"] = True
    app.session_state["mi_horizon"] = "30m"
    app.run(timeout=30)

    app.selectbox(key="mi_strategy_purpose").select("MARKET_MONITORING")
    app.button(key="FormSubmitter:mi_context_form-APPLY CONTEXT").click().run(timeout=30)

    assert not app.exception
    assert app.session_state["mi_strategy_purpose"] == "MARKET_MONITORING"
    rendered = "\n".join(str(item.value) for item in app.markdown)
    assert "What must be monitored or invalidate the current thesis over 30m?" in rendered
    assert "MONITOR" in rendered
    assert "Continue bounded observation" in rendered


def test_human_can_record_only_a_non_authorizing_session_disposition() -> None:
    app = AppTest.from_file("scripts/market_intelligence_smoke_app.py")
    app.session_state["mi_active_view"] = "live"
    app.session_state["mi_selected_symbol"] = "NVDA"
    app.session_state["mi_context_initialized"] = True
    app.session_state["mi_horizon"] = "30m"
    app.run(timeout=30)

    app.text_input(key="mi_strategy_actor_id").input("committee-17")
    app.text_area(key="mi_strategy_rationale").input(
        "Return for the named evidence before any human portfolio review."
    )
    app.checkbox(key="mi_strategy_acknowledgement").check()
    app.button(
        key="FormSubmitter:mi_strategic_disposition_form-RECORD NON-AUTHORIZING STRATEGIC DISPOSITION"
    ).click().run(timeout=30)

    assert not app.exception
    assert len(app.session_state["mi_strategy_journal"]) == 1
    record = app.session_state["mi_strategy_journal"][0]
    assert record.actor_id == "committee-17"
    assert record.subject_symbol == "NVDA"
    assert record.context_id
    assert record.memo_content_hash
    assert record.basis_validation_run_id
    assert record.execution_allowed is False
    assert record.scope == "SESSION_ONLY_NON_AUTHORIZING"
    assert any("execution remains disabled" in str(item.value) for item in app.success)
    assert any(
        button.label == "EXPORT SESSION DECISION JOURNAL · JSON"
        for button in app.get("download_button")
    )
