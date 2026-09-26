from __future__ import annotations

from dataclasses import replace

import pytest

from market_intelligence.evidence import (
    EvidenceConflictError,
    EvidenceIntegrityError,
    EvidenceLedger,
    canonical_hash,
)


STAMP = "2026-01-01T12:00:00Z"


def _append(ledger: EvidenceLedger, evidence_id: str, payload: object):
    return ledger.append(
        evidence_id=evidence_id,
        kind="test",
        source="unit-test",
        observed_at=STAMP,
        known_at=STAMP,
        recorded_at=STAMP,
        payload=payload,
    )


def test_canonical_hash_and_ledger_root_are_deterministic() -> None:
    assert canonical_hash({"b": 2, "a": 1}) == canonical_hash({"a": 1, "b": 2})
    left = EvidenceLedger()
    right = EvidenceLedger()
    for ledger in (left, right):
        _append(ledger, "evt-1", {"value": 1})
        _append(ledger, "evt-2", {"value": 2})
    assert left.root_hash == right.root_hash
    assert left.verify()


def test_idempotent_append_and_conflicting_identifier() -> None:
    ledger = EvidenceLedger()
    first = _append(ledger, "evt-1", {"value": 1})
    assert _append(ledger, "evt-1", {"value": 1}) is first
    assert len(ledger.records) == 1
    with pytest.raises(EvidenceConflictError):
        _append(ledger, "evt-1", {"value": 99})


def test_tampered_record_is_rejected_on_replay() -> None:
    ledger = EvidenceLedger()
    record = _append(ledger, "evt-1", {"value": 1})
    tampered = replace(record, payload_hash="f" * 64)
    with pytest.raises(EvidenceIntegrityError, match="hash mismatch"):
        EvidenceLedger((tampered,))
