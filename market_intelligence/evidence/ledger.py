"""Deterministic, append-only evidence chain for research decisions.

The ledger is intentionally storage-agnostic.  It provides canonical records,
hash chaining, idempotent append semantics and tamper detection without
performing file or network I/O during import or workspace rendering.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from enum import Enum
import hashlib
import json
import math
from typing import Any, Iterable, Mapping

from ..contracts import as_utc


GENESIS_HASH = "0" * 64


class EvidenceIntegrityError(ValueError):
    """Raised when an evidence chain is malformed or has been altered."""


class EvidenceConflictError(ValueError):
    """Raised when an evidence ID is reused for different content."""


def _canonicalize(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _canonicalize(asdict(value))
    if isinstance(value, Enum):
        return _canonicalize(value.value)
    if isinstance(value, datetime) or hasattr(value, "to_pydatetime"):
        stamp = as_utc(value)
        return stamp.isoformat().replace("+00:00", "Z")
    if isinstance(value, Mapping):
        return {str(key): _canonicalize(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        normalized = [_canonicalize(item) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Evidence payloads cannot contain non-finite numbers")
        return 0.0 if value == 0.0 else value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if hasattr(value, "item"):
        return _canonicalize(value.item())
    raise TypeError(f"Unsupported evidence payload type: {type(value)!r}")


def canonical_json(value: Any) -> str:
    """Serialize supported evidence values with stable ordering and UTC time."""

    return json.dumps(
        _canonicalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    evidence_id: str
    kind: str
    source: str
    observed_at: datetime
    known_at: datetime
    recorded_at: datetime
    schema_version: str
    payload_hash: str
    previous_hash: str
    record_hash: str
    flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("evidence_id", "kind", "source", "schema_version"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} cannot be empty")
        for name in ("observed_at", "known_at", "recorded_at"):
            object.__setattr__(self, name, as_utc(getattr(self, name)))
        if not self.observed_at <= self.known_at <= self.recorded_at:
            raise ValueError("Evidence timestamps must satisfy observed_at <= known_at <= recorded_at")
        for name in ("payload_hash", "previous_hash", "record_hash"):
            value = str(getattr(self, name))
            if not _is_sha256(value):
                raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")

    def hash_material(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "kind": self.kind,
            "source": self.source,
            "observed_at": self.observed_at,
            "known_at": self.known_at,
            "recorded_at": self.recorded_at,
            "schema_version": self.schema_version,
            "payload_hash": self.payload_hash,
            "previous_hash": self.previous_hash,
            "flags": self.flags,
        }

    def verify_hash(self) -> bool:
        return canonical_hash(self.hash_material()) == self.record_hash


class EvidenceLedger:
    """In-memory append-only hash chain with deterministic replay."""

    def __init__(self, records: Iterable[EvidenceRecord] = ()) -> None:
        self._records: list[EvidenceRecord] = list(records)
        self.verify()

    @property
    def records(self) -> tuple[EvidenceRecord, ...]:
        return tuple(self._records)

    @property
    def root_hash(self) -> str:
        return self._records[-1].record_hash if self._records else GENESIS_HASH

    def append(
        self,
        *,
        evidence_id: str,
        kind: str,
        source: str,
        observed_at: Any,
        known_at: Any,
        recorded_at: Any,
        payload: Any,
        schema_version: str = "mi-evidence-2.0.0",
        flags: Iterable[str] = (),
    ) -> EvidenceRecord:
        payload_hash = canonical_hash(payload)
        observed = as_utc(observed_at)
        known = as_utc(known_at)
        recorded = as_utc(recorded_at)
        normalized_flags = tuple(str(flag) for flag in flags)
        for existing in self._records:
            if existing.evidence_id != evidence_id:
                continue
            semantic_identity = (
                existing.kind,
                existing.source,
                existing.observed_at,
                existing.known_at,
                existing.recorded_at,
                existing.schema_version,
                existing.payload_hash,
                existing.flags,
            )
            candidate_identity = (
                kind,
                source,
                observed,
                known,
                recorded,
                schema_version,
                payload_hash,
                normalized_flags,
            )
            if semantic_identity == candidate_identity:
                return existing
            raise EvidenceConflictError(f"Evidence ID {evidence_id!r} already exists with different content")

        material = {
            "evidence_id": evidence_id,
            "kind": kind,
            "source": source,
            "observed_at": observed,
            "known_at": known,
            "recorded_at": recorded,
            "schema_version": schema_version,
            "payload_hash": payload_hash,
            "previous_hash": self.root_hash,
            "flags": normalized_flags,
        }
        record = EvidenceRecord(record_hash=canonical_hash(material), **material)
        self._records.append(record)
        return record

    def verify(self) -> bool:
        previous = GENESIS_HASH
        identifiers: set[str] = set()
        for position, record in enumerate(self._records):
            if record.evidence_id in identifiers:
                raise EvidenceIntegrityError(f"Duplicate evidence ID at position {position}: {record.evidence_id}")
            if record.previous_hash != previous:
                raise EvidenceIntegrityError(f"Broken evidence chain at position {position}")
            if not record.verify_hash():
                raise EvidenceIntegrityError(f"Evidence hash mismatch at position {position}")
            identifiers.add(record.evidence_id)
            previous = record.record_hash
        return True
