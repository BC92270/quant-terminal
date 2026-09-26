from __future__ import annotations

from dataclasses import replace

import pytest

from market_intelligence.catalysts import assess_interaction
from market_intelligence.demo import build_workspace_snapshot
from market_intelligence.governance import (
    DecisionState,
    GateStatus,
    ResearchBoundary,
    ResearchPosture,
    assess_workspace,
)


def test_canonical_fixture_builds_deterministic_fail_closed_decision_packet() -> None:
    snapshot = build_workspace_snapshot("NVDA")
    first = assess_workspace(snapshot)
    second = assess_workspace(snapshot)
    packet = first.decision

    assert packet.boundary == ResearchBoundary.RESEARCH_ONLY
    assert packet.state == DecisionState.WAITING_EVIDENCE
    assert packet.posture == ResearchPosture.OBSERVE_ONLY
    assert packet.execution_allowed is False
    assert packet.human_review_required is True
    assert packet.evidence_root == first.ledger.root_hash == second.ledger.root_hash
    assert packet.packet_id == second.decision.packet_id
    assert first.ledger.verify()
    statuses = {gate.gate_id: gate.status for gate in packet.validation.gates}
    assert statuses["EVIDENCE_INTEGRITY"] == GateStatus.PASS
    assert statuses["DATA_QUALITY"] == GateStatus.WAITING_EVIDENCE
    assert statuses["CALIBRATION"] == GateStatus.WAITING_EVIDENCE
    assert packet.blockers


def test_research_packet_can_never_authorize_execution() -> None:
    packet = assess_workspace(build_workspace_snapshot("NVDA")).decision
    with pytest.raises(ValueError, match="cannot authorize execution"):
        replace(packet, execution_allowed=True)


def test_missing_micro_inputs_are_invalid_not_neutral_confirmation() -> None:
    result = assess_interaction((-1.0,), {})
    assert result.confidence == "INVALID"
    assert result.state == "unexplained_information_flow"
    assert any(flag.startswith("MISSING_MICRO_INPUTS") for flag in result.validation_flags)
