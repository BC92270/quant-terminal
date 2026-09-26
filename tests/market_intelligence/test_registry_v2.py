from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from market_intelligence.demo import build_workspace_snapshot
from market_intelligence.governance import GateResult, GateStatus, ValidationRun
from market_intelligence.models.registry import (
    HumanApproval,
    ModelLifecycle,
    PromotionState,
    baseline_registry_from_snapshot,
)


def _validation() -> ValidationRun:
    return ValidationRun(
        run_id="validated-run",
        policy_version="test-policy-v1",
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        completed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        gates=(GateResult("TEST", "Test gate", GateStatus.PASS, True, "Typed test pass"),),
        evidence_root="a" * 64,
    )


def test_fixture_baseline_is_registered_but_waiting_for_evidence() -> None:
    registry = baseline_registry_from_snapshot(build_workspace_snapshot("NVDA"))
    assert len(registry.records) == 1
    record = registry.records[0]
    assert record.lifecycle == ModelLifecycle.REGISTERED
    assert record.promotion_state == PromotionState.WAITING_EVIDENCE
    assert record.research_boundary == "RESEARCH_ONLY"
    assert "PRODUCTION" not in {state.value.upper() for state in ModelLifecycle}


def test_registry_cannot_jump_to_shadow_or_bypass_human_approval() -> None:
    registry = baseline_registry_from_snapshot(build_workspace_snapshot("NVDA"))
    record = registry.records[0]
    with pytest.raises(ValueError, match="Illegal model transition"):
        registry.transition(record.model_id, record.version, ModelLifecycle.SHADOW)

    with pytest.raises(TypeError, match="typed ValidationRun"):
        registry.transition(
            record.model_id,
            record.version,
            ModelLifecycle.OFFLINE_VALIDATED,
            validation=object(),
        )

    validation = _validation()
    registry = registry.transition(
        record.model_id, record.version, ModelLifecycle.OFFLINE_VALIDATED, validation=validation
    )
    registry = registry.transition(
        record.model_id,
        record.version,
        ModelLifecycle.ELIGIBLE_FOR_HUMAN_REVIEW,
        validation=validation,
    )
    with pytest.raises(ValueError, match="typed human approval"):
        registry.transition(record.model_id, record.version, ModelLifecycle.SHADOW)

    wrong = HumanApproval(
        approval_id="approval-wrong",
        actor="independent-reviewer",
        approved_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        reason="Controlled shadow observation only",
        validation_run_id=validation.run_id,
        evidence_root="b" * 64,
    )
    with pytest.raises(ValueError, match="evidence root"):
        registry.transition(record.model_id, record.version, ModelLifecycle.SHADOW, approval=wrong)

    approval = HumanApproval(
        approval_id="approval-001",
        actor="independent-reviewer",
        approved_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        reason="Controlled shadow observation only",
        validation_run_id=validation.run_id,
        evidence_root=validation.evidence_root,
    )
    shadow = registry.transition(record.model_id, record.version, ModelLifecycle.SHADOW, approval=approval)
    promoted = shadow.get(record.model_id, record.version)
    assert promoted.lifecycle == ModelLifecycle.SHADOW
    assert promoted.approval_id == approval.approval_id


def test_model_registry_keeps_evidence_scoped_to_each_model() -> None:
    snapshot = build_workspace_snapshot("NVDA")
    baseline = snapshot.forecasts[0]
    challenger = replace(baseline, model_id="challenger", model_version="0.1.0", horizon="5m")
    mixed = replace(snapshot, forecasts=(*snapshot.forecasts, challenger))
    evidence = {
        (baseline.model_id, baseline.model_version): ("forecast:baseline:own",),
        (challenger.model_id, challenger.model_version): ("forecast:challenger:own",),
    }
    registry = baseline_registry_from_snapshot(mixed, evidence_ids_by_model=evidence)
    baseline_record = registry.get(baseline.model_id, baseline.model_version)
    challenger_record = registry.get(challenger.model_id, challenger.model_version)
    assert baseline_record.evidence_ids == ("forecast:baseline:own",)
    assert challenger_record.evidence_ids == ("forecast:challenger:own",)
