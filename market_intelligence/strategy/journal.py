"""Append-only, session-scoped journal for non-authorizing human dispositions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from ..contracts import as_utc
from ..evidence import GENESIS_HASH, canonical_hash
from .contracts import (
    DecisionPurpose,
    HumanDisposition,
    MemoValidity,
    StrategicDecisionMemo,
    StrategicDisposition,
)


@dataclass(frozen=True, slots=True)
class StrategicReviewRecord:
    record_id: str
    memo_id: str
    memo_content_hash: str
    context_id: str
    requested_symbol: str
    subject_symbol: str
    decision_horizon: str
    decision_purpose: DecisionPurpose
    basis_packet_id: str
    basis_validation_run_id: str
    basis_evidence_root: str
    disposition: HumanDisposition
    selected_process_option_id: str
    actor_id: str
    actor_role: str
    rationale: str
    recorded_at: datetime
    memo_expires_at: datetime
    memo_validity: MemoValidity
    identity_assurance: str
    previous_hash: str
    record_hash: str
    scope: str = "SESSION_ONLY_NON_AUTHORIZING"
    execution_allowed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "recorded_at", as_utc(self.recorded_at))
        object.__setattr__(self, "memo_expires_at", as_utc(self.memo_expires_at))
        if not isinstance(self.disposition, HumanDisposition):
            raise TypeError("disposition must be a HumanDisposition")
        if not isinstance(self.decision_purpose, DecisionPurpose):
            raise TypeError("decision_purpose must be a DecisionPurpose")
        if not isinstance(self.memo_validity, MemoValidity):
            raise TypeError("memo_validity must be a MemoValidity")
        for name in (
            "record_id",
            "memo_id",
            "context_id",
            "requested_symbol",
            "subject_symbol",
            "decision_horizon",
            "basis_packet_id",
            "basis_validation_run_id",
            "basis_evidence_root",
            "selected_process_option_id",
            "actor_id",
            "actor_role",
            "rationale",
            "identity_assurance",
            "scope",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} cannot be empty")
        for name in ("memo_content_hash", "basis_evidence_root", "previous_hash", "record_hash"):
            value = str(getattr(self, name))
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError(f"{name} must be a SHA-256 digest")
        if self.scope != "SESSION_ONLY_NON_AUTHORIZING" or self.execution_allowed:
            raise ValueError("Strategic review records cannot authorize execution")
        if self.identity_assurance != "SELF_ASSERTED_UNVERIFIED":
            raise ValueError("Session identity assurance must remain SELF_ASSERTED_UNVERIFIED")
        if self.requested_symbol != self.requested_symbol.upper() or self.subject_symbol != self.subject_symbol.upper():
            raise ValueError("Strategic review symbols must be normalized to uppercase")
        expected_validity = (
            MemoValidity.CURRENT
            if self.recorded_at <= self.memo_expires_at
            else MemoValidity.EXPIRED
        )
        if self.memo_validity != expected_validity:
            raise ValueError("Strategic review memo validity is inconsistent with the review clock")
        if self.memo_validity == MemoValidity.EXPIRED and self.disposition not in {
            HumanDisposition.RETURN_FOR_EVIDENCE,
            HumanDisposition.REJECT_MEMO,
        }:
            raise ValueError("Expired memos may only be returned for evidence or rejected")
        if (
            self.disposition == HumanDisposition.ADVANCE_TO_INDEPENDENT_REVIEW
            and self.selected_process_option_id != "MI-OPT-CONVENE-REVIEW"
        ):
            raise ValueError("Independent review advancement must select MI-OPT-CONVENE-REVIEW")
        if self.record_hash != canonical_hash(self.hash_material()):
            raise ValueError("Strategic review record hash mismatch")

    def hash_material(self) -> dict[str, object]:
        return {
            "record_id": self.record_id,
            "memo_id": self.memo_id,
            "memo_content_hash": self.memo_content_hash,
            "context_id": self.context_id,
            "requested_symbol": self.requested_symbol,
            "subject_symbol": self.subject_symbol,
            "decision_horizon": self.decision_horizon,
            "decision_purpose": self.decision_purpose,
            "basis_packet_id": self.basis_packet_id,
            "basis_validation_run_id": self.basis_validation_run_id,
            "basis_evidence_root": self.basis_evidence_root,
            "disposition": self.disposition,
            "selected_process_option_id": self.selected_process_option_id,
            "actor_id": self.actor_id,
            "actor_role": self.actor_role,
            "rationale": self.rationale,
            "recorded_at": self.recorded_at,
            "memo_expires_at": self.memo_expires_at,
            "memo_validity": self.memo_validity,
            "identity_assurance": self.identity_assurance,
            "previous_hash": self.previous_hash,
            "scope": self.scope,
            "execution_allowed": self.execution_allowed,
        }


class StrategicDecisionJournal:
    def __init__(self, records: Iterable[StrategicReviewRecord] = ()) -> None:
        self._records = list(records)
        self.verify()

    @property
    def records(self) -> tuple[StrategicReviewRecord, ...]:
        return tuple(self._records)

    @property
    def root_hash(self) -> str:
        return self._records[-1].record_hash if self._records else GENESIS_HASH

    def append(
        self,
        memo: StrategicDecisionMemo,
        *,
        disposition: HumanDisposition,
        selected_process_option_id: str,
        actor_id: str,
        actor_role: str,
        rationale: str,
        recorded_at: datetime,
    ) -> StrategicReviewRecord:
        if not isinstance(memo, StrategicDecisionMemo):
            raise TypeError("memo must be a StrategicDecisionMemo")
        if not isinstance(disposition, HumanDisposition):
            raise TypeError("disposition must be a HumanDisposition")
        option = next(
            (item for item in memo.options if item.option_id == selected_process_option_id),
            None,
        )
        if option is None or not option.selectable_for_session_record:
            raise ValueError("The selected option is not available for a session decision record")
        actor = str(actor_id).strip()
        role = str(actor_role).strip()
        reason = str(rationale).strip()
        if not actor or not role or len(reason) < 12:
            raise ValueError("Actor, role and a substantive rationale are required")
        stamp = as_utc(recorded_at)
        if stamp < memo.context.as_of:
            raise ValueError("Decision record cannot precede the governed snapshot")
        if self._records and stamp < self._records[-1].recorded_at:
            raise ValueError("Decision journal timestamps must be monotonic")
        validity = MemoValidity.CURRENT if stamp <= memo.expires_at else MemoValidity.EXPIRED
        if validity == MemoValidity.EXPIRED and disposition not in {
            HumanDisposition.RETURN_FOR_EVIDENCE,
            HumanDisposition.REJECT_MEMO,
        }:
            raise ValueError("Expired memos may only be returned for evidence or rejected")
        if disposition == HumanDisposition.ADVANCE_TO_INDEPENDENT_REVIEW and (
            validity != MemoValidity.CURRENT
            or memo.disposition != StrategicDisposition.READY_FOR_HUMAN_REVIEW
            or selected_process_option_id != memo.recommended_process_option_id
            or selected_process_option_id != "MI-OPT-CONVENE-REVIEW"
        ):
            raise ValueError(
                "Independent review can advance only from the recommended review option of a current review-ready memo"
            )
        semantic = {
            "memo_id": memo.memo_id,
            "memo_content_hash": memo.content_hash,
            "context_id": memo.context.context_id,
            "requested_symbol": memo.context.requested_symbol,
            "subject_symbol": memo.context.subject_symbol,
            "decision_horizon": memo.context.horizon,
            "decision_purpose": memo.context.purpose,
            "basis_packet_id": memo.basis_packet_id,
            "basis_validation_run_id": memo.basis_validation_run_id,
            "basis_evidence_root": memo.basis_evidence_root,
            "disposition": disposition,
            "selected_process_option_id": selected_process_option_id,
            "actor_id": actor,
            "actor_role": role,
            "rationale": reason,
            "recorded_at": stamp,
            "memo_expires_at": memo.expires_at,
            "memo_validity": validity,
            "identity_assurance": "SELF_ASSERTED_UNVERIFIED",
            "previous_hash": self.root_hash,
            "scope": "SESSION_ONLY_NON_AUTHORIZING",
            "execution_allowed": False,
        }
        record_id = "MI-SREV-" + canonical_hash(semantic)[:20].upper()
        material = {"record_id": record_id, **semantic}
        record = StrategicReviewRecord(record_hash=canonical_hash(material), **material)
        self._records.append(record)
        return record

    def verify(self) -> bool:
        previous = GENESIS_HASH
        last_recorded_at: datetime | None = None
        identifiers: set[str] = set()
        for record in self._records:
            if not isinstance(record, StrategicReviewRecord):
                raise TypeError("Strategic journal entries must be StrategicReviewRecord instances")
            if record.record_id in identifiers:
                raise ValueError("Duplicate strategic review record ID")
            if record.previous_hash != previous:
                raise ValueError("Broken strategic review journal chain")
            if record.record_hash != canonical_hash(record.hash_material()):
                raise ValueError("Strategic review journal hash mismatch")
            if last_recorded_at is not None and record.recorded_at < last_recorded_at:
                raise ValueError("Strategic review journal timestamps are not monotonic")
            identifiers.add(record.record_id)
            previous = record.record_hash
            last_recorded_at = record.recorded_at
        return True
